"""ComfyUI HTTP API クライアント (標準ライブラリのみ)."""
import copy
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

PLACEHOLDERS = ("%POSITIVE%", "%NEGATIVE%", "%SEED%", "%WIDTH%", "%HEIGHT%", "%STEPS%",
                "%CFG%", "%CKPT%", "%SAMPLER%", "%SCHEDULER%")


def base_url(c):
    scheme = "https" if c.get("use_https") else "http"
    return "%s://%s:%s" % (scheme, (c.get("host") or "127.0.0.1").strip(), int(c.get("port") or 8188))


def _error_text(raw):
    try:
        j = json.loads(raw)
    except ValueError:
        return raw[:500]
    msgs = []
    err = j.get("error")
    if isinstance(err, dict):
        msgs.append(err.get("message", ""))
    for nid, ne in (j.get("node_errors") or {}).items():
        for e in ne.get("errors", []):
            msgs.append("node %s (%s): %s %s" % (nid, ne.get("class_type", "?"),
                                                e.get("message", ""), e.get("details", "")))
    return " / ".join(m for m in msgs if m) or raw[:500]


def _req(url, data=None, timeout=15, raw=False):
    body, headers = None, {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError("ComfyUI HTTP %d: %s" % (e.code, _error_text(e.read().decode("utf-8", "replace"))))
    except urllib.error.URLError as e:
        raise RuntimeError("ComfyUI に接続できません (%s): %s" % (url, e.reason))
    return b if raw else json.loads(b.decode("utf-8"))


def _combo(spec):
    """object_info の COMBO 入力から選択肢を取り出す (新旧両形式)."""
    if not spec:
        return []
    if isinstance(spec[0], list):
        return spec[0]
    if len(spec) > 1 and isinstance(spec[1], dict):
        return spec[1].get("options", [])
    return []


def info(c):
    b = base_url(c)
    stats = _req(b + "/system_stats", timeout=5)
    out = {"ok": True, "url": b, "system": stats.get("system", {}),
           "devices": [d.get("name") for d in stats.get("devices", [])]}
    try:
        ck = _req(b + "/object_info/CheckpointLoaderSimple")["CheckpointLoaderSimple"]["input"]["required"]
        out["checkpoints"] = _combo(ck.get("ckpt_name"))
        ks = _req(b + "/object_info/KSampler")["KSampler"]["input"]["required"]
        out["samplers"] = _combo(ks.get("sampler_name"))
        out["schedulers"] = _combo(ks.get("scheduler"))
    except Exception as e:  # noqa: BLE001 - 一覧取得は失敗しても接続自体は成功扱い
        out["warning"] = str(e)
    return out


def builtin_workflow(c, pos, neg, seed):
    clip = ["4", 1]
    wf = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": c.get("ckpt", "")}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": int(c.get("width", 832)), "height": int(c.get("height", 1216)), "batch_size": 1}},
        "3": {"class_type": "KSampler",
              "inputs": {"seed": int(seed), "steps": int(c.get("steps", 28)), "cfg": float(c.get("cfg", 5.5)),
                         "sampler_name": c.get("sampler", "euler_ancestral"), "scheduler": c.get("scheduler", "normal"),
                         "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                         "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "kurashi", "images": ["8", 0]}},
    }
    skip = int(c.get("clip_skip", 1) or 1)
    if skip > 1:
        wf["10"] = {"class_type": "CLIPSetLastLayer", "inputs": {"stop_at_clip_layer": -skip, "clip": ["4", 1]}}
        clip = ["10", 0]
    wf["6"] = {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": clip}}
    wf["7"] = {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": clip}}
    return wf


def _values(c, pos, neg, seed):
    return {"%POSITIVE%": pos, "%NEGATIVE%": neg, "%SEED%": int(seed),
            "%WIDTH%": int(c.get("width", 832)), "%HEIGHT%": int(c.get("height", 1216)),
            "%STEPS%": int(c.get("steps", 28)), "%CFG%": float(c.get("cfg", 5.5)),
            "%CKPT%": c.get("ckpt", ""), "%SAMPLER%": c.get("sampler", "euler_ancestral"),
            "%SCHEDULER%": c.get("scheduler", "normal")}


def fill_placeholders(obj, vals):
    if isinstance(obj, dict):
        return {k: fill_placeholders(v, vals) for k, v in obj.items()}
    if isinstance(obj, list):
        return [fill_placeholders(v, vals) for v in obj]
    if isinstance(obj, str):
        if obj in vals:
            return vals[obj]          # 完全一致は型ごと置換 (数値など)
        for k, v in vals.items():
            if k in obj:
                obj = obj.replace(k, str(v))
    return obj


def validate_workflow(wf):
    """API 形式か確認し, 含まれるプレースホルダを返す."""
    if not isinstance(wf, dict) or not wf:
        raise ValueError("JSON オブジェクトではありません")
    if "nodes" in wf and "links" in wf:
        raise ValueError("UI 形式のワークフローです。ComfyUI で「Export (API)」/「Save (API Format)」した JSON を指定してください")
    for k, v in wf.items():
        if not isinstance(v, dict) or "class_type" not in v:
            raise ValueError("API 形式ではありません (node %s に class_type がない)" % k)
    text = json.dumps(wf, ensure_ascii=False)
    return [p for p in PLACEHOLDERS if p in text]


def generate(c, pos, neg, seed, custom=None):
    """生成して (画像バイト列, 拡張子) を返す."""
    b = base_url(c)
    if custom:
        wf = fill_placeholders(copy.deepcopy(custom), _values(c, pos, neg, seed))
    else:
        if not c.get("ckpt"):
            raise RuntimeError("チェックポイントが未設定です (設定 → 画像生成)")
        wf = builtin_workflow(c, pos, neg, seed)
    r = _req(b + "/prompt", {"prompt": wf, "client_id": uuid.uuid4().hex}, timeout=30)
    pid = r.get("prompt_id")
    if not pid:
        raise RuntimeError("ComfyUI がキューに積みませんでした: %s" % _error_text(json.dumps(r)))
    deadline = time.time() + float(c.get("timeout_sec", 300))
    while time.time() < deadline:
        h = _req(b + "/history/" + urllib.parse.quote(pid), timeout=10)
        ent = h.get(pid)
        if ent:
            st = ent.get("status") or {}
            if st.get("status_str") == "error":
                msgs = [m[1].get("exception_message", "") for m in st.get("messages", [])
                        if isinstance(m, list) and len(m) > 1 and m[0] == "execution_error"]
                raise RuntimeError("ComfyUI 実行エラー: %s" % (" / ".join(msgs) or "詳細不明"))
            imgs = []
            for out in (ent.get("outputs") or {}).values():
                imgs.extend(out.get("images") or [])
            if imgs:
                imgs.sort(key=lambda i: i.get("type") != "output")
                img = imgs[0]
                q = urllib.parse.urlencode({"filename": img["filename"], "subfolder": img.get("subfolder", ""),
                                            "type": img.get("type", "output")})
                data = _req(b + "/view?" + q, timeout=60, raw=True)
                ext = img["filename"].rsplit(".", 1)[-1].lower() if "." in img["filename"] else "png"
                return data, ext
            if st.get("completed"):
                raise RuntimeError("画像が出力されませんでした (SaveImage/PreviewImage があるか確認)")
        time.sleep(1.0)
    raise RuntimeError("生成がタイムアウトしました (%s 秒)" % c.get("timeout_sec", 300))
