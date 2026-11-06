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
from datetime import datetime, timedelta

from . import places as places_mod
from . import store
from . import transit as transit_mod

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
        self.last_refund = 0         # 直前に移動を途中でやめたとき, 払わずに済んだ分 (画面の文に)
        self.transit = transit_mod.Transit(self)

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
        if pid.startswith("pt:"):               # 移動の途中の地点 ("pt:x,y" / 駅で降りたところなら "pt:x,y,0.05". 覚えておかない)
            v = [float(x) for x in pid[3:].split(",")]
            return {"xy": v[:2], "acc": v[2] if len(v) > 2 else 0.3}
        if pid.startswith("st:") or pid == "st":
            st = self.transit.net()["stations"].get(pid)
            if st:
                return {"xy": st["xy"], "acc": 0.0}
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
        modes = {"walk": {"min": round(walk), "fare": 0, "ok": walk <= WALK_MAX_MIN,
                          "note": "" if walk <= WALK_MAX_MIN else "歩いて行くには遠すぎる（%d時間を超える）" % (WALK_MAX_MIN // 60)}}
        routes = self.routes(a, b, t) if km > 1.2 else []
        if routes and routes[0]["min"] < walk * 0.9:
            r0 = routes[0]
            modes["transit"] = {"min": r0["min"], "fare": r0["fare"], "ok": True, "note": r0["note"]}
        elif km > 1.2 and not routes and walk > 30:
            modes["transit"] = {"min": 0, "fare": 0, "ok": False, "note": "いまは電車・バスで行けない（走っていない時間）"}
        if km > 0 and self._vehicle_ok("bicycle", a):      # 自転車は近場でも乗れる
            m = km / BIKE_KMH * 60 * (1.2 if wet else 1.0)
            modes["bike"] = {"min": round(m), "fare": 0, "ok": m <= BIKE_MAX_MIN,
                             "note": ("自転車で行くには遠すぎる（%d分を超える）" % BIKE_MAX_MIN) if m > BIKE_MAX_MIN else "雨の中を走る" if wet else ""}
        elif km > 0 and self.app.items.count("bicycle") > 0:  # 持っているが, ここには無い: どこに置いてあるかを出す (行けば乗れる)
            m = km / BIKE_KMH * 60 * (1.2 if wet else 1.0)
            modes["bike"] = {"min": round(m), "fare": 0, "ok": False,
                             "note": "自転車は%sに置いてある" % self.app.places.label(self.veh_at("bicycle"))}
        if km > 0.3 and self._vehicle_ok("car", a):
            m = CAR_ADD + drive_min(km) * (JAM if _rush(h) else 1.0)
            modes["car"] = {"min": round(m), "fare": self.gas(km) + self.parking(b), "ok": True, "note": "渋滞" if _rush(h) else ""}
        elif km > 0.3 and self.app.items.count("car") > 0 and self.app.quals.has("drive"):   # 持っているが, ここには無い
            m = CAR_ADD + drive_min(km) * (JAM if _rush(h) else 1.0)
            modes["car"] = {"min": round(m), "fare": self.gas(km) + self.parking(b), "ok": False,
                            "note": "車は%sに置いてある" % self.app.places.label(self.veh_at("car"))}
        if km > 0.5:
            night = h >= 22 or h < 5
            m = (15 if night else 7) + drive_min(km) * (JAM if _rush(h) else 1.0)
            fare = int((TAXI_BASE + TAXI_KM * max(0.0, km - 1.0)) * (1.2 if night else 1.0) / 10) * 10
            modes["taxi"] = {"min": round(m), "fare": fare, "ok": True, "note": "深夜料金" if night else ""}
        out = {"km": round(km, 2), "modes": modes, "walk": modes["walk"], "transit": modes.get("transit"),
               "routes": [self.route_view(r, t) for r in routes]}
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
                self._delay(r, d)
                notes.append("電車が遅れた（%d分）" % round(d))
            if self.app.life.stamina() < 25 and random.random() < EV_DOZE:
                d = random.uniform(10, 25)
                self._delay(r, d)
                notes.append("うとうとして乗り過ごした（%d分）" % round(d))
        elif how in ("car", "taxi") and random.random() < EV_JAM:
            d = random.uniform(10, 30)
            r["min"] += d
            r["fare"] += int(d * 40 / 10) * 10 if how == "taxi" else 0
            notes.append("事故で道が混んでいた（%d分）" % round(d))
        elif how == "bike" and random.random() < EV_FLAT:
            part = random.uniform(0.2, 0.8)          # 途中でパンク: 残りは押して歩く
            r["flat"] = [r["min"] * part, self.walk_min(a, b, t) * (1 - part)]     # こいだ分 / 押して歩いた分 (区間の表示に)
            r["min"] = sum(r["flat"])
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
        if how not in modes and not str(how).startswith("route:"):       # route:<n> は経路の候補 (下の電車・バスで)
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
        rs = self.routes(a, b, t)
        if not rs:
            raise ValueError("電車・バスで行ける経路がありません（走っていない時間か、駅から遠すぎます）")
        r = rs[0]
        if str(how).startswith("route:"):
            r = next((x for x in rs if x["key"] == how), r)
        return self.route_leg(r, t)

    # ------------------------------------------------------------------ 経路 (A8. core/transit.py)
    def _taxi(self, km, t):
        h = _hour(t)
        night = h >= 22 or h < 5
        m = (15 if night else 7) + drive_min(km) * (JAM if _rush(h) else 1.0)
        return m, int((TAXI_BASE + TAXI_KM * max(0.0, km - 1.0)) * (1.2 if night else 1.0) / 10) * 10

    def _ends(self, pid, t, side, taxi):
        """駅・停留所との行き来の候補: {駅: (分, 円, 区間の種類, 乗り物)} (side: access = 出るところから / egress = 行き先まで)."""
        T = self.transit
        net = T.net()
        xy = self.pt(pid)["xy"]
        out = {}
        bike_here = side == "access" and self._vehicle_ok("bicycle", pid)
        car_here = side == "access" and self._vehicle_ok("car", pid)
        wet = self._weather(t) in ("rain", "snow")
        for sid, stn in net["stations"].items():
            if sid == pid:
                out[sid] = (0.0, 0, "walk", None)
                continue
            km = math.hypot(stn["xy"][0] - xy[0], stn["xy"][1] - xy[1]) * ROAD
            c = []
            wm = km / WALK_KMH * 60 * (1.15 if wet else 1.0)
            if wm <= transit_mod.ACCESS_WALK_MAX:
                c.append((wm, 0, "walk", None))
            if side == "access":
                if bike_here and km > 0.3:
                    c.append((km / BIKE_KMH * 60 * (1.2 if wet else 1.0), transit_mod.BIKE_PARK, "bike", "bicycle"))
                if car_here and km > 0.5:
                    c.append((CAR_ADD + drive_min(km), transit_mod.CAR_PARK, "car", "car"))
            else:                        # 駅に置いてある自転車・車で, 行き先まで
                if self.veh_at("bicycle") == sid and self.app.items.count("bicycle") > 0 and km > 0.3:
                    c.append((km / BIKE_KMH * 60, 0, "bike", "bicycle"))
                if self.veh_at("car") == sid and self.app.items.count("car") > 0 and self.app.quals.has("drive") and km > 0.5:
                    c.append((CAR_ADD + drive_min(km), self.parking(pid), "car", "car"))
            if taxi and km > 0.8:
                m, f = self._taxi(km, t)
                c.append((m, f, "taxi", None))
            if c:
                out[sid] = min(c, key=lambda x: (x[0], x[1]))
        return out

    VARIANTS = (("auto", "おまかせ", False, transit_mod.TRANSFER_BUF), ("few", "乗り換え少なめ", False, 15.0),
                ("taxi", "タクシーも使う", True, transit_mod.TRANSFER_BUF))

    def routes(self, a, b, t):
        """a → b の電車・バスを使う経路の候補 (速い順. 同じ乗り方は 1 つ). 各 {key, label, legs, t_arr, min, fare, transfers, note}."""
        T = self.transit
        out = []
        seen = set()
        egress_cache = {}
        for vi, (vk, label, taxi, tbuf) in enumerate(self.VARIANTS):
            ck = (store.WORLD, a, int(t // 60), vk, self.veh_at("bicycle"), self.veh_at("car"))
            sc = T._csa.get(ck)
            if sc is None:
                acc = {}
                for sid, (m, f, kind, veh) in self._ends(a, t, "access", taxi).items():
                    acc[sid] = (t + m * 60, [{"kind": kind, "from": a, "to": sid, "t0": t, "t1": t + m * 60, "fare": f, "veh": veh}])
                sc = T.scan(self.pt(a)["xy"], t, acc, transfer=tbuf)
                if len(T._csa) > 300:
                    T._csa.clear()
                T._csa[ck] = sc
            arr, how = sc
            if taxi not in egress_cache:
                egress_cache[taxi] = self._ends(b, t, "egress", taxi)
            eg = egress_cache[taxi]
            best = None
            for sid, at in arr.items():
                if sid not in eg or how[sid][0] == "access":
                    continue
                m, f, kind, veh = eg[sid]
                if best is None or at + m * 60 < best[0]:
                    best = (at + m * 60, sid, (m, f, kind, veh))
            if not best:
                continue
            t_arr, sid, (m, f, kind, veh) = best
            legs = T.journey(how, sid)
            legs.append({"kind": kind, "from": sid, "to": b, "t0": arr[sid], "t1": t_arr, "fare": f, "veh": veh})
            sig = tuple((lg["kind"], lg.get("line"), lg["to"]) for lg in legs if lg["kind"] != "wait")
            if sig in seen:
                continue
            seen.add(sig)
            fare = self._route_fare(legs)
            rides = [lg for lg in legs if lg["kind"] == "ride"]
            out.append({"key": "route:%d" % vi, "label": label, "legs": legs, "t_arr": t_arr, "min": max(1, round((t_arr - t) / 60)),
                        "fare": fare, "transfers": max(0, len(rides) - 1), "note": self._route_note(legs, t)})
        auto = next((r for r in out if r["key"] == "route:0"), None)
        km = self.km(a, b)
        tx_m, tx_f = self._taxi(km, t)

        def keep(r):
            if r["key"] != "route:2":
                return True        # タクシーも使う: おまかせより 5 分以上早く, タクシーだけより安く・早くないと出さない
            return (auto is None or r["t_arr"] <= auto["t_arr"] - 300) and r["fare"] < tx_f and r["t_arr"] < t + tx_m * 60
        return [r for r in out if keep(r)]

    def _route_fare(self, legs):
        """経路の代金: 鉄道は続けて乗った距離で (乗り換えても一つの運賃), バスは 1 回ごと, ほかは区間の代金 (駐輪・駐車・タクシー)."""
        T = self.transit
        net = T.net()
        tot, rail_km = 0, 0.0
        for lg in legs:
            if lg["kind"] == "ride":
                ln = T.line(lg["line"])
                if ln["kind"] == "rail":
                    pa, pb = net["stations"][lg["from"]]["xy"], net["stations"][lg["to"]]["xy"]
                    rail_km += math.hypot(pb[0] - pa[0], pb[1] - pa[1]) * 1.1
                    continue
                tot += transit_mod.BUS_FARE
            elif lg["kind"] != "wait":
                tot += int(lg.get("fare") or 0)
            if rail_km and lg["kind"] != "wait":
                tot += T.fare_rail(rail_km)
                rail_km = 0.0
        if rail_km:
            tot += T.fare_rail(rail_km)
        return tot

    def _route_note(self, legs, t):
        first = next((lg for lg in legs if lg["kind"] == "ride"), None)
        if not first:
            return ""
        w = (first["t0"] - t) / 60.0
        dep = datetime.fromtimestamp(first["t0"]).strftime("%H:%M")
        return "%s発%s" % (dep, "（始発を待つ）" if w > 90 else "")

    def leg_label(self, lg):
        T = self.transit
        net = T.net()
        nm = lambda pid: net["stations"][pid]["name"] if pid in net["stations"] else self.app.places.label(pid)   # noqa: E731
        k = lg["kind"]
        if k == "ride":
            ln = T.line(lg["line"])
            return "%s（%s→%s）" % (ln["name"], nm(lg["from"]), nm(lg["to"]))
        if k == "wait":
            return "%sで待つ" % nm(lg["from"])
        to = nm(lg["to"]) if lg["to"] in net["stations"] else None
        frm = nm(lg["from"]) if lg["from"] in net["stations"] else None
        word = {"walk": "歩く", "bike": "自転車", "car": "車", "taxi": "タクシー"}.get(k, k)
        if to and not frm:
            return "%sまで%s" % (to, word if k != "walk" else "歩く")
        if frm and not to:
            return "降りて%s" % ("歩く" if k == "walk" else word + "で")
        return "乗り換え（歩く）" if k == "walk" else word

    def route_view(self, r, t):
        """画面に出す経路: {key, label, min, fare, transfers, note, dep, arr, steps: [{kind, label, min, t0}]}."""
        steps = [{"kind": lg["kind"], "label": self.leg_label(lg), "min": max(1, round((lg["t1"] - lg["t0"]) / 60)),
                  "t0": lg["t0"], "line_kind": self.transit.line(lg["line"])["kind"] if lg["kind"] == "ride" else None}
                 for lg in r["legs"] if lg["t1"] - lg["t0"] >= 30 or lg["kind"] == "ride"]
        return {"key": r["key"], "label": r["label"], "min": r["min"], "fare": r["fare"], "transfers": r["transfers"],
                "note": r["note"], "dep": t, "arr": r["t_arr"], "steps": steps}

    def latest_departure(self, a, b, arrive):
        """arrive までに着く, いちばん遅い出発 (電車・バス. おまかせの経路で). (出発時刻, 経路) か None."""
        lo, hi = arrive - 8 * 3600, arrive
        best = None
        for _ in range(12):
            mid = (lo + hi) / 2.0
            rs = [r for r in self.routes(a, b, mid) if r["key"] == "route:0"]
            if rs and rs[0]["t_arr"] <= arrive:
                best, lo = (mid, rs[0]), mid
            else:
                hi = mid
            if hi - lo < 60:
                break
        return best

    def last_departure(self, a, b, t):
        """t から, その運行日 (翌 4 時まで) のうちに電車・バスで行ける, いちばん遅い出発 (終電・終バスに乗る). (出発時刻, 経路) か None."""
        day = transit_mod.service_day(t)
        end = datetime(day.year, day.month, day.day, transit_mod.DAY_START).timestamp() + 86400

        def ok(x):
            rs = [r for r in self.routes(a, b, x) if r["key"] == "route:0"]
            return rs[0] if rs and all(lg["t1"] <= end for lg in rs[0]["legs"] if lg["kind"] == "ride") else None
        best = None
        r0 = ok(t)
        if not r0:
            return None
        best, lo, hi = (t, r0), t, end
        for _ in range(14):
            mid = (lo + hi) / 2.0
            r = ok(mid)
            if r:
                best, lo = (mid, r), mid
            else:
                hi = mid
            if hi - lo < 60:
                break
        return best

    def route_search(self, to, at=None, by="depart"):
        """画面の経路検索: いまいる場所から to へ. by = now (いま出る) / depart (at に出る) / arrive (at までに着く) /
        first (始発で: 次の朝 4 時から) / last (終電で: いまから, その日のうちに行けるいちばん遅い出発)."""
        now = time.time()
        frm = self.where(now)
        at = float(at or now)
        if by == "now":
            at, by = now, "depart"
        if by == "first":
            d = datetime.fromtimestamp(now)
            d4 = d.replace(hour=transit_mod.DAY_START, minute=0, second=0, microsecond=0)
            at = (d4 if d.hour < transit_mod.DAY_START else d4 + timedelta(days=1)).timestamp()
            rs = self.routes(frm, to, at)
            return {"by": by, "at": at, "routes": [self.route_view(r, at) for r in rs if r["key"] == "route:0"],
                    "note": "始発で: %s" % datetime.fromtimestamp(at).strftime("%m/%d")}
        if by == "last":
            hit = self.last_departure(frm, to, now)
            if not hit:
                return {"by": by, "at": now, "routes": [], "note": "今日はもう電車・バスで行けません（始発を待つか、タクシー）"}
            t, r = hit
            return {"by": by, "at": t, "depart": t, "routes": [self.route_view(r, t)],
                    "note": "終電で行くなら、%sまでに出る" % datetime.fromtimestamp(t).strftime("%H:%M")}
        if by == "arrive":
            hit = self.latest_departure(frm, to, at)
            if not hit:
                return {"by": by, "at": at, "routes": [], "note": "その時刻までに着く電車・バスの経路がありません"}
            t, r = hit
            return {"by": by, "at": at, "depart": t, "routes": [self.route_view(r, t)],
                    "note": "%sに出れば間に合う" % datetime.fromtimestamp(t).strftime("%H:%M")}
        return {"by": by, "at": at, "routes": [self.route_view(r, at) for r in self.routes(frm, to, at)], "note": ""}

    def route_leg(self, r, t):
        """経路を, 移動 1 回 (leg) の形に."""
        wait = sum((lg["t1"] - lg["t0"]) / 60.0 for lg in r["legs"] if lg["kind"] == "wait")
        legs = [dict(lg) for lg in r["legs"]]
        return {"how": "transit", "min": (r["t_arr"] - t) / 60.0, "fare": r["fare"], "wait": round(wait, 1),
                "note": "始発を待った" if wait > 90 else "", "legs": legs, "route": r["key"]}

    @staticmethod
    def _delay(r, d):
        """遅れ d 分: 最初に乗る区間から先を後ろへずらす."""
        r["min"] += d
        legs = r.get("legs")
        if not legs:
            return
        hit = False
        for lg in legs:
            if lg["kind"] == "ride" and not hit:
                hit = True
                lg["t1"] += d * 60
                continue
            if hit:
                lg["t0"] += d * 60
                lg["t1"] += d * 60

    def leg_at(self, tr, now):
        """経路の移動で, いまいる区間 (無ければ None)."""
        legs = tr.get("legs")
        if not legs:
            return None
        for lg in legs:
            if now < lg["t1"]:
                return lg
        return legs[-1]

    def body_cost(self, lg, a, b):
        """移動 1 回の運動の量と疲れ (歩く・走る・自転車をこぐ分. 電車・バスは駅まで歩く分だけ, 車・タクシーは無し)."""
        from .body import MOVE_PER_H
        how = lg["how"]
        if lg.get("legs"):                       # 経路: 歩いた・こいだ区間の分
            from .body import MOVE_PER_H
            ex = tired = 0.0
            for x in lg["legs"]:
                h = (x["t1"] - x["t0"]) / 3600.0
                if x["kind"] == "walk":
                    ex, tired = ex + MOVE_PER_H["walk"] * h, tired + 2.5 * h
                elif x["kind"] == "bike":
                    ex, tired = ex + MOVE_PER_H["walk"] * 1.1 * h, tired + 3.0 * h
                elif x["kind"] in ("car", "taxi", "ride"):
                    tired += 0.3 * h
            return ex, tired
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
        if lg.get("legs"):                       # 経路: 自転車・車で駅まで行けば駅に, 駅から乗れば行き先に
            for x in lg["legs"]:
                if x.get("veh"):
                    self.rec().setdefault("veh", {})[x["veh"]] = x["to"]
            self.save()
            return
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

    def midway(self, now=None):
        """移動中の, いまの地点 ("pt:x,y". 進み具合で, 出たところと行き先の間). 移動していなければ None."""
        now = now or time.time()
        tr = self.travel()
        if not tr or now >= tr["arr"]:
            return None
        lg = self.leg_at(tr, now)
        if lg:                                   # 経路: いまいる区間の中で (待っていれば駅, 乗っていれば次の駅で降りる)
            if lg["kind"] == "wait" or now <= lg["t0"]:
                return lg["from"]
            k = max(0.0, min(1.0, (now - lg["t0"]) / max(1.0, lg["t1"] - lg["t0"])))
            if lg["kind"] == "ride":
                seq = self.transit.line(lg["line"])["seq"]
                i0, i1 = seq.index(lg["from"]), seq.index(lg["to"])
                path = seq[i0:i1 + 1] if i0 <= i1 else seq[i1:i0 + 1][::-1]
                return path[min(len(path) - 1, max(1, int(math.ceil(k * (len(path) - 1)))))]     # 次の駅で降りる
            if k <= 0.02:
                return lg["from"]
            if k >= 0.98:
                return lg["to"]
            a, b = self.pt(lg["from"])["xy"], self.pt(lg["to"])["xy"]
            return "pt:%.3f,%.3f" % (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)
        ph = self.phase(now)
        if ph:                                   # 電車・バス: 乗る前ならまだ出たところ, 乗っていれば次の駅で降りる, 降りたあとなら行き先のそば
            kind, k = ph
            if kind == "pre":
                return tr["from"]
            if kind == "post":
                return tr["to"]
            a, b = self.pt(tr["from"])["xy"], self.pt(tr["to"])["xy"]
            return "pt:%.3f,%.3f,0.05" % (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)
        k = max(0.0, min(1.0, (now - tr["t0"]) / max(1.0, tr["arr"] - tr["t0"])))
        if k <= 0.02:
            return tr["from"]
        a, b = self.pt(tr["from"])["xy"], self.pt(tr["to"])["xy"]
        return "pt:%.3f,%.3f" % (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)

    def segs(self, lg, frm, to):
        """移動 1 回の区間 [[種類, 分, ことば]] (画面で, いまどの区間かを出す). 種類: walk / wait / ride / bike / run / car / taxi.
        電車・バス: 駅・停留所まで歩く → 待つ → 乗る → 降りて歩く. タクシー: 来るまで待つ → 乗る. ほかは 1 区間."""
        how, tot = lg["how"], float(lg["min"])
        if lg.get("legs"):
            return [[x["kind"], round((x["t1"] - x["t0"]) / 60.0, 1), self.leg_label(x)] for x in lg["legs"]
                    if x["t1"] - x["t0"] >= 30 or x["kind"] == "ride"] or [["walk", round(tot, 1), "移動している"]]
        if how == "transit":
            a = self.pt(frm)["acc"] * ROAD / WALK_KMH * 60
            b = self.pt(to)["acc"] * ROAD / WALK_KMH * 60
            w = float(lg.get("wait", 0))
            out = [["walk", a, "駅・停留所まで歩く"], ["wait", w, "始発を待つ" if "始発" in (lg.get("note") or "") else "駅で待つ"],
                   ["ride", max(1.0, tot - a - w - b), "電車・バスに乗っている"], ["walk", b, "降りて歩く"]]
        elif how == "bike" and lg.get("flat"):
            out = [["bike", lg["flat"][0], "自転車に乗っている"], ["walk", lg["flat"][1], "パンクした自転車を押して歩く"]]
        elif how == "taxi":
            w = float(lg.get("wait", 0))
            out = [["wait", w, "タクシーを待つ"], ["taxi", tot - w, "タクシーに乗っている"]]
        else:
            out = [[how, tot, {"walk": "歩いている", "run": "走っている", "bike": "自転車に乗っている", "car": "車を運転している"}.get(how, "移動している")]]
        return [[k, round(m, 1), t] for k, m, t in out if m >= 0.5] or [[how, round(tot, 1), "移動している"]]

    SEATED = ("wait", "ride", "taxi")      # 移動中に読める・観られる区間 (駅で待つ・乗っている. 歩く・こぐ・運転中は無理)

    def can_read(self, tr=None):
        """いまの移動で, 読む・観ることができるか (電車・バス・タクシー)."""
        tr = tr or self.travel()
        return bool(tr) and tr.get("how") in ("transit", "taxi")

    def seated_h(self, tr, t0, t1):
        """t0〜t1 のうち, 座って (待って) いられた時間 (時間)."""
        segs = tr.get("segs") or []
        if not segs:
            return 0.0
        tot = sum(m for _, m, _ in segs) or 1e-6
        span = max(1.0, tr["arr"] - tr["t0"])
        acc, out = 0.0, 0.0
        for k, m, _ in segs:
            a = tr["t0"] + acc / tot * span
            b = tr["t0"] + (acc + m) / tot * span
            acc += m
            if k in self.SEATED:
                out += max(0.0, min(b, t1) - max(a, t0))
        return out / 3600.0

    def set_doing(self, what, now=None):
        """移動中にすること: read (小説の続き・ジャンル) / movie (映画の続き. スマホで) / book:<技能> (技能の本で研鑽) / None (やめる).
        着いたとき (やめたとき) に, 座っていられた時間ぶん進む."""
        now = now or time.time()
        tr = self.travel()
        if not tr or now >= tr["arr"]:
            raise ValueError("移動中ではありません")
        if not self.can_read(tr):
            raise ValueError("%sで移動しているので、読んだり観たりはできません" % HOW_LABEL.get(tr["how"], ""))
        note = self.finish_doing(tr, now)          # 前にしていたことは, ここまでの分
        if what:
            w = str(what)
            app = self.app
            if w.startswith("book:"):
                from .items import PRACTICE_BOOK
                if app.items.count(PRACTICE_BOOK.get(w[5:], "")) <= 0:
                    raise ValueError("その本を持っていません")
            elif w.startswith("read") and app.items.count("novel") <= 0 and not app.life.player_state().get("reading"):
                raise ValueError("読む本がない（小説は本屋や駅前などで買えます）")
            elif not (w.startswith("read") or w.startswith("movie")):
                raise ValueError("移動中にできることではありません")
            tr["doing"] = {"what": w, "t": now}
        self.app.presence.save()
        return {"doing": tr.get("doing"), "done": note}

    def finish_doing(self, tr, t_end):
        """移動中にしていたことを, 座っていられた時間ぶん進める. 文を返す (何もしていなければ None)."""
        d = tr.pop("doing", None)
        if not d:
            return None
        h = self.seated_h(tr, d["t"], min(t_end, tr["arr"]))
        if h < 1 / 60.0:
            return None
        app = self.app
        w = d["what"]
        g = w.split(":", 1)[1] if ":" in w else None
        if w.startswith("book:"):
            from .solo import SKILL_LABEL
            gain = app.life.train(g, min(3.0, 1.2 * h) * 1.2) if h >= 0.25 else 0
            text = "移動中に%sの本を読んだ（%d分）%s" % (SKILL_LABEL.get(g, g), round(h * 60), "" if gain >= 0.1 else "。あまり頭に入らなかった")
        elif w.startswith("read"):
            text = "移動中に" + app.topics.read(h, t_end, 1.5, genre=g)
        else:
            text = "移動中にスマホで" + app.topics.watch(h, t_end, 2.0, genre=g).replace("家で", "")
        app.solo.note("read" if not w.startswith("movie") else "movie", text, t_end)
        return text

    def seg_now(self, tr, now):
        """いまの区間の番号と, その区間の残り (秒). 遅れなどで全体が延びた分は, 全体にならす."""
        segs = tr.get("segs") or []
        if not segs:
            return None, 0
        tot = sum(m for _, m, _ in segs) or 1e-6
        span = max(1.0, tr["arr"] - tr["t0"])
        e = (now - tr["t0"]) / span * tot
        acc = 0.0
        for i, (_, m, _) in enumerate(segs):
            if e < acc + m or i == len(segs) - 1:
                return i, max(0, int((acc + m - e) * span / tot))
            acc += m
        return len(segs) - 1, 0

    def phase(self, now=None):
        """電車・バスで移動中の段階: ("pre", 0) 駅へ歩く・待つ / ("ride", 進み具合) 乗っている / ("post", 1) 降りて歩く. 電車・バスでなければ None."""
        now = now or time.time()
        tr = self.travel()
        if not tr or tr.get("how") != "transit" or not tr.get("ph"):
            return None
        pre, ride, post = tr["ph"]
        tot = pre + ride + post
        e = (now - tr["t0"]) / 60.0 * tot / max(1e-6, (tr["arr"] - tr["t0"]) / 60.0)    # 遅れなどで延びた分は, 全体にならす
        if e < pre:
            return ("pre", 0.0)
        if e < pre + ride:
            return ("ride", (e - pre) / ride)
        return ("post", 1.0)

    def cut(self, now=None):
        """移動をそこでやめる (行き先を変える・引き返す). いまの地点を返す. 自転車・車なら, 乗り物もそこに."""
        now = now or time.time()
        tr = self.travel()
        if not tr:
            return self.where(now)
        here = self.midway(now) or tr["to"]
        self.finish_doing(tr, now)                    # 移動中に読んでいた・観ていた分は, ここまで
        back = self.last_refund = self.unused_fare(tr, now)
        if back > 0:                             # 乗らなかった分 (電車・バスは乗った区間だけ, タクシー・車は走った分だけ払う)
            self.app.life.move(None, dp=back, cat="transport", note="%s（途中でやめた分）" % FARE_NOTE[tr["how"]])
        if tr.get("legs"):                       # 経路: まだ乗っていない乗り物は出たところ, 乗っている途中ならここ
            for x in tr["legs"]:
                if x.get("veh"):
                    self.rec().setdefault("veh", {})[x["veh"]] = x["from"] if now <= x["t0"] else here if now < x["t1"] else x["to"]
            self.save()
        elif tr["how"] in ("bike", "car"):
            self.rec().setdefault("veh", {})["bicycle" if tr["how"] == "bike" else "car"] = here
            self.save()
        self.rec_p().pop("travel", None)
        self.rec_p()["pos"] = here
        return here

    def unused_fare(self, tr, now):
        """途中でやめたとき, 払わずに済む分 (円)."""
        fare = int(tr.get("fare") or 0)
        if fare <= 0 or now >= tr["arr"]:
            return 0
        if tr.get("legs"):                       # 経路: まだ乗っていない区間は払わない. 乗っている区間は乗った分だけ
            T = self.transit
            net = T.net()
            back = 0
            for x in tr["legs"]:
                if x["kind"] == "ride":
                    ln = T.line(x["line"])
                    pa, pb = net["stations"][x["from"]]["xy"], net["stations"][x["to"]]["xy"]
                    full = T.fare_rail(math.hypot(pb[0] - pa[0], pb[1] - pa[1]) * 1.1) if ln["kind"] == "rail" else transit_mod.BUS_FARE
                    if now <= x["t0"]:
                        back += full
                    elif now < x["t1"] and ln["kind"] == "rail":
                        k = (now - x["t0"]) / max(1.0, x["t1"] - x["t0"])
                        back += max(0, full - T.fare_rail(math.hypot(pb[0] - pa[0], pb[1] - pa[1]) * 1.1 * k))
                elif x["kind"] != "wait" and now <= x["t0"]:
                    back += int(x.get("fare") or 0)
            return min(fare, back)
        if tr["how"] == "transit":
            ph = self.phase(now)
            if not ph or ph[0] == "post":
                return 0
            if ph[0] == "pre":
                return fare                      # まだ乗っていない
            return max(0, fare - self.fare(self.km(tr["from"], tr["to"]) * ph[1]))
        if tr["how"] in ("taxi", "car"):
            k = max(0.0, min(1.0, (now - tr["t0"]) / max(1.0, tr["arr"] - tr["t0"])))
            park = self.parking(tr["to"]) if tr["how"] == "car" else 0
            return int((fare - park) * (1 - k) / 10) * 10 + park
        return 0

    def where(self, now=None):
        """いまいる場所 (移動中なら, 途中のいまの地点)."""
        app = self.app
        now = now or time.time()
        p = self.rec_p()
        tr = p.get("travel")
        if tr:
            return self.midway(now) or tr["to"]
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
        if lg.get("legs"):                       # 経路の区間 (途中で降りる・置いた乗り物・区間の表示に)
            p["travel"]["legs"] = lg["legs"]
            p["travel"]["arr"] = max(p["travel"]["arr"], lg["legs"][-1]["t1"])
        elif lg["how"] == "transit":               # 駅まで歩いて待つ / 乗っている / 降りて歩く (途中で行き先を変えるときの居場所)
            pre = self.pt(frm)["acc"] * ROAD / WALK_KMH * 60 + lg.get("wait", 0)
            post = self.pt(to)["acc"] * ROAD / WALK_KMH * 60
            p["travel"]["ph"] = [round(pre, 1), round(max(1.0, lg["min"] - pre - post), 1), round(post, 1)]
        p["travel"]["segs"] = self.segs(lg, frm, to)
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
        if p.get("travel"):                      # 行く途中で引き返す: いまの地点から
            frm = self.cut(now)
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
        frm = (self.midway(t) or tr["to"]) if tr else self.where(t)
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
        did = self.finish_doing(tr, tr["arr"])        # 移動中に読んでいた・観ていた
        if did:
            tr["note"] = "。".join(x for x in (tr.get("note"), did) if x)
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
        seg, seg_remain = self.seg_now(tr, now)
        return {"to": tr["to"], "from": tr["from"], "t0": tr["t0"], "label": self.app.places.label(tr["to"]) if tr["dir"] == "go" else "家",
                "from_label": self.app.places.label(tr["from"]) if tr["from"] != places_mod.HOME_ME else "家",
                "how": tr["how"], "how_label": HOW_LABEL.get(tr["how"], ""), "dir": tr["dir"],
                "remain": max(0, int(tr["arr"] - now)), "arr": tr["arr"], "fare": tr["fare"], "note": tr.get("note", ""),
                "segs": [{"kind": k, "min": max(1, round(m)), "label": t} for k, m, t in tr.get("segs") or []],
                "can_read": self.can_read(tr), "doing": (tr.get("doing") or {}).get("what"),
                "seg": seg, "seg_remain": seg_remain}

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
            out[pid] = {"walk": o["walk"], "transit": o["transit"], "modes": o["modes"], "best": o["best"], "km": o["km"], "routes": o["routes"]}
        return out
