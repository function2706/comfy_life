"""ヨット (ヤッツィー系のダイスゲーム) のルールと AI.

役 (世界のアソビ大全のヨットに準拠):
  1〜6        その目の合計            チョイス      5 個の合計
  フォーダイス  同じ目 4 個以上 → 5 個の合計
  フルハウス    3 個 + 2 個 (5 個同じも可) → 5 個の合計
  S.ストレート  4 つ連続 → 15         B.ストレート  5 つ連続 → 30
  ヨット        5 個同じ → 50
上段 (1〜6) の合計が 63 以上なら +35. 1 ターン最大 3 回振れる.
"""
import random

CATS = ["ones", "twos", "threes", "fours", "fives", "sixes",
        "choice", "four", "full", "sstr", "lstr", "yacht"]
NAMES = {"ones": "1の目", "twos": "2の目", "threes": "3の目", "fours": "4の目", "fives": "5の目", "sixes": "6の目",
         "choice": "チョイス", "four": "フォーダイス", "full": "フルハウス",
         "sstr": "S.ストレート", "lstr": "B.ストレート", "yacht": "ヨット"}
UPPER = CATS[:6]
BONUS_LINE, BONUS = 63, 35
# 役ごとの「並みの点数」. これより良ければ得, 悪ければ損として役の選択に使う
PAR = {"ones": 2.5, "twos": 5, "threes": 8, "fours": 11, "fives": 14, "sixes": 17,
       "choice": 22, "four": 13, "full": 18, "sstr": 9, "lstr": 9, "yacht": 10}


def score(cat, dice):
    cnt = [dice.count(f) for f in range(1, 7)]
    total = sum(dice)
    if cat in UPPER:
        face = UPPER.index(cat) + 1
        return cnt[face - 1] * face
    if cat == "choice":
        return total
    if cat == "four":
        return total if max(cnt) >= 4 else 0
    if cat == "full":
        return total if sorted(c for c in cnt if c) in ([2, 3], [5]) else 0
    faces = set(dice)
    if cat == "sstr":
        return 15 if any(set(range(s, s + 4)) <= faces for s in (1, 2, 3)) else 0
    if cat == "lstr":
        return 30 if faces in ({1, 2, 3, 4, 5}, {2, 3, 4, 5, 6}) else 0
    if cat == "yacht":
        return 50 if max(cnt) == 5 else 0
    raise ValueError(cat)


def totals(sheet):
    upper = sum(v for k, v in sheet.items() if k in UPPER)
    bonus = BONUS if upper >= BONUS_LINE else 0
    return {"upper": upper, "bonus": bonus, "total": sum(sheet.values()) + bonus}


def roll(dice, hold):
    return [d if (dice and hold[i]) else random.randint(1, 6) for i, d in enumerate(dice or [0] * 5)]


# ---------------------------------------------------------------------- AI
def _cat_value(cat, dice, sheet):
    """役に入れたときの評価 (並みとの差 + 上段ボーナスへの寄与)."""
    s = score(cat, dice)
    v = s - PAR[cat]
    if cat in UPPER:
        face = UPPER.index(cat) + 1
        up = totals(sheet)["upper"]
        if up < BONUS_LINE:
            v += (s - 3 * face) * 0.6          # 3 個そろい基準で上段ボーナスに近づくか
            if up + s >= BONUS_LINE:
                v += 20
    if cat == "yacht" and s:
        v += 15
    return v


def choose_cat(dice, sheet):
    open_cats = [c for c in CATS if c not in sheet]
    return max(open_cats, key=lambda c: (_cat_value(c, dice, sheet), -PAR[c]))


def _best_value(dice, sheet):
    return max(_cat_value(c, dice, sheet) for c in CATS if c not in sheet)


def choose_hold(dice, sheet, rolls_left, err=0.0, samples=60):
    """残すサイコロを選ぶ. 32 通りの残し方を, 振り直し後の最善評価の平均で比べる."""
    if err and random.random() < err:
        return [random.random() < 0.5 for _ in range(5)]
    best, best_v = [True] * 5, _best_value(dice, sheet)   # 全部残す = ここで確定
    seen = set()
    for mask in range(31):
        hold = [bool(mask >> i & 1) for i in range(5)]
        key = tuple(sorted(d for d, h in zip(dice, hold) if h))
        if key in seen:
            continue
        seen.add(key)
        tot = 0.0
        for _ in range(samples):
            nd = roll(dice, hold)
            v = _best_value(nd, sheet)
            if rolls_left > 1:
                v += 2.5   # もう一回振れる余地をざっくり加点
            tot += v
        v = tot / samples
        if v > best_v:
            best, best_v = hold, v
    return best


def ai_turn(sheet, skill=0.7, err=0.0):
    """キャラの 1 ターン. (振った経過のリスト, 最後の出目, 入れた役)."""
    samples = 30 + int(60 * skill)
    dice = roll(None, [False] * 5)
    steps = [{"dice": list(dice), "hold": [False] * 5}]
    for rolls_left in (2, 1):
        hold = choose_hold(dice, sheet, rolls_left, err, samples)
        if all(hold):
            break
        dice = roll(dice, hold)
        steps.append({"dice": list(dice), "hold": hold})
    return steps, dice, choose_cat(dice, sheet)
