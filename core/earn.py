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

    # ================================================================== 時間の経過
    def daily(self, t, month_changed):
        """日付が替わったとき (life.tick_world から)."""
        if month_changed:
            self.review(t)
        self.bonus(t)
        self.check_absence(t)

    def view(self, now=None):
        now = now or time.time()
        pt = self.pt()
        out = {"wage": self.wage(), "base_wage": int(self.L.econ().get("work_wage_per_hour", 1200)),
               "jobs": [dict(j, place_label=self.app.places.label(j["place"])) for j in self.jobs()],
               "rejected": {k: v for k, v in (self.ps().get("pt_rejected") or {}).items() if v > now}}
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
