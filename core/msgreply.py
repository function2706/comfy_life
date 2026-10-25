"""向こうから来たメッセージ (離れている相手からの働きかけ) への返事を, 選択肢から選ぶ.

- 選択肢は, メッセージの内容に合ったものを 3〜4 つ (明るく乗る / 話を広げる / 心配する / からかう / 素っ気なく).
- どれが良く・悪く効くかは, 性格の好み (TASTE)・メッセージとの合い方 (FIT)・その時の機嫌・仲 (好感度)・揺らぎで決まる
  (good / neutral / bad). 返事をすれば必ず良くなる, ではない (公理). からかいは仲が深いほど通じ, 素っ気ない返事は寂しいときほど刺さる.
- 相手は選んだ返事に返す (性格プリセットの msgr.<種類>.<結果> があればそちら). ときどき, もう一言 (msgr.more.<結果>).
- 返事をしないまま時間が過ぎたとき (presence._expire): 性格 (traits.absence)・既読のまま放っておいたか・急ぎの内容か (approach の urgency)
  ・寂しさで重さが変わる. 気にしない性格もいる.
"""
import random

KINDS = {"cheerful": "明るく乗る", "expand": "話を広げる", "worry": "心配する", "tease": "からかう", "curt": "素っ気なく"}
# メッセージごとの選択肢と, あなたの返事 (トークに残る要約)
OPTIONS = {
    "msg_chat": [("cheerful", "「話そう話そう！」と返す"), ("expand", "「いま何してたの？」と聞き返す"),
                 ("tease", "「暇なの？」とからかう"), ("curt", "「ちょっと忙しい」とだけ返す")],
    "msg_miss": [("cheerful", "「会いたいね」と返す"), ("worry", "「何かあった？ 大丈夫？」と返す"),
                 ("tease", "「寂しがり屋だなぁ」とからかう"), ("curt", "「そっか」とだけ返す")],
    "msg_today": [("expand", "「それで？ もっと聞かせて」と返す"), ("cheerful", "「よかったね！」と返す"),
                  ("tease", "「長いよ（笑）」とからかう"), ("curt", "「へえ」とだけ返す")],
}
DEFAULT_OPTIONS = [("cheerful", "明るく返す"), ("expand", "話を広げる"), ("tease", "からかう"), ("curt", "素っ気なく返す")]
KIND_BASE = {"cheerful": 8, "expand": 8, "worry": 4, "tease": 0, "curt": -12}
FIT = {"msg_chat": {"cheerful": 4, "expand": 6, "tease": 2, "curt": -4},
       "msg_miss": {"worry": 8, "cheerful": 6, "tease": -6, "curt": -10, "expand": -2},
       "msg_today": {"expand": 10, "cheerful": 5, "curt": -8, "worry": -4}}
# 性格ごとの好み (控えめに. 決め打ちにしない)
TASTE = {
    "teinei": {"cheerful": 4, "worry": 4, "tease": -4}, "osananajimi": {"tease": 8, "curt": 2},
    "aneki": {"expand": 4, "worry": -2}, "kedakai": {"curt": -10, "tease": -6, "cheerful": 2},
    "sadist": {"tease": 6, "curt": -6, "worry": -4}, "itazura": {"tease": 10}, "mukuchi": {"curt": 10, "cheerful": -2},
    "jimuteki": {"curt": 8, "expand": 4}, "rikejo": {"expand": 10}, "otokomae": {"curt": 4, "worry": -4},
    "fushigi": {"expand": 6, "tease": -2}, "hitonatsukko": {"cheerful": 8, "curt": -14}, "hikutsu": {"worry": 8, "tease": -10, "curt": -12},
    "byoujaku": {"worry": 10, "tease": -6}, "tenshin": {"cheerful": 6, "expand": 6}, "tsundere": {"tease": 6, "worry": 2, "cheerful": -2},
    "uchiki": {"worry": 6, "tease": -10, "cheerful": 2}, "amaenbo": {"cheerful": 6, "worry": 8, "curt": -16},
    "genki": {"cheerful": 10, "curt": -8}, "ottori": {"worry": 4, "expand": 4}, "boyish": {"tease": 6, "curt": 2},
    "cool": {"curt": 8, "cheerful": -4}, "ojousama": {"cheerful": 4, "tease": -8, "curt": -8},
}
OUTCOMES = ("good", "neutral", "bad")
MORE_RATE = {"good": 0.55, "neutral": 0.3, "bad": 0.45}       # もう一言返ってくる割合
# 共通のセリフ (性格プリセットに無ければ). 鍵は msgr.<種類>.<結果> と msgr.more.<結果>
LINES = {
    "msgr.cheerful.good": "📱『ふふ、そう言ってもらえるとうれしいです！』",
    "msgr.cheerful.neutral": "📱『あ、はい。……そうですね』",
    "msgr.cheerful.bad": "📱『……なんか、軽いですね』",
    "msgr.expand.good": "📱『聞いてくれるんですか？ えっとですね……』",
    "msgr.expand.neutral": "📱『うーん、大したことじゃないんですけど』",
    "msgr.expand.bad": "📱『……別に、そこまで聞かなくても』",
    "msgr.worry.good": "📱『……ありがとうございます。そう言ってもらえるだけで、ほっとします』",
    "msgr.worry.neutral": "📱『大丈夫ですよ。心配しすぎです』",
    "msgr.worry.bad": "📱『……そういうのじゃないです。大げさです』",
    "msgr.tease.good": "📱『もう、からかわないでくださいよ〜。……ふふ』",
    "msgr.tease.neutral": "📱『……はいはい』",
    "msgr.tease.bad": "📱『……そういう言い方、ちょっと傷つきます』",
    "msgr.curt.good": "📱『ふふ、忙しいんですね。またあとで』",
    "msgr.curt.neutral": "📱『……そうですか』",
    "msgr.curt.bad": "📱『……なんか、冷たくないですか』",
    "msgr.more.good": "📱『あ、そうだ。今度また、ゆっくり話しましょうね』",
    "msgr.more.neutral": "📱『（スタンプが届いた）』",
    "msgr.more.bad": "📱『……もういいです』",
}
SCENE_LABEL = {"msgr.%s.%s" % (k, o): "メッセージへの返事「%s」に %s" % (KINDS[k], {"good": "よく効いた", "neutral": "ふつう",
                                                                                     "bad": "よくなかった"}[o])
               for k in KINDS for o in OUTCOMES}
SCENE_LABEL.update({"msgr.more.good": "返事のあとのもう一言 (よく効いた)", "msgr.more.neutral": "返事のあとのもう一言 (ふつう)",
                    "msgr.more.bad": "返事のあとのもう一言 (よくなかった)"})
EFFECT = {"neutral": {"loneliness": -3}, "bad": {"mood": -4, "affection": -1, "trust": -1}}
BAD_TELL = {"cheerful": "{call}の返事が軽かった", "expand": "{call}にしつこく聞かれた", "worry": "{call}に大げさに心配された",
            "tease": "{call}にからかわれた", "curt": "{call}の返事が素っ気なかった"}


def options(aid):
    return [{"id": k, "label": label} for k, label in OPTIONS.get(aid, DEFAULT_OPTIONS)]


def label(aid, kind):
    return dict(OPTIONS.get(aid, DEFAULT_OPTIONS)).get(kind, KINDS.get(kind, kind))


def said(aid, kind):
    """トークに残す, あなたの返事の要約 (過去形)."""
    t = label(aid, kind)
    for a, b in (("返す", "返した"), ("からかう", "からかった"), ("聞き返す", "聞き返した")):
        if t.endswith(a):
            return t[:-len(a)] + b
    return t


def judge(char, st, aid, kind, skill_mult=1.0, rng=random):
    """返事がどう受け取られるか: good / neutral / bad (揺らぎあり)."""
    p = st["params"]
    taste = TASTE.get(char.get("persona_id") or "", {})
    score = KIND_BASE[kind] + FIT.get(aid, {}).get(kind, 0) + taste.get(kind, 0) \
        + 0.25 * (p.get("mood", 50) - 50) + 0.3 * (p.get("affection", 45) - 45) + 8 * (skill_mult - 1.0) \
        + rng.uniform(-15, 15)
    if kind == "tease":                    # からかいは仲が深いほど通じる
        score += 0.4 * (p.get("affection", 45) - 60)
    if kind == "curt":                     # 素っ気ない返事は, 寂しいときほど刺さる
        score -= 0.2 * max(0.0, p.get("loneliness", 30) - 40)
    res = "good" if score >= 10 else "neutral" if score >= -8 else "bad"
    if res == "good" and rng.random() < 0.1:   # 合う返事でも, 今日はそれほど響かないこともある (確定させない)
        res = "neutral"
    return res
