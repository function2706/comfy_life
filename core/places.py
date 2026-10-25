"""行き先の表 (一人の外出・誰かとのお出かけ・偶然会った相手との合流・訪問・行動パターン・買い物が, すべてここを参照する).

- 公共の行き先 (PLACES): 人の多さ (時間帯ごと)・屋外か・そこで何ができるか (does) と, 何として分類するか (group).
  does: walk (ぶらぶら歩く) / shop (買い物. 品ぞろえは items.CATALOG の places) / tea (お茶) / see (見て回る・遊ぶ) / work (仕事) /
        eat (食べる. メニューは core/body.py の MENUS) / clinic (診てもらう)
- 家 (HOME_ME = あなたの家, "home:<id>" = 知っている相手の家): 表に加わるのは, あなたの家と, 家に行ける仲 (visit) の相手の家.
  家では偶然の出会いは起きない. 外出の行き先として相手の家を選ぶと, 訪ねてみる (在宅か・迎えてくれるかは状況・関係・性格しだい).
- 営業時間 (HOURS): 開く・閉まる時刻と, 定休日・季節. 載っていない行き先 (公園・河川敷・駅前・街・コンビニ・丘・家) は
  いつでも行ける (夜の公園のように人がほとんどいないだけ. 人の多さは crowd のまま). 閉まっている行き先には行けず,
  閉まる時刻になれば出される (open_state).
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
    "meal": {"dawn": 0.05, "morning": 0.4, "noon": 1.5, "evening": 1.3, "night": 0.7, "midnight": 0.1},
    "clinic": {"dawn": 0.0, "morning": 1.0, "noon": 0.6, "evening": 0.8, "night": 0.0, "midnight": 0.0},
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
    "teishoku": _p("定食屋", "🍱", "eat", False, "meal", ["eat"]),
    "ramen": _p("ラーメン屋", "🍜", "eat", False, "meal", ["eat"]),
    "fastfood": _p("ファストフード", "🍔", "eat", False, "meal", ["eat"]),
    "family": _p("ファミレス", "🍽", "eat", False, "meal", ["eat"]),
    "restaurant": _p("レストラン", "🍝", "eat", False, "meal", ["eat"]),
    "clinic": _p("病院", "🏥", "near", False, "clinic", ["clinic"]),
    "office": _p("職場", "💼", "work", False, "office", ["work"]),
}
# 営業時間: open / close ("HH:MM". close は当日中), closed_days (定休日. 0=月 ... 6=日), months (行ける月. 無ければ通年)
HOURS = {
    "shopping_street": {"open": "10:00", "close": "20:00"},
    "cafe": {"open": "08:00", "close": "21:00", "closed_days": [0]},
    "supermarket": {"open": "09:00", "close": "22:00"},
    "drugstore": {"open": "09:00", "close": "22:00"},
    "bookstore": {"open": "10:00", "close": "21:00"},
    "electronics": {"open": "10:00", "close": "21:00"},
    "mall": {"open": "10:00", "close": "21:00"},
    "aquarium": {"open": "09:30", "close": "17:30"},
    "amusement": {"open": "09:00", "close": "21:00"},
    "beach": {"open": "06:00", "close": "19:00", "months": [4, 5, 6, 7, 8, 9, 10]},
    "mountain": {"open": "06:00", "close": "16:00", "months": [3, 4, 5, 6, 7, 8, 9, 10, 11]},
    "office": {"open": "06:00", "close": "23:00"},
    "teishoku": {"open": "11:00", "close": "21:00", "closed_days": [6]},
    "ramen": {"open": "11:00", "close": "23:30"},
    "fastfood": {"open": "07:00", "close": "23:00"},
    "family": {"open": "07:00", "close": "24:00"},
    "restaurant": {"open": "11:00", "close": "22:00", "closed_days": [1]},
    "clinic": {"open": "09:00", "close": "18:00", "closed_days": [6]},
}
DAY_JA = "月火水木金土日"


def _hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def hours_label(pid):
    h = HOURS.get(pid)
    if not h:
        return "24時間"
    s = "%s〜%s" % (h["open"].lstrip("0") or "0", h["close"].lstrip("0") or "0")
    if h.get("closed_days"):
        s += "・%s曜休み" % "".join(DAY_JA[d] for d in h["closed_days"])
    if h.get("months"):
        s += "・%d〜%d月" % (h["months"][0], h["months"][-1])
    return s


def open_state(pid, dt):
    """その時刻に行き先が開いているか. {open, until (閉まる時刻 or None), note (閉まっていれば「10:00から」など), hours}."""
    h = HOURS.get(pid)
    out = {"open": True, "until": None, "note": "", "hours": hours_label(pid)}
    if not h or is_home(pid):
        return out
    from datetime import timedelta
    if h.get("months") and dt.month not in h["months"]:
        out.update(open=False, note="季節外（%d〜%d月）" % (h["months"][0], h["months"][-1]))
        return out
    if dt.weekday() in (h.get("closed_days") or []):
        out.update(open=False, note="定休日（%s曜）" % DAY_JA[dt.weekday()])
        return out
    mins = dt.hour * 60 + dt.minute
    o, c = _hm(h["open"]), _hm(h["close"])
    if o <= mins < c:
        day0 = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        out["until"] = (day0 + timedelta(minutes=c)).timestamp()
        return out
    if mins < o:
        note = "%sから" % h["open"]
    else:
        nxt = dt + timedelta(days=1)
        ok_next = nxt.weekday() not in (h.get("closed_days") or []) and (not h.get("months") or nxt.month in h["months"])
        note = "閉店（明日%sから）" % h["open"] if ok_next else "閉店"
    out.update(open=False, note=note)
    return out


def open_at(pid, t):
    from datetime import datetime
    return open_state(pid, datetime.fromtimestamp(t))["open"]


GROUP_LABEL = {"near": "近所", "shop": "お店", "eat": "食べに", "fun": "遊びに", "home": "家", "work": "仕事"}
DO_LABEL = {"walk": "ぶらぶら歩く", "shop": "買い物", "tea": "お茶", "see": "見て回る", "visit": "訪ねる", "work": "仕事",
            "eat": "食べる", "clinic": "診てもらう"}
HOME_ME = "home:me"
# 一人の外出で選べる行き先 (職場は「仕事に行く」から)
OUT_PLACES = [k for k, v in PLACES.items() if v["group"] != "work"]

# 以前の表し方からの読み替え
# お出かけの一時シーンの場所 (日本語) → 行き先
LOCATION_PLACE = {"公園": "park", "商店街": "shopping_street", "河川敷": "riverside", "駅前": "station", "カフェ": "cafe",
                  "ショッピングモール": "mall", "モール": "mall", "街": "town", "近所": "park", "海辺": "beach", "海": "beach",
                  "遊園地": "amusement", "水族館": "aquarium", "丘の上": "hill", "山道": "mountain", "山": "mountain",
                  "スーパー": "supermarket", "コンビニ": "convenience", "ドラッグストア": "drugstore", "本屋": "bookstore",
                  "家電量販店": "electronics", "星空の見える丘": "hill", "定食屋": "teishoku", "ラーメン屋": "ramen",
                  "ファストフード": "fastfood", "ファミレス": "family", "レストラン": "restaurant", "病院": "clinic"}
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


# 行き先の体の使い方 (一人の外出の疲れ・運動にかける. 無ければ 1): 山道は坂がきつい, 海は砂浜, 遊園地は歩き回って並ぶ
EFFORT = {"mountain": 2.0, "amusement": 1.5, "beach": 1.3, "hill": 1.2}


def effort(pid):
    return EFFORT.get(pid or "", 1.0)


def main_do(pid):
    """その行き先で, 一人で行ったときにすること (公共の行き先の最初の does. 人の家なら visit)."""
    if is_home(pid):
        return "visit"
    return (PLACES.get(pid) or PLACES["town"])["does"][0]


def solo_kind(pid):
    """一人の外出の結果の種類 (solo.result): walk / shopping / cafe / see / visit / eat / clinic."""
    return {"walk": "walk", "shop": "shopping", "tea": "cafe", "see": "see", "visit": "visit", "eat": "eat",
            "clinic": "clinic"}.get(main_do(pid), "walk")


# 相手の家を訪ねたときに見える暮らしぶり (好みの印 → 部屋のようす)
GLIMPSE_TAGS = {"books": "本棚に本がぎっしり並んでいる", "cute": "ベッドにぬいぐるみが並んでいる",
                "games": "テレビの前にゲーム機が置いてある", "flowers": "窓辺に花が飾ってある", "tea": "棚にお茶の缶がいくつも並んでいる",
                "fashion": "服がハンガーにたくさん掛かっている", "accessories": "小物入れにアクセサリーが並んでいる",
                "sweets": "テーブルにお菓子の箱が置いてある", "food": "台所に調味料がそろっている",
                "practical": "日用品がきちんと整理されている"}


def home_glimpse(app, char, st):
    """相手の家の暮らしぶり (きれい好きか・好きなもの・懐具合が, 部屋ににじむ). ナレーションを返す. 毎回少し違う."""
    import random
    import time
    neat = float(app.traits(char).get("neat", 0))
    r = random.gauss(neat / 10.0, 0.35)
    tidy = "きれいに片付いていた" if r > 0.35 else "ほどよく生活感があった" if r > -0.35 else "少し散らかっていた"
    likes = [t for t in app.items.likes(char)[0] if t in GLIMPSE_TAGS]
    picked = random.sample(likes, min(len(likes), random.choice((1, 2)))) if likes else []
    seen = [GLIMPSE_TAGS[t] for t in picked]
    from .items import TAG_LABEL
    for t in picked:                    # 部屋を見て分かった好きなもの (関係性)
        app.bonds.learn(st, "like", TAG_LABEL.get(t, t), time.time())
    money = app.life.her_money(st)["a"]
    if money < 5000:
        seen.append("家具は少なく、質素な暮らしぶりだ")
    elif money > 60000 and random.random() < 0.5:
        seen.append("家具は少しいいものをそろえているようだ")
    return "（%sの部屋は%s。%s）" % (char.get("name", ""), tidy, "。".join(seen)) if seen else "（%sの部屋は%s）" % (char.get("name", ""), tidy)


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

    def view(self, now=None):
        import time
        from datetime import datetime
        dt = datetime.fromtimestamp(now or time.time())
        out = {}
        for k, v in self.table().items():
            o = open_state(k, dt)
            out[k] = {"label": v["label"], "icon": v["icon"], "group": v["group"], "does": v["does"], "outdoor": v["outdoor"],
                      "open": o["open"], "note": o["note"], "hours": o["hours"], "until": o["until"]}
        return {"places": out,
                "groups": GROUP_LABEL, "does": DO_LABEL}
