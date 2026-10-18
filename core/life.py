"""キャラの暮らし: お金 (所持金・生活費・投資) と, キャラ側の出来事 (機嫌の理由・おねだり・留守中のこと).

- あなたのお金と投資は data/player.json (キャラ共通), キャラのお金は各キャラの state["money"].
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
SKILLS = ("talk", "touch", "cook", "work")     # あなたのスキル: 会話・スキンシップ・料理・仕事


def _amount(v):
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return int(random.randint(int(v[0]) // 100, int(v[1]) // 100) * 100)
    return int(v or 0)


class Life:
    def __init__(self, app):
        self.app = app
        self.player = None

    def econ(self):
        return self.app.world.get("economy") or {}

    # ================================================================== あなたのお金・スキル・投資
    def player_state(self):
        if self.player is None:
            self.player = store.load(store.dpath("player.json"))
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
        store.save(store.dpath("player.json"), self.player)

    # ---------------------------------------------------------- スキル
    def skill(self, k):
        return float(self.player_state()["skills"].get(k, 10.0))

    def skill_mult(self, k):
        """スキルによる効き目の倍率 (0.6〜1.4)."""
        return 0.6 + self.skill(k) / 100.0 * 0.8

    def train(self, k, gain):
        """スキルを伸ばす (上がるほど伸びにくい). 伸びた量を返す."""
        sk = self.player_state()["skills"]
        old = float(sk.get(k, 10.0))
        new = min(100.0, old + float(gain) * (1.0 - old / 110.0))
        sk[k] = round(new, 2)
        self.save_player()
        return round(new - old, 2)

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
            first = self.assets()[0]
            st = self._asset_state(m, first, t)
            value = float(ps["units"]) * float(ps.get("price", 1000))
            m["holdings"][first["id"]] = {"qty": max(1, int(round(value / st["price"]))), "cost": int(ps.get("invested", value))}
        for k in ("units", "invested", "price", "history"):
            ps.pop(k, None)

    def _asset_state(self, m, a, t=None):
        st = m["assets"].get(a["id"])
        if st is None:          # 後から増えた銘柄
            p0 = float(a.get("price", 1000))
            st = m["assets"][a["id"]] = {"price": p0, "history": [[t or time.time(), p0]], "bias": 0.0, "bias_until": 0}
        return st

    def tick_world(self, now=None):
        """市場の値動き・ニュースと, あなたの定期収入をリアル時間で進める."""
        ps, e = self.player_state(), self.econ()
        now = now or time.time()
        t = max(ps.get("last_tick", now), now - 14 * 86400)
        step = 300
        changed = False
        m = ps["market"]
        assets = self.assets()
        while t + step <= now:
            t += step
            changed = True
            if assets and random.random() < float(e.get("news_rate_per_hour", 0.12)) * step / 3600.0:
                self._news(m, random.choice(assets), t)
            for a in assets:
                st = self._asset_state(m, a, t)
                mu = float(a.get("drift", 0)) + (st["bias"] if st.get("bias_until", 0) > t else 0.0)
                st["price"] = max(1.0, st["price"] * math.exp(mu + float(a.get("vol", 0.003)) * random.gauss(0, 1)))
                if not st["history"] or t - st["history"][-1][0] >= 3600:
                    st["history"].append([t, round(st["price"], 2)])
                    del st["history"][:-168]
            mode = self.app.presence.at(t)
            if mode != "work":
                rec = float(e.get("stamina_recover_sleep" if mode == "sleep" else "stamina_recover", 12 if mode == "sleep" else 5))
                ps["stamina"] = min(100.0, float(ps.get("stamina", 100)) + rec * step / 3600.0)
            if datetime.fromtimestamp(t - step).date() != datetime.fromtimestamp(t).date():
                ps["money"] += int(e.get("player_daily_income", 1000))
        ps["last_tick"] = t
        if changed:
            self.save_player()

    def _news(self, m, a, t):
        """銘柄のニュース. 見出しの向きどおりに動くとは限らない (的中率 news_accuracy)."""
        e = self.econ()
        d = random.choice((1, -1))
        heads = (e.get("news") or {}).get("up" if d > 0 else "down") or ["{name}に関するニュース"]
        real = d if random.random() < float(e.get("news_accuracy", 0.7)) else -d
        lo, hi = (e.get("news_hours") or [6, 18])[:2]
        st = self._asset_state(m, a, t)
        st["bias"] = real * float(e.get("news_bias", 0.0005)) * random.uniform(0.6, 1.4)
        st["bias_until"] = t + random.uniform(float(lo), float(hi)) * 3600
        m["news"].append({"t": t, "asset": a["id"], "dir": d, "text": random.choice(heads).replace("{name}", a.get("name", a["id"]))})
        del m["news"][:-30]

    def portfolio_value(self):
        m = self.player_state()["market"]
        return int(sum(h["qty"] * m["assets"].get(k, {}).get("price", 0) for k, h in m["holdings"].items()))

    def portfolio_cost(self):
        return int(sum(h.get("cost", 0) for h in self.player_state()["market"]["holdings"].values()))

    def trade(self, asset, qty):
        """銘柄を売買する (qty > 0 で買い, < 0 で売り. 株数は整数). (お金の動き, 金額, 売却損益) を返す."""
        ps = self.player_state()
        m = ps["market"]
        a = next((x for x in self.assets() if x["id"] == asset), None)
        if not a:
            raise KeyError("銘柄が見つかりません: %s" % asset)
        qty = int(qty)
        if not qty:
            raise ValueError("株数を指定してください")
        price = self._asset_state(m, a)["price"]
        if qty > 0:
            amt = int(round(price * qty))
            if ps["money"] < amt:
                raise ValueError("お金が足りません（%s円必要）" % format(amt, ","))
            hold = m["holdings"].setdefault(asset, {"qty": 0, "cost": 0})
            ps["money"] -= amt
            hold["qty"] = int(hold["qty"]) + qty
            hold["cost"] = int(hold.get("cost", 0)) + amt
            self.save_player()
            return {"p": -amt}, amt, 0
        n = -qty
        hold = m["holdings"].get(asset)
        if not hold or hold["qty"] < n:
            raise ValueError("そんなに持っていません（%s株）" % format(int((hold or {}).get("qty", 0)), ","))
        amt = int(round(price * n))
        cost = int(round(hold.get("cost", 0) * n / hold["qty"]))
        hold["qty"] = int(hold["qty"]) - n
        hold["cost"] = int(hold.get("cost", 0)) - cost
        if hold["qty"] <= 0:
            m["holdings"].pop(asset, None)
        ps["money"] += amt
        self.save_player()
        return {"p": amt}, amt, amt - cost

    def market_view(self):
        m = self.player_state()["market"]
        now = time.time()
        out = []
        for a in self.assets():
            st = self._asset_state(m, a)
            hist = [x[1] for x in st["history"]]
            day = next((x[1] for x in reversed(st["history"]) if now - x[0] >= 86400), hist[0] if hist else st["price"])
            h = m["holdings"].get(a["id"]) or {}
            out.append({"id": a["id"], "name": a.get("name", a["id"]), "icon": a.get("icon", ""), "desc": a.get("desc", ""),
                        "price": round(st["price"], 1), "day": round((st["price"] / day - 1) * 100, 1) if day else 0,
                        "history": hist[-72:] + [round(st["price"], 1)],
                        "qty": int(h.get("qty", 0)), "cost": int(h.get("cost", 0)), "value": int(h.get("qty", 0) * st["price"])})
        names = {a["id"]: a.get("name", a["id"]) for a in self.assets()}
        return {"assets": out, "news": [dict(n, name=names.get(n["asset"], n["asset"])) for n in reversed(m["news"][-10:])]}

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
        return int(round(float(e.get("work_wage_per_hour", 1200)) * h * self.skill_mult("work") / 10.0)) * 10, h, raw

    def stamina(self):
        return float(self.player_state().get("stamina", 100))

    def tire(self, amount):
        ps = self.player_state()
        ps["stamina"] = max(0.0, float(ps.get("stamina", 100)) - float(amount))
        self.save_player()

    def stamina_mult(self):
        """体力が減っていると, キャラへの行動のうれしい効き目が落ちる (体力 0 で 0.6 倍)."""
        return 0.6 + 0.4 * self.stamina() / 100.0

    def recent_work(self, days=3):
        log = self.player_state().get("work_log") or {}
        return round(sum(v for k, v in sorted(log.items())[-days:]), 2)

    def side_job_pay(self, ok, ng):
        unit = float(self.econ().get("side_job_unit", 15)) * self.skill_mult("work")
        return max(0, int(round((ok - ng * 0.5) * unit / 10.0)) * 10)

    def her_money(self, st):
        m = st.setdefault("money", {})
        if "a" not in m:
            m["a"] = int(self.econ().get("start_money_her", 20000))
        return m

    def money_ctx(self, st):
        ps = self.player_state()
        value = self.portfolio_value()
        ctx = {"my_money": ps["money"], "her_money": self.her_money(st)["a"], "invest_value": value,
               "profit": value - self.portfolio_cost() if value else 0}
        ctx.update({"sk_" + k: round(v, 1) for k, v in ps["skills"].items()})
        ctx["my_stamina"] = round(float(ps.get("stamina", 100)), 1)
        ctx["work_3d"] = self.recent_work(3)            # ここ 3 日で働いた時間
        return ctx

    def move(self, st, dp=0, da=0):
        """お金を動かす (マイナス可). 実際に動いた額を返す."""
        ps, hm = self.player_state(), self.her_money(st)
        ps["money"] += int(dp)
        hm["a"] += int(da)
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
            pol = "her" if (r < 0.2 + aff / 500.0 and hm["a"] >= cost * 2) else "split" if r < 0.55 else "me"
        if pol == "split":
            half = cost // 2
            if ps["money"] >= cost - half and hm["a"] >= half:
                return {"payer": "split", "p": -(cost - half), "a": -half}
            pol = "me" if ps["money"] >= cost else "her"
        if pol == "her" and hm["a"] >= cost:
            return {"payer": "her", "p": 0, "a": -cost}
        if ps["money"] >= cost:
            return {"payer": "me", "p": -cost, "a": 0}
        if hm["a"] >= cost:
            return {"payer": "her", "p": 0, "a": -cost}
        raise ValueError("お金が足りません（費用 %s円 / あなた %s円 / %s %s円）"
                         % (format(cost, ","), format(ps["money"], ","), char.get("name", ""), format(hm["a"], ",")))

    # ================================================================== キャラの毎日
    def step(self, char, st, t0, t1, h):
        """5 分ごと: 日付が変わったら収入と生活費, ときどき出来事."""
        e = self.econ()
        hm = self.her_money(st)
        if datetime.fromtimestamp(t0).date() != datetime.fromtimestamp(t1).date():
            hm["a"] += int(e.get("her_daily_income", 2500))
            self._living_cost(char, st, int(e.get("living_cost_per_day", 3000)))
        dt = datetime.fromtimestamp(t1)
        ctx = self.app.context(char, st, dt)
        if ctx["asleep"]:
            return
        if random.random() < float(e.get("event_rate_per_hour", 0.08)) * h:
            self.happen(char, st, t1, ctx)

    def _living_cost(self, char, st, cost):
        pol = char.get("living_policy") or "split"
        ps, hm = self.player_state(), self.her_money(st)
        share_p = {"me": cost, "her": 0}.get(pol, cost // 2)
        share_a = cost - share_p
        pay_p, pay_a = min(share_p, max(ps["money"], 0)), min(share_a, max(hm["a"], 0))
        short = (share_p - pay_p) + (share_a - pay_a)   # 払えない分はもう一方が肩代わり
        extra_p = min(short, max(ps["money"] - pay_p, 0)) if share_a - pay_a else 0
        extra_a = min(short - extra_p, max(hm["a"] - pay_a, 0))
        ps["money"] -= pay_p + extra_p
        hm["a"] -= pay_a + extra_a
        self.save_player()
        if short - extra_p - extra_a > 0:      # 二人とも払えない
            self.app.apply_effects(st, {"stress": 15, "mood": -8})

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
        ev = random.choices(evs, [float(x.get("weight", 1)) for x in evs])[0]
        self.app.apply_effects(st, self.app.trait_effects(char, ev.get("effects") or {}))
        money = ev.get("money") or {}
        amt = _amount(money.get("a")) if money.get("a") else 0
        if amt:
            self.her_money(st)["a"] += amt
        if money.get("p"):
            self.move(st, dp=_amount(money["p"]))
        rec = {"id": ev["id"], "t": t, "label": ev.get("label", ev["id"]), "tell": ev.get("tell", ""),
               "mood": ev.get("mood", "neutral"), "told": False}
        st.setdefault("events", []).append(rec)
        del st["events"][:-30]
        if rec["mood"] in ("good", "bad"):
            self.add_reason(st, "event", rec["mood"], rec["tell"], t, told=False,
                            delta=float((ev.get("effects") or {}).get("mood", 0)), ev=ev["id"])
        req = ev.get("request")
        if req and not st.get("request"):
            st["request"] = {"id": uuid.uuid4().hex[:8], "kind": req.get("kind", "money"),
                             "amount": _amount(req.get("amount", 0)), "text": ev.get("tell", ""), "t": t,
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

    def resolve(self, st, mood, now):
        """謝る・相談にのる などで, その向きの理由を解決済みにする."""
        for r in self.reasons(st, now):
            if r["mood"] == mood:
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

    def view(self, char, st):
        ps = self.player_state()
        now = time.time()
        rs = self.reasons(st, now)
        untold = [r for r in rs if not r["told"]]
        call = self.app.pronouns(char)[2]
        fmt = lambda s: (s or "").replace("{call}", call)   # noqa: E731
        req = dict(st["request"], text=fmt(st["request"].get("text")), label=fmt(st["request"].get("label"))) \
            if st.get("request") else None
        return {
                "reasons": [{"mood": r["mood"], "kind": r["kind"], "t": r["t"],
                             "tell": fmt(r["tell"]) if r["told"] else None} for r in rs[:6]],"my_money": ps["money"], "her_money": self.her_money(st)["a"],
                "invest": {"value": self.portfolio_value(), "invested": self.portfolio_cost()},
                "market": self.market_view(),
                "skills": {k: round(v, 1) for k, v in ps["skills"].items()},
                "stamina": round(float(ps.get("stamina", 100)), 1), "work_today": round((ps.get("work_log") or {}).get(
                    datetime.now().strftime("%Y-%m-%d"), 0), 2),
                "pay_policy": char.get("pay_policy") or "auto", "living_policy": char.get("living_policy") or "split",
                "request": req,
                "hint": bool(untold), "hint_mood": untold[0]["mood"] if untold else None}
