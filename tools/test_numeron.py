"""数当て (Hit & Blow) の確認: ヒット・ブローの数え方・候補の絞り込み・勝ち負け引き分け・相手の推理の強さの幅
(性格の推理の冴え・体力・眠気・機嫌) (一時データディレクトリ, 画像生成なし).

    python tools/test_numeron.py
"""
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, numeron as N, store  # noqa: E402


def turns_to_solve(strength, err, n=60, seed=0):
    out = []
    for k in range(n):
        rng = random.Random(seed + k)
        secret, hist = rng.choice(N.ALL), []
        for t in range(1, 60):
            g, _ = N.ai_guess(hist, strength, err, rng)
            h, b = N.hb(secret, g)
            hist.append((g, h, b))
            if h == 3:
                break
        out.append(t)
    return sum(out) / float(len(out))


def main():
    # ---- 1. ヒット・ブロー
    assert N.hb("123", "123") == (3, 0) and N.hb("123", "321") == (1, 2) and N.hb("123", "456") == (0, 0) and N.hb("012", "120") == (0, 3)
    assert N.valid("307") and not N.valid("33 ") and not N.valid("112") and not N.valid("12")
    assert len(N.ALL) == 720 and len(N.candidates([("123", 0, 0)])) == 210
    print("ヒット・ブロー・候補: OK")

    # ---- 2. 推理の強さの幅 (いつも最善ではない)
    strong, mid, weak = turns_to_solve(1.0, 0.0), turns_to_solve(0.5, 0.06), turns_to_solve(0.0, 0.2)
    assert strong < mid < weak and weak > strong + 1.0, (strong, mid, weak)
    print("当てるまでの手数 (平均): 冴えている %.1f / ふつう %.1f / ぼんやり %.1f" % (strong, mid, weak))

    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    random.seed(31)
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        st = app.state("hina")
        st["override"] = {"activity": "relax", "label": "テスト", "location": "リビング", "until": 9e12}
        app.set_params({"affection": 80, "mood": 70, "sleepiness": 0, "energy": 90})
        G = app.games
        char = app.char()
        tr = app.traits(char)

        # ---- 3. 推理の冴え: 性格 (reason)・体力・眠気・機嫌
        tr["reason"] = 1.3
        sharp = G.nm_strength(char, st)
        tr["reason"] = 0.8
        dull = G.nm_strength(char, st)
        tr.pop("reason")
        base = G.nm_strength(char, st)
        app.set_params({"sleepiness": 95, "energy": 10, "mood": 20})
        tired = G.nm_strength(char, st)
        app.set_params({"sleepiness": 0, "energy": 90, "mood": 70})
        assert sharp > base > dull and base > tired + 0.4, (sharp, base, dull, tired)
        print("推理の冴え: 理詰めの性格 %.2f / ふつう %.2f / のんびり %.2f / 眠くて疲れて不機嫌 %.2f" % (sharp, base, dull, tired))

        # ---- 4. 遊ぶ: 秘密の数 → 言い合う. 先に 3 ヒットで勝ち (同じ手数なら引き分け)
        res = []
        for k in range(8):
            G.start("numeron")
            try:
                G.move(payload={"act": "guess", "value": "123"})
                raise AssertionError("秘密の数を決める前に言えた")
            except ValueError:
                pass
            G.move(payload={"act": "secret", "value": "479"})
            hist = []
            for _ in range(40):
                cands = N.candidates(hist)
                g = random.choice(cands)
                r = G.move(payload={"act": "guess", "value": g})
                m = st["game"]["nm"]
                hist.append(tuple(m["p"][-1]))
                assert len(m["a"]) == len(m["p"]), "あなたが言ったら, 相手も言う"
                if r["ended"]:
                    res.append(r["ended"])
                    v = G.view(char, st, app.context(char, st, datetime.now()))["current"]["nm"]
                    assert v["hers"] and v["over"] == r["ended"]
                    G.quit()
                    break
            else:
                raise AssertionError("数当てが終わらない")
        assert set(res) <= {"win", "lose", "draw"} and len(res) == 8, res
        log = [e for e in app.log("hina") if e["action"] == "_game_numeron"]
        print("数当て 8 回:", res, "| 例:", log[-1]["action_name"], log[-1]["text"])
        # 引き分け: 同じ手で当たり
        G.start("numeron")
        G.move(payload={"act": "secret", "value": "012"})
        m = st["game"]["nm"]
        m["hers"] = "345"
        m["a"] = []
        orig = N.ai_guess
        N.ai_guess = lambda h, s, e, rng=random: ("012", 1)
        r = G.move(payload={"act": "guess", "value": "345"})
        N.ai_guess = orig
        assert r["ended"] == "draw", r
        G.quit()
        print("引き分け: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
