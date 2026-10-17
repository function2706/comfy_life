"""くらし — ComfyUI 連携の疑似生活アプリ (ローカルサーバ).

    python server.py [--host 127.0.0.1] [--port 8765] [--no-browser]
"""
import argparse
import json
import mimetypes
import os
import sys
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import comfy, engine, llm, store  # noqa: E402

STATIC = os.path.join(store.BASE, "static")
APP = None


def _safe_join(root, rel):
    full = os.path.normpath(os.path.join(root, *[p for p in rel.split("/") if p]))
    if not full.startswith(os.path.normpath(root) + os.sep):
        return None
    return full


def _q(q, k, default=None):
    v = q.get(k)
    return v[0] if v else default


def route(method, path, q, body):
    a = APP
    cid = (body or {}).get("character") or _q(q, "character")
    if method == "GET":
        if path == "/api/boot":
            return a.boot_view()
        if path == "/api/state":
            return a.state_view(cid)
        if path == "/api/job":
            return a.job_view(_q(q, "id", ""))
        if path == "/api/jobs":
            return a.jobs_view()
        if path == "/api/log":
            return a.log_page(cid, int(_q(q, "offset", 0)), int(_q(q, "limit", 60)), _q(q, "images") == "1")
        if path == "/api/prompt":
            return a.prompt_preview(cid)
        if path == "/api/workflow":
            return {"workflow": store.load(store.dpath("workflow.json"))}
    else:
        b = body or {}
        if path == "/api/act":
            return a.act(b["action"], cid)
        if path == "/api/dress":
            return a.act("_dress", cid, dress=b.get("outfit") or "")
        if path == "/api/reroll":
            return a.reroll(b["entry"], cid)
        if path == "/api/visit":
            return {"result": a.visit(cid)}
        if path == "/api/generate":
            return a.snapshot(cid, b.get("pos"), b.get("neg"), b.get("seed"), b.get("entry"))
        if path == "/api/job/cancel":
            return a.cancel_job(b.get("id"), bool(b.get("all")))
        if path == "/api/settings":
            return {"settings": a.save_settings(b["settings"])}
        if path == "/api/character/save":
            return {"character": a.save_character(b["data"])}
        if path == "/api/character/new":
            return {"character": a.new_character(b.get("name"), b.get("copy_from"))}
        if path == "/api/character/delete":
            a.delete_character(b["id"])
            return {"ok": True}
        if path == "/api/character/select":
            a.select_character(b["id"])
            return {"ok": True}
        if path == "/api/actions":
            return {"actions": a.save_actions(b["actions"])}
        if path == "/api/params":
            return {"params": a.save_params(b["params"])}
        if path == "/api/world":
            return {"world": a.save_world(b["world"])}
        if path == "/api/workflow":
            return {"placeholders": a.save_workflow(b["workflow"])}
        if path == "/api/state/set":
            a.set_params(b["values"], cid)
            return {"ok": True}
        if path == "/api/state/reset":
            a.reset_state(cid)
            return {"ok": True}
        if path == "/api/state/clear_override":
            a.clear_override(cid)
            return {"ok": True}
        if path == "/api/comfy/info":
            return comfy.info(b.get("comfy") or a.settings.get("comfy") or {})
        if path == "/api/llm/test":
            cfg = b.get("llm") or a.settings.get("llm") or {}
            return {"text": llm.chat(cfg, "あなたは短く返事をするアシスタントです。", "「こんにちは」に一言で返して。")}
    raise LookupError("not found: %s %s" % (method, path))


class Handler(BaseHTTPRequestHandler):
    server_version = "kurashi/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, data, ctype, cache=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _file(self, full, cache=False):
        if not full or not os.path.isfile(full):
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype, cache)

    def _api(self, method):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        body = None
        if method == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}
        try:
            self._json(route(method, u.path, q, body))
        except LookupError as e:
            self._json({"error": str(e)}, 404)
        except Exception as e:  # noqa: BLE001
            APP.logq.put("[API ERROR] %s %s: %s\n%s" % (method, u.path, e, traceback.format_exc().rstrip()))
            self._json({"error": str(e)}, 400)

    def do_GET(self):
        p = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
        if p.startswith("/api/"):
            return self._api("GET")
        if p in ("/", "/index.html"):
            return self._file(os.path.join(STATIC, "index.html"))
        if p.startswith("/static/"):
            return self._file(_safe_join(STATIC, p[len("/static/"):]))
        if p.startswith("/images/"):
            return self._file(_safe_join(store.dpath("images"), p[len("/images/"):]), cache=True)
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self._api("POST")
        self._send(404, b"not found", "text/plain")


def main():
    global APP
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 8765))
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    APP = engine.App()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    url = "http://%s:%d/" % ("127.0.0.1" if args.host in ("0.0.0.0", "") else args.host, args.port)
    print("くらし: %s で起動しました (Ctrl+C で終了)" % url)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
