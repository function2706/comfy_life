"""誰かと出かけている・相手の家にいる途中は, 一人ですること (家事・研鑽・ジョギング・外出・本・映画・家計簿・作業・仕事・
自炊・内職) はできない (1.5.0 の直し). 寝る・席を外すはできる (泊まっているとき・少し離れるだけ).
家に来てもらっている・同居相手と家にいるときは, 声をかけてから一人のことができる (変わらない).
状態ごとに, 一人ですることをすべて押して確かめる (一時データ).

    python tools/test_out_with_solo.py
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
from core import engine, solo as S, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(3)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("一人のこと")
        cid = app.settings["active_character"]
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        st = app.state(cid)
        B = app.bonds
        name = app.chars[cid]["name"]
        kinds = [(k, None) for k in S.KINDS] + [("kakeibo", None)] + [(k, None) for k in S.PLAIN if k not in S.OUT_WITH_OK]

        def reset():
            if B.with_rec():
                B.end(go_home=False)
            st["override"] = None
            app.presence.declare("none", time.time())
            app.presence.rec()["pos"] = "home:me"
            app.save_state(cid)

        def check_blocked(label, word):
            ow = app.out_with()
            assert ow and name in ow and word in ow, (label, ow)
            bl = app.blocked_view()
            assert bl["solo"] == ow and bl["cook"] == ow and bl["side_job"] == ow and not bl["social"], (label, bl)
            assert app.task_ready()["reason"] == ow, (label, app.task_ready())
            for k, sk in kinds:
                try:
                    app.solo.start(k, sk, "park" if k in ("out", "jog") else None)
                    raise AssertionError("%s: 「%s」が始まった" % (label, k))
                except ValueError as e:
                    assert str(e) == ow, (label, k, str(e))
            v = app.solo.view()
            assert v["out_with"] == ow and all(p["out_ok"] == (p["id"] in S.OUT_WITH_OK) for p in v["plain"]), (label, v["plain"])
            print("%s: OK | 一人ですること %d 種すべて ×（%s）・寝る / 席を外すは ○" % (label, len(kinds), ow))

        # ---- 1. 外で会っている (約束の場所で会った形: 外で会う + お出かけ)
        B.set_stage(cid, "contact")
        reset()
        B.start(cid, "meet")
        st["override"] = {"outing": True, "place": "aquarium", "location": "水族館", "until": time.time() + 3600, "from_action": "aquarium"}
        app.save_state(cid)
        check_blocked("外で会っている", "出かけている")

        # ---- 2. 同居相手と一緒にお出かけ (行きの移動中も, 着いてからも)
        reset()
        B.set_stage(cid, "live")
        app.set_params({"affection": 80, "mood": 75, "energy": 80}, cid)
        engine.geo_mod.INSTANT = False
        app.act("aquarium", cid)
        assert app.outing_trip(st, time.time()), st["override"]
        check_blocked("一緒にお出かけ（移動中）", "出かけている")
        st["override"]["trips"] = []
        st["override"]["arr"] = time.time() - 1
        app.save_state(cid)
        check_blocked("一緒にお出かけ（着いてから）", "出かけている")
        engine.geo_mod.INSTANT = True

        # ---- 3. 相手の家に来ている
        reset()
        B.set_stage(cid, "visit")
        B.start(cid, "visit")
        check_blocked("相手の家に来ている", "家に来ている")

        # ---- 4. 変わらない: 家に来てもらっている・同居相手と家にいる・一人 → 一人のことができる
        for label, stage, mode in (("家に来てもらっている", "visit", "guest"), ("同居相手と家にいる", "live", "home"), ("一人", "contact", None)):
            reset()
            B.set_stage(cid, stage)
            if mode == "guest":
                B.start(cid, "guest")
            assert not app.out_with() and not app.blocked("solo"), (label, app.out_with())
            r = app.solo.start("chores")
            assert r.get("started") == "chores", (label, r)
            app.come_back()
            print("%s: OK | 家事 ○" % label)
        app.scheduled_scene = sched
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
