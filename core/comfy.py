"""ComfyUI HTTP API クライアント (標準ライブラリのみ)."""
import copy
import json
import socket
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


# Windows の urllib はシステム (レジストリ) のプロキシ設定を自動で使うため,
# LAN 上の ComfyUI への通信がプロキシに吸われて詰まることがある. 既定は直結.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_SYSTEM = urllib.request.build_opener()


class Cancelled(Exception):
    pass


def _req(url, data=None, timeout=15, raw=False, c=None):
    body, headers = None, {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    opener = _SYSTEM if (c or {}).get("use_proxy") else _DIRECT
    try:
        with opener.open(req, timeout=timeout) as r:
            b = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError("ComfyUI HTTP %d (%s): %s" % (e.code, url, _error_text(e.read().decode("utf-8", "replace"))))
    except urllib.error.URLError as e:
        raise RuntimeError("ComfyUI に接続できません (%s): %s" % (url, e.reason))
    except socket.timeout:
        raise RuntimeError("ComfyUI が %s 秒以内に応答しません (%s)" % (timeout, url))
    except OSError as e:
        raise RuntimeError("ComfyUI との通信に失敗 (%s): %s" % (url, e))
    if raw:
        return b
    try:
        return json.loads(b.decode("utf-8"))
    except ValueError:
        raise RuntimeError("ComfyUI 以外から応答がありました（アドレス/ポート違い、またはプロキシ）: %s → %r"
                           % (url, b[:120].decode("utf-8", "replace")))


def queue_position(c, pid):
    """ComfyUI のキュー上の位置. ('running', 0) / ('pending', n 番目) / (None, None)."""
    q = _req(base_url(c) + "/queue", timeout=10, c=c)
    for item in q.get("queue_running") or []:
        if len(item) > 1 and item[1] == pid:
            return "running", 0
    pending = sorted(q.get("queue_pending") or [], key=lambda x: x[0] if x else 0)
    for i, item in enumerate(pending):
        if len(item) > 1 and item[1] == pid:
            return "pending", i + 1 + len(q.get("queue_running") or [])
    return None, None


def cancel(c, pid):
    """ComfyUI 側のキューから削除し, 実行中なら中断する."""
    b = base_url(c)
    try:
        state, _ = queue_position(c, pid)
        if state == "pending":
            _req(b + "/queue", {"delete": [pid]}, timeout=10, c=c)
        elif state == "running":
            _req(b + "/interrupt", {}, timeout=10, c=c)
    except Exception:  # noqa: BLE001 - 取り消しは best effort
        pass


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
    stats = _req(b + "/system_stats", timeout=5, c=c)
    out = {"ok": True, "url": b, "system": stats.get("system", {}),
           "devices": [d.get("name") for d in stats.get("devices", [])]}
    try:
        ck = _req(b + "/object_info/CheckpointLoaderSimple", c=c)["CheckpointLoaderSimple"]["input"]["required"]
        out["checkpoints"] = _combo(ck.get("ckpt_name"))
        ks = _req(b + "/object_info/KSampler", c=c)["KSampler"]["input"]["required"]
        out["samplers"] = _combo(ks.get("sampler_name"))
        out["schedulers"] = _combo(ks.get("scheduler"))
    except Exception as e:  # noqa: BLE001 - 一覧取得は失敗しても接続自体は成功扱い
        out["warning"] = str(e)
    return out


def save_node(c, images):
    """最終出力ノード. 既定は PreviewImage (ComfyUI の temp に置かれ, ComfyUI 再起動で消える).
    keep_on_server をオンにしたときだけ SaveImage で output/<サブフォルダ> に残す."""
    if c.get("keep_on_server"):
        prefix = (c.get("output_prefix") or "kurashi/kurashi").strip().strip("/") or "kurashi/kurashi"
        return {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": images}}
    return {"class_type": "PreviewImage", "inputs": {"images": images}}


def prepare_custom(wf, c):
    """カスタムワークフローの SaveImage を, 設定に応じて PreviewImage に置き換える.
    戻り値の final は「本来の保存ノード」の id (画像を選ぶときに優先する)."""
    final = [nid for nid, n in wf.items() if n.get("class_type") == "SaveImage"]
    if not c.get("keep_on_server"):
        for nid in final:
            wf[nid] = {"class_type": "PreviewImage", "inputs": {"images": wf[nid].get("inputs", {}).get("images")},
                       "_meta": wf[nid].get("_meta", {})}
    return wf, final


def pick_image(outputs, final):
    """history の outputs から, 保存ノード → output 種別 → その他 の順で 1 枚選ぶ."""
    cands = []
    for nid, out in (outputs or {}).items():
        for i, img in enumerate(out.get("images") or []):
            cands.append(((nid not in final), img.get("type") != "output", i, nid, img))
    if not cands:
        return None
    return sorted(cands, key=lambda x: x[:4])[0][4]


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
        "9": save_node(c, ["8", 0]),
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


def generate(c, pos, neg, seed, custom=None, report=None, cancelled=None):
    """生成して (画像バイト列, 拡張子) を返す.

    report(stage, msg, **extra): 段階の通知. cancelled(): True なら中断.
    timeout_sec は ComfyUI で実行が始まってからの制限. キュー待ちは queue_timeout_sec まで.
    """
    report = report or (lambda *a, **k: None)
    cancelled = cancelled or (lambda: False)
    b = base_url(c)
    if custom:
        wf, final = prepare_custom(fill_placeholders(copy.deepcopy(custom), _values(c, pos, neg, seed)), c)
    else:
        if not c.get("ckpt"):
            raise RuntimeError("チェックポイントが未設定です (設定 → 画像生成)")
        wf, final = builtin_workflow(c, pos, neg, seed), ["9"]

    report("submit", "ComfyUI へ送信: %s/prompt" % b)
    r = _req(b + "/prompt", {"prompt": wf, "client_id": uuid.uuid4().hex}, timeout=30, c=c)
    pid = r.get("prompt_id")
    if not pid:
        raise RuntimeError("ComfyUI がキューに積みませんでした: %s" % _error_text(json.dumps(r)))
    report("comfy_queued", "ComfyUI が受理 prompt_id=%s" % pid, prompt_id=pid)

    run_limit = float(c.get("timeout_sec", 300))
    queue_limit = float(c.get("queue_timeout_sec", 1800))
    t0, run_started, last_state, last_q = time.time(), None, None, 0.0
    while True:
        if cancelled():
            cancel(c, pid)
            raise Cancelled("取り消されました")
        now = time.time()
        if run_started and now - run_started > run_limit:
            cancel(c, pid)
            raise RuntimeError("ComfyUI での生成が %d 秒を超えました（設定のタイムアウトを延ばすか、ComfyUI 側を確認）" % run_limit)
        if not run_started and now - t0 > queue_limit:
            cancel(c, pid)
            raise RuntimeError("ComfyUI のキュー待ちが %d 秒を超えました（ComfyUI が他の生成で混んでいる可能性）" % queue_limit)

        h = _req(b + "/history/" + urllib.parse.quote(pid), timeout=10, c=c)
        ent = h.get(pid)
        if ent:
            st = ent.get("status") or {}
            if st.get("status_str") == "error":
                msgs = []
                for m in st.get("messages", []):
                    if isinstance(m, list) and len(m) > 1 and m[0] == "execution_error":
                        d = m[1]
                        msgs.append("%s (node %s %s)" % (d.get("exception_message", "").strip(),
                                                         d.get("node_id", "?"), d.get("node_type", "")))
                raise RuntimeError("ComfyUI 実行エラー: %s" % (" / ".join(msgs) or "詳細不明"))
            img = pick_image(ent.get("outputs"), final)
            if img:
                report("download", "画像を取得: %s (%s)" % (img["filename"], img.get("type", "output")))
                q = urllib.parse.urlencode({"filename": img["filename"], "subfolder": img.get("subfolder", ""),
                                            "type": img.get("type", "output")})
                data = _req(b + "/view?" + q, timeout=60, raw=True, c=c)
                ext = img["filename"].rsplit(".", 1)[-1].lower() if "." in img["filename"] else "png"
                return data, ext
            if st.get("completed"):
                raise RuntimeError("画像が出力されませんでした (SaveImage/PreviewImage があるか確認)")
        elif now - last_q >= 2.0:
            last_q = now
            try:
                state, pos_ = queue_position(c, pid)
            except RuntimeError:
                state, pos_ = last_state, None
            if state == "running" and not run_started:
                run_started = now
            if state != last_state or state == "pending":
                if state == "running":
                    report("comfy_running", "ComfyUI で生成中", queue_pos=0)
                elif state == "pending":
                    report("comfy_queued", "ComfyUI のキューで %d 番目" % pos_, queue_pos=pos_, quiet=state == last_state)
                elif last_state is not None:
                    report("comfy_running", "ComfyUI のキューから消えた（完了待ち）")
                last_state = state
        time.sleep(1.0)
