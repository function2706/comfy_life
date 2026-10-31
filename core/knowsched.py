"""相手の予定の知り方: 遊んでいる画面では, 相手の予定 (キャラの生活スケジュール) は分からない. 少しずつ「知っていること」になる.

- 立ち話・会話のついでに: そばで話していると, ときどき予定をぽろっと聞ける (あなたの会話・気配りスキルと仲しだい. 必ずではない).
- 人づて: 話している相手が知っている人 (キャラ同士の関係 knows) の予定を, ついでに聞くことがある.
- 職場で: キャラの予定に勤め先 (workplace: 行き先の id) があれば, その時間にその行き先へ行くと, 店員として働いているのに出会う.
- 本人のメッセージで: 離れている相手からのメッセージに「今日は◯◯だった」が添えられることがある.
聞いた話は「知っていること」(状態の known. kind = schedule) に残り, 関係性タブに出る. 古くなり, 予定が変われば外れることもある
(聞いたときの予定の中身を覚えておき, いまの予定に同じものがなければ「もう違うかも」).
新しいセリフの場面は作らない (聞いたことはナレーションで書く).
"""
import random
import time
from datetime import datetime

DAYS_JA = {"all": "毎日", "weekday": "平日", "weekend": "週末", "mon": "月曜", "tue": "火曜", "wed": "水曜", "thu": "木曜",
           "fri": "金曜", "sat": "土曜", "sun": "日曜"}
STALE_DAYS = 60


def _hm(s):
    h, m = str(s or "00:00").split(":")
    return int(h) * 60 + int(m)


def when_word(e):
    """予定の時間帯を, 会話で聞くような言葉に (朝 / 昼 / 夕方 / 夜 / 夜中)."""
    m = _hm(e.get("from"))
    w = "朝" if 300 <= m < 600 else "午前" if m < 690 else "昼" if m < 900 else "夕方" if m < 1080 else "夜" if m < 1380 else "夜中"
    if m < 300:
        w = "夜中"
    return w


def key_of(e):
    """予定の中身の目印 (変わったら外れる)."""
    return "%s|%s|%s|%s|%s" % (e.get("days"), e.get("from"), e.get("to"), e.get("label"), e.get("workplace", ""))


def notable(char):
    """聞いて覚えるような予定: 出かけている・手が離せない・勤め先がある (寝る・食事などの家での時間は除く)."""
    out = []
    for e in char.get("schedule") or []:
        if e.get("asleep") or e.get("activity") in ("sleep", "breakfast", "lunch", "dinner", "bath", "morning", "night",
                                                                 "commute", "getready", "cooking"):
            continue
        if e.get("away") or e.get("busy") or e.get("workplace"):
            out.append(e)
    return out


def phrase(app, e):
    what = (e.get("label") or e.get("activity") or "").replace("中", "")
    return "%sの%sは%sらしい" % (days_word(e.get("days")), when_word(e), at_work(app, e, what))


def at_work(app, e, what):
    wp = e.get("workplace")
    if wp and app.places.label(wp) not in what:
        what = "%sで%s" % (app.places.label(wp), what or "仕事")
    return what


def days_word(spec):
    parts = [x.strip() for x in str(spec or "all").lower().split(",") if x.strip()] or ["all"]
    return "と".join(DAYS_JA.get(x, x) for x in parts)


class KnowSched:
    def __init__(self, app):
        self.app = app

    def known_keys(self, st):
        return {k.get("key") for k in st.get("known") or [] if k.get("kind") == "schedule"}

    def learn(self, cid, e, via, now=None):
        """予定を一つ知った. 知ったことの文を返す (もう知っていれば None)."""
        app = self.app
        now = now or time.time()
        st = app.state(cid)
        key = key_of(e)
        if key in self.known_keys(st):
            return None
        text = phrase(app, e)
        known = st.setdefault("known", [])
        known.append({"kind": "schedule", "text": text, "t": now, "key": key, "via": via})
        del known[:-30]
        app.save_state(cid)
        return text

    def unknown(self, char, st):
        ks = self.known_keys(st)
        return [e for e in notable(char) if key_of(e) not in ks]

    # ------------------------------------------------------------------ きっかけ
    def from_talk(self, char, st, now=None):
        """そばで話したついでに, 予定をぽろっと聞く (会話・気配り・仲しだい). 聞いたらナレーションを返す."""
        app = self.app
        L = app.life
        p = st["params"]
        cands = self.unknown(char, st)
        if not cands:
            return self._secondhand(char, st, now)
        chance = 0.06 + 0.08 * L.skill_soft("talk") + 0.06 * L.skill_soft("care") + max(-0.04, (p.get("affection", 50) - 50) / 500.0)
        if random.random() >= chance:
            return self._secondhand(char, st, now)
        text = self.learn(char["id"], random.choice(cands), "talk", now)
        return "（話のついでに、%sと聞いた）" % text if text else None

    def _secondhand(self, char, st, now=None):
        """人づて: 話している相手が知っている人の予定を, ついでに聞くことがある (まれ)."""
        app = self.app
        others = [b for b, r in (app.relations.get(char["id"]) or {}).items() if r.get("knows") and b in app.chars]
        if not others or random.random() >= 0.03 + 0.04 * app.life.skill_soft("care"):
            return None
        b = random.choice(others)
        cands = self.unknown(app.chars[b], app.state(b))
        if not cands:
            return None
        text = self.learn(b, random.choice(cands), "secondhand:" + char["id"], now)
        return "（%sから、%sは%sと聞いた）" % (char.get("name", ""), app.chars[b].get("name", ""), text) if text else None

    def at_workplace(self, now=None):
        """出かけている先が, 誰かの勤め先で, いまその人が働いている時間なら, 店員として働いているのに出会う (行き先ごとに一度).
        出会ったことのナレーションのリストを返す."""
        app = self.app
        now = now or time.time()
        p = app.presence.rec()
        if p.get("mode") not in ("out", "work") or not p.get("place") or p.get("travel"):
            return []       # 外出の行き先, またはアルバイト先
        place = p.get("place")
        seen = p.setdefault("work_seen", [])
        out = []
        dt = datetime.fromtimestamp(now)
        for cid, char in app.chars.items():
            if cid in seen:
                continue
            sc = app.scheduled_scene(char, dt)
            ov = app.state(cid).get("override")
            if ov and ov.get("until", 0) > now:
                continue
            e = next((x for x in char.get("schedule") or [] if x.get("workplace") == place and x.get("label") == sc.get("label")), None)
            if not e or app.bonds.together(cid):
                continue
            seen.append(cid)
            text = self.learn(cid, e, "workplace", now)
            st = app.state(cid)
            eff, _ = app.bonds.realize(char, st, {"mood": 1, "loneliness": -1}, "_workplace", now)
            app.apply_effects(st, app.trait_effects(char, eff))
            app.bonds.met(st, now)
            app.save_state(cid)
            if p.get("mode") == "work":        # 同じ店のアルバイト: 一緒に働く
                line = "%sのバイトで、%sと同じシフトだった。%s" % (
                    app.places.label(place), char.get("name", ""), random.choice(("休憩のときに少し話した", "忙しくて、目で合図をしあうくらいだった",
                                                                                "仕事のことを少し教えてもらった")))
            else:
                line = "%sで、%sが店員として働いていた。会釈すると、%s" % (
                    app.places.label(place), char.get("name", ""), random.choice(("小さく手を振ってくれた", "少し驚いた顔で会釈を返してくれた",
                                                                                "忙しそうに目で合図をくれた")))
            if text:
                line += "（%s）" % text
            app.outdoor.note(line, now)
            app.solo.note("out", line, now)
            out.append(line)
        app.presence.save()
        return out

    def from_message(self, char, st, now=None):
        """離れている相手からのメッセージに, 今日のこと (「今日は◯◯だった」) が添えられることがある. 添える一文 or None."""
        app = self.app
        now = now or time.time()
        if random.random() >= 0.3:
            return None
        dt = datetime.fromtimestamp(now)
        mins = dt.hour * 60 + dt.minute
        from .engine import day_match
        done = [e for e in notable(char) if day_match(e.get("days"), dt) and _hm(e.get("to")) <= mins]
        if not done:
            return None
        e = random.choice(done)
        if (st.get("sched_told") or {}).get("d") == dt.strftime("%Y-%m-%d"):
            return None             # 今日のことを添えるのは, 一日に一度
        st["sched_told"] = {"d": dt.strftime("%Y-%m-%d")}
        text = self.learn(char["id"], e, "message", now)
        what = at_work(app, e, (e.get("label") or "").replace("中", ""))
        return "（今日は%sだったらしい%s）" % (what, "。%s" % text if text else "")

    # ------------------------------------------------------------------ 関係性タブ
    def view(self, char, st, now=None):
        """知っている予定 (古さ・いまの予定と食い違っていないか)."""
        now = now or time.time()
        cur = {key_of(e) for e in char.get("schedule") or []}
        out = []
        for k in st.get("known") or []:
            if k.get("kind") != "schedule":
                continue
            age = (now - k.get("t", now)) / 86400.0
            out.append({"text": k["text"], "t": k.get("t"), "via": (k.get("via") or "").split(":")[0],
                        "stale": k.get("key") not in cur, "old": age > STALE_DAYS})
        return out
