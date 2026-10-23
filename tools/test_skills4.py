"""家事・気配り・身だしなみ・やりくりのスキルの確認 (一時データ, 画像生成なし).
- 既存のスキルと同じ伸び方・鈍り・得意不得意. 以前のデータには初期値で補う. 研鑽にも 4 つ (本は持ち物と連動)
- 効き目は控えめ (スキルが高くても確定的な結果にしない):
  家事 = 片付けのはかどり / 気配り = 何かあったことに気づく (出来事ごとに決まる) / 身だしなみ = 出先で知り合いになりやすさ /
  やりくり = 家計簿の覚え (丸め・書き漏らし)・少し安く買える・衝動買いが減る・品切れのとき代わりの品
- 伸ばし方: 家事・一緒に掃除 / 様子を見る・何かあった？ / 出かける・服を買う / 家計簿・買い物 / どれも研鑽

    python tools/test_skills4.py
"""
import os
import random
import shutil
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, items, life, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(12)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        L, I, S = app.life, app.items, app.solo
        ps = L.player_state()
        P = app.presence
        P.rec()["beat"] = P.rec()["input"] = time.time()

        # ---- 1. 4 つのスキルがあり, 以前のデータ (4 つしかない) にも初期値で補う
        for k in ("house", "care", "groom", "budget"):
            assert k in life.SKILLS and ps["skills"][k] == 10.0
        del ps["skills"]["budget"]
        L.player = None
        L.save_player = lambda: None
        store.save(store.wpath("player.json"), ps)
        assert L.player_state()["skills"]["budget"] == 10.0, "以前のデータには初期値"
        L.save_player = life.Life.save_player.__get__(L)
        ps = L.player_state()
        assert set(S.view()["skills"]) >= {"house", "care", "groom", "budget"}, "研鑽にも 4 つ"
        assert all(items.PRACTICE_BOOK[k] in items.CATALOG for k in ("house", "care", "groom", "budget"))

        # ---- 2. 伸ばし方
        g0 = dict(ps["skills"])
        S.start("chores")
        P.rec()["since"] -= 3600
        app.come_back()
        assert ps["skills"]["house"] > g0["house"], "家事で家事が伸びる"
        st = app.state("hina")
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": time.time() + 9e6}
        app.act("look", "hina")
        assert ps["skills"]["care"] > g0["care"], "様子を見ると気配りが伸びる"
        S.start("out", place="park")
        P.rec()["since"] -= 600
        app.come_back()
        assert ps["skills"]["groom"] > g0["groom"], "出かけると身だしなみが少し伸びる"
        L.move(None, dp=-500, cat="food", note="パン")
        app.kakeibo.write()
        assert ps["skills"]["budget"] > g0["budget"], "家計簿でやりくりが伸びる"
        S.start("practice", skill="budget")
        P.rec()["since"] -= 3600
        r = app.come_back()["solo"]
        assert "家計" in r["text"], r
        print("伸び:", {k: round(ps["skills"][k] - g0[k], 2) for k in ("house", "care", "groom", "budget")})

        # ---- 3. 効き目は控えめ: やりくりで少し安く・衝動買いが減る (確定ではない)
        def shop_stats(budget, n=400):
            ps["skills"]["budget"] = budget
            prices, impulse = [], 0
            for _ in range(n):
                ps["money"] = 100000
                ps["shop_list"] = {"detergent": 1}
                ps["items"] = {}
                b, _ = I.shop("supermarket", 1.0)
                prices += [x["price"] for x in b if x["id"] == "detergent" and not x.get("impulse")]
                impulse += any(x.get("impulse") for x in b)
            return statistics.mean(prices), impulse / float(n)
        p_lo, i_lo = shop_stats(10)
        p_hi, i_hi = shop_stats(95)
        assert p_hi < p_lo and p_hi > p_lo * 0.9, (p_lo, p_hi)       # 少しだけ
        assert i_hi < i_lo, (i_lo, i_hi)
        print("洗剤の平均 %d → %d 円 / 衝動買い %.2f → %.2f" % (p_lo, p_hi, i_lo, i_hi))
        # 品切れのとき代わりの品 (同じ栄養の食材)
        ps["skills"]["budget"] = 100
        subs = 0
        for _ in range(400):
            ps["money"] = 100000
            ps["shop_list"] = {"rice": 1}
            b, m = I.shop("supermarket", 1.0)
            subs += any(x.get("instead") for x in b)
        assert subs > 0
        # 家計簿: やりくりがうまいと, 2 日前の小さな出費もまとめずに覚えている
        ps["skills"]["budget"] = 100
        app.kakeibo.add(time.time() - 2 * 86400, -380, "food", "コンビニ")
        app.kakeibo.write()
        d2 = [b for b in app.kakeibo.rec()["book"] if b["day"] == __import__("datetime").date.fromtimestamp(time.time() - 2 * 86400).isoformat()]
        assert d2 and any(x["a"] == -380 for x in d2[0]["items"]), d2

        # ---- 4. 気配り: 何かあったことに気づく割合 (出来事ごとに決まる)
        def noticed(care):
            ps["skills"]["care"] = care
            return sum(L._noticed([{"t": 1700000000 + i * 37.3}]) for i in range(1000))
        lo, hi = noticed(10), noticed(100)
        assert 400 < lo < hi < 1000, (lo, hi)
        print("気づく: %d → %d / 1000" % (lo, hi))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
