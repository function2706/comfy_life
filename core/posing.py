"""ポーズと「見せて」: 頼む (コマンド _pose / _show)・相手からしてくる・持ちかけてくる (対価を求めることも)・好みの学習.

- 一覧 (data/poses.json. 既定は defaults/poses.json. 全体で 1 つ): {id, type: pose / show, name, icon, bold 0〜3, outside_ok, pos, neg,
  slot, group, with, silly, hand_ok}. 見せて は「〜 focus」の形のプロンプト. 既定は服を着たままの範囲で, 裸・性的な行為は入れない (設定から足せる).
- 組み合わせ (S44): 部位 slot は 姿勢 body (型 group: 立つ・座る・膝・うつ伏せ・仰向け・四つん這い)・手 hand・単独 whole (組み合わせない)・
  見せて show. 姿勢・手・見せるものから 1 つずつ (片方だけでもよい). 手と見せるものは, 組める姿勢の型を with に持つ. 見せるものに手を
  添えられるかは hand_ok. 大胆さは「いちばん大胆なもの + 0.5 × 残りの和」(combine). ポーズが大胆なときだけ, 着ている服の大胆さも同じ式に入れる.
  照れくささ silly 0〜2 (猫・うさぎ・ダブルピースなど. 肌は見せないが恥ずかしい) は大胆さとは別に, 性格の play (おどけへの平気さ −1〜+1) で効く.
  部位の無い項目は, 既定に同じ id があればその値を, 無ければ単独 (見せては姿勢と組めない) として読む (データは書き換えない).
- 大人のキャラだけ: 定義の age に 18 未満が入っている人には, 頼むことも相手からの行動も出さない. 未入力は (今までのキャラを
  使えなくしないよう) 大人として扱う. 判定は年齢の欄だけ (外見のタグ・性格・プロンプトの語からは推し量らない).
- 頼んだとき: 着てくれるかと同じ受け入れ (wardrobe.accept. 好感度・信頼・間柄・恥じらい・機嫌・場所・揺らぎ・しつこさ. pose_asks).
- 相手から (live): その気 (ドキドキ・好感度・機嫌・恥じらい) しだいで, 二人きりのときに, ポーズを取って見せる / 「見せてあげようか？」と
  持ちかけてくる. 持ちかけには対価 (お金・家事の肩代わり) を求めることがある (性格・仲・相手の懐しだい). 見せてきたら感想を選ぶ
  (褒める・照れる・もっと見たい・からかう・止める. 性格・機嫌・仲・揺らぎで良く/悪く効く).
- 好みの学習 (st["prefs"]): 頼んだもの・着せた服 (+), 感想の選び方 (褒める・もっと見たい +, 止める −) を覚える. 相手からの行動と
  本人の服選びが, 概してそちらに寄る (重みが変わるだけで, 確定しない).
"""
import math
import os
import random

from . import store

TYPES = {"pose": "ポーズ", "show": "見せて"}
SLOTS = {"body": "姿勢", "hand": "手", "whole": "単独", "show": "見せて"}
GROUPS = {"stand": "立つ", "sit": "座る", "kneel": "膝立ち・しゃがむ", "lie": "うつ伏せ・横向き", "back": "仰向け", "fours": "四つん這い"}
SILLY_LABEL = ("ふつう", "少し照れくさい", "照れくさい")
EXTRA = 0.5                   # 組み合わせの大胆さ: いちばん大胆なもの + EXTRA × 残りの和
# 以前の既定 (姿勢と手が 1 つに混ざっていた・猫とうさぎを大胆さで数えていた). 手を入れていなければ, 読むときに今の既定に直す (S44)
OLD_DEFAULT = {
    "head_rest": {"name": "頬杖", "pos": "head rest, sitting, looking at viewer", "bold": 0},
    "arms_behind_back": {"name": "後ろで手を組む", "pos": "arms behind back, leaning forward, looking at viewer", "bold": 0},
    "contrapposto": {"name": "モデル立ち", "pos": "contrapposto, hand on own hip, full body, looking at viewer", "bold": 0},
    "seiza": {"name": "正座", "pos": "seiza, hands on own knees, looking at viewer", "bold": 0},
    "paw_pose": {"name": "猫のポーズ", "pos": "paw pose, cat pose, smile, looking at viewer", "bold": 1},
    "rabbit_pose": {"name": "うさぎのポーズ", "pos": "rabbit pose, smile, looking at viewer", "bold": 1},
    "on_stomach": {"name": "うつ伏せで頬杖", "pos": "lying, on stomach, head rest, looking at viewer", "bold": 1},
    "on_side": {"name": "横向きに寝そべる", "pos": "lying, on side, head rest, looking at viewer", "bold": 2},
    "on_back": {"name": "仰向けで手を頭の後ろに", "pos": "lying, on back, hands behind head, looking at viewer", "bold": 2},
}
ADULT_AGE = 18
REACTIONS = [("praise", "「きれい」と褒める"), ("shy", "照れて目をそらす"), ("more", "「もっと見たい」と言う"),
             ("tease", "からかう"), ("stop", "「そういうのはいいよ」と止める")]
REACT_BASE = {"praise": 8, "shy": 4, "more": 2, "tease": -2, "stop": -10}
REACT_LEARN = {"praise": 1.5, "more": 2.5, "tease": 0.5, "shy": 0.5, "stop": -3.0}
EFFECT = {"good": {"heart": 6, "mood": 4, "affection": 1}, "neutral": {"heart": 2}, "bad": {"mood": -4, "shyness": 6, "trust": -1}}
WAIT_SEC = 15 * 60
RATE_PER_HOUR = 0.12          # 二人きりでいるとき, その気が満ちていれば 1 時間に 0.1 回ほど (その気しだいで 0〜)
# 共通のセリフ (性格プリセットに無ければ). {item} にポーズ・部位の名前, {amount} に額
LINES = {
    "pose.self.pose": "ねえ、見て見て。……{item}、どうですか？",
    "pose.self.show": "……ちょっとだけですよ。{item}、見てもいいです",
    "pose.offer.free": "ねえ、{call}。……{item}、見たいですか？",
    "pose.offer.money": "{item}、見せてあげてもいいですよ。……{amount}円で、どうですか？",
    "pose.offer.chore": "{item}、見せてあげてもいいです。そのかわり、今日の家事、代わりにやってくれます？",
    "pose.offer.declined_ok": "そうですか。……ふふ、ちょっとほっとしました",
    "pose.offer.declined_bad": "……そうですか。せっかく勇気出したのに",
    "pose.react.praise.good": "ほんとですか？ ……えへへ、うれしいです",
    "pose.react.praise.neutral": "……そうですか？ ありがとうございます",
    "pose.react.praise.bad": "……なんか、言わされてる感じがします",
    "pose.react.shy.good": "ふふ、{call}が照れてる。かわいいです",
    "pose.react.shy.neutral": "……え、なんで目をそらすんですか",
    "pose.react.shy.bad": "……そんなに見たくなかったですか",
    "pose.react.more.good": "もう、欲張りですね。……少しだけですよ",
    "pose.react.more.neutral": "……今日はここまでです",
    "pose.react.more.bad": "……そういうの、ちょっと引きます",
    "pose.react.tease.good": "もう、からかわないでください。……ふふ",
    "pose.react.tease.neutral": "……はいはい",
    "pose.react.tease.bad": "……恥ずかしいのに、そういうこと言うんですか",
    "pose.react.stop.good": "あ、はい。……ふふ、{call}って真面目ですね",
    "pose.react.stop.neutral": "……そうですか",
    "pose.react.stop.bad": "……せっかく見せたのに",
}
SCENE_LABEL = {
    "pose.self.pose": "相手から: ポーズを取って見せる ({item})", "pose.self.show": "相手から: 見せてくる ({item})",
    "pose.offer.free": "相手から: 見たい？と持ちかける", "pose.offer.money": "相手から: お金と引き換えに持ちかける ({amount})",
    "pose.offer.chore": "相手から: 家事の肩代わりと引き換えに持ちかける", "pose.offer.declined_ok": "持ちかけを断られた (気にしない)",
    "pose.offer.declined_bad": "持ちかけを断られた (がっかり)",
}
for _k, _l in REACTIONS:
    for _o, _ol in (("good", "よく効いた"), ("neutral", "ふつう"), ("bad", "よくなかった")):
        SCENE_LABEL["pose.react.%s.%s" % (_k, _o)] = "見せてくれたときの感想「%s」が%s" % (_l, _ol)


def adult(char):
    """大人か: 年齢が 18 未満と入っていなければ大人 (未入力は大人として扱う)."""
    age = char.get("age")
    if age in (None, ""):
        return True
    try:
        return int(float(age)) >= ADULT_AGE
    except (TypeError, ValueError):
        return True


def combine(vals):
    """組み合わせの大胆さ: いちばん大胆なもの + 0.5 × 残りの和 (0 同士は 0, 1 + 1 は 1.5)."""
    vals = [float(v) for v in vals if v]
    if not vals:
        return 0.0
    m = max(vals)
    return round(m + EXTRA * (sum(vals) - m), 2)


_DEFAULTS = {}


def _default(pid):
    if not _DEFAULTS:
        for d in store.load(os.path.join(store.DEFAULTS, "poses.json"), []) or []:
            _DEFAULTS[d.get("id")] = d
    return _DEFAULTS.get(pid) or {}


def _norm(o):
    o = dict(o)
    d = _default(o.get("id"))
    old = OLD_DEFAULT.get(o.get("id"))
    if old and d and all(o.get(k) == v for k, v in old.items()):
        o.update({k: d[k] for k in old})              # 既定のまま手を入れていない: 今の既定に (データは書き換えない)
    o["type"] = o.get("type") if o.get("type") in TYPES else "pose"
    o["bold"] = max(0, min(3, int(o.get("bold") or 0)))
    o["outside_ok"] = bool(o.get("outside_ok"))
    for k in ("name", "icon", "pos", "neg"):
        o[k] = o.get(k) or ""
    for k, v in (("slot", ""), ("group", ""), ("with", []), ("silly", 0), ("hand_ok", False)):
        if k not in o:
            o[k] = d.get(k, v) if d.get("type", "pose") == o["type"] else v
    if o["type"] == "show":
        o["slot"] = "show"
    elif o["slot"] not in SLOTS or o["slot"] == "show":
        o["slot"] = "whole"
    o["group"] = o["group"] if o["group"] in GROUPS and o["slot"] in ("body", "whole") else ""
    o["with"] = [g for g in o["with"] or [] if g in GROUPS] if o["slot"] in ("hand", "show") else []
    o["silly"] = max(0, min(2, int(o.get("silly") or 0)))
    o["hand_ok"] = bool(o["hand_ok"]) and o["slot"] == "show"
    return o


def _join(texts):
    out = []
    for t in texts:
        for w in (t or "").split(","):
            w = w.strip()
            if w and w not in out:
                out.append(w)
    return ", ".join(out)


class Posing:
    def __init__(self, app):
        self.app = app
        self.items = None

    # ------------------------------------------------------------------ 一覧
    def load(self):
        items = store.sync_list_defaults("poses.json")       # 既定に後から増えたものも足す (消したものは戻さない)
        self.items = [_norm(o) for o in items]
        return self.items

    def all(self, typ=None):
        items = self.items if self.items is not None else self.load()
        return [o for o in items if not typ or o["type"] == typ]

    def get(self, pid):
        return next((o for o in self.all() if o.get("id") == pid), None)

    def save_all(self, items):
        out = [_norm(o) for o in items]
        ids = [o.get("id") for o in out]
        if not all(ids) or len(ids) != len(set(ids)):
            raise ValueError("ポーズ・見せての id が空か、重なっています")
        store.save(store.dpath("poses.json"), out)
        self.items = out
        return out

    def catalog_view(self):
        return {"items": self.all(), "types": TYPES, "slots": SLOTS, "groups": GROUPS, "silly": SILLY_LABEL}

    def combo(self, ids, typ):
        """頼むものの組み合わせ (姿勢・手・見せるものから 1 つずつ). 無いもの・種類違いは KeyError, 合わない組み合わせは ValueError.
        返すのは 1 つのポーズと同じ形 (name・pos・neg・bold・silly・outside_ok) + parts."""
        ids = [ids] if isinstance(ids, str) else [i for i in ids or [] if i]
        if not ids:
            raise KeyError("ポーズ・見せるものを選んでください")
        parts = []
        for i in ids:
            o = self.get(i)
            if not o:
                raise KeyError("ポーズ・見せるものが見つかりません: %s" % i)
            parts.append(o)
        by = {}
        for o in parts:
            if o["slot"] in by:
                raise ValueError("同じ部位（%s）から 2 つは選べません" % SLOTS[o["slot"]])
            by[o["slot"]] = o
        if (typ == "show") != ("show" in by):
            raise KeyError("ポーズ・見せるものが見つかりません: %s" % ",".join(ids))
        w = by.get("whole")
        if w and len(parts) > 1:
            raise ValueError("「%s」はほかと組み合わせられません" % w["name"])
        b, h, s = by.get("body"), by.get("hand"), by.get("show")
        for x in (h, s):
            if b and x and b["group"] not in x["with"]:
                raise ValueError("「%s」と「%s」は組み合わせられません" % (b["name"], x["name"]))
        if s and h and not s["hand_ok"]:
            raise ValueError("「%s」に手のポーズは添えられません" % s["name"])
        order = [o for o in (s, b, h, w) if o]
        if s:
            name = s["name"] + ("（%s）" % "・".join(o["name"] for o in (b, h) if o) if b or h else "")
        else:
            name = "・".join(o["name"] for o in order)
        return {"id": "+".join(o["id"] for o in order), "type": typ, "name": name, "icon": order[0]["icon"],
                "pos": _join(o["pos"] for o in order), "neg": _join(o["neg"] for o in order),
                "bold": combine(o["bold"] for o in order), "silly": max(o["silly"] for o in order),
                "outside_ok": all(o["outside_ok"] for o in order), "parts": order}

    def clothes_bold(self, char, st, outing=False):
        """いま着ている服の大胆さ (ポーズの判定に入れる分). 部品の組み合わせなら, 描かれる部品から同じ式で (一式はその服の大胆さ)."""
        W = self.app.wardrobe
        d = st.get("dress") or {}
        if d.get("coord"):
            return combine(o["bold"] for o in W.drawn(W.coord_items(char, d["coord"]), outing))
        return float((W.worn(char, st, outing) or {}).get("bold") or 0)

    @staticmethod
    def with_clothes(bold, clothes_bold):
        """服の大胆さも入れた大胆さ. ポーズが大胆でなければ 0 のまま (大胆な服を着ていても, ピースはふつうに頼める)."""
        return combine([bold, clothes_bold]) if bold > 0 else 0.0

    def play(self, char):
        """おどけへの平気さ (−1 嫌がる〜+1 平気. 性格の traits の play. 無ければ 0)."""
        return max(-1.0, min(1.0, float(self.app.traits(char).get("play", 0) or 0)))

    # ------------------------------------------------------------------ 好み
    @staticmethod
    def learn(st, key, amount):
        prefs = st.setdefault("prefs", {})
        prefs[key] = round(max(-10.0, min(10.0, prefs.get(key, 0.0) + amount)), 2)

    @staticmethod
    def pref(st, key):
        return float((st.get("prefs") or {}).get(key, 0.0))

    # ------------------------------------------------------------------ 状況
    def outside(self, cid):
        """外にいるか. 同居相手と出かけている間も外 (一緒にいる形は home のままなので, engine.outside_with で見る)."""
        return self.app.bonds.mode(cid) not in ("home", "guest", "visit") or self.app.outside_with(cid)

    def can(self, char, st, now):
        """頼める・相手からしてくるか (理由). 大人だけ, 起きていて手が空いていて, そばにいるとき."""
        if not adult(char):
            return False, "18 歳未満のキャラにはできません"
        if not self.app.bonds.together(char["id"]):
            return False, "そばにいるときだけです"
        return True, ""

    def view(self, char, st, now):
        ok, why = self.can(char, st, now)
        out = self.outside(char["id"])
        items = [dict(o, here=(not out or o["outside_ok"])) for o in self.all()]
        return {"can": ok, "why": why, "items": items, "outside": out, "clothes_bold": self.clothes_bold(char, st, out) if ok else 0,
                "groups": GROUPS}

    # ------------------------------------------------------------------ 相手から
    def eagerness(self, char, st):
        p = st["params"]
        m = self.app.wardrobe.modesty(char)
        f = 0.2 + (p.get("heart", 0) - 20) / 60.0 + (p.get("affection", 40) - 55) / 80.0 + (p.get("mood", 50) - 50) / 150.0 - m / 20.0
        return max(0.0, min(1.5, f))

    def pick(self, char, st, rng=random):
        """相手が自分から選ぶポーズ・部位 (自分から出せる大胆さまで. 覚えた好みに寄る)."""
        cap = self.app.wardrobe.comfort(char, st) + (1 if st["params"].get("heart", 0) >= 50 else 0)
        out = self.outside(char["id"])
        play = self.play(char)               # 照れくさいものは, おどけが平気な人ほど自分からもする
        cands = [o for o in self.all() if o["bold"] <= cap and (not out or o["outside_ok"]) and o["silly"] * (1 - play) <= 1]
        if not cands:
            return None
        w = [max(0.2, 1.0 + 0.6 * self.pref(st, "%s:%s" % (o["type"], o["id"]))) for o in cands]
        return rng.choices(cands, w)[0]

    def price(self, char, st, o, rng=random):
        """持ちかけるときの対価 (無いことが多い). お金に困っているほど・仲が浅いほど・お金をあまり気にしない性格ほど求めやすい."""
        p = st["params"]
        her = self.app.life.her_money(st)["a"]
        tr = float(self.app.traits(char).get("money", 0))
        chance = 0.12 + (0.25 if her < 5000 else 0.1 if her < 15000 else 0.0) - (p.get("affection", 40) - 50) / 250.0 - tr / 60.0
        if rng.random() >= max(0.02, min(0.6, chance)):
            return None
        if rng.random() < 0.6:
            amt = (800 + 1200 * o["bold"]) * rng.uniform(0.7, 1.4) * (1.5 if her < 5000 else 1.0)
            return {"kind": "money", "amount": int(round(amt, -2))}
        return {"kind": "chore", "amount": 0}

    def live(self, char, st, now, rng=random):
        """二人きりのとき, その気しだいで, 相手からポーズを取る・見せる・持ちかける. 返事待ちが切れたら片付ける."""
        off = st.get("pose_offer")
        if off and now >= off["until"]:
            st["pose_offer"] = None
            self.app.apply_effects(st, {"mood": -1})
            return None
        if off or st.get("approach") or st.get("game"):
            return None
        last = st.get("pose_check") or now
        st["pose_check"] = now
        dt_h = min(max(now - last, 0), 600) / 3600.0
        ok, _ = self.can(char, st, now)
        if not dt_h or not ok or not self.app.bonds.alone_with(char["id"]):
            return None
        if self.app.presence.at(now) not in ("here", "idle"):
            return None
        rate = RATE_PER_HOUR * self.eagerness(char, st)
        if rng.random() >= 1 - math.exp(-rate * dt_h):
            return None
        o = self.pick(char, st, rng)
        if not o:
            return None
        if rng.random() < 0.6:
            return self.perform(char, st, o, now, key="pose.self." + o["type"])
        pr = self.price(char, st, o, rng)
        key = "pose.offer." + (pr["kind"] if pr else "free")
        e = self._entry(char, st, now, key, o, {"amount": format((pr or {}).get("amount", 0), ",")}, image=False)
        st["pose_offer"] = {"kind": "offer", "item": o["id"], "price": pr, "t": now, "until": now + WAIT_SEC, "entry": e["id"]}
        return e

    def perform(self, char, st, o, now, key):
        """相手がポーズを取る・見せる (画像あり). 感想を待つ."""
        e = self._entry(char, st, now, key, o, {}, image=True)
        st["pose_offer"] = {"kind": "did", "item": o["id"], "t": now, "until": now + WAIT_SEC, "entry": e["id"]}
        return e

    def _entry(self, char, st, now, key, o, extra, image):
        from datetime import datetime
        app = self.app
        d = datetime.fromtimestamp(now)
        text = app.persona_text(char, key) or LINES[key]
        for k, v in dict(extra, item=o["name"]).items():
            text = text.replace("{%s}" % k, str(v))
        scene = app.scene_at(char, st, d)
        text = app.format_text(text, char, scene, d)
        act = {"id": "_pose_self", "name": "%s（%s）" % (TYPES[o["type"]], o["name"]), "icon": o["icon"] or "📸",
               "pos": o["pos"] if image else "", "neg": o["neg"] if image else ""}
        pos, neg, parts = app.build_prompt(char, st, d, act if image else None)
        e = app._new_entry(char["id"], now, act, text, {}, scene, d, pos, neg, parts)
        if image and app.settings.get("auto_generate"):
            e["job"] = app._present_image(char["id"], e)
        st["last_auto"] = {"id": e["id"], "t": now}
        app.save_log(char["id"])
        return e

    def pending_view(self, char, st):
        off = st.get("pose_offer")
        if not off:
            return None
        o = self.get(off["item"]) or {"name": off["item"], "icon": "📸"}
        if off["kind"] == "did":
            choices = [{"id": k, "label": l} for k, l in REACTIONS]
            label = "%sを見せてくれた（感想は？）" % o["name"]
        else:
            pr = off.get("price") or {}
            yes = "見せてもらう" if not pr else ("%s円払って見せてもらう" % format(pr["amount"], ",")) if pr["kind"] == "money" \
                else "家事を代わりにやって見せてもらう"
            choices = [{"id": "yes", "label": yes}, {"id": "no", "label": "いまはいい"}]
            label = "「%s」を見せてくれるって" % o["name"]
        return {"id": "_pose", "entry": off.get("entry"), "until": off["until"], "label": label, "icon": o.get("icon") or "📸",
                "apart": False, "accept": "", "later": "何も言わない", "choices": choices}

    # ------------------------------------------------------------------ 答える
    def judge(self, char, st, choice, rng=random):
        p = st["params"]
        m = self.app.wardrobe.modesty(char)
        taste = ({"praise": 6, "shy": 6, "more": -8, "tease": -8, "stop": 2} if m >= 5 else
                 {"more": 8, "tease": 4, "praise": 2, "stop": -10} if m <= -3 else {"praise": 4, "stop": -6})
        score = REACT_BASE[choice] + taste.get(choice, 0) + 0.25 * (p.get("mood", 50) - 50) + 0.3 * (p.get("affection", 45) - 45) \
            + rng.uniform(-15, 15)
        res = "good" if score >= 10 else "neutral" if score >= -8 else "bad"
        if res == "good" and rng.random() < 0.1:         # 合う感想でも, それほど響かないこともある
            res = "neutral"
        return res

    def answer(self, char, st, choice, now, rng=random):
        """感想を選ぶ (did) / 持ちかけに答える (offer: yes / no). later は何も言わない (そのまま流れる)."""
        off = st.get("pose_offer")
        if not off:
            raise ValueError("いまは何も持ちかけられていません")
        o = self.get(off["item"]) or {"id": off["item"], "type": "pose", "name": off["item"], "bold": 0, "pos": "", "neg": "", "icon": ""}
        key_pref = "%s:%s" % (o["type"], o["id"])
        app = self.app
        if choice == "later":
            st["pose_offer"] = None
            app.apply_effects(st, {"mood": -1})
            return None
        if off["kind"] == "offer":
            if choice == "yes":
                pr = off.get("price")
                if pr and pr["kind"] == "money":
                    if app.life.player_state()["money"] < pr["amount"]:
                        raise ValueError("お金が足りません（%s円）" % format(pr["amount"], ","))
                    app.life.move(st, dp=-pr["amount"], da=pr["amount"], cat="social", note="%sに" % char.get("name", ""))
                elif pr and pr["kind"] == "chore":
                    app.life.tire(10)                    # あなたが代わりに家事をした
                    app.home.clean(25)
                st["pose_offer"] = None
                self.learn(st, key_pref, 1.0)
                return self.perform(char, st, o, now, key="pose.self." + o["type"])
            st["pose_offer"] = None
            m = app.wardrobe.modesty(char)
            hurt = (-1 if off.get("price") else -4 if m <= 0 else -2) * rng.uniform(0.5, 1.3)
            eff, _ = app.bonds.realize(char, st, {"mood": hurt}, "_pose_offer", now)
            deltas = app.apply_effects(st, app.trait_effects(char, eff))
            key = "pose.offer.declined_bad" if deltas.get("mood", 0) <= -2 else "pose.offer.declined_ok"
            e = self._entry(char, st, now, key, o, {}, image=False)
            e["deltas"] = deltas
            app.save_log(char["id"])
            return e
        if choice not in REACT_BASE:
            raise ValueError("感想の選び方が違います")
        st["pose_offer"] = None
        res = self.judge(char, st, choice, rng)
        eff, _ = app.bonds.realize(char, st, dict(EFFECT[res]), "_pose_react", now)
        app.bonds.touch(st, now)
        deltas = app.apply_effects(st, app.trait_effects(char, eff))
        self.learn(st, key_pref, REACT_LEARN[choice])
        key = "pose.react.%s.%s" % (choice, res)
        e = self._entry(char, st, now, key, o, {}, image=False)
        e["deltas"], e["reply"] = deltas, {"kind": choice, "result": res}
        app.save_log(char["id"])
        return e
