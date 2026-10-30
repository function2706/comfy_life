"""献身度・依存度・誠実さ (core/attach.py): 初めの値・動き方 (上限・帳簿・共依存)・今ある仕組みへの効き.

    python tools/test_attach.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import attach as AT, engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(21)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("関わり方")
        A = app.attach
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)

        def setv(**kw):
            r = A.rec(char, st)
            r.update(kw)
            r["day"] = {}

        # ---- 1. 初めの値: 性格の傾向と今の関係から (以前のセーブには, はじめて使うときに入る)
        st.pop("attach", None)
        char["persona_id"] = "amaenbo"
        amae = A.baseline(char, st)
        char["persona_id"] = "cool"
        cool = A.baseline(char, st)
        assert amae["dependence"] > cool["dependence"] + 20, (amae, cool)
        char["persona_id"] = "aneki"
        aneki = A.baseline(char, st)
        char["persona_id"] = "tenshin"
        assert aneki["devotion"] > A.baseline(char, st)["devotion"] + 10
        char["persona_id"] = "teinei"
        assert "attach" not in st
        ctx = app.context(char, st, datetime.now())
        assert all(k in ctx for k in AT.KEYS) and "attach" in st and A.baseline(char, st) == A.baseline(char, st)
        print("初めの値: OK | 甘えたがり %s / クール %s" % (amae, cool))

        # ---- 2. 動き方: 性格の動きやすさ × 揺らぎ. 一日に動く幅には上限
        setv(dependence=50.0)
        moved = sum(A.move(char, st, "dependence", 3.0, "テスト") for _ in range(10))
        assert 0 < moved <= AT.DAY_CAP["dependence"] + 1e-6, moved
        print("一日に動く幅の上限: OK | %.2f" % moved)

        # ---- 3. 帳簿: お互いさまなら献身度が上がり, 尽くさせてばかりだと下がる. 依存度が高いと逆に上がることも (共依存)
        def day_after(her, me, dep):
            setv(devotion=50.0, dependence=dep, ledger={"her": her, "me": me})
            A.daily(char, st, time.time())
            return A.get(char, st, "devotion") - 50.0
        assert day_after(3, 4, 50) > 0
        assert all(day_after(10, 0, 30) < 0 for _ in range(10))
        co = [day_after(10, 0, 80) for _ in range(40)]
        assert any(d > 0 for d in co) and any(d < 0 for d in co), co
        assert A.rec(char, st)["ledger"]["her"] < 10                  # 帳簿は日ごとに薄れる
        print("帳簿: OK | 共依存で上がった %d / 40" % sum(d > 0 for d in co))

        # 依存度: 会えて寂しさが紛れると上がる / 長く会わなくても平気だと下がる / 傷つけられることが続くと下がる
        setv(dependence=50.0, ledger={"her": 0, "me": 0})
        st["last_met"] = st["last_touch"] = time.time()
        app.set_params({"loneliness": 20, "mood": 60}, cid)
        A.daily(char, st, time.time())
        assert A.get(char, st, "dependence") > 50
        setv(dependence=50.0)
        st["last_met"] = st["last_touch"] = time.time() - 6 * 86400
        st["last_contact"] = time.time() - 6 * 86400
        A.daily(char, st, time.time())
        assert A.get(char, st, "dependence") < 50, A.rec(char, st)
        print("依存度の日ごとの動き: OK")

        # ---- 4. 依存度の効き: 連絡が多くても平気 / 相手から送ってくる / 嫉妬 / 黙っていなくなると堪える
        st["last_met"] = st["last_touch"] = time.time()
        setv(dependence=90.0)
        tol_hi, eag_hi, jea_hi = app.bonds.tolerance(char, cid, st), app.presence.eagerness_apart(app.context(char, st, datetime.now())), app.bonds.jealousy(char)
        pen_hi = app.silent_penalty(char, 3)["mood"]
        setv(dependence=10.0)
        tol_lo, eag_lo, jea_lo = app.bonds.tolerance(char, cid, st), app.presence.eagerness_apart(app.context(char, st, datetime.now())), app.bonds.jealousy(char)
        pen_lo = app.silent_penalty(char, 3)["mood"]
        assert tol_hi > tol_lo + 2 and eag_hi > eag_lo * 1.5 and jea_hi > jea_lo * 1.5 and pen_hi < pen_lo, \
            (tol_hi, tol_lo, eag_hi, eag_lo, jea_hi, jea_lo, pen_hi, pen_lo)
        print("依存度の効き: OK | 連絡の余裕 %.1f / %.1f・送ってくる %.2f / %.2f" % (tol_hi, tol_lo, eag_hi, eag_lo))

        # ---- 5. 献身度の効き: 払ってくれる / 予定を動かして合わせてくれる / おねだりの種類
        L = app.life
        L.her_money(st)["a"] = 10 ** 6
        L.player_state()["money"] = 10 ** 6
        char["pay_policy"] = "auto"

        def her_pays(dev, n=400):
            setv(devotion=dev)
            return sum(L.plan_payment(char, st, 2000)["payer"] == "her" for _ in range(n)) / float(n)
        ph, pl = her_pays(95), her_pays(5)
        assert ph > pl + 0.2, (ph, pl)
        print("払ってくれる: OK | 献身的 %.2f / 自分優先 %.2f" % (ph, pl))

        evs = [{"id": "m", "weight": 1, "request": {"kind": "money"}}, {"id": "t", "weight": 1, "request": {"kind": "treat"}}]
        real = app.events
        app.events = evs
        try:
            def money_share(dev, n=300):
                setv(devotion=dev)
                got = 0
                for _ in range(n):
                    st["events"], st["request"] = [], None
                    rec = L.happen(char, st, time.time(), {}, None)
                    got += rec["id"] == "m"
                return got / float(n)
            ms_lo, ms_hi = money_share(5), money_share(95)
        finally:
            app.events = real
        assert ms_lo > ms_hi + 0.4, (ms_lo, ms_hi)
        print("おねだりの種類: OK | 自分優先「貸して」%.2f / 献身的 %.2f" % (ms_lo, ms_hi))

        # 予定があっても, 献身的なら合わせてくれることがある (自分優先なら合わせない)
        from core import appoint as APm
        AP = app.appoint
        busy = {"away": True, "busy": True, "asleep": False}
        real_sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: busy
        try:
            def rearranged(dev, n=60):
                setv(devotion=dev)
                k = 0
                for i in range(n):
                    x = {"id": "x%d" % i, "cid": cid, "t": time.time() + 86400, "place": "cafe", "do": "cafe_date",
                         "by": "me", "status": "asked", "made": time.time(), "rounds": APm.COUNTER_MAX}
                    AP.all().append(x)
                    key, _, _ = AP.reply(char, st, {"appoint": x["id"]}, time.time(), {})
                    k += bool(x.get("rearranged")) and key == "appoint_yes"
                return k
            rh, rl = rearranged(100), rearranged(10)
        finally:
            app.scheduled_scene = real_sched
        assert rh > 5 and rl == 0, (rh, rl)
        print("予定を動かして合わせてくれる: OK | 献身的 %d / 60・自分優先 %d" % (rh, rl))

        # ---- 6. 誠実さ: 嫉妬 (裏切られたと感じた) で下がる
        setv(sincerity=70.0)
        other = [c for c in app.chars if c != cid] or [app.new_character("みお")["id"]]
        app.bonds.notice(char, st, other[0], time.time())
        assert A.get(char, st, "sincerity") < 70
        print("誠実さ (嫉妬で下がる): OK")

        # ---- 7. 判断の記録・書き出しに出る
        assert any(x.get("c") == "attach" for x in app.trace.read())
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
