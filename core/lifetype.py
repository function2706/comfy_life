"""生活の型: キャラクターごとの暮らし方 (会社員・シフト勤務・夜勤・学生・在宅・販売/サービス業) と, そこから作る基本の予定.

- 予定の形式 (定義の schedule の 1 行) は変えない. 型は「その schedule を作る元」として定義に life を足すだけ
  (schedule を読んでいる所 — engine._base_scene・rhythm・knowsched・appoint など — はそのまま動く).
- 定義の life: {type, v, src, seed, chrono, off, slot, workplace}.
  src: given (既定のキャラ. 予定は手書きのまま) / text (性格の文に職の言葉があった) / lottery (年齢で絞ったくじ) /
       custom (手で書き換えた予定. 作り直さない. 型は仕事の枠から近いものを当てるだけ).
- build(char): life から schedule を作る. 同じ life なら同じ予定 (くじは seed から決める. 移行が途中で止まってやり直しても同じ).
- 寝起きのずれ chrono (分. + が夜型): 性格の traits.chrono (−1 朝型 〜 +1 夜型) × 60 + 人ごとの揺らぎ ±30.
  型の仕事に間に合う範囲で止める. 日ごとのずれ (core/rhythm.py) はこの上にそのまま乗る.
- 日をまたぐ枠 (夜勤・夜ふかしの睡眠) は 0:00 で 2 行に割る (後半の行に cont: true). day_match は見ている時刻の曜日で引くため.
- シフトの曜日は人ごとに違うが, 週ごとには変えない (「火曜の夕方はバイトらしい」が成り立たなくなるため).
- 型は画面に出さない (分かるのは, 聞いた予定・返信の遅い時間帯・店で働いているのに出会う, から).

移行 (更新後の起動で一度だけ):
- 定義 (全体. migrate_defs): life の無い定義に life を付ける. 既定のキャラ (ひな) は予定をそのまま. 予定がひなの写し・空の人は
  型を決めて作り直す (元の予定は schedule_old に残す). 手で書き換えた予定は作り直さない.
- ワールド (ワールドごと. world_step): 作り直した人の「知っている予定」と, 覚えた日ごとのずれを消す. 決まっている約束は
  新しい予定で都合がつかなければ, 相手から別の日時を打診してくる (appoint.relife_mark → appoint.live).
"""
import copy
import json
import os
import random

from . import places as places_mod
from . import store

V = 1
FIXED = None              # テスト用: 型を決め打ちにする (tools/testclock.py. 昼に手が空いている型で, 既存のテストの前提を変えない)
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY = 1440
STEP = 5

# 勤め先にできる店 (シフト・学生のバイト / 販売・サービス業). 開いている時間 (分) は places.HOURS から
SHIFT_SHOPS = ("supermarket", "convenience", "drugstore", "bookstore", "cafe", "family", "fastfood")
SERVICE_SHOPS = ("mall", "electronics", "bookstore", "restaurant", "cafe", "drugstore")
SHOP_POS = {"supermarket": "supermarket", "convenience": "convenience store", "drugstore": "drugstore", "bookstore": "bookstore",
            "electronics": "electronics store", "mall": "shopping mall, clothing store", "cafe": "cafe, waitress",
            "family": "family restaurant, waitress", "fastfood": "fast food restaurant, counter", "restaurant": "restaurant, waitress"}
HOBBIES = (("趣味のお絵かき", "bedroom, drawing, sketchbook, sitting at desk"), ("読書の時間", "living room, reading book, sitting on sofa"),
           ("ゲームをしている", "bedroom, playing video game, holding controller"), ("映画を観ている", "living room, watching tv, sitting on sofa"),
           ("部屋の片付け", "bedroom, cleaning, tidying up"), ("おやつを作っている", "kitchen, baking, apron"),
           ("音楽を聴いている", "bedroom, headphones, listening to music"), ("ストレッチをしている", "living room, stretching, yoga mat"))

# 型: label / くじの重み / 合う年齢 / 寝起きの基本 (起きる, 寝る. 分) / pay・cost は所持金の収支 (A17 段 3) で使う
TYPES = {
    "office": {"label": "会社員", "weight": 34, "age": (20, 99), "sleep": (390, 1410),
               "pay": {"kind": "monthly", "rate": 1.15, "payday": 25, "bonus": (6, 12)}, "cost": {"home": 1.1, "living": 1.0}},
    "shift": {"label": "シフト勤務", "weight": 16, "age": (18, 99), "sleep": (420, 1440),
              "pay": {"kind": "hourly", "rate": 0.8, "payday": 15}, "cost": {"home": 0.85, "living": 0.9}},
    "night": {"label": "夜勤", "weight": 7, "age": (20, 99), "sleep": (930, 1920),
              "pay": {"kind": "monthly", "rate": 1.2, "payday": 25, "bonus": (7, 12)}, "cost": {"home": 1.0, "living": 1.0}},
    "student": {"label": "学生", "weight": 14, "age": (18, 24), "sleep": (420, 1470),
                "pay": {"kind": "hourly", "rate": 0.45, "payday": 10, "allowance": 1}, "cost": {"home": 0.7, "living": 0.8}},
    "freelance": {"label": "在宅・フリーランス", "weight": 12, "age": (22, 99), "sleep": (510, 1530),
                  "pay": {"kind": "irregular", "rate": 1.0}, "cost": {"home": 1.0, "living": 1.0}},
    "service": {"label": "販売・サービス業", "weight": 17, "age": (18, 99), "sleep": (420, 1440),
                "pay": {"kind": "monthly", "rate": 0.95, "payday": 25, "bonus": (7,)}, "cost": {"home": 0.95, "living": 1.0}},
}
# 性格の文 (persona) の職の言葉 → 型 (文面と食い違わせない). 上から順に見る
TEXT_HINTS = (("night", ("夜勤", "看護")), ("student", ("大学生", "学生", "専門学校", "院生")),
              ("freelance", ("在宅", "フリーランス", "イラストレーター", "漫画家", "作家", "ライター", "配信者")),
              ("service", ("店員", "販売", "ショップ", "美容師", "接客")), ("shift", ("フリーター", "パート", "アルバイト")),
              ("office", ("会社員", "OL", "事務", "社会人", "公務員")))


def _r5(x):
    return int(round(x / float(STEP)) * STEP)


def _hm(m):
    m = int(m)
    return "%02d:%02d" % (m // 60, m % 60)


def _mins(s):
    h, m = str(s or "00:00").split(":")
    return int(h) * 60 + int(m)


def shop_hours(pid):
    """店の (開く, 閉まる, 定休日). 載っていない店 (コンビニ) は 7:00〜23:00 として勤務を組む."""
    h = places_mod.HOURS.get(pid)
    if not h:
        return 420, 1380, []
    return _mins(h["open"]), _mins(h["close"]), list(h.get("closed_days") or [])


# ---------------------------------------------------------------------- 場面
def _scene(activity, label, location, pos, effects=None, outfit="", **flags):
    s = {"activity": activity, "label": label, "location": location, "outfit": outfit, "pos": pos, "neg": "", "effects": effects or {}}
    s.update(flags)
    return s


SLEEP = _scene("sleep", "就寝中", "寝室", "sleeping, lying on bed, closed eyes, bedroom, blanket", {"energy": 12, "sleepiness": -13},
               "pajamas", asleep=True)
MORNING = _scene("morning", "身支度中", "洗面所", "bathroom, mirror, brushing hair, morning routine", {"hygiene": 30}, "pajamas")
LUNCH = _scene("lunch", "お昼ごはん", "ダイニング", "eating lunch, dining table", {"satiety": 60, "hydration": 30})
COOKING = _scene("cooking", "夕飯の支度", "キッチン", "kitchen, cooking, frying pan", {}, "apron, casual clothes")
DINNER = _scene("dinner", "夕ごはん", "ダイニング", "eating dinner, dining table, rice bowl, miso soup", {"satiety": 70, "hydration": 40})
BATH = _scene("bath", "入浴中", "浴室", "hallway, bathroom door, steam", {"hygiene": 120, "stress": -10}, busy=True)
NIGHT = _scene("night", "寝る前のひととき", "自室", "bedroom, sitting on bed, reading book", {}, "pajamas")
ERRAND = _scene("errand", "買い物に出ている", "商店街", "outdoors, shopping street, walking, holding shopping bag", {"boredom": -6}, away=True)


def _breakfast(m):
    label = "朝ごはん" if m < 570 else "遅めの朝ごはん" if m < 690 else "起きてからの食事"
    return _scene("breakfast", label, "ダイニング", "eating breakfast, dining table, toast, coffee cup", {"satiety": 70, "hydration": 45}, "pajamas")


class _Week:
    """一週間 (7 日 × 5 分刻み) に場面を塗る. 先に塗ったものが優先 (あとからは空いている所だけ)."""

    def __init__(self):
        self.slots = [[None] * (DAY // STEP) for _ in range(7)]
        self.blocks = []

    def _cells(self, d, a, b):
        for m in range(int(a), int(b), STEP):
            yield (d + m // DAY) % 7, (m % DAY) // STEP

    def free(self, d, a, b):
        return b > a and all(self.slots[x][i] is None for x, i in self._cells(d, a, b))

    def paint(self, d, a, b, scene, fit=False):
        """日 d の a〜b 分 (1440 を超えたら翌日へ) に塗る. fit: 全部空いているときだけ. 塗れたら True."""
        a, b = _r5(a), _r5(b)
        if b <= a or (fit and not self.free(d, a, b)):
            return False
        self.blocks.append(scene)
        k = len(self.blocks) - 1
        done = False
        for x, i in self._cells(d, a, b):
            if self.slots[x][i] is None:
                self.slots[x][i] = k
                done = True
        return done

    def rows(self):
        """schedule の行に. 同じ中身の枠は曜日をまとめる. 日をまたいだ後半には cont."""
        found, order = {}, []
        for d in range(7):
            sl = self.slots[d]
            i = 0
            while i < len(sl):
                k = sl[i]
                j = i
                while j < len(sl) and sl[j] == k:
                    j += 1
                if k is not None:
                    e = dict(self.blocks[k])
                    e["from"], e["to"] = _hm(i * STEP), _hm(j * STEP)
                    if i == 0 and self.slots[(d - 1) % 7][-1] == k:      # 前の日から続いている (同じ一塗り)
                        e["cont"] = True
                    key = json.dumps(e, ensure_ascii=False, sort_keys=True)
                    if key not in found:
                        found[key] = (e, [])
                        order.append(key)
                    found[key][1].append(d)
                i = j
        out = []
        for key in order:
            e, ds = found[key]
            out.append(dict({"days": days_spec(ds)}, **e))
        out.sort(key=lambda e: (not e.get("asleep"), e["from"], e["days"]))
        return out


def days_spec(ds):
    ds = sorted(set(ds))
    if len(ds) == 7:
        return "all"
    if ds == [0, 1, 2, 3, 4]:
        return "weekday"
    if ds == [5, 6]:
        return "weekend"
    return ",".join(DAYS[d] for d in ds)


# ---------------------------------------------------------------------- 型を決める
def type_from_text(text):
    for tid, words in TEXT_HINTS:
        if any(w in (text or "") for w in words):
            return tid
    return None


def pick_type(rnd, age):
    age = int(age or 25)
    pool = [(tid, t["weight"]) for tid, t in TYPES.items() if t["age"][0] <= age <= t["age"][1]] or [("office", 1)]
    return rnd.choices([p[0] for p in pool], [p[1] for p in pool])[0]


def decide(char, traits=None, seed=None, type_id=None, src=None):
    """その人の life を決める (同じ seed・同じ人なら同じ結果). traits: 性格の傾向 (chrono を見る)."""
    seed = str(seed or char.get("id") or char.get("name") or "x")
    rnd = random.Random("life:%s" % seed)
    tid, how = type_id, src
    if not tid and FIXED:
        tid, how = FIXED, "lottery"
    if not tid:
        tid = type_from_text(char.get("persona"))
        how = "text" if tid else None
    lot = pick_type(rnd, char.get("age"))           # くじは必ず引く (型が文から決まっても, あとの乱数の並びを変えない)
    if not tid:
        tid, how = lot, "lottery"
    chrono = _r5(float((traits or {}).get("chrono", 0)) * 60 + rnd.uniform(-30, 30))
    life = {"type": tid, "v": V, "src": how or "lottery", "seed": seed, "chrono": chrono}
    days = list(range(7))
    if tid == "shift":
        wp = rnd.choice(SHIFT_SHOPS)
        closed = shop_hours(wp)[2]
        off = set(closed)
        n_off = rnd.choice((2, 2, 3))
        while len(off) < n_off:
            off.add(rnd.choice(days))
        life.update(off=[DAYS[d] for d in sorted(off)], slot=rnd.choice((0, 1)), workplace=wp)
    elif tid == "service":
        wp = rnd.choice(SERVICE_SHOPS)
        closed = [d for d in shop_hours(wp)[2] if d < 5]
        off = set(closed)
        while len(off) < 2:
            off.add(rnd.choice(days[:5]))           # 土日は仕事. 休みは平日 2 日
        life.update(off=[DAYS[d] for d in sorted(off)], slot=rnd.choice((0, 0, 1)), workplace=wp)
    elif tid == "night":
        off = set()
        n_off = rnd.choice((2, 3))
        while len(off) < n_off:
            off.add(rnd.choice(days))
        life.update(off=[DAYS[d] for d in sorted(off)], slot=0, workplace="convenience" if rnd.random() < 0.3 else None)
    elif tid == "student":
        life.update(off=[rnd.choice(DAYS[:5])] if rnd.random() < 0.5 else [], slot=rnd.choice((0, 1)), workplace=rnd.choice(SHIFT_SHOPS))
    elif tid == "freelance":
        off = set()
        while len(off) < 2:
            off.add(rnd.choice(days))
        life.update(off=[DAYS[d] for d in sorted(off)], slot=rnd.choice((0, 1, 2, 3)), workplace=None)
    else:
        life.update(off=["sat", "sun"], slot=rnd.choice((0, 1, 1, 2)), workplace=None)
    return life


# ---------------------------------------------------------------------- 予定を作る
def _work_plan(char, life, rnd):
    """曜日ごとの仕事など [(始まり, 終わり, 行き帰りの分, [(a, b, 場面), …])]. 始まり・終わりは家を出てから戻るまでを除いた本体."""
    tid = life["type"]
    off = {DAYS.index(d) for d in life.get("off") or [] if d in DAYS}
    out_fit = char.get("outfit_outing") or ""
    wp = life.get("workplace")
    plan = {}
    if tid == "office":
        s = 510 + 30 * int(life.get("slot", 1))
        work = _scene("work", "仕事中", "職場", "office, sitting at desk, computer, working", {"energy": -6, "boredom": -3}, out_fit, away=True)
        rest = _scene("lunch", "昼休み", "職場", "office, eating lunch, lunch box", {"satiety": 60, "hydration": 30}, out_fit, away=True)
        for d in range(7):
            if d not in off:
                plan[d] = (s, s + 540, 45, [(s, 720, work), (720, 780, rest), (780, s + 540, work)])
    elif tid in ("shift", "service"):
        o, c, closed = shop_hours(wp)
        length = 450 if tid == "shift" else 510
        s = max(o, 420) if not int(life.get("slot", 0)) else min(c, DAY) - length
        label = "%sで%s" % (places_mod.PLACES[wp]["label"], "バイト中" if tid == "shift" else "仕事中")
        work = _scene("parttime" if tid == "shift" else "work", label, places_mod.PLACES[wp]["label"],
                      "%s, working, apron, store clerk" % SHOP_POS.get(wp, "shop"), {"energy": -6, "boredom": -4}, "apron, casual clothes",
                      away=True, workplace=wp)
        rest = _scene("lunch", "休憩中", places_mod.PLACES[wp]["label"], "break room, sitting, eating, drinking tea",
                      {"satiety": 55, "hydration": 30}, "apron, casual clothes", away=True)
        mid = _r5(s + length / 2.0 - 20)
        for d in range(7):
            if d not in off and d not in closed:
                plan[d] = (s, s + length, 30, [(s, mid, work), (mid, mid + 45, rest), (mid + 45, s + length, work)])
    elif tid == "night":
        label = "%sで夜勤中" % places_mod.PLACES[wp]["label"] if wp else "夜勤中"
        work = _scene("work", label, places_mod.PLACES[wp]["label"] if wp else "職場",
                      "%s, night, working" % (SHOP_POS.get(wp, "workplace") if wp else "workplace"), {"energy": -7, "boredom": -3},
                      "apron, casual clothes" if wp else out_fit, away=True, **({"workplace": wp} if wp else {}))
        rest = _scene("lunch", "休憩中", "職場", "break room, sitting, eating, night", {"satiety": 55, "hydration": 30}, out_fit, away=True)
        for d in range(7):
            if d not in off:
                plan[d] = (1320, 1800, 45, [(1320, 1560, work), (1560, 1605, rest), (1605, 1800, work)])
    elif tid == "student":
        cls = _scene("class", "大学で講義中", "大学", "classroom, sitting at desk, taking notes", {"hydration": 2}, out_fit, away=True)
        rest = _scene("lunch", "学食でお昼", "大学", "cafeteria, eating lunch", {"satiety": 60, "hydration": 30}, out_fit, away=True)
        o, c, closed = shop_hours(wp)
        label = "%sでバイト中" % places_mod.PLACES[wp]["label"]
        job = _scene("parttime", label, places_mod.PLACES[wp]["label"], "%s, working, apron, store clerk" % SHOP_POS.get(wp, "shop"),
                     {"energy": -6, "boredom": -4}, "apron, casual clothes", away=True, workplace=wp)
        kinds = {}
        for d in range(5):
            if d not in off:
                k = rnd.choice(("full", "full", "am", "pm"))
                kinds[d] = k
                segs = {"full": [(530, 720, cls), (720, 780, rest), (780, 970, cls)], "am": [(530, 720, cls)], "pm": [(780, 970, cls)]}[k]
                plan[d] = (segs[0][0], segs[-1][1], 40, segs)
        if int(life.get("slot", 0)):          # 平日の夕方のバイト (講義のあと)
            ev = [d for d in range(5) if d not in closed and kinds.get(d) != "pm"]
            rnd.shuffle(ev)
            s = min(1050, c - 210)
            for d in sorted(ev[:rnd.choice((2, 3))]):
                if d in plan:
                    a, _, _, segs = plan[d]
                    plan[d] = (a, s + 210, 40, segs + [(s, s + 210, job)])
                else:
                    plan[d] = (s, s + 210, 30, [(s, s + 210, job)])
        else:                                   # 週末の昼のバイト
            we = [d for d in (5, 6) if d not in closed]
            rnd.shuffle(we)
            s = max(o, 600)
            for d in we[:rnd.choice((1, 2))]:
                plan[d] = (s, s + 300, 30, [(s, s + 300, job)])
    elif tid == "freelance":
        s = _r5(max(540, min(840, 600 + 60 * int(life.get("slot", 1)) + int(life.get("chrono", 0)) / 2.0)))
        work = _scene("work", "家で仕事中", "自室", "bedroom, sitting at desk, computer, working", {"energy": -4, "boredom": -2}, busy=True)
        for d in range(7):
            if d not in off:
                plan[d] = (s, s + 480, 0, [(s, s + 210, work), (s + 270, s + 480, work)])
    return plan


def build(char):
    """life から基本の予定 (schedule の行のリスト) を作る."""
    life = char.get("life") or {}
    tid = life.get("type")
    if tid not in TYPES:
        raise ValueError("生活の型がありません: %s" % tid)
    rnd = random.Random("build:%s:%s" % (life.get("seed") or char.get("id"), tid))
    chrono = int(life.get("chrono", 0))
    plan = _work_plan(char, life, rnd)
    wk = _Week()
    out_fit = char.get("outfit_outing") or ""
    wake, bed, limit, home = [0] * 7, [0] * 7, [None] * 7, [None] * 7
    if tid == "night":
        j = max(-30, min(30, chrono))
        for d in range(7):
            worked = (d - 1) % 7 in plan             # 前の晩から朝まで働いた日
            wake[d] = (930 if worked else 690) + j
            bed[d] = DAY + (480 if d in plan else 210) + j
    else:
        base_w, base_b = TYPES[tid]["sleep"]
        for d in range(7):
            if d in plan:
                s, e, go, _ = plan[d]
                limit[d] = s - go - 100            # 身支度・朝ごはん・出かける準備に間に合う時刻
                home[d] = e + go
            t = base_w + chrono + (0 if d in plan and plan[d][0] < 720 else 60 + (30 if chrono > 0 else 0))
            wake[d] = _r5(max(300, min(t, limit[d]) if limit[d] is not None else t))
        for d in range(7):
            n = (d + 1) % 7
            b = min(max(base_b + chrono, wake[n] + DAY - 540), wake[n] + DAY - 375)
            if home[d] is not None:
                b = max(b, home[d] + 30)
            if wake[n] + DAY - b < 360:               # 帰りが遅い: 翌朝を遅らせる. 遅らせられなければ, 帰ってすぐ寝る
                if limit[n] is None or b - DAY + 400 <= limit[n]:
                    wake[n] = _r5(b - DAY + 400)
                else:
                    b = wake[n] + DAY - 360
            bed[d] = _r5(b)
    for d in range(7):                                # 睡眠 (最優先)
        wk.paint(d, bed[d], DAY + wake[(d + 1) % 7], SLEEP)
    commute = _scene("commute", "移動中", "移動中", "outdoors, street, walking, holding bag", {}, out_fit, away=True)
    ready = _scene("getready", "出かける準備", "自室", "bedroom, getting ready, holding bag", {}, out_fit)
    for d, (s, e, go, segs) in sorted(plan.items()):  # 仕事・講義と, 行き帰り
        for a, b, sc in segs:
            wk.paint(d, a, b, sc)
        if go:
            wk.paint(d, s - go, s, dict(commute, label="通学中" if segs[0][2].get("activity") == "class" else "通勤中", location="行き道"))
            wk.paint(d, e, e + go, dict(commute, label="帰宅中", location="帰り道"))
            for i in range(len(segs) - 1):            # 講義とバイトのあいだ: 短ければそのまま向かう. 長ければいったん家に帰る
                a, b = segs[i][1], segs[i + 1][0]
                if b - a <= 0:
                    continue
                if b - a <= 120:
                    wk.paint(d, b - min(go, b - a), b, dict(commute, label="移動中"))
                    wk.paint(d, a, b, _scene("errand", "外で時間をつぶしている", "街", "outdoors, street, cafe, sitting", {}, out_fit, away=True))
                else:
                    wk.paint(d, a, a + go, dict(commute, label="帰宅中", location="帰り道"))
                    wk.paint(d, b - go, b, dict(commute, label="移動中", location="行き道"))
            wk.paint(d, s - go - 40, s - go, ready, fit=True)
    hobby = rnd.choice(HOBBIES)
    hobby2 = rnd.choice(HOBBIES)
    days_off = [d for d in range(7) if d not in plan]
    errand_day = rnd.choice(days_off) if days_off else None
    for d in range(7):                                # 暮らしの決まりごと (空いている所だけ)
        w, b = wake[d], bed[d]
        wk.paint(d, w, w + 25, MORNING, fit=True)
        wk.paint(d, w + 25, w + 60, _breakfast(w + 25), fit=True)
        if w + 60 <= 690 and b > 840:
            wk.paint(d, 720, 780, LUNCH, fit=True) or (tid == "freelance" and d in plan and
                                                         wk.paint(d, plan[d][0] + 210, plan[d][0] + 270, LUNCH, fit=True))
        if b > 1260 and w < 960:
            if not (wk.paint(d, 1050, 1110, COOKING, fit=True) and wk.paint(d, 1110, 1155, DINNER, fit=True)):
                h = home[d] if home[d] is not None else 1110
                for a in (1110, h + 15, h + 45, 1200, 1230):
                    if a + 45 <= b - 90 and wk.paint(d, a, a + 45, DINNER, fit=True):
                        break
        elif tid == "night":
            wk.paint(d, 1140, 1185, DINNER, fit=True)
        wk.paint(d, b - 80, b - 35, BATH, fit=True) or wk.paint(d, b - 50, b - 5, BATH, fit=True)
        wk.paint(d, b - 35, b, NIGHT, fit=True)
        if d not in plan:
            if d == errand_day:
                wk.paint(d, max(630, w + 90), max(630, w + 90) + 90, ERRAND, fit=True)
            hb = hobby if d % 2 == 0 else hobby2
            wk.paint(d, max(840, w + 150), max(840, w + 150) + 120,
                     _scene("hobby", hb[0], "自室" if "bedroom" in hb[1] else "リビング", hb[1], {"boredom": -15, "stress": -5}), fit=True)
    return wk.rows()


def default_activity():
    return {"activity": "relax", "label": "くつろぎ中", "location": "リビング", "pos": "living room, sitting on sofa, relaxing", "neg": "",
            "effects": {"hydration": 3}}


def assign(char, traits=None, seed=None, type_id=None):
    """新しい人に life と予定を付ける (定義を書き換える. 保存は呼ぶ側)."""
    char["life"] = decide(char, traits, seed=seed, type_id=type_id)
    char["schedule"] = build(char)
    if not char.get("default_activity"):
        char["default_activity"] = default_activity()
    return char


# ---------------------------------------------------------------------- 手で書いた予定から型を当てる
def _sig(sched):
    return {(e.get("days"), e.get("from"), e.get("to"), e.get("activity")) for e in sched or []}


def like(a, b):
    """二つの予定がほぼ同じか (曜日・時刻・活動の組の重なりが 8 割以上). 以前の既定の写し (少し古い版) も写しとみなす."""
    sa, sb = _sig(a), _sig(b)
    if not sa or not sb:
        return False
    return len(sa & sb) / float(len(sa | sb)) >= 0.8


def guess_type(char):
    """手で書いた予定の, 仕事の枠から近い型 (所持金の収支のためだけ. 予定は変えない)."""
    from .rhythm import WORK_ACTS, WORK_WORDS
    sched = char.get("schedule") or []
    if any(e.get("activity") == "class" or "講義" in (e.get("label") or "") or "授業" in (e.get("label") or "") for e in sched):
        return "student"
    work = [e for e in sched if e.get("activity") in WORK_ACTS or any(w in (e.get("label") or "") for w in WORK_WORDS)]
    if not work:
        return type_from_text(char.get("persona")) or ("student" if int(char.get("age") or 25) <= 22 else "freelance")
    if any(_mins(e.get("from")) >= 1260 or _mins(e.get("to") or "24:00") <= 420 for e in work):
        return "night"
    if all(not e.get("away") for e in work):
        return "freelance"
    days = set()
    for e in work:
        spec = (e.get("days") or "all").lower()
        days |= set(range(7)) if spec in ("all", "", "*") else set(range(5)) if spec == "weekday" else {5, 6} if spec == "weekend" \
            else {DAYS.index(x.strip()) for x in spec.split(",") if x.strip() in DAYS}
    if {5, 6} <= days and len(days) < 7:
        return "service"
    if days and days <= set(range(5)) and len(days) >= 4 and all(480 <= _mins(e.get("from")) and _mins(e.get("to") or "24:00") <= 1170 for e in work):
        return "office"
    return "shift"


# ---------------------------------------------------------------------- 移行 (定義. 全体で一度)
def _default_defs():
    out = {}
    for cid in store.default_character_ids():
        c = store.load(os.path.join(store.DEFAULTS, "characters", cid + ".json"))
        if c:
            out[cid] = c
    return out


def defs_pending():
    """life の無い定義があるか (起動時の移行が要るか)."""
    return any("life" not in c for c in store.all_characters().values())


def migrate_defs():
    """life の無い定義に life を付ける. 予定が既定 (ひな) の写し・空の人は, 型を決めて作り直す (元は schedule_old).
    既定のキャラと, 手で書き換えた予定はそのまま. 済んだ定義には何もしない (何度呼んでも同じ). 作り直した id のリストを返す."""
    chars = store.all_characters()
    todo = [c for c in chars.values() if "life" not in c]
    if not todo:
        return []
    defaults = _default_defs()
    personas = store.load_personas()
    refs = [d.get("schedule") or [] for d in defaults.values()] + [chars[k].get("schedule") or [] for k in defaults if k in chars]
    remade = []
    for c in todo:
        cid = c["id"]
        tr = (personas.get(c.get("persona_id") or "") or {}).get("traits") or {}
        sched = c.get("schedule") or []
        if cid in defaults:                                   # 既定のキャラ: 予定は手書きで, 性格の文とも合っている
            c["life"] = dict(decide(c, tr, type_id=(defaults[cid].get("life") or {}).get("type") or guess_type(c)), src="given")
        elif not sched or any(like(sched, r) for r in refs):  # 写し・空: 作り直す
            c["schedule_old"] = copy.deepcopy(sched)
            assign(c, tr)
            remade.append(cid)
        else:                                                 # 手で書き換えた予定: 作り直さない
            c["life"] = dict(decide(c, tr, type_id=guess_type(c)), src="custom")
        store.save_character(c)
    return remade


def ensure(app, c, old=None):
    """定義を保存するとき: life が無ければ付ける. 予定を手で書き換えたら src を custom に (作り直さない)."""
    if old:
        for k in ("life", "schedule_old"):
            if k not in c and k in old:
                c[k] = copy.deepcopy(old[k])
    tr = (app.personas.get(c.get("persona_id") or "") or {}).get("traits") or {}
    if "life" not in c:
        if c.get("schedule"):
            c["life"] = dict(decide(c, tr, type_id=guess_type(c)), src="custom")
        else:
            assign(c, tr)
    elif old and (c.get("life") or {}).get("src") in ("lottery", "text") and old.get("schedule") is not None \
            and json.dumps(old.get("schedule"), sort_keys=True) != json.dumps(c.get("schedule"), sort_keys=True):
        c["life"] = dict(c["life"], src="custom", type=guess_type(c) if c.get("schedule") else c["life"].get("type"))
    return c


# ---------------------------------------------------------------------- 移行 (ワールドごと. 開いたとき一度)
def remade_here(app):
    """このワールドにいる, 移行で予定を作り直した人."""
    return [cid for cid, c in app.chars.items() if "schedule_old" in c and (c.get("life") or {}).get("src") in ("lottery", "text")]


def world_step(app, now=None):
    """このワールドの記録を, 作り直した予定に合わせる (一度だけ): 知っている予定と覚えた日ごとのずれを消す・
    登録を尋ねている途中の人の予定も作り直す・決まっている約束の点検 (都合がつかなければ相手から打診. appoint.relife_mark).
    作り直した人の id のリストを返す (済んでいれば None)."""
    import time
    now = now or time.time()
    ps = app.life.player_state()
    if int(ps.get("life_v", 0)) >= V:
        return None
    ps["life_v"] = V
    enc = ps.get("encounter")
    if enc and isinstance(enc.get("char"), dict) and "life" not in enc["char"]:
        src = enc.get("src") or {}
        d = store.all_characters().get(src.get("id")) if src.get("type") == "def" else None
        if d and "life" in d:                              # すでにある定義の人: いまの定義の予定に
            enc["char"].update(life=copy.deepcopy(d["life"]), schedule=copy.deepcopy(d.get("schedule") or []))
        else:
            c = enc["char"]
            tr = (app.personas.get(c.get("persona_id") or "") or {}).get("traits") or {}
            assign(c, tr, seed="%s:%s" % (c.get("name", ""), int(enc.get("t", 0))))
    app.life.save_player()
    ids = remade_here(app)
    for cid in ids:
        st = app.state(cid)
        st["known"] = [k for k in st.get("known") or [] if k.get("kind") != "schedule"]
        st.pop("sched_told", None)
        st.pop("rhythm", None)
        app.save_state(cid)
    marked = app.appoint.relife_mark(ids, now) if ids else 0
    if ids and (len(app.solo.mylog()) or any(app.log(cid) for cid in ids)):      # 始めたばかりのワールドには書かない
        app.solo.note("home", "みんなの暮らしぶりが、少し変わったようだ（前に聞いた予定は、もう当てにならないかもしれない）", now, icon="🗓", name="暮らしぶり")
    app.trace.add("retro", "生活の型の割り当て", remade=ids, appoints=marked)
    return ids
