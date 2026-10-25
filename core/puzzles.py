"""内職のパズル: マインスイーパ・数独・ピクロス (お絵かきロジック)・スリザーリンク・15 パズル・2048.

- 盤面はサーバで作る (毎回ランダム). 数独とピクロスは解が一つだけになるように, マインスイーパは最初に開けたマスとその周りに
  地雷を置かない. 答え合わせもサーバでする (手をひとつずつ受け取って判定する. 画面の申告は信じない).
- ミス: マインスイーパの爆発 (続けられる)・数独の誤入力 (入らない)・ピクロスの誤りマス (×が付く). 15 パズルにミスはない.
- 稼ぎ (pay): 基本額 × 仕事スキルの倍率 × 速さ (目安の時間 PAR より速ければ 1.2 倍, 2 倍より遅ければ 0.8 倍)
  × ミス (1 回 1 割減, 4 割まで). 基本額は 目安の時間 (分) × 1 分あたりの額 (economy.side_job_rate_per_min) ×
  難しさの上乗せ (LEVEL_BONUS) で, 種類が違っても時間あたりの稼ぎがならされる. 解けずにやめたら, 進んだぶんの 2 割.
- 2048: 難しさは目標のタイル (易 512 / 中 1024 / 難 2048). 盤の大きさ・出るタイルは変えない (変えると別物になる).
  目標に届いたらそこでできあがり. 動かせなくなったら (詰み) そこまで. 元に戻すは無し. 出るタイルはサーバで決める.
  進み具合は最大のタイル (log2(最大) − 2) / (log2(目標) − 2) で, 詰んだ・やめたときはそのぶんの 2 割 (ほかと同じ).
- 一時停止 (pause / resume): 離席用. 止めている間は経過時間に数えず, 盤面も返さない (手も受け付けない).
盤面の状態は App.tasks[token]["puzzle"] (ワールドの tasks.json にも書く. サーバを再起動しても続きから. 1 日で消える).
"""
import math
import random
import threading
import time

from . import slither as SL

KINDS = {"mines": "マインスイーパ", "sudoku": "数独", "picross": "ピクロス", "slither": "スリザーリンク", "slide": "15パズル",
         "g2048": "2048"}
LEVEL_LABEL = {"easy": "易", "mid": "中", "hard": "難"}
DESC = {"mines": "数字は周りの地雷の数。地雷以外を全部開けたらできあがり（右クリック・長押しで旗。旗の数がそろった数字をダブルクリックで周りをまとめて開ける）",
        "sudoku": "縦・横・3×3 のどこにも 1〜9 が一つずつ。間違えた数字は入りません",
        "slither": "点と点の間に線を引いて、全体で一つの輪を作る。数字はそのマスの周りに引く線の数（なぞって線、クリックで×。仮置き・元に戻すも）",
        "picross": "数字は、その列に続けて塗るマスの数。答えどおりに塗れたらできあがり（クリックで塗る・もう一度で消す。右クリック・長押しで×）",
        "slide": "空いているマスの隣を押して動かし、1 から順に並べます",
        "g2048": "矢印キー・WASD・スワイプで全部のタイルを寄せ、同じ数がぶつかると合わさります。目標の数のタイルを作ったらできあがり（動かせなくなったらそこまで）"}
SIZE = {"mines": {"easy": (9, 9, 10), "mid": (12, 12, 24), "hard": (14, 14, 38)},
        "sudoku": {"easy": 38, "mid": 30, "hard": 23},          # 最初から入っている数の目安 (その難しさの解き方で解けなくなる分は残る)
        "picross": {"easy": 5, "mid": 8, "hard": 10},
        "slither": {"easy": (5, 5, 0.55), "mid": (7, 7, 0.3), "hard": (10, 10, 0.0)},   # (縦, 横, 残す数字の割合の下限. 解き方の段は core/slither.py)
        "slide": {"easy": (3, 40), "mid": (4, 80), "hard": (4, 250)},       # (一辺, 崩す手数)
        "g2048": {"easy": 512, "mid": 1024, "hard": 2048}}                  # 目標のタイル (盤は 4×4 のまま)
PAR = {"mines": {"easy": 120, "mid": 300, "hard": 540}, "sudoku": {"easy": 480, "mid": 900, "hard": 1500},
       "picross": {"easy": 120, "mid": 360, "hard": 720}, "slither": {"easy": 150, "mid": 420, "hard": 1080}, "slide": {"easy": 90, "mid": 300, "hard": 480},
       "g2048": {"easy": 300, "mid": 600, "hard": 1200}}        # 2048: 目標が倍になると手数もおよそ倍
RATE_PER_MIN = 50                                       # 目安の時間 1 分あたりの額
LEVEL_BONUS = {"easy": 1.0, "mid": 1.15, "hard": 1.3}     # 難しいほど, 同じ時間でも少し多め
TRAIN = {"easy": 0.8, "mid": 1.2, "hard": 1.6}


# ====================================================================== マインスイーパ
def _nb(r, c, h, w):
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if (dr or dc) and 0 <= r + dr < h and 0 <= c + dc < w:
                yield r + dr, c + dc


def mines_new(level, rng=random):
    h, w, n = SIZE["mines"][level]
    return {"kind": "mines", "h": h, "w": w, "n": n, "mines": None, "open": [], "boom": [], "miss": 0}


def _mines_place(p, r0, c0, rng):
    h, w = p["h"], p["w"]
    safe = {(r0, c0)} | set(_nb(r0, c0, h, w))
    cells = [(r, c) for r in range(h) for c in range(w) if (r, c) not in safe]
    p["mines"] = [list(x) for x in rng.sample(cells, p["n"])]


def mines_count(p, r, c):
    ms = {tuple(x) for x in p["mines"]}
    return sum(1 for x in _nb(r, c, p["h"], p["w"]) if x in ms)


def mines_move(p, mv, rng=random):
    r, c = int(mv["r"]), int(mv["c"])
    if not (0 <= r < p["h"] and 0 <= c < p["w"]):
        raise ValueError("盤の外です")
    if mv.get("chord"):
        return mines_chord(p, r, c, mv.get("flags") or [], rng)
    if p["mines"] is None:
        _mines_place(p, r, c, rng)
    ms = {tuple(x) for x in p["mines"]}
    opened = {tuple(x) for x in p["open"]}
    if (r, c) in opened or [r, c] in p["boom"]:
        return {}
    if (r, c) in ms:                    # 爆発: ミス. そのマスは開いたまま続けられる
        p["boom"].append([r, c])
        p["miss"] += 1
        return {"wrong": True}
    stack = [(r, c)]
    while stack:
        x = stack.pop()
        if x in opened:
            continue
        opened.add(x)
        if mines_count(p, *x) == 0:
            stack.extend(y for y in _nb(x[0], x[1], p["h"], p["w"]) if y not in opened and y not in ms)
    p["open"] = [list(x) for x in sorted(opened)]
    return {}


def mines_chord(p, r, c, flags, rng=random):
    """一括開け: 開いている数字マスの周りに, その数字と同じ数の旗があれば, 旗のない周りのマスをまとめて開ける.
    旗が間違っていれば, 普通に爆発する (ミス). 旗が足りなければ何もしない (short). 旗は画面の側の印なので, 位置を受け取る."""
    if p["mines"] is None or [r, c] not in p["open"]:
        return {}
    num = mines_count(p, r, c)
    fl = {(int(a), int(b)) for a, b in flags} | {(int(a), int(b)) for a, b in p["boom"]}   # 爆発したマスも地雷と分かっている
    around = list(_nb(r, c, p["h"], p["w"]))
    if num == 0 or sum(1 for x in around if x in fl) != num:
        return {"short": True}
    wrong = False
    for y, x in around:
        if (y, x) in fl or [y, x] in p["open"] or [y, x] in p["boom"]:
            continue
        wrong = mines_move(p, {"r": y, "c": x}, rng).get("wrong") or wrong
    return {"wrong": True} if wrong else {}


def mines_solved(p):
    return p["mines"] is not None and len(p["open"]) == p["h"] * p["w"] - p["n"]


def mines_progress(p):
    return len(p["open"]) / float(p["h"] * p["w"] - p["n"])


def mines_view(p, reveal=False):
    grid = [[None] * p["w"] for _ in range(p["h"])]
    for r, c in p["open"]:
        grid[r][c] = mines_count(p, r, c)
    for r, c in p["boom"]:
        grid[r][c] = "*"
    if reveal and p["mines"]:
        for r, c in p["mines"]:
            if grid[r][c] is None:
                grid[r][c] = "m"
    return {"h": p["h"], "w": p["w"], "n": p["n"], "grid": grid}


# ====================================================================== 数独
def _sd_cands(g, i):
    r, c = divmod(i, 9)
    used = set(g[r * 9:r * 9 + 9]) | {g[k * 9 + c] for k in range(9)}
    br, bc = r // 3 * 3, c // 3 * 3
    used |= {g[(br + a) * 9 + bc + b] for a in range(3) for b in range(3)}
    return [v for v in range(1, 10) if v not in used]


def sudoku_count(g, limit=2):
    """解の数 (limit で打ち切り). 候補の少ないマスから埋める."""
    g = list(g)
    count = [0]

    def rec():
        best, bc = None, None
        for i in range(81):
            if not g[i]:
                cs = _sd_cands(g, i)
                if not cs:
                    return
                if best is None or len(cs) < len(bc):
                    best, bc = i, cs
                    if len(cs) == 1:
                        break
        if best is None:
            count[0] += 1
            return
        for v in bc:
            g[best] = v
            rec()
            if count[0] >= limit:
                break
        g[best] = 0
    rec()
    return count[0]


# 人の解き方 (難しさを決める). 易: 一つに決まるマス (候補が一つ・その数が入れるのはそこだけ) だけ.
# 中: 易 + 候補の消し込み (ブロックの中で一列に並ぶ候補・列の中で一つのブロックに収まる候補, 2 つ組 (ペア)).
# 難: 中 + 3 つ組 (トリプル)・X-wing. 当てずっぽう (仮置き) は要らない. どれも正しい推理だけなので, 解き切れれば答えは一つ.
SD_LEVELS = ("easy", "mid", "hard")
_SD_UNITS = ([[r * 9 + c for c in range(9)] for r in range(9)] + [[r * 9 + c for r in range(9)] for c in range(9)] +
             [[(br + a) * 9 + bc + b for a in range(3) for b in range(3)] for br in (0, 3, 6) for bc in (0, 3, 6)])
_SD_PEERS = [sorted({j for u in _SD_UNITS if i in u for j in u} - {i}) for i in range(81)]


def _sd_place(g, cand, i, v):
    g[i] = v
    cand[i] = set()
    for j in _SD_PEERS[i]:
        cand[j].discard(v)


def _sd_singles(g, cand):
    """一つに決まるマスを一つ埋める. 埋めたら True."""
    for i in range(81):
        if not g[i] and len(cand[i]) == 1:
            _sd_place(g, cand, i, next(iter(cand[i])))
            return True
    for u in _SD_UNITS:
        for v in range(1, 10):
            if any(g[i] == v for i in u):
                continue
            where = [i for i in u if not g[i] and v in cand[i]]
            if len(where) == 1:
                _sd_place(g, cand, where[0], v)
                return True
    return False


def _sd_drop(cand, cells, vals):
    hit = False
    for i in cells:
        if cand[i] & vals:
            cand[i] -= vals
            hit = True
    return hit


def _sd_locked(g, cand):
    """ブロックと行・列の重なり: 一方の中で候補がもう一方に収まれば, もう一方の残りから消す."""
    boxes, lines = _SD_UNITS[18:], _SD_UNITS[:18]
    for b in boxes:
        for ln in lines:
            inter = set(b) & set(ln)
            if len(inter) != 3:
                continue
            for v in range(1, 10):
                in_b = {i for i in b if v in cand[i]}
                in_l = {i for i in ln if v in cand[i]}
                if in_b and in_b <= inter and _sd_drop(cand, in_l - inter, {v}):
                    return True
                if in_l and in_l <= inter and _sd_drop(cand, in_b - inter, {v}):
                    return True
    return False


def _sd_subsets(g, cand, k):
    """k 個のマスに k 個の候補だけ (naked) / k 個の候補が k 個のマスにだけ (hidden)."""
    from itertools import combinations
    for u in _SD_UNITS:
        empty = [i for i in u if not g[i]]
        if len(empty) <= k:
            continue
        for cs in combinations(empty, k):
            vals = set().union(*(cand[i] for i in cs))
            if len(vals) == k and _sd_drop(cand, [i for i in empty if i not in cs], vals):
                return True
        missing = [v for v in range(1, 10) if not any(g[i] == v for i in u)]
        for vs in combinations(missing, k):
            cells = [i for i in empty if cand[i] & set(vs)]
            if len(cells) == k:
                hit = False
                for i in cells:
                    if cand[i] - set(vs):
                        cand[i] &= set(vs)
                        hit = True
                if hit:
                    return True
    return False


def _sd_xwing(g, cand):
    from itertools import combinations
    for rows_first in (True, False):
        for v in range(1, 10):
            pos = {}
            for a in range(9):
                cells = [(a * 9 + b if rows_first else b * 9 + a) for b in range(9)]
                bs = tuple(b for b, i in zip(range(9), cells) if v in cand[i])
                if len(bs) == 2:
                    pos[a] = bs
            for a1, a2 in combinations(sorted(pos), 2):
                if pos[a1] == pos[a2]:
                    others = [(a * 9 + b if rows_first else b * 9 + a) for b in pos[a1] for a in range(9) if a not in (a1, a2)]
                    if _sd_drop(cand, others, {v}):
                        return True
    return False


def sudoku_human(puz, level="hard"):
    """その難しさの解き方だけで解き切れれば答え, だめなら None."""
    g = list(puz)
    cand = [set() if g[i] else set(_sd_cands(g, i)) for i in range(81)]
    lv = SD_LEVELS.index(level)
    steps = [_sd_singles]
    if lv >= 1:
        steps += [_sd_locked, lambda g, c: _sd_subsets(g, c, 2)]
    if lv >= 2:
        steps += [lambda g, c: _sd_subsets(g, c, 3), _sd_xwing]
    while not all(g):
        if any(not g[i] and not cand[i] for i in range(81)):
            return None
        if not any(f(g, cand) for f in steps):
            return None
    return g


def sudoku_grade(puz):
    for lv in SD_LEVELS:
        if sudoku_human(puz, lv):
            return lv
    return None


def _sd_full(rng):
    g = [0] * 81

    def rec(i):
        if i == 81:
            return True
        cs = _sd_cands(g, i)
        rng.shuffle(cs)
        for v in cs:
            g[i] = v
            if rec(i + 1):
                return True
        g[i] = 0
        return False
    rec(0)
    return g


def sudoku_new(level, rng=random, tries=None):
    """その難しさの解き方 (sudoku_human) で解き切れるあいだ, 数字を抜く (目安の数まで). 中・難は易の解き方 (一つに決まるマス)
    だけでは解けない盤にする (目安まで抜いてもまだ易で解けるなら 4 つまで多めに抜く. tries 回作って見つからなければ最後のもの).
    難の解き方 (トリプル・X-wing) が要る盤は作ってみてもまれなので, 難は数字の少なさと中の解き方で難しくなる."""
    target = SIZE["sudoku"][level]
    tries = tries or {"easy": 1, "mid": 12, "hard": 8}[level]
    for _ in range(tries):
        sol = _sd_full(rng)
        puz = list(sol)
        cells = list(range(81))
        rng.shuffle(cells)
        givens = 81
        for i in cells:
            if givens <= target and (level == "easy" or givens <= target - 4 or not sudoku_human(puz, "easy")):
                break
            v, puz[i] = puz[i], 0
            if sudoku_human(puz, level):
                givens -= 1
            else:
                puz[i] = v
        if level == "easy" or not sudoku_human(puz, "easy"):
            break
    return {"kind": "sudoku", "puzzle": puz, "solution": sol, "cur": list(puz), "miss": 0}


def sudoku_move(p, mv, rng=random):
    r, c, v = int(mv["r"]), int(mv["c"]), int(mv["v"])
    i = r * 9 + c
    if not (0 <= i < 81) or not 1 <= v <= 9:
        raise ValueError("入れられない数です")
    if p["puzzle"][i] or p["cur"][i]:
        return {}
    if p["solution"][i] != v:
        p["miss"] += 1
        return {"wrong": True}
    p["cur"][i] = v
    return {}


def sudoku_solved(p):
    return all(p["cur"])


def sudoku_progress(p):
    empty = sum(1 for x in p["puzzle"] if not x)
    return sum(1 for a, b in zip(p["puzzle"], p["cur"]) if not a and b) / float(max(1, empty))


def sudoku_view(p, reveal=False):
    return {"given": p["puzzle"], "cur": p["solution"] if reveal else p["cur"]}


# ====================================================================== ピクロス
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


def _placements(n, cl):
    cl = [x for x in cl if x]
    if not cl:
        yield [0] * n
        return

    def rec(i, pos, acc):
        if i == len(cl):
            yield acc + [0] * (n - len(acc))
            return
        rest = sum(cl[i + 1:]) + len(cl) - i - 1
        for s in range(pos, n - rest - cl[i] + 1):
            yield from rec(i + 1, s + cl[i] + 1, acc + [0] * (s - len(acc)) + [1] * cl[i] + ([0] if i < len(cl) - 1 else []))
    for p in rec(0, 0, []):
        yield p[:n]


def picross_solve(rows, cols):
    """行と列の手がかりだけで (一行ずつの理詰めで) 解ききれれば, その解. 解けなければ None (= 一意に決まらないことも)."""
    h, w = len(rows), len(cols)
    g = [[-1] * w for _ in range(h)]
    changed = True
    while changed:
        changed = False
        for horiz in (True, False):
            for i in range(h if horiz else w):
                line = g[i] if horiz else [g[r][i] for r in range(h)]
                cl = rows[i] if horiz else cols[i]
                n = len(line)
                ok = [pl for pl in _placements(n, cl) if all(k < 0 or k == v for k, v in zip(line, pl))]
                if not ok:
                    return None
                for j in range(n):
                    if line[j] < 0 and all(pl[j] == ok[0][j] for pl in ok):
                        v = ok[0][j]
                        if horiz:
                            g[i][j] = v
                        else:
                            g[j][i] = v
                        changed = True
    if any(x < 0 for row in g for x in row):
        return None
    return g


def picross_new(level, rng=random):
    n = SIZE["picross"][level]
    for _ in range(400):
        sol = [[1 if rng.random() < 0.58 else 0 for _ in range(n)] for _ in range(n)]
        rows = [clue(r) for r in sol]
        cols = [clue([sol[r][c] for r in range(n)]) for c in range(n)]
        if picross_solve(rows, cols) == sol:
            return {"kind": "picross", "n": n, "sol": sol, "rows": rows, "cols": cols, "filled": [], "x": [], "miss": 0}
    raise RuntimeError("ピクロスの盤面が作れませんでした")


def picross_move(p, mv, rng=random):
    """塗る・消すは自由 (普通のピクロスと同じく, 一手ごとの答え合わせはしない). op: fill / erase (無ければ切り替え).
    塗ったマスが答えとぴったり一致したら完成."""
    r, c = int(mv["r"]), int(mv["c"])
    if not (0 <= r < p["n"] and 0 <= c < p["n"]):
        raise ValueError("盤の外です")
    on = [r, c] in p["filled"]
    op = mv.get("op") or ("erase" if on else "fill")
    if op == "fill" and not on:
        p["filled"].append([r, c])
    elif op == "erase" and on:
        p["filled"].remove([r, c])
    return {}


def picross_solved(p):
    want = {(r, c) for r in range(p["n"]) for c in range(p["n"]) if p["sol"][r][c]}
    return {tuple(x) for x in p["filled"]} == want


def picross_progress(p):
    """やめたときの進み具合: 正しく塗れたマスから, 余計に塗ったマスを引く."""
    good = sum(1 for r, c in p["filled"] if p["sol"][r][c])
    bad = len(p["filled"]) - good
    return max(0.0, (good - bad) / float(max(1, sum(map(sum, p["sol"])))))


def picross_view(p, reveal=False):
    filled = [[r, c] for r in range(p["n"]) for c in range(p["n"]) if p["sol"][r][c]] if reveal else p["filled"]
    return {"n": p["n"], "rows": p["rows"], "cols": p["cols"], "filled": filled, "x": p["x"]}


# ====================================================================== 15 パズル
def slide_new(level, rng=random):
    n, k = SIZE["slide"][level]
    b = list(range(1, n * n)) + [0]
    goal = list(b)
    prev = None
    while True:
        for _ in range(k):
            z = b.index(0)
            zr, zc = divmod(z, n)
            opts = [y * n + x for y, x in ((zr - 1, zc), (zr + 1, zc), (zr, zc - 1), (zr, zc + 1))
                    if 0 <= y < n and 0 <= x < n and y * n + x != prev]
            t = rng.choice(opts)
            b[z], b[t] = b[t], 0
            prev = z
        if b != goal:
            break
    return {"kind": "slide", "n": n, "board": b, "moves": 0, "miss": 0}


def slide_move(p, mv, rng=random):
    n = p["n"]
    r, c = int(mv["r"]), int(mv["c"])
    z = p["board"].index(0)
    zr, zc = divmod(z, n)
    if abs(zr - r) + abs(zc - c) != 1:
        return {}
    t = r * n + c
    p["board"][z], p["board"][t] = p["board"][t], 0
    p["moves"] += 1
    return {}


def slide_solved(p):
    return p["board"] == list(range(1, p["n"] ** 2)) + [0]


def slide_progress(p):
    return sum(1 for i, v in enumerate(p["board"]) if v == i + 1) / float(p["n"] ** 2 - 1)


def slide_view(p, reveal=False):
    return {"n": p["n"], "board": p["board"], "moves": p["moves"]}


# ====================================================================== まとめ
# ====================================================================== スリザーリンク (core/slither.py)
_GRIDS = {}


def _sl_grid(p):
    key = (p["h"], p["w"])
    if key not in _GRIDS:
        _GRIDS[key] = SL.Grid(*key)
    return _GRIDS[key]


_SL_READY = {}                 # 難の盤を一つ, 裏で作っておく (作るのに数秒かかるので, 次に始めるときに待たせない)
_SL_LOCK = threading.Lock()


def _sl_make(level, rng):
    h, w, keep = SIZE["slither"][level]
    clues, sol = SL.generate(h, w, rng, keep, level)
    return {"kind": "slither", "h": h, "w": w, "clues": clues, "sol": sol, "st": [0] * len(sol), "miss": 0}


def _sl_prepare(level):
    def run():
        p = _sl_make(level, random.Random())
        with _SL_LOCK:
            _SL_READY.setdefault(level, p)
    threading.Thread(target=run, daemon=True, name="slither-prepare").start()


def slither_new(level, rng=random):
    if rng is not random or level != "hard":      # 乱数の種を決めた盤 (単独版の seed・テスト) はその場で作る
        return _sl_make(level, rng)
    with _SL_LOCK:
        p = _SL_READY.pop(level, None)
    _sl_prepare(level)                             # 次の分を裏で
    return p or _sl_make(level, rng)


def slither_move(p, mv, rng=random):
    """辺の状態をまとめて受け取る ({"edges": [[辺, 1 線 / 0 未定 / -1 ×], ...]}). 線も×も自由に引ける・消せる
    (仮置き・元に戻すは画面の側. 一手ごとの正誤は出さない)."""
    n = len(p["st"])
    for e, v in mv.get("edges") or []:
        e, v = int(e), int(v)
        if not (0 <= e < n) or v not in (1, 0, -1):
            raise ValueError("引けない辺です")
        p["st"][e] = v
    return {}


def slither_solved(p):
    return SL.is_solution(_sl_grid(p), p["clues"], p["st"])


def slither_progress(p):
    """やめたときの進み具合: 答えの線のうち引けた本数から, 余計な線を引く."""
    good = sum(1 for a, b in zip(p["st"], p["sol"]) if a == 1 and b == 1)
    bad = sum(1 for a, b in zip(p["st"], p["sol"]) if a == 1 and b != 1)
    return max(0.0, (good - bad) / float(max(1, sum(1 for b in p["sol"] if b == 1))))


def slither_view(p, reveal=False):
    st = [1 if x == 1 else 0 for x in p["sol"]] if reveal else p["st"]
    return {"h": p["h"], "w": p["w"], "clues": p["clues"], "st": st}


# ====================================================================== 2048
DIRS = ("up", "down", "left", "right")


def g2048_spawn(p, rng):
    empty = [i for i, x in enumerate(p["board"]) if not x]
    if empty:
        p["board"][rng.choice(empty)] = 4 if rng.random() < 0.1 else 2


def g2048_new(level, rng=random):
    p = {"kind": "g2048", "n": 4, "board": [0] * 16, "target": SIZE["g2048"][level], "moves": 0, "score": 0, "miss": 0}
    g2048_spawn(p, rng)
    g2048_spawn(p, rng)
    return p


def g2048_lines(n, d):
    """向き d に寄せるときの並び (寄せる先が先頭)."""
    rows = [[r * n + c for c in range(n)] for r in range(n)]
    cols = [[r * n + c for r in range(n)] for c in range(n)]
    return {"left": rows, "right": [x[::-1] for x in rows], "up": cols, "down": [x[::-1] for x in cols]}[d]


def g2048_slide(board, n, d):
    """寄せた盤と, 合わさって増えた点数. 一列で, 一度合わさったタイルはもう合わさらない (2 2 4 → 4 4, 8 にはならない)."""
    out, gain = list(board), 0
    for line in g2048_lines(n, d):
        vals = [board[i] for i in line if board[i]]
        merged = []
        i = 0
        while i < len(vals):
            if i + 1 < len(vals) and vals[i] == vals[i + 1]:
                merged.append(vals[i] * 2)
                gain += vals[i] * 2
                i += 2
            else:
                merged.append(vals[i])
                i += 1
        merged += [0] * (n - len(merged))
        for idx, v in zip(line, merged):
            out[idx] = v
    return out, gain


def g2048_stuck(p):
    return all(g2048_slide(p["board"], p["n"], d)[0] == p["board"] for d in DIRS)


def g2048_move(p, mv, rng=random):
    d = mv.get("dir")
    if d not in DIRS:
        raise ValueError("向きが違います")
    if g2048_solved(p) or g2048_stuck(p):
        return {"moved": False, "stuck": g2048_stuck(p)}
    board, gain = g2048_slide(p["board"], p["n"], d)
    if board == p["board"]:
        return {"moved": False, "stuck": False}       # その向きには動かない (手数に数えない)
    p["board"], p["score"], p["moves"] = board, p["score"] + gain, p["moves"] + 1
    g2048_spawn(p, rng)
    return {"moved": True, "stuck": g2048_stuck(p)}


def g2048_solved(p):
    return max(p["board"]) >= p["target"]


def g2048_progress(p):
    top = max(p["board"]) or 2
    return (math.log2(top) - 2) / (math.log2(p["target"]) - 2)


def g2048_view(p, reveal=False):
    return {"n": p["n"], "board": list(p["board"]), "target": p["target"], "moves": p["moves"], "score": p["score"],
            "max": max(p["board"]), "stuck": g2048_stuck(p)}


_F = {k: {f: globals()["%s_%s" % (k, f)] for f in ("new", "move", "solved", "progress", "view")} for k in KINDS}


# ====================================================================== 一時停止 (離席用)
def elapsed(t, now=None):
    """作業の経過秒 (一時停止していた間は数えない). t: 作業の記録 {t0, paused_at?, paused_total?}."""
    now = now or time.time()
    stop = t.get("paused_at")
    return max(0.0, (stop or now) - t["t0"] - float(t.get("paused_total") or 0))


def pause(t, now=None):
    if not t.get("paused_at"):
        t["paused_at"] = now or time.time()


def unpause(t, now=None):
    if t.get("paused_at"):
        t["paused_total"] = float(t.get("paused_total") or 0) + (now or time.time()) - t["paused_at"]
        t["paused_at"] = None


def paused(t):
    return bool(t.get("paused_at"))


def new(kind, level, rng=random):
    if kind not in KINDS or level not in LEVEL_LABEL:
        raise ValueError("パズルの種類か難しさが違います")
    p = _F[kind]["new"](level, rng)
    p["level"] = level
    return p


def move(p, mv, rng=random):
    out = _F[p["kind"]]["move"](p, mv, rng)
    out["solved"] = solved(p)
    return out


def solved(p):
    return _F[p["kind"]]["solved"](p)


def progress(p):
    return 1.0 if solved(p) else max(0.0, min(1.0, _F[p["kind"]]["progress"](p)))


def view(p, reveal=False):
    v = _F[p["kind"]]["view"](p, reveal)
    v.update(kind=p["kind"], level=p["level"], miss=p["miss"], solved=solved(p))
    return v


def base_pay(kind, level, rate=None):
    """解けたときの基本額 (仕事スキル・速さ・ミスの前): 目安の時間 (分) × 1 分あたりの額 × 難しさの上乗せ."""
    return PAR[kind][level] / 60.0 * float(rate or RATE_PER_MIN) * LEVEL_BONUS[level]


def pay(p, sec, mult=1.0, rate=None):
    """稼ぎ (10 円単位). rate: 1 分あたりの額 (economy.side_job_rate_per_min). 解けていなければ進んだぶんの 2 割."""
    b = base_pay(p["kind"], p["level"], rate) * mult
    if not solved(p):
        return int(round(b * progress(p) * 0.2 / 10.0)) * 10
    par = PAR[p["kind"]][p["level"]]
    speed = 1.2 if sec <= par else 0.8 if sec > 2 * par else 1.0
    return int(round(b * speed * max(0.4, 1 - 0.1 * p["miss"]) / 10.0)) * 10


def fast(p, sec):
    return solved(p) and sec <= PAR[p["kind"]][p["level"]]


def catalog():
    return {"kinds": [{"id": k, "name": v, "desc": DESC[k]} for k, v in KINDS.items()],
            "levels": [{"id": k, "name": v} for k, v in LEVEL_LABEL.items()], "par": PAR}


def now():
    return time.time()
