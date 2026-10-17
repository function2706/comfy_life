"""二人打ち簡易麻雀のルール (鳴きなし・リーチ/ツモ/ロンのみ).

牌は 0..33 の整数: 0-8 萬子, 9-17 筒子, 18-26 索子, 27-30 東南西北, 31-33 白發中.
"""
import random
from functools import lru_cache

HONOR = "東南西北白發中"
SUIT = "mps"


def label(t):
    return HONOR[t - 27] if t >= 27 else "%d%s" % (t % 9 + 1, SUIT[t // 9])


def is_yaochu(t):
    return t >= 27 or t % 9 in (0, 8)


def dora_of(ind):
    """ドラ表示牌 → ドラ."""
    if ind < 27:
        return ind // 9 * 9 + (ind % 9 + 1) % 9
    if ind < 31:
        return 27 + (ind - 27 + 1) % 4
    return 31 + (ind - 31 + 1) % 3


def to_counts(tiles):
    c = [0] * 34
    for t in tiles:
        c[t] += 1
    return c


# ---------------------------------------------------------------------- shanten
def shanten(c):
    """シャンテン数 (13 枚で 0 = 聴牌, 14 枚で -1 = 和了)."""
    return _shanten(tuple(c))


@lru_cache(maxsize=200000)
def _shanten(c):
    return min(_regular(list(c)), _chiitoi(c), _kokushi(c))


def _chiitoi(c):
    pairs = sum(1 for x in c if x >= 2)
    kinds = sum(1 for x in c if x >= 1)
    return 6 - pairs + max(0, 7 - kinds)


_YAOCHU = [i for i in range(34) if is_yaochu(i)]


def _kokushi(c):
    kinds = sum(1 for i in _YAOCHU if c[i])
    pair = any(c[i] >= 2 for i in _YAOCHU)
    return 13 - kinds - (1 if pair else 0)


def _regular(c):
    best = [8]

    def dfs(i, m, t, p):
        while i < 34 and c[i] == 0:
            i += 1
        cur = 8 - 2 * m - min(t, 4 - m) - p
        if i == 34:
            if cur < best[0]:
                best[0] = cur
            return
        rest = sum(c[i:])
        # 楽観的な見積もり (残り 3 枚で面子 1 つ) でも更新できないなら打ち切り
        if cur - (2 * rest) // 3 - (0 if p else 1) >= best[0]:
            return
        if c[i] >= 3:
            c[i] -= 3
            dfs(i, m + 1, t, p)
            c[i] += 3
        if i < 27 and i % 9 <= 6 and c[i + 1] and c[i + 2]:
            c[i] -= 1; c[i + 1] -= 1; c[i + 2] -= 1
            dfs(i, m + 1, t, p)
            c[i] += 1; c[i + 1] += 1; c[i + 2] += 1
        if c[i] >= 2:
            c[i] -= 2
            if not p:
                dfs(i, m, t, 1)
            dfs(i, m, t + 1, p)
            c[i] += 2
        if i < 27 and i % 9 <= 7 and c[i + 1]:
            c[i] -= 1; c[i + 1] -= 1
            dfs(i, m, t + 1, p)
            c[i] += 1; c[i + 1] += 1
        if i < 27 and i % 9 <= 6 and c[i + 2]:
            c[i] -= 1; c[i + 2] -= 1
            dfs(i, m, t + 1, p)
            c[i] += 1; c[i + 2] += 1
        c[i] -= 1
        dfs(i, m, t, p)
        c[i] += 1

    dfs(0, 0, 0, 0)
    return best[0]


# ---------------------------------------------------------------------- agari
def _melds(c, i):
    while i < 34 and c[i] == 0:
        i += 1
    if i == 34:
        return [[]]
    res = []
    if c[i] >= 3:
        c[i] -= 3
        res += [[("k", i)] + m for m in _melds(c, i)]
        c[i] += 3
    if i < 27 and i % 9 <= 6 and c[i + 1] and c[i + 2]:
        c[i] -= 1; c[i + 1] -= 1; c[i + 2] -= 1
        res += [[("s", i)] + m for m in _melds(c, i)]
        c[i] += 1; c[i + 1] += 1; c[i + 2] += 1
    return res


def decompositions(c):
    out = []
    for p in range(34):
        if c[p] >= 2:
            c2 = list(c)
            c2[p] -= 2
            out += [(p, ms) for ms in _melds(c2, 0)]
    return out


def is_chiitoi(c):
    return sum(c) == 14 and sum(1 for x in c if x == 2) == 7


def is_kokushi(c):
    return sum(c) == 14 and all(c[i] for i in _YAOCHU) and sum(c[i] for i in _YAOCHU) == 14


def is_agari(c):
    return sum(c) == 14 and (is_chiitoi(c) or is_kokushi(c) or bool(decompositions(c)))


def waits(tiles13):
    c = to_counts(tiles13)
    out = []
    for t in range(34):
        if c[t] >= 4:
            continue
        c[t] += 1
        if is_agari(c):
            out.append(t)
        c[t] -= 1
    return out


# ---------------------------------------------------------------------- yaku
def evaluate(tiles14, win, tsumo, riichi, seat, rnd, dora_inds, ura_inds):
    """和了形の最高評価 {"han", "yaku": [(名前, 翻)], "yakuman"} を返す. 役なしなら None."""
    c = to_counts(tiles14)
    best = [None]
    honors = any(t >= 27 for t in tiles14)
    suits = {t // 9 for t in tiles14 if t < 27}
    tanyao = not any(is_yaochu(t) for t in tiles14)
    all_yaochu = all(is_yaochu(t) for t in tiles14)
    all_honor = all(t >= 27 for t in tiles14)
    flush = []
    if len(suits) == 1:
        flush = [("混一色", 3)] if honors else [("清一色", 6)]
    common = ([("立直", 1)] if riichi else []) + ([("門前清自摸和", 1)] if tsumo else [])

    def finish(yaku):
        if not yaku:
            return
        ym = [y for y in yaku if y[1] >= 13]
        if ym:
            yaku = ym
        else:
            d = sum(c[dora_of(i)] for i in dora_inds)
            if d:
                yaku = yaku + [("ドラ", d)]
            if riichi:
                u = sum(c[dora_of(i)] for i in ura_inds)
                if u:
                    yaku = yaku + [("裏ドラ", u)]
        han = sum(h for _, h in yaku)
        if best[0] is None or han > best[0]["han"]:
            best[0] = {"han": han, "yaku": yaku, "yakuman": bool(ym)}

    if is_kokushi(c):
        finish([("国士無双", 13)])
    if is_chiitoi(c):
        y = common + [("七対子", 2)] + flush
        if tanyao:
            y.append(("断幺九", 1))
        if all_yaochu:
            y.append(("混老頭", 2))
        if all_honor:
            y.append(("字一色", 13))
        finish(y)

    for pair, melds in decompositions(c):
        places = [("pair", None)] if pair == win else []
        for j, (k, t) in enumerate(melds):
            if (k == "k" and t == win) or (k == "s" and t <= win <= t + 2):
                places.append((k, j))
        seqs = [t for k, t in melds if k == "s"]
        trips = [t for k, t in melds if k == "k"]
        for kind, j in places:
            y = list(common)
            if tanyao:
                y.append(("断幺九", 1))
            wait = "tanki" if kind == "pair" else "shanpon"
            if kind == "s":
                t = melds[j][1]
                if win == t + 1:
                    wait = "kanchan"
                elif (win == t and t % 9 == 6) or (win == t + 2 and t % 9 == 0):
                    wait = "penchan"
                else:
                    wait = "ryanmen"
            pair_yakuhai = pair >= 31 or pair in (seat, rnd)
            if len(seqs) == 4 and wait == "ryanmen" and not pair_yakuhai:
                y.append(("平和", 1))
            for t in trips:
                if t >= 31:
                    y.append(("役牌 " + HONOR[t - 27], 1))
                if t == seat:
                    y.append(("自風 " + HONOR[t - 27], 1))
                if t == rnd:
                    y.append(("場風 " + HONOR[t - 27], 1))
            if any(seqs.count(s) >= 2 for s in set(seqs)):
                y.append(("一盃口", 1))
            for s0 in (0, 9, 18):
                if s0 in seqs and s0 + 3 in seqs and s0 + 6 in seqs:
                    y.append(("一気通貫", 2))
            for n in range(7):
                if n in seqs and n + 9 in seqs and n + 18 in seqs:
                    y.append(("三色同順", 2))
                    break
            if len(trips) == 4:
                y.append(("対々和", 2))
            concealed = len(trips) - (1 if (kind == "k" and not tsumo) else 0)
            if concealed == 4:
                y.append(("四暗刻", 13))
            elif concealed == 3:
                y.append(("三暗刻", 2))
            dragons = [t for t in trips if t >= 31]
            if len(dragons) == 3:
                y.append(("大三元", 13))
            elif len(dragons) == 2 and pair >= 31:
                y.append(("小三元", 2))
            if seqs and is_yaochu(pair) and all(is_yaochu(t) if k == "k" else t % 9 in (0, 6) for k, t in melds):
                y.append(("混全帯幺九", 2) if honors else ("純全帯幺九", 3))
            if not seqs and all_yaochu and not all_honor:
                y.append(("混老頭", 2))
            if all_honor:
                y.append(("字一色", 13))
            finish(y + flush)
    return best[0]


def stage_steps(result, steps):
    """翻数 → 脱衣の段階数. steps = [[最低翻, 段階数], ...] (翻の昇順)."""
    n = 1
    for lo, k in steps:
        if result["han"] >= lo:
            n = k
    return n


# ---------------------------------------------------------------------- AI
def choose_discard(hand14, visible, opp_riichi=False, opp_river=(), err=0.0):
    """捨て牌を選ぶ. シャンテン数 → 受け入れ枚数 → 孤立した字牌/端牌 の順で評価.
    相手リーチ中で遠いときは現物を優先. err の確率で甘い手を選ぶ."""
    c = to_counts(hand14)
    scored = []
    for t in sorted(set(hand14)):
        c[t] -= 1
        scored.append({"t": t, "sh": shanten(c), "uk": 0})
        c[t] += 1
    mn = min(s["sh"] for s in scored)
    for s in scored:
        if s["sh"] > mn + (1 if err else 0):
            continue
        c[s["t"]] -= 1
        uk = 0
        for x in range(34):
            left = 4 - visible[x] - c[x]
            if left <= 0:
                continue
            c[x] += 1
            if shanten(c) < s["sh"]:
                uk += left
            c[x] -= 1
        c[s["t"]] += 1
        s["uk"] = uk

    def key(s):
        isolated = 1 if (c[s["t"]] == 1 and (s["t"] >= 27 or s["t"] % 9 in (0, 8))) else 0
        return (-s["sh"], s["uk"], isolated, random.random())

    if opp_riichi and mn >= 1:
        safe = [s for s in scored if s["t"] in opp_river]
        if safe:
            return max(safe, key=key)["t"]
    if err and random.random() < err:
        pool = [s for s in scored if s["sh"] <= mn + 1]
        return random.choice(pool)["t"]
    return max([s for s in scored if s["sh"] == mn], key=key)["t"]


def riichi_discards(hand14):
    """リーチ宣言できる捨て牌 (捨てると聴牌になる牌)."""
    c = to_counts(hand14)
    out = []
    for t in sorted(set(hand14)):
        c[t] -= 1
        if shanten(c) == 0:
            out.append(t)
        c[t] += 1
    return out
