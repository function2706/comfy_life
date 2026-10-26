"""内職のトランプの一人遊び (core/solitaire.py): 配りが解けること・手の正誤・行き先の自動選択・元に戻す・詰みの知らせ・稼ぎ.

    python tools/test_solitaire.py
"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import puzzles as P, solitaire as SO  # noqa: E402


def card(s):
    """"AS" → 0. テストで盤を組むため."""
    return SO.SUITS.index(s[1]) * 13 + SO.RANKS.index(s[0])


def freecell():
    # ---- 配り: 解く仕組みで確かめた, 解けるものだけ. 難しさはセルの数
    for lv, cells in (("easy", 4), ("mid", 3), ("hard", 2)):
        ts = []
        for seed in range(3):
            t = time.time()
            p = P.new("freecell", lv, random.Random(seed))
            ts.append(time.time() - t)
            assert len(p["cells"]) == cells and sum(len(c) for c in p["cols"]) + sum(p["found"]) == 52
            st = {"cols": [list(c) for c in p["cols"]], "cells": list(p["cells"]), "found": list(p["found"])}
            assert SO.fc_solve(st, 200000), (lv, seed)
        print("フリーセル %s (セル %d): 配りを作る時間 最大 %.1f 秒" % (lv, cells, max(ts)))
    # ---- 手の正誤
    st = {"cols": [[card("KS"), card("QH")], [card("JS")], [], [card("5D")], [], [], [], []], "cells": [None, None],
          "found": [0, 0, 0, 0], "hist": [], "miss": 0, "moves": 0, "kind": "freecell"}
    SO.fc_move(st, {"from": {"t": "col", "i": 1}, "to": {"t": "col", "i": 0}})          # 黒の J を赤の Q へ
    assert [SO.name(c) for c in st["cols"][0]] == ["KS", "QH", "JS"]
    for bad in ({"from": {"t": "col", "i": 3}, "to": {"t": "col", "i": 0}},             # 5 を J に重ねる
                {"from": {"t": "col", "i": 3}, "to": {"t": "found"}},                     # A からでない
                {"from": {"t": "col", "i": 0, "n": 3}, "to": {"t": "cell", "i": 0}}):     # セルに 3 枚
        try:
            SO.fc_move(st, bad)
            raise AssertionError("できないはずの手: %s" % bad)
        except ValueError:
            pass
    # まとめて動かせる枚数: (空きセル + 1) × 2^(空き列)
    st["cells"] = [card("2C"), None]
    assert SO.fc_max_run(st, True) == 2 * 2 ** 5 and SO.fc_max_run(st, False) == 2 * 2 ** 6     # 空き列 6 (行き先が空き列なら 5)
    SO.fc_move(st, {"from": {"t": "col", "i": 0, "n": 2}, "to": {"t": "col", "i": 2}})
    assert [SO.name(c) for c in st["cols"][2]] == ["QH", "JS"]
    # 元に戻す
    SO.fc_move(st, {"undo": True})
    assert [SO.name(c) for c in st["cols"][0]] == ["KS", "QH", "JS"] and not st["cols"][2]
    # クリックの行き先: 組札 → 重ねられる列 → 空き列 → 空きセル
    st2 = {"cols": [[card("AH")], [card("8S"), card("9D")], [card("TS")], [card("3C")]] + [[card("KC")]] * 4,
           "cells": [None], "found": [0, 0, 0, 0], "hist": [], "miss": 0, "moves": 0}
    assert SO.fc_auto_dst(st2, {"t": "col", "i": 0}) == {"t": "found"}
    assert SO.fc_auto_dst(st2, {"t": "col", "i": 1}) == {"t": "col", "i": 2}
    assert SO.fc_auto_dst(st2, {"t": "col", "i": 3}) == {"t": "cell", "i": 0}
    # 安全な組札上げは自動 (A・2 と, 反対の色がそこまで来ているもの)
    st3 = {"cols": [[card("2H"), card("AH")], [card("3H")]], "cells": [None], "found": [0, 0, 0, 0]}
    SO.fc_autoplay(st3)
    assert st3["found"][1] == 2 and st3["cols"][1], "3♥ は黒の 2 が上がるまで残す"
    # 詰み: どこにも動かせない
    st4 = {"cols": [[card("KS"), card("2H")], [card("KD"), card("3H")]], "cells": [card("5C")], "found": [0, 0, 0, 0]}
    assert SO.fc_stuck(st4)
    st4["cells"] = [None]
    assert not SO.fc_stuck(st4)
    # 稼ぎ: 組札に上がった枚数が進み具合
    p = P.new("freecell", "easy", random.Random(1))
    p["found"] = [13, 13, 0, 0]
    assert abs(P.progress(p) - 0.5) < 1e-9 and 0 < P.pay(p, 100) < P.pay(dict(p, found=[13] * 4), 100)
    print("フリーセル: 手・自動の行き先・元に戻す・詰み・稼ぎ OK")


def main():
    freecell()
    print("ALL OK")


if __name__ == "__main__":
    main()
