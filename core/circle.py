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

段 2: あなたに知られる経路. どれも裏の予定 (事実) からだけ出す.
- 言い方 (who_label): 「友達の佐藤さん」「職場の佐藤さん」「上司の佐藤さん」. 家族は名前でなく続柄 (母・姉 … 名前から決まった形で).
  元恋人・言い寄る人 (段 3・4 の HIDE_KINDS) は名前を言わず「知り合い」.
- 知ったこと (known): st["circle"]["known"][pid] = {t0 (初めて知った), t (最後に聞いた), via, feel}. st["known"] は 30 件で
  古いものから消えるので, 人はこちらに残す. via: phone / message / talk / decline / spot / grumble.
  feel は話しぶりから分かった向き (warm 仲がよさそう / uneasy 苦手そう). 関係性タブに「知っている知り合い」として出る.
- 話の中で (tell): 会ったあと 30 時間のうちに, メッセージ・対面の話で「昨日〇〇とご飯に行った」. 予定ごとに一度だけくじを引く.
- 愚痴 (grumble): 苦手な人と会ったあと, 「話そう」の理由が grumble になることがある (返し方で聞けば, 相手のストレスが下がる).
- 誰といるの / いたの (answer_mode の補正 hide_shift): 元恋人・言い寄る人・傾き (pull) の高い人ほどはぐらかす (段 3・4 で効く).
- ばったり (spot_here): あなたが外にいて, 相手が同じ行き先で予定の最中なら, 相手とその人を見かける (core/street.py).

段 3: 負の出来事と人の移り (step と daily. 効き目は bonds.realize を通さない: あなたとの交流ではない).
- 元恋人 (ex)・言い寄る人 (suitor) も人に入る (いたりいなかったり. くじ). この人たちとは予定を作らない (会うのは段 4).
  遡及: v1 の記録 (段 1・2) には, 一度だけ決まった形のくじ (circle3:<cid>) で足す (v: 2).
- 人どうしの仲 (_after: 予定が終わるたび): close が揺らぎ, まれに喧嘩 (親しい・ふつう → こじれる. ストレス・機嫌に一度だけ),
  こじれた人とは会ううち / 日がたつうちに和解する (→ ふつう). 親しさで warm ⇔ plain も移る.
  友達・学校の友達とは, COOL_AFTER 日会わないと少しずつ親しさが下がる.
- 人の移り (daily): 新しい人が加わる (JOIN_P. 生活の型で 職場 / 学校 / 友達. 上限 PEOPLE_MAX). 疎遠になった友達 (親しさ FADE_CLOSE 未満で
  FADE_DAYS 会っていない) は抜ける (gone. 消さずに印だけ: あなたが知っている人は, 関係性タブにそのまま残る. 抜けたことは見せない).
- 言い寄る人 (suitor): flags.interest (相手への好意)・persist (しつこさ). 日ごとのくじで誘い・連絡が来て (pester), 相手のストレスになる.
  相手が応じないので interest は下がっていき, 25 を切ると諦めて抜ける. 新しい言い寄る人も, まれに現れる (SUITOR_NEW_P).
- 元恋人 (ex): flags.interest (相手への未練. 連絡の来やすさ). ときどき連絡が来る (ex). こじれた別れなら迷惑 (ストレス),
  そうでなければ気持ちが揺れる (寂しさ・機嫌. 未練 warm なら pull が少し育つ: 段 4 の下地).
- 相談 (confide): 出来事のあと 1 日のうちに, 「話そう」の理由・電話 / 対面の会話の切れ目が pester / ex になることがある
  (出来事のときに一度だけくじ: 言い寄られている 0.55・元恋人がこじれて迷惑 0.45・気持ちが揺れている 0.2. 好感度が低ければ 0.3 倍).
  名前は言わない (「何度も誘ってくる人」「前に付き合ってた人」). 聞けば愚痴と同じくストレスが下がる.
- 機嫌の時間平均は, 出来事が無い場合との差 ±2 以内 (tools/check_circle.py).
"""
import hashlib
import random
import time
from datetime import datetime, timedelta

KINDS = {"friend": "友達", "classmate": "学校の友達", "coworker": "職場の人", "boss": "上司", "family": "家族",
         "ex": "元恋人", "suitor": "言い寄る人"}
WHO = {"friend": "friend", "classmate": "friend", "coworker": "coworker", "boss": "coworker", "family": "family",
       "ex": "friend", "suitor": "friend"}
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
FILL_RELIEF = {"loneliness": 4.0, "boredom": 2.5}   # 予定の 1 時間で紛れる分 ÷ ふだんのたまる速さ (fill_f のならし)
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

# 段 2: 知られる経路
HIDE_KINDS = ("ex", "suitor")           # 名前を言いたがらない間柄 (段 3・4 で人に加わる)
REL_WORD = {"friend": "友達", "classmate": "友達", "coworker": "職場", "boss": "上司"}
FAMILY_ROLES = ("母", "父", "姉", "兄", "妹", "弟", "いとこ")
DID = {"meal": "ご飯に行った", "hang": "出かけた", "drink": "飲みに行った", "work_after": "仕事帰りにご飯に行った"}
TELL_SPAN = 30 * 3600                   # 会ってからこれだけのうちなら, 話に出ることがある
TELL_P = {"message": 0.35, "talk": 0.5}     # 予定ごとに一度だけのくじ (最初に話す機会で)
GRUMBLE_SPAN = 4 * 3600                 # 苦手な人と会ってから, 愚痴になりうる長さ (「さっきまで一緒だった」と言える間)
GRUMBLE_P = 0.5
HIDE_SHIFT = {"ex": 0.45, "suitor": 0.35}   # 誰といるの？ を はぐらかす方へずらす量 (段 3・4)

# 段 3: 負の出来事と人の移り
V = 2                                   # 記録の版 (1: 段 1・2 / 2: 元恋人・言い寄る人を足した)
PEOPLE_MAX = 9                          # 抜けていない人の上限
EX_P = (0.15, 0.45)                     # 元恋人がいる (20 歳未満 / 以上)
EX_TONE = {"warm": 0.2, "plain": 0.4, "strained": 0.4}    # 未練がある / ふつう / こじれた別れ
SUITOR_P = 0.12                         # 最初から言い寄る人がいる (× 性格の approach)
SUITOR_NEW_P = 1 / 700.0                # 新しい言い寄る人が現れる (日あたり × 性格の approach. 一人いるあいだは現れない. 2 年に 1 人ほど)
SUITOR_QUIT = 25                        # 好意がこれを切ると諦める
SUITOR_COOL = 0.4                       # 好意が日ごとに冷める分 (連絡して応じてもらえないと, さらに冷める. 数週間〜3 か月で諦める)
JOIN_P = 1 / 50.0                       # 新しい知り合いが加わる (日あたり. 人が多いほど加わりにくい: JOIN_W)
JOIN_W = {3: 2.0, 4: 1.5, 5: 1.0, 6: 0.7, 7: 0.4, 8: 0.15}
FADE_CLOSE, FADE_DAYS = 25, 60          # 疎遠になって抜ける (友達・学校の友達)
COOL_AFTER, COOL_RATE = 21, 0.15        # 会わない日がこれだけ続くと, 日に COOL_RATE ずつ親しさが下がる
MOVE_P = 1 / 600.0                      # 職場の人が異動・退職でいなくなる (日あたり. 上司は替わらない)
QUARREL_P = {"warm": 0.012, "plain": 0.02}      # 会ったときに喧嘩してこじれる
MEND_P, MEND_DAY_P = 0.25, 1 / 90.0     # こじれた人と会ったときの和解 / 会わずに日がたっての和解
QUARREL_FX = {"stress": 8, "mood": -6}
MEND_FX = {"stress": -4, "mood": 4}
PESTER_RATE = 0.3                       # 言い寄る人からの連絡 (日あたり × persist × interest / 100)
EX_RATE = 1 / 60.0                      # 元恋人からの連絡 (日あたり × interest / 40)
TROUBLE_FX = {"pester": {"stress": 4, "mood": -2},          # + 5 × persist のストレス
              "ex_strained": {"stress": 6, "mood": -3},
              "ex": {"loneliness": 6, "mood": -2}}
CONFIDE_P = {"pester": 0.55, "ex_strained": 0.45, "ex": 0.2}
CONFIDE_SPAN = 24 * 3600
CONFIDE = ("grumble", "pester", "ex")   # 相談・愚痴の「話そう」の理由 (電話にしない. 聞けばストレスが下がる)


def _wave_mean():
    from .waves import SHARE
    return sum(SHARE[p] * WAVE_W[p] for p in SHARE)


WAVE_MEAN = _wave_mean()


def _day(t):
    return datetime.fromtimestamp(t).date().isoformat()


class Circle:
    events_on = True            # 段 3 の出来事 (仲の動き・人の移り・言い寄る人・元恋人). check_circle が「無い場合」と比べるときに切る

    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 記録
    def rec(self, char, st, now=None):
        r = st.get("circle")
        if r and r.get("v") == V:
            return r
        now = now or time.time()
        trace = getattr(self.app, "trace", None)
        if r and r.get("v") == 1:               # 段 1・2 の記録: 元恋人・言い寄る人を一度だけ足す (遡及)
            r["v"] = V
            add = self._extra_people(char, r["people"], now)
            r["people"] += add
            if trace:
                trace.add("circle", "段 3 の人を足した (遡及)", char.get("id"), now, people=["%s(%s)" % (p["name"], p["kind"]) for p in add])
            return r
        people = self._make_people(char, now)
        people += self._extra_people(char, people, now)
        r = {"v": V, "people": people, "plans": [], "partner": None, "made_to": _day(now)}
        st["circle"] = r
        if trace:
            trace.add("circle", "知り合いを初めて決めた", char.get("id"), now,
                      people=["%s(%s/%s)" % (p["name"], p["kind"], p["tone"]) for p in r["people"]])
        return r

    def _extra_people(self, char, people, now):
        """元恋人・言い寄る人 (いたりいなかったり. 決まった形のくじ circle3:<cid>)."""
        rnd = random.Random("circle3:%s" % char.get("id"))
        out = []
        used = {p["name"] for p in people}
        n = max([int(p["pid"][1:]) for p in people if p["pid"][1:].isdigit()] or [0])
        if rnd.random() < EX_P[0 if self._minor(char) else 1]:
            tone = rnd.choices(list(EX_TONE), list(EX_TONE.values()))[0]
            pull = rnd.uniform(15, 35) if tone == "warm" else rnd.uniform(0, 12)
            out.append(self._new(rnd, n + len(out) + 1, "ex", tone, rnd.uniform(15, 45), now, used,
                                 {"interest": round(rnd.uniform(15, 60), 1), "pull": round(pull, 1)}))
        approach = float(self.app.traits(char).get("approach", 1))
        if rnd.random() < SUITOR_P * max(0.5, min(1.5, approach)):
            out.append(self._new_suitor(rnd, n + len(out) + 1, now, used))
        return out

    def _new(self, rnd, i, kind, tone, close, now, used, flags=None):
        free = [x for x in SURNAMES if x not in used] or list(SURNAMES)
        name = rnd.choice(free)
        used.add(name)
        kp = KIND_PLANS.get(kind, KIND_PLANS["friend"])
        haunt = sorted({p for pk in kp for p in PLAN_KINDS[pk]["places"] if rnd.random() < 0.6}) or list(PLAN_KINDS[kp[0]]["places"][:2])
        p = {"pid": "p%d" % i, "name": name, "kind": kind, "tone": tone, "close": round(close, 1), "since": now, "haunt": haunt}
        if flags:
            p["flags"] = flags
        return p

    def _new_suitor(self, rnd, i, now, used):
        return self._new(rnd, i, "suitor", rnd.choice(("plain", "uneasy", "uneasy")), rnd.uniform(10, 35), now, used,
                         {"interest": round(rnd.uniform(55, 85), 1), "persist": round(rnd.uniform(0.2, 0.9), 2),
                          "pull": round(rnd.uniform(0, 10), 1)})

    def alive(self, r):
        """抜けていない人."""
        return [p for p in r["people"] if not p.get("gone")]

    def _next_i(self, r):
        return max([int(p["pid"][1:]) for p in r["people"] if p["pid"][1:].isdigit()] or [0]) + 1

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
        if self.events_on and r.get("d3", "") < _day(t):        # 段 3 の日締めは日に一度 (開き直し・追いつきで二重にしない)
            r["d3"] = _day(t)
            self._daily3(char, st, r, t)

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
        ppl = [p for p in self.alive(r) if p["kind"] in KIND_PLANS]     # 元恋人・言い寄る人とは会わない (段 4)
        if not ppl or random.random() >= self.rate(char, st, day):
            return None
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

    def fill_f(self, char, st, t, pid):
        """寂しさ・退屈のたまる速さへの倍率: 予定の最中は 1 (紛れる分は場面の効き目), ほかの時間は予定にいる割合でわずかに上げる.
        予定で寂しさ・退屈が紛れて, 機嫌の落ち着く先の下げ (寂しさ 60 以上 −15・退屈 70 以上 −10) に掛からなくなる分で,
        予定の多い人の機嫌の時間平均が +3 ほど上に偏っていた (段 1 から. tools/check_circle.py を 3 回の平均にして分かった)."""
        if pid not in FILL_RELIEF or self.plan_at(char, st, t):
            return 1.0
        sh = self.in_share(char, st)
        return round(1 + sh / (1 - sh) * FILL_RELIEF[pid], 4)

    def who_word(self, char, st, x):
        """誘いを予定で断るときの, 予定の相手の言い方 (名前入り). 断ったときに appoint が learn(via=decline) する."""
        return self.who_label(char, st, x["pid"])

    # ------------------------------------------------------------------ 段 2: 知られる経路
    def family_role(self, char, p):
        """家族の続柄 (名前から決まった形で. 記録には持たない: 段 1 のセーブにもそのまま効く)."""
        h = int(hashlib.md5(("%s|%s|%s" % (char.get("id"), p["pid"], p["name"])).encode("utf-8")).hexdigest()[:6], 16)
        return FAMILY_ROLES[h % len(FAMILY_ROLES)]

    def who_label(self, char, st, pid):
        """あなたに言うときの言い方: 友達の佐藤さん / 職場の佐藤さん / 上司の佐藤さん / 母. 言いたがらない間柄は「知り合い」."""
        p = self.person(char, st, pid)
        if not p or p["kind"] in HIDE_KINDS:
            return "知り合い"
        if p["kind"] == "family":
            return self.family_role(char, p)
        return "%sの%sさん" % (REL_WORD.get(p["kind"], "知り合い"), p["name"])

    def learn(self, char, st, pid, via, now=None, feel=None):
        """あなたがその人を知った (名前と間柄). 言いたがらない間柄は名前を言わないので, 知ったことにならない."""
        p = self.person(char, st, pid)
        if not p or p["kind"] in HIDE_KINDS:
            return None
        now = now or time.time()
        kn = self.rec(char, st).setdefault("known", {})
        k = kn.get(pid)
        if not k:
            k = kn[pid] = {"t0": now, "via": via}
            trace = getattr(self.app, "trace", None)
            if trace:
                trace.add("circle", "あなたが知り合いを知った: %s" % p["name"], char.get("id"), now, via=via, kind=p["kind"])
        k["t"] = now
        if feel:
            k["feel"] = feel
        return k

    def known_view(self, char, st):
        """関係性タブの「知っている知り合い」(新しく聞いた順)."""
        r = st.get("circle") or {}
        out = []
        for pid, k in (r.get("known") or {}).items():
            p = self.person(char, st, pid)
            if not p or p["kind"] in HIDE_KINDS:
                continue
            out.append({"pid": pid, "label": self.who_label(char, st, pid), "feel": k.get("feel"), "via": k.get("via"),
                        "t": k.get("t", k.get("t0"))})
        out.sort(key=lambda x: -(x["t"] or 0))
        return out

    def _when(self, t1, now):
        a, b = datetime.fromtimestamp(t1).date(), datetime.fromtimestamp(now).date()
        if a == b:
            return "さっき" if now - t1 < 3 * 3600 else "今日"
        return "昨日" if (b - a).days == 1 else "この前"

    def tell(self, char, st, now, via):
        """会ったあとの話: 「昨日, 〇〇とご飯に行った」. 30 時間のうちに終わった予定の, 最後の 1 つについて, 一度だけくじを引く.
        (セリフのキー, 置き換え) か None. キーは circle_told (親しい・ふつう) / circle_told_uneasy (苦手・こじれた)."""
        r = st.get("circle")
        if not r:
            return None
        cands = [x for x in r["plans"] if now - TELL_SPAN <= x["t1"] <= now and not x.get("told")]
        if not cands:
            return None
        x = cands[-1]
        x["told"] = True
        p = self.person(char, st, x["pid"])
        if not p or p["kind"] in HIDE_KINDS or random.random() >= TELL_P.get(via, 0.35):
            return None
        uneasy = p["tone"] in ("uneasy", "strained")
        self.learn(char, st, x["pid"], via, now, feel="uneasy" if uneasy else "warm" if p["tone"] == "warm" else None)
        trace = getattr(self.app, "trace", None)
        if trace:
            trace.add("circle", "会ったことを話した: %s" % p["name"], char.get("id"), now, via=via, tone=p["tone"])
        return ("circle_told_uneasy" if uneasy else "circle_told"), {"who": self.who_label(char, st, x["pid"]), "did": DID[x["kind"]],
                                                                       "when": self._when(x["t1"], now)}

    def grumble(self, char, st, now):
        """苦手な人・こじれた人と会ったあと (4 時間のうち), 「話そう」を愚痴にするか. 言い方 (who_label) か None. 予定ごとに一度だけ."""
        r = st.get("circle")
        if not r:
            return None
        for x in reversed(r["plans"]):
            if not (now - GRUMBLE_SPAN <= x["t1"] <= now) or x.get("gr"):
                continue
            p = self.person(char, st, x["pid"])
            if not p or p["tone"] not in ("uneasy", "strained") or p["kind"] in HIDE_KINDS:
                continue
            x["gr"] = True
            if random.random() >= GRUMBLE_P:
                return None
            x["told"] = True                        # 愚痴で話したので, あとで「昨日〇〇と」とは言わない
            self.learn(char, st, x["pid"], "grumble", now, feel="uneasy")
            return self.who_label(char, st, x["pid"])
        return None

    def hide_shift(self, char, st, pid):
        """「誰といるの / いたの」をはぐらかす方へのずれ (0〜): 元恋人・言い寄る人と, 傾き (flags.pull) の高い人ほど."""
        p = self.person(char, st, pid) if pid else None
        if not p:
            return 0.0
        pull = float((p.get("flags") or {}).get("pull", 0))
        return HIDE_SHIFT.get(p["kind"], 0.0) + 0.3 * max(0.0, pull - 30) / 70.0

    def spot_here(self, char, st, place, t):
        """時刻 t に, 行き先 place で知り合いと会っている最中なら, その予定 (ばったり見かけうる). 無ければ None."""
        x = self.plan_at(char, st, t)
        if x and x.get("place") == place:
            return x
        return None

    # ------------------------------------------------------------------ 段 3: 負の出来事と人の移り
    def _fx(self, char, st, fx, now, why):
        self.app.apply_effects(st, fx, now)
        trace = getattr(self.app, "trace", None)
        if trace:
            trace.add("circle", why, char.get("id"), now, fx=fx)

    def step(self, char, st, t0, t1):
        """5 分ごと (life.step): 終わった予定のあとの仲の動き (_after) と, 今日の出来事 (言い寄る人・元恋人からの連絡)."""
        r = st.get("circle")
        if not r or not self.events_on or r.get("v") != V:
            return
        for x in r["plans"]:
            if not x.get("done") and x["t1"] <= t1:
                x["done"] = True
                self._after(char, st, r, x, t1)
        evs = r.get("events") or []
        due = [e for e in evs if e["t"] <= t1]
        if due:
            r["events"] = [e for e in evs if e["t"] > t1]
            for e in due:
                self._event(char, st, r, e, t1)

    def _after(self, char, st, r, x, now):
        """予定が終わった: 会った人との仲が揺らぐ. まれに喧嘩, こじれた人とは和解することも. 効き目 (機嫌・ストレス) は
        終わってすぐのときだけ (閉じていた間の古い予定は, 仲だけ動かす)."""
        p = self.person(char, st, x["pid"])
        if not p or p.get("gone"):
            return
        fresh = now - x["t1"] < 3600
        fl = p.setdefault("flags", {})
        fl["last"] = x["t1"]
        tone = p["tone"]
        if tone in QUARREL_P and random.random() < QUARREL_P[tone]:
            p["tone"] = "strained"
            p["close"] = round(max(5.0, p["close"] - random.uniform(10, 20)), 1)
            fl["quarrel"] = x["t1"]
            if fresh:
                self._fx(char, st, QUARREL_FX, now, "喧嘩した: %s" % p["name"])
            return
        if tone == "strained":
            if random.random() < MEND_P:
                self._mend(char, st, p, now, fresh)
            return
        d = random.uniform(-2.0, 3.0) if tone in ("warm", "plain") else random.uniform(-3.0, 2.0)
        p["close"] = round(max(0.0, min(100.0, p["close"] + d)), 1)
        if tone == "plain" and p["close"] >= 65 and random.random() < 0.2:
            p["tone"] = "warm"
        elif tone == "warm" and p["close"] < 45:
            p["tone"] = "plain"
        elif tone == "uneasy" and p["close"] >= 45 and random.random() < 0.15:
            p["tone"] = "plain"

    def _mend(self, char, st, p, now, fresh):
        p["tone"] = "plain"
        p["close"] = round(min(100.0, p["close"] + random.uniform(5, 15)), 1)
        p.setdefault("flags", {})["mend"] = now
        if fresh:
            self._fx(char, st, MEND_FX, now, "和解した: %s" % p["name"])

    def _days_apart(self, p, t):
        return (t - float((p.get("flags") or {}).get("last") or p.get("since") or t)) / 86400.0

    def _daily3(self, char, st, r, t):
        """日締め: 会わない人の親しさ・和解・疎遠で抜ける・新しい人・言い寄る人が諦める / 現れる・今日の出来事の時刻."""
        trace = getattr(self.app, "trace", None)
        for p in self.alive(r):
            apart = self._days_apart(p, t)
            if p["kind"] in ("friend", "classmate") and apart > COOL_AFTER:
                p["close"] = round(max(0.0, p["close"] - COOL_RATE), 1)
                if p["tone"] == "warm" and p["close"] < 45:
                    p["tone"] = "plain"
            if p["tone"] == "strained" and p["kind"] not in HIDE_KINDS and random.random() < MEND_DAY_P:
                self._mend(char, st, p, t, False)
            if p["kind"] in ("friend", "classmate") and p["close"] < FADE_CLOSE and apart > FADE_DAYS:
                self._leave(char, st, r, p, t, "疎遠になった")
            elif p["kind"] == "coworker" and random.random() < MOVE_P:
                self._leave(char, st, r, p, t, "異動・退職")
            elif p["kind"] == "suitor":
                fl = p.setdefault("flags", {})
                fl["interest"] = round(float(fl.get("interest", 0)) - SUITOR_COOL, 2)     # 応じてもらえないまま, 日がたつと冷める
                if fl["interest"] < SUITOR_QUIT:
                    self._leave(char, st, r, p, t, "諦めた")
        n = len(self.alive(r))
        if n < PEOPLE_MAX and random.random() < JOIN_P * JOIN_W.get(n, 2.0 if n < 3 else 0.0):
            self._join(char, st, r, t)
        approach = max(0.5, min(1.5, float(self.app.traits(char).get("approach", 1))))
        if not any(p["kind"] == "suitor" for p in self.alive(r)) and len(self.alive(r)) < PEOPLE_MAX \
                and random.random() < SUITOR_NEW_P * approach:
            p = self._new_suitor(random.Random(), self._next_i(r), t, {q["name"] for q in r["people"]})
            r["people"].append(p)
            if trace:
                trace.add("circle", "言い寄る人が現れた: %s" % p["name"], char.get("id"), t, flags=p["flags"])
        # 今日の出来事 (起きている時間のどこか. 時刻は 10〜22 時)
        evs = r.setdefault("events", [])
        d0 = datetime.fromtimestamp(t).replace(hour=0, minute=0, second=0, microsecond=0)
        for p in self.alive(r):
            fl = p.get("flags") or {}
            if p["kind"] == "suitor":
                rate = PESTER_RATE * float(fl.get("persist", 0.5)) * float(fl.get("interest", 0)) / 100.0
                kind = "pester"
            elif p["kind"] == "ex":
                rate = EX_RATE * float(fl.get("interest", 0)) / 40.0
                kind = "ex"
            else:
                continue
            if random.random() < rate:
                at = (d0 + timedelta(hours=random.uniform(10, 22))).timestamp()
                if at > t and not any(e["pid"] == p["pid"] for e in evs):
                    evs.append({"t": at, "kind": kind, "pid": p["pid"]})
        # 抜けて久しく, あなたも知らない人は消す (記録を太らせない)
        kn = r.get("known") or {}
        live = {x["pid"] for x in r["plans"]}
        r["people"] = [p for p in r["people"] if not (p.get("gone") and t - p["gone"] > 120 * 86400 and p["pid"] not in kn
                                                       and p["pid"] not in live)]

    def _leave(self, char, st, r, p, t, why):
        p["gone"] = t
        for x in [x for x in r["plans"] if x["pid"] == p["pid"] and x["t0"] > t]:
            r["plans"].remove(x)
        r["events"] = [e for e in r.get("events") or [] if e["pid"] != p["pid"]]
        trace = getattr(self.app, "trace", None)
        if trace:
            trace.add("circle", "%s: %s(%s)" % (why, p["name"], p["kind"]), char.get("id"), t)

    def _join(self, char, st, r, t):
        life = (char.get("life") or {}).get("type", "")
        if life == "student":
            kinds = ("classmate", "classmate", "friend")
        elif life in ("office", "service", "shift", "night"):
            kinds = ("coworker", "coworker", "friend")
        else:
            kinds = ("friend",)
        rnd = random.Random()
        kind = rnd.choice(kinds)
        tone = rnd.choices(("warm", "plain", "uneasy"), (0.25, 0.65, 0.1))[0]
        close = {"warm": (45, 60), "plain": (25, 45), "uneasy": (15, 30)}[tone]
        p = self._new(rnd, self._next_i(r), kind, tone, rnd.uniform(*close), t, {q["name"] for q in r["people"]})
        r["people"].append(p)
        trace = getattr(self.app, "trace", None)
        if trace:
            trace.add("circle", "新しい知り合い: %s(%s/%s)" % (p["name"], kind, tone), char.get("id"), t)
        return p

    def _event(self, char, st, r, e, now):
        """言い寄る人・元恋人からの連絡. 相手のストレス・気持ちに効き, あとで話すかを一度だけくじで決める."""
        p = self.person(char, st, e["pid"])
        if not p or p.get("gone"):
            return
        fl = p.setdefault("flags", {})
        fresh = now - e["t"] < 3600
        if e["kind"] == "pester":
            persist = float(fl.get("persist", 0.5))
            fx = dict(TROUBLE_FX["pester"], stress=TROUBLE_FX["pester"]["stress"] + 5 * persist)
            # 応じないので, 好意は少しずつ冷める (しつこい人ほどゆっくり)
            fl["interest"] = round(float(fl.get("interest", 0)) - random.uniform(1.5, 5.0) * (1.2 - persist), 1)
            ck = "pester"
        else:
            ck = "ex_strained" if p["tone"] == "strained" else "ex"
            fx = dict(TROUBLE_FX[ck])
            fl["interest"] = round(max(0.0, float(fl.get("interest", 0)) - random.uniform(3, 8)), 1)
            if p["tone"] == "warm":                 # 未練がある: 気持ちが少し傾く (段 4 の下地. 必ずではない・上限あり)
                fl["pull"] = round(min(60.0, float(fl.get("pull", 0)) + random.uniform(0, 4)), 1)
        fl["contact"] = now
        if fresh:
            self._fx(char, st, fx, now, "連絡が来た (%s): %s" % (ck, p["name"]))
        aff = float(st["params"].get("affection", 50))
        if fresh and random.random() < CONFIDE_P[ck] * (0.3 if aff < 35 else 1.0):
            r["talk"] = {"why": "pester" if ck == "pester" else "ex", "t": now, "pid": p["pid"]}

    def confide(self, char, st, now):
        """「話そう」の理由・会話の切れ目にする相談 / 愚痴: (理由, 言い方) か None.
        苦手な人と会ったあとの愚痴 (grumble) が先. 次に, 言い寄る人・元恋人からの連絡のあと 1 日のうちの相談 (一度だけ)."""
        who = self.grumble(char, st, now)
        if who:
            return "grumble", who
        r = st.get("circle") or {}
        tk = r.get("talk")
        if not tk:
            return None
        r.pop("talk")
        if now - tk["t"] > CONFIDE_SPAN:
            return None
        trace = getattr(self.app, "trace", None)
        if trace:
            trace.add("circle", "相談した: %s" % tk["why"], char.get("id"), now, pid=tk["pid"])
        return tk["why"], ""

    def debug(self, char, st, now):
        r = self.rec(char, st, now)
        return {"知り合い": ["%s（%s・%s・%s%s%s）" % (p["name"], KINDS[p["kind"]], p["tone"], p["close"],
                                                 "".join("・%s %s" % (k, v) for k, v in sorted((p.get("flags") or {}).items())
                                                         if k in ("interest", "persist", "pull")),
                                                 "・抜けた" if p.get("gone") else "") for p in r["people"]],
                "予定": ["%s〜%s %sと%s（%s）" % (datetime.fromtimestamp(x["t0"]).strftime("%m/%d %H:%M"),
                                              datetime.fromtimestamp(x["t1"]).strftime("%H:%M"),
                                              (self.person(char, st, x["pid"]) or {}).get("name", "?"), x["kind"], x["place"])
                       for x in r["plans"] if x["t1"] > now],
                "あなたが知っている知り合い": ["%s（%s%s）" % (k["label"], k["via"], "・" + k["feel"] if k.get("feel") else "")
                                      for k in self.known_view(char, st)]}
