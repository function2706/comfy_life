"""機嫌・照れ・ドキドキの上がり方 (1.5.0):
- 高いほど上がりにくい (上限までの残りが少ないほど鈍る). 下がる方は鈍らない
- 照れ・ドキドキは, 30 分のうちに何度も揺さぶられると慣れる (同じ +10 でも, 回を重ねるほど小さく)
- 絵の頬の赤さは, いまの照れの値に合わせる (30 未満は赤くしない・55 未満はほんのり・80 未満は顔じゅう真っ赤にしない)
- 11/07 の報告と同じデートの流れで, 照れが真っ赤 (80) に届かず, 機嫌が 90 を超えない (tools/sim_date_mood.py)
(一時データ)

    python tools/test_mood_saturate.py
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("上がり方")
        cid = app.settings["active_character"]
        st = app.state(cid)
        P = st["params"]

        # ---- 1. 高いほど上がりにくい / 下がる方は鈍らない
        app.set_params({"mood": 50}, cid)
        d_lo = app.apply_effects(st, {"mood": 10})["mood"]
        app.set_params({"mood": 90}, cid)
        d_hi = app.apply_effects(st, {"mood": 10})["mood"]
        d_dn = app.apply_effects(st, {"mood": -10})["mood"]
        assert d_lo == 10 and d_hi < 3 and d_dn == -10, (d_lo, d_hi, d_dn)
        app.set_params({"mood": 99}, cid)
        for _ in range(20):
            app.apply_effects(st, {"mood": 10})
        assert P["mood"] < 100, P["mood"]
        print("機嫌: OK | 50 から +10 → +%.1f / 90 から +10 → +%.1f / 下げは -10 のまま" % (d_lo, d_hi))

        # ---- 2. 照れは慣れる (30 分のうち)
        app.set_params({"shyness": 0}, cid)
        st["habit"] = {}
        now = time.time()
        ds = [app.apply_effects(st, {"shyness": 10}, now=now + i * 60)["shyness"] for i in range(5)]
        assert ds[0] == 10 and all(ds[i] > ds[i + 1] for i in range(4)) and ds[-1] < 5, ds
        app.set_params({"shyness": 0}, cid)
        d_later = app.apply_effects(st, {"shyness": 10}, now=now + 4 * 60 + 1801)["shyness"]
        assert d_later == 10, d_later
        print("照れの慣れ: OK | +10 を 1 分おきに 5 回 → %s / 30 分あけると +%.1f" % (" ".join("%.1f" % d for d in ds), d_later))

        # ---- 3. 頬の赤さは照れの値に合わせる
        pos = "1girl, smile, full-face blush, looking away"
        for sh, want in ((10, None), (40, "light blush"), (65, "blush"), (85, "full-face blush")):
            P["shyness"] = sh
            tags = [t.strip() for t in app._blush_by_shyness(pos, st).split(",")]
            got = [t for t in tags if t in app.BLUSH_TAGS]
            assert got == ([want] if want else []), (sh, got)
        P["shyness"] = 10
        assert app._blush_by_shyness("1girl, smile", st) == "1girl, smile"
        pos2, neg2, _ = app.build_prompt(app.char(cid), st, __import__("datetime").datetime.now(), {"pos": "blush, smile", "name": "x"})
        assert "blush" not in [t.strip() for t in pos2.split(",")] and "照れ" not in neg2, (pos2, neg2)
        print("頬の赤さ: OK | 照れ 10 → なし / 40 → light blush / 65 → blush / 85 → full-face blush")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- 4. 報告と同じデートの流れ
    import sim_date_mood as S
    fin = []
    for seed in range(3):
        rows, blush = S.run(seed)
        fin.append((rows[-1][2], max(r[3] for r in rows), sum(1 for r in rows if r[5] == "full")))
    assert all(f[0] < 90 and f[1] < 80 and f[2] == 0 for f in fin), fin
    print("デートの流れ: OK | 終わりの機嫌 %s / 照れの最高 %s / 真っ赤な絵 0" % (
        " ".join("%.0f" % f[0] for f in fin), " ".join("%.0f" % f[1] for f in fin)))
    print("ALL OK")


if __name__ == "__main__":
    main()
