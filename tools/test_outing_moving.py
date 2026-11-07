"""相手とのお出かけの行き帰りの移動中にできること (engine.moving_ok / outing_moving):
話す・見る・連絡のほか, 手をつなぐ・頭をなでる・写真・飲み物・プレゼントはできる. 抱きしめる・料理・ゲームなどは着いてから
(押せないボタンに「移動中です（着いてから）」). 着いたら何でもできる (一時データ).

    python tools/test_outing_moving.py
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

fix_noon(engine)        # 時計はずらさない (お出かけの移動の時刻は, いまの時刻から)
G.INSTANT = False


def main():
    random.seed(2)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("移動中")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "live")
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        st = app.state(cid)
        app.set_params({"affection": 80, "mood": 70, "trust": 70}, cid)
        app.life.player_state()["money"] = 50000
        app.act("aquarium", cid)
        ov = st.get("override") or {}
        now = time.time()
        assert ov.get("outing") and ov.get("arr", 0) > now, ov
        assert app.outing_moving(st, now)

        av = app.person_view(cid)["available"]
        assert av["hold_hands"]["ok"], av["hold_hands"]
        assert not av["hug"]["ok"] and av["hug"]["why"] == "移動中です（着いてから）", av["hug"]
        r = app.act("hold_hands", cid)
        assert r.get("entry"), r
        try:
            app.act("hug", cid)
            raise AssertionError("移動中に抱きしめられた")
        except ValueError as e:
            assert "移動中" in str(e)
        print("移動中: OK | 手をつなぐ ○ / 抱きしめる ×（%s）" % av["hug"]["why"])

        # 着いたら何でも
        ov["arr"] = time.time() - 1
        st["cooldowns"] = {}
        assert not app.outing_moving(st, time.time())
        assert app.person_view(cid)["available"]["hug"]["ok"]
        print("着いたら: OK")
        app.scheduled_scene = sched
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
