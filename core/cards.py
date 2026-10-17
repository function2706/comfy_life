"""トランプゲームのルールと AI (ポーカー / ブラックジャック / 神経衰弱 / ババ抜き).

カードは文字列: ランク (A23456789TJQK) + スート (S♠ H♥ D♦ C♣). ジョーカーは "XJ".
"""
import random
from collections import Counter

SUITS = "SHDC"
RANKS = "A23456789TJQK"
JOKER = "XJ"


def new_deck(jokers=0, shuffle=True):
    d = [r + s for s in SUITS for r in RANKS] + [JOKER] * jokers
    if shuffle:
        random.shuffle(d)
    return d


def rank(c):
    return c[0]


# ====================================================================== ポーカー
POKER_NAMES = ["ハイカード", "ワンペア", "ツーペア", "スリーカード", "ストレート", "フラッシュ",
               "フルハウス", "フォーカード", "ストレートフラッシュ", "ロイヤルストレートフラッシュ"]


def _pv(c):
    return "23456789TJQKA".index(c[0]) + 2


def poker_eval(cards):
    """(役の強さ 0..9, 同じ役どうしの比較用タプル, 役名)."""
    vals = sorted((_pv(c) for c in cards), reverse=True)
    cnt = Counter(vals)
    groups = sorted(cnt.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    flush = len({c[1] for c in cards}) == 1
    uniq = sorted(set(vals), reverse=True)
    straight_hi = None
    if len(uniq) == 5:
        if uniq[0] - uniq[4] == 4:
            straight_hi = uniq[0]
        elif uniq == [14, 5, 4, 3, 2]:
            straight_hi = 5
    if straight_hi and flush:
        cat = 9 if straight_hi == 14 else 8
        return cat, (straight_hi,), POKER_NAMES[cat]
    shape = [n for _, n in groups]
    key = tuple(v for v, _ in groups)
    if shape[0] == 4:
        return 7, key, POKER_NAMES[7]
    if shape == [3, 2]:
        return 6, key, POKER_NAMES[6]
    if flush:
        return 5, tuple(vals), POKER_NAMES[5]
    if straight_hi:
        return 4, (straight_hi,), POKER_NAMES[4]
    if shape[0] == 3:
        return 3, key, POKER_NAMES[3]
    if shape[:2] == [2, 2]:
        return 2, key, POKER_NAMES[2]
    if shape[0] == 2:
        return 1, key, POKER_NAMES[1]
    return 0, tuple(vals), POKER_NAMES[0]


def poker_compare(a, b):
    ea, eb = poker_eval(a), poker_eval(b)
    return (ea[:2] > eb[:2]) - (ea[:2] < eb[:2])


def poker_exchange(hand, err=0.0):
    """AI が捨てるカードの添字 (役を残し, 4 枚フラッシュ/ストレートは引きにいく)."""
    if err and random.random() < err:
        return random.sample(range(5), random.randint(0, 3))
    cat = poker_eval(hand)[0]
    if cat >= 4 and cat != 7:
        return []
    vals = [_pv(c) for c in hand]
    cnt = Counter(vals)
    if cat in (1, 2, 3, 7):
        keep = {v for v, n in cnt.items() if n >= 2}
        return [i for i, v in enumerate(vals) if v not in keep]
    suits = Counter(c[1] for c in hand)
    s, n = suits.most_common(1)[0]
    if n == 4:
        return [i for i, c in enumerate(hand) if c[1] != s]
    for drop in range(5):     # 両面の 4 枚ストレート
        rest = sorted(v for j, v in enumerate(vals) if j != drop)
        if len(set(rest)) == 4 and rest[3] - rest[0] == 3:
            return [drop]
    order = sorted(range(5), key=lambda i: -vals[i])
    keep = [i for i in order[:2] if vals[i] >= 11]
    return [i for i in range(5) if i not in keep]


def poker_strength(hand):
    """0..1 のおおまかな手の強さ (勝負/降りる判断用)."""
    cat, key, _ = poker_eval(hand)
    base = [0.12, 0.35, 0.6, 0.72, 0.8, 0.84, 0.9, 0.96, 0.99, 1.0][cat]
    return min(1.0, base + (key[0] - 7) / 100.0)


# ====================================================================== ブラックジャック
def bj_value(cards):
    total, aces = 0, 0
    for c in cards:
        r = c[0]
        if r == "A":
            total += 11
            aces += 1
        elif r in "TJQK":
            total += 10
        else:
            total += int(r)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def bj_natural(cards):
    return len(cards) == 2 and bj_value(cards) == 21


# ====================================================================== ババ抜き
def remove_pairs(hand):
    """同じランクの 2 枚組を捨てる. (残りの手札, 捨てたランクのリスト)."""
    by = {}
    for c in hand:
        by.setdefault(c[0] if c != JOKER else JOKER, []).append(c)
    out, removed = [], []
    for r, cs in by.items():
        while len(cs) >= 2 and r != JOKER:
            removed.append(r)
            cs = cs[2:]
        out += cs
    random.shuffle(out)
    return out, removed


# ====================================================================== 神経衰弱
def concentration_deck(pairs=12):
    """pairs 組のペア (同じランク・同じ色) を作って並べる."""
    ranks = random.sample(RANKS, min(pairs, 13))
    deck = []
    for r in ranks:
        color = random.choice(["SC", "HD"])
        deck += [r + color[0], r + color[1]]
    random.shuffle(deck)
    return deck


def same_pair(a, b):
    return a[0] == b[0]


def cc_ai_pick(cards, taken, memory, first=None):
    """神経衰弱の AI. memory = {添字: カード} (覚えている裏の札)."""
    open_idx = [i for i in range(len(cards)) if i not in taken and i != first]
    known = {i: c for i, c in memory.items() if i not in taken and i != first}
    if first is None:
        seen = {}
        for i, c in known.items():          # 覚えているペアがあれば取りにいく
            if c[0] in seen:
                return seen[c[0]]
            seen[c[0]] = i
        unknown = [i for i in open_idx if i not in known]
        return random.choice(unknown or open_idx)
    for i, c in known.items():
        if same_pair(c, cards[first]):
            return i
    unknown = [i for i in open_idx if i not in known]
    return random.choice(unknown or open_idx)
