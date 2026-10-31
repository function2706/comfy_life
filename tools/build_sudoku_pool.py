"""数独の問題集 (中・難) を defaults/sudoku_pool.json に書き出す.

    python tools/build_sudoku_pool.py [難しさ ...] [--n 200] [--jobs 4]

中・難は, 山場 (手筋が要る局面) があり, 探し回り (盤のどこか 1 か所を探させる局面) が無く, 入口のある盤 (core/puzzles.sudoku_make).
山場のある盤は作ってみてもまれで, 一つ作るのに数秒〜数十秒かかるので, 遊ぶたびには作らずにここで作っておく.
遊ぶときは, 選んだ盤の数字の入れ替え・回転・裏返しで見た目を変える (解き味は同じ).
難しさを指定すると, その難しさだけ作り直して, ほかはそのまま残す. 決まり (SIZE["sudoku"]・sudoku_profile) を変えたら作り直すこと.
"""
import argparse
import io
import json
import os
import random
import sys
import time
from multiprocessing import Pool

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from core import puzzles as P  # noqa: E402

DST = os.path.join(BASE, "defaults", "sudoku_pool.json")


def one(args):
    level, seed = args
    p = P.sudoku_make(level, random.Random(seed), tries=1)
    if not p or not P.sudoku_robust(p["puzzle"], level):        # どの向きで出しても流れが良いものだけ
        return None
    return "%s|%s" % ("".join(map(str, p["puzzle"])), "".join(map(str, p["solution"])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("levels", nargs="*", default=["mid", "hard"])
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    try:
        out = json.load(io.open(DST, encoding="utf-8"))
    except (OSError, ValueError):
        out = {}
    with Pool(a.jobs) as pool:
        for lv in a.levels:
            got, seen, seed, t0 = [], set(), {"mid": 1, "hard": 500001}[lv], time.time()
            while len(got) < a.n:
                for r in pool.map(one, [(lv, s) for s in range(seed, seed + a.jobs * 4)]):
                    if r and r not in seen and len(got) < a.n:
                        seen.add(r)
                        got.append(r)
                seed += a.jobs * 4
                print("\r%s: %d / %d (%.0fs)" % (lv, len(got), a.n, time.time() - t0), end="", flush=True)
            print()
            out[lv] = got
            io.open(DST, "w", encoding="utf-8", newline="\n").write(json.dumps(out, indent=0) + "\n")
    print("->", DST)


if __name__ == "__main__":
    main()
