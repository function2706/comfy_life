"""家計簿の確認 (一時データ, 画像生成なし).
- お金の出入りは裏ですべて記録し (ledger.raw), 見えるのは家計簿につけた分だけ (ledger.book)
- つけるのは家事の「家計簿」だけ (日記ではつけない). 前回から今までをまとめて書く. 日を空けるほどうろ覚え
  (その日・前の日は正確 / 2 日以上前は丸まり, 小さな出費は「こまごま」にまとまる / 7 日以上前は一部を書き漏らす)
- 見積もり: 固定費は記録しなくても分かる. 変動費は記録から (記録が少ないほど幅が広い)

    python tools/test_kakeibo.py
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
    random.seed(4)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        L, K = app.life, app.kakeibo
        now = time.time()
        L.player_state()["beat"] = now
        app.presence.rec()["beat"] = app.presence.rec()["input"] = now

        # ---- 1. 裏の記録: 動いたお金はすべて残る. 家計簿をつけるまでは何も見えない
        L.move(None, dp=-1234, cat="food", note="スーパー")
        L.move(None, dp=5000, cat="income", note="給料")
        v = K.view()
        assert not v["days"] and v["estimate"]["need"] is None and v["money"] == L.player_state()["money"]
        assert v["estimate"]["fixed"]["rent"] > 0, "固定費は記録しなくても分かる"
        raw = K.rec()["raw"]
        assert any(x["a"] == -1234 for x in raw) and any(x["a"] == 5000 for x in raw)

        # ---- 2. 日を空けてつけると, うろ覚え (丸まる・こまごま・書き漏らし). 今日の分は正確
        d = 86400
        for i in range(40):
            K.add(now - 10 * d + i * 60, -random.randint(300, 2500), "food", "食材")          # 10 日前: 書き漏らしがある
        K.add(now - 3 * d, -1234, "shopping", "洗剤")                                        # 3 日前: 丸まる
        K.add(now - 3 * d + 60, -380, "food", "コンビニ")                                    # 3 日前の小さな出費: まとまる
        K.add(now - 10 * d + 600, -60000, "fixed", "家賃")                                  # 大きな固定の出費は覚えている
        K.rec()["raw"].sort(key=lambda x: x["t"])
        r = app.solo.start("kakeibo")
        assert r["done"].startswith("家計簿をつけた") and "うろ覚え" in r["done"], r
        book = {b["day"]: b for b in K.rec()["book"]}
        from datetime import date
        day = lambda t: date.fromtimestamp(t).isoformat()      # noqa: E731
        today = book[day(now)]
        assert any(x["a"] == -1234 and not x["approx"] for x in today["items"]), today
        d3 = book[day(now - 3 * d)]
        assert any(x["a"] == -1000 and x["approx"] for x in d3["items"]), d3["items"]
        assert any(x["n"] == "こまごました出費" for x in d3["items"]), d3["items"]
        d10 = book[day(now - 10 * d)]
        assert any(x["a"] == -60000 for x in d10["items"]), "家賃は覚えている"
        assert len([x for x in d10["items"] if x["c"] == "food"]) < 40 and r["kakeibo"]["forgot"] > 0, "書き漏らしがある"
        print("家計簿:", r["done"], "/ 書き漏らし", r["kakeibo"]["forgot"])

        # ---- 3. 見積もり: 記録が少ないうちは幅が広い
        v = K.view()
        e = v["estimate"]
        assert e["need"] and e["need"][0] <= e["need"][1] and e["variable"][1] > e["variable"][0], e
        assert "大体" in e["note"], e["note"]
        assert any(c["id"] == "fixed" for c in v["cats"]) and v["days"][0]["day"] == day(now)
        print("見積もり: 1日 %s〜%s円（%s）" % (e["need"][0], e["need"][1], e["note"]))

        # ---- 4. もう一度つけても, 書いた分は増えない. 新しい出入りだけ足される
        n0 = sum(len(b["items"]) for b in K.rec()["book"])
        K.write()
        assert sum(len(b["items"]) for b in K.rec()["book"]) == n0
        L.move(None, dp=-500, cat="eatout", note="定食")
        K.write()
        assert sum(len(b["items"]) for b in K.rec()["book"]) == n0 + 1

        # ---- 5. 外にいるときは, つけられない
        app.solo.start("out", place="park")
        try:
            app.solo.start("kakeibo")
            raise AssertionError("外で家計簿をつけられる")
        except ValueError:
            pass
        app.presence.rec()["since"] -= 600
        app.come_back()

        # ---- 6. オフラインの行動パターンでも, 家計簿をつけられる
        from core import offline
        days = {k: [{"at": "00:00", "do": "rest"}, {"at": "12:00", "do": "kakeibo"}, {"at": "13:00", "do": "rest"}] for k in offline.DAY_KEYS}
        app.save_settings({"offline": {"enabled": True, "days": days}})
        L.move(None, dp=-700, cat="food", note="パン")
        t1 = time.time()
        rep = app.offline.simulate(t1 - 30 * 3600, t1)
        assert any(x["do"] == "kakeibo" for x in rep["timeline"]), [x["do"] for x in rep["timeline"]]
        print("オフライン:", [x["text"] for x in rep["timeline"] if x["do"] == "kakeibo"])
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
