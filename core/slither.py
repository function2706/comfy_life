"""スリザーリンク (内職のパズルのひとつ. core/puzzles.py から使う).

盤: 縦 h × 横 w のマス. 点と点の間 (辺) に線を引いて, 全体で一つの輪を作る. 数字はそのマスの周りに引く線の数.
辺の番号: 横の辺 (r 行目の点の並び, c 列目) は r * w + c (r = 0..h, c = 0..w-1),
          縦の辺 (r 行目のマス, c 列目の点の並び) は H + r * (w + 1) + c (H = (h + 1) * w).
辺の状態: 1 = 線, 0 = 未定, -1 = × (線を引かない印).

- 生成: マスの連結な集まり (穴がなく, 角だけで接しない) を広げて, その境目を輪にする. 数字は輪から数え,
  解く側 (solve) で答えが一つに決まるあいだ, 数字を減らしていく.
- 解く側: 数字・点 (線は 0 本か 2 本)・輪が一つ の決まりで埋めていき (伝播), 決まらなければ分岐して, 解の数を数える (2 つで打ち切り).
- 答え合わせはサーバ: 引いた線 (1) が答えの輪とぴったり同じならできあがり. 一手ごとの正誤は出さない (ミスは数えない).
"""
import random


class Grid:
    def __init__(self, h, w):
        self.h, self.w = h, w
        self.H = (h + 1) * w
        self.n = self.H + h * (w + 1)
        # 辺 → 両端の点 (点の番号 = r * (w + 1) + c)
        self.ends = []
        for r in range(h + 1):
            for c in range(w):
                self.ends.append((r * (w + 1) + c, r * (w + 1) + c + 1))
        for r in range(h):
            for c in range(w + 1):
                self.ends.append((r * (w + 1) + c, (r + 1) * (w + 1) + c))
        self.vedges = [[] for _ in range((h + 1) * (w + 1))]
        for e, (a, b) in enumerate(self.ends):
            self.vedges[a].append(e)
            self.vedges[b].append(e)
        # マス → 周りの 4 辺 (上・下・左・右)
        self.cedges = [[r * w + c, (r + 1) * w + c, self.H + r * (w + 1) + c, self.H + r * (w + 1) + c + 1]
                       for r in range(h) for c in range(w)]
        self.ecells = [[] for _ in range(self.n)]
        for i, es in enumerate(self.cedges):
            for e in es:
                self.ecells[e].append(i)


# ====================================================================== 解く側
def _propagate(g, clues, st):
    """決まりから決まる辺を埋める (変わった辺のまわりだけ見直す). 矛盾があれば False."""
    cells = [i for i, cl in enumerate(clues) if cl is not None]
    verts = list(range(len(g.vedges)))
    qc, qv = set(cells), set(verts)

    def put(e, v):
        st[e] = v
        a, b = g.ends[e]
        qv.add(a)
        qv.add(b)
        for i in g.ecells[e]:
            if clues[i] is not None:
                qc.add(i)

    while True:
        while qc or qv:
            while qc:
                i = qc.pop()
                cl = clues[i]
                on = unk = 0
                for e in g.cedges[i]:
                    x = st[e]
                    if x == 1:
                        on += 1
                    elif x == 0:
                        unk += 1
                if on > cl or on + unk < cl:
                    return False
                if unk and (on == cl or on + unk == cl):
                    v = -1 if on == cl else 1
                    for e in g.cedges[i]:
                        if st[e] == 0:
                            put(e, v)
            while qv:
                x0 = qv.pop()
                on = 0
                unk = []
                for e in g.vedges[x0]:
                    x = st[e]
                    if x == 1:
                        on += 1
                    elif x == 0:
                        unk.append(e)
                if on > 2 or (on == 1 and not unk):
                    return False
                if unk and (on == 2 or (on == 0 and len(unk) == 1)):
                    for e in unk:
                        put(e, -1)
                elif on == 1 and len(unk) == 1:
                    put(unk[0], 1)
        # 輪が一つ: 線のかたまりの両端をつなぐ辺は, ほかに線が残っていれば引けない (小さな輪になる)
        comp = _components(g, st)
        if comp is None:
            return False
        root, _, n_comp = comp
        if n_comp <= 1:
            return True
        hit = False
        for e in range(g.n):
            if st[e] == 0:
                a, b = g.ends[e]
                if root[a] is not None and root[a] == root[b]:
                    put(e, -1)
                    hit = True
        if not hit:
            return True


def _components(g, st):
    """線のかたまり. (点 → かたまりの番号 or None, 端点の数, かたまりの数). 閉じた輪が他の線と並んでいれば None."""
    nv = len(g.vedges)
    root = [None] * nv
    nc = 0
    closed = 0
    for v in range(nv):
        if root[v] is not None or not any(st[e] == 1 for e in g.vedges[v]):
            continue
        stack, deg_ok = [v], True
        root[v] = nc
        members = []
        while stack:
            x = stack.pop()
            members.append(x)
            for e in g.vedges[x]:
                if st[e] == 1:
                    a, b = g.ends[e]
                    y = b if a == x else a
                    if root[y] is None:
                        root[y] = nc
                        stack.append(y)
        if all(sum(1 for e in g.vedges[x] if st[e] == 1) == 2 for x in members):
            closed += 1
        nc += 1
    if closed and nc > 1:
        return None
    return root, 0, nc


def _done(g, clues, st):
    """すべての辺が決まり, 数字どおりで, 輪が一つ."""
    if any(s == 0 for s in st):
        return False
    for i, cl in enumerate(clues):
        if cl is not None and sum(1 for e in g.cedges[i] if st[e] == 1) != cl:
            return False
    comp = _components(g, st)
    if comp is None or comp[2] != 1:
        return False
    return all(sum(1 for e in es if st[e] == 1) in (0, 2) for es in g.vedges)


def solve(g, clues, limit=2, budget=200000):
    """解の数 (limit で打ち切り) と, 見つかった最初の解. 手数が予算を超えたら (数え切れない) count = None."""
    sols = []
    steps = [0]

    def rec(st):
        steps[0] += 1
        if steps[0] > budget:
            raise TimeoutError
        if not _propagate(g, clues, st):
            return
        if all(s != 0 for s in st):
            if _done(g, clues, st):
                sols.append(st)
            return
        # 分岐: 線が 1 本だけ来ている点の未定の辺から (無ければ最初の未定の辺)
        e = None
        for es in g.vedges:
            if sum(1 for x in es if st[x] == 1) == 1:
                e = next((x for x in es if st[x] == 0), None)
                if e is not None:
                    break
        if e is None:
            e = st.index(0)
        for v in (1, -1):
            s2 = list(st)
            s2[e] = v
            rec(s2)
            if len(sols) >= limit:
                return

    try:
        rec([0] * g.n)
    except TimeoutError:
        return None, (sols[0] if sols else None)
    return len(sols), (sols[0] if sols else None)


# ====================================================================== 生成
def _loop_region(h, w, rng, fill):
    """穴がなく, 角だけで接しない, 連結なマスの集まり. その境目が一つの輪になる."""
    start = (rng.randrange(h), rng.randrange(w))
    region = {start}
    target = max(2, int(h * w * fill))
    tries = 0

    def inside(r, c):
        return (r, c) in region

    def ok_add(r, c):
        # 角だけで接する形 (斜めの 2 マスが内で, 残りの 2 マスが外) を作らない
        for dr in (-1, 1):
            for dc in (-1, 1):
                if inside(r + dr, c + dc) and not inside(r + dr, c) and not inside(r, c + dc):
                    return False
        # 外側 (盤の外を含む) が切れて穴ができない: 加えたあとの外側が連結か
        region.add((r, c))
        outside = [(y, x) for y in range(-1, h + 1) for x in range(-1, w + 1) if (y, x) not in region]
        seen = {outside[0]}
        stack = [outside[0]]
        while stack:
            y, x = stack.pop()
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if -1 <= ny <= h and -1 <= nx <= w and (ny, nx) not in region and (ny, nx) not in seen:
                    seen.add((ny, nx))
                    stack.append((ny, nx))
        region.discard((r, c))
        return len(seen) == len(outside)

    while len(region) < target and tries < h * w * 20:
        tries += 1
        r, c = rng.choice(sorted(region))
        dr, dc = rng.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
        nr, nc = r + dr, c + dc
        if 0 <= nr < h and 0 <= nc < w and (nr, nc) not in region and ok_add(nr, nc):
            region.add((nr, nc))
    return region


def _loop_edges(g, region):
    st = [-1] * g.n
    for i, es in enumerate(g.cedges):
        r, c = divmod(i, g.w)
        if (r, c) not in region:
            continue
        nb = ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))
        for e, (y, x) in zip(es, nb):
            if (y, x) not in region:
                st[e] = 1
    return st


def generate(h, w, rng=random, keep=0.0, budget=60000):
    """答えが一つのスリザーリンク. (数字 [マスごと, 無ければ None], 答えの辺の状態). keep: 残す数字の割合の下限 (易しくする)."""
    g = Grid(h, w)
    for _ in range(30):
        region = _loop_region(h, w, rng, rng.uniform(0.45, 0.6))
        sol = _loop_edges(g, region)
        full = [sum(1 for e in g.cedges[i] if sol[e] == 1) for i in range(h * w)]
        n, _ = solve(g, full, budget=budget)
        if n != 1:
            continue
        clues = list(full)
        order = list(range(h * w))
        rng.shuffle(order)
        floor = int(h * w * keep)
        for i in order:
            if sum(1 for x in clues if x is not None) <= floor:
                break
            v, clues[i] = clues[i], None
            n, _ = solve(g, clues, budget=budget)
            if n != 1:
                clues[i] = v                    # 一意でなくなる (か数え切れない) なら戻す
        return clues, sol
    raise RuntimeError("スリザーリンクの盤面が作れませんでした")


def is_solution(g, clues, st):
    """線 (1) だけを見て, 数字どおりの一つの輪になっているか (× と未定は区別しない)."""
    s = [1 if x == 1 else -1 for x in st]
    return _done(g, clues, s)
