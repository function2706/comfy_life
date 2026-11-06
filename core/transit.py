"""路線と時刻表・経路探索 (A8).

- 路線網 (ワールドごと. geo.json の net に覚える. まだ無いワールドは, はじめて使うときに作る. 場所の位置は変えない):
  鉄道は駅前 (station) から, 遠い行き先 (8 km より遠い: 水族館・遊園地・海・山・遠い職場・遠い相手の家) の方へ 1〜3 本.
  行き先の最寄り駅は, その場所から「最寄りまでの距離 (acc)」だけ駅前寄りの位置. 間は 3 km ほどごとに駅を置き, 先に終点.
  バスは駅前から, 近めの行き先 (0.8〜8 km: モール・家電量販店・病院・車の店 など) とあなたの家のそばを回る 1〜4 系統.
- 時刻表: 路線・方向・平日 / 土休日ごとに, 始発・終電 (終バス)・時間帯ごとの間隔 (朝夕は多く, 夜は少ない) を決める
  (ワールドと路線から決まる乱数. 毎日同じ). 一日は 4 時に切り替わる (0 時台の終電は前の日の便).
- 経路探索 (route): 出発→行き先を, 歩く・自転車・車・タクシーと鉄道・バスの組み合わせで探す (connection scan).
  乗り物 (自転車・車) は置いてある場所からしか乗れず, 駅に置けば駅に残る (駐輪・駐車代). タクシーはどこからでも.
  候補: おまかせ (タクシーを使わない早い経路) / 乗り換え少なめ / タクシーを使う (いちばん早い). 乗り継ぎの区間 (legs) を返す.
"""
import bisect
import math
import random
from datetime import datetime, timedelta

NET_V = 2                            # 路線網の作り方の版 (変えたら, 作り直す)
WALK_KMH = 4.5
ROAD = 1.3
RAIL_KMH, BUS_KMH = 55.0, 18.0
RAIL_FAR = 8.0                       # これより遠い行き先は鉄道で
BUS_NEAR = 0.8
DAY_START = 4                        # 一日の切り替わり (時)
BOARD_BUF, TRANSFER_BUF = 1.0, 3.0   # 乗るまでの余裕・乗り換え (分)
ACCESS_WALK_MAX = 40.0               # 駅・停留所まで歩くのはここまで (分)
BIKE_PARK, CAR_PARK = 150, 600       # 駅に置く代金 (円. 駅前はただの駐輪場はない)
BUS_FARE = 220
LINE_NAMES = ["湾岸線", "山手線", "北部線", "南部線"]
BUS_NAMES = ["市内バス 1 系統", "市内バス 2 系統", "市内バス 3 系統", "市内バス 4 系統"]
STATION_NAMES = ["本町", "桜町", "緑ヶ丘", "東町", "旭", "若葉", "中島", "新田", "青葉台", "松原", "宮前", "柳町", "大川",
                 "川崎台", "南浜", "北原", "西浦", "朝日台", "日の出", "高砂", "元町", "栄町", "寿町", "幸町", "曙町", "錦町",
                 "春日", "平和台", "富士見", "港町", "汐見", "花園", "弥生", "天神", "八幡", "上町", "常盤", "白山", "藤ヶ丘",
                 "梅ヶ丘", "竹の台", "清水", "小川", "森下", "石川", "浜田", "岡本", "原町", "野中"]


def _hm(m):
    m = int(round(m))
    return ("翌" if m >= 24 * 60 else "") + "%d:%02d" % (m // 60 % 24, m % 60)


def service_day(t):
    """t が属する運行日 (date). 4 時より前は前の日の便."""
    d = datetime.fromtimestamp(t)
    if d.hour < DAY_START:
        d -= timedelta(days=1)
    return d.date()


def holiday(day):
    return day.weekday() >= 5


class Transit:
    def __init__(self, geo):
        self.geo = geo
        self._conn = {}
        self._csa = {}

    # ------------------------------------------------------------------ 路線網
    def net(self):
        r = self.geo.rec()
        if (r.get("net") or {}).get("v") != NET_V:
            r["net"] = self._build()
            self.geo.save()
            self._conn.clear()
            self._csa.clear()
        return r["net"]

    def _build(self):
        from . import places as places_mod
        from .store import WORLD
        geo = self.geo
        rnd = random.Random("net:%s" % WORLD)
        geo.ensure()
        pts = geo.rec()["pts"]
        hub = [0.0, 0.0]
        rail_t, bus_t = [], []
        for pid, p in pts.items():
            if pid in ("station",) or pid.startswith("pt:"):
                continue
            d0 = math.hypot(*p["xy"])
            if pid == places_mod.HOME_ME:
                if d0 >= BUS_NEAR:
                    bus_t.append((pid, p, 0.15))
                continue
            if d0 >= RAIL_FAR:
                rail_t.append((pid, p, min(p.get("acc", 0.4), 0.9)))
            elif d0 >= BUS_NEAR and not places_mod.is_home(pid):
                bus_t.append((pid, p, min(p.get("acc", 0.3), 0.6)))
        stations = {"station": {"name": "中央駅", "xy": hub, "for": "station"}}
        lines = []
        names = iter(rnd.sample(STATION_NAMES, len(STATION_NAMES)))

        def stop_at(pid, p, acc, kind):
            x, y = p["xy"]
            d0 = math.hypot(x, y) or 1.0
            k = max(0.0, (d0 - acc) / d0)
            sid = "st:%s" % pid
            lab = (geo.app.places.label(pid) if pid != places_mod.HOME_ME else "あなたの家の近く")
            stations[sid] = {"name": ("%s前" % lab) if kind == "bus" else "%s駅" % lab.replace("あなたの家の近く", "住宅地"),
                             "xy": [round(x * k, 3), round(y * k, 3)], "for": pid}
            return sid

        def ang(t):
            return math.degrees(math.atan2(t[1]["xy"][1], t[1]["xy"][0]))

        def make_lines(targets, kind, gap_deg, nmax, spacing, label_pool, span_deg):
            if not targets:
                return
            targets = sorted(targets, key=ang)
            groups = [[targets[0]]]
            for t in targets[1:]:          # 角度で分ける: 前と離れている / 1 本の向きの幅を越える なら別の路線
                if ang(t) - ang(groups[-1][-1]) > gap_deg or ang(t) - ang(groups[-1][0]) > span_deg:
                    groups.append([t])
                else:
                    groups[-1].append(t)
            if len(groups) > 1 and ang(groups[0][0]) + 360 - ang(groups[-1][-1]) <= gap_deg                     and ang(groups[0][-1]) + 360 - ang(groups[-1][0]) <= span_deg:      # 一周してつながる
                groups[0] = groups.pop() + groups[0]

            def mid(g):
                return math.degrees(math.atan2(sum(math.sin(math.radians(ang(t))) for t in g), sum(math.cos(math.radians(ang(t))) for t in g)))
            while len(groups) > nmax:      # 多すぎれば, いちばん小さいまとまりを, 向きの近い路線へ
                groups.sort(key=len)
                g = groups.pop(0)
                near = min(groups, key=lambda x: abs((mid(x) - mid(g) + 180) % 360 - 180))
                near += g
            for gi, g in enumerate(groups):
                seq = ["station"]
                g = sorted(g, key=lambda t: math.hypot(*t[1]["xy"]))
                for pid, p, acc in g:
                    sid = stop_at(pid, p, acc, kind)
                    prev = stations[seq[-1]]["xy"]
                    cur = stations[sid]["xy"]
                    dist = math.hypot(cur[0] - prev[0], cur[1] - prev[1])
                    n = int(dist // spacing)
                    for j in range(1, n + 1):          # 間の駅・停留所
                        f = j / float(n + 1)
                        mid = "st:%s:%d:%d" % (kind, gi, len(seq))
                        nm = next(names, None) or "%s%d丁目" % (rnd.choice(STATION_NAMES), rnd.randint(1, 5))
                        stations[mid] = {"name": nm + ("駅" if kind == "rail" else ""), "xy": [round(prev[0] + (cur[0] - prev[0]) * f, 3),
                                                                                             round(prev[1] + (cur[1] - prev[1]) * f, 3)], "for": None}
                        seq.append(mid)
                    if sid != seq[-1]:
                        seq.append(sid)
                if kind == "rail":                     # 先に終点
                    last = stations[seq[-1]]["xy"]
                    d = math.hypot(*last) or 1.0
                    ext = rnd.uniform(2.0, 4.0)
                    end = "st:rail:%d:end" % gi
                    stations[end] = {"name": (next(names, None) or rnd.choice(STATION_NAMES) + "台") + "駅", "xy": [round(last[0] * (1 + ext / d), 3), round(last[1] * (1 + ext / d), 3)],
                                     "for": None}
                    seq.append(end)
                lines.append(self._timetable_params(rnd, kind, "%s%d" % (kind, gi), label_pool[gi % len(label_pool)], seq))

        make_lines(rail_t, "rail", 50, 4, 5.0, LINE_NAMES, 55)
        make_lines(bus_t, "bus", 40, 4, 1.2, BUS_NAMES, 70)
        return {"v": NET_V, "stations": stations, "lines": lines}

    @staticmethod
    def _timetable_params(rnd, kind, lid, name, seq):
        """路線の時刻表の決まり (始発・終電・時間帯ごとの間隔). 平日と土休日, 上り下りで少し違う."""
        tt = {}
        for dt in ("wd", "hd"):
            for dr in ("out", "in"):
                if kind == "rail":
                    first = rnd.uniform(4.8, 5.4) * 60
                    last = (rnd.uniform(23.7, 24.4) if dr == "out" else rnd.uniform(23.0, 23.6)) * 60
                    hw = {"rush": rnd.choice((4, 5, 6)) if dt == "wd" else rnd.choice((8, 10)), "day": rnd.choice((8, 10, 12)),
                          "eve": rnd.choice((6, 8)) if dt == "wd" else 10, "night": rnd.choice((15, 20))}
                else:
                    first = rnd.uniform(6.0, 7.0) * 60
                    last = rnd.uniform(20.8, 22.5) * 60
                    hw = {"rush": rnd.choice((10, 12, 15)) if dt == "wd" else 20, "day": rnd.choice((15, 20, 20)),
                          "eve": rnd.choice((15, 20)), "night": rnd.choice((30, 40))}
                tt["%s_%s" % (dt, dr)] = {"first": round(first), "last": round(last), "hw": hw}
        return {"id": lid, "kind": kind, "name": name, "seq": seq, "tt": tt}

    # ------------------------------------------------------------------ 時刻表
    def run_min(self, line):
        """隣の駅までの所要 (分) の並び."""
        st = self.net()["stations"]
        out = []
        for a, b in zip(line["seq"], line["seq"][1:]):
            pa, pb = st[a]["xy"], st[b]["xy"]
            km = math.hypot(pb[0] - pa[0], pb[1] - pa[1]) * (1.1 if line["kind"] == "rail" else ROAD)
            out.append(km / (RAIL_KMH if line["kind"] == "rail" else BUS_KMH) * 60 + (1.0 if line["kind"] == "rail" else 0.6))
        return out

    @staticmethod
    def _band(m):
        h = (m / 60.0) % 24
        if 6.5 <= h < 9.5:
            return "rush"
        if 9.5 <= h < 17:
            return "day"
        if 17 <= h < 20.5:
            return "eve"
        return "night"

    def departures(self, line, dt_key, dr):
        """始発駅を出る時刻の並び (運行日の 0 時からの分. 24 時を越えるのは翌 0 時台)."""
        p = line["tt"]["%s_%s" % (dt_key, dr)]
        out, m = [], float(p["first"])
        while m <= p["last"]:
            out.append(round(m))
            m += p["hw"][self._band(m)]
        return out

    def trips(self, day):
        """その運行日の全便: [(line_id, 方向, [(駅, 発・着の分)...])]."""
        dt_key = "hd" if holiday(day) else "wd"
        out = []
        for ln in self.net()["lines"]:
            run = self.run_min(ln)
            for dr in ("out", "in"):
                seq = ln["seq"] if dr == "out" else ln["seq"][::-1]
                rr = run if dr == "out" else run[::-1]
                for d0 in self.departures(ln, dt_key, dr):
                    times, m = [d0], float(d0)
                    for r in rr:
                        m += r
                        times.append(round(m, 1))
                    out.append((ln["id"], dr, list(zip(seq, times))))
        return out

    def connections(self, day):
        """運行日の接続 (connection scan 用): 発時刻の順に [(発 t, 着 t, 発駅, 着駅, 便, 路線)]."""
        if day in self._conn:
            return self._conn[day]
        base = datetime(day.year, day.month, day.day).timestamp()
        out = []
        for ti, (lid, dr, stops) in enumerate(self.trips(day)):
            trip = "%s:%s:%s:%d" % (day.isoformat(), lid, dr, ti)
            for (a, ta), (b, tb) in zip(stops, stops[1:]):
                out.append((base + ta * 60, base + tb * 60, a, b, trip, lid))
        out.sort()
        if len(self._conn) > 6:
            self._conn.clear()
        self._conn[day] = out
        return out

    def line(self, lid):
        return next(ln for ln in self.net()["lines"] if ln["id"] == lid)

    def timetable(self, sid, t):
        """駅・停留所の時刻表 (その日): [{line, name, dir_label, first, last, hours: {時: [分...]}}]."""
        net = self.net()
        if sid not in net["stations"]:
            raise KeyError(sid)
        day = service_day(t)
        out = []
        for lid, dr, stops in self.trips(day):
            for i, (s, m) in enumerate(stops[:-1]):
                if s != sid:
                    continue
                ln = self.line(lid)
                to = net["stations"][stops[-1][0]]["name"]
                key = (lid, dr)
                ent = next((x for x in out if x["key"] == key), None)
                if not ent:
                    ent = {"key": key, "line": lid, "name": ln["name"], "kind": ln["kind"], "dir_label": "%s方面" % to, "hours": {}, "times": []}
                    out.append(ent)
                ent["times"].append(m)
                h = int(m // 60)
                ent["hours"].setdefault(str(h), []).append(int(round(m)) % 60)
        for ent in out:
            ent.pop("key")
            ent["first"], ent["last"] = _hm(min(ent["times"])), _hm(max(ent["times"]))
            ent.pop("times")
        return {"id": sid, "name": net["stations"][sid]["name"], "day": day.isoformat(), "holiday": holiday(day), "lines": out}

    def map_view(self):
        net = self.net()
        return {"stations": {k: {"name": v["name"], "xy": v["xy"]} for k, v in net["stations"].items()},
                "lines": [{"id": ln["id"], "kind": ln["kind"], "name": ln["name"], "seq": ln["seq"]} for ln in net["lines"]]}

    def station_of(self, pid):
        """行き先にあてた駅・停留所 (無ければ None)."""
        st = self.net()["stations"]
        return next((k for k, v in st.items() if v.get("for") == pid and k != "station"), None)

    # ------------------------------------------------------------------ 経路探索
    def _walk_min(self, a_xy, b_xy):
        return math.hypot(b_xy[0] - a_xy[0], b_xy[1] - a_xy[1]) * ROAD / WALK_KMH * 60

    def fare_rail(self, km):
        return int(min(1500, 150 + 20 * km) / 10) * 10

    def scan(self, origin_xy, t, access, transfer=TRANSFER_BUF, horizon=8 * 3600):
        """connection scan: access {駅: (着く時刻, 区間)} から, 各駅に着くいちばん早い時刻と, そこまでの乗り方 (日をまたいでもよい).
        返す: (着 {駅: t}, 来かた {駅: ("ride", 乗った接続, 降りた接続) / ("access", 区間)})."""
        arr = {s: a[0] for s, a in access.items()}
        how = {s: ("access", a[1]) for s, a in access.items()}
        trip_in = {}
        day = service_day(t)
        conns = self.connections(day) + self.connections(day + timedelta(days=1))
        conns.sort()
        i = bisect.bisect_left(conns, (t,))
        end = t + horizon
        for c in conns[i:]:
            dep, at, a, b, trip, lid = c
            if dep > end:
                break
            if trip in trip_in:
                pass
            elif a in arr:
                buf = BOARD_BUF if how[a][0] == "access" else transfer
                if arr[a] + buf * 60 <= dep:
                    trip_in[trip] = c
                else:
                    continue
            else:
                continue
            if at < arr.get(b, float("inf")):
                arr[b] = at
                how[b] = ("ride", trip_in[trip], c)
        return arr, how

    def journey(self, how, sid):
        """駅 sid までの乗り方を, 区間の並び [{kind, from, to, t0, t1, line}] に (access も含む)."""
        legs = []
        s = sid
        guard = 0
        while guard < 20:
            guard += 1
            h = how[s]
            if h[0] == "access":
                legs = list(h[1]) + legs
                break
            _, cin, cout = h
            legs.insert(0, {"kind": "ride", "from": cin[2], "to": cout[3], "t0": cin[0], "t1": cout[1], "line": cin[5], "trip": cin[4]})
            s = cin[2]
        # 乗る前の待ち (駅に着いてから発車まで)
        out = []
        for lg in legs:
            if lg["kind"] == "ride" and out and out[-1]["t1"] < lg["t0"] - 30:
                out.append({"kind": "wait", "from": lg["from"], "to": lg["from"], "t0": out[-1]["t1"], "t1": lg["t0"]})
            out.append(lg)
        return out
