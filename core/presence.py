"""あなたの在席状態と, キャラからの働きかけ.

在席状態 (data/player.json の presence):
- here  : 画面を開いていて, 最近なにか操作した (そばで構っている)
- idle  : 画面は開いているが, しばらく何もしていない (そばにはいる)
- busy  : 「作業するね」と告げて, 家で作業中
- out / work / sleep / left : 出かけた / 仕事に行った / 寝た / 「またね」とそばを離れた (告げてから)
- gone  : 何も言わずに画面を閉じた (心拍が途絶えた)

画面は 30 秒ごとに /api/state を呼ぶ (心拍). 途絶えて gone_minutes 経つと gone とみなす.

働きかけ (data/approaches.json): あなたがそばにいる (here / idle / busy) ときに, キャラの状態しだいで
キャラのほうから話しかけてくる. 「応じる」「あとで」と答えるか, 放っておくと approach_wait_minutes で
「返事がなかった」になり, キャラの状態 (寂しさなど) に応じてパラメータが動く.
"""
import math
import random
import time
from datetime import datetime

from . import cond

DECLARED = ("busy", "out", "work", "sleep", "left")
AWAY_MODES = ("out", "work", "sleep", "left")
MODE_LABEL = {"here": "そばにいる", "idle": "そばでのんびり", "busy": "作業中", "out": "外出中", "work": "仕事中",
              "sleep": "就寝中", "left": "離れている", "gone": "いない"}


class Presence:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 設定
    def cfg(self):
        return self.app.world.get("presence") or {}

    def _gone_sec(self):
        return float(self.cfg().get("gone_minutes", 5)) * 60

    def _idle_sec(self):
        return float(self.cfg().get("idle_minutes", 10)) * 60

    def rec(self):
        ps = self.app.life.player_state()
        p = ps.setdefault("presence", {})
        p.setdefault("mode", "none")
        return p

    def save(self):
        self.app.life.save_player()

    # ------------------------------------------------------------------ 心拍・状態
    def beat(self, now=None, idle_sec=None):
        """画面からの心拍. 途絶えていた (= 黙って閉じていた) なら, そのことを覚えておく."""
        now = now or time.time()
        p = self.rec()
        prev = p.get("beat", 0)
        if prev and now - prev > self._gone_sec() and p["mode"] == "none":
            p["last_left"] = {"t": prev, "said": False, "mode": "gone", "back": now, "h": round((now - prev) / 3600, 2)}
        p["beat"] = now
        if idle_sec is not None:
            p["input"] = now - float(idle_sec)
        self.save()

    def touch(self, now=None):
        """あなたが何か操作した."""
        p = self.rec()
        p["input"] = now or time.time()

    def at(self, t):
        """時刻 t のあなたの在席状態 (過ぎた時間のまとめ計算にも使う)."""
        p = self.rec()
        m = p["mode"] if t >= p.get("since", 0) else "none"
        if m in AWAY_MODES:
            return m
        if t > p.get("beat", 0) + self._gone_sec():
            return "gone"
        if m == "busy":
            return "busy"
        return "idle" if t - p.get("input", 0) > self._idle_sec() else "here"

    def ctx(self, t):
        p = self.rec()
        ll = p.get("last_left") or {}
        recent = bool(ll) and t - ll.get("back", 0) < 900       # 戻ってきて 15 分は「どう離れていたか」を条件で使える
        return {"presence": self.at(t),
                "said": bool(ll.get("said")) if recent else True,
                "left_mode": ll.get("mode", "none") if recent else "none",
                "left_h": ll.get("h", 0) if recent else 0}

    def declare(self, mode, now=None):
        now = now or time.time()
        p = self.rec()
        p["mode"], p["since"] = mode, now
        p["input"] = now
        self.save()

    def back(self, now=None):
        """告げて離れていたところから戻る. (離れていた様子) を返す. 離れていなければ None."""
        now = now or time.time()
        p = self.rec()
        if p["mode"] == "none":
            return None
        ll = {"t": p.get("since", now), "said": True, "mode": p["mode"], "back": now,
              "h": round((now - p.get("since", now)) / 3600, 2)}
        p["last_left"] = ll
        p["mode"] = "none"
        p["input"] = p["beat"] = now
        self.save()
        return ll

    def effects(self, t):
        """在席状態による, キャラのパラメータ変化 (1時間あたり)."""
        return (self.cfg().get("effects") or {}).get(self.at(t)) or {}

    def view(self, now):
        p = self.rec()
        m = self.at(now)
        out = {"mode": p["mode"], "state": m, "label": MODE_LABEL.get(m, m), "since": p.get("since")}
        if p["mode"] == "work":
            pay, h = self.app.life.work_pay((now - p.get("since", now)) / 3600)
            out["work"] = {"hours": round(h, 2), "pay": pay}
        return out

    # ------------------------------------------------------------------ 働きかけ
    def find(self, aid):
        return next((x for x in self.app.approaches if x.get("id") == aid), None)

    def live(self, char, st, now):
        """画面を開いている間 (state_view のたび) に呼ぶ. 期限切れの処理と, 新しい働きかけ. 作った記録を返す."""
        ap = st.get("approach")
        if ap and now >= ap.get("until", 0):
            return self._expire(char, st, now)
        last = st.get("ap_check") or now
        st["ap_check"] = now
        if ap or now < st.get("ap_quiet_until", 0):
            return None
        dt_h = min(max(now - last, 0), 600) / 3600.0
        if not dt_h:
            return None
        pres = self.at(now)
        if pres not in ("here", "idle", "busy") or st.get("game"):
            return None
        d = datetime.fromtimestamp(now)
        scene = self.app.scene_at(char, st, d)
        ctx = self.app.context(char, st, d, scene)
        if not ctx["free"]:
            return None
        rate = float(self.cfg().get("approach_rate_per_hour", 0.8)) * self.eagerness(ctx) \
            * float(self.app.traits(char).get("approach", 1))
        if random.random() >= 1 - math.exp(-rate * dt_h):
            return None
        return self.fire(char, st, now, ctx)

    def eagerness(self, ctx):
        """キャラが自分から話しかけたくなる度合い. 寂しさ・退屈・好感度しだい.
        作業中と告げていれば遠慮する (ただし, とても寂しければ来る). いま構っている最中なら来にくい."""
        f = 0.3 + ctx.get("loneliness", 30) / 100.0 + ctx.get("boredom", 30) / 150.0 + (ctx.get("affection", 50) - 50) / 200.0
        if ctx.get("presence") == "busy":
            f *= 0.7 if ctx.get("loneliness", 0) >= 75 else 0.25
        elif ctx.get("presence") == "here" and ctx.get("absent", 1) < 5 / 60.0:
            f *= 0.3
        return max(0.05, min(2.0, f))

    def fire(self, char, st, now, ctx, force=None):
        cands = []
        for a in self.app.approaches:
            if force and a["id"] != force:
                continue
            if not force:
                if now - (st.get("ap_last") or {}).get(a["id"], 0) < float(a.get("cooldown_h", 3)) * 3600:
                    continue
                if not cond.check(a.get("when", ""), ctx):
                    continue
            cands.append(a)
        if not cands:
            return None
        a = random.choices(cands, [float(x.get("weight", 1)) for x in cands])[0]
        st.setdefault("ap_last", {})[a["id"]] = now
        wait = float(a.get("wait_minutes", self.cfg().get("approach_wait_minutes", 15))) * 60
        st["approach"] = {"id": a["id"], "t": now, "until": now + wait, "presence": ctx.get("presence")}
        e = self._entry(char, st, now, a, "call", a.get("text", ""), {}, a, gen=a.get("generate", True))
        st["approach"]["entry"] = e["id"]
        return e

    def _entry(self, char, st, now, a, ev, text, deltas, prompt_src, gen=True):
        """働きかけの記録を作る (セリフは性格プリセットの ap.<id>.<場面> があればそちら)."""
        app = self.app
        d = datetime.fromtimestamp(now)
        text = app.persona_text(char, "ap.%s.%s" % (a["id"], ev)) or text
        scene = app.scene_at(char, st, d)
        text = app.format_text(text, char, scene, d)
        act = {"id": "_ap_" + a["id"], "name": a.get("label", a["id"]), "icon": a.get("icon", "💬"),
               "pos": (prompt_src or {}).get("pos", ""), "neg": (prompt_src or {}).get("neg", "")}
        pos, neg, parts = app.build_prompt(char, st, d, act if prompt_src else None)
        e = app._new_entry(char["id"], now, act, text, deltas, scene, d, pos, neg, parts)
        e["approach"] = a["id"]
        if gen and prompt_src and app.settings.get("auto_generate"):
            e["job"] = app._present_image(char["id"], e)
        st["last_auto"] = {"id": e["id"], "t": now}
        app.save_log(char["id"])
        return e

    def _expire(self, char, st, now):
        """返事がないまま時間切れ. 作業中・不在なら軽く, 寂しいときほど重く受け止める."""
        ap = st.pop("approach")
        a = self.find(ap["id"]) or {"id": ap["id"]}
        ig = a.get("ignore") or {}
        pres = self.at(now)
        lon = st["params"].get("loneliness", 50)
        mult = (0.4 if ap.get("presence") == "busy" or pres == "busy" else 0.6 if pres in ("gone",) + AWAY_MODES else 1.0)
        mult *= 0.5 + lon / 100.0
        eff = {k: float(v) * mult for k, v in (ig.get("effects") or {"mood": -3, "loneliness": 5}).items()}
        deltas = self.app.apply_effects(st, self.app.trait_effects(char, eff))
        busy = ap.get("presence") == "busy"
        text = (ig.get("busy_text") if busy else None) or ig.get("text") or "（返事がないので、{name}はそっと離れていった）"
        st["ap_quiet_until"] = now + float(self.cfg().get("approach_quiet_minutes", 20)) * 60
        call = self.app.pronouns(char)[2]
        if deltas.get("mood", 0) <= -2 and (lon >= 75 or (lon >= 50 and not busy)):
            tell = "{call}が作業に夢中で、構ってもらえなかった" if busy else "{call}に話しかけたのに、返事がなかった"
            self.app.life.add_reason(st, "player", "bad", tell.replace("{call}", call), now, told=False,
                                     delta=deltas.get("mood", 0), action="_ap_" + a["id"])
        e = self._entry(char, st, now, a, "busy" if busy and ig.get("busy_text") else "ignore", text, deltas, None, gen=False)
        self.app.save_state(char["id"])
        return e

    def answer(self, char, st, ans, now=None, use_action=True):
        """働きかけに答える. ans = accept / later. (記録, 代わりに実行するコマンド id) を返す."""
        now = now or time.time()
        ap = st.get("approach")
        if not ap:
            raise ValueError("いまは話しかけられていません")
        a = self.find(ap["id"]) or {"id": ap["id"]}
        out = a.get(ans) or {}
        st["approach"] = None
        self.touch(now)
        st["last_interaction"] = now
        if ans == "later":
            # しばらくしたら, また同じことで来るかもしれない
            st.setdefault("ap_last", {})[a["id"]] = now - float(a.get("cooldown_h", 3)) * 3600 + 30 * 60
            st["ap_quiet_until"] = now + 30 * 60
        else:
            st["ap_quiet_until"] = now + float(self.cfg().get("approach_quiet_minutes", 20)) * 60
        if ans == "accept" and out.get("action") and use_action:
            return None, out["action"]
        mult = self.app.life.skill_mult(out["skill"]) if out.get("skill") else 1.0
        eff = {k: (float(v) * mult if float(v) * (1 if not (self.app.param_def(k) or {}).get("invert") else -1) > 0 else float(v))
               for k, v in (out.get("effects") or {}).items()}
        deltas = self.app.apply_effects(st, self.app.trait_effects(char, eff))
        if out.get("skill"):
            self.app.life.train(out["skill"], 1.0)
        if out.get("reason_good") and deltas.get("mood", 0) > 0:
            self.app.life.add_reason(st, "player", "good", out["reason_good"].replace("{call}", self.app.pronouns(char)[2]),
                                     now, told=True, delta=deltas.get("mood", 0), action="_ap_" + a["id"])
        e = self._entry(char, st, now, a, ans, out.get("text") or "", deltas, out if (out.get("pos") or out.get("neg")) else None,
                        gen=bool(out.get("pos") or out.get("neg")))
        self.app.save_state(char["id"])
        return e, None

    def drop(self, st):
        """あなたが別のことで構ったら, 待っていた働きかけはそれで済んだことにする."""
        if st.get("approach"):
            st["approach"] = None
            st["ap_quiet_until"] = time.time() + float(self.cfg().get("approach_quiet_minutes", 20)) * 60

    def pending_view(self, char, st):
        ap = st.get("approach")
        if not ap:
            return None
        a = self.find(ap["id"]) or {}
        return {"id": ap["id"], "entry": ap.get("entry"), "until": ap["until"], "label": a.get("label", ""),
                "icon": a.get("icon", "💬"),
                "accept": (a.get("accept") or {}).get("label") or "うん", "later": (a.get("later") or {}).get("label") or "あとでね"}

