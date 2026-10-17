"""二人対戦の盤面ゲーム (コネクトフォー / ヘックス / リバーシ) のルールと AI.

盤面は平らなリスト. 0 = 空, 1 = あなた, 2 = キャラ.
AI の強さ skill (0..1) と凡ミス率 err で揺らぎを付ける.
"""
import random
from collections import deque

ME, HER = 1, 2


def other(p):
    return 3 - p


# ====================================================================== コネクトフォー
C4_W, C4_H = 7, 6


def c4_new():
    return [0] * (C4_W * C4_H)


def c4_drop_row(b, col):
    """col に落としたときの行 (下が 0). 満杯なら None."""
    for r in range(C4_H):
        if b[r * C4_W + col] == 0:
            return r
    return None


def c4_moves(b):
    order = [3, 2, 4, 1, 5, 0, 6]
    return [c for c in order if b[(C4_H - 1) * C4_W + c] == 0]


def c4_play(b, col, p):
    r = c4_drop_row(b, col)
    if r is None:
        raise ValueError("その列はもう置けません")
    b[r * C4_W + col] = p
    return r * C4_W + col


_C4_LINES = []
for _r in range(C4_H):
    for _c in range(C4_W):
        for _dr, _dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
            cells = [(_r + _dr * k, _c + _dc * k) for k in range(4)]
            if all(0 <= rr < C4_H and 0 <= cc < C4_W for rr, cc in cells):
                _C4_LINES.append([rr * C4_W + cc for rr, cc in cells])


def c4_winner(b):
    for ln in _C4_LINES:
        v = b[ln[0]]
        if v and all(b[i] == v for i in ln):
            return v, ln
    if all(b[(C4_H - 1) * C4_W + c] for c in range(C4_W)):
        return 0, None   # 引き分け
    return None, None


def c4_eval(b, p):
    s = 0
    for ln in _C4_LINES:
        vals = [b[i] for i in ln]
        mine, theirs = vals.count(p), vals.count(other(p))
        if mine and theirs:
            continue
        if mine:
            s += (0, 1, 4, 32, 10000)[mine]
        elif theirs:
            s -= (0, 1, 5, 40, 10000)[theirs]
    for r in range(C4_H):
        if b[r * C4_W + 3] == p:
            s += 3
    return s


def _c4_negamax(b, depth, alpha, beta, p):
    w, _ = c4_winner(b)
    if w is not None:
        return 0 if w == 0 else (100000 + depth if w == p else -100000 - depth)
    if depth == 0:
        return c4_eval(b, p)
    best = -10 ** 9
    for col in c4_moves(b):
        i = c4_play(b, col, p)
        v = -_c4_negamax(b, depth - 1, -beta, -alpha, other(p))
        b[i] = 0
        if v > best:
            best = v
        alpha = max(alpha, v)
        if alpha >= beta:
            break
    return best


def c4_ai(b, skill=0.7, err=0.0):
    moves = c4_moves(b)
    if err and random.random() < err:
        return random.choice(moves)
    depth = 2 + round(skill * 3)   # 2..5
    scored = []
    for col in moves:
        i = c4_play(b, col, HER)
        v = -_c4_negamax(b, depth - 1, -10 ** 9, 10 ** 9, ME)
        b[i] = 0
        scored.append((v + random.random(), col))
    return max(scored)[1]


def c4_advantage(b):
    """あなた側から見た形勢 (正 = あなた有利)."""
    return c4_eval(b, ME)


# ====================================================================== ヘックス
def hex_new(n):
    return [0] * (n * n)


def hex_neighbors(n, i):
    r, c = divmod(i, n)
    for dr, dc in ((-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0)):
        rr, cc = r + dr, c + dc
        if 0 <= rr < n and 0 <= cc < n:
            yield rr * n + cc


def hex_winner(b, n):
    """あなた (1) は上下, キャラ (2) は左右をつなぐ."""
    for p in (ME, HER):
        if p == ME:
            start = [c for c in range(n) if b[c] == p]
            goal = lambda i: i // n == n - 1   # noqa: E731
        else:
            start = [r * n for r in range(n) if b[r * n] == p]
            goal = lambda i: i % n == n - 1    # noqa: E731
        seen, q = set(start), deque(start)
        while q:
            i = q.popleft()
            if goal(i):
                return p
            for j in hex_neighbors(n, i):
                if j not in seen and b[j] == p:
                    seen.add(j)
                    q.append(j)
    return None


def hex_distance(b, n, p):
    """p がつなぐのに必要な残り石数 (自石 0 / 空き 1 / 相手 通れない の最短路)."""
    INF = 10 ** 6
    dist = [INF] * (n * n)
    dq = deque()
    starts = range(n) if p == ME else range(0, n * n, n)
    for i in starts:
        if b[i] == other(p):
            continue
        d = 0 if b[i] == p else 1
        if d < dist[i]:
            dist[i] = d
            (dq.appendleft if d == 0 else dq.append)(i)
    while dq:
        i = dq.popleft()
        for j in hex_neighbors(n, i):
            if b[j] == other(p):
                continue
            nd = dist[i] + (0 if b[j] == p else 1)
            if nd < dist[j]:
                dist[j] = nd
                (dq.appendleft if b[j] == p else dq.append)(j)
    goals = [i for i in range(n * n) if (i // n == n - 1 if p == ME else i % n == n - 1)]
    return min(dist[i] for i in goals)


def hex_ai(b, n, skill=0.7, err=0.0):
    empty = [i for i in range(n * n) if b[i] == 0]
    if err and random.random() < err:
        return random.choice(empty)
    center = (n - 1) / 2.0
    scored = []
    for i in empty:
        b[i] = HER
        mine, theirs = hex_distance(b, n, HER), hex_distance(b, n, ME)
        b[i] = 0
        r, c = divmod(i, n)
        v = (theirs - mine) * 10 + skill * 2 * (theirs) - 0.3 * (abs(r - center) + abs(c - center))
        if mine == 0:
            v += 10 ** 6
        scored.append((v + random.random() * (1.5 - skill), i))
    return max(scored)[1]


def hex_advantage(b, n):
    return hex_distance(b, n, HER) - hex_distance(b, n, ME)


# ====================================================================== リバーシ
RV = 8
_DIRS8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
_WEIGHTS = [
    100, -20, 10, 5, 5, 10, -20, 100,
    -20, -50, -2, -2, -2, -2, -50, -20,
    10, -2, 1, 1, 1, 1, -2, 10,
    5, -2, 1, 0, 0, 1, -2, 5,
    5, -2, 1, 0, 0, 1, -2, 5,
    10, -2, 1, 1, 1, 1, -2, 10,
    -20, -50, -2, -2, -2, -2, -50, -20,
    100, -20, 10, 5, 5, 10, -20, 100,
]


def rv_new():
    b = [0] * 64
    b[27], b[36] = HER, HER
    b[28], b[35] = ME, ME
    return b


def rv_flips(b, i, p):
    if b[i]:
        return []
    r, c = divmod(i, RV)
    out = []
    for dr, dc in _DIRS8:
        line = []
        rr, cc = r + dr, c + dc
        while 0 <= rr < RV and 0 <= cc < RV and b[rr * RV + cc] == other(p):
            line.append(rr * RV + cc)
            rr += dr
            cc += dc
        if line and 0 <= rr < RV and 0 <= cc < RV and b[rr * RV + cc] == p:
            out += line
    return out


def rv_moves(b, p):
    return [i for i in range(64) if not b[i] and rv_flips(b, i, p)]


def rv_play(b, i, p):
    fl = rv_flips(b, i, p)
    if not fl:
        raise ValueError("そこには置けません")
    b[i] = p
    for j in fl:
        b[j] = p
    return fl


def rv_eval(b, p):
    s = sum(_WEIGHTS[i] * (1 if b[i] == p else -1) for i in range(64) if b[i])
    s += 5 * (len(rv_moves(b, p)) - len(rv_moves(b, other(p))))
    return s


def _rv_minimax(b, depth, alpha, beta, p):
    moves = rv_moves(b, p)
    if depth == 0 or (not moves and not rv_moves(b, other(p))):
        if not moves and not rv_moves(b, other(p)):
            d = b.count(p) - b.count(other(p))
            return 10000 * (d > 0) - 10000 * (d < 0) + d
        return rv_eval(b, p)
    if not moves:
        return -_rv_minimax(b, depth - 1, -beta, -alpha, other(p))
    best = -10 ** 9
    for i in moves:
        nb = list(b)
        rv_play(nb, i, p)
        v = -_rv_minimax(nb, depth - 1, -beta, -alpha, other(p))
        best = max(best, v)
        alpha = max(alpha, v)
        if alpha >= beta:
            break
    return best


def rv_ai(b, skill=0.7, err=0.0):
    moves = rv_moves(b, HER)
    if not moves:
        return None
    if err and random.random() < err:
        return random.choice(moves)
    depth = 1 + round(skill * 2)   # 1..3
    scored = []
    for i in moves:
        nb = list(b)
        rv_play(nb, i, HER)
        scored.append((-_rv_minimax(nb, depth - 1, -10 ** 9, 10 ** 9, ME) + random.random(), i))
    return max(scored)[1]


def rv_advantage(b):
    return b.count(ME) - b.count(HER)
