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
    """その日の基本の (起きる分, 寝る分). 寝る分は 1440 (= 翌 0:00) を超えない. 予定に睡眠が無ければ None."""
    es = [e for e in _entries(char, d, matcher) if e.get("asleep")]
    if not es:
        return None
    wake, bed = None, None
    for e in es:
        f, t = _mins(e.get("from", "00:00")), _mins(e.get("to", "24:00"))
        if f == 0 or f > t:                   # 朝まで寝ている (0:00 から, または日をまたぐ)
            wake = t if t < 12 * 60 else wake
        if f >= 12 * 60:                      # 夜に寝る
            bed = f
    if bed is None:
        nxt = [e for e in _entries(char, d + timedelta(days=1), matcher) if e.get("asleep") and _mins(e.get("from", "00:00")) == 0]
        bed = DAY if nxt else None
    return wake, bed


def free_morning(char, d, matcher):
    """その日の朝 (昼まで) に出かける予定が無い."""
    for e in _entries(char, d, matcher):
        if e.get("away") and _mins(e.get("from", "00:00")) < 12 * 60:
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
        if prev and ptimes and ptimes[1] is not None:
            pbed = ptimes[1]
            end = (DAY + (wake or 0) + (pl or {}).get("wake", 0)) if prev["all_night"] else pbed + max(0, prev["bed"])
            if end > DAY and m < end - DAY and not raw(dt).get("away"):
                s = raw(datetime.combine(d - timedelta(days=1), datetime.min.time()) + timedelta(minutes=pbed - 1))
                return self._awake(s, prev["all_night"])
        if not pl:
            return raw(dt)
        base = raw(dt)
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
    def _awake(s, all_night):
        """寝る前の場面のまま起きている (夜ふかし・徹夜)."""
        if s.get("asleep") or s.get("away"):
            s = dict(s, activity="night", asleep=False, away=False, busy=False, location=s.get("location") or "")
        return dict(s, label="徹夜している" if all_night else "夜ふかし中")
