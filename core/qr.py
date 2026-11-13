"""QR コード (スマホで開くアドレスを, カメラで読めるように). 追加パッケージなし.

作れるのは小さいものだけ: バイトモード・誤り訂正 L・型番 1〜5 (106 バイトまで. アドレスには足りる). 入りきらなければ None.
matrix(text) は, 黒いマスを 1 とした行のリスト (文字列 "0101…" の並び) を返す. まわりの余白 (4 マス) は描く側で付ける.
決まりは JIS X 0510 (ISO/IEC 18004): 位置合わせ・タイミング・形式情報 (BCH)・リード・ソロモン符号 (GF(256), 0x11D)・
右下からのジグザグ配置・マスク 8 種から罰点の小さいもの.
"""

# 型番 → (データのコード語数, 誤り訂正のコード語数). 誤り訂正 L・ブロックは 1 つ (型番 5 まで)
SPEC = {1: (19, 7), 2: (34, 10), 3: (55, 15), 4: (80, 20), 5: (108, 26)}

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gmul(a, b):
    return 0 if not a or not b else _EXP[_LOG[a] + _LOG[b]]


def rs_remainder(data, n):
    """リード・ソロモンの誤り訂正コード語 n 個 (生成多項式の根は α^0 … α^(n-1))."""
    gen = [1]
    for i in range(n):
        nxt = [0] * (len(gen) + 1)
        for j, g in enumerate(gen):
            nxt[j] ^= g
            nxt[j + 1] ^= _gmul(g, _EXP[i])
        gen = nxt
    rem = [0] * n
    for b in data:
        f = b ^ rem[0]
        rem = rem[1:] + [0]
        for j in range(n):
            rem[j] ^= _gmul(gen[j + 1], f)
    return rem


def codewords(data, version):
    """バイト列を, 型番のデータのコード語にする (モード 0100・文字数 8 ビット・終端・埋め草 0xEC 0x11)."""
    cap = SPEC[version][0]
    bits = [0, 1, 0, 0] + [(len(data) >> i) & 1 for i in range(7, -1, -1)]
    for b in data:
        bits += [(b >> i) & 1 for i in range(7, -1, -1)]
    bits += [0] * min(4, cap * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    out = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    while len(out) < cap:
        out.append(pad[(len(out) - len(bits) // 8) % 2])
    return out


def format_bits(mask):
    """形式情報 15 ビット (誤り訂正 L = 01 と, マスクの番号. BCH(15,5), 0x5412 を重ねる)."""
    d = (1 << 3) | mask
    rem = d
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return ((d << 10) | rem) ^ 0x5412


MASKS = (lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0, lambda x, y: (x + y) % 3 == 0,
         lambda x, y: (x // 3 + y // 2) % 2 == 0, lambda x, y: x * y % 2 + x * y % 3 == 0,
         lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0, lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0)


def _base(version):
    """機能パターン (位置検出・分離・タイミング・位置合わせ・形式情報の場所) を置いた盤と, その場所の印."""
    n = 17 + 4 * version
    m = [[0] * n for _ in range(n)]
    fn = [[False] * n for _ in range(n)]

    def put(x, y, v):
        if 0 <= x < n and 0 <= y < n:
            m[y][x] = 1 if v else 0
            fn[y][x] = True

    for i in range(n):                           # タイミング
        put(6, i, i % 2 == 0)
        put(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):      # 位置検出 (と分離の白)
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                put(cx + dx, cy + dy, max(abs(dx), abs(dy)) not in (2, 4))
    if version >= 2:                             # 位置合わせ (型番 2〜6 は右下に 1 つ)
        c = n - 7
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                put(c + dx, c + dy, max(abs(dx), abs(dy)) != 1)
    for i in range(9):                           # 形式情報の場所 (中身はあとで)
        if not fn[8][i]:
            put(i, 8, 0)
        if not fn[i][8]:
            put(8, i, 0)
    for i in range(8):
        put(n - 1 - i, 8, 0)
        put(8, n - 1 - i, 0)
    put(8, n - 8, 1)                             # いつも黒いマス
    return n, m, fn


def _put_format(m, n, mask):
    bits = format_bits(mask)
    b = lambda i: (bits >> i) & 1                # noqa: E731
    for i in range(6):
        m[i][8] = b(i)
    m[7][8], m[8][8], m[8][7] = b(6), b(7), b(8)
    for i in range(9, 15):
        m[8][14 - i] = b(i)
    for i in range(8):
        m[8][n - 1 - i] = b(i)
    for i in range(8, 15):
        m[n - 15 + i][8] = b(i)
    m[n - 8][8] = 1


def _penalty(m, n):
    """マスクの罰点 (同じ色の並び・2×2 のかたまり・位置検出に似た並び・黒の割合)."""
    p = 0
    for lines in (m, [list(c) for c in zip(*m)]):
        for row in lines:
            run, prev = 0, None
            for v in row:
                if v == prev:
                    run += 1
                else:
                    if run >= 5:
                        p += run - 2
                    run, prev = 1, v
            if run >= 5:
                p += run - 2
            s = "".join(map(str, row))
            p += 40 * (s.count("10111010000") + s.count("00001011101"))
    for y in range(n - 1):
        for x in range(n - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                p += 3
    dark = sum(map(sum, m)) * 100.0 / (n * n)
    p += int(abs(dark - 50) // 5) * 10
    return p


def matrix(text, mask=None):
    """text の QR コード: 行ごとの "0101…" (1 が黒). 入りきらなければ None."""
    data = text.encode("utf-8")
    version = next((v for v in sorted(SPEC) if len(data) <= SPEC[v][0] - 2), None)
    if version is None:
        return None
    cw = codewords(data, version)
    cw = cw + rs_remainder(cw, SPEC[version][1])
    n, base, fn = _base(version)
    i = 0
    for right in range(n - 1, 0, -2):            # 右下から, 2 列ずつ上下に折り返して置く (タイミングの列は飛ばす)
        if right <= 6:
            right -= 1
        for vert in range(n):
            for j in range(2):
                x = right - j
                y = n - 1 - vert if (right + 1) & 2 == 0 else vert
                if not fn[y][x] and i < len(cw) * 8:
                    base[y][x] = (cw[i >> 3] >> (7 - (i & 7))) & 1
                    i += 1
    best = None
    for k in ([mask] if mask is not None else range(8)):
        m = [row[:] for row in base]
        for y in range(n):
            for x in range(n):
                if not fn[y][x] and MASKS[k](x, y):
                    m[y][x] ^= 1
        _put_format(m, n, k)
        pen = _penalty(m, n)
        if best is None or pen < best[0]:
            best = (pen, m)
    return ["".join(map(str, row)) for row in best[1]]
