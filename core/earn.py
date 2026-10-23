"""稼ぎ方: 本業の昇給・賞与, アルバイト.

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
import random
import time
from datetime import datetime, timedelta


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
# 頼まれごと (知り合いから): (名前, 時間, 疲れ)
FAVORS = [("引っ越しの手伝い", 4.0, 30), ("大掃除の手伝い", 3.0, 20), ("家具の組み立て", 2.0, 12), ("留守中の植木の水やり", 0.5, 2),
          ("パソコンの設定", 1.0, 4), ("荷物運び", 1.5, 14)]
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
        """日付が替わった: 知り合い (連絡先を知っている・家に行ける仲) から, ときどき頼まれごとが来る (2 件まで). 古いものは流れる."""
        app = self.app
        fs = self.favors()
        keep = []
        for f in fs:
            if f["until"] > t:
                keep.append(f)
            elif f["cid"] in app.chars:          # 返事をしないまま流れた: 少しがっかり
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
            name, h, tire = random.choice(FAVORS)
            f = {"id": "f%d%s" % (int(t * 1000), cid), "cid": cid, "label": name, "h": h, "tire": tire, "t": t, "until": t + 3 * 86400}
            fs.append(f)
            out.append(f)
            app.chat.add(cid, "sys", "（%sから、%sを頼まれた）" % (char.get("name", ""), name), kind="favor", t=t)
        return out

    def favor_answer(self, fid, yes, now=None):
        """頼まれごとに答える. 引き受けたら, 取りかかる (在席は work). 断ったら少しがっかりされる."""
        now = now or time.time()
        app = self.app
        fs = self.favors()
        f = next((x for x in fs if x["id"] == fid), None)
        if not f:
            raise KeyError("頼まれごとが見つかりません（期限が過ぎたかもしれません）")
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
        app.apply_effects(st, app.trait_effects(char, {"affection": 2, "trust": 3, "mood": 3}))
        app.bonds.met(st, t)
        app.bonds.touch(st, t)
        p_money = (0.6 if stage == "contact" else 0.35) - (aff - 50) / 250.0       # 仲がいいほど, お金よりほかの形で
        her = self.L.her_money(st)
        amt = 0
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
        return amt, "%sの%sを終えた。%s" % (name, f["label"], how)

    # ================================================================== 時間の経過
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
        out["favors"] = [dict(f, name=(self.app.chars.get(f["cid"]) or {}).get("name", "")) for f in self.favors() if f["until"] > now]
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
