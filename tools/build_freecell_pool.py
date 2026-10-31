"""フリーセルの「難しさごとの配り」の一覧 (乱数の種) を defaults/freecell_pool.json に書き出す.

    python tools/build_freecell_pool.py [難しさ ...] [--n 200] [--jobs 4]

フリーセルはセル 4 つ (標準) で遊ぶ. 難しさは配りの余裕で分ける: その配りを解くのに要るセルの数 (core/solitaire.fc_need) が
易は 2 つ以下, 中は 3 つ, 難は 4 つ全部 (solitaire.FC_NEED). 要るセルの数を確かめるのに時間がかかる (難の配りはおよそ 20 に 1 つ)
ので, 遊ぶたびには確かめずに一覧にしておく. 配り方 (fc_deal・deck) や解く仕組みを変えたら作り直すこと.
難しさを指定すると, その難しさだけ作り直して, ほかはそのまま残す.
"""
import argparse
import io
import json
import os
import sys
import time
from multiprocessing import Pool

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from core import solitaire as SO  # noqa: E402

DST = os.path.join(BASE, "defaults", "freecell_pool.json")


def need(seed):
    return seed, SO.fc_need(seed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("levels", nargs="*", default=["easy", "mid", "hard"])
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    pool = json.load(io.open(DST, encoding="utf-8")) if os.path.exists(DST) else {}
    got = {lv: [] for lv in a.levels}
    seed, t0 = 1, time.time()
    with Pool(a.jobs) as pp:
        while any(len(v) < a.n for v in got.values()):
            for s, nd in pp.map(need, range(seed, seed + a.jobs * 4)):
                for lv in got:
                    lo, hi = SO.FC_NEED[lv]
                    if nd and lo <= nd <= hi and len(got[lv]) < a.n:
                        got[lv].append(s)
            seed += a.jobs * 4
            print("\r" + " / ".join("%s %d" % (lv, len(v)) for lv, v in got.items()) + " (試した %d, %.0f 秒)" % (seed - 1, time.time() - t0),
                  end="", flush=True)
    print()
    pool.update(got)
    io.open(DST, "w", encoding="utf-8", newline="\n").write(json.dumps(pool, sort_keys=True) + "\n")
    print("->", DST)


if __name__ == "__main__":
    main()
