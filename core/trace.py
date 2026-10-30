"""判断の記録 (トレース): 裏で決めたこと (返信するか・遅れ・既読だけ・働きかけの抽せん・謝罪/お礼/連絡の多さ・閉じていた間の過ごし方・
約束と頼まれごとの状態) を, 時刻つきで 1 件ずつ残す. 不具合を報告するときの書き出し (core/debugdump.py) のもと.

- ワールドごと (worlds/<id>/trace.dat). 1 件 1 行. 古いもの (KEEP_DAYS より前) と, 上限 (MAX_LINES) を超えた分は捨てる.
- 遊ぶ人がうっかり見てしまわないように (チートにならないように), ディスク上は読めない形: JSON → zlib → 固定の鍵で XOR → base64.
  本当に秘密にするものではない (コードは手元にある). 画面にもサーバのログにも, 中身は出さない.
- 書けなくても遊ぶのは止めない (例外は飲み込む).
"""
import base64
import json
import os
import threading
import time
import zlib

from . import store

KEY = b"kurashi/trace:do-not-peek"
MAX_LINES = 20000
KEEP_DAYS = 14
TRIM_EVERY = 300


def _xor(b):
    k = KEY
    return bytes(x ^ k[i % len(k)] for i, x in enumerate(b))


def enc(obj):
    """1 件を 1 行の符号に."""
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(_xor(zlib.compress(raw, 6))).decode("ascii")


def dec(line):
    return json.loads(zlib.decompress(_xor(base64.b64decode(line.strip()))).decode("utf-8"))


LONG = ("tb", "stack")      # トレースバック・スタックは長くても残す (LONG_MAX まで)
LONG_MAX = 4000
ERROR_CATS = ("error", "client")


def _clean(v, n=160):
    if isinstance(v, float):
        return round(v, 3)
    if isinstance(v, dict):
        return {str(k): _clean(x, LONG_MAX if k in LONG else n) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x, n) for x in v][:20]
    if isinstance(v, str) and len(v) > n:
        return v[:n] + "…"
    return v


SKIP_ARGS = ("image", "images", "data", "file", "zip", "values", "items", "actions", "params", "workflow", "prompt", "pos", "neg")


def brief_args(b):
    """操作の引数の要点: 短い値はそのまま, 長い文字列は頭だけ, 一覧は件数, 画像や定義まるごとは省く."""
    out = {}
    for k, v in (b or {}).items():
        if k in SKIP_ARGS:
            out[k] = "(省略)"
        elif isinstance(v, (list, tuple)):
            out[k] = "[%d 件]" % len(v)
        elif isinstance(v, dict):
            out[k] = {kk: vv for kk, vv in v.items() if isinstance(vv, (int, float, bool)) or (isinstance(vv, str) and len(vv) <= 40)} \
                if len(v) <= 8 else "{%d 項目}" % len(v)
        elif isinstance(v, str) and len(v) > 60:
            out[k] = v[:60] + "…"
        else:
            out[k] = v
    return out


class Trace:
    def __init__(self, app):
        self.app = app
        self._n = 0
        self._last = {}
        self._lock = threading.Lock()

    def path(self):
        return store.wpath("trace.dat")

    def add(self, cat, msg, cid=None, t=None, **vals):
        """判断を 1 件残す. cat: msg / deliver / approach / manners / offline / appoint / favor など. vals: 判定に使った値."""
        try:
            rec = {"t": round(float(t or time.time()), 1), "c": cat, "m": msg}
            if cid:
                rec["id"] = cid
            if vals:
                rec["v"] = _clean(vals)
            line = enc(rec) + "\n"
            with self._lock:
                p = self.path()
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "a", encoding="ascii") as f:
                    f.write(line)
                self._n += 1
                if self._n % TRIM_EVERY == 0:
                    self.trim()
        except Exception:  # noqa: BLE001 - 記録できなくても遊ぶのは止めない
            pass

    def error(self, where, exc_text, tb=None, t=None, **vals):
        """例外 (API・生成ワーカー・裏のスレッド) を残す. 書き出しでは, 上限とは別枠のエラーの欄に必ず入る."""
        self.add("error", "%s: %s" % (where, exc_text), t=t, tb=tb, **vals)

    def op(self, path, args, result, t=None):
        """あなたの操作 (状態を変える API). 引数は要点だけ (長いもの・画像は省く)."""
        self.add("op", path, t=t, args=brief_args(args), result=result)

    def every(self, key, sec, now=None):
        """同じ種類の記録を間引く (抽せんの外れなど, 数秒おきに起きるもの). 残してよければ True."""
        now = now or time.time()
        if now - self._last.get(key, 0) < sec:
            return False
        self._last[key] = now
        return True

    def read(self, t0=None, t1=None, cid=None):
        out = []
        try:
            with open(self.path(), encoding="ascii") as f:
                lines = f.readlines()
        except OSError:
            return out
        for ln in lines:
            if not ln.strip():
                continue
            try:
                r = dec(ln)
            except Exception:  # noqa: BLE001 - 壊れた行は飛ばす
                continue
            if (t0 and r["t"] < t0) or (t1 and r["t"] > t1) or (cid and r.get("id") not in (None, cid)):
                continue
            out.append(r)
        return out

    def trim(self, now=None):
        """古いもの・上限を超えた分を捨てる (呼ぶ側でロックを持つ)."""
        now = now or time.time()
        p = self.path()
        try:
            with open(p, encoding="ascii") as f:
                lines = [ln for ln in f.readlines() if ln.strip()]
        except OSError:
            return
        keep = []
        for ln in lines[-MAX_LINES:]:
            try:
                if dec(ln)["t"] >= now - KEEP_DAYS * 86400:
                    keep.append(ln)
            except Exception:  # noqa: BLE001
                continue
        if len(keep) != len(lines):
            with open(p + ".tmp", "w", encoding="ascii") as f:
                f.writelines(keep)
            os.replace(p + ".tmp", p)
