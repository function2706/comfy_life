"""品物・持ち物・買うものリスト.

- カタログ (CATALOG): 値段と, どの店 (core/places.py の行き先) で売っているか. 種類 (kind) は家での行動との対応, 好みの印 (tags) はプレゼントの好み
- 持ち物 (player.json の items) と 買うものリスト (shop_list) はワールドごと
- 買い物 (画面を開いての買い物でも, オフラインの流れの買い物でも) では, 買うものリストの品がその店にあれば買う.
  品切れ・値段の上下もあり, お金が足りなければ買えない. リスト以外の衝動買いも少しある
- 家での行動が持ち物を使う: 料理=食材, お茶=お茶っ葉など, おやつ=お菓子 (無ければありあわせで効き目が落ちる),
  家事=洗剤 (あるとはかどる), 研鑽=その分野の本・教材 (あると伸びやすい. 減らない)
- 常備数 (stock): 「卵と豆腐は 4 回分は置いておく」のように決めておくと, 使って減って下回ったとき, 足りない分が買うものリストに戻る
  (単位は持ち物の数と同じ. 食材は回分). リストから手で消しても, 次に使って減るまでは戻さない
- 借金のあいだは必需品 (ESSENTIAL_KINDS: 食材・日用品) しか買わない (リストにあっても見送る. 衝動買いもしない)
- プレゼントは持ち物から. キャラクターの好き・苦手 (定義の likes / dislikes. 無ければ性格プリセットの既定) と品物の印を照らす
"""
import random

# id: (名前, 印, 種類, 値段, 売っている行き先, 好みの印, プレゼントにできるか)
_C = [
    ("rice", "お米", "🍚", "food", 1800, ["supermarket", "shopping_street", "mall"], ["food"], False),
    ("bread", "パン", "🍞", "food", 320, ["convenience", "supermarket", "station", "shopping_street"], ["food"], False),
    ("veggies", "野菜", "🥬", "food", 450, ["supermarket", "shopping_street", "mall"], ["food"], False),
    ("meat_fish", "肉と魚", "🍖", "food", 900, ["supermarket", "shopping_street", "mall"], ["food"], False),
    ("eggs_tofu", "卵と豆腐", "🥚", "food", 350, ["supermarket", "convenience", "shopping_street"], ["food"], False),
    ("bento", "お弁当", "🍱", "meal", 550, ["convenience", "supermarket", "station"], ["food"], False),
    ("cup_noodle", "カップ麺", "🍜", "meal", 220, ["convenience", "supermarket"], ["food"], False),
    ("tea_leaves", "お茶っ葉", "🍵", "tea", 800, ["supermarket", "shopping_street", "mall", "cafe"], ["tea"], True),
    ("coffee_beans", "コーヒー豆", "☕", "tea", 1000, ["cafe", "supermarket", "mall"], ["tea"], True),
    ("cookies", "クッキー", "🍪", "sweets", 400, ["convenience", "supermarket", "shopping_street", "mall", "station", "cafe"], ["sweets"], True),
    ("cake", "ケーキ", "🍰", "sweets", 1200, ["cafe", "station", "shopping_street", "convenience"], ["sweets"], True),
    ("cold_medicine", "風邪薬", "💊", "medicine", 1200, ["drugstore", "convenience"], ["practical"], False),
    ("detergent", "洗剤", "🧴", "detergent", 500, ["drugstore", "supermarket", "convenience", "shopping_street", "mall"], ["practical"], False),
    ("book_talk", "話し方の本", "📕", "book_talk", 1500, ["bookstore", "station", "mall"], ["books"], True),
    ("book_touch", "マッサージの本", "📗", "book_touch", 1500, ["bookstore", "mall"], ["books"], True),
    ("book_cook", "レシピ本", "📙", "book_cook", 1600, ["bookstore", "mall", "shopping_street"], ["books"], True),
    ("book_work", "仕事の参考書", "📘", "book_work", 2000, ["bookstore", "station", "mall"], ["books"], True),
    ("book_house", "暮らしの家事の本", "📗", "book_house", 1300, ["bookstore", "mall", "drugstore"], ["books", "practical"], True),
    ("book_care", "人の気持ちの本", "📕", "book_care", 1500, ["bookstore", "station"], ["books"], True),
    ("book_groom", "身だしなみの本", "📙", "book_groom", 1400, ["bookstore", "mall", "drugstore"], ["books", "fashion"], True),
    ("book_budget", "家計の本", "📘", "book_budget", 1500, ["bookstore", "station", "mall"], ["books", "practical"], True),
    ("book_write", "文章の書き方の本", "📒", "book_write", 1400, ["bookstore", "station", "mall"], ["books"], True),
    ("clothes", "自分の服", "👕", "clothes", 4000, ["mall", "shopping_street"], ["fashion"], False),
    ("novel", "小説", "📖", "goods", 1200, ["bookstore", "station", "mall", "convenience"], ["books"], True),
    ("bicycle", "自転車", "🚲", "vehicle", 25000, ["mall", "electronics"], ["practical"], False),
    ("car", "中古車", "🚗", "vehicle", 800000, ["car_dealer"], [], False),
    ("flowers", "花束", "💐", "goods", 2500, ["shopping_street", "station"], ["flowers"], True),
    ("plush", "ぬいぐるみ", "🧸", "goods", 3000, ["mall", "amusement"], ["cute"], True),
    ("hairpin", "ヘアピン", "🎀", "goods", 1500, ["mall", "shopping_street", "drugstore"], ["accessories", "cute"], True),
    ("scarf", "マフラー", "🧣", "goods", 4000, ["mall"], ["fashion", "practical"], True),
    ("game", "ゲームソフト", "🎮", "goods", 6000, ["electronics", "mall"], ["games"], True),
    ("necklace", "ネックレス", "💎", "goods", 30000, ["mall"], ["accessories"], True),
]
ESSENTIAL_KINDS = ("food", "meal", "detergent", "medicine")      # 必需品 (借金のあいだも買える)
# 食材の栄養 (自炊で使う. core/body.py) と, 1 個で何回分か (買うと回数ぶん持ち物に入る)
NUT = {"rice": ("staple", 10), "bread": ("staple", 3), "veggies": ("veg", 3), "meat_fish": ("protein", 3), "eggs_tofu": ("protein", 4)}
FOOD_KINDS = ("food", "meal", "tea", "sweets")             # 家計簿で「食費」にするもの
CATALOG = {i: {"id": i, "name": n, "icon": ic, "kind": k, "price": p, "places": pl, "tags": tg, "giftable": gf,
               "essential": k in ESSENTIAL_KINDS}
           for i, n, ic, k, p, pl, tg, gf in _C}
for _i, (_n, _s) in NUT.items():
    CATALOG[_i].update(nut=_n, servings=_s)
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
PRACTICE_BOOK = {"talk": "book_talk", "touch": "book_touch", "cook": "book_cook", "work": "book_work",
                 "house": "book_house", "care": "book_care", "groom": "book_groom", "budget": "book_budget",
                 "write": "book_write"}


class Items:
    def __init__(self, app):
        self.app = app

    def ps(self):
        ps = self.app.life.player_state()
        ps.setdefault("items", {})
        ps.setdefault("shop_list", {})
        ps.setdefault("stock", {})
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
        if n < 0:
            self.restock(iid)
        self.save()

    def count_nut(self, nut):
        """その栄養の食材が何回分あるか (自炊)."""
        return sum(n for i, n in self.ps()["items"].items() if CATALOG.get(i, {}).get("nut") == nut)

    def use_nut(self, nut):
        """その栄養の食材を 1 回分使う (安いものから). 使えたら品物の id."""
        ids = sorted((i for i, n in self.ps()["items"].items() if n > 0 and CATALOG.get(i, {}).get("nut") == nut),
                     key=lambda i: CATALOG[i]["price"] / float(CATALOG[i].get("servings", 1)))
        if ids:
            self.add(ids[0], -1)
            return ids[0]
        return None

    @staticmethod
    def catalog_name(iid):
        return CATALOG.get(iid, {}).get("name", iid)

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

    def set_stock(self, iid, qty):
        """常備数を決める (0 で解除). 決めた時点で足りなければ, 買うものリストに入れる."""
        if iid not in CATALOG:
            raise KeyError("品物が見つかりません: %s" % iid)
        st = self.ps()["stock"]
        if int(qty) > 0:
            st[iid] = min(99, int(qty))
            self.restock(iid)
        else:
            st.pop(iid, None)
        self.save()
        return self.view()

    def restock(self, iid):
        """常備数を下回っていれば, 足りない分 (買う単位で) を買うものリストに. 入れた数を返す (足りていれば 0)."""
        ps = self.ps()
        want = int(ps["stock"].get(iid, 0))
        lack = want - self.count(iid)
        if lack <= 0:
            return 0
        per = int(CATALOG[iid].get("servings", 1))
        need = -(-lack // per)
        if ps["shop_list"].get(iid, 0) >= need:
            return 0
        ps["shop_list"][iid] = min(99, need)
        trace = getattr(self.app, "trace", None)
        if trace:
            trace.add("items", "常備数を下回ったので買うものリストへ", item=iid, stock=want, have=self.count(iid), list=need)
        return need

    # ------------------------------------------------------------------ 買い物
    def shop(self, place, hours=1.0, t=None):
        """行き先 place での買い物. 買うものリストの品がここで売っていれば買う (品切れ・値段の上下・お金しだい).
        リスト以外の衝動買いも少し. 買ったもの [{id, name, price}] と, 買えなかった理由 [str] を返す."""
        ps = self.ps()
        bought, missed = [], []
        strict = self.app.life.in_debt()
        thrift = self.app.life.skill_soft("budget")          # やりくりがうまいほど, 少し安く買え, 衝動買いが減る (確定ではない)
        for iid, want in list(ps["shop_list"].items()):
            it = CATALOG.get(iid)
            if not it or place not in it["places"]:
                continue
            if strict and not it["essential"]:
                missed.append("借金があるので、%sは見送った" % it["name"])
                continue
            if it["kind"] == "vehicle":           # 乗り物: 一台だけ. 車は免許が要る
                if self.count(iid) > 0:
                    missed.append("%sはもう持っている" % it["name"])
                    ps["shop_list"].pop(iid, None)
                    continue
                if iid == "car" and not self.app.quals.has("drive"):
                    missed.append("免許がないので、%sは買えなかった" % it["name"])
                    continue
                want = 1
            for _ in range(int(want)):
                if random.random() < 0.12:
                    alt = self._substitute(it, place) if random.random() < 0.15 + 0.45 * thrift else None
                    if alt and ps["money"] >= alt["price"]:          # 品切れ: 代わりの品を選ぶ (同じ使い道のもの)
                        ps["money"] -= alt["price"]
                        self.app.life.ledger(t, -alt["price"], "food" if alt["kind"] in FOOD_KINDS else "shopping", alt["name"])
                        self.add(alt["id"], alt.get("servings", 1))
                        bought.append({"id": alt["id"], "name": alt["name"], "icon": alt["icon"], "price": alt["price"], "instead": it["name"]})
                        missed.append("%sは品切れだったので、代わりに%sを買った" % (it["name"], alt["name"]))
                    else:
                        missed.append("%sは品切れだった" % it["name"])
                    break
                price = int(round(it["price"] * random.uniform(0.85, 1.15 - 0.08 * thrift) / 10.0)) * 10
                if ps["money"] < price:
                    missed.append("%sはお金が足りなくて買えなかった" % it["name"])
                    break
                ps["money"] -= price
                self.app.life.ledger(t, -price, "food" if it["kind"] in FOOD_KINDS else "medical" if it["kind"] == "medicine"
                                     else "transport" if it["kind"] == "vehicle" else "shopping", it["name"])
                self.add(iid, it.get("servings", 1))
                if it["kind"] == "vehicle":       # 買った店に置いてある (乗って帰る)
                    self.app.geo.rec().setdefault("veh", {})[iid] = place
                    self.app.geo.save()
                bought.append({"id": iid, "name": it["name"], "icon": it["icon"], "price": price})
                ps["shop_list"][iid] = ps["shop_list"].get(iid, 0) - 1
                if ps["shop_list"][iid] <= 0:
                    ps["shop_list"].pop(iid, None)
        # 衝動買い: 安いものをたまに (長くいるほど)
        cheap = [i for i in CATALOG.values() if place in i["places"] and i["price"] <= 1500]
        if cheap and not strict and random.random() < min(0.35, 0.12 * max(0.5, hours)) * (1.0 - 0.5 * thrift):
            it = random.choice(cheap)
            price = int(round(it["price"] * random.uniform(0.85, 1.15) / 10.0)) * 10
            if ps["money"] >= price + 3000:
                ps["money"] -= price
                self.app.life.ledger(t, -price, "food" if it["kind"] in FOOD_KINDS else "medical" if it["kind"] == "medicine" else "shopping", it["name"])
                self.add(it["id"], it.get("servings", 1))
                bought.append({"id": it["id"], "name": it["name"], "icon": it["icon"], "price": price, "impulse": True})
        self.save()
        if bought or missed:
            self.app.life.train("budget", 0.3)                # 買い物をするたびに, 少しずつ
        if any(b["id"] == "clothes" for b in bought):
            self.app.life.train("groom", 0.8)                 # 服を選ぶ
        return bought, missed

    def _substitute(self, it, place):
        """品切れの品の代わり: 同じ種類 (食材なら同じ栄養) で, この店に売っている別の品."""
        for c in CATALOG.values():
            if c["id"] == it["id"] or place not in c["places"]:
                continue
            if (it.get("nut") and c.get("nut") == it.get("nut")) or (not it.get("nut") and c["kind"] == it["kind"] and c["kind"] != "goods"):
                return dict(c, price=int(round(c["price"] * random.uniform(0.9, 1.1) / 10.0)) * 10)
        return None

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
                "shop_list": [dict(CATALOG[i], want=n) for i, n in sorted(ps["shop_list"].items()) if i in CATALOG],
                "stock": {i: n for i, n in ps["stock"].items() if i in CATALOG},
                "in_debt": self.app.life.in_debt()}

    @staticmethod
    def catalog():
        return {"items": list(CATALOG.values()), "tags": TAG_LABEL}
