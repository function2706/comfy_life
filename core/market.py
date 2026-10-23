"""株: 銘柄 (店の種類ごと)・取引時間・ニュース・積立・指値.

- 取引時間: 平日の 9:00〜11:30 と 12:30〜15:00 だけ (土日・祝日・年末年始 (12/31〜1/3) は休み). 値動きは取引時間のあいだだけ.
  取引時間外の売買は「注文の予約」(次の取引開始に成行で). 取引時間外に出たニュースは, 次の取引開始の値段 (寄り付き) に効く.
- 銘柄は world.json の economy.assets. sector (店の種類) があると, 季節・天気・行楽の時期に少しだけ左右される
  (目標の上下 (数%) に向かってゆっくり寄るだけで, 条件が変われば戻る. SECTOR_EFFECTS).
- 積立: 毎月決まった日 (その日以降の最初の取引時間) に, 決まった額で買える株数だけ買う. お金が足りなければその月は見送る.
- 指値: 「この値段以下になったら買う / 以上になったら売る」. 期限 (日数) が来たら取り消し. 買いの注文の分のお金は, 注文中は使えない
  (買付余力 = 手元 − 注文中の買いの額).
"""
import math
import random
import time
from datetime import date, datetime, timedelta

from . import outdoor as outdoor_mod

SESSIONS = ((9 * 60, 11 * 60 + 30), (12 * 60 + 30, 15 * 60))
STEP = 300
# 店の種類ごとの, 季節・天気・行楽の時期への感じやすさ (目標の上下 = 合計 × sector_scale)
SECTOR_EFFECTS = {
    "supermarket": {"rain": 0.6, "snow": 1.0, "holiday": -0.3},
    "convenience": {"summer": 0.6, "rain": 0.3, "winter": -0.3},
    "drugstore": {"winter": 0.8, "spring": 0.4, "summer": -0.4},
    "bookstore": {"rain": 0.5, "autumn": 0.4, "summer": -0.3},
    "electronics": {"summer": 0.5, "winter": 0.3, "holiday": 0.4, "spring": -0.3},
    "eat": {"rain": -0.7, "snow": -0.9, "holiday": 0.4, "sunny": 0.2},
    "mall": {"rain": 0.4, "holiday": 0.7, "summer": 0.2},
    "cafe": {"winter": 0.4, "rain": 0.3, "summer": -0.3},
    "amusement": {"sunny": 0.4, "rain": -1.0, "snow": -1.0, "holiday": 1.0, "winter": -0.6},
    "aquarium": {"summer": 0.6, "rain": 0.3, "holiday": 0.8, "winter": -0.4},
    "food": {"winter": 0.2},
}
SECTOR_LABEL = {"supermarket": "スーパー", "convenience": "コンビニ", "drugstore": "ドラッグストア", "bookstore": "本屋",
                "electronics": "家電量販店", "eat": "飲食店", "mall": "ショッピングモール", "cafe": "カフェ", "amusement": "遊園地",
                "aquarium": "水族館", "food": "食品", "maker": "メーカー", "game": "ゲーム", "index": "まとめ"}
_HOL = {}


def _nth_monday(y, m, n):
    d = date(y, m, 1)
    return d + timedelta(days=(0 - d.weekday()) % 7 + 7 * (n - 1))


def _equinox(y, spring):
    base = 20.8431 if spring else 23.2488
    return date(y, 3 if spring else 9, int(base + 0.242194 * (y - 1980) - int((y - 1980) / 4)))


def holidays(y):
    """その年の取引所の休みの日 (祝日・振替休日・国民の休日・年末年始). 祝日はいまの決まりでの近似 (春分・秋分は計算式)."""
    if y in _HOL:
        return _HOL[y]
    s = {date(y, m, d) for m, d in ((1, 1), (2, 11), (2, 23), (4, 29), (5, 3), (5, 4), (5, 5), (8, 11), (11, 3), (11, 23))}
    s |= {_nth_monday(y, 1, 2), _nth_monday(y, 7, 3), _nth_monday(y, 9, 3), _nth_monday(y, 10, 2), _equinox(y, True), _equinox(y, False)}
    for d in sorted(s):                     # 振替休日
        if d.weekday() == 6:
            n = d + timedelta(days=1)
            while n in s:
                n += timedelta(days=1)
            s.add(n)
    for d in sorted(s):                     # 国民の休日 (祝日に挟まれた日)
        mid, n2 = d + timedelta(days=1), d + timedelta(days=2)
        if n2 in s and mid not in s and mid.weekday() != 6:
            s.add(mid)
    s |= {date(y, 12, 31), date(y, 1, 2), date(y, 1, 3)}
    _HOL[y] = s
    return s


def trading_day(d):
    d = d.date() if isinstance(d, datetime) else d
    return d.weekday() < 5 and d not in holidays(d.year)


def is_open(dt):
    m = dt.hour * 60 + dt.minute
    return trading_day(dt) and any(a <= m < b for a, b in SESSIONS)


def next_open(dt):
    """dt より後で, 最初に取引が始まる時刻 (いま取引中なら dt)."""
    if is_open(dt):
        return dt
    d = dt.replace(second=0, microsecond=0)
    for _ in range(40):
        if trading_day(d):
            for a, _b in SESSIONS:
                st = d.replace(hour=a // 60, minute=a % 60)
                if st > dt:
                    return st
        d = (d + timedelta(days=1)).replace(hour=0, minute=0)
    return d


def session_end(dt):
    m = dt.hour * 60 + dt.minute
    for a, b in SESSIONS:
        if a <= m < b:
            return dt.replace(hour=b // 60, minute=b % 60, second=0, microsecond=0)
    return dt


def holiday_season(d):
    """行楽の時期 (大型連休・夏休み・年末年始)."""
    return (d.month == 5 and d.day <= 6) or d.month == 8 or (d.month == 12 and d.day >= 20) or (d.month == 1 and d.day <= 3) \
        or d.weekday() >= 5 or d in holidays(d.year)


def conditions(dt):
    w = outdoor_mod.weather(dt)["id"]
    c = {outdoor_mod.SEASONS[dt.month]: 1, w: 1}
    if holiday_season(dt.date()):
        c["holiday"] = 1
    return c


class Market:
    def __init__(self, app):
        self.app = app

    @property
    def L(self):
        return self.app.life

    def econ(self):
        return self.L.econ()

    def assets(self):
        return self.econ().get("assets") or []

    def asset(self, aid):
        a = next((x for x in self.assets() if x["id"] == aid), None)
        if not a:
            raise KeyError("銘柄が見つかりません: %s" % aid)
        return a

    def m(self):
        m = self.L.player_state()["market"]
        for k in ("orders", "plans", "fills"):
            m.setdefault(k, [])
        m.setdefault("plan_done", {})
        return m

    def state(self, a, t=None):
        m = self.L.player_state()["market"]
        st = m["assets"].get(a["id"])
        if st is None:          # 後から増えた銘柄
            p0 = float(a.get("price", 1000))
            st = m["assets"][a["id"]] = {"price": p0, "history": [[t or time.time(), p0]], "bias": 0.0}
        return st

    def sector_target(self, a, dt):
        eff = (self.econ().get("sector_effects") or {}).get(a.get("sector")) or SECTOR_EFFECTS.get(a.get("sector")) or {}
        c = conditions(dt)
        return float(self.econ().get("sector_scale", 0.02)) * sum(float(v) for k, v in eff.items() if c.get(k))

    # ------------------------------------------------------------------ 時間の経過 (life.tick_world の 5 分ごと)
    def step(self, t):
        e = self.econ()
        m = self.m()
        assets = self.assets()
        if not assets:
            return
        dt = datetime.fromtimestamp(t)
        if random.random() < float(e.get("news_rate_per_hour", 0.2)) * STEP / 3600.0:
            pick = [a for a in assets if a.get("sector") != "index"] or assets     # まとめ (インデックス) には個別のニュースは出ない
            self._news(m, random.choice(pick), t, is_open(dt))
        if not is_open(dt):
            return
        pend = m.get("pending") or []
        for p in [x for x in pend if x["at"] <= t]:          # 噂の出来事が表に出る (core/rumor.py)
            pend.remove(p)
            a = next((x for x in assets if x["id"] == p["asset"]), None)
            if a:
                self._news(m, a, t, True, real=p["real"])
        first = not is_open(datetime.fromtimestamp(t - STEP))     # 寄り付き (前場・後場のはじめ)
        for a in assets:
            st = self.state(a, t)
            if first and dt.hour < 12:
                st["prev_close"] = st["price"]
            if first and st.get("gap"):
                st["price"] = max(1.0, st["price"] * math.exp(st.pop("gap")))   # 取引時間外のニュースは, 寄り付きの値段に
            mu = float(a.get("drift", 0))
            if st.get("bias_left", 0) > 0:
                mu += st.get("bias", 0.0)
                st["bias_left"] -= 1
            tgt = self.sector_target(a, dt)          # 季節・天気・行楽の時期: 目標の上下へ, ゆっくり寄る
            ds = (tgt - st.get("sec", 0.0)) * 0.03
            st["sec"] = st.get("sec", 0.0) + ds
            st["price"] = max(1.0, st["price"] * math.exp(mu + ds + float(a.get("vol", 0.003)) * random.gauss(0, 1)))
            if not st["history"] or t - st["history"][-1][0] >= 3600 or first:
                st["history"].append([t, round(st["price"], 2)])
                del st["history"][:-168]
        self._orders(m, t, dt)
        self._plans(m, t, dt)

    def _news(self, m, a, t, live, real=None):
        """銘柄のニュース. 見出しの向きどおりに動くとは限らない (的中率 news_accuracy. 誰にとっても同じ).
        取引時間中なら, しばらくの取引時間 (news_session_hours) その向きに寄る. 取引時間外なら, 次の寄り付きの値段に効く."""
        e = self.econ()
        acc = float(e.get("news_accuracy", 0.7))
        if real is None:
            d = random.choice((1, -1))
            real = d if random.random() < acc else -d
        else:                   # 噂で先に知られていた出来事 (本当の向きは決まっている). 見出しの当たりやすさは同じ
            d = real if random.random() < acc else -real
        N = e.get("news") or {}
        heads = list(N.get("up" if d > 0 else "down") or ["{name}に関するニュース"])
        if a.get("sector") in SECTOR_EFFECTS and a.get("sector") != "food":
            heads += N.get("store_up" if d > 0 else "store_down") or []
        lo, hi = (e.get("news_session_hours") or [0.5, 2])[:2]
        st = self.state(a, t)
        st["bias"] = real * float(e.get("news_bias", 0.0003)) * random.uniform(0.6, 1.4)
        st["bias_left"] = int(random.uniform(float(lo), float(hi)) * 3600 / STEP)
        if not live:
            st["gap"] = st.get("gap", 0.0) + real * float(e.get("news_gap", 0.004)) * random.uniform(0.5, 1.5)
        m["news"].append({"t": t, "asset": a["id"], "dir": d, "after": not live,
                          "text": random.choice(heads).replace("{name}", a.get("name", a["id"]))})
        del m["news"][:-30]

    # ------------------------------------------------------------------ 売買
    def reserved(self):
        """注文中の買いの分 (使えないお金)."""
        m = self.m()
        out = 0
        for o in m["orders"]:
            if o["side"] == "buy":
                p = o.get("limit") or self.state(self.asset(o["asset"]))["price"] * 1.03
                out += int(math.ceil(p * o["qty"]))
        return out

    def buy_power(self):
        return int(self.L.player_state()["money"]) - self.reserved()

    def fill(self, a, qty, price, t, why=""):
        """約定: qty > 0 で買い, < 0 で売り. (お金の動き, 金額, 売却損益) を返す. 足りなければ ValueError."""
        ps = self.L.player_state()
        m = self.m()
        name = a.get("name", a["id"])
        if qty > 0:
            amt = int(round(price * qty))
            if ps["money"] < amt:
                raise ValueError("お金が足りません（%s円必要）" % format(amt, ","))
            hold = m["holdings"].setdefault(a["id"], {"qty": 0, "cost": 0})
            ps["money"] -= amt
            self.L.ledger(t, -amt, "invest", "%s%sを買った" % (why, name))
            hold["qty"] = int(hold["qty"]) + qty
            hold["cost"] = int(hold.get("cost", 0)) + amt
            return {"p": -amt}, amt, 0
        n = -qty
        hold = m["holdings"].get(a["id"])
        if not hold or hold["qty"] < n:
            raise ValueError("そんなに持っていません（%s株）" % format(int((hold or {}).get("qty", 0)), ","))
        amt = int(round(price * n))
        cost = int(round(hold.get("cost", 0) * n / hold["qty"]))
        hold["qty"] = int(hold["qty"]) - n
        hold["cost"] = int(hold.get("cost", 0)) - cost
        if hold["qty"] <= 0:
            m["holdings"].pop(a["id"], None)
        ps["money"] += amt
        self.L.ledger(t, amt, "invest", "%s%sを売った" % (why, name))
        return {"p": amt}, amt, amt - cost

    def trade(self, aid, qty, now=None):
        """いますぐ売買する (取引時間中). 取引時間外なら, 次の取引開始に成行で売買する注文 (予約) にする.
        (お金の動き, 金額, 売却損益, 予約の注文 or None) を返す."""
        now = now or time.time()
        a = self.asset(aid)
        qty = int(qty)
        if not qty:
            raise ValueError("株数を指定してください")
        if not is_open(datetime.fromtimestamp(now)):
            o = self.order(aid, "buy" if qty > 0 else "sell", abs(qty), None, None, now)
            return {}, 0, 0, o
        price = self.state(a)["price"]
        if qty > 0 and self.buy_power() < price * qty:
            raise ValueError("お金が足りません（注文中の分を除いて %s円）" % format(max(0, self.buy_power()), ","))
        mv, amt, profit = self.fill(a, qty, price, now)
        self.L.save_player()
        return mv, amt, profit, None

    def order(self, aid, side, qty, limit=None, days=None, now=None):
        """注文を出す. limit: 指値 (None なら成行 = 次の取引で). days: 期限 (日数. 成行は次の取引日まで)."""
        now = now or time.time()
        a = self.asset(aid)
        qty = int(qty)
        if qty <= 0:
            raise ValueError("株数を指定してください")
        if side not in ("buy", "sell"):
            raise ValueError("買いか売りを指定してください")
        limit = float(limit) if limit not in (None, "", 0) else None
        if limit is not None and limit <= 0:
            raise ValueError("値段を指定してください")
        m = self.m()
        if side == "buy":
            p = limit or self.state(a)["price"] * 1.03
            if self.buy_power() < p * qty:
                raise ValueError("お金が足りません（注文中の分を除いて %s円）" % format(max(0, self.buy_power()), ","))
        else:
            have = int((m["holdings"].get(aid) or {}).get("qty", 0)) - sum(o["qty"] for o in m["orders"] if o["asset"] == aid and o["side"] == "sell")
            if have < qty:
                raise ValueError("売れる株が足りません（注文中の分を除いて %s株）" % format(max(0, have), ","))
        days = max(1, min(30, int(days or 1)))
        nd = next_open(datetime.fromtimestamp(now))
        end = nd.date() + timedelta(days=days - 1) if limit is not None else nd.date()
        while not trading_day(end):
            end += timedelta(days=1)
        o = {"id": "o%d" % int(now * 1000), "asset": aid, "side": side, "qty": qty, "limit": limit, "t": now,
             "until": datetime(end.year, end.month, end.day, 15, 0).timestamp()}
        m["orders"].append(o)
        self.L.save_player()
        return o

    def cancel(self, oid):
        m = self.m()
        n = len(m["orders"])
        m["orders"] = [o for o in m["orders"] if o["id"] != oid]
        if len(m["orders"]) == n:
            raise KeyError("注文が見つかりません")
        self.L.save_player()

    def _note(self, m, t, text, money=None):
        m["fills"].append({"t": t, "text": text})
        del m["fills"][:-20]
        self.app.solo.note("invest", text, t, icon="📈", name="株の注文", **({"money": money} if money else {}))

    def _orders(self, m, t, dt):
        keep = []
        for o in m["orders"]:
            a = next((x for x in self.assets() if x["id"] == o["asset"]), None)
            if not a:
                continue
            price = self.state(a)["price"]
            name = a.get("name", a["id"])
            kind = "指値" if o.get("limit") else "予約"
            hit = o.get("limit") is None or (price <= o["limit"] if o["side"] == "buy" else price >= o["limit"])
            if hit:
                try:
                    mv, amt, profit = self.fill(a, o["qty"] if o["side"] == "buy" else -o["qty"], price, t, why="%sで" % kind)
                    text = "%sの注文で、%sを%s株、%s円で%s" % (kind, name, format(o["qty"], ","), format(amt, ","),
                                                         "買った" if o["side"] == "buy" else "売った")
                    if o["side"] == "sell" and profit:
                        text += "（%s%s円）" % ("+" if profit > 0 else "−", format(abs(profit), ","))
                    self._note(m, t, text, mv)
                except ValueError as ex:
                    self._note(m, t, "%sの%sの注文（%s株）は、取り消しになった（%s）" % (name, kind, format(o["qty"], ","), ex))
                continue
            if t >= o["until"]:
                self._note(m, t, "%sの指値の注文（%s株・%s円%s）は、期限が来て取り消しになった" % (
                    name, format(o["qty"], ","), format(int(o["limit"]), ","), "以下で買う" if o["side"] == "buy" else "以上で売る"))
                continue
            keep.append(o)
        m["orders"] = keep

    def _plans(self, m, t, dt):
        ym = dt.strftime("%Y-%m")
        for p in m["plans"]:
            if dt.day < int(p.get("day", 1)) or m["plan_done"].get(p["id"]) == ym:
                continue
            m["plan_done"][p["id"]] = ym
            a = next((x for x in self.assets() if x["id"] == p["asset"]), None)
            if not a:
                continue
            price = self.state(a)["price"]
            qty = int(int(p["amount"]) // price)
            name = a.get("name", a["id"])
            if qty <= 0:
                self._note(m, t, "%sの積立: 株価（%s円）が積立額より高く、今月は買えなかった" % (name, format(int(price), ",")))
                continue
            if self.buy_power() < price * qty:
                self._note(m, t, "%sの積立: お金が足りず、今月は見送った" % name)
                continue
            mv, amt, _ = self.fill(a, qty, price, t, why="積立で")
            self._note(m, t, "積立で、%sを%s株、%s円で買った" % (name, format(qty, ","), format(amt, ",")), mv)

    def set_plan(self, aid, amount, day):
        a = self.asset(aid)
        amount, day = int(amount), int(day)
        if amount < 1000:
            raise ValueError("積立額は 1,000円から")
        if not 1 <= day <= 28:
            raise ValueError("積立日は 1〜28日")
        m = self.m()
        m["plans"] = [p for p in m["plans"] if p["asset"] != aid]
        p = {"id": "p%d" % int(time.time() * 1000), "asset": a["id"], "amount": amount, "day": day}
        # 今月の積立日をもう過ぎていたら, 来月から
        if datetime.now().day > day:
            m["plan_done"][p["id"]] = datetime.now().strftime("%Y-%m")
        m["plans"].append(p)
        self.L.save_player()
        return p

    def drop_plan(self, pid):
        m = self.m()
        m["plans"] = [p for p in m["plans"] if p["id"] != pid]
        self.L.save_player()

    # ------------------------------------------------------------------ 画面
    def view(self, now=None):
        now = now or time.time()
        m = self.m()
        dt = datetime.fromtimestamp(now)
        out = []
        for a in self.assets():
            st = self.state(a)
            hist = [x[1] for x in st["history"]]
            base = st.get("prev_close") or next((x[1] for x in reversed(st["history"]) if now - x[0] >= 86400), hist[0] if hist else st["price"])
            h = m["holdings"].get(a["id"]) or {}
            out.append({"id": a["id"], "name": a.get("name", a["id"]), "icon": a.get("icon", ""), "desc": a.get("desc", ""),
                        "sector": a.get("sector", ""), "sector_label": SECTOR_LABEL.get(a.get("sector"), ""),
                        "price": round(st["price"], 1), "day": round((st["price"] / base - 1) * 100, 1) if base else 0,
                        "history": hist[-72:] + [round(st["price"], 1)],
                        "qty": int(h.get("qty", 0)), "cost": int(h.get("cost", 0)), "value": int(h.get("qty", 0) * st["price"])})
        names = {a["id"]: a.get("name", a["id"]) for a in self.assets()}
        op = is_open(dt)
        nx = next_open(dt)
        wd = "月火水木金土日"[nx.weekday()]
        return {"assets": out, "news": [dict(n, name=names.get(n["asset"], n["asset"])) for n in reversed(m["news"][-12:])],
                "open": op, "until": session_end(dt).strftime("%H:%M") if op else None,
                "next": None if op else ("%s %s" % ("今日" if nx.date() == dt.date() else "%d/%d（%s）" % (nx.month, nx.day, wd), nx.strftime("%H:%M"))),
                "orders": [dict(o, name=names.get(o["asset"], o["asset"])) for o in m["orders"]],
                "plans": [dict(p, name=names.get(p["asset"], p["asset"])) for p in m["plans"]],
                "fills": list(reversed(m["fills"][-6:])), "buy_power": self.buy_power(), "rumors": self.app.rumors.view(now)}
