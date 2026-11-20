"""相手の関心の揺らぎ (core/waves.py) に, 意図しない負の偏りが無いかを数える.

以前 (A35 の前) は, ほかの値が同じなら倍率は毎日 1 (どの相手も同じように連絡したがる). いまは時期 (生活の波) と新鮮さで揺らぐ.
- 時期の分: どの効き先も, 時間平均で 1 (受けやすさの差・機嫌の落ち着く先は 0) になっているか.
  性格別・生活の型別・仲の段階別・1 年 (季節) で見て, どこかの層だけ下がっていないか.
- 新鮮さの分: 意図した向き (会う日が多いほど少し控える・近い仲ほど控えない) だけで, その幅が小さいか.
ほかの値 (好感度・寂しさなど) は止めて, 時期と新鮮さの倍率だけを取り出す.

    python tools/check_waves.py
    python tools/check_waves.py --days 730 --seed 3
"""
import argparse
import collections
import os
import random
import shutil
import statistics
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, waves as W  # noqa: E402

MEET = {"毎日会う": 1, "3 日に一度": 3, "週に一度": 7, "会わない": 0}
LIVES = ("office", "student", "shift", "service", "freelance", "night")
STAGES = ("contact", "visit", "live")
KEYS = ("apart", "near", "invite", "lonely", "bored", "call")


def run(app, char, st, days, t0, every, out):
    """days 日ぶん時期と新鮮さを進め, 日ごとの値を out に足す."""
    V = app.waves
    st.pop("waves", None)
    st["touch_days"] = []
    for d in range(days):
        t = t0 + d * 86400
        met = every and d % every == 0
        st["last_touch"] = t - 3600 if met else t - 2 * 86400
        V.daily(char, st, t)
        row = {k: V.mult(char, st, k) for k in KEYS}
        row["accept"] = V.accept_shift(char, st)
        row["mood"] = V.mood_shift(char, st)
        row["fresh_f"] = V.fresh_f(char, st)
        row["contact"] = V.ctx(char, st)["wave_apart"]
        row["p"] = V.period(char, st)
        row["lean"] = V.lean_gain(char, st) if met else None
        out.append(row)


def mean(rows, k):
    v = [r[k] for r in rows if r[k] is not None]
    return statistics.mean(v) if v else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    random.seed(args.seed)
    tmp = tempfile.mkdtemp(prefix="kurashi_check_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("揺らぎ")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        st["params"].update(affection=65, loneliness=40, mood=55, stress=30)
        pdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "defaults", "personas")
        pids = sorted(f[:-5] for f in os.listdir(pdir) if f.endswith(".json"))
        t0 = datetime(2026, 1, 1, 0, 5).timestamp()
        life0 = dict(char.get("life") or {})
        bad = []

        # ---- 1. 時期の分: 全部の層を合わせた時間平均 (3 日に一度会う・連絡先)
        rows_all = []
        by_p, by_l = collections.defaultdict(list), collections.defaultdict(list)
        for pid in pids:
            char["persona_id"] = pid
            st.pop("attach", None)
            for life in LIVES:
                char["life"] = dict(life0, type=life)
                rows = []
                run(app, char, st, args.days, t0, 3, rows)
                rows_all += rows
                by_p[pid] += rows
                by_l[life] += rows
        print("== 時期の分の時間平均（%d 性格 × %d 型 × %d 日. 以前はどれも 1 / 0）==" % (len(pids), len(LIVES), args.days))
        line = []
        for k in KEYS:
            m = mean(rows_all, k)
            line.append("%s %.3f" % (k, m))
            if abs(m - 1) > 0.03:
                bad.append("全体 %s %.3f" % (k, m))
        for k in ("accept", "mood"):
            m = mean(rows_all, k)
            line.append("%s %+.3f" % (k, m))
            if abs(m) > (0.01 if k == "accept" else 0.3):
                bad.append("全体 %s %+.3f" % (k, m))
        print("  " + " / ".join(line))
        cnt = collections.Counter(r["p"] for r in rows_all)
        print("  時期の割合: " + " / ".join("%s %.0f%%（基準 %.0f%%）" % (W.WAVES[k]["label"], 100 * cnt[k] / len(rows_all), 100 * W.SHARE[k])
                                          for k in W.WAVES))

        def layer(title, groups, label=lambda x: x):
            print("== %s（連絡 apart の時期の分の平均. 0.9〜1.1 を外れたら偏り）==" % title)
            vals = []
            for g, rows in sorted(groups.items()):
                m = mean(rows, "apart")
                vals.append((m, label(g)))
                if not 0.9 <= m <= 1.1:
                    bad.append("%s %s apart %.3f" % (title, label(g), m))
            vals.sort()
            print("  低い順: " + " / ".join("%s %.2f" % (n, m) for m, n in vals[:4]) + " … 高い順: "
                  + " / ".join("%s %.2f" % (n, m) for m, n in vals[::-1][:4]))
        names = {}
        for pid in pids:
            char["persona_id"] = pid
            names[pid] = (app.persona(char) or {}).get("name", pid) if hasattr(app, "persona") else pid
        layer("性格別", by_p, lambda g: names.get(g, g))
        layer("生活の型別", by_l)

        # 季節: 月ごと
        by_m = collections.defaultdict(list)
        for i, r in enumerate(rows_all):
            by_m[datetime.fromtimestamp(t0 + (i % args.days) * 86400).month].append(r)
        print("== 月別（連絡 apart の時期の分）==")
        print("  " + " / ".join("%d月 %.2f" % (m, mean(rs, "apart")) for m, rs in sorted(by_m.items())))
        yr = mean(rows_all, "apart")
        for m, rs in by_m.items():
            if not 0.8 <= mean(rs, "apart") <= 1.2:
                bad.append("月別 %d月 %.3f" % (m, mean(rs, "apart")))

        # ---- 2. 新鮮さの分: 会い方 × 仲の段階 (性格 5 つ・会社員で)
        char["life"] = dict(life0, type="office")
        print("== 新鮮さの分（会い方 × 仲. 連絡の倍率 fresh_f / 依存度の上がり幅 lean の平均. 意図した向きだけか）==")
        table = {}
        for stage in STAGES:
            app.bonds.set_stage(cid, stage)
            cells = []
            for label, every in MEET.items():
                rows = []
                for pid in pids[::5]:
                    char["persona_id"] = pid
                    st.pop("attach", None)
                    run(app, char, st, 120, t0, every, rows)
                f, ln, c = mean(rows[30:], "fresh_f"), mean(rows[30:], "lean"), mean(rows[30:], "contact")
                table[(stage, label)] = f
                cells.append("%s %.2f%s（時期込み %.2f）" % (label, f, "" if ln != ln else " / lean %.2f" % ln, c))
            print("  %s: %s" % ({"contact": "連絡先", "visit": "家に行ける仲", "live": "同居"}[stage], " / ".join(cells)))
        for stage in STAGES:
            if not table[(stage, "毎日会う")] <= table[(stage, "3 日に一度")] <= table[(stage, "週に一度")] + 1e-9:
                bad.append("新鮮さの向き %s" % stage)
            if table[(stage, "毎日会う")] < 0.88:
                bad.append("新鮮さ 毎日会う %s %.3f（下げすぎ）" % (stage, table[(stage, "毎日会う")]))
        if not table[("contact", "毎日会う")] <= table[("visit", "毎日会う")] <= table[("live", "毎日会う")]:
            bad.append("新鮮さ 近い仲ほど控えない になっていない")
        print("偏りの候補: " + ("なし" if not bad else " / ".join(bad)))
        return 1 if bad else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
