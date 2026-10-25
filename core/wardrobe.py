"""服の一覧 (全体で 1 つ) と, キャラの持っている服.

- 服の一覧 (data/outfits.json. 既定は defaults/outfits.json): 名前・アイコン・服装のプロンプト・大胆さ (bold: 0 ふつう〜3 かなり大胆)・
  外に着ていけるか・季節・種類・値段と売っている店・着られる条件 (when)・サンプル画像 (sample).
- キャラの定義の clothes: 持っている服 [{id, from (default / player / self), t, pos?, neg?}]. pos / neg はその人用の上書き
  (体型などで見え方を変えたいときだけ). 着せ替えの画面には持っている服だけが並ぶ.
- 服を増やす: 店で服を買ってプレゼントする (持ち物の "outfit:<id>". 受け取るかは大胆さ・仲・好みしだい) / 本人が自分で買う.
- 大胆な服を着てくれるか (accept): 好感度・信頼・間柄・性格の恥じらい (traits.modesty)・その日の機嫌・場所 (家の中か外か,
  ほかに人がいるか)・しつこさの組み合わせ. 仲が深くても断られることはあり, 断られたのに続けて頼むと怒る. 補正なし.
- 本人の服選び (self_pick): 頼まれていないときは, その日の気分・季節・天気・行き先・持っている服の好みで, 普段着や外出の服を
  自分で選ぶことがある (その日・その場面ごとに決まる). あなたが贈った服は, 仲しだいで選ばれやすい.
- 以前の形式 (キャラごとの wardrobe) は起動時に一覧へ移し, 元のキャラの持っている服にする (中身が同じものは 1 つに).
"""
import math
import os
import random
import time
import uuid

from . import items as items_mod
from . import outdoor as outdoor_mod
from . import store

KINDS = {"casual": "普段着", "lounge": "部屋着", "formal": "よそ行き", "work": "仕事着", "pajamas": "パジャマ",
         "swim": "水着", "costume": "衣装"}
SEASONS = {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"}
BOLD_LABEL = ("ふつう", "少し大胆", "大胆", "かなり大胆")
BOLD_NEED = (None, 12, 32, 52)        # 着てくれるのに要る気持ち (下の score) の目安
STAGE_BONUS = {"known": -10, "contact": 0, "visit": 8, "live": 15}
HOME_KINDS = ("casual", "lounge")     # 家で本人が選ぶ服
OUT_KINDS = ("casual", "formal")      # 出かけるときに本人が選ぶ服
STARTER = ("casual", "lounge", "pajamas")     # 新しい人が最初から持っている服
# サンプル画像のプロンプト. {outfit} がその服の服装のプロンプトに置き換わる (設定 images.sample_prompt で変えられる)
SAMPLE_PROMPT = ("{outfit}, black hair, straight hair, medium hair, black eyes, looking at viewer, expressionless, full body, "
                 "contrapposto, simple background, 1girl, solo, masterpiece, best quality, amazing quality")
FIELDS = ("id", "name", "icon", "kind", "bold", "outing_ok", "seasons", "price", "places", "when", "pos", "neg", "sample")


def _norm(o):
    o = dict(o)
    o["id"] = str(o.get("id") or "o" + uuid.uuid4().hex[:6])
    o.setdefault("name", o["id"])
    o.setdefault("icon", "👕")
    o["kind"] = o.get("kind") if o.get("kind") in KINDS else "casual"
    o["bold"] = max(0, min(3, int(o.get("bold") or 0)))
    o["outing_ok"] = bool(o.get("outing_ok"))
    o["seasons"] = [s for s in o.get("seasons") or [] if s in SEASONS]
    o["price"] = max(0, int(o.get("price") or 0))
    o["places"] = list(o.get("places") or ["mall"])
    for k in ("when", "pos", "neg"):
        o[k] = o.get(k) or ""
    return o


def _same(a, b):
    k = ("name", "pos", "neg", "when", "outing_ok")
    return all((a.get(x) or "") == (b.get(x) or "") for x in k)


class Wardrobe:
    def __init__(self, app):
        self.app = app
        self.items = None

    # ------------------------------------------------------------------ 服の一覧
    def path(self):
        return store.dpath("outfits.json")

    def load(self):
        items = store.load(self.path())
        if items is None:
            items = store.load(os.path.join(store.DEFAULTS, "outfits.json"), []) or []
            store.save(self.path(), items)
        self.items = [_norm(o) for o in items]
        self._register_shop()
        return self.items

    def all(self):
        return self.items if self.items is not None else self.load()

    def get(self, oid):
        return next((o for o in self.all() if o["id"] == oid), None)

    def save_all(self, items):
        """設定から一覧を保存する. id が重なれば断る. 持っている人がいる服を消しても, その人の持ち物からは外れるだけ."""
        out = [_norm(o) for o in items]
        ids = [o["id"] for o in out]
        if len(ids) != len(set(ids)):
            raise ValueError("服の id が重なっています")
        old = {o["id"]: o for o in self.all()}
        for o in out:                          # サンプル画像は画面の古い一覧で消さない
            if "sample" not in o and old.get(o["id"], {}).get("sample"):
                o["sample"] = old[o["id"]]["sample"]
        store.save(self.path(), out)
        self.items = out
        self._register_shop()
        return out

    def set_sample(self, oid, rel):
        items = store.load(self.path(), []) or []
        for o in items:
            if o.get("id") == oid:
                o["sample"] = rel
        store.save(self.path(), items)
        self.items = [_norm(o) for o in items]

    def sample_prompt(self, o):
        """サンプル画像のプロンプト: 共通 + サンプルのキャラ (服装のトークンは black hair の前) + 服装の Negative."""
        s = self.app.settings
        pr = s.get("prompt") or {}
        tmpl = ((s.get("images") or {}).get("sample_prompt") or SAMPLE_PROMPT)
        body = tmpl.replace("{outfit}", o.get("pos", "")) if "{outfit}" in tmpl else "%s, %s" % (o.get("pos", ""), tmpl)
        from .engine import join_tags
        return join_tags([pr.get("prefix_pos", ""), body]), join_tags([pr.get("prefix_neg", ""), o.get("neg", "")])

    def _register_shop(self):
        """値段のある服を, 店の品物 (持ち物の "outfit:<id>") として並べる. プレゼントにできる."""
        for k in [k for k in items_mod.CATALOG if k.startswith("outfit:")]:
            del items_mod.CATALOG[k]
        for o in self.items:
            if o["price"] > 0:
                items_mod.CATALOG["outfit:" + o["id"]] = {
                    "id": "outfit:" + o["id"], "name": o["name"], "icon": o["icon"], "kind": "outfit", "price": o["price"],
                    "places": o["places"], "tags": ["fashion"], "giftable": True, "essential": False,
                    "outfit": o["id"], "bold": o["bold"]}

    # ------------------------------------------------------------------ 持っている服
    @staticmethod
    def owned_ids(char):
        return [x.get("id") for x in char.get("clothes") or []]

    def owned(self, char):
        """その人が持っている服 (一覧の中身に, その人用の上書きを重ねたもの)."""
        out = []
        for x in char.get("clothes") or []:
            o = self.get(x.get("id"))
            if not o:
                continue
            o = dict(o, owned_from=x.get("from", "default"))
            for k in ("pos", "neg"):
                if (x.get(k) or "").strip():
                    o[k] = x[k]
            out.append(o)
        return out

    def item(self, char, oid):
        return next((o for o in self.owned(char) if o["id"] == oid), None)

    def give_to(self, char, oid, src, t=None):
        """持っている服に足す (定義は全体なので, 全ワールドで持っていることになる)."""
        if oid in self.owned_ids(char):
            return False
        c = store.all_characters().get(char["id"]) or char
        c.setdefault("clothes", []).append({"id": oid, "from": src, "t": t or time.time()})
        store.save_character(c)
        if char is not c:
            char["clothes"] = c["clothes"]
        return True

    # ------------------------------------------------------------------ 移行
    def migrate(self):
        """キャラごとの wardrobe を服の一覧へ移す (中身が同じものは 1 つに). 済んでいれば何もしない."""
        defs = store.all_characters()
        todo = [c for c in defs.values() if "wardrobe" in c]
        if not todo:
            return 0
        store.backup("着せ替えの服をキャラごとから服の一覧へ移す")
        items = self.all()
        for c in todo:
            mine = []
            for w in c.get("wardrobe") or []:
                hit = next((o for o in items if _same(o, w)), None)
                if not hit:
                    o = dict(w)
                    if self.get(o.get("id")) or not o.get("id"):
                        o["id"] = "o" + uuid.uuid4().hex[:6]
                    o.setdefault("bold", 0)
                    o.setdefault("price", 0)            # 自作の服は店には並べない (設定で値段を付ければ並ぶ)
                    hit = _norm(o)
                    items.append(hit)
                if hit["id"] not in [m["id"] for m in mine]:
                    mine.append({"id": hit["id"], "from": "default", "t": time.time()})
                old = w.get("id")
                if old != hit["id"]:            # 着替えている途中の服の id も付け替える (このワールドの状態だけ)
                    self._rename_dress(c["id"], old, hit["id"])
            c["clothes"] = mine
            c.pop("wardrobe", None)
            store.save_character(c)
        self.save_all(items)
        return len(todo)

    @staticmethod
    def _rename_dress(cid, old, new):
        for w in (store.load_worlds() or {}).get("worlds") or []:
            f = store.dpath("worlds", w["id"], "state", cid + ".json")
            st = store.load(f)
            if st and (st.get("dress") or {}).get("id") == old:
                st["dress"]["id"] = new
                store.save(f, st)

    # ------------------------------------------------------------------ 大胆な服を着てくれるか
    def modesty(self, char):
        return float(self.app.traits(char).get("modesty", 0))

    def accept(self, char, st, o, now, outside=False, others=0, record=True):
        """大胆な服を頼まれたときの気持ち: ok (ふつうの服) / eager (ノリノリ) / shy (照れながら) / reluctant (渋々) /
        refuse (断る) / angry (断ったのにしつこく頼まれて怒る)."""
        bold = int(o.get("bold") or 0)
        if bold <= 0:
            return "ok"
        p = st["params"]
        asks = [a for a in st.get("dress_asks") or [] if now - a["t"] < 2 * 3600]
        refused = sum(1 for a in asks if not a["ok"])
        need = BOLD_NEED[bold] + (12 * bold if outside else 0) + (6 * bold if others else 0)
        score = 0.5 * (p.get("affection", 40) - 40) + 0.4 * (p.get("trust", 40) - 40) \
            + STAGE_BONUS.get(self.app.bonds.stage(char["id"]), 0) + 0.3 * (p.get("mood", 50) - 50) \
            - self.modesty(char) * (1 + 0.3 * bold) - 12 * refused + random.uniform(-15, 15)
        if random.random() < 0.04 * bold:          # 仲が深くても, 今日はそういう気分じゃないこともある
            score = min(score, need - 13)
        if score >= need + 25:
            feel = "eager" if random.random() < 0.6 - self.modesty(char) / 25.0 else "shy"
        elif score >= need:
            feel = "shy"
        elif score >= need - 12:
            feel = "reluctant"
        else:
            feel = "angry" if refused >= 2 else "refuse"
        if record:
            st["dress_asks"] = (asks + [{"t": now, "ok": feel not in ("refuse", "angry"), "bold": bold}])[-10:]
        return feel

    def gift_feel(self, char, st, oid, now):
        """服を贈られたとき: yes (受け取る) / bold_no (大胆すぎて受け取れない). 着るのとは別で, 受け取るほうが少し易しい."""
        o = self.get(oid) or {}
        if int(o.get("bold") or 0) <= 0:
            return "yes"
        f = self.accept(char, st, dict(o, bold=max(1, int(o["bold"]) - 1)), now, record=False)
        return "bold_no" if f in ("refuse", "angry") else "yes"

    # ------------------------------------------------------------------ 本人の服選び
    def comfort(self, char, st):
        """本人が自分から着る服の大胆さの上限 (恥じらいと機嫌しだい)."""
        m = self.modesty(char)
        c = 1 if m <= 2 else 0
        if m <= -4 and st["params"].get("mood", 50) >= 60:
            c = 2
        return c

    def self_pick(self, char, st, dt, outing=False):
        """頼まれていないときに本人が選ぶ服 (無ければ予定どおりの服). その日・場面ごとに決まり, 見るたびには変わらない."""
        rng = random.Random("%s|%s|%s" % (char["id"], dt.date().isoformat(), "out" if outing else "home"))
        if rng.random() < 0.45:           # 今日はいつもの服
            return None
        season = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring", 6: "summer",
                  7: "summer", 8: "summer"}.get(dt.month, "autumn")
        rain = outdoor_mod.weather(dt)["id"] in ("rain", "snow")
        aff = st["params"].get("affection", 40)
        cap = self.comfort(char, st)
        cands, weights = [], []
        for o in self.owned(char):
            if o["kind"] not in (OUT_KINDS if outing else HOME_KINDS) or (outing and not o["outing_ok"]):
                continue
            if o["seasons"] and season not in o["seasons"]:
                continue
            if o["bold"] > cap or o.get("when"):
                continue
            w = 1.0
            if o.get("owned_from") == "player":          # 贈ってもらった服: 仲しだいで選びやすい (必ずではない)
                w *= max(0.5, min(2.5, 1 + (aff - 45) / 30.0))
            if outing and rain and o["kind"] == "formal":
                w *= 0.4
            cands.append(o)
            weights.append(w)
        if not cands:
            return None
        return rng.choices(cands, weights)[0]

    # ------------------------------------------------------------------ 本人が服を買う
    def step(self, char, st, t, h):
        """ときどき自分で服を買う (お金と好みしだい. 一日に一度ほど考えて, 買うのはまれ)."""
        likes = self.app.items.likes(char)[0]
        rate = 0.03 * (2.0 if "fashion" in likes else 1.0) * h / 24.0
        if random.random() >= 1 - math.exp(-rate):
            return None
        money = self.app.life.her_money(st)["a"]
        have = set(self.owned_ids(char))
        cap = self.comfort(char, st)
        cands = [o for o in self.all() if o["id"] not in have and 0 < o["price"] <= money * 0.3 and o["bold"] <= cap
                 and o["kind"] in ("casual", "formal", "lounge", "pajamas", "work") and not o.get("when")]
        if not cands:
            return None
        o = random.choice(cands)
        self.app.life.her_money(st)["a"] -= o["price"]
        self.give_to(char, o["id"], "self", t)
        return o

    # ------------------------------------------------------------------ 画面
    def catalog_view(self):
        return {"items": self.all(), "kinds": KINDS, "seasons": SEASONS, "bold": BOLD_LABEL,
                "sample_prompt": SAMPLE_PROMPT}

