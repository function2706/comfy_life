"""生活リズムの揺らぎ: 予定 (キャラの schedule) は基本の一日. その日ごとに, 起きる時刻・寝る時刻・仕事の終わりが少しずれる.

- 起きる時刻: 前後に少しずれる. 朝に予定の無い日 (休みの日) は寝坊しやすい
- 寝る時刻: 疲れている・具合が悪いと早寝. 翌朝に予定が無い・機嫌がいいと夜ふかし. ごくまれに徹夜 (ストレスが高いと少し増える)
- 仕事・バイト: ときどき残業で終わりが延びる
- ずれ幅は性格の時間の正確さ (traits.punctual) しだい. 正確な人ほど小さく, ルーズな人ほど大きい

その日のずれは, 初めてその日を見たときの本人の状態で決めて状態の rhythm に覚える (読み込み直しても変わらない).
過去の日 (覚えていない日) は, 日付とキャラから決まる揺らぎだけ (状態は見ない). 入れる前の日 (rhythm_since より前) は揺らさない.
夜ふかし・徹夜の翌日が眠いのは, 起きている時間が延びるぶん眠気・体力の動き (params) で自然にそうなる.
「予定を知っている」(knowsched) で見える時刻は基本の予定のまま. その日のずれは, 会ったり連絡したりして分かる.
"""
import random
from datetime import datetime, timedelta

WORK_ACTS = ("parttime", "work", "job", "office", "shift")
WORK_WORDS = ("バイト", "仕事", "勤務", "出勤")
KEEP_DAYS = 4                 # 状態に覚えておく日数
DAY = 1440


def _mins(s):
    h, m = str(s).split(":")
    return int(h) * 60 + int(m)


def irregular(app, char):
    """ずれ幅の倍率 (性格の時間の正確さ punctual 0.5〜0.95 → 1.7〜0.35)."""
    p = float(app.traits(char).get("punctual", 0.8))
    return max(0.3, min(1.8, 0.35 + (0.95 - p) * 3.0))


def _entries(char, d, matcher):
    dt = datetime(d.year, d.month, d.day, 12, 0)
    return [e for e in char.get("schedule") or [] if matcher(e.get("days"), dt)]


def sleep_times(char, d, matcher):
    """その日の基本の (起きる分, 寝る分). 寝る分は 1440 (= 翌 0:00) を超えない. 予定に睡眠が無ければ None.
    夜に寝て朝起きる人は 起きる分 < 寝る分 (寝るのはその日の夜). 日付が変わってから寝る人・昼に寝る人 (夜勤) は,
    その日のうちの主な睡眠の枠を取り, 寝る分 < 起きる分 になる (same_day)."""
    es = [e for e in _entries(char, d, matcher) if e.get("asleep")]
    if not es:
        return None
    runs = []
    for e in es:
        f, t = _mins(e.get("from", "00:00")), _mins(e.get("to", "24:00"))
        runs += [(0, t), (f, DAY)] if f > t else [(f, t)]       # 1 行で日をまたぐ書き方は, 0:00 で割って見る
    runs.sort()
    merged = []
    for f, t in runs:
        if merged and f <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], t))
        else:
            merged.append((f, t))
    head = merged[0] if merged[0][0] == 0 else None
    if head or all(f >= 12 * 60 for f, _ in merged):           # 夜に寝て朝起きる
        wake = head[1] if head and head[1] < 12 * 60 else None
        late = [f for f, _ in merged if f >= 12 * 60]
        bed = late[-1] if late else None
        if bed is None:
            nxt = [e for e in _entries(char, d + timedelta(days=1), matcher) if e.get("asleep") and _mins(e.get("from", "00:00")) == 0]
            bed = DAY if nxt else None
        return wake, bed
    f, t = max(merged, key=lambda r: r[1] - r[0])              # 日付が変わってから寝る・昼に寝る: 主な睡眠の枠
    return (t if t < DAY else None), f


def same_day(times):
    """その日のうちに寝て起きる形か (日付が変わってから寝る・昼に寝る)."""
    return bool(times) and times[0] is not None and times[1] is not None and times[1] < times[0]


def free_morning(char, d, matcher):
    """起きたあとしばらく, 出かける予定が無い (朝に起きる人は昼まで. 昼すぎに起きる人は, 起きてから 5 時間)."""
    times = sleep_times(char, d, matcher)
    wake = times[0] if times else None
    for e in _entries(char, d, matcher):
        if not e.get("away"):
            continue
        f = _mins(e.get("from", "00:00"))
        if (f < 12 * 60) if (wake is None or wake < 12 * 60) else (wake <= f < wake + 300):
            return False
    return True


def work_end(char, d, matcher):
    """その日の仕事・バイトの終わりの分 (無ければ None). いちばん遅いもの."""
    ends = []
    for e in _entries(char, d, matcher):
        if e.get("activity") in WORK_ACTS or any(w in (e.get("label") or "") for w in WORK_WORDS):
            t = _mins(e.get("to", "24:00"))
            if 0 < t < DAY:
                ends.append(t)
    return max(ends) if ends else None


def decide(app, char, st, d, matcher, use_state=True):
    """その日の揺らぎ {wake, bed, all_night, ot} (分). 状態を見るのは use_state のときだけ."""
    rnd = random.Random("%s:%s" % (char.get("id"), d.isoformat()))
    irr = irregular(app, char)
    p = (st or {}).get("params", {}) if use_state else {}
    energy, health = p.get("energy", 60), p.get("health", 80)
    mood, stress = p.get("mood", 50), p.get("stress", 20)
    free_next = free_morning(char, d + timedelta(days=1), matcher)
    wake = max(-45, min(45, rnd.gauss(0, 12 * irr)))
    if free_morning(char, d, matcher) and rnd.random() < 0.35 * min(1.2, irr):
        wake += rnd.uniform(20, 90)                                  # 休みの日の寝坊
    p_early = 0.06 + max(0, 35 - energy) / 100.0 + max(0, 60 - health) / 80.0
    p_late = (0.08 + (0.17 if free_next else 0) + max(0, mood - 60) / 200.0) * irr
    p_allnight = (0.004 + (0.006 if free_next else 0) + (0.01 if stress >= 60 else 0)) * irr
    r = rnd.random()
    bed, all_night = 0, False
    if r < p_allnight and energy >= 30 and health >= 60:
        all_night = True
    elif r < p_allnight + p_early:
        bed = -rnd.uniform(30, 90)
    elif r < p_allnight + p_early + p_late:
        bed = rnd.uniform(30, 120)
    ot = 0
    if work_end(char, d, matcher) is not None and rnd.random() < 0.15 * max(0.6, min(1.3, irr)):
        ot = rnd.choice((30, 45, 60, 90, 120))                        # 残業
    return {"wake": int(round(wake / 5.0) * 5), "bed": int(round(bed / 5.0) * 5), "all_night": all_night, "ot": ot}


class Rhythm:
    def __init__(self, app):
        self.app = app

    def plan(self, char, d):
        """その日の揺らぎ. 入れる前の日は None."""
        app = self.app
        cid = char.get("id")
        if not cid or cid not in getattr(app, "chars", {}):
            return None
        st = app.state(cid)
        since = st.get("rhythm_since")
        if not since:
            since = st["rhythm_since"] = datetime.now().date().isoformat()
        if d.isoformat() < since:
            return None
        rec = st.setdefault("rhythm", {})
        key = d.isoformat()
        if key not in rec:
            from .engine import day_match
            today = datetime.now().date()
            got = decide(app, char, st, d, day_match, use_state=d >= today)
            if d < today - timedelta(days=1):
                return got                   # 過去の日 (状態を見ない決め方なので, 覚えなくても同じになる)
            rec[key] = got
            for k in sorted(rec)[:-KEEP_DAYS]:
                if k != key:
                    rec.pop(k, None)
        return rec[key]

    def adjust(self, char, dt, raw):
        """基本の予定の場面 raw を, その日の揺らぎで直す. raw(datetime) は基本の予定の場面を返す関数."""
        from .engine import day_match
        d = dt.date()
        m = dt.hour * 60 + dt.minute
        today = sleep_times(char, d, day_match)
        if today is None:
            return raw(dt)
        wake, bed = today
        pl = self.plan(char, d)
        prev = self.plan(char, d - timedelta(days=1))
        ptimes = sleep_times(char, d - timedelta(days=1), day_match)
        # 前の晩の夜ふかし・徹夜が, 日付をまたいで続いている
        if prev and ptimes and ptimes[1] is not None and not same_day(ptimes):
            pbed = ptimes[1]
            end = (DAY + (wake or 0) + (pl or {}).get("wake", 0)) if prev["all_night"] else pbed + max(0, prev["bed"])
            if end > DAY and m < end - DAY and not raw(dt).get("away"):
                s = raw(datetime.combine(d - timedelta(days=1), datetime.min.time()) + timedelta(minutes=pbed - 1))
                return self._awake(s, prev["all_night"])
        if not pl:
            return raw(dt)
        base = raw(dt)
        day0 = datetime.combine(d, datetime.min.time())
        if same_day(today):
            # 日付が変わってから寝る人・昼に寝る人 (夜勤): 寝るのも起きるのも, その日のうち
            if pl["all_night"] and bed <= m < wake and not base.get("away"):
                return self._awake(raw(day0 + timedelta(minutes=max(0, bed - 1))), True, night=bed < 240)
            if pl["bed"] > 0 and bed <= m < bed + pl["bed"] and not base.get("away"):
                return self._awake(raw(day0 + timedelta(minutes=max(0, bed - 1))), False, night=bed < 240)
            if pl["bed"] < 0 and bed + pl["bed"] <= m < bed and not base.get("away") and not base.get("asleep"):
                return raw(day0 + timedelta(minutes=bed))
            if not pl["all_night"]:
                w = wake + pl["wake"]
                if pl["wake"] > 0 and wake <= m < w and not base.get("away"):
                    s = raw(day0 + timedelta(minutes=wake - 1))
                    if s.get("asleep"):
                        return dict(s, label=s.get("label") or "就寝中")
                if pl["wake"] < 0 and w <= m < wake:
                    return raw(day0 + timedelta(minutes=wake))
            wake = bed = None                 # 朝・夜の直しは済み (残業だけ下で)
        else:
            # 夜中の 0 時すぎに寝る人が, 今夜は早寝する (翌日の枠の寝る時刻が, 日付の前へ出る)
            nt = sleep_times(char, d + timedelta(days=1), day_match)
            if same_day(nt) and nt[1] < 180 and m >= DAY - 120 and not base.get("away") and not base.get("asleep"):
                npl = self.plan(char, d + timedelta(days=1))
                if npl and npl["bed"] < 0 and m >= DAY + nt[1] + npl["bed"]:
                    return raw(day0 + timedelta(days=1, minutes=nt[1]))
        # 朝: 寝坊 (まだ寝ている) / 早起き (もう起きている)
        if wake is not None and not (prev and prev["all_night"]):
            w = wake + pl["wake"]
            if pl["wake"] > 0 and wake <= m < w and not base.get("away"):
                s = raw(datetime.combine(d, datetime.min.time()) + timedelta(minutes=max(0, wake - 1)))
                if s.get("asleep"):
                    return dict(s, label=s.get("label") or "就寝中")
            if pl["wake"] < 0 and w <= m < wake:
                return raw(datetime.combine(d, datetime.min.time()) + timedelta(minutes=wake))
        # 仕事・バイトの残業
        we = work_end(char, d, day_match)
        if pl["ot"] and we is not None and we <= m < we + pl["ot"]:
            s = raw(datetime.combine(d, datetime.min.time()) + timedelta(minutes=we - 1))
            return dict(s, label=(s.get("label") or "仕事中").rstrip("中") + "（残業中）")
        # 夜: 早寝 (もう寝ている) / 夜ふかし・徹夜 (まだ起きている)
        if bed is not None:
            if pl["all_night"] and m >= bed:
                s = raw(datetime.combine(d, datetime.min.time()) + timedelta(minutes=bed - 1))
                return self._awake(s, True)
            if pl["bed"] > 0 and bed <= m < bed + pl["bed"]:
                s = raw(datetime.combine(d, datetime.min.time()) + timedelta(minutes=bed - 1))
                return self._awake(s, False)
            if pl["bed"] < 0 and bed + pl["bed"] <= m < bed and not base.get("away") and not base.get("asleep"):
                if bed < DAY:
                    return raw(datetime.combine(d, datetime.min.time()) + timedelta(minutes=bed))
                return raw(datetime.combine(d + timedelta(days=1), datetime.min.time()))
        return base

    @staticmethod
    def _awake(s, all_night, night=True):
        """寝る前の場面のまま起きている (夜ふかし・徹夜). night: 夜のうちか (昼に寝る人は「夜ふかし」とは言わない)."""
        if s.get("asleep") or s.get("away"):
            s = dict(s, activity="night", asleep=False, away=False, busy=False, location=s.get("location") or "")
        if not night:
            return dict(s, label="寝ないで起きている" if all_night else "まだ起きている")
        return dict(s, label="徹夜している" if all_night else "夜ふかし中")
