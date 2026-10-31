"""メッセージのやりとりの「ノリ」: いまの会話に相手がどれだけ乗っているか (0〜100. 画面には出さない).

- 会話の始まり (相手から送ってきた・あなたのメッセージを読んだ) に, 退屈・寂しさ・機嫌・好感度・性格 (話しかけてくる多さ)・
  時間帯・揺らぎで決まる. 相手から送ってきたときは乗っている (暇で送ってきた「何してます？」はなおさら).
- やりとりのたびに動く: 返事がよく効けば上がり, 外せば下がる. 続けるほど少しずつ疲れて下がる (公理: 盛り上がり続けない).
- 効き目: 乗っているほど, スマホを見ている時間が長く, すぐ返ってきやすく, 時間差の返信も早く, もう一言が付きやすい.
  下がりきると, 相手から切り上げる (「そろそろ寝ますね」など). 30 分やりとりが無ければ, 会話は終わり (次はまた始まりから).
- 嫌われているときの未読スルー (読まない) は engine 側 (_send_later / deliver_due).
"""
import random
from datetime import datetime

IDLE = 30 * 60          # これだけやりとりが無ければ, 会話は終わり
CLOSE_BELOW = 20        # 会話中にこれを下回ったら, 相手から切り上げる
CLOSE_TURNS = 2         # 切り上げるのは, 何往復かしてから (1 通読んで返しただけで「またあとで」とは言わない)
TIRE = 6                # 1 往復ごとの疲れ
# 切り上げのひとこと (性格プリセットに chat.close_<場面> があればそちら)
LINES = {
    "chat.close_night": "📱『そろそろ寝ますね。おやすみなさい』",
    "chat.close_busy": "📱『あ、ちょっと用事があるので、またあとで！』",
    "chat.close_cold": "📱『（スタンプだけ返ってきた）』",
}
SCENE_LABEL = {"close_night": "ノリが下がって会話を切り上げる (夜)", "close_busy": "ノリが下がって会話を切り上げる (昼. 用事を口実に)",
               "close_cold": "ノリが下がって会話を切り上げる (仲が浅い・機嫌が悪い. 素っ気なく)"}


def _rec(st):
    return st.get("nori") or {}


def active(st, now):
    r = _rec(st)
    return bool(r) and now - r.get("t", 0) < IDLE


def level(st, now):
    """会話中ならノリ (0〜1), 会話していなければ None."""
    return _rec(st)["v"] / 100.0 if active(st, now) else None


def hour_at(now):
    """その時刻の時 (0〜23). テストでは時計を固定するので, ここから取る (tools/testclock.py)."""
    return datetime.fromtimestamp(now).hour


def base(app, char, st, now, boost=0.0):
    """会話の始まりのノリ."""
    p = st["params"]
    h = hour_at(now)
    v = 40 + 0.35 * (p.get("boredom", 30) - 30) + 0.3 * (p.get("loneliness", 30) - 30) + 0.3 * (p.get("mood", 50) - 50) \
        + 0.35 * (p.get("affection", 50) - 50) + 20 * (float(app.traits(char).get("approach", 1)) - 1) \
        + 8 * app.attach.factor(char, st, "dependence") - (25 if app.quarrel.active(st, now) else 0) - (12 if h >= 23 or h < 6 else 0) - (0.2 * max(0.0, p.get("stress", 0) - 50)) + boost + random.uniform(-12, 12)
    return max(0.0, min(100.0, v))


def start(app, char, st, now, boost=0.0, why=""):
    """会話を始める (もう始まっていれば, いまのノリに少し足すだけ). いまのノリ (0〜100) を返す."""
    if active(st, now):
        return bump(app, st, now, boost * 0.5, why)
    v = base(app, char, st, now, boost)
    st["nori"] = {"v": round(v, 1), "t": now, "turns": 0}
    trace = getattr(app, "trace", None)
    if trace:
        trace.add("nori", "会話の始まりのノリ", cid=char.get("id"), t=now, v=round(v, 1), boost=boost, why=why)
    return v


def bump(app, st, now, d, why=""):
    r = st.get("nori")
    if not r:
        return None
    r["v"] = round(max(0.0, min(100.0, r["v"] + d)), 1)
    r["t"] = now
    r["turns"] = r.get("turns", 0) + 1
    trace = getattr(app, "trace", None)
    if trace and why:
        trace.add("nori", "ノリが動いた", t=now, v=r["v"], d=round(d, 1), why=why, turns=r["turns"])
    return r["v"]


def after_reply(app, char, st, now, mood_delta, bad=False):
    """相手が返したあと: 返事の効き目 (機嫌の動き) で上下し, 続けた分だけ疲れる. 切り上げるなら True."""
    if not active(st, now):
        start(app, char, st, now, why="あなたのメッセージを読んだ")
    d = max(-12.0, min(10.0, 2.5 * mood_delta)) - (15 if bad else 0) - TIRE
    v = bump(app, st, now, d, "返信の効き目")
    return _closing(st, v)


def after_choice(app, char, st, now, res):
    """相手からのメッセージに選んだ返事をしたあと (good / neutral / bad)."""
    if not active(st, now):
        start(app, char, st, now, why="返事を読んだ")
    v = bump(app, st, now, {"good": 12, "neutral": -3, "bad": -18}[res] - TIRE * 0.6, "選んだ返事: " + res)
    return _closing(st, v)


def _closing(st, v):
    return v is not None and v < CLOSE_BELOW and (st.get("nori") or {}).get("turns", 0) >= CLOSE_TURNS


def close_key(app, char, st, now):
    """切り上げ方: 仲が浅い・機嫌が悪いなら素っ気なく, 夜なら寝る, 昼は用事を口実に."""
    p = st["params"]
    if p.get("affection", 50) < 40 or p.get("mood", 50) < 35:
        return "close_cold"
    h = hour_at(now)
    return "close_night" if h >= 21 or h < 5 else "close_busy"


def close(app, char, st, now):
    """相手から会話を切り上げる: ひとことを返し, スマホを置く. 次はまた会話の始まりから. 言ったひとことを返す."""
    key = close_key(app, char, st, now)
    text = app.persona_text(char, "chat." + key) or LINES["chat." + key]
    fp, _, call = app.pronouns(char)
    text = text.replace("{fp}", fp).replace("{call}", call).replace("{name}", char.get("name", ""))
    st.pop("nori", None)
    st["phone_until"] = 0
    st["phone_turns"] = 0
    trace = getattr(app, "trace", None)
    if trace:
        trace.add("nori", "ノリが下がって切り上げた", cid=char.get("id"), t=now, key=key)
    return key, text
