"""既読スルーまわりの確認 (一時データ, 画像生成なし):
1. 返事待ちのメッセージがあるときに相手が話したくなったら, 送ってこずにいま読んで返す (返さないと決めていても)
2. 既読のまま返さなかったあとしばらくは, 相手から気軽な話 (話そう・今日こんなことが) は来ない (とても寂しい「会いたい」は別)
3. 返事待ちに重ねて届いた分は, 最初の 1 通で決めたままにせず, 読んだときに一度だけ決め直す

    python tools/test_readignore.py
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
    random.seed(17)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("既読")
        C, B, P = app.chat, app.bonds, app.presence
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        B.set_stage(cid, "contact")
        relax = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}

        def reset():
            st.update(contacts=[], cooldowns={}, override=dict(relax), approach=None, ap_last={})
            for k in ("msg_pending", "ap_ignored_until", "ap_quiet_until", "phone_until"):
                st.pop(k, None)
            st["params"].update(mood=60, affection=55, trust=55, loneliness=30, boredom=60)
            C.save(cid, {"seen_t": 0, "items": []})

        def send_no_reply(n=1):
            for _ in range(n):
                st["cooldowns"] = {}
                st.pop("phone_until", None)
                C.send(cid, "smalltalk")
            st["msg_pending"]["reply"] = False          # 返さないと決まった
            st["msg_pending"]["unread"] = False

        def hers():
            return [it for it in C.load(cid)["items"] if it.get("who") == "her"]

        # ---- 1. 話したくなったら, 返事待ちのメッセージに返す
        reset()
        send_no_reply()
        now = time.time()
        pr = P.rec()
        pr["beat"] = pr["input"] = now
        st["ap_check"] = now - 600
        real = random.random
        random.random = lambda: 0.0                    # 抽せんに当たる
        try:
            got = P.live(char, st, now)
        finally:
            random.random = real
        assert got is None and st["msg_pending"]["reply"] and st["msg_pending"]["due"] <= now, st["msg_pending"]
        app.deliver_due(now + 1)
        assert hers() and "msg_pending" not in st, hers()
        assert not st.get("ap_ignored_until")
        print("話したくなったら, 返事待ちに返す: OK", hers()[-1]["text"])

        # ---- 2. 既読スルーのあとしばらくは, 気軽な話を送ってこない
        reset()
        send_no_reply()
        st["msg_pending"]["due"] = time.time() - 1
        app.deliver_due()
        assert not hers() and st.get("ap_ignored_until", 0) > time.time() + 3000, st.get("ap_ignored_until")
        now = time.time()
        ctx = app.context(char, st, engine.datetime.fromtimestamp(now))
        assert P.fire(char, st, now, ctx) is None, "既読スルーの直後に「話そう」は来ない"
        st["params"].update(loneliness=85, affection=60)          # とても寂しいときの「会いたい」だけは来ることがある
        ctx = app.context(char, st, engine.datetime.fromtimestamp(now))
        e = P.fire(char, st, now, ctx)
        assert e and st["approach"]["id"] == "msg_miss", st.get("approach")
        st["approach"] = None
        st["ap_ignored_until"] = now - 1                          # 時間がたてば, また来る
        st["params"].update(loneliness=30)
        st["ap_last"] = {}
        ctx = app.context(char, st, engine.datetime.fromtimestamp(now))
        assert P.fire(char, st, now, ctx), "時間がたてば, 気軽な話も来る"
        print("既読スルーのあとは気軽な話は来ない (とても寂しい「会いたい」は別)・時間がたてば来る: OK")

        # ---- 3. 重ねて届いた分は, 読んだときに決め直す (1 通だけなら決めたまま)
        def trial(n):
            reset()
            send_no_reply(n)
            st["msg_pending"]["due"] = time.time() - 1
            app.deliver_due()
            return bool(hers())
        once = sum(trial(1) for _ in range(20))
        piled = sum(trial(3) for _ in range(20))
        assert once == 0 and piled >= 12, (once, piled)
        print("重ねて届いた分は決め直す: 1 通 %d/20・3 通 %d/20 返事" % (once, piled))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
