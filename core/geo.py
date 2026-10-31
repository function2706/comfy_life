"""場所の位置と移動 (マップの段階 1: 距離と移動時間. 地図の画面はまだ無い).

- 位置: ワールドごとに, 行き先 (core/places.py の表)・あなたの家・相手の家・職場の位置 (km) を決めておく (geo.json).
  ランダムだが現実的な決まりに沿う: 駅前を真ん中に, 商店街・カフェ・本屋・食べ物屋は駅のまわり. あなたの家は住宅地
  (駅まで歩いて 6〜20 分ほど), 公園・コンビニ・スーパー・河川敷は家の近く. モール・家電量販店・病院は少し離れていて,
  水族館・遊園地・海・山は電車で行く距離. 職場は電車で通う距離. 相手の家は, たいてい同じ町 (ときどき何駅か先).
  まだ位置の無い場所は, 初めて引いたときに決める (以前のワールドも, 次に開いたときにそろう. 過去の記録には触れない).
- 移動のしかた: 歩く (時間と体力. 雨・雪だと遅い) / 電車・バス (駅・停留所まで歩く + 次の便を待つ + 乗る + 運賃.
  便は朝夕に多く夜は少ない. 0:30〜5:00 は走っていない). 近い場所は歩くだけ.
- 移動は画面の時間どおりに進む (リアルタイム). 出かけると「〇〇へ移動中」になり, 着くまで買い物・約束・その場所でのことは
  できない (スマホは使える). 帰るときも「家へ移動中」になり, 着いてから家にいる. 記録は player.json の presence:
  pos (いまいる場所), travel ({from, to, how, t0, arr, fare, dir: go / home, then}), arrived (着いた時刻), left (出た時刻).
"""
import math
import random
import time
from datetime import datetime

from . import places as places_mod
from . import store

ROAD = 1.3                 # 道のり / 直線
WALK_KMH = 4.5
RUN_KMH = 8.0
RIDE_KMH = (25.0, 50.0)    # 乗っている速さ: 10 km までは各駅・バス, その先は快速
RIDE_ADD = 3.0             # 乗り降りの分 (分)
WALK_MAX_MIN = 180         # これより長く歩く道は選べない (始発を待つ)
SERVICE = (5.0, 24.5)      # 電車・バスの走っている時間 (5:00〜翌 0:30)
INSTANT = False            # テスト用: 移動に時間をかけない (tools/testclock.py. 移動そのものは tools/test_geo.py で)
HOW_LABEL = {"walk": "徒歩", "transit": "電車・バス", "run": "走って"}

# 位置の決まり: (基準, 最小 km, 最大 km). 基準は station (駅前) か home (あなたの家)
NEAR_STATION = ("shopping_street", "cafe", "drugstore", "bookstore", "teishoku", "ramen", "fastfood", "family", "restaurant")
RULES = dict({k: ("station", 0.08, 0.6) for k in NEAR_STATION},
             town=("station", 0.2, 0.5), park=("home", 0.15, 0.6), convenience=("home", 0.1, 0.45),
             supermarket=("home", 0.25, 0.8), riverside=("home", 0.4, 1.2), clinic=("station", 0.5, 1.8),
             mall=("station", 2.0, 5.0), electronics=("station", 1.8, 4.5), hill=("station", 3.0, 7.0),
             aquarium=("station", 12.0, 35.0), amusement=("station", 12.0, 35.0), beach=("station", 25.0, 60.0),
             mountain=("station", 25.0, 60.0), office=("station", 3.0, 20.0))
HOME_KM = (0.35, 1.15)     # あなたの家と駅の距離
CHAR_NEAR, CHAR_FAR = (0.3, 2.5), (4.0, 20.0)
CHAR_FAR_P = 0.2


def ride_min(km):
    """乗っている時間 (分)."""
    return RIDE_ADD + min(km, 10.0) / RIDE_KMH[0] * 60 + max(0.0, km - 10.0) / RIDE_KMH[1] * 60


def headway(h):
    """その時刻の便の間隔 (分). 走っていなければ None."""
    if SERVICE[1] - 24 <= h < SERVICE[0]:
        return None
    if 6.5 <= h < 9.5 or 17 <= h < 20:
        return 6.0
    if 9.5 <= h < 17:
        return 10.0
    if 20 <= h < 23:
        return 15.0
    return 25.0


def _hour(t):
    d = datetime.fromtimestamp(t)
    return d.hour + d.minute / 60.0


def first_train(t):
    """t 以降で, 電車・バスが走り始める時刻 (走っていればそのまま t)."""
    if headway(_hour(t)) is not None:
        return t
    d = datetime.fromtimestamp(t)
    return d.replace(hour=int(SERVICE[0]), minute=0, second=0, microsecond=0).timestamp()


class Geo:
    def __init__(self, app):
        self.app = app
        self._cache = None

    # ------------------------------------------------------------------ 位置
    def rec(self):
        if self._cache is None or self._cache[0] != store.WORLD:
            self._cache = (store.WORLD, store.load(store.wpath("geo.json"), {}) or {})
        r = self._cache[1]
        r.setdefault("pts", {})
        return r

    def save(self):
        store.save(store.wpath("geo.json"), self.rec())

    @staticmethod
    def _ring(base, lo, hi):
        a = random.uniform(0, 2 * math.pi)
        d = random.uniform(lo, hi)
        return [round(base[0] + d * math.cos(a), 3), round(base[1] + d * math.sin(a), 3)]

    def _make(self, pid):
        if pid == "station":
            return {"xy": [0.0, 0.0], "acc": 0.0}
        if pid == places_mod.HOME_ME:
            xy = self._ring([0, 0], *HOME_KM)
            return {"xy": xy, "acc": round(math.hypot(*xy), 3)}         # 家から駅まで歩く
        if places_mod.is_home(pid):
            far = random.random() < CHAR_FAR_P
            xy = self._ring([0, 0], *(CHAR_FAR if far else CHAR_NEAR))
            return {"xy": xy, "acc": round(math.hypot(*xy), 3) if not far else round(random.uniform(0.2, 1.0), 3)}
        base, lo, hi = RULES.get(pid, ("station", 0.3, 1.5))
        bxy = self.pt(places_mod.HOME_ME)["xy"] if base == "home" else [0.0, 0.0]
        xy = self._ring(bxy, lo, hi)
        d0 = math.hypot(*xy)
        acc = d0 if d0 < 2.0 else random.uniform(0.15, 0.7)      # 駅の近くなら駅まで. 遠い場所は最寄りの駅・停留所まで
        return {"xy": xy, "acc": round(acc, 3)}

    def pt(self, pid):
        pid = pid or places_mod.HOME_ME
        r = self.rec()
        if pid not in r["pts"]:
            r["pts"][pid] = self._make(pid)
            self.save()
        return r["pts"][pid]

    def ensure(self):
        """表の行き先と知っている相手の家に, 位置をそろえる (以前のワールドの遡及も, ここで一度だけ)."""
        r = self.rec()
        n = len(r["pts"])
        for pid in ["station", places_mod.HOME_ME] + list(places_mod.PLACES):
            if pid not in r["pts"]:
                r["pts"][pid] = self._make(pid)
        for cid in self.app.chars:
            if self.app.bonds.stage(cid) != "known" and "home:" + cid not in r["pts"]:
                r["pts"]["home:" + cid] = self._make("home:" + cid)
        if len(r["pts"]) != n:
            self.save()

    def km(self, a, b):
        """道のりの距離 (km)."""
        if a == b:
            return 0.0
        pa, pb = self.pt(a)["xy"], self.pt(b)["xy"]
        return math.hypot(pa[0] - pb[0], pa[1] - pb[1]) * ROAD

    # ------------------------------------------------------------------ 経路
    def walk_min(self, a, b, t=None, run=False):
        m = self.km(a, b) / (RUN_KMH if run else WALK_KMH) * 60
        w = self._weather(t)
        return m * (1.15 if w in ("rain", "snow") else 1.0)

    def _weather(self, t):
        from .outdoor import weather
        return weather(datetime.fromtimestamp(t or time.time()))["id"]

    @staticmethod
    def fare(km):
        return int(min(1500, 150 + 20 * km) / 10) * 10

    def options(self, a, b, t=None):
        """a → b の行き方 (目安). {km, walk: {min, ok}, transit: {min, fare, ok, note} or None, best}."""
        t = t or time.time()
        km = self.km(a, b)
        walk = self.walk_min(a, b, t)
        out = {"km": round(km, 2), "walk": {"min": round(walk), "ok": walk <= WALK_MAX_MIN}, "transit": None}
        if km > 1.2:
            pa, pb = self.pt(a), self.pt(b)
            acc = (pa["acc"] + pb["acc"]) * ROAD / WALK_KMH * 60
            ride = ride_min(km)
            hw = headway(_hour(t))
            tm = acc + ride + (hw or 10) / 2
            if tm < walk * 0.9:
                note = "" if hw else "いまは走っていない（始発は5時）"
                out["transit"] = {"min": round(tm), "fare": self.fare(km), "ok": bool(hw), "note": note}
        tr = out["transit"]
        out["best"] = "transit" if tr and tr["ok"] and (tr["min"] < walk * 0.75 or walk > 25) else \
            "walk" if out["walk"]["ok"] else "transit" if tr else "walk"
        return out

    def leg(self, a, b, how, t, rand=True):
        """実際の移動 1 回: {how, min, fare, wait (待った分), note}. 行けなければ ValueError."""
        o = self.options(a, b, t)
        if how in (None, "", "auto"):
            how = o["best"]
        if how == "run":
            return {"how": "run", "min": self.walk_min(a, b, t, run=True), "fare": 0, "wait": 0.0, "note": ""}
        if how == "walk" or not o["transit"]:
            if not o["walk"]["ok"]:
                raise ValueError("歩いて行くには遠すぎます（%d分ほど）" % o["walk"]["min"])
            return {"how": "walk", "min": self.walk_min(a, b, t), "fare": 0, "wait": 0.0, "note": ""}
        pa, pb = self.pt(a), self.pt(b)
        km = o["km"]
        acc = (pa["acc"] + pb["acc"]) * ROAD / WALK_KMH * 60
        t_st = t + pa["acc"] * ROAD / WALK_KMH * 3600            # 駅・停留所に着く
        start = first_train(t_st)
        wait = (start - t_st) / 60.0
        hw = headway(_hour(start)) or 10
        wait += random.uniform(0, hw) if rand else hw / 2
        note = "始発を待った" if start > t_st else ""
        return {"how": "transit", "min": acc + wait + ride_min(km), "fare": self.fare(km), "wait": round(wait, 1),
                "note": note}

    # ------------------------------------------------------------------ いまどこにいるか
    def rec_p(self):
        return self.app.presence.rec()

    def travel(self):
        return self.rec_p().get("travel")

    def moving(self, now=None):
        tr = self.travel()
        return bool(tr) and (now or time.time()) < tr["arr"]

    def where(self, now=None):
        """いまいる場所 (移動中なら, 出たところ)."""
        app = self.app
        now = now or time.time()
        p = self.rec_p()
        tr = p.get("travel")
        if tr:
            return tr["from"] if now < tr["arr"] else tr["to"]
        w = app.bonds.with_rec()
        if w and w.get("mode") == "visit":
            return "home:" + w["cid"]
        for cid in app.chars:
            if app.bonds.together(cid):
                ov = app.state(cid).get("override") or {}
                if ov.get("outing") and ov.get("until", 0) > now and ov.get("place"):
                    return ov["place"]
        if p.get("mode") in ("out", "work"):
            return p.get("pos") or p.get("place") or places_mod.HOME_ME
        return places_mod.HOME_ME

    def away(self, now=None):
        """家から離れたところにいる (帰るのに移動がいる)."""
        return self.where(now) != places_mod.HOME_ME

    # ------------------------------------------------------------------ 出かける・着く・帰る
    def depart(self, to, how=None, now=None, then=None, frm=None, direction="go"):
        """いまいる場所から to へ向かう (presence の mode・place は呼ぶ側で決めておく). 移動が要らなければ None."""
        app = self.app
        now = now or time.time()
        frm = frm or self.where(now)
        p = self.rec_p()
        if direction == "go":
            p.pop("arrived", None)
            p.pop("left", None)
        if frm == to or INSTANT:
            p["pos"] = to
            if direction == "go" and not INSTANT:
                p["arrived"] = now
            app.presence.save()
            return None
        lg = self.leg(frm, to, how, now)
        if lg["fare"]:
            app.life.move(None, dp=-lg["fare"], cat="transport", note="交通費（%s）" % app.places.label(to))
        walk_h = (lg["min"] - lg.get("wait", 0)) / 60.0 if lg["how"] != "transit" else \
            (self.pt(frm)["acc"] + self.pt(to)["acc"]) * ROAD / WALK_KMH
        from .body import MOVE_PER_H
        app.body.add_exercise(MOVE_PER_H["jog" if lg["how"] == "run" else "walk"] * walk_h)
        app.life.tire((6.0 if lg["how"] == "run" else 2.5) * walk_h)
        p["travel"] = {"from": frm, "to": to, "how": lg["how"], "t0": now, "arr": now + lg["min"] * 60, "fare": lg["fare"],
                       "dir": direction, "then": then, "note": lg["note"]}
        app.presence.save()
        return p["travel"]

    def head_home(self, now=None, how=None):
        """出先から家へ向かう (戻るを押した). 着くまで「家へ移動中」."""
        now = now or time.time()
        p = self.rec_p()
        if p.get("travel") and p["travel"].get("dir") == "home":
            raise ValueError("家へ向かっている途中です（あと%d分）" % max(1, round((p["travel"]["arr"] - now) / 60)))
        if INSTANT:
            return None
        frm = self.where(now)
        if p.get("travel"):                      # 行く途中で引き返す: 出たところから
            frm = p["travel"]["from"]
            p.pop("travel", None)
            p["arrived"] = now
        p["left"] = now
        p.setdefault("arrived", p.get("since", now))     # 移動の記録が無い外出 (以前のセーブ): 出かけたときから
        tr = self.depart(places_mod.HOME_ME, how, now, frm=frm, direction="home")
        if not tr:                               # 家を出たところで引き返した: すぐ家
            return None
        return {"traveling": True, "text": "（家へ向かった。%sで%d分ほど）" % (HOW_LABEL[tr["how"]], max(1, round((tr["arr"] - now) / 60))),
                "travel": self.view(now)}

    def home_eta(self, t):
        """t に出先を出たら, 家に着く時刻 (画面を閉じたとき. 揺らぎなし)."""
        p = self.rec_p()
        tr = p.get("travel")
        if tr and tr.get("dir") == "home":
            return max(t, tr["arr"])
        frm = tr["from"] if tr and t < tr["arr"] else self.where(t)
        if frm == places_mod.HOME_ME or INSTANT:
            return t
        try:
            return t + self.leg(frm, places_mod.HOME_ME, None, t, rand=False)["min"] * 60
        except ValueError:
            return t

    def tick(self, now=None):
        """着いたか (心拍のたび). 着いたら知らせを返す."""
        app = self.app
        now = now or time.time()
        p = self.rec_p()
        tr = p.get("travel")
        if not tr or now < tr["arr"]:
            return None
        p.pop("travel", None)
        if tr["dir"] == "home":
            p["pos"] = places_mod.HOME_ME
            app.presence.save()
            r = app.come_back(at=tr["arr"], arrived=True)
            return {"text": "（家に着いた）", "act": r}
        p["pos"], p["arrived"] = tr["to"], tr["arr"]
        app.presence.save()
        label = app.places.label(tr["to"])
        then = tr.get("then")
        if then:
            r = app.solo.arrive_then(then, tr["to"], tr["arr"])
            if r:
                return dict(r, text=r.get("done") or r.get("text") or "（%sに着いた）" % label)
        app.solo.note("out", "%sに着いた" % label, tr["arr"])
        return {"text": "（%sに着いた）" % label}

    # ------------------------------------------------------------------ 画面
    def view(self, now=None):
        now = now or time.time()
        tr = self.travel()
        if not tr:
            return None
        return {"to": tr["to"], "label": self.app.places.label(tr["to"]) if tr["dir"] == "go" else "家",
                "how": tr["how"], "how_label": HOW_LABEL.get(tr["how"], ""), "dir": tr["dir"],
                "remain": max(0, int(tr["arr"] - now)), "arr": tr["arr"], "fare": tr["fare"], "note": tr.get("note", "")}

    def choices_view(self, ids, now=None):
        """行き先ごとの行き方の目安 (画面の行き先の欄に出す): {id: {walk, transit, best}}."""
        now = now or time.time()
        frm = self.where(now)
        out = {}
        for pid in ids:
            try:
                o = self.options(frm, pid, now)
            except Exception:  # noqa: BLE001 - 目安なので, 出せなければ出さない
                continue
            out[pid] = {"walk": o["walk"], "transit": o["transit"], "best": o["best"], "km": o["km"]}
        return out
