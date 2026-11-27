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
- アウター (kind = outer): 一式ではなく, 外でいまの服の上に羽織るもの. 着せ替えには並ばない. 出かけるとき, 季節が合えば本人が
  羽織っていくことがある (outer_pick). 一緒の買い物で買ってあげたものは, その場で「いま着てみて」と聞ける (tryon_feel.
  受け取ってくれても, 季節・気分しだいで「帰ってから」になる. 聞けるのは一度だけ)
- 以前の形式 (キャラごとの wardrobe) は起動時に一覧へ移し, 元のキャラの持っている服にする (中身が同じものは 1 つに).
- 部品 (S30): 服は区分 slot (SLOTS) を持つ. set (一式. いまの服とコスプレ・水着など) は着ると outer 以外を覆う. 部品の pos に {color} が
  あれば色違いで売る (COLORS. 品の鍵は "<id>:<色>", 持ち物は "outfit:<鍵>"). 部品の組み合わせ (コーデ) は st.dress = {coord: {区分: 鍵}}
  (アクセサリーは 3 つまで: 鍵 acc・acc2・acc3. S37).
  靴は外にいるときだけ, ランジェリーはトップスもワンピースも無いときだけ描く. 大胆さは描かれる部品のいちばん大胆なもの.
- 文の服装の色を固定する (resolve): いつもの服・予定の服装・一式の pos の中の部品の名前に, その人の色を付けて描く (毎回同じ色).
  いつもの服とお出かけ着の文から見つかった部品は, その色でその人の持っている服になる (seed_usual).
- 服の好み (S36): 服に tags (系統 STYLES・種類 TYPES). キャラの定義の fashion = {styles, colors, bad_colors, types, fuss}
  (default_fashion で性格・年齢・暮らしから毎回同じに決まる初期値). fit で合う度を出し, 本人が選ぶ・買う・贈られたとき・着てみてに
  確率で効かせる (必ず喜ぶ道は作らない). 値は遊ぶ画面に出さない (設定のキャラクターの「服の好み」だけ).
"""
import hashlib
import os
import re
import datetime
import math
import random
import time
import uuid

from . import items as items_mod
from . import outdoor as outdoor_mod
from . import season as season_mod
from . import store

KINDS = {"casual": "普段着", "lounge": "部屋着", "formal": "よそ行き", "work": "仕事着", "pajamas": "パジャマ",
         "swim": "水着", "costume": "衣装", "outer": "アウター", "part": "部品"}
# 区分: 描く順. onepiece は top と bottom を兼ねる. set (一式) は outer 以外を覆う
SLOTS = {"hat": "ハット", "top": "トップス", "onepiece": "ワンピース", "bottom": "ボトムス", "legwear": "ソックス・タイツ",
         "shoes": "靴", "acc": "アクセサリー", "lingerie": "ランジェリー", "outer": "アウター", "set": "一式"}
COORD_SLOTS = ("hat", "top", "onepiece", "bottom", "legwear", "shoes", "acc", "lingerie")
# コーデの鍵 (S37): アクセサリーは 3 つまで (acc・acc2・acc3. どれも区分は acc). ほかの鍵は区分と同じ
ACC_KEYS = ("acc", "acc2", "acc3")
COORD_KEYS = ("hat", "top", "onepiece", "bottom", "legwear", "shoes") + ACC_KEYS + ("lingerie",)


def key_slot(k):
    """コーデの鍵 → 区分 (acc2・acc3 は acc)."""
    return "acc" if k in ACC_KEYS else k


def pack_coord(parts):
    """部品の並び → コーデ {鍵: 品の鍵}. アクセサリーは acc・acc2・acc3 に順に詰める (同じ品は 1 つ. 4 つ目からは入れない)."""
    out, accs = {}, []
    for o in parts:
        if o["slot"] == "acc":
            if o["key"] not in accs and len(accs) < len(ACC_KEYS):
                accs.append(o["key"])
        else:
            out[o["slot"]] = o["key"]
    out.update(zip(ACC_KEYS, accs))
    return out
# 色 (固定): id: (日本語, 英語のタグ, 無彩色か)
COLORS = {"white": ("白", "white", True), "black": ("黒", "black", True), "grey": ("グレー", "grey", True),
          "navy": ("紺", "navy blue", True), "blue": ("青", "blue", False), "light_blue": ("水色", "light blue", False),
          "red": ("赤", "red", False), "pink": ("ピンク", "pink", False), "yellow": ("黄", "yellow", False),
          "green": ("緑", "green", False), "khaki": ("カーキ", "khaki", True), "beige": ("ベージュ", "beige", True),
          "brown": ("茶", "brown", True), "purple": ("紫", "purple", False)}
# 画面の色の見本 (S35)
HEX = {"white": "#f4f4f2", "black": "#222222", "grey": "#9a9a9a", "navy": "#1f2a52", "blue": "#2f6fd6", "light_blue": "#8fd0f0",
       "red": "#d23a3a", "pink": "#f29bc0", "yellow": "#f2d33c", "green": "#3f9b4f", "khaki": "#a69a6a", "beige": "#e2d3b0",
       "brown": "#7a4f2e", "purple": "#8a55b8"}
# サンプル画像で, 部品 1 つのときに足す無地の既定 (S35. 区分 -> その区分が無いときに足すもの)
SAMPLE_FILL = (("top", "plain grey t-shirt"), ("bottom", "plain black long pants"))
# 文の中の色の語 (これがあれば色を足さない)
COLOR_WORDS = re.compile(r"\b(white|black|gr[ae]y|navy|blue|red|pink|yellow|green|khaki|beige|brown|purple|ivory|cream|"
                         r"orange|gold|golden|silver|denim|pastel|lavender|burgundy|camel|olive|mint|multicolored|rainbow)\b", re.I)
OUTER = "outer"                       # 上に羽織るもの (コート・ジャケット). 着せ替えの一式ではなく, いまの服の上に重ねる
BASE_WARMTH = 2.3                     # 服の暖かさが文から分からないときの見積もり (トップス + ボトムス + 靴 + 靴下ほど. S38)
TRYON_MIN = 60                        # 買ってもらったアウターを「いま着てみて」と頼める時間 (分)
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
FIELDS = ("id", "name", "icon", "kind", "slot", "bold", "outing_ok", "seasons", "price", "places", "when", "pos", "neg", "colors",
          "match", "tags", "sample")

# ---- 服の好み (S36)
STYLES = {"casual": "カジュアル", "girly": "ガーリー", "elegant": "きれいめ", "street": "ストリート", "natural": "ナチュラル",
          "mode": "モード", "sporty": "スポーティ", "jirai": "地雷系"}
TYPES = {"skirt": "スカート", "pants": "パンツ", "mini": "ミニ丈", "long": "ロング丈", "boots": "ブーツ", "sneakers": "スニーカー",
         "heels": "ヒール"}
# こだわりの部位 (区分 → 部位. ワンピースはトップスと同じ)
FUSS_PART = {"hat": "hat", "top": "top", "onepiece": "top", "bottom": "bottom", "legwear": "legwear", "shoes": "shoes", "acc": "acc",
             "outer": "outer"}
FUSS_LABEL = {"hat": "ハット", "top": "トップス・ワンピース", "bottom": "ボトムス", "legwear": "ソックス・タイツ", "shoes": "靴",
              "acc": "アクセサリー", "outer": "アウター"}
FUSS_MUL = {0: 0.3, 1: 1.0, 2: 1.6}
# 性格ごとの系統 (1 つ目は必ず, 2 つ目は寄せる)
PERSONA_STYLE = {
    "teinei": ("elegant", "natural"), "amaenbo": ("girly", "jirai"), "aneki": ("elegant", "mode"), "boyish": ("sporty", "street"),
    "cool": ("mode", "elegant"), "genki": ("casual", "sporty"), "jimuteki": ("elegant", "casual"), "kedakai": ("elegant", "mode"),
    "mukuchi": ("natural", "casual"), "ojousama": ("elegant", "girly"), "osananajimi": ("casual", "girly"),
    "otokomae": ("street", "sporty"), "ottori": ("natural", "girly"), "tenshin": ("girly", "casual"), "tsundere": ("girly", "street"),
    "uchiki": ("natural", "girly"), "sadist": ("mode", "jirai"), "itazura": ("street", "casual"), "hikutsu": ("casual", "natural"),
    "byoujaku": ("natural", "elegant"), "hitonatsukko": ("casual", "girly"), "fushigi": ("natural", "jirai"),
    "rikejo": ("casual", "mode"), "shikkari": ("elegant", "casual"), "yareyare": ("casual", "street"),
    "rakuten": ("casual", "sporty"), "seijitsu": ("elegant", "natural")}
STYLE_COLORS = {"casual": ("white", "navy", "grey", "blue", "beige"), "girly": ("pink", "white", "light_blue", "beige", "red"),
                "elegant": ("white", "beige", "navy", "black", "grey"), "street": ("black", "khaki", "grey", "red", "yellow"),
                "natural": ("beige", "brown", "khaki", "green", "white"), "mode": ("black", "white", "grey", "navy", "purple"),
                "sporty": ("blue", "white", "black", "yellow", "green", "red"), "jirai": ("black", "pink", "white", "purple", "red")}
STYLE_TYPES = {"casual": {"pants": 1, "sneakers": 1}, "girly": {"skirt": 1}, "elegant": {"heels": 1},
               "street": {"pants": 1, "sneakers": 1}, "natural": {"long": 1, "heels": -1}, "mode": {"boots": 1},
               "sporty": {"sneakers": 1, "pants": 1, "heels": -1}, "jirai": {"mini": 1, "skirt": 1, "sneakers": -1}}


def _age(char):
    try:
        return int(char.get("age"))
    except (TypeError, ValueError):
        return None


def default_fashion(char):
    """服の好みの初期値 (キャラ id・性格・年齢・暮らし・好きなものから. 毎回同じ)."""
    pid = char.get("persona_id") or ""
    rng = random.Random(int(hashlib.md5(("%s|%s|fashion" % (char.get("id", ""), pid)).encode("utf-8")).hexdigest()[:8], 16))
    first, second = PERSONA_STYLE.get(pid, ("casual", "natural"))
    styles = [first]
    if rng.random() < 0.6:
        age, life = _age(char), (char.get("life") or {}).get("type")
        w = {k: (8.0 if k == second else 1.0) for k in STYLES if k != first}
        if "elegant" in w and ((age is not None and age >= 30) or life == "office"):
            w["elegant"] *= 2
        if age is not None and age <= 20:
            for k in ("girly", "street"):
                if k in w:
                    w[k] *= 2
        ks = sorted(w)
        styles.append(rng.choices(ks, [w[k] for k in ks])[0])
    pal = []
    for s in styles:
        pal += [c for c in STYLE_COLORS[s] if c not in pal]
    colors = []
    for _ in range(rng.choice((1, 2, 2, 3))):
        colors.append(rng.choice([c for c in pal if c not in colors]))
    out_pal = [c for c in COLORS if c not in pal and not COLORS[c][2]]
    bad = rng.sample(out_pal, min(len(out_pal), rng.choice((0, 1, 1, 2))))
    types = {}
    for s in styles:
        for t, v in STYLE_TYPES[s].items():
            types[t] = types.get(t, 0) + v
    types = {t: (1 if v > 0 else -1) for t, v in types.items() if v}
    if rng.random() < 0.3:                    # ひとつ, 系統と関係ない好き嫌い
        types.setdefault(rng.choice(sorted(TYPES)), rng.choice((1, -1)))
    dl, dd = items_mod.PERSONA_LIKES.get(pid, ([], []))
    likes = char.get("likes") if char.get("likes") is not None else dl
    dislikes = char.get("dislikes") if char.get("dislikes") is not None else dd
    fuss = {}
    for _ in range(2 if "fashion" in (likes or []) else 1):
        fuss[rng.choice([x for x in ("shoes", "top", "bottom", "acc") if x not in fuss])] = 2
    lo = [x for x in ("hat", "legwear", "acc", "outer") if x not in fuss]
    for p in rng.sample(lo, 2 if "fashion" in (dislikes or []) else rng.choice((1, 2))):
        fuss[p] = 0
    return {"styles": styles, "colors": colors, "bad_colors": bad, "types": types, "fuss": fuss}


def _int(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def norm_fashion(f):
    """服の好みを確かめる (知らない語は捨てる・数の上限・好きな色と苦手な色は重ねない)."""
    f = f if isinstance(f, dict) else {}
    colors = [c for c in f.get("colors") or [] if c in COLORS][:3]
    return {"styles": [s for s in f.get("styles") or [] if s in STYLES][:2], "colors": colors,
            "bad_colors": [c for c in f.get("bad_colors") or [] if c in COLORS and c not in colors][:2],
            "types": {t: (1 if _int(v) > 0 else -1) for t, v in (f.get("types") or {}).items() if t in TYPES and _int(v)},
            "fuss": {p: (2 if _int(v, 1) >= 2 else 0) for p, v in (f.get("fuss") or {}).items() if p in FUSS_LABEL and _int(v, 1) != 1}}


def fashion_of(char):
    """キャラの服の好み (定義に無ければ初期値)."""
    f = char.get("fashion")
    return norm_fashion(f) if isinstance(f, dict) else default_fashion(char)


def fuss_of(char, slot):
    """その区分へのこだわり: 0 どうでもいい / 1 ふつう / 2 こだわる (一式・ランジェリーは 1)."""
    p = FUSS_PART.get(slot)
    return int(fashion_of(char)["fuss"].get(p, 1)) if p else 1


def fit(char, o, color=None):
    """その服がその人の好みに合う度 (-1〜+1 に切ってから, こだわる部位は ×1.6, どうでもいい部位は ×0.3).
    color: 色 (省くと o の色. "" で色を見ない)."""
    f = fashion_of(char)
    tags = o.get("tags") or []
    x = 0.0
    st = [t for t in tags if t in STYLES]
    if st and f["styles"]:
        x += 0.5 if any(t in f["styles"] for t in st) else -0.2
    x += sum(0.4 * f["types"].get(t, 0) for t in tags if t in TYPES)
    color = o.get("color") if color is None else color
    if color and color in f["colors"]:
        x += 0.4
    elif color and color in f["bad_colors"]:
        x -= 0.6
    return max(-1.0, min(1.0, x)) * FUSS_MUL[fuss_of(char, o.get("slot"))]


def migrate_fashion():
    """服の好みの無いキャラの定義に, 初期値を一度だけ書く (S36). 書いた数を返す."""
    n = 0
    for c in store.all_characters().values():
        if "fashion" not in c:
            store.save_character(c)           # save_character が初期値を書く
            n += 1
    return n


_DEF_TAGS = {}


def _default_tags():
    """既定の服の一覧の id → tags (S36 より前の一覧でタグの無い服を補う)."""
    if not _DEF_TAGS:
        for o in store.load(os.path.join(store.DEFAULTS, "outfits.json"), []) or []:
            _DEF_TAGS[o.get("id")] = list(o.get("tags") or [])
    return _DEF_TAGS


def _norm(o):
    o = dict(o)
    o["id"] = str(o.get("id") or "o" + uuid.uuid4().hex[:6])
    o.setdefault("name", o["id"])
    o.setdefault("icon", "👕")
    o["kind"] = o.get("kind") if o.get("kind") in KINDS else "casual"
    slot = o.get("slot")
    if slot not in SLOTS:                     # 区分の無い服 (以前の形): アウターは outer, ほかは一式
        slot = "outer" if o["kind"] == OUTER else ("top" if o["kind"] == "part" else "set")
    o["slot"] = slot
    if slot == "outer":
        o["kind"] = OUTER
    elif slot != "set":
        o["kind"] = "part"
    elif o["kind"] == "part":
        o["kind"] = "casual"
    o["colors"] = [c for c in o.get("colors") or [] if c in COLORS]
    o["match"] = [str(m).strip().lower() for m in o.get("match") or [] if str(m).strip()]
    tags = o.get("tags")
    if tags is None:                          # タグの無い服 (S36 より前の一覧): 既定の同じ id のタグで補う (データは書き換えない)
        tags = _default_tags().get(o["id"]) or []
    o["tags"] = [t for t in tags if t in STYLES or t in TYPES]
    o["bold"] = max(0, min(3, int(o.get("bold") or 0)))
    o["outing_ok"] = bool(o.get("outing_ok"))
    o["seasons"] = [s for s in o.get("seasons") or [] if s in SEASONS]
    o["price"] = max(0, int(o.get("price") or 0))
    o["places"] = list(o.get("places") or ["mall"])
    for k in ("when", "pos", "neg"):
        o[k] = o.get(k) or ""
    return o


def colored(o):
    """色違いで売る服か ({color} を含む)."""
    return "{color}" in (o.get("pos") or "")


def sell_colors(o):
    return (o.get("colors") or list(COLORS)) if colored(o) else []


def split_key(key):
    """品の鍵 "<id>:<色>" → (id, 色). 色の無い服は (id, None)."""
    key = str(key or "")
    if ":" in key:
        i, c = key.rsplit(":", 1)
        if c in COLORS:
            return i, c
    return key, None


def key_of(oid, color=None):
    return "%s:%s" % (oid, color) if color else oid


def paint(o, color):
    """服の一覧の 1 着に色を付けたもの (鍵・名前・pos)."""
    if not colored(o):
        return dict(o, key=o["id"], color=None)
    color = color if color in sell_colors(o) else sell_colors(o)[0]
    return dict(o, key=key_of(o["id"], color), color=color, base_name=o["name"],
                name="%s（%s）" % (o["name"], COLORS[color][0]), pos=o["pos"].replace("{color}", COLORS[color][1]))


def _base_tags(o):
    """文の中でこの部品とみなす語 (pos から {color} を抜いたもの + 別名)."""
    if o["slot"] in ("set", "outer", "lingerie") or not colored(o):
        return []
    first = o["pos"].split(",")[0].replace("{color}", "").strip().lower()
    return [t for t in [first] + o["match"] if t]


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
        items = store.sync_list_defaults("outfits.json")     # 既定に後から増えた服も足す (消したものは戻さない)
        items = self._resync_shops(items)
        self.items = [_norm(o) for o in items]
        self._register_shop()
        return self.items

    SHOPS_MARK = "outfits.json.shops"

    def _resync_shops(self, items):
        """服屋の多様化 (1.8.0beta) を, いまの服の一覧へ一度だけ当てる: 既定にある服で, 売っている店が以前の既定の形
        (モールと商店街だけ) のままのものを, 新しい既定の店に. 店を自分で変えた服・自作の服は触らない. 当てたら印を残す."""
        mark = store.dpath(self.SHOPS_MARK)
        if os.path.exists(mark):
            return items
        dmap = {d.get("id"): d for d in store.load(os.path.join(store.DEFAULTS, "outfits.json"), []) or []}
        n = 0
        for o in items:
            d, pl = dmap.get(o.get("id")), list(o.get("places") or ["mall"])
            if d and "mall" in pl and set(pl) <= {"mall", "shopping_street"} and pl != d.get("places"):
                o["places"] = list(d.get("places") or ["mall"])
                n += 1
        if n:
            store.save(self.path(), items)
        store.save(mark, {"t": time.time(), "n": n})
        return items

    def all(self):
        return self.items if self.items is not None else self.load()

    def get(self, oid):
        """服の一覧の 1 着 (id で. 色の付いた鍵なら, その色を付けたもの)."""
        i, c = split_key(oid)
        o = next((o for o in self.all() if o["id"] == i), None)
        if o and c:
            return paint(o, c) if colored(o) else None
        return o

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
        pos = o.get("pos", "").replace("{color}", "white")        # 色違いの部品は白で描く
        sl = o.get("slot")
        if sl not in ("set", "outer", "lingerie", "onepiece"):   # 部品 1 つ: ほかは無地の既定で (上か下が無いと裸に描かれる)
            pos = ", ".join([pos] + [f for k, f in SAMPLE_FILL if k != sl])
        body = tmpl.replace("{outfit}", pos) if "{outfit}" in tmpl else "%s, %s" % (pos, tmpl)
        from .engine import join_tags
        return join_tags([pr.get("prefix_pos", ""), body]), join_tags([pr.get("prefix_neg", ""), o.get("neg", "")])

    def _register_shop(self):
        """値段のある服を, 店の品物 (持ち物の "outfit:<id>") として並べる. プレゼントにできる."""
        for k in [k for k in items_mod.CATALOG if k.startswith("outfit:")]:
            del items_mod.CATALOG[k]
        for o in self.items:
            if o["price"] <= 0:
                continue
            for v in [paint(o, c) for c in sell_colors(o)] or [dict(o, key=o["id"], color=None)]:   # 色違いは色ごとに 1 品
                items_mod.CATALOG["outfit:" + v["key"]] = {
                    "id": "outfit:" + v["key"], "name": v["name"], "icon": o["icon"], "kind": "outfit", "price": o["price"],
                    "places": o["places"], "tags": ["fashion"], "giftable": True, "essential": False,
                    "outfit": v["key"], "bold": o["bold"], "slot": o["slot"], "okind": o["kind"], "color": v["color"],
                    "variant_of": "outfit:" + o["id"] if v["color"] else None, "base_name": o["name"],
                    "otags": o["tags"], "seasons": o["seasons"]}      # 服の棚の絞り込み (S37)

    # ------------------------------------------------------------------ 持っている服
    @staticmethod
    def owned_ids(char):
        """持っている服の鍵 (色違いの部品は "<id>:<色>")."""
        return [key_of(x.get("id"), x.get("color")) for x in char.get("clothes") or []]

    def owned(self, char):
        """その人が持っている服 (一覧の中身に, その人用の上書きを重ねたもの. 色違いの部品は色を付けて. key が鍵)."""
        out = []
        for x in char.get("clothes") or []:
            o = next((o for o in self.all() if o["id"] == x.get("id")), None)
            if not o:
                continue
            o = paint(o, x.get("color") or self._color(char, o))
            o = dict(o, owned_from=x.get("from", "default"), owned_t=x.get("t") or 0)
            for k in ("pos", "neg"):
                if (x.get(k) or "").strip():
                    o[k] = x[k]
            out.append(o)
        return out

    def item(self, char, key):
        """持っている服 (鍵で. 色違いの部品で色の無い鍵なら, 持っている最初の色)."""
        own = self.owned(char)
        return next((o for o in own if o["key"] == key), None) or next((o for o in own if o["id"] == key), None)

    def give_to(self, char, key, src, t=None):
        """持っている服に足す (定義は全体なので, 全ワールドで持っていることになる). key は鍵 (色違いの部品は "<id>:<色>")."""
        if key in self.owned_ids(char):
            return False
        oid, color = split_key(key)
        c = store.all_characters().get(char["id"]) or char
        x = {"id": oid, "from": src, "t": t or time.time()}
        if color:
            x["color"] = color
        c.setdefault("clothes", []).append(x)
        store.save_character(c)
        if char is not c:
            char["clothes"] = c["clothes"]
        return True

    # ------------------------------------------------------------------ 部品の組み合わせ (コーデ) と色
    @staticmethod
    def _color(char, o, rng=None, near=(), pref=None):
        """その人のその部品の色 (持っていなければ, キャラ id と部品から毎回同じに決まる. 無彩色に寄せる).
        near: 一緒に着る部品の色 (違う有彩色どうしは選ばれにくい). pref: 服の好み (本人が買うときだけ. 好きな色 ×3・苦手 ×0.15.
        描く色の既定は変えない)."""
        cs = sell_colors(o)
        if not cs:
            return None
        if rng is None:
            h = int(hashlib.md5(("%s|%s" % (char.get("id", ""), o["id"])).encode("utf-8")).hexdigest()[:8], 16)
            rng = random.Random(h)
        w = []
        for c in cs:
            x = 2.0 if COLORS[c][2] else 1.0
            if pref:
                x *= 3.0 if c in pref["colors"] else 0.15 if c in pref["bad_colors"] else 1.0
            for b in near:
                x *= Wardrobe._match(c, b)
            w.append(x)
        return rng.choices(cs, w)[0]

    def own_color(self, char, oid):
        """その人が持っているその部品の色 (最初に手に入れたもの). 持っていなければ None."""
        return next((x.get("color") for x in char.get("clothes") or [] if x.get("id") == oid and x.get("color")), None)

    def _parts_index(self):
        out = []
        for o in self.all():
            for t in _base_tags(o):
                out.append((t, re.compile(r"(?<![\w-])%s(?![\w-])" % re.escape(t), re.I), o))
        out.sort(key=lambda x: -len(x[0]))
        return out

    def find_parts(self, text):
        """文を , で区切り, 部品の名前を含むかけらを探す: [(かけら, 部品 or None)]."""
        idx = self._parts_index()
        out = []
        for tok in [t.strip() for t in (text or "").split(",")]:
            if not tok:
                continue
            hit = next((o for _, rx, o in idx if rx.search(tok)), None)
            out.append((tok, hit))
        return out

    def resolve(self, char, text):
        """文の服装の中の部品に, その人の色を付ける (色の語があるかけらはそのまま). 描くたびに色が変わらないように."""
        if not text or not char:
            return text or ""
        out = []
        for tok, o in self.find_parts(text):
            if o and not COLOR_WORDS.search(tok):
                c = self.own_color(char, o["id"]) or self._color(char, o)
                tok = "%s %s" % (COLORS[c][1], tok)
            out.append(tok)
        return ", ".join(out)

    def seed_usual(self, char):
        """いつもの服・お出かけ着の文に出てくる部品を, その色でその人の持っている服にする (文ごとに一度だけ). 足した数を返す."""
        texts = [char.get("outfit_default") or "", char.get("outfit_outing") or ""]
        seen = list(char.get("usual_seen") or [])
        todo = [t for t in texts if t and t not in seen]
        if not todo:
            return 0
        n = 0
        have = {x.get("id") for x in char.get("clothes") or []}
        for t in todo:
            near = []
            for tok, o in self.find_parts(t):
                if not o:
                    continue
                if o["id"] in have:
                    near.append(self.own_color(char, o["id"]))
                    continue
                m = COLOR_WORDS.search(tok)
                c = next((k for k, v in COLORS.items() if m and m.group(1).lower() in (k, v[1].split()[0])), None)
                if c not in sell_colors(o):
                    c = self._color(char, o, near=[x for x in near if x])
                near.append(c)
                # 時刻は付けない (最初から持っている服と同じ. 別の PC で同じ人を読み込んでも同じ定義になるように)
                char.setdefault("clothes", []).append({"id": o["id"], "color": c, "from": "default"})
                have.add(o["id"])
                n += 1
        char["usual_seen"] = (seen + todo)[-6:]
        store.save_character(char)
        return n

    def coord_items(self, char, coord):
        """コーデ {区分: 鍵} を, 持っている服の並び (区分の順) に. 持っていない・区分の合わないものは除く."""
        out = []
        for k in COORD_KEYS:
            key = (coord or {}).get(k)
            o = self.item(char, key) if key else None
            if o and o["slot"] == key_slot(k) and o["key"] not in [x["key"] for x in out]:
                out.append(o)
        if any(o["slot"] == "onepiece" for o in out):
            out = [o for o in out if o["slot"] not in ("top", "bottom")]
        return out

    @staticmethod
    def drawn(parts, outing):
        """描く部品: 靴は外にいるときだけ, ランジェリーはトップスもワンピースも無いときだけ."""
        covered = any(o["slot"] in ("top", "onepiece") for o in parts)
        return [o for o in parts if not (o["slot"] == "shoes" and not outing) and not (o["slot"] == "lingerie" and covered)]

    def coord_bold(self, char, coord, outing=False):
        """コーデの大胆さ: 描かれる部品のいちばん大胆なもの."""
        return max([o["bold"] for o in self.drawn(self.coord_items(char, coord), outing)] or [0])

    def coord_view(self, char, coord, outing=False):
        """コーデを, 一式の服と同じ形の 1 着に (pos・名前・大胆さ・外に着ていけるか)."""
        parts = self.coord_items(char, coord)
        d = self.drawn(parts, outing)
        top = any(o["slot"] in ("top", "onepiece") for o in parts)
        low = any(o["slot"] in ("bottom", "onepiece") for o in parts)
        worn = [o for o in parts if not (o["slot"] == "lingerie" and top)]       # 上に着ていれば下着は外から見えない
        return {"id": "coord", "key": "coord", "slot": "coord", "kind": "coord", "icon": "👚",
                "name": "・".join(o["name"] for o in parts if o["slot"] != "lingerie" or not top) or "（何も着ていない）",
                "pos": ", ".join(o["pos"] for o in d), "neg": ", ".join(o["neg"] for o in d if o.get("neg")),
                "bold": max([o["bold"] for o in d] or [0]), "when": "", "seasons": [],
                "warmth": season_mod.total(d),            # 重ね着の暖かさ (S38)
                "outing_ok": top and low and all(o["outing_ok"] for o in worn),
                "coord": pack_coord(parts)}

    def norm_coord(self, char, coord):
        """画面から来たコーデを確かめる (持っている・区分が合う). 合わなければ ValueError."""
        if not isinstance(coord, dict):
            raise ValueError("組み合わせの形が違います")
        parts = []
        for k in COORD_KEYS:                     # 鍵の順に見る (アクセサリーは acc → acc2 → acc3)
            key = coord.get(k)
            if not key:
                continue
            o = self.item(char, key)
            if not o or o["slot"] != key_slot(k):
                raise KeyError("服が見つかりません: %s" % key)
            parts.append(o)
        bad = [k for k, v in coord.items() if v and k not in COORD_KEYS]
        if bad:
            raise ValueError("その区分は組み合わせに入れられません: %s" % bad[0])
        out = pack_coord(parts)                   # 同じアクセサリーの重なりを除き, acc から詰める
        if not out:
            raise ValueError("服を選んでください")
        if "onepiece" in out:
            out.pop("top", None)
            out.pop("bottom", None)
        return out

    def worn(self, char, st, outing=False):
        """いま着せている服 (st.dress. 一式なら持っている 1 着, コーデなら coord_view). 無ければ None."""
        d = st.get("dress") or {}
        if d.get("coord"):
            v = self.coord_view(char, d["coord"], outing)
            return v if v["pos"] else None
        return self.item(char, d.get("id")) if d.get("id") else None

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

    def accept(self, char, st, o, now, outside=False, others=0, record=True, asks_key="dress_asks"):
        """大胆な服 (やポーズ・見せて) を頼まれたときの気持ち: ok (ふつう) / eager (ノリノリ) / shy (照れながら) / reluctant (渋々) /
        refuse (断る) / angry (断ったのにしつこく頼まれて怒る). しつこさは asks_key ごとに覚える."""
        bold = int(o.get("bold") or 0)
        if bold <= 0:
            return "ok"
        p = st["params"]
        asks = [a for a in st.get(asks_key) or [] if now - a["t"] < 2 * 3600]
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
            st[asks_key] = (asks + [{"t": now, "ok": feel not in ("refuse", "angry"), "bold": bold}])[-10:]
        return feel

    def gift_feel(self, char, st, oid, now, rnd=random):
        """服を贈られたとき: bold_no (大胆すぎて受け取れない. 着るのとは別で, 受け取るほうが少し易しい) /
        plain (どうでもいい部位: 受け取るが喜びは小さい) / love (好みに合って喜ぶ) / meh (好みに合わず微妙) /
        fussy (こだわる部位で好みに合わず, そう言う) / yes. 好みは確率で効くだけ (合っても必ず love ではない)."""
        o = self.get(oid) or {}
        if int(o.get("bold") or 0) > 0:
            f = self.accept(char, st, dict(o, bold=max(1, int(o["bold"]) - 1)), now, record=False)
            if f in ("refuse", "angry"):
                return "bold_no"
        if not o:
            return "yes"
        fs = fuss_of(char, o.get("slot"))
        if fs == 0:
            return "plain"
        x = fit(char, o)
        if x >= 0.35 and rnd.random() < min(0.8, 0.3 + 0.5 * x):
            return "love"
        if x <= -0.35 and rnd.random() < min(0.85, 0.3 - 0.4 * x):
            return "fussy" if fs == 2 else "meh"
        return "yes"

    # ------------------------------------------------------------------ 本人の服選び
    def temp_feel(self, char, o, dt):
        """家の中で着替えを頼まれたとき, 寒すぎる服か (cold / ""). 外が 15℃ 未満の時期に, ずれが −2.5 より寒い側で,
        寒いほど断りやすい (S38. 暖かい時期の家の中では, 薄着でも寒いとは言わない)."""
        t = season_mod.temp(dt)
        d = season_mod.gap(self.app, char, season_mod.warmth(o or {}), t, inside=True)
        if t >= 15 or d > -2.5:
            return ""
        return "cold" if random.random() < min(0.85, 0.2 * (-d - 2.0)) else ""

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
        season = self.season(dt)
        rain = outdoor_mod.weather(dt)["id"] in ("rain", "snow")
        t = season_mod.temp(dt)
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
            x = fit(char, o)
            w = math.exp(0.8 * x)                         # 本人の好み (S36)
            if o.get("owned_from") == "player" and x >= -0.3:   # 贈ってもらった服: 仲しだいで選びやすい (好みに外れたものは着ない)
                w *= max(0.5, min(2.5, 1 + (aff - 45) / 30.0))
            if outing and rain and o["kind"] == "formal":
                w *= 0.4
            w *= max(0.3, 1.0 + 0.15 * float((st.get("prefs") or {}).get("outfit:" + o["id"], 0.0)))     # あなたの好み (着せた服)
            w *= season_mod.fit_weight(self.temp_gap(char, o, dt, outing, t))         # その時の気温 (S38)
            cands.append(o)
            weights.append(w)
        cos, seen = [], set()
        for _ in range(4):                # 持っている部品から組んだコーデも候補に (4 通り組んで, 気温に合うものを選びやすく)
            co = self._pick_coord(char, st, rng, season, outing, cap, aff)
            if not co:
                break
            k = tuple(sorted(co["coord"].items()))
            if k not in seen:
                seen.add(k)
                cos.append(co)
        for co in cos:                    # 合わせて一式 1 着と同じ重み
            cands.append(co)
            weights.append(season_mod.fit_weight(self.temp_gap(char, co, dt, outing, t)) / len(cos))
        if not cands:
            return None
        return rng.choices(cands, weights)[0]

    @staticmethod
    def _match(a, b):
        """色の合わせ: 無彩色はどれとも合う・同じ色は合う. 違う有彩色どうしは合いにくい."""
        if not a or not b or a == b or COLORS[a][2] or COLORS[b][2]:
            return 1.0
        return 0.3

    def _pick_coord(self, char, st, rng, season, outing, cap, aff):
        """持っている部品から本人が組むコーデ (トップス + ボトムス か ワンピース. 外なら靴. ときどきソックス・ハット・アクセサリー).
        組めなければ None."""
        prefs = st.get("prefs") or {}
        by = {}
        for o in self.owned(char):
            if o["slot"] not in COORD_SLOTS or o["slot"] == "lingerie" or o["bold"] > cap or o.get("when"):
                continue
            if o["seasons"] and season not in o["seasons"]:
                continue
            if outing and not o["outing_ok"]:
                continue
            by.setdefault(o["slot"], []).append(o)

        def pick(slot, base=None):
            xs = by.get(slot) or []
            if not xs:
                return None
            w = []
            for o in xs:
                fx = fit(char, o)
                x = math.exp(0.8 * fx)
                if o.get("owned_from") == "player" and fx >= -0.3:
                    x *= max(0.5, min(2.5, 1 + (aff - 45) / 30.0))
                x *= max(0.3, 1.0 + 0.15 * float(prefs.get("outfit:" + o["key"], 0.0)))
                for b in base or []:
                    x *= self._match(o.get("color"), b.get("color"))
                w.append(x)
            return rng.choices(xs, w)[0]
        two = bool(by.get("top") and by.get("bottom"))
        if by.get("onepiece") and (not two or rng.random() < 0.35):
            parts = [pick("onepiece")]
        elif two:
            t = pick("top")
            parts = [t, pick("bottom", [t])]
        else:
            return None
        if outing:
            sh = pick("shoes", parts)
            if sh:
                parts.append(sh)
        for slot, p in (("legwear", 0.4), ("hat", 0.25 if outing else 0.0), ("acc", 0.3)):
            if rng.random() < p:
                x = pick(slot, parts)
                if x:
                    parts.append(x)
        while parts[-1]["slot"] == "acc" and rng.random() < 0.3:      # アクセサリーは重ねることもある (3 つまで. S37)
            rest = [o for o in by.get("acc") or [] if o["key"] not in [x["key"] for x in parts]]
            if not rest or sum(1 for x in parts if x["slot"] == "acc") >= len(ACC_KEYS):
                break
            by["acc"] = rest
            parts.append(pick("acc", parts))
        return self.coord_view(char, pack_coord(parts), outing)

    # ------------------------------------------------------------------ アウター (上に羽織るもの)
    @staticmethod
    def season(dt):
        return season_mod.season(dt)        # 季節の表は core/season.py に 1 つ (S38)

    def _outers(self, char, dt):
        """その日に羽織れるアウター (持っていて季節が合う. 今日手に入れたものは, 出かけるときにはまだ持っていなかった)."""
        season = self.season(dt)
        day0 = datetime.datetime.combine(dt.date(), datetime.time()).timestamp()
        return [o for o in self.owned(char) if o["kind"] == OUTER and (not o["seasons"] or season in o["seasons"])
                and o["owned_t"] < day0]

    def temp_gap(self, char, o, dt, outing=False, t=None):
        """服 o のその時の気温とのずれ (+ 暑すぎ / − 寒すぎ. S38). 外では, 寒い分は持っているアウターで補える."""
        t = season_mod.temp(dt) if t is None else t
        d = season_mod.gap(self.app, char, season_mod.warmth(o), t, inside=not outing)
        if outing and d < 0:
            d = min(0.0, d + max([season_mod.warmth(x) for x in self._outers(char, dt)] or [0.0]))
        return d

    def text_warmth(self, text):
        """文の服装の暖かさ (見つかった部品・アウターの足し算. 見つからなければ None)."""
        found = [o for _, o in self.find_parts(text) if o and (o["slot"] in COORD_SLOTS or o["kind"] == OUTER)]
        return season_mod.total(found) if found else None

    def outer_pick(self, char, st, dt, base=None):
        """出かけるときに本人が羽織っていくアウター (無ければ None). いまの服の暖かさ base で足りない分 (と寒がり) で羽織るかを決め,
        足りない分に近いものを選びやすい (S38). その日ごとのくじなので, 見るたびには変わらない (気温が下がれば羽織る)."""
        cands = self._outers(char, dt)
        if not cands:
            return None
        rng = random.Random("%s|%s|outer" % (char["id"], dt.date().isoformat()))
        short = -season_mod.gap(self.app, char, BASE_WARMTH if base is None else base, season_mod.temp(dt))   # 足りない暖かさ
        if rng.random() >= max(0.05, min(0.97, 1.0 / (1.0 + math.exp(-2.2 * (short - 0.5))))):
            return None                   # 今日は羽織らない (足りないほど, たいてい着る)
        aff = st["params"].get("affection", 40)
        w = [(max(0.5, min(2.5, 1 + (aff - 45) / 30.0)) if o.get("owned_from") == "player" else 1.0)
             * max(0.1, math.exp(-0.6 * (season_mod.warmth(o) - max(short, 0.8)) ** 2)) for o in cands]
        return rng.choices(cands, w)[0]

    def tryon_feel(self, char, st, o, dt):
        """買ってもらったアウターを, その場で着てみてと頼まれたとき: glad (喜んで) / yes / later (帰ってから) /
        season (いまの季節には合わない) / mood (そういう気分じゃない). 受け取ったからといって, 必ずその場で着るわけではない."""
        p = st["params"]
        if o.get("seasons") and self.season(dt) not in o["seasons"]:
            return "season"
        if season_mod.gap(self.app, char, BASE_WARMTH + season_mod.warmth(o), season_mod.temp(dt)) > 2.0 and random.random() < 0.7:
            return "season"               # 羽織ると暑すぎる日 (S38)
        if p.get("mood", 50) < 25:
            return "mood"
        aff = p.get("affection", 40)
        likes = self.app.items.likes(char)
        chance = 0.6 + (aff - 50) / 120.0 + (0.1 if "fashion" in likes[0] else -0.1 if "fashion" in likes[1] else 0) \
            - self.modesty(char) / 60.0 + 0.15 * fit(char, o)
        if random.random() >= max(0.25, min(0.92, chance)):
            return "later"
        return "glad" if aff >= 60 and p.get("mood", 50) >= 60 and random.random() < 0.5 else "yes"

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
        cands = [o for o in self.all() if 0 < o["price"] <= money * 0.3 and o["bold"] <= cap and o["slot"] != "lingerie"
                 and o["kind"] in ("casual", "formal", "lounge", "pajamas", "work", OUTER, "part") and not o.get("when")]
        cands = [o for o in cands if colored(o) or o["id"] not in have]
        if not cands:
            return None
        o = random.choices(cands, [math.exp(fit(char, x, color="")) for x in cands])[0]     # 好みの系統・種類に寄せる
        if colored(o):                    # 色は無彩色と好きな色に寄せたくじ. 持っている色なら買わない
            o = paint(o, self._color(char, o, random, pref=fashion_of(char)))
            if o["key"] in have:
                return None
        else:
            o = dict(o, key=o["id"])
        self.app.life.her_money(st)["a"] -= o["price"]
        self.give_to(char, o["key"], "self", t)
        return o

    # ------------------------------------------------------------------ 画面
    def catalog_view(self):
        return {"items": self.all(), "kinds": KINDS, "seasons": SEASONS, "bold": BOLD_LABEL,
                "sample_prompt": SAMPLE_PROMPT, "slots": SLOTS, "styles": STYLES, "types": TYPES, "fuss": FUSS_LABEL, "colors": {k: {"name": v[0], "tag": v[1], "hex": HEX[k]} for k, v in COLORS.items()}}

