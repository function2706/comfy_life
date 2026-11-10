"""スマホ用の入り口 (/phone. 外から開く画面) (A16 の 1 段目).
📱 スマホ (トーク・カレンダー・買うもの) だけを出す入り口で, 家の画面を閉じている間に外から開く.
- 目印が phone- で始まる画面は排他の外: 家の画面を取らない・家の画面に止められない (読むのも送るのも)
- 家の画面どうしの排他は今までどおり
- スマホ用の入り口からの操作 (メッセージを送る) は在席を動かさない: 心拍も操作の時刻もそのまま
  (閉じていた間の過ごし方の始まりがずれない. 家の画面の前にいることにならない)
- 家の画面からの同じ操作は, 今までどおり在席になる
(一時データ)

    python tools/test_phone_entry.py
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
import server  # noqa: E402
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(16)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("スマホ用の入り口")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)

        # ---- 1. 排他: 家の画面は 1 つ. スマホ用の入り口はその外
        server.ACTIVE["client"] = None
        g = server.gate
        assert g("GET", "/api/state", "pc-a") is None and server.ACTIVE["client"] == "pc-a"
        assert g("GET", "/api/state", "phone-x") is None, "スマホ用の入り口は, 家の画面が使っていても読める"
        assert g("POST", "/api/chat/send", "phone-x") is None, "送れる"
        assert g("POST", "/api/claim", "phone-x") is None and server.ACTIVE["client"] == "pc-a", "家の画面を取らない"
        assert g("GET", "/api/state", "pc-b") == ({"inactive": True}, 200), "家の画面どうしは今までどおり"
        assert g("POST", "/api/act", "pc-b")[1] == 409
        server.ACTIVE["client"] = None
        assert g("GET", "/api/state", "phone-x") is None and server.ACTIVE["client"] is None, "先に開いても, 使う側にならない"

        # ---- 2. スマホ用の入り口からの操作は在席を動かさない
        p = app.presence.rec()
        t0 = time.time() - 3 * 3600                 # 3 時間前に家の画面を閉じた
        p["mode"], p["beat"], p["input"] = "none", t0, t0
        assert app.presence.at(time.time()) == "gone"
        app.via.phone = True
        n0 = len(app.chat.load(cid)["items"])
        app.chat.send(cid, "ask_how")
        assert len(app.chat.load(cid)["items"]) == n0 + 1, "スマホ用の入り口から送れる"
        assert p["beat"] == t0 and p["input"] == t0, (p["beat"] - t0, p["input"] - t0)
        assert app.presence.at(time.time()) == "gone", "家の画面の前にいることにならない"
        app.presence.touch()
        assert p["input"] == t0
        v = app.state_view()                         # 入り口の画面の更新 (心拍なし)
        assert p["beat"] == t0 and not v.get("gap"), "更新しても心拍にならない・閉じていた間のまとめも始めない"
        assert app.state(cid).get("msg_pending"), "返事待ちになっている"

        # ---- 3. 家の画面からの同じ操作は, 今までどおり在席になる
        app.via.phone = False
        app.state(cid)["msg_pending"] = None
        app.chat.send(cid, "ask_how")
        assert p["beat"] > t0 + 3600 and app.presence.at(time.time()) == "here"
        print("ok: スマホ用の入り口 (排他の外・在席を動かさない)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
