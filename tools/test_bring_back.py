"""出先に置いてある自転車・車で帰る (geo._best の carry) と, 帰る行き方を選ぶ (come_back の how) (一時データ).

- 自転車を取りに行った店から「帰る」(おまかせ): 自転車に乗って帰る (歩いて帰って, 自転車を置いたままにしない)
- 帰る行き方を選べる (歩いて帰る を選べば歩く. 自転車は店に残る)
- 家から出るときのおまかせは, これまでどおり (近ければ歩く)

    python tools/test_bring_back.py
"""
import os
import random
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, geo as G, store  # noqa: E402
from testclock import fix_noon, run_at  # noqa: E402

fix_noon(engine)
run_at(11)
G.INSTANT = False


def main():
    random.seed(3)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("自転車")
        geo, P = app.geo, app.presence
        app.life.player_state()["stamina"] = 100
        app.items.add("bicycle", 1)
        home = "home:me"

        # 家から: 近ければ歩く (これまでどおり)
        o = geo.options(home, "supermarket")
        assert o["best"] == "walk" or o["walk"]["min"] > 15, o["best"]

        def at_shop():
            P.rec().pop("travel", None)
            with app.lock:
                app.solo.start("out", place="supermarket", how="walk")
            tr = geo.travel()
            with app.lock:
                geo.tick(tr["arr"] + 1)
            geo.rec().setdefault("veh", {})["bicycle"] = "supermarket"      # 店に置いてあった自転車を取りに来た
            assert geo.where() == "supermarket"

        # ---- 1. おまかせで帰る: 自転車に乗って
        at_shop()
        assert geo.options("supermarket", home)["best"] == "bike"
        with app.lock:
            r = app.come_back()
        tr = geo.travel()
        assert r.get("traveling") and tr["how"] == "bike", (r, tr)
        with app.lock:
            geo.tick(tr["arr"] + 1)
        assert geo.veh_at("bicycle") == home
        print("おまかせで帰る: OK |", r["text"])

        # ---- 2. 帰る行き方を選ぶ: 歩いて帰れば, 自転車は店に残る
        at_shop()
        with app.lock:
            r = app.come_back(how="walk")
        tr = geo.travel()
        assert tr["how"] == "walk", tr
        with app.lock:
            geo.tick(tr["arr"] + 1)
        assert geo.veh_at("bicycle") == "supermarket"
        print("歩いて帰るを選ぶ: OK |", r["text"])
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
