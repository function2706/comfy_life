"""予定の行き方 (core/offline.py の GO_HOW, planner の go): 外出の予定で行き方を決められる (おまかせ・歩く・自転車・車・
電車・バス・乗り換え少なめ・タクシー). 閉じていた間はその行き方で行く. できないとき (自転車が無い など) はおまかせで.
画面の経路の下見 (geo.route_search の from) も (一時データ).

    python tools/test_plan_go.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, geo, store  # noqa: E402

geo.INSTANT = False


def at(date, hm):
    return datetime.strptime("%s %s" % (date, hm), "%Y-%m-%d %H:%M").timestamp()


def main():
    random.seed(9)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("予定の行き方")
        P, O, L = app.planner, app.offline, app.life
        L.player_state()["skills"].update(work=80, budget=70)
        P.horizon_days = lambda: 14                 # 流す曜日しだいで, 次の土日が予定の範囲の外になって平日 (仕事) に戻っていた
        d = datetime.now() + timedelta(days=1)
        while d.weekday() < 5:                      # 土日 (仕事の時間に重ならない)
            d += timedelta(days=1)
        if (d - datetime.now()).days > P.horizon_days():
            d = datetime.now() + timedelta(days=1)
        day = d.strftime("%Y-%m-%d")

        def moves(go, place="mall"):
            P.rec()["items"] = []
            P.add(day, "11:00", dict({"do": "out", "place": place}, **({"go": go} if go else {})))
            L.player_state()["stamina"], L.player_state()["money"] = 100, 50000
            app.presence.rec()["pos"] = "home:me"
            rep = O.simulate(at(day, "10:50"), at(day, "13:30"))
            return [x["text"] for x in rep["timeline"] if x["do"] == "move"]

        # ---- 1. 名前に行き方が付く. 違う値は捨てる
        P.add(day, "11:00", {"do": "out", "place": "mall", "go": "taxi"})
        x = P.view()["items"][0]
        assert x["go"] == "taxi" and x["label"].endswith("・タクシーで"), x
        P.add(day, "11:00", {"do": "out", "place": "mall", "go": "rocket"})
        assert "go" not in P.rec()["items"][0], P.rec()["items"][0]
        print("名前: OK |", x["label"])

        # ---- 2. 閉じていた間は, 決めた行き方で
        mv = moves("taxi")
        assert mv and "タクシー" in mv[0], mv
        mv = moves("walk")
        assert mv and "徒歩" in mv[0], mv
        mv = moves(None)
        print("行き方: OK | タクシー / 徒歩 / おまかせ:", mv[0] if mv else "-")

        # ---- 3. できない行き方 (自転車を持っていない) は, おまかせで
        assert app.items.count("bicycle") == 0
        mv = moves("bike")
        assert mv and "自転車" not in mv[0], mv
        print("できないときはおまかせ: OK |", mv[0])

        # ---- 4. 画面の下見: その日時に家から出たら
        r = app.geo.route_search("mall", at(day, "11:00"), "depart", "home:me")
        assert "modes" in r and "walk" in r["modes"], r.keys()
        print("下見: OK | 電車・バスの候補 %d・歩いて %d分" % (len(r["routes"]), r["modes"]["walk"]["min"]))
        # ---- 5. 到着時刻から逆算: 12:00 までに着く出発を調べ, その時刻・行き方で予定に入れると, 閉じていた間もその便で 12:00 までに着く
        goal = at(day, "12:00")
        r = app.geo.route_search("aquarium", goal, "arrive", "home:me")
        assert r["routes"] and r["depart"] < goal and r["depart"] % 60 == 0, r.get("note")
        dep = datetime.fromtimestamp(r["depart"]).strftime("%H:%M")
        assert all(m["dep"] < goal for m in r["modes"].values())
        P.rec()["items"] = []
        P.add(day, dep, {"do": "out", "place": "aquarium", "go": "transit"})
        L.player_state()["stamina"], L.player_state()["money"] = 100, 50000
        app.presence.rec()["pos"] = "home:me"
        rep = O.simulate(at(day, "09:00"), at(day, "13:00"))
        mv = [x for x in rep["timeline"] if x["do"] == "move"]
        assert mv and "電車・バス" in mv[0]["text"] and mv[0]["end"] <= goal + 60, [(x["text"], datetime.fromtimestamp(x["end"]).strftime("%H:%M")) for x in mv]
        print("到着時刻から: OK | 12:00 までに着くには %s に出る → 着いたのは %s" % (dep, datetime.fromtimestamp(mv[0]["end"]).strftime("%H:%M")))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
