"""内職の疲れ (一時データ, 画像生成なし).
- 休憩の縛りはない: 終えてすぐ次を始められる. 体力が足りなければ始められない
- 体力は手を動かした時間ぶん (1 時間で 12 ほど). 一時停止していた間は数えない
- 続けるほど減りが速い (続けて 1 時間で 2 倍). ほかのことをして休むと, 続けている疲れは 30 分ごとに半分抜ける

    python tools/test_side_job_tire.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(7)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        ps = app.life.player_state()

        def job(minutes, gap_min=0, paused_min=0):
            """minutes 分手を動かした内職を終える (gap_min: 前の内職を終えてから始めるまで). 使った体力."""
            ps["stamina"] = 100
            if gap_min and ps.get("side_job_streak"):
                ps["side_job_streak"]["t"] -= gap_min * 60
            tk = app.task_start("slide", "easy")
            t = app.tasks[tk["token"]]
            t["t0"] -= (minutes + paused_min) * 60
            if paused_min:
                t["paused_total"] = paused_min * 60
            r = app.task_finish(tk["token"])
            assert abs(r["task"]["stamina"] - (100 - ps["stamina"])) < 0.2, (r["task"], ps["stamina"])
            return r["task"]

        a = job(60)
        print("はじめての 1 時間: 体力 -%s" % a["stamina"])
        assert 15 <= a["stamina"] <= 21 and not a["tired"] is None
        b = job(60)                                         # 終えてすぐ, もう 1 時間 (休憩なしで始められる)
        print("続けてもう 1 時間: 体力 -%s (疲れが早い: %s)" % (b["stamina"], b["tired"]))
        assert b["stamina"] > a["stamina"] * 1.5 and b["tired"]
        ps["side_job_streak"] = None
        c = job(5)
        print("5 分だけ: 体力 -%s" % c["stamina"])
        assert 0.5 <= c["stamina"] <= 1.5 and not c["tired"]
        d = job(5, gap_min=240)                             # 4 時間あいだを空けると, ほぼ最初と同じ
        assert abs(d["stamina"] - c["stamina"]) < 0.3, (c, d)
        ps["side_job_streak"] = None
        e = job(30, paused_min=120)                         # 一時停止していた 2 時間は数えない
        print("30 分 (2 時間止めていた): 体力 -%s" % e["stamina"])
        assert 6 <= e["stamina"] <= 9, e
        ps["stamina"] = 2
        why = app.task_ready()
        assert why and "体力" in why["reason"], why
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
