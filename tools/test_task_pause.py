"""内職の一時停止: 一時停止のあいだは家でのこと (家事・研鑽など) ができ, 出かける・仕事に行くのは内職を終えてから.
ほかのことの途中・家にいないときは再開できない. 開くだけなら一時停止のまま.

    python tools/test_task_pause.py
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.path.insert(0, HERE)
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def refused(fn, *a, **k):
    try:
        fn(*a, **k)
    except ValueError as e:
        return str(e)
    raise AssertionError("断られなかった: %s" % fn)


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("一時停止")
        app.life.player_state().update(stamina=100, money=50000)
        tk = app.task_start("sudoku", "easy")
        tok = tk["token"]
        assert app.blocked("solo") and app.doing_now()["kind"] == "task"          # している間は, ほかのことはできない

        # ---- 一時停止: 家でのことはできる. 出かけるのはできない
        app.task_pause(tok, True)
        assert app.blocked("solo") is None and app.doing_now() is None and app.presence.rec()["mode"] == "none"
        assert app.state_view()["task_paused"] is True
        assert "一時停止" in refused(app.solo.start, "out", place="park")
        assert "一時停止" in refused(app.solo.start, "work")
        app.solo.start("chores", "dishes")
        assert app.doing_now()["kind"] == "chores"
        assert "途中" in refused(app.task_pause, tok, False)                          # 家事の途中は再開できない
        assert app.task_resume(tok)["paused"]                                          # 開くだけなら一時停止のまま
        assert app.presence.rec()["mode"] == "busy" and (app.presence.rec().get("solo") or {}).get("kind") == "chores"
        app.come_back()                                                                # 家事を終える
        r = app.task_pause(tok, False)                                                 # 再開
        assert not r["paused"] and app.doing_now()["kind"] == "task" and app.presence.rec()["mode"] == "busy"
        print("一時停止: OK")
        app.task_finish(tok)
        assert app.stay_home() is None and not app.state_view()["task_paused"]
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
