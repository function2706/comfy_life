"""ピクロスの問題集 (絵の問題) を defaults/picross_pool.json に書き出す.

    python tools/build_picross_pool.py --font <NotoEmoji[wght].ttf> --names <cldr annotations ja.xml> [--names <annotationsDerived ja.xml>]
                                       [--sheet <見本の画像を出すフォルダ>] [--exclude <除く絵文字 (文字のまま, 空白区切り)>]

ピクロスは答えが絵のパズル. 絵を先に決めて, そこから数字を作る (でたらめな点々の盤は絵にならず, 解いてもうれしくない).
- 絵の元: Noto Emoji (モノクロ版, SIL Open Font License 1.1) の絵文字を大きく描いて, 盤の大きさ (10・15・20) の白黒に縮める.
  答えの名前: Unicode CLDR の日本語の読み上げ名 (Unicode License v3). ライセンスは defaults/picross_LICENSES.txt.
- 一行ずつの理詰め (行・列の数字だけで決まるマスを決めていく) で最後まで解け, 答えが一つに決まる絵だけを使う.
  解き切れない絵は, 決まらないマスを少しだけ (盤の 3% まで) 塗り替えて直す. 直せなければ捨てる.
- 絵として弱いものは捨てる: 塗る割合が極端 (25% 未満・75% 超), 何もない行・列が多い (盤が大きすぎる), 細かい点が散らばる.
  白黒では見分けられない色違い (名前に色が入るもの・肌の色) は使わない. よく似た絵 (違うマスが 12% 以下) は先の一つだけ.
- 難しさの目安: 解き切るまでに全部の行・列を見直した回数 (passes). 多いほど, 行と列を行き来して考える.
- --sheet: 見本の画像 (番号つき) を出す. 目で見て何の絵か分かるものを tools/picross_keep.txt に書き, --keep-file で
  その絵だけで作る (いまの問題集はこれで作った. 縮め方や解く仕組みを変えたら, 見本を見直して一覧を直す).
"""
import argparse
import io
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

from multiprocessing import Pool

from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(BASE, "defaults", "picross_pool.json")
SIZES = {"easy": 10, "mid": 15, "hard": 20}
RENDER = 320
COLOR = re.compile(r"赤|青|黄|緑|紫|茶|黒|白|オレンジ|灰色|ピンク|水色|肌色|色の")
SIMILAR = 0.12            # 違うマスがこれ以下なら, 同じ絵とみなす
REPAIR_TRY = 40           # 手直しで, 一手ごとに試す塗り替えの数 (決まらないマスから)


# ====================================================================== 一行ずつの理詰め
def line_solve(k, cl):
    """行 (列) の今の状態 k (-1 未定 / 0 白 / 1 黒) と数字 cl から, 決まるマスを決めた新しい状態. 矛盾なら None."""
    c = [x for x in cl if x]
    n, m = len(k), len(c)
    fits = [[False] * (n + 1) for _ in range(m)]       # 塊 j を s から置けるか (塊の中に白が無く, すぐ後ろが黒でない)
    for j, L in enumerate(c):
        for s in range(0, n - L + 1):
            if all(k[t] != 0 for t in range(s, s + L)) and (s + L == n or k[s + L] != 1):
                fits[j][s] = True

    def end(s, L):
        return s + L + 1 if s + L < n else n
    fwd = [[False] * (n + 1) for _ in range(m + 1)]
    fwd[0][0] = True
    for i in range(n + 1):
        for j in range(m + 1):
            if not fwd[j][i]:
                continue
            if i < n and k[i] != 1:
                fwd[j][i + 1] = True
            if j < m and i < n and fits[j][i]:
                fwd[j + 1][end(i, c[j])] = True
    bwd = [[False] * (n + 1) for _ in range(m + 1)]
    bwd[m][n] = True
    for i in range(n, -1, -1):
        for j in range(m, -1, -1):
            if i < n and k[i] != 1 and bwd[j][i + 1]:
                bwd[j][i] = True
            if j < m and i < n and fits[j][i] and bwd[j + 1][end(i, c[j])]:
                bwd[j][i] = True
    if not fwd[m][n]:
        return None
    can0, can1 = [False] * n, [False] * n
    for i in range(n):
        for j in range(m + 1):
            if fwd[j][i] and k[i] != 1 and bwd[j][i + 1]:
                can0[i] = True
                break
    for j, L in enumerate(c):
        for s in range(0, n - L + 1):
            if fits[j][s] and fwd[j][s] and bwd[j + 1][end(s, L)]:
                for t in range(s, s + L):
                    can1[t] = True
                if s + L < n:
                    can0[s + L] = True
    out = []
    for i in range(n):
        if not can0[i] and not can1[i]:
            return None
        out.append(k[i] if k[i] >= 0 else (1 if not can0[i] else 0 if not can1[i] else -1))
    return out


def solve(rows, cols):
    """(盤, 見直した回数). 解き切れなければ盤に -1 が残る. 矛盾なら (None, 回数)."""
    h, w = len(rows), len(cols)
    g = [[-1] * w for _ in range(h)]
    dirty_r, dirty_c = set(range(h)), set(range(w))
    passes = 0
    while dirty_r or dirty_c:
        passes += 1
        nr, nc = set(), set()
        for r in sorted(dirty_r):
            new = line_solve(g[r], rows[r])
            if new is None:
                return None, passes
            for c in range(w):
                if new[c] != g[r][c]:
                    g[r][c] = new[c]
                    nc.add(c)
        for c in sorted(dirty_c | nc):
            col = [g[r][c] for r in range(h)]
            new = line_solve(col, cols[c])
            if new is None:
                return None, passes
            for r in range(h):
                if new[r] != col[r]:
                    g[r][c] = new[r]
                    nr.add(r)
        dirty_r, dirty_c = nr, set()
    return g, passes


def clue(line):
    out, run = [], 0
    for x in line:
        if x:
            run += 1
        elif run:
            out.append(run)
            run = 0
    if run:
        out.append(run)
    return out or [0]


def clues_of(bm):
    return [clue(r) for r in bm], [clue([bm[r][c] for r in range(len(bm))]) for c in range(len(bm[0]))]


def unknown(g):
    return sum(1 for row in g for x in row if x < 0)


def repair(bm, max_flips):
    """解き切れない絵を, 決まらないマスを少しずつ塗り替えて直す (一手ごとに, いちばん多くのマスが決まる塗り替えを選ぶ).
    (直した絵, 塗り替えた数, passes) か None."""
    bm = [list(r) for r in bm]
    n = len(bm)
    flips = 0
    while True:
        g, passes = solve(*clues_of(bm))
        if g is not None and not unknown(g):
            return bm, flips, passes
        if flips >= max_flips or g is None:
            return None
        cand = [(r, c) for r in range(n) for c in range(n) if g[r][c] < 0]
        if len(cand) > n * n * 0.4:
            return None                           # 決まらないマスが多すぎる: 少しの手直しでは直らない
        cand = cand[::max(1, len(cand) // REPAIR_TRY)]
        best = None
        for r, c in cand:
            bm[r][c] ^= 1
            g2, _ = solve(*clues_of(bm))
            score = -1 if g2 is None else n * n - unknown(g2)
            bm[r][c] ^= 1
            if best is None or score > best[0]:
                best = (score, r, c)
        if best is None or best[0] < 0:
            return None
        bm[best[1]][best[2]] ^= 1
        flips += 1


# ====================================================================== 絵
def load_names(paths):
    out = {}
    for p in paths:
        for a in ET.parse(p).getroot().iter("annotation"):
            if a.get("type") == "tts" and a.get("cp") and a.get("cp") not in out:
                out[a.get("cp")] = a.text
    return out


def render(font, ch):
    img = Image.new("L", (RENDER * 2, RENDER * 2), 0)
    ImageDraw.Draw(img).text((RENDER // 2, RENDER // 4), ch, font=font, fill=255)
    return img


def to_bitmap(img, n, thr):
    box = img.getbbox()
    if not box:
        return None
    x0, y0, x1, y1 = box
    side = max(x1 - x0, y1 - y0)
    sq = Image.new("L", (side, side), 0)
    sq.paste(img.crop(box), ((side - (x1 - x0)) // 2, (side - (y1 - y0)) // 2))
    small = sq.resize((n, n), Image.BOX)
    px = small.load()
    return [[1 if px[c, r] >= thr * 255 else 0 for c in range(n)] for r in range(n)]


def weak(bm):
    """絵として弱い理由 (無ければ None)."""
    n = len(bm)
    fill = sum(map(sum, bm)) / float(n * n)
    if not 0.25 <= fill <= 0.75:
        return "塗る割合 %.2f" % fill
    empty = sum(1 for r in bm if not any(r)) + sum(1 for c in range(n) if not any(bm[r][c] for r in range(n)))
    if empty > max(1, n // 5):
        return "何もない行・列 %d" % empty
    lone = 0                                     # 周り (縦横) に塗りが無い, ぽつんとした点
    for r in range(n):
        for c in range(n):
            if bm[r][c] and not any(0 <= r + dr < n and 0 <= c + dc < n and bm[r + dr][c + dc]
                                    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                lone += 1
    if lone > n // 5:
        return "ぽつんとした点 %d" % lone
    return None


def candidates(font, names):
    blank = render(font, "\U0010FFFD").tobytes()        # フォントに無い文字の形
    for cp, name in names.items():
        chars = [ch for ch in cp if ch not in ("️", "︎")]
        if len(chars) != 1 or 0x1F1E6 <= ord(chars[0]) <= 0x1F1FF or ord(chars[0]) < 0x2000 or COLOR.search(name or ""):
            continue                                   # 一文字の絵文字だけ (旗・肌の色・つなげた絵文字・記号の数字・色違いなどは除く)
        img = render(font, chars[0])
        if img.tobytes() == blank or not img.getbbox():
            continue
        yield chars[0], name, img


def sheet(items, n, path):
    """見本: 番号つきで並べる (目で見て何の絵か確かめる用)."""
    cols, cell = 10, n * 6 + 30
    rows = (len(items) + cols - 1) // cols
    im = Image.new("RGB", (cols * cell, rows * cell), "white")
    d = ImageDraw.Draw(im)
    for k, it in enumerate(items):
        x0, y0 = (k % cols) * cell, (k // cols) * cell
        for r, row in enumerate(it["bm"]):
            for c, v in enumerate(row):
                if v:
                    d.rectangle([x0 + 4 + c * 6, y0 + 4 + r * 6, x0 + 4 + c * 6 + 5, y0 + 4 + r * 6 + 5], fill="black")
        d.text((x0 + 4, y0 + n * 6 + 8), str(k), fill="red")
    im.save(path)


_FONT = None


def _init(font_path):
    global _FONT
    _FONT = ImageFont.truetype(font_path, RENDER)
    try:
        _FONT.set_variation_by_name("Bold")              # 小さく縮めても形が残るよう, 太め
    except Exception:  # noqa: BLE001 - 太さを変えられないフォントならそのまま
        pass


def make(args):
    """一つの絵文字を n×n の問題に (できなければ (None, 捨てた理由))."""
    ch, name, n = args
    img = render(_FONT, ch)
    why = None
    for thr in (0.45, 0.35, 0.55, 0.3, 0.6):
        bm = to_bitmap(img, n, thr)
        if bm is None:
            return None, "空"
        w = weak(bm)
        if w:
            why = w.split()[0]
            continue
        fixed = repair(bm, max(1, int(n * n * 0.03)))
        if fixed:
            bm, flips, passes = fixed
            return {"ch": ch, "name": re.sub(r"\s+", " ", name or "").strip(), "rows": ["".join(map(str, r)) for r in bm],
                    "passes": passes, "flips": flips, "bm": bm}, None
        why = "解き切れない"
    return None, why


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", required=True)
    ap.add_argument("--names", action="append", required=True)
    ap.add_argument("--sheet")
    ap.add_argument("--exclude", default="", help="除く絵文字 (文字のまま, 空白区切り. 目で見て何の絵か分からないもの)")
    ap.add_argument("--exclude-file", help="除く絵文字を書いたファイル (難しさ<TAB>文字 の行. 難しさが * ならどれでも)")
    ap.add_argument("--keep-file", help="使う絵の一覧 (tools/picross_keep.txt: 難しさ<TAB>絵文字<TAB>名前). 指定するとその絵だけで作る")
    ap.add_argument("--only", default="", help="この大きさだけ作り直す (easy/mid/hard. 空なら全部)")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    _init(a.font)
    names = load_names(a.names)
    src = [(ch, name) for ch, name, _ in candidates(_FONT, names)]
    excl = {"*": set(a.exclude.split())}
    if a.exclude_file:
        for ln in io.open(a.exclude_file, encoding="utf-8"):
            if "\t" in ln:
                lv, ch = ln.rstrip("\n").split("\t", 1)
                excl.setdefault(lv, set()).add(ch.strip())
    keep = None
    if a.keep_file:
        keep = {}
        for ln in io.open(a.keep_file, encoding="utf-8"):
            if ln.startswith("#") or "\t" not in ln:
                continue
            lv, ch = ln.rstrip("\n").split("\t")[:2]
            keep.setdefault(lv, set()).add(ch)
    print("絵文字の候補: %d" % len(src))
    try:
        out = json.load(io.open(DST, encoding="utf-8"))
    except (OSError, ValueError):
        out = {}
    with Pool(a.jobs, initializer=_init, initargs=(a.font,)) as pool:
        for lv, n in SIZES.items():
            if a.only and lv != a.only:
                continue
            todo = [(ch, name, n) for ch, name in src if ch not in excl["*"] and ch not in excl.get(lv, set())
                    and (keep is None or ch in keep.get(lv, set()))]
            got, why = [], {}
            for it, w in pool.map(make, todo, chunksize=4):
                if not it:
                    why[w] = why.get(w, 0) + 1
                    continue
                if any(sum(x != y for ra, rb in zip(it["rows"], g["rows"]) for x, y in zip(ra, rb)) <= n * n * SIMILAR for g in got):
                    why["似た絵"] = why.get("似た絵", 0) + 1
                    continue
                got.append(it)
            print("%s (%d×%d): %d 問 (捨てた理由 %s)" % (lv, n, n, len(got), why), flush=True)
            if a.sheet:
                os.makedirs(a.sheet, exist_ok=True)
                for k in range(0, len(got), 100):
                    sheet(got[k:k + 100], n, os.path.join(a.sheet, "%s_%03d.png" % (lv, k)))
                io.open(os.path.join(a.sheet, "%s_index.txt" % lv), "w", encoding="utf-8").write(
                    "\n".join("%d\t%s\t%s\tpasses=%d\tflips=%d" % (k, it["ch"], it["name"], it["passes"], it["flips"])
                              for k, it in enumerate(got)))
            out[lv] = [{k: v for k, v in it.items() if k != "bm"} for it in got]
            io.open(DST, "w", encoding="utf-8", newline="\n").write(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")
    print("->", DST)


if __name__ == "__main__":
    sys.exit(main())
