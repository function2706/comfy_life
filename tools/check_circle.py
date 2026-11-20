"""相手の交友関係 (core/circle.py) が, 現実のラインに収まっているかを数える (A34).

段 1 (人と予定):
- 予定の多さ: 相手ごとに 1 年ぶん日締めを進め, 週あたりの予定の数 (平日 / 週末)・会う人の向き・予定の種類.
  目安: 週 0.5〜2 件ほど (社交的な性格・人付き合いの時期で多く). 苦手な人と会うのは 1 割ほどまで (ほぼ仕事の付き合い).
- 機嫌の偏り: 同じ相手を, 予定あり / なし (場面を重ねない) で 4 週ずつ進め, 機嫌・ストレス・寂しさの時間平均の差.
  目安: 機嫌の差は ±2 以内 (苦手な人がいても, 全体を大きく下げない).
段 4 (恋愛) が入ったら, ここに 1 年で付き合い始める割合・浮気の割合を足す (目安は REMAINING の A34).

    python tools/check_circle.py
    python tools/check_circle.py --days 364 --weeks 4 --seed 3
"""
import argparse
import os
import random
import shutil
import statistics
import sys
import tempfile
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, circle as C, lifetype  # noqa: E402

T0 = datetime(2026, 1, 5, 0, 0)             # 月曜
PERSONAS = ("amaenbo", "cool", "genki", "mukuchi", "hitonatsukko", "uchiki")
LIVES = ("office", "student", "shift", "service", "freelance", "night")


def variants(app, base):
    """性格 × 生活の型 (予定を作り直した) の組み合わせ. (名前, char, st)."""
    import copy
    for i, (pid, life) in enumerate([(p, l) for p in PERSONAS for l in LIVES]):
        c = copy.deepcopy(base)
        c["id"] = "v%d" % i
        c["persona_id"] = pid
        lifetype.assign(c, app.traits(c), seed="check%d" % i, type_id=life)
        app.chars[c["id"]] = c
        yield "%s/%s" % (pid, life), c, app.state(c["id"])


def plans_year(app, char, st, days):
    st.pop("circle", None)
    t0 = T0.timestamp()
    app.circle.rec(char, st, t0 - 86400)
    seen, out = set(), []
    for d in range(days):
        app.circle.daily(char, st, t0 + d * 86400 + 60)
        for p in st["circle"]["plans"]:
            k = (p["t0"], p["pid"])
            if k not in seen:
                seen.add(k)
                out.append(p)
    return out


def bad_n(st, ps, app, char):
    return sum(1 for p in ps if (app.circle.person(char, st, p["pid"]) or {}).get("tone") in ("uneasy", "strained")) / 52.0


def mood_run(app, char, st, weeks, with_plans, seed):
    """weeks 週ぶん, 本人の 5 分刻み (_step) と日締めを進めて, 機嫌・ストレス・寂しさの平均."""
    random.seed(seed)
    st.pop("circle", None)
    st.pop("waves", None)
    st["params"].update(mood=60, stress=20, loneliness=30, boredom=35, affection=50, energy=80, satiety=70, hydration=70)
    real = C.Circle.scene
    if not with_plans:
        C.Circle.scene = lambda self, char, st, base, dt: base
    t = T0.timestamp()
    acc = {"mood": [], "stress": [], "loneliness": []}
    try:
        for i in range(weeks * 7 * 288):
            t1 = t + 300
            if datetime.fromtimestamp(t).date() != datetime.fromtimestamp(t1).date():
                app.waves.daily(char, st, t1)
                app.circle.daily(char, st, t1)
            app._step(char, st, datetime.fromtimestamp(t + 150), 300 / 3600.0)
            if i % 12 == 0:
                for k in acc:
                    acc[k].append(st["params"].get(k, 0))
            t = t1
    finally:
        C.Circle.scene = real
    return {k: statistics.mean(v) for k, v in acc.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=364)
    ap.add_argument("--weeks", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    random.seed(a.seed)
    tmp = tempfile.mkdtemp(prefix="kurashi_check_")
    store.DATA = tmp
    ok = True
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("交友関係の確かめ")
        print("== 予定の多さ (%d 日)" % a.days)
        rates, tones_all, by_rate = [], Counter(), []
        base = next(iter(app.chars.values()))
        vs = list(variants(app, base))
        for name, char, st in vs:
            ps = plans_year(app, char, st, a.days)
            wk = a.days / 7.0
            we = sum(1 for p in ps if datetime.fromtimestamp(p["t0"]).weekday() >= 5)
            tones = Counter((app.circle.person(char, st, p["pid"]) or {}).get("tone") for p in ps)
            tones_all.update(tones)
            kinds = Counter(p["kind"] for p in ps)
            r = len(ps) / wk
            rates.append(r)
            by_rate.append((r + bad_n(st, ps, app, char) * 0.5, name, char, st))
            print("%-22s 週 %.2f 件 (週末 %.2f) / 人 %d / 向き %s / 種類 %s" % (
                name, r, we / wk, len(st["circle"]["people"]),
                dict(tones), dict(kinds)))
        bad = sum(tones_all[k] for k in ("uneasy", "strained")) / float(max(1, sum(tones_all.values())))
        print("全体: 週 %.2f 件 (%.2f〜%.2f) / 苦手な人と会う割合 %.1f%%" % (statistics.mean(rates), min(rates), max(rates), bad * 100))
        if not (0.4 <= statistics.mean(rates) <= 2.0 and max(rates) <= 3.0):
            print("!! 予定の多さが目安 (週 0.5〜2 件ほど) から外れている")
            ok = False
        if bad > 0.15:
            print("!! 苦手な人と会う割合が多い")
            ok = False

        print("== 機嫌の偏り (%d 週. 予定あり − なし. 予定の多い人・苦手な人とよく会う人)" % a.weeks)
        diffs = []
        for _, name, char, st in sorted(by_rate, key=lambda x: -x[0])[:6]:      # 予定の多い人・苦手な人とよく会う人で確かめる
            w = mood_run(app, char, st, a.weeks, True, a.seed)
            n = mood_run(app, char, st, a.weeks, False, a.seed)
            d = {k: w[k] - n[k] for k in w}
            diffs.append(d["mood"])
            print("%-22s 機嫌 %+.2f / ストレス %+.2f / 寂しさ %+.2f (なし: 機嫌 %.1f)" % (
                name, d["mood"], d["stress"], d["loneliness"], n["mood"]))
        if max(abs(x) for x in diffs) > 2.0:
            print("!! 機嫌の時間平均の差が ±2 を超えている")
            ok = False
        print("OK" if ok else "NG")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
