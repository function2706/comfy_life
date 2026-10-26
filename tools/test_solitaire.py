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


def spider():
    # ---- 配り: 104 枚. スートの数が難しさ
    for lv, ns in (("easy", 1), ("mid", 2), ("hard", 4)):
        p = P.new("spider", lv, random.Random(2))
        allc = [c for col in p["cols"] for c in col] + p["stock"]
        assert len(allc) == 104 and len({SO.suit(c) for c in allc}) == ns and len(p["stock"]) == 50
        assert [len(c) for c in p["cols"]] == [6] * 4 + [5] * 6 and all(p["down"][i] == len(c) - 1 for i, c in enumerate(p["cols"]))
    v = P.view(p)
    assert v["cols"][0][:5] == [None] * 5 and v["cols"][0][5], "表は一番上だけ"

    def mk(cols, down=None, stock=()):
        return {"kind": "spider", "cols": [[card(x) for x in c] for c in cols] + [[] for _ in range(10 - len(cols))],
                "down": (down or [0] * len(cols)) + [0] * (10 - len(cols)), "stock": [card(x) for x in stock], "done": [], "hist": [],
                "miss": 0, "moves": 0, "level": "mid"}
    # ---- 手: 1 つ大きいカードの上へ. 同じスートのひと続きだけまとめて. 裏は動かせない. 動かすと下の裏が表に
    st = mk([["9S", "8H", "7S", "6S"], ["8D"], ["KC", "QH"]], down=[1, 0, 1])
    SO.sp_move(st, {"from": {"t": "col", "i": 0, "n": 2}, "to": {"t": "col", "i": 1}})       # 7♠6♠ を 8♦ へ (スートは問わない)
    assert [SO.name(c) for c in st["cols"][1]] == ["8D", "7S", "6S"]
    for bad in ({"from": {"t": "col", "i": 1, "n": 3}, "to": {"t": "col", "i": 2}},            # 8♦7♠ はスート違いでまとめられない
                {"from": {"t": "col", "i": 2, "n": 2}, "to": {"t": "col", "i": 5}},            # 裏の K♣ は動かせない
                {"from": {"t": "col", "i": 1, "n": 1}, "to": {"t": "col", "i": 0}}):           # 6 を 8 に
        try:
            SO.sp_move(st, bad)
            raise AssertionError("できないはずの手: %s" % bad)
        except ValueError:
            pass
    SO.sp_move(st, {"from": {"t": "col", "i": 0, "n": 1}, "to": {"t": "col", "i": 4}})           # 8♥ を空き列へ → 9♠ が表に
    assert st["down"][0] == 0 and P.view(dict(st, level="mid"))["cols"][0] == ["9S"]
    SO.sp_move(st, {"undo": True})
    assert [SO.name(c) for c in st["cols"][0]] == ["9S", "8H"] and st["down"][0] == 1
    # クリックの行き先: 同じスートで続く列が先
    st = mk([["5H"], ["6S"], ["6H"], ["9C"]])
    assert SO.sp_auto_dst(st, 0, 1) == 2
    # ---- K から A まで同じスートで揃ったら片付く
    run = ["KS", "QS", "JS", "TS", "9S", "8S", "7S", "6S", "5S", "4S", "3S", "2S"]
    st = mk([["5D"] + run, ["AS"]], down=[1, 0])
    SO.sp_move(st, {"from": {"t": "col", "i": 1, "n": 1}, "to": {"t": "col", "i": 0}})
    assert len(st["done"]) == 1 and [SO.name(c) for c in st["cols"][0]] == ["5D"] and st["down"][0] == 0
    # ---- 山から配る: 空いた列があると配れない
    st = mk([["5D"]] * 10, stock=["AS"] * 10)
    SO.sp_move(st, {"stock": True})
    assert all(len(c) == 2 for c in st["cols"]) and not st["stock"]
    st = mk([["5D"]] * 9, stock=["AS"] * 10)
    try:
        SO.sp_move(st, {"stock": True})
        raise AssertionError("空き列があるのに配れた")
    except ValueError:
        pass
    # ---- 詰み: 山が無く, 意味のある手が無い (行き来するだけの手は数えない)
    st = mk([["9S", "8S"], ["2C"], ["5D"], ["JS"], ["KD"], ["9H"], ["2H"], ["5C"], ["JD"], ["KS"]])
    assert SO.sp_stuck(st), "8♠ を 9♥ へ動かすのは, 自分の 9♠ から離すだけ (意味が無い)"
    st["cols"][1] = [card("3D")]
    assert not SO.sp_stuck(st), "2♥ は 3♦ へ動かせる"
    st["cols"][1] = [card("2C")]
    st["stock"] = [card("AS")] * 10
    assert not SO.sp_stuck(st), "山があれば配れる"
    print("スパイダー: 配り・手・自動の行き先・片付け・山・元に戻す・詰み OK")


def main():
    spider()
    freecell()
    print("ALL OK")


if __name__ == "__main__":
    main()
