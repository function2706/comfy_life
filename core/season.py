"""季節と気温 (S38). 季節の表はここだけに置き, ほかはここを引く.

気温はリアルの日時から決まる (毎回同じ. 保存しない):
  月の平年値 (東京の 1991〜2020 年の平均. 月の中ほどの値を日でつなぐ) + その日の振れ (前後の日をならした波 + 5 日ごとの波)
  + 一日の上下 (5 時ごろが低く 14 時ごろが高い. くもり・雨で幅が小さい) + 天気 (雨・雪の時間帯は少し下がる).
服の暖かさ (warmth) は服の一覧に書いてあればそれ, 無ければ区分・季節の札・種類のタグ・大胆さから読むときに決める.
暑がり / 寒がり / 外好きは性格プリセットの traits (heat / cold / outdoorsy. 1 がふつう) に, キャラごとの小さな揺れを掛ける.
効かせるのは確率と重みだけ (気温で必ず断る・必ず喜ぶ道は作らない).
"""
import functools
import hashlib
import math
import random
from datetime import date, datetime, timedelta

SEASONS = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
           6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}
# 月の平年値 (℃. 東京 1991〜2020 年の月平均)
NORMAL = (5.4, 6.1, 9.4, 14.3, 18.8, 21.9, 25.7, 26.9, 23.3, 18.0, 12.5, 7.7)
AMP = (5.4, 5.4, 5.2, 5.0, 4.7, 4.1, 4.1, 4.8, 4.5, 4.7, 5.1, 5.4)       # 晴れた日の上下の幅 (平年の最高と最低の差の半分を, くもり・雨で縮む分だけ大きく)
AMP_WX = {"sunny": 1.0, "cloudy": 0.7, "rain": 0.4, "snow": 0.4}
WET_DROP = 1.5            # 雨・雪の時間帯は下がる
SNOW_MAX = 4.0            # これより暖かい時間帯の雪は雨になる (outdoor.weather)
SWING = 8.0               # その日の振れの上限
BIAS = 0.4                # 雨・雪で下がる分と, 上下の形の片寄りの埋め合わせ (月の平均が平年値になるように)


def season(dt):
    return SEASONS[dt.month]


def _g(key):
    """日付などから決まる標準正規の値 (毎回同じ)."""
    return random.Random(int(hashlib.md5(("season:" + key).encode()).hexdigest()[:12], 16)).gauss(0, 1)


def _normal(d):
    """その日の平年値と一日の幅 (月の中ほど = 15 日の値を, 日でなめらかにつなぐ)."""
    mid = date(d.year, d.month, 15)
    if d >= mid:
        nx = date(d.year + (d.month == 12), d.month % 12 + 1, 15)
        a, b, f = d.month - 1, d.month % 12, (d - mid).days / float((nx - mid).days)
    else:
        pv = date(d.year - (d.month == 1), (d.month - 2) % 12 + 1, 15)
        a, b, f = (d.month - 2) % 12, d.month - 1, (d - pv).days / float((mid - pv).days)
    f = (1 - math.cos(math.pi * f)) / 2
    return NORMAL[a] + (NORMAL[b] - NORMAL[a]) * f + BIAS, AMP[a] + (AMP[b] - AMP[a]) * f


def day_offset(d):
    """その日の振れ (数日続く暑い日・寒い日の波). 前後の日をならした波と, 5 日ごとの波."""
    n = d.toordinal()
    short = 0.25 * _g("d%d" % (n - 1)) + 0.5 * _g("d%d" % n) + 0.25 * _g("d%d" % (n + 1))
    k, f = divmod(n, 5)
    f = (1 - math.cos(math.pi * f / 5.0)) / 2
    slow = _g("w%d" % k) * (1 - f) + _g("w%d" % (k + 1)) * f
    return max(-SWING, min(SWING, 3.6 * short + 1.6 * slow))


def base_temp(dt):
    """天気を入れる前の気温."""
    mean, amp = _normal(dt.date())
    h = dt.hour + dt.minute / 60.0
    return mean + day_offset(dt.date()) + amp * _diurnal(h)


def _diurnal(h):
    """一日の上下 (−1〜1). 5 時が最低・14 時が最高 (上りは速く, 下りはゆっくり)."""
    if 5 <= h < 14:
        return -math.cos(math.pi * (h - 5) / 9.0)
    x = (h - 14) % 24
    return math.cos(math.pi * x / 15.0)


def temp(dt, wx=None):
    """その日時の気温 (℃. 小数 1 桁). wx: その時間帯の天気 id (無ければ outdoor.weather で決める)."""
    if wx is None:
        from .outdoor import weather
        wx = weather(dt)["id"]
    mean, amp = _normal(dt.date())
    h = dt.hour + dt.minute / 60.0
    t = mean + day_offset(dt.date()) + amp * AMP_WX.get(wx, 1.0) * _diurnal(h)
    if wx in ("rain", "snow"):
        t -= WET_DROP
    return round(t, 1)


@functools.lru_cache(maxsize=256)
def day_range(d):
    """その日の (最低, 最高, 平均) (5 時・14 時と, その日の平均)."""
    lo = temp(datetime(d.year, d.month, d.day, 5))
    hi = temp(datetime(d.year, d.month, d.day, 14))
    return lo, hi, round(_normal(d)[0] + day_offset(d), 1)


def indoor(t):
    """家の中の温度 (外の気温をやわらげたもの. 冷暖房の細かいことは入れない)."""
    return 21.0 + 0.4 * (t - 21.0)


def need(t):
    """その気温でちょうどいい服の暖かさ (暖かさの足し算で. 28℃ で 1.5・18℃ で 3.3・5℃ で 5.6)."""
    return 1.5 + 0.18 * (28.0 - t) if t < 28 else max(0.5, 1.5 - 0.1 * (t - 28.0))


# ------------------------------------------------------------------ 服の暖かさ
_SEASON_SCORE = {"summer": 0.0, "spring": 1.0, "autumn": 1.0, "winter": 2.0}
BY_ID = {"winter_coat": 4.8, "detective": 4.0, "santa": 3.5}          # 既定の一式のうち, コートまで含むもの (札だけでは薄く出る)
SLOT_BASE = {"top": 1.0, "onepiece": 1.5, "bottom": 1.0, "legwear": 0.4, "shoes": 0.2, "hat": 0.0, "acc": 0.0,
             "lingerie": 0.0, "outer": 1.8, "set": 2.0}


def warmth(o):
    """服の暖かさ (−0.5〜3.5 ほど). 書いてあればその値, 無ければ区分・季節の札・種類のタグ・大胆さから."""
    if o.get("warmth") is not None:
        try:
            return float(o["warmth"])
        except (TypeError, ValueError):
            pass
    if o.get("id") in BY_ID:
        return BY_ID[o["id"]]
    slot = o.get("slot") or ("outer" if o.get("kind") == "outer" else "set")
    ss = [s for s in o.get("seasons") or [] if s in _SEASON_SCORE]
    lo_ = min(_SEASON_SCORE[x] for x in ss) if ss else None                 # いちばん薄い季節 (0 夏 〜 2 冬)
    hi_ = max(_SEASON_SCORE[x] for x in ss) if ss else None                 # いちばん厚い季節
    s = (lo_ + hi_) / 2.0 if ss else None
    types = set(o.get("tags") or [])                                         # 種類のタグ (mini / skirt / long …)
    if slot == "set":
        w = 0.0 if o.get("kind") == "swim" else (2.0 if s is None else 0.5 + lo_ + 0.5 * hi_)
    elif slot == "outer":
        w = SLOT_BASE["outer"] if s is None else 0.8 + 0.7 * lo_ + 0.4 * hi_
    elif slot == "top":
        w = 1.2 if s is None else 0.5 + lo_ + 0.5 * hi_                     # タンク 0.5・T シャツ 1.0・ニット 2.5
    elif slot == "onepiece":
        w = 1.8 if s is None else 1.0 + lo_ + 0.5 * hi_
    elif slot == "bottom":
        w = 0.3 if "mini" in types else (0.9 if "long" in types else 0.7) if "skirt" in types else 1.0
        if s is not None:
            w = min(w, 0.3 + 0.7 * s)
    elif slot in ("hat", "acc"):
        w = 0.6 if (s is not None and s >= 1.5) else 0.0          # ニット帽・耳あて・マフラー・手袋
    elif slot == "shoes":
        w = 0.5 if (s is not None and s >= 1.5) else 0.0 if s == 0 else 0.2
    elif slot == "legwear":
        w = 0.9 if (s is not None and s >= 1.5) else 0.4
    else:
        w = 0.0
    bold = int(o.get("bold") or 0)
    if bold > 0 and slot in ("set", "top", "onepiece"):
        w -= 0.4 * bold                                            # 肌の出る服は薄い (ボトムスは丈で見ている)
    return round(w, 2)


def total(items):
    """重ね着の暖かさ (描かれる服の足し算. ランジェリーは数えない)."""
    return round(sum(warmth(o) for o in items if o and o.get("slot") != "lingerie"), 2)


# ------------------------------------------------------------------ 暑がり・寒がり・外好き
def _jitter(cid, k):
    return 1.0 + 0.15 * max(-1.0, min(1.0, _g("tr:%s:%s" % (cid, k)) / 1.5))


def sense(app, char):
    """{heat 暑がり, cold 寒がり, outdoorsy 外好き}. 性格の値 (1 がふつう) × キャラごとの揺れ (±15%)."""
    tr = app.traits(char) if app is not None else {}
    cid = char.get("id", "")
    return {k: round(float(tr.get(k, 1.0)) * _jitter(cid, k), 3) for k in ("heat", "cold", "outdoorsy")}


def gap(app, char, w, t, inside=False):
    """服の暖かさ w のずれ (+ 暑すぎ / − 寒すぎ). t は外の気温. 暑がりは暑い側に, 寒がりは寒い側にずれる."""
    tt = indoor(t) if inside else t
    sn = sense(app, char)
    d = w - need(tt)
    if tt < 20:
        d -= 0.8 * (sn["cold"] - 1.0)
    elif tt > 24:
        d += 0.8 * (sn["heat"] - 1.0)
    return round(d, 2)


def fit_weight(d):
    """ずれ d の服の選ばれやすさ (±1 までは変わらない. 下限 0.08: 必ず外すわけではない)."""
    x = abs(d) - 1.0
    return 1.0 if x <= 0 else max(0.08, math.exp(-2.0 * x * x))


# ------------------------------------------------------------------ 外出の気分
def load(app, char, dt, wx=None):
    """外にいる負担 (0 = 気にならない). 暑さ・寒さ・雨・雪."""
    if wx is None:
        from .outdoor import weather
        wx = weather(dt)["id"]
    t = temp(dt, wx)
    sn = sense(app, char)
    hot = max(0.0, t - 30.0) / 5.0 * sn["heat"]
    cold = max(0.0, 5.0 - t) / 6.0 * sn["cold"]
    return {"hot": hot, "cold": cold, "wet": {"rain": 0.5, "snow": 0.6}.get(wx, 0.0), "t": t}


def out_factor(app, char, dt, wx=None):
    """外の行き先への気持ち (0.35〜1.25. ふつうの日は外好きしだいで 0.95〜1.1 ほど. 猛暑日・真冬・雨で下がる)."""
    ld = load(app, char, dt, wx)
    f = (1.0 + 0.2 * (sense(app, char)["outdoorsy"] - 1.0)) / (1.0 + 0.5 * (ld["hot"] + ld["cold"] + ld["wet"]))
    return max(0.35, min(1.25, f))


def out_why(app, char, dt):
    """外へ出たくない理由 (hot / cold / None). 暑さ・寒さの負担が大きい方."""
    ld = load(app, char, dt)
    if max(ld["hot"], ld["cold"]) < 0.3:
        return None
    return "hot" if ld["hot"] >= ld["cold"] else "cold"


def label(t):
    """気温の表示 (例 31℃)."""
    return "%d℃" % int(round(t))


def view(dt):
    """画面の天気に足す {temp, lo, hi}."""
    lo, hi, _ = day_range(dt.date())
    return {"temp": int(round(temp(dt))), "lo": int(round(lo)), "hi": int(round(hi))}


def daylist(d0, days):
    """d0 から days 日の (日付, 最低, 最高) (テスト・確かめ用)."""
    return [(d0 + timedelta(days=i),) + day_range(d0 + timedelta(days=i))[:2] for i in range(days)]
