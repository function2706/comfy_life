"""内職のパズルの単独版 (何度でも続けて遊んで試す). 本体とは別の小さなサーバ.

    python tools/puzzle_lab.py [--port 8790] [--host 127.0.0.1] [--no-browser]

- 盤面の生成と答え合わせは本体と同じ core/puzzles.py, 画面は本体と同じ static/puzzles.js (static/puzzle_lab.html から使う).
- ゲームの状態 (お金・体力・休憩・スキル・ワールドのデータ) には一切触れない. data/ にも書かない (盤面はメモリだけ).
- できること: 種類と難しさを選んで何度でも続けて遊ぶ, すぐ新しい盤面, 答えを表示, かかった時間・ミス・本体ならいくら稼げたか
  (仕事スキルを入れて試算), 乱数の種 (seed) を指定して同じ盤面を出す.
API (本体の内職と同じ形): POST /api/task/start {kind, level, seed?, skill?} / /api/task/move {token, move} /
/api/task/answer {token} / /api/task/finish {token}, GET /api/catalog.
"""
import argparse
import json
import os
import random
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from core import puzzles  # noqa: E402
from core.life import skill_mult_of  # noqa: E402

STATIC = os.path.join(BASE, "static")
TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".svg": "image/svg+xml", ".png": "image/png"}


class Lab:
    """盤面 (token -> {puzzle, rng, t0, seed, skill, finished}). メモリだけ."""

    def __init__(self):
        self.games = {}
        self.lock = threading.Lock()

    def _info(self, token):
        g = self.games[token]
        pz = g["puzzle"]
        k, lv = pz["kind"], pz["level"]
        base = puzzles.base_pay(k, lv) * skill_mult_of(g["skill"])
        return {"token": token, "view": puzzles.view(pz), "name": puzzles.KINDS[k], "level_name": puzzles.LEVEL_LABEL[lv],
                "desc": puzzles.DESC[k], "par": puzzles.PAR[k][lv], "base": int(round(base / 10.0)) * 10,
                "elapsed": round(time.time() - g["t0"], 1), "seed": g["seed"], "skill": g["skill"]}

    def start(self, kind, level, seed=None, skill=10):
        seed = int(seed) if seed not in (None, "") else random.randrange(1, 10 ** 9)
        rng = random.Random(seed)
        pz = puzzles.new(kind, level, rng)
        token = uuid.uuid4().hex[:10]
        with self.lock:
            now = time.time()
            self.games = {k: v for k, v in self.games.items() if now - v["t0"] < 6 * 3600}
            self.games[token] = {"puzzle": pz, "rng": rng, "t0": now, "seed": seed,
                                 "skill": max(0.0, min(100.0, float(skill or 0))), "finished": False}
        return self._info(token)

    def _get(self, token):
        g = self.games.get(token)
        if not g:
            raise ValueError("盤面が見つかりません（新しい盤面を出してください）")
        return g

    def move(self, token, mv):
        with self.lock:
            g = self._get(token)
            if g["finished"]:
                raise ValueError("もう終わった盤面です")
            r = puzzles.move(g["puzzle"], mv, g["rng"])
            return dict(r, view=puzzles.view(g["puzzle"]), sec=round(time.time() - g["t0"], 1))

    def answer(self, token):
        """答えを表示 (その盤面はおしまい. 稼ぎの試算は解けなかった扱い)."""
        with self.lock:
            g = self._get(token)
            pz = g["puzzle"]
            if pz["kind"] == "mines" and pz["mines"] is None:          # まだ一手も打っていない: 地雷を置いてから見せる
                puzzles.move(pz, {"r": pz["h"] // 2, "c": pz["w"] // 2}, g["rng"])
            return {"view": puzzles.view(pz, reveal=True)}

    def finish(self, token):
        """終える (解けていても, やめても). 本体ならいくら稼げたかの試算 (お金・体力・休憩には触れない)."""
        with self.lock:
            g = self._get(token)
            g["finished"] = True
            pz = g["puzzle"]
            sec = time.time() - g["t0"]
            solved = puzzles.solved(pz)
            return {"task": {"solved": solved, "fast": puzzles.fast(pz, sec), "miss": pz["miss"], "sec": round(sec),
                             "pay": puzzles.pay(pz, sec, skill_mult_of(g["skill"])), "kind": pz["kind"], "level": pz["level"],
                             "seed": g["seed"], "par": puzzles.PAR[pz["kind"]][pz["level"]],
                             "view": puzzles.view(pz, reveal=not solved)}}


LAB = Lab()


def call_api(method, path, body):
    """(応答, 状態コード). 利用者向けのお断り (ValueError) は 400."""
    b = body or {}
    try:
        if method == "GET" and path == "/api/catalog":
            return dict(puzzles.catalog(), rate=puzzles.RATE_PER_MIN, bonus=puzzles.LEVEL_BONUS), 200
        if method == "POST" and path == "/api/task/start":
            return LAB.start(b.get("kind") or "mines", b.get("level") or "easy", b.get("seed"), b.get("skill", 10)), 200
        if method == "POST" and path == "/api/task/move":
            return LAB.move(b["token"], b.get("move") or {}), 200
        if method == "POST" and path == "/api/task/answer":
            return LAB.answer(b["token"]), 200
        if method == "POST" and path == "/api/task/finish":
            return LAB.finish(b["token"]), 200
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
        name = "puzzle_lab.html" if path in ("/", "/index.html") else path[len("/static/"):] if path.startswith("/static/") else None
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
    ap = argparse.ArgumentParser(description="内職のパズルの単独版 (本体のデータには触れない)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = "http://%s:%d/" % (a.host, a.port)
    print("内職のパズルの単独版: %s （Ctrl+C で終わる）" % url, flush=True)
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
