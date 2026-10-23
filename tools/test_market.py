"""株の確認 (一時データ, 画像生成なし).
- 取引時間: 平日 9:00〜11:30・12:30〜15:00 だけ (土日・祝日・年末年始は休み). 値段は取引時間のあいだだけ動く
- 取引時間外のニュースは, 次の取引開始 (寄り付き) の値段に効く
- 取引時間外の売買は予約の注文になり, 次の取引開始に成行で売買される
- 指値: 以下で買う / 以上で売る. 期限が来たら取り消し. 注文中の買いの分のお金は使えない
- 積立: 毎月決まった日以降の最初の取引時間に買う. お金が足りなければその月は見送る
- 以前の 4 銘柄のワールドには, 新しい銘柄を足す (持っている株はそのまま)
- シミュレーション: 1 年の値動き (銘柄ごとの年の騰落の分布)

    python tools/test_market.py
"""
import os
import random
import shutil
import statistics
import sys
import tempfile
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, market  # noqa: E402


def ts(*a):
    return datetime(*a).timestamp()


def run(app, t0, t1):
    t = t0
    while t + market.STEP <= t1:
        t += market.STEP
        app.market.step(t)
    return t


def main():
    random.seed(11)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        # ---- 取引時間・休み
        assert market.is_open(datetime(2026, 10, 23, 9, 0)) and market.is_open(datetime(2026, 10, 23, 14, 55))
        assert not market.is_open(datetime(2026, 10, 23, 11, 45)) and not market.is_open(datetime(2026, 10, 23, 15, 0))
        assert not market.is_open(datetime(2026, 10, 24, 10, 0)), "土曜は休み"
        for d in (date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 12), date(2026, 3, 20), date(2026, 5, 6), date(2026, 9, 22),
                  date(2026, 9, 23), date(2026, 10, 12), date(2026, 11, 3), date(2026, 12, 31)):
            assert not market.trading_day(d), d
        assert market.trading_day(date(2026, 10, 23))
        nx = market.next_open(datetime(2026, 10, 23, 15, 30))
        assert nx == datetime(2026, 10, 26, 9, 0), nx            # 金曜の引けのあとは, 月曜の朝
        assert market.next_open(datetime(2026, 10, 23, 11, 40)) == datetime(2026, 10, 23, 12, 30)

        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("株")
        M = app.market
        L = app.life
        ps = L.player_state()
        ids = [a["id"] for a in M.assets()]
        assert len(ids) >= 14 and {"super", "conv", "drug", "book", "elec", "eat", "mall", "cafe", "fun", "aqua"} <= set(ids), ids
        assert all(a.get("sector") for a in M.assets())

        # ---- 取引時間外は動かない
        a = M.asset("super")
        st = M.state(a)
        p0 = st["price"]
        run(app, ts(2026, 10, 24, 0, 0), ts(2026, 10, 25, 23, 0))   # 土日
        assert M.state(a)["price"] == p0, "休みの日は値段が動かない"
        run(app, ts(2026, 10, 26, 9, 0), ts(2026, 10, 26, 11, 0))
        assert M.state(a)["price"] != p0, "取引時間には動く"

        # ---- 時間外のニュースは寄り付きに
        m = M.m()
        st = M.state(a)
        rate = app.world["economy"]["news_rate_per_hour"]
        app.world["economy"]["news_rate_per_hour"] = 0
        M._news(m, a, ts(2026, 10, 26, 20, 0), False)
        assert m["news"][-1]["after"] and st.get("gap")
        g = st["gap"]
        p1 = st["price"]
        run(app, ts(2026, 10, 26, 20, 0), ts(2026, 10, 27, 9, 0))
        assert not st.get("gap") and st.get("prev_close") == p1, "寄り付きで時間外のニュースが効く"
        print("時間外のニュース: 寄り付きの上下 %+.2f%%（向き %+d）" % (g * 100, 1 if g > 0 else -1))

        # ---- 予約の注文 (時間外の売買)
        ps["money"] = 200000
        mv, amt, profit, o = M.trade("idx", 10, ts(2026, 10, 27, 18, 0))
        assert o and o["limit"] is None and not mv and ps["money"] == 200000
        assert M.buy_power() < 200000, "予約の買いの分は使えない"
        run(app, ts(2026, 10, 27, 18, 0), ts(2026, 10, 28, 9, 10))
        assert not m["orders"] and m["holdings"]["idx"]["qty"] == 10 and ps["money"] < 200000
        assert "予約の注文" in m["fills"][-1]["text"]

        # ---- 指値: 期限切れ / 約定
        pr = M.state(M.asset("tech"))["price"]
        o1 = M.order("tech", "buy", 2, round(pr * 0.5), 2, ts(2026, 10, 28, 10, 0))       # 半値まで下がることはまずない
        with_err = False
        try:
            M.order("tech", "buy", 1000, round(pr), 1, ts(2026, 10, 28, 10, 0))
        except ValueError:
            with_err = True
        assert with_err, "買付余力を超える注文は出せない"
        run(app, ts(2026, 10, 28, 10, 0), ts(2026, 10, 30, 16, 0))
        assert not m["orders"] and "期限が来て" in m["fills"][-1]["text"], m["fills"][-1]
        o2 = M.order("idx", "sell", 5, 1, 3, ts(2026, 10, 30, 16, 0))        # 1円以上で売る = 次の取引で売れる
        run(app, ts(2026, 10, 30, 16, 0), ts(2026, 11, 2, 9, 30))
        assert m["holdings"]["idx"]["qty"] == 5 and "指値の注文" in m["fills"][-1]["text"]
        try:
            M.order("idx", "sell", 6, 1, 1)
            raise AssertionError("持っている以上は売れない")
        except ValueError:
            pass

        # ---- 積立
        n0 = m["holdings"]["idx"]["qty"]
        p = M.set_plan("idx", 10000, 5)
        m["plan_done"].pop(p["id"], None)
        run(app, ts(2026, 11, 2, 9, 30), ts(2026, 11, 6, 15, 0))      # 11/5 (木) の朝に買う
        q1 = m["holdings"]["idx"]["qty"]
        assert q1 > n0 and m["plan_done"][p["id"]] == "2026-11" and "積立で" in m["fills"][-1]["text"], m["fills"][-1]
        run(app, ts(2026, 11, 6, 15, 0), ts(2026, 11, 30, 15, 0))
        assert m["holdings"]["idx"]["qty"] == q1, "積立は月に一度"
        ps["money"] = 100
        run(app, ts(2026, 11, 30, 15, 0), ts(2026, 12, 7, 15, 0))
        assert m["holdings"]["idx"]["qty"] == q1 and "見送った" in m["fills"][-1]["text"], m["fills"][-1]
        assert any(x.get("kind") == "invest" and "積立" in x["text"] for x in app.solo.mylog())
        app.world["economy"]["news_rate_per_hour"] = rate

        # ---- 以前の 4 銘柄のワールド: 新しい銘柄を足す (持っている株はそのまま)
        w = store.load(store.wpath("world.json"), {}) or {}
        w.setdefault("economy", {})["assets"] = [{"id": i, "name": n, "icon": "", "price": 1000, "vol": 0.003, "drift": 2e-05}
                                                 for i, n in (("idx", "くらしインデックス"), ("food", "まんぷく食品"), ("tech", "ミライ電機"), ("game", "ピコピコ堂"))]
        store.save(store.wpath("world.json"), w)
        L.save_player()
        app2 = engine.App()
        ids2 = [a["id"] for a in app2.market.assets()]
        assert ids2[:4] == ["idx", "food", "tech", "game"] and "fun" in ids2, ids2
        assert app2.market.asset("idx")["drift"] < 1e-05, "以前の drift は新しい既定に"
        assert app2.life.player_state()["market"]["holdings"]["idx"]["qty"] == q1

        # ---- シミュレーション: 1 年
        random.seed(5)
        res = {i: [] for i in ids}
        for k in range(6):
            for a in M.assets():
                M.state(a)["price"] = float(a["price"])
                M.state(a)["sec"] = 0.0
                M.state(a)["bias_left"] = 0
            M.m()["orders"], M.m()["plans"] = [], []
            run(app, ts(2025, 1, 1, 0, 0), ts(2026, 1, 1, 0, 0))
            for a in M.assets():
                res[a["id"]].append(M.state(a)["price"] / float(a["price"]) - 1)
        print("1 年の騰落（6 回）: 銘柄 中央値 [最小〜最大]")
        for a in M.assets():
            r = res[a["id"]]
            print("  %-16s %+6.1f%% [%+6.1f%% 〜 %+6.1f%%]" % (a["name"], statistics.median(r) * 100, min(r) * 100, max(r) * 100))
            assert -0.75 < min(r) and max(r) < 2.5, (a["id"], r)
        idx = statistics.median(res["idx"])
        assert -0.3 < idx < 0.4, idx
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp + "_backup", ignore_errors=True)


if __name__ == "__main__":
    main()
