"""疑似生活シミュレーション本体.

- リアル時刻でパラメータを進める (5 分刻みで追いつき計算)
- スケジュール / 行動による一時シーン (override) から現在の場面を決める
- 行動 → 反応選択 → 効果適用 → プロンプト合成 → ComfyUI ジョブ
"""
import os
import queue
import random
import threading
import time
import uuid
from datetime import datetime

from . import comfy, cond, llm, store

STEP_SEC = 300
MAX_CATCHUP_SEC = 14 * 24 * 3600
DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_JA = "月火水木金土日"
LOG_KEEP_IN_VIEW = 60


def hm(s):
    s = str(s).strip()
    if ":" in s:
        h, m = s.split(":", 1)
        return int(h) * 60 + int(m)
    return int(float(s) * 60)


def in_range(mins, frm, to):
    a, b = hm(frm), hm(to)
    if a == b:
        return True
    if a < b:
        return a <= mins < b
    return mins >= a or mins < b


def day_match(spec, dt):
    spec = (spec or "all").strip().lower()
    wd = dt.weekday()
    if spec in ("all", "", "*"):
        return True
    if spec == "weekday":
        return wd < 5
    if spec == "weekend":
        return wd >= 5
    return DAY_KEYS[wd] in [x.strip() for x in spec.split(",")]


def split_tags(s):
    """カンマ区切り (括弧内は分割しない) でタグに分ける."""
    out, buf, depth = [], "", 0
    for ch in (s or "").replace("\n", ","):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append(buf)
            buf = ""
        else:
            buf += ch
    out.append(buf)
    return [t.strip() for t in out if t.strip()]


def join_tags(chunks):
    seen, out = set(), []
    for c in chunks:
        for t in split_tags(c):
            k = t.lower()
            if k not in seen:
                seen.add(k)
                out.append(t)
    return ", ".join(out)


class App:
    def __init__(self):
        store.bootstrap()
        self.lock = threading.RLock()
        self.states, self.logs, self.jobs = {}, {}, {}
        self.jobq = queue.Queue()
        self.reload()
        threading.Thread(target=self._worker, daemon=True).start()

    # ------------------------------------------------------------------ config
    def reload(self):
        self.settings = store.load_settings()
        self.params = store.load(store.dpath("params.json"), [])
        self.actions = store.load(store.dpath("actions.json"), [])
        self.world = store.load(store.dpath("world.json"), {})
        self.chars = store.load_characters()
        if self.settings.get("active_character") not in self.chars and self.chars:
            self.settings["active_character"] = next(iter(self.chars))

    def char(self, cid=None):
        cid = cid or self.settings.get("active_character")
        c = self.chars.get(cid)
        if not c:
            raise KeyError("キャラクターが見つかりません: %s" % cid)
        return c

    def action(self, aid):
        for a in self.actions:
            if a.get("id") == aid:
                return a
        raise KeyError("行動が見つかりません: %s" % aid)

    def param_def(self, pid):
        for p in self.params:
            if p["id"] == pid:
                return p
        return None

    # ------------------------------------------------------------------ state / log
    def state(self, cid):
        st = self.states.get(cid)
        if st is None:
            st = store.load(store.dpath("state", cid + ".json"))
            if st is None:
                t = time.time()
                st = {"params": {}, "last_tick": t, "last_interaction": t, "override": None,
                      "cooldowns": {}, "created": t}
            self.states[cid] = st
        for p in self.params:
            st["params"].setdefault(p["id"], float(p.get("init", 50)))
        return st

    def save_state(self, cid):
        store.save(store.dpath("state", cid + ".json"), self.states[cid])

    def log(self, cid):
        if cid not in self.logs:
            self.logs[cid] = store.load(store.dpath("log", cid + ".json"), [])
        return self.logs[cid]

    def save_log(self, cid):
        store.save(store.dpath("log", cid + ".json"), self.logs[cid])

    def find_entry(self, cid, eid):
        for e in reversed(self.log(cid)):
            if e["id"] == eid:
                return e
        return None

    # ------------------------------------------------------------------ scene / context
    def _norm_scene(self, e, char, src):
        return {"activity": e.get("activity") or "relax", "label": e.get("label") or "",
                "location": e.get("location") or "", "outfit": e.get("outfit") or "",
                "pos": e.get("pos", ""), "neg": e.get("neg", ""), "effects": e.get("effects") or {},
                "away": bool(e.get("away")), "asleep": bool(e.get("asleep")), "busy": bool(e.get("busy")),
                "source": src}

    def scheduled_scene(self, char, dt):
        mins = dt.hour * 60 + dt.minute
        for e in char.get("schedule") or []:
            if day_match(e.get("days"), dt) and in_range(mins, e.get("from", "00:00"), e.get("to", "24:00")):
                s = self._norm_scene(e, char, "schedule")
                break
        else:
            s = self._norm_scene(char.get("default_activity") or {}, char, "default")
        s["outfit"] = s["outfit"] or char.get("outfit_default", "")
        return s

    def scene_at(self, char, st, dt):
        base = self.scheduled_scene(char, dt)
        ov = st.get("override")
        if ov and ov.get("until", 0) > dt.timestamp():
            s = self._norm_scene(ov, char, "override")
            s["outfit"] = s["outfit"] or base["outfit"]
            s["until"] = ov["until"]
            return s
        return base

    def phase_at(self, dt):
        mins = dt.hour * 60 + dt.minute
        for p in self.world.get("phases") or []:
            if in_range(mins, p.get("from", "00:00"), p.get("to", "24:00")):
                return p
        return {"id": "day", "label": "", "pos": "", "neg": ""}

    def context(self, char, st, dt, scene=None):
        scene = scene or self.scene_at(char, st, dt)
        ctx = {k: round(v, 3) for k, v in st["params"].items()}
        ctx.update({
            "activity": scene["activity"], "location": scene["location"],
            "away": scene["away"], "asleep": scene["asleep"], "busy": scene["busy"],
            "free": not (scene["away"] or scene["asleep"] or scene["busy"]),
            "phase": self.phase_at(dt).get("id", ""), "hour": dt.hour, "time": dt.hour * 60 + dt.minute,
            "weekday": dt.weekday(), "day": DAY_KEYS[dt.weekday()], "weekend": dt.weekday() >= 5,
            "absent": round((dt.timestamp() - st.get("last_interaction", dt.timestamp())) / 3600.0, 2),
            "repeat": 0,
        })
        return ctx

    # ------------------------------------------------------------------ time
    def _clamp(self, p, v):
        return max(float(p.get("min", 0)), min(float(p.get("max", 100)), v))

    def _step(self, char, st, dt, h):
        scene = self.scene_at(char, st, dt)
        ctx = self.context(char, st, dt, scene)
        vals = st["params"]
        for p in self.params:
            pid = p["id"]
            v = vals.get(pid, float(p.get("init", 50)))
            rate = float(p.get("rate", 0))
            for r in p.get("rate_rules") or []:
                if cond.check(r.get("when", ""), ctx):
                    rate = float(r.get("rate", 0))
                    break
            d = rate * h + float(scene["effects"].get(pid, 0)) * h
            dr = p.get("drift")
            if dr:
                target = float(dr.get("target", v)) + sum(
                    float(m.get("add", 0)) for m in dr.get("mods") or [] if cond.check(m.get("when", ""), ctx))
                d += (target - v) * min(1.0, float(dr.get("rate", 0)) * h)
            vals[pid] = self._clamp(p, v + d)

    def tick(self, cid, now=None):
        char, st = self.char(cid), self.state(cid)
        now = now or time.time()
        t = st.get("last_tick") or now
        if now - t > MAX_CATCHUP_SEC:
            t = now - MAX_CATCHUP_SEC
        changed = False
        while t + STEP_SEC <= now:
            self._step(char, st, datetime.fromtimestamp(t + STEP_SEC / 2), STEP_SEC / 3600.0)
            t += STEP_SEC
            changed = True
        st["last_tick"] = t
        ov = st.get("override")
        if ov and ov.get("until", 0) <= now:
            st["override"] = None
            changed = True
        if changed:
            self.save_state(cid)

    # ------------------------------------------------------------------ prompt
    def active_tags(self, ctx):
        out = []
        for p in self.params:
            for tg in p.get("tags") or []:
                if cond.check(tg.get("when", ""), ctx):
                    out.append({"param": p["id"], "label": tg.get("label") or p.get("name", p["id"]),
                                "pos": tg.get("pos", ""), "neg": tg.get("neg", "")})
        return out

    def build_prompt(self, char, st, dt, act=None, reaction=None):
        scene = self.scene_at(char, st, dt)
        ctx = self.context(char, st, dt, scene)
        phase = self.phase_at(dt)
        pr = self.settings.get("prompt") or {}
        parts = [{"src": "共通", "pos": pr.get("prefix_pos", ""), "neg": pr.get("prefix_neg", "")},
                 {"src": "主人公", "pos": char.get("pos", ""), "neg": char.get("neg", "")},
                 {"src": "服装", "pos": scene["outfit"], "neg": ""}]
        if not (act and act.get("replace_scene")):
            parts.append({"src": "場面: " + scene["label"], "pos": scene["pos"], "neg": scene["neg"]})
        parts.append({"src": "時間帯: " + phase.get("label", ""), "pos": phase.get("pos", ""), "neg": phase.get("neg", "")})
        for tg in self.active_tags(ctx):
            parts.append({"src": "状態: " + tg["label"], "pos": tg["pos"], "neg": tg["neg"]})
        if act:
            parts.append({"src": "行動: " + act.get("name", ""), "pos": act.get("pos", ""), "neg": act.get("neg", "")})
        if reaction and (reaction.get("pos") or reaction.get("neg")):
            parts.append({"src": "反応", "pos": reaction.get("pos", ""), "neg": reaction.get("neg", "")})
        parts = [p for p in parts if p["pos"] or p["neg"]]
        return join_tags(p["pos"] for p in parts), join_tags(p["neg"] for p in parts), parts

    # ------------------------------------------------------------------ text
    def format_text(self, text, char, scene, dt):
        player = self.settings.get("player_name") or "あなた"
        call = (char.get("player_call") or "{player}").replace("{player}", player)
        for k, v in (("{call}", call), ("{player}", player), ("{name}", char.get("name", "")),
                     ("{location}", scene["location"]), ("{activity_label}", scene["label"]),
                     ("{time}", dt.strftime("%H:%M"))):
            text = text.replace(k, v)
        return text

    def _llm_text(self, char, st, dt, act, template, scene):
        cfg = self.settings.get("llm") or {}
        player = self.settings.get("player_name") or "あなた"
        call = (char.get("player_call") or "{player}").replace("{player}", player)
        ctx = self.context(char, st, dt, scene)
        lines = []
        for p in self.params:
            lines.append("%s %d/%d" % (p.get("name", p["id"]), round(st["params"][p["id"]]), p.get("max", 100)))
        tags = "、".join(t["label"] for t in self.active_tags(ctx)) or "特になし"
        recent = "\n".join("- %s → %s" % (e.get("action_name", ""), e.get("text", ""))
                           for e in self.log(char["id"])[-4:])
        system = (cfg.get("system") or "").replace("{name}", char.get("name", "")).replace("{call}", call) \
            .replace("{player}", player).replace("{persona}", char.get("persona", ""))
        user = ("現在 %s（%s曜 %s）\n%sの状況: %s（%s）\nパラメータ: %s\n目立つ状態: %s\n直近のやりとり:\n%s\n\n"
                "%sの行動: %s\n参考セリフ（この方向性で）: %s\n\n%sとしてのセリフだけを返して。"
                % (dt.strftime("%H:%M"), DAY_JA[dt.weekday()], self.phase_at(dt).get("label", ""),
                   char.get("name", ""), scene["label"], scene["location"], "、".join(lines), tags,
                   recent or "（なし）", player, act.get("name", ""), template, char.get("name", "")))
        return llm.chat(cfg, system, user)

    # ------------------------------------------------------------------ actions
    def pick_reaction(self, act, ctx):
        cands = [r for r in act.get("reactions") or [] if cond.check(r.get("when", ""), ctx)]
        if not cands:
            return {"text": ""}
        top = max(int(r.get("priority", 0)) for r in cands)
        cands = [r for r in cands if int(r.get("priority", 0)) == top]
        return random.choices(cands, [1 + cond.count(r.get("when", "")) for r in cands])[0]

    def apply_effects(self, st, effects):
        deltas = {}
        for pid, dv in effects.items():
            p = self.param_def(pid)
            if not p:
                continue
            old = st["params"][pid]
            st["params"][pid] = self._clamp(p, old + float(dv))
            d = round(st["params"][pid] - old, 1)
            if d:
                deltas[pid] = d
        return deltas

    def available(self, char, st, dt):
        ctx = self.context(char, st, dt)
        now = dt.timestamp()
        out = {}
        for a in self.actions:
            if a.get("category") == "system":
                continue
            cd = float(a.get("cooldown", 0)) * 60
            last = max(st["cooldowns"].get(a["id"], [0]) or [0])
            out[a["id"]] = {"ok": cond.check(a.get("when", ""), ctx),
                            "cooldown": max(0, int(last + cd - now)) if cd else 0}
        return out

    def act(self, aid, cid=None):
        with self.lock:
            char = self.char(cid)
            cid = char["id"]
            self.tick(cid)
            st, a = self.state(cid), self.action(aid)
            now = time.time()
            dt = datetime.fromtimestamp(now)
            scene = self.scene_at(char, st, dt)
            ctx = self.context(char, st, dt, scene)
            if not cond.check(a.get("when", ""), ctx):
                raise ValueError("今は「%s」できません（%s）" % (a.get("name", aid), a.get("when", "")))
            cd = float(a.get("cooldown", 0)) * 60
            hist = [x for x in st["cooldowns"].get(aid, []) if now - x < cd] if cd else []
            ctx["repeat"] = len(hist)
            r = self.pick_reaction(a, ctx)
            scale = float(a.get("repeat_scale", 0.5)) ** len(hist)
            eff = {}
            if not r.get("override"):
                for k, v in (a.get("effects") or {}).items():
                    eff[k] = eff.get(k, 0) + float(v) * scale
            for k, v in (r.get("effects") or {}).items():
                eff[k] = eff.get(k, 0) + float(v)
            deltas = self.apply_effects(st, eff)
            if a.get("override") and not r.get("override"):
                ov = dict(a["override"])
                ov["until"] = now + float(ov.get("minutes", 30)) * 60
                ov["from_action"] = aid
                st["override"] = ov
            if cd:
                st["cooldowns"][aid] = hist + [now]
            st["last_interaction"] = now
            scene2 = self.scene_at(char, st, dt)
            text = self.format_text(r.get("text", ""), char, scene, dt)
            pos, neg, parts = self.build_prompt(char, st, dt, a, r)
            self.save_state(cid)

        text_src, llm_error = "template", None
        cfg = self.settings.get("llm") or {}
        if cfg.get("enabled") and text and not text.startswith("（") and not a.get("no_llm"):
            try:
                t2 = self._llm_text(char, st, dt, a, text, scene2)
                if t2:
                    text, text_src = t2, "llm"
            except Exception as e:  # noqa: BLE001 - LLM 失敗時は定型文で続行
                llm_error = str(e)

        with self.lock:
            entry = self._new_entry(cid, now, a, text, deltas, scene2, dt, pos, neg, parts)
            entry["text_src"] = text_src
            job = None
            if self.settings.get("auto_generate") and a.get("generate", True):
                job = self.enqueue(cid, entry["id"], pos, neg)
                entry["job"] = job
            self.save_log(cid)
        return {"entry": entry, "job": job, "llm_error": llm_error}

    def _new_entry(self, cid, now, a, text, deltas, scene, dt, pos, neg, parts):
        e = {"id": uuid.uuid4().hex[:12], "t": now, "action": a.get("id"), "action_name": a.get("name", ""),
             "icon": a.get("icon", ""), "text": text, "deltas": deltas, "scene": scene["label"],
             "location": scene["location"], "phase": self.phase_at(dt).get("label", ""),
             "pos": pos, "neg": neg, "parts": parts, "images": [], "image": None, "seed": None}
        self.log(cid).append(e)
        return e

    def visit(self, cid=None):
        """一定時間空けて開いたときの「おかえり」イベント."""
        char = self.char(cid)
        with self.lock:
            self.tick(char["id"])
            st = self.state(char["id"])
            absent = (time.time() - st.get("last_interaction", time.time())) / 3600.0
        if absent < float(self.world.get("absent_greet_hours", 3)):
            return None
        try:
            self.action("_return")
        except KeyError:
            return None
        return self.act("_return", char["id"])

    # ------------------------------------------------------------------ generation
    def snapshot(self, cid=None, pos=None, neg=None, seed=None, entry_id=None):
        """手動生成. entry_id 指定ならその記録で再生成, 無ければ現在の様子を新規記録."""
        with self.lock:
            char = self.char(cid)
            cid = char["id"]
            if entry_id:
                e = self.find_entry(cid, entry_id)
                if not e:
                    raise KeyError("記録が見つかりません")
            else:
                self.tick(cid)
                st = self.state(cid)
                now = time.time()
                dt = datetime.fromtimestamp(now)
                p2, n2, parts = self.build_prompt(char, st, dt)
                e = self._new_entry(cid, now, {"id": "_snapshot", "name": "スナップ", "icon": "📷"}, "",
                                    {}, self.scene_at(char, st, dt), dt, p2, n2, parts)
            if pos is not None:
                e["pos"] = pos
            if neg is not None:
                e["neg"] = neg
            job = self.enqueue(cid, e["id"], e["pos"], e["neg"], seed)
            e["job"] = job
            self.save_log(cid)
            return {"entry": e, "job": job}

    def enqueue(self, cid, eid, pos, neg, seed=None):
        jid = uuid.uuid4().hex
        if seed in (None, "", -1):
            seed = random.randint(0, 2 ** 32 - 1)
        self.jobs[jid] = {"id": jid, "status": "queued", "cid": cid, "entry": eid, "pos": pos, "neg": neg,
                          "seed": int(seed), "created": time.time(), "error": None, "image": None}
        self.jobq.put(jid)
        return jid

    def job_view(self, jid):
        j = self.jobs.get(jid)
        if not j:
            return {"id": jid, "status": "unknown"}
        ahead = sum(1 for x in self.jobs.values() if x["status"] == "queued" and x["created"] < j["created"])
        out = {k: j[k] for k in ("id", "status", "entry", "seed", "error", "image", "created")}
        out["ahead"] = ahead
        out["elapsed"] = round(time.time() - j.get("started", j["created"]), 1)
        return out

    def _worker(self):
        while True:
            jid = self.jobq.get()
            j = self.jobs[jid]
            j["status"], j["started"] = "running", time.time()
            try:
                c = dict(self.settings.get("comfy") or {})
                custom = None
                if c.get("workflow_mode") == "custom":
                    custom = store.load(store.dpath("workflow.json"))
                    if not custom:
                        raise RuntimeError("カスタムワークフローが未登録です")
                data, ext = comfy.generate(c, j["pos"], j["neg"], j["seed"], custom)
                rel = "%s/%s_%s.%s" % (j["cid"], datetime.now().strftime("%Y%m%d_%H%M%S"), jid[:6], ext)
                full = store.dpath("images", *rel.split("/"))
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "wb") as f:
                    f.write(data)
                with self.lock:
                    e = self.find_entry(j["cid"], j["entry"])
                    if e:
                        e["image"], e["seed"] = rel, j["seed"]
                        e.setdefault("images", []).append({"path": rel, "seed": j["seed"], "pos": j["pos"],
                                                           "neg": j["neg"], "t": time.time()})
                        e.pop("job", None)
                        self.save_log(j["cid"])
                j["image"], j["status"] = rel, "done"
            except Exception as ex:  # noqa: BLE001
                j["error"], j["status"] = str(ex), "error"
                with self.lock:
                    e = self.find_entry(j["cid"], j["entry"])
                    if e and e.get("job") == jid:
                        e.pop("job", None)
                        e["error"] = str(ex)
                        self.save_log(j["cid"])

    # ------------------------------------------------------------------ views
    def state_view(self, cid=None):
        with self.lock:
            char = self.char(cid)
            cid = char["id"]
            self.tick(cid)
            st = self.state(cid)
            now = time.time()
            dt = datetime.fromtimestamp(now)
            scene = self.scene_at(char, st, dt)
            ctx = self.context(char, st, dt, scene)
            phase = self.phase_at(dt)
            log = self.log(cid)
            pending = [self.job_view(j["id"]) for j in self.jobs.values()
                       if j["cid"] == cid and j["status"] in ("queued", "running")]
            return {
                "now": now, "character": cid, "name": char.get("name", ""),
                "params": {k: round(v, 1) for k, v in st["params"].items()},
                "scene": {k: scene[k] for k in ("activity", "label", "location", "away", "asleep", "busy", "source")},
                "override_until": scene.get("until"),
                "phase": {"id": phase.get("id"), "label": phase.get("label", "")},
                "tags": [{"param": t["param"], "label": t["label"]} for t in self.active_tags(ctx)],
                "available": self.available(char, st, dt),
                "absent": ctx["absent"], "log": log[-LOG_KEEP_IN_VIEW:], "log_total": len(log),
                "jobs": pending,
            }

    def prompt_preview(self, cid=None):
        with self.lock:
            char = self.char(cid)
            self.tick(char["id"])
            pos, neg, parts = self.build_prompt(char, self.state(char["id"]), datetime.now())
            return {"pos": pos, "neg": neg, "parts": parts}

    def boot_view(self):
        return {"settings": self.settings, "params": self.params, "actions": self.actions, "world": self.world,
                "characters": [{"id": c["id"], "name": c.get("name", "")} for c in self.chars.values()],
                "character": self.char(), "placeholders": list(comfy.PLACEHOLDERS),
                "has_workflow": os.path.exists(store.dpath("workflow.json"))}

    # ------------------------------------------------------------------ editing
    def save_settings(self, obj):
        with self.lock:
            obj = dict(obj)
            if "active_character" in obj and obj["active_character"] not in self.chars:
                obj.pop("active_character")
            self.settings = store.deep_merge(self.settings, obj)
            store.save(store.dpath("settings.json"), self.settings)
            return self.settings

    def select_character(self, cid):
        self.char(cid)
        return self.save_settings({"active_character": cid})

    def save_character(self, c):
        with self.lock:
            if not c.get("id"):
                raise ValueError("id がありません")
            old = self.chars.get(c["id"])
            hist = list((old or {}).get("prompt_history") or [])
            if old and not hist:
                hist.insert(0, {"t": time.time() - 1, "pos": old.get("pos", ""), "neg": old.get("neg", "")})
            if not old or not hist or hist[0].get("pos") != c.get("pos") or hist[0].get("neg") != c.get("neg"):
                hist.insert(0, {"t": time.time(), "pos": c.get("pos", ""), "neg": c.get("neg", "")})
            c["prompt_history"] = hist[:200]
            self.chars[c["id"]] = c
            store.save_character(c)
            return c

    def new_character(self, name, copy_from=None):
        with self.lock:
            src = self.char(copy_from) if copy_from else self.char()
            cid = "c" + uuid.uuid4().hex[:8]
            c = {"id": cid, "name": name or "新しいキャラ", "player_call": "{player}", "persona": "",
                 "pos": "1girl, solo", "neg": "", "outfit_default": src.get("outfit_default", ""),
                 "schedule": src.get("schedule", []), "default_activity": src.get("default_activity", {}),
                 "prompt_history": []}
            self.save_character(c)
            self.select_character(cid)
            return c

    def delete_character(self, cid):
        with self.lock:
            if len(self.chars) <= 1:
                raise ValueError("最後のキャラクターは削除できません")
            self.chars.pop(cid, None)
            store.delete_character(cid)
            if self.settings.get("active_character") == cid:
                self.select_character(next(iter(self.chars)))

    def _check_conds(self, items, label):
        for it in items:
            try:
                cond.parse(it.get("when", ""))
            except ValueError as e:
                raise ValueError("%s: %s" % (label, e))

    def save_actions(self, actions):
        with self.lock:
            ids = [a.get("id") for a in actions]
            if any(not i for i in ids) or len(set(ids)) != len(ids):
                raise ValueError("行動 id が空か重複しています")
            for a in actions:
                self._check_conds([a] + list(a.get("reactions") or []), "行動「%s」" % a.get("name", a["id"]))
            self.actions = actions
            store.save(store.dpath("actions.json"), actions)
            return actions

    def save_params(self, params):
        with self.lock:
            ids = [p.get("id") for p in params]
            if any(not i for i in ids) or len(set(ids)) != len(ids):
                raise ValueError("パラメータ id が空か重複しています")
            for p in params:
                lab = "パラメータ「%s」" % p.get("name", p["id"])
                self._check_conds(p.get("rate_rules") or [], lab)
                self._check_conds(p.get("tags") or [], lab)
                self._check_conds((p.get("drift") or {}).get("mods") or [], lab)
            self.params = params
            store.save(store.dpath("params.json"), params)
            for cid in list(self.states):
                self.state(cid)
                self.save_state(cid)
            return params

    def save_world(self, world):
        with self.lock:
            self.world = world
            store.save(store.dpath("world.json"), world)
            return world

    def save_workflow(self, wf):
        found = comfy.validate_workflow(wf)
        store.save(store.dpath("workflow.json"), wf)
        return found

    def set_params(self, values, cid=None):
        with self.lock:
            char = self.char(cid)
            st = self.state(char["id"])
            for k, v in values.items():
                p = self.param_def(k)
                if p:
                    st["params"][k] = self._clamp(p, float(v))
            self.save_state(char["id"])

    def reset_state(self, cid=None):
        with self.lock:
            char = self.char(cid)
            self.states.pop(char["id"], None)
            p = store.dpath("state", char["id"] + ".json")
            if os.path.exists(p):
                os.remove(p)
            self.state(char["id"])
            self.save_state(char["id"])

    def clear_override(self, cid=None):
        with self.lock:
            char = self.char(cid)
            self.state(char["id"])["override"] = None
            self.save_state(char["id"])

    def log_page(self, cid=None, offset=0, limit=60, images_only=False):
        char = self.char(cid)
        items = self.log(char["id"])
        if images_only:
            items = [e for e in items if e.get("images")]
        items = list(reversed(items))
        return {"total": len(items), "items": items[offset:offset + limit]}
