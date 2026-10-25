"""出先で会った人の顔のアイコン: 登録キャラ (まだ無ければ作る)・登録していない人 (一度だけ作って people.json に固定し,
登録したら定義に引き継ぐ)・出先のカードの顔・画像の自動表示が切れていれば作らない.

    python tools/test_street_icon.py         (ComfyUI もどきを中で立てる)
"""
import os
import random
import shutil
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import mock_comfy  # noqa: E402
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def wait(app, jid):
    for _ in range(200):
        j = app.job_view(jid)
        if j["status"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError("timeout")


def icon_jobs(app, kind):
    return [j for j in app.jobs.values() if j.get("kind") == kind]


def main():
    random.seed(3)
    mock_comfy.DELAY = 0.05
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mock_comfy.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"comfy": {"port": srv.server_address[1], "ckpt": "mock.safetensors"}, "auto_generate": True})
        app.create_world("出先")
        S = app.street

        # ---- 1. 登録キャラに出先で会った: まだアイコンが無ければ作る
        cid = app.settings["active_character"]
        assert not app.has_icon(app.char(cid))
        S._meet("char", cid, "スーパー", None, time.time(), "supermarket")
        jobs = [j for j in icon_jobs(app, "icon") if j["cid"] == cid]
        assert jobs, "登録キャラのアイコンを作る"
        wait(app, jobs[0]["id"])
        assert app.has_icon(store.all_characters()[cid])
        assert S.view()["face"] == store.all_characters()[cid]["icon"], "カードに顔"
        S.resolve("nod", auto=True)
        print("登録キャラ: OK")

        # ---- 2. 登録していない人: 初めて会ったときに一度だけ作って people.json に固定
        ppl = S.people()
        pid = S._new_person(ppl, "supermarket", "noon", False, time.time())
        S._meet("person", pid, "スーパー", None, time.time(), "supermarket")
        assert S.view()["name"] == "知らない人" and S.view()["face"] is None, "できるまでは顔なし (名前は知らない人のまま)"
        pj = [j for j in icon_jobs(app, "icon_person") if j["entry"] == pid]
        assert len(pj) == 1
        wait(app, pj[0]["id"])
        icon = S.people()[pid]["icon"]
        assert icon and S.view()["face"] == icon and S.view()["name"] == "知らない人"
        S.resolve("nod", auto=True)
        S._meet("person", pid, "スーパー", None, time.time(), "supermarket")
        assert len([j for j in icon_jobs(app, "icon_person") if j["entry"] == pid]) == 1, "一度だけ"
        S.resolve("nod", auto=True)
        print("登録していない人: OK", icon)

        # ---- 3. 知り合いになって登録したら, そのアイコンを定義に引き継ぐ (作り直さない)
        pr = S.people()[pid]
        app.encounters.ask_register(pr["char"], "スーパー", None, pr.get("src") or {"type": "new"}, pid=pid, now=time.time())
        n_icon = len(icon_jobs(app, "icon"))
        r = app.encounters.answer(True)
        new_cid = r["registered"]["id"]
        assert store.all_characters()[new_cid]["icon"] == icon
        assert len(icon_jobs(app, "icon")) == n_icon, "作り直さない"
        assert app.chat.face(new_cid) == icon
        print("登録で引き継ぐ: OK")

        # ---- 4. 画面を閉じていた間の出会いも同じ (street.happen を通る). 自動表示が切れていれば作らない
        app.save_settings({"auto_generate": False})
        pid2 = S._new_person(S.people(), "park", "noon", False, time.time())
        S._meet("person", pid2, "公園", None, time.time(), "park")
        assert not [j for j in icon_jobs(app, "icon_person") if j["entry"] == pid2], "自動表示が切れていれば作らない"
        S.resolve("nod", auto=True)
        app.save_settings({"auto_generate": True})
        before = len(icon_jobs(app, "icon_person"))
        for _ in range(60):
            if S.pending():
                S.resolve("nod", auto=True)
            app.offline._outing_meets("supermarket", time.time() - 3600, time.time())
        assert len(icon_jobs(app, "icon_person")) > before or any(app.has_icon(p) for p in S.people().values() if p is not None)
        print("閉じていた間・自動表示オフ: OK")

        # ---- 5. 一緒に過ごす誘いのカードにも顔
        S.rec()["mode"] = "out"                  # 一人で出かけているときのカード
        S.rec()["street_join"] = {"cid": new_cid, "name": "x", "place": "supermarket", "where": "スーパー", "t": time.time(),
                                  "until": time.time() + 600, "offer": True, "line": ""}
        assert S.join_view()["face"] == icon
        print("ALL OK")
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
