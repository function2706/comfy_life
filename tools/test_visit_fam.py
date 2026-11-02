"""家に上がる慣れ (core/visit.py の home_fam): 上がるたびに増え (増えるほど増えにくい), 間が空くと薄れ, 断られると減る.
慣れているほど約束なしに訪ねても迎えてもらいやすい. 一度も上がったことがなければ, かなり迎えてもらいにくい.
慣れていても断られることは残る. 以前のセーブは一度上がったことにする (一時データ, 画像生成なし).

    python tools/test_visit_fam.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, visit as VI  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(5)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("慣れ")
        B, V = app.bonds, app.athome
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        now = time.time()

        # ---- 以前のセーブ: 慣れを入れる前から家に行ける仲なら, 一度上がったことにする
        B.set_stage(cid, "visit", now - 30 * 86400)
        st.pop("home_fam", None)
        v, n = V.fam(cid, st, now)
        assert n == 1 and 0.15 < v <= 0.2, (v, n)
        # 入れたあとに家に行ける仲になった: まだ上がったことがない
        VI.FAM_SINCE = now - 86400
        B.set_stage(cid, "contact", now)
        B.set_stage(cid, "visit", now)
        st.pop("home_fam", None)
        assert V.fam(cid, st, now) == (0.0, 0)
        print("以前のセーブ / 新しく家に行ける仲: OK")

        # ---- 上がるたびに増える (増えるほど増えにくい). 間が空くと薄れる. 断られると減る (夜は余計に)
        gains = []
        for i in range(6):
            v0 = V.fam(cid, st, now)[0]
            B.start(cid, "visit", now)
            B.end(go_home=False)
            gains.append(V.fam(cid, st, now)[0] - v0)
        v6, n6 = V.fam(cid, st, now)
        assert n6 == 6 and gains[0] > gains[-1] > 0 and v6 < 1, gains
        half = V.fam(cid, st, now + VI.FAM_HALF_DAYS * 86400)[0]
        assert abs(half - v6 / 2) < 0.01, (half, v6)
        V.refused(cid, False, now)
        v7 = V.fam(cid, st, now)[0]
        V.refused(cid, True, now)
        v8 = V.fam(cid, st, now)[0]
        assert v6 - v7 > 0.1 and v7 - v8 > v6 - v7, (v6, v7, v8)
        ctx = app.context(char, st, app.now_dt() if hasattr(app, "now_dt") else __import__("datetime").datetime.now())
        assert "home_fam" in ctx and ctx["home_visits"] == 6
        print("増え方 %s / 30日で %.2f→%.2f / 断られる %.2f→%.2f→%.2f(夜)" % (["%.2f" % g for g in gains], v6, half, v6, v7, v8))

        # ---- 約束なしに訪ねる: 慣れているほど迎えてもらいやすい. 一度も上がったことがなければ, かなり迎えてもらいにくい
        def rate(fam, n=150):
            ok = 0
            for _ in range(n):
                st["params"].update(affection=62, trust=58, mood=55, energy=80, health=90)
                st["home_fam"] = dict(fam, t=time.time())
                st["override"] = None
                app.presence.declare("none", time.time())
                r = app.drop_in(cid)
                ok += r["started"] == "visit"
                if B.with_rec():
                    B.end(go_home=False)
                app.presence.declare("none", time.time())
            return ok / float(n)
        first, some, used = rate({"v": 0.0, "n": 0}), rate({"v": 0.2, "n": 1}), rate({"v": 0.8, "n": 8})
        print("迎えてもらえた: 初めて %.2f / 一度 %.2f / 慣れている %.2f" % (first, some, used))
        assert first + 0.15 < some < used and used < 0.98, (first, some, used)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
