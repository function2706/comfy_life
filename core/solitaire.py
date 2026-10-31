"""一人で遊ぶトランプ (内職): フリーセル・スパイダーソリティア・クロンダイク.

- カードは 0〜51 の数 (スート = c // 13: 0 ♠ / 1 ♥ / 2 ♦ / 3 ♣, ランク = c % 13 + 1). 画面には "AS" "TH" のような文字で渡す
  (core/cards.py と同じ書き方).
- 配りはサーバで作り, 解く仕組み (solve_*) で確かめて, 解ける配りだけを出す (確かめきれなかった配りは捨てて配り直す).
- 手 (move) はサーバで当てる. 元に戻す (undo) はサーバが持つ履歴で. もう動かせないとき (stuck) は画面に知らせる.
"""
import heapq
import random

RANKS = "A23456789TJQK"
SUITS = "SHDC"


def name(c):
    return RANKS[c % 13] + SUITS[c // 13]


def suit(c):
    return c // 13


def rank(c):
    return c % 13 + 1


def red(c):
    return c // 13 in (1, 2)


def deck(rng, n_suits=4, copies=1):
    """山 (よく切る). n_suits: 使うスートの数 (スパイダー). copies: 何組ぶん."""
    suits = {1: [0], 2: [0, 1], 4: [0, 1, 2, 3]}[n_suits]
    cards = [s * 13 + r for s in suits for r in range(13)] * (copies * 4 // len(suits))
    rng.shuffle(cards)
    return cards


# ====================================================================== フリーセル
FC_CELLS = {"easy": 4, "mid": 4, "hard": 4}       # セルは 4 つ (標準). 難しさは配りの余裕で分ける (FC_NEED)
FC_NEED = {"easy": (1, 2), "mid": (3, 3), "hard": (4, 4)}     # その配りを解くのに要るセルの数 (少ないセルでも解ける配りほど余裕がある)
FC_BUDGET = 25000          # 解く仕組みで調べる局面の上限 (超えたら確かめきれなかった配りとして捨てる)


def fc_deal(rng, cells):
    d = deck(rng)
    cols = [[] for _ in range(8)]
    for i, c in enumerate(d):
        cols[i % 8].append(c)
    return {"cols": cols, "cells": [None] * cells, "found": [0, 0, 0, 0]}


def fc_can_stack(a, b):
    """a の上に b を重ねられるか (色違いで 1 つ小さい)."""
    return red(a) != red(b) and rank(b) == rank(a) - 1


def fc_safe_auto(found, c):
    """組札に上げても困らないカード (反対の色の組札がそこまで来ている)."""
    r, s = rank(c), suit(c)
    if found[s] != r - 1:
        return False
    if r <= 2:
        return True
    opp = (1, 2) if s in (0, 3) else (0, 3)
    return all(found[o] >= r - 1 for o in opp)


def fc_autoplay(st):
    """安全に上げられるカードを組札へ (上げた枚数)."""
    n = 0
    moved = True
    while moved:
        moved = False
        for i, col in enumerate(st["cols"]):
            if col and fc_safe_auto(st["found"], col[-1]):
                st["found"][suit(col[-1])] += 1
                col.pop()
                n += 1
                moved = True
        for i, c in enumerate(st["cells"]):
            if c is not None and fc_safe_auto(st["found"], c):
                st["found"][suit(c)] += 1
                st["cells"][i] = None
                n += 1
                moved = True
    return n


def _fc_key(cols, cells, found):
    return (tuple(sorted(tuple(c) for c in cols)), tuple(sorted(x for x in cells if x is not None)), tuple(found))


def _fc_h(cols, found):
    h = (52 - sum(found)) * 3
    for col in cols:
        low = 99
        for c in col:
            if rank(c) > low:
                h += 1
            low = min(low, rank(c))
    return h


def fc_solve(st, budget=FC_BUDGET):
    """解けるか (一枚ずつの手だけで探す. 安全な組札上げは自動). 解ければ True, 解けない・調べきれなければ False."""
    start = ([list(c) for c in st["cols"]], list(st["cells"]), list(st["found"]))
    _fc_auto_tuple(start)
    seen = {_fc_key(*start)}
    heap = [(_fc_h(start[0], start[2]), 0, start)]
    tick = 0
    while heap and tick < budget:
        _, _, (cols, cells, found) = heapq.heappop(heap)
        if sum(found) == 52:
            return True
        tick += 1
        for nxt in _fc_moves(cols, cells, found):
            _fc_auto_tuple(nxt)
            k = _fc_key(*nxt)
            if k in seen:
                continue
            seen.add(k)
            heapq.heappush(heap, (_fc_h(nxt[0], nxt[2]), tick * 64 + len(heap) % 64, nxt))
    return False


def _fc_auto_tuple(t):
    st = {"cols": t[0], "cells": t[1], "found": t[2]}
    fc_autoplay(st)


def _fc_moves(cols, cells, found):
    out = []
    empty_cell = next((i for i, c in enumerate(cells) if c is None), None)
    empty_cols = [i for i, c in enumerate(cols) if not c]
    # 組札へ (安全でなくても)
    for i, col in enumerate(cols):
        if col and found[suit(col[-1])] == rank(col[-1]) - 1:
            nc = [list(c) for c in cols]
            f = list(found)
            f[suit(col[-1])] += 1
            nc[i].pop()
            out.append((nc, list(cells), f))
    for j, c in enumerate(cells):
        if c is None:
            continue
        if found[suit(c)] == rank(c) - 1:
            ce = list(cells)
            ce[j] = None
            f = list(found)
            f[suit(c)] += 1
            out.append(([list(x) for x in cols], ce, f))
        for i, col in enumerate(cols):         # セルから列へ
            if (col and fc_can_stack(col[-1], c)) or (not col and i == (empty_cols[0] if empty_cols else -1)):
                nc = [list(x) for x in cols]
                nc[i].append(c)
                ce = list(cells)
                ce[j] = None
                out.append((nc, ce, list(found)))
    for i, col in enumerate(cols):             # 列から列へ (一枚)
        if not col:
            continue
        c = col[-1]
        for k, dst in enumerate(cols):
            if k == i:
                continue
            if dst and fc_can_stack(dst[-1], c) or (not dst and len(col) > 1 and k == (empty_cols[0] if empty_cols else -1)):
                nc = [list(x) for x in cols]
                nc[k].append(nc[i].pop())
                out.append((nc, list(cells), list(found)))
        if empty_cell is not None:             # 列からセルへ
            nc = [list(x) for x in cols]
            ce = list(cells)
            ce[empty_cell] = nc[i].pop()
            out.append((nc, ce, list(found)))
    return out


def fc_need(seed, budget=FC_BUDGET):
    """配り (乱数の種) を解くのに要るセルの数 (1〜4. 4 つでも解けなければ None). 少ないセルで解けるほど, 4 つで遊ぶと余裕がある."""
    for cells in range(1, 5):
        if fc_solve(fc_deal(random.Random(seed), cells), budget):
            return cells
    return None


_FC_POOL = {}


def fc_pool():
    """難しさごとの配りの種 (defaults/freecell_pool.json. tools/build_freecell_pool.py で作る)."""
    if not _FC_POOL:
        import json
        import os
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "defaults", "freecell_pool.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                _FC_POOL.update(json.load(f))
    return _FC_POOL


def fc_new(level, rng=random):
    """その難しさの余裕の配り (要るセルの数が FC_NEED) を出す. 一覧から選ぶ (一覧が無ければ, その場で確かめながら)."""
    seeds = fc_pool().get(level)
    lo, hi = FC_NEED[level]
    if seeds:
        seed = rng.choice(seeds)
    else:
        for _ in range(200):
            seed = rng.randrange(1, 10 ** 9)
            need = fc_need(seed)
            if need and lo <= need <= hi:
                break
    st = fc_deal(random.Random(seed), FC_CELLS[level])
    st.update(kind="freecell", hist=[], miss=0, moves=0, seed=seed)
    fc_autoplay(st)
    return st


def _snap(st, keys):
    return {k: [list(x) if isinstance(x, list) else x for x in st[k]] for k in keys}


def fc_seq_ok(cards):
    """重ねて動かせるひと続き (色違いで 1 つずつ小さい)."""
    return all(fc_can_stack(a, b) for a, b in zip(cards, cards[1:]))


def fc_max_run(st, to_empty):
    """一度に動かせる枚数: (空きセル + 1) × 2^(空き列. 行き先が空き列ならそれを除く)."""
    free = sum(1 for c in st["cells"] if c is None)
    empty = sum(1 for c in st["cols"] if not c) - (1 if to_empty else 0)
    return (free + 1) * (2 ** max(0, empty))


def fc_try(st, src, dst):
    """一手 (src → dst) をしてみる. できなければ ValueError. src: {t: col/cell, i, n?}, dst: {t: col/cell/found, i?}."""
    cols, cells, found = st["cols"], st["cells"], st["found"]
    if src.get("t") == "col":
        col = cols[int(src["i"])]
        n = max(1, int(src.get("n") or 1))
        if n > len(col):
            raise ValueError("その枚数は動かせません")
        run = col[-n:]
        if not fc_seq_ok(run):
            raise ValueError("ひと続きになっていないカードはまとめて動かせません")
    elif src.get("t") == "cell":
        c = cells[int(src["i"])]
        if c is None:
            raise ValueError("そのセルは空です")
        run, n = [c], 1
    else:
        raise ValueError("動かすカードが違います")
    t = dst.get("t")
    if t == "found":
        if n != 1 or found[suit(run[0])] != rank(run[0]) - 1:
            raise ValueError("組札には A から順に、同じスートで一枚ずつ")
        found[suit(run[0])] += 1
    elif t == "cell":
        j = int(dst["i"])
        if n != 1 or cells[j] is not None:
            raise ValueError("セルには一枚だけ置けます")
        cells[j] = run[0]
    elif t == "col":
        j = int(dst["i"])
        if src.get("t") == "col" and j == int(src["i"]):
            raise ValueError("同じ列です")
        to = cols[j]
        if to and not fc_can_stack(to[-1], run[0]):
            raise ValueError("色違いで 1 つ小さいカードだけ重ねられます")
        if n > fc_max_run(st, not to):
            raise ValueError("一度に動かせるのは %d 枚までです（空きセル・空き列しだい）" % fc_max_run(st, not to))
        to.extend(run)
    else:
        raise ValueError("行き先が違います")
    if src.get("t") == "col":
        del cols[int(src["i"])][-n:]
    else:
        cells[int(src["i"])] = None


def fc_auto_dst(st, src):
    """クリックで動かす行き先: 組札 → 重ねられる列 → 空き列 → 空きセル."""
    if src.get("t") == "col":
        col = st["cols"][int(src["i"])]
        n = max(1, int(src.get("n") or 1))
        c = col[-n] if n <= len(col) else None
    else:
        c = st["cells"][int(src["i"])]
    if c is None:
        return None
    cands = []
    if (src.get("n") or 1) == 1:
        cands.append({"t": "found"})
    cands += [{"t": "col", "i": j} for j, col in enumerate(st["cols"]) if col and fc_can_stack(col[-1], c)]
    cands += [{"t": "col", "i": j} for j, col in enumerate(st["cols"]) if not col and not (src.get("t") == "col" and len(st["cols"][int(src["i"])]) == (src.get("n") or 1))]
    if (src.get("n") or 1) == 1 and src.get("t") == "col":
        cands += [{"t": "cell", "i": j} for j, x in enumerate(st["cells"]) if x is None][:1]
    for d in cands:
        trial = _snap(st, ("cols", "cells", "found"))
        try:
            fc_try(trial, src, d)
            return d
        except ValueError:
            continue
    return None


def fc_stuck(st):
    return sum(st["found"]) < 52 and not _fc_moves(st["cols"], st["cells"], st["found"])


def fc_move(st, mv):
    if mv.get("undo"):
        if not st["hist"]:
            raise ValueError("戻せる手がありません")
        st.update(st["hist"].pop())
        return {"undo": True}
    src = mv.get("from") or {}
    dst = mv.get("to") or (fc_auto_dst(st, src) if mv.get("auto") else None)
    if not dst:
        raise ValueError("動かせる行き先がありません")
    before = _snap(st, ("cols", "cells", "found"))
    fc_try(st, src, dst)
    st["hist"] = (st["hist"] + [before])[-300:]
    st["moves"] += 1
    up = fc_autoplay(st)
    return {"to": dst, "auto_up": up}


def fc_view(st, reveal=False):
    return {"cols": [[name(c) for c in col] for col in st["cols"]], "cells": [name(c) if c is not None else None for c in st["cells"]],
            "found": [name(s * 13 + n - 1) if n else None for s, n in enumerate(st["found"])], "up": sum(st["found"]),
            "moves": st["moves"], "undo": len(st["hist"]), "stuck": fc_stuck(st)}


# ====================================================================== スパイダーソリティア
SP_SUITS = {"easy": 1, "mid": 2, "hard": 4}


def sp_new(level, rng=random):
    """2 組ぶん (104 枚) を 10 列に 54 枚 (左の 4 列は 6 枚, 残りは 5 枚. 一番上だけ表), 山に 50 枚 (5 回ぶん)."""
    d = deck(rng, SP_SUITS[level], copies=2)
    cols = [[] for _ in range(10)]
    for i in range(54):
        cols[i % 10].append(d.pop())
    return {"kind": "spider", "cols": cols, "down": [len(c) - 1 for c in cols], "stock": d, "done": [], "hist": [], "miss": 0, "moves": 0}


def sp_run_start(st, i):
    """列 i の上から, 同じスートで 1 つずつ小さいひと続きの始まり (動かせる一番下の位置)."""
    col = st["cols"][i]
    k = len(col) - 1
    while k > st["down"][i] and suit(col[k - 1]) == suit(col[k]) and rank(col[k - 1]) == rank(col[k]) + 1:
        k -= 1
    return k


def _sp_flip(st, i):
    if st["cols"][i] and st["down"][i] >= len(st["cols"][i]):
        st["down"][i] = len(st["cols"][i]) - 1


def _sp_complete(st, i):
    """K から A まで同じスートで揃ったら片付ける."""
    col = st["cols"][i]
    if len(col) >= 13 and sp_run_start(st, i) <= len(col) - 13 and rank(col[-13]) == 13:
        st["done"].append(col[-13])
        del col[-13:]
        st["down"][i] = min(st["down"][i], max(0, len(col) - 1))
        _sp_flip(st, i)
        return True
    return False


def sp_try(st, i, n, j):
    col, to = st["cols"][i], st["cols"][j]
    if i == j:
        raise ValueError("同じ列です")
    if n < 1 or n > len(col) or len(col) - n < st["down"][i]:
        raise ValueError("裏のカードは動かせません")
    if len(col) - n < sp_run_start(st, i):
        raise ValueError("同じスートのひと続きだけ、まとめて動かせます")
    if to and rank(to[-1]) != rank(col[-n]) + 1:
        raise ValueError("1 つ大きいカードの上にだけ重ねられます")
    to.extend(col[-n:])
    del col[-n:]
    _sp_flip(st, i)
    _sp_complete(st, j)


def sp_auto_dst(st, i, n):
    """クリックの行き先: 同じスートで続く列 → 1 つ大きいカードの列 → 空き列."""
    c = st["cols"][i][-n]
    same, other, empty = [], [], []
    for j, to in enumerate(st["cols"]):
        if j == i:
            continue
        if not to:
            empty.append(j)
        elif rank(to[-1]) == rank(c) + 1:
            (same if suit(to[-1]) == suit(c) else other).append(j)
    if len(st["cols"][i]) == n:
        empty = []                     # 列ごと空き列へ動かしても意味がない
    for j in same + other + empty:
        return j
    return None


def sp_deal(st):
    if not st["stock"]:
        raise ValueError("山がもうありません")
    if any(not c for c in st["cols"]):
        raise ValueError("空いている列があると配れません（何か置いてから）")
    for i in range(10):
        st["cols"][i].append(st["stock"].pop())
    for i in range(10):
        _sp_complete(st, i)


def sp_useful(st):
    """意味のある手があるか (同じところへ行き来するだけの手は数えない)."""
    for i, col in enumerate(st["cols"]):
        if not col:
            continue
        for k in range(sp_run_start(st, i), len(col)):
            below = col[k - 1] if k > 0 else None
            down_below = k - 1 < st["down"][i]
            for j, to in enumerate(st["cols"]):
                if j == i:
                    continue
                if to and rank(to[-1]) != rank(col[k]) + 1:
                    continue
                if not to and k == 0:
                    continue
                if below is None or down_below or rank(below) != rank(col[k]) + 1 \
                        or (suit(below) != suit(col[k]) and to and suit(to[-1]) == suit(col[k])):
                    return True
    return False


def sp_stuck(st):
    return len(st["done"]) < 8 and not st["stock"] and not sp_useful(st)


def sp_move(st, mv):
    if mv.get("undo"):
        if not st["hist"]:
            raise ValueError("戻せる手がありません")
        st.update(st["hist"].pop())
        return {"undo": True}
    before = _snap(st, ("cols", "down", "stock", "done"))
    if mv.get("stock"):
        sp_deal(st)
    else:
        src = mv.get("from") or {}
        if src.get("t") != "col":
            raise ValueError("動かすカードが違います")
        i, n = int(src["i"]), max(1, int(src.get("n") or 1))
        if mv.get("auto"):
            if n > len(st["cols"][i]) or len(st["cols"][i]) - n < sp_run_start(st, i):
                raise ValueError("同じスートのひと続きだけ、まとめて動かせます")
            j = sp_auto_dst(st, i, n)
            if j is None:
                raise ValueError("動かせる行き先がありません")
        else:
            dst = mv.get("to") or {}
            if dst.get("t") != "col":
                raise ValueError("列にだけ動かせます")
            j = int(dst["i"])
        sp_try(st, i, n, j)
    st["hist"] = (st["hist"] + [before])[-300:]
    st["moves"] += 1
    return {}


def sp_view(st):
    return {"cols": [[name(c) if k >= st["down"][i] else None for k, c in enumerate(col)] for i, col in enumerate(st["cols"])],
            "stock": len(st["stock"]) // 10, "done": [name(c) for c in st["done"]], "up": len(st["done"]) * 13, "total": 104,
            "moves": st["moves"], "undo": len(st["hist"]), "stuck": sp_stuck(st)}


# ====================================================================== クロンダイク
KL_RULES = {"easy": (1, None), "mid": (3, None), "hard": (3, 2)}     # (めくる枚数, 山を戻せる回数. None は何度でも)
KL_BUDGET = 20000


def kl_deal(rng, level):
    d = deck(rng)
    cols = []
    for i in range(7):
        cols.append([d.pop() for _ in range(i + 1)])
    draw, passes = KL_RULES[level]
    return {"cols": cols, "down": [i for i in range(7)], "talon": d, "ptr": 0, "found": [0, 0, 0, 0], "draw": draw, "passes": passes}


def kl_reach(talon, ptr, draw, passes):
    """山と捨て札から, めくっていけば一番上に出せるカード: [(位置 q (捨て札が q 枚の状態で T[q-1] が一番上), 山を戻す回数)]."""
    out, seen = [], set()
    n = len(talon)
    if ptr > 0:
        out.append((ptr, 0))
        seen.add(ptr)
    q = ptr
    while q < n:
        q = min(n, q + draw)
        if q not in seen:
            out.append((q, 0))
            seen.add(q)
    if passes is None or passes > 0:
        q = 0
        while q < n:
            q = min(n, q + draw)
            if q not in seen:
                out.append((q, 1))
                seen.add(q)
    return out


def _kl_safe(found, c):
    return fc_safe_auto(found, c)


def _kl_autoplay(cols, down, found):
    moved = True
    while moved:
        moved = False
        for i, col in enumerate(cols):
            if col and len(col) > down[i] and _kl_safe(found, col[-1]):
                found[suit(col[-1])] += 1
                col.pop()
                if col and down[i] >= len(col):
                    down[i] = len(col) - 1
                moved = True


def _kl_moves(st):
    """解く仕組みの手 (状態の辞書の列). 意味のある手だけ (表のカードを出す・列を空けて K を入れる・組札へ・山から出す)."""
    cols, down, found, talon, ptr = st["cols"], st["down"], st["found"], st["talon"], st["ptr"]
    out = []

    def clone(**kw):
        s = {"cols": [list(c) for c in cols], "down": list(down), "found": list(found), "talon": list(talon), "ptr": ptr,
             "draw": st["draw"], "passes": st["passes"]}
        s.update(kw)
        return s
    for i, col in enumerate(cols):                     # 列から組札へ
        if col and len(col) > down[i] and found[suit(col[-1])] == rank(col[-1]) - 1:
            s = clone()
            s["found"][suit(col[-1])] += 1
            s["cols"][i].pop()
            if s["cols"][i] and s["down"][i] >= len(s["cols"][i]):
                s["down"][i] -= 1
            out.append(s)
    for i, col in enumerate(cols):                     # 列から列へ (表のひと続きの一番下から. 裏を出す・空けて K を入れるとき)
        if not col or len(col) <= down[i]:
            continue
        k = down[i]
        c = col[k]
        for j, to in enumerate(cols):
            if j == i:
                continue
            ok = (to and len(to) > down[j] and red(to[-1]) != red(c) and rank(to[-1]) == rank(c) + 1) or (not to and rank(c) == 13 and k > 0)
            if ok:
                s = clone()
                s["cols"][j].extend(s["cols"][i][k:])
                del s["cols"][i][k:]
                if s["cols"][i]:
                    s["down"][i] = len(s["cols"][i]) - 1
                else:
                    s["down"][i] = 0
                out.append(s)
                break
    for q, recycle in kl_reach(talon, ptr, st["draw"], st["passes"]):   # 山・捨て札から出す
        c = talon[q - 1]
        dsts = []
        if found[suit(c)] == rank(c) - 1:
            dsts.append(("found", None))
        for j, to in enumerate(cols):
            if (to and len(to) > down[j] and red(to[-1]) != red(c) and rank(to[-1]) == rank(c) + 1) or (not to and rank(c) == 13):
                dsts.append(("col", j))
        for kind, j in dsts:
            t2 = talon[:q - 1] + talon[q:]
            s = clone(talon=t2, ptr=q - 1, passes=(st["passes"] - recycle) if st["passes"] is not None else None)
            if kind == "found":
                s["found"][suit(c)] += 1
            else:
                s["cols"][j].append(c)
            out.append(s)
    return out


def _kl_key(st):
    return (tuple(tuple(c) for c in st["cols"]), tuple(st["down"]), tuple(st["talon"]), st["ptr"], tuple(st["found"]), st["passes"])


def kl_solve(st, budget=KL_BUDGET):
    s0 = {k: (list(map(list, v)) if k == "cols" else list(v) if isinstance(v, list) else v) for k, v in st.items()
          if k in ("cols", "down", "found", "talon", "ptr", "draw", "passes")}
    _kl_autoplay(s0["cols"], s0["down"], s0["found"])
    seen = {_kl_key(s0)}
    heap = [(0, 0, s0)]
    tick = 0
    while heap and tick < budget:
        _, _, s = heapq.heappop(heap)
        if sum(s["found"]) == 52:
            return True
        tick += 1
        for n in _kl_moves(s):
            _kl_autoplay(n["cols"], n["down"], n["found"])
            k = _kl_key(n)
            if k in seen:
                continue
            seen.add(k)
            h = (52 - sum(n["found"])) * 2 + sum(n["down"]) * 3
            heapq.heappush(heap, (h, tick * 64 + len(heap) % 64, n))
    return False


def kl_new(level, rng=random):
    for _ in range(60):
        st = kl_deal(rng, level)
        if kl_solve(st):
            break
    st.update(kind="klondike", hist=[], miss=0, moves=0)
    return st


_KL_POOL = {}


def kl_pool():
    """解けると確かめた配りの種 (defaults/klondike_pool.json. tools/build_klondike_pool.py で作る)."""
    if not _KL_POOL:
        import json
        import os
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "defaults", "klondike_pool.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                _KL_POOL.update(json.load(f))
    return _KL_POOL


def kl_new(level, rng=random):
    """確かめた配りの一覧から選ぶ (一覧が無ければ, その場で確かめながら配る)."""
    seeds = kl_pool().get(level)
    if seeds:
        seed = rng.choice(seeds)
        st = kl_deal(random.Random(seed), level)
        st["seed"] = seed
    else:
        for _ in range(60):
            st = kl_deal(rng, level)
            if kl_solve(st):
                break
    st.update(kind="klondike", hist=[], miss=0, moves=0)
    kl_autoplay(st)
    return st


def kl_can_stack(to, c):
    return red(to) != red(c) and rank(to) == rank(c) + 1


def _kl_take(st, src):
    """動かすカードの並び (src から取る前に確かめるだけ)."""
    t = src.get("t")
    if t == "col":
        i = int(src["i"])
        col = st["cols"][i]
        n = max(1, int(src.get("n") or 1))
        if n > len(col) or len(col) - n < st["down"][i]:
            raise ValueError("裏のカードは動かせません")
        run = col[-n:]
        if not fc_seq_ok(run):
            raise ValueError("ひと続きになっていないカードはまとめて動かせません")
        return run
    if t == "waste":
        if not st["ptr"]:
            raise ValueError("捨て札がありません")
        return [st["talon"][st["ptr"] - 1]]
    if t == "found":
        s = int(src["i"])
        if not st["found"][s]:
            raise ValueError("組札がありません")
        return [s * 13 + st["found"][s] - 1]
    raise ValueError("動かすカードが違います")


def kl_try(st, src, dst):
    run = _kl_take(st, src)
    c = run[0]
    if dst.get("t") == "found":
        if len(run) != 1 or src.get("t") == "found" or st["found"][suit(c)] != rank(c) - 1:
            raise ValueError("組札には A から順に、同じスートで一枚ずつ")
        st["found"][suit(c)] += 1
    elif dst.get("t") == "col":
        j = int(dst["i"])
        if src.get("t") == "col" and int(src["i"]) == j:
            raise ValueError("同じ列です")
        to = st["cols"][j]
        if (to and not kl_can_stack(to[-1], c)) or (not to and rank(c) != 13):
            raise ValueError("色違いで 1 つ小さいカードだけ重ねられます（空いた列には K だけ）")
        to.extend(run)
    else:
        raise ValueError("行き先が違います")
    t = src.get("t")
    if t == "col":
        i = int(src["i"])
        del st["cols"][i][-len(run):]
        if st["cols"][i] and st["down"][i] >= len(st["cols"][i]):
            st["down"][i] = len(st["cols"][i]) - 1
        if not st["cols"][i]:
            st["down"][i] = 0
    elif t == "waste":
        del st["talon"][st["ptr"] - 1]
        st["ptr"] -= 1
    else:
        st["found"][suit(c)] -= 1


def kl_auto_dst(st, src):
    """クリックの行き先: 組札 → 重ねられる列 → 空き列 (K)."""
    run = _kl_take(st, src)
    c = run[0]
    cands = []
    if len(run) == 1 and src.get("t") != "found":
        cands.append({"t": "found"})
    cands += [{"t": "col", "i": j} for j, to in enumerate(st["cols"]) if to and kl_can_stack(to[-1], c)]
    whole = src.get("t") == "col" and len(run) == len(st["cols"][int(src["i"])])
    if rank(c) == 13 and not whole:
        cands += [{"t": "col", "i": j} for j, to in enumerate(st["cols"]) if not to][:1]
    for d in cands:
        if d.get("t") == "col" and src.get("t") == "col" and d["i"] == int(src["i"]):
            continue
        trial = {k: (list(map(list, v)) if k == "cols" else list(v) if isinstance(v, list) else v) for k, v in st.items() if k != "hist"}
        try:
            kl_try(trial, src, d)
            return d
        except ValueError:
            continue
    return None


def kl_draw(st):
    if st["ptr"] < len(st["talon"]):
        st["ptr"] = min(len(st["talon"]), st["ptr"] + st["draw"])
    elif st["passes"] is None or st["passes"] > 0:
        if not st["talon"]:
            raise ValueError("山がありません")
        st["ptr"] = 0
        if st["passes"] is not None:
            st["passes"] -= 1
    else:
        raise ValueError("山はもう戻せません")


def kl_stuck(st):
    return sum(st["found"]) < 52 and not _kl_moves(st)


def kl_move(st, mv):
    if mv.get("undo"):
        if not st["hist"]:
            raise ValueError("戻せる手がありません")
        st.update(st["hist"].pop())
        return {"undo": True}
    before = {k: (list(map(list, st[k])) if k == "cols" else list(st[k]) if isinstance(st[k], list) else st[k])
              for k in ("cols", "down", "talon", "ptr", "found", "passes")}
    if mv.get("stock"):
        kl_draw(st)
    else:
        src = mv.get("from") or {}
        dst = mv.get("to") or (kl_auto_dst(st, src) if mv.get("auto") else None)
        if not dst:
            raise ValueError("動かせる行き先がありません")
        kl_try(st, src, dst)
    st["hist"] = (st["hist"] + [before])[-300:]
    st["moves"] += 1
    kl_autoplay(st)
    return {}


def kl_autoplay(st):
    """安全に上げられるカードを組札へ (列の一番上と, 捨て札の一番上)."""
    while True:
        _kl_autoplay(st["cols"], st["down"], st["found"])
        if st["ptr"] and _kl_safe(st["found"], st["talon"][st["ptr"] - 1]):
            c = st["talon"].pop(st["ptr"] - 1)
            st["ptr"] -= 1
            st["found"][suit(c)] += 1
            continue
        return


def kl_view(st):
    waste = st["talon"][max(0, st["ptr"] - (3 if st["draw"] == 3 else 1)):st["ptr"]]
    return {"cols": [[name(c) if k >= st["down"][i] else None for k, c in enumerate(col)] for i, col in enumerate(st["cols"])],
            "stock": len(st["talon"]) - st["ptr"], "waste": [name(c) for c in waste], "recycle": st["passes"], "draw": st["draw"],
            "found": [name(s * 13 + n - 1) if n else None for s, n in enumerate(st["found"])], "up": sum(st["found"]), "total": 52,
            "moves": st["moves"], "undo": len(st["hist"]), "stuck": kl_stuck(st)}
