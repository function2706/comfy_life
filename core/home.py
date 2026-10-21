"""あなたの家の状態 (data/worlds/<id>/home.json).

- 散らかり・洗い物・洗濯物・ゴミ (それぞれ 0〜100. 0 = 片付いている). 暮らしているうちに少しずつたまる
  (家にいて起きている間がいちばん, 寝ている・出かけている間はほとんど. 同居相手がいれば早い. 料理をすれば洗い物, 来客のあとは散らかる).
- 家事 (一人の時間) と「一緒に掃除」で片付く. 洗剤があるとはかどる.
- 家に招いた相手は, 来たときの家の様子に反応する. 同居相手は, 日々の家の様子に反応する (一日に一度ほど, 気づいたときだけ).
  反応は性格しだい: きれい好き (traits.neat) ほど散らかりを気にし, 片付いていれば好印象を持ちやすい. 世話焼き (traits.carer) ほど,
  散らかっていると片付けを手伝い出す. 気にしない人もいる.
- 現実的であること: 片付いていても必ず好印象になるわけではない (気づかないこともある). 散らかっていても気にしない人もいる.
"""
import random
import time
from datetime import datetime

from . import store

PARTS = (("mess", "部屋の散らかり", 0.4), ("dishes", "洗い物", 0.2), ("laundry", "洗濯物", 0.2), ("trash", "ゴミ", 0.2))
PART_LABEL = {k: n for k, n, _ in PARTS}
# 家にいて起きている間の, 1 時間あたりのたまり方
RATE = {"mess": 0.45, "dishes": 0.9, "laundry": 0.5, "trash": 0.35}
WORDS = {
    "mess": ["片付いている", "少し物が出ている", "物が出しっぱなし", "足の踏み場が少ない", "足の踏み場もない"],
    "dishes": ["洗い物はない", "少したまっている", "流しにたまっている", "流しにあふれている", "流しが山になっている"],
    "laundry": ["洗濯物はない", "少したまっている", "かごにたまっている", "かごからあふれている", "着る服がなくなりそう"],
    "trash": ["ゴミはない", "少したまっている", "ゴミ箱がいっぱい", "ゴミ袋が並んでいる", "ゴミ袋が山になっている"],
}
LEVELS = ((15, "きれいに片付いている"), (35, "まあまあ片付いている"), (55, "少し散らかっている"), (75, "散らかっている"),
          (101, "かなり散らかっている"))

# 共通のセリフ (性格プリセットに無ければ)
LINES = {
    "home.guest_clean": "きれいにしてるんですね。ちょっと見直しちゃいました。",
    "home.guest_messy_mind": "……ちょっと散らかってますね。人を呼ぶなら、片付けておいてほしかったです。",
    "home.guest_messy_ok": "散らかってても平気ですよ。{call}らしくて、ほっとします。",
    "home.guest_messy_help": "あの……ちょっとだけ、片付けてもいいですか？ 気になっちゃって。",
    "home.live_clean": "最近、お部屋がきれいで気持ちいいですね。",
    "home.live_messy": "{call}、ちょっと散らかってきましたよ？ そろそろ片付けましょう。",
    "home.live_messy_help": "散らかってたので、少し片付けておきました。",
}
SCENE_LABEL = {
    "home.guest_clean": "招いた相手 / 片付いていて好印象", "home.guest_messy_mind": "招いた相手 / 散らかっていて気にする",
    "home.guest_messy_ok": "招いた相手 / 散らかっていても気にしない", "home.guest_messy_help": "招いた相手 / 散らかっていて片付けを手伝い出す",
    "home.live_clean": "同居相手 / 片付いていて気持ちいい", "home.live_messy": "同居相手 / 散らかっていて気にする",
    "home.live_messy_help": "同居相手 / 散らかっていたので片付けてくれた",
}


def level_of(score):
    for i, (hi, label) in enumerate(LEVELS):
        if score < hi:
            return i, label
    return len(LEVELS) - 1, LEVELS[-1][1]


class Home:
    def __init__(self, app):
        self.app = app
        self._rec = None
        self._wid = None
        self.last_key = None      # いちばん最近の反応の場面 (home.<場面>)

    # ------------------------------------------------------------------ 記録
    def rec(self):
        if self._rec is None or self._wid != store.WORLD:
            r = store.load(store.wpath("home.json"), None) or {}
            for k, _, _ in PARTS:
                r.setdefault(k, 10.0)
            r.setdefault("last_t", time.time())
            r.setdefault("live_seen", {})
            self._rec, self._wid = r, store.WORLD
        return self._rec

    def save(self):
        store.save(store.wpath("home.json"), self.rec())

    def score(self):
        r = self.rec()
        return round(sum(float(r[k]) * w for k, _, w in PARTS), 1)

    def add(self, **amounts):
        r = self.rec()
        for k, v in amounts.items():
            r[k] = max(0.0, min(100.0, float(r[k]) + float(v)))
        self.save()

    # ------------------------------------------------------------------ 時間とともにたまる
    def tick(self, now=None):
        now = now or time.time()
        r = self.rec()
        t = max(float(r.get("last_t", now)), now - 14 * 86400)
        if now - t < 600:
            return
        live = self.app.bonds.living()
        step = 1800.0
        while t < now:
            seg = min(step, now - t)
            mode = self.app.presence.at(t + seg / 2)
            # 画面を閉じている間 (gone) は, 家にいたり出かけていたり. ならして半分ほど
            f = 0.05 if mode in ("work", "out") else 0.15 if mode == "sleep" else 0.5 if mode == "gone" else 1.0
            if live:
                f += 0.6           # 同居相手も暮らしている
            if self.app.bonds.with_rec() and (self.app.bonds.with_rec() or {}).get("mode") == "guest":
                f += 0.5           # 来客中
            for k, _, _ in PARTS:
                r[k] = min(100.0, float(r[k]) + RATE[k] * f * seg / 3600.0 * random.uniform(0.7, 1.3))
            t += seg
        r["last_t"] = now
        self.save()

    # ------------------------------------------------------------------ 片付ける
    def clean(self, power):
        """片付ける (power = 片付く量の合計). たまっているものほど多く片付く. (前の目安, 後の目安) を返す."""
        r = self.rec()
        before = self.score()
        total = sum(float(r[k]) for k, _, _ in PARTS) or 1.0
        for k, _, _ in PARTS:
            r[k] = max(0.0, float(r[k]) - power * float(r[k]) / total)
        self.save()
        return before, self.score()

    def chores(self, h, soap, jit):
        """一人の時間の家事 (h 時間). 片付き具合の説明を返す."""
        before, after = self.clean(100.0 * h * (1.0 if soap else 0.55) * jit)
        return "家は「%s」→「%s」" % (level_of(before)[1], level_of(after)[1])

    # ------------------------------------------------------------------ 性格
    def _attitude(self, char):
        """散らかっているのを見たときの受け止め方: mind (気にする) / ok (気にしない) / help (片付けを手伝い出す)."""
        tr = self.app.traits(char)
        neat, carer = float(tr.get("neat", 0)), float(tr.get("carer", 0.2))
        w = {"mind": 1.0 + max(0.0, neat) / 3.0, "ok": 1.0 + max(0.0, -neat) / 3.0, "help": carer * 3.0}
        return random.choices(list(w), list(w.values()))[0]

    def _line(self, char, key):
        self.last_key = key
        return self.app.persona_text(char, key) or LINES[key]

    # ------------------------------------------------------------------ 招いた相手が来たとき
    def on_guest(self, char, st, now):
        """家に招いた相手が, 家の様子に反応する. (セリフ or None, 効果) を返す."""
        app = self.app
        neat = float(app.traits(char).get("neat", 0))
        s = self.score()
        key, eff = None, {}
        if s < 25:
            if random.random() < 0.45 + neat / 40.0:          # 片付いていても, 気づかない・何とも思わないことはある
                key, eff = "home.guest_clean", {"mood": random.uniform(2, 5), "affection": random.uniform(0.5, 2), "trust": random.uniform(0, 1)}
        elif s >= 50 or (s >= 35 and neat >= 4 and random.random() < 0.4):
            att = self._attitude(char)
            if att == "mind":
                k = 1 + max(0.0, neat) / 10.0
                key, eff = "home.guest_messy_mind", {"mood": -random.uniform(2, 5) * k, "affection": -random.uniform(0, 1.5) * k}
                app.life.add_reason(st, "player", "bad", "%sの家が散らかっていた" % app.pronouns(char)[2], now, told=True,
                                    delta=eff["mood"], action="_home")
            elif att == "help":
                key, eff = "home.guest_messy_help", {"energy": -5, "trust": random.uniform(0, 1.5)}
                self.clean(random.uniform(15, 30))
            else:
                key, eff = "home.guest_messy_ok", {"stress": -random.uniform(0, 3)}
        if not key:
            return None, {}
        eff, _ = app.bonds.realize(char, st, eff, "_home", now)
        return self._line(char, key), eff

    def guest_left(self):
        self.add(mess=random.uniform(3, 8), dishes=random.uniform(3, 8))      # 来客のあとは少し散らかる

    # ------------------------------------------------------------------ 同居相手 (日々の家の様子)
    def live_check(self, char, st, now):
        """同居相手が, 日々の家の様子に反応する (一日に一度ほど, 気づいたときだけ). (セリフ or None, 効果) を返す."""
        app = self.app
        r = self.rec()
        cid = char["id"]
        if now - float(r["live_seen"].get(cid, 0)) < 20 * 3600 or random.random() > 0.35:
            return None, {}
        r["live_seen"][cid] = now
        self.save()
        neat = float(app.traits(char).get("neat", 0))
        s = self.score()
        key, eff = None, {}
        if s < 20 and random.random() < 0.4 + neat / 40.0:
            key, eff = "home.live_clean", {"mood": random.uniform(1, 3), "stress": -random.uniform(1, 3)}
        elif s >= 55:
            att = self._attitude(char)
            if att == "mind":
                k = 1 + max(0.0, neat) / 10.0
                key, eff = "home.live_messy", {"mood": -random.uniform(1, 4) * k, "stress": random.uniform(1, 4) * k}
                app.life.add_reason(st, "player", "bad", "家が散らかっている", now, told=True, delta=eff["mood"], action="_home")
            elif att == "help":
                key, eff = "home.live_messy_help", {"energy": -6}
                self.clean(random.uniform(20, 35))
        if not key:
            return None, {}
        return self._line(char, key), eff

    def notice_chores(self, h, soap, now, jit):
        """一人で家事をした: 同居相手が気づけば機嫌が上がる (気づくかどうかは偶然). 添える説明 or ""."""
        app, L = self.app, self.app.life
        live = app.bonds.living()
        if not live or h < 0.25 or random.random() >= (0.6 if soap else 0.3):
            return ""
        st, char = app.state(live), app.char(live)
        neat = float(app.traits(char).get("neat", 0))
        d = app.apply_effects(st, {"mood": round(min(4.0, 1.5 * h) * jit * (1 + max(0.0, neat) / 20.0), 1), "stress": -round(min(5.0, 2 * h), 1)})
        L.add_reason(st, "player", "good", "%sが家事をしてくれた" % app.pronouns(char)[2], now, told=True,
                     delta=d.get("mood", 0), action="_chores")
        app.save_state(live)
        return "。%sが気づいてくれたようだ" % char.get("name", "")

    # ------------------------------------------------------------------ 表示
    def view(self):
        r = self.rec()
        s = self.score()
        lv, label = level_of(s)
        parts = []
        for k, name, _ in PARTS:
            v = float(r[k])
            parts.append({"id": k, "label": name, "value": round(v, 1), "word": WORDS[k][min(4, int(v // 20))]})
        worst = max(parts, key=lambda p: p["value"])
        return {"score": s, "level": lv, "label": label, "parts": parts,
                "hint": ("%sが気になる" % worst["label"]) if worst["value"] >= 40 else "",
                "at": datetime.now().strftime("%H:%M")}
