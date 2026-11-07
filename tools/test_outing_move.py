"""相手と一緒にお出かけ中に, そのまま一緒に次の場所へ (engine.outing_move).
- 応じるかは関係 (間柄・好感度・依存度・献身度)・機嫌・性格 (話したがり) で決まり, 疲れていれば・夜遅ければ断る
- 応じれば, いまいる場所から一緒に移動して (一緒の移動), 着いたらその場所で過ごす
- 移動の途中・いまいる場所へは行けない (一時データ).

    python tools/test_outing_move.py
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
from core import engine, geo as G, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
G.INSTANT = False


def main():
    random.seed(6)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("次の場所")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "live")
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        st = app.state(cid)
        L = app.life

        def start():
            st["override"], st["cooldowns"] = None, {}
            L.player_state()["money"] = 100000
            app.set_params({"affection": 80, "mood": 75, "energy": 80, "trust": 70}, cid)
            app.act("aquarium", cid)
            ov = st["override"]
            for tr in ov.get("trips") or []:          # 着いたことに (行きの移動を過去へ)
                if tr["dir"] == "go":
                    d = tr["arr"] - time.time() + 1
                    tr["t0"] -= d
                    tr["arr"] -= d
                    for lg in tr.get("legs") or []:
                        lg["t0"] -= d
                        lg["t1"] -= d
            ov["arr"] = time.time() - 1
            assert app.geo.where() == "aquarium" and not app.outing_trip(st, time.time())

        # ---- 1. 応じる: 水族館からカフェへ一緒に移動して, カフェで過ごす
        start()
        try:
            app.outing_move("aquarium")
            raise AssertionError("いまいる場所へ行けた")
        except ValueError:
            pass
        ok = None
        for _ in range(10):
            r = app.outing_move("cafe")
            if not r.get("refused"):
                ok = r
                break
            st["cooldowns"] = {}
        assert ok, "何度誘っても応じない"
        ov = st["override"]
        assert ov["place"] == "cafe" and ov["from_action"] == "cafe", ov
        trip = app.outing_trip(st, time.time())
        assert trip and trip["from"] == "aquarium" and trip["to"] == "cafe", trip
        try:
            app.outing_move("park")
            raise AssertionError("移動の途中に次へ行けた")
        except ValueError as e:
            assert "移動の途中" in str(e)
        print("応じる: OK |", (ok.get("entry") or {}).get("text", "").split("\n")[0], "|", app.person_view(cid)["scene"]["label"])

        # ---- 2. 疲れていれば断る
        start()
        app.set_params({"energy": 10}, cid)
        r = app.outing_move("cafe")
        assert r.get("refused") and "疲れ" in r["entry"]["text"], r
        print("疲れていれば: OK |", r["entry"]["text"].split("\n")[-1])

        # ---- 3. 関係・機嫌で応じやすさが変わる
        def rate(**params):
            n = 0
            for _ in range(60):
                start()
                app.set_params(params, cid)
                r = app.outing_move("cafe")
                n += 0 if r.get("refused") else 1
            return n
        hi = rate(affection=90, mood=85, energy=80)
        lo = rate(affection=30, mood=25, energy=80)
        assert hi > lo + 10, (hi, lo)
        print("関係・機嫌: OK | 仲よく機嫌がいい %d/60・仲が浅く不機嫌 %d/60" % (hi, lo))
        app.scheduled_scene = sched
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
