"""内職の印とお詫び (一時データ, 画像生成なし).
- 画面の側の印 (ピクロスの×・旗・数独のメモ) は, やりかけと一緒に残り, 再起動・読み込み直しのあとも戻る
- お詫び (一度だけ): やりかけのピクロスは仕上げた扱いで終える (体力は使わない). もう途中でやめていれば, 仕上げた額との差を払う

    python tools/test_task_marks.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, puzzles, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(3)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        ps = app.life.player_state()

        # ---- 印が残る
        tk = app.task_start("picross", "mid")
        assert tk["marks"] is None
        app.task_marks(tk["token"], {"xs": ["0,1", "2,3"], "flags": [], "memo": {}, "junk": 1})
        app2 = engine.App()
        r = app2.task_resume()
        print("読み込み直したあとの印:", r["marks"])
        assert r["marks"] == {"xs": ["0,1", "2,3"], "flags": [], "memo": {}}

        # ---- お詫び: やりかけのピクロスは仕上げた扱いで終える
        app2.life.player_state().setdefault("fix_comp", {}).pop("task_marks", None)
        L = app2.life
        m0, s0, w0 = L.player_state()["money"], L.stamina(), L.skill("work")
        pay = app2.task_marks_comp()
        want = int(round(puzzles.base_pay("picross", "mid") * puzzles.skill_mult("picross", L.skill_mult) / 10.0)) * 10
        note = app2.solo.mylog()[-1]["text"]
        print("やりかけ:", pay, "円 /", note)
        assert pay == want and L.player_state()["money"] - m0 == pay and L.stamina() == s0 and L.skill("work") > w0
        assert app2.task_active() is None and "仕上げた扱い" in note
        assert app2.task_marks_comp() == 0, "一度だけ"

        # ---- もう途中でやめていた: 仕上げた額との差 (難しさは終えたときの記録から)
        app2.life.player_state()["fix_comp"].pop("task_marks")
        tk = app2.task_start("picross", "easy")
        got = app2.task_finish(tk["token"])["task"]["pay"]
        m0 = L.player_state()["money"]
        pay = app2.task_marks_comp()
        want = int(round(puzzles.base_pay("picross", "easy") * puzzles.skill_mult("picross", L.skill_mult) / 10.0)) * 10 - got
        print("やめていた:", pay, "円 /", app2.solo.mylog()[-1]["text"])
        assert pay == want and L.player_state()["money"] - m0 == pay, (pay, want, got, app2.solo.mylog()[-2:])

        # ---- 以前のアプリで, 誰かのそばでやめていた (種類も額も残っていない): ピクロスの「中」を途中でやめたとみなす
        app2.life.player_state()["fix_comp"].pop("task_marks")
        app2.life.player_state().pop("side_job_last")
        m0 = L.player_state()["money"]
        pay = app2.task_marks_comp()
        assert pay == int(round(puzzles.base_pay("picross", "mid") * puzzles.skill_mult("picross", L.skill_mult) / 10.0)) * 10, pay
        # 仕上げていた・ほかの内職だったなら払わない
        app2.life.player_state()["fix_comp"].pop("task_marks")
        tk = app2.task_start("slide", "easy")
        app2.task_finish(tk["token"])
        assert app2.task_marks_comp() == 0

        # ---- 期限を過ぎたら何もしない
        app2.life.player_state()["fix_comp"].pop("task_marks")
        assert app2.task_marks_comp(now=engine.App.TASK_MARKS_UNTIL + 1) == 0
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
