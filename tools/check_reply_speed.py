# -*- coding: utf-8 -*-
"""重み検査: メッセージの返信の早さ (core/replyspeed.py).
性格 × 間柄 × 場面ごとに, すぐ返る (3 分以内) 割合・中央値 (分)・1 時間以上空く割合を出す.
python tools/check_reply_speed.py [--scene home|moving|meal|out] [--n 4000]"""
import argparse
import glob
import io
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import replyspeed  # noqa: E402

# 間柄: (好感度, 機嫌, 献身度, 依存度, 近さ)
RELS = [("浅い", 45, 55, 0.0, -0.2, 0.05), ("ふつう", 60, 55, 0.0, 0.0, 0.2),
        ("家に行ける仲", 72, 60, 0.2, 0.2, 0.55), ("親密(同居)", 85, 60, 0.4, 0.4, 0.85)]
STATES = [("機嫌悪い", dict(mood=30)), ("言い争いのあと", dict(fight=True)), ("連絡多め", dict(many=True)),
          ("依存度 高", dict(dep=0.8)), ("依存度 低", dict(dep=-0.6))]


def stats(traits, place, aff, mood, dv, dep, close, n, rnd, many=False, fight=False):
    xs, q = [], 0
    for _ in range(n):
        s, hand = replyspeed.plan(traits, place, dv, dep, aff, mood, close, many=many, fight=fight, rnd=rnd)
        xs.append(s / 60.0)
        q += s <= 180
    xs.sort()
    return 100.0 * q / n, xs[n // 2], 100.0 * sum(1 for x in xs if x >= 60) / n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="home")
    ap.add_argument("--n", type=int, default=4000)
    a = ap.parse_args()
    rnd = random.Random(7)
    root = os.path.join(os.path.dirname(__file__), "..", "defaults", "personas")
    ps = []
    for f in sorted(glob.glob(os.path.join(root, "*.json"))):
        d = json.load(io.open(f, encoding="utf-8"))
        ps.append((os.path.basename(f)[:-5], d.get("traits") or {}))
    print("場面: %s   各欄 = すぐ(3分以内)%% / 中央値(分) / 1時間以上%%" % a.scene)
    print("%-13s" % "性格" + "".join("%-22s" % r[0] for r in RELS))
    for pid, tr in ps:
        row = "%-13s" % ("%s(%.1f)" % (pid, float(tr.get("reply", 1))))
        for _, aff, mood, dv, dep, close in RELS:
            q, med, long_ = stats(tr, a.scene, aff, mood, dv, dep, close, a.n, rnd)
            row += "%3.0f%% / %5.1f / %3.0f%%      " % (q, med, long_)
        print(row)
    print("\n状態ごと (ふつうの仲, 性格の早さ 1.0)")
    base = {"reply": 1.0}
    _, aff, mood, dv, dep, close = RELS[1]
    q, med, long_ = stats(base, a.scene, aff, mood, dv, dep, close, a.n, rnd)
    print("%-14s %3.0f%% / %5.1f / %3.0f%%" % ("そのまま", q, med, long_))
    for name, kw in STATES:
        k = dict(aff=aff, mood=mood, dv=dv, dep=dep, many=False, fight=False)
        k.update(kw)
        q, med, long_ = stats(base, a.scene, k["aff"], k["mood"], k["dv"], k["dep"], close, a.n, rnd, k["many"], k["fight"])
        print("%-14s %3.0f%% / %5.1f / %3.0f%%" % (name, q, med, long_))
    print("\n場面ごと (ふつうの仲, 性格の早さ 1.0)")
    for pl in ("home", "moving", "meal", "out"):
        q, med, long_ = stats(base, pl, aff, mood, dv, dep, close, a.n, rnd)
        print("%-8s %3.0f%% / %5.1f / %3.0f%%" % (pl, q, med, long_))


if __name__ == "__main__":
    main()
