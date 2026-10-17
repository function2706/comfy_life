"""疑似生活シミュレーション本体.

- リアル時刻でパラメータを進める (5 分刻みで追いつき計算)
- スケジュール / 行動による一時シーン (override) から現在の場面を決める
- 行動 → 反応選択 → 効果適用 → プロンプト合成 → ComfyUI ジョブ
"""
import glob
import hashlib
import os
import queue
import random
import re
import threading
import time
import uuid
from datetime import datetime

from . import comfy, cond, games, llm, store
from . import keys as keys_mod
from .keys import line_keys

STEP_SEC = 300
MAX_CATCHUP_SEC = 14 * 24 * 3600
DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_JA = "月火水木金土日"
LOG_KEEP_IN_VIEW = 60
PERSONA_ORDER = ["teinei", "osananajimi", "aneki", "ottori", "ojousama", "kedakai", "tsundere", "cool", "mukuchi", "jimuteki", "otokomae",
                 "genki", "tenshin", "uchiki", "boyish", "amaenbo"]


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
        self.logq = queue.Queue()
        threading.Thread(target=self._log_writer, daemon=True, name="log-writer").start()
        self.reload()
        self.games = games.Games(self)
        self._load_index()
        self._ensure_worker()

    # ------------------------------------------------------------------ config
    def reload(self):
        self.settings = store.load_settings()
        self.params = store.load(store.dpath("params.json"), [])
        self.actions = store.load(store.dpath("actions.json"), [])
        self.world = store.load(store.dpath("world.json"), {})
        self.chars = store.load_characters()
        self.minigames = store.load(store.dpath("minigames.json"), [])
        self.personas = store.load_personas()
        if self.settings.get("active_character") not in self.chars and self.chars:
            self.settings["active_character"] = next(iter(self.chars))
        self._migrate()

    def _migrate(self):
        """既存の data/ に, 後から増えた既定項目を補う (ユーザーの編集内容は上書きしない)."""
        have = {a.get("id") for a in self.actions}
        added = [a for a in store.load(os.path.join(store.DEFAULTS, "actions.json"), [])
                 if a["id"].startswith("_") and a["id"] not in have]
        if added:
            self.actions += added
            store.save(store.dpath("actions.json"), self.actions)
        # ミニゲーム: 新しく増えた既定ゲームを追加 (ユーザーが消したものは seen に残るので戻さない)
        defaults = store.load(os.path.join(store.DEFAULTS, "minigames.json"), [])
        have = {g.get("id") for g in self.minigames}
        seen = set(self.settings.get("seen_minigames") or []) or set(have)
        new = [g for g in defaults if g["id"] not in have and g["id"] not in seen]
        all_ids = seen | {g["id"] for g in defaults}
        if new or all_ids != set(self.settings.get("seen_minigames") or []):
            if new:
                self.minigames += new
                store.save(store.dpath("minigames.json"), self.minigames)
            self.settings["seen_minigames"] = sorted(all_ids)
            store.save(store.dpath("settings.json"), self.settings)
        for c in self.chars.values():
            # 以前は性格を選ぶと呼び方をキャラにコピーしていた. プリセットと同じなら「プリセットに従う」(空欄) に戻す
            p = self.personas.get(c.get("persona_id") or "")
            if p and c.get("player_call") and c["player_call"] == p.get("player_call"):
                c["player_call"] = ""
                store.save_character(c)
            if "wardrobe" not in c:
                d = store.load(os.path.join(store.DEFAULTS, "characters", c["id"] + ".json")) or {}
                c["wardrobe"] = d.get("wardrobe", [])
                store.save_character(c)

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
        asleep = bool(e.get("asleep"))
        return {"activity": e.get("activity") or "relax", "label": e.get("label") or "",
                "location": e.get("location") or "", "outfit": e.get("outfit") or "", "outfit_neg": "",
                "pos": e.get("pos", ""), "neg": e.get("neg", ""), "effects": e.get("effects") or {},
                "away": bool(e.get("away")), "asleep": asleep, "busy": bool(e.get("busy")),
                # 服装固定 (着せ替えより優先). 未指定なら睡眠中の場面だけ固定
                "fixed_outfit": bool(e.get("fixed_outfit", asleep)),
                "dress": None, "source": src}

    def wardrobe_item(self, char, oid):
        for o in char.get("wardrobe") or []:
            if o.get("id") == oid:
                return o
        return None

    def _apply_dress(self, char, st, s):
        """着せ替え中なら, 服装固定でない場面の服装を差し替える (ミニゲームの服装が最優先)."""
        go = (st.get("game") or {}).get("outfit")
        if go:
            s["outfit"], s["outfit_neg"], s["dress"] = go.get("pos", ""), go.get("neg", ""), go.get("label") or None
            s["remove_tags"] = go.get("remove") or []
            return s
        o = self.wardrobe_item(char, (st.get("dress") or {}).get("id"))
        if o and not s["fixed_outfit"]:
            s["outfit"], s["outfit_neg"], s["dress"] = o.get("pos", ""), o.get("neg", ""), o.get("name", o["id"])
        return s

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
            return self._apply_dress(char, st, s)
        return self._apply_dress(char, st, base)

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
            "repeat": 0, "outfit": (st.get("dress") or {}).get("id", ""),
        })
        return ctx

    # ------------------------------------------------------------------ time
    def _clamp(self, p, v):
        return max(float(p.get("min", 0)), min(float(p.get("max", 100)), v))

    def _step(self, char, st, dt, h):
        scene = self.scene_at(char, st, dt)
        if scene["asleep"] and st.get("dress") and char.get("dress_reset_on_sleep", True):
            st["dress"] = None   # 寝たら翌日はスケジュール通りの服に戻る
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
                 {"src": "服装" + (": " + scene["dress"] if scene["dress"] else ""),
                  "pos": scene["outfit"], "neg": scene["outfit_neg"]}]
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
        pos = join_tags(p["pos"] for p in parts)
        rm = {t.lower() for t in scene.get("remove_tags") or []}
        if rm:   # ミニゲームの段階で外したもの (例: hair ribbon) を外見プロンプトからも除く
            pos = ", ".join(t for t in split_tags(pos) if t.lower() not in rm)
            parts.append({"src": "除外", "pos": "", "neg": "（除外）" + ", ".join(sorted(rm))})
        return pos, join_tags(p["neg"] for p in parts if p["src"] != "除外"), parts

    # ------------------------------------------------------------------ text
    def pronouns(self, char):
        """(一人称, 言いよどみの一人称, 呼び方). 主人公で固定していればそれ, 無ければ性格プリセットに従う."""
        p = self.personas.get(char.get("persona_id") or "") or {}
        player = self.settings.get("player_name") or "あなた"
        fixed_fp = (char.get("first_person") or "").strip()
        fp = fixed_fp or p.get("first_person") or "私"
        fp_st = fixed_fp or p.get("first_person_stutter") or fp
        call = (char.get("player_call") or "").strip() or p.get("player_call") or "{player}"
        return fp, fp_st, call.replace("{player}", player)

    def format_text(self, text, char, scene, dt):
        player = self.settings.get("player_name") or "あなた"
        fp, fp_st, call = self.pronouns(char)
        for k, v in (("{fp_st}", fp_st), ("{fp}", fp), ("{call}", call), ("{player}", player), ("{name}", char.get("name", "")),
                     ("{location}", scene["location"]), ("{activity_label}", scene["label"]),
                     ("{time}", dt.strftime("%H:%M"))):
            text = text.replace(k, v)
        return text

    def _llm_text(self, char, st, dt, act, template, scene):
        cfg = self.settings.get("llm") or {}
        player = self.settings.get("player_name") or "あなた"
        fp, _, call = self.pronouns(char)
        ctx = self.context(char, st, dt, scene)
        lines = []
        for p in self.params:
            lines.append("%s %d/%d" % (p.get("name", p["id"]), round(st["params"][p["id"]]), p.get("max", 100)))
        tags = "、".join(t["label"] for t in self.active_tags(ctx)) or "特になし"
        recent = "\n".join("- %s → %s" % (e.get("action_name", ""), e.get("text", ""))
                           for e in self.log(char["id"])[-4:])
        system = (cfg.get("system") or "").replace("{name}", char.get("name", "")).replace("{call}", call) \
            .replace("{player}", player).replace("{persona}", char.get("persona", "")).replace("{fp}", fp)
        system += "\n一人称は必ず「%s」、%sのことは必ず「%s」と呼ぶ。" % (fp, player, call)
        user = ("現在 %s（%s曜 %s）\n%sの状況: %s（%s）\nパラメータ: %s\n目立つ状態: %s\n直近のやりとり:\n%s\n\n"
                "%sの行動: %s\n参考セリフ（この方向性で）: %s\n\n%sとしてのセリフだけを返して。"
                % (dt.strftime("%H:%M"), DAY_JA[dt.weekday()], self.phase_at(dt).get("label", ""),
                   char.get("name", ""), scene["label"], scene["location"], "、".join(lines), tags,
                   recent or "（なし）", player, act.get("name", ""), template, char.get("name", "")))
        return llm.chat(cfg, system, user)

    # ------------------------------------------------------------------ actions
    def persona_text(self, char, key):
        """主人公の性格プリセットにそのキーのセリフがあれば 1 つ選んで返す."""
        if not key:
            return None
        p = self.personas.get(char.get("persona_id") or "")
        texts = (p or {}).get("lines", {}).get(key)
        if isinstance(texts, str):
            return texts
        return random.choice(texts) if texts else None

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

    def act(self, aid, cid=None, dress=None):
        """行動を実行する. aid="_dress" のときは dress に着替え先の id ("" でおまかせ) を渡す."""
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
            outfit = None
            if dress is not None:
                if dress:
                    outfit = self.wardrobe_item(char, dress)
                    if not outfit:
                        raise KeyError("服が見つかりません: %s" % dress)
                    if not cond.check(outfit.get("when", ""), ctx):
                        raise ValueError("今は「%s」に着替えられません（%s）" % (outfit.get("name", dress), outfit.get("when", "")))
                ctx["outfit"] = dress   # 反応の条件では「着替え先」を outfit として参照できる
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
            if dress is not None and not r.get("override"):
                st["dress"] = {"id": dress, "t": now} if dress else None
            if cd:
                st["cooldowns"][aid] = hist + [now]
            st["last_interaction"] = now
            scene2 = self.scene_at(char, st, dt)
            rs = a.get("reactions") or []
            pkey = "%s.%s" % (aid, line_keys(rs)[rs.index(r)]) if r in rs else None
            text = self.format_text(self.persona_text(char, pkey) or r.get("text", ""), char, scene, dt)
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
                job = self._present_image(cid, entry)
            self.save_log(cid)
        return {"entry": entry, "job": job, "llm_error": llm_error}

    # ------------------------------------------------------------------ image reuse
    @staticmethod
    def prompt_key(pos, neg):
        """同一プロンプト判定のキー (generatw と同じく pos+neg の MD5)."""
        return hashlib.md5((pos + neg).encode("utf-8")).hexdigest()

    def _load_index(self):
        """プロンプト → 生成済み画像の索引. 無ければ全キャラのログから作り直す."""
        idx = store.load(store.dpath("images", "index.json"))
        if idx is None:
            idx = {}
            for f in glob.glob(store.dpath("log", "*.json")):
                for e in store.load(f, []):
                    for im in e.get("images") or []:
                        idx.setdefault(self.prompt_key(im.get("pos", ""), im.get("neg", "")), []).append(
                            {"path": im["path"], "seed": im.get("seed"), "t": im.get("t")})
            store.save(store.dpath("images", "index.json"), idx)
        self.img_index = idx

    def existing_images(self, pos, neg):
        """同じプロンプトで生成済みの画像 (ファイルが残っているもの)."""
        items = self.img_index.get(self.prompt_key(pos, neg)) or []
        return [im for im in items if os.path.exists(store.dpath("images", *im["path"].split("/")))]

    def _present_image(self, cid, entry):
        """設定に従い, 既存画像をすぐ表示するか / 新規生成するかを決める. 生成したらジョブ id を返す."""
        ic = self.settings.get("images") or {}
        mode = ic.get("mode", "reuse")
        # 生成中 (実行中 or 待ちあり) なら, 既存画像があればそれで済ませて待たせない
        busy = ic.get("busy_reuse", True) and self.generating()
        have = self.existing_images(entry["pos"], entry["neg"]) if (mode == "reuse" or busy) else []
        entry["same_prompt"] = len(have)
        if have:
            im = random.choice(have)
            entry["image"], entry["seed"], entry["reused"] = im["path"], im.get("seed"), True
            if busy:
                entry["busy_skip"] = True
                return None   # 生成中なので新規生成はしない
        limit = int(ic.get("max_per_prompt", 8))
        if mode == "reuse" and have and len(have) >= limit:
            return None   # 上限に達しているので生成しない
        job = self.enqueue(cid, entry["id"], entry["pos"], entry["neg"])
        entry["job"] = job
        return job

    def generating(self):
        """生成ジョブが実行中か待ち行列にあるか."""
        return any(j["status"] in ("queued", "running") for j in self.jobs.values())

    def reroll(self, entry_id, cid=None):
        """同じプロンプトの既存画像から別の 1 枚を選び直す."""
        with self.lock:
            char = self.char(cid)
            e = self.find_entry(char["id"], entry_id)
            if not e:
                raise KeyError("記録が見つかりません")
            have = self.existing_images(e["pos"], e["neg"])
            if not have:
                raise ValueError("このプロンプトの画像はまだありません")
            others = [im for im in have if im["path"] != e.get("image")] or have
            im = random.choice(others)
            e["image"], e["seed"], e["reused"] = im["path"], im.get("seed"), True
            e["same_prompt"] = len(have)
            self.save_log(char["id"])
            return {"entry": e}

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

    STAGE_LABEL = {"queued": "前のジョブ待ち", "prepare": "準備中", "submit": "ComfyUI へ送信中",
                   "comfy_queued": "ComfyUI のキュー待ち", "comfy_running": "ComfyUI で生成中",
                   "download": "画像を取得中", "done": "完了", "error": "失敗", "cancelled": "取り消し"}

    def jlog(self, j, msg, level="info"):
        """ジョブの経過を記録 (ジョブ内 / コンソール / data/server.log)."""
        now = time.time()
        j.setdefault("events", []).append({"t": now, "msg": msg, "level": level})
        del j["events"][:-40]
        line = "%s [%s] job %s (%s): %s" % (datetime.fromtimestamp(now).strftime("%m-%d %H:%M:%S"),
                                            level.upper(), j["id"][:6], j.get("action", ""), msg)
        self.logq.put(line)

    def _log_writer(self):
        # コンソールへの出力は別スレッドで行う (Windows のコンソールで範囲選択中は
        # 書き込みがブロックされるため, 生成ワーカーが道連れで止まらないように)
        while True:
            line = self.logq.get()
            try:
                with open(store.dpath("server.log"), "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass
            try:
                print(line, flush=True)
            except Exception:  # noqa: BLE001
                pass

    def _set_stage(self, j, stage, msg=None, level="info", **extra):
        j["stage"], j["stage_at"] = stage, time.time()
        if stage in ("done", "error", "cancelled"):
            j["finished"] = j["stage_at"]
        j.update({k: v for k, v in extra.items() if k != "quiet"})
        if msg and not extra.get("quiet"):
            self.jlog(j, msg, level)

    def enqueue(self, cid, eid, pos, neg, seed=None):
        jid = uuid.uuid4().hex
        if seed in (None, "", -1):
            seed = random.randint(0, 2 ** 32 - 1)
        e = self.find_entry(cid, eid) or {}
        j = {"id": jid, "status": "queued", "stage": "queued", "cid": cid, "entry": eid,
             "action": e.get("action_name", ""), "pos": pos, "neg": neg, "seed": int(seed),
             "created": time.time(), "error": None, "image": None, "prompt_id": None, "queue_pos": None,
             "cancel": False, "events": []}
        self.jobs[jid] = j
        self.jlog(j, "受付 (アプリ内の待ち %d 件)" % (self.jobq.qsize()))
        self._ensure_worker()
        self.jobq.put(jid)
        # 古い完了済みジョブを掃除
        done = [x for x in self.jobs.values() if x["status"] in ("done", "error", "cancelled")]
        for x in sorted(done, key=lambda x: x["created"])[:-100]:
            self.jobs.pop(x["id"], None)
        return jid

    def _ensure_worker(self):
        t = getattr(self, "_worker_thread", None)
        if t is None or not t.is_alive():
            if t is not None:
                self.logq.put("%s [ERROR] 生成ワーカーが停止していたため再起動" % datetime.now().strftime("%m-%d %H:%M:%S"))
            self.worker = {"current": None, "since": time.time(), "restarts": getattr(self, "worker", {}).get("restarts", -1) + 1}
            self._worker_thread = threading.Thread(target=self._worker, daemon=True, name="gen-worker")
            self._worker_thread.start()

    def job_view(self, jid, detail=False):
        j = self.jobs.get(jid)
        if not j:
            return {"id": jid, "status": "unknown", "error": "サーバにこのジョブがありません（サーバ再起動など）"}
        now = j.get("finished") or time.time()
        ahead = sum(1 for x in self.jobs.values() if x["status"] == "queued" and x["created"] < j["created"])
        keys = ("id", "status", "stage", "cid", "entry", "action", "seed", "error", "image", "created",
                "prompt_id", "queue_pos")
        out = {k: j.get(k) for k in keys}
        out["stage_label"] = self.STAGE_LABEL.get(j.get("stage"), j.get("stage"))
        out["ahead"] = ahead
        out["elapsed"] = round(now - j.get("started", j["created"]), 1)
        out["waited"] = round(now - j["created"], 1)
        out["stage_elapsed"] = round(now - j.get("stage_at", j["created"]), 1)
        ev = j.get("events") or []
        out["last_event"] = ev[-1]["msg"] if ev else ""
        if detail:
            out["events"] = ev
        return out

    def jobs_view(self):
        t = getattr(self, "_worker_thread", None)
        w = dict(getattr(self, "worker", {}))
        w["alive"] = bool(t and t.is_alive())
        cur = self.jobs.get(w.get("current") or "")
        w["current_action"] = cur.get("action") if cur else None
        w["busy_for"] = round(time.time() - w.get("since", time.time()), 1)
        jobs = sorted(self.jobs.values(), key=lambda x: x["created"], reverse=True)[:30]
        c = self.settings.get("comfy") or {}
        return {"worker": w, "comfy_url": comfy.base_url(c), "use_proxy": bool(c.get("use_proxy")),
                "queue_len": self.jobq.qsize(), "jobs": [self.job_view(x["id"], detail=True) for x in jobs]}

    def cancel_job(self, jid=None, all_pending=False):
        n = 0
        for j in list(self.jobs.values()):
            if (all_pending or j["id"] == jid) and j["status"] in ("queued", "running"):
                j["cancel"] = True
                if j["status"] == "queued":
                    j["status"] = "cancelled"
                    self._set_stage(j, "cancelled", "取り消し（実行前）")
                    self._clear_entry_job(j, None)
                else:
                    self.jlog(j, "取り消し要求")
                n += 1
        return {"cancelled": n}

    def _clear_entry_job(self, j, error):
        with self.lock:
            e = self.find_entry(j["cid"], j["entry"])
            if e and e.get("job") == j["id"]:
                e.pop("job", None)
                if error:
                    e["error"] = error
                self.save_log(j["cid"])

    def _worker(self):
        while True:
            jid = self.jobq.get()
            j = self.jobs.get(jid)
            if not j or j["status"] != "queued":
                continue
            self.worker.update(current=jid, since=time.time())
            j["status"], j["started"] = "running", time.time()
            self._set_stage(j, "prepare", "処理開始（待ち %.1f 秒）" % (j["started"] - j["created"]))
            try:
                c = dict(self.settings.get("comfy") or {})
                custom = None
                if c.get("workflow_mode") == "custom":
                    custom = store.load(store.dpath("workflow.json"))
                    if not custom:
                        raise RuntimeError("カスタムワークフローが未登録です")
                data, ext = comfy.generate(
                    c, j["pos"], j["neg"], j["seed"], custom,
                    report=lambda stage, msg, **kw: self._set_stage(j, stage, msg, **kw),
                    cancelled=lambda: j["cancel"])
                rel = "%s/%s_%s.%s" % (j["cid"], datetime.now().strftime("%Y%m%d_%H%M%S"), jid[:6], ext)
                full = store.dpath("images", *rel.split("/"))
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "wb") as f:
                    f.write(data)
                with self.lock:
                    e = self.find_entry(j["cid"], j["entry"])
                    self.img_index.setdefault(self.prompt_key(j["pos"], j["neg"]), []).append(
                        {"path": rel, "seed": j["seed"], "t": time.time()})
                    store.save(store.dpath("images", "index.json"), self.img_index)
                    if e:
                        e["image"], e["seed"], e["reused"] = rel, j["seed"], False
                        e.pop("error", None)
                        e.setdefault("images", []).append({"path": rel, "seed": j["seed"], "pos": j["pos"],
                                                           "neg": j["neg"], "t": time.time()})
                        e.pop("job", None)
                        self.save_log(j["cid"])
                j["image"], j["status"] = rel, "done"
                self._set_stage(j, "done", "完了 %s（%.1f 秒）" % (rel, time.time() - j["started"]))
            except comfy.Cancelled:
                j["status"] = "cancelled"
                self._set_stage(j, "cancelled", "取り消し（ComfyUI 側も中断を要求）")
                self._clear_entry_job(j, None)
            except Exception as ex:  # noqa: BLE001 - どんな失敗でもワーカーは止めない
                j["error"], j["status"] = str(ex), "error"
                self._set_stage(j, "error", "失敗: %s" % ex, level="error")
                self._clear_entry_job(j, str(ex))
            finally:
                self.worker.update(current=None, since=time.time())

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
                "dress": self._dress_view(char, st, scene, ctx),
                "games": self.games.view(char, st, ctx),
            }

    def _dress_view(self, char, st, scene, ctx):
        try:
            da = self.action("_dress")
            can, why = cond.check(da.get("when", ""), ctx), da.get("when", "")
        except KeyError:
            can, why = False, "着せ替え用のコマンド (_dress) がありません"
        return {"current": (st.get("dress") or {}).get("id", ""), "wearing": scene["dress"],
                "outfit": scene["outfit"], "fixed": scene["fixed_outfit"], "can": can, "why": why,
                "items": {o["id"]: cond.check(o.get("when", ""), ctx) for o in char.get("wardrobe") or []}}

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
                "has_workflow": os.path.exists(store.dpath("workflow.json")), "minigames": self.minigames,
                "personas": [{k: p.get(k) for k in ("id", "name", "desc", "persona", "player_call", "first_person", "_custom")}
                             for p in sorted(self.personas.values(), key=lambda p: (
                                 PERSONA_ORDER.index(p["id"]) if p["id"] in PERSONA_ORDER else 99, p.get("name", "")))]}

    # ------------------------------------------------------------------ personas
    def persona_full(self, pid):
        p = self.personas.get(pid)
        if not p:
            raise KeyError("性格プリセットが見つかりません: %s" % pid)
        return {"persona": p, "keys": keys_mod.all_keys(self.actions, self.minigames)}

    def save_persona(self, p):
        with self.lock:
            if not p.get("id") or not re.match(r"^[A-Za-z0-9_-]+$", p["id"]):
                raise ValueError("id は英数字・_・- で指定してください")
            lines = p.get("lines") or {}
            if not isinstance(lines, dict):
                raise ValueError("lines の形式が違います")
            p["lines"] = {k: [t for t in (v if isinstance(v, list) else [v]) if str(t).strip()]
                          for k, v in lines.items()}
            p["lines"] = {k: v for k, v in p["lines"].items() if v}
            store.save_persona(p)
            self.personas = store.load_personas()
            return self.personas[p["id"]]

    def reset_persona(self, pid):
        with self.lock:
            f = store.dpath("personas", pid + ".json")
            if os.path.exists(f):
                os.remove(f)
            self.personas = store.load_personas()
            return {"exists": pid in self.personas}

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
            c = {"id": cid, "name": name or "新しいキャラ", "player_call": "", "first_person": "", "persona": "",
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

    def save_minigames(self, items):
        with self.lock:
            if not isinstance(items, list):
                raise ValueError("ミニゲーム定義は配列で指定してください")
            ids = [g.get("id") for g in items]
            if any(not i for i in ids) or len(set(ids)) != len(ids):
                raise ValueError("ミニゲームの id が空か重複しています")
            for g in items:
                if g.get("kind") not in games.KINDS:
                    raise ValueError("「%s」の kind は %s のどれかです" % (g.get("name", g["id"]), " / ".join(games.KINDS)))
                for k in ("require", "when"):
                    cond.parse(g.get(k, ""))
                for ev, lines in (g.get("lines") or {}).items():
                    self._check_conds(lines, "「%s」の %s" % (g.get("name", g["id"]), ev))
                if g["kind"] in games.STRIP_KINDS and not g.get("stages"):
                    raise ValueError("「%s」の stages が空です" % g.get("name", g["id"]))
            self.minigames = items
            store.save(store.dpath("minigames.json"), items)
            for st in self.states.values():   # 消えたゲームの進行中状態は破棄
                if st.get("game") and st["game"].get("id") not in ids:
                    st["game"] = None
            return items

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
