"""顔だけのアイコン: 一度だけ作って定義に固定する・作り直す・自動表示が切れていれば作らない.

    python tools/test_icon.py         (ComfyUI もどきを中で立てる)
"""
import os
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


def main():
    mock_comfy.DELAY = 0.05
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mock_comfy.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"comfy": {"port": srv.server_address[1], "ckpt": "mock.safetensors"},
                           "auto_generate": True, "images": {"mode": "always"}})
        cid = "hina"
        c = app.chars[cid]
        assert not app.has_icon(c)

        # プロンプト: キャラの外見 + 顔だけのタグ. 共通プロンプト・場面・服は入れない
        app.settings.setdefault("prompt", {})["prefix_pos"] = "common_prefix_tag"
        pos, neg = app.icon_prompt(c)
        assert "portrait" in pos and "looking at viewer" in pos and "common_prefix_tag" not in pos, pos
        for tg in [t.strip() for t in c.get("pos", "").split(",") if t.strip()]:
            assert tg.lower() in pos.lower(), tg
        assert c.get("outfit_default", "x") not in pos or not c.get("outfit_default")
        assert "full body" in neg

        # ログの画像を出すついでに, まだアイコンのない人は一度だけ作る
        jid = app.make_icon(cid)
        assert jid and app.make_icon(cid) == jid, "作っている途中なら同じジョブ"
        j = wait(app, jid)
        assert j["status"] == "done", j
        icon = store.all_characters()[cid]["icon"]
        assert icon == j["image"] and app.chars[cid]["icon"] == icon
        assert app.chat.face(cid) == icon, "顔はアイコンを使う"
        print("一度だけ作って定義に固定:", icon)

        # すでにあれば作らない (作り直しは force)
        assert app.make_icon(cid) is None
        j2 = wait(app, app.make_icon(cid, force=True))
        assert j2["status"] == "done" and j2["image"] != icon
        assert app.chat.face(cid) == j2["image"]
        print("作り直し:", j2["image"])

        # 古い画面の保存 (icon を持たない定義) でアイコンを消さない
        c2 = {k: v for k, v in store.all_characters()[cid].items() if k not in ("icon", "icon_seed")}
        app.save_character(c2)
        assert store.all_characters()[cid]["icon"] == j2["image"]

        # アイコンの画像を消したら, ログの最新の画像に戻る
        app.delete_image(j2["image"])
        assert app.chat.face(cid) != j2["image"]

        # 新しい人: 自動表示が切れていれば作らない. 入れば知り合った時点で作る
        app.save_settings({"auto_generate": False})
        a = app.new_character("みお", stage="contact", pos="1girl, solo, short hair")
        assert app.icon_job(a["id"]) is None and not store.all_characters()[a["id"]].get("icon")
        app.save_settings({"auto_generate": True})
        b = app.new_character("さき", stage="contact", pos="1girl, solo, ponytail")
        jb = app.icon_job(b["id"])
        assert jb, "知り合った時点で作る"
        assert wait(app, jb)["status"] == "done" and store.all_characters()[b["id"]].get("icon")
        # 作り直すは自動表示の設定によらない
        app.save_settings({"auto_generate": False})
        assert wait(app, app.make_icon(a["id"], force=True))["status"] == "done"
        assert app.has_icon(store.all_characters()[a["id"]])
        print("ALL OK")
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
