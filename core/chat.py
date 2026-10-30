"""メッセージアプリ (離れている相手とのトーク).

- トークは相手ごと (data/worlds/<id>/chats/<cid>.json): {"seen_t": あなたが読んだところ, "items": [{t, who, kind, text, read_t?}]}
  who: me (あなたの発言. 要約「（挨拶をした）」) / her (相手の本文) / sys (電話の履歴・約束など)
- 送るメッセージの種類 (KINDS). 返信は既存の時間差の仕組み (msg_pending) に乗る: 相手が寝ている・手が離せないなら落ち着いてから,
  機嫌や仲しだいで遅れる・来ない (既読だけ付く). 返信の中身は種類 × 状況 (性格・間柄・機嫌・機嫌の理由・時間帯・頻度) で変わる.
  現実的に: 浅い仲で甘えると引かれる, からかいは逆効果のことも, 理由を知らずに謝ると戸惑われる, 夜中は迷惑, 送りすぎると冷たくなる.
  謝罪・お礼・あいさつ・スタンプ・「今いい？」などの受け止め方は core/manners.py (許し方の幅・心当たり・習慣・続け方).
  「会おう」に応じてくれたら, 会おうという話になる (date_promise. 半日のうちに約束を持ちかけると受けてもらいやすい).
  日時と行き先を決めて会うのは約束 (core/appoint.py). 約束の誘いの返事も, この時間差で届く.
- 電話 (出た・出なかった)・折り返し・相手からのメッセージ (働きかけ・オフライン中に届いたもの) も同じトークに並べる.
"""
import random
import time
from datetime import datetime

from . import store

# id: (ボタン, 印, あなたの発言の要約)
KINDS = {
    "greet_morning": ("おはよう", "☀", "（おはようと送った）"),
    "greet_night": ("おやすみ", "🌙", "（おやすみと送った）"),
    "thanks": ("ありがとう", "🙏", "（お礼を言った）"),
    "apology": ("ごめんね", "🙇", "（謝った）"),
    "smalltalk": ("雑談", "💬", "（他愛ない話をした）"),
    "ask_how": ("最近どう？", "❓", "（近況を聞いた）"),
    "consult": ("相談する", "🤔", "（相談した）"),
    "tease": ("からかう", "😜", "（からかった）"),
    "flirt": ("甘える", "💕", "（甘えてみた）"),
    "invite": ("会おうよ", "📅", "（会おうと誘った）"),
    "photo": ("写真を送る", "📷", "（写真を送った）"),
    "ask_selfie": ("自撮り送って", "🤳", "（自撮りを送ってとお願いした）"),
    "stamp": ("スタンプ", "🐾", "（スタンプを送った）"),
    "may_call": ("今いい？", "☎", "（電話していいか聞いた）"),
    "otsukare": ("お疲れさま", "🍵", "（お疲れさまと送った）"),
    "you_ok": ("大丈夫？", "🩹", "（大丈夫？と気づかった）"),
    "what_doing": ("今何してる？", "👀", "（今何してるか聞いた）"),
    "nudge": ("返事まだ？", "⏳", "（返事を催促した）"),
}
# 共通の返信 (性格プリセットに無ければ). 鍵は chat.<場面>
LINES = {
    "chat.greet_morning": "📱『おはようございます、{call}。今日もがんばりましょうね』",
    "chat.greet_night": "📱『おやすみなさい、{call}。また明日』",
    "chat.thanks": "📱『どういたしまして。そう言ってもらえるとうれしいです』",
    "chat.apology": "📱『……うん、もういいですよ。ちゃんと言ってくれて、ありがとうございます』",
    "chat.apology_confused": "📱『え、何がですか？ ……何かあったんですか？』",
    "chat.smalltalk": "📱『ふふ、なんですかそれ。……でも、ちょっと元気出ました』",
    "chat.ask_how": "📱『最近ですか？ {news}』",
    # 「最近どう？」の {news} の中身 (一文のかけら. 性格ごとの言い方に差し替える). {tell} に出来事 (「友だちとケンカした」の形)
    "chat.ask_how_news": "{tell}んです。",
    "chat.ask_how_nothing": "特に変わりないですよ。",
    "chat.consult": "📱『そうだったんですね……。{fp}でよければ、いつでも聞きますよ』",
    "chat.tease": "📱『もう、からかわないでくださいよ〜』",
    "chat.tease_hurt": "📱『……そういうの、ちょっと傷つきます』",
    "chat.flirt": "📱『……もう。{fp}も、会いたいです』",
    "chat.flirt_cold": "📱『え……えっと、急にどうしたんですか……？』",
    "chat.invite_yes": "📱『いいですね！ 会いましょう』",
    "chat.invite_no": "📱『ごめんなさい、しばらくはちょっと……』",
    "chat.photo": "📱『わ、いい写真ですね！』",
    "chat.stamp": "📱『（スタンプが返ってきた）』",
    "chat.apology_half": "📱『……うん』",
    "chat.apology_deeds": "📱『謝るなら、態度で示してください』",
    "chat.apology_refuse": "📱『……今は、そういうのいいです』",
    "chat.apology_late": "📱『……今さらですか？ ……まあ、いいですけど』",
    "chat.apology_enough": "📱『もういいですって。何回も謝らないでください』",
    "chat.apology_irritated": "📱『……だから、もういいって言ってるじゃないですか』",
    "chat.too_often_again": "📱『……謝ったばかりなのに、またですか？』",
    "chat.thanks_what": "📱『え、何がですか？』",
    "chat.thanks_again": "📱『それ、もう聞きましたよ。何回言うんですか』",
    "chat.thanks_not_yet": "📱『……まだ、許したわけじゃないですけど』",
    "chat.thanks_unforgiven": "📱『……許してないですけど。お礼を言われても困ります』",
    "chat.greet_odd_morning": "📱『おはよう……って、もうそんな時間じゃないですよ？』",
    "chat.greet_odd_night": "📱『え、もう寝るんですか？ まだ明るいですよ？』",
    "chat.greet_again": "📱『さっきも言いましたよね？』",
    "chat.stamp_only": "📱『……スタンプだけですか？』",
    "chat.stamp_spam": "📱『スタンプ連打はやめてください……』",
    "chat.may_call_ok": "📱『はい、大丈夫ですよ』",
    "chat.may_call_later": "📱『ごめんなさい、今はちょっと……あとでいいですか？』",
    "chat.otsukare": "📱『ありがとうございます。ちょうど終わったところです』",
    "chat.otsukare_odd": "📱『？ ……何がですか？』",
    "chat.you_ok": "📱『……気にしてくれてたんですね。ありがとうございます、少し楽になりました』",
    "chat.you_ok_what": "📱『え、何がですか？ 別に何もないですけど』",
    "chat.what_doing": "📱『今ですか？ {doing}ですよ』",
    "chat.what_doing_much": "📱『……なんで、そんなにいちいち聞くんですか？』",
    "chat.nudge_ok": "📱『あ、ごめんなさい、今返します』",
    "chat.nudge_bad": "📱『……ちょっと待っててください。急かさないで』",
    "chat.nudge_huh": "📱『え？ 返しましたよね？』",
    "chat.selfie_yes": "📱『もう……しょうがないですね。はい、どうぞ』",
    "chat.selfie_no": "📱『え、自撮りですか？ ……今はちょっと』",
    "chat.selfie_pester": "📱『……さっきも言いましたよね？ しつこいです』",
    "chat.late_night": "📱『……こんな時間に、どうしたんですか？ もう寝ますね』",
    "chat.too_often": "📱『……ちょっと、連絡多くないですか？』",
    "chat.repaid": "📱『あ、確かに受け取りました。わざわざありがとうございます』",
    "chat.money_worry": "📱『……あの、{call}。お金のこと、大丈夫ですか？ 無理してないか、ちょっと心配で』",
    "chat.money_distrust": "📱『……{call}、お金のこと、ちゃんと考えてますか？ ……ちょっと気になってて』",
    "chat.appoint_yes": "📱『{when}、{place}ですね。楽しみにしてます！』",
    "chat.appoint_no": "📱『ごめんなさい、その日はちょっと……』",
    "chat.appoint_busy": "📱『その時間は予定があって……ごめんなさい』",
    "chat.appoint_invite": "📱『{call}、{when}、{place}に行きませんか？』",
    "chat.appoint_counter": "📱『その時間はちょっと……。{when}なら、{place}行けますけど、どうですか？』",
    "chat.appoint_cancel": "📱『ごめんなさい、ちょっと体調を崩しちゃって……今日の約束、また今度にしてもらえますか』",
    "chat.appoint_sorry": "📱『今日は本当にごめんなさい……行けなくて』",
    "chat.appoint_missed": "📱『……今日、どうしたんですか？ ずっと待ってたんですけど』",
    "chat.favor_ask_move": "📱『{call}、お願いがあって……{when}に引っ越しなんですけど、手伝ってもらえませんか？ その日しか無理で……』",
    "chat.favor_ask_offer": "📱『{call}、{what}をお願いできませんか？ {when}はどうでしょう』",
    "chat.favor_ask_when": "📱『{call}、{what}をお願いしたいんですけど……いつなら空いてますか？』",
    "chat.favor_ask_plants": "📱『{from}から{to}まで家を空けるので、そのあいだに植木の水やりをお願いできませんか？ 鍵は預けますね』",
    "chat.favor_yes": "📱『助かります！ じゃあ{when}にお願いします』",
    "chat.favor_busy": "📱『ごめんなさい、その時間はちょっと……』",
    "chat.favor_counter": "📱『その時間はちょっと……{when}ならどうですか？』",
    "chat.favor_lapsed": "📱『{what}のこと、ほかの人に頼んだら片付きました。気にしないでくださいね』",
    "chat.favor_missed": "📱『……今日、来てくれると思って待ってたんですけど』",
    "chat.favor_plants_dead": "📱『……帰ったら、植木が枯れてました』",
    "chat.favor_plants_thanks": "📱『ただいま戻りました。植木、元気でした！ 水やり、ありがとうございました』",
    "chat.favor_resched": "📱『ごめんなさい、{what}の日、{when}にずらしてもらえませんか？』",
    "chat.favor_cancel": "📱『ごめんなさい、{what}は取りやめになりました。せっかくだったのに……』",
    "chat.want_space": "📱『ごめんなさい、今日はちょっと一人でいたい気分で……。また連絡しますね』",
    "chat.own_time": "📱『ふふ、うれしいです。でも、たまには{call}も自分の時間を大事にしてくださいね』",
    "chat.appoint_rearranged": "📱『その日、予定があったんですけど、ずらしました。{when}、{place}で大丈夫です！』",
    "chat.appoint_move_mine": "📱『ごめんなさい、その日やっぱり都合が悪くなっちゃって……{when}にしてもらえませんか？』",
    "chat.req_money_again": "またお願いしてもいいですか……？ 今月も、ちょっと足りなくて",
}
# 何もないときの共通の言い方 (性格プリセットに chat.ask_how_nothing が無ければ, ここから選ぶ)
NOTHING = ("特に変わりないですよ。", "相変わらずです。", "まあ、ぼちぼちです。")
SCENE_LABEL = {"greet_morning": "おはよう", "greet_night": "おやすみ", "thanks": "お礼", "apology": "謝罪 (理由を知っている)",
               "apology_confused": "謝罪 (理由がわからない)", "smalltalk": "雑談", "ask_how": "近況 ({news} に下の 2 つのどちらか)",
               "ask_how_news": "近況の中身: 出来事があったとき ({tell} に出来事. 一文のかけら)",
               "ask_how_nothing": "近況の中身: 特に何もないとき (一文のかけら)",
               "consult": "相談", "tease": "からかい (笑ってくれた)", "tease_hurt": "からかい (傷ついた)", "flirt": "甘える (応えてくれた)",
               "flirt_cold": "甘える (引かれた)", "invite_yes": "会おう (応じた)", "invite_no": "会おう (断った)", "photo": "写真",
               "stamp": "スタンプ",
               "apology_half": "謝罪 (半分だけ許す. 理由は弱まるが残る)", "apology_deeds": "謝罪 (謝るなら態度で)",
               "apology_refuse": "謝罪 (受け付けない)", "apology_late": "謝罪 (日が経ってから. 今さら？)",
               "apology_enough": "謝罪 (続けて謝られて. もういいって)", "apology_irritated": "謝罪 (さらに続けて. 苛立つ)",
               "too_often_again": "謝ったばかりなのに, また連絡しすぎ",
               "thanks_what": "お礼 (心当たりがない)", "thanks_again": "お礼 (同じことに何度も)",
               "thanks_not_yet": "謝ったあとのお礼 (半分だけ許した. まだ許したわけじゃない)",
               "thanks_unforgiven": "謝ったあとのお礼 (許していない. 態度で・受け付けない)",
               "greet_odd_morning": "おはよう (昼・夜に)", "greet_odd_night": "おやすみ (朝・昼に)",
               "greet_again": "あいさつ (同じ朝・夜の 2 回目)", "stamp_only": "メッセージにスタンプだけで返された",
               "stamp_spam": "スタンプを続けて送られた", "may_call_ok": "今いい？ (いいよ)", "may_call_later": "今いい？ (あとで)",
               "otsukare": "お疲れさま (ちょうど終わった頃)", "otsukare_odd": "お疲れさま (的外れな時間)",
               "you_ok": "大丈夫？ (体調・落ち込みを知っていて)", "you_ok_what": "大丈夫？ (心当たりがない)",
               "what_doing": "今何してる？ ({doing} に今していること)", "what_doing_much": "今何してる？ (聞きすぎ. 束縛っぽい)",
               "nudge_ok": "返事まだ？ (急ぎの話で. 多少許される)", "nudge_bad": "返事まだ？ (急かされて嫌がる)",
               "nudge_huh": "返事まだ？ (もう返している)",
               "want_space": "連絡が続いて, 一人でいたいと距離を置く (依存度が低い)",
               "own_time": "連絡が続いて, あなたの時間も大事にしてと気づかう (献身的で依存度が低い)",
               "appoint_rearranged": "約束の誘い (自分の予定をずらして合わせた. {when} {place})",
               "appoint_move_mine": "約束した日を, 自分の都合で動かしたいと言ってくる (自分優先. {when})",
               "req_money_again": "（そばで）お金のおねだり. しょっちゅう頼んでいるとき (自分優先. 文頭の 📱 なし)",
               "selfie_yes": "自撮り送って (送ってくれた. 自撮りが添えられる)",
               "selfie_no": "自撮り送って (断られた)", "selfie_pester": "自撮り送って (続けて頼みすぎ)", "late_night": "夜中のメッセージ", "too_often": "連絡しすぎ",
               "repaid": "借りたお金を返した (一緒にいればその場で)", "money_worry": "返済が遅くて心配する (一緒にいればその場で)",
               "money_distrust": "返済が遅くて不信感を持つ (一緒にいればその場で)",
               "appoint_yes": "約束の誘い (応じた. {when} {place})", "appoint_no": "約束の誘い (断った)",
               "appoint_busy": "約束の誘い (その時間は予定がある)", "appoint_invite": "相手から約束に誘う ({when} {place})",
               "appoint_counter": "約束のやりとりで, 相手が別の日時を返す ({when} {place})",
               "appoint_cancel": "約束の当日, 体調を崩してキャンセル", "appoint_sorry": "約束をすっぽかしたあとで謝る",
               "appoint_missed": "あなたが約束をすっぽかした",
               "favor_ask_move": "頼まれごと: 引っ越しの手伝い ({when} その日しか無理)", "favor_ask_offer": "頼まれごと: 日時の案つき ({what} {when})",
               "favor_ask_when": "頼まれごと: いつなら空いているか聞く ({what})", "favor_ask_plants": "頼まれごと: 留守中の植木の水やり ({from}〜{to})",
               "favor_yes": "頼まれごとの日時を返した / 受けてくれた ({when})", "favor_busy": "頼まれごとの日時を返した / その時間は無理",
               "favor_counter": "頼まれごとの日時を返した / 別の日時を返してくる ({when})",
               "favor_lapsed": "頼まれごとの返事を放っておいた / ほかの人に頼んで済んだ ({what})",
               "favor_missed": "頼まれごとの約束をすっぽかした", "favor_plants_dead": "植木の水やりに行かず, 枯れていた",
               "favor_plants_thanks": "留守中の植木の水やりをした / 帰ってきてからのお礼",
               "favor_resched": "相手の都合で, 頼まれごとの日をずらしたい ({what} {when})", "favor_cancel": "相手の都合で, 頼まれごとが取りやめ ({what})"}


class Chat:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 記録
    def _path(self, cid):
        return store.wpath("chats", cid + ".json")

    def load(self, cid):
        d = store.load(self._path(cid), None) or {}
        d.setdefault("seen_t", 0)
        d.setdefault("items", [])
        return d

    def save(self, cid, d):
        d["items"] = d["items"][-500:]
        store.save(self._path(cid), d)

    def add(self, cid, who, text, kind=None, t=None, **extra):
        d = self.load(cid)
        it = {"t": t or time.time(), "who": who, "kind": kind, "text": text}
        it.update(extra)
        d["items"].append(it)
        d["items"].sort(key=lambda x: x["t"])
        if who == "me":
            d["seen_t"] = max(d["seen_t"], it["t"])        # 自分で送った時点までは, 読んだことに
        self.save(cid, d)
        return it

    def retime_last(self, cid, t, who="her"):
        d = self.load(cid)
        for it in reversed(d["items"]):
            if it["who"] == who:
                it["t"] = t
                break
        d["items"].sort(key=lambda x: x["t"])
        self.save(cid, d)

    def mark_read_by_her(self, cid, t):
        """相手が読んだ (既読が付く)."""
        d = self.load(cid)
        for it in d["items"]:
            if it["who"] == "me" and not it.get("read_t") and it["t"] <= t:
                it["read_t"] = t
        self.save(cid, d)

    def mark_seen(self, cid):
        d = self.load(cid)
        d["seen_t"] = time.time()
        self.save(cid, d)
        return {"ok": True}

    def unread(self, cid, d=None):
        d = d or self.load(cid)
        return sum(1 for it in d["items"] if it["who"] == "her" and it["t"] > d["seen_t"])

    # ------------------------------------------------------------------ 送る
    def send(self, cid, kind):
        if kind not in KINDS:
            raise ValueError("メッセージの種類が違います: %s" % kind)
        return self.app.act("message", cid, opts={"msg_kind": kind})

    # ------------------------------------------------------------------ 返信の中身
    def reply(self, char, st, kind, now, ctx):
        """届いたメッセージを読んで, 返す内容と効果を決める. (場面の鍵, 効果, 置き換え) を返す."""
        app, L = self.app, self.app.life
        p = st["params"]
        cid = char["id"]
        stage = app.bonds.stage(cid)
        extra = {}
        if kind == "repaid":                    # 返したお金の受け取り (効き目は返したときに済んでいる)
            return "repaid", {}, extra
        meta = ctx.get("_meta") or {}
        if kind == "apology":       # 謝るのは, 連絡が多いうちに数えない (連絡しすぎを謝るのも). 許し方は manners
            return app.manners.reply(char, st, kind, now, ctx, meta)
        sent = ctx.get("_sent") or now
        if kind == "thanks" and (ctx.get("_after_apology") and not (st.get("apology_last") or {}).get("grace_used")
                                 or app.manners.thanks_grace(st, sent)):
            st["apology_last"]["grace_used"] = True          # 謝罪の返事のすぐあとのお礼 1 通目: 連絡が多いうちに数えない
            st["contacts"] = [x for x in st.get("contacts") or [] if abs(app.bonds.contact_t(x) - sent) > 1e-6]
        elif ctx.get("too_often"):
            if app.manners.again(st, "_too_often", now):      # 謝ったばかりなのに, また連絡しすぎ: ふつうより強く響く
                st["apology_last"]["out_before"] = st["apology_last"].get("out")      # 謝罪の結果 (あとで当て直すとき用)
                st["apology_last"]["out"] = "broken"
                L.add_reason(st, "player", "bad", "謝ったばかりなのに、%sからまた連絡が多い" % app.pronouns(char)[2], now,
                             told=True, delta=-4.0, action="_too_often")
                return "too_often_again", {"mood": -5, "trust": -2, "affection": -1}, extra
            # 連絡が多くて少し疲れた: あなたのせいの理由として覚える (謝れば和らぐ)
            L.add_reason(st, "player", "bad", "%sからの連絡が多くて、少し疲れた" % app.pronouns(char)[2], now, told=True,
                         delta=-2.0, action="_too_often")
            return "too_often", {"mood": -2, "affection": -1}, extra
        if ctx.get("phase") in ("midnight", "dawn") and kind != "greet_night":
            return "late_night", {"mood": -2, "stress": 2}, extra
        space = self._space(char, st, kind, now, ctx)
        if space:
            return space, {}, extra
        got = app.manners.reply(char, st, kind, now, ctx, meta)
        if got:
            return got
        if kind == "ask_selfie":
            # 自撮りを頼む: 仲・機嫌・ドキドキ・恥じらい・間柄しだい (必ずではない). 続けて頼むと嫌がられる
            asks = [t for t in st.get("selfie_asks") or [] if now - t < 3 * 3600]
            st["selfie_asks"] = (asks + [now])[-6:]
            if len(asks) >= 2:
                return "selfie_pester", {"mood": -4, "affection": -1}, extra
            chance = 0.15 + (p.get("affection", 40) - 40) / 100.0 + (p.get("mood", 50) - 50) / 150.0 \
                + p.get("heart", 0) / 300.0 - app.wardrobe.modesty(char) / 40.0 + (0.1 if stage in ("visit", "live") else 0.0)
            if random.random() < max(0.03, min(0.85, chance)):
                return "selfie_yes", {"heart": 3, "loneliness": -4}, extra
            return "selfie_no", {"shyness": 3}, extra
        if kind == "consult":
            app.manners.favor(st, "consult", now)          # 相談にのってくれた (お礼の心当たり)
        if kind == "ask_how":
            untold = [x for x in L.reasons(st, now) if not x["told"] and x.get("tell")]
            if untold:
                L.mark_told(untold[0])
                news = app.persona_text(char, "chat.ask_how_news") or LINES["chat.ask_how_news"]
                extra["news"] = news.replace("{tell}", untold[0]["tell"])
            else:
                extra["news"] = app.persona_text(char, "chat.ask_how_nothing") or random.choice(NOTHING)
            return "ask_how", {"loneliness": -4, "trust": 1}, extra
        if kind == "tease":
            if p.get("affection", 0) >= 55 and p.get("mood", 50) >= 50 and random.random() < 0.7:
                return "tease", {"heart": 3, "mood": 2, "boredom": -4}, extra
            return "tease_hurt", {"mood": -4, "trust": -1}, extra
        if kind == "flirt":
            if stage in ("visit", "live") or p.get("affection", 0) >= 70:
                return "flirt", {"heart": 6, "affection": 2, "loneliness": -6}, extra
            return "flirt_cold", {"shyness": 5, "affection": -2, "trust": -1}, extra
        if kind == "invite":
            ok = p.get("affection", 0) >= float(app.bonds.cfg()["meet_min_affection"]) and p.get("mood", 50) >= 40 \
                and random.random() < 0.75
            if ok:
                st["date_promise"] = now + 12 * 3600
                return "invite_yes", {"heart": 3, "mood": 3}, extra
            return "invite_no", {}, extra
        eff = {"greet_morning": {"loneliness": -3, "mood": 1}, "greet_night": {"loneliness": -3, "mood": 1},
               "thanks": {"mood": 3, "trust": 1}, "smalltalk": {"boredom": -6, "loneliness": -5, "mood": 2},
               "consult": {"trust": 2, "affection": 1}, "photo": {"mood": 2, "loneliness": -3},
               "stamp": {"loneliness": -2}}.get(kind, {})
        return kind, eff, extra

    def _space(self, char, st, kind, now, ctx):
        """連絡が続いたとき (多すぎるほどではない), 依存度が低い相手は距離を置き, 献身的で依存度が低い相手は気づかう.
        一日に一度まで. 必ずではない."""
        if kind not in ("smalltalk", "what_doing", "ask_how", "stamp", "tease", "flirt", "photo", "otsukare"):
            return None
        dep, dev = ctx.get("dependence", 50), ctx.get("devotion", 50)
        if dep >= 35:
            return None
        day = datetime.fromtimestamp(now).strftime("%Y%m%d")
        if st.get("space_day") == day:
            return None
        tol = self.app.bonds.tolerance(char, char["id"], st, now)
        if ctx.get("contacts_24h", 0) < 0.6 * tol or random.random() >= 0.5:
            return None
        st["space_day"] = day
        return "own_time" if dev >= 65 else "want_space" if dep < 25 else None

    def line(self, char, key, extra):
        app = self.app
        t = app.persona_text(char, "chat." + key) or LINES["chat." + key]
        fp, _, call = app.pronouns(char)
        for k, v in dict(extra, fp=fp, call=call, name=char.get("name", "")).items():
            t = t.replace("{%s}" % k, str(v))
        return t

    # ------------------------------------------------------------------ 一覧・トーク
    def list_view(self):
        """トーク一覧 (連絡先を知っている人). 新しい順."""
        app = self.app
        out = []
        for cid, c in app.chars.items():
            if app.bonds.stage(cid) == "known":
                continue
            d = self.load(cid)
            last = d["items"][-1] if d["items"] else None
            out.append({"id": cid, "name": c.get("name", ""), "face": self.face(cid), "unread": self.unread(cid, d),
                        "last": last, "together": app.bonds.together(cid),
                        "waiting": bool(app.state(cid).get("msg_pending"))})
        out.sort(key=lambda x: -(x["last"] or {}).get("t", 0))
        return out

    def face(self, cid):
        """顔: 顔だけのアイコンがあればそれ, 無ければログの最新の画像."""
        c = self.app.chars.get(cid) or {}
        if self.app.has_icon(c):
            return c["icon"]
        for e in reversed(self.app.log(cid)):
            if e.get("image"):
                return e["image"]
        return None

    def thread(self, cid):
        app = self.app
        d = self.load(cid)
        st = app.state(cid)
        return {"id": cid, "name": app.chars[cid].get("name", ""), "face": self.face(cid), "items": d["items"][-200:],
                "seen_t": d["seen_t"], "waiting": bool(st.get("msg_pending")), "together": app.bonds.together(cid),
                "promise": st.get("date_promise", 0) if st.get("date_promise", 0) > time.time() else 0,
                "appoints": [x for x in app.appoint.view() if x["cid"] == cid],
                "appoint_choices": app.appoint.choices(cid) if app.bonds.stage(cid) in ("contact", "visit") else [],
                "kinds": [{"id": k, "label": v[0], "icon": v[1]} for k, v in KINDS.items()],
                "actions": self.phone_actions(cid)}

    def phone_actions(self, cid):
        """スマホからできる, メッセージ以外のこと (電話・「家に行ってもいい？」など. 離れている相手だけ)."""
        app = self.app
        if app.bonds.together(cid) or app.bonds.stage(cid) == "known":
            return []
        av = app.person_view(cid)["available"]
        return [{"id": a["id"], "name": a.get("name", a["id"]), "icon": a.get("icon", ""), "ok": True}
                for a in app.actions if a["id"] in av and av[a["id"]]["ok"] and a["id"] != "message" and a.get("category") in ("連絡", "会う")
                and not (a.get("override") or {}).get("outing") and not a.get("bond", "").endswith(("_start", "_end"))
                and app.bonds.allowed_apart(a, cid) and not app.appoint.needs(a, cid)]

    def unread_total(self):
        return sum(x["unread"] for x in self.list_view())
