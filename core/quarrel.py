"""意見が割れる・言い争い・仲直り (相手の出方に, あなたがどう応じるか. 変わるのは相手の値と, あなたが払うものだけ).

- 意見が割れる (行き先): 会っているときにお出かけの行き先を選ぶと, 相手の好み (appoint.place_weight) の方がずっと良く,
  献身度が低いほど・機嫌が悪いほど「そこじゃなくて〇〇がいい」と言われることがある. 押す (あなたの行き先. 相手の機嫌が下がる.
  意地っ張りなら言い争いに) / 譲る (相手の行き先. 費用・時間はそのぶん. 喜ぶ. 帳簿ではあなたが尽くした) /
  折衷案 (両方が許せる別の行き先. 乗ってくれるかは会話スキル) / 話をそらす (今回は出かけない. 少しむっとする).
- 言い争い: 行き先で押し切った / 家事でたしなめて反発された (core/chores.py). しばらく相手が素っ気ない (話しかけてこない・
  ノリが低い・返事が冷たい). 仲直りは謝罪 (いつもの謝罪の仕組み. 言い争いの理由が解決すれば終わる) か, 時間 (根に持つ性格ほど長い).
  相手に非があったときは, 献身度が高いほど相手から謝ってくることがあり, 許す / まだ許さない を選ぶ.
"""
import random
import time
from datetime import datetime

CHOICES = {"push": "押す（自分の行き先で）", "yield": "譲る（相手の行き先で）", "compromise": "折衷案を出す", "dodge": "話をそらす（今回はやめる）"}
SORRY = {"forgive": "許す", "not_yet": "まだ許さない"}
COLD_KINDS = ("smalltalk", "what_doing", "ask_how", "stamp", "tease", "flirt", "photo", "otsukare", "greet_morning", "greet_night")
LINES = {
    "fight.disagree": "えー、そこですか？ {place}のほうがよくないですか？",
    "fight.push_unhappy": "……わかりました。そっちでいいですよ",
    "fight.push_fight": "どうしていつも{call}が決めるんですか。……もういいです",
    "fight.yield_happy": "ほんとですか？ やった、ありがとうございます",
    "fight.compromise_ok": "{place}ですか。……うん、それならいいですね",
    "fight.compromise_meh": "{place}……まあ、いいですけど",
    "fight.dodge": "……話そらしましたね。まあ、いいですけど",
    "fight.cold": "……そうですか",
    "fight.sorry": "……さっきは、ごめんなさい。言いすぎました",
    "fight.forgiven": "……ありがとうございます。ほっとしました",
    "fight.not_forgiven": "……そうですよね。……ごめんなさい",
}
SCENE_LABEL = {"disagree": "行き先の意見が割れる ({place} に相手の行きたい所)", "push_unhappy": "行き先を押し切られて, 渋々",
               "push_fight": "行き先を押し切られて, 言い争いに", "yield_happy": "行き先を譲ってもらって, 喜ぶ",
               "compromise_ok": "折衷案に乗る ({place})", "compromise_meh": "折衷案が微妙 ({place})",
               "dodge": "話をそらされて, むっとする", "cold": "言い争いのあと, 素っ気ない返事",
               "sorry": "言い争いのあと, 自分から謝る", "forgiven": "謝って, 許してもらえた", "not_forgiven": "謝ったが, まだ許してもらえない"}


class Quarrel:
    def __init__(self, app):
        self.app = app

    def line(self, char, key, extra=None, phone=False):
        app = self.app
        t = app.persona_text(char, "fight." + key) or LINES["fight." + key]
        fp, _, call = app.pronouns(char)
        for k, v in dict(extra or {}, fp=fp, call=call, name=char.get("name", "")).items():
            t = t.replace("{%s}" % k, str(v))
        return "📱『%s』" % t if phone else t

    def _entry(self, char, st, t, key, text, deltas):
        app = self.app
        dt = datetime.fromtimestamp(t)
        scene = app.scene_at(char, st, dt)
        act = {"id": "_fight", "name": "言い合い", "icon": "💢", "pos": "", "neg": ""}
        pos, neg, parts = app.build_prompt(char, st, dt, act)
        e = app._new_entry(char["id"], t, act, text, deltas, scene, dt, pos, neg, parts)
        e["fight"] = key
        app.save_log(char["id"])
        return e

    def _eff(self, char, st, eff, now, tag):
        app = self.app
        if any(v > 0 for v in eff.values()):
            eff, _ = app.bonds.realize(char, st, eff, "_fight_" + tag, now)
        return app.apply_effects(st, app.trait_effects(char, eff))

    @staticmethod
    def active(st, now=None):
        f = st.get("fight")
        return bool(f) and (now or time.time()) < f.get("until", 0)

    # ------------------------------------------------------------------ 意見が割れる (行き先)
    def disagree(self, char, st, a, mine, now, dt):
        """お出かけの行き先を選んだとき: 相手の好みとずっと違えば, 言い返されることがある. 記録 (か None) を返す."""
        app = self.app
        from . import places as places_mod
        if now - float(st.get("disagree_last", 0)) < 3 * 3600:
            return None
        opts = [p for p in a.get("places") or [] if p != mine and places_mod.open_state(p, dt)["open"]]
        if not opts:
            return None
        W = app.appoint.place_weight
        wm = W(char, st, mine)
        hers = max(opts, key=lambda p: W(char, st, p))
        gap = W(char, st, hers) - wm
        if gap < 0.15:
            return None
        fv = app.attach.factor(char, st, "devotion")
        p = 0.05 + 0.3 * max(0.0, -fv) - 0.1 * max(0.0, fv) + (50 - st["params"].get("mood", 50)) / 150.0 + 0.6 * gap
        if self.active(st, now):
            p += 0.2
        if random.random() >= max(0.0, min(0.7, p)):
            return None
        st["disagree_last"] = now
        st["disagree"] = {"aid": a["id"], "mine": mine, "hers": hers, "t": now, "cid": char["id"]}
        e = self._entry(char, st, now, "disagree", "（%sに行こうと言った）\n%s" % (app.places.label(mine),
                                                                         self.line(char, "disagree", {"place": app.places.label(hers)})), {})
        app.trace.add("fight", "行き先の意見が割れた", char["id"], now, mine=mine, hers=hers, p=round(p, 2), gap=round(gap, 2))
        return e

    def pending(self):
        """いま答えを待っている「意見が割れた」か「相手から謝ってきた」. 画面用."""
        app = self.app
        for cid, char in app.chars.items():
            st = app.state(cid)
            d = st.get("disagree")
            if d and time.time() - d["t"] < 1800 and app.bonds.together(cid):
                return {"kind": "disagree", "cid": cid, "name": char.get("name", ""),
                        "text": "（%sは%sに行きたいらしい）" % (char.get("name", ""), app.places.label(d["hers"])),
                        "choices": [{"id": k, "label": v} for k, v in CHOICES.items()]}
            if st.get("fight_sorry"):
                return {"kind": "sorry", "cid": cid, "name": char.get("name", ""), "text": "（%sが謝ってきた）" % char.get("name", ""),
                        "choices": [{"id": k, "label": v} for k, v in SORRY.items()]}
        return None

    def respond(self, choice, cid=None, now=None):
        app = self.app
        now = now or time.time()
        pv = self.pending()
        if not pv:
            raise ValueError("いまは何もありません")
        char = app.char(pv["cid"])
        st = app.state(char["id"])
        if pv["kind"] == "sorry":
            return self._sorry_answer(char, st, choice, now)
        d = st.pop("disagree")
        if choice not in CHOICES:
            raise ValueError("選び方が違います")
        fv = app.attach.factor(char, st, "devotion")
        p = st["params"]
        key, eff, place, extra = None, {}, None, {}
        if choice == "push":
            place = d["mine"]
            stubborn = random.random() < max(0.05, min(0.8, 0.15 + 0.4 * max(0.0, -fv) + (50 - p.get("mood", 50)) / 150.0))
            if stubborn:
                key, eff = "push_fight", {"mood": -5, "affection": -1}
            else:
                key, eff = "push_unhappy", {"mood": -(1 + 3 * max(0.0, -fv))}
        elif choice == "yield":
            place, key, eff = d["hers"], "yield_happy", {"mood": 3}
            app.attach.give(char, st, "me", 1, "行き先を譲った")
        elif choice == "compromise":
            from . import places as places_mod
            dt = datetime.fromtimestamp(now)
            a = app.action(d["aid"])
            third = [x for x in a.get("places") or [] if x not in (d["mine"], d["hers"]) and places_mod.open_state(x, dt)["open"]]
            place = max(third, key=lambda x: app.appoint.place_weight(char, st, x)) if third else d["hers"]
            ok = random.random() < 0.3 + 0.5 * app.life.skill_soft("talk")
            key, eff = ("compromise_ok", {"mood": 1}) if ok else ("compromise_meh", {"mood": -1})
            extra = {"place": app.places.label(place)}
        else:
            key, eff = "dodge", {"mood": -1}
        deltas = self._eff(char, st, eff, now, choice)
        said = {"push": "（%sで行こうと押した）" % app.places.label(d["mine"]), "yield": "（%sにしようと譲った）" % app.places.label(d["hers"]),
                "compromise": "（%sはどうかと言ってみた）" % extra.get("place", ""), "dodge": "（話をそらした）"}[choice]
        e = self._entry(char, st, now, key, said + "\n" + self.line(char, key, extra), deltas)
        app.trace.add("fight", "意見が割れたときの出方", char["id"], now, choice=choice, key=key, place=place)
        if key == "push_fight":
            self.start(char, st, now, "行き先", her_fault=False)
        app.save_state(char["id"])
        r = {"entry": e, "key": key}
        if place:
            r["act"] = app.act(d["aid"], char["id"], opts={"place": place, "quarrel_ok": True})
        return r

    # ------------------------------------------------------------------ 言い争い
    def start(self, char, st, now, about, her_fault):
        app = self.app
        grudge = float(app.traits(char).get("grudge", 1))
        st["fight"] = {"t": now, "about": about, "her_fault": her_fault, "until": now + random.uniform(6, 30) * 3600 * grudge}
        app.life.add_reason(st, "player", "bad", "%sと%sのことで言い争いになった" % (app.pronouns(char)[2], about), now, told=True,
                            delta=-3, action="_fight")
        fv = app.attach.factor(char, st, "devotion")
        if her_fault and random.random() < max(0.05, min(0.85, 0.3 + 0.5 * fv)):
            st["fight"]["sorry_at"] = now + random.uniform(1, 6) * 3600
        app.trace.add("fight", "言い争いになった", char["id"], now, about=about, her_fault=her_fault, until=st["fight"]["until"],
                      sorry_at=st["fight"].get("sorry_at"))

    def end(self, char, st, now, why):
        st.pop("fight", None)
        st.pop("fight_sorry", None)
        for r in st.get("reasons") or []:
            if r.get("action") == "_fight" and not r.get("resolved"):
                r["resolved"] = True
        self.app.trace.add("fight", "言い争いが収まった", char["id"], now, why=why)

    def tick(self, char, st, now):
        """家事で反発された → 言い争いに / 謝罪で理由が解決した・時間がたった → 収まる / 相手から謝ってくる."""
        app = self.app
        if st.pop("chores_fight", None):
            self.start(char, st, now, "家事", her_fault=True)
        f = st.get("fight")
        if not f:
            return
        open_r = [r for r in st.get("reasons") or [] if r.get("action") == "_fight" and not r.get("resolved")]
        if now >= f["until"] or not open_r:
            self.end(char, st, now, "時間がたった" if now >= f["until"] else "謝って解決した")
            return
        if f.get("sorry_at") and now >= f["sorry_at"] and not st.get("fight_sorry"):
            f.pop("sorry_at", None)
            st["fight_sorry"] = now
            if app.bonds.together(char["id"]):
                self._entry(char, st, now, "sorry", self.line(char, "sorry"), {})
            else:
                app.chat.add(char["id"], "her", self.line(char, "sorry", phone=True), kind="fight_sorry", t=now)
                app.picked_up_phone(char, st, now)

    def _sorry_answer(self, char, st, choice, now):
        app = self.app
        if choice not in SORRY:
            raise ValueError("選び方が違います")
        st.pop("fight_sorry", None)
        if choice == "forgive":
            key = "forgiven"
            deltas = self._eff(char, st, {"mood": 3, "trust": 1}, now, "forgive")
            self.end(char, st, now, "許した")
        else:
            key = "not_forgiven"
            deltas = self._eff(char, st, {"mood": -3, "affection": -1}, now, "not_yet")
            if st.get("fight"):
                st["fight"]["until"] += 6 * 3600
        said = "（許した）" if choice == "forgive" else "（まだ許せないと言った）"
        e = self._entry(char, st, now, key, said + "\n" + self.line(char, key), deltas)
        app.save_state(char["id"])
        return {"entry": e, "key": key}

    def cold_reply(self, st, kind, now):
        """言い争い中のメッセージ: 素っ気ない返事になることがある."""
        return self.active(st, now) and kind in COLD_KINDS and random.random() < 0.6
