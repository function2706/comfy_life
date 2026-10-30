"""常備数: 使って減って下回ると, 足りない分 (買う単位に切り上げ) が買うものリストに戻る (core/items.py の stock / restock).

    python tools/test_stock.py
"""
import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(4)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("常備")
        I = app.items
        sl = lambda: I.ps()["shop_list"]           # noqa: E731
        sl().clear()
        I.ps()["items"].clear()

        # ---- 1. 決めた時点で足りなければ, すぐリストに (卵と豆腐は 1 個 4 回分: 6 回分なら 2 個)
        v = I.set_stock("eggs_tofu", 6)
        assert v["stock"] == {"eggs_tofu": 6} and sl()["eggs_tofu"] == 2, (v["stock"], sl())
        print("決めた時点で足りなければリストへ: OK", sl())

        # ---- 2. 買って足りれば戻らない. 使って下回ると, 足りない分だけ戻る
        sl().clear()
        I.add("eggs_tofu", 8)
        assert I.restock("eggs_tofu") == 0 and "eggs_tofu" not in sl()
        I.use_nut("protein")
        I.use_nut("protein")                       # 8 → 6 回分: まだ常備数ちょうど
        assert "eggs_tofu" not in sl(), sl()
        I.use_nut("protein")                       # 5 回分: 1 回分足りない → 1 個
        assert sl()["eggs_tofu"] == 1, sl()
        print("使って下回ると足りない分だけ戻る: OK", sl())

        # ---- 3. 手で消したら, 次に減るまでは戻さない. 手で多めにしていれば減らさない
        I.set_list("eggs_tofu", 0)
        assert "eggs_tofu" not in sl()
        I.set_stock("cookies", 0)                  # 別の品に触っても戻らない
        assert "eggs_tofu" not in sl()
        I.use_nut("protein")                       # 4 回分
        assert sl()["eggs_tofu"] == 1
        I.set_list("eggs_tofu", 5)
        I.use_nut("protein")
        assert sl()["eggs_tofu"] == 5, sl()
        print("手で消した・多めにしたリストを尊重: OK")

        # ---- 4. 回分でない品 (洗剤) も. 常備数を解除したら戻らない
        sl().clear()
        I.add("detergent", 2)
        I.set_stock("detergent", 2)
        I.use_kind("detergent")
        assert sl()["detergent"] == 1
        sl().clear()
        I.set_stock("detergent", 0)
        I.use_kind("detergent")
        assert "detergent" not in sl() and "detergent" not in I.view()["stock"]
        print("回分でない品・解除: OK")

        # ---- 5. 買い物でリストどおり買えば, 常備数まで戻る (ちょうどで, 余計に増えない)
        I.ps()["items"].clear()
        sl().clear()
        I.ps()["money"] = 100000
        I.set_stock("veggies", 3)
        assert sl()["veggies"] == 1
        for _ in range(20):                        # 品切れのこともあるので, 買えるまで
            I.shop("supermarket", 1.0)
            if I.count("veggies") >= 3:
                break
        assert I.count("veggies") >= 3 and "veggies" not in sl(), (I.count("veggies"), sl())
        print("買い物で常備数まで戻る: OK")

        # ---- 6. 以前のセーブ (stock の無い player) でも動く
        I.ps().pop("stock")
        assert I.view()["stock"] == {} and I.restock("rice") == 0
        try:
            I.set_stock("no_such", 1)
            raise AssertionError("無い品に常備数を決められた")
        except KeyError:
            pass
        print("以前のセーブ: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
