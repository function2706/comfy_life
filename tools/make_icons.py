"""スマホ用の入り口のアイコン (ホーム画面・通知) を作る. 標準ライブラリだけで PNG を書く.

    python tools/make_icons.py        # static/img/icon-{180,192,512}.png と icon-badge.png

絵: 濃い紫の地に, 吹き出し (トークのしるし). ふちまで地の色で塗る (maskable: 端末が丸や角丸に切り抜く).
icon-badge.png は通知の小さな印 (Android. 白い形だけ・透明の地).
"""
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "static", "img")
BG = (27, 23, 34)
BUBBLE = (255, 143, 177)
DOT = (27, 23, 34)


def png(path, w, h, px):
    """px: [(r, g, b, a)] を左上から."""
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw.extend(px[y * w + x])

    def chunk(kind, data):
        c = kind + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def in_bubble(u, v):
    """吹き出しの形 (u, v は 0〜1). 角丸の四角 + 左下のしっぽ."""
    x0, y0, x1, y1, r = 0.24, 0.27, 0.76, 0.64, 0.10
    cx = min(max(u, x0 + r), x1 - r)
    cy = min(max(v, y0 + r), y1 - r)
    if (u - cx) ** 2 + (v - cy) ** 2 <= r * r:
        return True
    # しっぽ: (0.34, 0.62) (0.50, 0.62) (0.33, 0.77) の三角
    ax, ay, bx, by, cx2, cy2 = 0.34, 0.62, 0.50, 0.62, 0.33, 0.77
    d1 = (u - bx) * (ay - by) - (ax - bx) * (v - by)
    d2 = (u - cx2) * (by - cy2) - (bx - cx2) * (v - cy2)
    d3 = (u - ax) * (cy2 - ay) - (cx2 - ax) * (v - ay)
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def in_dot(u, v):
    return any((u - x) ** 2 + (v - 0.455) ** 2 <= 0.034 ** 2 for x in (0.38, 0.50, 0.62))


def render(size, badge=False, ss=3):
    px = []
    n = float(size * ss)
    for y in range(size):
        for x in range(size):
            bub = dot = 0
            for sy in range(ss):
                for sx in range(ss):
                    u, v = (x * ss + sx + 0.5) / n, (y * ss + sy + 0.5) / n
                    if in_bubble(u, v):
                        bub += 1
                        if in_dot(u, v):
                            dot += 1
            a, d = bub / float(ss * ss), dot / float(ss * ss)
            if badge:                               # 白い形・透明の地 (点は抜く)
                px.append((255, 255, 255, int(round(255 * max(0.0, a - d)))))
                continue
            col = [BG[i] * (1 - a) + BUBBLE[i] * a for i in range(3)]
            col = [col[i] * (1 - d) + DOT[i] * d for i in range(3)]
            px.append((int(round(col[0])), int(round(col[1])), int(round(col[2])), 255))
    return px


def main():
    os.makedirs(OUT, exist_ok=True)
    for size in (180, 192, 512):
        png(os.path.join(OUT, "icon-%d.png" % size), size, size, render(size))
    png(os.path.join(OUT, "icon-badge.png"), 96, 96, render(96, badge=True))
    print("ok: icon-180.png icon-192.png icon-512.png icon-badge.png → %s" % OUT)


if __name__ == "__main__":
    main()
