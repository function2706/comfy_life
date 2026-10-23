"""同時にできないことの確認 (一時データ, 画像生成なし).
- 一人の時間 (休む・家事・研鑽) の途中: 内職・ほかの一人の行動・誰かとすること・ミニゲームは始められない (休んでいる途中の自炊はよい)
- 内職の途中: 一人の行動・誰かとすること・ミニゲーム・自炊は始められない
- ミニゲームの途中: 内職・一人の行動・誰かとすることは始められない
- 始められない理由は, 押す前に画面に出す (state_view.blocked / side_job)
- 話しかけられて応じたら, 一人の時間はそこで終わる (結果は残る)

    python tools/test_busy.py
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


def refused(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except ValueError as e:
        return str(e)
    raise AssertionError("できてしまう: %s" % fn)


def main():
    random.seed(1)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        S, P = app.solo, app.presence
        P.rec()["beat"] = P.rec()["input"] = time.time()
        st = app.state("hina")
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": time.time() + 9e6}
        app.set_params({"mood": 70, "energy": 80, "sleepiness": 0}, "hina")
        app.items.add("rice", 5)
        app.items.add("veggies", 3)

        # ---- 1. 研鑽の途中
        S.start("practice", skill="cook")
        bl = app.state_view()["blocked"]
        assert all(bl[k] for k in ("solo", "side_job", "social", "game", "cook")) and "研鑽" in bl["solo"], bl
        assert "研鑽" in app.task_ready()["reason"]
        assert "研鑽" in refused(app.task_start, "mines", "easy")
        assert "研鑽" in refused(S.start, "out", place="park")
        assert "研鑽" in refused(S.start, "kakeibo")
        assert "研鑽" in refused(S.start, "work")
        assert "研鑽" in refused(app.act, "talk", "hina")
        assert "研鑽" in refused(app.body.cook, "rice")
        assert "研鑽" in refused(app.games.start, app.minigames[0]["id"], "hina")
        print("研鑽の途中:", bl["solo"])
        P.rec()["since"] -= 1800
        app.come_back()
        assert app.blocked("solo") is None

        # ---- 2. 休んでいる途中の自炊はよい
        S.start("rest")
        assert app.blocked("cook") is None and app.blocked("social")
        app.body.cook("rice")
        P.rec()["since"] -= 600
        app.come_back()

        # ---- 3. 内職の途中
        tk = app.task_start("mines", "easy")
        assert "内職" in refused(S.start, "rest") and "内職" in refused(app.act, "talk", "hina")
        assert "内職" in refused(app.body.cook, "rice") and app.task_ready() is None, "やりかけは続きから"
        app.task_finish(tk["token"])
        assert app.blocked("solo") is None

        # ---- 4. ミニゲームの途中
        g = next(x for x in app.minigames if x["kind"] == "connect4") if any(x["kind"] == "connect4" for x in app.minigames) else app.minigames[0]
        r = app.games.start(g["id"], "hina")
        if not r.get("refused"):
            assert "ミニゲーム" in refused(S.start, "rest") and "ミニゲーム" in app.task_ready()["reason"]
            app.games.quit("hina")
            assert app.blocked("solo") is None
            print("ミニゲームの途中: OK")

        # ---- 5. 話しかけられて応じたら, 一人の時間はそこで終わる (結果は残る)
        S.start("practice", skill="talk")
        P.rec()["since"] -= 1800
        n = len(S.mylog())
        app.force_approach("chat", "hina")
        app.answer_approach("accept", "hina")
        assert P.rec()["mode"] == "none" and len(S.mylog()) > n, P.rec()
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
