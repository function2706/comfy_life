"""あなたのスキルの鈍りの確認 (一時データ, 画像生成なし).
- しばらく (RUST_AFTER_DAYS) 使わないスキルは少しずつ下がる. 下がるのはこれまでの最高値の半分くらいまで
- 鈍ったあと, 元の高さ (最高値) までは戻りやすい. 使っているスキルは下がらない

    python tools/test_rust.py
"""
import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, life, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(2)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        L = app.life
        ps = L.player_state()
        t0 = 1_800_000_000.0
        ps["skills"].update(cook=60.0, talk=60.0)
        ps["skill_peak"] = {"cook": 60.0, "talk": 60.0}
        ps["skill_used"] = {k: t0 for k in life.SKILLS}

        def days(n, keep=()):
            for i in range(n):
                t = t0 + (i + 1) * 86400
                for k in keep:
                    ps["skill_used"][k] = t
                L.rust(t)

        days(9, keep=("talk",))
        assert ps["skills"]["cook"] == 60.0, "まだ鈍らない"
        days(120, keep=("talk",))
        cook = ps["skills"]["cook"]
        assert 30.0 <= cook < 45.0, cook
        assert ps["skills"]["talk"] == 60.0, "使っているスキルは下がらない"
        days(400, keep=("talk",))
        assert ps["skills"]["cook"] >= 30.0, "最高値の半分より下がらない"
        print("120 日使わなかった料理: 60 → %.1f / 400 日: %.1f" % (cook, ps["skills"]["cook"]))
        assert "cook" in [k for k in life.SKILLS if ps["skill_peak"][k] - ps["skills"][k] >= 0.5]

        # 戻りやすさ: 同じ経験で, 鈍ったスキルは普通のスキルより大きく戻る
        ps["skills"]["work"] = ps["skills"]["cook"]
        ps["skill_peak"]["work"] = ps["skills"]["cook"]
        ps.setdefault("aptitude", {}).update(cook=1.0, work=1.0)
        ps["skill_day"] = {"d": "x", "f": {}, "got": {}}
        random.seed(5)
        g_rust = L.train("cook", 2.0)
        ps["skill_day"] = {"d": "x", "f": {}, "got": {}}
        random.seed(5)
        g_plain = L.train("work", 2.0)
        assert g_rust > g_plain * 1.8, (g_rust, g_plain)
        print("戻りやすさ: 鈍った料理 +%.2f / 普通 +%.2f" % (g_rust, g_plain))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
