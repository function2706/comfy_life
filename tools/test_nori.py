"""メッセージのやりとりのノリ (core/nori.py): 始まり方・返事で上下・疲れ・切り上げ・すぐの返信と時間差・未読スルー.

    python tools/test_nori.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, nori, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(8)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("ノリ")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}
        C = app.chat

        def params(**kw):
            app.set_params(dict({"mood": 60, "affection": 60, "trust": 55, "loneliness": 50, "boredom": 50, "stress": 10}, **kw), cid)

        # ---- 1. 始まり: 暇・寂しいほど, 仲がいいほど乗っている. 相手から送ってきたらなおさら
        def avg_base(n=200, boost=0.0, **kw):
            params(**kw)
            return sum(nori.base(app, char, st, time.time(), boost) for _ in range(n)) / n
        hi, lo = avg_base(boredom=85, loneliness=80, affection=75), avg_base(boredom=10, loneliness=10, affection=35, mood=35)
        assert hi > lo + 30, (hi, lo)
        assert avg_base(boost=15) > avg_base() + 10
        print("始まりのノリ: OK | 暇で仲よし %.0f / 退屈せず仲が浅い %.0f" % (hi, lo))

        # 相手から「何してます？」が来た: 会話が始まり, 乗っている
        params(boredom=80)
        st.pop("nori", None)
        st["approach"] = None
        app.force_approach("msg_chat", cid)
        assert nori.active(st, time.time()) and st["nori"]["v"] > 0
        print("相手から送ってきたら会話が始まる: OK | ノリ", st["nori"]["v"])

        # ---- 2. 返事で上下し, 続けると疲れる. 下がりきると相手から切り上げる (ひとことが届き, スマホを置く)
        now = time.time()
        st["nori"] = {"v": 60, "t": now, "turns": 0}
        assert nori.after_choice(app, char, st, now, "good") is False and st["nori"]["v"] > 60
        v0 = st["nori"]["v"]
        nori.after_choice(app, char, st, now, "bad")
        assert st["nori"]["v"] < v0 - 15
        closed = 0
        for _ in range(30):                        # 当たり障りなく続けても, いずれ切り上げる (盛り上がり続けない)
            if nori.after_reply(app, char, st, now, 0.0):
                closed += 1
                break
        assert closed, st["nori"]
        st["phone_until"] = now + 600
        key, text = nori.close(app, char, st, now)
        assert key.startswith("close_") and text and "nori" not in st and st["phone_until"] == 0
        print("上下・疲れ・切り上げ: OK |", key, text)

        # 切り上げのことば: 仲が浅い・機嫌が悪いなら素っ気なく
        params(affection=30)
        assert nori.close_key(app, char, st, now) == "close_cold"
        params()

        # 選んだ返事で下がりきれば, トークに切り上げのひとことが出る
        st["approach"] = None
        app.force_approach("msg_chat", cid)
        st["nori"]["v"] = 21
        r = app.answer_approach("reply", cid, "curt")
        last = C.thread(cid)["items"][-1]
        if r["entry"].get("closed"):
            assert last["kind"].startswith("close_") and st.get("phone_until", 0) == 0
        print("選んだ返事のあとの切り上げ: OK |", r["entry"]["reply"]["result"], r["entry"].get("closed"))

        # ---- 3. 30 分やりとりが無ければ, 会話は終わり
        st["nori"] = {"v": 70, "t": time.time() - nori.IDLE - 1, "turns": 3}
        assert nori.level(st, time.time()) is None
        print("30 分で会話は終わり: OK")

        # ---- 4. すぐの返信: スマホを見ている間, 乗っているほどすぐ返ってきやすい
        scene = app.scene_at(char, st, __import__("datetime").datetime.now())

        def quick_rate(v, n=400):
            hit = 0
            for _ in range(n):
                now = time.time()
                st["nori"] = {"v": v, "t": now, "turns": 1}
                st["phone_until"] = now + 600
                hit += app._still_on_phone(char, st, now, scene, {})
            return hit / float(n)
        qh, ql = quick_rate(85), quick_rate(15)
        assert qh > ql + 0.35, (qh, ql)
        print("すぐの返信: OK | 乗っている %.2f / 冷めている %.2f" % (qh, ql))

        # スマホを見ている時間も, 乗っているほど長い
        def phone_len(v, n=300):
            tot = 0.0
            for _ in range(n):
                now = time.time()
                st["nori"] = {"v": v, "t": now, "turns": 1}
                app.picked_up_phone(char, st, now)
                tot += st["phone_until"] - now
            return tot / n
        assert phone_len(90) > phone_len(10) * 1.8
        print("スマホを見ている時間: OK")

        # ---- 5. 時間差の返信: 会話の途中なら, 乗っているほど早い
        def delay(v, n=150):
            tot = 0.0
            for _ in range(n):
                st.pop("msg_pending", None)
                st["contacts"] = []
                now = time.time()
                st["nori"] = {"v": v, "t": now, "turns": 1}
                st["phone_until"] = 0
                C.send(cid, "smalltalk")
                tot += st["msg_pending"]["due"] - now
            return tot / n
        params()
        dh, dl = delay(90), delay(10)
        assert dl > dh * 1.5, (dh, dl)
        print("時間差の返信: OK | 乗っている %.0f 分 / 冷めている %.0f 分" % (dh / 60, dl / 60))

        # ---- 6. 未読スルー: 嫌われていて返さないときは, 読みもしないことがある (既読はずっとあと)
        params(affection=15, mood=40)
        unread = 0
        for _ in range(60):
            st.pop("msg_pending", None)
            st.pop("nori", None)
            st["contacts"] = []
            C.send(cid, "smalltalk")
            pend = st["msg_pending"]
            unread += bool(pend.get("unread"))
            assert not (pend.get("unread") and pend.get("reply"))
        assert unread > 5, unread
        st.pop("msg_pending", None)
        C.send(cid, "smalltalk")
        st["msg_pending"].update(reply=False, unread=True, due=time.time() - 1)
        app.deliver_due()
        mine = [x for x in C.thread(cid)["items"] if x["who"] == "me"][-1]
        assert not mine.get("read_t") and st["msg_pending"]["due"] > time.time() + 2.5 * 3600
        app.deliver_due(st["msg_pending"]["due"] + 1)
        mine = [x for x in C.thread(cid)["items"] if x["who"] == "me"][-1]
        assert mine.get("read_t") and not st.get("msg_pending")
        print("未読スルー: OK | 60 通中 %d 通は読まれない (既読はずっとあと)" % unread)

        # 仲がよければ未読スルーはしない
        params(affection=60)
        for _ in range(40):
            st.pop("msg_pending", None)
            st["contacts"] = []
            C.send(cid, "smalltalk")
            assert not st["msg_pending"].get("unread")
        print("仲がよければ未読スルーしない: OK")

        # ---- 7. 以前のセーブ (ノリの記録なし) でもこれまでどおり
        st.pop("nori", None)
        assert nori.level(st, time.time()) is None and nori.after_reply(app, char, st, time.time(), 0.0) is False
        print("以前のセーブ: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
