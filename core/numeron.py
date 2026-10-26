"""数当て (Hit & Blow / ヌメロン): 0〜9 の違う数字 3 つを当て合う.

- 当てる側が 3 桁を言うと, 言われた側は ヒット (数字も場所も合う) と ブロー (数字だけ合う) の数を答える. 3 ヒットで当たり.
- キャラの推理 (ai_guess): これまでの答えと矛盾しない候補 (candidates) から選ぶ. 強さ (0〜1) が高いほど, 答えの分かれ方が細かい
  (残る候補の見込みが少ない) 一手を選ぶ. 弱いときはそれっぽい候補を適当に, 前の手がかりを忘れたり, 読み違えると矛盾する手も
  言う (いつも最善ではない).
"""
import itertools
import random

ALL = ["".join(p) for p in itertools.permutations("0123456789", 3)]


def hb(secret, guess):
    hit = sum(1 for a, b in zip(secret, guess) if a == b)
    blow = len(set(secret) & set(guess)) - hit
    return hit, blow


def valid(s):
    return isinstance(s, str) and len(s) == 3 and s.isdigit() and len(set(s)) == 3


def candidates(history):
    """これまでの (言った数, ヒット, ブロー) と矛盾しない候補."""
    return [c for c in ALL if all(hb(c, g) == (h, b) for g, h, b in history)]


def expected_left(guess, cands):
    """この数を言ったときに残る候補の見込み (答えごとの候補数の二乗和 / 候補数). 小さいほど絞れる一手."""
    groups = {}
    for c in cands:
        k = hb(c, guess)
        groups[k] = groups.get(k, 0) + 1
    return sum(v * v for v in groups.values()) / float(len(cands))


def ai_guess(history, strength, err, rng=random):
    """キャラの一手. strength: 0〜1 (推理の冴え), err: 読み違え (矛盾する手を言う) の確率."""
    cands = candidates(history)
    if len(history) > 2 and rng.random() < (1 - strength) * 0.6:      # 前の手がかりをうっかり忘れる (直近の 2 つだけで考える)
        said = {g for g, _, _ in history}
        cands = [c for c in candidates(history[-2:]) if c not in said] or cands
    if not cands or rng.random() < err:
        pool = [c for c in ALL if c not in {g for g, _, _ in history}]
        return rng.choice(pool), len(cands)
    if len(cands) <= 2 or rng.random() >= strength:
        return rng.choice(cands), len(cands)
    look = rng.sample(cands, min(len(cands), 40)) + rng.sample(ALL, 20)
    best = min(look, key=lambda g: (expected_left(g, cands), g not in cands))
    return best, len(cands)
