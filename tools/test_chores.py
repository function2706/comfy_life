"""家事 (core/home.py の選べる家事・天気・ゴミの日) と, 同居相手との分担 (core/chores.py): 分担を話す・相手の担当・
さぼりへの出方 (見逃す・お願い・たしなめる・冗談)・あなたの担当がたまったとき・帳簿・カレンダー.

    python tools/test_chores.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import chores as CH, engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(71)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("家事")
        H, C = app.home, app.chores
        r = H.rec()

        def fill(**kw):
            for k in ("mess", "dishes", "laundry", "trash"):
                r[k] = float(kw.get(k, 10.0))

        # ---- 1. ゴミの日: ワールドごとに週 2 日 (3 日あけて). その日の朝 5:00〜8:30 だけ出せる
        days = H.trash_days()
        assert len(days) == 2 and days[1] - days[0] == 3 and H.trash_days() == days
        d0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        tday = d0 + timedelta(days=(days[0] - d0.weekday()) % 7)
        other = tday + timedelta(days=1)
        assert H.trash_ok((tday + timedelta(hours=7)).timestamp()) and not H.trash_ok((tday + timedelta(hours=9)).timestamp())
        assert not H.trash_ok((other + timedelta(hours=7)).timestamp())
        print("ゴミの日: OK |", H.view()["trash_days"])

        # ---- 2. 一人の家事: 一つだけ選べばそこだけ. 洗濯は雨なら部屋干し (減りが少ない). ゴミはゴミの日の朝でなければまとめるだけ
        wet = H.wet
        H.wet = lambda now=None: False
        try:
            fill(mess=80, dishes=80, laundry=80, trash=80)
            H.chores(1.0, True, 1.0, "dishes", (tday + timedelta(hours=12)).timestamp())
            assert r["dishes"] < 30 and r["mess"] == 80 and r["laundry"] == 80
            fill(laundry=80)
            H.clean(60, ["laundry"])
            dry = r["laundry"]
            H.wet = lambda now=None: True
            fill(laundry=80)
            _, _, notes = H.clean(60, ["laundry"])
            assert r["laundry"] > dry + 15 and any("部屋干し" in n for n in notes)
            fill(trash=80)
            H.clean(60, ["trash"], (tday + timedelta(hours=7)).timestamp())
            ok_day = r["trash"]
            fill(trash=80)
            _, _, notes = H.clean(60, ["trash"], (other + timedelta(hours=7)).timestamp())
            assert r["trash"] > ok_day + 30 and any("ゴミの日" in n for n in notes)
        finally:
            H.wet = wet
        out = app.solo.result("chores", 1.0, time.time(), skill="mess")
        assert "部屋の散らかり" in out["text"]
        try:
            app.solo.start("chores", skill="nope")
            raise AssertionError("無い家事を選べた")
        except ValueError:
            pass
        print("一人の家事: OK |", out["text"])

        # ---- 3. 分担: 一緒に暮らしている相手と, そばで. 相手の担当にするかは相手しだい (献身度・きれい好き・機嫌・さぼり癖)
        cid = app.settings["active_character"]
        try:
            C.set_share("dishes", "her")
            raise AssertionError("同居していないのに分担を話せた")
        except ValueError:
            pass
        app.bonds.set_stage(cid, "live")
        char, st = app.char(cid), app.state(cid)
        assert app.bonds.together(cid), "同居相手が家にいない"
        A = app.attach

        def accept(dev, n=60):
            ok = 0
            for _ in range(n):
                A.rec(char, st)["devotion"] = dev
                st["chores_share"] = {}
                st["slack"] = 0.0
                ok += C.set_share("dishes", "her")["ok"]
            return ok / float(n)
        hi, lo = accept(95.0), accept(5.0)
        assert hi > lo + 0.3, (hi, lo)
        assert C.set_share("mess", "me")["ok"] and C.share(st)["mess"] == "me"
        print("分担を話す: OK | 引き受けた 献身的 %.2f / 自分優先 %.2f" % (hi, lo))

        # ---- 4. 相手の担当: 決めた時刻にやるかどうか. やれば帳簿に「相手が尽くした」
        def her_does(dev, slack=0.0, n=60):
            done = 0
            for _ in range(n):
                A.rec(char, st)["devotion"] = dev
                st["slack"] = slack
                st["chores_share"] = {"dishes": "her", "mess": "either", "laundry": "either", "trash": "either"}
                fill(dishes=50)
                st["chores_plan"] = [{"part": "dishes", "at": time.time() - 1}]
                st["chores_seen_day"] = datetime.now().date().isoformat()
                C.tick(char, st, time.time())
                done += r["dishes"] < 50
            return done / float(n)
        d_hi, d_lo, d_slack = her_does(95.0), her_does(5.0), her_does(95.0, 0.9)
        assert d_hi > d_lo + 0.3 and d_hi > d_slack + 0.3, (d_hi, d_lo, d_slack)
        C.daily(char, st, time.time())
        assert [x["part"] for x in st["chores_plan"]] == ["dishes"]
        print("相手の担当: OK | やった 献身的 %.2f / 自分優先 %.2f / さぼり癖 %.2f" % (d_hi, d_lo, d_slack))

        # ---- 5. さぼりの知らせ (相手の担当がたまっていて二人とも家に) と, あなたの出方
        def slack_now():
            fill(dishes=80, mess=10)
            st.pop("chores_slack", None)
            st.pop("chores_asked", None)
            st.pop("chores_seen_day", None)
            st["chores_plan"] = []
            st["chores_share"] = {"dishes": "her", "mess": "either", "laundry": "either", "trash": "either"}
            C.tick(char, st, time.time())
            assert C.pending() and C.pending()["part"] == "dishes"
        slack_now()
        s0, sta0 = float(st.get("slack", 0)), app.life.player_state()["stamina"]
        C.respond("overlook")
        assert r["dishes"] < 80 and st["slack"] > s0 and not C.pending()
        print("見逃して自分でやる: OK | さぼり癖 %.2f → %.2f" % (s0, st["slack"]))
        keys = {}
        for ch in ("ask", "scold", "joke"):
            for _ in range(30):
                slack_now()
                k = C.respond(ch)["key"]
                keys.setdefault(ch, set()).add(k)
        assert keys["ask"] >= {"ask_yes"} and keys["scold"] == {"scold_ok", "scold_back"} and "joke_ok" in keys["joke"] or "joke_bad" in keys["joke"], keys
        assert any(x.get("action") == "_chores_scold" for x in st.get("reasons") or []) and st.get("chores_fight")
        try:
            C.respond("ask")
            raise AssertionError("知らせが無いのに答えられた")
        except ValueError:
            pass
        print("出方: OK |", {k: sorted(v) for k, v in keys.items()})

        # ---- 6. あなたの担当がたまっていると, 代わりにやるか責めるか
        seen = set()
        for _ in range(40):
            fill(mess=90)
            st.pop("chores_seen_day", None)
            st.pop("chores_slack", None)
            st["chores_share"] = {"mess": "me", "dishes": "either", "laundry": "either", "trash": "either"}
            n0 = len(app.log(cid))
            C.tick(char, st, time.time())
            seen |= {e.get("chores") for e in app.log(cid)[n0:]}
        assert {"cover", "complain"} <= seen, seen
        print("あなたの担当がたまる: OK")

        # ---- 7. 帳簿: 相手の担当を片付けたら, あなたが尽くした側
        st["chores_share"] = {"dishes": "her", "mess": "me", "laundry": "either", "trash": "either"}
        led = A.rec(char, st)["ledger"]["me"]
        C.did_mine("dishes", 1.0, time.time())
        assert A.rec(char, st)["ledger"]["me"] > led
        print("帳簿: OK")

        # ---- 8. カレンダーにゴミの日
        cal = app.calview.month(tday.year, tday.month)
        assert any(e["kind"] == "trash" for e in cal["days"].get(tday.date().isoformat(), []))
        assert C.view()["share"][0]["id"] == "mess"
        print("カレンダー・画面: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
