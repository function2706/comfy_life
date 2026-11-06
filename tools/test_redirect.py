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
from testclock import fix_noon, run_at  # noqa: E402

fix_noon(engine)
run_at(11)                # 時刻表の電車・バスが走っている平日の昼前 (core/transit.py)
G.INSTANT = False


def shift(app, sec):
    """移動を sec 秒前に始めたことにする (いまの時刻で途中にいるように)."""
    tr = app.geo.travel()
    tr["t0"] -= sec
    tr["arr"] -= sec
    for lg in tr.get("legs") or []:        # 経路の区間も
        lg["t0"] -= sec
        lg["t1"] -= sec


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

        # ---- 1. 電車の経路 (core/transit.py の時刻表): 歩いている → 駅で待つ → 乗っている (次の駅で降りる) → 降りて歩く
        with app.lock:
            app.solo.start("out", place="aquarium", how="transit")
        tr = dict(geo.travel())
        legs = tr.get("legs") or []
        assert tr["how"] == "transit" and legs and any(lg["kind"] == "ride" for lg in legs), tr
        mid_of = lambda lg: (lg["t0"] + lg["t1"]) / 2.0                     # noqa: E731
        walk0 = legs[0]
        ride = next(lg for lg in legs if lg["kind"] == "ride")
        last = legs[-1]
        t_pre, t_ride, t_post = mid_of(walk0), ride["t0"] + (ride["t1"] - ride["t0"]) * 0.4, mid_of(last)
        assert geo.midway(t_pre).startswith("pt:")                            # 駅へ歩いている途中
        mid = geo.midway(t_ride)
        line_seq = geo.transit.line(ride["line"])["seq"]
        assert mid in line_seq and mid != ride["from"], (mid, ride)            # 乗っていれば, 次の駅で降りる
        assert mid == "station" or app.places.label(mid) == geo.transit.net()["stations"][mid]["name"], (mid, app.places.label(mid))
        assert geo.midway(t_post).startswith("pt:")
        kinds = [k for k, _, _ in tr["segs"]]
        assert kinds[0] == "walk" and "ride" in kinds, tr["segs"]
        v = geo.view(t_ride)
        assert "→" in v["segs"][v["seg"]]["label"] and v["segs"][v["seg"]]["kind"] == "ride", v["segs"]
        print("区間:", " → ".join("%s %d分" % (t, m) for _, m, t in tr["segs"]))
        assert geo.unused_fare(tr, t_pre) == tr["fare"]
        part = geo.unused_fare(tr, t_ride)
        assert 0 < part < tr["fare"], (part, tr["fare"])
        assert geo.unused_fare(tr, t_post) == 0
        print("電車の経路: OK | 片道%d円, 乗っている途中でやめれば %d円戻る" % (tr["fare"], part))

        # ---- 2. 乗っている途中で行き先を変える: 次の駅で降りて, そこから. 乗らなかった分は戻る
        shift(app, t_ride - time.time())
        part = geo.unused_fare(geo.travel(), time.time())
        m0 = L.player_state()["money"]
        with app.lock:
            r = app.solo.move("mall")
        tr2 = geo.travel()
        assert tr2 and tr2["to"] == "mall" and tr2["from"] in line_seq, tr2
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
