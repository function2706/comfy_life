"""メッセージアプリ (離れている相手とのトーク).

- トークは相手ごと (data/worlds/<id>/chats/<cid>.json): {"seen_t": あなたが読んだところ, "items": [{t, who, kind, text, read_t?}]}
  who: me (あなたの発言. 要約「（挨拶をした）」) / her (相手の本文) / sys (電話の履歴・約束など)
- 送るメッセージの種類 (KINDS). 返信は既存の時間差の仕組み (msg_pending) に乗る: 相手が寝ている・手が離せないなら落ち着いてから,
  機嫌や仲しだいで遅れる・来ない (既読だけ付く). 返信の中身は種類 × 状況 (性格・間柄・機嫌・機嫌の理由・時間帯・頻度) で変わる.
  現実的に: 浅い仲で甘えると引かれる, からかいは逆効果のことも, 理由を知らずに謝ると戸惑われる, 夜中は迷惑, 送りすぎると冷たくなる.
  「会おう」に応じてくれたら, 会おうという話になる (date_promise. 半日のうちに約束を持ちかけると受けてもらいやすい).
  日時と行き先を決めて会うのは約束 (core/appoint.py). 約束の誘いの返事も, この時間差で届く.
- 電話 (出た・出なかった)・折り返し・相手からのメッセージ (働きかけ・オフライン中に届いたもの) も同じトークに並べる.
"""
import random
import time

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
    "stamp": ("スタンプ", "🐾", "（スタンプを送った）"),
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
    "chat.consult": "📱『そうだったんですね……。{fp}でよければ、いつでも聞きますよ』",
    "chat.tease": "📱『もう、からかわないでくださいよ〜』",
    "chat.tease_hurt": "📱『……そういうの、ちょっと傷つきます』",
    "chat.flirt": "📱『……もう。{fp}も、会いたいです』",
    "chat.flirt_cold": "📱『え……えっと、急にどうしたんですか……？』",
    "chat.invite_yes": "📱『いいですね！ 会いましょう』",
    "chat.invite_no": "📱『ごめんなさい、しばらくはちょっと……』",
    "chat.photo": "📱『わ、いい写真ですね！』",
    "chat.stamp": "📱『（スタンプが返ってきた）』",
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
}
SCENE_LABEL = {"greet_morning": "おはよう", "greet_night": "おやすみ", "thanks": "お礼", "apology": "謝罪 (理由を知っている)",
               "apology_confused": "謝罪 (理由がわからない)", "smalltalk": "雑談", "ask_how": "近況 ({news} に出来事)",
               "consult": "相談", "tease": "からかい (笑ってくれた)", "tease_hurt": "からかい (傷ついた)", "flirt": "甘える (応えてくれた)",
               "flirt_cold": "甘える (引かれた)", "invite_yes": "会おう (応じた)", "invite_no": "会おう (断った)", "photo": "写真",
               "stamp": "スタンプ", "late_night": "夜中のメッセージ", "too_often": "連絡しすぎ",
               "repaid": "借りたお金を返した (一緒にいればその場で)", "money_worry": "返済が遅くて心配する (一緒にいればその場で)",
               "money_distrust": "返済が遅くて不信感を持つ (一緒にいればその場で)",
               "appoint_yes": "約束の誘い (応じた. {when} {place})", "appoint_no": "約束の誘い (断った)",
               "appoint_busy": "約束の誘い (その時間は予定がある)", "appoint_invite": "相手から約束に誘う ({when} {place})",
               "appoint_counter": "約束のやりとりで, 相手が別の日時を返す ({when} {place})",
               "appoint_cancel": "約束の当日, 体調を崩してキャンセル", "appoint_sorry": "約束をすっぽかしたあとで謝る",
               "appoint_missed": "あなたが約束をすっぽかした"}


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
        if kind == "apology":       # 謝るのは, 連絡が多いうちに数えない (連絡しすぎを謝るのも)
            bad = L.dominant(st, now, "bad")
            if bad and bad["kind"] == "player":            # あなたのせいで機嫌が悪い理由がある: 謝れば和らぐ
                L.resolve(st, "bad", now)
                return "apology", {"mood": 4, "trust": 1}, extra
            return "apology_confused", {"mood": -1}, extra
        if ctx.get("too_often"):
            # 連絡が多くて少し疲れた: あなたのせいの理由として覚える (謝れば和らぐ)
            L.add_reason(st, "player", "bad", "%sからの連絡が多くて、少し疲れた" % app.pronouns(char)[2], now, told=True,
                         delta=-2.0, action="_too_often")
            return "too_often", {"mood": -2, "affection": -1}, extra
        if ctx.get("phase") in ("midnight", "dawn") and kind != "greet_night":
            return "late_night", {"mood": -2, "stress": 2}, extra
        if kind == "ask_how":
            untold = [x for x in L.reasons(st, now) if not x["told"] and x.get("tell")]
            if untold:
                L.mark_told(untold[0])
                extra["news"] = untold[0]["tell"] + "んです。"
            else:
                extra["news"] = random.choice(["特に変わりないですよ。", "相変わらずです。", "まあ、ぼちぼちです。"])
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
