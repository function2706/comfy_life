"""あなたのメッセージに返していない相手は, 別の話 (離れている相手からのメッセージ) を送ってこない.
送ってきそうになったら, そのときスマホを手に取ったので, あなたのメッセージをいま読む (返すかどうかは決めていたとおり).
以前: 謝罪の返事を待たせたまま「何してるの？」が届き, そのあと送った近況への返事と一緒に, 半日前の謝罪への返事が届いていた.

    python tools/test_pending_vs_approach.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(3)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("返事待ち")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        app.set_params({"mood": 60, "affection": 70, "trust": 60, "loneliness": 90, "boredom": 80}, cid)
        app.presence.at = lambda now=None: "here"          # あなたは家にいる (働きかけが来うる)
        real = random.random

        def tick_until(cond, n=400):
            for _ in range(n):
                now = time.time()
                st["ap_check"] = now - 600
                st["ap_quiet_until"] = 0
                st["ap_last"] = {}
                random.random = lambda: 0.0                 # 働きかけの抽せんは必ず当たる
                try:
                    e = app.presence.live(char, st, now)
                finally:
                    random.random = real
                if cond(e):
                    return e
            raise AssertionError("条件にならなかった")

        # ---- 1. 返事待ちがあると, 別の話は来ず, あなたのメッセージをいま読む
        now = time.time()
        st["approach"] = None
        st["msg_pending"] = {"aid": "message", "t": now - 3600, "due": now + 5 * 3600, "reply": True, "count": 1,
                             "kind": "apology", "meta": {}}
        st["ap_check"] = now - 600
        random.random = lambda: 0.0
        try:
            e = app.presence.live(char, st, now)
        finally:
            random.random = real
        assert e is None and not st.get("approach"), "返事待ちなのに別の話が来た"
        assert st["msg_pending"]["due"] <= now, st["msg_pending"]
        out = app.deliver_due(time.time() + 1)
        assert not st.get("msg_pending")
        th = app.chat.thread(cid)["items"]
        assert out and th[-1]["who"] == "her", th[-3:]
        print("返事待ちのあいだは別の話を送らず, いま読む: OK |", th[-1]["text"])

        # ---- 2. 返さないと決めていた (既読スルー) なら, 読むだけ. 別の話はそのあと
        now = time.time()
        st["msg_pending"] = {"aid": "message", "t": now - 600, "due": now + 3600, "reply": False, "count": 1,
                             "kind": "smalltalk", "meta": {}}
        n0 = len(app.chat.thread(cid)["items"])
        st["ap_check"] = now - 600
        random.random = lambda: 0.0
        try:
            assert app.presence.live(char, st, now) is None
        finally:
            random.random = real
        app.deliver_due(time.time() + 1)
        th = app.chat.thread(cid)["items"]
        assert not st.get("msg_pending") and len(th) == n0, "既読スルーのはずが返事が来た"
        print("既読スルーなら読むだけ: OK")

        # ---- 3. 返事待ちがなければ, これまでどおり別の話が届く
        n0 = sum(x["kind"] == "approach" for x in app.chat.thread(cid)["items"])
        e = tick_until(lambda e: e is not None)
        assert st.get("approach"), st.get("approach")
        assert sum(x["kind"] == "approach" for x in app.chat.thread(cid)["items"]) == n0 + 1
        print("返事待ちがなければ届く: OK |", e["text"])
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
