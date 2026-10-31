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
EV_DELAY, EV_DOZE, EV_JAM, EV_FLAT = 0.04, 0.15, 0.03, 0.015      # 途中の出来事の起きやすさ (1 回あたり)
FLAT_FIX = 1000
HOW_LABEL = {"walk": "徒歩", "transit": "電車・バス", "run": "走って", "bike": "自転車", "car": "車", "taxi": "タクシー"}
BIKE_KMH, BIKE_MAX_MIN = 15.0, 90
CAR_ADD = 6.0              # 車: 乗り込む・停める分 (分)
JAM = 1.35                 # 朝夕の渋滞 (車・タクシー)
GAS_PER_KM = 12            # ガソリン代 (円/km)
TAXI_BASE, TAXI_KM = 500, 400
FARE_NOTE = {"transit": "交通費", "taxi": "タクシー代", "car": "ガソリン・駐車場", "walk": "交通費", "bike": "交通費", "run": "交通費"}
FREE_PARKING = ("park", "riverside", "convenience", "supermarket", "mall", "electronics", "car_dealer", "driving_school", "clinic",
                "office", "hill")

# 位置の決まり: (基準, 最小 km, 最大 km). 基準は station (駅前) か home (あなたの家)
NEAR_STATION = ("shopping_street", "cafe", "drugstore", "bookstore", "teishoku", "ramen", "fastfood", "family", "restaurant")
RULES = dict({k: ("station", 0.08, 0.6) for k in NEAR_STATION},
             town=("station", 0.2, 0.5), park=("home", 0.15, 0.6), convenience=("home", 0.1, 0.45),
             supermarket=("home", 0.25, 0.8), riverside=("home", 0.4, 1.2), clinic=("station", 0.5, 1.8),
             mall=("station", 2.0, 5.0), electronics=("station", 1.8, 4.5), hill=("station", 3.0, 7.0),
             aquarium=("station", 12.0, 35.0), amusement=("station", 12.0, 35.0), beach=("station", 25.0, 60.0),
             mountain=("station", 25.0, 60.0), office=("station", 3.0, 20.0), car_dealer=("station", 2.0, 6.0),
             driving_school=("station", 1.5, 5.0))
HOME_KM = (0.35, 1.15)     # あなたの家と駅の距離
CHAR_NEAR, CHAR_FAR = (0.3, 2.5), (4.0, 20.0)
CHAR_FAR_P = 0.2


def ride_min(km):
    """乗っている時間 (分)."""
    return RIDE_ADD + min(km, 10.0) / RIDE_KMH[0] * 60 + max(0.0, km - 10.0) / RIDE_KMH[1] * 60


def drive_min(km):
    """車で走る時間 (分): 10 km までは街なか, その先は幹線道路."""
    return min(km, 10.0) / 25.0 * 60 + max(0.0, km - 10.0) / 55.0 * 60


def _rush(h):
    return 7 <= h < 9.5 or 17 <= h < 19.5


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

    def _vehicle_ok(self, vid, a):
        """その乗り物で a から出られるか: 持っていて, いま a に置いてある (車は免許も)."""
        app = self.app
        if app.items.count(vid) <= 0 or self.veh_at(vid) != a:
            return False
        return vid != "car" or app.quals.has("drive")

    def veh_at(self, vid):
        """乗り物の置いてある場所 (乗って出かければ, 行った先に置いてある)."""
        return self.rec().setdefault("veh", {}).get(vid, places_mod.HOME_ME)

    @staticmethod
    def parking(pid):
        """車を停めるお金 (行き先ごと. 家・郊外の店・職場はただ)."""
        if places_mod.is_home(pid or "") or pid in FREE_PARKING:
            return 0
        if pid in ("aquarium", "amusement", "beach", "mountain", "hill"):
            return 1000
        return 400

    def options(self, a, b, t=None):
        """a → b の行き方 (目安). {km, modes: {how: {min, fare, ok, note}}, walk, transit, best}.
        modes: walk (いつも) / transit (1.2 km より遠く, 歩くより早ければ) / bike・car (持っていて, a に置いてあれば) / taxi (いつでも. 高い)."""
        t = t or time.time()
        km = self.km(a, b)
        h = _hour(t)
        wet = self._weather(t) in ("rain", "snow")
        walk = self.walk_min(a, b, t)
        modes = {"walk": {"min": round(walk), "fare": 0, "ok": walk <= WALK_MAX_MIN, "note": ""}}
        if km > 1.2:
            pa, pb = self.pt(a), self.pt(b)
            acc = (pa["acc"] + pb["acc"]) * ROAD / WALK_KMH * 60
            hw = headway(h)
            tm = acc + ride_min(km) + (hw or 10) / 2
            if tm < walk * 0.9:
                modes["transit"] = {"min": round(tm), "fare": self.fare(km), "ok": bool(hw), "note": "" if hw else "いまは走っていない（始発は5時）"}
        if km > 0.3 and self._vehicle_ok("bicycle", a):
            m = km / BIKE_KMH * 60 * (1.2 if wet else 1.0)
            modes["bike"] = {"min": round(m), "fare": 0, "ok": m <= BIKE_MAX_MIN, "note": "雨の中を走る" if wet else ""}
        if km > 0.3 and self._vehicle_ok("car", a):
            m = CAR_ADD + drive_min(km) * (JAM if _rush(h) else 1.0)
            modes["car"] = {"min": round(m), "fare": self.gas(km) + self.parking(b), "ok": True, "note": "渋滞" if _rush(h) else ""}
        if km > 0.5:
            night = h >= 22 or h < 5
            m = (15 if night else 7) + drive_min(km) * (JAM if _rush(h) else 1.0)
            fare = int((TAXI_BASE + TAXI_KM * max(0.0, km - 1.0)) * (1.2 if night else 1.0) / 10) * 10
            modes["taxi"] = {"min": round(m), "fare": fare, "ok": True, "note": "深夜料金" if night else ""}
        out = {"km": round(km, 2), "modes": modes, "walk": modes["walk"], "transit": modes.get("transit")}
        out["best"] = self._best(modes)
        return out

    @staticmethod
    def _best(modes):
        """おまかせ: 近ければ歩く (15 分まで). ほかは, 行ける中でいちばん早いもの (タクシーは, ほかに無いときだけ)."""
        if modes["walk"]["ok"] and modes["walk"]["min"] <= 15:
            return "walk"
        ok = [(m["min"], k) for k, m in modes.items() if m["ok"] and k != "taxi"]
        if ok:
            return min(ok)[1]
        return "taxi" if "taxi" in modes else "walk"

    def leg(self, a, b, how, t, rand=True):
        """実際の移動 1 回: {how, min, fare, wait (待った分), note}. 行けなければ ValueError.
        rand: 待ちの揺らぎと, 途中の出来事 (遅延・渋滞・パンク・乗り過ごし) を入れる."""
        r = self._leg(a, b, how, t, rand)
        return self._event(r, a, b, t) if rand else r

    def _event(self, r, a, b, t):
        """移動の途中の出来事 (まれ. 補正なし): 電車・バスの遅延 / 乗り過ごし (疲れているとき) / 車・タクシーの事故渋滞 /
        自転車のパンク (押して歩く. 修理代). 時間とお金が足され, note に残る."""
        how = r["how"]
        h = _hour(t)
        notes = [r["note"]] if r["note"] else []
        if how == "transit":
            if random.random() < (EV_DELAY * 2 if _rush(h) else EV_DELAY):
                d = random.uniform(5, 30)
                r["min"] += d
                notes.append("電車が遅れた（%d分）" % round(d))
            if self.app.life.stamina() < 25 and random.random() < EV_DOZE:
                d = random.uniform(10, 25)
                r["min"] += d
                notes.append("うとうとして乗り過ごした（%d分）" % round(d))
        elif how in ("car", "taxi") and random.random() < EV_JAM:
            d = random.uniform(10, 30)
            r["min"] += d
            r["fare"] += int(d * 40 / 10) * 10 if how == "taxi" else 0
            notes.append("事故で道が混んでいた（%d分）" % round(d))
        elif how == "bike" and random.random() < EV_FLAT:
            part = random.uniform(0.2, 0.8)          # 途中でパンク: 残りは押して歩く
            r["min"] = r["min"] * part + self.walk_min(a, b, t) * (1 - part)
            r["fare"] += FLAT_FIX
            notes.append("自転車がパンクして、押して歩いた（修理代%d円）" % FLAT_FIX)
        r["note"] = "。".join(notes)
        return r

    def _leg(self, a, b, how, t, rand):
        o = self.options(a, b, t)
        if how in (None, "", "auto"):
            how = o["best"]
        if how == "run":
            return {"how": "run", "min": self.walk_min(a, b, t, run=True), "fare": 0, "wait": 0.0, "note": ""}
        modes = o["modes"]
        if how == "transit" and not modes.get("transit"):
            how = "walk"                          # 近すぎる: 歩く
        if how not in modes:
            raise ValueError({"bike": "自転車がここにありません", "car": "車がここにありません（免許も要ります）",
                              "taxi": "タクシーを使うほどの距離ではありません"}.get(how, "その行き方はできません"))
        if how == "walk":
            if not modes["walk"]["ok"]:
                raise ValueError("歩いて行くには遠すぎます（%d分ほど）" % modes["walk"]["min"])
            return {"how": "walk", "min": self.walk_min(a, b, t), "fare": 0, "wait": 0.0, "note": ""}
        if how == "bike":
            if not modes["bike"]["ok"]:
                raise ValueError("自転車で行くには遠すぎます（%d分ほど）" % modes["bike"]["min"])
            return {"how": "bike", "min": float(modes["bike"]["min"]), "fare": 0, "wait": 0.0, "note": modes["bike"]["note"]}
        if how in ("car", "taxi"):
            m = dict(modes[how])
            wait = 0.0
            if how == "taxi" and rand:            # 来るまでの待ち (呼んでから)
                wait = random.uniform(-3, 6)
            return {"how": how, "min": max(3.0, m["min"] + wait), "fare": m["fare"], "wait": max(0.0, wait), "note": m["note"]}
        pa, pb = self.pt(a), self.pt(b)
        km = o["km"]
        acc = (pa["acc"] + pb["acc"]) * ROAD / WALK_KMH * 60
        t_st = t + pa["acc"] * ROAD / WALK_KMH * 3600            # 駅・停留所に着く
        start = first_train(t_st)
        wait = (start - t_st) / 60.0
        hw = headway(_hour(start)) or 10
        wait += random.uniform(0, hw) if rand else hw / 2
        note = "始発を待った" if start > t_st else ""
        return {"how": "transit", "min": acc + wait + ride_min(km), "fare": self.fare(km), "wait": round(wait, 1), "note": note}

    def body_cost(self, lg, a, b):
        """移動 1 回の運動の量と疲れ (歩く・走る・自転車をこぐ分. 電車・バスは駅まで歩く分だけ, 車・タクシーは無し)."""
        from .body import MOVE_PER_H
        how = lg["how"]
        if how in ("car", "taxi"):
            return 0.0, 0.3 * lg["min"] / 60.0
        if how == "transit":
            h = (self.pt(a)["acc"] + self.pt(b)["acc"]) * ROAD / WALK_KMH
        else:
            h = (lg["min"] - lg.get("wait", 0)) / 60.0
        per = {"run": (MOVE_PER_H["jog"], 6.0), "bike": (MOVE_PER_H["walk"] * 1.1, 3.0)}.get(how, (MOVE_PER_H["walk"], 2.5))
        return per[0] * h, per[1] * h

    def used(self, lg, to):
        """自転車・車で行った: 乗り物は行った先に置いてある."""
        if lg["how"] in ("bike", "car"):
            self.rec().setdefault("veh", {})["bicycle" if lg["how"] == "bike" else "car"] = to
            self.save()

    def vehicles_view(self, now=None):
        """持っている乗り物と, どこに置いてあるか (画面)."""
        app = self.app
        here = self.where(now)
        out = {}
        for vid, label in (("bicycle", "自転車"), ("car", "車")):
            if app.items.count(vid) > 0:
                at = self.veh_at(vid)
                out[vid] = {"label": label, "at": at, "at_label": app.places.label(at) if at != places_mod.HOME_ME else "家",
                            "here": at == here, "ok": self._vehicle_ok(vid, here)}
        return {"own": out, "license": app.quals.has("drive")}

    @staticmethod
    def gas(km):
        return int(GAS_PER_KM * km / 10) * 10

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
            app.life.move(None, dp=-lg["fare"], cat="transport", note="%s（%s）" % (FARE_NOTE[lg["how"]], app.places.label(to)))
        ex, tired = self.body_cost(lg, frm, to)
        app.body.add_exercise(ex)
        app.life.tire(tired)
        self.used(lg, to)
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
            return {"text": "（家に着いた%s）" % ("。" + tr["note"] if tr.get("note") else ""), "act": r}
        p["pos"], p["arrived"] = tr["to"], tr["arr"]
        app.presence.save()
        label = app.places.label(tr["to"])
        then = tr.get("then")
        if then:
            r = app.solo.arrive_then(then, tr["to"], tr["arr"])
            if r:
                return dict(r, text=r.get("done") or r.get("text") or "（%sに着いた）" % label)
        text = "%sに着いた%s" % (label, "（%s）" % tr["note"] if tr.get("note") else "")
        app.solo.note("out", text, tr["arr"])
        return {"text": "（%s）" % text}

    # ------------------------------------------------------------------ 画面
    def view(self, now=None):
        now = now or time.time()
        tr = self.travel()
        if not tr:
            return None
        return {"to": tr["to"], "from": tr["from"], "t0": tr["t0"], "label": self.app.places.label(tr["to"]) if tr["dir"] == "go" else "家",
                "how": tr["how"], "how_label": HOW_LABEL.get(tr["how"], ""), "dir": tr["dir"],
                "remain": max(0, int(tr["arr"] - now)), "arr": tr["arr"], "fare": tr["fare"], "note": tr.get("note", "")}

    def map_view(self, ids, now=None):
        """地図に出す点: 駅前・あなたの家・行き先・職場 (と, 表にある相手の家). {id: [x, y]} (km)."""
        out = {}
        for pid in ["station", places_mod.HOME_ME, "office"] + list(ids):
            try:
                out[pid] = self.pt(pid)["xy"]
            except Exception:  # noqa: BLE001
                continue
        return out

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
            out[pid] = {"walk": o["walk"], "transit": o["transit"], "modes": o["modes"], "best": o["best"], "km": o["km"]}
        return out
