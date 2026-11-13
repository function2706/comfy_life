"""QR コード (core/qr.py. スマホで開くアドレスをカメラで読めるように. 追加パッケージなし).
- 形式情報 (BCH): 誤り訂正 L・マスク 0 は 111011111000100
- リード・ソロモン符号: よく知られた例 (「HELLO WORLD」の型番 1-M のデータ 16 語 → 誤り訂正 10 語)
- 型番は長さで決まる (17 バイトまで 21 マス … 106 バイトまで 37 マス). 入りきらなければ None
- 形: 位置検出 (3 すみ)・タイミング・いつも黒いマス・位置合わせ (型番 2 から)
- 読み戻し: ここに書いた復号 (形式情報を読む → マスクを外す → ジグザグにコード語を取り出す → 誤りが無いことを確かめる →
  バイトに戻す) で, 元の文字列に戻る. マスク 8 種のどれでも. 選ばれるマスクは罰点がいちばん小さいもの
- 設定のスイッチ (core/tailnet.py): 外から開けるときだけ, アドレスの QR を返す
(本物の読み取り機では確かめていない: 開発の PC に読み取る道具が無い. 最後はスマホのカメラで)

    python tools/test_qr.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from core import qr  # noqa: E402


def syndromes_zero(cw, n_ec):
    """受け取ったコード語に誤りが無いか (α^0 … α^(n-1) を入れて 0)."""
    for i in range(n_ec):
        s = 0
        for b in cw:
            s = qr._gmul(s, qr._EXP[i]) ^ b
        if s:
            return False
    return True


def decode(rows):
    """QR を読み戻す (qr.matrix とは別に書いた手順). (文字列, マスクの番号) を返す."""
    n = len(rows)
    version = (n - 17) // 4
    m = [[int(c) for c in r] for r in rows]
    # 形式情報 (左上のまわり): マスクと誤り訂正の水準
    pos = [(8, i) for i in range(6)] + [(8, 7), (8, 8), (7, 8)] + [(14 - i, 8) for i in range(9, 15)]       # (x, y)
    bits = sum(m[y][x] << i for i, (x, y) in enumerate(pos))
    pos2 = [(n - 1 - i, 8) for i in range(8)] + [(8, n - 15 + i) for i in range(8, 15)]
    assert bits == sum(m[y][x] << i for i, (x, y) in enumerate(pos2)), "形式情報の 2 つの写しが食い違う"
    raw = bits ^ 0x5412
    level, mask = raw >> 13, (raw >> 10) & 7
    assert level == 1 and qr.format_bits(mask) == bits, "形式情報 (誤り訂正 L・BCH)"
    # 機能パターンの場所 (データの入らないマス)
    fn = [[False] * n for _ in range(n)]
    for y in range(n):
        for x in range(n):
            if x == 6 or y == 6 or (x < 9 and y < 9) or (x >= n - 8 and y < 9) or (x < 9 and y >= n - 8):
                fn[y][x] = True
            if version >= 2 and abs(x - (n - 7)) <= 2 and abs(y - (n - 7)) <= 2:
                fn[y][x] = True
    data_cw, ec_cw = qr.SPEC[version]
    out, i = [0] * (data_cw + ec_cw), 0
    x = n - 1
    up = True
    while x > 0:
        if x == 6:
            x -= 1
        for y in (range(n - 1, -1, -1) if up else range(n)):
            for xx in (x, x - 1):
                if not fn[y][xx] and i < len(out) * 8:
                    v = m[y][xx] ^ (1 if qr.MASKS[mask](xx, y) else 0)
                    out[i >> 3] |= v << (7 - (i & 7))
                    i += 1
        x -= 2
        up = not up
    assert i == len(out) * 8, "コード語を取り切れていない"
    assert syndromes_zero(out, ec_cw), "誤り訂正の符号が合わない"
    bitstr = "".join("{:08b}".format(b) for b in out[:data_cw])
    assert bitstr[:4] == "0100", "バイトモード"
    ln = int(bitstr[4:12], 2)
    body = bytes(int(bitstr[12 + 8 * k:20 + 8 * k], 2) for k in range(ln))
    return body.decode("utf-8"), mask


def main():
    assert qr.format_bits(0) == 0b111011111000100
    assert qr.rs_remainder([32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17], 10) == \
        [196, 35, 39, 119, 235, 215, 231, 226, 93, 23]
    assert qr.codewords(b"A", 1)[:3] == [0x40, 0x14, 0x10] and qr.codewords(b"A", 1)[3:5] == [0xEC, 0x11] and len(qr.codewords(b"A", 1)) == 19

    url = "https://my-pc.tail1234.ts.net/phone"
    for text, size in (("A", 21), ("a" * 17, 21), ("a" * 18, 25), (url, 29), ("b" * 53, 29), ("b" * 54, 33), ("c" * 78, 33),
                       ("d" * 106, 37), ("日本語のアドレス", 25)):
        rows = qr.matrix(text)
        n = len(rows)
        assert n == size and all(len(r) == n and set(r) <= {"0", "1"} for r in rows), (text[:10], n)
        # 位置検出 (3 すみ): 7×7 の黒い枠と, 中の 3×3
        for ox, oy in ((0, 0), (n - 7, 0), (0, n - 7)):
            got = ["".join(rows[oy + y][ox + x] for x in range(7)) for y in range(7)]
            assert got == ["1111111", "1000001", "1011101", "1011101", "1011101", "1000001", "1111111"], (text[:10], ox, oy, got)
        assert all(rows[6][i] == str((i + 1) % 2) and rows[i][6] == str((i + 1) % 2) for i in range(8, n - 8)), "タイミング"
        assert rows[n - 8][8] == "1", "いつも黒いマス"
        if n > 21:
            c = n - 7
            assert ["".join(rows[c + y][c + x] for x in range(-2, 3)) for y in range(-2, 3)] == ["11111", "10001", "10101", "10001", "11111"]
        got, mask = decode(rows)
        assert got == text, (text[:10], got[:10])
        for k in range(8):                         # どのマスクでも読み戻せる
            assert decode(qr.matrix(text, mask=k)) == (text, k), (text[:10], k)
        pens = []
        for k in range(8):
            r2 = qr.matrix(text, mask=k)
            pens.append(qr._penalty([[int(ch) for ch in r] for r in r2], n))
        assert pens[mask] == min(pens), "罰点のいちばん小さいマスクを選ぶ"
    assert qr.matrix("e" * 107) is None, "入りきらなければ None"

    # 設定のスイッチ: 外から開けるときだけ QR を返す
    import json
    import shutil
    import tempfile
    from core import engine, store
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        st = {"BackendState": "Running", "Self": {"DNSName": "my-pc.tail1234.ts.net."}, "CertDomains": ["my-pc.tail1234.ts.net"]}
        serve = {"Web": {"my-pc.tail1234.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8765"}}}}}
        on = [False]
        app.tailnet.run = lambda args, timeout=20: (0, json.dumps(st if args[0] == "status" else serve if on[0] else {}))
        assert "qr" not in app.tailnet.view(), "出していないときは QR を出さない"
        on[0] = True
        v = app.tailnet.view()
        assert decode(v["qr"])[0] == v["url"] == url, v.get("url")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ok: QR コード (形式情報・誤り訂正・形・読み戻し 9 通り × マスク 8 種・設定のスイッチ)")


if __name__ == "__main__":
    main()
