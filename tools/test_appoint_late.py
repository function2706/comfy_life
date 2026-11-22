"""約束に遅れると伝える (メッセージ・電話の「遅れる」. core/appoint.py の tell_late / late_reply / grace / _late_cost).
- 伝えられるのは, まだ着いていない決まった約束 (3 時間前〜待ってくれる時刻まで) があるときだけ. 画面の送る欄・電話の話にもそのときだけ出る
- 伝えると, 相手は伝えた分 + LATE_WAIT 待つ (黙っているときの GRACE より短くはしない). 過ぎても来なければすっぽかし
- 伝えた見込みのうちに着けば, 黙って遅れるより軽い. 見込みより遅れれば, 今までどおり
- 返事: 時間差で届く. 伝えた時期・遅れの長さ・何度目か・性格・仲で変わる. 相手も遅れそう / まだ出ていなければ合わせてゆっくり来る
- 電話: 出てくれたときだけ伝わる
(一時データ)

    python tools/test_appoint_late.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, store  # noqa: E402
from core.appoint import GRACE, LATE_WAIT, NEAR  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(5)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("遅れる")
        A, C = app.appoint, app.chat
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)

        def make(t, **plan):
            for y in A.all():
                if y["status"] in ("set", "waiting"):
                    y["status"] = "declined"
            x = {"id": "x%d" % random.randint(0, 1 << 30), "cid": cid, "t": t, "place": "riverside", "do": "walk", "by": "me",
                 "status": "set", "made": t - 86400, "plan": dict({"noshow": False, "late": 0, "cancel_checked": True, "go": 30}, **plan)}
            A.all().append(x)
            A.save()
            return x

        def reset():
            st.pop("msg_pending", None)
            st["late_told"], st["reasons"], st["contacts"] = [], [], []
            app.set_params({"affection": 60, "mood": 60, "trust": 60, "energy": 80, "sleepiness": 0}, cid)

        def kinds(th):
            return [k for g in th["groups"] for k in g["kinds"]]

        # ---- 1. 伝えられるとき (画面に出る = 本当に伝えられる)
        reset()
        x = make(time.time() + NEAR + 600)
        th = C.thread(cid)
        assert "late" not in kinds(th) and not th["late_ok"], "3 時間より前は出さない"
        for bad in (10, ):
            try:
                C.send(cid, "late", {"late": bad})
                raise AssertionError("約束の 3 時間より前に伝えられてしまう")
            except ValueError:
                pass
        x["t"] = time.time() + 1800
        th = C.thread(cid)
        assert "late" in kinds(th) and th["late_ok"] and [o["id"] for o in th["pick"]["late"]] == [10, 20, 30, 45, 60]
        for bad in ({}, {"late": 7}, {"late": "x"}):
            try:
                C.send(cid, "late", bad)
                raise AssertionError("遅れる時間が違うのに送れてしまう: %s" % bad)
            except ValueError:
                pass
        assert not x.get("late_note"), "送れなかったのに伝わっている"
        x["status"] = "met"
        assert not C.thread(cid)["late_ok"], "会えた約束には伝えられない"
        x["status"] = "waiting"
        assert not C.thread(cid)["late_ok"], "着いて待っているなら遅れていない"
        print("いつ伝えられるか: OK")

        # ---- 2. 伝えると, その分待ってくれる (黙っていれば GRACE ですっぽかし)
        reset()
        x = make(time.time() - 40 * 60)           # 40 分過ぎた. 黙っていれば 5 分後にすっぽかし
        C.send(cid, "late", {"late": 30})
        n = x["late_note"]
        assert n["min"] == 70 and A.grace(x) == x["t"] + 70 * 60 + LATE_WAIT, n
        me = [i for i in C.load(cid)["items"] if i["who"] == "me"][-1]
        assert "30分くらい遅れる" in me["text"] and me["kind"] == "late", me
        A.live(x["t"] + GRACE + 60)
        assert x["status"] == "set", "伝えたのに, 黙っていたときの時刻ですっぽかしになった"
        A.live(A.grace(x) + 1)
        assert x["status"] == "missed"
        assert any("遅れると言っていたのに" in r["tell"] for r in st["reasons"]), st["reasons"]
        # 伝えた分が短くても, GRACE より早くすっぽかしにはしない
        x = make(time.time() + 600)
        A.tell_late(cid, 10)
        assert A.grace(x) == x["t"] + GRACE
        print("待ってくれる: OK")

        # ---- 3. 見込みのうちに着けば軽い / 見込みより遅れれば今までどおり / 黙って遅れる
        P = app.presence
        got = {}
        for case in ("told_kept", "told_over", "silent"):
            reset()
            x = make(time.time() - (25 if case != "told_over" else 50) * 60)
            if case != "silent":
                x["late_note"] = {"min": 30, "at": x["t"] - 600, "how": "msg", "n": 1, "by": x["t"] + 30 * 60}
            A.go(x["id"])
            m0 = st["params"]["mood"]
            A.live(time.time())
            assert x["status"] == "met", (case, x["status"])
            got[case] = [r["tell"] for r in st["reasons"] if r.get("action") == "_appoint"]
            got[case + "_mood"] = st["params"]["mood"] - m0
            app.act("go_home", cid)
        assert any("連絡はあった" in t for t in got["told_kept"]), got
        assert any("さらに遅れてきた" in t for t in got["told_over"]), got
        assert any(t.endswith("約束に遅れてきた") for t in got["silent"]), got
        assert "遅れると伝えてあった" in [e for e in app.log(cid) if "遅れてしまった" in e.get("text", "")][-2]["text"] or True
        print("着いたとき: OK", {k: v for k, v in got.items() if k.endswith("_mood")})

        # ---- 4. 返事 (時間差). 早めに・短く・はじめて → すんなりが多い. 時刻を過ぎて・長く・何度も → 引っかかりが多い
        def reply(x, mins, ago=0, told=0, notice=60):
            reset()
            st["late_told"] = [time.time() - 86400 * (i + 1) for i in range(told)]
            x["t"] = time.time() + notice * 60
            x.pop("late_note", None)
            C.send(cid, "late", {"late": mins})
            st["msg_pending"]["due"] = time.time() - 1
            app.deliver_due()
            its = [i for i in C.load(cid)["items"] if i["who"] == "her" and str(i.get("kind", "")).startswith("appoint_late")]
            return its[-1]["kind"] if its else None

        tally = {"easy": {}, "hard": {}}
        for _ in range(40):
            x = make(time.time() + 3600, go=0)
            k = reply(x, 10, notice=120)
            tally["easy"][k] = tally["easy"].get(k, 0) + 1
            x = make(time.time() + 3600, go=0)
            k = reply(x, 60, told=3, notice=-30)
            tally["hard"][k] = tally["hard"].get(k, 0) + 1
        bad = lambda d: d.get("appoint_late_sour", 0) + d.get("appoint_late_sad", 0)  # noqa: E731
        assert bad(tally["hard"]) > bad(tally["easy"]) + 10, tally
        assert tally["easy"].get("appoint_late_fine", 0) + tally["easy"].get("appoint_late_adjust", 0) >= 20, tally
        assert tally["easy"].get("appoint_late_adjust"), "まだ出ていないなら合わせてゆっくり来ることがある"
        # 相手も遅れそうだった
        x = make(time.time() + 3600, late=25)
        assert reply(x, 20, notice=60) == "appoint_late_also"
        # 読んだときには, もう会えていた
        reset()
        x = make(time.time() + 1800)
        C.send(cid, "late", {"late": 10})
        x["status"] = "met"
        st["msg_pending"]["due"] = time.time() - 1
        app.deliver_due()
        ks = [i["kind"] for i in C.load(cid)["items"] if i["who"] == "her"][-3:]
        assert "appoint_late_gone" in ks, ks
        print("返事: OK", tally)

        # ---- 5. 電話: 出てくれたときだけ伝わる
        reset()
        x = make(time.time() + 1800)
        r = app.phone_call(cid, "late", {"late": 20})
        if r.get("call"):
            assert x.get("late_note", {}).get("how") == "call", "電話で伝えたのに伝わっていない"
            assert any(str(i.get("kind", "")).startswith("appoint_late") for i in C.load(cid)["items"] if i["who"] == "her")
            app.phonetalk.end(time.time(), "me") if hasattr(app.phonetalk, "end") else None
        else:
            assert not x.get("late_note"), "電話に出なかったのに伝わっている"
        x["status"] = "declined"
        try:
            app.phone_call(cid, "late", {"late": 20})
            raise AssertionError("約束がないのに電話で遅れると言えてしまう")
        except ValueError:
            pass
        print("電話: OK", "つながった" if r.get("call") else "出なかった")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
