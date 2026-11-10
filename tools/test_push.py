"""スマホへの通知 (Web Push. A16 の 3 段目. core/push.py).
- 署名 (P-256 の ECDSA + SHA-256. 標準ライブラリだけ): RFC 6979 A.2.5 の例 (公開鍵・乱数 k・署名) と一致. 自前の検証も通る
- openssl があれば, 送り主の印 (JWT) の署名を openssl で検証する (無ければ飛ばす)
- 送り主の印 (VAPID): 見出し・中身 (aud = 送り先のオリジン, exp, sub)・署名 64 バイト
- 通知を受け取る端末: 中継サーバ (Apple・Google・Mozilla・Windows) の https の送り先だけ受け付ける. 同じ送り先は 1 つに
- 合図を送る: 本文なし (Content-Length 0)・Authorization: vapid t=…, k=…. 404 / 410 の端末は消す. 続けては送らない
- 送るのは, あなたが家の画面の前にいないときだけ. 相手の発言が届いたときに (まとめの計算でさかのぼる分は送らない)
- 届いたものの控えを取れる (通知のテストも)
(一時データ. 外へは送らない)

    python tools/test_push.py
"""
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, push, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def der_int(n):
    b = n.to_bytes((n.bit_length() + 8) // 8, "big")
    return b"\x02" + bytes([len(b)]) + b


def openssl_verify(pub, msg, r, s, tmp):
    """openssl で署名を検証する. 検証できたら True / 失敗 False / openssl が無ければ None."""
    exe = shutil.which("openssl")
    if not exe:
        return None
    # SubjectPublicKeyInfo (id-ecPublicKey, prime256v1) + 圧縮しない点
    spki = bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d030107034200") + push.pub_bytes(pub)
    body = der_int(r) + der_int(s)
    sig = b"\x30" + bytes([len(body)]) + body
    pem = os.path.join(tmp, "pub.pem")
    with open(pem, "w") as f:
        f.write("-----BEGIN PUBLIC KEY-----\n%s\n-----END PUBLIC KEY-----\n" % base64.encodebytes(spki).decode().strip())
    for name, data in (("msg.bin", msg), ("sig.der", sig)):
        with open(os.path.join(tmp, name), "wb") as f:
            f.write(data)
    try:
        out = subprocess.run([exe, "dgst", "-sha256", "-verify", pem, "-signature", os.path.join(tmp, "sig.der"), os.path.join(tmp, "msg.bin")],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return b"Verified OK" in out.stdout


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        # ---- 1. 署名: RFC 6979 A.2.5 (P-256, SHA-256, "sample")
        d = 0xC9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721
        pub = push.public_key(d)
        assert pub == (0x60FED4BA255A9D31C961EB74C6356D68C049B8923B61FA6CE669622E60F29FB6,
                       0x7903FE1008B8BC99A41AE9E95628BC64F2F1B20C2D7E9F5177A3C294D4462299), "公開鍵"
        assert push._rfc6979_k(d, hashlib.sha256(b"sample").digest()) == \
            0xA6E3C57DD01ABE90086538398355DD4C3B17AA873382B0F24D6129493D8AAD60, "乱数 k"
        r, s = push.sign(d, b"sample")
        assert r == 0xEFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716
        assert s == 0xF7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8
        r2, s2 = push.sign(d, b"test")
        assert r2 == 0xF1ABB023518351CD71D881567B1EA663ED3EFCF6C5132B354F28D3B0B7D38367
        assert s2 == 0x019F4113742A2B14BD25926B49C649155F267E60D3814B4C0CC84250E46F0083
        assert push.verify(pub, b"sample", r, s) and not push.verify(pub, b"sampl", r, s) and not push.verify(pub, b"sample", r, s + 1)

        # ---- 2. 送り主の印 (JWT)
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("通知")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        P = app.push
        priv, pubkey = P.key()
        assert P.key() == (priv, pubkey), "鍵は一度作ったら同じ"
        pb = unb64(pubkey)
        assert len(pb) == 65 and pb[0] == 4 and pb == push.pub_bytes(push.public_key(priv))
        exp = time.time() + 3600
        jwt = push.vapid_jwt(priv, "https://fcm.googleapis.com", push.SUB_DEFAULT, exp)
        h, b, sg = jwt.split(".")
        assert json.loads(unb64(h)) == {"typ": "JWT", "alg": "ES256"}
        assert json.loads(unb64(b)) == {"aud": "https://fcm.googleapis.com", "exp": int(exp), "sub": push.SUB_DEFAULT}
        raw = unb64(sg)
        assert len(raw) == 64
        jr, js = int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
        assert push.verify(push.public_key(priv), (h + "." + b).encode(), jr, js)
        ov = openssl_verify(push.public_key(priv), (h + "." + b).encode(), jr, js, tmp)
        assert ov is not False, "openssl が署名を認めない"
        assert "@" not in push.SUB_DEFAULT.replace("@example.com", ""), "送り主の連絡先に個人の情報を入れない"

        # ---- 3. 受け取る端末
        for bad in ("http://fcm.googleapis.com/x", "https://example.com/x", "https://evil-push.apple.com.example.org/x", "", None):
            try:
                P.subscribe({"endpoint": bad})
                raise AssertionError("受け付けてはいけない送り先: %r" % (bad,))
            except ValueError:
                pass
        e1, e2 = "https://fcm.googleapis.com/fcm/send/aaa", "https://web.push.apple.com/bbb"
        P.subscribe({"endpoint": e1, "keys": {"p256dh": "x", "auth": "y"}}, "Android")
        P.subscribe({"endpoint": e1}, "Android")
        P.subscribe({"endpoint": e2}, "iPhone")
        v = P.view()
        assert v["count"] == 2 and v["key"] == pubkey and [x["ua"] for x in v["devices"]] == ["Android", "iPhone"], v
        assert "keys" not in json.dumps(P.rec()["subs"]), "端末の暗号の鍵は持たない (本文を送らないので要らない)"

        # ---- 4. 合図を送る (外へは送らず, 送る中身を見る)
        sent = []
        codes = {e1: 201, e2: 201}

        def post(ep, headers):
            sent.append((ep, headers))
            return codes[ep]
        P.post = post
        now = time.time()
        out = P.send_all(now=now)
        assert out == [("fcm.googleapis.com", 201), ("web.push.apple.com", 201)], out
        ep, hd = sent[0]
        assert hd["Content-Length"] == "0" and hd["TTL"] == "3600" and hd["Authorization"].startswith("vapid t="), hd
        t_, k_ = hd["Authorization"][len("vapid "):].split(", ")
        assert k_ == "k=" + pubkey
        assert json.loads(unb64(t_[2:].split(".")[1]))["aud"] == "https://fcm.googleapis.com"
        assert json.loads(unb64(sent[1][1]["Authorization"].split("t=")[1].split(",")[0].split(".")[1]))["aud"] == "https://web.push.apple.com"
        assert P.send_all(now=now + 5) == [], "続けては送らない"
        assert len(P.send_all(force=True, now=now + 5)) == 2, "テストは間を置かずに送る"
        codes[e2] = 410
        P.send_all(now=now + 60)
        assert [x["endpoint"] for x in P.rec()["subs"]] == [e1], "もう受け取らない端末は消す"
        codes[e1] = 403
        P.send_all(now=now + 120)
        assert P.rec()["subs"][0]["err"] == "403", "送れなかったことを残す (端末は消さない)"
        codes[e1] = 201

        # ---- 5. いつ送るか: 家の画面の前にいないときだけ. 相手の発言が届いたときに
        kicks = []
        P.kick = lambda force=False: kicks.append(force)
        p = app.presence.rec()
        p["mode"], p["beat"], p["input"] = "none", time.time(), time.time()
        assert app.presence.at(time.time()) == "here" and not P.want()
        app.chat.add(cid, "her", "📱『いま何してます？』", kind="approach")
        assert kicks == [], "家の画面の前にいる間は送らない"
        assert app.remote.news[-1]["text"] == "いま何してます？" and app.remote.news[-1]["cid"] == cid
        p["beat"] = p["input"] = time.time() - 3600           # 家の画面を閉じている
        assert P.want()
        app.chat.add(cid, "her", "📱『お疲れさまです』", kind="approach")
        assert kicks == [False]
        app.chat.add(cid, "me", "（返した）")
        app.chat.add(cid, "her", "📱『昔の話』", kind="approach", t=time.time() - 3 * 3600)     # まとめの計算でさかのぼって入る
        assert kicks == [False], "あなたの発言・さかのぼって入る分では送らない"
        p["mode"], p["since"], p["beat"] = "out", time.time() - 600, time.time()               # 外出中 (画面は開いている)
        assert P.want()
        P.unsubscribe(e1)
        assert not P.want(), "受け取る端末が無ければ送らない"

        # ---- 6. 届いたものの控え (スマホが取りに来る)
        last = app.remote.news[-1]["id"]
        n = app.remote.add_news("_test", "Comfy LIFE", "通知のテストです")
        assert [x["id"] for x in app.remote.news_since(last)] == [n["id"]]
        print("ok: 通知 (署名は RFC 6979 の例と一致%s・送り主の印・端末・合図・いつ送るか)" % ("・openssl でも検証" if ov else "・openssl は無いので飛ばした"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
