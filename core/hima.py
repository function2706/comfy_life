"""「話したい」: 話題なしで「暇だし話したい」と持ちかけて, 相手に乗ってもらう (会って = コマンド talk / メッセージ・電話 = 種類 smalltalk. 判定は同じ).

- 「話題を振る」(core/topics.py) は, あなたの体験を相手に渡す. こちらは話題なしで「話したい」と投げて, 相手が話すかどうか.
- 結果: hit (弾む) / ok (ふつう) / flat (乗らない). 相手の機嫌・話したがり (traits.approach)・ノリ・眠気・疲れ・退屈・寂しさ,
  あなたの話す力 (スキル talk), その日に何度目か (続けると飽きる) と揺らぎで決まる. 必ず弾む道は作らない.
- 乗らないときも, 基本は素っ気ない一言を返す (既読だけにはしない). 返さない・断るのは, メッセージ共通の関門
  (engine._reply_chance: 機嫌・好感度・ストレス・送りすぎ) と, 会っていて機嫌が悪いときの断り (talk の反応) だけ.
  仲の近さは結果ではなく断り方に効く: 近い仲 (互いの家に行ける・同居・好感度 70 以上) ははっきり断り, 浅い仲は取り繕う.
- 弾んだときに, ときどき相手の好き・苦手 (話題の好み. topics.tastes) が口に出て「知っていること」に残る (bonds.learn).
  まだ知らないものが先. 知っているものは, ときどき意見として口にする (「やっぱり○○っていいよね」. OPINION).
  話したがりで, 信頼があり, 機嫌がよいほど言う. 口にしたことは相手の言い分 (core/stance.py) になり, 肯定・否定で返せる.
"""
import random
from datetime import datetime

from . import nori as nori_mod

RESULTS = ("hit", "ok", "flat")
EFFECT = {"hit": {"boredom": -10, "loneliness": -8, "mood": 3, "affection": 1},
          "ok": {"boredom": -6, "loneliness": -5, "mood": 1},
          "flat": {"boredom": -1, "loneliness": -1}}
NORI = {"hit": 8, "ok": 0, "flat": -8}
HIT, FLAT = 12, -8           # 点数の区切り (これ以上で弾む / これ未満で乗らない)
REVEAL = {"like": "そういえば{fp}、{genre}がけっこう好きなんです。", "dislike": "{genre}は、正直ちょっと苦手で。"}
OPINION = {"like": "{genre}って、やっぱりいいですよね。", "dislike": "{genre}って、どうしても好きになれないんですよね。"}
OPINION_P = 0.5              # まだ知らない好みが無いとき, 知っている好みを意見として口にする割合
LABEL = {"hit": "弾んだ", "ok": "ふつう", "flat": "乗らない"}


def close(app, char, st):
    """断り方が率直になる仲か (近い仲: 互いの家に行ける・同居, または好感度 70 以上)."""
    return app.bonds.stage(char["id"]) in ("visit", "live") or st["params"].get("affection", 0) >= 70


def _today(st, now):
    day = datetime.fromtimestamp(now).strftime("%Y%m%d")
    rec = st.get("hima") or {}
    return day, (rec.get("n", 0) if rec.get("day") == day else 0)


def judge(app, char, st, now):
    """(結果, 判定の値). その日の回数を数える (結果を出したら 1 回)."""
    p = st["params"]
    tr = app.traits(char)
    lv = nori_mod.level(st, now)
    day, n = _today(st, now)
    sk = app.life.skill("talk")
    score = 0.25 * (p.get("mood", 50) - 50) + 14 * (float(tr.get("approach", 1.0)) - 1.0) \
        + (15 * (lv - 0.5) if lv is not None else 0) + 0.15 * (sk - 30) \
        + 0.1 * max(0.0, p.get("boredom", 0) - 40) + 0.08 * max(0.0, p.get("loneliness", 0) - 40) \
        - (10 if p.get("energy", 60) < 25 else 0) - (8 if p.get("sleepiness", 0) >= 70 else 0) \
        - 6 * n + random.uniform(-15, 15)
    res = "hit" if score >= HIT else "flat" if score < FLAT else "ok"
    if res != "ok" and random.random() < 0.1:      # 条件がそろっても今日はそれほど / 悪くても今日は付き合ってくれる (確定させない)
        res = "ok"
    st["hima"] = {"day": day, "n": n + 1}
    return res, {"score": round(score, 1), "n": n, "nori": lv, "skill": round(sk, 1)}


def speak(app, char, st, now, rng=random, opinion_p=OPINION_P):
    """好み (topics.tastes) を一つ口にする: まだ知らないもの (REVEAL. 知っていることに残す) が先, 無ければ opinion_p で
    知っているものを意見として (OPINION). (文, セリフの鍵, 言い分) を返す. 言わなければ None."""
    from .topics import TAGS
    from . import stance as stance_mod
    known = {(k.get("kind"), k.get("text")) for k in st.get("known") or []}
    tv = [(k, v) for k, v in sorted(app.topics.tastes(char, st).items()) if abs(v) >= 0.3 and k in TAGS]
    cands = [(k, v) for k, v in tv if (("like" if v > 0 else "dislike"), TAGS[k]) not in known]
    if cands:
        base, lines = "hima.reveal_", REVEAL
    elif tv and rng.random() < opinion_p:
        cands, base, lines = tv, "hima.opinion_", OPINION
    else:
        return None
    k, v = rng.choice(cands)
    kind = "like" if v > 0 else "dislike"
    app.bonds.learn(st, kind, TAGS[k], now)
    t = app.persona_text(char, base + kind) or lines[kind]
    fp = app.pronouns(char)[0]
    return t.replace("{genre}", TAGS[k]).replace("{fp}", fp), base + kind, stance_mod.of_taste(k, v)


def settle(app, char, st, res, now, out=None):
    """結果のあとの始末: ノリ・好みが口に出るか. 口にした一言 (文. {fp} は置き換え済み) を返す. 言わなければ None.
    out: 渡されれば, 口にした言い分を out["stance"] に (メッセージのトークに残す)."""
    if nori_mod.active(st, now) and NORI[res]:
        nori_mod.bump(app, st, now, NORI[res], "話したい: " + res)
    if res != "hit":
        return None
    p = st["params"]
    pr = 0.25 + (p.get("trust", 50) - 50) / 200.0 + (p.get("mood", 50) - 50) / 250.0 \
        + 0.15 * (float(app.traits(char).get("approach", 1.0)) - 1.0)
    if random.random() >= max(0.05, min(0.7, pr)):
        return None
    got = speak(app, char, st, now)
    if not got:
        return None
    if out is not None:
        out["stance"] = got[2]
    return got[0]
