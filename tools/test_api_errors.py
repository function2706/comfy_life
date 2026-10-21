"""API のお断りとログの確認 (一時データ).
- 利用者へのお断り (ValueError: 休憩中 など) は 400 で返し, ログはトレースバックなしの 1 行
- 想定外の例外はトレースバックをログに残す. 見つからないものは 404
- 内職を始められないときは, 画面に先に理由が出る (state_view.side_job: 休憩の残り・体力不足)

    python tools/test_api_errors.py
"""
import os
import shutil
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


class Capture:
    """ログの行を受け取って取っておく (ログ書き込みのスレッドには渡さない)."""
    def __init__(self):
        self.lines = []

    def put(self, line):
        self.lines.append(line)

    def get(self):
        threading.Event().wait()


def drain(app):
    out, app.logq.lines = app.logq.lines, []
    return out


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        server.APP = app
        app.logq = Capture()
        cid = app.bonds.living()
        app.state(cid)["override"] = {"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": 9e12}
        drain(app)

        # ---- 内職: 始められる → 終える → 休憩中 (画面に先に出る. API はお断りの 1 行)
        assert app.state_view(cid)["side_job"] is None
        tk, code = server.call_api("POST", "/api/task/start", {}, {"kind": "slide", "level": "easy"})
        assert code == 200 and tk["token"]
        server.call_api("POST", "/api/task/finish", {}, {"token": tk["token"]})
        why = app.state_view(cid)["side_job"]
        assert why and "あと" in why["reason"] and 0 < why["wait"] <= 1800, why
        drain(app)
        r, code = server.call_api("POST", "/api/task/start", {}, {"kind": "slide", "level": "easy"})
        logs = drain(app)
        assert code == 400 and "疲れ" in r["error"]
        assert len(logs) == 1 and "[INFO]" in logs[0] and "Traceback" not in logs[0] and "\n" not in logs[0], logs
        # 体力が足りないときも, 先に理由が出る
        app.state(cid)["cooldowns"] = {}
        app.life.player_state()["stamina"] = 3
        assert "体力" in app.state_view(cid)["side_job"]["reason"]
        app.life.player_state()["stamina"] = 100
        assert app.state_view(cid)["side_job"] is None
        print("refusals: OK")

        # ---- 見つからない: 404. 想定外: トレースバックを残す
        r, code = server.call_api("POST", "/api/no/such", {}, {})
        assert code == 404 or code == 400
        real = app.boot_view
        app.boot_view = lambda: 1 / 0
        r, code = server.call_api("GET", "/api/boot", {}, None)
        logs = drain(app)
        assert code == 400 and any("[API ERROR]" in x and "Traceback" in x for x in logs), logs
        app.boot_view = real
        print("unexpected: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
