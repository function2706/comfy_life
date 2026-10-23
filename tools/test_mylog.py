"""あなた一人の行動の記録の置き場所の確認 (一時データ, 画像生成なし).
- その場にいない相手のログに, あなた一人の行動 (仕事から帰った・出かけた など) を書かない. あなたの記録 (mylog) に残す
- 以前のデータで, 離れている相手のログに書かれていた「（仕事から帰ってきた。…）」などは, あなたの記録へ移す (一度だけ)
- 外で会っていた相手と別れたところ (「〇〇と別れて、…」) と, その人が関わった記録は, その人のログに残す

    python tools/test_mylog.py
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
    random.seed(4)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("記録")
        cid = next(c for c in app.chars if app.bonds.stage(c) != "known")
        assert not app.bonds.together(cid)
        P = app.presence
        P.rec()["beat"] = P.rec()["input"] = time.time()

        # ---- 1. いまは: 離れている相手には書かない
        n = len(app.log(cid))
        r = app.act("go_work", cid)
        assert r["entry"].get("mine") and len(app.log(cid)) == n and P.rec()["mode"] == "work", r["entry"]
        P.rec()["since"] -= 3600
        r = app.come_back()
        assert r["entry"].get("mine") and "仕事" in r["entry"]["text"] and len(app.log(cid)) == n
        assert any(x.get("kind") == "work" for x in app.solo.mylog())

        # ---- 2. 以前のデータ: 離れている相手のログの, あなた一人の行動の記録を移す
        t = time.time() - 86400
        old = [
            {"id": "a1", "t": t, "action": "work", "action_name": "仕事から帰る", "icon": "💼", "text": "（仕事から帰ってきた。今日の稼ぎは 7,200円）",
             "deltas": {}, "images": [], "money": {"p": 7200}},
            {"id": "a2", "t": t + 60, "action": "go_out", "action_name": "ちょっと出かけてくる", "icon": "🚪", "text": "（ちょっと出かけた）",
             "deltas": {}, "images": []},
            {"id": "a3", "t": t + 120, "action": "go_work", "action_name": "仕事に行ってくる", "icon": "💼",
             "text": "（{name}と別れて、仕事に出かけた）".replace("{name}", app.chars[cid]["name"]), "deltas": {}, "images": []},
            {"id": "a4", "t": t + 180, "action": "talk", "action_name": "話しかける", "icon": "💬", "text": "こんにちは", "deltas": {"mood": 1},
             "images": []},
        ]
        store.save(store.wpath("log", cid + ".json"), old)
        ps = store.load(store.wpath("player.json"))
        ps.pop("migrated", None)
        store.save(store.wpath("player.json"), ps)
        app2 = engine.App()
        log = app2.log(cid)
        ids = [e["id"] for e in log]
        assert ids == ["a3", "a4"], ids
        my = [x for x in app2.solo.mylog() if x.get("migrated")]
        assert {x["id"] for x in my} == {"ma1", "ma2"} and any(x.get("money", {}).get("p") == 7200 for x in my), my
        # 一度だけ (もう一度起動しても, 移さない)
        store.save(store.wpath("log", cid + ".json"), log + [dict(old[1], id="a5")])
        app3 = engine.App()
        assert "a5" in [e["id"] for e in app3.log(cid)], "移行は一度だけ"
        print("移した:", [x["text"] for x in my])
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp + "_backup", ignore_errors=True)


if __name__ == "__main__":
    main()
