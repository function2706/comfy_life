"""対面の会話 (A23 段 4): 会って「話したい」(talk) が弾んだ / ふつうだったとき, そのまま話が続く. 電話の対話 (core/phonetalk.py) の
切れ目・返し方・待つ秒・判定・ノリ・話していたい長さ (span) をそのまま使う. 記録は presence.rec()["face"] (電話の call とは別).

- 電話と違う所: 「もしもし？」は「ねえ、聞いてる？」, 黙ったのは「上の空」(機嫌の理由 _face_silent. 謝れる心当たり face_silent).
  寝落ちは, うたた寝 (近い仲で, 外でないとき): そっとしておく / 何か掛けてあげる (家・相手の家) / 起こす.
  そっとしておくと 15〜40 分あとに起きて一言 (st["face_doze"]. 一緒にいなければ言わない).
  ながら・誰かいるの？・相手の側の気配・頼みごと・用事の時刻 (lim) は無い (その場にいるので).
- 終わり方: 相手から (ノリ・span・眠い) / 「話を切り上げる」/ ほかのことを始めた (interrupt. 相手の話の途中なら少し響く) /
  電話をかける・出る (話の途中で電話. 響く) / 一緒にいなくなった. 終わったら相手のログに要約と最後のひとこと.
- 絵: 切れ目ごとに「様子」(表情 LOOK + 服装・場面・状態のプロンプトの部品) を比べ, 違うときだけ絵の記録 (action _face) を作る
  (engine._present_image: 使い回しの索引・生成中の使い回しが効く). この会話の生成が終わっていなければ積まない (前の絵のまま).
  電話は声だけなので, 通話では絵を作らない (core/phonetalk.py は作らない).
"""
import random
import time
import uuid
from datetime import datetime

from . import nori as nori_mod
from .phonetalk import PhoneTalk, RETURNS, HOW, EFFECT, STANCE_RETURNS

FACE_RETURNS = [(k, "話を切り上げる" if k == "bye" else l, i) for k, l, i in RETURNS]
ASLEEP_RETURNS = [("keep", "そっとしておく", "🤫"), ("cover", "何か掛けてあげる", "🧣"), ("wake", "起こす", "👋")]
COVER_MODES = ("home", "guest", "visit")
DOZE_WAKE = (15 * 60, 40 * 60)
# 対面だけのセリフ (性格プリセットの face.<場面> があればそちら). ここに無いものは電話のセリフ (phone.<場面>) を使う
LINES = {
    "face.topic_plain": "今日は、特に何もない一日でした。……こういう日もいいですよね。",
    "face.lull": ["……ふふ。こうして話してると、なんだか落ち着きます。", "……なんだか、話が尽きないですね。"],
    "face.sleepy": "ん……ごめんなさい、なんだか眠くなってきて……。",
    "face.hello": "……ねえ、{call}。聞いてます？",
    "face.silent_cut": "……もういいです。聞いてないなら。",
    "face.silent_awkward": "あ、すみません。なんだか一人で話しちゃって。",
    "face.end_sleepy": "すみません、ちょっと眠くて……。少し休んでもいいですか？",
    "face.end_cold": "……まあ、そんな感じです。",
    "face.end_enough": "ふふ、たくさん話しちゃいましたね。楽しかったです。",
    "face.bye_ok": "はい。また話しましょうね。",
    "face.bye_early": "あ……はい。そうですね。",
    "face.doze_glad": "……ん、寝ちゃってました？ ……そばにいてくれたんですね。",
    "face.doze_shy": "あっ、寝ちゃってた……。寝顔、見てませんよね？",
    "face.doze_awkward": "……すみません、話の途中で寝ちゃって。",
    "face.woke": "ん……あ、ごめんなさい。寝ちゃってました。",
}
SCENE_LABEL = {
    "face.topic_plain": "対面の会話 / 話を振る: 特に何もなかった",
    "face.lull": "対面の会話 / 話がひと段落した",
    "face.sleepy": "対面の会話 / 眠くなってきた (うたた寝しそう)",
    "face.hello": "対面の会話 / あなたが上の空: ねえ、聞いてる？",
    "face.silent_cut": "対面の会話 / 上の空のまま: 話をやめる (近い仲. 不満)",
    "face.silent_awkward": "対面の会話 / 上の空のまま: 話をやめる (浅い仲. 気まずそうに)",
    "face.end_sleepy": "対面の会話 / 眠くて話を終える",
    "face.end_cold": "対面の会話 / 乗らなくて話を終える (素っ気なく)",
    "face.end_enough": "対面の会話 / 十分話して, 満足して話を終える",
    "face.bye_ok": "対面の会話 / あなたが話を切り上げた (応じる)",
    "face.bye_early": "対面の会話 / あなたが話を切り上げた (まだ話したかった)",
    "face.doze_glad": "対面の会話のあと / うたた寝から起きた: そっとしておいてくれた (うれしい)",
    "face.doze_shy": "対面の会話のあと / うたた寝から起きた: 寝顔を見られたかも (照れる)",
    "face.doze_awkward": "対面の会話のあと / うたた寝から起きた: 話の途中で寝たのを謝る",
    "face.woke": "対面の会話 / うたた寝しかけたところを起こされた",
}
NARRATION = {"asleep": "（うとうとして、そのまま眠ってしまった）", "keep": "（起こさないように、そっとしておいた）",
             "cover": "（起こさないように、何か掛けてあげた）", "wake": "（肩を軽くたたいて、起こした）"}
# 表情・姿勢 (絵の「行動」の部品). start は「話したい」の絵そのもの (talk / happy と同じ様子とみなす)
LOOK = {"talk": "talking, looking at viewer, open mouth", "happy": "smile, talking, looking at viewer",
        "sulk": "pout, looking away", "quiet": "closed mouth, looking down", "puzzled": "head tilt, looking at viewer, closed mouth",
        "sleepy": "sleepy, half-closed eyes, drowsy", "asleep": "sleeping, closed eyes"}
START_SAME = ("start", "talk", "happy")
SIG_SRC = ("服装", "場面", "状態")


class FaceTalk(PhoneTalk):
    KEY = "face"

    # ------------------------------------------------------------------ 道具
    def line(self, char, key, **kw):
        k = key.replace("phone.", "face.", 1) if key.startswith("phone.") else key
        if k == "face.hello_asleep":
            k = "face.hello"
        if k in LINES:
            app = self.app
            t = app.persona_text(char, k) or LINES[k]
            if isinstance(t, list):
                t = random.choice(t)
            fp, _, call = app.pronouns(char)
            t = t.replace("{fp}", fp).replace("{call}", call).replace("{name}", char.get("name", ""))
            for a, v in kw.items():
                t = t.replace("{%s}" % a, v)
            return t
        return PhoneTalk.line(self, char, key, **kw)

    def doing_now(self, now):
        return None                                   # ながらは無い (その場にいる)

    def _late_guess(self, char, st, b):
        return False                                  # 顔が見えているので「寝ちゃった？」とは思わない

    def _doze_ok(self, char, st):
        return self.close_rel(char, st) and not self.app.outside_with(char["id"])

    def _company(self, char, st, c, now):
        return None

    def _hush_bg(self, char, st, c, now):
        return None

    def _can_ask_bg(self, c):
        return False

    # ------------------------------------------------------------------ 始まる
    def begin(self, char, st, said, entry, now):
        """「話したい」の反応 (said) が済んだところから. entry はその絵の記録 (様子 start)."""
        app = self.app
        if nori_mod.level(st, now) is None:
            nori_mod.start(app, char, st, now, why="話したい")
        lv = nori_mod.level(st, now) or 0.3
        c = {"cid": char["id"], "name": char.get("name", ""), "t": now, "by": "me", "turns": 0, "score": 0.0,
             "span": round(self.span_min(char, st, lv), 1), "lim": None, "cut": None, "mine_cut": False,
             "doing": None, "doze": 0, "log": [], "look": "start", "sig": self._sig(char, st, now),
             "entry": (entry or {}).get("id"), "job": (entry or {}).get("job")}
        text = (said or "").split(chr(10))[0].strip()
        if text.startswith("「") and text.endswith("」"):
            text = text[1:-1]
        app.presence.rec()[self.KEY] = c
        self._new_beat(char, st, c, "reply", None, text or "……うん。", now)
        app.presence.save()
        app.trace.add("talk", "対面の会話が始まった", char["id"], now, span=c["span"])
        return c

    # ------------------------------------------------------------------ 様子と絵
    def _sig(self, char, st, t):
        """服装・場面・状態のプロンプトの部品と照れの段 (表情は別に LOOK で)."""
        app = self.app
        _, _, parts = app.build_prompt(char, st, datetime.fromtimestamp(t), {"name": "", "pos": "", "neg": ""})
        sh = float(st["params"].get("shyness", 0))
        blush = 0 if sh < app.BLUSH_MIN else 1 if sh < app.BLUSH_MID else 2 if sh < app.BLUSH_FULL else 3
        return "|".join("%s=%s/%s" % (p["src"], p["pos"], p["neg"]) for p in parts if p["src"].startswith(SIG_SRC)) + "|blush=%d" % blush

    @staticmethod
    def same_look(a, b):
        if a == b:
            return True
        return "start" in (a, b) and a in START_SAME and b in START_SAME

    def look_for(self, c, kind):
        """切れ目の種類と直前の返しの結果から, 表情."""
        if kind in ("quiet", "sleepy", "asleep"):
            return kind
        if kind == "reply":
            return c.get("look") or "start"
        rs = c.get("res") or []
        last = rs[-1] if rs else None
        return "happy" if last == "good" else "sulk" if last == "bad" else "talk"

    def _job_busy(self, c):
        j = self.app.jobs.get(c.get("job") or "")
        return bool(j) and j.get("status") in ("queued", "running")

    def set_look(self, char, st, c, look, text, t):
        """様子が前と違えば絵の記録を作る. 作った記録 (無ければ None). 生成中なら作らず, 次に回す."""
        app = self.app
        sig = self._sig(char, st, t)
        if self.same_look(c.get("look"), look) and sig == c.get("sig"):
            return None
        if not app.settings.get("auto_generate"):
            c["look"], c["sig"] = look, sig
            return None
        if self._job_busy(c):
            app.trace.add("talk", "対面の会話: 様子が変わったが, 生成中なので前の絵のまま", char["id"], t, look=look)
            return None
        dt = datetime.fromtimestamp(t)
        act = {"id": "_face", "name": "話している", "icon": "💬", "pos": LOOK.get(look, LOOK["talk"]), "neg": ""}
        pos, neg, parts = app.build_prompt(char, st, dt, act)
        scene = app.scene_at(char, st, dt)
        e = app._new_entry(char["id"], t, act, text, {}, scene, dt, pos, neg, parts)
        e["face"] = True
        job = app._present_image(char["id"], e)
        app.save_log(char["id"])
        c.update(look=look, sig=sig, entry=e["id"], job=job)
        c["pics"] = c.get("pics", 0) + 1
        app.trace.add("talk", "対面の会話: 様子が変わった", char["id"], t, look=look, job=job, reused=bool(e.get("reused")))
        return e

    def _new_beat(self, char, st, c, kind, key, text, t):
        if kind == "asleep":
            text = NARRATION["asleep"]                # 電話の「寝息だけが聞こえる」ではなく, 目の前で眠った
        PhoneTalk._new_beat(self, char, st, c, kind, key, text, t)
        self.set_look(char, st, c, self.look_for(c, kind), text, t)

    # ------------------------------------------------------------------ 進める
    def tick(self, now=None):
        now = now or time.time()
        app = self.app
        c = self.rec()
        if not c:
            return None
        if c.get("cid") in app.chars and not app.bonds.together(c["cid"]):
            return self._finish(app.char(c["cid"]), app.state(c["cid"]), c, now, "you", "apart")
        stage0 = (c.get("beat") or {}).get("stage", 0)
        out = PhoneTalk.tick(self, now)
        if out is None:
            c = self.rec()
            b = (c or {}).get("beat") or {}
            if c and b.get("stage") == 1 and not stage0:
                self.set_look(app.char(c["cid"]), app.state(c["cid"]), c, "puzzled", b.get("hello") or "", b.get("t", now))
                app.presence.save()
        return out

    # ------------------------------------------------------------------ 返す
    def reply(self, kind, now=None):
        now = now or time.time()
        app = self.app
        ended = self.tick(now)
        if ended:
            return {"ended": ended}
        c = self.rec()
        if not c or not c.get("beat"):
            raise ValueError("いまは返すところではありません（相手が話すのを待っています）" if c else "話している途中ではありません")
        b = c["beat"]
        char, st = app.char(c["cid"]), app.state(c["cid"])
        if b["kind"] == "asleep":
            app.presence.rec()["beat"] = app.presence.rec()["input"] = now
            if kind not in [k for k, _, _ in self.asleep_returns(char)]:
                raise ValueError("眠っている（そっとしておく・起こす から）")
            return {"ended": self._finish(char, st, c, now, "you", kind)}
        if kind not in [k for k, _, _ in FACE_RETURNS + STANCE_RETURNS]:
            raise ValueError("返し方を選んでください")
        out = PhoneTalk.reply(self, kind, now)
        c = self.rec()
        if c and "ended" not in out:
            rs = c.get("res") or []
            if rs and rs[-1] != "neutral":           # 返しが効いた / 外した: 表情が変わる
                lk = self.look_for(c, "topic")
                said = [x["text"] for x in c.get("log") or [] if x["who"] == "her"]
                self.set_look(char, st, c, lk, said[-1] if said else "", now)
                app.presence.save()
            out = {"face": self.view(now)}
        return out

    def asleep_returns(self, char):
        cover = self.app.bonds.mode(char["id"]) in COVER_MODES and not self.app.outside_with(char["id"])
        return [r for r in ASLEEP_RETURNS if r[0] != "cover" or cover]

    def end(self, now=None):
        """「話を切り上げる」(切れ目でなくても). 眠っているなら選んでもらう."""
        now = now or time.time()
        ended = self.tick(now)
        if ended:
            return ended
        c = self.rec()
        if not c:
            raise ValueError("話している途中ではありません")
        b = c.get("beat") or {}
        if b.get("kind") == "asleep":
            raise ValueError("眠っている（そっとしておく・起こす から）")
        if b:
            r = self.reply("bye", now)
            return r.get("ended")
        app = self.app
        return self._finish(app.char(c["cid"]), app.state(c["cid"]), c, now, "you", "bye")

    def interrupt(self, now, why="other"):
        """ほかのことを始めた (other) / 電話をかける・出る (phone): 話は終わる. 返事を待っている途中なら, そのぶん響く."""
        c = self.rec()
        if not c:
            return None
        ended = self.tick(now)
        if ended:
            return ended
        c = self.rec()
        if not c:
            return None
        app = self.app
        return self._finish(app.char(c["cid"]), app.state(c["cid"]), c, now, "you", why)

    # ------------------------------------------------------------------ 終わる
    def _finish(self, char, st, c, t, who, why, res=None):
        app = self.app
        cid = char["id"]
        mins = max(1, int(round((t - c["t"]) / 60.0)))
        rs = c.get("res") or []
        avg = c.get("score", 0) / max(1, len(rs))
        lv = nori_mod.level(st, t) or 0.3
        how = HOW["good" if avg >= 8 and lv >= 0.5 else "ok" if avg >= -2 else "flat" if lv >= 0.3 else "cold"]
        b = c.get("beat") or {}
        name = char.get("name", "相手")
        last, note = None, ""
        if why == "silent":
            close = self.close_rel(char, st)
            last = self.line(char, "face.silent_cut" if close else "face.silent_awkward")
            self._silent(char, st, c, b, t, False)
            note = "あなたが上の空になり、%sは話をやめた" % name
        elif why == "sleepy":
            last = self.line(char, "face.end_sleepy")
            note = "%sが眠そうで、話を終えた" % name
        elif why == "cold":
            last = self.line(char, "face.end_cold")
            note = "話が続かず、%sが話を終えた" % name
        elif why == "enough":
            last = self.line(char, "face.end_enough")
            note = "十分話して、%sが話を終えた" % name
        elif why == "bye":
            early = b.get("mine") and (mins < 5 or c.get("turns", 0) < 3)
            last = self.line(char, "face.bye_early" if early or res == "bad" else "face.bye_ok")
            note = "あなたから話を切り上げた"
            if early:
                self._cut_short(char, st, c, t, 0.5, "話の途中で、{call}に切り上げられた")
        elif why in ("other", "phone"):
            note = "あなたがほかのことを始めて、話は終わった" if why == "other" else "話の途中で、あなたが電話を始めた"
            if b and (b.get("mine") or why == "phone"):
                self._cut_short(char, st, c, t, 1.0 if why == "phone" else 0.5,
                                "話の途中で、{call}が電話を始めた" if why == "phone" else "話している途中で、{call}がほかのことを始めた")
        elif why == "apart":
            note = "離れて、話は終わった"
        elif why in ("keep", "cover"):
            note = "%sがうたた寝してしまい、%s" % (name, "そっとしておいた" if why == "keep" else "何か掛けてあげた")
            self._log(c, "me", NARRATION[why], t)
            self._nap(char, st, t, why)
        elif why == "wake":
            self._log(c, "me", NARRATION["wake"], t)
            last = self.line(char, "face.woke")
            note = "%sがうたた寝しかけて、起こした" % name
        if last:
            self._log(c, "her", last, t)
        good = why not in ("silent", "cold", "apart") and c.get("turns", 0) >= 3 and avg >= -2
        if good and c.get("turns", 0) >= 6:
            app.regard.sign(char, st, "call_long", t, k=0.5)        # 長く付き合ってくれた
        app.presence.rec().pop(self.KEY, None)
        app.presence.save()
        text = "（%d分ほど話した。%s。%s）" % (mins, how, note)
        if last:
            text += "\n「%s」" % last
        if why != "apart" and cid in app.chars:
            e = app.note_entry(char, st, t, "_face_end", "話し終えた", "💬", text)
            e["face"] = True
            app.save_log(cid)
        app.trace.add("talk", "対面の会話が終わった", cid, t, who=who, why=why, mins=mins, turns=c.get("turns", 0), how=how,
                      avg=round(avg, 1), pics=c.get("pics", 0))
        app.save_state(cid)
        out = {"mins": mins, "name": char.get("name", ""), "who": who, "why": why, "how": how, "last": last, "note": note,
               "turns": c.get("turns", 0), "cid": cid, "id": uuid.uuid4().hex[:8], "face": True}
        self._last = dict(out, at=time.time())
        return out

    def _silent(self, char, st, c, b, t, asleep):
        """上の空: 機嫌が下がり, 謝れる心当たりになる. 相手が自分の話をしている最中ほど重い (目の前なので, 電話より少し重め)."""
        app = self.app
        w = (1.5 if b.get("mine") else 1.0) * 1.2
        w *= max(0.5, float(app.traits(char).get("absence", 1.0))) * (1 + 0.3 * max(0.0, app.attach.factor(char, st, "dependence")))
        if not self.close_rel(char, st):
            w *= 0.7
        w *= random.uniform(0.7, 1.3)
        d = round(min(12.0, 6.0 * w), 1)
        app.apply_effects(st, {"mood": -d, "affection": -0.3 * w}, t)
        app.life.add_reason(st, "player", "bad", "話している途中で{call}が上の空だった", t, told=False, delta=-d, action="_face_silent")
        app.regard.sign(char, st, "call_silent", t, k=min(1.5, 0.8 * w))

    def _cut_short(self, char, st, c, t, k, reason):
        app = self.app
        w = k * random.uniform(0.7, 1.3) * (1 + 0.3 * max(0.0, app.attach.factor(char, st, "dependence")))
        d = round(min(6.0, 3.0 * w), 1)
        app.apply_effects(st, {"mood": -d}, t)
        app.life.add_reason(st, "player", "bad", reason, t, told=False, delta=-d, action="_face_cut")

    def _nap(self, char, st, t, how):
        """うたた寝: 少しあとに起きて一言 (うれしい・照れる・気まずい. 性格と仲で. 掛けてあげたら, うれしい寄り)."""
        p = st["params"]
        r = random.random() + 0.3 * (p.get("affection", 50) - 60) / 40.0 + (0.2 if how == "cover" else 0)
        mood = "glad" if r > 0.65 else "shy" if r > 0.3 else "awkward"
        if float(self.app.traits(char).get("modesty", 0)) > 3 and mood == "glad":
            mood = "shy"
        st["face_doze"] = {"t": t, "mood": mood, "how": how, "due": t + random.uniform(*DOZE_WAKE)}

    def wake(self, char, st, now):
        """うたた寝から起きた: 一緒にいれば一言 (ログに). 一緒にいなければ言わずに終わり. 言ったら True."""
        dz = st.get("face_doze")
        if not dz or now < dz.get("due", 0):
            return False
        st.pop("face_doze", None)
        app = self.app
        app.apply_effects(st, {"sleepiness": -15, "energy": 8}, now)
        if not app.bonds.together(char["id"]):
            return False
        app.note_entry(char, st, min(now, dz["due"] + 60), "_face_doze", "うたた寝から起きた", "😴", "「%s」" % self.line(char, "face.doze_" + dz["mood"]))
        app.trace.add("talk", "うたた寝から起きた", char["id"], now, mood=dz["mood"], how=dz.get("how"))
        return True

    # ------------------------------------------------------------------ 画面
    def view(self, now=None):
        now = now or time.time()
        c = self.rec()
        if not c:
            return None
        b = c.get("beat")
        out = {"cid": c["cid"], "name": c.get("name", ""), "t": c["t"], "mins": int((now - c["t"]) // 60),
               "log": c.get("log", [])[-12:], "turns": c.get("turns", 0), "entry": c.get("entry"), "look": c.get("look")}
        if b:
            out["beat"] = {"id": b["id"] + ("h" if b.get("stage") else ""), "kind": b["kind"], "text": b.get("hello") if b.get("stage") else b["text"],
                           "left": None if b.get("due") is None else max(0, int(-(-(b["due"] - now) // 1))), "stage": b.get("stage", 0)}
            rs = self.asleep_returns(self.app.char(c["cid"])) if b["kind"] == "asleep" \
                else (STANCE_RETURNS if b.get("stance") else []) + FACE_RETURNS
            out["returns"] = [{"id": k, "label": l, "icon": i} for k, l, i in rs]
        else:
            out["talking"] = True
        return out
