"""動作確認用の ComfyUI もどき. 受け取ったプロンプトに応じた色のダミー PNG を返す.

    python tools/mock_comfy.py [--port 8188] [--delay 2] [--fail reject|exec|hang]

--fail で失敗を再現する:
    reject = /prompt を 400 で拒否 (チェックポイント名違いなど)
    exec   = 実行中にエラー
    hang   = いつまでも終わらない (取り消し・タイムアウトの確認用)
"""
import argparse
import hashlib
import json
import struct
import threading
import time
import urllib.parse
import uuid
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HISTORY, IMAGES, RUNNING, SAVED_OUTPUT = {}, {}, set(), []
DELAY = 2.0
FAIL = None


def png(w, h, seed_text):
    d = hashlib.md5(seed_text.encode("utf-8")).digest()
    c1, c2 = d[0:3], d[3:6]
    rows = []
    for y in range(h):
        t = y / max(1, h - 1)
        px = bytes(int(c1[i] * (1 - t) + c2[i] * t) for i in range(3))
        rows.append(b"\x00" + px * w)
    raw = zlib.compress(b"".join(rows), 6)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def run_job(pid, wf):
    RUNNING.add(pid)
    time.sleep(DELAY)
    if FAIL == "hang":
        return
    RUNNING.discard(pid)
    if FAIL == "exec":
        HISTORY[pid] = {"status": {"status_str": "error", "completed": False, "messages": [
            ["execution_error", {"node_id": "3", "node_type": "KSampler",
                                 "exception_message": "mock: CUDA out of memory"}]]}, "outputs": {}}
        return
    texts = [n["inputs"].get("text", "") for n in wf.values() if n.get("class_type") == "CLIPTextEncode"]
    lat = next((n["inputs"] for n in wf.values() if n.get("class_type") == "EmptyLatentImage"), {})
    w, h = int(lat.get("width", 832)) // 4, int(lat.get("height", 1216)) // 4
    data = png(w, h, "|".join(texts))
    outputs = {}
    # 本物の ComfyUI と同じく, SaveImage は output (サブフォルダ可), PreviewImage は temp に置く
    for nid, n in wf.items():
        ct = n.get("class_type")
        if ct not in ("SaveImage", "PreviewImage"):
            continue
        if ct == "SaveImage":
            prefix = n["inputs"].get("filename_prefix", "ComfyUI")
            sub, base = (prefix.rsplit("/", 1) if "/" in prefix else ("", prefix))
            name, typ = "%s_%s.png" % (base, pid[:8]), "output"
            SAVED_OUTPUT.append((sub + "/" if sub else "") + name)
        else:
            sub, name, typ = "", "preview_%s.png" % pid[:8], "temp"
        IMAGES[(typ, sub, name)] = data
        outputs[nid] = {"images": [{"filename": name, "subfolder": sub, "type": typ}]}
    HISTORY[pid] = {"status": {"status_str": "success", "completed": True, "messages": []}, "outputs": outputs}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/system_stats":
            return self._json({"system": {"os": "mock", "comfyui_version": "mock"}, "devices": [{"name": "MockGPU"}]})
        if u.path == "/object_info/CheckpointLoaderSimple":
            return self._json({"CheckpointLoaderSimple": {"input": {"required": {
                "ckpt_name": [["mock_model_a.safetensors", "mock_model_b.safetensors"]]}}}})
        if u.path == "/object_info/KSampler":
            return self._json({"KSampler": {"input": {"required": {
                "sampler_name": [["euler", "euler_ancestral", "dpmpp_2m"]],
                "scheduler": [["normal", "karras"]]}}}})
        if u.path == "/queue":
            return self._json({"queue_running": [[0, p, {}, {}, []] for p in RUNNING], "queue_pending": []})
        if u.path.startswith("/history/"):
            pid = u.path.split("/")[-1]
            return self._json({pid: HISTORY[pid]} if pid in HISTORY else {})
        if u.path == "/mock/saved":     # テスト用: output に保存されたファイルの一覧
            return self._json(SAVED_OUTPUT)
        if u.path == "/view":
            qs = urllib.parse.parse_qs(u.query)
            data = IMAGES.get((qs.get("type", ["output"])[0], qs.get("subfolder", [""])[0], qs.get("filename", [""])[0]))
            if not data:
                return self._json({"error": "no image"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/prompt":
            if FAIL == "reject":
                return self._json({"error": {"message": "Prompt outputs failed validation"}, "node_errors": {
                    "4": {"class_type": "CheckpointLoaderSimple", "errors": [
                        {"message": "Value not in list", "details": "ckpt_name: 'x.safetensors' not in [...]"}]}}}, 400)
            wf = body.get("prompt") or {}
            if not any(v.get("class_type") == "CLIPTextEncode" for v in wf.values()):
                return self._json({"error": {"message": "Prompt has no outputs"}, "node_errors": {}}, 400)
            pid = str(uuid.uuid4())
            threading.Thread(target=run_job, args=(pid, wf), daemon=True).start()
            return self._json({"prompt_id": pid, "number": 0, "node_errors": {}})
        if self.path in ("/interrupt", "/queue"):
            RUNNING.clear()
            return self._json({})
        self._json({"error": "not found"}, 404)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8188)
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--fail", choices=["reject", "exec", "hang"])
    a = ap.parse_args()
    DELAY, FAIL = a.delay, a.fail
    print("mock ComfyUI on http://127.0.0.1:%d (fail=%s)" % (a.port, FAIL))
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
