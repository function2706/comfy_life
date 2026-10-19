"""品物・持ち物・買うものリスト.

- カタログ (CATALOG): 値段と, どの行き先で売っているか. 種類 (kind) は家での行動との対応, 好みの印 (tags) はプレゼントの好み
- 持ち物 (player.json の items) と 買うものリスト (shop_list) はワールドごと
- 買い物 (画面を開いての買い物でも, オフラインの流れの買い物でも) では, 買うものリストの品がその店にあれば買う.
  品切れ・値段の上下もあり, お金が足りなければ買えない. リスト以外の衝動買いも少しある
- 家での行動が持ち物を使う: 料理=食材, お茶=お茶っ葉など, おやつ=お菓子 (無ければありあわせで効き目が落ちる),
  家事=洗剤 (あるとはかどる), 研鑽=その分野の本・教材 (あると伸びやすい. 減らない)
- プレゼントは持ち物から. キャラクターの好き・苦手 (定義の likes / dislikes. 無ければ性格プリセットの既定) と品物の印を照らす
"""
import random

# id: (名前, 印, 種類, 値段, 売っている行き先, 好みの印, プレゼントにできるか)
_C = [
    ("veggies", "野菜と米", "🥕", "food", 1200, ["shopping_street", "mall"], ["food"], False),
    ("meat_fish", "肉と魚", "🍖", "food", 1500, ["shopping_street", "mall"], ["food"], False),
    ("tea_leaves", "お茶っ葉", "🍵", "tea", 800, ["shopping_street", "mall", "cafe"], ["tea"], True),
    ("coffee_beans", "コーヒー豆", "☕", "tea", 1000, ["cafe", "mall"], ["tea"], True),
    ("cookies", "クッキー", "🍪", "sweets", 400, ["shopping_street", "mall", "station", "cafe"], ["sweets"], True),
    ("cake", "ケーキ", "🍰", "sweets", 1200, ["cafe", "station", "shopping_street"], ["sweets"], True),
    ("detergent", "洗剤", "🧴", "detergent", 500, ["shopping_street", "mall"], ["practical"], False),
    ("book_talk", "話し方の本", "📕", "book_talk", 1500, ["station", "mall"], ["books"], True),
    ("book_touch", "マッサージの本", "📗", "book_touch", 1500, ["station", "mall"], ["books"], True),
    ("book_cook", "レシピ本", "📙", "book_cook", 1600, ["station", "mall", "shopping_street"], ["books"], True),
    ("book_work", "仕事の参考書", "📘", "book_work", 2000, ["station", "mall"], ["books"], True),
    ("novel", "小説", "📖", "goods", 1200, ["station", "mall"], ["books"], True),
    ("flowers", "花束", "💐", "goods", 2500, ["shopping_street", "station"], ["flowers"], True),
    ("plush", "ぬいぐるみ", "🧸", "goods", 3000, ["mall"], ["cute"], True),
    ("hairpin", "ヘアピン", "🎀", "goods", 1500, ["mall", "shopping_street"], ["accessories", "cute"], True),
    ("scarf", "マフラー", "🧣", "goods", 4000, ["mall"], ["fashion", "practical"], True),
    ("game", "ゲームソフト", "🎮", "goods", 6000, ["mall"], ["games"], True),
    ("necklace", "ネックレス", "💎", "goods", 30000, ["mall"], ["accessories"], True),
]
CATALOG = {i: {"id": i, "name": n, "icon": ic, "kind": k, "price": p, "places": pl, "tags": tg, "giftable": gf}
           for i, n, ic, k, p, pl, tg, gf in _C}
TAG_LABEL = {"food": "食べ物", "tea": "お茶", "sweets": "甘いもの", "practical": "実用品", "books": "本", "flowers": "花",
             "cute": "かわいいもの", "accessories": "アクセサリー", "fashion": "服", "games": "ゲーム"}
# 性格プリセットごとの, 好き・苦手の既定 (キャラクターの定義の likes / dislikes で上書きできる)
PERSONA_LIKES = {
    "teinei": (["sweets", "flowers", "books"], []), "amaenbo": (["sweets", "cute"], []), "aneki": (["tea", "practical"], []),
    "boyish": (["games", "food"], ["flowers"]), "cool": (["books", "tea"], ["cute"]), "genki": (["sweets", "games"], ["books"]),
    "jimuteki": (["practical", "books"], ["cute"]), "kedakai": (["flowers", "accessories"], ["games"]),
    "mukuchi": (["books", "cute"], []), "ojousama": (["flowers", "tea", "accessories"], ["games"]),
    "osananajimi": (["games", "sweets"], []), "otokomae": (["practical", "food"], ["cute"]), "ottori": (["tea", "flowers"], []),
    "tenshin": (["cute", "flowers"], []), "tsundere": (["sweets", "cute"], []), "uchiki": (["books", "cute"], []),
    "sadist": (["accessories", "fashion"], ["cute"]), "itazura": (["games", "sweets"], []), "hikutsu": (["books", "tea"], []),
    "byoujaku": (["flowers", "tea", "books"], ["games"]), "hitonatsukko": (["sweets", "cute", "food"], []),
    "fushigi": (["flowers", "cute"], ["practical"]), "rikejo": (["books", "practical", "tea"], ["cute"]),
}
# 家での行動 → 使う品物の種類. 無いときのひとこと
USES = {"cook": "food", "tea": "tea", "snack": "sweets", "clean": "detergent"}
MISSING = {"cook": "（食材がなくて、ありあわせで簡単なものしか作れなかった）", "tea": "（お茶っ葉を切らしていて、白湯を出した）",
           "snack": "（お菓子がなくて、残っていたものを少しだけ出した）", "clean": "（洗剤が切れていて、思うようにははかどらなかった）"}
PRACTICE_BOOK = {"talk": "book_talk", "touch": "book_touch", "cook": "book_cook", "work": "book_work"}


class Items:
    def __init__(self, app):
        self.app = app

    def ps(self):
        ps = self.app.life.player_state()
        ps.setdefault("items", {})
        ps.setdefault("shop_list", {})
        return ps

    def save(self):
        self.app.life.save_player()

    def count(self, iid):
        return int(self.ps()["items"].get(iid, 0))

    def has_kind(self, kind):
        return next((i for i, n in self.ps()["items"].items() if n > 0 and CATALOG.get(i, {}).get("kind") == kind), None)

    def add(self, iid, n=1):
        inv = self.ps()["items"]
        inv[iid] = inv.get(iid, 0) + n
        if inv[iid] <= 0:
            inv.pop(iid)
        self.save()

    def use_kind(self, kind):
        """その種類の品を 1 つ使う. 使えたら品物の id, 無ければ None."""
        iid = self.has_kind(kind)
        if iid:
            self.add(iid, -1)
        return iid

    def set_list(self, iid, qty):
        if iid not in CATALOG:
            raise KeyError("品物が見つかりません: %s" % iid)
        sl = self.ps()["shop_list"]
        if int(qty) > 0:
            sl[iid] = min(99, int(qty))
        else:
            sl.pop(iid, None)
        self.save()
        return self.view()

    # ------------------------------------------------------------------ 買い物
    def shop(self, place, hours=1.0):
        """行き先 place での買い物. 買うものリストの品がここで売っていれば買う (品切れ・値段の上下・お金しだい).
        リスト以外の衝動買いも少し. 買ったもの [{id, name, price}] と, 買えなかった理由 [str] を返す."""
        ps = self.ps()
        bought, missed = [], []
        for iid, want in list(ps["shop_list"].items()):
            it = CATALOG.get(iid)
            if not it or place not in it["places"]:
                continue
            for _ in range(int(want)):
                if random.random() < 0.12:
                    missed.append("%sは品切れだった" % it["name"])
                    break
                price = int(round(it["price"] * random.uniform(0.85, 1.15) / 10.0)) * 10
                if ps["money"] < price:
                    missed.append("%sはお金が足りなくて買えなかった" % it["name"])
                    break
                ps["money"] -= price
                self.add(iid, 1)
                bought.append({"id": iid, "name": it["name"], "icon": it["icon"], "price": price})
                ps["shop_list"][iid] = ps["shop_list"].get(iid, 0) - 1
                if ps["shop_list"][iid] <= 0:
                    ps["shop_list"].pop(iid, None)
        # 衝動買い: 安いものをたまに (長くいるほど)
        cheap = [i for i in CATALOG.values() if place in i["places"] and i["price"] <= 1500]
        if cheap and random.random() < min(0.35, 0.12 * max(0.5, hours)):
            it = random.choice(cheap)
            price = int(round(it["price"] * random.uniform(0.85, 1.15) / 10.0)) * 10
            if ps["money"] >= price + 3000:
                ps["money"] -= price
                self.add(it["id"], 1)
                bought.append({"id": it["id"], "name": it["name"], "icon": it["icon"], "price": price, "impulse": True})
        self.save()
        return bought, missed

    @staticmethod
    def describe(bought, missed):
        parts = []
        if bought:
            parts.append("買ったもの: " + "、".join("%s%s（%s円）" % (b["name"], "・衝動買い" if b.get("impulse") else "",
                                                                 format(b["price"], ",")) for b in bought))
        parts += missed
        return "。".join(parts)

    # ------------------------------------------------------------------ 好み
    def likes(self, char):
        """キャラクターの好き・苦手 (定義に無ければ性格プリセットの既定)."""
        dl, dd = PERSONA_LIKES.get(char.get("persona_id") or "", ([], []))
        return (char.get("likes") if char.get("likes") is not None else dl,
                char.get("dislikes") if char.get("dislikes") is not None else dd)

    def feel(self, char, iid):
        lk, dk = self.likes(char)
        tags = CATALOG[iid]["tags"]
        return {"liked": any(t in lk for t in tags), "disliked": any(t in dk for t in tags)}

    def view(self):
        ps = self.ps()
        return {"items": [dict(CATALOG[i], count=n) for i, n in sorted(ps["items"].items()) if i in CATALOG and n > 0],
                "shop_list": [dict(CATALOG[i], want=n) for i, n in sorted(ps["shop_list"].items()) if i in CATALOG]}

    @staticmethod
    def catalog():
        return {"items": list(CATALOG.values()), "tags": TAG_LABEL}
