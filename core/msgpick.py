"""メッセージで「何について」を選ぶ: 謝る理由・お礼の理由・相談の中身・スタンプの種類 (A1/A2).

- 謝る理由 (apology_choices): あなたが相手にした・しなかったこと. 分類も「最近あったこと」も出さず, 決まった順に 1 列
  (ちゃんと選ぶ手間も遊びのうち). 機嫌の理由 (life.add_reason) の action を, 選べる項目に当てる (reason_item).
  「近い」は画面に出さない内部のまとまり (NEAR) で見る. コマンド・メッセージの種類が原因の理由は, その名前の項目に.
- お礼の理由 (thanks_choices): 相手がしてくれたこと (manners.favor の what) と「許してくれた」.
- 相談の中身 (CONSULT): 一人でやること (仕事・勉強・家事 など) と, ほかの人との仲・将来・趣味. 合うかは性格しだい (chat.consult_reply).
- スタンプ (STAMPS): よくある種類. 返事は manners.reply の stamp.
"""

# 謝る理由: (id, 画面の文言). 状況のことを先に, そのあとメッセージの種類・コマンド (決まった順)
SITUATIONS = [
    ("no_reply", "返事をしなかった"),
    ("too_often", "連絡しすぎた"),
    ("late_night", "夜中に連絡した"),
    ("stamp_spam", "スタンプばかり送った"),
    ("selfie_pester", "自撮りをしつこく頼んだ"),
    ("reply_manner", "返事のしかたがよくなかった"),
    ("greet_miss", "あいさつをしなかった"),
    ("appoint", "約束に遅れた・行けなかった"),
    ("drop_in", "約束なしに家に行った"),
    ("drift", "しばらく会っていない"),
    ("street", "外で会ったのに、急いでいると流した"),
    ("anniv_forgot", "誕生日・記念日を忘れていた"),
    ("home", "家が散らかっていた"),
    ("chores", "家事をためていた"),
    ("chores_scold", "家事のことで責めた"),
    ("borrow", "お金のこと（貸し借り）"),
    ("pay", "支払いのこと"),
    ("help", "手伝いのお礼のこと"),
    ("fight", "言い争いをした"),
    ("jealous", "ほかの人と仲よくしていた"),
]
# 理由の action → 項目 (メッセージの種類・コマンドの id は, そのまま msg: / cmd: の項目に)
ACTION_ITEM = {
    "_too_often": "too_often", "_chat_late_night": "late_night", "_chat_stamp_spam": "stamp_spam",
    "_chat_selfie_pester": "selfie_pester", "_chat_flirt_cold": "msg:flirt", "_chat_tease_hurt": "msg:tease",
    "_nudge": "msg:nudge", "_what_doing": "msg:what_doing", "_greet_miss": "greet_miss", "_offline": "no_reply",
    "_appoint": "appoint", "_drop_in": "drop_in", "_drift": "drift", "_street": "street", "_anniv_forgot": "anniv_forgot",
    "_home": "home", "_chores": "chores", "_chores_mine": "chores", "_chores_scold": "chores_scold",
    "_borrow": "borrow", "_money_concern": "borrow", "_pay": "pay", "_help": "help", "_fight": "fight", "_jealous": "jealous",
    "_react": "reply_manner",
}
# 「近い」(それもだけど……) とみなすまとまり. 画面には出さない
NEAR = [
    {"no_reply", "greet_miss", "reply_manner", "msg:nudge"},
    {"too_often", "late_night", "stamp_spam", "selfie_pester", "msg:what_doing", "msg:nudge", "msg:stamp"},
    {"msg:tease", "msg:flirt", "reply_manner"},
    {"appoint", "drop_in", "drift", "street"},
    {"home", "chores", "chores_scold"},
    {"borrow", "pay", "help"},
    {"fight", "jealous", "anniv_forgot"},
]
# 謝る理由に並べるメッセージの種類 (あいさつ・お礼など, 謝ることになりにくいものも混ぜる. 選ぶ手間のうち)
MSG_KINDS = ("greet_morning", "greet_night", "smalltalk", "ask_how", "consult", "tease", "flirt", "invite", "photo", "ask_selfie",
             "stamp", "may_call", "what_doing", "nudge", "topic", "otsukare", "you_ok")

# お礼の理由: manners.favor の what と「許してくれた」
FAVORS = [
    ("forgave", "許してくれた"),
    ("selfie", "自撮りを送ってくれた"),
    ("call", "電話に出てくれた"),
    ("consult", "相談にのってくれた"),
    ("told", "話してくれた"),
    ("invite", "会おうと言ってくれた"),
    ("appoint", "約束してくれた"),
    ("change", "約束を変えてくれた"),
    ("met", "会ってくれた"),
    ("treat", "おごってくれた"),
    ("lent", "お金を貸してくれた"),
    ("help", "手伝ってくれた"),
    ("tidy", "片付けてくれた"),
    ("care", "看病してくれた"),
    ("celebrate", "お祝いしてくれた"),
]

# 相談の中身: (id, 文言, 話の言い方 {topic})
CONSULT = [
    ("work", "仕事のこと", "仕事"),
    ("study", "勉強・資格のこと", "勉強"),
    ("house", "家事・暮らしのこと", "暮らし"),
    ("money", "お金のこと", "お金"),
    ("health", "体調のこと", "体調"),
    ("people", "ほかの人との仲のこと", "人間関係"),
    ("future", "将来・進路のこと", "将来"),
    ("hobby", "趣味のこと", "趣味"),
]
CONSULT_WORD = {k: w for k, _, w in CONSULT}

# スタンプ: (id, 印, 文言)
STAMPS = [
    ("like", "👍", "いいね"),
    ("thanks", "🙏", "ありがとう"),
    ("wow", "😮", "びっくり"),
    ("think", "🤔", "考え中"),
    ("lol", "😂", "笑"),
    ("ok", "👌", "OK"),
    ("sorry", "🙇", "ごめん"),
    ("heart", "❤", "ハート"),
    ("cheer", "💪", "がんばれ"),
    ("sleep", "💤", "おやすみ"),
]
STAMP = {k: (i, w) for k, i, w in STAMPS}


def apology_choices(app):
    """謝る理由の一覧 [{id, label}] (決まった順. 分類しない)."""
    from .chat import KINDS
    out = [{"id": k, "label": w} for k, w in SITUATIONS]
    out += [{"id": "msg:" + k, "label": "「%s」と送ったこと" % KINDS[k][0]} for k in MSG_KINDS if k in KINDS]
    out += [{"id": "cmd:" + a["id"], "label": "「%s」をしたこと" % a.get("name", a["id"])}
            for a in app.actions if a.get("category") != "system" and not a["id"].startswith("_")]
    return out


def thanks_choices():
    return [{"id": k, "label": w} for k, w in FAVORS]


def reason_item(r):
    """機嫌の理由 (あなたのせい) が, 謝る理由のどの項目にあたるか. 当てられなければ None (以前のセーブの, 印の無い理由)."""
    a = r.get("action") or ""
    if a in ACTION_ITEM:
        return ACTION_ITEM[a]
    if a.startswith("_ap_"):           # 相手からの働きかけ: 放っておいた / 返事のしかた
        return "no_reply" if any(w in (r.get("tell") or "") for w in ("返事がなかった", "放っておかれた", "構ってもらえなかった")) \
            else "reply_manner"
    if a.startswith("_chat_"):
        return "msg:" + a[6:]
    if a and not a.startswith("_"):    # コマンドが原因 (あなたの行動で機嫌が大きく動いた)
        return "cmd:" + a
    return None


def near(a, b, app=None):
    """2 つの項目が近いか (同じまとまり / 同じ分類のコマンド)."""
    if a == b:
        return True
    if any(a in g and b in g for g in NEAR):
        return True
    if app and a.startswith("cmd:") and b.startswith("cmd:"):
        try:
            return app.action(a[4:]).get("category") == app.action(b[4:]).get("category")
        except KeyError:
            return False
    return False


def valid_apology(app, pid):
    return any(x["id"] == pid for x in apology_choices(app))


def check_extra(app, kind, extra):
    """選んだ理由・中身を確かめて, トークに残す要約 (said) を付ける (メッセージ・電話で共通). 違えば ValueError."""
    from .chat import KINDS
    extra = dict(extra or {})
    rs = extra.get("reason")
    if kind == "apology" and rs:
        item = next((x for x in apology_choices(app) if x["id"] == rs), None)
        if not item:
            raise ValueError("謝る理由が違います")
        extra["said"] = "（謝った: %s）" % item["label"]
    elif kind == "thanks" and rs:
        if rs not in dict(FAVORS):
            raise ValueError("お礼の理由が違います")
        extra["said"] = "（お礼を言った: %s）" % dict(FAVORS)[rs]
    elif kind == "consult" and extra.get("consult"):
        if extra["consult"] not in CONSULT_WORD:
            raise ValueError("相談の中身が違います")
        extra["said"] = "（%sを相談した）" % dict((k, w) for k, w, _ in CONSULT)[extra["consult"]]
    elif kind == "stamp" and extra.get("stamp"):
        if extra["stamp"] not in STAMP:
            raise ValueError("スタンプの種類が違います")
        ic, w = STAMP[extra["stamp"]]
        extra["said"] = "（%s %sのスタンプを送った）" % (ic, w)
    extra.setdefault("said", KINDS[kind][2] if kind in KINDS else "")
    return extra
