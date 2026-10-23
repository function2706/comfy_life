"""家計簿: あなたのお金の出入りは裏ですべて記録しておき (raw), あなたに見えるのは家計簿につけた分 (book) だけ.

- 記録 (raw): 給料・内職・買い物・外食・家賃・生活費・借りた/返したお金・株・入場料など, 財布のお金が動いたらすべて.
  player.json の ledger.raw (120 日ぶん). これは画面には出さない.
- 家計簿をつける (家事の「家計簿」. 15 分ほど): 前回つけたときから今までの出入りを, 日ごとにまとめて書き込む.
  ただし日を空けるほど記憶が薄れる: その日・前の日の分は正確, 2〜6 日前は細かい額が丸まり (小さな出費はまとめて「こまごま」),
  7 日以上前は丸まったうえ一部を書き漏らす (家賃のような大きな固定の出費は覚えている). 書いた分 (ledger.book) は変わらない.
- 見積もり: 1 日にどれくらい稼げばいいか. 固定費 (家賃・光熱費・通信費・生活費の分担・借金の利息) は記録しなくても分かる.
  変動費 (食費・外食・買い物・交際費・娯楽など) は家計簿の記録から見積もり, 記録が少ないほど・うろ覚えが多いほど幅を広く.
- 今の財布の残高は, 家計簿と関係なくいつも見える.
"""
import math
import random
import time
from datetime import date, datetime

CATS = {"income": "収入", "food": "食費", "eatout": "外食", "shopping": "買い物", "social": "交際費", "fun": "娯楽",
        "medical": "医療", "fixed": "家賃・光熱費・通信費", "living": "生活費", "borrow": "借りたお金", "repay": "返済",
        "invest": "株", "other": "その他"}
FIXED_CATS = ("fixed", "living")                          # 記録しなくても分かる (毎月・毎日決まっている)
NOT_SPENDING = ("income", "borrow", "repay", "invest")    # 変動費の見積もりに入れない
RAW_DAYS = 120
BOOK_DAYS = 400


def _day(t):
    return date.fromtimestamp(t).isoformat()


def _round(a, age):
    """うろ覚えの額: 日が空くほど粗く丸まる."""
    step = 1000 if age >= 7 or abs(a) >= 10000 else 500 if abs(a) >= 1000 else 100
    r = int(round(a / float(step))) * step
    return r if r else (step if a > 0 else -step)


class Kakeibo:
    def __init__(self, app):
        self.app = app

    def rec(self):
        ps = self.app.life.player_state()
        lg = ps.setdefault("ledger", {})
        lg.setdefault("raw", [])
        lg.setdefault("book", [])
        lg.setdefault("upto", None)
        return lg

    # ------------------------------------------------------------------ 裏の記録 (すべて)
    def add(self, t, amount, cat, note=""):
        """財布のお金が動いた (amount: 入れば +, 出れば −). cat は CATS のどれか."""
        amount = int(amount)
        if not amount:
            return
        lg = self.rec()
        lg["raw"].append({"t": float(t or time.time()), "a": amount, "c": cat if cat in CATS else "other", "n": note or ""})
        cut = time.time() - RAW_DAYS * 86400
        if len(lg["raw"]) > 3000 or (lg["raw"] and lg["raw"][0]["t"] < cut):
            lg["raw"] = [x for x in lg["raw"] if x["t"] >= cut][-3000:]

    # ------------------------------------------------------------------ 家計簿をつける
    def write(self, now=None):
        """前回つけたときから今までを, 日ごとにまとめて書き込む (日を空けるほど, うろ覚え). 書いた結果のまとめを返す."""
        now = now or time.time()
        lg = self.rec()
        since = lg["upto"] if lg["upto"] is not None else 0
        todo = [x for x in lg["raw"] if not x.get("w") and x["t"] <= now]      # まだ書いていない出入り
        for x in todo:
            x["w"] = 1
        today = date.fromtimestamp(now)
        days = {}
        for x in todo:
            days.setdefault(_day(x["t"]), []).append(x)
        fuzzy = forgot = 0
        written = []
        thrift = self.app.life.skill_soft("budget")       # やりくりがうまいほど, 覚えている (丸めが遅く, 書き漏らしが少ない)
        sharp = 1 if thrift >= 0.5 else 0
        for d in sorted(days):
            age = (today - date.fromisoformat(d)).days
            items = []
            small = 0
            for x in days[d]:
                a, cat = x["a"], x["c"]
                if age >= 7 and cat not in FIXED_CATS and abs(a) < 20000 and \
                        random.random() < min(0.6, 0.08 * (age - 5)) * (1.0 - 0.6 * thrift):
                    forgot += 1                             # 書き漏らし (本人は気づかない)
                    continue
                if age >= 2 + sharp and cat not in FIXED_CATS and cat != "income" and -1000 < a < 0:
                    small += a                              # 細かい出費は, もう何だったか覚えていない
                    continue
                items.append({"a": _round(a, age) if age >= 2 + sharp else a, "c": cat, "n": x["n"] if age < 7 else "",
                              "approx": age >= 2 + sharp})
            if small:
                items.append({"a": _round(small, age), "c": "other", "n": "こまごました出費", "approx": True})
            if age >= 2:
                fuzzy += 1
            if not items:
                continue
            ent = next((b for b in lg["book"] if b["day"] == d), None)
            if ent:
                ent["items"] += items
                ent["fuzzy"] = ent.get("fuzzy") or age >= 2
            else:
                lg["book"].append({"day": d, "items": items, "fuzzy": age >= 2, "written": now})
            written.append(d)
        lg["book"].sort(key=lambda b: b["day"])
        del lg["book"][:-BOOK_DAYS]
        gap = max([(today - date.fromisoformat(d)).days for d in written] or [0])
        lg["upto"] = now
        lg["last_written"] = now
        if todo:
            self.app.life.train("budget", min(1.5, 0.3 + 0.1 * len(written)))
        self.app.life.save_player()
        if not written:
            text = "家計簿をつけた。前につけてから、お金の出入りはなかった" if todo or since else "家計簿をつけ始めた。まだ書くことはない"
        else:
            text = "家計簿をつけた（%d日分）" % len(written)
            if fuzzy:
                text += "。日が空いていたので、%sはうろ覚え" % ("何日か前の分" if gap < 7 else "前のほうの分")
        return {"days": written, "fuzzy": fuzzy, "text": text, "forgot": forgot}

    # ------------------------------------------------------------------ 画面
    def fixed_per_day(self):
        """記録しなくても分かる 1 日あたりの固定費 (家賃・光熱費・通信費・生活費のあなたの分・借金の利息)."""
        app = self.app
        e = app.life.econ()
        live = app.bonds.living()
        share = 1.0
        if live:
            share = {"me": 1.0, "her": 0.0}.get(app.chars[live].get("living_policy") or "split", 0.5)
        rent = float(e.get("home_cost_per_month", 60000)) / 30.0 * share
        living = float(e.get("living_cost_per_day", 3000)) / (1 if live else 2) * share
        debt = int(app.life.player_state().get("debt", 0))
        interest = debt * float(e.get("debt_interest_per_month", 0.015)) / 30.0
        return {"rent": int(round(rent)), "living": int(round(living)), "interest": int(round(interest)),
                "total": int(round(rent + living + interest))}

    def view(self, now=None):
        now = now or time.time()
        lg = self.rec()
        app = self.app
        book = lg["book"]
        recent = [b for b in book if (date.fromtimestamp(now) - date.fromisoformat(b["day"])).days < 30]
        cats = {}
        for b in recent:
            for x in b["items"]:
                cats[x["c"]] = cats.get(x["c"], 0) + x["a"]
        days = []
        for b in reversed(book[-21:]):
            inc = sum(x["a"] for x in b["items"] if x["a"] > 0)
            out = sum(x["a"] for x in b["items"] if x["a"] < 0)
            days.append({"day": b["day"], "in": inc, "out": out, "fuzzy": bool(b.get("fuzzy")),
                         "items": [dict(x, label=CATS.get(x["c"], x["c"])) for x in b["items"]]})
        fixed = self.fixed_per_day()
        passive = int(app.life.econ().get("player_daily_income", 1000))
        est = {"fixed": fixed, "passive": passive, "variable": None, "need": None, "note": ""}
        if recent:
            d0 = date.fromisoformat(recent[0]["day"])
            span = max(1, (date.fromtimestamp(now) - d0).days + 1)
            covered = len(recent)
            var = -sum(x["a"] for b in recent for x in b["items"] if x["a"] < 0 and x["c"] not in FIXED_CATS + NOT_SPENDING)
            per = var / float(max(covered, 1))      # 毎日の生活費が入るので, 記録した日 ≒ 過ごした日
            del span
            fz = sum(1 for b in recent if b.get("fuzzy")) / float(len(recent))
            w = max(0.12, min(0.9, (1.1 / math.sqrt(covered) + 0.25 * fz) * (1.0 - 0.3 * self.app.life.skill_soft("budget"))))
            lo, hi = per * (1 - 0.6 * w), per * (1 + w)              # 書き漏らしがあるぶん, 上には広め
            est["variable"] = [int(round(lo, -1)), int(round(hi, -1))]
            need = [fixed["total"] + lo - passive, fixed["total"] + hi - passive]
            est["need"] = [max(0, int(round(need[0], -2))), max(0, int(round(need[1], -2)))]
            est["note"] = "記録が少ないので大体" if covered < 5 else "うろ覚えの日が多いので大体" if fz > 0.4 \
                else "だいたいの見当" if covered < 14 else "記録からの見当"
        else:
            est["note"] = "食費・買い物などは、家計簿をつけないと分からない"
        last = lg.get("last_written")
        return {"money": int(app.life.player_state()["money"]), "days": days,
                "cats": [{"id": k, "label": CATS.get(k, k), "total": v} for k, v in sorted(cats.items(), key=lambda kv: kv[1])],
                "estimate": est, "last_written": last,
                "since_days": (date.fromtimestamp(now) - date.fromtimestamp(last)).days if last else None}
