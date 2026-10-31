"""資格: 申し込み (試験の 1 か月前まで・受験料)・勉強 (研鑽の「資格の勉強」で勉強時間がたまる)・試験 (年に数回の日曜の午前)・
合否 (2 週間後に届く). 受かった資格はずっと有効.

- 受かるか: 要るスキルが目安に届いているか・勉強時間が目安に届いているか・当日の体調と疲れ・運.
  目安に届いていても 1〜2 割は落ち, 届いていなくてもまれに受かる. 落ちたら勉強時間の 3 割を次に持ち越す.
- 寝込むほど体調が悪ければ欠席 (受験料は戻らない). 画面を閉じていても, 試験の日になれば受けたことにする.
- 受かると: 本業 (時給の見直しで上がりやすく・上限が上がる・毎月の資格手当) / アルバイト (受かりやすい・時給) /
  副業 (依頼が増える・単価) / 家計簿 (簿記: 覚えている). 受かった・落ちたことは話題に残る (core/topics.py).
"""
import math
import random
import time
from datetime import date, datetime, timedelta

QUALS = {
    "biz": {"label": "ビジネス実務検定", "icon": "💼", "skills": ["work"], "need": 45, "study": 30, "fee": 6000, "months": [2, 6, 10],
            "allow": 5000, "raise": 0.15, "cap": 2.3, "desc": "本業: 時給が上がりやすく上限も上がる・毎月の資格手当"},
    "boki": {"label": "簿記検定", "icon": "📒", "skills": ["budget", "work"], "need": 40, "study": 35, "fee": 5000, "months": [2, 6, 11],
             "allow": 3000, "raise": 0.05, "kakeibo": 0.25, "desc": "本業: 毎月の資格手当・家計簿をよく覚えている"},
    "service": {"label": "接客検定", "icon": "🙇", "skills": ["talk", "care"], "need": 35, "study": 20, "fee": 4000, "months": [3, 9],
                "jobs": ["conv", "cafe", "elec"], "job_wage": 50, "job_pass": 0.15, "desc": "アルバイト: 接客の店に受かりやすく・時給が少し上がる"},
    "cook": {"label": "調理の検定", "icon": "🍳", "skills": ["cook"], "need": 45, "study": 30, "fee": 8000, "months": [5, 11],
             "jobs": ["family"], "job_wage": 100, "gig": "cook", "gig_rate": 0.2, "gig_p": 1.2,
             "desc": "アルバイト: キッチンの時給が上がる・副業: 作り置きの単価が上がる"},
    "house": {"label": "家事の認定", "icon": "🧹", "skills": ["house"], "need": 35, "study": 20, "fee": 5000, "months": [4, 10],
              "gig": "house", "gig_rate": 0.2, "gig_p": 1.4, "desc": "副業: 家事代行の依頼が増え・単価が上がる"},
    "drive": {"label": "普通自動車免許", "icon": "🚗", "skills": ["care"], "need": 25, "study": 30, "fee": 300000,
              "months": list(range(1, 13)), "place": "driving_school",
              "desc": "車を運転できる（申し込むと教習所に入校。教習は教習所に通って受ける。費用は試験込み）"},
    "write": {"label": "文章検定", "icon": "✍", "skills": ["write"], "need": 40, "study": 25, "fee": 5000, "months": [6, 12],
              "gig": "write", "gig_rate": 0.2, "gig_p": 1.4, "desc": "副業: 文章の仕事の依頼が増え・単価が上がる"},
}
DEADLINE_DAYS = 30
RESULT_DAYS = 14
EXAM_H = (10, 13)
CARRY = 0.3


def exam_day(y, m):
    """その月の第 2 日曜."""
    d = date(y, m, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(days=7)


def next_exam(qid, today):
    """申し込める次の試験日 (締め切り = 試験の 30 日前を過ぎていないもの)."""
    q = QUALS[qid]
    for y in (today.year, today.year + 1, today.year + 2):
        for m in sorted(q["months"]):
            d = exam_day(y, m)
            if d - timedelta(days=DEADLINE_DAYS) >= today:
                return d
    return None


class Quals:
    def __init__(self, app):
        self.app = app

    def rec(self):
        ps = self.app.life.player_state()
        r = ps.setdefault("quals", {})
        r.setdefault("apps", {})
        r.setdefault("study", {})
        r.setdefault("have", {})
        return r

    def has(self, qid):
        return qid in self.rec()["have"]

    def have_list(self):
        return [QUALS[q] for q in self.rec()["have"] if q in QUALS]

    # ------------------------------------------------------------------ 申し込み・勉強
    def apply(self, qid, now=None):
        now = now or time.time()
        if qid not in QUALS:
            raise KeyError("資格が見つかりません: %s" % qid)
        q = QUALS[qid]
        r = self.rec()
        if self.has(qid):
            raise ValueError("%sはもう持っています" % q["label"])
        a = r["apps"].get(qid)
        if a and a["status"] in ("applied", "taken"):
            raise ValueError("%sはもう申し込んでいます（%s）" % (q["label"], a["exam"]))
        d = next_exam(qid, datetime.fromtimestamp(now).date())
        L = self.app.life
        ps = L.player_state()
        if ps["money"] < q["fee"]:
            raise ValueError("受験料が足りません（%s円）" % format(q["fee"], ","))
        ps["money"] -= q["fee"]
        L.ledger(now, -q["fee"], "other", "%sの受験料" % q["label"])
        r["apps"][qid] = {"exam": d.isoformat(), "status": "applied", "fee": q["fee"], "t": now}
        L.save_player()
        self.app.solo.note("money", "%sに申し込んだ（%s円。試験は%s）" % (q["label"], format(q["fee"], ","), self._md(d)), now,
                           icon="🎓", name="資格", money={"p": -q["fee"]})
        self.app.trace.add("quals", "申し込んだ", None, now, qid=qid, exam=d.isoformat())
        return r["apps"][qid]

    def enrolled(self, qid):
        """申し込んで, まだ試験を受けていない (教習所なら入校している)."""
        return (self.rec()["apps"].get(qid) or {}).get("status") == "applied"

    def study(self, qid, h):
        """資格の勉強 (研鑽). 勉強時間がたまり, 要るスキルの最初のものも少し伸びる. (文, スキルの伸び) を返す."""
        q = QUALS.get(qid)
        if not q:
            raise KeyError("資格が見つかりません: %s" % qid)
        r = self.rec()
        r["study"][qid] = round(r["study"].get(qid, 0.0) + h, 2)
        sk = q["skills"][0]
        gain = self.app.life.train(sk, min(2.0, 0.7 * h)) if h >= 0.25 else 0
        self.app.life.save_player()
        return "%sの勉強をした（勉強時間 %d／目安 %d時間）" % (q["label"], int(r["study"][qid]), q["study"]), {sk: gain}

    # ------------------------------------------------------------------ 試験・合否
    def pass_chance(self, qid):
        q = QUALS[qid]
        L = self.app.life
        s = sum(L.skill(k) for k in q["skills"]) / float(len(q["skills"])) / q["need"]
        r = self.rec()["study"].get(qid, 0.0) / float(q["study"])
        ps = L.player_state()
        tired = max(0.0, (40 - float(ps.get("stamina", 100))) / 40.0) + 0.5 * self.app.body.level()
        z = 1.6 + 4 * (min(s, 1.3) - 1) + 3 * (min(r, 1.3) - 1) - tired
        return round(max(0.01, min(0.92, 1 / (1 + math.exp(-z)))), 3)

    def daily(self, t):
        """日付が替わったとき: 今日が試験なら受ける (寝込んでいれば欠席) / 合否が届く."""
        r = self.rec()
        today = datetime.fromtimestamp(t).date()
        for qid, a in list(r["apps"].items()):
            q = QUALS.get(qid)
            if not q:
                continue
            exam = date.fromisoformat(a["exam"])
            if a["status"] == "applied" and exam <= today:
                at = datetime(exam.year, exam.month, exam.day, EXAM_H[1]).timestamp()
                if self.app.body.level() >= 3:
                    a["status"] = "absent"
                    self.app.solo.note("work", "%sの試験の日だったが、寝込んでいて受けられなかった（受験料は戻らない）" % q["label"], at,
                                       icon="🎓", name="資格")
                    self.app.trace.add("quals", "欠席", None, at, qid=qid)
                    continue
                p = self.pass_chance(qid)
                a.update(status="taken", ok=random.random() < p, p=p, result_at=at + RESULT_DAYS * 86400)
                self.app.life.tire(15)
                self.app.solo.note("work", "%sの試験を受けた（結果は2週間後）" % q["label"], at, icon="🎓", name="資格")
                self.app.trace.add("quals", "試験を受けた", None, at, qid=qid, p=p, ok=a["ok"])
            if a["status"] == "taken" and a.get("result_at", 9e18) <= t:
                at = a["result_at"]
                if a["ok"]:
                    a["status"] = "pass"
                    r["have"][qid] = at
                    text = "%sに合格した！" % q["label"]
                    self.app.topics.add("qual", "%sに受かった話" % q["label"], ["work"], at)
                else:
                    a["status"] = "fail"
                    r["study"][qid] = round(r["study"].get(qid, 0.0) * CARRY, 2)
                    text = "%sは不合格だった（勉強時間は少しだけ次に持ち越す）" % q["label"]
                    self.app.topics.add("qual", "%sに落ちた話" % q["label"], ["work"], at)
                self.app.solo.note("work", text, at, icon="🎓", name="資格")
                self.app.life.money_note(at, text)
                self.app.trace.add("quals", "合否", None, at, qid=qid, ok=a["ok"])
        self.app.life.save_player()

    def exam_now(self, now=None):
        """いま資格の試験の最中か (申し込んだ試験の日の 10〜13 時). 試験名 or None."""
        d = datetime.fromtimestamp(now or time.time())
        if not EXAM_H[0] <= d.hour < EXAM_H[1]:
            return None
        for qid, a in self.rec()["apps"].items():
            if a.get("exam") == d.date().isoformat() and a.get("status") in ("applied", "taken") and qid in QUALS:
                return QUALS[qid]["label"]
        return None

    # ------------------------------------------------------------------ 効き目
    def raise_bonus(self):
        return sum(q.get("raise", 0) for q in self.have_list())

    def wage_cap(self):
        return max([2.0] + [q.get("cap", 2.0) for q in self.have_list()])

    def allowance(self):
        return sum(int(q.get("allow", 0)) for q in self.have_list())

    def job_wage(self, jid):
        return sum(int(q.get("job_wage", 0)) for q in self.have_list() if jid in q.get("jobs", ()))

    def job_pass(self, jid):
        return sum(float(q.get("job_pass", 0)) for q in self.have_list() if jid in q.get("jobs", ()))

    def gig(self, kind):
        """副業の (依頼の来やすさの倍率, 単価の倍率)."""
        p, r = 1.0, 1.0
        for q in self.have_list():
            if q.get("gig") == kind:
                p *= q.get("gig_p", 1.0)
                r *= 1 + q.get("gig_rate", 0.0)
        return p, r

    def kakeibo(self):
        return sum(q.get("kakeibo", 0.0) for q in self.have_list())

    # ------------------------------------------------------------------ 画面
    @staticmethod
    def _md(d):
        return "%d/%d（%s）" % (d.month, d.day, "月火水木金土日"[d.weekday()])

    def view(self, now=None):
        now = now or time.time()
        today = datetime.fromtimestamp(now).date()
        r = self.rec()
        L = self.app.life
        out = []
        for qid, q in QUALS.items():
            a = r["apps"].get(qid) or {}
            nx = next_exam(qid, today)
            out.append({"id": qid, "label": q["label"], "icon": q["icon"], "fee": q["fee"], "desc": q["desc"], "place": q.get("place"),
                        "skills": [{"id": k, "now": round(L.skill(k), 1)} for k in q["skills"]], "need": q["need"],
                        "study": round(r["study"].get(qid, 0.0), 1), "study_need": q["study"],
                        "have": qid in r["have"], "status": a.get("status"), "exam": a.get("exam"),
                        "result_at": a.get("result_at") if a.get("status") == "taken" else None,
                        "next_exam": nx.isoformat() if nx else None,
                        "deadline": (nx - timedelta(days=DEADLINE_DAYS)).isoformat() if nx else None})
        return out

    def calendar(self, first, nxt):
        """カレンダーに出すもの: 申し込んだ試験の日と, 合否が届く日."""
        out = []
        for qid, a in self.rec()["apps"].items():
            q = QUALS.get(qid)
            if not q:
                continue
            if a["status"] == "applied":
                out.append((a["exam"], {"kind": "exam", "at": "%d:00" % EXAM_H[0], "text": "%sの試験" % q["label"]}))
            if a["status"] == "taken" and a.get("result_at"):
                out.append((datetime.fromtimestamp(a["result_at"]).date().isoformat(),
                            {"kind": "exam", "at": "", "text": "%sの合否が届く" % q["label"]}))
        return [(d, e) for d, e in out if first.isoformat() <= d < nxt.isoformat()]
