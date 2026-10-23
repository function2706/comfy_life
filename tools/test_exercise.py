"""あなたの運動量の確認 (一時データ, 画像生成なし).
- 運動の蓄えは日ごとに減り, 体を動かすと増える (ぶらぶら歩く外出・ジョギング・誰かとのお出かけ・家事. 仕事は少しだけ)
- 足りない日が続くと (運動不足) 体力の上限が下がり, 戻りにくく, 体調を崩しやすい. 動けば戻る
- ジョギングは一人の行動 (公園・河川敷・街で). 行動パターンの外出・家事でも体を動かす

    python tools/test_exercise.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import body as body_mod, engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(8)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        B, P, S = app.body, app.presence, app.solo
        b = B.rec()
        t = time.time()
        P.rec()["beat"] = P.rec()["input"] = t

        # ---- 1. 何もしなければ減る. 歩く・走ると増える (走るほうが多い)
        b["exercise"] = 50.0
        B.step(t, 24.0, "here")
        assert b["exercise"] < 25, b["exercise"]
        S.start("out", place="park")
        e0 = b["exercise"]
        B.step(t, 0.5, "out")
        walk = b["exercise"] - e0
        app.presence.rec()["since"] -= 1800
        app.come_back()
        r = S.start("jog", place="riverside")
        assert r["started"] == "jog" and P.rec()["place"] == "riverside"
        e0 = b["exercise"]
        B.step(t, 0.5, "out")
        jog = b["exercise"] - e0
        assert jog > walk > 20, (walk, jog)
        st0 = app.life.stamina()
        P.rec()["since"] -= 1800
        res = app.come_back()["solo"]
        assert "走った" in res["text"] and app.life.stamina() < st0, res
        print("30分: 散歩 +%.0f / ジョギング +%.0f" % (walk, jog))
        try:
            S.start("jog", place="supermarket")
            raise AssertionError("スーパーを走れる")
        except ValueError:
            pass

        # ---- 2. 運動不足が続くと: 体力の上限が下がり, 戻りにくく, 崩しやすい. 動けば戻る
        b["exercise"] = 5.0
        b["lazy_days"] = 0
        b["nutri"] = {"staple": 70.0, "protein": 70.0, "veg": 70.0}
        b["today"] = {"slept": 7.5}
        app.life.player_state()["stamina"] = 80.0
        r0, _ = B.risk(t)
        for _ in range(6):
            b["exercise"] = 5.0
            b["today"] = {"slept": 7.5}
            B.daily(t)
        assert b["lazy_days"] >= 6 and B.stamina_cap() < 100 and B.stamina_mult() < 1.0, (b["lazy_days"], B.stamina_cap())
        assert app.life.stamina() <= B.stamina_cap()
        b["nutri"] = {"staple": 70.0, "protein": 70.0, "veg": 70.0}
        b["today"] = {"slept": 7.5}
        app.life.player_state()["stamina"] = 60.0
        r1, why = B.risk(t)
        assert r1 > r0 and "exercise" in why, (r0, r1, why)
        assert "なまって" in B.view()["health"]["exercise"]
        print("運動不足 %d 日: 体力の上限 %d" % (b["lazy_days"], B.stamina_cap()))
        for _ in range(3):
            b["exercise"] = 60.0
            B.daily(t)
        assert b["lazy_days"] == 0 and B.stamina_cap() == 100

        # ---- 3. 行動パターンの外出・家事でも体を動かす
        assert app.offline._move("out", "park") == body_mod.MOVE_PER_H["walk"] and app.offline._move("chores", None) > 0
        assert app.offline._move("sleep", None) == 0
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
