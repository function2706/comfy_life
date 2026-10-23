"""あなたの体: お腹 (満腹度) と栄養 (主食・たんぱく質・野菜). 食べ方は 自炊・外食・買って食べる (と, 買ってきたものを家で).

- お腹 (satiety 0〜100): 起きている間は 1 時間に 4 ほど, 寝ている間は 1.5 ほど減る. 1 日に何度か食べないと空腹になる.
  空腹のあいだは体力が戻りにくい (life.tick_world).
- 栄養 (nutri: staple 主食 / protein たんぱく質 / veg 野菜. 各 0〜100): 数日分の蓄え. 1 日に 36 ほど減り, 食べたものの中身で戻る.
  一つだけ多く食べても, ほかの不足は埋まらない (偏り). 細かい栄養素までは見ない.
- 自炊 (cook): 持ち物の食材 (items の nut: staple / protein / veg. 1 個 = 1 回分) を使う. 料理スキルが高いほど作れる献立が増え,
  一度に使える食材が増えて栄養がそろう. 低いと失敗することも. 食材がなければ作れない. 家でだけ.
- 外食 (out): 行き先の表の食べに行く店 (定食屋・ラーメン屋・ファストフード・レストラン・ファミレス. 営業時間つき) とカフェ.
  お腹は満たされるが, 栄養と値段は店とメニューしだい.
- 買って食べる (buy): コンビニ・スーパー・駅前で, お弁当・おにぎり・サラダなど. 手軽だが栄養は偏りがち.
- 持ち物の食べもの (item): 買ってきたお弁当・カップ麺などを家で.
あなたにしか見えない体の様子は, 自覚できる言葉でだけ出す (「お腹がすいた」「野菜が足りていない気がする」).

体調 (health.level 0〜3): 0 = ふつう / 1 = 軽い不調 (少しだるい) / 2 = 風邪 (熱っぽい) / 3 = 寝込むほど (病院へ行ったほうが良さそう).
- 崩れやすさ: 日付が変わるたびに, その日の過ごし方から決まる. 栄養の偏り・寝不足・働きすぎ (ここ 3 日の勤務)・空腹の時間・
  体力の消耗・雨や雪の中の外出・冬. 重なるほど崩しやすい (補正はしない. 何もなくても, ごくまれに崩す).
- 治り方: 軽ければ, 休めば (よく寝る・休む) 自然に治る. 薬 (持ち物の風邪薬. ドラッグストア・コンビニ) を飲むと治りやすい
  (寝込むほどだと効きにくい). 寝込むほどなら病院 (行き先. 営業時間・お金がかかる) で診てもらうと, 軽いところまで戻る.
  無理をすれば (働きすぎ・寝不足・偏った食事のまま) こじらせることもある.
- 体調が悪い間: 体力が戻りにくい・仕事の給料が下がる・スキルが伸びにくい. 寝込んでいると仕事に行けない.
  行動パターンの仕事も, 休む・早退することがある.

運動 (exercise 0〜100): 数日分の「体を動かした量」. 1 日に EXERCISE_PER_DAY ずつ減り, 体を動かすと増える
(ぶらぶら歩く外出・ジョギング (一人の行動. 公園・河川敷・街で)・誰かとのお出かけ・家事・店を見て回る. 仕事は少しだけ).
足りない日が続くと (運動不足), 体力の上限が下がり, 体力が戻りにくく, 体調を崩しやすい. 自覚できる言葉でだけ出す (「体がなまっている気がする」).
"""
import random
import time
from datetime import datetime

NUTRI = ("staple", "protein", "veg")
NUTRI_LABEL = {"staple": "主食", "protein": "たんぱく質", "veg": "野菜"}
SATIETY_PER_H = 4.0          # 起きている間
SATIETY_PER_H_SLEEP = 1.5    # 寝ている間
NUTRI_PER_DAY = 24.0         # 栄養の蓄えの減り (1 日あたり. 4 日ほどで尽きる)
NUTRI_GAIN = 1.3             # 食べたものの栄養 (表の値) の入り方. そろった食事 2〜3 回で, その日の減りを埋められるくらい

# 自炊の献立: (id, 名前, 使う食材の栄養 (1 回分ずつ), いる料理スキル)
DISHES = [
    ("rice", "ご飯だけ", ("staple",), 0),
    ("tkg", "卵かけご飯", ("staple", "protein"), 0),
    ("miso", "ご飯と味噌汁", ("staple", "veg"), 5),
    ("boiled", "ゆで野菜と目玉焼き", ("protein", "veg"), 5),
    ("stirfry", "野菜炒めとご飯", ("staple", "protein", "veg"), 15),
    ("curry", "カレーライス", ("staple", "protein", "veg"), 25),
    ("teishoku", "焼き魚の定食", ("staple", "protein", "veg"), 40),
    ("nabe", "具だくさんの鍋とご飯", ("staple", "protein", "veg", "veg"), 55),
]
# 外食・買って食べる: 行き先 → [(id, 名前, 値段, 栄養, お腹)]
MENUS = {
    "teishoku": [("saba", "さばの塩焼き定食", 900, {"staple": 12, "protein": 12, "veg": 9}, 60),
                 ("shoga", "生姜焼き定食", 950, {"staple": 12, "protein": 13, "veg": 6}, 65),
                 ("yasai", "野菜炒め定食", 850, {"staple": 11, "protein": 7, "veg": 13}, 58)],
    "ramen": [("ramen", "ラーメン", 850, {"staple": 14, "protein": 5, "veg": 2}, 65),
              ("tanmen", "野菜たっぷりタンメン", 950, {"staple": 12, "protein": 5, "veg": 9}, 62),
              ("gyoza", "ラーメンと餃子", 1150, {"staple": 15, "protein": 8, "veg": 3}, 75)],
    "fastfood": [("burger", "ハンバーガーのセット", 700, {"staple": 10, "protein": 7, "veg": 1}, 55),
                 ("salad_set", "サラダのセット", 750, {"staple": 7, "protein": 6, "veg": 7}, 45)],
    "restaurant": [("pasta", "パスタ", 1400, {"staple": 12, "protein": 6, "veg": 5}, 55),
                   ("hamburg", "ハンバーグのランチ", 1600, {"staple": 11, "protein": 12, "veg": 7}, 65),
                   ("course", "コース料理", 4500, {"staple": 10, "protein": 13, "veg": 10}, 70)],
    "family": [("doria", "ドリア", 450, {"staple": 11, "protein": 4, "veg": 2}, 50),
               ("hamburg_f", "ハンバーグのセット", 900, {"staple": 11, "protein": 11, "veg": 5}, 62),
               ("salad_f", "サラダとスープ", 500, {"staple": 2, "protein": 4, "veg": 11}, 25)],
    "cafe": [("sandwich", "サンドイッチ", 650, {"staple": 8, "protein": 5, "veg": 4}, 35),
             ("cake_set", "ケーキセット", 900, {"staple": 3, "protein": 1, "veg": 0}, 25)],
}
_BUY = [("bento", "お弁当", 550, {"staple": 11, "protein": 7, "veg": 2}, 52),
        ("onigiri", "おにぎりとパン", 380, {"staple": 13, "protein": 1, "veg": 0}, 38),
        ("salad", "サラダ", 350, {"staple": 0, "protein": 2, "veg": 11}, 10),
        ("sandwich_b", "サンドイッチと野菜ジュース", 480, {"staple": 7, "protein": 4, "veg": 6}, 30)]
for _p in ("convenience", "supermarket", "station"):
    MENUS[_p] = _BUY
EAT_OUT_PLACES = ("teishoku", "ramen", "fastfood", "restaurant", "family", "cafe")
BUY_PLACES = ("convenience", "supermarket", "station")
# 持ち物の食べもの (家で食べる): 品物の id → (栄養, お腹)
ITEM_MEALS = {"bento": ({"staple": 11, "protein": 7, "veg": 2}, 52), "cup_noodle": ({"staple": 9, "protein": 1, "veg": 1}, 38)}


EXERCISE_PER_DAY = 30.0      # 運動の蓄えの減り (1 日あたり. 30 分ほど歩けば, その日の分になる)
# 体を動かす量 (1 時間あたり): 何をしているか (在席・一人の時間の中身・行き先) から
MOVE_PER_H = {"jog": 120.0, "walk": 66.0, "outing": 48.0, "shop": 36.0, "see": 40.0, "chores": 24.0, "work": 2.0, "other": 12.0}
EXERCISE_LOW = 20.0          # これを下回る日が続くと運動不足
HEALTH_WORD = {0: "", 1: "少しだるい", 2: "熱っぽい。風邪をひいたみたいだ", 3: "寝込むほどつらい。病院へ行ったほうが良さそうだ"}
HEALTH_MULT = {"stamina": (1.0, 0.85, 0.65, 0.35), "work": (1.0, 0.92, 0.75, 0.5), "train": (1.0, 0.85, 0.6, 0.3)}
MEDICINE = "cold_medicine"


def _meal_label(t):
    h = datetime.fromtimestamp(t).hour
    return "朝ご飯" if 4 <= h < 10 else "昼ご飯" if 10 <= h < 15 else "夕ご飯" if 15 <= h < 22 else "夜食"


class Body:
    def __init__(self, app):
        self.app = app

    def rec(self):
        ps = self.app.life.player_state()
        b = ps.setdefault("body", {})
        b.setdefault("satiety", 70.0)
        b.setdefault("nutri", {k: 60.0 for k in NUTRI})
        b.setdefault("meals", [])
        b.setdefault("health", {"level": 0, "since": None})
        b.setdefault("today", {})
        b.setdefault("exercise", 50.0)
        b.setdefault("lazy_days", 0)          # 運動が足りない日が続いた日数
        return b

    # ------------------------------------------------------------------ 時間の経過 (life.tick_world の 5 分ごと)
    def step(self, t, h, mode):
        b = self.rec()
        sleeping = mode == "sleep" or (mode == "gone" and datetime.fromtimestamp(t).hour < 7)
        b["satiety"] = max(0.0, b["satiety"] - (SATIETY_PER_H_SLEEP if sleeping else SATIETY_PER_H) * h)
        for k in NUTRI:
            b["nutri"][k] = max(0.0, b["nutri"][k] - NUTRI_PER_DAY * h / 24.0)
        td = b["today"]                       # その日の過ごし方 (日付が変わったときの体調の判定に)
        if sleeping:
            td["slept"] = td.get("slept", 0.0) + h
        if b["satiety"] < 15:
            td["hungry"] = td.get("hungry", 0.0) + h
        if mode in ("out", "work"):
            td["out"] = td.get("out", 0.0) + h
        sl = self.app.presence.rec().get("solo") or {}
        if mode == "busy" and sl.get("kind") == "rest":
            td["rested"] = td.get("rested", 0.0) + h
        b["exercise"] = max(0.0, min(100.0, b["exercise"] - EXERCISE_PER_DAY * h / 24.0 + self.move_rate(mode, sl) * h))

    def move_rate(self, mode, sl=None):
        """いま体を動かしている量 (1 時間あたり). 何をしているかから."""
        from .places import is_home, solo_kind
        app = self.app
        sl = sl or {}
        if mode == "out":
            kind = sl.get("kind")
            if kind == "jog":
                return MOVE_PER_H["jog"]
            place = app.presence.rec().get("place") or "town"
            if is_home(place):
                return MOVE_PER_H["other"]
            k = solo_kind(place)
            return MOVE_PER_H["walk"] if k == "walk" else MOVE_PER_H["see"] if k == "see" else \
                MOVE_PER_H["shop"] if k == "shopping" else MOVE_PER_H["other"]
        if mode == "work":
            return MOVE_PER_H["work"]
        if mode == "busy" and sl.get("kind") == "chores":
            return MOVE_PER_H["chores"]
        if mode in ("here", "idle"):
            cur = app.outdoor.current()
            if cur and cur["kind"] == "outing":      # 誰かとのお出かけ (散歩・ハイキングなど)
                return MOVE_PER_H["outing"]
        return 0.0

    def add_exercise(self, points):
        """まとめて体を動かした (行動パターンの外出・家事など)."""
        b = self.rec()
        b["exercise"] = max(0.0, min(100.0, b["exercise"] + float(points)))

    def stamina_cap(self):
        """体力の上限: 運動不足が続くと下がる (最大 25)."""
        return 100.0 - min(25.0, 3.0 * self.rec().get("lazy_days", 0))

    def level(self):
        return int(self.rec()["health"]["level"])

    def stamina_mult(self):
        """お腹がすいている・体調が悪いと, 体力が戻りにくい."""
        b = self.rec()
        s = b["satiety"]
        lazy = 0.9 if b.get("lazy_days", 0) >= 3 else 1.0          # 運動不足が続くと戻りにくい
        return (0.4 if s < 8 else 0.6 if s < 20 else 1.0) * HEALTH_MULT["stamina"][self.level()] * lazy

    def train_mult(self):
        return HEALTH_MULT["train"][self.level()]

    def work_mult(self):
        return HEALTH_MULT["work"][self.level()]

    # ------------------------------------------------------------------ 体調 (日付が変わったとき)
    def risk(self, t):
        """その日の過ごし方から, 体調を崩しやすさ (目安 0〜). 何が効いたかも返す."""
        from .outdoor import weather
        b = self.rec()
        td = b["today"]
        L = self.app.life
        why = {}
        for k in NUTRI:
            v = b["nutri"][k]
            if v < 20:
                why["nutri_" + k] = 0.04
            elif v < 35:
                why["nutri_" + k] = 0.015
        if td.get("hungry", 0) > 2:
            why["hungry"] = min(0.06, 0.01 * td["hungry"])
        slept = td.get("slept")
        if slept is not None and slept < 5:
            why["sleep"] = 0.06
        elif slept is not None and slept < 6.5:
            why["sleep"] = 0.02
        w3 = L.recent_work(3)
        if w3 > 30:
            why["work"] = 0.07
        elif w3 > 26:
            why["work"] = 0.035
        if L.stamina() < 15:
            why["stamina"] = 0.03
        wx = weather(datetime.fromtimestamp(t - 3600))
        if td.get("out", 0) > 1 and wx["id"] in ("rain", "snow"):
            why["weather"] = 0.02
        if datetime.fromtimestamp(t).month in (12, 1, 2):
            why["winter"] = 0.01
        if b.get("lazy_days", 0) >= 4:
            why["exercise"] = 0.015 if b["lazy_days"] < 10 else 0.03
        return 0.006 + sum(why.values()), why

    def daily(self, t):
        """日付が変わったとき: 体調が崩れる・こじれる・治る (その日の過ごし方と, 薬・病院しだい. 補正はしない)."""
        b = self.rec()
        hl = b["health"]
        lv = int(hl["level"])
        r, why = self.risk(t)
        td = b["today"]
        rest = (0.2 if td.get("slept", 0) >= 7 else 0.0) + min(0.2, 0.05 * td.get("rested", 0))
        med = hl.get("med_until", 0) > t
        rest += 0.15 if hl.get("care_until", 0) > t - 86400 else 0.0          # 看病してもらった
        note = None
        if lv == 0:
            if random.random() < min(0.5, r):
                hl.update(level=1, since=t)
                note = "体調を崩しかけている"
        else:
            heal = {1: 0.4, 2: 0.25, 3: 0.06}[lv] + rest + (0.3 if med and lv <= 2 else 0.08 if med else 0.0) - 1.5 * (r - 0.006)
            worse = 0.0 if lv >= 3 else (r - 0.006) * 3.0 + (0.08 if not rest else 0.0)
            x = random.random()
            if x < max(0.03, heal):
                hl["level"] = lv - 1
                note = "体調が少しよくなった" if lv > 1 else "体調が戻った"
                if hl["level"] == 0:
                    hl["since"] = None
            elif x < max(0.03, heal) + min(0.5, worse):
                hl["level"] = lv + 1
                note = "体調が悪くなった"
        hl["why"] = sorted(why, key=why.get, reverse=True)[:3]
        b["lazy_days"] = b.get("lazy_days", 0) + 1 if b["exercise"] < EXERCISE_LOW else max(0, b.get("lazy_days", 0) - 2)
        ps = self.app.life.player_state()
        ps["stamina"] = min(float(ps.get("stamina", 100)), self.stamina_cap())
        b["today"] = {}
        if note:
            self.app.solo.note("health", "%s（%s）" % (note, HEALTH_WORD[hl["level"]] or "いつもどおり"), t)
        return note

    def medicine(self, now=None):
        """風邪薬を飲む (持ち物). 一日ほど治りやすくなる (寝込むほどだと効きにくい)."""
        app = self.app
        now = now or time.time()
        if app.items.count(MEDICINE) <= 0:
            raise ValueError("風邪薬を持っていません（ドラッグストア・コンビニで買えます）")
        b = self.rec()
        app.items.add(MEDICINE, -1)
        b["health"]["med_until"] = now + 24 * 3600
        app.life.save_player()
        text = "風邪薬を飲んだ" + ("" if self.level() else "（特に悪いところはないけれど）")
        app.solo.note("health", text, now, id="h%d" % int(now * 1000), icon="💊", name="薬")
        return {"text": text}

    def clinic(self, now=None):
        """病院で診てもらう (行き先 clinic から戻ったとき). お金がかかる. 寝込むほどでも軽いところまで戻り, 薬ももらえる."""
        app = self.app
        now = now or time.time()
        lv = self.level()
        ps = app.life.player_state()
        fee = random.choice((1500, 2000, 2500)) + (1000 if lv >= 2 else 0)
        paid = min(fee, max(0, int(ps["money"])))
        ps["money"] -= paid
        app.life.ledger(now, -paid, "medical", "病院")
        hl = self.rec()["health"]
        if lv == 0:
            text = "病院で診てもらったが、特に悪いところはないと言われた"
        else:
            hl["level"] = 1
            hl["med_until"] = now + 48 * 3600
            app.items.add(MEDICINE, 2)
            text = "病院で診てもらい、薬をもらった。少し楽になった気がする"
        app.life.save_player()
        return {"text": "%s（%s円）" % (text, format(paid, ",")), "money": -paid}

    # ------------------------------------------------------------------ 食べる
    def _eat(self, t, how, label, nutri, full, price=0, where="", note=""):
        b = self.rec()
        before = b["satiety"]
        f = max(0.3, 1.0 - max(0.0, before - 60) / 60.0)        # お腹いっぱいのときは, あまり入らない
        b["satiety"] = min(100.0, before + full * f)
        for k in NUTRI:
            b["nutri"][k] = min(100.0, b["nutri"][k] + float(nutri.get(k, 0)) * NUTRI_GAIN * (0.5 + 0.5 * f))
        b["meals"].append({"t": t, "how": how, "label": label, "where": where, "price": price})
        del b["meals"][:-60]
        self.app.life.save_player()
        text = "%s%sを食べた%s" % (_meal_label(t) + "に" if how != "snack" else "", label,
                                 "（%s円）" % format(price, ",") if price else "") + (note and "。" + note)
        return {"text": text, "satiety": round(b["satiety"]), "how": how}

    def dishes(self):
        """いま作れる献立 (食材と料理スキルしだい) と, 作れない理由."""
        items = self.app.items
        sk = self.app.life.skill("cook")
        have = {n: items.count_nut(n) for n in NUTRI}
        out = []
        for did, name, need, req in DISHES:
            want = {n: need.count(n) for n in set(need)}
            miss = [NUTRI_LABEL[n] for n, c in want.items() if have[n] < c]
            out.append({"id": did, "name": name, "need": [NUTRI_LABEL[n] for n in need], "skill": req,
                        "ok": sk >= req and not miss, "why": ("料理スキルが足りない" if sk < req else "") or
                        ("%sの食材がない" % "・".join(miss) if miss else "")})
        return out

    def cook(self, did, now=None):
        """自炊. 持ち物の食材を使う. 料理スキルで出来ばえ (栄養の入り方)・失敗が変わる. 家でだけ."""
        app = self.app
        now = now or time.time()
        d = next((x for x in DISHES if x[0] == did), None)
        if not d:
            raise ValueError("その献立は作れません")
        if not self.at_home(now):
            raise ValueError("自炊は家でします")
        opt = next(x for x in self.dishes() if x["id"] == did)
        if not opt["ok"]:
            raise ValueError("%sは作れません（%s）" % (d[1], opt["why"]))
        r = self.cook_at(did, now)
        app.life.tire(2)
        app.solo.note("meal", r["text"], now, id="e%d" % int(now * 1000), icon="🍳", name="自炊")
        return r

    def at_home(self, now=None):
        app = self.app
        now = now or time.time()
        w = app.bonds.with_rec()
        return app.presence.rec().get("mode") in ("none", "busy") and not app.outdoor.current(now) \
            and not (w and w["mode"] in ("meet", "visit"))

    def here(self, now=None):
        """いる行き先 (一人の外出・誰かとのお出かけ). 家なら None."""
        cur = self.app.outdoor.current(now)
        return cur["place"] if cur else None

    def menu(self, place, now=None):
        from datetime import datetime as _dt
        from .places import open_state
        if place not in MENUS:
            return []
        if not open_state(place, _dt.fromtimestamp(now or time.time()))["open"]:
            return []
        return [{"id": m[0], "name": m[1], "price": m[2], "nutri": m[3], "full": m[4]} for m in MENUS[place]]

    def eat_at(self, mid, place=None, now=None, pay=True, log=True):
        """外食・買って食べる (いる行き先のメニューから). 値段は少し上下する. pay=False なら払いは呼び出し側 (誰かとの外食)."""
        app = self.app
        now = now or time.time()
        place = place or self.here(now)
        m = next((x for x in self.menu(place, now) if x["id"] == mid), None)
        if not m:
            raise ValueError("ここでは食べられません（閉まっているか、メニューにありません）")
        price = int(round(m["price"] * random.uniform(0.95, 1.08) / 10.0)) * 10
        if pay:
            ps = app.life.player_state()
            if ps["money"] < price:
                raise ValueError("お金が足りません（%s円）" % format(price, ","))
            ps["money"] -= price
            app.life.ledger(now, -price, "eatout" if place in EAT_OUT_PLACES else "food", "%s（%s）" % (m["name"], app.places.label(place)))
        how = "out" if place in EAT_OUT_PLACES else "buy"
        r = self._eat(now, how, m["name"], m["nutri"], m["full"], price if pay else 0, place)
        cur = app.presence.rec().get("solo")
        if cur:
            cur["ate"] = True
        if log:
            app.solo.note("meal", r["text"], now, id="e%d" % int(now * 1000), icon="🍽" if how == "out" else "🍙",
                          name="外食" if how == "out" else "買って食べる")
        r["price"] = price
        return r

    def pair_cost(self, place):
        """一緒に外食したときの費用の目安 (二人分. メニューの安いほう二つの平均 x 2)."""
        m = sorted(x[2] for x in MENUS.get(place) or [])[:2]
        return int(round(sum(m) / float(len(m)) * 2 / 100.0)) * 100 if m else 2000

    def eat_with(self, place, char, now=None):
        """誰かと外食したときの, あなたの食事 (払いは呼び出し側). 書き添えるナレーションを返す."""
        now = now or time.time()
        menu = MENUS.get(place) or MENUS["family"]
        m = random.choice(menu[:2])
        r = self._eat(now, "out", m[1], m[3], m[4], 0, place)
        self.app.solo.note("meal", "%sと%s" % (char.get("name", ""), r["text"]), now, id="e%d" % int(now * 1000), icon="🍽", name="外食")
        return "（%sを食べた）" % m[1]

    def cared(self, char, now=None):
        """そばにいる人が看病してくれた: お粥でお腹が少し満たされ, 半日ほど治りやすい."""
        now = now or time.time()
        b = self.rec()
        b["health"]["care_until"] = now + 12 * 3600
        r = self._eat(now, "cared", "%sの作ったお粥" % char.get("name", ""), {"staple": 6, "protein": 1, "veg": 1}, 25)
        return r

    def eat_item(self, iid, now=None):
        """買ってきたもの (お弁当・カップ麺) を家で食べる."""
        app = self.app
        now = now or time.time()
        if iid not in ITEM_MEALS or app.items.count(iid) <= 0:
            raise ValueError("それは持っていません")
        if not self.at_home(now):
            raise ValueError("家で食べます")
        app.items.add(iid, -1)
        from .items import CATALOG
        nutri, full = ITEM_MEALS[iid]
        r = self._eat(now, "item", CATALOG[iid]["name"], nutri, full)
        app.solo.note("meal", r["text"], now, id="e%d" % int(now * 1000), icon="🍱", name="食べる")
        return r

    def eat(self, how, mid, now=None):
        if how == "cook":
            return self.cook(mid, now)
        if how == "item":
            return self.eat_item(mid, now)
        return self.eat_at(mid, now=now)

    # ------------------------------------------------------------------ 行動パターン (オフライン) の食事
    def routine_meal(self, b, t):
        """行動パターンの「食事」1 回. 予定どおりにいかないこともある. (書くこと, 食べられたか)."""
        how = b.get("how") or "cook"
        try:
            if how == "cook":
                ok = [d for d in self.dishes() if d["ok"]]
                if not ok:
                    meal = next((i for i in ITEM_MEALS if self.app.items.count(i) > 0), None)
                    if meal:                    # 食材がない: 買い置きで済ませる
                        r = self.eat_item_at(meal, t)
                        return "食材がなくて自炊はできず、" + r["text"], True
                    return "食材がなくて、何も作れなかった（食べなかった）", False
                return self.cook_at(self.best_dish(ok)["id"], t)["text"], True
            place = b.get("place") or ("teishoku" if how == "out" else "convenience")
            menu = self.menu(place, t)
            if not menu:
                from .places import open_state
                o = open_state(place, datetime.fromtimestamp(t))
                return "%sは%s（%s）ので、食べなかった" % (self.app.places.label(place), "閉まっていた" if not o["open"] else "やっていなかった",
                                                    o["note"]), False
            ps = self.app.life.player_state()
            afford = [m for m in menu if m["price"] <= ps["money"]]
            if not afford:
                return "お金が足りなくて、%sでは食べられなかった" % self.app.places.label(place), False
            m = random.choice(afford[:2])
            return self.eat_at(m["id"], place, t, log=False)["text"], True
        except ValueError as e:
            return "食べられなかった（%s）" % e, False

    def best_dish(self, ok):
        """作れる献立のうち, いま足りないものを補えるもの (行動パターンの自炊で選ぶ)."""
        n = self.rec()["nutri"]
        lab = {v: k for k, v in NUTRI_LABEL.items()}
        return max(ok, key=lambda d: (sum(100 - n[lab[x]] for x in d["need"]), d["skill"]))

    def cook_at(self, did, t):
        """行動パターンの自炊 (家にいる扱い. 在席の確かめはしない)."""
        d = next(x for x in DISHES if x[0] == did)
        sk = self.app.life.skill("cook")
        for n in d[2]:
            self.app.items.use_nut(n)
        q = 0.75 + sk / 200.0 * random.uniform(0.8, 1.2)
        fail = random.random() < max(0.0, 0.22 - sk / 180.0)
        nutri = {}
        for n in d[2]:
            nutri[n] = nutri.get(n, 0) + 13.0 * q
        self.app.life.train("cook", 0.6)
        self.app.home.add(dishes=8)
        return self._eat(t, "cook", d[1], nutri, (30 + 10 * len(d[2])) * (0.6 if fail else 1.0),
                         note="少し焦がしてしまった" if fail else "")

    def eat_item_at(self, iid, t):
        self.app.items.add(iid, -1)
        from .items import CATALOG
        nutri, full = ITEM_MEALS[iid]
        return self._eat(t, "item", CATALOG[iid]["name"], nutri, full)

    # ------------------------------------------------------------------ 画面
    @staticmethod
    def hunger_word(s):
        return "お腹がぺこぺこ" if s < 10 else "お腹がすいた" if s < 30 else "少し小腹がすいた" if s < 50 else \
            "お腹は落ち着いている" if s < 85 else "お腹いっぱい"

    def nutri_words(self):
        """数日分の偏りを, 自覚できる言葉で (はっきりした不足だけ)."""
        n = self.rec()["nutri"]
        out = []
        for k in NUTRI:
            if n[k] < 15:
                out.append("%sがかなり足りていない気がする" % NUTRI_LABEL[k])
            elif n[k] < 35:
                out.append("%sが足りていない気がする" % NUTRI_LABEL[k])
        return out

    def view(self, now=None):
        now = now or time.time()
        b = self.rec()
        place = self.here(now)
        items = [{"id": i, "name": self.app.items.catalog_name(i), "count": self.app.items.count(i)} for i in ITEM_MEALS
                 if self.app.items.count(i) > 0]
        last = b["meals"][-1] if b["meals"] else None
        hl = b["health"]
        health = {"level": int(hl["level"]), "word": HEALTH_WORD[int(hl["level"])], "since": hl.get("since"),
                  "medicine": self.app.items.count(MEDICINE), "med": hl.get("med_until", 0) > now}
        ex = b["exercise"]
        health["exercise"] = "体がなまっている気がする" if b.get("lazy_days", 0) >= 3 else \
            "最近あまり体を動かしていない" if ex < EXERCISE_LOW else "よく体を動かしている" if ex > 75 else ""
        health["cap"] = round(self.stamina_cap())
        return {"health": health, "hunger": self.hunger_word(b["satiety"]), "satiety_low": b["satiety"] < 30, "nutri": self.nutri_words(),
                "home": self.at_home(now), "dishes": self.dishes(), "items": items,
                "place": place, "place_label": self.app.places.label(place) if place else "",
                "menu": self.menu(place, now) if place else [],
                "last": {"t": last["t"], "label": last["label"]} if last else None}
