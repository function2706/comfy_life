"""バックエンドの簡易動作確認 (一時データディレクトリで実行, data/ は汚さない).

    python tools/mock_comfy.py --port 8189 --delay 0.5   (別ターミナル)
    python tools/smoke_test.py [--comfy-port 8189]
"""
import argparse
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import cond, engine, store  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comfy-port", type=int, default=0, help="0 なら生成テストを省略")
    a = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        assert cond.check("mood>=50, phase=night|midnight", {"mood": 60, "phase": "midnight"})
        assert not cond.check("free=true", {"free": False})
        assert cond.check("time>=07:30", {"time": 8 * 60})
        assert not cond.check("unknown=1", {})

        app = engine.App()
        app.save_settings({"comfy": {"port": a.comfy_port or 1, "ckpt": "mock_model_a.safetensors"},
                           "auto_generate": bool(a.comfy_port)})
        v = app.state_view()
        print("scene:", v["scene"]["label"], "/ phase:", v["phase"]["label"], "/ tags:", [t["label"] for t in v["tags"]])
        ok = [k for k, x in v["available"].items() if x["ok"]]
        print("available:", ok)

        # 12 時間前から追いつき計算
        st = app.state("hina")
        st["last_tick"] -= 12 * 3600
        st["last_interaction"] -= 12 * 3600
        app.tick("hina")
        print("after 12h:", {k: round(x) for k, x in st["params"].items()})

        r = app.visit()
        print("visit:", r and r["entry"]["text"])
        r = app.act("look")
        print("look:", r["entry"]["text"])
        print("pos:", r["entry"]["pos"][:200])
        for aid in ok[:6]:
            try:
                r = app.act(aid)
                print("%s: %s %s" % (aid, r["entry"]["text"], r["entry"]["deltas"]))
            except ValueError as e:
                print("%s: (不可) %s" % (aid, e))

        if a.comfy_port:
            jid = r["job"] or app.snapshot()["job"]
            for _ in range(60):
                j = app.job_view(jid)
                if j["status"] in ("done", "error"):
                    break
                time.sleep(0.5)
            print("job:", j["status"], j.get("image"), j.get("error"))
            assert j["status"] == "done", j
            assert os.path.exists(store.dpath("images", *j["image"].split("/")))
        print("OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
