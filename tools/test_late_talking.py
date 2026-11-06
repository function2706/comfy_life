"""夜中のメッセージ: 相手から少し前 (30 分以内) に届いていたら, やりとりの最中なので「こんな時間に」とは言わない.
相手からしばらく何も無ければ, これまでどおり夜中の連絡として響く (一時データ).

    python tools/test_late_talking.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402


def main():
    random.seed(4)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("夜中")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        now = time.time()
        ctx = dict(app.context(char, st, datetime.fromtimestamp(now)), phase="midnight", too_often=False, _sent=now, _meta={})

        # 相手からしばらく何も無い: 夜中の連絡
        key, _, _ = app.chat.reply(char, st, "thanks", now, dict(ctx))
        assert key == "late_night", key

        # 11 分前に相手から届いていた (約束の返事など): やりとりの最中
        app.chat.add(cid, "her", "11/7（土） 13:00、水族館ね。いいわ", t=now - 11 * 60)
        assert app.chat.talking(cid, now)
        key, _, _ = app.chat.reply(char, st, "thanks", now, dict(ctx))
        assert key != "late_night", key
        print("やりとりの最中:", key)

        # 2 時間前なら, やりとりは途切れている
        assert not app.chat.talking(cid, now + 2 * 3600)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
