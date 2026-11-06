"""「今いい？」の返事は 1 つだけ (「いいわ。かけてきなさい」のあとに「用事があるので, またあとで」と続いた件):
返事のあと, ノリが下がりきっても切り上げのひとことを付けない. あわせて, 画面の更新とトーク画面の見直しが同時に来ても
同じ返事待ちを二度届けない (engine.deliver_due のロック) (一時データ).

    python tools/test_deliver_once.py
"""
import os
import shutil
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("返信")
        cid = app.settings["active_character"]
        st = app.state(cid)
        st["override"] = {"activity": "relax", "label": "くつろいでいる", "location": "自宅", "until": time.time() + 9e6}
        for n in range(15):
            st.pop("msg_pending", None)
            app.chat.send(cid, "may_call")
            st["msg_pending"]["due"] = time.time() - 1
            st["msg_pending"]["reply"] = True
            before = len([x for x in app.chat.load(cid)["items"] if x["who"] == "her"])
            go = threading.Barrier(4)

            def run():
                go.wait()
                app.deliver_due()
            ts = [threading.Thread(target=run) for _ in range(4)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            after = len([x for x in app.chat.load(cid)["items"] if x["who"] == "her"])
            assert after - before == 1, ("返事は 1 つだけ", n, [(x.get("kind"), x["text"]) for x in app.chat.load(cid)["items"][-3:]])
            assert not st.get("msg_pending")
            st["contacts"] = []
        print("同時に 4 回見直しても, 返事は 1 つ: OK (15 回)")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
