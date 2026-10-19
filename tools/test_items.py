"""品物・持ち物・買うものリストの確認: 買い物でリストの品を買う (店・品切れ・お金), 家での行動が持ち物を使う,
持ち物からのプレゼントと好き・苦手 (一時データ, 画像生成なし).

    python tools/test_items.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, items, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)     # 時刻を日曜の昼に固定 (流す日時に左右されないように)


def main():
    random.seed(41)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        I, L = app.items, app.life
        ps = L.player_state()
        ps["money"] = 100000
        st = app.state("hina")
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": 9e12}
        app.set_params({"mood": 70, "sleepiness": 0, "energy": 80, "satiety": 30, "affection": 70, "trust": 70})

        # ---- 1. 買い物: 買うものリストの品が, その店で売っていれば買う (売っていない店では買わない)
        I.set_list("tea_leaves", 2)
        I.set_list("book_work", 1)
        I.set_list("plush", 1)
        b, m = I.shop("shopping_street", 1)
        names = [x["id"] for x in b if not x.get("impulse")]
        assert "plush" not in names and "book_work" not in names, "商店街にはぬいぐるみも参考書もない"
        assert I.count("tea_leaves") + sum(1 for x in m if "お茶っ葉" in x) >= 1
        b, m = I.shop("mall", 1)
        assert I.count("plush") == 1 or any("ぬいぐるみ" in x for x in m)
        # お金が足りなければ買えない
        ps["money"] = 100
        I.set_list("game", 1)
        b, m = I.shop("mall", 1)
        assert I.count("game") == 0 and any("お金が足りなくて" in x for x in m), m
        ps["money"] = 100000
        # 画面を開いての買い物 (一人で) でも
        I.set_list("veggies", 2)
        app.solo.start("shopping", place="shopping_street")
        app.presence.rec()["since"] -= 3600
        r = app.come_back()
        assert r["solo"]["bought"] or "品切れ" in r["solo"]["text"], r["solo"]
        print("shopping: OK", r["solo"]["text"])

        # ---- 2. 家での行動が持ち物を使う
        ps["items"] = {"veggies": 1}
        st["cooldowns"] = {}
        e = app.act("cook")["entry"]
        assert I.count("veggies") == 0 and "ありあわせ" not in e["text"], e["text"]
        st["cooldowns"] = {}
        e = app.act("cook")["entry"]
        assert "ありあわせ" in e["text"], "食材が無いと, 簡単なものだけ"
        st["cooldowns"] = {}
        e = app.act("tea")["entry"]
        assert "白湯" in e["text"]
        # 研鑽は本があると伸びやすい (減らない)
        def practice(book):
            ps["items"] = {"book_cook": 1} if book else {}
            g = 0
            for _ in range(10):
                ps["skills"]["cook"] = 20
                app.solo.start("practice", "cook")
                app.presence.rec()["since"] -= 2 * 3600
                g += app.come_back()["solo"]["skill"]["cook"]
            return g
        assert practice(True) > practice(False), "本があると伸びやすい"
        ps["items"] = {"book_cook": 1}
        app.solo.start("practice", "cook")
        app.presence.rec()["since"] -= 3600
        assert "本を見ながら" in app.come_back()["solo"]["text"] and I.count("book_cook") == 1
        print("use: OK")

        # ---- 3. 持ち物からプレゼント: 好き・苦手で反応が変わる. 断られたら手元に残る
        char = app.char("hina")
        char["persona_id"] = "teinei"            # 甘いもの・花・本が好き
        assert I.feel(char, "cookies")["liked"] and not I.feel(char, "game")["liked"]
        char["dislikes"] = ["games"]
        ps["items"] = {"cookies": 1, "game": 1, "necklace": 1}
        st["gifts"] = []
        e = app.give_item("cookies", "hina")["entry"]
        assert I.count("cookies") == 0 and ("大好き" in e["text"] or "クッキー" in e["text"] or e["text"]), e["text"]
        st["cooldowns"] = {}
        e = app.give_item("game", "hina")["entry"]
        assert "ゲームソフト" in e["text"] and I.count("game") == 0, ("苦手でも受け取りはする", e["text"])
        # 高価な物は「重い」と断られることも (仲が浅いと). 断られたら手元に残る
        app.set_params({"affection": 30, "trust": 30}, "hina")
        char["persona_id"] = "kedakai"
        st["cooldowns"], st["gifts"] = {}, []
        e = app.give_item("necklace", "hina")["entry"]
        assert I.count("necklace") == 1 and "受け取れない" in e["text"], e["text"]
        try:
            app.give_item("veggies", "hina")
            raise AssertionError("食材をプレゼントできてしまう")
        except ValueError:
            pass
        try:
            app.give_item("plush", "hina")
            raise AssertionError("持っていない物を渡せてしまう")
        except ValueError:
            pass
        print("gift: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
