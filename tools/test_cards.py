"""花札・トランプゲームの確認 (一時データディレクトリで実行, 画像生成なし).

    python tools/test_cards.py
"""
import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import cards as CD  # noqa: E402
from core import engine, store  # noqa: E402


def run(app, st, gid, step, limit=600):
    """step(cards_view) → payload で最後まで進める. 結果 (win/lose/draw) を返す."""
    app.games.start(gid)
    for _ in range(limit):
        g = st.get("game")
        if not g:
            return None
        v = app.games.view(app.char(), st, app.context(app.char(), st, __import__("datetime").datetime.now()))["current"]
        c = v["cards"]
        if c.get("phase") == "round_end":
            over = g.get("over")
            app.games.move(payload={"act": "next"})
            if over:
                return over
            continue
        app.games.move(payload=step(c))
    raise AssertionError("%s が終わらない" % gid)


def koikoi_step(c):
    ph = c["phase"]
    if ph in ("p_choose_hand", "p_choose_draw"):
        return {"act": "target", "target": c["targets"][0]}
    if ph == "p_koi":
        return {"act": random.choice(["koi", "stop"])}
    return {"act": "play", "card": random.choice(c["hand"])}


def poker_step(c):
    if c["phase"] == "exchange":
        return {"act": "exchange", "discard": random.sample(range(5), random.randint(0, 3))}
    return {"act": random.choice(["call", "raise"])}


def bj_step(c):
    if c["value"] < 15:
        return {"act": "hit"}
    return {"act": "stand"}


def cc_step(c):
    if c["phase"] == "p_miss":
        return {"act": "ok"}
    closed = [i for i, f in enumerate(c["faces"]) if f is None and i not in c["up"]]
    return {"act": "flip", "idx": random.choice(closed)}


def om_step(c):
    return {"act": random.choice(["peek", "draw"]), "idx": random.randrange(c["her_count"])}


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    random.seed(11)
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        st = app.state("hina")
        st["override"] = {"activity": "relax", "label": "テスト", "location": "リビング", "until": 9e12}
        app.set_params({"affection": 80, "mood": 70, "sleepiness": 0})
        for gid, step, n in (("koikoi", koikoi_step, 3), ("poker", poker_step, 3), ("blackjack", bj_step, 3),
                             ("concentration", cc_step, 3), ("oldmaid", om_step, 3)):
            res = [run(app, st, gid, step) for _ in range(n)]
            log = [e for e in app.log("hina") if e["action"] == "_game_" + gid]
            print("%-13s %s | 記録 %d 件, 例: %s" % (gid, res, len(log), log[-1]["action_name"] + " " + log[-1]["text"]))
            assert all(r in ("win", "lose", "draw") for r in res), res
        # 野球拳と同じ脱衣の段階がポーカーで進むこと
        app.games.start("poker")
        g = st["game"]
        d = g["cd"]
        d["hands"]["p"] = ["AS", "AD", "AC", "AH", "KS"]
        d["hands"]["a"] = ["2S", "4D", "6C", "8H", "TS"]
        app.games.move(payload={"act": "exchange", "discard": []})
        d["hands"]["a"] = ["2S", "4D", "6C", "8H", "TS"]   # 交換後も弱い手に固定
        app.games.move(payload={"act": "call"})
        assert g["stage"] == 1 and "barefoot" in app.prompt_preview()["pos"], (g["stage"], g.get("outfit"))
        app.games.quit()
        assert "barefoot" not in app.prompt_preview()["pos"]
        print("poker strip: OK")
        # ババ抜きのペア処理
        h, removed = CD.remove_pairs(["7S", "7H", "XJ", "9C"])
        assert sorted(h) == ["9C", "XJ"] and removed == ["7"]
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
