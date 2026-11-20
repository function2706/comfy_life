"""道 (A11): 道のり・川と橋・大通り・踏切. 路線網 (core/transit.py) と一緒に, ワールドごとに net.roads に覚える.

- 川: 町を横切る 1 本 (駅前から 0.8〜2.5 km 離れた直線). 橋は川沿いに, 町なかは 1.2〜2.0 km ごと, 遠くは 3〜6 km ごと.
  川を挟む 2 点の道のりは, いちばん得な橋を通る (a → 橋 → b).
- 大通り: 駅前からの放射 4〜6 本と, 環状の大通り (半径 2.5〜4 km). それ以外は裏道.
  車・タクシー・バスは, 大通りに乗っている割合 (出るところ・着くところから大通りまでの裏道を引いた残り) で速く,
  平日の朝夕は大通りほど混む. 歩き・自転車は裏道も同じ.
- 踏切: 鉄道の線路 (駅と駅の間) を横切るたびに待つ (見込み: 平日朝夕 3 分・ほか 1 分・電車の無い夜中 0).
  駅の 250 m 以内で横切るなら, 駅の自由通路・地下道で待たない.
- 道のり = 直線 (橋を通るなら折れ線) × 1.3.
"""
import math

ROAD = 1.3
SIDE_KMH, ART_KMH, FAR_KMH = 25.0, 38.0, 55.0       # 裏道・大通り・10 km より先 (幹線道路)
JAM_ART, JAM_SIDE, JAM_HOLI = 1.6, 1.15, 1.15       # 平日朝夕の混み (大通り・裏道) / 土休日の大通り
NIGHT_FAST = 0.85                                   # 深夜は空いている
CROSS_RUSH, CROSS_DAY = 3.0, 1.0                    # 踏切の待ちの見込み (分)
CROSS_FREE = 0.25                                   # 駅からこの距離 (km) 以内は自由通路
ART_NEAR = 0.15                                     # 大通りから, これより近ければ大通り沿い


def build(rnd, stations, lines):
    """道の形 (ワールドごとに 1 回. 乱数は路線網と別)."""
    ang = rnd.uniform(0, math.pi)
    u = [math.cos(ang), math.sin(ang)]
    n = [-u[1], u[0]]
    off = rnd.uniform(0.8, 2.5) * rnd.choice((1, -1))
    p0 = [round(n[0] * off, 3), round(n[1] * off, 3)]
    bridges, s = [], rnd.uniform(-0.6, 0.6)
    while s < 40:
        bridges.append(round(s, 3))
        s += rnd.uniform(1.2, 2.0) if abs(s) < 6 else rnd.uniform(3.0, 6.0)
    s = bridges[0]
    while s > -40:
        s -= rnd.uniform(1.2, 2.0) if abs(s) < 6 else rnd.uniform(3.0, 6.0)
        bridges.insert(0, round(s, 3))
    k = rnd.randint(4, 6)
    a0 = rnd.uniform(0, 360)
    radials = sorted(round((a0 + i * 360.0 / k + rnd.uniform(-15, 15)) % 360, 1) for i in range(k))
    return {"river": {"p": p0, "u": [round(u[0], 4), round(u[1], 4)]}, "bridges": bridges,
            "radials": radials, "ring": round(rnd.uniform(2.5, 4.0), 2)}


def _seg_x(a, b, c, d):
    """線分 ab と cd が交わる点 (無ければ None)."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-12:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    w = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if 0 < t < 1 and 0 <= w <= 1:
        return (a[0] + r[0] * t, a[1] + r[1] * t)
    return None


class Roads:
    def __init__(self, transit):
        self.transit = transit
        self._cache = {}
        self._rails = None

    def clear(self):
        self._cache.clear()
        self._rails = None

    def rec(self):
        return self.transit.net().get("roads")

    def _rail_segs(self):
        if self._rails is None:
            net = self.transit.net()
            st = net["stations"]
            segs = set()
            for ln in net["lines"]:
                if ln["kind"] != "rail" or ln.get("of"):
                    continue
                for a, b in zip(ln["seq"], ln["seq"][1:]):
                    segs.add(tuple(sorted((a, b))))
            self._rails = [(st[a]["xy"], st[b]["xy"]) for a, b in segs]
        return self._rails

    # ------------------------------------------------------------------ 形
    def side(self, xy):
        r = self.rec()["river"]
        return (xy[0] - r["p"][0]) * -r["u"][1] + (xy[1] - r["p"][1]) * r["u"][0] >= 0

    def bridge_xy(self, s):
        r = self.rec()["river"]
        return [r["p"][0] + r["u"][0] * s, r["p"][1] + r["u"][1] * s]

    def to_artery(self, xy):
        """いちばん近い大通りまでの距離 (km)."""
        r = self.rec()
        d0 = math.hypot(*xy)
        best = abs(d0 - r["ring"])
        a = math.degrees(math.atan2(xy[1], xy[0]))
        for ra in r["radials"]:
            dd = math.radians((a - ra + 180) % 360 - 180)
            best = min(best, d0 * abs(math.sin(dd)) if abs(dd) < math.pi / 2 else d0)
        return best

    def crossings(self, a, b):
        """a→b の直線で横切る踏切の数 (駅のそばは数えない)."""
        n = 0
        for c, d in self._rail_segs():
            p = _seg_x(a, b, c, d)
            if p and math.hypot(p[0] - c[0], p[1] - c[1]) > CROSS_FREE and math.hypot(p[0] - d[0], p[1] - d[1]) > CROSS_FREE:
                n += 1
        return n

    def path(self, a, b):
        """a→b (xy) の道: {km (道のり), cross (踏切の数), bridge (渡る橋の位置 xy か None), art (大通りの割合 0〜0.85)}."""
        key = (round(a[0], 3), round(a[1], 3), round(b[0], 3), round(b[1], 3))
        hit = self._cache.get(key)
        if hit:
            return hit
        r = self.rec()
        if not r:
            d = math.hypot(b[0] - a[0], b[1] - a[1])
            out = {"km": d * ROAD, "cross": 0, "bridge": None, "art": 0.0}
        else:
            br = None
            d = math.hypot(b[0] - a[0], b[1] - a[1])
            if d > 0 and self.side(a) != self.side(b):
                best = None
                for s in r["bridges"]:
                    q = self.bridge_xy(s)
                    dd = math.hypot(q[0] - a[0], q[1] - a[1]) + math.hypot(b[0] - q[0], b[1] - q[1])
                    if best is None or dd < best[0]:
                        best = (dd, q)
                d, br = best
            cross = self.crossings(a, br) + self.crossings(br, b) if br else self.crossings(a, b)
            side = self.to_artery(a) + self.to_artery(b)
            art = 0.0 if d <= 0 else max(0.0, min(0.85, 1 - side * ROAD / max(1e-6, d * ROAD)))
            out = {"km": d * ROAD, "cross": cross, "bridge": [round(br[0], 3), round(br[1], 3)] if br else None, "art": round(art, 3)}
        if len(self._cache) > 20000:
            self._cache.clear()
        self._cache[key] = out
        return out

    # ------------------------------------------------------------------ 時間
    @staticmethod
    def cross_wait(h, holiday=False):
        """踏切 1 つの待ちの見込み (分). h: 時 (0〜24). 電車の無い夜中は待たない."""
        if 1.0 <= h < 5.0:
            return 0.0
        if not holiday and (7 <= h < 9.5 or 17 <= h < 19.5):
            return CROSS_RUSH
        return CROSS_DAY

    @staticmethod
    def drive_min(km, art, h, holiday=False):
        """車で走る時間 (分): 裏道と大通り (10 km より先は幹線道路) を, 時間帯の混み・空きで."""
        side_km, art_km = km * (1 - art), km * art
        near = min(art_km, 10.0)
        m_side = side_km / SIDE_KMH * 60
        m_art = near / ART_KMH * 60 + max(0.0, art_km - 10.0) / FAR_KMH * 60
        if 7 <= h < 9.5 or 17 <= h < 19.5:
            if holiday:
                m_art *= JAM_HOLI
            else:
                m_art, m_side = m_art * JAM_ART, m_side * JAM_SIDE
        elif h >= 22 or h < 5:
            m_art, m_side = m_art * NIGHT_FAST, m_side * NIGHT_FAST
        return m_art + m_side

    @staticmethod
    def jam(h, holiday=False):
        return (7 <= h < 9.5 or 17 <= h < 19.5) and not holiday

    def view(self):
        """地図に描く: 川 (端から端) と橋, 大通り (放射と環状)."""
        r = self.rec()
        if not r:
            return None
        return {"river": [self.bridge_xy(-45), self.bridge_xy(45)], "bridges": [self.bridge_xy(s) for s in r["bridges"]],
                "radials": r["radials"], "ring": r["ring"]}
