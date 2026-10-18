"""疑似生活シミュレーション本体.

- リアル時刻でパラメータを進める (5 分刻みで追いつき計算)
- スケジュール / 行動による一時シーン (override) から現在の場面を決める
- 行動 → 反応選択 → 効果適用 → プロンプト合成 → ComfyUI ジョブ
"""
import glob
import hashlib
import json
import math
import os
import queue
import random
import re
import shutil
import threading
import time
import uuid
from datetime import datetime

from . import bonds as bonds_mod
from . import encounters as encounters_mod
from . import solo as solo_mod
from . import outdoor as outdoor_mod
from . import presence as presence_mod
from . import comfy, cond, games, life, llm, store
from . import keys as keys_mod
from .keys import line_keys

STEP_SEC = 300
MAX_CATCHUP_SEC = 14 * 24 * 3600
DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_JA = "月火水木金土日"
LOG_KEEP_IN_VIEW = 60
SEASONS = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
           6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}
PERSONA_ORDER = ["teinei", "osananajimi", "aneki", "ottori", "ojousama", "kedakai", "tsundere", "sadist", "itazura", "cool", "mukuchi", "jimuteki",
                 "rikejo", "otokomae", "genki", "tenshin", "fushigi", "hitonatsukko", "uchiki", "hikutsu", "byoujaku", "boyish", "amaenbo"]


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
        self.life = life.Life(self)
        self.bonds = bonds_mod.Bonds(self)
        self.encounters = encounters_mod.Encounters(self)
        self.solo = solo_mod.Solo(self)
        self.outdoor = outdoor_mod.Outdoor(self)
        self.presence = presence_mod.Presence(self)
        self.tasks = {}          # 内職の作業 (token -> {t0, kind, cid})
        self._load_index()
        self._ensure_worker()

    # ------------------------------------------------------------------ config
    def reload(self):
        self.settings = store.load_settings()
        self.params = store.load(store.wpath("params.json"), [])
        self.actions = store.load(store.wpath("actions.json"), [])
        # 既定に増えた項目 (economy など) も使えるよう, 既定の上に data を重ねる
        self.world = store.deep_merge(store.load(os.path.join(store.DEFAULTS, "world.json"), {}),
                                      store.load(store.wpath("world.json"), {}))
        self.chars = store.load_characters()
        self.minigames = store.load(store.wpath("minigames.json"), [])
        self.events = store.load(store.wpath("events.json"), [])
        self.approaches = store.load(store.wpath("approaches.json"), [])
        self.personas = store.load_personas()
        self.relations = store.load(store.wpath("relations.json"), {}) or {}
        if self.settings.get("active_character") not in self.chars and self.chars:
            self.settings["active_character"] = next(iter(self.chars))
        self._migrate()

    def _migrate(self):
        """既存の data/ に, 後から増えた既定項目を補う (ユーザーの編集内容は上書きしない)."""
        self._sync_defaults("actions", self.actions, "actions.json")
        self._sync_defaults("minigames", self.minigames, "minigames.json")
        self._sync_defaults("events", self.events, "events.json")
        self._sync_defaults("approaches", self.approaches, "approaches.json")
        for c in self.chars.values():
            # お出かけ着と, 着せ替えの服を外に着ていけるか (既定の服だけ判定. 自作の服は設定で選ぶ)
            if "outfit_outing" not in c or any("outing_ok" not in o for o in c.get("wardrobe") or []):
                c.setdefault("outfit_outing", c.get("outfit_default", ""))
                for o in c.get("wardrobe") or []:
                    o.setdefault("outing_ok", o.get("id") in ("casual", "onepiece", "yukata"))
                store.save_character(c)
            # 以前は性格を選ぶと呼び方をキャラにコピーしていた. プリセットと同じなら「プリセットに従う」(空欄) に戻す
            p = self.personas.get(c.get("persona_id") or "")
            if p and c.get("player_call") and c["player_call"] == p.get("player_call"):
                c["player_call"] = ""
                store.save_character(c)
            if "wardrobe" not in c:
                d = store.load(os.path.join(store.DEFAULTS, "characters", c["id"] + ".json")) or {}
                c["wardrobe"] = d.get("wardrobe", [])
                store.save_character(c)

    def _sync_defaults(self, kind, items, fname):
        """data/ の項目を既定に追従させる.
        - 過去の既定と完全に同じ (=未編集) 項目は最新の既定に更新する. 手を加えたものは触らない
        - 新しく増えた既定項目を, 既定での並び位置に近いところへ追加する (ユーザーが消したものは戻さない)"""
        defaults = store.load(os.path.join(store.DEFAULTS, fname), [])
        hist = (store.load(os.path.join(store.DEFAULTS, "default_history.json"), {}) or {}).get(kind, {})
        dmap = {d["id"]: d for d in defaults}
        updated = []
        for i, it in enumerate(items):
            d = dmap.get(it.get("id"))
            if d is None:
                continue
            h = store.obj_hash(it)
            if h != store.obj_hash(d) and h in hist.get(it["id"], []):
                items[i] = json.loads(json.dumps(d))
                updated.append(it["id"])
        have = [it.get("id") for it in items]
        key = "seen_" + kind
        seen = set(self.settings.get(key) or []) or set(have)
        added = []
        for pos, d in enumerate(defaults):
            if d["id"] in have or d["id"] in seen:
                continue
            prev = next((defaults[j]["id"] for j in range(pos - 1, -1, -1) if defaults[j]["id"] in have), None)
            at = have.index(prev) + 1 if prev else len(items)
            items.insert(at, json.loads(json.dumps(d)))
            have.insert(at, d["id"])
            added.append(d["id"])
        if updated or added:
            store.save(store.wpath(fname), items)
            self.logq.put("%s [INFO] 既定の%sを反映: 更新 %d 件 %s / 追加 %d 件 %s" % (
                datetime.now().strftime("%m-%d %H:%M:%S"), kind, len(updated), ",".join(updated),
                len(added), ",".join(added)))
        all_ids = sorted(seen | set(dmap))
        if all_ids != sorted(self.settings.get(key) or []):
            self.settings[key] = all_ids
            store.save_settings(self.settings)

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
            st = store.load(store.wpath("state", cid + ".json"))
            if st is None:
                t = time.time()
                st = {"params": {}, "last_tick": t, "last_interaction": t, "override": None,
                      "cooldowns": {}, "created": t}
            self.states[cid] = st
        for p in self.params:
            st["params"].setdefault(p["id"], float(p.get("init", 50)))
        return st

    def save_state(self, cid):
        store.save(store.wpath("state", cid + ".json"), self.states[cid])

    def log(self, cid):
        if cid not in self.logs:
            self.logs[cid] = store.load(store.wpath("log", cid + ".json"), [])
        return self.logs[cid]

    def save_log(self, cid):
        store.save(store.wpath("log", cid + ".json"), self.logs[cid])

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
                "outing": bool(e.get("outing")),   # 外出 (散歩・お出かけ). 部屋着のままにはしない
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
        if o and s["outing"] and not o.get("outing_ok"):
            o = None          # 部屋着・パジャマなどは外に着ていかない (お出かけ着のまま)
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
            if s["outfit"] == "@outing" or (s["outing"] and not s["outfit"]):
                s["outfit"] = char.get("outfit_outing") or char.get("outfit_default", "")
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
            "outing": scene.get("outing", False),
            # 行動による一時的な過ごし方 (ゲーム・映画・散歩など) の最中か. 寝ているのは除く
            "overriding": scene.get("source") == "override" and not scene["asleep"],
            "month": dt.month, "season": SEASONS[dt.month],
        })
        ctx.update(self.life.money_ctx(st))                    # my_money / her_money / invest_value / profit
        ctx.update(self.life.mood_ctx(st, dt.timestamp()))     # cause / knows / reason / untold / request / away_events
        ctx.update(self.presence.ctx(dt.timestamp()))          # presence / said / left_mode / left_h
        ctx.update(self.bonds.ctx(char["id"], st))             # stage / apart / with_mode / living_other / rivals
        if ctx["apart"]:
            ctx["away"] = True      # あなたから見れば, そばにいない (free は相手自身の予定のまま = 誘えるか)
        ctx["roll"] = random.randint(0, 99)
        ctx.update(self.player_ctx())                          # player_gender / player_age / player_has_job / player_likes                    # 反応を確率で分けたいとき用 (例: sk_cook<30, roll<50)
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
        pres = self.presence.effects(dt.timestamp()) \
            if char["id"] == self.settings.get("active_character") and not scene["away"] and self.bonds.together(char["id"]) else {}
        tr = self.traits(char)
        t_rate, t_drift, t_speed = tr.get("rate") or {}, tr.get("drift") or {}, tr.get("drift_speed") or {}
        if pres and self.presence.at(dt.timestamp()) == "gone":     # 黙っていなくなった: 性格しだいで堪える
            pres = {k: float(v) * float(tr.get("absence", 1)) for k, v in pres.items()}
        for p in self.params:
            pid = p["id"]
            v = vals.get(pid, float(p.get("init", 50)))
            rate = float(p.get("rate", 0))
            for r in p.get("rate_rules") or []:
                if cond.check(r.get("when", ""), ctx):
                    rate = float(r.get("rate", 0))
                    break
            rate *= float(t_rate.get(pid, 1))
            d = rate * h + float(scene["effects"].get(pid, 0)) * h + float(pres.get(pid, 0)) * h
            dr = p.get("drift")
            if dr:
                target = float(dr.get("target", v)) + float(t_drift.get(pid, 0)) + sum(
                    float(m.get("add", 0)) for m in dr.get("mods") or [] if cond.check(m.get("when", ""), ctx))
                d += (target - v) * min(1.0, float(dr.get("rate", 0)) * float(t_speed.get(pid, 1)) * h)
            vals[pid] = self._clamp(p, v + d)

    def tick(self, cid, now=None):
        char, st = self.char(cid), self.state(cid)
        now = now or time.time()
        t = st.get("last_tick") or now
        if now - t > MAX_CATCHUP_SEC:
            t = now - MAX_CATCHUP_SEC
        changed = False
        self.life.tick_world(now)
        while t + STEP_SEC <= now:
            self._step(char, st, datetime.fromtimestamp(t + STEP_SEC / 2), STEP_SEC / 3600.0)
            self.life.step(char, st, t, t + STEP_SEC, STEP_SEC / 3600.0)   # お金の出入り・キャラ側の出来事
            self.bonds.step(char, st, t + STEP_SEC, STEP_SEC / 3600.0)     # ほかの人との仲に気づく (嫉妬)
            t += STEP_SEC
            changed = True
        st["last_tick"] = t
        ov = st.get("override")
        if ov and ov.get("until", 0) <= now:
            st["override"] = None
            changed = True
        self.bonds.sync(cid, st, now)         # 外で会っていたお出かけが終わった / 遊びに来ていた時間が過ぎた
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
                 {"src": "キャラクター", "pos": char.get("pos", ""), "neg": char.get("neg", "")},
                 {"src": "服装" + (": " + scene["dress"] if scene["dress"] else ""),
                  "pos": scene["outfit"], "neg": scene["outfit_neg"]}]
        looks = (self.player_profile().get("looks") or "").strip()
        if act and act.get("with_player") and looks:
            parts.append({"src": "あなた", "pos": looks, "neg": ""})
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
        """(一人称, 言いよどみの一人称, 呼び方). キャラクターで固定していればそれ, 無ければ性格プリセットに従う."""
        p = self.personas.get(char.get("persona_id") or "") or {}
        player = self.player_name()
        fixed_fp = (char.get("first_person") or "").strip()
        fp = fixed_fp or p.get("first_person") or "私"
        fp_st = fixed_fp or p.get("first_person_stutter") or fp
        call = (char.get("player_call") or "").strip() or p.get("player_call") or "{player}"
        return fp, fp_st, call.replace("{player}", player)

    # ------------------------------------------------------------------ あなた (プレイヤー)
    def player_profile(self):
        """あなたの情報 (全ワールド共通). キャラクターはこれを見て反応する."""
        p = dict(self.settings.get("player") or {})
        p["name"] = (p.get("name") or self.settings.get("player_name") or "").strip()
        return p

    def player_name(self):
        return self.player_profile()["name"] or "あなた"

    @staticmethod
    def _items(s):
        return [x.strip() for x in str(s or "").replace("、", ",").split(",") if x.strip()]

    def player_ctx(self):
        p = self.player_profile()
        age = p.get("age")
        return {"player_gender": p.get("gender") or "none", "player_age": float(age) if str(age or "").strip() else 0,
                "player_has_job": bool((p.get("job") or "").strip()),
                "player_likes": len(self._items(p.get("likes"))), "player_dislikes": len(self._items(p.get("dislikes")))}

    def player_text(self):
        """LLM に渡す, あなたの紹介."""
        p = self.player_profile()
        g = {"male": "男性", "female": "女性", "other": "その他"}.get(p.get("gender") or "", "")
        bits = [x for x in (g, ("%s歳" % p["age"]) if str(p.get("age") or "").strip() else "",
                            ("職業: " + p["job"]) if p.get("job") else "",
                            ("人柄: " + p["personality"]) if p.get("personality") else "",
                            ("好きなもの: " + p["likes"]) if p.get("likes") else "",
                            ("苦手なもの: " + p["dislikes"]) if p.get("dislikes") else "",
                            p.get("note") or "") if x]
        return "、".join(bits)

    def format_text(self, text, char, scene, dt):
        player = self.player_name()
        prof = self.player_profile()
        likes, dislikes = self._items(prof.get("likes")), self._items(prof.get("dislikes"))
        text = text.replace("{player_job}", prof.get("job") or "お仕事") \
            .replace("{player_like}", random.choice(likes) if likes else "好きなもの") \
            .replace("{player_dislike}", random.choice(dislikes) if dislikes else "苦手なもの")
        fp, fp_st, call = self.pronouns(char)
        for k, v in (("{fp_st}", fp_st), ("{fp}", fp), ("{call}", call), ("{player}", player), ("{name}", char.get("name", "")),
                     ("{location}", scene["location"]), ("{activity_label}", scene["label"]),
                     ("{time}", dt.strftime("%H:%M"))):
            text = text.replace(k, v)
        return text

    def _llm_text(self, char, st, dt, act, template, scene):
        cfg = self.settings.get("llm") or {}
        player = self.player_name()
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
        if self.player_text():
            system += "\n%sについて知っていること: %s。これを踏まえて話す（好きなものの話題に乗る、苦手なものは避ける など）。" % (
                player, self.player_text())
        bv = self.bonds.view(char["id"])
        system += "\n%sとの間柄: %s（いまは%s）。" % (player, bv["stage_label"], bv["label"])
        known = self.relations_text(char)
        if known:
            system += "\n知っている人: %s。それ以外の登場人物は知らない。" % known
        user = ("現在 %s（%s曜 %s）\n%sの状況: %s（%s）\nパラメータ: %s\n目立つ状態: %s\n直近のやりとり:\n%s\n\n"
                "%sの行動: %s\n参考セリフ（この方向性で）: %s\n\n%sとしてのセリフだけを返して。"
                % (dt.strftime("%H:%M"), DAY_JA[dt.weekday()], self.phase_at(dt).get("label", ""),
                   char.get("name", ""), scene["label"], scene["location"], "、".join(lines), tags,
                   recent or "（なし）", player, act.get("name", ""), template, char.get("name", "")))
        return llm.chat(cfg, system, user)

    # ------------------------------------------------------------------ actions
    def persona_text(self, char, key):
        """キャラクターの性格プリセットにそのキーのセリフがあれば 1 つ選んで返す."""
        if not key:
            return None
        p = self.personas.get(char.get("persona_id") or "")
        texts = (p or {}).get("lines", {}).get(key)
        if isinstance(texts, str):
            return texts
        return random.choice(texts) if texts else None

    def traits(self, char):
        """性格プリセットの傾向 (パラメータの動きやすさ・話しかけてくる多さなど)."""
        return (self.personas.get(char.get("persona_id") or "") or {}).get("traits") or {}

    def trait_effects(self, char, eff):
        """性格による効き目の違い: うれしい方向は gain, つらい方向は hurt の倍率をかける."""
        tr = self.traits(char)
        gain, hurt = tr.get("gain") or {}, tr.get("hurt") or {}
        if not (gain or hurt):
            return dict(eff)
        out = {}
        for k, v in eff.items():
            pd = self.param_def(k) or {}
            good = (float(v) > 0) != bool(pd.get("invert"))
            out[k] = float(v) * float((gain if good else hurt).get(k, 1))
        return out

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
            out[a["id"]] = {"ok": cond.check(a.get("when", ""), ctx) and not (a.get("home_only") and ctx["outing"])
                            and (not ctx["apart"] or self.bonds.allowed_apart(a, char["id"])),
                            "cooldown": max(0, int(last + cd - now)) if cd else 0}
        return out

    def act(self, aid, cid=None, dress=None, opts=None):
        """行動を実行する. aid="_dress" のときは dress に着替え先の id ("" でおまかせ) を渡す.
        opts: 呼び出し側で済ませたお金の動きなど {"money": {p, a}, "extra": 置換文字, "ctx": 条件に足す値}."""
        opts = opts or {}
        with self.lock:
            char = self.char(cid)
            cid = char["id"]
            self.tick(cid)
            st, a = self.state(cid), self.action(aid)
            now = time.time()
            dt = datetime.fromtimestamp(now)
            if a.get("category") != "system":       # 画面から操作した = そばにいる
                pr = self.presence.rec()
                if not opts.get("deliver"):        # 時間差で届いた返信は, あなたの操作ではない
                    pr["beat"] = pr["input"] = now
            scene = self.scene_at(char, st, dt)
            ctx = self.context(char, st, dt, scene)
            if not cond.check(a.get("when", ""), ctx):
                raise ValueError("今は「%s」できません（%s）" % (a.get("name", aid), a.get("when", "")))
            if a.get("home_only") and ctx["outing"]:
                raise ValueError("お出かけ中は「%s」できません" % a.get("name", aid))
            apart = ctx["apart"]
            if apart and a.get("reply_later", aid == "message") and not opts.get("deliver"):
                # 離れている相手へのメッセージは, 送るだけ. 返信は相手の状況しだいで, しばらくしてから (来ないことも)
                return self._send_later(char, st, a, now, dt, scene, ctx)
            if apart and a.get("category") != "system" and not self.bonds.allowed_apart(a, cid):
                if self.bonds.stage(cid) == "known":
                    raise ValueError("%sの連絡先を知りません（偶然会えたら交換できます）" % char.get("name", ""))
                raise ValueError("いまは%sと一緒にいません（連絡するか、会いに行きましょう）" % char.get("name", ""))
            ctx.update(opts.get("ctx") or {})
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
            # ---- お金: 誰が払うか・払えるかを先に決める (反応の条件 payer で使える)
            extra = self.life.mood_text(st, now)          # {ev_text} {bad_text} {away_text} {req_text} {amount}
            extra.update(opts.get("extra") or {})
            plan, req = None, st.get("request")
            if a.get("cost"):
                plan = self.life.plan_payment(char, st, int(a["cost"]), "me" if a.get("payer") == "me" else None)
                ctx["payer"] = plan["payer"]
                extra["cost"] = format(int(a["cost"]), ",")
            ans = a.get("request_answer")
            if ans:
                if not req:
                    raise ValueError("今はお願いされていません")
                ctx["req_kind"] = req["kind"]
                if ans == "yes" and req["kind"] in ("money", "gift") and self.life.player_state()["money"] < req["amount"]:
                    raise ValueError("お金が足りません（%s円必要）" % format(req["amount"], ","))
            tr = a.get("transfer")
            if tr and tr.get("from") == "p" and self.life.player_state()["money"] < int(tr.get("amount", 0)):
                raise ValueError("お金が足りません（%s円必要）" % format(int(tr["amount"]), ","))
            r = self.pick_reaction(a, ctx)
            invite = apart and (a.get("override") or {}).get("outing")
            if invite and ctx.get("affection", 0) < float(self.bonds.cfg()["meet_min_affection"]) and not r.get("override"):
                r = {"text": "📱『ごめんなさい、その日はちょっと……』", "override": True, "key": "_invite_no"}
            mine = (a.get("category") == "あなたの予定" or aid in bonds_mod.APART_TEXT) and not a.get("request_answer")
            # 同居していない相手と外で会っている / 相手の家にいるときに出かける・離れる = 別れて行く
            parting = mine and not apart and self.bonds.mode(cid) in ("meet", "visit")                 and a.get("presence_set") in ("work", "out", "left", "sleep")
            narrate = (apart and mine) or parting
            if narrate:     # 離れている相手は見送りも出迎えもしない. あなたの行動だけを書く
                what = a.get("apart_text") or bonds_mod.APART_TEXT.get(aid) or a.get("name", aid)
                r = {"text": "（%s%s）" % ("{name}と別れて、" if parting else "", what)}
            scale = float(a.get("repeat_scale", 0.5)) ** len(hist)
            sk = a.get("skill")
            sk_mult = self.life.skill_mult(sk) if sk else 1.0
            if a.get("category") not in ("system", "あなたの予定"):
                sk_mult *= self.life.stamina_mult()        # 疲れていると, 構っても効きが悪い
            eff = {}
            if not r.get("override"):
                for k, v in (a.get("effects") or {}).items():
                    v = float(v) * scale
                    pd = self.param_def(k) or {}
                    if (v < 0) == bool(pd.get("invert")) or pd.get("neutral"):
                        v *= sk_mult          # あなたのスキルで, うれしい方向の効き目が変わる
                    eff[k] = eff.get(k, 0) + v
            for k, v in (r.get("effects") or {}).items():
                eff[k] = eff.get(k, 0) + float(v)
            if narrate:
                eff = {}
            for k, v in (opts.get("effects") or {}).items():
                eff[k] = eff.get(k, 0) + float(v)
            real_note = None
            social = a.get("category") not in ("system", "あなたの予定") or a.get("request_answer")
            if social and not narrate:
                # 現実的に: 好感度・信頼の上がり方は揺らぎ, 鈍り, 繰り返せばうんざりされる. 交流した日も記録する
                eff, real_note = self.bonds.realize(char, st, eff, aid, now, gift=a.get("gift"))
                self.bonds.touch(st, now)
                if a.get("gift"):
                    st.setdefault("gifts", []).append(now)
                    st["gifts"] = [x for x in st["gifts"] if now - x < 30 * 86400]
            deltas = self.apply_effects(st, self.trait_effects(char, eff))
            if a.get("override") and not r.get("override"):
                ov = dict(a["override"])
                ov["until"] = now + float(ov.get("minutes", 30)) * 60
                ov["from_action"] = aid
                st["override"] = ov
            if a.get("end_override") and not r.get("override"):
                st["override"] = None     # 「家に帰る」「切り上げる」: 一時的な過ごし方を終えて予定に戻る
            if dress is not None and not r.get("override"):
                st["dress"] = {"id": dress, "t": now} if dress else None
            if not r.get("override"):
                self.bonds.apply(a, cid, now)
                if invite:
                    self.bonds.start(cid, "meet", now)      # 誘いに乗ってくれた: 外で会う
            self.bonds.sync(cid, st, now)                   # 「家に帰る」で別れる など
            money = self._act_money(char, st, a, r, plan, req, extra)
            for k, v in (opts.get("money") or {}).items():
                money[k] = money.get(k, 0) + v
            self._act_reasons(char, st, a, r, deltas, now)
            skill_up = {sk: self.life.train(sk, 1.2 * scale)} if sk else {}
            skill_up.update(opts.get("skill") or {})
            if a.get("presence_set"):
                self.presence.declare(a["presence_set"], now)
                if parting:
                    self.bonds.end()
            elif a.get("category") != "system" and not opts.get("deliver"):
                self.presence.touch(now)
                if self.presence.rec()["mode"] == "busy":
                    self.presence.rec()["mode"] = "none"     # 作業中でも, 構いに来たら作業はおしまい
                    self.presence.rec().pop("solo", None)
                self.presence.drop(st)
            if cd:
                st["cooldowns"][aid] = hist + [now]
            st["last_interaction"] = now
            scene2 = self.scene_at(char, st, dt)
            rs = a.get("reactions") or []
            pkey = "%s.%s" % (aid, line_keys(rs)[rs.index(r)]) if r in rs else None
            text = self.persona_text(char, pkey) or r.get("text", "")
            if "{away_text}" in text or "{ev_text}" in text or "{bad_text}" in text:
                # 話して聞かせた出来事は「理由を知っている」扱いにする
                said = " ".join(extra.get(k, "") for k in ("away_text", "ev_text", "bad_text") if "{%s}" % k in text)
                for x in self.life.reasons(st, now):
                    if x["kind"] == "event" and x["tell"] and x["tell"] in said:
                        x["told"] = True
            for k, v in extra.items():                     # 先に差し込む (中の {call} なども下で置換される)
                text = text.replace("{%s}" % k, str(v))
            text = self.format_text(text, char, scene, dt)
            gen_ok = a.get("generate", True)
            selfie = False
            if not self.bonds.together(cid):
                # 離れている相手の画像は出さない. ただしメッセージには, テンションしだいで自撮りが添えられる
                selfie = bool(a.get("selfie")) and not r.get("override") and random.random() < self.bonds.selfie_chance(ctx)
                gen_ok = selfie
            pa = dict(a, pos=a.get("selfie_pos") or "selfie, holding smartphone, looking at viewer, upper body") if selfie else a
            pos, neg, parts = self.build_prompt(char, st, dt, pa, r)
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

        if selfie:
            text += "\n（📷 自撮りが添えられていた）"
        if real_note:
            text += "\n" + self.format_text(real_note, char, scene, dt)
        with self.lock:
            entry = self._new_entry(cid, now, a, text, deltas, scene2, dt, pos, neg, parts)
            entry["text_src"] = text_src
            if selfie:
                entry["selfie"] = True
            if money:
                entry["money"] = money
            if any(skill_up.values()):
                entry["skill"] = {k: v for k, v in skill_up.items() if v}
            job = None
            if self.settings.get("auto_generate") and gen_ok:
                job = self._present_image(cid, entry)
            self.save_log(cid)
        return {"entry": entry, "job": job, "llm_error": llm_error}

    def _send_later(self, char, st, a, now, dt, scene, ctx):
        """離れている相手にメッセージを送る. 返信の予定 (いつ・来るか) を決めて, 送った記録だけを残す."""
        cid = char["id"]
        p = st["params"]
        pend = st.get("msg_pending")
        if pend:
            pend["count"] = pend.get("count", 1) + 1
        else:
            delay = random.uniform(3, 40) * 60
            if p.get("mood", 50) < 35:
                delay *= 2
            if p.get("affection", 50) < 40:
                delay *= 2
            pr = 0.9 * (0.6 if p.get("mood", 50) < 30 else 1) * (0.7 if p.get("affection", 50) < 35 else 1) \
                * (0.7 if p.get("stress", 0) > 70 else 1)
            st["msg_pending"] = {"aid": a["id"], "t": now, "due": now + delay, "reply": random.random() < pr, "count": 1}
        cd = float(a.get("cooldown", 0)) * 60
        if cd:
            st["cooldowns"][a["id"]] = [x for x in st["cooldowns"].get(a["id"], []) if now - x < cd] + [now]
        text = "（📱 %sにメッセージを送った）" % char.get("name", "")
        pos, neg, parts = self.build_prompt(char, st, dt, a)
        e = self._new_entry(cid, now, a, text, {}, scene, dt, pos, neg, parts)
        e["sent"] = True
        self.save_state(cid)
        self.save_log(cid)
        return {"entry": e, "job": None, "llm_error": None, "sent": True}

    def deliver_due(self, now=None):
        """時間差の返信: 期限が来て, 相手が寝ていない・手が離せないなら返信が届く (来ないと決まっていれば読むだけ).
        届いた返信 [{cid, name, text}] を返す."""
        now = now or time.time()
        out = []
        for cid in list(self.chars):
            st = self.state(cid)
            pend = st.get("msg_pending")
            if not pend or now < pend.get("due", 0):
                continue
            if now - pend["t"] > 24 * 3600:          # 一日たっても返ってこなければ, もう来ない
                st.pop("msg_pending", None)
                self.save_state(cid)
                continue
            char = self.chars[cid]
            self.tick(cid, now)
            scene = self.scene_at(char, st, datetime.fromtimestamp(now))
            if scene["asleep"] or scene["busy"]:       # 寝ている・入浴中・仕事中など: 落ち着いてから
                pend["due"] = now + random.uniform(15, 40) * 60
                self.save_state(cid)
                continue
            st.pop("msg_pending", None)
            if not pend.get("reply"):
                self.save_state(cid)                   # 読んだが, 返事はしなかった
                continue
            try:
                r = self.act(pend["aid"], cid, opts={"deliver": True})
            except (ValueError, KeyError):
                self.save_state(cid)
                continue
            e = r["entry"]
            e["action_name"], e["icon"], e["reply"] = "返信", "📱", True
            self.save_log(cid)
            out.append({"cid": cid, "name": char.get("name", ""), "text": e["text"], "late": now - pend["t"] > 3600})
        return out

    def _act_money(self, char, st, a, r, plan, req, extra):
        """行動に伴うお金の出入り. 断られた (override) ときは動かさない. 動いた額 {p, a} を返す."""
        money = {}

        def add(m):
            for k, v in m.items():
                money[k] = money.get(k, 0) + v

        if r.get("override"):
            if a.get("request_answer"):
                st["request"] = None
            return money
        L = self.life
        if plan:
            add(L.move(st, plan["p"], plan["a"]))
        if a.get("earn"):
            for who, rng in a["earn"].items():
                amt = life._amount(rng)
                add(L.move(st, dp=amt) if who == "p" else L.move(st, da=amt))
                extra["amount"] = format(amt, ",")
        tr = a.get("transfer")
        if tr:
            amt = int(tr.get("amount", 0))
            if tr.get("from") == "a":
                amt = min(amt, max(L.her_money(st)["a"], 0))
            if amt:
                add(L.move(st, dp=-amt, da=amt) if tr.get("from") == "p" else L.move(st, dp=amt, da=-amt))
            extra["amount"] = format(amt, ",")
        ans = a.get("request_answer")
        if ans and req:
            amt = int(req.get("amount", 0))
            if ans == "yes":
                if req["kind"] == "money":
                    add(L.move(st, dp=-amt, da=amt))
                elif req["kind"] == "gift":
                    add(L.move(st, dp=-amt))
                elif req["kind"] == "treat":
                    add(L.move(st, da=-min(amt, max(L.her_money(st)["a"], 0))))
            st["request"] = None
        return money

    def _act_reasons(self, char, st, a, r, deltas, now):
        """機嫌の理由: 聞いた (ask) / 相談にのった (comfort) / 謝った (apologize) を反映し,
        それ以外の行動で機嫌が大きく動いたら, あなたの行動を理由として記録する."""
        L = self.life
        rr = r.get("reason")
        if rr and rr.get("tell"):          # 反応に理由が書いてあれば, それを記録する (例: 黙っていなくなった)
            L.add_reason(st, "player", rr.get("mood", "bad"), rr["tell"].replace("{call}", self.pronouns(char)[2]), now,
                         told=True, delta=deltas.get("mood", 0), action=a.get("id"))
            return
        ma = a.get("mood_action")
        if ma:
            if r.get("override"):           # はぐらかされた・逆効果: 理由は分からないまま
                return
            if ma == "ask":
                untold = [x for x in L.reasons(st, now) if not x["told"]]
                L.mark_told(untold[0] if untold else L.dominant(st, now))
            elif ma == "comfort":
                bad = L.dominant(st, now, "bad")
                if bad and bad["kind"] == "event":
                    L.mark_told(bad)
                    L.resolve(st, "bad", now)
            elif ma == "apologize":
                bad = L.dominant(st, now, "bad")
                if bad and bad["kind"] == "player":
                    L.resolve(st, "bad", now)
            return
        if a.get("request_answer") or a.get("category") == "system":
            return
        L.note_player_reason(char, st, a, deltas, now, self.pronouns(char)[2])

    # ------------------------------------------------------------------ image reuse
    @staticmethod
    def prompt_key(pos, neg):
        """同一プロンプト判定のキー (generatw と同じく pos+neg の MD5)."""
        return hashlib.md5((pos + neg).encode("utf-8")).hexdigest()

    def _load_index(self):
        """プロンプト → 生成済み画像の索引 (全ワールド共通). 無ければ全ワールドのログから作り直す."""
        idx = store.load(store.dpath("images", "index.json"))
        if idx is None:
            idx = {}
            for f in glob.glob(store.dpath("worlds", "*", "log", "*.json")):
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
        """開いたときの「おかえり」. 告げて離れていたなら, その戻り (仕事なら稼ぎも). 黙って閉じていたら一定時間で."""
        char = self.char(cid)
        with self.lock:
            self.tick(char["id"])
            st = self.state(char["id"])
            absent = (time.time() - st.get("last_interaction", time.time())) / 3600.0
            p = self.presence.rec()
            if p["mode"] in presence_mod.AWAY_MODES or (p["mode"] == "busy" and self.presence.at(time.time() - 1) == "gone"):
                declared = True
            else:
                declared = False
        if declared:
            return self.come_back(char["id"])
        if self.bonds.mode(char["id"]) != "home":     # 「おかえり」は一緒に暮らしている相手だけ
            return None
        pc = self.presence.ctx(time.time())
        silent = pc["left_mode"] == "gone" and not pc["said"]
        if absent < float(self.world.get("absent_greet_hours", 3)) and not (silent and absent >= 1):
            return None
        try:
            self.action("_return")
        except KeyError:
            return None
        return self.act("_return", char["id"], opts={"effects": self.silent_penalty(char, absent) if silent else {}})

    def silent_penalty(self, char, hours):
        """何も言わずにいなくなったぶんの機嫌・信頼の目減り (空けた時間・寂しさ・性格しだい)."""
        st = self.state(char["id"])
        k = float(self.traits(char).get("absence", 1)) * (0.4 + st["params"].get("loneliness", 30) / 100.0)
        eff = {"mood": -min(10.0, 2 + hours * 0.4) * k}
        if hours >= 3:
            eff["trust"] = -min(4.0, hours * 0.1) * k
        if hours >= 24:
            eff["affection"] = -min(3.0, hours / 24.0) * k
        return {key: round(v, 1) for key, v in eff.items()}

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
        j = {"id": jid, "status": "queued", "stage": "queued", "cid": cid, "entry": eid, "wid": store.WORLD,
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

    def _job_entry(self, j, fn):
        """ジョブの元になったログ項目を fn(e) で書き換えて保存する.
        生成中にワールドを切り替えていたら, 元のワールドのログファイルを直接直す."""
        with self.lock:
            if j.get("wid", store.WORLD) == store.WORLD:
                e = self.find_entry(j["cid"], j["entry"])
                if e and fn(e) is not False:
                    self.save_log(j["cid"])
                return
            f = store.dpath("worlds", j["wid"], "log", j["cid"] + ".json")
            log = store.load(f, [])
            e = next((x for x in reversed(log) if x.get("id") == j["entry"]), None)
            if e and fn(e) is not False:
                store.save(f, log)

    def _clear_entry_job(self, j, error):
        def fn(e):
            if e.get("job") != j["id"]:
                return False
            e.pop("job", None)
            if error:
                e["error"] = error
        self._job_entry(j, fn)

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
                    self.img_index.setdefault(self.prompt_key(j["pos"], j["neg"]), []).append(
                        {"path": rel, "seed": j["seed"], "t": time.time()})
                    store.save(store.dpath("images", "index.json"), self.img_index)

                def put(e):
                    e["image"], e["seed"], e["reused"] = rel, j["seed"], False
                    e.pop("error", None)
                    e.setdefault("images", []).append({"path": rel, "seed": j["seed"], "pos": j["pos"],
                                                       "neg": j["neg"], "t": time.time()})
                    e.pop("job", None)
                self._job_entry(j, put)
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
    def state_view(self, cid=None, beat=False, idle=None):
        replies = self.deliver_due()
        # 画面を閉じていた (心拍が途絶えた) なら, 外出はその時点で終わっていた: 家で静かに過ごしていた
        gap = self.outdoor.check_gap() if beat else None
        with self.lock:
            char = self.char(cid)
            cid = char["id"]
            self.tick(cid)                  # 先に, 心拍が途絶えていた間を「いない」として進める
            if beat:
                self.presence.beat(time.time(), idle)
            street = self.outdoor.live() if beat else None     # 外出中の偶然の出会い (心拍のたびに)
            st = self.state(cid)
            now = time.time()
            if beat and cid == self.settings.get("active_character") and self.presence.live(char, st, now):
                self.save_state(cid)
            dt = datetime.fromtimestamp(now)
            scene = self.scene_at(char, st, dt)
            ctx = self.context(char, st, dt, scene)
            phase = self.phase_at(dt)
            log = self.log(cid)
            pending = [self.job_view(j["id"]) for j in self.jobs.values()
                       if j["cid"] == cid and j.get("wid") == store.WORLD and j["status"] in ("queued", "running")]
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
                "life": self.life.view(char, st),
                "solo": self.solo.view(), "replies": replies, "outdoor": self.outdoor.view(), "gap": gap, "street": street,
                "pending_msg": bool(st.get("msg_pending")),
                "bond": self.bonds.view(cid), "bonds": self.bonds.list_view(), "encounter": self.encounters.view(),
                "presence": self.presence.view(now),
                "approach": self.presence.pending_view(char, st),
                "auto": st.get("last_auto"),
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

    # ------------------------------------------------------------------ 在席・働きかけ・仕事・投資
    def come_back(self, cid=None, at=None, quiet=False):
        """告げて離れていたところから戻る. 仕事なら, 働いた時間ぶんの稼ぎを受け取る.
        at: 戻った時刻 (心拍が途絶えていたときは最後の心拍). quiet: 誰の反応もなく, 結果だけ (画面を閉じていたとき).
        偶然の出会いは外出中に起きるので (outdoor.live), 戻ったときには判定しない."""
        with self.lock:
            char = self.char(cid)
            st = self.state(char["id"])
            ll = self.presence.back(at)
            if not ll:
                raise ValueError("いまは離れていません")
            if ll["mode"] != "work":
                solo = self.solo.finish(ll)          # 一人の時間 (休む・家事・研鑽・散歩・買い物) の結果
                if quiet:
                    return {"text": ((solo or {}).get("text") or "").strip("（）") or "出かけ先から帰った", "solo": solo}
                r = self.act("_back", char["id"])
                r["solo"] = solo
                return r
            pay, h, raw = self.life.work_pay(ll["t"], ll["back"], record=True)
            mv = self.life.move(st, dp=pay) if pay else {}
            gain = self.life.train("work", 0.5 * h) if h >= 0.25 else 0
            self.life.tire(float(self.world.get("economy", {}).get("stamina_per_work_hour", 9)) * h)
            if quiet:
                self.save_state(char["id"])
                return {"text": "仕事を終えて帰った（%s円）" % format(pay, ","), "pay": pay}
        r = self.act("work", char["id"], opts={"money": mv, "extra": {"amount": format(pay, ",")},
                                               "ctx": {"work_h": round(raw, 2), "paid_h": round(h, 2), "pay": pay},
                                               "skill": {"work": gain}})
        return r

    def answer_encounter(self, yes):
        r = self.encounters.answer(yes)
        return r

    def answer_approach(self, ans, cid=None):
        with self.lock:
            char = self.char(cid)
            st = self.state(char["id"])
            ap = st.get("approach") or {}
            spec = (self.presence.find(ap.get("id")) or {}).get(ans) or {}
            aid = spec.get("action")
            if aid:           # 応じたら, そのコマンドをする (できない状況なら, ふつうに応じたことにする)
                try:
                    a = self.action(aid)
                    now = time.time()
                    ctx = self.context(char, st, datetime.fromtimestamp(now))
                    if not cond.check(a.get("when", ""), ctx) or (a.get("home_only") and ctx["outing"]):
                        aid = None
                except KeyError:
                    aid = None
            e, run = self.presence.answer(char, st, ans, use_action=bool(aid))
        if run:
            return self.act(run, char["id"])
        return {"entry": e, "job": e.get("job") if e else None}

    def force_approach(self, aid, cid=None):
        with self.lock:
            char = self.char(cid)
            st = self.state(char["id"])
            if st.get("approach"):
                st["approach"] = None
            now = time.time()
            d = datetime.fromtimestamp(now)
            e = self.presence.fire(char, st, now, self.context(char, st, d), force=aid)
            if not e:
                raise KeyError("働きかけが見つかりません: %s" % aid)
            self.save_state(char["id"])
            return {"entry": e, "job": e.get("job")}

    def trade(self, asset, qty, cid=None):
        with self.lock:
            mv, amt, profit = self.life.trade(asset, qty)
        name = next((a.get("name", asset) for a in self.life.assets() if a["id"] == asset), asset)
        return self.act("invest_buy" if int(qty) > 0 else "invest_sell", cid, opts={
            "money": mv, "ctx": {"profit": profit},
            "extra": {"amount": format(amt, ","), "profit": format(abs(profit), ","), "asset": name, "qty": format(abs(int(qty)), ",")}})

    def task_start(self, kind, cid=None):
        """内職を始める. 連続ではできない (コマンド side_job のクールダウン)."""
        with self.lock:
            char = self.char(cid)
            st = self.state(char["id"])
            a = self.action("side_job")
            now = time.time()
            ctx = self.context(char, st, datetime.fromtimestamp(now))
            if not cond.check(a.get("when", ""), ctx) or (a.get("home_only") and ctx["outing"]):
                raise ValueError("今は内職できません")
            cd = float(a.get("cooldown", 0)) * 60
            last = max(st["cooldowns"].get("side_job", [0]) or [0])
            if cd and now - last < cd:
                raise ValueError("まだ疲れが残っています（あと%d分）" % math.ceil((last + cd - now) / 60))
            need = float(self.world.get("economy", {}).get("stamina_per_side_job", 10))
            if self.life.stamina() < need:
                raise ValueError("疲れていて作業できません（体力 %d / %d 必要）" % (self.life.stamina(), need))
            token = uuid.uuid4().hex[:10]
            sec = int(self.world.get("economy", {}).get("side_job_seconds", 60))
            self.tasks = {k: v for k, v in self.tasks.items() if now - v["t0"] < 3600}
            self.tasks[token] = {"t0": now, "kind": kind, "cid": char["id"], "sec": sec}
            self.presence.declare("busy", now)
            return {"token": token, "seconds": sec, "skill": round(self.life.skill("work"), 1),
                    "unit": round(float(self.world.get("economy", {}).get("side_job_unit", 15)) * self.life.skill_mult("work"), 1)}

    def task_finish(self, token, ok, ng, cid=None):
        with self.lock:
            t = self.tasks.get(token)
            if not t:
                raise ValueError("作業が見つかりません（やり直してください）")
            now = time.time()
            if now - t["t0"] < t["sec"] - 3:
                raise ValueError("作業時間が足りません")
            self.tasks.pop(token, None)
            ok = max(0, min(int(ok), t["sec"] * 3))        # 1 秒に 3 個より速いのはありえない
            ng = max(0, int(ng))
            st = self.state(t["cid"])
            pay = self.life.side_job_pay(ok, ng)
            mv = self.life.move(st, dp=pay) if pay else {}
            gain = self.life.train("work", 0.05 * ok)
            self.life.tire(float(self.world.get("economy", {}).get("stamina_per_side_job", 10)))
            p = self.presence.rec()
            if p["mode"] == "busy":
                p["mode"] = "none"
        r = self.act("side_job", t["cid"], opts={"money": mv, "extra": {"amount": format(pay, ","), "ok": ok, "ng": ng},
                                                 "ctx": {"task_ok": ok, "task_ng": ng, "pay": pay}, "skill": {"work": gain}})
        r["task"] = {"ok": ok, "ng": ng, "pay": pay}
        return r

    def prompt_preview(self, cid=None):
        with self.lock:
            char = self.char(cid)
            self.tick(char["id"])
            pos, neg, parts = self.build_prompt(char, self.state(char["id"]), datetime.now())
            return {"pos": pos, "neg": neg, "parts": parts}

    def boot_view(self):
        return {"settings": self.settings, "params": self.params, "worlds": self.worlds_view(), "relations": self.relations, "actions": self.actions, "world": self.world,
                "characters": [{"id": c["id"], "name": c.get("name", "")} for c in self.chars.values()],
                "character": self.char(), "placeholders": list(comfy.PLACEHOLDERS),
                "has_workflow": os.path.exists(store.dpath("workflow.json")), "minigames": self.minigames,
                "events": self.events, "approaches": self.approaches,
                "personas": [{k: p.get(k) for k in ("id", "name", "desc", "persona", "player_call", "first_person", "traits", "_custom")}
                             for p in sorted(self.personas.values(), key=lambda p: (
                                 PERSONA_ORDER.index(p["id"]) if p["id"] in PERSONA_ORDER else 99, p.get("name", "")))]}

    # ------------------------------------------------------------------ personas
    def persona_full(self, pid):
        p = self.personas.get(pid)
        if not p:
            raise KeyError("性格プリセットが見つかりません: %s" % pid)
        return {"persona": p, "keys": keys_mod.all_keys(self.actions, self.minigames, self.approaches)}

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
            # あなたの名前は player.name に一本化 (古い player_name も同じ値にそろえておく)
            if "player_name" in obj and "player" not in obj:
                self.settings.setdefault("player", {})["name"] = obj["player_name"]
            self.settings["player_name"] = (self.settings.get("player") or {}).get("name") or self.settings.get("player_name", "")
            store.save_settings(self.settings)
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

    NEW_STAGES = ("contact", "known", "absent", "random")

    def new_character(self, name, copy_from=None, stage="contact", pos=None, persona_id=None):
        """設定からキャラを追加する. stage: このワールドでのあなたとの間柄.
        contact = 連絡先を知っている / known = 知り合い / absent = このワールドには現れない (偶然の出会いを待つ) /
        random = くじ (新しいワールドを作るときと同じ割合). 同居はいきなりは選べない (仲を深めて提案する).
        どれを選んでも登録キャラになり, ほかのワールドでは出会いの候補・新しいワールドの顔ぶれの候補になる."""
        if stage not in self.NEW_STAGES:
            raise ValueError("間柄の指定が違います: %s" % stage)
        with self.lock:
            src = self.char(copy_from) if copy_from else self.char()
            cid = "c" + uuid.uuid4().hex[:8]
            p = self.personas.get(persona_id or "") or {}
            c = {"id": cid, "name": name or "新しいキャラ", "player_call": "", "first_person": "",
                 "persona_id": p.get("id", ""), "persona": p.get("persona", ""),
                 "pos": (pos or "").strip() or "1girl, solo", "neg": "", "outfit_default": src.get("outfit_default", ""),
                 "schedule": src.get("schedule", []), "default_activity": src.get("default_activity", {}),
                 "prompt_history": []}
            if stage == "random":
                ec = self.encounters.cfg()
                r = random.random()
                pc, pk = float(ec["start_contact"]), float(ec["start_known"])
                stage = "contact" if r < pc else "known" if r < pc + pk else "absent"
            if stage == "absent":
                store.save(store.dpath("registry", "characters", cid + ".json"), c)
                return dict(c, _stage="absent")
            self.save_character(c)
            self.bonds.set_stage(cid, stage)
            self.select_character(cid)
            return dict(c, _stage=stage)

    def delete_character(self, cid):
        with self.lock:
            if len(self.chars) <= 1:
                raise ValueError("最後のキャラクターは削除できません")
            self.chars.pop(cid, None)
            store.delete_character(cid)
            self.relations.pop(cid, None)
            for r in self.relations.values():
                r.pop(cid, None)
            ps = self.bonds.rec()
            ps["bonds"].pop(cid, None)
            if (ps.get("with") or {}).get("cid") == cid:
                ps["with"] = None
            self.bonds.save()
            store.save(store.wpath("relations.json"), self.relations)
            if self.settings.get("active_character") == cid:
                self.select_character(next(iter(self.chars)))

    # ------------------------------------------------------------------ worlds
    def worlds_view(self):
        meta = store.load_worlds()
        return {"current": store.WORLD, "worlds": meta.get("worlds") or []}

    def create_world(self, name, copy_from=None, switch=True):
        """新しいワールド. copy_from を指定すればそのワールドの定義類とキャラ設定を複製 (状態・ログ・お金は引き継がない)."""
        with self.lock:
            meta = store.load_worlds()
            if copy_from and copy_from not in [w["id"] for w in meta["worlds"]]:
                raise KeyError("ワールドが見つかりません: %s" % copy_from)
            wid = "w" + uuid.uuid4().hex[:8]
            start = None
            if copy_from:
                store.init_world(wid, copy_from)
            else:
                # 登録済みのキャラ (どのワールドで作ったかを問わない) から, くじで連絡先を知っている人・知り合いを決める
                chars, start = self.encounters.start_cast()
                store.init_world(wid, chars=chars)
            if copy_from:
                rel = store.load(store.dpath("worlds", copy_from, "relations.json"))
                if rel:
                    store.save(store.dpath("worlds", wid, "relations.json"), rel)
            # 新しいワールドでは, あなたは最初だれとも暮らしていない (登録したキャラとは連絡先を知っている仲)
            meta["worlds"].append({"id": wid, "name": (name or "").strip() or "新しいワールド", "created": time.time(), "alone": True})
            if start is not None:
                meta["worlds"][-1]["start_bonds"] = start
            store.save_worlds(meta)
            if switch:
                self.switch_world(wid)
            return {"id": wid, "worlds": self.worlds_view()}

    def switch_world(self, wid):
        with self.lock:
            meta = store.load_worlds()
            if wid not in [w["id"] for w in meta["worlds"]]:
                raise KeyError("ワールドが見つかりません: %s" % wid)
            if wid == store.WORLD:
                return self.worlds_view()
            store.WORLD = wid
            store.init_world(wid)
            meta["current"] = wid
            store.save_worlds(meta)
            # ワールドごとの記憶を捨てて読み直す (生成中のジョブは元のワールドのログへ書き戻す)
            self.states, self.logs, self.tasks = {}, {}, {}
            self.life.player = None
            self.reload()
            return self.worlds_view()

    def rename_world(self, wid, name):
        with self.lock:
            meta = store.load_worlds()
            for w in meta["worlds"]:
                if w["id"] == wid:
                    w["name"] = (name or "").strip() or w["name"]
                    store.save_worlds(meta)
                    return self.worlds_view()
            raise KeyError("ワールドが見つかりません: %s" % wid)

    def delete_world(self, wid):
        """ワールドを消す (キャラ設定・状態・ログ・お金). 画像は全体共通なので残す."""
        with self.lock:
            meta = store.load_worlds()
            ids = [w["id"] for w in meta["worlds"]]
            if wid not in ids:
                raise KeyError("ワールドが見つかりません: %s" % wid)
            if len(ids) <= 1:
                raise ValueError("最後のワールドは削除できません")
            if wid == store.WORLD:
                self.switch_world(next(i for i in ids if i != wid))
                meta = store.load_worlds()
            meta["worlds"] = [w for w in meta["worlds"] if w["id"] != wid]
            store.save_worlds(meta)
            shutil.rmtree(store.dpath("worlds", wid), ignore_errors=True)
            return self.worlds_view()

    # ------------------------------------------------------------------ relations (同じワールドのキャラ同士)
    def relation(self, a, b):
        """a から見た b. knows: 知っているか / kind: 関係 (自由記述) / affinity: 好感度 (0〜100)."""
        r = (self.relations.get(a) or {}).get(b) or {}
        return {"knows": bool(r.get("knows")), "kind": r.get("kind", ""), "affinity": float(r.get("affinity", 50))}

    def save_relations(self, cid, rels):
        """cid から見た他キャラとの関係をまとめて保存. rels: {b: {knows, kind, affinity}}."""
        with self.lock:
            self.char(cid)
            out = {}
            for b, r in (rels or {}).items():
                if b == cid or b not in self.chars:
                    continue
                out[b] = {"knows": bool(r.get("knows")), "kind": str(r.get("kind") or "").strip(),
                          "affinity": max(0.0, min(100.0, float(r.get("affinity", 50))))}
            self.relations[cid] = out
            store.save(store.wpath("relations.json"), self.relations)
            return self.relations

    def change_affinity(self, a, b, delta):
        """出来事などで a→b の好感度を動かす (知り合いになる)."""
        with self.lock:
            r = self.relation(a, b)
            r["knows"] = True
            r["affinity"] = max(0.0, min(100.0, r["affinity"] + delta))
            self.relations.setdefault(a, {})[b] = r
            store.save(store.wpath("relations.json"), self.relations)
            return r

    def relations_text(self, char):
        """LLM へ渡す「このキャラが知っている人」."""
        out = []
        for b, r in sorted((self.relations.get(char["id"]) or {}).items()):
            if not r.get("knows") or b not in self.chars:
                continue
            a = float(r.get("affinity", 50))
            feel = "大好き" if a >= 80 else "好意的" if a >= 60 else "普通" if a >= 40 else "苦手" if a >= 20 else "嫌い"
            out.append("%s（%s、%s）" % (self.chars[b].get("name", b), r.get("kind") or "知り合い", feel))
        return "、".join(out)

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
            store.save(store.wpath("actions.json"), actions)
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
            store.save(store.wpath("params.json"), params)
            for cid in list(self.states):
                self.state(cid)
                self.save_state(cid)
            return params

    def save_world(self, world):
        with self.lock:
            self.world = world
            store.save(store.wpath("world.json"), world)
            return world

    def force_event(self, eid, cid=None):
        """テスト用: 出来事をいま起こす (条件・クールダウンは無視)."""
        with self.lock:
            char = self.char(cid)
            self.tick(char["id"])
            st = self.state(char["id"])
            rec = self.life.happen(char, st, time.time(), self.context(char, st, datetime.now()), force=eid)
            if not rec:
                raise KeyError("出来事が見つかりません: %s" % eid)
            self.save_state(char["id"])
            return rec

    def save_events(self, items):
        with self.lock:
            if not isinstance(items, list):
                raise ValueError("出来事は配列で指定してください")
            ids = [e.get("id") for e in items]
            if any(not i for i in ids) or len(set(ids)) != len(ids):
                raise ValueError("出来事の id が空か重複しています")
            self._check_conds(items, "出来事")
            self.events = items
            store.save(store.wpath("events.json"), items)
            return items

    def save_approaches(self, items):
        with self.lock:
            if not isinstance(items, list):
                raise ValueError("働きかけは配列で指定してください")
            ids = [e.get("id") for e in items]
            if any(not i for i in ids) or len(set(ids)) != len(ids):
                raise ValueError("働きかけの id が空か重複しています")
            self._check_conds(items, "働きかけ")
            self.approaches = items
            store.save(store.wpath("approaches.json"), items)
            return items

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
            store.save(store.wpath("minigames.json"), items)
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
            p = store.wpath("state", char["id"] + ".json")
            if os.path.exists(p):
                os.remove(p)
            self.state(char["id"])
            self.save_state(char["id"])

    def clear_override(self, cid=None):
        with self.lock:
            char = self.char(cid)
            self.state(char["id"])["override"] = None
            self.save_state(char["id"])

    def album(self, cid=None, key=None):
        """アルバム: シチュエーション (= 合成後のプロンプト) ごとのまとまり. key を指定すればその中の画像."""
        char = self.char(cid)
        groups = {}
        for e in self.log(char["id"]):
            for im in e.get("images") or []:
                if not os.path.exists(store.dpath("images", *im["path"].split("/"))):
                    continue
                k = self.prompt_key(im.get("pos", ""), im.get("neg", ""))
                if key and k != key:
                    continue
                g = groups.setdefault(k, {"key": k, "items": []})
                g["items"].append({"path": im["path"], "seed": im.get("seed"), "t": im.get("t") or e["t"], "pos": im.get("pos", ""),
                                   "neg": im.get("neg", ""), "entry": {k2: e.get(k2) for k2 in ("id", "t", "text", "action_name", "icon", "scene")}})
        if key:
            g = groups.get(key) or {"key": key, "items": []}
            g["items"].sort(key=lambda x: -x["t"])
            return g
        out = []
        for g in groups.values():
            last = max(g["items"], key=lambda x: x["t"])
            labels = {}
            for it in g["items"]:
                lb = "%s%s・%s" % (it["entry"].get("icon") or "", it["entry"].get("action_name") or "", it["entry"].get("scene") or "")
                labels[lb] = labels.get(lb, 0) + 1
            out.append({"key": g["key"], "count": len(g["items"]), "t": last["t"], "cover": last["path"],
                        "label": max(labels, key=labels.get), "pos": last["pos"]})
        out.sort(key=lambda x: -x["t"])
        return {"groups": out}

    def delete_image(self, path):
        """気に入らない画像を消す: ファイル・索引・全キャラのログから取り除く."""
        with self.lock:
            full = store.dpath("images", *[p for p in path.split("/") if p and p != ".."])
            if not full.startswith(store.dpath("images")) or not path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                raise ValueError("消せない画像です")
            if os.path.exists(full):
                os.remove(full)
            for k in list(self.img_index):
                self.img_index[k] = [im for im in self.img_index[k] if im["path"] != path]
                if not self.img_index[k]:
                    del self.img_index[k]
            store.save(store.dpath("images", "index.json"), self.img_index)
            # 画像は全ワールド共通なので, 他のワールドのログからも外す
            for f in glob.glob(store.dpath("worlds", "*", "log", "*.json")):
                cid = os.path.splitext(os.path.basename(f))[0]
                here = os.path.normcase(os.path.dirname(f)) == os.path.normcase(store.wpath("log"))
                log = self.log(cid) if here else store.load(f, [])
                changed = False
                for e in log:
                    if any(im["path"] == path for im in e.get("images") or []):
                        e["images"] = [im for im in e["images"] if im["path"] != path]
                        changed = True
                    if e.get("image") == path:
                        e["image"] = e["images"][-1]["path"] if e.get("images") else None
                        changed = True
                if changed:
                    self.save_log(cid) if here else store.save(f, log)
            return {"ok": True}

    def log_page(self, cid=None, offset=0, limit=60, images_only=False):
        char = self.char(cid)
        items = self.log(char["id"])
        if images_only:
            items = [e for e in items if e.get("images")]
        items = list(reversed(items))
        return {"total": len(items), "items": items[offset:offset + limit]}
