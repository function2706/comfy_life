"""移動の途中で行き先を変える (core/geo.py の phase・midway・cut / core/solo.py の move) と, 仕事から寄り道.

- 電車・バス: 駅へ歩く・待つ間はまだ出たところ (運賃は戻る) / 乗っていれば次の駅で降りる (乗った区間だけ払う) / 降りたあとは行き先のそば.
- 職場へ向かう途中に行き先を変える: 仕事には行かず (給料なし), いまの地点からそちらへ.
- 職場で働いたあと: 仕事を終えて (働いた時間ぶん), 家に寄らずにそちらへ. 帰る途中でも同じ.
- 押せない理由 (engine.cond_why) の文.

    python tools/test_redirect.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from core import engine, geo as G, places as PL, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
G.INSTANT = False


def shift(app, sec):
    """移動を sec 秒前に始めたことにする (いまの時刻で途中にいるように)."""
    tr = app.geo.travel()
    tr["t0"] -= sec
    tr["arr"] -= sec


def main():
    random.seed(7)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("寄り道")
        geo, L, P = app.geo, app.life, app.presence
        L.player_state()["stamina"] = 100
        L.player_state()["money"] = 50000
        geo.ensure()
        home = PL.HOME_ME

        # ---- 1. 電車の段階: 乗る前 → 乗っている (途中の駅) → 降りたあと
        now = time.time()
        with app.lock:
            app.solo.start("out", place="aquarium", how="transit")
        tr = dict(geo.travel())
        assert tr["how"] == "transit" and tr.get("ph"), tr
        pre, ride, post = tr["ph"]
        tot = (tr["arr"] - tr["t0"]) / 60.0
        k = tot / (pre + ride + post)
        t_pre = tr["t0"] + pre * k * 60 * 0.5
        t_ride = tr["t0"] + (pre + ride * 0.5) * k * 60
        t_post = tr["arr"] - post * k * 60 * 0.3
        assert geo.phase(t_pre)[0] == "pre" and geo.midway(t_pre) == home
        assert geo.phase(t_ride)[0] == "ride"
        mid = geo.midway(t_ride)
        assert mid.startswith("pt:") and mid.count(",") == 2 and app.places.label(mid) == "途中の駅", mid
        assert geo.phase(t_post)[0] == "post" and geo.midway(t_post) == "aquarium"
        assert geo.unused_fare(tr, t_pre) == tr["fare"]
        part = geo.unused_fare(tr, t_ride)
        assert 0 < part < tr["fare"], (part, tr["fare"])
        assert geo.unused_fare(tr, t_post) == 0
        # 途中の駅からの行き方: 駅にいるので, 電車ならすぐ乗れる (歩く分が小さい)
        assert geo.pt(mid)["acc"] == 0.05 and geo.pt(mid.rsplit(",", 1)[0])["acc"] == 0.3
        print("電車の段階: OK | 片道%d円, 乗っている途中でやめれば %d円戻る" % (tr["fare"], part))

        # ---- 2. 乗っている途中で行き先を変える: 次の駅で降りて, そこから. 乗らなかった分は戻る
        shift(app, t_ride - tr["t0"])
        m0 = L.player_state()["money"]
        with app.lock:
            r = app.solo.move("mall")
        tr2 = geo.travel()
        assert tr2 and tr2["to"] == "mall" and tr2["from"].count(",") == 2, tr2
        assert "払わずに済んだ" in (r.get("done") or ""), r
        assert L.player_state()["money"] - m0 == part - tr2["fare"], (L.player_state()["money"] - m0, part, tr2["fare"])
        assert P.rec()["mode"] == "out" and P.rec()["place"] == "mall"
        print("乗っている途中で:", r["done"])

        # 片付け: 家に戻す
        P.rec().pop("travel", None)
        with app.lock:
            P.back(time.time())
        P.rec()["pos"] = home

        # ---- 3. 職場へ向かう途中で行き先を変える: 仕事には行かない (給料なし)
        with app.lock:
            app.solo.start("work")
        tr = geo.travel()
        assert tr and tr["to"] == "office" and P.rec()["mode"] == "work", tr
        shift(app, (tr["arr"] - tr["t0"]) * 0.4)
        m0 = L.player_state()["money"]
        with app.lock:
            r = app.solo.move("park")
        assert P.rec()["mode"] == "out" and geo.travel()["to"] == "park", P.rec()
        assert "仕事に行くのをやめた" in r["solo"]["text"], r["solo"]
        assert L.player_state()["money"] - m0 <= geo.last_refund   # 給料は出ない (運賃が戻るだけ)
        print("通勤の途中で:", r["solo"]["text"], "/", r["done"])
        P.rec().pop("travel", None)
        with app.lock:
            P.back(time.time())
        P.rec()["pos"] = home

        # ---- 4. 職場で 3 時間働いてから: 仕事を終えて, 家に寄らずにそちらへ
        with app.lock:
            app.solo.start("work")
        tr = geo.travel()
        shift(app, (tr["arr"] - tr["t0"]) + 3 * 3600)
        with app.lock:
            geo.tick(time.time())
        assert geo.where() == "office" and P.rec().get("arrived"), P.rec()
        m0 = L.player_state()["money"]
        with app.lock:
            r = app.solo.move("supermarket")
        txt = r["solo"]["text"]
        assert txt.startswith("仕事を終えた（") and "帰った" not in txt, txt
        assert geo.travel()["from"] == "office" and geo.travel()["to"] == "supermarket"
        assert L.player_state()["money"] > m0, "給料が入っていない"
        print("職場から:", txt, "/", r["done"])
        P.rec().pop("travel", None)
        with app.lock:
            P.back(time.time())
        P.rec()["pos"] = home

        # ---- 5. 仕事を終えて帰る途中で: 働いた分はもらって, そちらへ
        with app.lock:
            app.solo.start("work")
        tr = geo.travel()
        shift(app, (tr["arr"] - tr["t0"]) + 2 * 3600)
        with app.lock:
            geo.tick(time.time())
            app.come_back()                       # 家へ向かう (仕事中のまま)
        trh = geo.travel()
        assert trh and trh["dir"] == "home" and P.rec()["mode"] == "work", trh
        shift(app, (trh["arr"] - trh["t0"]) * 0.5)
        m0 = L.player_state()["money"]
        with app.lock:
            r = app.solo.move("convenience")
        assert r["solo"]["text"].startswith("仕事を終えた（"), r["solo"]
        assert L.player_state()["money"] > m0 - 2000
        assert geo.travel()["to"] == "convenience" and P.rec()["mode"] == "out"
        print("帰る途中で:", r["solo"]["text"])
        P.rec().pop("travel", None)
        with app.lock:
            P.back(time.time())
        P.rec()["pos"] = home

        # ---- 6. 家で仕事モードでなければ, 寄り道はできない (外出していない)
        try:
            app.solo.move("park")
            raise AssertionError("家から move できてしまった")
        except ValueError as e:
            assert "出かけていません" in str(e)

        # ---- 7. 押せない理由の文
        ctx = {"phase": "noon", "hour": 23, "affection": 10, "my_stamina": 5, "mood": 80, "free": False, "asleep": True}
        assert app.cond_why("phase=night|midnight", ctx) == "夜・深夜にできることです"
        assert app.cond_why("phase!=noon", ctx) == "昼はできません"
        assert app.cond_why("hour<21", ctx) == "21時を過ぎたらできません"
        assert app.cond_why("affection>=50", ctx) == "まだそこまでの仲ではありません"
        assert app.cond_why("my_stamina>=20", ctx) == "あなたの体力が足りません"
        assert app.cond_why("free=true", ctx) is None                  # 見れば分かる (相手の様子)
        assert app.cond_why("asleep=false", ctx) is None
        print("押せない理由: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
