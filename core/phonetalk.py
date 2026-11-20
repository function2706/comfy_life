"""電話の対話 (A23 段 1): 話している間, 何度も選んで返すことで電話が続く. 時計は実時間.

- 切れ目 (beat): 数分おき (ノリが高いほど短い間) に, 相手のひとことが来る (話を振る・聞いてくる・ひと段落・少し黙る・眠そう・
  何してるの？). あなたは返し方 (相づち・掘り下げる・自分の話・話を変える・そろそろ切る) から選ぶ. 合う・外すはノリに効き,
  ノリが下がりきる・相手が話していたい長さ (span) を過ぎる・相手の次の用事や寝る時刻 (lim) で, 相手から切り上げる.
  長く話して掘り下げるほど, 相手が今日あったこと・好き・苦手を口にして「知っていること」(known) に残る (好感度ではなく材料).
- 返事を待つのは「読む時間 + 数秒」. 過ぎると「もしもし？」, それでも返さないと相手から切る (黙った). 画面を閉じたら電話を置いたのと同じ.
  黙ったのは機嫌の理由 (謝れる心当たり) になる. 相手が自分の話をしている最中・あなたからかけたときほど重い.
  近い仲の夜更けは「寝ちゃった？」と受け取って軽いことも.
- 相手から切るときの謝り方は切る理由で分ける: 用事・時間 → 謝る (律儀さ・仲で揺らす) + 「またかけるね」(call_back. 段 2 の着信が使う) /
  眠い → 軽く / 機嫌・ノリ → 謝らない. 謝ったひとことはトークに残り, 「気にしないで」で返せる (core/react.py の sorry).
- 寝落ち: 近い仲で, 相手が眠い・寝る時刻になると, 返事が短くなり (sleepy) やがて寝息だけ (asleep). 切る / 小さくおやすみと言って切る /
  つないだまま を選べる. つないだままなら翌朝に反応 (call_doze).
- ながら電話: 手が空く一人のこと (家事・休む・歩き / 電車バスの移動) は通話中もできる (NAGARA). 生活音で「何してるの？」と聞かれる
  ことがあり, 返しの効き目が少し下がる (家事の出来も少し下がる: solo.result).
- 誰かといるときの通話 (A23 段 3): あなたのそばに人がいると (bonds.company), 電話の相手が声に気づいて「誰かいるの？」(who) と聞く.
  正直に言う / ごまかす. 通話が終わると, そばにいた人がひとこと (長かった・恋敵・ごまかされた・言ってくれた).
  相手の側の気配 (background): 相手のいまの場面から一緒にいる人を決めて st["with_log"] に残し (根拠が無ければ出さない), 後ろの話し声と
  「誰といるの？」の返し方になる. あとでメッセージの「誰といたの？」(manners) で聞いても, 同じ記録から答える. 電車・職場は手短に (hush).
  割り込みの着信 (core/ring.py の catch) で待たせると, いまの相手が「誰から？」と聞くことがある.
記録は presence.rec()["call"] (docs/REMAINING の A23 段 1 か CHANGES 1.7.0beta にデータの形).
"""
import math
import random
import time
import uuid
from datetime import datetime, timedelta

from . import msgreply
from . import nori as nori_mod
from . import circle as circle_mod

# 返し方: (id, 文言, 印)
RETURNS = [("aizuchi", "相づちを打つ", "🙂"), ("dig", "掘り下げる", "👂"), ("mine", "自分の話をする", "💬"),
           ("change", "話を変える", "🔀"), ("bye", "そろそろ切る", "👋")]
ASLEEP_RETURNS = [("hang", "そっと切る", "📵"), ("night", "小さく「おやすみ」と言って切る", "🌙"), ("keep", "つないだままにする", "📞")]
RETURN_LABEL = dict((k, l) for k, l, _ in RETURNS + ASLEEP_RETURNS)
SAID = {"aizuchi": "相づちを打った", "dig": "掘り下げて聞いた", "mine": "自分の話をした", "change": "話を変えた", "bye": "そろそろ切ろうと言った"}
CAT = {"aizuchi": "cheerful", "dig": "expand", "mine": "cheerful", "change": "curt", "bye": "curt"}     # 性格の好み (msgreply.TASTE) の読み替え
BASE = {"aizuchi": 4, "dig": 5, "mine": 4, "change": 0, "bye": 0}
# 切れ目の種類 × 返し方の合い方 (react.FIT と同じ目盛り)
FIT = {
    "reply": {"aizuchi": 6, "dig": 8, "mine": 0, "change": -6, "bye": -8},
    "topic": {"aizuchi": 5, "dig": 10, "mine": -8, "change": -12, "bye": -10},
    "ask": {"mine": 12, "aizuchi": -6, "dig": -6, "change": -6, "bye": -8},
    "lull": {"change": 8, "mine": 6, "dig": 2, "aizuchi": -2, "bye": 0},
    "quiet": {"change": 8, "mine": 8, "dig": 2, "aizuchi": -10, "bye": -2},
    "what": {"mine": 12, "aizuchi": -8, "dig": -10, "change": -4, "bye": -4},
    "sleepy": {"bye": 10, "aizuchi": 4, "dig": -10, "mine": -8, "change": -8},
}
NORI = {"good": 10, "neutral": -2, "bad": -15}
EFFECT = {"good": {"boredom": -3, "loneliness": -3, "mood": 1}, "neutral": {"boredom": -1, "loneliness": -1}, "bad": {"mood": -2}}
WAIT_MIN, WAIT_MAX = 5.0, 25.0          # 返事を待つ秒 (読む時間込み)
HELLO_WAIT = (6.0, 10.0)                # 「もしもし？」のあと待つ秒
GAP = (60.0, 210.0)                     # 切れ目の間 (秒. ノリが高いほど短い)
ASLEEP_KEEP = 30 * 60                   # 寝息のまま, これだけ何も選ばなければ「つないだまま」にしたことに
LOG_MAX = 40
NAGARA = ("chores", "rest", "out")      # 通話中もできる一人のこと (外出は歩き・電車・バスのとき. 運転・自転車はできない)
NAGARA_HOW = ("walk", "transit", "taxi")
NAGARA_LABEL = {"chores": "家事", "rest": "ひと休み", "out": "移動"}
# 誰かといるときの通話 (A23 段 3)
WHO_RETURNS = [("honest", "正直に言う", "🙋"), ("dodge", "ごまかす", "🙊")]
WHO_ASK = ("who_ask", "誰といるの？と聞く", "🕵")
NEAR_P = {"home": 0.55, "guest": 0.55, "meet": 0.4, "visit": 0.45}     # そばの人の声に, 電話の相手が気づく割合のもと (一緒にいる形)
BG_P = {"coworker": 0.7, "friend_uni": 0.6, "friend_out": 0.3}           # 相手の場面から, 一緒にいる人がいる割合
WHO_LABEL = {"coworker": "職場の人", "friend": "友達", "family": "家族"}
HUSH_SPAN = {"train": 0.5, "work": 0.6}                                    # 電車の中・職場: 話していたい長さを縮める
WORK_ACTS = ("work", "parttime")
WITH_KEEP = 3 * 86400                                                      # with_log を残す長さ
ASK_SPAN = 12 * 3600                                                       # 「誰といるの / 誰といたの」の聞きすぎを数える長さ
NEAR_LONG = 10                                                             # そばの人を放っておいたと感じる通話の分

# 共通のセリフ (性格プリセットの phone.<場面> があればそちら. 「電話する」コマンドの反応 call.<キー> とは別). 📞 は付けない (通話画面とトークで付ける)
LINES = {
    "phone.topic_news": "そういえば今日、{news}んです。",
    "phone.topic_plain": "今日は、特に何もない一日でした。……こういう日もいいですよね。",
    "phone.ask": ["{call}は、今日どうでした？", "{call}のほうは、最近どうですか？"],
    "phone.lull": ["……ふふ。こうして話してると、なんだか落ち着きます。", "……なんだか、話が尽きないですね。"],
    "phone.sleepy": "ん……ごめんなさい、ちょっと眠くなってきて……。",
    "phone.what": "……ん？ 何か音がしますけど、いま何してるんですか？",
    "phone.hello": "……もしもし？ 聞こえてます？",
    "phone.hello_asleep": "……{call}？ 寝ちゃいました？",
    "phone.silent_cut": "……もういいです。切りますね。",
    "phone.silent_awkward": "あ、あの……電波が悪いみたいなので、いったん切りますね。",
    "phone.silent_sleep": "……おやすみなさい。",
    "phone.end_limit": "あ、ごめんなさい、そろそろ行かないと。またかけますね。",
    "phone.end_limit_plain": "じゃあ、そろそろ時間なので。また。",
    "phone.end_sleepy": "すみません、もう眠くて……。おやすみなさい。",
    "phone.end_cold": "……じゃあ、そろそろ切りますね。",
    "phone.end_enough": "今日はたくさん話せて楽しかったです。じゃあ、また。",
    "phone.bye_ok": "はい。じゃあ、また話しましょうね。",
    "phone.bye_early": "あ……はい。じゃあ、また。",
    "phone.react_good": "ふふ、なんか楽しいです。",
    "phone.react_neutral": "……うん、うん。",
    "phone.react_bad": "……うーん。",
    "phone.morning_glad": "📱『昨日、寝ちゃってましたよね。……つないだままにしてくれてたんですか？ ちょっとうれしかったです』",
    "phone.morning_shy": "📱『昨日、電話の途中で寝ちゃって……。寝息とか聞こえてませんでした？ 恥ずかしい……』",
    "phone.morning_awkward": "📱『昨日は電話の途中で寝ちゃって、すみませんでした』",
    # 相手からかかってくる電話 (A23 段 2. core/ring.py): 出たときの最初のひとこと (理由ごと)
    "phone.ring_bored": "もしもし。……暇だったので、かけちゃいました。いま大丈夫ですか？",
    "phone.ring_tired": "もしもし……。今日ちょっと疲れちゃって。少しだけ、声が聞きたくて。",
    "phone.ring_happy": "もしもし、{call}？ ちょっと聞いてほしいことがあって！",
    "phone.ring_lonely": "もしもし。……なんとなく、{call}と話したくなって。",
    "phone.ring_unsure": "もしもし。……最近、忙しいですか？ ちょっと気になって。",
    "phone.ring_changed": "もしもし、{call}？ 何かありました？ いつもと少し違う気がして。",
    "phone.ring_back": "もしもし。さっきは途中で切っちゃって、すみません。いま大丈夫ですか？",
    "phone.ring_asked": "もしもし。いいって言ってくれて、ありがとうございます。",
    "phone.ring_req": "もしもし、{call}？ ちょっと、お願いがあって……。",
    "phone.ring_ask": "📱『{call}、いま電話してもいいですか？』",
    "phone.ring_ask_no": "📱『わかりました。また今度』",
    "phone.ring_missed_msg": "📱『さっき電話したんですけど……また時間のあるときに』",
    "phone.ring_declined_msg": "📱『……忙しかったですか？ ごめんなさい、急にかけて』",
    "phone.req_yes": "ほんとですか？ ありがとうございます、助かります。",
    "phone.req_later": "あ、はい。じゃあ、わかったら教えてください。",
    "phone.req_no": "……そうですか。ううん、急に言ったのはこっちなので。",
    # 誰かといるときの通話 (A23 段 3)
    "phone.who": "……あれ、そばに誰かいるんですか？",
    "phone.catch_who": "……さっきの電話、誰からだったんですか？",
    "phone.who_ok": "あ、そうなんですね。",
    "phone.who_jealous": "……{other}さん、ですか。……ふうん。",
    "phone.who_lie_ok": "そうですか。気のせいだったかな。",
    "phone.who_lie_seen": "……そうですか。まあ、いいですけど。",
    "phone.hush_train": "（小声で）ごめんなさい、いま電車の中で……少しだけなら。",
    "phone.hush_work": "ごめんなさい、いま職場なので、手短にでもいいですか？",
    "phone.whoask_tell": "いまですか？ {who}と一緒なんです。",
    "phone.whoask_vague": "え？ ……ちょっと、知り合いと。",
    "phone.whoask_much": "……なんでそんなに気にするんですか？",
    "phone.near_ok": "電話、もういいんですか？",
    "phone.near_long": "……長い電話でしたね。",
    "phone.near_jealous": "……いまの、{other}さんですよね。",
    "phone.near_hid": "……さっき、一人だって言ってましたよね。",
    "phone.near_told": "……ちゃんと、一緒にいるって言ってくれたんですね。",
}
SCENE_LABEL = {
    "phone.topic_news": "電話 / 話を振る: 今日あったこと ({news} に出来事. 「〜た」で終わる)",
    "phone.topic_plain": "電話 / 話を振る: 特に何もなかった",
    "phone.ask": "電話 / あなたのことを聞いてくる",
    "phone.lull": "電話 / 話がひと段落した",
    "phone.sleepy": "電話 / 眠くなってきた (寝落ちしそう)",
    "phone.what": "電話 / 生活音に気づいて「何してるの？」(ながら電話)",
    "phone.hello": "電話 / 返事が無い: もしもし？",
    "phone.hello_asleep": "電話 / 返事が無い: 夜更けで, 寝落ちしたと思う",
    "phone.silent_cut": "電話 / 返事が無いので切る (近い仲. 不満)",
    "phone.silent_awkward": "電話 / 返事が無いので切る (浅い仲. 気まずそうに)",
    "phone.silent_sleep": "電話 / 返事が無いので切る (寝落ちしたと思って, そっと)",
    "phone.end_limit": "電話 / 用事・時間で切り上げる (謝って, またかけると言う)",
    "phone.end_limit_plain": "電話 / 用事・時間で切り上げる (謝らない)",
    "phone.end_sleepy": "電話 / 眠くて切り上げる",
    "phone.end_cold": "電話 / 乗らなくて切り上げる (謝らない)",
    "phone.end_enough": "電話 / 十分話して, 満足して切り上げる",
    "phone.bye_ok": "電話 / あなたが「そろそろ」と言った (応じる)",
    "phone.bye_early": "電話 / あなたが「そろそろ」と言った (まだ話したかった)",
    "phone.react_good": "電話 / あなたの返しがよく効いた",
    "phone.react_neutral": "電話 / あなたの返しがふつう",
    "phone.react_bad": "電話 / あなたの返しがよくなかった",
    "phone.morning_glad": "電話の翌朝 / 寝落ちをつないだままにしてくれた (うれしい. 📱 で包む)",
    "phone.morning_shy": "電話の翌朝 / 寝落ちをつないだままにしてくれた (照れる. 📱 で包む)",
    "phone.morning_awkward": "電話の翌朝 / 寝落ちしたことを気まずく謝る (📱 で包む)",
    "phone.ring_bored": "かかってきた電話 / 出たときの最初のひとこと: 暇だった",
    "phone.ring_tired": "かかってきた電話 / 出たときの最初のひとこと: 疲れている",
    "phone.ring_happy": "かかってきた電話 / 出たときの最初のひとこと: いいことがあった",
    "phone.ring_lonely": "かかってきた電話 / 出たときの最初のひとこと: 寂しい",
    "phone.ring_unsure": "かかってきた電話 / 出たときの最初のひとこと: あなたの気持ちが気になる (探り)",
    "phone.ring_changed": "かかってきた電話 / 出たときの最初のひとこと: あなたの返し方がいつもと違った",
    "phone.ring_back": "かかってきた電話 / 出たときの最初のひとこと: さっき用事で切ったのを, かけ直した",
    "phone.ring_asked": "かかってきた電話 / 出たときの最初のひとこと: 電話していい？に「いいよ」と返してもらった",
    "phone.ring_req": "かかってきた電話 / 出たときの最初のひとこと: 頼みごとがある (このあと頼みごとを言う)",
    "phone.ring_ask": "電話の前に / 電話していい？と聞く (📱 で包む)",
    "phone.ring_ask_no": "電話の前に / いまはちょっと と返された (📱 で包む)",
    "phone.ring_missed_msg": "かけた電話に出てもらえなかったあとのメッセージ (📱 で包む)",
    "phone.ring_declined_msg": "かけた電話を切られた (拒否) あとのメッセージ (📱 で包む)",
    "phone.req_yes": "電話での頼みごと / 受けてもらえた",
    "phone.req_later": "電話での頼みごと / あとで返事すると言われた",
    "phone.req_no": "電話での頼みごと / 断られた",
    "phone.who": "誰かといるときの電話 / 相手が, あなたのそばの人の声に気づいた: 誰かいるの？",
    "phone.catch_who": "誰かといるときの電話 / 割り込みの着信で待たされたあと: 誰からだったの？",
    "phone.who_ok": "誰かといるときの電話 / 正直に言われた (気にしない)",
    "phone.who_jealous": "誰かといるときの電話 / 正直に言われた, 相手がほかに親しい人だった ({other} に名前. やきもち)",
    "phone.who_lie_ok": "誰かといるときの電話 / ごまかされたが, 気づかなかった",
    "phone.who_lie_seen": "誰かといるときの電話 / ごまかされたのに気づいた (問い詰めない)",
    "phone.hush_train": "電話 / 相手が電車の中にいる (小声で, 手短に)",
    "phone.hush_work": "電話 / 相手が職場にいる (手短に)",
    "phone.whoask_tell": "電話 / 誰といるの？と聞かれて, 正直に答える ({who} に 職場の人・友達・名前)",
    "phone.whoask_vague": "電話 / 誰といるの？と聞かれて, はぐらかす",
    "phone.whoask_much": "電話 / 誰といるの？を聞かれすぎた (束縛っぽい)",
    "phone.near_ok": "あなたの電話のあと, そばにいた人のひとこと / ふつう",
    "phone.near_long": "あなたの電話のあと, そばにいた人のひとこと / 長くて放っておかれた",
    "phone.near_jealous": "あなたの電話のあと, そばにいた人のひとこと / 電話の相手がほかに親しい人だった ({other} に名前)",
    "phone.near_hid": "あなたの電話のあと, そばにいた人のひとこと / 電話の相手に, 自分のことをごまかされた",
    "phone.near_told": "あなたの電話のあと, そばにいた人のひとこと / 電話の相手に, 一緒にいると正直に言ってくれた",
}
NARRATION = {"quiet": "（……少しの間、黙っている）", "asleep": "（すう……すう……。寝息だけが聞こえる）",
             "night": "（小さく「おやすみ」と言って、電話を切った）", "hang": "（そっと電話を切った）",
             "keep": "（つないだまま、寝息を聞いていた）", "bg": "（後ろで誰かの話し声がする）",
             "catch": "（キャッチが入って、少し待ってもらった）"}
HOW = {"good": "楽しそうだった", "ok": "落ち着いて話してくれた", "flat": "少し気まずそうだった", "cold": "素っ気なかった"}


def rng():
    return random


class PhoneTalk:
    KEY = "call"                                 # presence.rec() の記録の置き場 (対面の会話 core/facetalk.py は "face")

    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 道具
    def rec(self):
        return self.app.presence.rec().get(self.KEY)

    def line(self, char, key, **kw):
        app = self.app
        t = app.persona_text(char, key) or LINES[key]
        if isinstance(t, list):
            t = random.choice(t)
        fp, _, call = app.pronouns(char)
        t = t.replace("{fp}", fp).replace("{call}", call).replace("{name}", char.get("name", ""))
        for k, v in kw.items():
            t = t.replace("{%s}" % k, v)
        return t

    def close_rel(self, char, st):
        return self.app.bonds.stage(char["id"]) in ("visit", "live") or st["params"].get("affection", 0) >= 70

    def _log(self, c, who, text, t):
        lg = c.setdefault("log", [])
        lg.append({"who": who, "text": text, "t": t})
        del lg[:-LOG_MAX]

    def wait_secs(self, char, st, text, kind, now):
        """返事を待つ秒: 読む時間 (8 字/秒) + 数秒. 待たない性格・相手が話に熱を入れているほど縮む."""
        tr = self.app.traits(char)
        lv = nori_mod.level(st, now) or 0.4
        w = len(text or "") / 8.0 + random.uniform(4.0, 9.0)
        w *= 1.0 - 0.25 * (float(tr.get("approach", 1.0)) - 1.0)        # 話したがりほど, 間を待てない
        if kind == "topic" and lv > 0.6:
            w *= 0.85
        if self.close_rel(char, st):
            w *= 1.15                                                     # 近い仲は, 黙っていても少し待つ
        return max(WAIT_MIN, min(WAIT_MAX, w))

    def span_min(self, char, st, lv):
        """相手が話していたい分 (これを過ぎると切り上げに入りやすい). 決め打ちにしない."""
        tr = self.app.traits(char)
        m = (8 + 25 * lv + 12 * (float(tr.get("approach", 1.0)) - 1.0) + 8 * self.app.attach.factor(char, st, "dependence")) \
            * (1.3 if self.close_rel(char, st) else 1.0) * random.uniform(0.6, 1.5)
        return max(4.0, m)

    # ------------------------------------------------------------------ つながる
    def begin(self, char, st, said, good, now, by="me", sys_t=None):
        """電話がつながって最初の受け答え (said: 相手の返事の文) が済んだところから, 通話の記録を作る."""
        app = self.app
        lv0 = nori_mod.level(st, now)
        if lv0 is None:
            nori_mod.start(app, char, st, now, boost=8 if by == "her" else 0, why="電話がつながった")
        nori_mod.bump(app, st, now, 6 if good else -8, "電話の最初の受け答え", turn=False)
        lv = nori_mod.level(st, now) or 0.3
        lim, cut, mine_cut = self.limit(char, st, now)
        c = {"cid": char["id"], "name": char.get("name", ""), "t": now, "by": by, "sys_t": sys_t, "turns": 0, "score": 0.0,
             "span": round(self.span_min(char, st, lv), 1), "lim": lim, "cut": cut, "mine_cut": mine_cut,
             "doing": self.doing_now(now), "doze": 0, "log": []}
        text = (said or "").split(chr(10))[0].replace("📞", "").replace("📱", "").strip()
        if text.startswith("『") and text.endswith("』"):
            text = text[1:-1]
        self._new_beat(char, st, c, "reply", None, text or "……もしもし。", now)
        self._company(char, st, c, now)
        self._hush_bg(char, st, c, now)
        app.presence.rec()[self.KEY] = c
        app.presence.save()
        return c

    def limit(self, char, st, now):
        """(切り上げる時刻 or None, 理由, あなたの都合か). engine._call_limit を長めに見て使う."""
        mins, cut = self.app._call_limit(char, st, now, 180)
        if not cut:
            return None, None, False
        mine = cut in ("約束がある", "予定の時刻が近い", "あなたが疲れていた")
        return now + mins * 60, cut, mine

    def doing_now(self, now):
        """いましている「ながら」のこと (無ければ None)."""
        app = self.app
        pr = app.presence.rec()
        tv = pr.get("travel")
        if tv and now < tv.get("arr", 0):
            return "out" if tv.get("how") in NAGARA_HOW else "drive"
        sl = pr.get("solo") or {}
        if pr.get("mode") in ("busy", "out") and sl.get("kind") in NAGARA:
            return sl["kind"]
        return None

    def nagara_why(self, kind=None, how=None):
        """通話中に始められない一人のことなら, その理由. 始められるなら None."""
        c = self.rec()
        if not c:
            return None
        if kind in NAGARA and (kind != "out" or how in NAGARA_HOW or how is None):
            return None
        if kind == "out" and how not in NAGARA_HOW:
            return "%sと電話で話している途中です（運転・自転車は、電話を切ってから）" % c.get("name", "")
        return self.app.call_block()

    def start_why(self, now):
        """電話をかけられない (手が離せない) 理由: 研鑽・読書・映画・内職の途中 / 運転中. かけられるなら None."""
        d = self.doing_now(now)
        if d == "drive":
            return "運転中です（電話は、着いてから）"
        pr = self.app.presence.rec()
        sl = pr.get("solo") or {}
        if pr.get("mode") == "busy" and sl.get("kind") in ("practice", "read", "movie"):
            from .solo import KINDS
            return "%sの途中です（電話は、終えてから）" % KINDS[sl["kind"]]["doing"].replace("中", "")
        return None

    # ------------------------------------------------------------------ 切れ目
    def _new_beat(self, char, st, c, kind, key, text, t):
        app = self.app
        mine = kind in ("topic",)
        due = None if kind == "asleep" else t + self.wait_secs(char, st, text, kind, t)
        c["beat"] = {"id": uuid.uuid4().hex[:8], "kind": kind, "key": key, "text": text, "t": t, "due": due, "stage": 0, "mine": mine}
        c.pop("next", None)
        self._log(c, "her", text, t)
        app.trace.add("call", "電話の切れ目", char["id"], t, kind=kind, key=key, wait=round((due or t) - t, 1))

    def req_beat(self, char, st, c, r, t):
        """頼みごと (core/ring.py): 出たときのひとことのあとに切り出す. 受ける / あとで返事する / 断る から選ぶ (考える間は少し長め)."""
        c["req"] = {"aid": r["req"], "kind": r.get("req_kind")}
        self._new_beat(char, st, c, "req", None, r.get("req_text") or "……", t)
        c["beat"]["due"] += 10.0

    def _req_answer(self, char, st, c, kind, now):
        """電話での頼みごとに, その場で答える. 約束の記録はいまのもの (appoint.answer). 断る・保留は, 直接言うぶん少し響く."""
        app = self.app
        rq = c.pop("req", None) or {}
        aid = rq.get("aid")
        self._log(c, "me", "（%s）" % {"yes": "受けた", "later": "あとで返事すると言った", "no": "断った"}[kind], now)
        try:
            if kind == "later":
                app.appoint.post_offer(aid, now + 0.5)          # トークから, あとで答えられる
            else:
                app.appoint.answer(aid, kind == "yes", now)
        except (ValueError, KeyError):                          # もう答えた・取り下げた約束
            pass
        if kind != "yes":
            w = (1.5 if kind == "no" else 0.6) * random.uniform(0.7, 1.3) * (1.3 if rq.get("kind") == "care" else 1.0) \
                * max(0.5, float(app.traits(char).get("absence", 1.0)))
            app.apply_effects(st, {"mood": -round(w, 1)}, now)
        self._log(c, "her", self.line(char, "phone.req_" + kind), now + 0.5)
        app.trace.add("call", "電話での頼みごとに答えた", char["id"], now, kind=kind, req=rq.get("kind"), appoint=aid)
        nori_mod.bump(app, st, now, {"yes": 8, "later": -2, "no": -10}[kind], "電話での頼みごと: " + kind)
        c["turns"] = c.get("turns", 0) + 1
        c.pop("beat", None)
        c["next"] = now + self._gap(st, now)
        app.save_state(char["id"])
        app.presence.save()
        return {"call": self.view(now)}

    def _pick_beat(self, char, st, c, t):
        """次の切れ目の種類と文."""
        app = self.app
        p = st["params"]
        lv = nori_mod.level(st, t) or 0.3
        q = c.get("who_q")
        if q and c.get("turns", 0) >= q.get("after", 0):
            c.pop("who_q")
            key = "phone.catch_who" if q.get("src") == "catch" else "phone.who"
            c["who"] = {"about": q.get("about"), "src": q.get("src")}
            return "who", key, self.line(char, key)
        if c.get("doing") and not c.get("asked_doing") and random.random() < 0.3 * self._nosy(char):
            c["asked_doing"] = True
            return "what", "phone.what", self.line(char, "phone.what")
        w = {"topic": 1.0 + lv + 0.3 * c.get("deep", 0), "ask": 0.8 + 0.4 * (p.get("affection", 50) - 50) / 50.0,
             "lull": 0.4 + 0.02 * self._elapsed(c, t), "quiet": 0.5 * (1.2 - lv)}
        recent = c.get("recent") or []
        for k in w:                                       # 同じことを続けて言わない
            w[k] *= 0.25 ** recent[-2:].count(k)
        kind = random.choices(list(w), [max(0.05, v) for v in w.values()])[0]
        c["recent"] = (recent + [kind])[-3:]
        if kind == "topic":
            kind, key, text = self._topic(char, st, c, t)
            if key == "phone.topic_plain":
                if "phone.topic_plain" in (c.get("said") or []):         # 「特に何もない一日」は一度だけ
                    return "lull", "phone.lull", self.line(char, "phone.lull")
                c["said"] = (c.get("said") or []) + [key]
            return kind, key, text
        if kind == "quiet":
            return "quiet", None, NARRATION["quiet"]
        return kind, "phone." + kind, self.line(char, "phone." + kind)

    def _nosy(self, char):
        """生活音を気にする性格か (0.3〜1.5)."""
        return max(0.3, min(1.5, 0.8 + 0.4 * (float(self.app.traits(char).get("jealousy", 1.0)) - 1.0) * 2))

    def _topic(self, char, st, c, t):
        """相手が自分の話をする: 今日あったこと (話していない出来事) / 好き・苦手 (まだ知らないもの) / 特になし.
        口にしたことは「知っていること」に残る. 長く話して掘り下げるほど (deep), 中身のある話が出やすい."""
        app = self.app
        call = app.pronouns(char)[2]
        deep = c.get("deep", 0)
        ev = [r for r in st.get("reasons") or [] if r.get("kind") == "event" and not r.get("told") and t - r.get("t", 0) < 36 * 3600]
        if ev and random.random() < 0.45 + 0.15 * deep:
            r = max(ev, key=lambda x: x["t"])
            r["told"] = True
            app.bonds.remember(char, st, t)
            news = r["tell"].replace("{call}", call)
            return "topic", "phone.topic_news", self.line(char, "phone.topic_news", news=news)
        if random.random() < 0.25 + 0.2 * deep:
            from .topics import TAGS
            known = {(k.get("kind"), k.get("text")) for k in st.get("known") or []}
            cands = [(k, v) for k, v in app.topics.tastes(char, st).items()
                     if abs(v) >= 0.3 and k in TAGS and (("like" if v > 0 else "dislike"), TAGS[k]) not in known]
            if cands:
                k, v = random.choice(cands)
                kind = "like" if v > 0 else "dislike"
                app.bonds.learn(st, kind, TAGS[k], t)
                from .hima import REVEAL
                txt = (app.persona_text(char, "hima.reveal_" + kind) or REVEAL[kind]).replace("{genre}", TAGS[k]) \
                    .replace("{fp}", app.pronouns(char)[0])
                return "topic", "hima.reveal_" + kind, txt
        return "topic", "phone.topic_plain", self.line(char, "phone.topic_plain")

    def _elapsed(self, c, t):
        return (t - c["t"]) / 60.0

    def _gap(self, st, t):
        lv = nori_mod.level(st, t) or 0.3
        return (GAP[0] + (GAP[1] - GAP[0]) * (1 - lv)) * random.uniform(0.7, 1.3)

    def _late_guess(self, char, st, b):
        """返事が無いのを「寝ちゃった？」と受け取るか (近い仲の夜更け)."""
        return self.close_rel(char, st) and (nori_mod.hour_at(b["due"]) >= 23 or nori_mod.hour_at(b["due"]) < 4) \
            and random.random() < 0.6

    def _doze_ok(self, char, st):
        """眠くなったとき, 寝落ちに向かうか (近い仲だけ. 浅い仲は眠いと言って切る)."""
        return self.close_rel(char, st)

    def _sleepy(self, char, st, t):
        """寝落ちに向かうか: 眠気が高い / 寝る時刻を過ぎた (近い仲だけ. 浅い仲は眠いと言って切る)."""
        sc = self.app.scene_at(char, st, datetime.fromtimestamp(t))
        return st["params"].get("sleepiness", 0) >= 75 or bool(sc.get("asleep"))

    # ------------------------------------------------------------------ 進める (心拍・画面の問い合わせ)
    def tick(self, now=None):
        """通話を now まで進める (閉じていた間の分は, 時刻をさかのぼって). 終わったら終わりの結果を返す."""
        now = now or time.time()
        app = self.app
        c = self.rec()
        if not c:
            return None
        if "beat" not in c and "next" not in c:          # 以前の形 (決め打ちの until): その通話は終わったことに (遡及)
            app.presence.rec().pop(self.KEY, None)
            app.presence.save()
            return None
        cid = c["cid"]
        if cid not in app.chars:
            app.presence.rec().pop(self.KEY, None)
            app.presence.save()
            return None
        char, st = app.char(cid), app.state(cid)
        for _ in range(12):
            b = c.get("beat")
            if b:
                if b["kind"] == "asleep":
                    if now - b["t"] >= ASLEEP_KEEP:
                        return self._finish(char, st, c, b["t"] + ASLEEP_KEEP, "you", "keep")
                    return None
                if now < b["due"]:
                    return None
                if b["stage"] == 0:                       # もしもし？
                    late = self._late_guess(char, st, b)
                    key = "phone.hello_asleep" if late else "phone.hello"
                    text = self.line(char, key)
                    b.update(stage=1, t0=b["t"], t=b["due"], due=b["due"] + random.uniform(*HELLO_WAIT), asleep_guess=late,
                             hello=text)
                    self._log(c, "her", text, b["t"])
                    app.presence.save()
                    continue
                return self._finish(char, st, c, b["due"], "her", "silent")
            t = c.get("next", now)
            if now < t:
                return None
            c["doing"] = self.doing_now(now)              # ながら: いましていること (途中で家事を始めた・移動を終えた)
            sl = app.presence.rec().get("solo") or {}
            if c["doing"] == "chores" and sl.get("kind") == "chores":
                sl["phone"] = True                        # 家事の出来が少し下がる (solo.result)
            if c.get("lim") and t >= c["lim"]:
                return self._finish(char, st, c, c["lim"], "you" if c.get("mine_cut") else "her", "limit")
            if c.get("doze", 0) >= 1 or self._sleepy(char, st, t):
                if self._doze_ok(char, st):
                    c["doze"] = c.get("doze", 0) + 1
                    if c["doze"] >= 2:
                        self._new_beat(char, st, c, "asleep", None, NARRATION["asleep"], t)
                    else:
                        self._new_beat(char, st, c, "sleepy", "phone.sleepy", self.line(char, "phone.sleepy"), t)
                    app.presence.save()
                    continue
                return self._finish(char, st, c, t, "her", "sleepy")
            if self._elapsed(c, t) > c.get("span", 20) and random.random() < 0.35:
                return self._finish(char, st, c, t, "her", "enough")
            kind, key, text = self._pick_beat(char, st, c, t)
            if text in [x["text"] for x in (c.get("log") or [])[-6:] if x["who"] == "her"]:
                kind, key, text = "quiet", None, NARRATION["quiet"]          # さっきと同じことは言わない
            self._new_beat(char, st, c, kind, key, text, t)
            app.save_state(cid)
            app.presence.save()
        return None

    # ------------------------------------------------------------------ 返す
    def judge(self, char, st, c, kind, now):
        p = st["params"]
        b = c["beat"]
        taste = msgreply.TASTE.get(char.get("persona_id") or "", {})
        lv = nori_mod.level(st, now)
        score = BASE[kind] + 1.3 * FIT.get(b["kind"], FIT["lull"]).get(kind, 0) + 0.5 * taste.get(CAT[kind], 0) \
            + 0.25 * (p.get("mood", 50) - 50) + 0.2 * (p.get("affection", 45) - 45) + 8 * (self.app.life.skill_mult("talk") - 1.0) \
            + (12 * (lv - 0.5) if lv is not None else 0) + random.uniform(-12, 12)
        if b.get("stage"):
            score -= 6                                    # もしもし？と言わせてから返した
        if c.get("doing"):
            score -= 4                                    # ながら: 生活音で, 気もそぞろに聞こえる
        if c.get("last") == kind and c.get("rep", 0) >= 1:
            score -= 5 * c["rep"]                         # 同じ返しばかり (相づちばかり など)
        res = "good" if score >= 10 else "neutral" if score >= -8 else "bad"
        if res == "good" and random.random() < 0.1:
            res = "neutral"
        return res, score

    def reply(self, kind, now=None):
        """いまの切れ目に返す. 通話の様子 (view) を返す. 終わったら {"ended": …}."""
        now = now or time.time()
        app = self.app
        ended = self.tick(now)
        if ended:
            return {"ended": ended}
        c = self.rec()
        if not c or not c.get("beat"):
            raise ValueError("いまは返すところではありません（相手が話すのを待っています）" if c else "電話で話している途中ではありません")
        b = c["beat"]
        char, st = app.char(c["cid"]), app.state(c["cid"])
        app.presence.rec()["beat"] = app.presence.rec()["input"] = now      # 画面の前にいる
        if b["kind"] == "asleep":
            if kind not in ("hang", "night", "keep"):
                raise ValueError("寝息だけが聞こえる（切る・おやすみと言って切る・つないだまま から）")
            return {"ended": self._finish(char, st, c, now, "you", kind)}
        if b["kind"] == "req":
            if kind not in ("yes", "later", "no"):
                raise ValueError("頼みごとに答えてください（受ける・あとで返事する・断る）")
            return self._req_answer(char, st, c, kind, now)
        if b["kind"] == "who":
            if kind not in ("honest", "dodge"):
                raise ValueError("正直に言うか、ごまかすか を選んでください")
            return self._who_answer(char, st, c, kind, now)
        if kind == "who_ask":
            if not self._can_ask_bg(c):
                raise ValueError("いまは聞けません")
            return self._bg_ask(char, st, c, now)
        if kind not in BASE:
            raise ValueError("返し方を選んでください")
        self._log(c, "me", "（%s）" % SAID[kind], now)
        res, score = self.judge(char, st, c, kind, now)
        c["rep"] = c.get("rep", 0) + 1 if c.get("last") == kind else 0
        c["last"] = kind
        c["turns"] = c.get("turns", 0) + 1
        c["score"] = round(c.get("score", 0) + score, 1)
        c.setdefault("res", []).append(res)
        eff = dict(EFFECT[res])
        if c.get("doing"):
            eff = {k: v * 0.8 for k, v in eff.items()}
        app.apply_effects(st, eff, now)
        app.trace.add("call", "電話で返した", char["id"], now, beat=b["kind"], kind=kind, res=res, score=round(score, 1),
                      turns=c["turns"], doing=c.get("doing"))
        if kind == "bye":
            return {"ended": self._finish(char, st, c, now, "you", "bye", res=res)}
        if kind == "dig" and res == "good":
            c["deep"] = c.get("deep", 0) + 1
        closing = nori_mod.bump(app, st, now, NORI[res] - nori_mod.TIRE * 0.6 - 0.05 * self._elapsed(c, now), "電話の返し: " + res)
        if res != "neutral" or random.random() < 0.5:
            self._log(c, "her", self.line(char, "phone.react_" + res), now + 0.5)
        if closing is not None and closing < nori_mod.CLOSE_BELOW and c["turns"] >= nori_mod.CLOSE_TURNS:
            return {"ended": self._finish(char, st, c, now + 1, "her", "cold")}
        c.pop("beat", None)
        c["next"] = now + self._gap(st, now)
        app.save_state(char["id"])
        app.presence.save()
        return {"call": self.view(now)}

    # ------------------------------------------------------------------ 終わる
    def hangup(self, now=None):
        """あなたから切る (返さずに, いきなり)."""
        now = now or time.time()
        ended = self.tick(now)
        if ended:
            return ended
        c = self.rec()
        if not c:
            raise ValueError("電話で話している途中ではありません")
        app = self.app
        char, st = app.char(c["cid"]), app.state(c["cid"])
        b = c.get("beat") or {}
        if b.get("kind") == "asleep":
            return self._finish(char, st, c, now, "you", "hang")
        return self._finish(char, st, c, now, "you", "hangup")

    def switch(self, now):
        """割り込みの着信に出るため, いまの電話を切る (core/ring.py)."""
        c = self.rec()
        if not c:
            return None
        app = self.app
        return self._finish(app.char(c["cid"]), app.state(c["cid"]), c, now, "you", "switch")

    def _finish(self, char, st, c, t, who, why, res=None):
        """通話を終える: トークの要約・相手の最後のひとこと・機嫌・見立て・お礼の心当たり・寝落ちの翌朝・またかけるね."""
        app = self.app
        cid = char["id"]
        p = st["params"]
        mins = max(1, int(round((t - c["t"]) / 60.0)))
        rs = c.get("res") or []
        avg = c.get("score", 0) / max(1, len(rs))
        lv = nori_mod.level(st, t) or 0.3
        how = HOW["good" if avg >= 8 and lv >= 0.5 else "ok" if avg >= -2 else "flat" if lv >= 0.3 else "cold"]
        b = c.get("beat") or {}
        last, sorry, note = None, False, ""
        call = app.pronouns(char)[2]
        if why == "silent":                               # 黙ったまま: 相手から切る
            asleep = b.get("asleep_guess")
            key = "phone.silent_sleep" if asleep else "phone.silent_cut" if self.close_rel(char, st) else "phone.silent_awkward"
            last = self.line(char, key)
            self._silent(char, st, c, b, t, asleep)
            note = "途中で返事をしなくなり、%sから切れた" % char.get("name", "相手")
        elif why == "limit" and who == "her":
            pun = float(app.traits(char).get("punctual", 0.6))
            recent = [x for x in st.get("call_sorries") or [] if t - x < 7 * 86400]      # 毎回謝ると決まり文句になる
            sorry = random.random() < 0.35 + 0.4 * pun + (0.15 if self.close_rel(char, st) else 0) - 0.12 * len(recent)
            if sorry:
                st["call_sorries"] = (recent + [t])[-5:]
            last = self.line(char, "phone.end_limit" if sorry else "phone.end_limit_plain")
            if sorry and random.random() < 0.7:
                st["call_back"] = {"t": t, "why": c.get("cut")}           # またかけるね (段 2 の着信が使う)
            note = "%sので、%sから切り上げた" % (c.get("cut") or "用事がある", char.get("name", "相手"))
        elif why == "limit":
            note = "%sので、切り上げた" % (c.get("cut") or "用事がある")
        elif why == "sleepy":
            sorry = random.random() < 0.5
            last = self.line(char, "phone.end_sleepy")
            note = "%sが眠そうで、切り上げた" % char.get("name", "相手")
        elif why == "cold":
            last = self.line(char, "phone.end_cold")
            note = "話が続かず、%sから切り上げた" % char.get("name", "相手")
        elif why == "enough":
            last = self.line(char, "phone.end_enough")
            note = "十分話して、%sから切り上げた" % char.get("name", "相手")
        elif why == "bye":
            early = (c.get("by") == "her" or b.get("mine")) and (mins < 5 or c.get("turns", 0) < 3)
            last = self.line(char, "phone.bye_early" if early or res == "bad" else "phone.bye_ok")
            note = "あなたから切り上げた"
            if early:
                self._cut_early(char, st, c, t, soft=True)
        elif why == "hangup":
            note = "あなたから切った"
            if c.get("by") == "her" and (mins < 5 or c.get("turns", 0) < 3):
                self._cut_early(char, st, c, t)
            elif b.get("mine") and b.get("kind") != "sleepy":
                app.apply_effects(st, {"mood": -2}, t)    # 話している途中で切られた
        elif why in ("hang", "night", "keep"):
            note = {"hang": "%sが寝てしまい、そっと切った", "night": "%sが寝てしまい、小さくおやすみと言って切った",
                    "keep": "%sが寝てしまい、つないだままにした"}[why] % char.get("name", "相手")
            self._log(c, "me", NARRATION[why], t)
            self._doze_after(char, st, c, t, why)
        elif why == "switch":                             # 割り込みの着信に出るため, あなたから切った (core/ring.py)
            note = "ほかの電話に出るため、あなたから切った"
            w = random.uniform(0.7, 1.3) * (1.3 if b.get("mine") else 1.0) * (1 + 0.3 * max(0.0, app.attach.factor(char, st, "dependence")))
            d = round(min(8.0, 3.5 * w), 1)
            app.apply_effects(st, {"mood": -d}, t)
            app.life.add_reason(st, "player", "bad", "話の途中で、{call}がほかの電話に出た", t, told=False, delta=-d, action="_call_switch")
            app.regard.sign(char, st, "call_cut", t, k=0.8 * w)
        if last:
            self._log(c, "her", last, t)
        if c.get("req"):                                  # 頼みごとに答えないまま切れた: メッセージで届く (トークから答えられる)
            app.appoint.post_offer(c.pop("req").get("aid"), t + 30)
        # 長く付き合ってくれた / 付き合った
        good_call = why not in ("silent", "cold") and c.get("turns", 0) >= 3 and avg >= -2
        if good_call:
            if c.get("by") == "her":
                app.regard.sign(char, st, "call_long", t)            # 相手からかけて, 長く付き合ってもらえた
            else:
                app.manners.favor(st, "call", t)                      # 電話に付き合ってくれた (お礼の心当たり)
                if c.get("turns", 0) >= 6:
                    app.regard.sign(char, st, "call_long", t, k=0.6)
        if good_call and how == HOW["good"] and not st.get("msg_pending") and random.random() < 0.35:
            st["msg_pending"] = {"aid": "message", "t": t, "due": t + random.uniform(10, 60) * 60, "reply": True,
                                 "count": 1, "kind": "after_call", "meta": {}, "quick": False}
        # トーク: 要約と, 相手の最後のひとこと (謝ったなら「気にしないで」で返せる)
        d = app.chat.load(cid)
        summary = "📞 電話で話した（%d分ほど。%s。%s）" % (mins, how, note) if note else "📞 電話で話した（%d分ほど。%s）" % (mins, how)
        hit = False
        for it in d["items"]:
            if it.get("kind") == "call" and it.get("who") == "sys" and c.get("sys_t") is not None and it.get("t") == c["sys_t"]:
                it["text"] = summary
                hit = True
        app.chat.save(cid, d)
        if not hit:
            app.chat.add(cid, "sys", summary, kind="call", t=t)
        if last:
            app.chat.add(cid, "her", "📞『%s』" % last, kind="call_sorry" if sorry else "call_end", t=t + 0.001)
        near = []
        for oid in c.get("near") or []:                 # そばにいた人 (まだそばにいれば) のひとこと
            if oid in app.chars and oid in app.bonds.company() and oid != cid:
                near.append(self._near_react(oid, c, mins, t))
        app.presence.rec().pop(self.KEY, None)
        app.presence.save()
        app.trace.add("call", "電話が終わった", cid, t, who=who, why=why, mins=mins, turns=c.get("turns", 0), how=how,
                      sorry=sorry, avg=round(avg, 1), near=near)
        app.save_state(cid)
        out = {"mins": mins, "name": char.get("name", ""), "who": who, "why": why, "how": how, "last": last, "note": note,
               "turns": c.get("turns", 0), "cid": cid, "id": uuid.uuid4().hex[:8]}
        self._last = dict(out, at=time.time())
        return out

    _last = None

    def last_end(self):
        """直前に終わった通話 (画面が終わり方を知らせる. 20 秒のうちだけ)."""
        x = self._last
        return x if x and time.time() - x["at"] < 20 else None

    def _silent(self, char, st, c, b, t, asleep):
        """話の途中で黙った: 機嫌が下がり, 謝れる心当たりになる. 自分の話の最中・あなたからかけたときほど重い."""
        app = self.app
        w = 1.0
        if b.get("mine"):
            w *= 1.5
        if c.get("by") == "me":
            w *= 1.4                                       # そっちからかけてきたのに
        w *= max(0.5, float(app.traits(char).get("absence", 1.0))) * (1 + 0.3 * max(0.0, app.attach.factor(char, st, "dependence")))
        if asleep:
            w *= 0.3                                       # 寝落ちだと受け取った
        elif not self.close_rel(char, st):
            w *= 0.7                                       # 浅い仲は, 気まずいだけ
        w *= random.uniform(0.7, 1.3)
        d = round(min(12.0, 6.0 * w), 1)
        app.apply_effects(st, {"mood": -d, "affection": -0.3 * w}, t)
        if not asleep or w > 0.6:
            app.life.add_reason(st, "player", "bad", "電話の途中で{call}が黙ってしまった", t, told=False, delta=-d,
                                action="_call_silent")
        app.regard.sign(char, st, "call_silent", t, k=min(1.5, w))

    def _cut_early(self, char, st, c, t, soft=False):
        """相手からかけてきたのに, あなたが早く切った."""
        app = self.app
        w = (0.5 if soft else 1.0) * random.uniform(0.7, 1.3) * (1 + 0.4 * max(0.0, app.attach.factor(char, st, "dependence")))
        d = round(min(8.0, 4.0 * w), 1)
        app.apply_effects(st, {"mood": -d}, t)
        app.life.add_reason(st, "player", "bad", "せっかく電話したのに、{call}にすぐ切られた", t, told=False, delta=-d, action="_call_cut")
        app.regard.sign(char, st, "call_cut", t, k=w)

    def _doze_after(self, char, st, c, t, how):
        """寝落ちのあと: つないだままなら, 翌朝に反応 (うれしい・照れる・気まずい. 性格と仲で)."""
        if how != "keep":
            return
        p = st["params"]
        r = random.random() + 0.3 * (p.get("affection", 50) - 60) / 40.0
        mood = "glad" if r > 0.65 else "shy" if r > 0.3 else "awkward"
        if float(self.app.traits(char).get("modesty", 0)) > 3 and mood == "glad":
            mood = "shy"
        day = datetime.fromtimestamp(t)
        wake = (day + timedelta(days=1 if day.hour >= 5 else 0)).replace(hour=7, minute=0, second=0, microsecond=0)
        st["call_doze"] = {"t": t, "mood": mood, "due": wake.timestamp() + random.uniform(0, 90) * 60}

    def morning(self, char, st, now):
        """寝落ちした電話の翌朝のひとこと (届く時刻が来ていて, 相手が起きていれば)."""
        dz = st.get("call_doze")
        if not dz or now < dz.get("due", 0):
            return False
        t = dz["due"]
        if self.app.scene_at(char, st, datetime.fromtimestamp(min(now, t + 3 * 3600))).get("asleep") and now - t < 6 * 3600:
            return False
        st.pop("call_doze", None)
        self.app.chat.add(char["id"], "her", self.line(char, "phone.morning_" + dz["mood"]), kind="call_morning", t=min(now, t + 60))
        self.app.trace.add("call", "寝落ちした電話の翌朝", char["id"], now, mood=dz["mood"])
        return True

    # ------------------------------------------------------------------ 誰かといるときの通話 (A23 段 3)
    def _company(self, char, st, c, now):
        """あなたのそばにいる人 (電話の相手を除く). 声に気づかれたら, 1〜2 つめの切れ目で「誰かいるの？」."""
        app = self.app
        near = [o for o in app.bonds.company() if o != char["id"] and o in app.chars]
        if not near:
            return
        c["near"] = near
        mode = app.bonds.mode(near[0]) or "meet"
        p = NEAR_P.get(mode, 0.45) * self._nosy(char) * random.uniform(0.8, 1.2)
        c["noticed"] = random.random() < min(0.9, p)
        if c["noticed"]:
            c["who_q"] = {"about": near[0], "src": "near", "after": 0 if random.random() < 0.6 else 1}
        app.trace.add("call", "そばに人がいる通話", char["id"], now, near=near, mode=mode, p=round(p, 2), noticed=c["noticed"])

    def _who_answer(self, char, st, c, kind, now):
        """「誰かいるの？ / 誰から？」に, 正直に言う / ごまかす."""
        app = self.app
        w = c.get("who") or {}
        about, src = w.get("about"), w.get("src")
        other = (app.chars.get(about) or {}).get("name", "")
        self._log(c, "me", "（正直に言った）" if kind == "honest" else "（ごまかした）", now)
        w["ans"] = kind
        c["who"] = w
        close = self.close_rel(char, st)
        if kind == "honest":
            if about in app.chars and self._rival(char["id"], about, st, now):
                app.bonds.notice(char, st, about, now, again=about in (st.get("jealous") or {}), k=0.6)
                key, bump = "phone.who_jealous", -10
            else:
                key, bump = "phone.who_ok", 0
        else:
            mode = app.bonds.mode(about) if src == "near" and about in app.chars else None
            p = 0.3 + (0.2 if close else 0) + 0.25 * (self._nosy(char) - 0.8) + (0.1 if mode in ("home", "guest") else 0)
            seen = random.random() < max(0.1, min(0.9, p))
            w["seen"] = seen
            if seen:
                k = random.uniform(0.7, 1.3) * (1.3 if close else 1.0)
                d = round(4 * k, 1)
                app.apply_effects(st, {"mood": -d, "trust": -round(3 * k, 1)}, now)
                app.life.add_reason(st, "player", "bad", "電話で、{call}に何かをごまかされた", now, told=False, delta=-d,
                                    action="_call_dodge")
                app.regard.sign(char, st, "call_dodge", now, k=min(1.5, k))
                key, bump = "phone.who_lie_seen", -12
            else:
                key, bump = "phone.who_lie_ok", -1
        self._log(c, "her", self.line(char, key, other=other), now + 0.5)
        app.trace.add("call", "誰かいるの？に答えた", char["id"], now, kind=kind, src=src, about=about, key=key)
        nori_mod.bump(app, st, now, bump, "電話: 誰かいるの？ " + kind)
        c["turns"] = c.get("turns", 0) + 1
        c.pop("beat", None)
        c["next"] = now + self._gap(st, now)
        app.save_state(char["id"])
        app.presence.save()
        return {"call": self.view(now)}

    def _rival(self, cid, other, st, now):
        """cid から見て other が恋敵か (どちらもあなたと深い仲). 少し前に気づいたばかりなら重ねない."""
        app = self.app
        if not (app.bonds.deep(cid) and app.bonds.deep(other)):
            return False
        seen = (st.get("jealous") or {}).get(other)
        return seen is None or now - seen >= float(app.bonds.cfg()["renotice_days"]) * 86400

    def _near_react(self, oid, c, mins, t):
        """通話が終わったとき, そばにいた人のひとこと (その場の記録に). ごまかされた・恋敵・長かった・言ってくれた・ふつう."""
        app = self.app
        och, ost = app.char(oid), app.state(oid)
        partner = c["cid"]
        pname = (app.chars.get(partner) or {}).get("name", "")
        w = c.get("who") or {}
        mine = w.get("about") == oid and w.get("src") == "near"
        eff, key = {}, None
        if mine and w.get("ans") == "dodge":
            k = random.uniform(0.7, 1.3) * (1.4 if app.bonds.deep(oid) else 1.0) * max(0.5, float(app.traits(och).get("absence", 1.0)))
            eff = {"mood": -round(5 * k, 1), "trust": -round(3 * k, 1)}
            app.life.add_reason(ost, "player", "bad", "電話の相手に、{call}がそばにいる人のことをごまかしていた", t, told=False,
                                delta=eff["mood"], action="_call_hid")
            key = "phone.near_hid"
        elif self._rival(oid, partner, ost, t) and random.random() < 0.5 + 0.3 * (app.bonds.jealousy(och) - 1.0):
            app.bonds.notice(och, ost, partner, t, again=partner in (ost.get("jealous") or {}), k=0.6)
            key = "phone.near_jealous"
        elif mins >= NEAR_LONG:
            d = round(min(5.0, 0.25 * (mins - NEAR_LONG + 4)) * random.uniform(0.7, 1.3) * float(app.traits(och).get("absence", 1.0)), 1)
            eff = {"mood": -d, "loneliness": d}
            key = "phone.near_long"
        elif mine and w.get("ans") == "honest":
            eff, _ = app.bonds.realize(och, ost, {"trust": 1.0, "mood": 1.0}, "_call_told", t)
            key = "phone.near_told"
        elif random.random() < 0.5:
            key = "phone.near_ok"
        if eff:
            app.apply_effects(ost, eff, t)
        if not key:
            return None
        text = self.line(och, key, other=pname)
        dt = datetime.fromtimestamp(t)
        scene = app.scene_at(och, ost, dt)
        act = {"id": "_call_near", "name": "電話のあと", "icon": "📞", "pos": "looking at viewer", "neg": ""}
        pos, neg, parts = app.build_prompt(och, ost, dt, act)
        app._new_entry(oid, t, act, text, eff, scene, dt, pos, neg, parts)
        app.save_log(oid)
        app.trace.add("call", "そばにいた人の反応", oid, t, key=key, partner=partner, mins=mins, eff=eff)
        app.save_state(oid)
        return key

    def background(self, char, st, t, make=True):
        """相手の時刻 t の場面から, 一緒にいる人 (st["with_log"] の 1 件) を決める. 同じ場面のあいだは決め直さない.
        家にいる・寝ている (外にいない) ときは決めない (None). who: None (一人) / coworker / friend / char (cid に登録キャラ)."""
        app = self.app
        log = [x for x in st.get("with_log") or [] if t - x.get("t1", x["t0"]) < WITH_KEEP]
        st["with_log"] = log
        for x in reversed(log):
            if x["t0"] - 60 <= t <= x["t1"] + 60:
                return x
        if not make:
            return None
        dt = datetime.fromtimestamp(t)
        sc = app.scene_at(char, st, dt)
        if not sc.get("away") or sc.get("asleep"):
            return None
        act, loc = sc.get("activity"), sc.get("location") or ""
        who, ocid, hush, pid = None, None, None, None
        if sc.get("circle"):                             # 知り合いと会う予定の最中 (core/circle.py): その人と一緒
            pl = sc["circle"]
            pid = pl["pid"]
            who = circle_mod.WHO.get((app.circle.person(char, st, pid) or {}).get("kind"), "friend")
        elif act in ("commute", "moving"):
            hush = "train"
        else:
            if act in WORK_ACTS:
                hush = "work"
            for oid, och in app.chars.items():          # ほかの登録キャラが, 同じ時刻に同じ所にいる
                if oid == char["id"] or app.bonds.together(oid) or not loc or loc in ("移動中", "行き道", "街"):
                    continue
                osc = app.scene_at(och, app.state(oid), dt)
                if osc.get("away") and not osc.get("asleep") and osc.get("location") == loc \
                        and osc.get("activity") not in ("commute", "moving"):
                    who, ocid = "char", oid
                    break
            if not who:
                kind = "coworker" if act in WORK_ACTS or (act == "lunch" and loc != "大学") else \
                    "friend_uni" if act == "class" or loc == "大学" else "friend_out" if act == "errand" else None
                if kind and random.random() < BG_P[kind]:
                    who = "coworker" if kind == "coworker" else "friend"
        t1 = t
        while t1 - t < 4 * 3600:                         # 同じ場面が続くあいだ
            s2 = app.scene_at(char, st, datetime.fromtimestamp(t1 + 600))
            if s2.get("label") != sc.get("label") or s2.get("location") != loc:
                break
            t1 += 600
        if pid:
            t1 = max(t, min(sc["circle"]["t1"], t + 4 * 3600))
        x = {"t0": t, "t1": t1, "who": who, "cid": ocid, "label": sc.get("label", ""), "loc": loc, "hush": hush}
        if pid:
            x["pid"] = pid
        st["with_log"] = (log + [x])[-20:]
        app.trace.add("call", "相手の側の気配を決めた", char["id"], t, who=who, other=ocid, label=x["label"], hush=hush)
        return x

    def with_recent(self, char, st, t):
        """「誰といたの？」の答えのもと: 24 時間のうちの with_log の最後 (いま外にいれば, いまの場面で決める)."""
        x = self.background(char, st, t)
        if x:
            return x
        log = [x for x in st.get("with_log") or [] if x["t0"] <= t and t - x.get("t1", x["t0"]) < 86400]
        return log[-1] if log else None

    def who_label(self, x, char=None, st=None):
        """一緒にいる (いた) 人の言い方. 知り合いと会う予定 (pid. core/circle.py) なら名前入り (友達の佐藤さん など).
        以前の記録 (pid なし) は間柄だけ."""
        if not x or not x.get("who"):
            return ""
        if x["who"] == "char":
            return (self.app.chars.get(x.get("cid")) or {}).get("name", "知り合い")
        if x.get("pid") and char is not None and st is not None:
            return self.app.circle.who_label(char, st, x["pid"])
        return WHO_LABEL.get(x["who"], "知り合い")

    def told_who(self, char, st, x, via, now):
        """正直に言った: 知り合いと会う予定の人なら, あなたがその人を知ったことにする (core/circle.py)."""
        if x and x.get("pid"):
            self.app.circle.learn(char, st, x["pid"], via, now)

    def answer_mode(self, char, st, x):
        """「誰といるの / 誰といたの」に正直に言うか (honest / vague). 同じ場面について一度決めたら変えない.
        知り合いと会う予定なら, その人との間柄で (元恋人・言い寄る人・傾きの高い人ほどはぐらかす. circle.hide_shift)."""
        if x.get("ans"):
            return x["ans"]
        app = self.app
        p = 0.7 + (0.15 if self.close_rel(char, st) else 0) - 0.08 * max(0.0, float(app.traits(char).get("modesty", 0)) - 2)
        if x.get("who") == "char" and x.get("cid") in app.chars and app.bonds.deep(x["cid"]):
            p -= 0.25                                    # あなたとも親しい人と一緒: 言いにくい
        if x.get("pid"):
            p -= app.circle.hide_shift(char, st, x["pid"])
        x["ans"] = "honest" if random.random() < max(0.05, min(0.95, p)) else "vague"
        return x["ans"]

    def ask_count(self, st, now):
        """「誰といるの / 誰といたの」を聞いた回数 (12 時間の). 聞いたことを記録する."""
        asks = [x for x in st.get("whoask") or [] if now - x < ASK_SPAN]
        st["whoask"] = asks + [now]
        return len(asks)

    def _hush_bg(self, char, st, c, now):
        """相手の側: 電車・職場なら手短に (小声で). 一緒にいる人がいれば, 後ろの話し声 (誰といるの？ と聞ける)."""
        x = self.background(char, st, now)
        if not x:
            return
        if x.get("hush"):
            c["hush"] = x["hush"]
            c["span"] = round(max(3.0, c["span"] * HUSH_SPAN[x["hush"]]), 1)
            self._log(c, "her", self.line(char, "phone.hush_" + x["hush"]), now + 0.2)
        if x.get("who"):
            c["bg"] = {"t0": x["t0"]}
            self._log(c, "her", NARRATION["bg"], now + 0.3)

    def _can_ask_bg(self, c):
        b = c.get("beat") or {}
        return bool(c.get("bg")) and not c.get("bg_asked") and b.get("kind") not in ("asleep", "sleepy", "req", "who")

    def _bg_ask(self, char, st, c, now):
        """「誰といるの？」: 正直に (誰と) / はぐらかす. 聞きすぎは嫌がられる (今何してる？ と同じ)."""
        app = self.app
        c["bg_asked"] = True
        self._log(c, "me", "（誰といるのか聞いた）", now)
        x = self.background(char, st, now, make=False) or {}
        n = self.ask_count(st, now)
        if n >= 2:
            app.life.add_reason(st, "player", "bad", "%sに何度も、誰といるのか聞かれた" % app.pronouns(char)[2], now, told=True,
                                delta=-2.0, action="_what_doing")
            app.apply_effects(st, {"mood": -3, "trust": -1, "affection": -1}, now)
            key, bump = "phone.whoask_much", -12
        else:
            mode = self.answer_mode(char, st, x) if x.get("who") else "honest"
            key, bump = ("phone.whoask_tell" if mode == "honest" else "phone.whoask_vague"), (0 if self.close_rel(char, st) else -3)
            if mode == "honest":
                self.told_who(char, st, x, "phone", now)
        self._log(c, "her", self.line(char, key, who=self.who_label(x, char, st)), now + 0.5)
        app.trace.add("call", "誰といるの？と聞いた", char["id"], now, key=key, who=x.get("who"), n=n)
        nori_mod.bump(app, st, now, bump, "電話: 誰といるの？")
        c["turns"] = c.get("turns", 0) + 1
        c.pop("beat", None)
        c["next"] = now + self._gap(st, now)
        app.save_state(char["id"])
        app.presence.save()
        return {"call": self.view(now)}

    def catch_wait(self, caller, now):
        """割り込みの着信で, いまの相手を少し待たせた (core/ring.py). 詮索しがちな人ほど, 次に「誰から？」."""
        c = self.rec()
        if not c:
            return
        app = self.app
        char, st = app.char(c["cid"]), app.state(c["cid"])
        self._log(c, "me", NARRATION["catch"], now)
        nori_mod.bump(app, st, now, -3, "電話: 待たされた")
        if not c.get("who_q") and random.random() < 0.5 * self._nosy(char):
            c["who_q"] = {"about": caller, "src": "catch", "after": 0}
        b = c.get("beat")
        if b and b.get("due"):
            b["due"] += 15.0                            # 待たせていた間は, 返事を待つ
        app.presence.save()

    # ------------------------------------------------------------------ 画面
    def view(self, now=None):
        now = now or time.time()
        c = self.rec()
        if not c or "beat" not in c and "next" not in c:
            return None
        b = c.get("beat")
        out = {"cid": c["cid"], "name": c.get("name", ""), "t": c["t"], "by": c.get("by", "me"), "mins": int((now - c["t"]) // 60),
               "log": c.get("log", [])[-12:], "doing": NAGARA_LABEL.get(c.get("doing")), "turns": c.get("turns", 0)}
        if b:
            out["beat"] = {"id": b["id"] + ("h" if b.get("stage") else ""), "kind": b["kind"], "text": b.get("hello") if b.get("stage") else b["text"],
                           "left": None if b.get("due") is None else max(0, int(math.ceil(b["due"] - now))),
                           "stage": b.get("stage", 0)}
            from .ring import REQ_RETURNS
            rs = ASLEEP_RETURNS if b["kind"] == "asleep" else REQ_RETURNS if b["kind"] == "req" else WHO_RETURNS if b["kind"] == "who"                 else RETURNS + ([WHO_ASK] if self._can_ask_bg(c) else [])
            out["returns"] = [{"id": k, "label": l, "icon": i} for k, l, i in rs]
        else:
            out["talking"] = True                          # 話している (次に相手が話すまで)
        return out
