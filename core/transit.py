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
- 遅れ (A11 段 1): 路線・運行日ごとの出来事 (incidents. ワールド・路線・日から決まる乱数. 毎日違う. 朝夕に多い).
  出来事は {始まり s, 終わり e (分), 遅れ d (分), 方向}. s〜e のあいだにある駅を出る便は, そこから先が d 分遅れる.
  経路を調べるときは「その時点で始まっている出来事」だけを知っている (known = 時刻). 実際の移動は全部 (known = "all") で進む.
- 路線を増やす (A11): 環状線 (放射の鉄道 2 本以上で. 交わる所が乗り換え駅) / 支線 (駅から遠い家・職場の方へ) /
  快速 (行き先の駅・乗り換え駅だけ止まる. 昼だけ. 遅れは元の路線の出来事) / 深夜バス (あなたの家のそばの系統を, 終バスのあと駅前発だけ.
  運賃 2 倍). 既存の駅・路線は同じ乱数の順で同じに作り, 新しいものは別の乱数で足す (駅の id は消えない).
  バスは平日の朝夕に遅く, 深夜は速い. 平日の朝夕の電車・バスは混んでいて立つ (始発駅から乗れば座れる. 区間の crowd).
- 道 (A11. core/roads.py): 川と橋・大通り・踏切. net.roads に覚える.
"""
import bisect
import math
import random
from datetime import datetime, timedelta

from . import roads as roads_mod

NET_V = 4                            # 路線網の作り方の版 (変えたら, 作り直す)
RAPID_KMH = 75.0                     # 快速の速さ
BUS_JAM, BUS_NIGHT = 1.35, 0.85      # バスの所要の倍率: 平日朝夕 / 深夜
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
DELAY_DAY = 0.3                      # 1 路線・1 日に遅れの出来事が起きる見込み (geo.EV_DELAY / 0.04 を掛ける. 0 なら遅れなし)
DELAY_CAUSE = {"rail": ("車両点検", "信号の故障", "線路内への立ち入り", "急病人の救護", "混雑"),
               "bus": ("道路の混雑", "事故渋滞", "工事")}
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
        self._stops = {}
        self._inc = {}
        self._csa = {}
        self.roads = roads_mod.Roads(self)

    # ------------------------------------------------------------------ 路線網
    def net(self):
        r = self.geo.rec()
        old = r.get("net") or {}
        if old.get("v") != NET_V:
            # 版 3 の路線網があれば, それを土台に足す (A11): 作ったあとに場所 (遠い相手の家など) が増えていても, いまの駅・路線はそのまま
            r["net"] = self._upgrade(old) if old.get("v") == 3 and old.get("stations") and old.get("lines") else self._build()
            self.geo.save()
            self._conn.clear()
            self._stops.clear()
            self._inc.clear()
            self._csa.clear()
            self.roads.clear()
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
            if pid == places_mod.HOME_ME:          # あなたの家のそばの停留所: 町の名前で
                lab = next(names, None) or rnd.choice(STATION_NAMES)
                nm = "%s住宅前" % lab if kind == "bus" else "%s駅" % lab
            else:
                lab = geo.app.places.label(pid)
                nm = "%s前" % lab if kind == "bus" else "%s駅" % lab
            stations[sid] = {"name": nm,
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
        self._extend(random.Random("net4:%s" % WORLD), stations, lines, names)        # A11: ここまでは NET_V 3 と同じ
        roads = roads_mod.build(random.Random("roads:%s" % WORLD), stations, lines)
        return {"v": NET_V, "stations": stations, "lines": lines, "roads": roads}

    def _upgrade(self, old):
        """版 3 の路線網に, 環状線・支線・快速・深夜バスと道を足す (いまの駅の id・名前・位置, 路線の時刻表はそのまま)."""
        import copy
        from .store import WORLD
        stations = copy.deepcopy(old["stations"])
        lines = copy.deepcopy(old["lines"])
        for ln in lines:                           # 土休日の昼は平日より多く走らせない (_timetable_params と同じ)
            tt = ln.get("tt") or {}
            for dr in ("out", "in"):
                if "hd_%s" % dr in tt and "wd_%s" % dr in tt:
                    tt["hd_%s" % dr]["hw"]["day"] = max(tt["hd_%s" % dr]["hw"]["day"], tt["wd_%s" % dr]["hw"]["day"])
        used = {v["name"].replace("駅", "").replace("住宅前", "") for v in stations.values()}
        rnd = random.Random("net:%s" % WORLD)
        names = iter([n for n in rnd.sample(STATION_NAMES, len(STATION_NAMES)) if n not in used])
        self._extend(random.Random("net4:%s" % WORLD), stations, lines, names)
        roads = roads_mod.build(random.Random("roads:%s" % WORLD), stations, lines)
        return {"v": NET_V, "stations": stations, "lines": lines, "roads": roads}

    def _extend(self, rnd, stations, lines, names):
        """環状線・支線・快速・深夜バス (A11). 既存の駅・路線は変えずに足す (環状線との乗り換え駅だけ, 既存の路線の並びに差し込む)."""
        from . import places as places_mod

        def nm():
            return next(names, None) or "%s%s" % (rnd.choice(STATION_NAMES), rnd.choice(("台", "原", "野", "坂")))

        def dist(a, b):
            return math.hypot(a[0] - b[0], a[1] - b[1])
        radial = [ln for ln in lines if ln["kind"] == "rail"]
        hubs = set()                                   # 乗り換え駅 (快速が止まる)
        # 環状線: 放射の鉄道と交わる所を乗り換え駅に. 間は 2.5 km ほどごとに駅
        if len(radial) >= 2:
            R = rnd.uniform(3.0, 4.5)
            ring = []
            for ln in radial:
                seq = ln["seq"]
                for i in range(len(seq) - 1):
                    pa, pb = stations[seq[i]]["xy"], stations[seq[i + 1]]["xy"]
                    da, db = math.hypot(*pa), math.hypot(*pb)
                    if da < R <= db:
                        f = (R - da) / (db - da)
                        q = [round(pa[0] + (pb[0] - pa[0]) * f, 3), round(pa[1] + (pb[1] - pa[1]) * f, 3)]
                        near = min((seq[i], seq[i + 1]), key=lambda s: dist(stations[s]["xy"], q))
                        if near != "station" and dist(stations[near]["xy"], q) <= 0.6:
                            sid = near
                        else:
                            sid = "st:ring:%d" % len(ring)
                            stations[sid] = {"name": nm() + "駅", "xy": q, "for": None}
                            seq.insert(i + 1, sid)
                        xy = stations[sid]["xy"]
                        ring.append((math.atan2(xy[1], xy[0]), sid))
                        break
            if len(ring) >= 2:
                ring.sort()
                seq, m = [], 0
                for k, (a0, s0) in enumerate(ring):
                    a1 = ring[(k + 1) % len(ring)][0] + (2 * math.pi if k + 1 == len(ring) else 0)
                    seq.append(s0)
                    n = int(R * (a1 - a0) // 2.5)
                    for j in range(1, n + 1):
                        a = a0 + (a1 - a0) * j / (n + 1)
                        sid = "st:ring:m%d" % m
                        m += 1
                        stations[sid] = {"name": nm() + "駅", "xy": [round(R * math.cos(a), 3), round(R * math.sin(a), 3)], "for": None}
                        seq.append(sid)
                seq.append(seq[0])
                hubs.update(s for _, s in ring)
                ln = self._timetable_params(rnd, "rail", "ring0", "環状線", seq)
                ln["loop"] = True
                lines.append(ln)
        # 支線: 駅から 1.5 km より遠い家・職場があれば, いちばん遠いものの方へ. 無ければ, いちばん路線の無い向きへ
        if radial:
            rail_st = [s for ln in lines if ln["kind"] == "rail" for s in ln["seq"] if s != "station"]
            pts = self.geo.rec()["pts"]
            far = []
            for pid, p in pts.items():
                if not (places_mod.is_home(pid) or pid == "office") or math.hypot(*p["xy"]) < 2.0:
                    continue
                g = min(dist(p["xy"], v["xy"]) for v in stations.values())
                if g > 1.5:
                    far.append((g, pid, p["xy"]))
            org = end = None
            if far:
                _, _, txy = max(far)
                org = min(rail_st, key=lambda s: dist(stations[s]["xy"], txy))
                oxy = stations[org]["xy"]
                L = dist(oxy, txy)
                if L >= 2.0:
                    end = [txy[0] + (oxy[0] - txy[0]) * 0.3 / L, txy[1] + (oxy[1] - txy[1]) * 0.3 / L]
            if end is None:
                angs = sorted(math.atan2(stations[ln["seq"][-1]]["xy"][1], stations[ln["seq"][-1]]["xy"][0]) for ln in radial)
                gaps = [((angs[(i + 1) % len(angs)] - a) % (2 * math.pi) or 2 * math.pi, a) for i, a in enumerate(angs)]
                g, a = max(gaps)
                d = a + g / 2
                aim = [4.0 * math.cos(d), 4.0 * math.sin(d)]
                org = min(rail_st, key=lambda s: dist(stations[s]["xy"], aim))
                oxy = stations[org]["xy"]
                L = rnd.uniform(4.0, 7.0)
                ux, uy = aim[0] - oxy[0], aim[1] - oxy[1]
                n0 = math.hypot(ux, uy) or 1.0
                end = [oxy[0] + ux / n0 * L, oxy[1] + uy / n0 * L]
            oxy = stations[org]["xy"]
            L = dist(oxy, end)
            n = max(1, int(L // 2.0))
            seq = [org]
            for j in range(1, n + 1):
                f = j / float(n)
                sid = "st:branch:0:%d" % j
                stations[sid] = {"name": nm() + "駅", "xy": [round(oxy[0] + (end[0] - oxy[0]) * f, 3), round(oxy[1] + (end[1] - oxy[1]) * f, 3)], "for": None}
                seq.append(sid)
            parent = next(ln for ln in lines if ln["kind"] == "rail" and org in ln["seq"])
            base = parent["name"][:-1] if parent["name"].endswith("線") else parent["name"]
            ln = self._timetable_params(rnd, "rail", "branch0", base + "支線", seq)
            for p in ln["tt"].values():
                p["hw"] = {k: min(30, v * 2) for k, v in p["hw"].items()}
            lines.append(ln)
            hubs.add(org)
        # 快速: 放射の鉄道 (駅 4 つ以上) に. 始発・終点・行き先の駅・乗り換え駅だけ止まる. 昼だけ
        for k, ln in enumerate(radial):
            seq = ln["seq"]
            keep = [s for i, s in enumerate(seq) if i in (0, len(seq) - 1) or stations[s].get("for") or s in hubs]
            if len(seq) < 4 or len(keep) >= len(seq):
                continue
            tt = {}
            for dt in ("wd", "hd"):
                for dr in ("out", "in"):
                    a, b = (600, 960) if dt == "wd" else (540, 1080)
                    h = rnd.choice((20, 30))
                    tt["%s_%s" % (dt, dr)] = {"first": a + rnd.randint(0, 9), "last": b, "hw": {"rush": h, "day": h, "eve": h, "night": h}}
            lines.append({"id": "rapid%d" % k, "kind": "rail", "of": ln["id"], "rapid": True, "name": ln["name"] + "（快速）", "seq": keep, "tt": tt})
        # 深夜バス: あなたの家のそばを通る系統 (無ければいちばん長い系統) を, 終バスのあと駅前発だけ (平日)
        buses = [ln for ln in lines if ln["kind"] == "bus" and not ln.get("of")]
        if buses:
            home_sid = "st:%s" % places_mod.HOME_ME
            base = next((ln for ln in buses if home_sid in ln["seq"]), None) or max(buses, key=lambda x: len(x["seq"]))
            h = rnd.choice((20, 30))
            lines.append({"id": "night0", "kind": "bus", "of": base["id"], "night": True, "name": "深夜バス", "seq": list(base["seq"]),
                          "fare": BUS_FARE * 2, "tt": {"wd_out": {"first": 1420, "last": 1490, "hw": {"rush": h, "day": h, "eve": h, "night": h}}}})

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
        for dr in ("out", "in"):                   # 土休日の昼は, 平日より多くは走らない (乱数は引かない: 路線網のほかの所が変わらないように)
            tt["hd_%s" % dr]["hw"]["day"] = max(tt["hd_%s" % dr]["hw"]["day"], tt["wd_%s" % dr]["hw"]["day"])
        return {"id": lid, "kind": kind, "name": name, "seq": seq, "tt": tt}

    # ------------------------------------------------------------------ 時刻表
    def run_min(self, line):
        """隣の駅までの所要 (分) の並び."""
        st = self.net()["stations"]
        out = []
        for a, b in zip(line["seq"], line["seq"][1:]):
            pa, pb = st[a]["xy"], st[b]["xy"]
            if line["kind"] == "rail":
                km = math.hypot(pb[0] - pa[0], pb[1] - pa[1]) * 1.1
                out.append(km / (RAPID_KMH if line.get("rapid") else RAIL_KMH) * 60 + 1.0)
            else:                                  # バスは道を走る (川は橋を渡る)
                km = self.roads.path(pa, pb)["km"]
                out.append(km / BUS_KMH * 60 + 0.6)
        return out

    @staticmethod
    def bus_factor(m, hol):
        """バスの所要の倍率 (運行日の分 m に出る便): 平日の朝夕は道が混んで遅く, 深夜は速い."""
        h = (m / 60.0) % 24
        if roads_mod.Roads.jam(h, hol):
            return BUS_JAM
        if h >= 22 or h < 5:
            return BUS_NIGHT
        return 1.0

    def crowded(self, lg):
        """乗る区間が混んでいて立つか: 平日の朝夕 (7:00〜9:30・17:30〜19:30) の電車・バス. 始発駅から乗れば座れる. 深夜バスは座れる."""
        if lg.get("kind") != "ride" or not lg.get("trip"):
            return False
        ln = self.line(lg["line"])
        if ln.get("night") or holiday(service_day(lg["t0"])):
            return False
        d = datetime.fromtimestamp(lg["t0"])
        h = d.hour + d.minute / 60.0
        if not (7 <= h < 9.5 or 17.5 <= h < 19.5):
            return False
        try:
            return self.trip_stops(lg["trip"], None)[0][0] != lg["from"]
        except (KeyError, ValueError):
            return True

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
        p = line["tt"].get("%s_%s" % (dt_key, dr))
        if not p:                                  # 走らない日・向き (深夜バスは平日の駅前発だけ)
            return []
        out, m = [], float(p["first"])
        while m <= p["last"]:
            out.append(round(m))
            m += p["hw"][self._band(m)]
        return out

    # ------------------------------------------------------------------ 遅れ (A11 段 1)
    @staticmethod
    def _scale():
        from . import geo as geo_mod          # 遅れの起きやすさの倍率 (テストで geo.EV_DELAY を 0 にすれば遅れない)
        return geo_mod.EV_DELAY / 0.04

    def incidents(self, day):
        """その運行日の遅れの出来事: [{id, line, s, e, d, dirs, cause}] (s・e は運行日の 0 時からの分). ワールド・路線・日で決まる."""
        from .store import WORLD
        sc = self._scale()
        key = (day, sc)
        if key in self._inc:
            return self._inc[key]
        out = []
        if sc > 0:
            for ln in self.net()["lines"]:
                if ln.get("of"):                   # 快速・深夜バスは, 元の路線の出来事で遅れる
                    continue
                rnd = random.Random("delay:%s:%s:%s" % (WORLD, ln["id"], day.isoformat()))
                p = DELAY_DAY * sc
                n = 0
                while n < 3 and rnd.random() < min(0.95, p):
                    n += 1
                    p *= 0.35
                    u = rnd.random()
                    h = rnd.uniform(6.8, 9.3) if u < 0.3 else rnd.uniform(17.0, 20.0) if u < 0.55 else rnd.uniform(6.0, 22.5)
                    s = h * 60
                    rail = ln["kind"] == "rail"
                    out.append({"id": "%s:%d" % (ln["id"], n), "line": ln["id"], "s": round(s, 1), "e": round(s + rnd.uniform(20, 90), 1),
                                "d": round(rnd.uniform(5, 30) if rail else rnd.uniform(5, 20)),
                                "dirs": rnd.choice((("out", "in"), ("out",), ("in",))), "cause": rnd.choice(DELAY_CAUSE[ln["kind"]])})
        if len(self._inc) > 12:
            self._inc.clear()
        self._inc[key] = out
        return out

    @staticmethod
    def day_base(day):
        return datetime(day.year, day.month, day.day).timestamp()

    def known(self, day, known):
        """その運行日の出来事のうち, 分かっているもの. known: None (時刻表どおり) / "all" (全部) / 時刻 (それまでに始まったもの)."""
        if known is None:
            return []
        incs = self.incidents(day)
        if known == "all":
            return incs
        base = self.day_base(day)
        return [x for x in incs if base + x["s"] * 60 <= known]

    def known_sig(self, t, known):
        """経路のキャッシュの鍵に: t の運行日と次の日で分かっている出来事の id."""
        day = service_day(t)
        return tuple(x["id"] for d in (day, day + timedelta(days=1)) for x in self.known(d, known))

    def delays_now(self, t):
        """いま遅れている路線 (経路を調べる画面に出す): [{line, name, kind, d, cause}]."""
        out = []
        day = service_day(t)
        for d in (day - timedelta(days=1), day):
            base = self.day_base(d)
            for x in self.known(d, t):
                if t <= base + (x["e"] + x["d"]) * 60:
                    ln = self.line(x["line"])
                    if not any(o["line"] == x["line"] and o["d"] >= x["d"] for o in out):
                        out = [o for o in out if o["line"] != x["line"]]
                        out.append({"line": x["line"], "name": ln["name"], "kind": ln["kind"], "d": x["d"], "cause": x["cause"]})
        return out

    def trips(self, day, incs=()):
        """その運行日の全便: [(line_id, 方向, [(駅, 発・着の分)...])]. incs: 効かせる遅れの出来事."""
        hol = holiday(day)
        dt_key = "hd" if hol else "wd"
        out = []
        for ln in self.net()["lines"]:
            run = self.run_min(ln)
            for dr in ("out", "in"):
                seq = ln["seq"] if dr == "out" else ln["seq"][::-1]
                rr = run if dr == "out" else run[::-1]
                mine = [x for x in incs if x["line"] in (ln["id"], ln.get("of")) and dr in x["dirs"]]
                for d0 in self.departures(ln, dt_key, dr):
                    times, m = [d0], float(d0)
                    f = self.bus_factor(d0, hol) if ln["kind"] == "bus" else 1.0
                    for r in rr:
                        m += r * f
                        times.append(round(m, 1))
                    if mine:                       # 出来事のあいだに出る駅から先が遅れる (いちど遅れたら, その先も)
                        late = 0
                        for i, m in enumerate(times):
                            late = max([late] + [x["d"] for x in mine if x["s"] <= m <= x["e"]])
                            times[i] = round(m + late, 1)
                    out.append((ln["id"], dr, list(zip(seq, times))))
        return out

    def connections(self, day, known=None):
        """運行日の接続 (connection scan 用): 発時刻の順に [(発 t, 着 t, 発駅, 着駅, 便, 路線)]. known: 効かせる遅れ (known() と同じ)."""
        incs = self.known(day, known)
        key = (day, tuple(x["id"] for x in incs), self._scale() if incs else 0)
        if key in self._conn:
            return self._conn[key]
        base = self.day_base(day)
        out = []
        stops_of = {}
        for ti, (lid, dr, stops) in enumerate(self.trips(day, incs)):
            trip = "%s:%s:%s:%d" % (day.isoformat(), lid, dr, ti)
            stops_of[trip] = [(s, base + m * 60) for s, m in stops]
            for (a, ta), (b, tb) in zip(stops, stops[1:]):
                out.append((base + ta * 60, base + tb * 60, a, b, trip, lid))
        out.sort()
        if len(self._conn) > 12:
            self._conn.clear()
            self._stops.clear()
        self._conn[key] = out
        self._stops[key] = stops_of
        return out

    def trip_stops(self, trip, known=None):
        """便の駅と時刻 [(駅, t)] (known の遅れを効かせて)."""
        day = datetime.strptime(trip.split(":")[0], "%Y-%m-%d").date()
        self.connections(day, known)
        incs = self.known(day, known)
        return self._stops[(day, tuple(x["id"] for x in incs), self._scale() if incs else 0)][trip]

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
                    lab = ("外回り" if dr == "out" else "内回り") if ln.get("loop") else "%s方面" % to
                    ent = {"key": key, "line": lid, "name": ln["name"], "kind": ln["kind"], "dir_label": lab, "hours": {}, "times": []}
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
                "lines": [{"id": ln["id"], "kind": ln["kind"], "name": ln["name"], "seq": ln["seq"], "over": bool(ln.get("of"))}
                          for ln in net["lines"]],
                "roads": self.roads.view()}

    def station_of(self, pid):
        """行き先にあてた駅・停留所 (無ければ None)."""
        st = self.net()["stations"]
        return next((k for k, v in st.items() if v.get("for") == pid and k != "station"), None)

    # ------------------------------------------------------------------ 経路探索
    def _walk_min(self, a_xy, b_xy):
        return math.hypot(b_xy[0] - a_xy[0], b_xy[1] - a_xy[1]) * ROAD / WALK_KMH * 60

    def fare_rail(self, km):
        return int(min(1500, 150 + 20 * km) / 10) * 10

    def scan(self, origin_xy, t, access, transfer=TRANSFER_BUF, horizon=8 * 3600, known=None):
        """connection scan: access {駅: (着く時刻, 区間)} から, 各駅に着くいちばん早い時刻と, そこまでの乗り方 (日をまたいでもよい).
        返す: (着 {駅: t}, 来かた {駅: ("ride", 乗った接続, 降りた接続) / ("access", 区間)},
               電車・バスで着く時刻 {駅: t}, その来かた {駅: ("ride", ...)}).
        後ろの 2 つは, 歩いて (access) 着くほうが早い駅でも, 電車・バスで着く時刻を別に覚えたもの (降りる駅に使う).
        以前は駅ごとにいちばん早い着き方だけを覚えていたので, バスが出た直後など乗り継ぎの悪い数分は, 降りる駅にも
        歩いて着くほうが早くなって電車・バスの着き方が消え, 「電車・バスで行ける経路がありません」になっていた."""
        arr = {s: a[0] for s, a in access.items()}
        how = {s: ("access", a[1]) for s, a in access.items()}
        rarr, rhow = {}, {}
        trip_in = {}
        day = service_day(t)
        conns = self.connections(day, known) + self.connections(day + timedelta(days=1), known)
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
            if at < rarr.get(b, float("inf")):
                rarr[b] = at
                rhow[b] = ("ride", trip_in[trip], c)
        return arr, how, rarr, rhow

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
            if lg["kind"] == "ride":
                lg["crowd"] = self.crowded(lg)
            if lg["kind"] == "ride" and out and out[-1]["t1"] < lg["t0"] - 30:
                out.append({"kind": "wait", "from": lg["from"], "to": lg["from"], "t0": out[-1]["t1"], "t1": lg["t0"]})
            out.append(lg)
        return out
