"""内職のパズルの確認 (一時データ, 画像生成なし).
- 盤面の生成: 数独とピクロスは解が一つだけ, マインスイーパは最初に開けたマスの周りに地雷が無い, 15 パズルは崩れている
- 答え合わせはサーバ: 爆発・誤入力・誤りマスはミス, 正しい手だけが入る, できあがりの判定
- 稼ぎ: 難しさ・速さ・ミス・仕事スキル. 解けずにやめたら進んだぶんの少しだけ
- 内職の流れ (体力・休憩・キャラの反応) と, 反応のセリフのキーの移し替え (旧いキーの編集分も新しいキーとして読む)

    python tools/test_puzzles.py
"""
import json
import os
import re
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, puzzles as P, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    rng = random.Random(5)
    # ---- 1. 数独: 解が一つだけ. 誤入力はミスで, 入らない
    for lv in ("easy", "mid", "hard"):
        for _ in range(3):
            p = P.new("sudoku", lv, rng)
            assert P.sudoku_count(p["puzzle"]) == 1 and all(p["solution"]) and sum(1 for x in p["puzzle"] if x) <= 45
            assert all(a == b for a, b in zip(p["puzzle"], p["solution"]) if a)
    i = p["puzzle"].index(0)
    r, c = divmod(i, 9)
    bad = next(v for v in range(1, 10) if v != p["solution"][i])
    assert P.move(p, {"r": r, "c": c, "v": bad}).get("wrong") and p["miss"] == 1 and not p["cur"][i]
    P.move(p, {"r": r, "c": c, "v": p["solution"][i]})
    assert p["cur"][i] == p["solution"][i]
    for j, v in enumerate(p["solution"]):
        if not p["cur"][j]:
            out = P.move(p, {"r": j // 9, "c": j % 9, "v": v})
    assert out["solved"] and P.progress(p) == 1.0
    print("sudoku: OK")

    # ---- 2. ピクロス: 手がかりだけで解ける (= 解が一つ). 塗るマスでなければミスで×
    for lv in ("easy", "mid", "hard"):
        for _ in range(5):
            p = P.new("picross", lv, rng)
            assert P.picross_solve(p["rows"], p["cols"]) == p["sol"]
            assert p["rows"] == [P.clue(x) for x in p["sol"]]
    empty = next((r, c) for r in range(p["n"]) for c in range(p["n"]) if not p["sol"][r][c])
    assert P.move(p, {"r": empty[0], "c": empty[1]})["wrong"] and p["miss"] == 1 and [empty[0], empty[1]] in p["x"]
    for r in range(p["n"]):
        for c in range(p["n"]):
            if p["sol"][r][c]:
                out = P.move(p, {"r": r, "c": c})
    assert out["solved"]
    print("picross: OK")

    # ---- 3. マインスイーパ: 最初に開けたマスの周りに地雷は無い. 爆発はミス (続けられる)
    for _ in range(20):
        p = P.new("mines", "hard", rng)
        P.move(p, {"r": 5, "c": 6}, rng)
        ms = {tuple(x) for x in p["mines"]}
        assert len(ms) == p["n"] and not any((5 + a, 6 + b) in ms for a in (-1, 0, 1) for b in (-1, 0, 1))
        assert [5, 6] in p["open"] and len(p["open"]) >= 9 and P.mines_count(p, 5, 6) == 0
    m = p["mines"][0]
    assert P.move(p, {"r": m[0], "c": m[1]})["wrong"] and p["miss"] == 1 and not P.solved(p)
    for r in range(p["h"]):
        for c in range(p["w"]):
            if [r, c] not in p["mines"]:
                out = P.move(p, {"r": r, "c": c})
    assert out["solved"] and P.view(p)["grid"][m[0]][m[1]] == "*"
    # 一括開け: 旗の数がそろっていれば周りを開ける. 足りなければ何もしない. 旗が違えば爆発
    def fresh():
        for _ in range(200):
            q = P.new("mines", "easy", rng)
            P.move(q, {"r": 4, "c": 4}, rng)
            ms = {tuple(x) for x in q["mines"]}
            for (r, c) in sorted(tuple(x) for x in q["open"]):
                n = P.mines_count(q, r, c)
                around = list(P._nb(r, c, q["h"], q["w"]))
                closed = [x for x in around if list(x) not in q["open"]]
                if n and len(closed) > n:
                    return q, (r, c), [x for x in around if x in ms], [x for x in closed if x not in ms]
        raise AssertionError("一括開けを試せる盤面が無い")

    q, (r, c), mines_near, safe_near = fresh()
    assert P.move(q, {"r": r, "c": c, "chord": True, "flags": mines_near[:-1]}).get("short") and q["miss"] == 0
    before = len(q["open"])
    out = P.move(q, {"r": r, "c": c, "chord": True, "flags": [list(x) for x in mines_near]})
    assert not out.get("wrong") and q["miss"] == 0 and all(list(x) in q["open"] for x in safe_near) and len(q["open"]) > before
    q, (r, c), mines_near, safe_near = fresh()
    wrong_flags = [list(safe_near[0])] + [list(x) for x in mines_near[1:]]     # 旗を一つ間違える
    out = P.move(q, {"r": r, "c": c, "chord": True, "flags": wrong_flags})
    assert out.get("wrong") and q["miss"] >= 1 and list(mines_near[0]) in q["boom"], "旗が違えば, 普通に爆発する"
    closed = next([y, x] for y in range(q["h"]) for x in range(q["w"]) if [y, x] not in q["open"] and [y, x] not in q["boom"])
    n0 = len(q["open"])
    P.move(q, {"r": closed[0], "c": closed[1], "chord": True, "flags": []})
    assert len(q["open"]) == n0, "閉じているマスでは一括開けしない"
    print("mines: OK")

    # ---- 4. 15 パズル: 崩れていて, 隣の駒だけ動く
    p = P.new("slide", "easy", rng)
    assert not P.solved(p) and sorted(p["board"]) == list(range(9))
    z = p["board"].index(0)
    far = next(i for i in range(9) if abs(i // 3 - z // 3) + abs(i % 3 - z % 3) > 1)
    P.move(p, {"r": far // 3, "c": far % 3})
    assert p["moves"] == 0, "離れた駒は動かない"
    p["board"] = [1, 2, 3, 4, 5, 6, 7, 0, 8]
    assert P.move(p, {"r": 2, "c": 2})["solved"] and p["moves"] == 1
    print("slide: OK")

    # ---- 5. 稼ぎ: 難しさ・速さ・ミス. 解けずにやめたら少しだけ
    def done(kind, level, miss=0):
        q = P.new(kind, level, rng)
        if kind == "slide":
            q["board"] = list(range(1, q["n"] ** 2)) + [0]
        elif kind == "mines":
            P.move(q, {"r": 0, "c": 0}, rng)
            q["open"] = [[r, c] for r in range(q["h"]) for c in range(q["w"]) if [r, c] not in q["mines"]]
        elif kind == "picross":
            q["filled"] = [[r, c] for r in range(q["n"]) for c in range(q["n"]) if q["sol"][r][c]]
        elif kind == "sudoku":
            q["cur"] = list(q["solution"])
        q["miss"] = miss
        return q

    # 種類が違っても, 目安の時間あたりの稼ぎはならされる (難しいほど少し上乗せ)
    for lv in ("easy", "mid", "hard"):
        per_min = [P.pay(done(k, lv), P.PAR[k][lv]) / (P.PAR[k][lv] / 60.0) for k in P.KINDS]
        assert max(per_min) / min(per_min) < 1.15, (lv, per_min)
    assert P.pay(done("sudoku", "easy"), 1) > P.pay(done("mines", "easy"), 1) * 3, "時間のかかる数独は, そのぶん多い"
    e, m_, h = done("sudoku", "easy"), done("sudoku", "mid"), done("sudoku", "hard")
    par = P.PAR["sudoku"]
    assert P.pay(e, par["easy"]) < P.pay(m_, par["mid"]) < P.pay(h, par["hard"])
    assert P.pay(e, par["easy"]) > P.pay(e, par["easy"] + 1) > P.pay(e, par["easy"] * 3), "速いほど多い"
    assert P.pay(done("sudoku", "easy", 3), 100) < P.pay(e, 100), "ミスが多いと減る"
    assert P.pay(done("sudoku", "easy", 20), 100) > 0, "ミスが多くても, 解けたぶんの 4 割は出る"
    assert P.pay(e, 100, mult=1.4) > P.pay(e, 100, mult=0.6), "仕事スキルで上がる"
    half = P.new("sudoku", "easy", rng)
    assert P.pay(half, 100) == 0
    for j in range(81):
        if not half["cur"][j] and sum(1 for x in half["cur"] if x) < 60:
            half["cur"][j] = half["solution"][j]
    g = P.pay(half, 100)
    assert 0 < g < P.pay(e, 100) * 0.25, g
    print("pay: OK", P.pay(e, 100), P.pay(m_, 100), P.pay(h, 100), g)

    # ---- 6. 内職の流れ: 反応 (速い / ミスが多い)・体力・仕事スキル
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        cid = app.bonds.living()
        st = app.state(cid)
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": 9e12}
        app.char(cid)["persona_id"] = "teinei"
        L = app.life
        lines = app.personas["teinei"]["lines"]
        assert "side_job.fast" in lines and "side_job.sloppy" in lines and "side_job.task_ok_ge_45__free_true" not in lines

        def said(text, key):      # 置換文字を除いた部分が, すべて本文にあるか
            return any(all(x in text for x in re.split(r"\{\w+\}", t) if x) for t in lines[key])

        def run(miss, fast=True):
            st["cooldowns"] = {}
            L.player_state()["stamina"] = 100
            tk = app.task_start("slide", "mid")
            pz = app.tasks[tk["token"]]["puzzle"]
            pz["board"] = list(range(1, 16)) + [0]
            pz["miss"] = miss
            if not fast:
                app.tasks[tk["token"]]["t0"] -= 10000
            return app.task_finish(tk["token"])

        s0, m0 = L.player_state()["stamina"], L.player_state()["money"]
        r = run(0)
        assert r["task"]["solved"] and r["task"]["fast"] and L.player_state()["money"] - m0 == r["task"]["pay"] > 0
        assert said(r["entry"]["text"], "side_job.fast"), r["entry"]["text"]
        assert r["entry"]["skill"]["work"] > 0 and L.player_state()["stamina"] < 100
        r = run(6, fast=False)
        assert said(r["entry"]["text"], "side_job.sloppy") and "6" in r["entry"]["text"], r["entry"]["text"]
        try:
            app.task_start("slide")
            raise AssertionError("休憩なしで続けられる")
        except ValueError:
            pass
        st["cooldowns"] = {}
        tk = app.task_start("mines", "easy")
        try:
            app.task_move("nope", {"r": 0, "c": 0})
            raise AssertionError("知らない作業に手を打てる")
        except ValueError:
            pass
        r = app.task_finish(tk["token"])
        assert not r["task"]["solved"] and r["task"]["pay"] == 0 and r["task"]["view"]["grid"]
        print("flow: OK")

        # サーバを再起動しても, やりかけの内職は続きから (盤面・経過時間). やりかけがあるうちは新しく始めない
        st["cooldowns"] = {}
        L.player_state()["stamina"] = 100
        tk = app.task_start("sudoku", "easy")
        pz = app.tasks[tk["token"]]["puzzle"]
        i = pz["puzzle"].index(0)
        app.task_move(tk["token"], {"r": i // 9, "c": i % 9, "v": pz["solution"][i]})
        try:
            app.task_start("mines")
            raise AssertionError("やりかけがあるのに新しく始められる")
        except ValueError as e:
            assert "続き" in str(e)
        app2 = engine.App()                        # 再起動
        assert app2.task_active() == tk["token"] and app2.state_view(cid)["task_active"] == tk["token"]
        assert app2.state_view(cid)["side_job"] is None, "やりかけがあれば, 休憩中でも続きはできる"
        r = app2.task_resume()
        assert r["token"] == tk["token"] and r["view"]["cur"][i] == pz["solution"][i] and r["elapsed"] >= 0
        out = app2.task_finish(tk["token"])
        assert not out["task"]["solved"] and app2.task_active() is None
        assert engine.App().task_active() is None, "終えたら, 保存からも消える"
        print("resume after restart: OK")

        # 旧いキーのままの編集分 (data/personas) も, 新しいキーとして読む
        p = json.load(open(os.path.join(store.DEFAULTS, "personas", "genki.json"), encoding="utf-8"))
        p["lines"]["side_job.task_ok_ge_45__free_true"] = p["lines"].pop("side_job.fast")
        p["lines"]["side_job.task_ok_ge_45__free_true"] = ["旧いキーの編集分"]
        store.save_persona(p)
        assert store.load_personas()["genki"]["lines"]["side_job.fast"] == ["旧いキーの編集分"]
        print("line keys: OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK")


if __name__ == "__main__":
    main()
