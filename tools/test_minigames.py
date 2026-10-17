"""ミニゲームの確認 (一時データディレクトリで実行, 画像生成なし).

    python tools/test_minigames.py
"""
import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, games, store  # noqa: E402


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    random.seed(1)
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        st = app.state("hina")
        st["override"] = {"activity": "relax", "label": "テスト", "location": "リビング", "until": 9e12}

        # 好感度が足りないと断られる
        app.set_params({"affection": 20})
        r = app.games.start("yakyuken")
        assert r.get("refused") and not st.get("game"), r
        print("refuse:", r["entry"]["text"])

        # 野球拳: 必ず勝つ手を出し続けて降参まで
        app.set_params({"affection": 70})
        r = app.games.start("yakyuken")
        print("start:", r["entry"]["text"], "| hint:", r.get("hint"))
        for _ in range(20):
            her = st["game"]["next"]
            win_hand = next(h for h in games.HANDS if games.BEATS[h] == her)
            r = app.games.move(hand=win_hand)
            print("  %s → %s | %s" % (r["entry"]["action_name"], r["entry"]["text"],
                                     [p["pos"] for p in r["entry"]["parts"] if p["src"].startswith("服装")]))
            if r["ended"]:
                break
        assert r["ended"] == "win" and st.get("game") is None
        assert "wrapped in blanket" in r["entry"]["pos"] and "hair ribbon" not in r["entry"]["pos"], r["entry"]["pos"]
        assert "camisole" not in app.prompt_preview()["pos"], "終わったら服は元に戻る"

        # 野球拳: 負け続けてライフ切れ
        app.games.start("yakyuken")
        for _ in range(20):
            her = st["game"]["next"]
            lose_hand = games.BEATS[her]
            r = app.games.move(hand=lose_hand)
            if r["ended"]:
                break
        assert r["ended"] == "lose", r
        print("lose:", r["entry"]["text"])

        # あっち向いてホイ: 最後まで遊べること
        app.games.start("acchimuite")
        for _ in range(200):
            g = st["game"]
            if g["phase"] == "rps":
                r = app.games.move(hand=random.choice(games.HANDS))
            else:
                r = app.games.move(direction=random.choice(games.DIRS))
            if r["ended"]:
                break
        assert r["ended"] in ("win", "lose"), r
        print("acchimuite:", r["ended"], r["entry"]["action_name"], r["entry"]["text"])

        # 中断
        app.games.start("acchimuite")
        r = app.games.quit()
        assert st.get("game") is None and r["ended"] == "quit"
        st["override"] = {"activity": "class", "label": "授業", "away": True, "until": 9e12}
        try:
            app.games.start("acchimuite")
            raise AssertionError("外出中に開始できてしまった")
        except ValueError as e:
            print("require:", e)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
