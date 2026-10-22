"""ミニゲームの単独版 (セリフ・画像なしで, ミニゲームをするだけ). 本体とは別の小さなサーバ.

    python tools/minigame_lab.py [--port 8791] [--host 127.0.0.1] [--no-browser]

- ゲームの中身 (ルール・相手の打ち方) は本体と同じ core/games.py, 画面は本体のゲームタブと同じ static/minigames.js
  (static/minigame_lab.html から使う).
- 本体のデータには触れない: 起動のたびに一時フォルダに使い捨ての世界を作り (KURASHI_DATA), 終わったら消す. data/ には書かない.
- 遊べるかの条件 (機嫌・眠気・間柄など)・クールダウンは無視して, いつでも何度でも遊べる (始めるたびに相手を元気な状態に戻す).
- セリフ・画像・相手の様子のヒントは出さない (応答から除く). 遊ぶたびに変わるのは盤面と結果だけ.
API (本体と同じ形): GET /api/state, POST /api/game/start {game} / /api/game/move {...} / /api/game/quit.
"""
import argparse
import atexit
import json
import os
import shutil
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="kurashi_minigame_lab_")
os.environ["KURASHI_DATA"] = TMP                   # 使い捨ての世界 (本体の data/ は使わない)
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
sys.path.insert(0, BASE)
from core import engine, store  # noqa: E402

STATIC = os.path.join(BASE, "static")
TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".svg": "image/svg+xml", ".png": "image/png"}
OPPONENT = "相手"
KEEP = ("ended", "refused", "error")               # 応答のうち画面に返すもの (セリフ・画像・ヒントは返さない)


class Lab:
    def __init__(self):
        store.DATA = TMP
        self.app = engine.App()
        self.app.save_settings({"auto_generate": False, "llm": {"enabled": False}})
        self.cid = self.app.settings["active_character"]
        self.app.bonds.set_stage(self.cid, "live")

    def _ready(self):
        """相手をいつでも遊べる状態に (元気・眠くない・機嫌が良い・家にいる). 遊ぶたびに同じ条件で."""
        app = self.app
        st = app.state(self.cid)
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": 9e12}
        app.set_params({"mood": 70, "sleepiness": 0, "energy": 90, "affection": 90, "trust": 90, "boredom": 50,
                        "stress": 10, "health": 95, "satiety": 70, "hydration": 70}, self.cid)
        st["cooldowns"] = {}
        app.presence.rec()["mode"] = "none"

    def view(self):
        app = self.app
        with app.lock:
            from datetime import datetime
            char, st = app.char(self.cid), app.state(self.cid)
            gv = app.games.view(char, st, app.context(char, st, datetime.now()))
            for g in gv["list"]:
                g["ok"] = True                  # 条件は無視する
                g["desc"] = (g.get("desc") or "").replace(char.get("name", ""), OPPONENT)
            return {"games": gv, "name": OPPONENT}

    def call(self, what, body):
        app = self.app
        with app.lock:
            g = app.games
            if what == "start":
                self._ready()
                original = [dict(x) for x in app.minigames]
                for x in app.minigames:              # 条件 (require / when) は無視して始める
                    x["require"], x["when"] = "", ""
                try:
                    r = g.start(body["game"], self.cid)
                finally:
                    app.minigames[:] = original
            elif what == "move":
                for x in app.minigames:
                    x["_require"] = x.get("require", "")
                    x["require"] = ""
                try:
                    r = g.move(self.cid, body)
                finally:
                    for x in app.minigames:
                        x["require"] = x.pop("_require", "")
            else:
                r = g.quit(self.cid)
            app.logs[self.cid] = []                  # 記録 (セリフ) は残さない
        return {k: r[k] for k in KEEP if k in r}


LAB = None


def call_api(method, path, body):
    """(応答, 状態コード). 利用者向けのお断り (ValueError) は 400."""
    try:
        if method == "GET" and path == "/api/state":
            return LAB.view(), 200
        if method == "POST" and path in ("/api/game/start", "/api/game/move", "/api/game/quit"):
            out = LAB.call(path.rsplit("/", 1)[1], body or {})
            return dict(out, view=LAB.view()), 200
        return {"error": "見つかりません: %s" % path}, 404
    except (ValueError, KeyError) as e:
        return {"error": str(e)}, 400


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, data, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            return self._json(*call_api("GET", path, None))
        name = "minigame_lab.html" if path in ("/", "/index.html") else path[len("/static/"):] if path.startswith("/static/") else None
        full = os.path.normpath(os.path.join(STATIC, name)) if name else None
        if not full or not full.startswith(STATIC + os.sep) or not os.path.isfile(full):
            return self._send(404, b"not found", "text/plain")
        with open(full, "rb") as f:
            self._send(200, f.read(), TYPES.get(os.path.splitext(full)[1], "application/octet-stream"))

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}
        self._json(*call_api("POST", self.path.split("?")[0], body))


def main():
    global LAB
    ap = argparse.ArgumentParser(description="ミニゲームの単独版 (本体のデータには触れない)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    LAB = Lab()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = "http://%s:%d/" % (a.host, a.port)
    print("ミニゲームの単独版: %s （Ctrl+C で終わる）" % url, flush=True)
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
