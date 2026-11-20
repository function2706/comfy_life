"""相手の交友関係 (A34). 段 1: 人と予定.

相手ごとに, 登録していない知り合い (people) と, その人たちと会う予定 (plans) を持つ. 画面には出さない
(知られる経路は段 2. 気配・断る理由は, ここの予定という裏の事実からだけ出す. 作り事はしない).

人 (people): {pid, name, kind, tone, close, since, haunt}
- kind: friend (友達) / classmate (学校の友達) / coworker (職場の人) / boss (上司) / family (家族)
  (段 3・4 で ex 元恋人・suitor 言い寄る人を足す)
- tone (相手からその人への向き): warm 親しい / plain ふつう / uneasy 苦手 / strained こじれている
- close: 親しさ 0〜100. haunt: 会うときの行き先の種類 (places の id)
- 人数は 3〜7 (生活の型と, 性格の approach). 苦手な人は 1〜2 人いることが多い (いない人もいる).
  人は random.Random("circle:<cid>") で決まった形に作る (遡及: いまのセーブの相手にも, 初めて触れたときに一度だけ).

予定 (plans): {t0, t1, pid, place, kind}
- 日締め (life.step) で, 先 AHEAD 日ぶんを, まだ作っていない日だけ作る (made_to). 過去の予定は作らない (作った次の日から).
- 起きやすさ: 週に WEEK_RATE ほど × 性格の approach × 生活の波 (人付き合いが多い時期で多く, 忙しい・落ち込みで少なく.
  時間平均が 1 になるよう waves.SHARE で正規化) × 曜日 (週末が多い). くじだけで, 確定させない.
- 空いている時間 (予定・寝ている・手が離せない でない), あなたとの約束の前後 2 時間を避け, 行き先が開いている時間だけ.
  職場の人・上司とは, 平日の仕事のあと (work_after). 苦手な人と会うのは, ほぼ仕事の付き合いだけ.
- 場面: engine.scheduled_scene に重ねる (外出. 風邪・お泊り・あなたと会っているときは, そちらが勝つ).
  会った人で効き目が違う: 親しい人は寂しさ・退屈が紛れて機嫌が上がり, 苦手・こじれた人はストレスがたまり機嫌が下がる.
  効き目は bonds.realize を通さない (あなたとの交流ではない. 予定の場面の毎時の効果と同じ道).
- 予定の最中は, 離れていて連絡しにくい (contact_f = CONTACT_IN). そのぶん全体の連絡は減らさないよう, 予定にいる見込みの時間の
  割合で, それ以外の時間をわずかに上げる (負の偏りを作らない. tools/check_circle.py).
- あなたの誘いがその時間に重なると, 相手は予定がふさがっている (appoint の busy) ので断る (理由は appoint_plan).
  献身的なら予定のほうをずらして合わせてくれることがある (drop).
"""
import random
import time
from datetime import datetime, timedelta

KINDS = {"friend": "友達", "classmate": "学校の友達", "coworker": "職場の人", "boss": "上司", "family": "家族"}
WHO = {"friend": "friend", "classmate": "friend", "coworker": "coworker", "boss": "coworker", "family": "family"}
TONES = ("warm", "plain", "uneasy", "strained")

SURNAMES = ("佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺", "山本", "中村", "小林", "加藤", "吉田", "山田", "佐々木", "山口", "松本",
            "井上", "木村", "林", "斎藤", "清水", "山崎", "森", "池田", "橋本", "阿部", "石川", "山下", "中島", "石井", "小川",
            "前田", "岡田", "長谷川", "藤田", "後藤", "近藤", "村上", "遠藤", "青木", "坂本")

AHEAD = 3                   # 先何日ぶんの予定を持つか
KEEP_DAYS = 3               # 終わった予定を残す日数 (気配・「誰といたの？」のもと)
WEEK_RATE = 1.2             # 予定の多さの基準 (週あたり. 性格・時期・曜日で揺れる)
DAY_W = {True: 1.6, False: 0.76}        # 本人の休み (昼に予定が無い日) / 仕事・学校のある日. 週の重みの和で割って, 週の合計をそろえる
WAVE_W = {"normal": 1.0, "busy": 0.4, "hooked": 0.7, "social": 2.6, "down": 0.5, "free": 1.3}
CONTACT_IN = 0.5            # 予定の最中に, 離れて自分から連絡してくる度合い
TRY = 8                     # 1 日の予定の時刻を探す回数

# 予定の種類: 行き先の候補・長さ (時間)・ラベル
PLAN_KINDS = {
    "meal": {"places": ("family", "restaurant", "ramen", "teishoku", "cafe"), "hours": (1.5, 2.5), "label": "%sと%sでご飯"},
    "hang": {"places": ("mall", "cafe", "town", "shopping_street", "station"), "hours": (2.0, 4.0), "label": "%sと%sで過ごしている"},
    "drink": {"places": ("restaurant",), "hours": (2.0, 3.0), "label": "%sと%sで飲んでいる"},
    "work_after": {"places": ("restaurant", "family", "ramen"), "hours": (1.5, 2.5), "label": "%sと仕事帰りに%sへ"},
}
# 誰とどんな予定になりやすいか
KIND_PLANS = {"friend": ("meal", "hang", "hang", "drink"), "classmate": ("meal", "hang", "hang"),
              "coworker": ("work_after", "meal"), "boss": ("work_after",), "family": ("meal",)}
# 会った人の向きごとの, 1 時間あたりの効き目
TONE_FX = {"warm": {"loneliness": -5, "boredom": -6, "mood": 2, "stress": -2},
           "plain": {"loneliness": -3, "boredom": -4, "mood": 0.5},
           "uneasy": {"loneliness": -1, "boredom": -2, "stress": 4, "mood": -2},
           "strained": {"boredom": -1, "stress": 6, "mood": -3}}
MEAL_FX = {"satiety": 25, "hydration": 15}
WORK_ACTS = ("work", "parttime")


def _wave_mean():
    from .waves import SHARE
    return sum(SHARE[p] * WAVE_W[p] for p in SHARE)


WAVE_MEAN = _wave_mean()


def _day(t):
    return datetime.fromtimestamp(t).date().isoformat()


class Circle:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 記録
    def rec(self, char, st, now=None):
        r = st.get("circle")
        if r and r.get("v") == 1:
            return r
        now = now or time.time()
        r = {"v": 1, "people": self._make_people(char, now), "plans": [], "partner": None, "made_to": _day(now)}
        st["circle"] = r
        trace = getattr(self.app, "trace", None)
        if trace:
            trace.add("circle", "知り合いを初めて決めた", char.get("id"), now,
                      people=["%s(%s/%s)" % (p["name"], p["kind"], p["tone"]) for p in r["people"]])
        return r

    def _make_people(self, char, now):
        rnd = random.Random("circle:%s" % char.get("id"))
        life = (char.get("life") or {}).get("type", "")
        approach = float(self.app.traits(char).get("approach", 1))
        kinds = []
        if life == "student":
            kinds += ["classmate"] * rnd.choice((2, 2, 3))
        elif life in ("office", "service", "shift", "night"):
            kinds += ["coworker"] * rnd.choice((1, 2, 2)) + ["boss"]
        else:                                   # 在宅など: 職場の人はいない
            pass
        kinds += ["friend"] * rnd.choice((1, 2, 2, 3))
        if rnd.random() < 0.5:
            kinds.append("family")
        if approach >= 1.2 and rnd.random() < 0.6:
            kinds.append("friend")
        elif approach < 0.8 and kinds.count("friend") > 1 and rnd.random() < 0.6:
            kinds.remove("friend")              # 人付き合いの少ない性格は, 友達が少なめ
        while len(kinds) < 3:                   # 誰でも, 会う人は数人いる
            kinds.append(rnd.choice(("friend", "friend", "family")) if "family" not in kinds else "friend")
        kinds = kinds[:7]
        names = rnd.sample(SURNAMES, len(kinds))
        out = []
        n_uneasy = 0
        for i, k in enumerate(kinds):
            if k == "boss":
                tone = rnd.choices(TONES, (0.15, 0.4, 0.35, 0.1))[0]
            elif k == "coworker":
                tone = rnd.choices(TONES, (0.3, 0.45, 0.2, 0.05))[0]
            elif k == "family":
                tone = rnd.choices(TONES, (0.55, 0.3, 0.05, 0.1))[0]
            else:
                tone = rnd.choices(TONES, (0.55, 0.35, 0.05, 0.05))[0]
            if tone in ("uneasy", "strained"):
                n_uneasy += 1
                if n_uneasy > 2:
                    tone = "plain"
            close = {"warm": (55, 90), "plain": (30, 60), "uneasy": (15, 40), "strained": (10, 45)}[tone]
            kp = KIND_PLANS[k]
            haunt = sorted({p for pk in kp for p in PLAN_KINDS[pk]["places"] if rnd.random() < 0.6}) or list(PLAN_KINDS[kp[0]]["places"][:2])
            out.append({"pid": "p%d" % (i + 1), "name": names[i], "kind": k, "tone": tone,
                        "close": round(rnd.uniform(*close), 1), "since": now, "haunt": haunt})
        return out

    def person(self, char, st, pid):
        return next((p for p in self.rec(char, st)["people"] if p["pid"] == pid), None)

    # ------------------------------------------------------------------ 予定
    def plan_at(self, char, st, t):
        """時刻 t に進行中の予定 (無ければ None)."""
        r = st.get("circle")
        if not r:
            return None
        for x in r["plans"]:
            if x["t0"] <= t < x["t1"]:
                return x
        return None

    def plan_over(self, char, st, t0, t1):
        """t0〜t1 に重なる予定 (最初の 1 つ. 無ければ None)."""
        for x in (st.get("circle") or {}).get("plans") or []:
            if x["t0"] < t1 and t0 < x["t1"]:
                return x
        return None

    def plans_on(self, char, st, t):
        """時刻 t と同じ日の予定."""
        r = st.get("circle")
        d = _day(t)
        return [x for x in (r or {}).get("plans") or [] if _day(x["t0"]) == d]

    def scene(self, char, st, base, dt):
        """予定の最中なら, 予定の場面 (engine.scheduled_scene から). 寝ている・手が離せない予定の時間には重ならない (作るときに避けている)."""
        x = self.plan_at(char, st, dt.timestamp())
        if not x or base.get("asleep"):
            return base
        p = self.person(char, st, x["pid"]) or {}
        pk = PLAN_KINDS[x["kind"]]
        from . import places as places_mod
        loc = (places_mod.PLACES.get(x["place"]) or {}).get("label", x["place"])
        fx = dict(TONE_FX.get(p.get("tone"), TONE_FX["plain"]))
        fx["energy"] = -3
        if x["kind"] in ("meal", "drink", "work_after"):
            for k, v in MEAL_FX.items():
                fx[k] = fx.get(k, 0) + v
        return dict(base, activity="circle", label=pk["label"] % (KINDS.get(p.get("kind"), "知り合い"), loc), location=loc,
                    away=True, busy=False, asleep=False, outing=True, effects=fx, source="circle",
                    pos="sitting at %s, holding smartphone, casual outing" % ("table, restaurant" if x["kind"] != "hang" else "outdoors, town"),
                    neg="", outfit=char.get("outfit_outing") or char.get("outfit_default", ""), plain_outfit=True, circle=x)

    def daily(self, char, st, t):
        """日付が替わったとき: 古い予定を消し, 先 AHEAD 日ぶんの, まだ作っていない日の予定を作る."""
        r = self.rec(char, st, t)
        r["plans"] = [x for x in r["plans"] if x["t1"] > t - KEEP_DAYS * 86400]
        d0 = datetime.fromtimestamp(t).replace(hour=0, minute=0, second=0, microsecond=0)
        for i in range(AHEAD):
            day = d0 + timedelta(days=i)
            key = day.date().isoformat()
            if key <= r.get("made_to", ""):
                continue
            r["made_to"] = key
            self._make_day(char, st, r, day, t)

    def day_off(self, char, day):
        """本人の休みの日か (10〜18 時に外の予定・手の離せない予定が無い). 休みが平日の人 (シフト・接客) もいる."""
        for h in range(10, 18):
            sc = self.app.own_scene(char, day + timedelta(hours=h, minutes=15))
            if sc["away"] or sc["busy"]:
                return False
        return True

    def rate(self, char, st, day):
        """その日に予定ができる見込み. 週の見込み (WEEK_RATE × 性格 × 時期) を, その週の休み / 仕事の日の重みで割り振る
        (休みが週末の人も平日の人も, 週の合計は同じ. 休みの少ない人ほど, 休みの日に寄る)."""
        tr = self.app.traits(char)
        approach = max(0.5, min(1.6, float(tr.get("approach", 1))))
        wave = WAVE_W.get(self.app.waves.period(char, st), 1.0) / WAVE_MEAN
        monday = day - timedelta(days=day.weekday())
        tot = sum(DAY_W[self.day_off(char, monday + timedelta(days=i))] for i in range(7))
        return min(0.9, WEEK_RATE * approach * wave * DAY_W[self.day_off(char, day)] / tot)

    def _make_day(self, char, st, r, day, now):
        if not r["people"] or random.random() >= self.rate(char, st, day):
            return None
        ppl = r["people"]
        weekend = self.day_off(char, day)          # 休みの日 (職場の人とは会いにくい. 仕事帰りは無い)
        w = []
        for p in ppl:
            k = {"warm": 1.0, "plain": 0.6, "uneasy": 0.25, "strained": 0.08}[p["tone"]] * (0.5 + p["close"] / 100.0)
            if p["kind"] in ("coworker", "boss") and weekend:
                k *= 0.15                       # 職場の人と休日に会うのはまれ
            if p["kind"] == "family" and not weekend:
                k *= 0.3
            w.append(k)
        p = random.choices(ppl, w)[0]
        kinds = [k for k in KIND_PLANS[p["kind"]] if not (k == "work_after" and weekend) and not (k == "drink" and self._minor(char))]
        if not kinds:
            return None
        kind = random.choice(kinds)
        slot = self._slot(char, st, day, kind, now)
        if not slot:
            return None
        t0, t1 = slot
        place = self._place(p, kind, datetime.fromtimestamp(t0), datetime.fromtimestamp(t1 - 60))
        if not place:
            return None
        x = {"t0": t0, "t1": t1, "pid": p["pid"], "place": place, "kind": kind, "made": now}
        r["plans"].append(x)
        r["plans"].sort(key=lambda y: y["t0"])
        trace = getattr(self.app, "trace", None)
        if trace:
            trace.add("circle", "予定ができた: %s(%s)と%s" % (p["name"], p["kind"], kind), char.get("id"), now, at=t0, until=t1, place=place)
        return x

    def _minor(self, char):
        try:
            return int(char.get("age") or 20) < 20
        except (TypeError, ValueError):
            return False

    def _place(self, p, kind, d0, d1):
        from . import places as places_mod
        cands = [x for x in PLAN_KINDS[kind]["places"] if x in p.get("haunt", ())] or list(PLAN_KINDS[kind]["places"])
        random.shuffle(cands)
        for pid in cands:
            if pid in places_mod.PLACES and places_mod.open_state(pid, d0)["open"] and places_mod.open_state(pid, d1)["open"]:
                return pid
        return None

    def _free(self, char, t0, t1):
        """t0〜t1 のあいだ, 本人の予定 (この予定を除く) が空いているか."""
        app = self.app
        t = t0
        while t <= t1:
            sc = app.own_scene(char, datetime.fromtimestamp(t))
            if sc["away"] or sc["busy"] or sc["asleep"]:
                return False
            t += 1800
        return True

    def _clash(self, char, st, t0, t1):
        """あなたとの約束 (前後 2 時間) や, ほかの予定と重なるか."""
        app = self.app
        if hasattr(app, "appoint"):
            for x in app.appoint.open_with(char["id"]):
                if x["t"] - 7200 < t1 and t0 < x["t"] + 4 * 3600:
                    return True
        for y in (st.get("circle") or {}).get("plans") or []:
            if y["t0"] - 3600 < t1 and t0 < y["t1"] + 3600:
                return True
        return False

    def _work_end(self, char, day):
        """その日の仕事の終わり (30 分刻み. 仕事が無ければ None)."""
        app = self.app
        was = False
        for m in range(13 * 60, 23 * 60, 30):
            d = day + timedelta(minutes=m)
            act = app.own_scene(char, d).get("activity")
            if act in WORK_ACTS:
                was = True
            elif was:
                return d
        return None

    def _slot(self, char, st, day, kind, now):
        lo, hi = PLAN_KINDS[kind]["hours"]
        for _ in range(TRY):
            if kind == "work_after":
                end = self._work_end(char, day)
                if not end:
                    return None
                start = end + timedelta(minutes=random.choice((15, 30, 45)))
            elif self.day_off(char, day):        # 休みの日 (週末とは限らない): 昼から夜
                start = day + timedelta(hours=random.choice((11, 12, 13, 14, 15, 17, 18, 19)), minutes=random.choice((0, 30)))
            else:                                # 仕事・学校のある日: 終わったあとの夜
                start = day + timedelta(hours=random.choice((18, 19, 19, 20, 21)), minutes=random.choice((0, 30)))
            t0 = start.timestamp()
            t1 = t0 + random.uniform(lo, hi) * 3600
            t1 = t0 + round((t1 - t0) / 1800.0) * 1800
            if t0 < now + 3600:
                continue
            if datetime.fromtimestamp(t1 - 1).date() != start.date():
                continue                         # 日をまたぐ予定は作らない
            if self._clash(char, st, t0, t1):
                continue
            if kind == "work_after":
                if not self._free(char, t0 + 600, t1):
                    continue
            elif not self._free(char, t0 - 1800, t1):      # 出かける前の 30 分も空いている
                continue
            return t0, t1
        return None

    def drop(self, char, st, x, why=""):
        """予定をやめる (あなたに合わせて予定をずらした など)."""
        r = st.get("circle") or {}
        if x in r.get("plans") or []:
            r["plans"].remove(x)
            trace = getattr(self.app, "trace", None)
            if trace:
                trace.add("circle", "予定をやめた", char.get("id"), time.time(), at=x["t0"], pid=x["pid"], why=why)

    def drop_over(self, char, st, t0, t1, why=""):
        """t0〜t1 に重なる予定をやめる. やめた予定を返す."""
        out = []
        for x in list((st.get("circle") or {}).get("plans") or []):
            if x["t0"] < t1 and t0 < x["t1"]:
                self.drop(char, st, x, why)
                out.append(x)
        return out

    # ------------------------------------------------------------------ 効き方
    def in_share(self, char, st):
        """予定にいる見込みの, 起きている時間に対する割合 (連絡の正規化に使う)."""
        hours = sum(sum(PLAN_KINDS[k]["hours"]) / 2.0 for k in ("meal", "hang")) / 2.0
        per_day = WEEK_RATE / 7.0 * max(0.5, min(1.6, float(self.app.traits(char).get("approach", 1))))
        return min(0.3, per_day * hours / 16.0)

    def contact_f(self, char, st, t):
        """離れて自分から連絡してくる度合いへの倍率: 予定の最中は CONTACT_IN, ほかの時間はわずかに上げて, 時間平均を 1 にそろえる."""
        sh = self.in_share(char, st)
        if self.plan_at(char, st, t):
            return CONTACT_IN
        return round((1 - sh * CONTACT_IN) / (1 - sh), 4)

    def who_word(self, char, st, x):
        """予定の相手を, あなたに言うときの言い方 (段 1 は間柄だけ. 名前は段 2)."""
        p = self.person(char, st, x["pid"]) or {}
        return KINDS.get(p.get("kind"), "知り合い") if p.get("kind") != "classmate" else "友達"

    def debug(self, char, st, now):
        r = self.rec(char, st, now)
        return {"知り合い": ["%s（%s・%s・%s）" % (p["name"], KINDS[p["kind"]], p["tone"], p["close"]) for p in r["people"]],
                "予定": ["%s〜%s %sと%s（%s）" % (datetime.fromtimestamp(x["t0"]).strftime("%m/%d %H:%M"),
                                              datetime.fromtimestamp(x["t1"]).strftime("%H:%M"),
                                              (self.person(char, st, x["pid"]) or {}).get("name", "?"), x["kind"], x["place"])
                       for x in r["plans"] if x["t1"] > now]}
