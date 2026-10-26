"""クロンダイクの「解けると確かめた配り」の一覧 (乱数の種) を defaults/klondike_pool.json に書き出す.

    python tools/build_klondike_pool.py [難しさ ...] [--n 200]

クロンダイクは解けない配りが混ざるゲームで, 解く仕組み (core/solitaire.kl_solve) で確かめると, 難 (3 枚めくり・山 3 周まで) は
一つ見つけるのに数秒かかる. 内職を始めるたびに確かめると待たせるので, 確かめた配りの種をあらかじめ一覧にしておき, そこから選ぶ
(solitaire.kl_new). 配り方 (kl_deal・deck) や解く仕組みを変えたら作り直すこと (tools/test_solitaire.py が一部を解き直して確かめる).
難しさを指定すると, その難しさだけ作り直して, ほかはそのまま残す.
"""
import argparse
import io
import json
import os
import random
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from core import solitaire as SO  # noqa: E402

DST = os.path.join(BASE, "defaults", "klondike_pool.json")


def build(level, n, budget):
    out, seed, t0 = [], {"easy": 1, "mid": 100001, "hard": 200001}[level], time.time()
    while len(out) < n:
        if SO.kl_solve(SO.kl_deal(random.Random(seed), level), budget):
            out.append(seed)
        seed += 1
    print("%s: %d 個 (試した %d, %.0f 秒)" % (level, n, seed - out[0] + 1, time.time() - t0), flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("levels", nargs="*", default=["easy", "mid", "hard"])
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--budget", type=int, default=30000)
    ap.add_argument("--out", default=DST)
    a = ap.parse_args()
    dst = a.out
    pool = json.load(io.open(dst, encoding="utf-8")) if os.path.exists(dst) else {}
    for lv in a.levels:
        pool[lv] = build(lv, a.n, a.budget)
        io.open(dst, "w", encoding="utf-8", newline="\n").write(json.dumps(pool, sort_keys=True) + "\n")
    print("->", dst)


if __name__ == "__main__":
    main()
