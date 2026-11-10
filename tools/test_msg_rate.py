"""離れている相手が自分から送ってくるメッセージの多さ (1.6.0. core/presence.py eagerness_apart).
- あなたへの興味 (好感度) の掛け算: 好感度 30 以下なら送ってこない. 寂しくても, 嫌っている相手には送らない
  (以前は寂しさと好感度の足し算で下限もあったので, 好感度 10 でも寂しいと 1 日 1 通ほど届いていた)
- 好感度が上がるほど, はっきり増える. 中くらいでは, 依存度・性格 (話しかけてくる多さ) の差が出る
- 「話そう」「今日の出来事」も, 好感度 35 未満では選ばれない
(一時データ)

    python tools/test_msg_rate.py
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import cond, engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("メッセージの多さ")
        P = app.presence
        rate = float(P.cfg().get("approach_apart_rate_per_hour", 0.25))

        def per_day(aff, lon=30, mood=50, dep=45, boredom=30, approach=1.0):
            ctx = {"affection": aff, "loneliness": lon, "mood": mood, "dependence": dep, "boredom": boredom}
            return rate * P.eagerness_apart(ctx) * approach * 16        # 起きている 16 時間

        # ---- 1. 好感度 30 以下: 寂しくても, 機嫌がよくても送ってこない
        for lon in (10, 50, 90):
            for aff in (5, 20, 30):
                assert per_day(aff, lon=lon, mood=70, boredom=80) == 0, (aff, lon)
        print("嫌っている相手からは来ない: OK")

        # ---- 2. 好感度で増える. 中くらいで 2 日に 1 通〜1 日 1 通台, 高いとはっきり多い
        table = [(aff, per_day(aff, lon=lon, mood=mood, dep=dep)) for aff, lon, mood, dep in
                 ((40, 30, 50, 40), (50, 30, 50, 45), (60, 40, 55, 50), (80, 60, 60, 60))]
        vals = [v for _, v in table]
        assert vals == sorted(vals) and 0.2 < vals[0] < 0.9 and vals[-1] > 3 * vals[1], table
        print("好感度で増える: OK |", " / ".join("好感度 %d: %.1f 通" % (a, v) for a, v in table))

        # ---- 3. 寂しさ・退屈は, 興味のある相手に送る理由を強める (興味がなければ効かない)
        assert per_day(60, lon=80) > per_day(60, lon=20) * 1.3
        assert per_day(30, lon=90) == per_day(30, lon=10) == 0
        # 中くらいの好感度では, 依存度と性格の差が出る
        hi, lo = per_day(50, dep=80, approach=1.7), per_day(50, dep=20, approach=0.5)
        assert hi > 5 * lo, (hi, lo)
        print("寂しさ・依存度・性格: OK | 好感度 50 で 話しかけたがり %.1f 通 / 慎重 %.2f 通" % (hi, lo))

        # ---- 4. 「話そう」「今日の出来事」は好感度 35 未満では選ばれない
        for aid in ("msg_chat", "msg_today"):
            a = P.find(aid)
            ctx = {"affection": 34, "boredom": 80, "mood": 80, "loneliness": 80}
            assert not cond.check(a["when"], ctx), aid
            assert cond.check(a["when"], dict(ctx, affection=40)), aid
        print("働きかけの下限: OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK")


if __name__ == "__main__":
    main()
