"""稼ぎ方: 本業の昇給・賞与, アルバイト, 副業, 頼まれごと, フリマ, 宝くじ.

本業 (仕事に行く):
- 時給はあなたのもの (player.json の career.wage. 始めは economy.work_wage_per_hour). 月が替わると, 前の月の勤務を見直す:
  よく働いた月 (100 時間以上) は, 仕事スキルしだいで少し上がることがある (+1〜3%. 必ずではない). 休みが多い月 (40 時間未満) は下がる (−1〜3%).
  下限は始めの 85%, 上限は 2 倍.
- 賞与: 6 月と 12 月の 10 日. 前の半年に本業で稼いだ額の 15% ほど × 仕事スキルと運 (半年で 200 時間に届かなければ出ない).
アルバイト:
- 求人 (店ごとに時給と仕事内容が違う. JOBS. world.json の economy.parttime_jobs で書き換えられる) から選び, 曜日と時間 (シフト) を決めて応募する.
  受かるかは身だしなみ・会話しだい (落ちたら 3 日はその店に応募できない). 一つだけ.
- シフトの時間に「バイトに行く」(前後 30 分から). 戻ったとき, シフトの時間と重なった分だけ時給が出る. 仕事の上手さ (その店で使うスキル) で少し上下する.
  画面を閉じている間は, 行動パターンの「アルバイト」の時間に働く (シフトと重なった分だけ).
- シフトを休むと (その日の働いた時間がシフトの半分未満) 注意され, 30 日で 3 回休むと辞めさせられる.
- 店ではその店で働いている知り合いに会うことがある (相手の予定の勤め先が同じ店なら, 一緒に働く: knowsched.at_workplace).
"""
import math
import random
import time
from datetime import datetime, timedelta

from . import items as items_mod


JOBS = [
    {"id": "super", "place": "supermarket", "label": "スーパーの品出し・レジ", "wage": 1100, "skill": "work", "tire": 9, "hours": [8, 22]},
    {"id": "conv", "place": "convenience", "label": "コンビニの店員", "wage": 1150, "skill": "talk", "tire": 8, "hours": [6, 24]},
    {"id": "book", "place": "bookstore", "label": "本屋の店員（品出し・レジ）", "wage": 1050, "skill": "work", "tire": 7, "hours": [10, 21]},
    {"id": "cafe", "place": "cafe", "label": "カフェのホール", "wage": 1100, "skill": "talk", "tire": 9, "hours": [8, 21]},
    {"id": "drug", "place": "drugstore", "label": "ドラッグストアの品出し", "wage": 1100, "skill": "work", "tire": 8, "hours": [9, 22]},
    {"id": "family", "place": "family", "label": "ファミレスのキッチン", "wage": 1200, "skill": "cook", "tire": 11, "hours": [7, 24]},
    {"id": "elec", "place": "electronics", "label": "家電量販店の販売", "wage": 1250, "skill": "talk", "tire": 9, "hours": [10, 21]},
    {"id": "mall", "place": "mall", "label": "ショッピングモールのイベントスタッフ", "wage": 1200, "skill": "care", "tire": 10, "hours": [10, 21]},
]
def hm(s):
    h, m = str(s).split(":")
    return int(h) * 60 + int(m)


# 副業 (スキルを生かす): 依頼が来るかは運と評判しだい. 時給の目安 rate. min: このスキルに届くと依頼が来はじめる
GIGS = {
    "house": {"label": "家事代行", "skill": "house", "min": 15, "h": (2, 3), "rate": 1500, "icon": "🧹",
              "clients": ["近所の高齢の方", "共働きの家庭", "引っ越してきたばかりの人", "忙しい一人暮らしの人"]},
    "cook": {"label": "作り置きの代行", "skill": "cook", "min": 20, "h": (2, 3), "rate": 1450, "icon": "🍳",
             "clients": ["子育て中の家庭", "一人暮らしの高齢の方", "共働きの家庭", "食事を気にしている人"]},
    "write": {"label": "文章の仕事", "skill": "write", "min": 20, "h": (1, 3), "rate": 1300, "icon": "✍",
              "clients": ["地域の情報サイト", "小さな会社のブログ", "お店の紹介ページ", "町内会の会報"]},
}
# 頼まれごと (知り合いから): (種類, 名前, 時間, 疲れ). 日時の決め方は core/appoint.py (favor_offer):
#   move = 相手が日時を決めてくる (その日しか無理) / plants = 相手の留守中の数日のうちに, 自分で家へ行く (会わない) /
#   ほか = 相手が案を出すことも, こちらに都合を聞いてくることもある (「別の日時なら」でやりとり)
FAVORS = [("move", "引っ越しの手伝い", 4.0, 30), ("clean", "大掃除の手伝い", 3.0, 20), ("furniture", "家具の組み立て", 2.0, 12),
          ("plants", "留守中の植木の水やり", 0.5, 2), ("pc", "パソコンの設定", 1.0, 4), ("carry", "荷物運び", 1.5, 14)]
FAVOR_KIND = {k: (k, n, h, t) for k, n, h, t in FAVORS}
FAVOR_BY_LABEL = {n: k for k, n, h, t in FAVORS}
# フリマ: 売れない種類 (食べ物・消耗品). 送料 (種類ごと). 手数料 10%
FLEA_NG = ("food", "meal", "tea", "sweets", "medicine", "detergent")
FLEA_SHIP = {"books": 230, "clothes": 450}         # 本は安い送り方で. ほかは 350
FLEA_FEE = 0.10
# 宝くじ: 1 枚 300 円. 1 枚あたりの当せん (確率, 金額). 期待値はおよそ 4 割 (現実の宝くじと同じくらい)
LOTTO_PRICE = 300
LOTTO = [(1e-7, 300000000), (5e-7, 10000000), (2e-5, 1000000), (1e-3, 10000), (0.01, 3000), (0.1, 300)]
LOTTO_PLACES = ("station", "shopping_street", "mall")       # 売り場のある行き先
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAYS_JA = dict(zip(DAYS, "月火水木金土日"))


class Earn:
    def __init__(self, app):
        self.app = app

    @property
    def L(self):
        return self.app.life

    def ps(self):
        return self.L.player_state()

    # ================================================================== 本業
    def career(self):
        ps = self.ps()
        c = ps.get("career")
        if c is None:
            c = ps["career"] = {"wage": int(self.L.econ().get("work_wage_per_hour", 1200)), "months": {}}
        return c

    def wage(self):
        return int(self.career()["wage"])

    def record_main(self, h, pay, t):
        """本業で働いた時間と稼ぎを, 月ごとに覚える (見直し・賞与のもと)."""
        if h <= 0:
            return
        mo = self.career()["months"]
        k = datetime.fromtimestamp(t).strftime("%Y-%m")
        r = mo.setdefault(k, {"h": 0.0, "pay": 0})
        r["h"] = round(r["h"] + h, 2)
        r["pay"] = int(r["pay"] + pay)
        for old in sorted(mo)[:-8]:
            mo.pop(old)

    def review(self, t):
        """月が替わった: 前の月の本業を見直す. 時給が変わったらひとことを返す."""
        c = self.career()
        dt = datetime.fromtimestamp(t)
        prev = (dt.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        if c.get("reviewed") == prev:
            return None
        c["reviewed"] = prev
        h = float((c["months"].get(prev) or {}).get("h", 0))
        base = float(self.L.econ().get("work_wage_per_hour", 1200))
        w0 = float(c["wage"])
        sk = self.L.skill("work")
        if h >= 100 and random.random() < 0.25 + sk / 200.0:
            w = w0 * (1 + random.uniform(0.01, 0.03) * (0.5 + sk / 100.0))
        elif h < 40 and c["months"]:
            w = w0 * (1 - random.uniform(0.01, 0.03))
        else:
            return None
        w = int(round(min(base * 2, max(base * 0.85, w)) / 10.0)) * 10
        if w == int(w0):
            return None
        c["wage"] = w
        text = "%sの勤務の見直しで、本業の時給が %s円 → %s円に%s" % (
            prev.replace("-", "年") + "月", format(int(w0), ","), format(w, ","), "上がった" if w > w0 else "下がった（休みが多かった）")
        self.L.money_note(t, text)
        return text

    def bonus(self, t):
        """6 月・12 月の 10 日の賞与. 出たら額を返す."""
        dt = datetime.fromtimestamp(t)
        c = self.career()
        key = dt.strftime("%Y-%m")
        if dt.month not in (6, 12) or dt.day != 10 or c.get("bonus_paid") == key:
            return 0
        c["bonus_paid"] = key
        months = [(dt.replace(day=1) - timedelta(days=31 * i)).strftime("%Y-%m") for i in range(1, 7)]
        h = sum(float((c["months"].get(m) or {}).get("h", 0)) for m in months)
        pay = sum(int((c["months"].get(m) or {}).get("pay", 0)) for m in months)
        if h < 200:
            if pay:
                self.app.solo.note("work", "賞与の時期だが、この半年は勤務が少なく、賞与は出なかった", t, icon="💼", name="賞与")
            return 0
        amt = int(pay * 0.15 * (0.7 + 0.6 * self.L.skill("work") / 100.0) * random.uniform(0.85, 1.15) / 1000) * 1000
        if amt <= 0:
            return 0
        self.ps()["money"] += amt
        self.L.ledger(t, amt, "income", "賞与")
        text = "%d月の賞与が出た（%s円）" % (dt.month, format(amt, ","))
        self.app.solo.note("work", text, t, icon="💼", name="賞与", money={"p": amt})
        return amt

    # ================================================================== アルバイト
    def jobs(self):
        return self.L.econ().get("parttime_jobs") or JOBS

    def job(self, jid):
        j = next((x for x in self.jobs() if x["id"] == jid), None)
        if not j:
            raise KeyError("求人が見つかりません: %s" % jid)
        return j

    def pt(self):
        return self.ps().get("parttime")

    def apply(self, jid, shifts, now=None):
        """求人に応募する. shifts: [{days: "tue,thu", from: "17:00", to: "21:00"}] (1〜3 つ. 1 回 2〜8 時間, 店の時間の中)."""
        now = now or time.time()
        j = self.job(jid)
        ps = self.ps()
        if self.pt():
            raise ValueError("もうアルバイトをしています（先に辞めてください）")
        ng = (ps.get("pt_rejected") or {}).get(jid, 0)
        if now < ng:
            raise ValueError("%sには、少し前に落ちたばかりです（%s から応募できます）" % (j["label"], datetime.fromtimestamp(ng).strftime("%m/%d")))
        clean = []
        for s in (shifts or [])[:3]:
            days = [d for d in str(s.get("days") or "").split(",") if d in DAYS]
            a, b = hm(s.get("from") or "0:00"), hm(s.get("to") or "0:00")
            if not days:
                raise ValueError("シフトの曜日を選んでください")
            if not 120 <= b - a <= 480:
                raise ValueError("シフトは 1 回 2〜8 時間です")
            lo, hi = j.get("hours") or [9, 21]
            if a < lo * 60 or b > hi * 60:
                raise ValueError("%sのシフトは %d:00〜%d:00 の中で" % (j["label"], lo, hi))
            clean.append({"days": ",".join(days), "from": "%02d:%02d" % divmod(a, 60), "to": "%02d:%02d" % divmod(b, 60)})
        if not clean:
            raise ValueError("シフトを決めてください")
        # 面接: 身だしなみと会話で受かりやすく (必ずではない)
        p = 0.55 + 0.2 * self.L.skill_soft("groom") + 0.15 * self.L.skill_soft("talk")
        if random.random() >= p:
            ps.setdefault("pt_rejected", {})[jid] = now + 3 * 86400
            self.L.save_player()
            text = "%sの面接を受けたが、今回は見送りになった" % j["label"]
            self.app.solo.note("work", text, now, icon="🧑‍💼", name="バイトの面接")
            return {"ok": False, "text": text}
        ps["parttime"] = {"job": jid, "shifts": clean, "since": now, "att": {}, "absent": []}
        self.L.save_player()
        text = "%sの面接に受かった。%sから働く" % (j["label"], self.shift_text(clean))
        self.app.solo.note("work", text, now, icon="🧑‍💼", name="バイトの面接")
        return {"ok": True, "text": text}

    def quit(self, now=None, fired=False):
        pt = self.pt()
        if not pt:
            raise ValueError("アルバイトをしていません")
        j = self.job(pt["job"])
        self.ps()["parttime"] = None
        self.L.save_player()
        text = ("休みが続いて、%sを辞めさせられた" if fired else "%sのアルバイトを辞めた") % j["label"]
        self.app.solo.note("work", text, now or time.time(), icon="🧑‍💼", name="アルバイト")
        return {"text": text}

    @staticmethod
    def shift_text(shifts):
        return "・".join("%s %s〜%s" % ("".join(DAYS_JA.get(d, d) for d in s["days"].split(",")), s["from"], s["to"]) for s in shifts)

    def windows(self, t0, t1):
        """[t0, t1) に重なるシフトの時間 [(開始, 終了)]."""
        from .engine import day_match
        pt = self.pt()
        if not pt:
            return []
        out = []
        day = datetime.fromtimestamp(t0).replace(hour=0, minute=0, second=0, microsecond=0)
        while day.timestamp() < t1:
            for s in pt["shifts"]:
                if day_match(s["days"], day):
                    a = day.timestamp() + hm(s["from"]) * 60
                    b = day.timestamp() + hm(s["to"]) * 60
                    if b > t0 and a < t1:
                        out.append((a, b))
            day += timedelta(days=1)
        return out

    def shift_now(self, now=None):
        """いま入れるシフト (前後 30 分から) (開始, 終了) or None."""
        now = now or time.time()
        w = self.windows(now - 86400, now + 86400)
        return next(((a, b) for a, b in w if a - 1800 <= now < b), None)

    def pt_pay(self, t0, t1, record=True):
        """バイトから戻った: シフトと重なった時間 × 時給 × 上手さ. (稼ぎ, 時間, スキルの伸び) を返す."""
        pt = self.pt()
        if not pt:
            return 0, 0.0, {}
        j = self.job(pt["job"])
        h = sum(max(0.0, min(b, t1) - max(a, t0)) for a, b in self.windows(t0, t1)) / 3600.0
        if h < 0.25:
            return 0, 0.0, {}
        q = 0.9 + 0.2 * self.L.skill_soft(j.get("skill", "work"))
        pay = int(j["wage"] * h * q * self.app.body.work_mult() / 10) * 10
        gain = {}
        if record:
            d = datetime.fromtimestamp(t0).strftime("%Y-%m-%d")
            pt["att"][d] = round(pt["att"].get(d, 0) + h, 2)
            for k in sorted(pt["att"])[:-40]:
                pt["att"].pop(k)
            gain = {j.get("skill", "work"): self.L.train(j.get("skill", "work"), 0.3 * h)}
            if j.get("skill") != "work":
                gain["work"] = self.L.train("work", 0.15 * h)
            self.L.tire(float(j.get("tire", 9)) * h)
        return pay, h, gain

    def check_absence(self, t):
        """日付が替わった: 前の日のシフトを休んでいたら注意. 30 日で 3 回で辞めさせられる."""
        pt = self.pt()
        if not pt:
            return None
        day = datetime.fromtimestamp(t).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        if day.timestamp() < pt.get("since", 0):
            return None
        need = sum(b - a for a, b in self.windows(day.timestamp(), day.timestamp() + 86400)) / 3600.0
        if need <= 0 or pt["att"].get(day.strftime("%Y-%m-%d"), 0) >= need * 0.5:
            return None
        pt["absent"] = [x for x in pt.get("absent") or [] if t - x < 30 * 86400] + [t]
        j = self.job(pt["job"])
        if len(pt["absent"]) >= 3:
            return self.quit(t, fired=True)["text"]
        text = "%s（%d/%d）のバイトのシフトを休んでしまった。店長に注意された" % (j["label"], day.month, day.day)
        self.app.solo.note("work", text, t, icon="🧑‍💼", name="アルバイト")
        return text

    # ================================================================== 副業 (スキルを生かす)
    def gigs(self):
        ps = self.ps()
        g = ps.get("gigs")
        if g is None:
            g = ps["gigs"] = {"rep": {k: 30.0 for k in GIGS}, "offers": []}
        return g

    def gig_offers(self, t):
        """日付が替わった: スキルと評判しだいで, 副業の依頼が来る (運しだい. 3 件まで). 来た依頼を返す."""
        g = self.gigs()
        g["offers"] = [o for o in g["offers"] if o["until"] > t]
        out = []
        for k, G in GIGS.items():
            sk = self.L.skill(G["skill"])
            if sk < G["min"] or len(g["offers"]) >= 3 or any(o["kind"] == k for o in g["offers"]):
                continue
            rep = float(g["rep"].get(k, 30))
            p = max(0.01, min(0.35, 0.04 + 0.12 * self.L.skill_soft(G["skill"]) + 0.12 * (rep - 30) / 70.0))
            if random.random() >= p:
                continue
            h = round(random.uniform(*G["h"]) * 2) / 2.0
            pay = int(G["rate"] * h * random.uniform(0.9, 1.2) * (0.9 + 0.2 * rep / 100.0) / 100) * 100
            o = {"id": "g%d%s" % (int(t * 1000), k), "kind": k, "label": G["label"], "client": random.choice(G["clients"]),
                 "h": h, "pay": pay, "t": t, "until": t + 2 * 86400}
            g["offers"].append(o)
            out.append(o)
        return out

    def gig_take(self, gid, now=None):
        """依頼を受けて, 取りかかる (在席は work. 家事代行・作り置きは依頼先へ, 文章は家で)."""
        now = now or time.time()
        g = self.gigs()
        o = next((x for x in g["offers"] if x["id"] == gid), None)
        if not o:
            raise KeyError("依頼が見つかりません（期限が過ぎたかもしれません）")
        if self.app.presence.rec().get("mode") != "none":
            raise ValueError("いまは取りかかれません（先に戻ってください）")
        if self.L.stamina() < 15:
            raise ValueError("疲れていて、いまは取りかかれません（体力15以上）")
        g["offers"].remove(o)
        return o

    def gig_done(self, o, h, t):
        """副業から戻った: 時間と出来ばえで, 報酬と評判が決まる. (稼ぎ, 文, スキルの伸び)."""
        G = GIGS[o["kind"]]
        g = self.gigs()
        if h < 0.25:
            g["rep"][o["kind"]] = max(0.0, g["rep"].get(o["kind"], 30) - 5)
            return 0, "%sの依頼（%s）に取りかかったが、すぐにやめてしまった。依頼は取り消しになった" % (G["label"], o["client"]), {}
        done = min(1.0, h / o["h"])
        q = max(0.0, min(1.0, 0.25 + 0.6 * self.L.skill_soft(G["skill"]) + random.gauss(0, 0.15)))
        if done < 0.8:
            pay = int(o["pay"] * done * 0.8 / 100) * 100
            dr = -6.0
            how = "時間が足りず、途中までになった"
        else:
            pay = int(o["pay"] * (0.85 + 0.3 * q) / 100) * 100
            dr = (q - 0.5) * 16
            how = "とても喜ばれ、また頼みたいと言われた" if q > 0.7 else "お礼を言われた" if q > 0.4 else "少し不満そうだった"
        g["rep"][o["kind"]] = max(0.0, min(100.0, g["rep"].get(o["kind"], 30) + dr))
        gain = {G["skill"]: self.L.train(G["skill"], 0.4 * min(h, o["h"] * 1.5))}
        self.L.tire(7 * min(h, o["h"] * 1.5))
        if pay:
            self.ps()["money"] += pay
            self.L.ledger(t, pay, "income", "副業（%s）" % G["label"])
        return pay, "%s（%s）を終えた。%s（%s円）" % (G["label"], o["client"], how, format(pay, ",")), gain

    # ================================================================== 頼まれごと (知り合いから)
    def favors(self):
        return self.ps().setdefault("favors", [])

    def favor_offers(self, t):
        """日付が替わった: 知り合い (連絡先を知っている・家に行ける仲) から, ときどき頼まれごとが来る (2 件まで).
        頼まれ方と日時のすり合わせは約束の仕組み (core/appoint.py の favor_offer): 離れていればメッセージ, そばにいれば対面で.
        返事を放っておくと流れる (ほかの人に頼んで済んでしまう. appoint.live). 約束していないまま期限が過ぎたものも消す."""
        app = self.app
        fs = self.favors()
        keep = []
        for f in fs:
            x = app.appoint.find(f.get("appoint")) if f.get("appoint") else None
            if x and x["status"] in ("asked", "offered", "set", "waiting"):
                keep.append(f)
            elif not x and f["until"] > t:
                keep.append(f)
            elif not x and f["cid"] in app.chars:          # 返事をしないまま流れた: 少しがっかり
                st = app.state(f["cid"])
                app.apply_effects(st, {"trust": -1})
                app.save_state(f["cid"])
        fs[:] = keep
        out = []
        for cid, char in app.chars.items():
            if len(fs) >= 2 or app.bonds.stage(cid) not in ("contact", "visit") or any(f["cid"] == cid for f in fs):
                continue
            st = app.state(cid)
            if random.random() >= 0.012 + float(st["params"].get("affection", 50)) / 5000.0:
                continue
            kind, name, h, tire = random.choice(FAVORS)
            f = {"id": "f%d%s" % (int(t * 1000), cid), "cid": cid, "kind": kind, "label": name, "h": h, "tire": tire, "t": t,
                 "until": t + 3 * 86400}
            fs.append(f)
            out.append(f)
            app.appoint.favor_offer(f, t)
        return out

    def favor(self, fid):
        return next((f for f in self.favors() if f["id"] == fid), None)

    def migrate_favors(self, now=None):
        """以前から「頼まれている」もの (日時のすり合わせの前の形): 新しい流れ (トークの約束の欄で日時を決める) で答えられるように,
        相手から都合を聞かれている形の約束にする (起動したとき一度. 期限が過ぎていれば, そのまま流れる)."""
        app = self.app
        now = now or time.time()
        n = 0
        for f in self.favors():
            if f.get("appoint") or f["cid"] not in app.chars or f["until"] <= now:
                continue
            f.setdefault("kind", FAVOR_BY_LABEL.get(f["label"], "clean"))
            app.appoint.favor_offer(f, now, legacy=True)
            n += 1
        if n:
            self.L.save_player()
        return n

    def favor_answer(self, fid, yes, now=None):
        """頼まれごとに答える. 日時のすり合わせのある頼まれごと (いまはすべて) は, 約束の答えとして (トークの約束の欄と同じ).
        引き受けるには日時を決める (相手が日時を出していれば「行く」, 都合を聞かれていれば「別の日時なら」で日時を返す)."""
        now = now or time.time()
        app = self.app
        fs = self.favors()
        f = next((x for x in fs if x["id"] == fid), None)
        if not f:
            raise KeyError("頼まれごとが見つかりません（期限が過ぎたかもしれません）")
        if f.get("appoint"):
            x = app.appoint.find(f["appoint"])
            if x and x["status"] == "offered":
                if yes and x.get("ask"):
                    raise ValueError("いつなら行けるか、トークの約束の欄で日時を返してください")
                app.appoint.answer(x["id"], yes, now)
                return f, ("%sの%sは断った" % (app.chars[f["cid"]].get("name", ""), f["label"]) if not yes else
                           "%sの%sを引き受けた（%s）" % (app.chars[f["cid"]].get("name", ""), f["label"], app.appoint.when_of(x, now)))
            raise ValueError("日時は、トークの約束の欄で決めましょう")
        char = app.chars.get(f["cid"]) or {}
        if yes:
            if app.presence.rec().get("mode") != "none":
                raise ValueError("いまは手伝いに行けません（先に戻ってください）")
            if self.L.stamina() < f["tire"] * 0.5:
                raise ValueError("疲れていて、いまは手伝えそうにない")
        fs.remove(f)
        if not yes:
            st = app.state(f["cid"])
            app.apply_effects(st, {"mood": -1})
            app.save_state(f["cid"])
            app.chat.add(f["cid"], "me", "（%sは断った）" % f["label"], kind="favor", t=now)
            return f, "%sの%sは断った" % (char.get("name", ""), f["label"])
        app.chat.add(f["cid"], "me", "（%sを引き受けた）" % f["label"], kind="favor", t=now)
        return f, None

    def favor_done(self, f, h, t):
        """手伝いから戻った: 終わっていれば, お礼 (お金をもらえることも, もらえないことも. 仲しだい). (お礼の額, 文)."""
        app = self.app
        cid = f["cid"]
        char = app.chars.get(cid) or {}
        name = char.get("name", "")
        st = app.state(cid)
        self.L.tire(f["tire"] * min(1.0, h / max(0.25, f["h"])))
        if h < f["h"] * 0.6:
            app.apply_effects(st, {"trust": -1, "mood": -1})
            app.save_state(cid)
            return 0, "%sの%sに行ったが、途中で帰ってきてしまった" % (name, f["label"])
        stage = app.bonds.stage(cid)
        aff = float(st["params"].get("affection", 50))
        eff, _ = app.bonds.realize(char, st, {"affection": 2, "trust": 3, "mood": 3}, "_favor_done", t)    # 必ず深まる, ではない
        app.apply_effects(st, app.trait_effects(char, eff))
        app.bonds.met(st, t)
        app.bonds.touch(st, t)
        p_money = (0.6 if stage == "contact" else 0.35) - (aff - 50) / 250.0       # 仲がいいほど, お金よりほかの形で
        her = self.L.her_money(st)
        amt = 0
        if f.get("kind") == "plants":          # 留守中の水やり: 会っていないので, お礼は帰ってきてからのメッセージで
            app.save_state(cid)
            app.chat.add(cid, "sys", "（%sの%sを終えた）" % (name, f["label"]), kind="favor", t=t)
            app.chat.add(cid, "her", app.chat.line(char, "favor_plants_thanks", {}), kind="favor_plants_thanks", t=t + 3600)
            if f in self.favors():
                self.favors().remove(f)
            return 0, "%sの%sを終えた。鍵をかけて帰った（お礼は、帰ってきてからメッセージで）" % (name, f["label"])
        if random.random() < p_money and her["a"] > 3000:
            amt = min(int(her["a"] * 0.3), int(1000 * f["h"] * random.uniform(0.8, 1.5) / 500) * 500)
        if amt > 0:
            her["a"] -= amt
            self.ps()["money"] += amt
            self.L.ledger(t, amt, "income", "%sからのお礼" % name)
            how = "お礼にと、%s円を渡された" % format(amt, ",")
        else:
            how = random.choice(("お礼に、ご飯をごちそうしてくれた", "何度もお礼を言われた", "今度何かお返しするね、と言われた",
                                 "お礼に、お菓子を持たせてくれた"))
        app.save_state(cid)
        app.chat.add(cid, "sys", "（%sの%sを終えた）" % (name, f["label"]), kind="favor", t=t)
        if f in self.favors():
            self.favors().remove(f)
        return amt, "%sの%sを終えた。%s" % (name, f["label"], how)

    # ================================================================== フリマ
    def flea(self):
        return self.ps().setdefault("flea", [])

    @staticmethod
    def fair(iid):
        """中古の相場 (定価の 45%)."""
        return max(100, int(items_mod.CATALOG[iid]["price"] * 0.45 / 10) * 10)

    @staticmethod
    def ship(iid):
        it = items_mod.CATALOG[iid]
        return FLEA_SHIP["books"] if "books" in it["tags"] else FLEA_SHIP.get(it["kind"], 350)

    def flea_list(self, iid, price, now=None):
        """持ち物を出品する (1 個. 30 日で売れなければ手元に戻る)."""
        now = now or time.time()
        it = items_mod.CATALOG.get(iid)
        if not it or it["kind"] in FLEA_NG:
            raise ValueError("その品は出品できません（食べ物・消耗品は出せません）")
        if self.app.items.count(iid) < 1:
            raise ValueError("%sを持っていません" % it["name"])
        price = int(price)
        lo = int((self.ship(iid) + 100) / (1 - FLEA_FEE) / 10) * 10        # 送料と手数料で赤字にならない値段から
        if not lo <= price <= it["price"] * 2:
            raise ValueError("値段は %s円〜%s円で（送料と手数料を引いて手元に残るように）" % (format(lo, ","), format(it["price"] * 2, ",")))
        if len(self.flea()) >= 10:
            raise ValueError("出品は 10 個まで")
        self.app.items.add(iid, -1)
        x = {"id": "x%d" % int(now * 1000), "iid": iid, "name": it["name"], "icon": it["icon"], "price": price, "t": now,
             "until": now + 30 * 86400}
        self.flea().append(x)
        self.L.save_player()
        return x

    def flea_cancel(self, xid):
        fl = self.flea()
        x = next((y for y in fl if y["id"] == xid), None)
        if not x:
            raise KeyError("出品が見つかりません")
        fl.remove(x)
        self.app.items.add(x["iid"], 1)
        self.L.save_player()
        return x

    def flea_demand(self, iid, t):
        """季節の売れやすさ (服は衣替えの春秋, マフラーは秋冬, ゲームは年末)."""
        m = datetime.fromtimestamp(t).month
        it = items_mod.CATALOG[iid]
        if iid == "scarf":
            return 1.6 if m in (10, 11, 12, 1) else 0.4 if m in (5, 6, 7, 8) else 1.0
        if it["kind"] == "clothes":
            return 1.3 if m in (3, 4, 9, 10) else 0.9
        if iid == "game":
            return 1.4 if m in (12, 1) else 1.0
        if iid == "necklace":
            return 0.6
        return 1.0

    def flea_rate(self, x, t):
        """1 時間あたりに売れる見込み: 相場より安いほど売れやすい. やりくりスキルで少し (出品の写真や説明が上手い)."""
        r = x["price"] / float(self.fair(x["iid"]))
        return 0.012 * min(3.0, math.exp(-2.5 * (r - 1))) * self.flea_demand(x["iid"], t) * (1 + 0.25 * self.L.skill_soft("budget"))

    def flea_step(self, t, step):
        fl = self.flea()
        for x in list(fl):
            if random.random() < 1 - math.exp(-self.flea_rate(x, t) * step / 3600.0):
                fl.remove(x)
                net = int(x["price"] * (1 - FLEA_FEE)) - self.ship(x["iid"])
                self.ps()["money"] += net
                self.L.ledger(t, net, "income", "フリマ（%s）" % x["name"])
                self.app.solo.note("money", "フリマで%sが %s円で売れた（手数料・送料を引いて %s円）" % (
                    x["name"], format(x["price"], ","), format(net, ",")), t, icon="📦", name="フリマ", money={"p": net})
            elif t >= x["until"]:
                fl.remove(x)
                self.app.items.add(x["iid"], 1)
                self.app.solo.note("money", "フリマに出していた%sは、売れないまま期限が来たので取り下げた" % x["name"], t, icon="📦", name="フリマ")

    # ================================================================== 宝くじ
    def lotto(self):
        return self.ps().setdefault("lotto", {"tickets": [], "results": []})

    @staticmethod
    def next_draw(t):
        """次の抽せん (金曜 18:00)."""
        d = datetime.fromtimestamp(t)
        x = d.replace(hour=18, minute=0, second=0, microsecond=0) + timedelta(days=(4 - d.weekday()) % 7)
        if x <= d:
            x += timedelta(days=7)
        return x.timestamp()

    def lotto_buy(self, n, now=None):
        """売り場のある行き先 (駅前・商店街・モール) にいるときに買える."""
        now = now or time.time()
        p = self.app.presence.rec()
        if p.get("mode") != "out" or p.get("place") not in LOTTO_PLACES:
            raise ValueError("宝くじは、売り場のある駅前・商店街・ショッピングモールで買えます")
        n = int(n)
        if not 1 <= n <= 100:
            raise ValueError("1〜100枚で")
        cost = LOTTO_PRICE * n
        if self.ps()["money"] < cost:
            raise ValueError("お金が足りません（%s円）" % format(cost, ","))
        self.ps()["money"] -= cost
        self.L.ledger(now, -cost, "fun", "宝くじ %d枚" % n)
        L = self.lotto()
        tk = {"t": now, "n": n, "draw": self.next_draw(now)}
        L["tickets"].append(tk)
        self.L.save_player()
        self.app.solo.note("money", "宝くじを%d枚買った（%s円。%sに抽せん）" % (n, format(cost, ","), datetime.fromtimestamp(tk["draw"]).strftime("%m/%d %H:%M")),
                           now, icon="🎫", name="宝くじ", money={"p": -cost})
        return tk

    def lotto_step(self, t):
        L = self.lotto()
        for tk in [x for x in L["tickets"] if x["draw"] <= t]:
            L["tickets"].remove(tk)
            won = 0
            for _ in range(tk["n"]):
                r = random.random()
                acc = 0.0
                for p, amt in LOTTO:
                    acc += p
                    if r < acc:
                        won += amt
                        break
            if won:
                self.ps()["money"] += won
                self.L.ledger(tk["draw"], won, "income", "宝くじの当せん")
            text = "宝くじ%d枚の抽せん: %s" % (tk["n"], "%s円当たった" % format(won, ",") if won else "はずれ")
            L["results"].append({"t": tk["draw"], "n": tk["n"], "won": won})
            del L["results"][:-10]
            self.app.solo.note("money", text, tk["draw"], icon="🎫", name="宝くじ", **({"money": {"p": won}} if won else {}))

    # ================================================================== 時間の経過
    def step(self, t, step):
        """5 分ごと (life.tick_world から): フリマの売れ行き, 宝くじの抽せん."""
        if self.ps().get("flea"):
            self.flea_step(t, step)
        if (self.ps().get("lotto") or {}).get("tickets"):
            self.lotto_step(t)

    def daily(self, t, month_changed):
        """日付が替わったとき (life.tick_world から)."""
        if month_changed:
            self.review(t)
        self.bonus(t)
        self.check_absence(t)
        self.gig_offers(t)
        self.favor_offers(t)

    def view(self, now=None):
        now = now or time.time()
        pt = self.pt()
        out = {"wage": self.wage(), "base_wage": int(self.L.econ().get("work_wage_per_hour", 1200)),
               "jobs": [dict(j, place_label=self.app.places.label(j["place"])) for j in self.jobs()],
               "rejected": {k: v for k, v in (self.ps().get("pt_rejected") or {}).items() if v > now}}
        g = self.gigs()
        out["gigs"] = {"offers": [dict(o, icon=GIGS[o["kind"]]["icon"]) for o in g["offers"] if o["until"] > now],
                       "rep": {k: round(v) for k, v in g["rep"].items()},
                       "kinds": [{"id": k, "label": G["label"], "skill": G["skill"], "min": G["min"], "open": self.L.skill(G["skill"]) >= G["min"]}
                                 for k, G in GIGS.items()]}
        out["flea"] = [dict(x, fair=self.fair(x["iid"]), net=int(x["price"] * (1 - FLEA_FEE)) - self.ship(x["iid"])) for x in self.flea()]
        out["flea_items"] = [{"id": i, "name": items_mod.CATALOG[i]["name"], "icon": items_mod.CATALOG[i]["icon"], "n": n,
                              "price": items_mod.CATALOG[i]["price"], "fair": self.fair(i), "ship": self.ship(i)}
                             for i, n in sorted((self.ps().get("items") or {}).items())
                             if n > 0 and i in items_mod.CATALOG and items_mod.CATALOG[i]["kind"] not in FLEA_NG]
        lt = self.lotto()
        p = self.app.presence.rec()
        out["lotto"] = {"price": LOTTO_PRICE, "tickets": lt["tickets"], "results": list(reversed(lt["results"][-3:])),
                        "can": p.get("mode") == "out" and p.get("place") in LOTTO_PLACES}
        out["favors"] = []
        for f in self.favors():
            x = self.app.appoint.find(f.get("appoint")) if f.get("appoint") else None
            if not x and f["until"] <= now:
                continue
            out["favors"].append(dict(f, name=(self.app.chars.get(f["cid"]) or {}).get("name", ""),
                                      status=x["status"] if x else "", status_label=self.app.appoint.favor_status(x, now) if x else "",
                                      appoint=x["id"] if x else None,
                                      at=x["t"] if x and not x.get("ask") else None))      # カレンダーで開く日 (日時の決まっていないものは今日)
        mo = self.career()["months"].get(datetime.fromtimestamp(now).strftime("%Y-%m")) or {}
        out["month_h"] = round(float(mo.get("h", 0)), 1)
        if pt:
            j = self.job(pt["job"])
            sh = self.shift_now(now)
            nx = next(((a, b) for a, b in self.windows(now, now + 8 * 86400) if a > now), None)
            out["parttime"] = {"job": j["id"], "label": j["label"], "place": j["place"], "place_label": self.app.places.label(j["place"]),
                               "wage": j["wage"], "shifts": pt["shifts"], "shift_text": self.shift_text(pt["shifts"]),
                               "now": list(sh) if sh else None, "next": nx[0] if nx else None,
                               "absent": len([x for x in pt.get("absent") or [] if now - x < 30 * 86400])}
        return out
