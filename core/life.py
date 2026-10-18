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

    # ================================================================== あなたのお金・投資
    def player_state(self):
        if self.player is None:
            self.player = store.load(store.dpath("player.json"))
        if self.player is None:
            t = time.time()
            self.player = {"money": int(self.econ().get("start_money_player", 30000)), "units": 0.0, "invested": 0,
                           "price": 1000.0, "history": [[t, 1000.0]], "last_tick": t}
            self.save_player()
        return self.player

    def save_player(self):
        store.save(store.dpath("player.json"), self.player)

    def tick_world(self, now=None):
        """市場の値動きと, あなたの定期収入 (放置でもたまる) をリアル時間で進める."""
        ps, e = self.player_state(), self.econ()
        now = now or time.time()
        t = max(ps.get("last_tick", now), now - 14 * 86400)
        step = 300
        changed = False
        drift, vol = float(e.get("invest_drift", 0.00003)), float(e.get("invest_vol", 0.004))
        while t + step <= now:
            t += step
            changed = True
            ps["price"] = max(1.0, ps["price"] * math.exp(drift + vol * random.gauss(0, 1)))
            if t - ps["history"][-1][0] >= 3600:
                ps["history"].append([t, round(ps["price"], 2)])
                del ps["history"][:-72]
            if datetime.fromtimestamp(t - step).date() != datetime.fromtimestamp(t).date():
                ps["money"] += int(e.get("player_daily_income", 3000))
        ps["last_tick"] = t
        if changed:
            self.save_player()

    def her_money(self, st):
        m = st.setdefault("money", {})
        if "a" not in m:
            m["a"] = int(self.econ().get("start_money_her", 20000))
        return m

    def money_ctx(self, st):
        ps = self.player_state()
        value = int(ps["units"] * ps["price"])
        return {"my_money": ps["money"], "her_money": self.her_money(st)["a"], "invest_value": value,
                "profit": value - int(ps.get("invested", 0)) if ps["units"] else 0}

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

    def invest(self, mode, unit=None):
        ps = self.player_state()
        if mode == "buy":
            unit = int(unit or self.econ().get("invest_unit", 10000))
            if ps["money"] < unit:
                raise ValueError("投資するお金が足りません（%s円必要）" % format(unit, ","))
            ps["money"] -= unit
            ps["units"] += unit / ps["price"]
            ps["invested"] = int(ps.get("invested", 0)) + unit
            self.save_player()
            return {"p": -unit}, unit, 0
        if not ps["units"]:
            raise ValueError("売れる投資がありません")
        value = int(ps["units"] * ps["price"])
        profit = value - int(ps.get("invested", 0))
        ps["money"] += value
        ps["units"], ps["invested"] = 0.0, 0
        self.save_player()
        return {"p": value}, value, profit

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
        self.app.apply_effects(st, ev.get("effects") or {})
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
                "invest": {"units": round(ps["units"], 4), "price": round(ps["price"], 2),
                           "value": int(ps["units"] * ps["price"]), "invested": int(ps.get("invested", 0)),
                           "history": [h[1] for h in ps.get("history", [])][-48:]},
                "pay_policy": char.get("pay_policy") or "auto", "living_policy": char.get("living_policy") or "split",
                "request": req,
                "hint": bool(untold), "hint_mood": untold[0]["mood"] if untold else None}
