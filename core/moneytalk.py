"""お金のこと: あなたのお金の使い方への口出し (相手の管理傾向しだい) と, どっちが出すか (性格しだいで, 喧嘩にならずに冷めることも).

- 使い方: 宝くじ・株を買った・5,000 円以上の買い物 (家計簿の裏の記録 life.ledger から拾う). 同居相手か, 家に行ける仲で
  好感度 50 以上の相手が, そばにいるときに気づくと, 管理傾向 (性格 MANAGE + 依存度) と額・続け方しだいで口を出す (一日に一度まで).
  説明する (会話スキルで納得 / 微妙) / 謝る / 言い返す (言い争いに. core/quarrel.py) / 聞き流す (言わないまま少し冷める).
- どっちが出すか: 一緒に払う行動のたびに, 誰が払ったかを覚える (pay_hist). 性格の好み PAY_PREF:
  treat = おごられたい (割り勘・自分が払うと, ときどき言わないまま少し冷める. たまに口に出す) /
  split = 割り勘がいい (いつもあなたが払うと, 気が引ける) / それ以外は気にしない. 必ずではない (公理).
変わるのは相手の値だけ (あなたの値は無い). 遡及なし (これから使ったお金・払った分から).
"""
import random
import time
from datetime import datetime

MANAGE = {"jimuteki": 0.9, "aneki": 0.8, "rikejo": 0.7, "kedakai": 0.6, "sadist": 0.6, "tsundere": 0.6, "osananajimi": 0.6,
          "teinei": 0.5, "otokomae": 0.5, "cool": 0.4, "hikutsu": 0.4, "uchiki": 0.4, "byoujaku": 0.4, "amaenbo": 0.4,
          "ojousama": 0.3, "mukuchi": 0.3, "ottori": 0.3, "genki": 0.3, "boyish": 0.3, "hitonatsukko": 0.3, "itazura": 0.3,
          "tenshin": 0.1, "fushigi": 0.1}
PAY_PREF = {"ojousama": "treat", "amaenbo": "treat", "sadist": "treat", "kedakai": "treat", "tenshin": "treat",
            "jimuteki": "split", "rikejo": "split", "cool": "split", "boyish": "split", "osananajimi": "split", "aneki": "split"}
BIG = 5000
CHOICES = {"explain": "わけを説明する", "sorry": "謝る", "push": "言い返す", "ignore": "聞き流す"}
LINES = {
    "money.complain": "……また{what}ですか？ そういうの、ちょっと心配なんですけど",
    "money.explain_ok": "……そういうことなら、まあ。でも、ほどほどにしてくださいね",
    "money.explain_meh": "……ふうん。言いたいことはわかりますけど",
    "money.sorry_ok": "わかってくれたなら、いいです。気をつけてくださいね",
    "money.fight": "心配して言ってるのに、そんな言い方ないじゃないですか",
    "money.ignore": "……聞いてます？ ……もういいです",
    "money.remark_treat": "……たまには、{call}がごちそうしてくれてもいいんですよ？",
    "money.remark_owe": "いつも出してもらってばかりで、なんだか悪いです。次は{fp}に出させてください",
}
SCENE_LABEL = {"complain": "あなたのお金の使い方に口を出す ({what} に 宝くじ・株・高い買い物)",
               "explain_ok": "使い方のわけを聞いて, 納得する", "explain_meh": "使い方のわけを聞いたが, 微妙",
               "sorry_ok": "使い方を謝られて, 受け入れる", "fight": "使い方のことで言い返されて, 言い争いに",
               "ignore": "使い方の話を聞き流されて, 冷める",
               "remark_treat": "割り勘・自分持ちが続いて, たまにはおごってほしいと漏らす (おごられたい性格)",
               "remark_owe": "いつもあなたが払うので, 気が引ける (割り勘がいい性格)"}


class MoneyTalk:
    def __init__(self, app):
        self.app = app

    def line(self, char, key, extra=None):
        app = self.app
        t = app.persona_text(char, "money." + key) or LINES["money." + key]
        fp, _, call = app.pronouns(char)
        for k, v in dict(extra or {}, fp=fp, call=call, name=char.get("name", "")).items():
            t = t.replace("{%s}" % k, str(v))
        return t

    def _entry(self, char, st, t, key, text, deltas):
        app = self.app
        dt = datetime.fromtimestamp(t)
        scene = app.scene_at(char, st, dt)
        act = {"id": "_money_talk", "name": "お金のこと", "icon": "💴", "pos": "", "neg": ""}
        pos, neg, parts = app.build_prompt(char, st, dt, act)
        e = app._new_entry(char["id"], t, act, text, deltas, scene, dt, pos, neg, parts)
        e["money_talk"] = key
        app.save_log(char["id"])
        return e

    def manage(self, char, st):
        """管理傾向 (0〜1): 性格 + 依存度 (相手を自分のものと思うほど口を出す)."""
        m = MANAGE.get(char.get("persona_id") or "", 0.4) + 0.2 * self.app.attach.factor(char, st, "dependence")
        return max(0.0, min(1.0, m))

    # ------------------------------------------------------------------ 使い方
    def spent(self, t, amount, cat, note):
        """家計簿の裏の記録から: 宝くじ・株を買った・高い買い物を覚える."""
        if amount >= 0:
            return
        what = "宝くじ" if note.startswith("宝くじ") else "株" if cat == "invest" else \
            "高い買い物（%s）" % note if cat == "shopping" and -amount >= BIG else None
        if not what:
            return
        ps = self.app.life.player_state()
        log = [x for x in ps.get("spend_log") or [] if t - x["t"] < 14 * 86400]
        log.append({"t": t, "what": what, "amount": int(-amount)})
        ps["spend_log"] = log[-40:]

    def tick(self, char, st, now):
        """そばにいる (同居相手か, 家に行ける仲で好感度 50 以上の) 相手が, あなたの使い方に気づいて口を出すか (一日に一度)."""
        app = self.app
        cid = char["id"]
        stage = app.bonds.stage(cid)
        if st.get("money_talk") or not app.bonds.together(cid, now):
            return
        if not (stage == "live" or (stage == "visit" and st["params"].get("affection", 50) >= 50)):
            return
        day = datetime.fromtimestamp(now).date().isoformat()
        if st.get("money_day") == day:
            return
        seen = float(st.get("money_seen", 0))
        new = [x for x in app.life.player_state().get("spend_log") or [] if x["t"] > seen and now - x["t"] < 3 * 86400]
        if not new:
            return
        st["money_day"] = day
        st["money_seen"] = now
        total = sum(x["amount"] for x in new)
        money = max(0, int(app.life.player_state().get("money", 0)))
        M = self.manage(char, st)
        p = M * (0.25 + min(1.0, total / float(max(10000, money + total)))) * (1.3 if len(new) >= 2 else 1.0)
        app.trace.add("money_talk", "使い方に気づいた", cid, now, M=round(M, 2), total=total, n=len(new), p=round(p, 2))
        if random.random() >= min(0.85, p):
            return
        big = max(new, key=lambda x: x["amount"])
        st["money_talk"] = {"what": big["what"], "amount": big["amount"], "t": now}
        self._entry(char, st, now, "complain", self.line(char, "complain", {"what": big["what"].split("（")[0]}), {})

    def pending(self):
        app = self.app
        for cid, char in app.chars.items():
            mt = app.state(cid).get("money_talk")
            if mt and app.bonds.together(cid):
                return {"cid": cid, "name": char.get("name", ""),
                        "text": "（%sが、%sのことを気にしている）" % (char.get("name", ""), mt["what"]),
                        "choices": [{"id": k, "label": v} for k, v in CHOICES.items()]}
        return None

    def respond(self, choice, now=None):
        app = self.app
        now = now or time.time()
        pv = self.pending()
        if not pv or choice not in CHOICES:
            raise ValueError("いまは何もありません")
        char = app.char(pv["cid"])
        st = app.state(char["id"])
        mt = st.pop("money_talk")
        if choice == "explain":
            ok = random.random() < 0.3 + 0.5 * app.life.skill_soft("talk")
            key, eff = ("explain_ok", {}) if ok else ("explain_meh", {"mood": -1})
        elif choice == "sorry":
            key, eff = "sorry_ok", {"mood": 1}
        elif choice == "push":
            key, eff = "fight", {"mood": -4}
            app.quarrel.start(char, st, now, "お金", her_fault=False)
        else:
            key, eff = "ignore", {"mood": -2, "affection": -1, "trust": -1}
        if any(v > 0 for v in eff.values()):
            eff, _ = app.bonds.realize(char, st, eff, "_money_" + choice, now)
        d = app.apply_effects(st, app.trait_effects(char, eff))
        said = {"explain": "（%sのわけを説明した）", "sorry": "（%sのことを謝った）", "push": "（%sのことで言い返した）",
                "ignore": "（%sの話を聞き流した）"}[choice] % mt["what"].split("（")[0]
        e = self._entry(char, st, now, key, said + "\n" + self.line(char, key), d)
        app.trace.add("money_talk", "使い方の話への出方", char["id"], now, choice=choice, key=key)
        app.save_state(char["id"])
        return {"entry": e, "key": key}

    # ------------------------------------------------------------------ どっちが出すか
    def after_pay(self, char, st, payer, now):
        """一緒に払ったあと: 誰が払ったかを覚え, 性格の好みとずれていれば, ときどき (言わないまま) 少し冷める / 漏らす."""
        app = self.app
        hist = (st.get("pay_hist") or []) + [payer]
        st["pay_hist"] = hist[-6:]
        pref = PAY_PREF.get(char.get("persona_id") or "")
        key, eff, tell = None, {}, None
        call = app.pronouns(char)[2]
        if pref == "treat" and payer in ("split", "her"):
            fv = app.attach.factor(char, st, "devotion")
            if random.random() < max(0.05, 0.25 - 0.15 * fv):
                eff = {"affection": -random.uniform(0.5, 1.5)}
                tell = "%sがおごってくれない" % call
                if random.random() < 0.3:
                    key = "remark_treat"
        elif pref == "split" and len(hist) >= 4 and all(x == "me" for x in hist[-4:]) and random.random() < 0.25:
            eff, key = {"mood": -1}, "remark_owe"
        if not eff:
            return None
        d = app.apply_effects(st, app.trait_effects(char, eff))
        if tell:
            app.life.add_reason(st, "player", "bad", tell, now, told=False, delta=d.get("affection", 0), action="_pay")
        app.trace.add("money_talk", "払い方のずれ", char["id"], now, pref=pref, payer=payer, hist=st["pay_hist"], key=key)
        if key:
            return self._entry(char, st, now + 0.001, key, self.line(char, key), d)
        return None
