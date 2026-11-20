"""相手の交友関係 (core/circle.py) が, 現実のラインに収まっているかを数える (A34).

段 1 (人と予定):
- 予定の多さ: 相手ごとに 1 年ぶん日締めを進め, 週あたりの予定の数 (平日 / 週末)・会う人の向き・予定の種類.
  目安: 週 0.5〜2 件ほど (社交的な性格・人付き合いの時期で多く). 苦手な人と会うのは 1 割ほどまで (ほぼ仕事の付き合い).
- 機嫌の偏り: 同じ相手を, 予定あり / なし (場面を重ねない) で 4 週ずつ進め, 機嫌・ストレス・寂しさの時間平均の差.
  目安: 機嫌の差は ±2 以内 (苦手な人がいても, 全体を大きく下げない).
段 3 (負の出来事と人の移り): 同じ 1 年で, 人の入れ替わり (加わる / 抜ける)・人数の幅・喧嘩 / 和解・言い寄る人のいる日の割合と
  連絡の数・元恋人からの連絡の数. 目安: 入れ替わりは年に数人〜十人ほど (人数は 3〜9 人に収まる). 喧嘩は年に 0〜2 回ほど.
  言い寄る人がいる日は 3 割以下・連絡は週 1〜2 回まで. 元恋人からの連絡は年に数回まで.
  機嫌の偏りは, 予定に加えて段 3 の出来事も「無い場合」(Circle.events_on = False) と比べる.
段 4 (恋愛) が入ったら, ここに 1 年で付き合い始める割合・浮気の割合を足す (目安は REMAINING の A34).

    python tools/check_circle.py
    python tools/check_circle.py --days 364 --weeks 4 --seed 3 --runs 5
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


COUNT = Counter()


def _counting():
    """段 3 の出来事を数える (Circle のメソッドを包む)."""
    def wrap(name, key):
        real = getattr(C.Circle, name)

        def f(self, *a, **k):
            COUNT[key(a, k) if callable(key) else key] += 1
            return real(self, *a, **k)
        setattr(C.Circle, name, f)
    wrap("_join", "join")
    wrap("_leave", lambda a, k: "leave:" + a[5])
    wrap("_mend", "mend")
    wrap("_event", lambda a, k: "event:" + a[3]["kind"])
    real_after = C.Circle._after

    def after(self, char, st, r, x, now):
        p = self.person(char, st, x["pid"]) or {}
        q = (p.get("flags") or {}).get("quarrel")
        real_after(self, char, st, r, x, now)
        if (p.get("flags") or {}).get("quarrel") != q:
            COUNT["quarrel"] += 1
    C.Circle._after = after


def plans_year(app, char, st, days, stat=None):
    st.pop("circle", None)
    t0 = T0.timestamp()
    app.circle.rec(char, st, t0 - 86400)
    seen, out = set(), []
    alive, suitor_days = [], 0
    for d in range(days):
        t = t0 + d * 86400 + 60
        app.circle.daily(char, st, t)
        app.circle.step(char, st, t, t + 86400 - 120)          # その日の予定のあと・出来事 (日ごと. 効き目は数えない)
        r = st["circle"]
        alive.append(len(app.circle.alive(r)))
        suitor_days += any(p["kind"] == "suitor" for p in app.circle.alive(r))
        for p in r["plans"]:
            k = (p["t0"], p["pid"])
            if k not in seen:
                seen.add(k)
                out.append(p)
    if stat is not None:
        stat.update(alive_min=min(alive), alive_max=max(alive), suitor=suitor_days / float(days))
    return out


def bad_n(st, ps, app, char):
    return sum(1 for p in ps if (app.circle.person(char, st, p["pid"]) or {}).get("tone") in ("uneasy", "strained")) / 52.0


def mood_run(app, char, st, weeks, with_plans, seed):
    """weeks 週ぶん, 本人の 5 分刻み (_step) と日締めを進めて, 機嫌・ストレス・寂しさの平均."""
    random.seed(seed)
    st.pop("circle", None)
    st.pop("waves", None)
    st["params"].update(mood=60, stress=20, loneliness=30, boredom=35, affection=50, energy=80, satiety=70, hydration=70)
    real, real_fill = C.Circle.scene, C.Circle.fill_f
    if not with_plans:
        C.Circle.scene = lambda self, char, st, base, dt: base
        C.Circle.events_on = False
        C.Circle.fill_f = lambda self, char, st, t, pid: 1.0            # 予定が無ければ, ならしも無い
    t = T0.timestamp()
    acc = {"mood": [], "stress": [], "loneliness": []}
    try:
        for i in range(weeks * 7 * 288):
            t1 = t + 300
            if datetime.fromtimestamp(t).date() != datetime.fromtimestamp(t1).date():
                app.waves.daily(char, st, t1)
                app.circle.daily(char, st, t1)
            app._step(char, st, datetime.fromtimestamp(t + 150), 300 / 3600.0)
            app.circle.step(char, st, t, t1)                  # 予定のあとの仲の動き・言い寄る人 / 元恋人からの連絡 (段 3)
            if i % 12 == 0:
                for k in acc:
                    acc[k].append(st["params"].get(k, 0))
            t = t1
    finally:
        C.Circle.scene = real
        C.Circle.fill_f = real_fill
        C.Circle.events_on = True
    return {k: statistics.mean(v) for k, v in acc.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=364)
    ap.add_argument("--weeks", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--runs", type=int, default=5)          # 機嫌の偏りを平均する回数
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
        _counting()
        stage3 = []
        for name, char, st in vs:
            COUNT.clear()
            stat = {}
            ps = plans_year(app, char, st, a.days, stat)
            stage3.append((name, dict(COUNT), stat))
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

        print("== 段 3 の出来事 (%d 日)" % a.days)
        yr = a.days / 365.0
        tot = Counter()
        for name, cnt, stat in stage3:
            tot.update(cnt)
            print("%-22s 人 %d〜%d / 加わる %d・抜ける %d / 喧嘩 %d・和解 %d / 言い寄る人のいる日 %.0f%%・連絡 %d / 元恋人の連絡 %d" % (
                name, stat["alive_min"], stat["alive_max"], cnt.get("join", 0),
                sum(v for k, v in cnt.items() if k.startswith("leave:")), cnt.get("quarrel", 0), cnt.get("mend", 0),
                stat["suitor"] * 100, cnt.get("event:pester", 0), cnt.get("event:ex", 0)))
        n = float(len(stage3)) * yr
        sui = statistics.mean(s["suitor"] for _, _, s in stage3)
        print("全体 (1 人・1 年あたり): 加わる %.1f・抜ける %.1f / 喧嘩 %.2f・和解 %.2f / 言い寄る人のいる日 %.0f%%・連絡 %.1f / 元恋人の連絡 %.1f" % (
            tot["join"] / n, sum(v for k, v in tot.items() if k.startswith("leave:")) / n, tot["quarrel"] / n, tot["mend"] / n,
            sui * 100, tot["event:pester"] / n, tot["event:ex"] / n))
        if min(s["alive_min"] for _, _, s in stage3) < 2 or max(s["alive_max"] for _, _, s in stage3) > C.PEOPLE_MAX:
            print("!! 人数が 2〜%d 人から外れている" % C.PEOPLE_MAX)
            ok = False
        if tot["quarrel"] / n > 2.0 or sui > 0.3 or tot["event:ex"] / n > 6:
            print("!! 段 3 の出来事が多い (喧嘩 年 2 回 / 言い寄る人のいる日 3 割 / 元恋人の連絡 年 6 回 まで)")
            ok = False

        print("== 機嫌の偏り (%d 週 × %d 回の平均. 予定・段 3 の出来事あり − なし. 予定の多い人・苦手な人とよく会う人・言い寄る人 / 元恋人のいる人)"
              % (a.weeks, a.runs))
        diffs = []
        picks = sorted(by_rate, key=lambda x: -x[0])[:4]                          # 予定の多い人・苦手な人とよく会う人
        for kind in ("suitor", "ex"):                                              # 言い寄る人・元恋人がいる人 (段 3)
            more = [x for x in by_rate if x not in picks and any(p["kind"] == kind for p in app.circle._extra_people(x[2], [], 0))]
            if more:
                picks.append(more[0])
        for _, name, char, st in picks:
            # 4 週・週 1 件ほどでは予定の数のくじで差がぶれる (同じ相手で 3 件 / 8 件) ので, seed を変えて平均する
            ws = [mood_run(app, char, st, a.weeks, True, a.seed + i) for i in range(a.runs)]
            ns = [mood_run(app, char, st, a.weeks, False, a.seed + i) for i in range(a.runs)]
            w = {k: statistics.mean(x[k] for x in ws) for k in ws[0]}
            n = {k: statistics.mean(x[k] for x in ns) for k in ns[0]}
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
