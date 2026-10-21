"""行き先の表 (一人の外出・誰かとのお出かけ・偶然会った相手との合流・訪問・行動パターン・買い物が, すべてここを参照する).

- 公共の行き先 (PLACES): 人の多さ (時間帯ごと)・屋外か・そこで何ができるか (does) と, 何として分類するか (group).
  does: walk (ぶらぶら歩く) / shop (買い物. 品ぞろえは items.CATALOG の places) / tea (お茶) / see (見て回る・遊ぶ) / work (仕事)
- 家 (HOME_ME = あなたの家, "home:<id>" = 知っている相手の家): 表に加わるのは, あなたの家と, 家に行ける仲 (visit) の相手の家.
  家では偶然の出会いは起きない. 外出の行き先として相手の家を選ぶと, 訪ねてみる (在宅か・迎えてくれるかは状況・関係・性格しだい).
- 以前の行き先の表し方 (お出かけの一時シーンの日本語の場所・一人の時間の散歩/買い物/カフェ・行動パターンの do) は,
  ここで読み替える (LOCATION_PLACE / LEGACY_DO).
"""

# 時間帯ごとの人の多さの型
_CROWD = {
    "park": {"dawn": 0.3, "morning": 1.0, "noon": 1.2, "evening": 1.0, "night": 0.3, "midnight": 0.05},
    "street": {"dawn": 0.05, "morning": 0.6, "noon": 1.5, "evening": 1.4, "night": 0.4, "midnight": 0.02},
    "river": {"dawn": 0.4, "morning": 0.7, "noon": 0.6, "evening": 0.8, "night": 0.15, "midnight": 0.02},
    "station": {"dawn": 0.2, "morning": 1.3, "noon": 1.0, "evening": 1.5, "night": 0.8, "midnight": 0.1},
    "cafe": {"dawn": 0.0, "morning": 0.8, "noon": 1.2, "evening": 0.9, "night": 0.4, "midnight": 0.0},
    "mall": {"dawn": 0.0, "morning": 0.5, "noon": 1.4, "evening": 1.2, "night": 0.5, "midnight": 0.0},
    "town": {"dawn": 0.1, "morning": 0.8, "noon": 1.1, "evening": 1.1, "night": 0.5, "midnight": 0.05},
    "office": {"dawn": 0.2, "morning": 1.0, "noon": 1.0, "evening": 0.8, "night": 0.4, "midnight": 0.1},
    "shop": {"dawn": 0.05, "morning": 0.7, "noon": 1.0, "evening": 1.2, "night": 0.4, "midnight": 0.0},
    "conveni": {"dawn": 0.3, "morning": 0.9, "noon": 1.0, "evening": 1.0, "night": 0.7, "midnight": 0.3},
    "leisure": {"dawn": 0.0, "morning": 0.8, "noon": 1.4, "evening": 1.0, "night": 0.2, "midnight": 0.0},
    "far": {"dawn": 0.2, "morning": 0.6, "noon": 0.7, "evening": 0.5, "night": 0.2, "midnight": 0.02},
    "hill": {"dawn": 0.1, "morning": 0.3, "noon": 0.3, "evening": 0.4, "night": 0.5, "midnight": 0.1},
}


def _p(label, icon, group, outdoor, crowd, does, fee=0):
    return {"label": label, "icon": icon, "group": group, "outdoor": outdoor, "crowd": _CROWD[crowd], "does": does, "fee": fee}


# id: 名前・印・分類・屋外か・人の多さ・できること・入るのにかかるお金 (一人分の目安)
PLACES = {
    "park": _p("公園", "🌳", "near", True, "park", ["walk"]),
    "riverside": _p("河川敷", "🌊", "near", True, "river", ["walk"]),
    "shopping_street": _p("商店街", "🏮", "shop", True, "street", ["shop", "walk"]),
    "station": _p("駅前", "🚉", "near", False, "station", ["walk", "shop"]),
    "town": _p("街", "🏙", "near", True, "town", ["walk"]),
    "cafe": _p("カフェ", "☕", "shop", False, "cafe", ["tea"]),
    "supermarket": _p("スーパー", "🛒", "shop", False, "shop", ["shop"]),
    "convenience": _p("コンビニ", "🏪", "shop", False, "conveni", ["shop"]),
    "drugstore": _p("ドラッグストア", "💊", "shop", False, "shop", ["shop"]),
    "bookstore": _p("本屋", "📚", "shop", False, "shop", ["shop"]),
    "electronics": _p("家電量販店", "🔌", "shop", False, "shop", ["shop"]),
    "mall": _p("ショッピングモール", "🏬", "shop", False, "mall", ["shop", "walk"]),
    "aquarium": _p("水族館", "🐠", "fun", False, "leisure", ["see"], fee=2500),
    "amusement": _p("遊園地", "🎡", "fun", True, "leisure", ["see"], fee=6000),
    "beach": _p("海", "🏖", "fun", True, "far", ["walk"]),
    "mountain": _p("山", "⛰", "fun", True, "far", ["walk"]),
    "hill": _p("星空の見える丘", "🌌", "fun", True, "hill", ["walk"]),
    "office": _p("職場", "💼", "work", False, "office", ["work"]),
}
GROUP_LABEL = {"near": "近所", "shop": "お店", "fun": "遊びに", "home": "家", "work": "仕事"}
DO_LABEL = {"walk": "ぶらぶら歩く", "shop": "買い物", "tea": "お茶", "see": "見て回る", "visit": "訪ねる", "work": "仕事"}
HOME_ME = "home:me"
# 一人の外出で選べる行き先 (職場は「仕事に行く」から)
OUT_PLACES = [k for k, v in PLACES.items() if v["group"] != "work"]

# 以前の表し方からの読み替え
# お出かけの一時シーンの場所 (日本語) → 行き先
LOCATION_PLACE = {"公園": "park", "商店街": "shopping_street", "河川敷": "riverside", "駅前": "station", "カフェ": "cafe",
                  "ショッピングモール": "mall", "モール": "mall", "街": "town", "近所": "park", "海辺": "beach", "海": "beach",
                  "遊園地": "amusement", "水族館": "aquarium", "丘の上": "hill", "山道": "mountain", "山": "mountain",
                  "スーパー": "supermarket", "コンビニ": "convenience", "ドラッグストア": "drugstore", "本屋": "bookstore",
                  "家電量販店": "electronics", "星空の見える丘": "hill"}
# 一人の時間・行動パターンの「散歩・買い物・カフェ」→ 外出の既定の行き先
LEGACY_DO = {"walk": "park", "shopping": "shopping_street", "cafe": "cafe"}

# 約束なしに相手の家を訪ねたときの, 相手のひとこと (性格プリセットに無ければ). 留守・出てこないときはナレーションだけ
LINES = {
    "drop.yes": "あれ、{call}？ 急にどうしたんですか……まあ、上がってください。",
    "drop.no": "ごめんなさい、急に来られても……今日はちょっと。",
}
SCENE_LABEL = {"drop.yes": "約束なしに家を訪ねた / 迎えてくれた", "drop.no": "約束なしに家を訪ねた / 断られた"}


def is_home(pid):
    return isinstance(pid, str) and pid.startswith("home:")


def home_of(pid):
    """家の行き先の持ち主 ("me" か キャラの id). 家でなければ None."""
    return pid.split(":", 1)[1] if is_home(pid) else None


def from_location(loc, default="town"):
    """お出かけの一時シーンの場所 (日本語の自由記述) を行き先に."""
    return LOCATION_PLACE.get(loc or "", default)


def main_do(pid):
    """その行き先で, 一人で行ったときにすること (公共の行き先の最初の does. 人の家なら visit)."""
    if is_home(pid):
        return "visit"
    return (PLACES.get(pid) or PLACES["town"])["does"][0]


def solo_kind(pid):
    """一人の外出の結果の種類 (solo.result): walk / shopping / cafe / see / visit."""
    return {"walk": "walk", "shop": "shopping", "tea": "cafe", "see": "see", "visit": "visit"}.get(main_do(pid), "walk")


class Places:
    """表に家を加えて引く (家に行ける仲の相手が変われば, 表も変わる)."""

    def __init__(self, app):
        self.app = app

    def homes(self):
        """表に加わる家: あなたの家と, 家に行ける仲の相手の家 (同居相手の家はあなたの家)."""
        app = self.app
        out = {HOME_ME: {"label": "あなたの家", "icon": "🏠", "group": "home", "outdoor": False, "crowd": {}, "does": ["home"],
                         "fee": 0}}
        for cid, c in app.chars.items():
            if app.bonds.stage(cid) == "visit":
                out["home:" + cid] = {"label": "%sの家" % c.get("name", cid), "icon": "🚪", "group": "home", "outdoor": False,
                                      "crowd": {}, "does": ["visit"], "fee": 0, "owner": cid}
        return out

    def table(self):
        t = dict(PLACES)
        t.update(self.homes())
        return t

    def get(self, pid):
        return self.table().get(pid)

    def label(self, pid):
        p = self.get(pid)
        return p["label"] if p else pid

    def out_choices(self):
        """一人の外出の行き先 (公共の行き先 + 訪ねられる相手の家)."""
        return OUT_PLACES + [k for k in self.homes() if k != HOME_ME]

    def view(self):
        return {"places": {k: {"label": v["label"], "icon": v["icon"], "group": v["group"], "does": v["does"],
                               "outdoor": v["outdoor"]} for k, v in self.table().items()},
                "groups": GROUP_LABEL, "does": DO_LABEL}
