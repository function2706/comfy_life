"""スピード (二人で同時に出す) の確認: 出せる札 (1 つ違い, A と K もつながる)・場札の補充・どちらも出せないときの「スピード！」・
勝ち負け・キャラの速さの幅 (体力・眠気・機嫌)・「せーの」まで出せない・問い合わせで何も起きなければ書き込まない
(一時データディレクトリ, 画像生成なし).

    python tools/test_speed.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, speedcards as SC, store  # noqa: E402


def c(s):
    return "SHDC".index(s[1]) * 13 + "A23456789TJQK".index(s[0])


def ai_rate(params, secs=60.0, seed=0):
    """キャラだけが出し続けたとき, 1 分あたり何枚出すか (台札はいつも出せる形に戻す)."""
    rng = random.Random(seed)
    st = SC.new(rng)
    st["ai_next"] = 0.0
    n, t = 0, 0.0
    q = SC.quickness(params)
    while t < secs:
        t += 0.1
        st["center"] = [st["a"]["field"][0] or c("5S"), c("KD")]
        st["center"][0] = (st["center"][0] // 13) * 13 + ((st["center"][0] % 13) + 1) % 13      # 一番目の場札と 1 つ違い
        before = SC.left(st, "a")
        SC.advance(st, t, q, rng)
        n += before - SC.left(st, "a")
        st["a"]["stock"] = st["a"]["stock"] or [c("2S")] * 20
        st.pop("over", None)
    return n * 60.0 / secs


def main():
    # ---- 1. 出せる札: 1 つ違い (A と K もつながる)
    assert SC.fits(c("5H"), c("4S")) and SC.fits(c("5H"), c("6C")) and SC.fits(c("AH"), c("KS")) and SC.fits(c("KD"), c("AC"))
    assert not SC.fits(c("5H"), c("5S")) and not SC.fits(c("5H"), c("7S"))
    st = SC.new(random.Random(1))
    assert len(st["p"]["stock"]) == 21 and len(st["a"]["stock"]) == 21 and all(x // 13 in (1, 2) for x in st["p"]["field"])
    # 出したら山から補う. 出せない札は出せない
    st["center"] = [c("6S"), c("9C")]
    st["p"]["field"][0] = c("7H")
    SC.play(st, "p", 0, 0)
    assert st["center"][0] == c("7H") and st["p"]["field"][0] is not None and len(st["p"]["stock"]) == 20
    st["p"]["field"][1] = c("2D")
    try:
        SC.play(st, "p", 1, 0)
        raise AssertionError("出せない札を出せた")
    except ValueError:
        pass
    # どちらも出せない → スピード (山から 1 枚ずつ台札へ. 山が無ければ場札から)
    st = {"p": {"field": [c("2H"), None, None, None], "stock": [c("9H")]}, "a": {"field": [c("2S"), None, None, None], "stock": []},
          "center": [c("6C"), c("6D")], "speeds": 0, "ai_next": 0.0}
    SC.advance(st, 1.0, 0.5, random.Random(0))
    assert st["speeds"] == 0 and st["speed_at"] == 0.0 + SC.SPEED_WAIT, "まずカウントダウン (予定の時刻 0.0 から)"
    assert SC.view(st, 1.0)["speed_in"] == 2.0
    SC.advance(st, 2.5, 0.5, random.Random(0))
    assert st["speeds"] == 0, "カウントダウン中は出さない"
    SC.advance(st, 3.1, 0.5, random.Random(0))
    assert st["speeds"] == 1 and st["center"] == [c("9H"), c("2S")] and st["a"]["field"][0] is None, st
    assert SC.view(st, 3.5)["flip_ago"] == 0.5 and SC.view(st, 3.5)["speed_in"] == 0, "山から出した直後 (画面が台札を光らせる)"
    print("出せる札・補充・スピード！: OK")

    # ---- 2. キャラの速さ: 体力・眠気・機嫌しだい (いつも最速ではない. ときどき見落とす)
    fresh = ai_rate({"energy": 95, "sleepiness": 0, "mood": 80})
    tired = ai_rate({"energy": 15, "sleepiness": 90, "mood": 25})
    assert fresh > tired * 1.6 and 15 < tired < fresh < 90, (fresh, tired)
    print("キャラの出す速さ (1 分あたり): 元気 %.0f 枚 / 眠くて疲れて不機嫌 %.0f 枚" % (fresh, tired))

    # ---- 3. 本体: 「せーの」まで出せない・勝ち負け・問い合わせ
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    random.seed(41)
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        st = app.state("hina")
        st["override"] = {"activity": "relax", "label": "テスト", "location": "リビング", "until": 9e12}
        app.set_params({"affection": 80, "mood": 70, "sleepiness": 0, "energy": 90})
        G = app.games
        G.start("speed")
        sp = st["game"]["sp"]
        try:
            G.move(payload={"act": "play", "i": 0})
            raise AssertionError("「せーの」の前に出せた")
        except ValueError:
            pass
        sp["start_at"] = time.time() - 1
        sp["ai_next"] = time.time() + 60          # キャラはまだ動かない
        saves = []
        orig = app.save_state
        app.save_state = lambda cid: saves.append(cid) or orig(cid)
        r = G.move(payload={"act": "tick"})
        assert not saves and r["speed"]["left"]["p"] == 25, "何も起きない問い合わせは書き込まない"
        app.save_state = orig
        # あなたが出し切ったら勝ち
        sp["p"] = {"field": [c("5H"), None, None, None], "stock": []}
        sp["center"] = [c("4S"), c("JC")]
        r = G.move(payload={"act": "play", "i": 0})
        assert r["ended"] == "win" and st["game"]["over"] == "win", r
        G.quit()
        # キャラが出し切ったら負け
        G.start("speed")
        sp = st["game"]["sp"]
        sp["start_at"] = time.time() - 5
        sp["a"] = {"field": [c("5S"), None, None, None], "stock": []}
        sp["p"]["field"] = [c("2H"), c("2D"), c("2H"), c("2D")]
        sp["center"] = [c("4C"), c("JC")]
        sp["ai_next"] = time.time() - 1
        orig_rand = random.random
        random.random = lambda: 0.99                 # 見落とさない
        r = G.move(payload={"act": "tick"})
        random.random = orig_rand
        assert r["ended"] == "lose", r
        G.quit()
        log = [e for e in app.log("hina") if e["action"] == "_game_speed"]
        print("勝ち負け・せーの・問い合わせ: OK | 例:", log[-1]["text"])
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
