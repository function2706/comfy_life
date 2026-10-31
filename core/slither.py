"""スリザーリンク (内職のパズルのひとつ. core/puzzles.py から使う).

盤: 縦 h × 横 w のマス. 点と点の間 (辺) に線を引いて, 全体で一つの輪を作る. 数字はそのマスの周りに引く線の数.
辺の番号: 横の辺 (r 行目の点の並び, c 列目) は r * w + c (r = 0..h, c = 0..w-1),
          縦の辺 (r 行目のマス, c 列目の点の並び) は H + r * (w + 1) + c (H = (h + 1) * w).
辺の状態: 1 = 線, 0 = 未定, -1 = × (線を引かない印).

- 生成: 盤全体のマスから, 外側に面したマスを削っていって (連結のまま・穴がなく・角だけで接しない), 残った集まりの境目を輪にする.
  外から食い込む形になるので, 輪は盤全体に広がって入り組む. 輪が盤の四辺すべてに触れ, 線の無いマス (数字 0) の連なった塊が
  小さい (BLANK_MAX) 形だけを使う (以前は 1 マスから広げていて, 10×10 で線の無いマスが 40〜60 と空白が大きかった). 数字は輪から数え,
  その難しさの人の解き方 (human_solve: 易は基本の定石, 中は近くの数手の行き詰まりまで, 難は 1 段の仮置きまで) で
  解き切れるあいだ, 数字を減らしていく (正しい推理だけで解き切れるので答えは一つ).
- 解く側 (solve, 確かめ用): 数字・点 (線は 0 本か 2 本)・輪が一つ の決まりで埋めていき (伝播), 決まらなければ分岐して, 解の数を数える (2 つで打ち切り).
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
def _loop_region_carve(h, w, rng, fill):
    """盤全体から, 外側に面したマスを削った集まり (連結・穴なし・角だけで接しない). その境目が一つの輪になる.
    中が詰まったところ (2 マス先も中) に食い込むマスを削りやすくして, 線の無いマスの塊を作りにくくする."""
    region = {(r, c) for r in range(h) for c in range(w)}
    target = max(2, int(h * w * fill))

    def inn(y, x):
        return (y, x) in region

    def touch_ok(y0, x0):
        # 削ったマスのまわりの 2×2 に, 角だけで接する形 (市松) がないか
        for y in (y0 - 1, y0):
            for x in (x0 - 1, x0):
                a, b, c, d = inn(y, x), inn(y, x + 1), inn(y + 1, x), inn(y + 1, x + 1)
                if (a and d and not b and not c) or (b and c and not a and not d):
                    return False
        return True

    def connected():
        s = next(iter(region))
        seen, stack = {s}, [s]
        while stack:
            y, x = stack.pop()
            for q in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if q in region and q not in seen:
                    seen.add(q)
                    stack.append(q)
        return len(seen) == len(region)

    fails = 0
    while len(region) > target and fails < h * w * 30:
        cands = [(y, x) for (y, x) in region if any(not inn(*q) for q in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)))]
        wts = [1 + 3 * sum(1 for q in ((y + 2, x), (y - 2, x), (y, x + 2), (y, x - 2)) if inn(*q)) for (y, x) in cands]
        cell = rng.choices(cands, wts)[0]
        region.discard(cell)               # 外側に面したマスを削るので, 外側は外とつながったまま (穴はできない)
        if region and touch_ok(*cell) and connected():
            continue
        region.add(cell)
        fails += 1
    return region


BLANK_MAX = {5: 2, 7: 3, 10: 4}          # 線の無いマス (数字 0) の連なった塊の大きさの上限 (盤の一辺ごと)


def shape_stats(h, w, region):
    """(線の無いマスの数, その連なった塊のいちばん大きいもの, 輪が四辺すべてに触れるか)."""
    inn = lambda y, x: (y, x) in region  # noqa: E731
    zeros = set()
    for r in range(h):
        for c in range(w):
            nb = [inn(y, x) for y, x in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))]
            if all(v == inn(r, c) for v in nb):
                zeros.add((r, c))
    big, seen = 0, set()
    for z in zeros:
        if z in seen:
            continue
        stack, n = [z], 0
        seen.add(z)
        while stack:
            y, x = stack.pop()
            n += 1
            for q in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if q in zeros and q not in seen:
                    seen.add(q)
                    stack.append(q)
        big = max(big, n)
    sides = (any(inn(0, c) for c in range(w)) and any(inn(h - 1, c) for c in range(w))
             and any(inn(r, 0) for r in range(h)) and any(inn(r, w - 1) for r in range(h)))
    return len(zeros), big, sides


def board_region(h, w, rng):
    """盤全体に広がる輪の元: 四辺すべてに触れ, 線の無いマスの塊が小さい形 (いくつか作って, 合うものを. 無ければいちばん近いもの)."""
    cap = BLANK_MAX.get(max(h, w), max(2, max(h, w) // 2 - 1))
    best = None
    for _ in range(30):
        region = _loop_region_carve(h, w, rng, rng.uniform(0.5, 0.62))
        zeros, big, sides = shape_stats(h, w, region)
        if sides and big <= cap:
            return region
        score = (not sides, big, zeros)
        if best is None or score < best[0]:
            best = (score, region)
    return best[1]


def _loop_region(h, w, rng, fill):
    """(以前の生成) 1 マスから広げた, 穴がなく角だけで接しない連結なマスの集まり. いまは board_region を使う."""
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


def generate(h, w, rng=random, keep=0.0, level="hard", tries=12, harder=True):
    """その難しさの解き方 (human_solve) で解き切れるスリザーリンク. (数字 [マスごと, 無ければ None], 答えの辺の状態).
    数字は, その解き方で (行き詰まるたびに進める場所が MIN_HITS か所以上ある形で) 解き切れるあいだ減らす (解き切れれば答えは一つ).
    keep: 残す数字の割合の下限 (易しくする). harder: 一つ易しい解き方では解けない盤を選ぶ (tries 回作って見つからなければ,
    いちばん近いもの)."""
    g = Grid(h, w)
    best = None
    for _ in range(tries):
        region = board_region(h, w, rng)
        sol = _loop_edges(g, region)
        clues = [sum(1 for e in g.cedges[i] if sol[e] == 1) for i in range(h * w)]
        if not human_solve(g, clues, level, MIN_HITS):
            continue
        order = list(range(h * w))
        rng.shuffle(order)
        floor = int(h * w * keep)
        for i in order:
            if sum(1 for x in clues if x is not None) <= floor:
                break
            v, clues[i] = clues[i], None
            if not human_solve(g, clues, level, MIN_HITS):
                clues[i] = v                    # その解き方で解き切れなくなる (・進める場所が 1 か所だけになる) なら戻す
        lv = LEVELS.index(level)
        if lv == 0 or not harder or not human_solve(g, clues, LEVELS[lv - 1]):
            return clues, sol
        if best is None:
            best = (clues, sol)
    if best:
        return best
    raise RuntimeError("スリザーリンクの盤面が作れませんでした")


def is_solution(g, clues, st):
    """線 (1) だけを見て, 数字どおりの一つの輪になっているか (× と未定は区別しない)."""
    s = [1 if x == 1 else -1 for x in st]
    return _done(g, clues, s)


# ====================================================================== 人の解き方 (難しさを決める)
# 易: 基本の定石だけ = 数字の数 (0 の周りなど)・各点で線は 0 本か 2 本 (行き止まり・分岐なし)・輪を早く閉じない・
#     角の定石 (点に残る辺が 1 つのマスの角の 2 本だけなら, そのマスが 1 なら両方×, 3 なら両方線.
#     線が 1 本来ている点で残りがマスの角の 2 本なら, 1 ならそのマスの残り 2 本は×, 3 なら残り 2 本は線. 盤の角の 1・3 もこれ)
# 中: 易 + 近くの数手で行き詰まる形 (隣り合う 3 と 3, 斜めの 3, 2 の絡む形など. ある辺を決めると数手以内に矛盾 → 逆に決まる)
# 難: 中 + 1 段の仮置き (ある辺を決めて, もう少し先 (TRIAL_STEPS) まで進めると矛盾 → 逆に決まる)
# どの推理も正しい推理だけなので, 解き切れれば答えは一つ.
# 出来の悪い問題にしない: 行き詰まったとき (仮置きが要るとき), 進める手がかり (矛盾の出る仮置き) が盤のどこか 1 か所にしかない,
# のような「枝の多い樹形図を総当たりする」問題は捨てる. 行き詰まるたびに, 進める場所が MIN_HITS か所以上あること.
# 仮置きの深さにも上限を置く (最後まで進めないと矛盾が出ない仮置きは, 人には総当たりと同じ).
LEVELS = ("easy", "mid", "hard")
LOCAL_STEPS = 10             # 中の「近くの数手」: 決まる辺の数の上限
TRIAL_STEPS = 30             # 難の仮置き: 決まる辺の数の上限
MIN_HITS = 2                 # 行き詰まったとき, 進める場所がこれだけはあること


class _Ctx:
    def __init__(self, g, clues):
        self.g, self.clues = g, clues
        self.pair_cell = {}          # 角をなす 2 辺 → そのマス
        for i, es in enumerate(g.cedges):
            for a in es:
                for b in es:
                    if a < b and set(g.ends[a]) & set(g.ends[b]):
                        self.pair_cell[(a, b)] = i
        self.vpair = {}              # 隣り合う 2 点 → 辺
        for e, (a, b) in enumerate(g.ends):
            self.vpair[(a, b)] = self.vpair[(b, a)] = e
        self.clued = [i for i, c in enumerate(clues) if c is not None]


class _Stop(Exception):
    pass


def _other(g, e, x):
    a, b = g.ends[e]
    return b if a == x else a


def _walk(g, st, x, prev, stop):
    """線をたどって端へ. (端の点, 辺の数). stop に戻ったら (None, 辺の数) = 閉じた輪."""
    n = 0
    while n <= len(st):
        nxt = None
        for f in g.vedges[x]:
            if f != prev and st[f] == 1:
                nxt = f
                break
        if nxt is None:
            return x, n
        y = _other(g, nxt, x)
        n += 1
        if y == stop:
            return None, n
        x, prev = y, nxt
    return x, n


def _clues_ok(ctx, st, extra=None):
    g = ctx.g
    for i in ctx.clued:
        if sum(1 for e in g.cedges[i] if st[e] == 1 or e == extra) != ctx.clues[i]:
            return False
    return True


def _prop(ctx, st, first, limit=None):
    """first: [(辺, 値)] を置いて, 易の定石で進める. 矛盾なら False. limit: 決める辺の数の上限 (超えたら打ち切って True)."""
    g, clues = ctx.g, ctx.clues
    qv, qc = set(), set()
    cnt = [0, sum(1 for x in st if x == 1)]       # 決めた数, 線の数

    def put(e, v):
        if st[e] == v:
            return True
        if st[e] != 0:
            return False
        if limit is not None and cnt[0] >= limit:
            raise _Stop
        st[e] = v
        cnt[0] += 1
        a, b = g.ends[e]
        qv.add(a)
        qv.add(b)
        for i in g.ecells[e]:
            if clues[i] is not None:
                qc.add(i)
        if v == 1:
            cnt[1] += 1
            return close_check(e)
        return True

    def close_check(e):
        a, b = g.ends[e]
        p, n1 = _walk(g, st, a, e, b)
        if p is None:                                  # 輪が閉じた: ほかに線が無く, 数字が全部合っていること
            if cnt[1] != n1 + 1 or not _clues_ok(ctx, st):
                return False
            for f in range(g.n):
                if st[f] == 0:
                    st[f] = -1
            return True
        q, n2 = _walk(g, st, b, e, a)
        f = ctx.vpair.get((p, q))
        if f is not None and st[f] == 0:
            if cnt[1] > n1 + n2 + 1 or not _clues_ok(ctx, st, f):
                return put(f, -1)
        return True

    try:
        for e, v in first:
            if not put(e, v):
                return False
        if not first:
            qv.update(range(len(g.vedges)))
            qc.update(ctx.clued)
        while qv or qc:
            while qc:
                i = qc.pop()
                cl = clues[i]
                es = g.cedges[i]
                on = sum(1 for e in es if st[e] == 1)
                unk = [e for e in es if st[e] == 0]
                if on > cl or on + len(unk) < cl:
                    return False
                if unk and (on == cl or on + len(unk) == cl):
                    v = -1 if on == cl else 1
                    for e in unk:
                        if not put(e, v):
                            return False
            while qv and not qc:
                x = qv.pop()
                on = sum(1 for e in g.vedges[x] if st[e] == 1)
                unk = [e for e in g.vedges[x] if st[e] == 0]
                if on > 2 or (on == 1 and not unk):
                    return False
                todo = []
                if unk and on == 2:
                    todo = [(e, -1) for e in unk]
                elif on == 1 and len(unk) == 1:
                    todo = [(unk[0], 1)]
                elif on == 0 and len(unk) == 1:
                    todo = [(unk[0], -1)]
                elif len(unk) == 2 and on < 2:              # 角の定石
                    c = ctx.pair_cell.get((min(unk), max(unk)))
                    cl = clues[c] if c is not None else None
                    if cl in (1, 3):
                        if on == 0:
                            todo = [(e, -1 if cl == 1 else 1) for e in unk]
                        else:
                            todo = [(e, -1 if cl == 1 else 1) for e in g.cedges[c] if e not in unk]
                for e, v in todo:
                    if not put(e, v):
                        return False
    except _Stop:
        return True
    return True


def _loop_scan(ctx, st):
    """線のかたまりの両端をつなぐ辺: ほかに線が残るか, 数字が合わないなら×. 矛盾なら False."""
    g = ctx.g
    seen = set()
    total = sum(1 for x in st if x == 1)
    out = []
    for x in range(len(g.vedges)):
        if x in seen or sum(1 for e in g.vedges[x] if st[e] == 1) != 1:
            continue
        y, n = _walk(g, st, x, None, None)
        seen.add(x)
        seen.add(y)
        f = ctx.vpair.get((x, y))
        if f is not None and st[f] == 0 and (total > n or not _clues_ok(ctx, st, f)):
            out.append(f)
    for f in out:
        if st[f] == 0 and not _prop(ctx, st, [(f, -1)]):
            return False
    return True


def _try_edges(ctx, st):
    """仮に決めてみる辺の候補: 線の来ている点か, 数字のマスに接する未定の辺."""
    g = ctx.g
    out = []
    for e in range(g.n):
        if st[e] != 0:
            continue
        a, b = g.ends[e]
        if any(st[f] == 1 for f in g.vedges[a] + g.vedges[b]) or any(ctx.clues[i] is not None for i in g.ecells[e]):
            out.append(e)
    return out


def human_solve(g, clues, level="hard", min_hits=1):
    """その難しさの解き方だけで解き切れれば答えの辺の状態 (1 線 / -1), だめなら None.
    min_hits: 行き詰まるたびに, 進める場所 (矛盾の出る仮置き) がこれだけあること (無ければ出来の悪い問題として None)."""
    ctx = _Ctx(g, clues)
    lv = LEVELS.index(level)
    st = [0] * g.n
    if not _prop(ctx, st, []) or not _loop_scan(ctx, st):
        return None
    limits = {0: (), 1: (LOCAL_STEPS,), 2: (LOCAL_STEPS, TRIAL_STEPS)}[lv]
    while any(x == 0 for x in st):
        hits = []
        for limit in limits:
            hits = []
            for e in _try_edges(ctx, st):
                for v in (1, -1):
                    s2 = list(st)
                    if not _prop(ctx, s2, [(e, v)], limit):      # 矛盾 → 逆に決まる
                        hits.append((e, -v))
                        break
                if len(hits) >= min_hits:
                    break
            if len(hits) >= min_hits or (hits and not any(x == 0 for x in _rest_after(ctx, st, hits[0]))):
                break                               # (最後の一手なら, 1 か所でよい)
        if not hits or (len(hits) < min_hits and any(x == 0 for x in _rest_after(ctx, st, hits[0]))):
            return None
        hit = hits[0]
        if not _prop(ctx, st, [hit]) or not _loop_scan(ctx, st):
            return None
    st = [1 if x == 1 else -1 for x in st]
    return st if _done(g, clues, st) else None


def _rest_after(ctx, st, hit):
    """hit を置いて基本の定石で進めたあとの盤 (矛盾なら全部埋まった扱いにはしない)."""
    s2 = list(st)
    if not _prop(ctx, s2, [hit]) or not _loop_scan(ctx, s2):
        return [0]
    return s2


def grade(g, clues):
    """解ける いちばん易しい難しさ (どれでも解けなければ None)."""
    for lv in LEVELS:
        if human_solve(g, clues, lv):
            return lv
    return None
