"""スマホへの通知 (Web Push). 追加パッケージなし (標準ライブラリだけ).

通知には本文を載せない (合図だけ). 合図を受けたスマホ (static/sw.js) が, 家の PC から届いたものを取りに来て
(GET /api/phone/news), 通知に出す. 取りに来られなければ (圏外・Tailscale が切れている), 「新しいメッセージ」とだけ出す.
- 本文を載せないので, 本文の暗号化 (ECDH + AES-GCM. 標準ライブラリに無い) が要らない
- 本文が, 通知を中継するサーバ (Apple・Google・Mozilla) を通らない. そちらへ送るのは, 署名した送り主の印 (VAPID) だけ

送り主の印 (VAPID. RFC 8292) は ES256 (P-256 の ECDSA + SHA-256) の JWT. 標準ライブラリに楕円曲線が無いので, ここに書く
(署名の乱数は RFC 6979 で決める. 確かめは tools/test_push.py: RFC 6979 の例と, openssl での検証).
鍵と, 通知を受け取る端末 (購読) は data/push.json (全ワールド共通).
"""
import base64
import hashlib
import hmac
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import store

# ---------------------------------------------------------------- P-256 (secp256r1)
P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = P - 3
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
     0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)


def _add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    (x1, y1), (x2, y2) = p, q
    if x1 == x2:
        if (y1 + y2) % P == 0:
            return None
        m = (3 * x1 * x1 + A) * pow(2 * y1, -1, P) % P
    else:
        m = (y2 - y1) * pow(x2 - x1, -1, P) % P
    x3 = (m * m - x1 - x2) % P
    return x3, (m * (x1 - x3) - y1) % P


def _mul(k, p):
    r = None
    while k:
        if k & 1:
            r = _add(r, p)
        p = _add(p, p)
        k >>= 1
    return r


def public_key(d):
    """秘密鍵 d (整数) の公開鍵 (x, y)."""
    return _mul(d, G)


def _rfc6979_k(d, h1):
    """RFC 6979 3.2: 秘密鍵とメッセージのハッシュから決まる署名の乱数 k (SHA-256. qlen = hlen = 256)."""
    x = d.to_bytes(32, "big")
    h = (int.from_bytes(h1, "big") % N).to_bytes(32, "big")
    v, k = b"\x01" * 32, b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        c = int.from_bytes(v, "big")
        if 1 <= c < N:
            return c
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def sign(d, msg):
    """ECDSA (P-256, SHA-256) の署名 (r, s)."""
    h1 = hashlib.sha256(msg).digest()
    z = int.from_bytes(h1, "big")
    while True:
        k = _rfc6979_k(d, h1)
        r = _mul(k, G)[0] % N
        s = pow(k, -1, N) * (z + r * d) % N
        if r and s:
            return r, s
        h1 = hashlib.sha256(h1).digest()        # まず起きない (r か s が 0)


def verify(pub, msg, r, s):
    if not (1 <= r < N and 1 <= s < N):
        return False
    z = int.from_bytes(hashlib.sha256(msg).digest(), "big")
    w = pow(s, -1, N)
    pt = _add(_mul(z * w % N, G), _mul(r * w % N, pub))
    return pt is not None and pt[0] % N == r


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def pub_bytes(pub):
    """公開鍵の, 圧縮しない形 (65 バイト. 画面の applicationServerKey と, 送るときの k=)."""
    return b"\x04" + pub[0].to_bytes(32, "big") + pub[1].to_bytes(32, "big")


def vapid_jwt(d, aud, sub, exp):
    head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    body = b64u(json.dumps({"aud": aud, "exp": int(exp), "sub": sub}, separators=(",", ":")).encode())
    r, s = sign(d, (head + "." + body).encode("ascii"))
    return head + "." + body + "." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


# ---------------------------------------------------------------- 送る
# 通知を中継するサーバ (ブラウザが決める) だけに送る. それ以外の送り先は受け付けない
HOSTS = ("fcm.googleapis.com", ".push.apple.com", ".push.services.mozilla.com", ".notify.windows.com")
SUB_DEFAULT = "mailto:comfy-life@example.com"       # 送り主の連絡先 (VAPID の sub). 個人の情報は入れない (設定 remote.push_sub で変えられる)
MIN_GAP = 20                                         # 同じ端末への合図は, これより詰めない (続けて届いても通知は 1 つで足りる)


def host_ok(endpoint):
    u = urllib.parse.urlparse(endpoint or "")
    h = (u.hostname or "").lower()
    return u.scheme == "https" and any(h == x or (x.startswith(".") and h.endswith(x)) for x in HOSTS)


class Push:
    def __init__(self, app):
        self.app = app
        self._lock = threading.Lock()
        self._q = queue.Queue()
        self._worker = None
        self._jwt = {}               # 送り先のオリジン → (JWT, 期限)
        self.post = self._post       # テストで差し替える

    def path(self):
        return store.dpath("push.json")

    def rec(self):
        d = store.load(self.path(), None) or {}
        d.setdefault("subs", [])
        return d

    def _save(self, d):
        store.save(self.path(), d)

    def key(self):
        """送り主の鍵 (無ければ作る). (秘密鍵, 公開鍵の base64url)."""
        with self._lock:
            d = self.rec()
            if not d.get("priv"):
                while True:
                    k = int.from_bytes(os.urandom(32), "big")
                    if 1 <= k < N:
                        break
                d["priv"] = "%064x" % k
                d["pub"] = b64u(pub_bytes(public_key(k)))
                self._save(d)
            return int(d["priv"], 16), d["pub"]

    def view(self):
        d = self.rec()
        return {"key": self.key()[1], "count": len(d["subs"]),
                "devices": [{"ua": s.get("ua", ""), "t": s.get("t"), "last": s.get("last"), "err": s.get("err")} for s in d["subs"]]}

    def subscribe(self, sub, ua=""):
        ep = (sub or {}).get("endpoint")
        if not host_ok(ep):
            raise ValueError("この通知の送り先には対応していません")
        with self._lock:
            d = self.rec()
            d["subs"] = [s for s in d["subs"] if s.get("endpoint") != ep]
            d["subs"].append({"endpoint": ep, "ua": str(ua or "")[:120], "t": time.time()})
            del d["subs"][:-10]
            self._save(d)
        return {"ok": True, "count": len(d["subs"])}

    def unsubscribe(self, endpoint):
        with self._lock:
            d = self.rec()
            n = len(d["subs"])
            d["subs"] = [s for s in d["subs"] if s.get("endpoint") != endpoint]
            self._save(d)
        return {"ok": True, "removed": n - len(d["subs"])}

    # ---- 合図を送る (裏のスレッドで. 呼ぶ側は待たない)
    def want(self, now=None):
        """いま通知を送るか: 受け取る端末があり, あなたが家の画面の前にいない (閉じている・外出中・寝ている など)."""
        now = now or time.time()
        if not self.rec()["subs"]:
            return False
        return self.app.presence.at(now) not in ("here",)

    def on_news(self, n):
        """相手の発言が届いた (core/remote.py の note から)."""
        if self.want():
            self.kick()

    def kick(self, force=False):
        self._q.put(bool(force))
        if not self._worker or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._run, daemon=True, name="push")
            self._worker.start()

    def _run(self):
        while True:
            try:
                force = self._q.get(timeout=30)
            except queue.Empty:
                return
            while not self._q.empty():          # たまった分は 1 回にまとめる
                force = self._q.get() or force
            try:
                self.send_all(force)
            except Exception as e:  # noqa: BLE001
                self.app.trace.add("push", "送れなかった: %s: %s" % (type(e).__name__, e))

    def send_all(self, force=False, now=None):
        """受け取る端末すべてに合図を送る. [(送り先のホスト, 状態コード か 例外の文)] を返す."""
        now = now or time.time()
        priv, pub = self.key()
        sub_ = (self.app.settings.get("remote") or {}).get("push_sub") or SUB_DEFAULT
        out, gone = [], []
        for s in list(self.rec()["subs"]):
            ep = s["endpoint"]
            if not force and now - (s.get("last") or 0) < MIN_GAP:
                continue
            u = urllib.parse.urlparse(ep)
            aud = "%s://%s" % (u.scheme, u.netloc)
            jwt, exp = self._jwt.get(aud, (None, 0))
            if exp - now < 3600:
                exp = now + 12 * 3600
                jwt = vapid_jwt(priv, aud, sub_, exp)
                self._jwt[aud] = (jwt, exp)
            try:
                code = self.post(ep, {"Authorization": "vapid t=%s, k=%s" % (jwt, pub), "TTL": "3600", "Urgency": "high",
                                      "Content-Length": "0"})
            except Exception as e:  # noqa: BLE001  (つながらない など)
                code = "%s: %s" % (type(e).__name__, e)
            out.append((u.hostname, code))
            if code in (404, 410):               # もう受け取らない端末 (通知を切った・アプリを消した)
                gone.append(ep)
            with self._lock:
                d = self.rec()
                for x in d["subs"]:
                    if x["endpoint"] == ep:
                        x["last"] = now
                        x["err"] = None if isinstance(code, int) and code < 300 else str(code)[:120]
                d["subs"] = [x for x in d["subs"] if x["endpoint"] not in gone]
                self._save(d)
        if out:
            self.app.trace.add("push", "合図を送った", None, now, result=["%s %s" % o for o in out])
        return out

    @staticmethod
    def _post(endpoint, headers):
        req = urllib.request.Request(endpoint, data=b"", headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
