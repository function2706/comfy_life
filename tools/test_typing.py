"""内職のタイピング (データ入力): ローマ字の打ち方の揺れ (core/romaji.py)・辞書・出題・当て直し・稼ぎ・設定で足す語・文 (一時データ).

    python tools/test_typing.py
"""
import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, puzzles as P, romaji as R, store  # noqa: E402

# (読み, 受け付ける打ち方, 受け付けない打ち方)
CASES = [
    ("しお", ["shio", "sio", "cio"], ["sho"]),
    ("つくえ", ["tsukue", "tukue"], ["tskue"]),
    ("ちず", ["chizu", "tizu"], ["cizu"]),
    ("ふとん", ["futonn", "hutonn", "hutoxn"], ["futon", "phuton"]),
    ("じかん", ["jikann", "zikann"], ["jikan"]),
    ("じゃがいも", ["jagaimo", "zyagaimo", "jyagaimo", "jixyagaimo", "zilyagaimo"], ["zagaimo"]),
    ("しゃしん", ["shashinn", "syasinn", "sixyasinn"], ["shasin"]),
    ("ちゃわん", ["chawann", "tyawann", "cyawann"], []),
    ("きって", ["kitte", "kixtute", "kiltute", "kixtsute"], ["kite"]),
    ("まっちゃ", ["matcha", "maccha", "mattya", "maxtucha"], ["macha"]),
    ("さんぽ", ["sanpo", "sannpo", "saxnpo"], []),
    ("れんあい", ["rennai", "rexnai"], ["renai"]),
    ("こんにちは", ["konnnichiha", "konnnitiha"], ["konnichiha"]),
    ("きんよう", ["kinnyou"], ["kinyou"]),
    ("ちーず", ["chi-zu"], ["chiizu"]),
    ("ふぁいる", ["fairu", "fuxairu", "hulairu"], []),
    ("1,280えん", ["1,280enn"], ["1280enn"]),
    ("10:30~", ["10:30~"], []),
]


def main():
    random.seed(5)
    # ---- 1. ローマ字の打ち方の揺れ
    for y, good, bad in CASES:
        k = R.normalize(y)
        for t in good:
            assert R.complete(k, t), (y, t)
            assert all(R.accepts(k, t[:i]) for i in range(len(t) + 1)), (y, t)
        for t in bad:
            assert not R.complete(k, t), (y, t)
        g = R.guide(k)
        assert R.complete(k, g), (y, g)
    assert R.guide(R.normalize("しんぶん")) == "shinbunn" and R.guide(R.normalize("まっちゃ")) == "maccha"
    assert R.guide(R.normalize("しんぶん"), "sinn") == "sinnbunn", "見本は打った分に続ける"
    # 押したキーの当て直し: 受け付けないキーは打ち間違いとして数え, 入れない
    typed, miss = R.replay(R.normalize("さかな"), "sakxanqa")
    assert typed == "sakana" and miss == 2, (typed, miss)
    assert R.normalize("カタカナ　ＡＢ１") == "かたかなab1"
    print("ローマ字の打ち方: %d 通りの読みで OK" % len(CASES))

    # ---- 2. 辞書: 数と, どれも打てること
    d = P.typing_dict()
    assert len(d["words"]) >= 300 and len(d["short"]) >= 150 and len(d["long"]) >= 60, {k: len(v) for k, v in d.items()}
    for part, xs in d.items():
        for x in xs:
            assert R.typeable(x["y"]), (part, x)
        assert len({x["t"] for x in xs}) == len(xs), part
    import re
    assert sum(1 for x in d["long"] if re.search(r"[0-9]", x["y"])) >= 50, "長めの文は数字・記号まじり"
    print("辞書: 単語 %d・短い文 %d・長めの文 %d" % (len(d["words"]), len(d["short"]), len(d["long"])))

    # ---- 3. 出題と当て直し
    for lv, n in (("easy", 12), ("mid", 6), ("hard", 3)):
        p = P.new("typing", lv, random.Random(1))
        assert len(p["items"]) == n and len({x["t"] for x in p["items"]}) == n
        for it in list(p["items"]):
            r = P.move(p, {"i": p["i"], "keys": "!" + R.guide(it["k"])})       # 頭に打ち間違いを一つ
        assert P.solved(p) and r["solved"] and p["miss"] == n, (lv, p["miss"])
    p = P.new("typing", "mid", random.Random(2))
    try:
        P.move(p, {"i": 1, "keys": "a"})
        raise AssertionError("違う文を受け付けた")
    except ValueError:
        pass
    try:
        P.move(p, {"i": 0, "keys": R.guide(p["items"][0]["k"])[:-1]})
        raise AssertionError("打ちかけで次へ進んだ")
    except ValueError:
        pass
    assert p["i"] == 0
    print("出題・当て直し: OK")

    # ---- 4. 稼ぎ: 正確さと速さ. 解けなければ進んだぶんの 2 割
    def run(lv, miss_each, sec):
        p = P.new("typing", lv, random.Random(3))
        for it in list(p["items"]):
            g = R.guide(it["k"])
            P.move(p, {"i": p["i"], "keys": "!" * miss_each + g})
        return P.pay(p, sec, 1.0), P.typing_accuracy(p)
    par = P.PAR["typing"]["mid"]
    clean_fast, acc1 = run("mid", 0, par * 0.6)
    clean_slow, _ = run("mid", 0, par * 2.5)
    sloppy, acc2 = run("mid", 6, par * 0.6)
    assert clean_fast > clean_slow and clean_fast > sloppy, (clean_fast, clean_slow, sloppy)
    assert acc1 == 1.0 and acc2 < 0.9
    p = P.new("typing", "mid", random.Random(3))
    P.move(p, {"i": 0, "keys": R.guide(p["items"][0]["k"])})
    part = P.pay(p, 30, 1.0)
    assert 0 < part < clean_slow
    print("稼ぎ (中, 仕事スキル前): 正確で速い %d 円 / 正確で遅い %d 円 / 打ち間違いが多い %d 円 (正確さ %d%%) / 1 つでやめた %d 円" % (
        clean_fast, clean_slow, sloppy, acc2 * 100, part))

    # ---- 5. 設定で足した語・文 (打てない行は飛ばす)
    extra = {"words": "買い物袋|かいものぶくろ\n漢字だけ|漢字\nだめな行\n縁側｜えんがわ", "long": ""}
    d2 = P.typing_dict(extra)
    assert len(d2["words"]) == len(d["words"]) + 2 and {"t": "縁側", "y": "えんがわ"} in d2["words"]
    assert len(P.typing_dict()["words"]) == len(d["words"]), "既定の辞書は変わらない"

    # ---- 6. 本体: 文章のスキルを 1/3 混ぜ, 少し伸ばす
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("タイピング")
        app.world["typing_extra"] = {"words": "\n".join("足した語%d|たしたご%d" % (i, i) for i in range(400))}
        L = app.life
        L.player_state()["skills"].update(work=10, write=90)
        m_mix = P.skill_mult("typing", L.skill_mult)
        assert L.skill_mult("work") < m_mix < L.skill_mult("write")
        assert P.skill_mult("sudoku", L.skill_mult) == L.skill_mult("work")
        L.player_state()["skills"]["write"] = 20
        tk = app.task_start("typing", "easy")
        v = tk["view"]
        assert any(x["t"].startswith("足した語") for x in v["items"]), "設定で足した語も出る"
        w0 = L.skill("write")
        for i, it in enumerate(v["items"]):
            r = app.task_move(tk["token"], {"i": i, "keys": R.guide(it["k"])})
        assert r["solved"]
        fin = app.task_finish(tk["token"])
        assert fin["task"]["solved"] and fin["task"]["pay"] > 0 and L.skill("write") > w0, fin["task"]
        print("本体: 稼ぎ %d 円, 文章スキル %.2f → %.2f" % (fin["task"]["pay"], w0, L.skill("write")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK")


if __name__ == "__main__":
    main()
