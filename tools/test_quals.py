"""資格 (core/quals.py): 試験日と締め切り・申し込み (受験料)・勉強・受かりやすさ・試験の日 (欠席)・合否 (2 週間後)・
本業 (手当・見直し・上限)・アルバイト・副業・家計簿・カレンダー・話題.

    python tools/test_quals.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, quals as QM, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(61)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("資格")
        Q, L = app.quals, app.life
        ps = L.player_state()

        # ---- 1. 試験日は第 2 日曜. 締め切り (30 日前) を過ぎたら次の回
        d = QM.exam_day(2027, 6)
        assert d.weekday() == 6 and 8 <= d.day <= 14
        assert QM.next_exam("biz", d - timedelta(days=31)) == d
        assert QM.next_exam("biz", d - timedelta(days=29)) > d
        print("試験日と締め切り: OK |", d)

        # ---- 2. 申し込み: 受験料を払う (家計簿にも). 二度は申し込めない. お金が足りなければ申し込めない
        ps["money"] = 100000
        a = Q.apply("boki")
        assert ps["money"] == 95000 and a["status"] == "applied"
        try:
            Q.apply("boki")
            raise AssertionError("二度申し込めた")
        except ValueError:
            pass
        ps["money"] = 100
        try:
            Q.apply("cook")
            raise AssertionError("お金が足りないのに申し込めた")
        except ValueError:
            pass
        ps["money"] = 100000
        print("申し込み: OK")

        # ---- 3. 勉強 (研鑽の「資格の勉強」): 勉強時間がたまり, 要るスキルも少し伸びる
        sk0 = L.skill("budget")
        app.solo.result("practice", 3.0, time.time(), skill="qual:boki")
        assert Q.rec()["study"]["boki"] > 1.5 and L.skill("budget") > sk0
        try:
            app.solo.start("practice", skill="qual:nope")
            raise AssertionError("無い資格を勉強できた")
        except ValueError:
            pass
        print("勉強: OK | 勉強時間 %.1f" % Q.rec()["study"]["boki"])

        # ---- 4. 受かりやすさ: スキルと勉強が目安に届くほど. 届いていても 1〜2 割は落ち, 届いていなくてもまれに受かる
        sk = ps.setdefault("skills", {})
        sk["budget"], sk["work"] = 45.0, 45.0
        Q.rec()["study"]["boki"] = 40.0
        ps["stamina"] = 100
        hi = Q.pass_chance("boki")
        sk["budget"], sk["work"] = 15.0, 15.0
        Q.rec()["study"]["boki"] = 5.0
        lo = Q.pass_chance("boki")
        assert 0.75 <= hi <= 0.92 and lo < 0.1, (hi, lo)
        print("受かりやすさ: OK | 届いている %.2f / 届いていない %.2f" % (hi, lo))

        # ---- 5. 試験の日に受け, 2 週間後に合否が届く. 受かれば持っている資格に, 話題にも
        sk["budget"], sk["work"] = 60.0, 60.0
        Q.rec()["study"]["boki"] = 50.0
        exam = date.fromisoformat(Q.rec()["apps"]["boki"]["exam"])
        t_exam = datetime(exam.year, exam.month, exam.day, 0, 5).timestamp()
        real = random.random
        random.random = lambda: 0.0                      # 受かる
        try:
            Q.daily(t_exam)
        finally:
            random.random = real
        a = Q.rec()["apps"]["boki"]
        assert a["status"] == "taken" and a["ok"]
        Q.daily(t_exam + 13 * 86400)
        assert a["status"] == "taken"
        Q.daily(t_exam + 15 * 86400)
        assert a["status"] == "pass" and Q.has("boki") and any("簿記検定に受かった話" == x["text"] for x in app.topics.all(t_exam + 15 * 86400))
        print("試験と合否: OK")

        # 落ちれば勉強時間の 3 割を持ち越す. 寝込んでいれば欠席 (受験料は戻らない)
        Q.apply("write")
        Q.rec()["study"]["write"] = 20.0
        ex = date.fromisoformat(Q.rec()["apps"]["write"]["exam"])
        te = datetime(ex.year, ex.month, ex.day, 0, 5).timestamp()
        random.random = lambda: 0.999                    # 落ちる
        try:
            Q.daily(te)
        finally:
            random.random = real
        Q.daily(te + 15 * 86400)
        assert Q.rec()["apps"]["write"]["status"] == "fail" and abs(Q.rec()["study"]["write"] - 6.0) < 0.01
        Q.apply("house")
        ex = date.fromisoformat(Q.rec()["apps"]["house"]["exam"])
        lv = app.body.level
        app.body.level = lambda: 3
        try:
            Q.daily(datetime(ex.year, ex.month, ex.day, 0, 5).timestamp())
        finally:
            app.body.level = lv
        assert Q.rec()["apps"]["house"]["status"] == "absent" and not Q.has("house")
        print("不合格・欠席: OK")

        # ---- 6. 効き目: 本業 (手当・見直しで上がりやすい・上限) / アルバイト / 副業 / 家計簿
        Q.rec()["have"]["biz"] = time.time()
        assert Q.allowance() == 8000 and abs(Q.raise_bonus() - 0.2) < 1e-9 and Q.wage_cap() == 2.3
        E = app.earn
        c = E.career()
        prev = (datetime.now().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        c["months"][prev] = {"h": 120.0, "pay": 150000}
        c.pop("reviewed", None)
        m0 = ps["money"]
        E.review(time.time())
        assert ps["money"] == m0 + 8000, (ps["money"], m0)
        print("本業: OK | 手当 %d円・上限 %.1f 倍" % (Q.allowance(), Q.wage_cap()))
        Q.rec()["have"]["service"] = time.time()
        Q.rec()["have"]["cook"] = time.time()
        assert Q.job_wage("family") == 100 and Q.job_wage("conv") == 50 and Q.job_pass("cafe") == 0.15 and Q.job_pass("super") == 0
        assert Q.gig("cook") == (1.2, 1.2) and Q.gig("write") == (1.0, 1.0)
        assert Q.kakeibo() == 0.25
        print("アルバイト・副業・家計簿: OK")

        # ---- 7. 画面とカレンダー
        v = Q.view()
        assert {x["id"] for x in v} == set(QM.QUALS) and next(x for x in v if x["id"] == "boki")["have"]
        Q.rec()["apps"]["write"] = {"exam": (date.today() + timedelta(days=40)).isoformat(), "status": "applied", "fee": 5000, "t": time.time()}
        ex = date.fromisoformat(Q.rec()["apps"]["write"]["exam"])
        cal = app.calview.month(ex.year, ex.month)
        assert any(e["kind"] == "exam" for e in cal["days"].get(ex.isoformat(), []))
        print("画面・カレンダー: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
