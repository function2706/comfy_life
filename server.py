"""Comfy LIFE — ComfyUI 連携の疑似生活アプリ (ローカルサーバ).

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
from datetime import datetime
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


def call_api(method, path, q, body):
    """API を呼んで (応答, 状態コード) を返す. 利用者へのお断り (ValueError: 休憩中・お金が足りない など) は 400 で返し,
    ログは 1 行だけ (トレースバックなし). 見つからないものは 404. 想定外の例外はトレースバックをログに残して 400."""
    try:
        return route(method, path, q, body), 200
    except LookupError as e:
        return {"error": str(e)}, 404
    except ValueError as e:
        APP.logq.put("%s [INFO] お断り %s %s: %s" % (datetime.now().strftime("%m-%d %H:%M:%S"), method, path, e))
        return {"error": str(e)}, 400
    except Exception as e:  # noqa: BLE001
        APP.logq.put("[API ERROR] %s %s: %s\n%s" % (method, path, e, traceback.format_exc().rstrip()))
        return {"error": str(e)}, 400


def route(method, path, q, body):
    a = APP
    cid = (body or {}).get("character") or _q(q, "character")
    if method == "GET":
        if path == "/api/boot":
            return a.boot_view()
        if path == "/api/state":
            return a.state_view(cid, beat=_q(q, "beat") == "1",
                                idle=float(_q(q, "idle")) if _q(q, "idle") not in (None, "") else None)
        if path == "/api/job":
            return a.job_view(_q(q, "id", ""))
        if path == "/api/jobs":
            return a.jobs_view()
        if path == "/api/log":
            return a.log_page(_q(q, "who") or None, int(_q(q, "offset", 0)), int(_q(q, "limit", 60)), _q(q, "images") == "1")
        if path == "/api/album":
            return a.album(cid, _q(q, "key"))
        if path == "/api/prompt":
            return a.prompt_preview(cid)
        if path == "/api/workflow":
            return {"workflow": store.load(store.dpath("workflow.json"))}
        if path == "/api/diary":
            return {"diary": a.solo.diary_list(), "mylog": a.solo.mylog()[-100:]}
        if path == "/api/character":
            c = store.all_characters().get(_q(q, "id", ""))
            if not c:
                raise LookupError("キャラの定義が見つかりません")
            return {"character": c}
        if path == "/api/chats":
            a.deliver_due()             # トークを開いている間も, すぐの返信が届くように
            return {"chats": a.chat.list_view(), "unread": a.chat.unread_total()}
        if path == "/api/chat":
            return a.chat.thread(_q(q, "id", ""))
        if path == "/api/worlds":
            return a.worlds_view()
        if path == "/api/persona":
            return a.persona_full(_q(q, "id", ""))
    else:
        b = body or {}
        if path == "/api/act":
            return a.act(b["action"], cid, opts={"place": b["place"]} if b.get("place") else None)
        if path == "/api/dress":
            return a.act("_dress", cid, dress=b.get("outfit") or "")
        if path == "/api/game/start":
            return a.games.start(b["game"], cid)
        if path == "/api/game/move":
            return a.games.move(cid, b)
        if path == "/api/game/quit":
            return a.games.quit(cid)
        if path == "/api/persona/save":
            return {"persona": a.save_persona(b["persona"])}
        if path == "/api/persona/reset":
            return a.reset_persona(b["id"])
        if path == "/api/events/force":
            return {"event": a.force_event(b["id"], cid)}
        if path == "/api/events":
            return {"events": a.save_events(b["events"])}
        if path == "/api/minigames":
            return {"minigames": a.save_minigames(b["minigames"])}
        if path == "/api/presence/back":
            return a.come_back(cid)
        if path == "/api/approach":
            return a.answer_approach(b["answer"], cid)
        if path == "/api/solo/start":
            return a.solo.start(b["kind"], b.get("skill"), b.get("place"), cid)
        if path == "/api/medicine":
            with a.lock:
                return a.body.medicine()
        if path == "/api/meal":
            with a.lock:
                return {"meal": a.body.eat(b["how"], b["id"])}
        if path == "/api/shop/ack":
            return a.solo.shop_ack()
        if path == "/api/solo/move":
            with a.lock:
                return a.solo.move(b["place"])
        if path == "/api/diary/write":
            return {"diary": a.solo.write_diary()}
        if path == "/api/items/list":
            return a.items.set_list(b["id"], int(b.get("qty", 0)))
        if path == "/api/gift":
            return a.give_item(b["item"], cid)
        if path == "/api/chat/send":
            return a.chat.send(b["id"], b["kind"])
        if path == "/api/chat/seen":
            return a.chat.mark_seen(b["id"])
        if path == "/api/offline/ack":
            return a.offline.ack()
        if path == "/api/street":
            return a.street.answer(b["choice"])
        if path == "/api/appoint":
            return a.appoint.propose(b["id"], b["t"], b["place"], b["do"])
        if path == "/api/appoint/answer":
            c = b.get("counter")
            if c:                   # 「別の日時（・行き先）なら」
                return a.appoint.counter(b["id"], c["t"], c.get("place"), c.get("do"))
            return a.appoint.answer(b["id"], bool(b.get("yes")))
        if path == "/api/appoint/go":
            return a.appoint.go(b["id"])
        if path == "/api/street/join":
            return a.street.join(bool(b.get("yes")))
        if path == "/api/encounter/force":
            return {"encounter": a.encounters.happen("out", stranger=b.get("stranger"))}
        if path == "/api/encounter":
            return a.answer_encounter(bool(b.get("yes")))
        if path == "/api/approach/force":
            return a.force_approach(b["id"], cid)
        if path == "/api/approaches":
            return {"approaches": a.save_approaches(b["approaches"])}
        if path == "/api/money/repay":
            return a.repay(b["to"], int(b.get("amount", 0)), cid)
        if path == "/api/market/trade":
            return a.trade(b["asset"], int(b["qty"]), cid)
        if path == "/api/earn/parttime/go":
            return a.go_parttime(cid)
        if path == "/api/earn/parttime/apply":
            return a.earn_api("apply", b)
        if path == "/api/earn/parttime/quit":
            return a.earn_api("quit", b)
        if path in ("/api/earn/flea", "/api/earn/flea_cancel", "/api/earn/lotto"):
            return a.earn_api(path.rsplit("/", 1)[1], b)
        if path == "/api/earn/gig":
            return a.earn_api("gig", b)
        if path == "/api/earn/favor":
            return a.earn_api("favor", b)
        if path == "/api/market/order":
            return a.market_order(b["asset"], b.get("side"), int(b.get("qty") or 0), b.get("limit"), b.get("days"))
        if path == "/api/market/cancel":
            return a.market_cancel(b["id"])
        if path == "/api/market/plan":
            return a.market_plan(b.get("asset"), b.get("amount"), b.get("day"), b.get("drop"))
        if path == "/api/task/start":
            return a.task_start(b.get("kind") or "mines", b.get("level") or "easy", cid)
        if path == "/api/task/resume":
            return a.task_resume(b.get("token"))
        if path == "/api/task/move":
            return a.task_move(b["token"], b.get("move") or {})
        if path == "/api/task/finish":
            return a.task_finish(b["token"], cid)
        if path == "/api/image/delete":
            return a.delete_image(b["path"])
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
            return {"character": a.new_character(b.get("name"), b.get("copy_from"), b.get("stage") or "contact",
                                                 b.get("pos"), b.get("persona_id"))}
        if path == "/api/character/define":
            return {"character": a.save_definition(b["data"])}
        if path == "/api/character/place":
            return {"character": a.place_character(b["id"], b.get("stage") or "contact")}
        if path == "/api/character/icon":
            return {"job": a.make_icon(b["id"], force=True)}
        if path == "/api/character/delete":
            return a.delete_character(b["id"])
        if path == "/api/character/select":
            a.select_character(b["id"])
            return {"ok": True}
        if path == "/api/target":
            a.set_target(b["id"])
            return {"ok": True}
        if path == "/api/world/create":
            return a.create_world(b.get("name"), b.get("copy_from") or None)
        if path == "/api/world/switch":
            return a.switch_world(b["id"])
        if path == "/api/world/rename":
            return a.rename_world(b["id"], b.get("name"))
        if path == "/api/world/delete":
            return a.delete_world(b["id"])
        if path == "/api/relations":
            return {"relations": a.save_relations(b["id"], b.get("relations") or {})}
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
        obj, code = call_api(method, u.path, q, body)
        self._json(obj, code)

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
    print("Comfy LIFE: %s で起動しました (Ctrl+C で終了)" % url)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
