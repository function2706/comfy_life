"""麻雀・盤面ゲームの確認 (一時データディレクトリで実行, 画像生成なし).

    python tools/test_mahjong_board.py
"""
import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import boardgames as BG  # noqa: E402
from core import engine, store  # noqa: E402
from core import mahjong as MJ  # noqa: E402


def T(s):
    """'123m456p789s11z' 形式 → 牌リスト (z: 1-7 = 東南西北白發中)."""
    out, num = [], []
    for ch in s:
        if ch.isdigit():
            num.append(int(ch))
        else:
            base = {"m": 0, "p": 9, "s": 18, "z": 27}[ch]
            out += [base + n - 1 for n in num]
            num = []
    return out


def names(res):
    return [n for n, _ in res["yaku"]] if res else None


def test_yaku():
    # 平和・断幺九 (両面 6-9p 待ちを 9p ではなく 6p で… → 345p678p? ここでは 67p に 8p)
    h = T("234m345p456s55s67p") + [9 + 7]
    r = MJ.evaluate(sorted(h), 9 + 7, False, False, 28, 27, [], [])
    assert "平和" in names(r) and "断幺九" in names(r), names(r)
    # 嵌張は平和にならない
    h = T("234m345p456s55s68p") + [9 + 6]
    assert "平和" not in names(MJ.evaluate(sorted(h), 9 + 6, False, False, 28, 27, [], []))
    # ロンの暗刻は三暗刻に数えない / ツモなら数える
    assert "三暗刻" not in (names(MJ.evaluate(sorted(T("111m222p333s456m99p")), 9 + 1, False, True, 28, 27, [], [])) or [])
    r = MJ.evaluate(sorted(T("111m222p333s99p34m") + [4]), 4, True, False, 28, 27, [], [])
    assert r and "三暗刻" in names(r), names(r)
    r = MJ.evaluate(sorted(T("111m222p333s99p55m") + [4]), 4, True, False, 28, 27, [], [])
    assert r["yakuman"] and names(r) == ["四暗刻"], names(r)
    # 役なしは和了れない / ドラだけでは和了れない
    assert MJ.evaluate(sorted(T("123m456p789s11z789m")), 8, False, False, 28, 27, [0, 1], []) is None
    # 役満
    assert MJ.evaluate(sorted(T("555666777z11p")+T("234m")), 3, False, False, 28, 27, [], [])["yakuman"]
    # ドラ
    r = MJ.evaluate(sorted(T("234m345p456s55s67p") + [16]), 16, True, True, 28, 27, [15], [])   # 7p 表示 → ドラ 8p
    assert ("ドラ", 1) in r["yaku"], r
    print("yaku: OK")


def play_mahjong(app, st, policy):
    app.games.start("mahjong")
    for _ in range(3000):
        g = st.get("game")
        if not g:
            return None
        m = g["mj"]
        if m["phase"] == "hand_end":
            if g.get("over"):
                over = g["over"]
                app.games.move(payload={"act": "next"})
                return over
            app.games.move(payload={"act": "next"})
        elif m["phase"] == "p_ron":
            app.games.move(payload={"act": "ron"})
        elif m.get("can_tsumo"):
            app.games.move(payload={"act": "tsumo"})
        elif m["riichi_tiles"] and policy == "ai":
            app.games.move(payload={"act": "riichi", "tile": m["riichi_tiles"][0]})
        else:
            hand = m["hands"]["p"]
            t = MJ.choose_discard(hand, MJ.to_counts(hand)) if policy == "ai" else m["drawn"]["p"]
            app.games.move(payload={"act": "discard", "tile": t})
    raise AssertionError("麻雀が終わらない")


def play_board(app, st, gid):
    app.games.start(gid)
    for _ in range(200):
        g = st["game"]
        b = g["board"]
        if g.get("over"):
            res = g["over"]
            app.games.quit()
            return res
        if gid == "connect4":
            app.games.move(payload={"col": random.choice(BG.c4_moves(b))})
        elif gid == "hex":
            app.games.move(payload={"cell": random.choice([i for i, v in enumerate(b) if not v])})
        else:
            app.games.move(payload={"cell": random.choice(BG.rv_moves(b, BG.ME))})
    raise AssertionError("盤面ゲームが終わらない")


def main():
    test_yaku()
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    random.seed(7)
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        st = app.state("hina")
        st["override"] = {"activity": "relax", "label": "テスト", "location": "リビング", "until": 9e12}
        app.set_params({"affection": 80, "mood": 70, "sleepiness": 0})
        assert {"mahjong", "connect4", "hex", "reversi"} <= {g["id"] for g in app.minigames}

        results = [play_mahjong(app, st, "ai") for _ in range(3)]
        print("mahjong (AI的に打つ):", results)
        results = [play_mahjong(app, st, "tsumogiri") for _ in range(2)]
        print("mahjong (ツモ切り):", results)
        log = app.log("hina")
        print("  例:", [e["action_name"] + " " + e["text"] for e in log if "局" in e["action_name"]][-3:])
        for gid in ("connect4", "hex", "reversi"):
            res = [play_board(app, st, gid) for _ in range(3)]
            print("%s (ランダム相手):" % gid, res)
            assert res.count("lose") >= 2, "AI がランダム相手に負け越している"
        v = app.state_view()["games"]
        assert v["current"] is None and len(v["list"]) == 6
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
