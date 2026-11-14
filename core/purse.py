"""キャラクターの所持金の収支 (生活の型の段 3. A17): 型ごとの収入と, 住まい・暮らし・買い物のお金.

- 一日のシミュレートは作らない. 予定 (schedule) と日ごとのずれ (rhythm) をその人の一日とみなし, 日付が変わるときの
  日締め (life.step → close) で, 終わった日の分を出す.
- 収入 (lifetype.TYPES[型]["pay"]. 額は econ.her_daily_income × 30.4 を 1 か月の基準 S として倍率で持つ):
  monthly   給料日 (payday) に S × rate. 風邪で休んだ勤務日は引き, 残業は足す. 賞与の月 (bonus) は 0.8 か月ぶんを足す
  hourly    働いた時間 × 時給 (S × rate / hours) を給料日に. 学生は月はじめに仕送り (S × allowance)
  irregular 人ごとの入金日に S × rate × 月ごとの揺らぎ (少ない月・入らない月もある)
  型の無い人 (life.type が無い) は, 以前のまま (毎日 her_daily_income).
- 出費 (econ.her_living_cost_per_day を 1 日の基準として): 住まい 4 割 (月はじめにまとめて. 一人暮らしの人だけ)・
  暮らし 3.5 割 (毎日. 一人暮らしの人だけ)・買い物と交際費 2.5 割 (日ごとのくじ. 給料日のあとは多め, 給料日の前は少なめ,
  苦しいときはさらに控える. 使い方の荒さは性格の traits.savings). 同居相手の住まい・暮らしは, あなたの家の分として pay_home で分ける.
- 足りなければ 0 円で止める (キャラの借金は作らない). 住まい・暮らしが払いきれない日は, 以前と同じくストレス・機嫌に響く.
- 苦しい (tight): 所持金が暮らし 10 日ぶんを切っている. 覚えずに, その場の残高から見る (お小遣いをもらえば, すぐに抜ける).
  効き目: おごらない・割り勘を申し出る (life.plan_payment) / 誘いが減り, お金のかかる行き先を避ける (appoint) /
  お金を素直に受け取りやすい (bonds.gift_feel. 誇りの高い性格は, それでも断る).
- くじは「人 × 日付」から決める (その場で進めても, まとめて追いついても同じ結果). 状態 st["money"]["pay"] に覚えるのは,
  締めた最後の日 (last. 二重に締めない)・今の給料の期間に働いた時間 (h)・休んだ勤務日 (sick)・残業 (ot. 分).
- 14 日を超えて追いつけなかった分 (engine.tick が捨てる分) は, 日数 × その人の平均でまとめて足す (skip).
- 相手の所持金は画面に出さない. 分かるのは振る舞いと一言だけ.
"""
import random
from datetime import date, datetime, timedelta

from . import lifetype
from .rhythm import WORK_ACTS, WORK_WORDS

MONTH = 30.4
WORK_DAYS = 21.0            # 月給の人の, ひと月の勤務日 (休んだ日に引く額の元)
WORK_HOURS = 168.0          # 同じく勤務時間 (残業代の元)
BONUS = 0.8                 # 賞与: 月給の何か月ぶん
HOME, LIVING, FUN = 0.4, 0.35, 0.25      # 1 日の出費の基準の内訳 (住まい・暮らし・買い物と交際費)
FUN_RATE = 0.35             # 買い物・交際費のある日の割合
TIGHT_DAYS = 10             # 暮らし何日ぶんを切ったら「苦しい」
START_TYPE = {"office": 1.2, "night": 1.2, "service": 1.0, "shift": 0.8, "student": 0.4, "freelance": 1.0}   # 初めの所持金の倍率


def _mins(s):
    h, m = str(s or "00:00").split(":")
    return int(h) * 60 + int(m)


def is_work(e):
    return e.get("activity") in WORK_ACTS or any(w in (e.get("label") or "") for w in WORK_WORDS)


def work_hours(char, d):
    """その日の予定の, 仕事・バイトの時間 (時間. 講義は入れない). 日をまたぐ 1 行は, その日の夜の分と翌朝の分をまとめて数える."""
    from .engine import day_match
    dt = datetime(d.year, d.month, d.day, 12, 0)
    tot = 0
    for e in char.get("schedule") or []:
        if is_work(e) and day_match(e.get("days"), dt):
            f, t = _mins(e.get("from", "00:00")), _mins(e.get("to", "24:00"))
            tot += (t - f) if t > f else (1440 - f + t)
    return tot / 60.0


def age_mult(age):
    """初めの所持金の, 年齢の倍率 (20 歳で 0.5, 30 歳で 1.0, 50 歳で 2.0. 年齢が無ければ 1.0)."""
    try:
        return max(0.5, min(2.0, 0.5 + (int(age) - 20) * 0.05))
    except (TypeError, ValueError):
        return 1.0


class Purse:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 型・基準
    def spec(self, char):
        """その人の型の (pay, cost). 型が無ければ (None, None)."""
        t = lifetype.TYPES.get((char.get("life") or {}).get("type"))
        return (t["pay"], t["cost"]) if t else (None, None)

    def base(self):
        e = self.app.life.econ()
        return float(e.get("her_daily_income", 2500)) * MONTH, float(e.get("her_living_cost_per_day", 1500))

    def lives_here(self, char):
        return self.app.bonds.living() == char.get("id")

    def payday(self, char, pay):
        if pay["kind"] == "irregular":
            return random.Random("purse:payday:%s" % char.get("id")).randint(1, 28)
        return int(pay.get("payday", 25))

    def spender(self, char):
        """使い方の荒さ (性格の traits.savings 0.5〜4.0 → 1.27〜0.62)."""
        s = max(0.3, float(self.app.traits(char).get("savings", 1.0)))
        return max(0.5, min(1.4, s ** -0.35))

    def rec(self, char, st, d=None):
        """st["money"]["pay"]. 初めて使うとき: 締めた最後の日を d の前の日に (それより前は, 以前の決め方で済んでいる).
        時給の人は, 前の給料日から今までに予定どおり働いた分を入れておく (それまでも働いていたので)."""
        m = self.app.life.her_money(st)
        p = m.get("pay")
        if p is None:
            d = d or date.today()
            p = m["pay"] = {"last": (d - timedelta(days=1)).isoformat(), "h": 0.0, "sick": 0, "ot": 0}
            pay, _ = self.spec(char)
            if pay and pay["kind"] == "hourly":
                x, pd = d - timedelta(days=1), self.payday(char, pay)
                for _ in range(31):
                    p["h"] += work_hours(char, x)
                    if x.day == pd:
                        break
                    x -= timedelta(days=1)
                p["h"] = round(p["h"], 2)
        return p

    # ------------------------------------------------------------------ 苦しいか
    def living_per_day(self, char):
        _, out = self.base()
        _, cost = self.spec(char)
        return out * (cost or {}).get("living", 1.0)

    def tight(self, char, st):
        """苦しい: 所持金が暮らし 10 日ぶんを切っている (その場の残高から)."""
        return self.app.life.her_money(st)["a"] < TIGHT_DAYS * self.living_per_day(char)

    # ------------------------------------------------------------------ 日締め
    def _ot(self, char, st, d):
        r = (st.get("rhythm") or {}).get(d.isoformat())
        if r is None:
            from .engine import day_match
            from .rhythm import decide
            r = decide(self.app, char, None, d, day_match, use_state=False)
        return int(r.get("ot", 0))

    def _ill(self, st, d):
        il = st.get("ill")
        noon = datetime(d.year, d.month, d.day, 12, 0).timestamp()
        return bool(il and il.get("t0", 0) <= noon < il.get("until", 0))

    def month_factor(self, char, d):
        """在宅・フリーランスの, その月の入金の揺らぎ (平均 1. 入らない月は 0)."""
        rnd = random.Random("purse:month:%s:%04d-%02d" % (char.get("id"), d.year, d.month))
        if rnd.random() < 0.1:
            return 0.0
        return rnd.lognormvariate(-0.125, 0.5) / 0.9          # 対数正規の平均は exp(-0.125 + 0.125) = 1. 入らない月のぶん 0.9 で割る

    def income(self, char, st, p, d1):
        """d1 (明けた日) に入るお金. 給料日なら, 覚えていた働きぶりを精算して消す."""
        pay, _ = self.spec(char)
        S, _ = self.base()
        got = 0.0
        if pay.get("allowance") and d1.day == 1:
            got += S * float(pay["allowance"])                    # 仕送り
        if d1.day != self.payday(char, pay):
            return got
        kind = pay["kind"]
        if kind == "monthly":
            sal = S * float(pay["rate"])
            got += max(0.0, sal - p["sick"] * sal / WORK_DAYS) + p["ot"] / 60.0 * sal / WORK_HOURS * 1.25
            if d1.month in (pay.get("bonus") or ()):
                got += sal * BONUS
        elif kind == "hourly":
            got += (p["h"] + p["ot"] / 60.0 * 1.25) * S * float(pay["rate"]) / float(pay.get("hours", WORK_HOURS))
        else:
            got += S * float(pay["rate"]) * self.month_factor(char, d1)
        p.update(h=0.0, sick=0, ot=0)
        return got

    def fun_phase(self, char, pay, d):
        """給料日からの日数で, 使い方が変わる (あとは多め・前は少なめ)."""
        n = (d.day - self.payday(char, pay)) % 30
        return 1.5 if n < 7 else 0.5 if n >= 21 else 1.0

    def close(self, char, st, d):
        """日締め: d (終わった日) の働きぶりを覚え, 明けた日に入るお金と, d の出費を出す. 同じ日を二度は締めない.
        住まい・暮らしが払いきれなかったら True (呼ぶ側がストレス・機嫌に)."""
        L = self.app.life
        hm = L.her_money(st)
        pay, cost = self.spec(char)
        if not pay:                                   # 型の無い人: 以前のまま
            e = L.econ()
            hm["a"] += int(e.get("her_daily_income", 2500))
            if self.lives_here(char):
                return False
            own = int(e.get("her_living_cost_per_day", 1500))
            short = hm["a"] < own
            hm["a"] -= min(own, max(hm["a"], 0))
            return short
        p = self.rec(char, st, d)
        if d.isoformat() <= p["last"]:
            return False
        p["last"] = d.isoformat()
        wh = work_hours(char, d)
        if wh > 0:
            if self._ill(st, d):
                p["sick"] += 1
            else:
                p["h"] = round(p["h"] + wh, 2)
                p["ot"] += self._ot(char, st, d)
        d1 = d + timedelta(days=1)
        hm["a"] += int(round(self.income(char, st, p, d1), -2))
        _, out = self.base()
        need = 0
        if not self.lives_here(char):
            need = out * LIVING * cost["living"]
            if d1.day == 1:
                need += out * MONTH * HOME * cost["home"]
        need = int(round(need, -1))
        short = hm["a"] < need
        hm["a"] -= min(need, max(hm["a"], 0))
        rnd = random.Random("purse:%s:%s" % (char.get("id"), d.isoformat()))
        if rnd.random() < FUN_RATE:
            amt = out * FUN / FUN_RATE * cost["living"] * self.spender(char) * self.fun_phase(char, pay, d) * rnd.uniform(0.4, 1.6)
            if self.tight(char, st):
                amt *= 0.3
            hm["a"] -= min(int(round(amt, -2)), max(hm["a"], 0))
        return short

    # ------------------------------------------------------------------ 平均 (追いつけなかった分・確かめ)
    def average(self, char):
        """1 日あたりの平均の (収入, 出費). 型の無い人は以前の額."""
        S, out = self.base()
        pay, cost = self.spec(char)
        live = self.lives_here(char)
        if not pay:
            return S / MONTH, 0.0 if live else out
        if pay["kind"] == "monthly":
            inc = S * pay["rate"] * (1 + BONUS * len(pay.get("bonus") or ()) / 12.0)
        elif pay["kind"] == "hourly":
            week = sum(work_hours(char, date(2026, 11, 2) + timedelta(days=i)) for i in range(7))
            inc = week / 7.0 * MONTH * S * pay["rate"] / float(pay.get("hours", WORK_HOURS)) + S * float(pay.get("allowance", 0))
        else:
            inc = S * pay["rate"]
        spend = out * FUN * cost["living"] * self.spender(char)
        if not live:
            spend += out * (LIVING * cost["living"] + HOME * cost["home"])
        return inc / MONTH, spend

    def skip(self, char, st, days):
        """追いつけなかった日数ぶんを, 平均でまとめて足す (減る人は 0 円で止める)."""
        if days <= 0:
            return 0
        inc, spend = self.average(char)
        hm = self.app.life.her_money(st)
        add = int(round((inc - spend) * days, -2))
        hm["a"] = max(0, hm["a"] + add) if add < 0 else hm["a"] + add
        return add

    # ------------------------------------------------------------------ 初めの所持金 (新しく現れる人)
    def start_mult(self, char):
        return START_TYPE.get((char.get("life") or {}).get("type"), 1.0) * age_mult(char.get("age"))

