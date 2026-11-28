"""あなたの好みの記憶 (A44 段 1. 相手が「この人はこれが好き」と覚える).

- 値は状態の prefs (鍵 → −10〜+10). 鍵: pose:<id> / show:<id> / outfit:<id> (ポーズ・見せて・着せた服. core/posing.py),
  act:<aid> (ふれあい・手をつなぐ・一緒に映画), place:<id> (あなたから誘って一緒に行った所), game:<gid> (あなたが選んで始めたゲーム),
  genre:<id> (一緒に観た映画のジャンル).
- 薄れ: 最後に覚えてから半減期 HALF_DAYS 日 (prefs_t に最後に覚えた時刻). 読むときに計算するので, 閉じていた間・再起動でずれない.
  覚えるときに, 薄れた値を確定してから足す. 時刻の無い鍵 (この仕組みより前に覚えたもの) は, 最初に触れたときに今を入れる (遡及: 今日から薄れ始める).
- 効き: factor は働きかけ・行き先の重みに掛ける倍率. 回数で必ず出る作りにしない (重みだけ. 出る条件・間隔は変えない).
  受け止めは世話焼き (traits の carer) で 0.6〜1.1, 機嫌が悪いと効かない. 見せない値 (画面に出さない).
"""
import time

HALF_DAYS = 30.0
CAP = 10.0
GAIN = 0.05            # 好み 1 あたりの重みの増え (受け止め 1 のとき)
F_MIN, F_MAX = 0.6, 1.6
MOOD_MIN = 40          # これより機嫌が悪いと, 覚えた好みは働きかけに効かない


def _decayed(v, t, now):
    if not t or now <= t:
        return v
    return v * 0.5 ** ((now - t) / (HALF_DAYS * 86400.0))


def _stamp(st, now):
    """時刻の無い鍵に, 今を入れる (一度だけ. 二重に入れない)."""
    pt = st.setdefault("prefs_t", {})
    for k in st.get("prefs") or {}:
        if k not in pt:
            pt[k] = now
    return pt


def pref(st, key, now=None):
    """いまの好み (薄れを入れた値). 鍵の末尾が * なら, その種類の最大 (例 game:*)."""
    now = now or time.time()
    prefs = st.get("prefs") or {}
    pt = _stamp(st, now) if prefs else {}
    if key.endswith("*"):
        head = key[:-1]
        vals = [_decayed(float(v), pt.get(k), now) for k, v in prefs.items() if k.startswith(head)]
        return max(vals) if vals else 0.0
    return _decayed(float(prefs.get(key, 0.0)), pt.get(key), now)


def best(st, head, now=None, floor=0.0):
    """その種類 (head = "game:" など) でいちばんの鍵と値. 無ければ (None, 0)."""
    now = now or time.time()
    out = (None, 0.0)
    for k in list((st.get("prefs") or {})):
        if k.startswith(head):
            v = pref(st, k, now)
            if v > max(out[1], floor):
                out = (k, v)
    return out


def learn(st, key, amount, now=None):
    now = now or time.time()
    prefs = st.setdefault("prefs", {})
    pt = _stamp(st, now)
    v = _decayed(float(prefs.get(key, 0.0)), pt.get(key), now)
    prefs[key] = round(max(-CAP, min(CAP, v + amount)), 2)
    pt[key] = now


def receptive(app, char, st):
    """覚えた好みをどれだけ汲むか (0 = 汲まない〜1.1). 世話焼きほど汲み, 機嫌が悪いと汲まない."""
    if st["params"].get("mood", 50) < MOOD_MIN:
        return 0.0
    return 0.6 + 0.5 * max(0.0, min(1.0, float(app.traits(char).get("carer", 0.3) or 0)))


def factor(app, char, st, keys, now=None):
    """重みの倍率 (F_MIN〜F_MAX). keys は鍵 1 つか並び (並びなら最大の好みで)."""
    if not keys:
        return 1.0
    keys = [keys] if isinstance(keys, str) else keys
    v = max(pref(st, k, now) for k in keys)
    return max(F_MIN, min(F_MAX, 1.0 + GAIN * v * receptive(app, char, st)))
