"""電話の対話 (A23 段 1): 話している間, 何度も選んで返すことで電話が続く. 時計は実時間.

- 切れ目 (beat): 数分おき (ノリが高いほど短い間) に, 相手のひとことが来る (話を振る・聞いてくる・ひと段落・少し黙る・眠そう・
  何してるの？). あなたは返し方 (相づち・掘り下げる・自分の話・話を変える・そろそろ切る) から選ぶ. 合う・外すはノリに効き,
  ノリが下がりきる・相手が話していたい長さ (span) を過ぎる・相手の次の用事や寝る時刻 (lim) で, 相手から切り上げる.
  長く話して掘り下げるほど, 相手が今日あったこと・好き・苦手を口にして「知っていること」(known) に残る (好感度ではなく材料).
- 返事を待つのは「読む時間 + 数秒」. 過ぎると「もしもし？」, それでも返さないと相手から切る (黙った). 画面を閉じたら電話を置いたのと同じ.
  黙ったのは機嫌の理由 (謝れる心当たり) になる. 相手が自分の話をしている最中・あなたからかけたときほど重い.
  近い仲の夜更けは「寝ちゃった？」と受け取って軽いことも.
- 相手から切るときの謝り方は切る理由で分ける: 用事・時間 → 謝る (律儀さ・仲で揺らす) + 「またかけるね」(call_back. 段 2 の着信が使う) /
  眠い → 軽く / 機嫌・ノリ → 謝らない. 謝ったひとことはトークに残り, 「気にしないで」で返せる (core/react.py の sorry).
- 寝落ち: 近い仲で, 相手が眠い・寝る時刻になると, 返事が短くなり (sleepy) やがて寝息だけ (asleep). 切る / 小さくおやすみと言って切る /
  つないだまま を選べる. つないだままなら翌朝に反応 (call_doze).
- ながら電話: 手が空く一人のこと (家事・休む・歩き / 電車バスの移動) は通話中もできる (NAGARA). 生活音で「何してるの？」と聞かれる
  ことがあり, 返しの効き目が少し下がる (家事の出来も少し下がる: solo.result).
記録は presence.rec()["call"] (docs/REMAINING の A23 段 1 か CHANGES 1.7.0beta にデータの形).
"""
import math
import random
import time
import uuid
from datetime import datetime, timedelta

from . import msgreply
from . import nori as nori_mod

# 返し方: (id, 文言, 印)
RETURNS = [("aizuchi", "相づちを打つ", "🙂"), ("dig", "掘り下げる", "👂"), ("mine", "自分の話をする", "💬"),
           ("change", "話を変える", "🔀"), ("bye", "そろそろ切る", "👋")]
ASLEEP_RETURNS = [("hang", "そっと切る", "📵"), ("night", "小さく「おやすみ」と言って切る", "🌙"), ("keep", "つないだままにする", "📞")]
RETURN_LABEL = dict((k, l) for k, l, _ in RETURNS + ASLEEP_RETURNS)
SAID = {"aizuchi": "相づちを打った", "dig": "掘り下げて聞いた", "mine": "自分の話をした", "change": "話を変えた", "bye": "そろそろ切ろうと言った"}
CAT = {"aizuchi": "cheerful", "dig": "expand", "mine": "cheerful", "change": "curt", "bye": "curt"}     # 性格の好み (msgreply.TASTE) の読み替え
BASE = {"aizuchi": 4, "dig": 5, "mine": 4, "change": 0, "bye": 0}
# 切れ目の種類 × 返し方の合い方 (react.FIT と同じ目盛り)
FIT = {
    "reply": {"aizuchi": 6, "dig": 8, "mine": 0, "change": -6, "bye": -8},
    "topic": {"aizuchi": 5, "dig": 10, "mine": -8, "change": -12, "bye": -10},
    "ask": {"mine": 12, "aizuchi": -6, "dig": -6, "change": -6, "bye": -8},
    "lull": {"change": 8, "mine": 6, "dig": 2, "aizuchi": -2, "bye": 0},
    "quiet": {"change": 8, "mine": 8, "dig": 2, "aizuchi": -10, "bye": -2},
    "what": {"mine": 12, "aizuchi": -8, "dig": -10, "change": -4, "bye": -4},
    "sleepy": {"bye": 10, "aizuchi": 4, "dig": -10, "mine": -8, "change": -8},
}
NORI = {"good": 10, "neutral": -2, "bad": -15}
EFFECT = {"good": {"boredom": -3, "loneliness": -3, "mood": 1}, "neutral": {"boredom": -1, "loneliness": -1}, "bad": {"mood": -2}}
WAIT_MIN, WAIT_MAX = 5.0, 25.0          # 返事を待つ秒 (読む時間込み)
HELLO_WAIT = (6.0, 10.0)                # 「もしもし？」のあと待つ秒
GAP = (60.0, 210.0)                     # 切れ目の間 (秒. ノリが高いほど短い)
ASLEEP_KEEP = 30 * 60                   # 寝息のまま, これだけ何も選ばなければ「つないだまま」にしたことに
LOG_MAX = 40
NAGARA = ("chores", "rest", "out")      # 通話中もできる一人のこと (外出は歩き・電車・バスのとき. 運転・自転車はできない)
NAGARA_HOW = ("walk", "transit", "taxi")
NAGARA_LABEL = {"chores": "家事", "rest": "ひと休み", "out": "移動"}

# 共通のセリフ (性格プリセットの phone.<場面> があればそちら. 「電話する」コマンドの反応 call.<キー> とは別). 📞 は付けない (通話画面とトークで付ける)
LINES = {
    "phone.topic_news": "そういえば今日、{news}んです。",
    "phone.topic_plain": "今日は、特に何もない一日でした。……こういう日もいいですよね。",
    "phone.ask": ["{call}は、今日どうでした？", "{call}のほうは、最近どうですか？"],
    "phone.lull": ["……ふふ。こうして話してると、なんだか落ち着きます。", "……なんだか、話が尽きないですね。"],
    "phone.sleepy": "ん……ごめんなさい、ちょっと眠くなってきて……。",
    "phone.what": "……ん？ 何か音がしますけど、いま何してるんですか？",
    "phone.hello": "……もしもし？ 聞こえてます？",
    "phone.hello_asleep": "……{call}？ 寝ちゃいました？",
    "phone.silent_cut": "……もういいです。切りますね。",
    "phone.silent_awkward": "あ、あの……電波が悪いみたいなので、いったん切りますね。",
    "phone.silent_sleep": "……おやすみなさい。",
    "phone.end_limit": "あ、ごめんなさい、そろそろ行かないと。またかけますね。",
    "phone.end_limit_plain": "じゃあ、そろそろ時間なので。また。",
    "phone.end_sleepy": "すみません、もう眠くて……。おやすみなさい。",
    "phone.end_cold": "……じゃあ、そろそろ切りますね。",
    "phone.end_enough": "今日はたくさん話せて楽しかったです。じゃあ、また。",
    "phone.bye_ok": "はい。じゃあ、また話しましょうね。",
    "phone.bye_early": "あ……はい。じゃあ、また。",
    "phone.react_good": "ふふ、なんか楽しいです。",
    "phone.react_neutral": "……うん、うん。",
    "phone.react_bad": "……うーん。",
    "phone.morning_glad": "📱『昨日、寝ちゃってましたよね。……つないだままにしてくれてたんですか？ ちょっとうれしかったです』",
    "phone.morning_shy": "📱『昨日、電話の途中で寝ちゃって……。寝息とか聞こえてませんでした？ 恥ずかしい……』",
    "phone.morning_awkward": "📱『昨日は電話の途中で寝ちゃって、すみませんでした』",
}
SCENE_LABEL = {
    "phone.topic_news": "電話 / 話を振る: 今日あったこと ({news} に出来事. 「〜た」で終わる)",
    "phone.topic_plain": "電話 / 話を振る: 特に何もなかった",
    "phone.ask": "電話 / あなたのことを聞いてくる",
    "phone.lull": "電話 / 話がひと段落した",
    "phone.sleepy": "電話 / 眠くなってきた (寝落ちしそう)",
    "phone.what": "電話 / 生活音に気づいて「何してるの？」(ながら電話)",
    "phone.hello": "電話 / 返事が無い: もしもし？",
    "phone.hello_asleep": "電話 / 返事が無い: 夜更けで, 寝落ちしたと思う",
    "phone.silent_cut": "電話 / 返事が無いので切る (近い仲. 不満)",
    "phone.silent_awkward": "電話 / 返事が無いので切る (浅い仲. 気まずそうに)",
    "phone.silent_sleep": "電話 / 返事が無いので切る (寝落ちしたと思って, そっと)",
    "phone.end_limit": "電話 / 用事・時間で切り上げる (謝って, またかけると言う)",
    "phone.end_limit_plain": "電話 / 用事・時間で切り上げる (謝らない)",
    "phone.end_sleepy": "電話 / 眠くて切り上げる",
    "phone.end_cold": "電話 / 乗らなくて切り上げる (謝らない)",
    "phone.end_enough": "電話 / 十分話して, 満足して切り上げる",
    "phone.bye_ok": "電話 / あなたが「そろそろ」と言った (応じる)",
    "phone.bye_early": "電話 / あなたが「そろそろ」と言った (まだ話したかった)",
    "phone.react_good": "電話 / あなたの返しがよく効いた",
    "phone.react_neutral": "電話 / あなたの返しがふつう",
    "phone.react_bad": "電話 / あなたの返しがよくなかった",
    "phone.morning_glad": "電話の翌朝 / 寝落ちをつないだままにしてくれた (うれしい. 📱 で包む)",
    "phone.morning_shy": "電話の翌朝 / 寝落ちをつないだままにしてくれた (照れる. 📱 で包む)",
    "phone.morning_awkward": "電話の翌朝 / 寝落ちしたことを気まずく謝る (📱 で包む)",
}
NARRATION = {"quiet": "（……少しの間、黙っている）", "asleep": "（すう……すう……。寝息だけが聞こえる）",
             "night": "（小さく「おやすみ」と言って、電話を切った）", "hang": "（そっと電話を切った）",
             "keep": "（つないだまま、寝息を聞いていた）"}
HOW = {"good": "楽しそうだった", "ok": "落ち着いて話してくれた", "flat": "少し気まずそうだった", "cold": "素っ気なかった"}


def rng():
    return random


class PhoneTalk:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 道具
    def rec(self):
        return self.app.presence.rec().get("call")

    def line(self, char, key, **kw):
        app = self.app
        t = app.persona_text(char, key) or LINES[key]
        if isinstance(t, list):
            t = random.choice(t)
        fp, _, call = app.pronouns(char)
        t = t.replace("{fp}", fp).replace("{call}", call).replace("{name}", char.get("name", ""))
        for k, v in kw.items():
            t = t.replace("{%s}" % k, v)
        return t

    def close_rel(self, char, st):
        return self.app.bonds.stage(char["id"]) in ("visit", "live") or st["params"].get("affection", 0) >= 70

    def _log(self, c, who, text, t):
        lg = c.setdefault("log", [])
        lg.append({"who": who, "text": text, "t": t})
        del lg[:-LOG_MAX]

    def wait_secs(self, char, st, text, kind, now):
        """返事を待つ秒: 読む時間 (8 字/秒) + 数秒. 待たない性格・相手が話に熱を入れているほど縮む."""
        tr = self.app.traits(char)
        lv = nori_mod.level(st, now) or 0.4
        w = len(text or "") / 8.0 + random.uniform(4.0, 9.0)
        w *= 1.0 - 0.25 * (float(tr.get("approach", 1.0)) - 1.0)        # 話したがりほど, 間を待てない
        if kind == "topic" and lv > 0.6:
            w *= 0.85
        if self.close_rel(char, st):
            w *= 1.15                                                     # 近い仲は, 黙っていても少し待つ
        return max(WAIT_MIN, min(WAIT_MAX, w))

    def span_min(self, char, st, lv):
        """相手が話していたい分 (これを過ぎると切り上げに入りやすい). 決め打ちにしない."""
        tr = self.app.traits(char)
        m = (8 + 25 * lv + 12 * (float(tr.get("approach", 1.0)) - 1.0) + 8 * self.app.attach.factor(char, st, "dependence")) \
            * (1.3 if self.close_rel(char, st) else 1.0) * random.uniform(0.6, 1.5)
        return max(4.0, m)

    # ------------------------------------------------------------------ つながる
    def begin(self, char, st, said, good, now, by="me", sys_t=None):
        """電話がつながって最初の受け答え (said: 相手の返事の文) が済んだところから, 通話の記録を作る."""
        app = self.app
        lv0 = nori_mod.level(st, now)
        if lv0 is None:
            nori_mod.start(app, char, st, now, boost=8 if by == "her" else 0, why="電話がつながった")
        nori_mod.bump(app, st, now, 6 if good else -8, "電話の最初の受け答え", turn=False)
        lv = nori_mod.level(st, now) or 0.3
        lim, cut, mine_cut = self.limit(char, st, now)
        c = {"cid": char["id"], "name": char.get("name", ""), "t": now, "by": by, "sys_t": sys_t, "turns": 0, "score": 0.0,
             "span": round(self.span_min(char, st, lv), 1), "lim": lim, "cut": cut, "mine_cut": mine_cut,
             "doing": self.doing_now(now), "doze": 0, "log": []}
        text = (said or "").split(chr(10))[0].replace("📞", "").replace("📱", "").strip()
        if text.startswith("『") and text.endswith("』"):
            text = text[1:-1]
        self._new_beat(char, st, c, "reply", None, text or "……もしもし。", now)
        app.presence.rec()["call"] = c
        app.presence.save()
        return c

    def limit(self, char, st, now):
        """(切り上げる時刻 or None, 理由, あなたの都合か). engine._call_limit を長めに見て使う."""
        mins, cut = self.app._call_limit(char, st, now, 180)
        if not cut:
            return None, None, False
        mine = cut in ("約束がある", "予定の時刻が近い", "あなたが疲れていた")
        return now + mins * 60, cut, mine

    def doing_now(self, now):
        """いましている「ながら」のこと (無ければ None)."""
        app = self.app
        pr = app.presence.rec()
        tv = pr.get("travel")
        if tv and now < tv.get("arr", 0):
            return "out" if tv.get("how") in NAGARA_HOW else "drive"
        sl = pr.get("solo") or {}
        if pr.get("mode") in ("busy", "out") and sl.get("kind") in NAGARA:
            return sl["kind"]
        return None

    def nagara_why(self, kind=None, how=None):
        """通話中に始められない一人のことなら, その理由. 始められるなら None."""
        c = self.rec()
        if not c:
            return None
        if kind in NAGARA and (kind != "out" or how in NAGARA_HOW or how is None):
            return None
        if kind == "out" and how not in NAGARA_HOW:
            return "%sと電話で話している途中です（運転・自転車は、電話を切ってから）" % c.get("name", "")
        return self.app.call_block()

    def start_why(self, now):
        """電話をかけられない (手が離せない) 理由: 研鑽・読書・映画・内職の途中 / 運転中. かけられるなら None."""
        d = self.doing_now(now)
        if d == "drive":
            return "運転中です（電話は、着いてから）"
        pr = self.app.presence.rec()
        sl = pr.get("solo") or {}
        if pr.get("mode") == "busy" and sl.get("kind") in ("practice", "read", "movie"):
            from .solo import KINDS
            return "%sの途中です（電話は、終えてから）" % KINDS[sl["kind"]]["doing"].replace("中", "")
        return None

    # ------------------------------------------------------------------ 切れ目
    def _new_beat(self, char, st, c, kind, key, text, t):
        app = self.app
        mine = kind in ("topic",)
        due = None if kind == "asleep" else t + self.wait_secs(char, st, text, kind, t)
        c["beat"] = {"id": uuid.uuid4().hex[:8], "kind": kind, "key": key, "text": text, "t": t, "due": due, "stage": 0, "mine": mine}
        c.pop("next", None)
        self._log(c, "her", text, t)
        app.trace.add("call", "電話の切れ目", char["id"], t, kind=kind, key=key, wait=round((due or t) - t, 1))

    def _pick_beat(self, char, st, c, t):
        """次の切れ目の種類と文."""
        app = self.app
        p = st["params"]
        lv = nori_mod.level(st, t) or 0.3
        if c.get("doing") and not c.get("asked_doing") and random.random() < 0.3 * self._nosy(char):
            c["asked_doing"] = True
            return "what", "phone.what", self.line(char, "phone.what")
        w = {"topic": 1.0 + lv + 0.3 * c.get("deep", 0), "ask": 0.8 + 0.4 * (p.get("affection", 50) - 50) / 50.0,
             "lull": 0.4 + 0.02 * self._elapsed(c, t), "quiet": 0.5 * (1.2 - lv)}
        recent = c.get("recent") or []
        for k in w:                                       # 同じことを続けて言わない
            w[k] *= 0.25 ** recent[-2:].count(k)
        kind = random.choices(list(w), [max(0.05, v) for v in w.values()])[0]
        c["recent"] = (recent + [kind])[-3:]
        if kind == "topic":
            kind, key, text = self._topic(char, st, c, t)
            if key == "phone.topic_plain":
                if "phone.topic_plain" in (c.get("said") or []):         # 「特に何もない一日」は一度だけ
                    return "lull", "phone.lull", self.line(char, "phone.lull")
                c["said"] = (c.get("said") or []) + [key]
            return kind, key, text
        if kind == "quiet":
            return "quiet", None, NARRATION["quiet"]
        return kind, "phone." + kind, self.line(char, "phone." + kind)

    def _nosy(self, char):
        """生活音を気にする性格か (0.3〜1.5)."""
        return max(0.3, min(1.5, 0.8 + 0.4 * (float(self.app.traits(char).get("jealousy", 1.0)) - 1.0) * 2))

    def _topic(self, char, st, c, t):
        """相手が自分の話をする: 今日あったこと (話していない出来事) / 好き・苦手 (まだ知らないもの) / 特になし.
        口にしたことは「知っていること」に残る. 長く話して掘り下げるほど (deep), 中身のある話が出やすい."""
        app = self.app
        call = app.pronouns(char)[2]
        deep = c.get("deep", 0)
        ev = [r for r in st.get("reasons") or [] if r.get("kind") == "event" and not r.get("told") and t - r.get("t", 0) < 36 * 3600]
        if ev and random.random() < 0.45 + 0.15 * deep:
            r = max(ev, key=lambda x: x["t"])
            r["told"] = True
            app.bonds.remember(char, st, t)
            news = r["tell"].replace("{call}", call)
            return "topic", "phone.topic_news", self.line(char, "phone.topic_news", news=news)
        if random.random() < 0.25 + 0.2 * deep:
            from .topics import TAGS
            known = {(k.get("kind"), k.get("text")) for k in st.get("known") or []}
            cands = [(k, v) for k, v in app.topics.tastes(char, st).items()
                     if abs(v) >= 0.3 and k in TAGS and (("like" if v > 0 else "dislike"), TAGS[k]) not in known]
            if cands:
                k, v = random.choice(cands)
                kind = "like" if v > 0 else "dislike"
                app.bonds.learn(st, kind, TAGS[k], t)
                from .hima import REVEAL
                txt = (app.persona_text(char, "hima.reveal_" + kind) or REVEAL[kind]).replace("{genre}", TAGS[k]) \
                    .replace("{fp}", app.pronouns(char)[0])
                return "topic", "hima.reveal_" + kind, txt
        return "topic", "phone.topic_plain", self.line(char, "phone.topic_plain")

    def _elapsed(self, c, t):
        return (t - c["t"]) / 60.0

    def _gap(self, st, t):
        lv = nori_mod.level(st, t) or 0.3
        return (GAP[0] + (GAP[1] - GAP[0]) * (1 - lv)) * random.uniform(0.7, 1.3)

    def _sleepy(self, char, st, t):
        """寝落ちに向かうか: 眠気が高い / 寝る時刻を過ぎた (近い仲だけ. 浅い仲は眠いと言って切る)."""
        sc = self.app.scene_at(char, st, datetime.fromtimestamp(t))
        return st["params"].get("sleepiness", 0) >= 75 or bool(sc.get("asleep"))

    # ------------------------------------------------------------------ 進める (心拍・画面の問い合わせ)
    def tick(self, now=None):
        """通話を now まで進める (閉じていた間の分は, 時刻をさかのぼって). 終わったら終わりの結果を返す."""
        now = now or time.time()
        app = self.app
        c = self.rec()
        if not c:
            return None
        if "beat" not in c and "next" not in c:          # 以前の形 (決め打ちの until): その通話は終わったことに (遡及)
            app.presence.rec().pop("call", None)
            app.presence.save()
            return None
        cid = c["cid"]
        if cid not in app.chars:
            app.presence.rec().pop("call", None)
            app.presence.save()
            return None
        char, st = app.char(cid), app.state(cid)
        for _ in range(12):
            b = c.get("beat")
            if b:
                if b["kind"] == "asleep":
                    if now - b["t"] >= ASLEEP_KEEP:
                        return self._finish(char, st, c, b["t"] + ASLEEP_KEEP, "you", "keep")
                    return None
                if now < b["due"]:
                    return None
                if b["stage"] == 0:                       # もしもし？
                    late = self.close_rel(char, st) and (nori_mod.hour_at(b["due"]) >= 23 or nori_mod.hour_at(b["due"]) < 4) \
                        and random.random() < 0.6
                    key = "phone.hello_asleep" if late else "phone.hello"
                    text = self.line(char, key)
                    b.update(stage=1, t0=b["t"], t=b["due"], due=b["due"] + random.uniform(*HELLO_WAIT), asleep_guess=late,
                             hello=text)
                    self._log(c, "her", text, b["t"])
                    app.presence.save()
                    continue
                return self._finish(char, st, c, b["due"], "her", "silent")
            t = c.get("next", now)
            if now < t:
                return None
            c["doing"] = self.doing_now(now)              # ながら: いましていること (途中で家事を始めた・移動を終えた)
            sl = app.presence.rec().get("solo") or {}
            if c["doing"] == "chores" and sl.get("kind") == "chores":
                sl["phone"] = True                        # 家事の出来が少し下がる (solo.result)
            if c.get("lim") and t >= c["lim"]:
                return self._finish(char, st, c, c["lim"], "you" if c.get("mine_cut") else "her", "limit")
            if c.get("doze", 0) >= 1 or self._sleepy(char, st, t):
                if self.close_rel(char, st):
                    c["doze"] = c.get("doze", 0) + 1
                    if c["doze"] >= 2:
                        self._new_beat(char, st, c, "asleep", None, NARRATION["asleep"], t)
                    else:
                        self._new_beat(char, st, c, "sleepy", "phone.sleepy", self.line(char, "phone.sleepy"), t)
                    app.presence.save()
                    continue
                return self._finish(char, st, c, t, "her", "sleepy")
            if self._elapsed(c, t) > c.get("span", 20) and random.random() < 0.35:
                return self._finish(char, st, c, t, "her", "enough")
            kind, key, text = self._pick_beat(char, st, c, t)
            if text in [x["text"] for x in (c.get("log") or [])[-6:] if x["who"] == "her"]:
                kind, key, text = "quiet", None, NARRATION["quiet"]          # さっきと同じことは言わない
            self._new_beat(char, st, c, kind, key, text, t)
            app.save_state(cid)
            app.presence.save()
        return None

    # ------------------------------------------------------------------ 返す
    def judge(self, char, st, c, kind, now):
        p = st["params"]
        b = c["beat"]
        taste = msgreply.TASTE.get(char.get("persona_id") or "", {})
        lv = nori_mod.level(st, now)
        score = BASE[kind] + 1.3 * FIT.get(b["kind"], FIT["lull"]).get(kind, 0) + 0.5 * taste.get(CAT[kind], 0) \
            + 0.25 * (p.get("mood", 50) - 50) + 0.2 * (p.get("affection", 45) - 45) + 8 * (self.app.life.skill_mult("talk") - 1.0) \
            + (12 * (lv - 0.5) if lv is not None else 0) + random.uniform(-12, 12)
        if b.get("stage"):
            score -= 6                                    # もしもし？と言わせてから返した
        if c.get("doing"):
            score -= 4                                    # ながら: 生活音で, 気もそぞろに聞こえる
        if c.get("last") == kind and c.get("rep", 0) >= 1:
            score -= 5 * c["rep"]                         # 同じ返しばかり (相づちばかり など)
        res = "good" if score >= 10 else "neutral" if score >= -8 else "bad"
        if res == "good" and random.random() < 0.1:
            res = "neutral"
        return res, score

    def reply(self, kind, now=None):
        """いまの切れ目に返す. 通話の様子 (view) を返す. 終わったら {"ended": …}."""
        now = now or time.time()
        app = self.app
        ended = self.tick(now)
        if ended:
            return {"ended": ended}
        c = self.rec()
        if not c or not c.get("beat"):
            raise ValueError("いまは返すところではありません（相手が話すのを待っています）" if c else "電話で話している途中ではありません")
        b = c["beat"]
        char, st = app.char(c["cid"]), app.state(c["cid"])
        app.presence.rec()["beat"] = app.presence.rec()["input"] = now      # 画面の前にいる
        if b["kind"] == "asleep":
            if kind not in ("hang", "night", "keep"):
                raise ValueError("寝息だけが聞こえる（切る・おやすみと言って切る・つないだまま から）")
            return {"ended": self._finish(char, st, c, now, "you", kind)}
        if kind not in BASE:
            raise ValueError("返し方を選んでください")
        self._log(c, "me", "（%s）" % SAID[kind], now)
        res, score = self.judge(char, st, c, kind, now)
        c["rep"] = c.get("rep", 0) + 1 if c.get("last") == kind else 0
        c["last"] = kind
        c["turns"] = c.get("turns", 0) + 1
        c["score"] = round(c.get("score", 0) + score, 1)
        c.setdefault("res", []).append(res)
        eff = dict(EFFECT[res])
        if c.get("doing"):
            eff = {k: v * 0.8 for k, v in eff.items()}
        app.apply_effects(st, eff, now)
        app.trace.add("call", "電話で返した", char["id"], now, beat=b["kind"], kind=kind, res=res, score=round(score, 1),
                      turns=c["turns"], doing=c.get("doing"))
        if kind == "bye":
            return {"ended": self._finish(char, st, c, now, "you", "bye", res=res)}
        if kind == "dig" and res == "good":
            c["deep"] = c.get("deep", 0) + 1
        closing = nori_mod.bump(app, st, now, NORI[res] - nori_mod.TIRE * 0.6 - 0.05 * self._elapsed(c, now), "電話の返し: " + res)
        if res != "neutral" or random.random() < 0.5:
            self._log(c, "her", self.line(char, "phone.react_" + res), now + 0.5)
        if closing is not None and closing < nori_mod.CLOSE_BELOW and c["turns"] >= nori_mod.CLOSE_TURNS:
            return {"ended": self._finish(char, st, c, now + 1, "her", "cold")}
        c.pop("beat", None)
        c["next"] = now + self._gap(st, now)
        app.save_state(char["id"])
        app.presence.save()
        return {"call": self.view(now)}

    # ------------------------------------------------------------------ 終わる
    def hangup(self, now=None):
        """あなたから切る (返さずに, いきなり)."""
        now = now or time.time()
        ended = self.tick(now)
        if ended:
            return ended
        c = self.rec()
        if not c:
            raise ValueError("電話で話している途中ではありません")
        app = self.app
        char, st = app.char(c["cid"]), app.state(c["cid"])
        b = c.get("beat") or {}
        if b.get("kind") == "asleep":
            return self._finish(char, st, c, now, "you", "hang")
        return self._finish(char, st, c, now, "you", "hangup")

    def _finish(self, char, st, c, t, who, why, res=None):
        """通話を終える: トークの要約・相手の最後のひとこと・機嫌・見立て・お礼の心当たり・寝落ちの翌朝・またかけるね."""
        app = self.app
        cid = char["id"]
        p = st["params"]
        mins = max(1, int(round((t - c["t"]) / 60.0)))
        rs = c.get("res") or []
        avg = c.get("score", 0) / max(1, len(rs))
        lv = nori_mod.level(st, t) or 0.3
        how = HOW["good" if avg >= 8 and lv >= 0.5 else "ok" if avg >= -2 else "flat" if lv >= 0.3 else "cold"]
        b = c.get("beat") or {}
        last, sorry, note = None, False, ""
        call = app.pronouns(char)[2]
        if why == "silent":                               # 黙ったまま: 相手から切る
            asleep = b.get("asleep_guess")
            key = "phone.silent_sleep" if asleep else "phone.silent_cut" if self.close_rel(char, st) else "phone.silent_awkward"
            last = self.line(char, key)
            self._silent(char, st, c, b, t, asleep)
            note = "途中で返事をしなくなり、%sから切れた" % char.get("name", "相手")
        elif why == "limit" and who == "her":
            pun = float(app.traits(char).get("punctual", 0.6))
            recent = [x for x in st.get("call_sorries") or [] if t - x < 7 * 86400]      # 毎回謝ると決まり文句になる
            sorry = random.random() < 0.35 + 0.4 * pun + (0.15 if self.close_rel(char, st) else 0) - 0.12 * len(recent)
            if sorry:
                st["call_sorries"] = (recent + [t])[-5:]
            last = self.line(char, "phone.end_limit" if sorry else "phone.end_limit_plain")
            if sorry and random.random() < 0.7:
                st["call_back"] = {"t": t, "why": c.get("cut")}           # またかけるね (段 2 の着信が使う)
            note = "%sので、%sから切り上げた" % (c.get("cut") or "用事がある", char.get("name", "相手"))
        elif why == "limit":
            note = "%sので、切り上げた" % (c.get("cut") or "用事がある")
        elif why == "sleepy":
            sorry = random.random() < 0.5
            last = self.line(char, "phone.end_sleepy")
            note = "%sが眠そうで、切り上げた" % char.get("name", "相手")
        elif why == "cold":
            last = self.line(char, "phone.end_cold")
            note = "話が続かず、%sから切り上げた" % char.get("name", "相手")
        elif why == "enough":
            last = self.line(char, "phone.end_enough")
            note = "十分話して、%sから切り上げた" % char.get("name", "相手")
        elif why == "bye":
            early = (c.get("by") == "her" or b.get("mine")) and (mins < 5 or c.get("turns", 0) < 3)
            last = self.line(char, "phone.bye_early" if early or res == "bad" else "phone.bye_ok")
            note = "あなたから切り上げた"
            if early:
                self._cut_early(char, st, c, t, soft=True)
        elif why == "hangup":
            note = "あなたから切った"
            if c.get("by") == "her" and (mins < 5 or c.get("turns", 0) < 3):
                self._cut_early(char, st, c, t)
            elif b.get("mine") and b.get("kind") != "sleepy":
                app.apply_effects(st, {"mood": -2}, t)    # 話している途中で切られた
        elif why in ("hang", "night", "keep"):
            note = {"hang": "%sが寝てしまい、そっと切った", "night": "%sが寝てしまい、小さくおやすみと言って切った",
                    "keep": "%sが寝てしまい、つないだままにした"}[why] % char.get("name", "相手")
            self._log(c, "me", NARRATION[why], t)
            self._doze_after(char, st, c, t, why)
        if last:
            self._log(c, "her", last, t)
        # 長く付き合ってくれた / 付き合った
        good_call = why not in ("silent", "cold") and c.get("turns", 0) >= 3 and avg >= -2
        if good_call:
            if c.get("by") == "her":
                app.regard.sign(char, st, "call_long", t)            # 相手からかけて, 長く付き合ってもらえた
            else:
                app.manners.favor(st, "call", t)                      # 電話に付き合ってくれた (お礼の心当たり)
                if c.get("turns", 0) >= 6:
                    app.regard.sign(char, st, "call_long", t, k=0.6)
        if good_call and how == HOW["good"] and not st.get("msg_pending") and random.random() < 0.35:
            st["msg_pending"] = {"aid": "message", "t": t, "due": t + random.uniform(10, 60) * 60, "reply": True,
                                 "count": 1, "kind": "after_call", "meta": {}, "quick": False}
        # トーク: 要約と, 相手の最後のひとこと (謝ったなら「気にしないで」で返せる)
        d = app.chat.load(cid)
        summary = "📞 電話で話した（%d分ほど。%s。%s）" % (mins, how, note) if note else "📞 電話で話した（%d分ほど。%s）" % (mins, how)
        hit = False
        for it in d["items"]:
            if it.get("kind") == "call" and it.get("who") == "sys" and c.get("sys_t") is not None and it.get("t") == c["sys_t"]:
                it["text"] = summary
                hit = True
        app.chat.save(cid, d)
        if not hit:
            app.chat.add(cid, "sys", summary, kind="call", t=t)
        if last:
            app.chat.add(cid, "her", "📞『%s』" % last, kind="call_sorry" if sorry else "call_end", t=t + 0.001)
        app.presence.rec().pop("call", None)
        app.presence.save()
        app.trace.add("call", "電話が終わった", cid, t, who=who, why=why, mins=mins, turns=c.get("turns", 0), how=how,
                      sorry=sorry, avg=round(avg, 1))
        app.save_state(cid)
        out = {"mins": mins, "name": char.get("name", ""), "who": who, "why": why, "how": how, "last": last, "note": note,
               "turns": c.get("turns", 0), "cid": cid, "id": uuid.uuid4().hex[:8]}
        self._last = dict(out, at=time.time())
        return out

    _last = None

    def last_end(self):
        """直前に終わった通話 (画面が終わり方を知らせる. 20 秒のうちだけ)."""
        x = self._last
        return x if x and time.time() - x["at"] < 20 else None

    def _silent(self, char, st, c, b, t, asleep):
        """話の途中で黙った: 機嫌が下がり, 謝れる心当たりになる. 自分の話の最中・あなたからかけたときほど重い."""
        app = self.app
        w = 1.0
        if b.get("mine"):
            w *= 1.5
        if c.get("by") == "me":
            w *= 1.4                                       # そっちからかけてきたのに
        w *= max(0.5, float(app.traits(char).get("absence", 1.0))) * (1 + 0.3 * max(0.0, app.attach.factor(char, st, "dependence")))
        if asleep:
            w *= 0.3                                       # 寝落ちだと受け取った
        elif not self.close_rel(char, st):
            w *= 0.7                                       # 浅い仲は, 気まずいだけ
        w *= random.uniform(0.7, 1.3)
        d = round(min(12.0, 6.0 * w), 1)
        app.apply_effects(st, {"mood": -d, "affection": -0.3 * w}, t)
        if not asleep or w > 0.6:
            app.life.add_reason(st, "player", "bad", "電話の途中で{call}が黙ってしまった", t, told=False, delta=-d,
                                action="_call_silent")
        app.regard.sign(char, st, "call_silent", t, k=min(1.5, w))

    def _cut_early(self, char, st, c, t, soft=False):
        """相手からかけてきたのに, あなたが早く切った."""
        app = self.app
        w = (0.5 if soft else 1.0) * random.uniform(0.7, 1.3) * (1 + 0.4 * max(0.0, app.attach.factor(char, st, "dependence")))
        d = round(min(8.0, 4.0 * w), 1)
        app.apply_effects(st, {"mood": -d}, t)
        app.life.add_reason(st, "player", "bad", "せっかく電話したのに、{call}にすぐ切られた", t, told=False, delta=-d, action="_call_cut")
        app.regard.sign(char, st, "call_cut", t, k=w)

    def _doze_after(self, char, st, c, t, how):
        """寝落ちのあと: つないだままなら, 翌朝に反応 (うれしい・照れる・気まずい. 性格と仲で)."""
        if how != "keep":
            return
        p = st["params"]
        r = random.random() + 0.3 * (p.get("affection", 50) - 60) / 40.0
        mood = "glad" if r > 0.65 else "shy" if r > 0.3 else "awkward"
        if float(self.app.traits(char).get("modesty", 0)) > 3 and mood == "glad":
            mood = "shy"
        day = datetime.fromtimestamp(t)
        wake = (day + timedelta(days=1 if day.hour >= 5 else 0)).replace(hour=7, minute=0, second=0, microsecond=0)
        st["call_doze"] = {"t": t, "mood": mood, "due": wake.timestamp() + random.uniform(0, 90) * 60}

    def morning(self, char, st, now):
        """寝落ちした電話の翌朝のひとこと (届く時刻が来ていて, 相手が起きていれば)."""
        dz = st.get("call_doze")
        if not dz or now < dz.get("due", 0):
            return False
        t = dz["due"]
        if self.app.scene_at(char, st, datetime.fromtimestamp(min(now, t + 3 * 3600))).get("asleep") and now - t < 6 * 3600:
            return False
        st.pop("call_doze", None)
        self.app.chat.add(char["id"], "her", self.line(char, "phone.morning_" + dz["mood"]), kind="call_morning", t=min(now, t + 60))
        self.app.trace.add("call", "寝落ちした電話の翌朝", char["id"], now, mood=dz["mood"])
        return True

    # ------------------------------------------------------------------ 画面
    def view(self, now=None):
        now = now or time.time()
        c = self.rec()
        if not c or "beat" not in c and "next" not in c:
            return None
        b = c.get("beat")
        out = {"cid": c["cid"], "name": c.get("name", ""), "t": c["t"], "by": c.get("by", "me"), "mins": int((now - c["t"]) // 60),
               "log": c.get("log", [])[-12:], "doing": NAGARA_LABEL.get(c.get("doing")), "turns": c.get("turns", 0)}
        if b:
            out["beat"] = {"id": b["id"] + ("h" if b.get("stage") else ""), "kind": b["kind"], "text": b.get("hello") if b.get("stage") else b["text"],
                           "left": None if b.get("due") is None else max(0, int(math.ceil(b["due"] - now))),
                           "stage": b.get("stage", 0)}
            out["returns"] = [{"id": k, "label": l, "icon": i} for k, l, i in (ASLEEP_RETURNS if b["kind"] == "asleep" else RETURNS)]
        else:
            out["talking"] = True                          # 話している (次に相手が話すまで)
        return out
