"""相手が体調を崩す (風邪) と, 看病に呼ぶか.

- 風邪 (状態の ill = {level, t0, until, called, nursed}): 時間の経過で, まれにひく (ILL_PER_DAY × 季節 (冬は多め)
  × 疲れ・ストレス・具合 × 体の弱さ (性格の hurt.health. 病弱な人ほど. 治りは drift_speed.health で遅く)). level 1 = 具合が悪い (健康は 42 まで) / 2 = 寝込む (25 まで).
  かかっている間は, 予定の外出 (大学・バイトなど) を休んで家で寝ている (sick_scene). until を過ぎると治る (健康は drift で戻る).
- 看病に呼ぶか (かかったとき一度): 一人で暮らしていて (あなたと同居なら, 家で看病できるので呼ばない), 連絡先以上の仲.
  起きやすさ = 具合 (寝込むほど) × 仲 (好感度・信頼) × 頼りたさ (依存度) × 性格 (人に頼りやすさ approach ・弱っているところを見せにくさ modesty).
  自分から来ない人・照れ屋は, 寝込むほどでなければまず呼ばない. 必ず呼ぶ, はない.
  頼み方: 来てほしいだけのことも, 品物 (CARE_ITEMS) を言ってくることもある.
  呼ぶ = 急な誘いと同じ形の約束 (place は相手の家, care: True, want: 品物). 答え方も同じ.
  断ると: あなたが仕事・外出中なら仕方ない (機嫌 −1). 家にいて断ると, 機嫌 −3・信頼 −1 (性格の hurt 倍率で揺れる).
- 来てくれた (with.care): 相手は寝込んでいる場面. 来てくれたこと自体がうれしい (realize を通す). 「看病する」(nurse) で治りが早まる (一度).
  持ってきた品 (CARE_ITEMS) を渡せる: 頼まれた品ならよく効く. ほかの品でも気が利いていればうれしい. 薬・飲み物などは治りを早める.
- 呼ばなかった: 治ったあと, 機嫌の理由 (言っていない) に「風邪で寝込んでいた」を残す (「何かあった？」で聞ける).
"""
import random
import time
from datetime import datetime

ILL_PER_DAY = 0.006          # 何もないときの, 1 日に風邪をひく割合
CARE_ITEMS = {               # 看病の品: 治りを早める時間 (時間)
    "sports_drink": 4, "jelly_drink": 4, "okayu": 5, "pudding": 2, "cold_medicine": 8,
}
CARE_LINES = {
    "care.arrived": "……{call}、来てくれたんですね。ごめんなさい、こんな格好で……",
    "care.got_wanted": "あ、{item}……ちゃんと買ってきてくれたんですね。ありがとうございます",
    "care.got_other": "{item}……わざわざ、ありがとうございます",
    "care.nursed": "……なんだか、少し楽になってきました。ありがとう",
}
CARE_SCENE_LABEL = {
    "care.arrived": "看病に来てくれた", "care.got_wanted": "頼んだ品を持ってきてくれた",
    "care.got_other": "看病の品を持ってきてくれた", "care.nursed": "看病してもらった",
}


class Care:
    def __init__(self, app):
        self.app = app

    def ill(self, st, now=None):
        il = st.get("ill")
        if il and (now or time.time()) < il["until"]:
            return il
        return None

    # ------------------------------------------------------------------ かかる・治る
    def tick(self, char, st, now, h):
        """時間の経過 (engine.tick). かかる / 治る / 看病に呼ぶか. 何か変わったら True."""
        app = self.app
        il = st.get("ill")
        if il and now >= il["until"]:
            st.pop("ill")
            if not il.get("called") and app.bonds.stage(char["id"]) in ("contact", "visit") and not il.get("seen"):
                app.life.add_reason(st, "event", "bad", "風邪で寝込んでいた", il["until"], told=False)
            return True
        if il:
            st["params"]["health"] = min(float(st["params"].get("health", 90)), 42.0 if il["level"] == 1 else 25.0)
            return False
        if h <= 0 or random.random() >= self.rate(char, st, now) * min(h, 24) / 24.0:
            return False
        weak, slow = self.frail(char)
        lv = 2 if random.random() < 0.35 * weak else 1
        days = (random.uniform(1.0, 2.5) if lv == 1 else random.uniform(2.0, 4.0)) / slow
        st["ill"] = {"level": lv, "t0": now, "until": now + days * 86400}
        st["params"]["health"] = min(float(st["params"].get("health", 90)), 42.0 if lv == 1 else 25.0)
        app.trace.add("care", "風邪をひいた (%s)" % ("寝込む" if lv == 2 else "具合が悪い"), char["id"], now, days=round(days, 1))
        return True                                     # (看病に呼ぶかは, 画面を開いているときに live_call で)

    def rate(self, char, st, now):
        p = st["params"]
        m = datetime.fromtimestamp(now).month
        f = 2.0 if m in (12, 1, 2) else 1.3 if m in (3, 11) else 0.7 if m in (7, 8) else 1.0
        f *= 1 + max(0.0, 40 - p.get("energy", 60)) / 40.0 + max(0.0, p.get("stress", 20) - 50) / 50.0
        return ILL_PER_DAY * f * self.frail(char)[0]

    def frail(self, char):
        """体の弱さ: 崩しやすさ (性格の hurt.health) と治りの速さ (drift_speed.health)."""
        tr = self.app.traits(char)
        return float((tr.get("hurt") or {}).get("health", 1)), float((tr.get("drift_speed") or {}).get("health", 1))

    # ------------------------------------------------------------------ 看病に呼ぶ
    def call_chance(self, char, st, lv):
        app = self.app
        cid = char["id"]
        if app.bonds.stage(cid) not in ("contact", "visit") or app.bonds.living():
            return 0.0                                  # (同居相手がいる / あなたと暮らしている: 呼ばなくても誰かいる)
        p = st["params"]
        tr = app.traits(char)
        base = 0.12 if lv == 1 else 0.45
        bond = max(0.0, (p.get("affection", 50) - 45) / 30.0) * max(0.3, (p.get("trust", 50) - 30) / 40.0)
        lean = 1 + 0.5 * app.attach.factor(char, st, "dependence")
        who = min(2.0, float(tr.get("approach", 1)) ** (2.5 if lv == 1 else 1.0)) * max(0.3, 1 - 0.05 * max(0, float(tr.get("modesty", 0))))
        return max(0.0, min(0.8, base * bond * lean * who))

    def live_call(self, cid, now):
        """画面を開いている間 (appoint.live): かかってからまだ考えていなければ, 看病に呼ぶか一度だけ考える."""
        app = self.app
        char, st = app.chars[cid], app.state(cid)
        il = self.ill(st, now)
        if not il or il.get("call_checked") or app.bonds.together(cid):
            return None
        il["call_checked"] = True
        x = self.maybe_call(char, st, now)
        app.save_state(cid)
        return x

    def maybe_call(self, char, st, now):
        """かかったときに一度: 看病に呼ぶか. 呼んだら約束 (急な誘いと同じ形) を返す."""
        app = self.app
        cid = char["id"]
        il = st["ill"]
        if app.appoint.open_with(cid) or random.random() >= self.call_chance(char, st, il["level"]):
            return None
        want = random.sample(sorted(CARE_ITEMS), random.choice((1, 1, 2))) if random.random() < 0.5 else []
        x = app.appoint.care_call(char, st, now, want)
        if x:
            il["called"] = x["id"]
        return x

    # ------------------------------------------------------------------ 来てくれた
    def arrive(self, cid, x, now):
        """看病の約束で相手の家に着いた: 相手の家に来ている状態 (with.care). 来てくれたこと自体がうれしい."""
        app = self.app
        char, st = app.chars[cid], app.state(cid)
        app.bonds.start(cid, "visit", now)
        w = app.bonds.with_rec()
        w["care"] = {"want": list(x.get("want") or []), "given": [], "nursed": False}
        app.bonds.save()
        il = self.ill(st, now)
        if il:
            il["seen"] = True
        eff, _ = app.bonds.realize(char, st, {"mood": 4, "trust": 2, "loneliness": -10}, "_care_come", now)
        d = app.apply_effects(st, app.trait_effects(char, eff))
        app.attach.give(char, st, "me", 3, "看病に来てくれた")
        app.presence.touch(now)
        app.solo.note("visit", "%sの看病に来た" % char.get("name", ""), now)
        return app.note_entry(char, st, now, "_care_arrive", "看病に来た", "🤒", self.line(char, "care.arrived", {}), d)

    def rec(self, cid=None):
        w = self.app.athome.rec(cid)
        return (w or {}).get("care")

    def give(self, cid, iid, now=None):
        """持ってきた品を渡す."""
        app = self.app
        now = now or time.time()
        cid = cid or (app.athome.rec() or {}).get("cid")
        with app.lock:
            c = self.rec(cid)
            if c is None:
                raise ValueError("いまは看病に来ていません")
            if iid not in CARE_ITEMS or app.items.count(iid) <= 0:
                raise ValueError("その品は持っていません")
            if iid in c["given"]:
                raise ValueError("それはもう渡しました")
            char, st = app.chars[cid], app.state(cid)
            app.items.add(iid, -1)
            c["given"].append(iid)
            app.bonds.save()
            wanted = iid in c["want"]
            eff, _ = app.bonds.realize(char, st, {"mood": 3, "affection": 2, "trust": 2} if wanted else {"mood": 2, "affection": 1},
                                       "_care_give", now)
            d = app.apply_effects(st, app.trait_effects(char, eff))
            self._quicken(st, CARE_ITEMS[iid], now)
            name = self._name(iid)
            e = app.note_entry(char, st, now, "_care_give", "看病の品を渡した", "🛍",
                               self.line(char, "care.got_wanted" if wanted else "care.got_other", {"item": name}), d)
            app.save_state(cid)
            return {"entry": e}

    def nursed(self, char, st, now):
        """看病した (nurse. 相手の家で一度): 治りが早まる."""
        c = self.rec(char["id"])
        if c is None or c.get("nursed") or not self.ill(st, now):
            return None
        c["nursed"] = True
        self.app.bonds.save()
        self._quicken(st, 6, now)
        return self.line(char, "care.nursed", {})

    def _quicken(self, st, hours, now):
        il = self.ill(st, now)
        if il:
            il["until"] = max(now + 3600, il["until"] - hours * 3600)

    # ------------------------------------------------------------------ 場面
    def sick_scene(self, char, st, base, t):
        """かかっている間: 予定の外出は休んで家で寝ている (寝ている時間はそのまま)."""
        il = self.ill(st, t)
        if not il or base.get("asleep"):
            return base
        lab = "寝込んでいる" if il["level"] == 2 else "具合が悪くて家で休んでいる"
        return dict(base, activity="sick", label=lab, location="自宅", away=False, busy=False, asleep=False, outing=False,
                    pos="sick, in bed, pajamas, under blanket, flushed face, fever", neg="smile")

    def view(self, cid, now=None):
        """相手の家の欄に出す: 頼まれた品・渡せる品 (持ち物にある看病の品)."""
        c = self.rec(cid)
        if c is None:
            return None
        app = self.app
        have = [{"id": i, "name": self._name(i), "wanted": i in c["want"]}
                for i in sorted(CARE_ITEMS) if app.items.count(i) > 0 and i not in c["given"]]
        return {"want": [self._name(i) for i in c["want"]], "have": have, "nursed": c.get("nursed", False)}

    def _name(self, iid):
        from .items import CATALOG
        return (CATALOG.get(iid) or {}).get("name", iid)

    def want_text(self, want):
        return "・".join(self._name(i) for i in want)

    def line(self, char, key, extra):
        app = self.app
        t = app.persona_text(char, key) or CARE_LINES[key]
        fp, _, call = app.pronouns(char)
        for k, v in dict(extra, fp=fp, call=call).items():
            t = t.replace("{%s}" % k, str(v))
        return t
