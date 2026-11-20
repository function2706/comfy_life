"""相手の関心の揺らぎ: 自分の生活の波 (時期) と, あなたへの慣れ・新鮮さ (相手ごと. 画面には出さない).

「関心」という値は作らない (好感度・依存度・ノリ・見立てと意味が重なる). 持つのは時期と新鮮さだけで,
効かせる先はいまの連絡・話しかけ・誘いの度合い, 寂しさ・退屈のたまり方, 誘いの受け方, 電話にする割合.

時期 (WAVES): 数日〜数週間続く, 相手の生活の波. ふつう / 忙しい / 何かにはまっている / 人付き合いが多い / 落ち込んでいる / 暇.
- 日付が替わったとき (life.step の日締め) に daily で期限を見て, 過ぎていれば次を抽せんする. ふつうのあとは 7 割で何かの時期,
  3 割でふつうを延ばす. 時期のあとは必ずふつう. 長さはふつう 4〜16 日, 時期 4〜18 日 (8 日あたりが多い).
- 起きやすさ (くじの重みだけ. 確定させない): 忙しいは生活の型 (char.life.type) と月, はまっているは夜型・話しかけの少ない性格,
  人付き合いは話しかけの多い性格と月, 落ち込みはストレス・機嫌, 暇は 8 月・学生.
- 人付き合いが多い時期は, あなた以外と過ごして寂しさが紛れる (寂しさのたまりが鈍る). A34 (相手の交友関係) で実際の人が入ったら,
  ここをその人たちとの予定に置き換える / 差し込む.
- 時期の間に相手から送るメッセージ (presence.fire) に, 5 割で一言添える (時期ごとに一度だけ). 誘いを断るときの理由にも出る.

新鮮さ (fresh. 0〜100): あなたと会う・連絡するのが続くと少しずつ下がり, 間が空く・初めてのこと (初めての行き先・初めての話題) で戻る.
- 会った日は「慣れの落ち着き先」へ近づく (そこより下がらない). 落ち着き先は仲が近いほど高い (連絡先 25・家に行ける仲 45・
  同居 54・同居で好感度 70 以上 57 ほど). 近づく速さは人ごとの慣れやすさ (0.7〜1.3) × 揺らぎ.
  「たくさん会うと損」に振れすぎないよう, 効き目は 0.8〜1.2 倍 (そばの話しかけは 0.9〜1.1 倍) にとどめる.
- 初めてのことで戻るのも確率 (必ず戻る道は作らない).
- 依存度が会うほど上がる一方なのを釣り合わせる: attach.daily の「一緒にいて寂しさが紛れた」の上がり幅に lean_gain を掛ける.

負の偏りを作らない (2026-11-20): 時期の倍率は, 基本の重みと長さから出した「時期ごとに過ごす日の割合」で重み付けた時間平均が
1 になるよう MEAN で割る (ふつうの時期はわずかに 1 を超える). 誘いの受けやすさの差・機嫌の落ち着く先も時間平均 0.
時期は「入れ替わりで揺らぐ」だけで, 全体の連絡・誘いは減らさない. 新鮮さは FRESH_CENTER (3 日に一度ほど会う人の落ち着くあたり) で 1.
確かめは tools/check_waves.py (性格別・生活の型別・月別・会い方 × 仲).

遡及: st["waves"] が無いときに一度だけ作る (時期はふつう・期限は 2〜10 日後で人ごとにずらす. 新鮮さは最近 14 日に交流した日数から).
"""
import random
import time
from datetime import datetime

# apart: 離れて自分から連絡 / near: そばで話しかけ / invite: 誘う / lonely・bored: 寂しさ・退屈のたまる速さ / call: 電話にする割合
# accept: 誘いを受ける見込みに足す / mood: 機嫌の落ち着く先に足す / say: 断るときの理由のセリフ (chat.<key>)
WAVES = {
    "normal": {"label": "ふつう"},
    "busy": {"label": "忙しい", "apart": 0.55, "near": 0.8, "invite": 0.5, "lonely": 0.75, "bored": 0.7, "call": 0.5,
             "accept": -0.15, "say": "appoint_no_busy"},
    "hooked": {"label": "何かにはまっている", "apart": 0.7, "near": 0.85, "invite": 0.8, "lonely": 0.85, "bored": 0.4, "call": 0.8,
               "accept": -0.05, "mood": 2},
    "social": {"label": "人付き合いが多い", "apart": 0.7, "near": 0.85, "invite": 0.6, "lonely": 0.75, "bored": 0.8, "call": 0.8,
               "accept": -0.15, "say": "appoint_no_friends", "mood": 3},
    "down": {"label": "落ち込んでいる", "apart": None, "near": 0.9, "invite": 0.5, "accept": -0.1, "mood": -8},
    "free": {"label": "暇", "apart": 1.3, "near": 1.15, "invite": 1.3, "lonely": 1.1, "bored": 1.3, "accept": 0.05},
}
SPECIAL = ("busy", "hooked", "social", "down", "free")
NORMAL_DAYS = (4, 16)
WAVE_DAYS = (4, 18, 8)            # 三角分布 (下限, 上限, 多いところ)
KEEP_NORMAL = 0.3                 # ふつうのあと, ふつうを延ばす割合
SAY_REASON = 0.6                  # 誘いを断るとき, 時期の理由を言う割合 (残りはいまの断り方)
TELL_CHANCE = 0.5                 # 時期の間に送るメッセージに一言添える割合

# 生活の型 (core/lifetype.py) ごとの, 忙しくなりやすい月
BUSY_MONTHS = {"office": (3, 12), "student": (1, 2, 7), "service": (12,), "shift": (12,), "night": (12,), "freelance": ()}
SOCIAL_MONTHS = (4, 7, 8, 12)

BASE_W = {"busy": 1.0, "hooked": 0.7, "social": 0.8, "down": 0.5, "free": 0.8}      # 時期のくじの基本の重み (weights で月・性格が掛かる)
NORM = ("apart", "near", "invite", "lonely", "bored", "call")
DOWN_APART0 = 0.6                 # 落ち込んでいる時期の apart (依存度がふつう以下のとき. 高いと増える)


def _means():
    """負の偏りを作らないための基準: 基本の重みと長さで, 時期ごとに過ごす日の割合を出し, 倍率の時間平均を 1 に,
    誘いの受けやすさの差・機嫌の落ち着く先の時間平均を 0 にそろえる (時期は「入れ替わりで揺らぐ」だけで, 全体を減らさない)."""
    n_days = sum(NORMAL_DAYS) / 2.0 / (1 - KEEP_NORMAL)
    w_days = sum(WAVE_DAYS) / 3.0
    tot_w = sum(BASE_W.values())
    share = {"normal": n_days / (n_days + w_days)}
    for k, w in BASE_W.items():
        share[k] = (1 - share["normal"]) * w / tot_w
    mean = {}
    for key in NORM + ("accept", "mood"):
        dflt = 0.0 if key in ("accept", "mood") else 1.0
        v = 0.0
        for p, sh in share.items():
            x = WAVES[p].get(key)
            if key == "apart" and p == "down":
                x = DOWN_APART0
            v += sh * (dflt if x is None else float(x))
        mean[key] = v
    return share, mean


SHARE, MEAN = _means()

FRESH_MIN, FRESH_MAX, FRESH_REST = 10.0, 95.0, 70.0
FRESH_CENTER = 50.0               # 新鮮さの効き目が 1 になる所 (3 日に一度ほど会っている人の落ち着くあたり)
FRESH_DROP = 0.15                 # 前の日に交流したとき, 慣れの落ち着き先へ近づく割合 (差に対して)
FRESH_HABIT_K = 45.0              # 慣れの落ち着き先 = FRESH_REST − これ × 仲の近さの係数 (close_k)
FRESH_BACK = 0.10                 # 交流しなかった日に FRESH_REST へ戻る割合 (差に対して)
NOVEL = {"place": (0.6, 2.0, 6.0), "topic": (0.5, 1.0, 4.0)}      # 初めてのこと: (戻る確率, 幅の下限, 上限)


def _clamp(v, lo, hi):
    return max(lo, min(hi, float(v)))


class Waves:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 記録
    def rec(self, char, st, now=None):
        r = st.get("waves")
        if r and "p" in r and "fresh" in r:
            return r
        now = now or time.time()
        rnd = random.Random("waves:%s" % char["id"])
        freq = self.app.bonds.freq(st, now, 14)
        r = {"p": "normal", "from": now, "until": now + rnd.uniform(2, 10) * 86400, "told": False,
             "fresh": round(_clamp(80 - 4 * freq + rnd.uniform(-5, 5), 35, 90), 1), "since": now}
        st["waves"] = r
        trace = getattr(self.app, "trace", None)
        if trace:
            trace.add("waves", "時期と新鮮さを初めて決めた", char.get("id"), now, fresh=r["fresh"], freq=freq)
        return r

    def period(self, char, st):
        return self.rec(char, st)["p"]

    def fresh(self, char, st):
        return float(self.rec(char, st)["fresh"])

    # ------------------------------------------------------------------ 倍率
    def mult(self, char, st, key):
        """いまの時期の倍率. 時期の時間平均が 1 になるよう MEAN で割る (ふつうの時期はわずかに 1 を超える).
        down の apart は依存度しだい (頼って増える / 閉じこもる)."""
        w = WAVES.get(self.period(char, st)) or {}
        if key == "apart" and w.get("apart", 1) is None:
            dep = self.app.attach.factor(char, st, "dependence")
            v = _clamp(DOWN_APART0 + 0.7 * max(0.0, dep) + 0.4 * max(0.0, dep) ** 2, DOWN_APART0, 1.3)
        else:
            v = w.get(key)
            v = 1.0 if v is None else float(v)
        return round(v / MEAN[key], 3) if key in MEAN and key in NORM else v

    def fresh_f(self, char, st, near=False):
        """新鮮さの効き目: 0.8〜1.2 倍 (そばの話しかけは 0.9〜1.1 倍). FRESH_CENTER で 1."""
        k = 0.2 if near else 0.4
        return round(_clamp(1 + k * (self.fresh(char, st) - FRESH_CENTER) / 100.0, 1 - k / 2, 1 + k / 2), 3)

    def ctx(self, char, st):
        """条件式・度合いに使う値 (engine.context に入る)."""
        return {"wave": self.period(char, st),
                "wave_apart": round(self.mult(char, st, "apart") * self.fresh_f(char, st), 3),
                "wave_near": round(self.mult(char, st, "near") * self.fresh_f(char, st, near=True), 3),
                "fresh": round(self.fresh(char, st), 1)}

    def invite_factor(self, char, st):
        return round(self.mult(char, st, "invite") * self.fresh_f(char, st), 3)

    def accept_shift(self, char, st):
        """誘いを受ける見込みに足す分 (時間平均 0)."""
        return round(float((WAVES.get(self.period(char, st)) or {}).get("accept", 0.0)) - MEAN["accept"], 4)

    def mood_shift(self, char, st):
        """機嫌の落ち着く先に足す分 (時間平均 0)."""
        return round(float((WAVES.get(self.period(char, st)) or {}).get("mood", 0.0)) - MEAN["mood"], 3)

    def lean_gain(self, char, st):
        """依存度の「一緒にいて寂しさが紛れた」の上がり幅への倍率 (0.6〜1.45. FRESH_CENTER で 1).
        慣れて当たり前になるほど深まりにくい."""
        return round(1 + (self.fresh(char, st) - FRESH_CENTER) / 100.0, 3)

    def decline_key(self, char, st, t=None):
        """誘いを断るときの理由のセリフ (時期しだい. 必ずではない). 無ければ None.
        「友達と約束がある」(social) は, 誘われた日に本当に知り合いと会う予定があるときだけ (core/circle.py. 作り事にしない).
        予定があれば, 時期によらず言うことがある."""
        circle = getattr(self.app, "circle", None)
        has_plan = bool(t and circle and circle.plans_on(char, st, t))
        k = (WAVES.get(self.period(char, st)) or {}).get("say")
        if k == "appoint_no_friends" and not has_plan:
            return None
        if not k and has_plan:
            k = "appoint_no_friends"
        return k if k and random.random() < SAY_REASON else None

    # ------------------------------------------------------------------ 時期の移り
    def weights(self, char, st, t):
        """次の時期のくじの重み."""
        app = self.app
        tr = app.traits(char)
        p = st["params"]
        m = datetime.fromtimestamp(t).month
        life = (char.get("life") or {}).get("type", "")
        approach = float(tr.get("approach", 1))
        w = dict(BASE_W)
        if life == "freelance":
            w["busy"] *= 1.3
        if m in BUSY_MONTHS.get(life, ()):
            w["busy"] *= 1.8
        if float(tr.get("chrono", 0)) > 0.3:
            w["hooked"] *= 1.3
        if approach < 1:
            w["hooked"] *= 1.2
        w["social"] *= max(0.5, min(1.6, approach))
        if m in SOCIAL_MONTHS:
            w["social"] *= 1.4
        if p.get("stress", 0) >= 60:
            w["down"] *= 1.8
        if p.get("mood", 50) < 40:
            w["down"] *= 1.5
        if m == 8:
            w["free"] *= 1.3
        if life == "student":
            w["free"] *= 1.2
        return w

    def next(self, char, st, t):
        r = self.rec(char, st, t)
        old = r["p"]
        if old == "normal" and random.random() >= KEEP_NORMAL:
            w = self.weights(char, st, t)
            p = random.choices(SPECIAL, [w[k] for k in SPECIAL])[0]
            days = random.triangular(*WAVE_DAYS)
        else:
            p = "normal"
            days = random.uniform(*NORMAL_DAYS)
        r.update(p=p, **{"from": t}, until=t + days * 86400, told=False)
        trace = getattr(self.app, "trace", None)
        if trace:
            trace.add("waves", "時期が移った: %s → %s" % (WAVES[old]["label"], WAVES[p]["label"]), char.get("id"), t,
                      days=round(days, 1))
        return p

    def daily(self, char, st, t):
        """日付が替わったとき (相手の毎日): 時期の期限と, 新鮮さの上下."""
        r = self.rec(char, st, t)
        if t >= r.get("until", 0):
            self.next(char, st, t)
        gap = self.app.bonds.gap_days(st, t)
        old = r["fresh"]
        if gap < 1:
            habit = self.habit(char, st)
            if old > habit:
                rnd = random.Random("fresh:%s" % char["id"])
                k = (old - habit) * FRESH_DROP * rnd.uniform(0.7, 1.3) * random.uniform(0.5, 1.3)
                r["fresh"] = round(_clamp(old - k, FRESH_MIN, FRESH_MAX), 2)
        else:
            r["fresh"] = round(_clamp(old + (FRESH_REST - old) * FRESH_BACK * random.uniform(0.6, 1.2), FRESH_MIN, FRESH_MAX), 2)

    def habit(self, char, st):
        """慣れの落ち着き先: 毎日のように会っていても, ここより下がらない (仲が近いほど高い)."""
        return FRESH_REST - FRESH_HABIT_K * self.close_k(char, st)

    def close_k(self, char, st):
        """仲の近さで, 慣れて新鮮さが下がるのが鈍る (同居 0.35・家に行ける仲 0.55. 好感度 70 以上でさらに 0.8 倍)."""
        k = {"live": 0.35, "visit": 0.55}.get(self.app.bonds.stage(char["id"]), 1.0)
        if st["params"].get("affection", 50) >= 70:
            k *= 0.8
        return k

    def novel(self, char, st, kind, now=None, why=""):
        """初めてのこと (kind: place / topic) で新鮮さが戻る (確率. 必ずではない). 戻った幅を返す."""
        r = self.rec(char, st, now)
        prob, lo, hi = NOVEL[kind]
        if random.random() >= prob:
            return 0.0
        old = r["fresh"]
        r["fresh"] = round(_clamp(old + random.uniform(lo, hi), FRESH_MIN, FRESH_MAX), 2)
        trace = getattr(self.app, "trace", None)
        if trace:
            trace.add("waves", "初めてのことで新鮮さが戻った (%s)" % kind, char.get("id"), now, fresh=r["fresh"], d=round(r["fresh"] - old, 2),
                      why=why)
        return r["fresh"] - old

    # ------------------------------------------------------------------ 口にする
    def tell_key(self, char, st):
        """時期の間に送るメッセージに添える一言のキー (時期ごとに一度だけ. 確率). 無ければ None."""
        r = self.rec(char, st)
        if r["p"] == "normal" or r.get("told") or random.random() >= TELL_CHANCE:
            return None
        r["told"] = True
        return "wave_" + r["p"]

    def debug(self, char, st, now):
        """チート画面 (engine.cheat_view) 用."""
        r = self.rec(char, st, now)
        return {"時期": WAVES[r["p"]]["label"], "時期の残り": "%.1f 日" % max(0.0, (r["until"] - now) / 86400.0),
                "新鮮さ": round(r["fresh"], 1), "連絡の倍率（時期 × 新鮮さ）": self.ctx(char, st)["wave_apart"]}

    def view(self, char, st):
        r = self.rec(char, st)
        return {"period": r["p"], "label": WAVES[r["p"]]["label"], "until": r["until"], "fresh": r["fresh"]}
