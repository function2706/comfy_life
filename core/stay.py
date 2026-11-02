"""お泊り: 相手の家に来ている (visit) / あなたの家に招いている (guest) 夜に, 泊まる・泊める (with.stay).

- 聞く: 夜 (20 時〜翌 3 時) に, 相手の家なら「泊まっていってもいい？」, あなたの家なら「泊まっていく？」.
  受けるかは, 好感度・信頼・機嫌・慎重さ (性格の caution)・照れ (modesty)・家に上がる慣れ (相手の家のとき) と, その日の揺らぎ.
  親しくても断られることはある (必ず泊まれる, にはしない). 断られても少し気まずいだけ (機嫌 −1).
- 相手から言い出す: 来ているあいだ, 夜 22 時を過ぎた最初のときに一度だけ考える (受ける見込みの半分くらい).
  「もう遅いし……泊まっていきますか？」/「今日、泊まっていってもいい？」→ 答えるまで with.stay_offer.
- 泊まる: 一緒にいるのを翌朝 (STAY_MORNING 時. 夜中の 0〜5 時に決めたらその日の朝) まで延ばす.
  あなたが寝ても別れたことにならない. 相手も寝る時間には寝ている (泊まっている家で).
  寝るのは別々. 添い寝 (sleep_together) は泊まっていて, 好感度 SLEEP_AFF・信頼 SLEEP_TRUST 以上のときだけ.
  朝になれば, 相手の家ならあなたが帰る / あなたの家なら相手が帰る (いつもの別れ方).
"""
import random
import time
from datetime import datetime, timedelta

STAY_MORNING = 9.5
SLEEP_AFF = 80
SLEEP_TRUST = 70
LINES = {
    "stay.yes": "……うん、いいですよ。もう遅いですしね",
    "stay.no": "えっと……今日は、ちょっと。ごめんなさい",
    "stay.guest_yes": "いいんですか？ ……じゃあ、お言葉に甘えて",
    "stay.guest_no": "ううん、今日は帰ります。また今度",
    "stay.offer": "もう遅いですし……泊まっていきますか？",
    "stay.guest_offer": "あの……今日、泊まっていってもいいですか？",
    "stay.offer_yes": "（泊まっていくことにした）",
    "stay.offer_no": "そうですか……じゃあ、気をつけて",
}
SCENE_LABEL = {
    "stay.yes": "泊まっていいか聞いて, 受けてくれた (相手の家)", "stay.no": "泊まっていいか聞いて, 断られた (相手の家)",
    "stay.guest_yes": "泊まっていくか誘って, 受けてくれた (あなたの家)", "stay.guest_no": "泊まっていくか誘って, 断られた (あなたの家)",
    "stay.offer": "相手から, 泊まっていくか聞いてくる (相手の家)", "stay.guest_offer": "相手から, 泊まっていいか聞いてくる (あなたの家)",
    "stay.offer_no": "相手から泊まっていくか聞かれて, 帰ると答えた",
}


def night(dt):
    return dt.hour >= 20 or dt.hour < 3


class Stay:
    def __init__(self, app):
        self.app = app

    def rec(self, cid=None):
        """泊まれる形で一緒にいるときの with (相手の家に来ている / 招いている)."""
        w = self.app.bonds.with_rec()
        if not w or w.get("mode") not in ("visit", "guest") or (cid and w.get("cid") != cid):
            return None
        return w

    def staying(self, cid=None):
        w = self.rec(cid)
        return bool(w and w.get("stay"))

    def chance(self, char, st, w, now):
        """受ける見込み (0〜0.9)."""
        app = self.app
        p = st["params"]
        tr = app.traits(char)
        c = 0.1 + (p.get("affection", 50) - 60) / 40.0 + (p.get("trust", 50) - 55) / 60.0 + (p.get("mood", 50) - 50) / 120.0 \
            + float(tr.get("caution", 0)) / 40.0 - max(0.0, float(tr.get("modesty", 0))) / 60.0      # (caution: + ほど心を開きやすい)
        if w["mode"] == "visit":
            c += 0.25 * app.athome.fam(char["id"], st, now)[0]
            if app.care.ill(st, now) and w.get("care"):
                c += 0.2                                   # 看病に来てくれている
        if app.quarrel.active(st, now):
            c -= 0.5
        return max(0.0, min(0.9, c))

    def morning(self, now):
        dt = datetime.fromtimestamp(now)
        day = dt.date() if dt.hour < 5 else dt.date() + timedelta(days=1)
        return (datetime(day.year, day.month, day.day) + timedelta(hours=STAY_MORNING)).timestamp()

    def _begin(self, w, char, now):
        app = self.app
        w["stay"] = {"t": now}
        w.pop("stay_offer", None)
        w["until"] = max(float(w.get("until", 0)), self.morning(now))
        app.bonds.save()
        st = app.state(char["id"])
        if (st.get("override") or {}).get("activity") == "guest":
            st["override"] = None                         # 招いた場面から, 泊まっている場面へ (host_scene)
        eff, _ = app.bonds.realize(char, st, {"affection": 1, "mood": 2, "loneliness": -6}, "_stay", now)
        return app.apply_effects(st, app.trait_effects(char, eff))

    def ask(self, cid, now=None):
        """泊まっていい？ / 泊まっていく？"""
        app = self.app
        now = now or time.time()
        with app.lock:
            w = self.rec(cid) or self.rec()
            if not w:
                raise ValueError("いまは泊まる・泊める話はできません（相手の家にいるか、家に招いているときに）")
            cid = w["cid"]
            if w.get("stay"):
                raise ValueError("もう泊まることになっています")
            if not night(datetime.fromtimestamp(now)):
                raise ValueError("泊まる話は、夜になってから")
            if w.get("helping"):
                raise ValueError("手伝いの最中です")
            if w.get("stay_asked"):
                raise ValueError("今日はもう聞きました")
            char, st = app.chars[cid], app.state(cid)
            w["stay_asked"] = True
            guest = w["mode"] == "guest"
            if random.random() < self.chance(char, st, w, now):
                d = self._begin(w, char, now)
                key = "stay.guest_yes" if guest else "stay.yes"
            else:
                app.bonds.save()
                d = app.apply_effects(st, app.trait_effects(char, {"mood": -1}))
                key = "stay.guest_no" if guest else "stay.no"
            e = app.note_entry(char, st, now, "_stay_ask", "泊まっていく？" if guest else "泊まっていい？", "🌙", self.line(char, key), d)
            app.save_state(cid)
            return {"entry": e, "stay": bool(w.get("stay"))}

    def live(self, cid, now):
        """来ているあいだ (tick): 夜 22 時を過ぎた最初のときに一度だけ, 相手から言い出すか考える."""
        app = self.app
        w = self.rec(cid)
        if not w or w.get("stay") or w.get("stay_checked") or w.get("helping"):
            return None
        dt = datetime.fromtimestamp(now)
        if not (dt.hour >= 22 or dt.hour < 3):
            return None
        w["stay_checked"] = True
        char, st = app.chars[cid], app.state(cid)
        if random.random() >= 0.5 * self.chance(char, st, w, now):
            app.bonds.save()
            return None
        w["stay_offer"] = True
        app.bonds.save()
        key = "stay.guest_offer" if w["mode"] == "guest" else "stay.offer"
        return app.note_entry(char, st, now, "_stay_offer", "泊まっていく？", "🌙", self.line(char, key))

    def answer(self, cid, yes, now=None):
        """相手からの「泊まっていく？」に答える."""
        app = self.app
        now = now or time.time()
        with app.lock:
            w = self.rec(cid) or self.rec()
            if not w or not w.get("stay_offer"):
                raise ValueError("いまは聞かれていません")
            cid = w["cid"]
            char, st = app.chars[cid], app.state(cid)
            if yes:
                d = self._begin(w, char, now)
                e = app.note_entry(char, st, now, "_stay_yes", "泊まる", "🌙", self.line(char, "stay.offer_yes"), d)
            else:
                w.pop("stay_offer", None)
                app.bonds.save()
                d = app.apply_effects(st, app.trait_effects(char, {"mood": -1}))
                e = app.note_entry(char, st, now, "_stay_no", "泊まらない", "🌙", self.line(char, "stay.offer_no"), d)
            app.save_state(cid)
            return {"entry": e}

    # ------------------------------------------------------------------ 場面・できること
    def scene(self, char, base, t):
        """泊まっている間 / 招いている間の相手の場面. 相手の家のふだんの場面は visit.host_scene."""
        w = self.rec(char.get("id"))
        if not w or not w.get("stay") or not (w.get("t", 0) - 60 <= t < w.get("until", 0)):
            return None
        where = "自宅" if w["mode"] == "visit" else "あなたの家"
        if base.get("asleep"):
            return dict(base, label="泊まっていて、寝ている" if w["mode"] == "guest" else base.get("label") or "就寝中", location=where)
        return dict(base, activity="stay", label="あなたの家に泊まりに来ている" if w["mode"] == "guest" else "家で一緒に過ごしている",
                    location=where, away=False, busy=False, asleep=False, outing=False, pos="indoors, at home, relaxed", neg="")

    def allows(self, a, cid):
        """添い寝は, 泊まっていて親密なときだけ (相手の家・招いたとき. 同居はこれまでどおり)."""
        if a["id"] != "sleep_together" or not self.rec(cid):
            return None
        if not self.staying(cid):
            return "泊まっていないので、添い寝はしません"
        p = self.app.state(cid)["params"]
        if p.get("affection", 0) < SLEEP_AFF or p.get("trust", 0) < SLEEP_TRUST:
            return "泊まっていても、寝るのは別々です"
        return "ok"

    def view(self, cid, now=None):
        w = self.rec(cid)
        if not w:
            return None
        now = now or time.time()
        return {"mode": w["mode"], "staying": bool(w.get("stay")), "offered": bool(w.get("stay_offer")),
                "can_ask": not w.get("stay") and not w.get("stay_asked") and not w.get("helping") and night(datetime.fromtimestamp(now)),
                "until": w.get("until")}

    def line(self, char, key):
        app = self.app
        t = app.persona_text(char, key) or LINES[key]
        fp, _, call = app.pronouns(char)
        return t.replace("{fp}", fp).replace("{call}", call)
