"""Tailscale で外から開けるようにする (設定のスイッチ. core/tailnet.py).
本物の tailscale は呼ばない (コマンドの呼び出しを差し替えて, 出力の読み方と呼ぶ引数を確かめる).
- 入っていない / サインインしていない / 止まっている / HTTPS が有効でない: それぞれ理由を出す
- つながっている: スマホで開くアドレス (https://<PC の名前>.<tailnet>.ts.net/phone)
- 出ているか: serve の設定に, このサーバのポートへ渡すものがあるか (ほかのポートの設定は数えない)
- オン: tailscale serve --bg <ポート> / オフ: tailscale serve --https=443 off. 引数は決め打ち (funnel は使わない)
- オン / オフは設定に覚える. オンなら起動のときに出し直す. オフなら起動のときは何も呼ばない
- うまくいかなかったら (返ってこない・エラー), 出力を理由に出す
(一時データ)

    python tools/test_tailnet.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, store, tailnet  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)

STATUS = {"BackendState": "Running", "Self": {"DNSName": "my-pc.tail1234.ts.net.", "HostName": "my-pc"},
          "CertDomains": ["my-pc.tail1234.ts.net"]}
SERVE = {"TCP": {"443": {"HTTPS": True}},
         "Web": {"my-pc.tail1234.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8765"}}}}}


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        T = app.tailnet
        assert T.port == 8765
        calls = []
        world = {"installed": True, "status": dict(STATUS), "serve": {}, "serve_code": 0, "on_code": 0, "on_out": "", "off_code": 0}

        def fake(args, timeout=20):
            calls.append(list(args))
            if not world["installed"]:
                return None, ""
            if args == ["status", "--json"]:
                return 0, json.dumps(world["status"])
            if args == ["serve", "status", "--json"]:
                return world["serve_code"], json.dumps(world["serve"])
            if args[:2] == ["serve", "--bg"]:
                if world["on_code"] == 0:
                    world["serve"] = json.loads(json.dumps(SERVE).replace("8765", args[2]))
                return world["on_code"], world["on_out"]
            if args == ["serve", "--https=443", "off"]:
                if world["off_code"] == 0:
                    world["serve"] = {}
                return world["off_code"], "boom" if world["off_code"] else ""
            raise AssertionError("呼ぶはずのないコマンド: %r" % (args,))
        T.run = fake

        # ---- 1. 入っていない
        world["installed"] = False
        v = T.view()
        assert not v["installed"] and "入っていません" in v["why"] and not v["url"], v
        v = T.set(True)
        assert not v["serving"] and "入っていません" in v["why"]
        world["installed"] = True
        app.save_settings({"remote": {"tailscale": False}})

        # ---- 2. サインインしていない / 止まっている
        world["status"] = {"BackendState": "NeedsLogin"}
        v = T.view()
        assert v["installed"] and not v["running"] and "サインイン" in v["why"], v
        world["status"] = {"BackendState": "Stopped"}
        assert "接続されていません" in T.view()["why"]

        # ---- 3. HTTPS が有効でない: アドレスは出すが, 理由も出す
        world["status"] = dict(STATUS, CertDomains=None)
        v = T.view()
        assert v["running"] and not v["https"] and "HTTPS" in v["why"] and v["url"] == "https://my-pc.tail1234.ts.net/phone", v

        # ---- 4. つながっている・まだ出していない
        world["status"] = dict(STATUS)
        v = T.view()
        assert v == {"installed": True, "running": True, "https": True, "serving": False, "url": "https://my-pc.tail1234.ts.net/phone",
                     "why": None, "wanted": False, "port": 8765}, v
        # ほかのポートへ渡す設定は, 出ていることにしない. 読めない出力・エラーも
        world["serve"] = json.loads(json.dumps(SERVE).replace("8765", "3000"))
        assert not T.view()["serving"]
        world["serve"] = SERVE
        assert T.view()["serving"]
        world["serve_code"] = 1
        assert not T.view()["serving"]
        world["serve_code"], world["serve"] = 0, {}

        # ---- 5. オン: 呼ぶ引数・設定に覚える
        del calls[:]
        v = T.set(True)
        assert ["serve", "--bg", "8765"] in calls and v["serving"] and v["wanted"] and not v["why"], (calls, v)
        assert app.settings["remote"]["tailscale"] is True
        assert not any("funnel" in " ".join(c) for c in calls)
        # ポートが違えば, そのポートで
        T.port = 9000
        world["serve"] = {}
        assert T.set(True)["serving"] and ["serve", "--bg", "9000"] in calls
        T.port = 8765
        world["serve"] = {}

        # ---- 6. オンにできなかった: 出力を理由に
        world["on_code"], world["on_out"] = 1, "Serve is not enabled on your tailnet."
        v = T.set(True)
        assert not v["serving"] and "Serve is not enabled" in v["why"], v
        world["on_code"], world["on_out"] = -1, "To enable, visit: https://login.tailscale.com/f/serve"
        v = T.set(True)
        assert not v["serving"] and "返事が返ってきません" in v["why"] and "login.tailscale.com" in v["why"], v
        world["on_code"], world["on_out"] = 0, ""

        # ---- 7. 起動のとき: 設定がオンなら出し直す. オフなら何も呼ばない
        del calls[:]
        assert T.startup() is None and calls == [["serve", "--bg", "8765"]], calls
        v = T.set(False)
        assert ["serve", "--https=443", "off"] in calls and not v["serving"] and not v["wanted"], (calls, v)
        assert app.settings["remote"]["tailscale"] is False
        del calls[:]
        assert T.startup() is None and calls == [], "オフなら起動のときは何も呼ばない"

        # ---- 8. 止められなかった
        world["serve"], world["off_code"] = SERVE, 1
        v = T.set(False)
        assert v["serving"] and "止められませんでした" in v["why"] and "reset" in v["why"], v

        # ---- 9. 出力の前に注意書きが付いていても読める
        assert tailnet._json('Warning: something\n{"BackendState": "Running"}') == {"BackendState": "Running"}
        assert tailnet._json("not json") is None
        print("ok: Tailscale のスイッチ (状態の読み方・アドレス・呼ぶ引数・起動のとき・うまくいかないとき)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
