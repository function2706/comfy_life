"""向こうからのメッセージへの返事に, 相手が返してくるまでの時間差 (1.6.0).
以前は, 返事を選んだ瞬間に相手の返しが届いていた (時間を置いて返しても, すぐ).
- 返事を出した時点では, 相手の返しはまだ来ない (返事待ち. 既読も届いたとき)
- 届く時刻が来れば届く (受け取り方と返しは, そのとき決まる)
- 相手は送ったあとしばらくスマホを見ているので, すぐ返せば早い. 時間を置いて (スマホを置いたあと) 返すと, 遅いことが多い
- 寝ている・手が離せない間は, そのあと
(一時データ)

    python tools/test_ap_reply_delay.py
"""
import os
import random
import shutil
import statistics
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(4)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("返事の時間差")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        sched = app.scheduled_scene
        free = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)      # noqa: E731
        app.scheduled_scene = free
        C = app.chat

        def fire():
            st["approach"], st["ap_quiet_until"], st["ap_last"], st["msg_pending"] = None, 0, {}, None
            app.set_params({"affection": 70, "mood": 65, "loneliness": 40, "boredom": 60}, cid)
            assert app.force_approach("msg_chat", cid)

        # ---- 1. 返事を出した時点では来ない. 届く時刻に届く
        fire()
        n0 = len(C.load(cid)["items"])
        r = app.answer_approach("reply", cid, "expand")
        items = C.load(cid)["items"][n0:]
        assert r["entry"].get("sent") and [x["who"] for x in items] == ["me"], items
        pend = st["msg_pending"]
        assert pend["kind"] == "ap_reply" and pend["due"] > time.time(), pend
        out = app.deliver_due(pend["due"] + 1)
        items = C.load(cid)["items"][n0:]
        assert out and items[-1]["who"] == "her" and items[-1]["t"] >= pend["due"] - 1, (out, items[-1])
        assert not st.get("msg_pending")
        print("届くまで待つ: OK | %.0f 秒後に「%s」" % (pend["due"] - pend["t"], items[-1]["text"][:30]))

        # ---- 2. すぐ返す (スマホを見ている間) / 時間を置いて返す (スマホを置いたあと)
        def delays(wait, n=60):
            ds = []
            for _ in range(n):
                fire()
                if wait:
                    st["phone_until"] = 0          # 時間を置いた: もうスマホを置いている
                app.answer_approach("reply", cid, "cheerful")
                ds.append(st["msg_pending"]["due"] - st["msg_pending"]["t"])
            return ds
        quick, late = delays(False), delays(True)
        mq, ml = statistics.median(quick), statistics.median(late)
        assert mq < 120 and ml > mq * 3, (mq, ml)
        print("早さ: OK | すぐ返したとき 中央値 %.0f 秒 / 時間を置いたとき 中央値 %.0f 秒" % (mq, ml))

        # ---- 3. 寝ている間は届かない (起きてから)
        fire()
        app.answer_approach("reply", cid, "cheerful")
        due = st["msg_pending"]["due"]
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=True)
        assert not app.deliver_due(due + 1) and st["msg_pending"]["due"] > due + 1
        app.scheduled_scene = free
        assert app.deliver_due(st["msg_pending"]["due"] + 1)
        print("寝ている間: OK | 起きてから届いた")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK")


if __name__ == "__main__":
    main()
