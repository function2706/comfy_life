"""内職の 2048 と, 内職の一時停止 (離席用) の確認 (一時データ).

    python tools/test_2048.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, puzzles as P, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    rng = random.Random(3)
    # ---- 1. 寄せる・合わさる (一列で, 一度合わさったタイルはもう合わさらない)
    slide = lambda b, d: P.g2048_slide(b, 4, d)[0]  # noqa: E731
    b = [2, 2, 4, 0,
         2, 2, 2, 2,
         0, 0, 0, 2,
         4, 0, 4, 8]
    assert slide(b, "left") == [4, 4, 0, 0, 4, 4, 0, 0, 2, 0, 0, 0, 8, 8, 0, 0]
    assert slide(b, "right") == [0, 0, 4, 4, 0, 0, 4, 4, 0, 0, 0, 2, 0, 0, 8, 8]
    assert slide(b, "up")[:4] == [4, 4, 4, 4] and slide(b, "down")[12:] == [4, 4, 4, 8], (slide(b, "up"), slide(b, "down"))
    assert P.g2048_slide([2, 2, 2, 2] + [0] * 12, 4, "left")[1] == 8, "点数は合わさった数の合計"
    print("寄せる・合わさる: OK")

    # ---- 2. 一手: 動いたら新しいタイルが 1 つ出る. 動かない向きは手数に数えない
    p = P.new("g2048", "easy", rng)
    assert p["target"] == 512 and sum(1 for x in p["board"] if x) == 2
    p["board"] = [2, 0, 0, 0] + [0] * 12
    r = P.move(p, {"dir": "left"}, rng)
    assert not r["moved"] and p["moves"] == 0 and p["board"].count(0) == 15
    r = P.move(p, {"dir": "right"}, rng)
    assert r["moved"] and p["moves"] == 1 and p["board"][3] == 2 and sum(1 for x in p["board"] if x) == 2
    try:
        P.move(p, {"dir": "x"}, rng)
        raise AssertionError("向きの間違いを受け付けた")
    except ValueError:
        pass
    print("一手: OK")

    # ---- 3. 詰み: どの向きにも動かせない. 進み具合は最大のタイルで
    p["board"] = [2, 4, 2, 4, 4, 2, 4, 2, 2, 4, 2, 4, 4, 2, 4, 128]
    assert P.g2048_stuck(p) and P.view(p)["stuck"] and not P.solved(p)
    assert not P.move(p, {"dir": "up"}, rng)["moved"]
    assert abs(P.progress(p) - (7 - 2) / (9 - 2)) < 1e-9, P.progress(p)
    p["board"] = [4] + [0] * 15
    assert P.progress(p) == 0.0, "始めのタイルだけでは進んでいない"
    p["board"][5] = 512
    assert P.solved(p) and P.progress(p) == 1.0
    assert P.new("g2048", "mid", rng)["target"] == 1024 and P.new("g2048", "hard", rng)["target"] == 2048
    print("詰み・進み具合: OK")

    # ---- 4. 稼ぎ: 目標が上がるほど多い. 詰んだら進み具合のぶんの 2 割
    def done(level):
        q = P.new("g2048", level, rng)
        q["board"][0] = q["target"]
        return q
    pays = [P.pay(done(lv), P.PAR["g2048"][lv]) for lv in ("easy", "mid", "hard")]
    assert pays[0] < pays[1] < pays[2], pays
    q = P.new("g2048", "easy", rng)
    q["board"] = [2, 4, 2, 4, 4, 2, 4, 2, 2, 4, 2, 4, 4, 2, 4, 128]
    part = P.pay(q, 100)
    assert 0 < part < pays[0] * 0.2, (part, pays)
    print("稼ぎ: 易 %d / 中 %d / 難 %d 円, 128 で詰んだら %d 円" % (pays[0], pays[1], pays[2], part))

    # ---- 5. ランダムに打っても詰むか目標に届くかで終わる (盤はいつも 16 マス)
    for seed in range(5):
        rr = random.Random(seed)
        q = P.new("g2048", "easy", rr)
        for _ in range(5000):
            if P.solved(q) or P.g2048_stuck(q):
                break
            P.move(q, {"dir": rr.choice(P.DIRS)}, rr)
        assert P.solved(q) or P.g2048_stuck(q)
        assert len(q["board"]) == 16 and all(x == 0 or x & (x - 1) == 0 for x in q["board"])
    print("最後まで: OK")

    # ---- 6. 本体: 一時停止の間は時間に数えず, 盤面も返さず, 手も受け付けない. 保存して閉じても続きから
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        tk = app.task_start("g2048", "easy")
        tok = tk["token"]
        assert tk["view"]["kind"] == "g2048" and not tk["paused"]
        t = app._task_store()[tok]
        t["t0"] -= 100                                    # 100 秒たった
        pz = app.task_pause(tok)
        assert pz["paused"] and pz["view"] is None and 99 <= pz["elapsed"] <= 101
        t["paused_at"] -= 600                             # 10 分離席
        try:
            app.task_move(tok, {"dir": "left"})
            raise AssertionError("一時停止中に手を受け付けた")
        except ValueError as e:
            assert "一時停止" in str(e)
        app2 = engine.App()                               # 閉じて開き直しても, 止まったまま
        r = app2.task_resume()
        assert r["paused"] and r["view"] is None
        r = app2.task_pause(tok, on=False)
        assert not r["paused"] and r["view"]["kind"] == "g2048" and 99 <= r["elapsed"] <= 102, r["elapsed"]
        for d in P.DIRS * 3:
            app2.task_move(tok, {"dir": d})
        fin = app2.task_finish(tok)
        assert fin["task"]["sec"] < 110, fin["task"]["sec"]
        print("一時停止 (本体): OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- 7. 実験場 (tools/puzzle_lab.py) でも一時停止できる
    import puzzle_lab as LAB
    out, code = LAB.call_api("POST", "/api/task/start", {"kind": "g2048", "level": "easy", "seed": 1})
    assert code == 200
    tok = out["token"]
    out, code = LAB.call_api("POST", "/api/task/pause", {"token": tok, "on": True})
    assert code == 200 and out["paused"] and out["view"] is None
    out, code = LAB.call_api("POST", "/api/task/move", {"token": tok, "move": {"dir": "up"}})
    assert code == 400
    out, code = LAB.call_api("POST", "/api/task/pause", {"token": tok, "on": False})
    assert code == 200 and not out["paused"] and out["view"]["board"]
    print("一時停止 (実験場): OK")
    print("ALL OK")


if __name__ == "__main__":
    main()
