"""誰かと一緒にいる間の, あなたの体力 (1.6.0).
以前はデート中も「相手のそばにいる」扱いで, 家でくつろいでいるのと同じく 1 時間に 5 ずつ回復していた.
- 一緒に出かけた先で過ごしている間は回復せず, 一人で同じところにいるのと同じだけ疲れる
  (散歩・見て回る 2 × 場所の疲れやすさ / 買い物 2 / 食事 1 / カフェ 0.5. 1 時間あたり)
- 一緒の移動は, 一人の移動と同じだけ疲れる (行きも帰りも). 移動の間も回復しない
- 相手の家にいる / 相手を招いている間は, 回復が遅い (1 時間に 2)
- デートのあいだ相手の体力 (energy) も減っている
(一時データ. 時刻を進めて確かめる)

    python tools/test_stamina_with.py
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, geo as G, parting as PT, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
PT.FIXED = "ok"


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    real = time.time
    off = [0.0]
    time.time = lambda: real() + off[0]
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("体力")
        cid = app.settings["active_character"]
        B = app.bonds
        B.set_stage(cid, "visit")
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        st = app.state(cid)
        ps = app.life.player_state()
        ps["money"] = 100000

        def reset():
            st["cooldowns"], st["override"] = {}, None
            if B.mode(cid):
                B.end(go_home=False)
            app.presence.back(time.time())
            ps["stamina"] = 60.0
            ps["last_tick"] = time.time()
            app.set_params({"energy": 80, "affection": 70, "mood": 70}, cid)

        def run(hours):
            s0, e0 = ps["stamina"], st["params"]["energy"]
            for _ in range(int(hours * 2)):
                off[0] += 1800
                app.life.tick_world(time.time())
                app.tick(cid)
            return ps["stamina"] - s0, st["params"]["energy"] - e0

        # ---- 1. 一緒に出かけた先 (約束の場所で会った. 移動なし): 回復せず, 場所しだいで疲れる
        got = {}
        for aid in ("walk", "amusement", "cafe"):
            reset()
            app.act(aid, cid, opts={"appointment": "test"})
            st["override"]["until"] = time.time() + 5 * 3600
            pl = st["override"]["place"]
            want = app.with_load(time.time())
            d, de = run(4)
            got[pl] = (d, de)
            assert want and want[0] == "tire" and abs(d + 4 * want[1]) < 0.3, (pl, want, d)
            assert de < -5, ("相手の体力が減っていない", pl, de)
        assert got["amusement"][0] < got["park"][0] < got["cafe"][0] < 0, got
        print("出かけた先: OK | 4 時間で %s" % " / ".join("%s %+.1f（相手 %+.1f）" % (k, v[0], v[1]) for k, v in got.items()))

        # ---- 2. 比べ: 家で相手のそばにいるだけなら, 回復する (変えていない)
        reset()
        B.set_stage(cid, "live")
        B.sync(cid, st, time.time())
        d, _ = run(2)
        assert d > 8, d
        B.set_stage(cid, "visit")
        print("家でそばにいる: OK | 2 時間で %+.1f" % d)

        # ---- 3. 相手の家にいる: 回復は 1 時間に 2
        reset()
        B.start(cid, "visit", time.time())
        B.rec()["with"]["until"] = time.time() + 6 * 3600
        d, _ = run(3)
        assert abs(d - 3 * app.JOINT_REST) < 0.3, d
        print("相手の家: OK | 3 時間で %+.1f" % d)

        # ---- 4. 一緒の移動: 一人の移動と同じだけ疲れる (同居相手と家から: 行きと帰り). 移動の間は回復しない
        reset()
        G.INSTANT = False
        B.set_stage(cid, "live")
        B.sync(cid, st, time.time())
        s0 = ps["stamina"]
        app.act("amusement", cid)
        ov = st["override"]
        tr = ov.get("trips") or []
        assert [x["dir"] for x in tr] == ["go", "home"], tr
        cost = 0.0
        for x in tr:
            lg = {"how": x["how"], "legs": x.get("legs"), "min": (x["arr"] - x["t0"]) / 60.0}
            cost += app.geo.body_cost(lg, x["from"], x["to"])[1]
        assert cost > 0 and abs((s0 - ps["stamina"]) - cost) < 0.5, (s0 - ps["stamina"], cost)
        assert app.with_load(time.time() + 60) == ("tire", 0.0), app.with_load(time.time() + 60)
        print("一緒の移動: OK | 行きと帰りで %.1f（移動中は回復しない）" % (s0 - ps["stamina"]))
    finally:
        time.time = real
        PT.FIXED = None
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK")


if __name__ == "__main__":
    main()
