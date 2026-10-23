"""店での買い物の確認 (一時データ, 画像生成なし).
- 店に出かけて, 品を選び終える時間がたつと, その場で買い物が済む (知らせ). 済んだあともその場にいてよい. 帰ったときに買い直さない
- 済む前に店を出れば「まだ買い物の途中だった」(何も買わない)
- 出かけている先から, ほかの店へ (いまの外出の結果を出して, そのまま向かう)
- 行動パターンの買い物は, 今どおりその場で買う

    python tools/test_shop.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(3)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        S, I, P = app.solo, app.items, app.presence
        P.rec()["beat"] = P.rec()["input"] = time.time()
        app.life.player_state()["money"] = 50000

        # ---- 1. 店で品を選び終えると, その場で買い物が済む
        I.set_list("detergent", 1)
        I.set_list("veggies", 1)
        S.start("out", place="supermarket")
        sl = P.rec()["solo"]
        assert sl.get("shop_need", 0) > 8 and S.shop_tick() is None and "shop_wait" in P.view(time.time())
        sl["t"] -= sl["shop_need"] * 60 + 1
        res = S.shop_tick()
        assert res and res["label"] == "スーパー" and res["total"] == sum(b["price"] for b in res["bought"]), res
        assert P.view(time.time())["shop"]["text"] == res["text"] and S.shop_tick() is None, "一度だけ"
        n = dict(I.ps()["items"])
        S.shop_ack()
        assert P.view(time.time())["shop"]["seen"]
        r = app.come_back()["solo"]
        assert dict(I.ps()["items"]) == n and "買い物をした" in r["text"], (r, n, I.ps()["items"])
        print("済んだ:", res["text"], "/ 合計", res["total"])

        # ---- 2. 済む前に店を出る
        I.set_list("detergent", 1)
        S.start("out", place="drugstore")
        n = dict(I.ps()["items"])
        r = app.come_back()["solo"]
        assert r.get("shop_pending") and "途中" in r["text"] and dict(I.ps()["items"]) == n, r
        print("途中:", r["text"])

        # ---- 3. ほかの店へ
        S.start("out", place="convenience")
        P.rec()["solo"]["t"] -= 3600
        S.shop_tick()
        r = S.move("bookstore")
        assert r["solo"] and "買い物をした" in r["solo"]["text"] and P.rec()["place"] == "bookstore" and P.rec()["mode"] == "out"
        app.come_back()

        # ---- 3b. 買うものがなかったときも知らせる (リストが空 / この店には売っていない)
        I.ps()["shop_list"] = {}
        S.start("out", place="supermarket")
        P.rec()["solo"]["t"] -= 3600
        res = S.shop_tick()
        assert res["nothing"] == "買うものリストは空だった" and "買うものはなかった" in res["text"], res
        app.come_back()
        I.set_list("game", 1)                       # ゲームソフトはスーパーには売っていない
        S.start("out", place="supermarket")
        P.rec()["solo"]["t"] -= 3600
        res = S.shop_tick()
        assert res["nothing"] and "売っていなかった" in res["nothing"] and "ゲームソフト" in res["nothing"], res
        app.come_back()
        I.ps()["shop_list"] = {}
        print("買うものなし:", res["text"])

        # ---- 4. 行動パターン (その場で買う)
        I.set_list("detergent", 1)
        n = I.count("detergent")
        out = S.result("out", 1.0, time.time(), place="supermarket")
        assert I.count("detergent") > n or "品切れ" in out["text"], out
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
