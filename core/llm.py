"""ローカル LLM (Ollama / OpenAI 互換) によるセリフ生成. 失敗時は呼び出し側で定型文へ戻す."""
import json
import re
import socket
import urllib.error
import urllib.request


# ローカル LLM 向けなので既定はプロキシを通さない (Windows はシステム設定を自動で拾うため)
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_SYSTEM = urllib.request.build_opener()


def _post(url, data, headers=None, timeout=60, use_proxy=False):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=h)
    try:
        with (_SYSTEM if use_proxy else _DIRECT).open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError("LLM HTTP %d: %s" % (e.code, e.read().decode("utf-8", "replace")[:300]))
    except urllib.error.URLError as e:
        raise RuntimeError("LLM に接続できません (%s): %s" % (url, e.reason))
    except socket.timeout:
        raise RuntimeError("LLM が %s 秒以内に応答しません (%s)" % (timeout, url))


def clean(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    text = " ".join(lines[:3])
    text = re.sub(r"^[^「]{0,12}[:：]\s*", "", text)          # 「ひな: 」のような話者名を除去
    if text.startswith("「") and text.endswith("」"):
        text = text[1:-1]
    return text.strip().strip('"')


def chat(cfg, system, user):
    url = (cfg.get("url") or "").rstrip("/")
    model = cfg.get("model") or ""
    temp = float(cfg.get("temperature", 0.8))
    timeout = float(cfg.get("timeout_sec", 60))
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if cfg.get("kind", "ollama") == "ollama":
        j = _post(url + "/api/chat", {"model": model, "messages": msgs, "stream": False,
                                      "options": {"temperature": temp}}, timeout=timeout,
                  use_proxy=cfg.get("use_proxy"))
        return clean(j.get("message", {}).get("content", ""))
    headers = {"Authorization": "Bearer " + cfg["api_key"]} if cfg.get("api_key") else {}
    j = _post(url + "/v1/chat/completions", {"model": model, "messages": msgs, "temperature": temp},
              headers=headers, timeout=timeout, use_proxy=cfg.get("use_proxy"))
    return clean(j["choices"][0]["message"]["content"])
