"""ダウト (二人で嘘を見抜き合う) の確認: 勝ち負け・引き取り・表情の出方 (性格のポーカーフェイス)・見抜き方 (機嫌・眠気) と,
ババ抜きの表情もポーカーフェイスに合わせること (一時データディレクトリ, 画像生成なし).

    python tools/test_doubt.py
"""
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    random.seed(23)
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        st = app.state("hina")
        st["override"] = {"activity": "relax", "label": "テスト", "location": "リビング", "until": 9e12}
        app.set_params({"affection": 80, "mood": 70, "sleepiness": 0})
        G = app.games
        g = G.get("doubt")
        char = app.char()

        def view():
            return G.view(char, st, app.context(char, st, datetime.now()))["current"]["cards"]

        # ---- 1. 最後まで遊べる (あなたは持っていれば本当に, 無ければ 1 枚で嘘. 相手が出したら 15% でダウト)
        res = []
        for _ in range(6):
            G.start("doubt")
            for _ in range(800):
                c = view()
                if c["phase"] == "round_end":
                    over = st["game"]["over"]
                    G.move(payload={"act": "next"})
                    res.append(over)
                    break
                if c["phase"] == "p_play":
                    idx = [i for i, x in enumerate(c["hand"]) if x[0] == c["rank"]][:4] or [0]
                    G.move(payload={"act": "play", "idx": idx})
                else:
                    G.move(payload={"act": "doubt" if random.random() < 0.15 else "pass"})
            else:
                raise AssertionError("ダウトが終わらない")
        assert all(r in ("win", "lose") for r in res) and len(res) == 6, res
        log = [e for e in app.log("hina") if e["action"] == "_game_doubt"]
        print("ダウト 6 回:", res, "| 記録 %d 件, 例: %s" % (len(log), log[-1]["text"]))

        # ---- 2. 引き取り: 嘘なら出した側が, 本当ならダウトした側が場をぜんぶ
        G.start("doubt")
        d = st["game"]["cd"]
        d["hands"] = {"p": ["5S", "5H", "9C"], "a": ["AS", "2D", "3C"]}
        d.update(pile=["KD", "QD"], rank=4, phase="p_judge", last={"who": "a", "cards": ["7C"], "rank": "4"})
        d["pile"].append("7C")
        G.move(payload={"act": "doubt"})
        assert len(d["hands"]["a"]) == 6 and not d["pile"] and d["phase"] == "p_play", d
        d.update(pile=["4H"], phase="p_judge", last={"who": "a", "cards": ["4H"], "rank": "4"})
        G.move(payload={"act": "doubt"})
        assert len(d["hands"]["p"]) == 4 and not d["pile"]
        # 数が合わない (手持ちと合わせて 5 枚以上) なら, まず見抜かれる
        calls = 0
        for _ in range(200):
            d.update(hands={"p": ["2S", "2H", "9C", "9D"], "a": ["2D", "2C", "5C"]}, pile=[], phase="p_play", rank=1, last=None)
            r = G._dt_her_call(char, st, g, st["game"], dict(d, last={"who": "p", "cards": ["9C", "9D", "2S"], "rank": "2"}))
            calls += r
        assert calls > 170, calls
        G.quit()
        print("引き取り・数が合わない嘘は見抜かれる (%d/200): OK" % calls)

        # ---- 3. 表情: ポーカーフェイスほど, 嘘をついても顔に出にくい
        tr = app.traits(char)

        def tell_rate(poker, lie=True, n=600):
            tr["poker"] = poker
            hit = 0
            for _ in range(n):
                game = {"id": "doubt", "cd": {}}
                d = {"hands": {"p": [], "a": (["9C", "8D"] if lie else ["5S", "9C"])}, "pile": [], "rank": 4, "log": []}
                G._dt_her_play(char, st, g, game, d)
                lie_now = any(c[0] != "5" for c in d["last"]["cards"])
                if lie_now == lie:
                    hit += d["face"] == G._say(char, st, g, "play_tell", game)
            return hit / float(n)
        face, poker = tell_rate(0.6), tell_rate(1.4)
        honest = tell_rate(1.0, lie=False)
        tr.pop("poker", None)
        assert face > poker + 0.25 and honest < 0.25, (face, poker, honest)
        print("嘘で顔に出る割合: 顔に出る性格 %.0f%% / ポーカーフェイス %.0f%% (本当でも %.0f%%)" % (face * 100, poker * 100, honest * 100))

        # ---- 4. 見抜き方: 眠い・不機嫌だと読み違えが増える
        def accuracy(sleep, mood, n=800):
            app.set_params({"sleepiness": sleep, "mood": mood})
            ok = 0
            for k in range(n):         # 見え見えの嘘 (自分が 3 枚持っている数を 2 枚と言われた) と, ありそうな本当 (自分は 0 枚・1 枚と言われた)
                if k % 2:
                    d = {"hands": {"p": ["2S", "4S", "6S", "8S"], "a": ["7C", "7D", "7H", "KS"]},
                         "last": {"who": "p", "cards": ["3S", "5S"], "rank": "7"}, "pile": ["3S", "5S"]}
                    ok += G._dt_her_call(char, st, g, {}, d)
                else:
                    d = {"hands": {"p": ["2S", "4S", "6S", "8S", "9S", "TS", "JS", "QS", "KD", "2D", "3D", "4D"], "a": ["KS", "QD", "JD"]},
                         "last": {"who": "p", "cards": ["7S"], "rank": "7"}, "pile": ["7S"]}
                    ok += not G._dt_her_call(char, st, g, {}, d)
            return ok / float(n)
        alert, tired = accuracy(0, 70), accuracy(100, 20)
        app.set_params({"sleepiness": 0, "mood": 70})
        assert alert > tired + 0.05, (alert, tired)
        print("ダウトの当たり (嘘のときに言い・本当のときに通す): 冴えている %.0f%% / 眠くて不機嫌 %.0f%%" % (alert * 100, tired * 100))

        # ---- 5. ババ抜きの表情もポーカーフェイスに合わせる (本当の顔の出る確率)
        om = G.get("oldmaid")
        tr["poker"] = 0.6
        lo = G.honesty(char, om)
        tr["poker"] = 1.4
        hi = G.honesty(char, om)
        tr.pop("poker")
        assert lo > G.honesty(char, om) > hi >= 0.5, (lo, hi)
        print("ババ抜きの表情が本当を表す割合: 顔に出る %.0f%% / ふつう %.0f%% / ポーカーフェイス %.0f%%" % (lo * 100, G.honesty(char, om) * 100, hi * 100))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
