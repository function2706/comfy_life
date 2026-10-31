"""キャラの暮らし: お金 (所持金・生活費・投資) と, キャラ側の出来事 (機嫌の理由・おねだり・留守中のこと).

- あなたのお金と投資は data/player.json (キャラ共通), キャラのお金は各キャラの state["money"].
- 暮らしのお金は家ごと: あなたが払うのは, あなたの家の分だけ. 毎日の生活費 (living_cost_per_day は二人暮らしの額.
  一人なら半分) と, 月はじめの基本コスト (家賃・光熱費・通信費. home_cost_per_month). 一緒に暮らしている相手とは
  その人の living_policy (折半 / あなた / 相手) で分ける. 一緒に暮らしていない人は, 自分の生活費を自分で払う (her_living_cost_per_day).
- 払えなければ, 連絡先を知っている人に借りる (頼む相手・断られるか・印象がどう変わるかは間柄・仲・性格・懐具合しだい).
  借りられなければ借金になる (player.json の debt). 借りたお金は loans に残る.
- 借金のあいだ (debt か loans が残っている) は, 必需品 (食材・日用品. items.ESSENTIAL_KINDS) しか買えない. スキルの伸びは抑えない.
  借金 (debt) には月はじめに少し利息がつく (debt_interest_per_month). お金があるときに返せる (repay).
  事情を知っている相手 (お金を貸した人・同居相手) は, 返すのが遅いと心配したり不信感を持ったりする (性格・仲しだい. money_concern).
- 出来事は data/events.json. 時間の経過でときどき起き, 機嫌などを動かし, 「理由」として記録される.
- 機嫌の理由は state["reasons"] に良い方・悪い方とも記録する: キャラ側の出来事 (event) か, あなたの行動 (player) か,
  あなたがその理由を知っているか (told). 謝る・相談にのる・何かあった？ の反応はこれで変わる.
"""
import math
import random
import time
import uuid
from datetime import datetime

from . import cond, store

WHO = {"p": "あなた", "a": "キャラ"}
# あなたのスキル: 会話・スキンシップ・料理・仕事・家事・気配り・身だしなみ・やりくり (後の 4 つは, 以前のデータには初期値で補う)
SKILLS = ("talk", "touch", "cook", "work", "house", "care", "groom", "budget", "write")
SKILL_RATE = 0.4         # 経験のうち身につく割合
SKILL_DAY_SOFT = 2.0     # その日に伸びた量がこれだけあると, 次の経験は半分しか身につかない
RUST_AFTER_DAYS = 10     # これだけ使わないスキルは, 少しずつ鈍る
RUST_RATE = 0.02         # 鈍る速さ (1 日あたり, 最高値の半分 との差のうち). 使わない日が続くほど (10 日かけて) この速さに
RUST_FLOOR = 0.5         # 鈍っても, これまでの最高値のこの割合までしか下がらない
RELEARN = 2.5            # 鈍ったあと, 元の高さ (最高値) までは戻りやすい


def skill_mult_of(v):
    """スキルの値 (0〜100) による効き目の倍率 (0.6〜1.4). 内職の単独版 (tools/puzzle_lab.py) の試算にも使う."""
    return 0.6 + float(v) / 100.0 * 0.8


def _amount(v):
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return int(random.randint(int(v[0]) // 100, int(v[1]) // 100) * 100)
    return int(v or 0)



def chat_lines():
    from .chat import LINES
    return LINES


CAR_MONTHLY = 18000         # 車を持っていると毎月かかる (駐車場・保険)

class Life:
    def __init__(self, app):
        self.app = app
        self.player = None

    def econ(self):
        return self.app.world.get("economy") or {}

    # ================================================================== あなたのお金・スキル・投資
    def player_state(self):
        if self.player is None:
            self.player = store.load(store.wpath("player.json"))
        if self.player is None:
            t = time.time()
            self.player = {"money": int(self.econ().get("start_money_player", 30000)), "last_tick": t}
        ps = self.player
        ps.setdefault("skills", {k: 10.0 for k in SKILLS})
        ps.setdefault("stamina", 100.0)          # あなたの体力 (仕事・内職で減り, 時間で戻る. 寝ると早い)
        ps.setdefault("work_log", {})            # 日付 -> その日に給料が出た時間
        for k in SKILLS:
            ps["skills"].setdefault(k, 10.0)
        if "market" not in ps:
            self._init_market(ps)
            self.save_player()
        return ps

    def save_player(self):
        store.save(store.wpath("player.json"), self.player)

    # ---------------------------------------------------------- スキル
    def skill(self, k):
        return float(self.player_state()["skills"].get(k, 10.0))

    def skill_mult(self, k):
        """スキルによる効き目の倍率 (0.6〜1.4)."""
        return skill_mult_of(self.skill(k))

    def skill_soft(self, k):
        """家事・気配り・身だしなみ・やりくりの効き目 (0〜1. 控えめに使う: 確定的な結果にしないため, 呼ぶ側で小さく掛ける)."""
        return max(0.0, min(1.0, (self.skill(k) - 10.0) / 90.0))

    def train(self, k, gain):
        """スキルを伸ばす. gain は経験の量 (1 回の会話で 1.2, 仕事 1 時間で 0.5 など). 伸びた量を返す.
        数か月かけて少しずつ上達する: 経験の SKILL_RATE 倍しか身につかず, 上がるほど伸びにくく ((1 - 値/100)^1.5),
        同じ日にたくさんやるほど身につきにくい (その日に伸びた量で割る). 得意・不得意 (ワールドごとに一度決まる aptitude) と,
        その日の調子 (伸びない日もある) で揺れる."""
        ps = self.player_state()
        sk = ps["skills"]
        old = float(sk.get(k, 10.0))
        apt = ps.setdefault("aptitude", {})
        if k not in apt:
            apt[k] = round(random.uniform(0.7, 1.3), 2)
        day = datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d")
        sd = ps.get("skill_day") or {}
        if sd.get("d") != day:
            sd = {"d": day, "f": {}, "got": {}}
            ps["skill_day"] = sd
        if k not in sd["f"]:
            sd["f"][k] = round(0.1 if random.random() < 0.15 else random.uniform(0.5, 1.3), 2)     # 伸びない日もある
        got = float(sd["got"].get(k, 0.0))
        g = float(gain) * SKILL_RATE * apt[k] * sd["f"][k] * max(0.0, 1.0 - old / 100.0) ** 1.5 / (1.0 + got / SKILL_DAY_SOFT)
        g *= self.app.body.train_mult()          # 体調が悪いと伸びにくい
        peak = float(ps.setdefault("skill_peak", {}).get(k, old))
        if old < peak and g > 0:        # 鈍ったぶんは戻りやすい (元の高さまで)
            back = min(peak - old, g * RELEARN)
            g = back + max(0.0, g - back / RELEARN)
        ps.setdefault("skill_used", {})[k] = time.time()
        new = min(100.0, old + g)
        ps["skill_peak"][k] = round(max(peak, new), 2)
        sd["got"][k] = round(got + new - old, 3)
        sk[k] = round(new, 2)
        self.save_player()
        return round(new - old, 2)

    def rust(self, t):
        """日付が変わったとき: しばらく使わないスキルは少しずつ鈍る (最高値の半分までで止まる. 完全には消えない)."""
        ps = self.player_state()
        used = ps.setdefault("skill_used", {})
        peak = ps.setdefault("skill_peak", {})
        for k in SKILLS:
            v = float(ps["skills"].get(k, 10.0))
            peak[k] = max(float(peak.get(k, v)), v)
            if k not in used:
                used[k] = t                         # 以前のデータ: いまから数える
                continue
            idle = (t - used[k]) / 86400.0 - RUST_AFTER_DAYS
            floor = max(min(v, 10.0), peak[k] * RUST_FLOOR)
            if idle <= 0 or v <= floor:
                continue
            v -= (v - floor) * RUST_RATE * min(1.0, idle / 10.0)
            ps["skills"][k] = round(v, 2)

    def rusty(self, now=None):
        """鈍ってきているスキル (しばらく使っていなくて, 最高値より下がっている)."""
        ps = self.player_state()
        now = now or time.time()
        return [k for k in SKILLS if now - float((ps.get("skill_used") or {}).get(k, now)) > RUST_AFTER_DAYS * 86400
                and float((ps.get("skill_peak") or {}).get(k, 0)) - float(ps["skills"].get(k, 10)) >= 0.5]

    # ---------------------------------------------------------- 市場 (銘柄・ニュース)
    def assets(self):
        return self.econ().get("assets") or []

    def _init_market(self, ps):
        t = time.time()
        m = ps["market"] = {"assets": {}, "holdings": {}, "news": []}
        for a in self.assets():
            self._asset_state(m, a, t)
        # 以前の「投資」(1 銘柄) を持っていたら, 最初の銘柄 (インデックス) の保有に移す
        if ps.get("units") and self.assets():
            store.backup("以前の投資 (1 銘柄) を株の保有に移す")
            first = self.assets()[0]
            st = self._asset_state(m, first, t)
            value = float(ps["units"]) * float(ps.get("price", 1000))
            m["holdings"][first["id"]] = {"qty": max(1, int(round(value / st["price"]))), "cost": int(ps.get("invested", value))}
        for k in ("units", "invested", "price", "history"):
            ps.pop(k, None)

    def _asset_state(self, m, a, t=None):
        return self.app.market.state(a, t)

    def tick_world(self, now=None):
        """市場の値動き・ニュースと, あなたの定期収入をリアル時間で進める."""
        ps, e = self.player_state(), self.econ()
        now = now or time.time()
        t = max(ps.get("last_tick", now), now - 14 * 86400)
        step = 300
        changed = False
        while t + step <= now:
            t += step
            changed = True
            self.app.market.step(t)          # 株: 値動きは取引時間だけ. 注文・積立 (core/market.py)
            self.app.earn.step(t, step)          # フリマの売れ行き・宝くじの抽せん (core/earn.py)
            mode = self.app.presence.at(t)
            self.app.body.step(t, step / 3600.0, mode)          # お腹と栄養 (あなた)
            if mode != "work":
                rec = float(e.get("stamina_recover_sleep" if mode == "sleep" else "stamina_recover", 12 if mode == "sleep" else 5))
                sl = self.app.presence.rec().get("solo") or {}
                if mode == "busy" and sl.get("kind") == "rest":      # 一人で休んでいる: 寝るほどではないが早く戻る
                    rec = float(e.get("stamina_recover_rest", 9))
                rec *= self.app.body.stamina_mult()                  # お腹がすいている・体調が悪いと戻りにくい
                ps["stamina"] = min(self.app.body.stamina_cap(), float(ps.get("stamina", 100)) + rec * step / 3600.0)
            d0, d1 = datetime.fromtimestamp(t - step).date(), datetime.fromtimestamp(t).date()
            if d0 != d1:
                self.app.earn.daily(t, d0.month != d1.month)      # 時給の見直し・賞与・バイトの休み (core/earn.py)
                self.rust(t)
                self.app.body.daily(t)                         # 体調 (その日の過ごし方しだい)
                ps["money"] += int(e.get("player_daily_income", 1000))
                self.ledger(t, int(e.get("player_daily_income", 1000)), "income", "日々の収入")
                live = self.app.bonds.living()
                self.pay_home(int(e.get("living_cost_per_day", 3000)) // (1 if live else 2), t, "生活費")
                if d0.month != d1.month:
                    self.charge_interest(t)
                    self.pay_home(int(e.get("home_cost_per_month", 60000)), t, "%d月の家賃・光熱費・通信費" % d1.month)
                    if self.app.items.count("car") > 0:           # 車: 駐車場・保険 (毎月)
                        ps["money"] -= CAR_MONTHLY
                        self.ledger(t, -CAR_MONTHLY, "transport", "%d月の駐車場・保険（車）" % d1.month)
        ps["last_tick"] = t
        if changed:
            self.save_player()

    def portfolio_value(self):
        m = self.player_state()["market"]
        return int(sum(h["qty"] * m["assets"].get(k, {}).get("price", 0) for k, h in m["holdings"].items()))

    def portfolio_cost(self):
        return int(sum(h.get("cost", 0) for h in self.player_state()["market"]["holdings"].values()))

    def trade(self, asset, qty):
        """銘柄を売買する (qty > 0 で買い, < 0 で売り). 取引時間外なら予約の注文. (お金の動き, 金額, 売却損益, 予約 or None)."""
        return self.app.market.trade(asset, qty)

    def market_view(self):
        return self.app.market.view()

    # ---------------------------------------------------------- 仕事・内職
    def work_hours(self, t0, t1, record=False):
        """t0〜t1 のうち給料が出る時間: 働ける時間帯 (work_hours) の中だけ, 1 日の上限 (work_max_hours) まで.
        record=True ならその日の働いた時間に記録する. (給料の出る時間, 離れていた時間) を返す."""
        e = self.econ()
        lo, hi = (e.get("work_hours") or [6, 23])[:2]
        cap = float(e.get("work_max_hours", 9))
        log = dict(self.player_state().get("work_log") or {})
        paid, t, step = 0.0, float(t0), 300.0
        while t < t1:
            dt = datetime.fromtimestamp(t)
            day = dt.strftime("%Y-%m-%d")
            seg = min(step, t1 - t) / 3600.0
            if lo <= dt.hour < hi and log.get(day, 0) < cap:
                add = min(seg, cap - log.get(day, 0))
                log[day] = log.get(day, 0) + add
                paid += add
            t += step
        if record:
            keep = sorted(log)[-14:]
            self.player_state()["work_log"] = {k: round(log[k], 3) for k in keep}
            self.save_player()
        return paid, (t1 - t0) / 3600.0

    def work_pay(self, t0, t1, record=False):
        """仕事から帰ったときの稼ぎ (時給 x 給料の出る時間 x 仕事スキル x 体力). 15 分未満は 0.
        (稼ぎ, 給料の出る時間, 離れていた時間) を返す."""
        e = self.econ()
        if (t1 - t0) < 900:
            return 0, 0.0, (t1 - t0) / 3600.0
        h, raw = self.work_hours(t0, t1, record)
        pay = int(round(float(self.app.earn.wage()) * h * self.skill_mult("work") * self.app.body.work_mult() / 10.0)) * 10
        if record:
            self.app.earn.record_main(h, pay, t1)        # 月ごとの勤務 (時給の見直し・賞与のもと. core/earn.py)
        return pay, h, raw

    def stamina(self):
        return float(self.player_state().get("stamina", 100))

    def tire(self, amount):
        """体力を減らす (負の量は無視する. 体力は時間・休息でだけ戻る)."""
        ps = self.player_state()
        ps["stamina"] = max(0.0, float(ps.get("stamina", 100)) - max(0.0, float(amount)))
        self.save_player()

    def stamina_mult(self):
        """体力が減っていると, キャラへの行動のうれしい効き目が落ちる (体力 0 で 0.6 倍)."""
        return 0.6 + 0.4 * self.stamina() / 100.0

    def recent_work(self, days=3):
        log = self.player_state().get("work_log") or {}
        return round(sum(v for k, v in sorted(log.items())[-days:]), 2)

    def her_money(self, st):
        m = st.setdefault("money", {})
        if "a" not in m:
            m["a"] = int(self.econ().get("start_money_her", 20000))
        return m

    def money_ctx(self, st):
        ps = self.player_state()
        value = self.portfolio_value()
        ctx = {"my_money": ps["money"], "her_money": self.her_money(st)["a"] if st is not None else 0, "invest_value": value,
               "profit": value - self.portfolio_cost() if value else 0}
        ctx.update({"sk_" + k: round(v, 1) for k, v in ps["skills"].items()})
        ctx["my_stamina"] = round(float(ps.get("stamina", 100)), 1)
        ctx["work_3d"] = self.recent_work(3)            # ここ 3 日で働いた時間
        return ctx

    def ledger(self, t, amount, cat, note=""):
        """財布のお金の出入りを, 裏の記録に残す (見えるのは家計簿につけた分だけ. core/kakeibo.py)."""
        self.app.kakeibo.add(t, amount, cat, note)
        mt = getattr(self.app, "moneytalk", None)
        if mt:
            mt.spent(t or time.time(), amount, cat, note or "")    # 宝くじ・株・高い買い物 (相手が口を出すことも)

    def move(self, st, dp=0, da=0, cat="other", note=""):
        """お金を動かす (マイナス可). 実際に動いた額を返す. cat / note: あなたのお金の出入りの記録 (家計簿の元)."""
        ps = self.player_state()
        ps["money"] += int(dp)
        if dp:
            self.ledger(time.time(), dp, cat, note)
        if da:                                  # st なしで呼べるのは, あなたのお金だけ動かすとき
            self.her_money(st)["a"] += int(da)
        self.save_player()
        out = {}
        if dp:
            out["p"] = int(dp)
        if da:
            out["a"] = int(da)
        return out

    # ---------------------------------------------------------- 支払い
    def plan_payment(self, char, st, cost, fixed=None):
        """誰が払うか決める. 方針: me (あなた) / split (割り勘) / her (おごってもらう) / auto (おまかせ).
        払えなければ ValueError."""
        ps, hm = self.player_state(), self.her_money(st)
        pol = fixed or char.get("pay_policy") or "auto"
        if pol == "auto":
            r = random.random()
            aff = st["params"].get("affection", 50)
            fv = self.app.attach.factor(char, st, "devotion")     # 献身的なほど払ってくれ, 自分優先なほど払わせる
            ph = max(0.0, 0.2 + aff / 500.0 + 0.25 * fv)
            pol = "her" if (r < ph and hm["a"] >= cost * 2) else "split" if r < max(ph, 0.55 + 0.15 * fv) else "me"
        if pol == "split":
            half = cost // 2
            if ps["money"] >= cost - half and hm["a"] >= half:
                return {"payer": "split", "p": -(cost - half), "a": -half}
            pol = "me" if ps["money"] >= cost else "her"
        if pol == "her" and hm["a"] >= cost:
            self.app.attach.give(char, st, "her", 2, "払ってくれた")
            return {"payer": "her", "p": 0, "a": -cost}
        if ps["money"] >= cost:
            return {"payer": "me", "p": -cost, "a": 0}
        if hm["a"] >= cost:
            return {"payer": "her", "p": 0, "a": -cost}
        raise ValueError("お金が足りません（費用 %s円 / あなた %s円）" % (format(cost, ","), format(ps["money"], ",")))

    # ================================================================== キャラの毎日
    def step(self, char, st, t0, t1, h):
        """5 分ごと: 日付が変わったら収入と (一緒に暮らしていなければ) 自分の生活費, ときどき出来事.
        一緒に暮らしている相手の生活費は, あなたの家の分として tick_world (pay_home) で分ける."""
        e = self.econ()
        hm = self.her_money(st)
        if datetime.fromtimestamp(t0).date() != datetime.fromtimestamp(t1).date():
            hm["a"] += int(e.get("her_daily_income", 2500))
            if self.app.bonds.living() != char["id"]:
                own = int(e.get("her_living_cost_per_day", 1500))
                if hm["a"] < own:
                    self.app.apply_effects(st, {"stress": 10, "mood": -5})      # 自分の生活費が苦しい
                hm["a"] -= min(own, max(hm["a"], 0))
            self.money_concern(char, st, t1)
        if datetime.fromtimestamp(t0).date() != datetime.fromtimestamp(t1).date():
            self.app.attach.daily(char, st, t1)                  # 献身度・依存度の日ごとの動き
            self.app.anniv.daily(char, st, t1)                   # 誕生日・記念日 (前の日の受け止め・今日のこと)
            self.app.chores.daily(char, st, t1)                  # 同居相手: 今日, 自分の担当の家事をやる時刻
        self.app.manners.settle(char, st, t1)                    # 「態度で」の理由が消える・あいさつの習慣が途切れた
        dt = datetime.fromtimestamp(t1)
        ctx = self.app.context(char, st, dt, view=False)         # 本人の過ごし方 (離れていても)
        if ctx["asleep"]:
            return
        if random.random() < float(e.get("event_rate_per_hour", 0.08)) * h:
            self.happen(char, st, t1, ctx)

    # ---------------------------------------------------------- あなたの家の暮らしのお金
    def pay_home(self, cost, t, what):
        """あなたの家の分 (生活費・家賃など) を払う. 一緒に暮らしている相手とは, その人の方針で分ける.
        相手が払えない分はあなたが肩代わりし, あなたも払えなければ借りるか借金. あなたが払った額を返す."""
        app = self.app
        live = app.bonds.living()
        mine = cost
        if live:
            char, st = app.chars[live], app.state(live)
            pol = char.get("living_policy") or "split"
            share_a = cost - {"me": cost, "her": 0}.get(pol, cost // 2)
            hm = self.her_money(st)
            pay_a = min(share_a, max(hm["a"], 0))
            hm["a"] -= pay_a
            mine = cost - pay_a
            app.save_state(live)
        self.pay(mine, t, what)
        return mine

    def pay(self, amount, t, what):
        """あなたが払う. 足りなければ, 連絡先の人に借りる (borrow). それでも足りなければ借金 (debt)."""
        ps = self.player_state()
        amount = int(amount)
        if amount <= 0:
            return
        cat = "living" if what == "生活費" else "fixed"
        have = max(int(ps["money"]), 0)
        if have >= amount:
            ps["money"] -= amount
            self.ledger(t, -amount, cat, what)
            self.save_player()
            return
        ps["money"] -= have
        short = amount - have
        got = self.borrow(short, t, what)
        ps["money"] -= got                      # 借りた分は, そのまま支払いに
        if have + got:
            self.ledger(t, -(have + got), cat, what + ("（足りない分は借りた）" if got else "（払いきれなかった）"))
        short -= got
        if short > 0:
            if not int(ps.get("debt", 0)):
                ps["debt_t"] = t                # 借金が始まった時 (返済の遅れの目安)
            ps["debt"] = int(ps.get("debt", 0)) + short
            self.money_note(t, "%sが払えず、%s円の借金をした（借金 %s円）" % (what, format(short, ","), format(ps["debt"], ",")))
        self.save_player()

    def money_note(self, t, text):
        ps = self.player_state()
        ps.setdefault("money_notes", []).append({"t": t, "text": text})
        del ps["money_notes"][:-10]
        self.app.solo.note("money", text, t)

    def lend_chance(self, char, st, amount, t):
        """お金を貸してくれる確率 (0〜0.9). 間柄・好感度・信頼・性格 (慎重さ)・最近も貸したか・相手の懐具合しだい."""
        hm = self.her_money(st)["a"]
        if hm < amount + 3000:
            return 0.0
        p = st["params"]
        recent = sum(1 for x in st.get("lent") or [] if t - x["t"] < 30 * 86400)
        owed = int((self.player_state().get("loans") or {}).get(char["id"], 0))     # まだ返してもらっていない
        f = 0.2 + (p.get("affection", 40) - 50) / 100.0 + (p.get("trust", 40) - 50) / 120.0 \
            + {"contact": 0.0, "visit": 0.15, "live": 0.25}.get(self.app.bonds.stage(char["id"]), -1) - 0.15 * recent \
            - float(self.app.traits(char).get("caution", 0)) / 50.0 - (0.2 if hm < amount * 2 else 0.0) - (0.2 if owed else 0.0)
        return max(0.03, min(0.9, f))

    def borrow(self, amount, t, what):
        """足りない分を, 連絡先を知っている人に頼む (仲の深い順に二人まで). 借りられた額を返す.
        貸してくれても信頼は少し下がり (何度も頼むほど), 断られると少し気まずい. 機嫌の理由にも残る (あなたは知っている)."""
        app = self.app
        rank = {"live": 3, "visit": 2, "contact": 1}
        cands = [cid for cid in app.chars if app.bonds.stage(cid) in rank]
        cands.sort(key=lambda c: (-rank[app.bonds.stage(c)],
                                  -(app.state(c)["params"].get("affection", 0) + app.state(c)["params"].get("trust", 0))))
        for cid in cands[:2]:
            char, st = app.chars[cid], app.state(cid)
            call = app.pronouns(char)[2]
            recent = sum(1 for x in st.get("lent") or [] if t - x["t"] < 30 * 86400)
            if random.random() < self.lend_chance(char, st, amount, t):
                self.her_money(st)["a"] -= amount
                self.player_state()["money"] += amount
                self.ledger(t, amount, "borrow", "%sに借りた" % char.get("name", ""))
                st.setdefault("lent", []).append({"t": t, "amount": amount, "what": what})
                del st["lent"][:-20]
                app.manners.favor(st, "lent", t)              # お金を貸してくれた (お礼の心当たり)
                loans = self.player_state().setdefault("loans", {})
                if not int(loans.get(cid, 0)):
                    self.player_state().setdefault("loan_t", {})[cid] = t
                loans[cid] = int(loans.get(cid, 0)) + amount
                d = app.apply_effects(st, app.trait_effects(char, {"trust": -(1.5 + 1.5 * recent), "mood": -1 - recent}))
                self.add_reason(st, "player", "bad", "%sに%sのお金を貸した" % (call, what), t, told=True,
                                delta=d.get("mood", 0), action="_borrow")
                app.save_state(cid)
                self.money_note(t, "%sが足りず、%sに%s円借りた" % (what, char.get("name", ""), format(amount, ",")))
                return amount
            d = app.apply_effects(st, app.trait_effects(char, {"mood": -1, "affection": -0.5}))
            self.add_reason(st, "player", "bad", "%sにお金を貸してと頼まれて、断った" % call, t, told=True,
                            delta=d.get("mood", 0), action="_borrow")
            app.save_state(cid)
            self.money_note(t, "%sが足りず、%sに借りようとしたが断られた" % (what, char.get("name", "")))
        return 0

    # ---------------------------------------------------------- 借金のあいだ・利息・返済・返済の遅れ
    def in_debt(self):
        """借金 (debt) か, 誰かに借りたお金 (loans) が残っている."""
        ps = self.player_state()
        return int(ps.get("debt", 0)) > 0 or any(int(v) > 0 for v in (ps.get("loans") or {}).values())

    def charge_interest(self, t):
        """月はじめ: 借金に少し利息がつく (知り合いに借りた分にはつかない)."""
        ps = self.player_state()
        debt = int(ps.get("debt", 0))
        if debt <= 0:
            return 0
        add = max(1, int(round(debt * float(self.econ().get("debt_interest_per_month", 0.015)))))
        ps["debt"] = debt + add
        self.money_note(t, "借金に%s円の利息がついた（借金 %s円）" % (format(add, ","), format(ps["debt"], ",")))
        self.save_player()
        return add

    def owed_since(self, cid, st, t):
        """その相手が, あなたのお金のことで気にし始める起点 (貸したまま返ってきていない・同居していて借金を知っている). 無ければ None."""
        ps = self.player_state()
        since = None
        if int((ps.get("loans") or {}).get(cid, 0)) > 0:
            since = (ps.get("loan_t") or {}).get(cid) or min([x["t"] for x in st.get("lent") or []] or [t])
        if self.app.bonds.living() == cid and int(ps.get("debt", 0)) > 0:
            d0 = ps.get("debt_t") or t
            since = min(since, d0) if since else d0
        return since

    def money_concern(self, char, st, t):
        """日付が変わったとき: 事情を知っている相手は, 返済が遅いと気にする (猶予 loan_grace_days を過ぎてから, ときどき).
        心配するか不信感を持つかは, 慎重さ (caution)・好感度・信頼・遅れの長さしだい. 不信感は口に出さないことも.
        口に出したら, 一緒にいればその場で, 離れていればメッセージで. 鍵は chat.money_worry / chat.money_distrust."""
        cid = char["id"]
        e = self.econ()
        since = self.owed_since(cid, st, t)
        if not since:
            return None
        over = (t - since) / 86400.0 - float(e.get("loan_grace_days", 14))
        if over <= 0 or random.random() >= float(e.get("money_concern_per_day", 0.25)):
            return None
        app = self.app
        p = st["params"]
        pd = 0.3 + float(app.traits(char).get("caution", 0)) / 30.0 - (p.get("affection", 50) - 50) / 100.0 \
            - (p.get("trust", 50) - 50) / 120.0 + over / 60.0
        distrust = random.random() < max(0.1, min(0.9, pd))
        eff = {"trust": -2, "affection": -1, "mood": -2} if distrust else {"mood": -1, "stress": 2}
        d = app.apply_effects(st, app.trait_effects(char, eff))
        owed = int((self.player_state().get("loans") or {}).get(cid, 0))
        call = app.pronouns(char)[2]
        said = not distrust or random.random() < 0.5
        self.add_reason(st, "player", "bad", ("%sが貸したお金を返してくれない" if owed else "%sの借金が気になる") % call, t,
                        told=said, delta=d.get("mood", 0), action="_money_concern")
        key = "money_distrust" if distrust else "money_worry"
        if said:
            text = app.chat.line(char, key, {})
            if app.bonds.together(cid):
                app.note_entry(char, st, t, "_money_concern", "お金のこと", "💴", text.replace("📱", "", 1), d)
            else:
                app.chat.add(cid, "her", text, kind=key, t=t)
                app.picked_up_phone(char, st, t)
        return key

    def repay(self, to, amount, t=None):
        """お金を返す. to = "debt" (借金) か, 借りた相手の id. 返した額と, 相手 (いれば) を返す.
        相手に返したら, 喜ばれ, 信頼が少し戻る (bonds.realize を通す. 遅れていたほど全部は戻らない)."""
        t = t or time.time()
        ps = self.player_state()
        amount = int(amount)
        if amount <= 0:
            raise ValueError("返す額を入れてください")
        if to == "debt":
            owed = int(ps.get("debt", 0))
        else:
            if to not in self.app.chars:
                raise KeyError("相手が見つかりません: %s" % to)
            owed = int((ps.get("loans") or {}).get(to, 0))
        if owed <= 0:
            raise ValueError("返すお金はありません")
        amount = min(amount, owed)
        if ps["money"] < amount:
            raise ValueError("お金が足りません（手元 %s円）" % format(ps["money"], ","))
        ps["money"] -= amount
        self.ledger(t, -amount, "repay", "借金の返済" if to == "debt" else "%sに返した" % self.app.chars[to].get("name", ""))
        left = owed - amount
        if to == "debt":
            ps["debt"] = left
            if not left:
                ps.pop("debt_t", None)
            self.money_note(t, "借金を%s円返した（%s）" % (format(amount, ","), "残り %s円" % format(left, ",") if left else "完済"))
            self.save_player()
            return {"amount": amount, "left": left}
        app = self.app
        char, st = app.chars[to], app.state(to)
        app.attach.give(char, st, "me", 1, "借りたお金を返した")
        self.her_money(st)["a"] += amount
        ps["loans"][to] = left
        since = (ps.get("loan_t") or {}).get(to) or t
        if not left:
            ps["loans"].pop(to, None)
            ps.get("loan_t", {}).pop(to, None)
        late = max(0.0, (t - since) / 86400.0 - float(self.econ().get("loan_grace_days", 14)))
        eff = {"mood": 2, "trust": (2.5 if not left else 1.0) * (0.5 if late > 0 else 1.0)}
        eff, _ = app.bonds.realize(char, st, eff, "_repay", t)
        app.bonds.touch(st, t)
        d = app.apply_effects(st, app.trait_effects(char, eff))
        if not left:
            for r in st.get("reasons") or []:        # 返してもらえない, は解決
                if r.get("action") in ("_money_concern", "_borrow") and r["mood"] == "bad":
                    r["resolved"] = True
        self.money_note(t, "%sに%s円返した（%s）" % (char.get("name", ""), format(amount, ","),
                                                  "残り %s円" % format(left, ",") if left else "全部返した"))
        self.save_player()
        if app.bonds.together(to):
            text = app.chat.line(char, "repaid", {}).replace("📱", "", 1)
            app.note_entry(char, st, t, "_repay", "お金を返した", "💴", text, d)
        else:                                       # 離れていれば振り込み. 返事はいつものメッセージの時間差で
            app.chat.add(to, "sys", "💴 %s円を返した（振り込んだ）" % format(amount, ","), kind="repay", t=t)
            pend = st.get("msg_pending")
            if pend:
                pend["kind"] = "repaid"
            else:
                st["msg_pending"] = {"aid": "message", "t": t, "due": t + random.uniform(5, 60) * 60, "reply": True,
                                     "count": 1, "kind": "repaid"}
        app.save_state(to)
        return {"amount": amount, "left": left, "to": to, "deltas": d}

    # ---------------------------------------------------------- 出来事
    def happen(self, char, st, t, ctx, force=None):
        mc = self.money_ctx(st)
        ctx = dict(ctx, **mc)
        evs = []
        for ev in self.app.events:
            if force and ev["id"] != force:
                continue
            last = max([x["t"] for x in st.get("events", []) if x["id"] == ev["id"]] or [0])
            if t - last < float(ev.get("cooldown_h", 24)) * 3600:
                continue
            if not force and not cond.check(ev.get("when", ""), ctx):
                continue
            evs.append(ev)
        if not evs:
            return None
        fv = self.app.attach.factor(char, st, "devotion")

        def w(x):                     # 自分優先なほど「貸して・買って」, 献身的なほど「ごちそう・プレゼント」
            k = (x.get("request") or {}).get("kind")
            f = 1 - 0.8 * fv if k in ("money", "gift") else 1 + 0.8 * fv if k in ("treat", "present") else 1
            return float(x.get("weight", 1)) * max(0.2, f)
        ev = random.choices(evs, [w(x) for x in evs])[0]
        self.app.apply_effects(st, self.app.trait_effects(char, ev.get("effects") or {}))
        money = ev.get("money") or {}
        amt = _amount(money.get("a")) if money.get("a") else 0
        if amt:
            self.her_money(st)["a"] += amt
        if money.get("p"):
            self.move(st, dp=_amount(money["p"]), cat="other", note=ev.get("label", ""))
        rec = {"id": ev["id"], "t": t, "label": ev.get("label", ev["id"]), "tell": ev.get("tell", ""),
               "mood": ev.get("mood", "neutral"), "told": False}
        st.setdefault("events", []).append(rec)
        del st["events"][:-30]
        if rec["mood"] in ("good", "bad"):
            self.add_reason(st, "event", rec["mood"], rec["tell"], t, told=False,
                            delta=float((ev.get("effects") or {}).get("mood", 0)), ev=ev["id"])
        req = ev.get("request")
        if req and not st.get("request"):
            text = ev.get("tell", "")
            if req.get("kind") == "money":           # しょっちゅう頼んでいる (2 週間以内にも頼んだ) なら, 頼み方もそれらしく
                if any(x.get("id") == ev["id"] and 0 < t - x.get("t", 0) < 14 * 86400 for x in st.get("events", [])[:-1]):
                    text = self.app.persona_text(char, "chat.req_money_again") or chat_lines()["chat.req_money_again"]
            st["request"] = {"id": uuid.uuid4().hex[:8], "kind": req.get("kind", "money"),
                             "amount": _amount(req.get("amount", 0)), "text": text, "t": t,
                             "label": req.get("label", ev.get("label", ""))}
        return rec

    # ---------------------------------------------------------- 機嫌の理由
    # state["reasons"]: [{kind: event|player, mood: good|bad, tell, t, told, delta, resolved}]
    #   event  = キャラ側の出来事 (聞くまで理由は分からない)
    #   player = あなたの行動 (あなたは知っている)
    def add_reason(self, st, kind, mood, tell, t, told, delta=0.0, **extra):
        for r in self.reasons(st, t):          # 同じ理由が続いたら 1 つにまとめる (効き目は足し合わせる)
            if r["kind"] == kind and r["mood"] == mood and r["tell"] == tell:
                r["t"], r["delta"] = t, round(r.get("delta", 0) + float(delta), 1)
                r["told"] = r["told"] and told
                return r
        r = {"kind": kind, "mood": mood, "tell": tell, "t": t, "told": told, "delta": round(float(delta), 1),
             "resolved": False}
        r.update(extra)
        st.setdefault("reasons", []).append(r)
        del st["reasons"][:-20]
        return r

    def reasons(self, st, now):
        """いま効いている理由 (12 時間以内・解決していないもの). 新しい順."""
        rs = [r for r in st.get("reasons", []) if now - r["t"] <= 12 * 3600 and not r.get("resolved")]
        return sorted(rs, key=lambda r: -r["t"])

    def dominant(self, st, now, mood=None):
        """今の機嫌に一番効いている理由. mood を指定すればその向き (good/bad) だけから選ぶ.
        指定しなければ, 機嫌が低いときは悪い理由, 高いときは良い理由を優先する."""
        rs = self.reasons(st, now)
        if mood is None:
            m = st["params"].get("mood", 50)
            pref = "bad" if m < 45 else "good" if m >= 55 else None
            if pref and any(r["mood"] == pref for r in rs):
                mood = pref
        if mood:
            rs = [r for r in rs if r["mood"] == mood]
        if not rs:
            return None
        return max(rs, key=lambda r: (abs(r.get("delta", 0)) + (3 if not r["told"] else 0), r["t"]))

    def resolve(self, st, mood, now, kind=None):
        """謝る・相談にのる などで, その向きの理由を解決済みにする. kind を渡せば, その出どころの理由だけ
        (謝って消えるのは あなたのせい (player) の理由だけ. 仕事の疲れなどは謝っても消えない)."""
        for r in self.reasons(st, now):
            if r["mood"] == mood and (kind is None or r["kind"] == kind):
                r["resolved"] = True

    def mark_told(self, r):
        if r:
            r["told"] = True

    def mood_ctx(self, st, now):
        d = self.dominant(st, now)
        bad = self.dominant(st, now, "bad")
        untold = [r for r in self.reasons(st, now) if not r["told"]]
        req = st.get("request")
        if req and now - req.get("t", 0) > 12 * 3600:
            st["request"] = req = None
        away = [e for e in st.get("events", []) if e["t"] > st.get("last_interaction", now)]
        return {"cause": (bad or {}).get("kind", "none"),            # 悪い機嫌の原因: player / event / none
                "knows": bool(bad and bad.get("told")),              # その理由をあなたが知っているか
                "reason": (d or {}).get("mood", "none"),             # 今いちばん効いている理由の向き
                "untold": len(untold),                               # まだ聞いていない理由の数
                "ev_mood": (untold[0]["mood"] if untold else "none"),
                "request": (req or {}).get("kind", "none"),
                "away_events": len(away)}

    def mood_text(self, st, now):
        bad = self.dominant(st, now, "bad") or {}
        untold = [r for r in self.reasons(st, now) if not r["told"]]
        away = [e for e in st.get("events", []) if e["t"] > st.get("last_interaction", now)]
        req = st.get("request") or {}
        return {"ev_text": (untold[0] if untold else self.dominant(st, now) or {}).get("tell", ""),
                "bad_text": bad.get("tell", ""),
                "away_text": "、".join(e["tell"] for e in away[-2:] if e.get("tell")),
                "req_text": req.get("text", ""), "amount": format(int(req.get("amount", 0)), ",")}

    def note_player_reason(self, char, st, a, deltas, now, call):
        """あなたの行動で機嫌が大きく動いたら, その理由として覚える (良い方も悪い方も)."""
        d = deltas.get("mood", 0)
        if abs(d) < 5:
            return None
        mood = "good" if d > 0 else "bad"
        tell = (a.get("reason_good") if mood == "good" else a.get("reason_bad")) or \
            ("{call}と「%s」" % a.get("name", a.get("id", "")))
        return self.add_reason(st, "player", mood, tell.replace("{call}", call), now, told=True, delta=d, action=a.get("id"))

    def player_view(self):
        """あなたのお金・体力・スキル (誰がそばにいても同じ. お金タブ)."""
        ps = self.player_state()
        return {
                "debt": int(ps.get("debt", 0)), "in_debt": self.in_debt(),
                "loans": [{"id": k, "name": (self.app.chars.get(k) or {}).get("name", k), "amount": v}
                          for k, v in (ps.get("loans") or {}).items() if v],
                "money_notes": (ps.get("money_notes") or [])[-5:],
                # 相手の所持金は出さない (分かるのは, 貸し借り・取り決め・本人が口にしたことだけ)
                "my_money": ps["money"],
                "invest": {"value": self.portfolio_value(), "invested": self.portfolio_cost()},
                "market": self.market_view(),
                "skills": {k: round(v, 1) for k, v in ps["skills"].items()}, "rusty": self.rusty(),
                "stamina": round(float(ps.get("stamina", 100)), 1), "work_today": round((ps.get("work_log") or {}).get(
                    datetime.now().strftime("%Y-%m-%d"), 0), 2)}

    def partner_view(self, char, st):
        """相手のこと (あなたが知りうることだけ): 機嫌の理由 (聞いたもの)・お願い・お金の取り決め・あなたが借りている額."""
        ps = self.player_state()
        now = time.time()
        rs = self.reasons(st, now)
        untold = [r for r in rs if not r["told"]]
        call = self.app.pronouns(char)[2]
        fmt = lambda s: (s or "").replace("{call}", call)   # noqa: E731
        req = dict(st["request"], text=fmt(st["request"].get("text")), label=fmt(st["request"].get("label")))             if st.get("request") else None
        return {"living": self.app.bonds.living() == char["id"],
                "reasons": [{"mood": r["mood"], "kind": r["kind"], "t": r["t"],
                             "tell": fmt(r["tell"]) if r["told"] else None} for r in rs[:6]],
                "pay_policy": char.get("pay_policy") or "auto", "living_policy": char.get("living_policy") or "split",
                "owed": int((ps.get("loans") or {}).get(char["id"], 0)),
                "request": req,
                "hint": self._noticed(untold), "hint_mood": untold[0]["mood"] if self._noticed(untold) else None}

    def _noticed(self, untold):
        """まだ聞いていない出来事があることに, 様子から気づくか (気配りしだい. 出来事ごとに決まり, 見るたびには変わらない)."""
        if not untold:
            return False
        seed = int(float(untold[0].get("t", 0)) * 1000) % 997 / 997.0
        return seed < 0.55 + 0.4 * self.skill_soft("care")

    def view(self, char, st):
        return dict(self.player_view(), **self.partner_view(char, st))
