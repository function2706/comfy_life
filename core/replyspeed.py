# -*- coding: utf-8 -*-
"""メッセージの返信の早さ (時間差の返信がいつ届くか).

- 性格の「返信の早さ」(traits.reply. 0.4 遅い 〜 1.6 早い) と, 返す間隔のばらつき (traits.reply_spread. 既定 0.9).
  話しかけてくる多さ (approach) とは別の軸: 事務的な人は自分からは来ないが返すのは早い, クールな人は遅い, など.
- たまたまスマホを手にしていれば, 最初の 1 通でもすぐ返ってくる (0.5〜3 分). 見込みは場面 (家でくつろいでいる > 移動中 >
  外にいる・食事中) × 性格の早さ × 依存度 (+ で上がる)・献身度 (少し) × 好感度・機嫌 × 連絡の多さ・言い争いのあと・会話のノリ.
- 手にしていなければ, 対数正規の待ち (数分で返すことが多く, たまに何時間も空く). 中央値は 15 分 / 性格の早さ を,
  依存度・献身度 (+) で縮め, 機嫌・好感度の低さ・連絡の多さ・言い争いで延ばす.
- 現実性の公理: 親しくなるほど一様に早くなる作りにはしない. 近い仲 (同居など) では「気づいていたけど後回し」の安心感の遅れが
  ときどき入る. 依存度が高くても毎回すぐではない. 寝ている・手が離せないあいだは, 届くときに後回し (engine.deliver_due).
- 直前まで相手がスマホを見ていたときのすぐの返信 (engine._still_on_phone) は, この前に決まる (こちらは別の仕組み).
"""
import math
import random

BASE_MEDIAN = 15.0           # 分. 性格の早さ 1・ふつうの状態での中央値
QUICK = (30, 180)            # 秒. 手にしていたときの返信
MIN_S, MAX_S = 20, 6 * 3600  # 待ちの下限・上限
HOME_IDLE = ("relax", "night", "awake", "morning", "game", "hobby", "getready")
MOVING = ("moving", "commute", "walk")


def where(scene):
    """返信の見込みに効く場面の大まかな区分: home (家でくつろいでいる) / moving (移動中) / meal (食事・家事) / out (外・ほか)."""
    act = scene.get("activity") or ""
    if act in MOVING:
        return "moving"
    if scene.get("away") or scene.get("outing"):
        return "out"
    if act in HOME_IDLE:
        return "home"
    return "meal"


HAND = {"home": 0.28, "moving": 0.22, "meal": 0.14, "out": 0.12}
WAIT = {"home": 1.0, "moving": 1.1, "meal": 1.3, "out": 1.6}     # 手にしていなかったときの待ちの伸び


def hand_chance(speed, place, dv, dep, aff, mood, many=False, fight=False, lv=None):
    """たまたまスマホを手にしていて, すぐ返す見込み."""
    p = HAND.get(place, 0.12) * speed
    p *= 1 + 0.45 * max(0.0, dep) + 0.15 * max(0.0, dv) - 0.2 * max(0.0, -dep)
    p *= 0.5 if aff < 40 else (1.15 if aff >= 75 else 1.0)
    p *= 0.6 if mood < 35 else 1.0
    p *= 0.6 if many else 1.0
    p *= 0.4 if fight else 1.0
    if lv is not None:
        p *= 0.5 + lv
    return max(0.0, min(0.5, p))


def median_min(speed, dv, dep, aff, mood, many=False, fight=False, lv=None, place="home"):
    """手にしていなかったときの待ちの中央値 (分)."""
    m = BASE_MEDIAN / max(0.3, speed) * WAIT.get(place, 1.3)
    m *= 1 - 0.3 * max(0.0, dep) - 0.1 * max(0.0, dv) + 0.25 * max(0.0, -dep)
    m *= 2 if mood < 35 else 1
    m *= 2 if aff < 40 else 1
    m *= 1.5 if many else 1
    m *= 1.8 if fight else 1
    if lv is not None:
        m *= 1.5 - lv
    return m


def slack_chance(close):
    """近い仲の「気づいていたけど後回し」(安心感の遅れ) の見込み."""
    return 0.0 if close < 0.6 else min(0.25, 0.1 + 0.4 * (close - 0.6))


def plan(traits, place, dv, dep, aff, mood, close, many=False, fight=False, lv=None, rnd=random):
    """返信までの秒数と, すぐ返したか (手にしていた) を決める."""
    speed = float(traits.get("reply", 1.0))
    if rnd.random() < hand_chance(speed, place, dv, dep, aff, mood, many, fight, lv):
        return rnd.uniform(*QUICK), True
    m = median_min(speed, dv, dep, aff, mood, many, fight, lv, place)
    sd = float(traits.get("reply_spread", 0.9))
    s = m * 60 * math.exp(rnd.gauss(0, sd))
    if rnd.random() < slack_chance(close):
        s *= rnd.uniform(2, 5)
    return max(MIN_S, min(MAX_S, s)), False
