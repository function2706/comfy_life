"""稼ぎ方その 3 (フリマ・宝くじ) の確認 (一時データ, 画像生成なし).
- フリマ: 持ち物を出品 (食べ物・消耗品は出せない). 相場より安いほど早く売れる, 季節でも変わる (マフラーは冬).
  売れたら手数料と送料を引いて入る. 30 日で売れなければ手元に戻る. 取り下げもできる
- 宝くじ: 売り場のある行き先でだけ買える. 金曜 18 時に抽せん. 期待値はおよそ 4 割 (シミュレーション)

    python tools/test_earn3.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, earn  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def ts(*a):
    return datetime(*a).timestamp()


def days_to_sell(E, iid, price, t0, n=200):
    """出品してから売れるまでの日数 (中央値. 30 日で売れなければ 30)."""
    out = []
    for i in range(n):
        x = {"id": "x", "iid": iid, "name": "", "icon": "", "price": price, "t": t0, "until": t0 + 30 * 86400}
        t = t0
        while t < x["until"]:
            t += 3600
            if random.random() < 1 - 2.718281828 ** (-E.flea_rate(x, t)):
                break
        out.append((t - t0) / 86400.0)
    out.sort()
    return out[len(out) // 2]


def main():
    random.seed(8)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("フリマ")
        E, L = app.earn, app.life
        ps = L.player_state()

        # ---- 出品できるもの
        app.items.add("novel", 2)
        app.items.add("bread", 1)
        app.items.add("scarf", 1)
        try:
            E.flea_list("bread", 200)
            raise AssertionError("食べ物は出せない")
        except ValueError:
            pass
        try:
            E.flea_list("novel", 200)
            raise AssertionError("送料と手数料で赤字になる値段")
        except ValueError:
            pass
        x = E.flea_list("novel", 500)
        assert app.items.count("novel") == 1 and E.flea()
        E.flea_cancel(x["id"])
        assert app.items.count("novel") == 2 and not E.flea()
        v = app.state_view()["earn"]
        assert {i["id"] for i in v["flea_items"]} >= {"novel", "scarf"} and "bread" not in {i["id"] for i in v["flea_items"]}

        # ---- 売れやすさ: 値段・季節
        fair = E.fair("novel")
        cheap, dear = days_to_sell(E, "novel", int(fair * 0.7), ts(2026, 10, 1)), days_to_sell(E, "novel", int(fair * 1.6), ts(2026, 10, 1))
        winter, summer = days_to_sell(E, "scarf", E.fair("scarf"), ts(2026, 12, 1)), days_to_sell(E, "scarf", E.fair("scarf"), ts(2026, 7, 1))
        print("売れるまで（中央値・日）: 小説 安め %.1f / 高め %.1f・マフラー 冬 %.1f / 夏 %.1f" % (cheap, dear, winter, summer))
        assert cheap < dear and winter < summer

        # ---- 売れる / 期限で戻る (時間を進める)
        m0 = ps["money"]
        x = E.flea_list("novel", int(fair * 0.9 / 10) * 10)
        t = time.time()
        for i in range(24 * 60):
            t += 300
            E.step(t, 300)
            if not E.flea():
                break
        assert not E.flea() and ps["money"] > m0 and any("フリマで" in e["text"] for e in app.solo.mylog())
        print("売れた:", next(e["text"] for e in reversed(app.solo.mylog()) if "フリマで" in e["text"]))
        x = E.flea_list("scarf", 8000)
        E.step(x["until"] + 1, 300)
        assert not E.flea() and app.items.count("scarf") == 1, "期限で手元に戻る"

        # ---- 宝くじ: 売り場でだけ
        P = app.presence
        try:
            E.lotto_buy(10)
            raise AssertionError("家で買えた")
        except ValueError:
            pass
        P.declare("out", time.time())
        P.rec()["place"] = "station"
        ps["money"] = 10000
        tk = E.lotto_buy(10)
        assert ps["money"] == 7000 and datetime.fromtimestamp(tk["draw"]).weekday() == 4 and datetime.fromtimestamp(tk["draw"]).hour == 18
        E.step(tk["draw"] + 1, 300)
        assert not E.lotto()["tickets"] and E.lotto()["results"]
        print("宝くじ:", E.lotto()["results"][-1])
        assert E.next_draw(ts(2026, 10, 23, 17, 0)) == ts(2026, 10, 23, 18, 0)
        assert E.next_draw(ts(2026, 10, 23, 19, 0)) == ts(2026, 10, 30, 18, 0)

        # ---- 期待値 (シミュレーション)
        exp = sum(p * a for p, a in earn.LOTTO) / earn.LOTTO_PRICE
        random.seed(1)
        n, won = 200000, 0
        for i in range(n):
            r, acc = random.random(), 0.0
            for p, a in earn.LOTTO:
                acc += p
                if r < acc:
                    won += a
                    break
        print("宝くじの期待値 %.0f%%（20万枚で %.0f%% 戻った）" % (exp * 100, won * 100.0 / (n * earn.LOTTO_PRICE)))
        assert 0.35 < exp < 0.5
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp + "_backup", ignore_errors=True)


if __name__ == "__main__":
    main()
