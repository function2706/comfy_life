"""稼ぎ方 (本業の昇給・賞与, アルバイト) の確認 (一時データ, 画像生成なし).
- 本業: 月の勤務で時給が見直される (よく働けば上がることがある / 休みが多いと下がる). 6・12 月の 10 日に賞与 (勤務が少なければ出ない)
- アルバイト: 応募 (面接に落ちることも), シフトの時間にだけ行ける, シフトと重なった分だけ時給が出る
- シフトを休むと注意, 30 日で 3 回で辞めさせられる
- 画面を閉じている間: 行動パターンの「アルバイト」でシフトの分を働く
- 同じ店で働く知り合いと, 一緒のシフトになる

    python tools/test_earn.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

REAL_SCHED = engine.App.scheduled_scene
fix_noon(engine)


def ts(*a):
    return datetime(*a).timestamp()


def main():
    random.seed(3)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("稼ぐ")
        E, L = app.earn, app.life
        ps = L.player_state()

        # ---- 本業: 時給の見直し
        base = E.wage()
        assert base == int(L.econ()["work_wage_per_hour"])
        ups = downs = 0
        for i in range(200):
            c = E.career()
            c["wage"], c["reviewed"] = base, None
            c["months"] = {"2026-09": {"h": 140.0, "pay": 170000}}
            ps["skills"]["work"] = 60
            E.review(ts(2026, 10, 1, 0, 5))
            ups += c["wage"] > base
            c["wage"], c["reviewed"] = base, None
            c["months"] = {"2026-09": {"h": 12.0, "pay": 15000}}
            E.review(ts(2026, 10, 1, 0, 5))
            downs += c["wage"] < base
        print("見直し: よく働いた月に上がった %d/200・休みが多い月に下がった %d/200" % (ups, downs))
        assert 40 < ups < 160 and downs == 200
        c = E.career()
        c["wage"] = base
        # 本業の稼ぎは月ごとに記録される
        pay, h, _ = L.work_pay(ts(2026, 10, 20, 9, 0), ts(2026, 10, 20, 17, 0), record=True)
        assert c["months"]["2026-10"]["h"] >= 8 and pay > 0

        # ---- 賞与
        c["months"] = {m: {"h": 140.0, "pay": 170000} for m in ("2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11")}
        m0 = ps["money"]
        amt = E.bonus(ts(2026, 12, 10, 0, 5))
        print("賞与:", amt)
        assert amt > 50000 and ps["money"] == m0 + amt
        assert E.bonus(ts(2026, 12, 10, 3, 0)) == 0, "一度だけ"
        c["months"] = {"2027-05": {"h": 30.0, "pay": 36000}}
        assert E.bonus(ts(2027, 6, 10, 0, 5)) == 0, "勤務が少なければ出ない"

        # ---- アルバイト: 応募
        try:
            E.apply("book", [{"days": "sat", "from": "08:00", "to": "12:00"}])
            raise AssertionError("店の時間の外のシフト")
        except ValueError:
            pass
        ok = None
        for i in range(30):
            ps.pop("pt_rejected", None)
            r = E.apply("book", [{"days": "sat", "from": "10:00", "to": "14:00"}])
            if r["ok"]:
                ok = r
                break
        assert ok and E.pt()["job"] == "book", ok
        print("応募:", ok["text"])
        try:
            E.apply("cafe", [{"days": "mon", "from": "10:00", "to": "14:00"}])
            raise AssertionError("二つ目")
        except ValueError:
            pass
        # 落ちることもある
        fails = 0
        for i in range(200):
            ps["parttime"] = None
            ps.pop("pt_rejected", None)
            fails += not E.apply("cafe", [{"days": "mon", "from": "10:00", "to": "14:00"}])["ok"]
        print("面接に落ちた: %d/200" % fails)
        assert 10 < fails < 120
        ps["parttime"] = None
        ps.pop("pt_rejected", None)
        while not E.apply("book", [{"days": "sat", "from": "10:00", "to": "14:00"}])["ok"]:
            ps.pop("pt_rejected", None)
        E.pt()["since"] = ts(2026, 10, 1)

        # ---- シフトと重なった分だけ
        pay, h, gain = E.pt_pay(ts(2026, 10, 24, 9, 30), ts(2026, 10, 24, 15, 0))
        assert abs(h - 4.0) < 0.01 and 3800 <= pay <= 4800, (h, pay)
        assert E.pt()["att"]["2026-10-24"] == 4.0 and gain.get("work")
        pay2, h2, _ = E.pt_pay(ts(2026, 10, 23, 10, 0), ts(2026, 10, 23, 14, 0))
        assert pay2 == 0 and h2 == 0, "シフトの無い日は出ない"
        assert E.shift_now(ts(2026, 10, 24, 9, 40)) and not E.shift_now(ts(2026, 10, 24, 9, 0))

        # ---- 休み: 注意 → 3 回で辞めさせられる
        assert E.check_absence(ts(2026, 10, 25, 0, 5)) is None, "出た日は休みにならない"
        n1 = E.check_absence(ts(2026, 11, 1, 0, 5))
        assert "注意" in n1, n1
        E.check_absence(ts(2026, 11, 8, 0, 5))
        n3 = E.check_absence(ts(2026, 11, 15, 0, 5))
        assert "辞めさせられた" in n3 and E.pt() is None, n3

        # ---- 画面からバイトに行く (シフトの時間だけ) → 戻る
        while not E.apply("book", [{"days": "mon,tue,wed,thu,fri,sat,sun", "from": "10:00", "to": "18:00"}])["ok"]:
            ps.pop("pt_rejected", None)
        P = app.presence
        now = time.time()
        if E.shift_now(now):
            for c2 in list(app.bonds.company()):
                app.bonds.end()
            app.go_parttime()
            assert P.rec()["mode"] == "work" and P.rec()["job"] == "parttime" and P.rec()["place"] == "bookstore"
            P.rec()["since"] -= 2 * 3600
            m0 = ps["money"]
            r = app.come_back()
            assert "バイト" in r["entry"]["text"] and ps["money"] >= m0, r["entry"]["text"]
            print("バイトから:", r["entry"]["text"])
        else:
            try:
                app.go_parttime()
                raise AssertionError("シフトの時間外に行けた")
            except ValueError:
                pass

        # ---- 同じ店で働く知り合い
        cid = "hina" if "hina" in app.chars else None
        if cid:
            P.declare("work", ts(2026, 10, 24, 10, 0))
            P.rec().update(job="parttime", place="bookstore")
            app.scheduled_scene = lambda ch, dt: REAL_SCHED(app, ch, datetime(2026, 10, 24, 11, 0))
            lines = app.knowsched.at_workplace(ts(2026, 10, 24, 11, 0))
            app.scheduled_scene = REAL_SCHED.__get__(app)
            assert lines and "同じシフト" in lines[0], lines
            print("職場:", lines[0])
            P.back()

        # ---- オフライン: 行動パターンの「アルバイト」
        from core import offline
        days = {d: [{"at": "00:00", "do": "sleep"}, {"at": "09:00", "do": "parttime"}, {"at": "19:00", "do": "rest"}] for d in offline.DAY_KEYS}
        app.settings.setdefault("offline", {})["days"] = days
        app.settings["offline"]["enabled"] = True
        m0 = ps["money"]
        t1 = ts(2026, 10, 27, 20, 0)
        ps["last_tick"] = ts(2026, 10, 27, 8, 0)
        rep = app.offline.simulate(ts(2026, 10, 27, 8, 0), t1)
        pt_ent = [e for e in rep["timeline"] if e["do"] == "parttime"]
        print("オフライン:", [e["text"] for e in pt_ent])
        assert pt_ent and "円" in pt_ent[0]["text"] and ps["money"] > m0
        assert E.pt()["att"].get("2026-10-27", 0) >= 7.9

        assert "earn" in app.state_view() and app.state_view()["earn"]["parttime"]["label"]
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp + "_backup", ignore_errors=True)


if __name__ == "__main__":
    main()
