"""ComfyUI の output フォルダを汚さないことの確認.

    python tools/mock_comfy.py --port 8189 --delay 0.3   (別ターミナル)
    python tools/test_comfy_output.py --comfy-port 8189
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import comfy, engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)     # 同居相手が家にいる時刻に (平日の昼は出かけていて, そばにいない)


def saved(port):
    return json.loads(urllib.request.urlopen("http://127.0.0.1:%d/mock/saved" % port).read())


def gen(app):
    jid = app.snapshot()["job"]
    for _ in range(100):
        j = app.job_view(jid)
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.1)
    raise AssertionError("timeout")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comfy-port", type=int, required=True)
    port = ap.parse_args().comfy_port
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"comfy": {"port": port, "ckpt": "mock.safetensors"}, "images": {"mode": "always"}})
        before = len(saved(port))

        # 既定: 内蔵ワークフローは PreviewImage → output に残らない
        j = gen(app)
        assert j["status"] == "done", j
        assert len(saved(port)) == before, "output に保存されてしまった"
        print("内蔵 (既定): output に保存なし, 取得 OK →", j["image"])

        # カスタムワークフローの SaveImage も一時保存に置き換わる
        wf = comfy.builtin_workflow({"ckpt": "x"}, "%POSITIVE%", "%NEGATIVE%", 1)
        wf["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": "my_workflow", "images": ["8", 0]}}
        wf["20"] = {"class_type": "PreviewImage", "inputs": {"images": ["8", 0]}}   # 途中経過のプレビューも混ぜる
        app.save_workflow(wf)
        app.save_settings({"comfy": {"workflow_mode": "custom"}})
        j = gen(app)
        assert j["status"] == "done" and len(saved(port)) == before, j
        print("カスタム (既定): SaveImage → PreviewImage, output に保存なし")

        # オンにしたときだけ output/<サブフォルダ> に残す
        app.save_settings({"comfy": {"workflow_mode": "builtin", "keep_on_server": True, "output_prefix": "kurashi/kurashi"}})
        j = gen(app)
        new = saved(port)[before:]
        assert j["status"] == "done" and len(new) == 1 and new[0].startswith("kurashi/"), new
        print("保存オン: output/%s" % new[0])

        # pick_image: 保存ノードを優先
        outs = {"20": {"images": [{"filename": "a", "type": "temp"}]}, "9": {"images": [{"filename": "b", "type": "temp"}]}}
        assert comfy.pick_image(outs, ["9"])["filename"] == "b"
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
