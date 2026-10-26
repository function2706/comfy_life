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
FC_CELLS = {"easy": 4, "mid": 3, "hard": 2}
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


def fc_new(level, rng=random):
    """解ける配り (確かめた) を出す."""
    cells = FC_CELLS[level]
    for _ in range(40):
        st = fc_deal(rng, cells)
        if fc_solve(st):
            break
    st.update(kind="freecell", hist=[], miss=0, moves=0)
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
