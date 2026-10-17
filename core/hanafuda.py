"""花札「こいこい」のルールと AI.

札は 0..47 の整数 (月 = id // 4). 出来役は一般的なルール (任天堂系) に準拠.
"""
import random

MONTHS = ["松", "梅", "桜", "藤", "菖蒲", "牡丹", "萩", "芒", "菊", "紅葉", "柳", "桐"]
# (種類, 札の名前, 特別なしるし)
CARDS = [
    ("hikari", "鶴", "tsuru"), ("tan", "赤短", "aka"), ("kasu", "カス", ""), ("kasu", "カス", ""),
    ("tane", "鶯", ""), ("tan", "赤短", "aka"), ("kasu", "カス", ""), ("kasu", "カス", ""),
    ("hikari", "幕", "maku"), ("tan", "赤短", "aka"), ("kasu", "カス", ""), ("kasu", "カス", ""),
    ("tane", "不如帰", ""), ("tan", "短冊", ""), ("kasu", "カス", ""), ("kasu", "カス", ""),
    ("tane", "八橋", ""), ("tan", "短冊", ""), ("kasu", "カス", ""), ("kasu", "カス", ""),
    ("tane", "蝶", "cho"), ("tan", "青短", "ao"), ("kasu", "カス", ""), ("kasu", "カス", ""),
    ("tane", "猪", "ino"), ("tan", "短冊", ""), ("kasu", "カス", ""), ("kasu", "カス", ""),
    ("hikari", "月", "tsuki"), ("tane", "雁", ""), ("kasu", "カス", ""), ("kasu", "カス", ""),
    ("tane", "盃", "sake"), ("tan", "青短", "ao"), ("kasu", "カス", ""), ("kasu", "カス", ""),
    ("tane", "鹿", "shika"), ("tan", "青短", "ao"), ("kasu", "カス", ""), ("kasu", "カス", ""),
    ("hikari", "小野道風", "rain"), ("tane", "燕", ""), ("tan", "短冊", ""), ("kasu", "カス", ""),
    ("hikari", "鳳凰", "houou"), ("kasu", "カス", ""), ("kasu", "カス", ""), ("kasu", "カス", ""),
]
KIND_NAME = {"hikari": "光", "tane": "タネ", "tan": "短冊", "kasu": "カス"}


def month(c):
    return c // 4


def kind(c):
    return CARDS[c][0]


def mark(c):
    return CARDS[c][2]


def card_label(c):
    return "%sに%s" % (MONTHS[month(c)], CARDS[c][1]) if CARDS[c][1] != "カス" else "%sのカス" % MONTHS[month(c)]


def new_deck():
    d = list(range(48))
    random.shuffle(d)
    return d


def deal():
    """手札 8 枚ずつ, 場 8 枚. 場に同じ月が 4 枚そろったら配り直し."""
    while True:
        d = new_deck()
        hands = {"p": sorted(d[:8]), "a": sorted(d[8:16])}
        field = d[16:24]
        if max(sum(1 for c in field if month(c) == m) for m in range(12)) < 4:
            return hands, field, d[24:]


def yaku(caps):
    """取り札から出来役 [(名前, 点)] を返す."""
    out = []
    hik = [c for c in caps if kind(c) == "hikari"]
    rain = any(mark(c) == "rain" for c in hik)
    if len(hik) == 5:
        out.append(("五光", 10))
    elif len(hik) == 4:
        out.append(("雨四光", 7) if rain else ("四光", 8))
    elif len(hik) == 3 and not rain:
        out.append(("三光", 5))
    marks = {mark(c) for c in caps}
    tane = sum(1 for c in caps if kind(c) == "tane")
    if {"ino", "shika", "cho"} <= marks:
        out.append(("猪鹿蝶", 5 + tane - 3))
    elif tane >= 5:
        out.append(("タネ", 1 + tane - 5))
    tan = sum(1 for c in caps if kind(c) == "tan")
    aka = sum(1 for c in caps if mark(c) == "aka")
    ao = sum(1 for c in caps if mark(c) == "ao")
    if aka == 3 and ao == 3:
        out.append(("赤短・青短", 10 + tan - 6))
    elif aka == 3:
        out.append(("赤短", 5 + tan - 3))
    elif ao == 3:
        out.append(("青短", 5 + tan - 3))
    elif tan >= 5:
        out.append(("タン", 1 + tan - 5))
    kasu = sum(1 for c in caps if kind(c) == "kasu") + (1 if "sake" in marks else 0)
    if kasu >= 10:
        out.append(("カス", 1 + kasu - 10))
    if "sake" in marks and "maku" in marks:
        out.append(("花見で一杯", 5))
    if "sake" in marks and "tsuki" in marks:
        out.append(("月見で一杯", 5))
    return out


def points(caps):
    return sum(p for _, p in yaku(caps))


def matches(card, field):
    return [f for f in field if month(f) == month(card)]


def capture(card, field, target=None):
    """card を場に出す. (取った札のリスト, 新しい場). 2 枚合うときは target を取る."""
    m = matches(card, field)
    field = list(field)
    if not m:
        return [], field + [card]
    if len(m) == 3:
        for f in m:
            field.remove(f)
        return [card] + m, field
    if len(m) == 2:
        t = target if target in m else max(m, key=value)
    else:
        t = m[0]
    field.remove(t)
    return [card, t], field


# ---------------------------------------------------------------------- AI
def value(c):
    k, mk = kind(c), mark(c)
    if k == "hikari":
        return 12 if mk == "rain" else 20
    if k == "tane":
        return 16 if mk == "sake" else 13 if mk in ("ino", "shika", "cho") else 8
    if k == "tan":
        return 10 if mk in ("aka", "ao") else 6
    return 1


def _gain(caps, got, opp_caps):
    """取った札の価値 + 役ができる/伸びる分 + 相手の役を邪魔できる分."""
    before = points(caps)
    after = points(caps + got)
    block = sum(value(c) * 0.3 for c in got if points(opp_caps + [c]) > points(opp_caps))
    return sum(value(c) for c in got) + (after - before) * 12 + block


def choose_play(hand, field, caps, opp_caps, err=0.0):
    """(出す札, 取る札 or None)."""
    if err and random.random() < err:
        return random.choice(hand), None
    best, best_v = None, -10 ** 9
    for c in hand:
        m = matches(c, field)
        targets = m if len(m) == 2 else [None]
        for t in targets:
            got, nf = capture(c, field, t)
            if got:
                v = _gain(caps, got, opp_caps)
            else:
                # 捨て札: 安い札を, 相手に取られにくい形で
                v = -value(c) * 1.5 - (6 if any(points(opp_caps + [c, f]) > points(opp_caps) for f in nf) else 0)
            v += random.random() * 0.5
            if v > best_v:
                best, best_v = (c, t), v
    return best


def choose_target(card, field, caps, opp_caps):
    m = matches(card, field)
    return max(m, key=lambda t: _gain(caps, [card, t], opp_caps)) if len(m) == 2 else None


def decide_koi(caps, opp_caps, hand_left, mood=50):
    """こいこいするか. 点が高い / 手札が少ない / 相手が役に近いときはあがる."""
    pts = points(caps)
    if pts >= 7 or hand_left <= 2:
        return False
    opp_threat = len([c for c in opp_caps if kind(c) == "hikari"]) >= 2 or points(opp_caps) > 0
    if opp_threat:
        return False
    rate = 0.45 + (mood - 50) / 200.0
    return random.random() < rate
