"""相手のメッセージへの返し (1.6.0). 「よかったね」「大変だったね」「もっと聞かせて」など.

- 相手の最後のメッセージに, まだ返していないとき (24 時間のうち) だけ, 送る欄の先頭に「返す」のまとまりが出る.
  何に返すかは, 相手の最後のメッセージ (target). その中身の向き (tone) は, 返信の場面の鍵と文面 (問いかけで終わるか) から決める.
- 合う・外すは, 向き × 返し方 (FIT)・性格の好み (msgreply.TASTE を半分)・機嫌と仲・話の上手さ・揺らぎ. 返事を待つ話 (問いかけ・
  聞いて・寂しい など) に遅れて返すと, そのぶん響きにくい. 合えば, スタンプよりはっきり効き, 外すとはっきり悪い (謝れる心当たりに).
  「了解」「そっか」で話が終わるのは自然なので, 相手は返さないことも多い (返さなくても, 受け取り方は決まる).
- 相手からのメッセージ (働きかけ: 「話そう」「会いたい」「聞いて」「今どこ？」) にも, この返し方で返す (以前の 4 択の代わり).
  判定はここ, 効き目と相手の返しは働きかけのまま (core/presence.py reply_land. セリフは msgr.<区分>.<結果>).
- 返さないことの重さ (ignore_tick): 働きかけの待ち時間が過ぎたあとも既読のままなら, 相手の起きている時間に応じて少しずつ重くなる
  (上限あり). あなたが送った話への相手の返事が, 問いかけ・話を聞かせてくれたもの なら, 既読のまま放っておくと少し気にする.
  遅れてでも返せば, 重くなった分の一部は戻る.
"""
import random
from datetime import datetime

from . import msgreply

# (id, 文言, 印, トークに残す要約, 働きかけへの返事としての区分 msgreply.KINDS)
REACTS = [
    ("re_glad", "よかったね", "😊", "（「よかったね」と返した）", "cheerful"),
    ("re_hard", "大変だったね", "🫂", "（「大変だったね」とねぎらった）", "worry"),
    ("re_more", "もっと聞かせて", "👂", "（「もっと聞かせて」と返した）", "expand"),
    ("re_agree", "わかる", "🤝", "（「わかる」と返した）", "cheerful"),
    ("re_really", "ほんとに？", "😮", "（「ほんとに？」と返した）", "expand"),
    ("re_lol", "笑", "😆", "（「笑」と返した）", "cheerful"),
    ("re_sokka", "そっか", "💭", "（「そっか」と返した）", "curt"),
    ("re_ok", "了解", "👌", "（「了解」と返した）", "curt"),
    ("re_answer", "答える", "💬", "（聞かれたことに答えた）", "expand"),
]
IDS = tuple(r[0] for r in REACTS)
CAT = {r[0]: r[4] for r in REACTS}
CAT.update({"tease": "tease", "you_ok": "worry"})          # もとからある種類も, 相手のメッセージへの返しとして読む
AP_KINDS = IDS + ("tease", "you_ok")                       # 働きかけへの返事にできる種類
OPEN_H = 24                                                # これより前のメッセージには「返す」を出さない
GROUP = ("react", "↩", "返す")

TONE_LABEL = {"happy": "うれしい話", "down": "疲れた・沈んだ話", "upset": "不満・傷ついた", "lonely": "寂しい", "bored": "退屈",
              "question": "問いかけ", "where": "今どこ？", "news": "話を聞かせてくれた", "advice": "相談への答え",
              "notice": "予定・用件の連絡", "greet": "あいさつ", "close": "切り上げ", "plain": "ふつうの話"}
# 返信の場面の鍵 → 向き (無ければ plain. 問いかけで終わる文面は question)
_TONES = {
    "happy": ("invite_yes", "appoint_yes", "appoint_change_glad", "flirt", "tease", "photo", "selfie_yes", "stamp_heart", "smalltalk",
              "after_call", "favor_plants_thanks", "thanks", "stamp_thanks"),
    "upset": ("tease_hurt", "appoint_change_sour", "appoint_change_sour_late", "appoint_change_sour_again", "appoint_cancel_sour",
              "appoint_cancel_sour_late", "appoint_cancel_sour_again", "appoint_cancel_hurt", "appoint_cancel_favor_sour",
              "appoint_change_others", "appoint_missed", "favor_missed", "money_distrust", "want_space", "own_time", "too_often",
              "too_often_mild", "too_often_again", "late_night", "selfie_pester", "stamp_spam", "nudge_bad", "fight_cold", "apology_refuse",
              "apology_irritated", "stamp_sorry_bad", "stamp_only", "what_doing_much", "consult_jealous", "apology_not_yet"),
    "down": ("appoint_change_sad", "appoint_cancel_sad", "favor_plants_dead", "money_worry", "favor_lapsed"),
    "news": ("ask_how",),
    "advice": ("consult", "consult_good", "consult_off"),
    "notice": ("appoint_busy", "appoint_no", "appoint_counter", "appoint_cancel", "appoint_sorry", "appoint_rearranged", "appoint_move_mine",
               "appoint_change_fine", "appoint_change_keep_want", "appoint_change_keep_busy", "appoint_change_counter", "appoint_change_gone",
               "appoint_cancel_fine", "appoint_cancel_favor", "favor_ask_move", "favor_ask_offer", "favor_ask_when", "favor_ask_plants",
               "favor_yes", "favor_busy", "favor_counter", "favor_resched", "favor_cancel", "help_yes", "help_no", "help_busy", "help_counter",
               "help_iou_remind", "may_call_ok", "may_call_later", "invite_no", "invite_again", "care_call", "care_call_want", "repaid",
               "req_money_again", "selfie_no"),
    "greet": ("greet_morning", "greet_night", "greet_odd_morning", "greet_odd_night", "greet_again", "otsukare", "otsukare_odd"),
    "close": ("close_busy", "close_night", "close_cold"),
}
TONE_OF = {k: t for t, ks in _TONES.items() for k in ks}
AP_TONE = {"msg_miss": "lonely", "msg_today": "news", "msg_where": "where", "msg_chat": "bored"}
WHY_TONE = {"bored": "bored", "tired": "down", "happy": "happy", "lonely": "lonely"}
AWAIT = ("question", "where", "news", "lonely", "bored", "down", "happy")   # 返事を待っている話 (遅れると響きにくい)

# 返し方そのものの重み (msgreply.KIND_BASE と同じ目盛り: 10 以上で よく効く / -8 未満で よくない)
BASE = {"re_glad": 6, "re_hard": 4, "re_more": 6, "re_agree": 5, "re_really": 2, "re_lol": 1, "re_sokka": -5, "re_ok": -3, "re_answer": 3,
        "tease": 0, "you_ok": 3}
FIT = {
    "happy": {"re_glad": 10, "re_more": 8, "re_agree": 4, "re_really": 4, "re_lol": 2, "re_hard": -14, "you_ok": -10, "re_sokka": -10,
              "re_ok": -10, "re_answer": -6},
    "down": {"re_hard": 12, "you_ok": 10, "re_more": 4, "re_agree": 4, "re_glad": -16, "re_lol": -18, "re_really": -6, "re_sokka": -8,
             "re_ok": -10, "tease": -14, "re_answer": -6},
    "upset": {"re_ok": 4, "re_sokka": -4, "re_agree": 0, "re_hard": -6, "re_glad": -16, "re_lol": -20, "re_more": -8, "re_really": -12,
              "tease": -16, "you_ok": -2, "re_answer": -4},
    "lonely": {"re_more": 6, "re_hard": 4, "you_ok": 6, "re_agree": 2, "re_glad": -4, "re_lol": -8, "re_sokka": -16, "re_ok": -14,
               "tease": -4, "re_answer": -6},
    "bored": {"re_more": 6, "re_lol": 6, "re_agree": 4, "re_really": 2, "tease": 4, "re_glad": 0, "re_hard": -6, "re_sokka": -12, "re_ok": -10,
              "re_answer": -4},
    "question": {"re_answer": 12, "re_more": -4, "re_glad": -6, "re_agree": -4, "re_really": -4, "re_lol": -6, "re_sokka": -10, "re_ok": -6,
                 "re_hard": -6, "you_ok": -6, "tease": -4},
    "where": {"re_answer": 14, "you_ok": 2, "re_ok": -10, "re_sokka": -14, "re_lol": -12, "tease": -10, "re_glad": -8, "re_more": -8,
              "re_agree": -8, "re_really": -10, "re_hard": -8},
    "news": {"re_more": 10, "re_really": 6, "re_glad": 4, "re_agree": 2, "re_hard": 2, "re_sokka": -6, "re_ok": -8, "re_lol": -4, "re_answer": -4},
    "advice": {"re_agree": 8, "re_ok": 6, "re_more": 4, "re_glad": -4, "re_lol": -10, "re_sokka": -2, "re_really": -2, "re_hard": -4,
               "re_answer": -2},
    "notice": {"re_ok": 12, "re_glad": 4, "re_sokka": 2, "re_more": -6, "re_really": -2, "re_lol": -4, "re_hard": -6, "re_answer": -2},
    "greet": {"re_ok": 2, "re_glad": 2, "re_sokka": 0, "re_more": -2, "re_hard": -4, "re_answer": -6},
    "close": {"re_ok": 10, "re_sokka": 4, "re_glad": 0, "re_more": -12, "re_really": -6, "re_lol": -4, "re_answer": -6},
    "plain": {"re_sokka": -2, "re_answer": -6},
}
# 返さなくても自然な返し (話がそこで終わる): 相手が返事をしてくる割合を下げる
QUIET = {"notice", "close", "greet", "advice", "upset"}
EFFECT = {"good": {"mood": 2.5, "loneliness": -4, "affection": 0.5}, "neutral": {"loneliness": -1.5},
          "bad": {"mood": -3, "trust": -0.5}}
BAD_TELL = {"re_glad": "{call}に、話を軽く流された", "re_hard": "{call}に、大げさに受け取られた", "re_more": "{call}に、しつこく聞かれた",
            "re_agree": "{call}に、分かったふうに言われた", "re_really": "{call}に、疑われた", "re_lol": "{call}に、笑われた",
            "re_sokka": "{call}の返事が素っ気なかった", "re_ok": "{call}の返事が事務的だった", "re_answer": "{call}の答えがずれていた"}
# 共通の返し (性格プリセットに無ければ). 鍵は chat.react_<返し方>_<結果>
LINES = {
    "chat.react_glad_good": "📱『ありがとうございます。{call}にそう言ってもらえると、もっとうれしくなります』",
    "chat.react_glad_neutral": "📱『ふふ、ありがとうございます』",
    "chat.react_glad_bad": "📱『……よかった、っていう話じゃなかったんですけど』",
    "chat.react_hard_good": "📱『……うん。わかってもらえて、少し楽になりました』",
    "chat.react_hard_neutral": "📱『そこまでじゃないですよ。大丈夫です』",
    "chat.react_hard_bad": "📱『え？ ……別に、大変なことなんてないですけど』",
    "chat.react_more_good": "📱『聞いてくれるんですか？ えっと、それでですね……』",
    "chat.react_more_neutral": "📱『続きって言っても、それくらいなんですけど』",
    "chat.react_more_bad": "📱『……いまは、その話はもういいです』",
    "chat.react_agree_good": "📱『ですよね。わかってもらえて、うれしいです』",
    "chat.react_agree_neutral": "📱『そうですか？』",
    "chat.react_agree_bad": "📱『……本当にわかってます？』",
    "chat.react_really_good": "📱『ほんとなんです。{fp}もびっくりしました』",
    "chat.react_really_neutral": "📱『ほんとですよ』",
    "chat.react_really_bad": "📱『……嘘なんてついてないです』",
    "chat.react_lol_good": "📱『ふふ、笑ってもらえてよかったです』",
    "chat.react_lol_neutral": "📱『……そんなに面白かったですか？』",
    "chat.react_lol_bad": "📱『……笑うところじゃないです』",
    "chat.react_sokka_good": "📱『はい。また話しましょうね』",
    "chat.react_sokka_neutral": "📱『……はい』",
    "chat.react_sokka_bad": "📱『……それだけですか』",
    "chat.react_ok_good": "📱『はい、お願いしますね』",
    "chat.react_ok_neutral": "📱『はい』",
    "chat.react_ok_bad": "📱『……なんだか、事務的ですね』",
    "chat.react_answer_good": "📱『そうなんですね。教えてくれて、ありがとうございます』",
    "chat.react_answer_neutral": "📱『そうですか。わかりました』",
    "chat.react_answer_bad": "📱『……それ、答えになってないです』",
}
_RES_LABEL = {"good": "よく効いた", "neutral": "ふつう", "bad": "よくなかった"}
SCENE_LABEL = {"react_%s_%s" % (r[0][3:], o): "相手のメッセージへの返し「%s」に %s" % (r[1], _RES_LABEL[o])
               for r in REACTS for o in ("good", "neutral", "bad")}

# 返さないことの重さ (ignore_tick)
IGNORE_RATE, IGNORE_CAP = 0.5, 5.0          # 働きかけを既読のまま: 起きている 1 時間あたり / 上限 (機嫌. 性格・依存・急ぎで変わる)
AWAIT_RATE, AWAIT_CAP = 0.25, 2.0           # 相手の問いかけ・話を既読のまま (あなたが始めた話への返事)
AWAIT_AFTER_H = 2.0                         # これより早く返せば, 何も起きない
IGNORE_SPAN_H = 48                          # これを過ぎたら数えない
REFUND = 1.0 / 3                            # 遅れてでも返したら, 重くなった分のうちこれだけ戻る (よくなかった返事なら戻らない)


def said(kind):
    from .chat import KINDS
    return KINDS[kind][2] if kind in KINDS else ""


def text_question(text):
    """文面が問いかけで終わるか (性格ごとの文面しだい)."""
    t = (text or "").split("\n")[0].rstrip()
    if t.endswith("』"):
        t = t[:-1]
    t = t.rstrip("…。 　")
    return t.endswith(("？", "?"))


def tone_of(app, st, it):
    """相手のメッセージ (トークの 1 件) の向き."""
    kind = it.get("kind") or ""
    if kind == "approach":
        ap = it.get("ap")
        why = it.get("why")
        cur = st.get("approach") or {}
        if not ap and cur and abs(float(cur.get("t", 0)) - float(it.get("t", 0))) < 1:      # 以前のトーク: 印が無い. 待っている働きかけから
            ap, why = cur.get("id"), cur.get("why")
        if ap:
            if ap == "msg_chat" and why in WHY_TONE:
                return WHY_TONE[why]
            return AP_TONE.get(ap, "plain")
    if kind.startswith("react_"):
        return "plain"
    t = TONE_OF.get(kind)
    if t is None and kind.startswith("topic_"):
        t = "happy" if kind.endswith(("_good", "_like", "_yes")) else "plain"
    t = t or "plain"
    if t not in ("upset", "close") and text_question(it.get("text")):
        return "question"
    return t


def target(app, cid, st, now):
    """いま返すことのできる相手のメッセージ (相手の最後の発言. あなたがまだ返していない). 無ければ None."""
    items = [it for it in app.chat.load(cid)["items"] if it.get("who") in ("me", "her")]
    if not items or items[-1]["who"] != "her" or now - items[-1]["t"] > OPEN_H * 3600:
        return None
    it = items[-1]
    return {"t": it["t"], "kind": it.get("kind"), "tone": tone_of(app, st, it), "ap": it.get("ap")}


def ap_tone(aid, why):
    if aid == "msg_chat" and why in WHY_TONE:
        return WHY_TONE[why]
    return AP_TONE.get(aid, "plain")


def kinds_for(tone):
    """「返す」に並べる種類 (「答える」は問いかけのときだけ)."""
    return [k for k in IDS if k != "re_answer" or tone in ("question", "where")]


def group(app, cid, st, now):
    """送る欄の「返す」のまとまり (出さないときは None) と, 何に返すか."""
    tg = target(app, cid, st, now)
    ap = st.get("approach") or {}
    if ap and (app.presence.find(ap.get("id")) or {}).get("apart"):
        tone = ap_tone(ap.get("id"), ap.get("why"))
        tg = {"t": ap.get("t"), "kind": "approach", "tone": tone, "ap": ap.get("id")}
    if not tg:
        return None, None
    return {"id": GROUP[0], "icon": GROUP[1], "label": GROUP[2], "kinds": kinds_for(tg["tone"])}, tg


def judge(app, char, st, tone, kind, late_h=0.0, rng=random, noise=12):
    """返しがどう受け取られるか: (good / neutral / bad, 点)."""
    p = st["params"]
    taste = msgreply.TASTE.get(char.get("persona_id") or "", {})
    cat = CAT.get(kind, "cheerful")
    skill = app.life.skill_mult("talk")
    score = BASE.get(kind, 0) + FIT.get(tone, FIT["plain"]).get(kind, 0) + 0.5 * taste.get(cat, 0) \
        + 0.25 * (p.get("mood", 50) - 50) + 0.3 * (p.get("affection", 45) - 45) + 8 * (skill - 1.0) + rng.uniform(-noise, noise)
    if kind in ("tease", "re_lol"):          # 冗談・からかいは, 仲が深いほど通じる
        score += 0.3 * (p.get("affection", 45) - 60)
    if kind in ("re_sokka", "re_ok") and tone not in QUIET:     # 素っ気ない返しは, 寂しいときほど刺さる
        score -= 0.2 * max(0.0, p.get("loneliness", 30) - 40)
    if tone in AWAIT and late_h > 1:         # 返事を待っていた話に, 遅れて返す
        score -= min(12.0, 1.5 * (late_h - 1))
    res = "good" if score >= 10 else "neutral" if score >= -8 else "bad"
    if res == "good" and rng.random() < 0.1:   # 合う返しでも, 今日はそれほど響かないこともある
        res = "neutral"
    return res, score


def reply_chance(pr, kind, to):
    """相手が返事をしてくる割合: 「了解」「そっか」で話が終わるのは自然なので, 返さないことも多い."""
    tone = (to or {}).get("tone")
    if kind in ("re_ok", "re_sokka") and tone in QUIET:
        return pr * 0.35
    if tone in QUIET:
        return pr * 0.7
    return pr


def _refund(app, char, st, t_target, res, now):
    """遅れてでも返した: 返さないことで重くなった分の一部が戻る (よくなかった返事なら戻らない)."""
    back = 0.0
    for key in ("ap_ignored", "await_ignored"):
        rec = st.get(key)
        if not rec or abs(float(rec.get("t_msg", 0)) - float(t_target or 0)) > 1:
            continue
        st.pop(key, None)
        if res != "bad" and rec.get("applied"):
            back += float(rec["applied"]) * REFUND
    if back >= 0.1:
        app.apply_effects(st, {"mood": round(back, 2)})
        app.trace.add("react", "遅れてでも返した: 重くなった分の一部が戻った", char["id"], now, back=round(back, 2))
    return back


def land(app, char, st, kind, meta, now, silent=False):
    """返しを相手が読んだ: (場面の鍵, 効果, 置き換え). silent: 相手は返事をしない (受け取り方だけ決まる)."""
    to = (meta or {}).get("to") or {}
    tone = to.get("tone") or "plain"
    sent = float((meta or {}).get("sent") or now)
    late_h = max(0.0, (sent - float(to.get("t") or sent)) / 3600.0)
    res, score = judge(app, char, st, tone, kind, late_h)
    app.trace.add("react", "返しの受け取り方: %s → %s" % (kind, res), char["id"], now, tone=tone, score=round(score, 1),
                  late_h=round(late_h, 2), silent=silent)
    eff = dict(EFFECT[res])
    if res == "bad":
        call = app.pronouns(char)[2]
        app.life.add_reason(st, "player", "bad", BAD_TELL[kind].replace("{call}", call), now, told=not silent, delta=-3.0,
                            action="_react")
    _refund(app, char, st, to.get("t"), res, now)
    return "react_%s_%s" % (kind[3:], res), eff, {}


def land_silent(app, char, st, pend, now):
    """返事はしないが, 読んだ: 受け取り方だけ決まって効く."""
    _, eff, _ = land(app, char, st, pend["kind"], pend.get("meta") or {}, now, silent=True)
    eff, _ = app.bonds.realize(char, st, eff, "_chat_" + pend["kind"], now)
    app.apply_effects(st, app.trait_effects(char, eff))


# ------------------------------------------------------------------ 返さないことの重さ
def _awake_h(t0, t1):
    """t0〜t1 のうち, 相手が起きていそうな時間 (7 時〜24 時) の長さ (時間)."""
    if t1 <= t0:
        return 0.0
    h, t = 0.0, t0
    step = 900.0
    while t < t1:
        dt = min(step, t1 - t)
        if datetime.fromtimestamp(t + dt / 2).hour >= 7:
            h += dt / 3600.0
        t += dt
    return h


def _answered(items, t):
    return any(it.get("who") == "me" and it["t"] > t + 0.5 for it in items)


def ignore_tick(app, char, st, now):
    """画面を開いている間 (働きかけの抽せんのたび) に呼ぶ. 返さないまま既読で放っておくほど, 少しずつ重くなる. 変えたら True."""
    cid = char["id"]
    d = app.chat.load(cid)
    items = d["items"]
    seen = float(d.get("seen_t") or 0)
    changed = False
    since = st.setdefault("react_since", now)          # これより前のメッセージは数えない (以前のセーブ: 遡って重くしない)
    if since == now:
        changed = True
    tr = app.traits(char)
    call = app.pronouns(char)[2]
    # 1) 働きかけ (相手から来たメッセージ) を, 待ち時間が過ぎても既読のまま
    rec = st.get("ap_ignored")
    if rec:
        if _answered(items, rec["t_msg"]) or now - rec["t_msg"] > IGNORE_SPAN_H * 3600:
            st.pop("ap_ignored", None)
            rec, changed = None, True
        elif seen >= rec["t_msg"]:
            start = rec.setdefault("from", max(rec["t"], now if not rec.get("read") else rec["t"]))
            k = float(tr.get("absence", 1)) * float(rec.get("urgency", 1)) * (1 + 0.5 * app.attach.factor(char, st, "dependence"))
            want = min(IGNORE_CAP * k, IGNORE_RATE * k * _awake_h(start, now))
            d_ = want - float(rec.get("applied", 0))
            if d_ >= 0.2:
                app.apply_effects(st, {"mood": -round(d_, 2), "loneliness": round(d_ * 0.5, 2)})
                rec["applied"] = round(want, 2)
                changed = True
                if want >= 3 and not rec.get("told"):
                    rec["told"] = True
                    app.life.add_reason(st, "player", "bad", "%sに既読のまま、ずっと放っておかれた" % call, now, told=False,
                                        delta=-want, action="_ap_ignored")
                app.trace.add("react", "働きかけを既読のまま放っておいた: 重くなった", cid, now, applied=rec["applied"], k=round(k, 2))
    # 2) あなたが始めた話への相手の返事が, 問いかけ・話を聞かせてくれたもの: 既読のまま放っておくと少し気にする
    tg = target(app, cid, st, now)
    aw = st.get("await_ignored")
    if aw and (not tg or abs(tg["t"] - aw["t_msg"]) > 1):
        st.pop("await_ignored", None)
        aw, changed = None, True
    if tg and tg["kind"] != "approach" and tg["tone"] in ("question", "news") and tg["t"] >= since and seen >= tg["t"] \
            and now - tg["t"] > AWAIT_AFTER_H * 3600 and now - tg["t"] < IGNORE_SPAN_H * 3600:
        if not aw:
            aw = st["await_ignored"] = {"t_msg": tg["t"], "applied": 0.0, "tone": tg["tone"]}
        k = float(tr.get("absence", 1))
        want = min(AWAIT_CAP * k, AWAIT_RATE * k * _awake_h(tg["t"] + AWAIT_AFTER_H * 3600, now))
        d_ = want - float(aw.get("applied", 0))
        if d_ >= 0.2:
            app.apply_effects(st, {"mood": -round(d_, 2)})
            aw["applied"] = round(want, 2)
            changed = True
            if want >= 1.5 and not aw.get("told"):
                aw["told"] = True
                tell = "%sに聞いたのに、返事がなかった" if tg["tone"] == "question" else "%sに話したのに、返事がなかった"
                app.life.add_reason(st, "player", "bad", tell % call, now, told=False, delta=-want, action="_ap_await")
            app.trace.add("react", "問いかけ・話を既読のまま: 少し気にした", cid, now, applied=aw["applied"], tone=tg["tone"])
    return changed
