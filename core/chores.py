"""同居相手との家事の分担 (家の汚れの 4 つ: 散らかり・洗い物・洗濯物・ゴミ. core/home.py).

- 分担: 4 つそれぞれを「あなた / 相手 / 気づいた方」から (同居相手との会話「家事の分担を話す」). 相手の担当にしようとすると,
  献身度・きれい好き・機嫌・さぼり癖しだいで引き受ける / 断る. あなたの担当・気づいた方にするのはいつでも.
- 相手の担当: 一日のうち (昼〜夕方の決まった時刻) に, やるかどうか (献身度・世話焼き・きれい好き・機嫌・疲れ・さぼり癖).
  やれば献身度の帳簿に「相手が尽くした」. そばにいれば「やっておいた」と言うことも.
- さぼったとき (相手の担当がたまっていて, 二人とも家にいる): 知らせが出て, あなたの出方を選ぶ (一日に一度).
  見逃して自分でやる (あなたの時間と体力. さぼり癖が少しつく) / お願いする (すぐ・あとで・渋々) /
  たしなめる (改まる・反発) / 冗談めかして言う (仲が深ければ通じ, 浅いと嫌味). 変わるのは相手の値と, あなたが払うものだけ.
- あなたの担当がたまっていると, 相手が代わりにやってくれる (帳簿では相手が尽くした) か, 責められる (機嫌の理由に).
- さぼり癖 (slack 0〜1) は相手ごとの裏の値 (画面に出さない).
以前のセーブ: 分担は全部「気づいた方」, さぼり癖なしから (過去の家事にはさかのぼらない).
"""
import random
import time
from datetime import datetime

from .home import PART_LABEL, PARTS

WHO = ("me", "her", "either")
SLACK_AT = 60          # 相手の担当がここまでたまると「さぼっている」
MINE_AT = 70           # あなたの担当がここまでたまると, 相手が気にする
CHOICES = {"overlook": "見逃して自分でやる", "ask": "お願いする", "scold": "たしなめる", "joke": "冗談めかして言う"}
# 共通のセリフ (性格プリセットの chores.<場面> があればそちら). {part} に家事の名前
LINES = {
    "chores.did": "{part}、やっておきましたよ",
    "chores.share_yes": "{part}ですね。わかりました、{fp}がやります",
    "chores.share_no": "{part}は……ちょっと、{fp}には無理です",
    "chores.ask_yes": "あ、ごめんなさい。今やります",
    "chores.ask_later": "はーい、あとでやりますね",
    "chores.ask_grudging": "……わかりましたよ。やればいいんでしょう",
    "chores.scold_ok": "……ごめんなさい。ちゃんとやります",
    "chores.scold_back": "そんな言い方しなくてもいいじゃないですか。{call}だって、やってないときあるでしょう",
    "chores.joke_ok": "ふふ、バレました？ 今やりますね",
    "chores.joke_bad": "……それ、嫌味ですか？",
    "chores.cover": "{part}、たまってたのでやっておきましたよ",
    "chores.complain": "{call}、{part}、たまってますよ。{call}の番ですよね？",
}
SCENE_LABEL = {"did": "自分の担当の家事をやっておいた ({part})", "share_yes": "家事の分担: 引き受ける ({part})",
               "share_no": "家事の分担: 断る ({part})", "ask_yes": "さぼりをお願いされて, すぐやる",
               "ask_later": "さぼりをお願いされて, あとでやる", "ask_grudging": "さぼりをお願いされて, 渋々やる",
               "scold_ok": "さぼりをたしなめられて, 改める", "scold_back": "さぼりをたしなめられて, 反発する",
               "joke_ok": "さぼりを冗談めかして言われて, 通じる", "joke_bad": "さぼりを冗談めかして言われて, 嫌味に取る",
               "cover": "あなたの担当がたまっていたので, 代わりにやっておいた ({part})",
               "complain": "あなたの担当がたまっているのを責める ({part})"}


class Chores:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 記録
    def partner(self):
        cid = self.app.bonds.living()
        if not cid:
            return None, None
        return self.app.char(cid), self.app.state(cid)

    @staticmethod
    def share(st):
        sh = st.setdefault("chores_share", {})
        for k, _, _ in PARTS:
            sh.setdefault(k, "either")
        return sh

    def _fd(self, char, st):
        tr = self.app.traits(char)
        return self.app.attach.factor(char, st, "devotion"), float(tr.get("neat", 0)), float(tr.get("carer", 0.3))

    def line(self, char, key, extra=None):
        app = self.app
        t = app.persona_text(char, "chores." + key) or LINES["chores." + key]
        fp, _, call = app.pronouns(char)
        for k, v in dict(extra or {}, fp=fp, call=call, name=char.get("name", "")).items():
            t = t.replace("{%s}" % k, str(v))
        return t

    def _entry(self, char, st, t, key, text, deltas):
        app = self.app
        dt = datetime.fromtimestamp(t)
        scene = app.scene_at(char, st, dt)
        act = {"id": "_chores", "name": "家事", "icon": "🧺", "pos": "", "neg": ""}
        pos, neg, parts = app.build_prompt(char, st, dt, act)
        e = app._new_entry(char["id"], t, act, text, deltas, scene, dt, pos, neg, parts)
        e["chores"] = key
        app.save_log(char["id"])
        return e

    def _apply(self, char, st, eff, now, tag):
        eff, _ = self.app.bonds.realize(char, st, eff, "_chores_" + tag, now) if any(v > 0 for v in eff.values()) else (eff, None)
        return self.app.apply_effects(st, self.app.trait_effects(char, eff))

    # ------------------------------------------------------------------ 分担を決める
    def set_share(self, part, who, now=None):
        """同居相手と分担を話す (そばにいるとき). 相手の担当にするときだけ, 引き受けるか決める. 記録を返す."""
        app = self.app
        now = now or time.time()
        if part not in PART_LABEL or who not in WHO:
            raise ValueError("分担が違います")
        char, st = self.partner()
        if not char or not app.bonds.together(char["id"]):
            raise ValueError("分担は、一緒に暮らしている相手とそばで話しましょう")
        sh = self.share(st)
        extra = {"part": PART_LABEL[part]}
        if who != "her":
            sh[part] = who
            e = self._entry(char, st, now, None, "（%sは%sにした）" % (PART_LABEL[part], "自分の担当" if who == "me" else "気づいた方がやること"), {})
            app.save_state(char["id"])
            return {"entry": e, "ok": True}
        fv, neat, carer = self._fd(char, st)
        p = st["params"]
        pa = 0.45 + 0.3 * fv + neat / 40.0 + carer * 0.2 + (p.get("mood", 50) - 50) / 200.0 - 0.4 * float(st.get("slack", 0))
        ok = random.random() < max(0.05, min(0.95, pa))
        if ok:
            sh[part] = "her"
        key = "share_yes" if ok else "share_no"
        d = self._apply(char, st, {} if ok else {"mood": -1}, now, "share")
        e = self._entry(char, st, now, key, "（%sを頼んだ）\n%s" % (PART_LABEL[part], self.line(char, key, extra)), d)
        app.trace.add("chores", "分担を話した", char["id"], now, part=part, ok=ok, pa=round(pa, 2))
        app.save_state(char["id"])
        return {"entry": e, "ok": ok}

    # ------------------------------------------------------------------ 毎日・時間の経過
    def daily(self, char, st, t):
        """日付が替わったとき (同居相手): 今日, 自分の担当をやる時刻を決める."""
        if self.app.bonds.living() != char["id"]:
            return
        d0 = datetime.fromtimestamp(t).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        st["chores_plan"] = [{"part": k, "at": d0 + random.uniform(10, 20) * 3600}
                             for k, w in self.share(st).items() if w == "her"]
        st.pop("chores_asked", None)

    def tick(self, char, st, now):
        """同居相手: 決めた時刻に自分の担当をやるか / あなたの担当がたまっていれば気にする / さぼりの知らせ."""
        app = self.app
        if app.bonds.living() != char["id"]:
            return
        r = app.home.rec()
        fv, neat, carer = self._fd(char, st)
        p = st["params"]
        slack = float(st.get("slack", 0))
        together = app.bonds.together(char["id"], now)
        for x in [x for x in st.get("chores_plan") or [] if x["at"] <= now]:
            st["chores_plan"].remove(x)
            k = x["part"]
            if float(r[k]) < 25:
                continue
            pd = 0.35 + 0.35 * fv + 0.15 * carer + neat / 40.0 + (p.get("mood", 50) - 50) / 150.0 \
                - (0.15 if p.get("energy", 60) < 30 else 0) - 0.6 * slack
            done = random.random() < max(0.05, min(0.9, pd))
            app.trace.add("chores", "相手の担当", char["id"], now, part=k, done=done, pd=round(pd, 2))
            if not done:
                continue
            app.home.clean(55.0, [k], now)
            app.attach.give(char, st, "her", 1, "家事: " + PART_LABEL[k])
            if together and random.random() < 0.4:
                self._entry(char, st, now, "did", self.line(char, "did", {"part": PART_LABEL[k]}), {})
        if not together or st.get("chores_seen_day") == datetime.fromtimestamp(now).date().isoformat():
            return
        # あなたの担当がたまっている: 代わりにやる (献身的・世話焼き) か, 責める
        sh = self.share(st)
        mine = [k for k, w in sh.items() if w == "me" and float(r[k]) >= MINE_AT]
        if mine and random.random() < 0.5:
            st["chores_seen_day"] = datetime.fromtimestamp(now).date().isoformat()
            k = mine[0]
            if random.random() < max(0.05, min(0.8, 0.25 + 0.35 * fv + 0.3 * carer)):
                app.home.clean(55.0, [k], now)
                app.attach.give(char, st, "her", 2, "あなたの担当の家事を代わりに")
                self._entry(char, st, now, "cover", self.line(char, "cover", {"part": PART_LABEL[k]}), {})
            else:
                d = self._apply(char, st, {"mood": -2}, now, "complain")
                app.life.add_reason(st, "player", "bad", "%sが%sをためている" % (app.pronouns(char)[2], PART_LABEL[k]), now,
                                    told=True, delta=d.get("mood", 0), action="_chores_mine")
                self._entry(char, st, now, "complain", self.line(char, "complain", {"part": PART_LABEL[k]}), d)
            return
        # 相手の担当がたまっている: さぼりの知らせ (一日に一度)
        hers = [k for k, w in sh.items() if w == "her" and float(r[k]) >= SLACK_AT]
        if hers and not st.get("chores_slack") and not st.get("chores_asked"):
            st["chores_slack"] = {"part": hers[0], "t": now}
            st["chores_asked"] = True

    def pending(self):
        char, st = self.partner()
        if not char or not st.get("chores_slack"):
            return None
        k = st["chores_slack"]["part"]
        return {"cid": char["id"], "name": char.get("name", ""), "part": k, "part_label": PART_LABEL[k],
                "text": "（%sがたまっている。%sの担当のはずだ）" % (PART_LABEL[k], char.get("name", "")),
                "choices": [{"id": c, "label": l} for c, l in CHOICES.items()]}

    # ------------------------------------------------------------------ さぼりへの出方
    def respond(self, choice, now=None):
        app = self.app
        now = now or time.time()
        char, st = self.partner()
        sl = (st or {}).get("chores_slack")
        if not sl or choice not in CHOICES:
            raise ValueError("いまは何もありません")
        st.pop("chores_slack", None)
        k = sl["part"]
        extra = {"part": PART_LABEL[k]}
        fv, neat, carer = self._fd(char, st)
        p = st["params"]
        aff = p.get("affection", 50)
        slack = float(st.get("slack", 0))
        key, eff, text = None, {}, ""
        if choice == "overlook":                    # 自分でやる: あなたの時間と体力. さぼり癖が少しつく
            app.home.clean(70.0, [k], now)
            app.life.tire(4)
            app.attach.give(char, st, "me", 1, "家事: 相手の担当を代わりに")
            st["slack"] = round(min(1.0, slack + random.uniform(0.04, 0.1)), 3)
            text = "（%sは自分で片付けた）" % PART_LABEL[k]
        elif choice == "ask":
            r = random.random() - 0.3 * fv + 0.4 * slack - (p.get("mood", 50) - 50) / 150.0
            key = "ask_yes" if r < 0.45 else "ask_later" if r < 0.8 else "ask_grudging"
            if key == "ask_later":
                st.setdefault("chores_plan", []).append({"part": k, "at": now + random.uniform(1, 4) * 3600})
            else:
                app.home.clean(55.0, [k], now)
                app.attach.give(char, st, "her", 1, "家事: お願いされて")
            eff = {"mood": -1} if key == "ask_grudging" else {}
            st["slack"] = round(max(0.0, slack - 0.02), 3)
        elif choice == "scold":
            back = random.random() < max(0.05, min(0.85, 0.35 - 0.35 * fv + (50 - p.get("mood", 50)) / 100.0
                                                   + 0.2 * float(app.traits(char).get("grudge", 1)) - 0.2))
            if back:
                key, eff = "scold_back", {"mood": -5, "affection": -1}
                app.life.add_reason(st, "player", "bad", "%sに家事のことで責められた" % app.pronouns(char)[2], now, told=True,
                                    delta=-5, action="_chores_scold")
                st["chores_fight"] = now           # 喧嘩 (core の言い争い) のきっかけ
            else:
                key, eff = "scold_ok", {"mood": -2}
                app.home.clean(55.0, [k], now)
                st["slack"] = round(max(0.0, slack - 0.1), 3)
        else:                                       # 冗談めかして
            if random.random() < max(0.1, min(0.9, 0.2 + (aff - 50) / 60.0)):
                key, eff = "joke_ok", {"mood": 1}
                app.home.clean(55.0, [k], now)
                st["slack"] = round(max(0.0, slack - 0.05), 3)
            else:
                key, eff = "joke_bad", {"mood": -3}
        d = self._apply(char, st, eff, now, choice) if eff else {}
        said = "（%s）" % {"overlook": "", "ask": "%sをお願いした", "scold": "%sのことをたしなめた",
                           "joke": "%sのことを冗談めかして言った"}[choice].replace("%s", PART_LABEL[k]) if choice != "overlook" else ""
        e = self._entry(char, st, now, key, (said + "\n" + self.line(char, key, extra)) if key else text, d)
        app.trace.add("chores", "さぼりへの出方", char["id"], now, part=k, choice=choice, key=key, slack=st.get("slack"))
        app.save_state(char["id"])
        return {"entry": e, "key": key}

    # ------------------------------------------------------------------ あなたが家事をした
    def did_mine(self, part, h, now):
        """一人で家事をした: 相手の担当を片付けたなら, 帳簿ではあなたが尽くした側."""
        char, st = self.partner()
        if not char or h < 0.25:
            return
        sh = self.share(st)
        if (part and sh.get(part) == "her") or (not part and "her" in sh.values()):
            self.app.attach.give(char, st, "me", 1, "家事: 相手の担当も片付けた")
            self.app.save_state(char["id"])

    def view(self):
        char, st = self.partner()
        if not char:
            return None
        return {"cid": char["id"], "name": char.get("name", ""),
                "share": [{"id": k, "label": n, "who": self.share(st)[k]} for k, n, _ in PARTS]}
