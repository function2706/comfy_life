"""路線と時刻表・経路探索 (A8. core/transit.py と geo.routes).

- 路線網: 遠い行き先には鉄道の駅, 近めの行き先にはバス停. 時刻表 (始発・終電・平日と土休日).
- 経路: 時刻表どおり (始発を待つ・終電のあとは翌朝). 到着時刻を決めて, 間に合ういちばん遅い出発.
- 自転車で駅まで行けば駅に置く (駐輪代). 駅に置いた自転車で行き先まで行ける. 同じ乗り方の候補は 1 つ (一時データ).

    python tools/test_transit.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from core import engine, geo as G, store, transit as TR  # noqa: E402

G.INSTANT = False


def weekday_at(h, m=0):
    d = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.timestamp()


def main():
    random.seed(5)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("路線")
        geo = app.geo
        T = geo.transit
        net = T.net()
        home = "home:me"

        # ---- 1. 路線網: 遠い行き先には鉄道の駅, 近めにはバス停
        kinds = {ln["kind"] for ln in net["lines"]}
        assert "rail" in kinds, kinds
        far = [pid for pid in ("aquarium", "beach", "mountain", "amusement") if geo.km("station", pid) / 1.3 >= TR.RAIL_FAR]
        for pid in far:
            sid = T.station_of(pid)
            assert sid and any(sid in ln["seq"] and ln["kind"] == "rail" for ln in net["lines"]), pid
        assert all(ln["seq"][0] == "station" for ln in net["lines"])
        print("路線網: OK |", ", ".join("%s(%d駅)" % (ln["name"], len(ln["seq"])) for ln in net["lines"]))

        # ---- 2. 時刻表: 始発は早朝, 終電は深夜. 平日と土休日で本数が違うことも
        wd, hd = weekday_at(10), weekday_at(10) + (5 - datetime.fromtimestamp(weekday_at(10)).weekday()) * 86400
        tt = T.timetable("station", wd)
        assert tt["lines"] and not tt["holiday"]
        for ln in tt["lines"]:
            h0 = int(ln["first"].split(":")[0])
            assert 4 <= h0 <= 7, ln["first"]
        rail = next(ln for ln in net["lines"] if ln["kind"] == "rail")
        n_wd = len(T.departures(rail, "wd", "out"))
        n_hd = len(T.departures(rail, "hd", "out"))
        assert n_wd >= n_hd > 30, (n_wd, n_hd)
        assert T.timetable("station", hd)["holiday"]
        print("時刻表: OK | %s 平日%d本・土休日%d本, 始発 %s 終電 %s" % (rail["name"], n_wd, n_hd, tt["lines"][0]["first"], tt["lines"][0]["last"]))

        # ---- 3. 経路: 時刻表どおり. 夜中は始発を待つ
        dst = far[0] if far else "mall"
        rs = geo.routes(home, dst, wd)
        assert rs and rs[0]["key"] == "route:0" and any(lg["kind"] == "ride" for lg in rs[0]["legs"]), rs
        r0 = rs[0]
        ride = next(lg for lg in r0["legs"] if lg["kind"] == "ride")
        assert ride["t0"] >= wd and r0["fare"] > 0
        legs = r0["legs"]
        assert all(a["t1"] <= b["t0"] + 1 for a, b in zip(legs, legs[1:])), [(x["kind"], x["t0"], x["t1"]) for x in legs]
        night = geo.routes(home, dst, weekday_at(2))
        first = next(lg for lg in night[0]["legs"] if lg["kind"] == "ride")
        assert datetime.fromtimestamp(first["t0"]).hour >= 4 and "始発" in night[0]["note"], night[0]["note"]
        print("経路: OK |", " → ".join("%s %d分" % (s["label"], s["min"]) for s in geo.route_view(r0, wd)["steps"]), "| %d分・%d円" % (r0["min"], r0["fare"]))

        # ---- 4. 到着時刻を決めて: 間に合ういちばん遅い出発
        goal = weekday_at(11)
        dep, r = geo.latest_departure(home, dst, goal)
        assert r["t_arr"] <= goal and goal - dep < 4 * 3600
        later = [x for x in geo.routes(home, dst, dep + 600) if x["key"] == "route:0"]
        assert not later or later[0]["t_arr"] > goal - 60 or later[0]["t_arr"] >= r["t_arr"], (later and later[0]["t_arr"], goal)
        print("到着時刻から: OK | %sまでに着くには %s に出る" % (datetime.fromtimestamp(goal).strftime("%H:%M"), datetime.fromtimestamp(dep).strftime("%H:%M")))

        # ---- 4b. いま出発 / 始発で / 終電で (画面の経路検索)
        now_r = geo.route_search(dst, None, "now")
        assert now_r["by"] == "depart" and abs(now_r["at"] - time.time()) < 5
        fr = geo.route_search(dst, None, "first")
        fride = next(lg for lg in fr["routes"][0]["steps"] if lg["kind"] == "ride")
        assert datetime.fromtimestamp(fr["at"]).hour == TR.DAY_START and 4 <= datetime.fromtimestamp(fride["t0"]).hour <= 7, fr
        hit = geo.last_departure(home, dst, weekday_at(19))
        assert hit, "終電の経路がない"
        t_last, r_last = hit
        lride = [lg for lg in r_last["legs"] if lg["kind"] == "ride"][-1]
        assert datetime.fromtimestamp(t_last).hour in (21, 22, 23, 0) and lride["t1"] <= weekday_at(4) + 86400, datetime.fromtimestamp(t_last)
        after = [x for x in geo.routes(home, dst, t_last + 600) if x["key"] == "route:0"]
        assert not after or any(lg["t1"] > weekday_at(4) + 86400 for lg in after[0]["legs"] if lg["kind"] == "ride"), "終電のあとも同じ日に行けてしまう"
        print("始発・終電: OK | 始発 %s発 / 終電で行くなら %s までに出る" % (datetime.fromtimestamp(fride["t0"]).strftime("%H:%M"),
                                                             datetime.fromtimestamp(t_last).strftime("%H:%M")))

        # ---- 5. 自転車で駅まで (駐輪代) / 駅に置いた自転車で行き先まで
        app.items.add("bicycle", 1)
        acc = geo._ends(home, wd, "access", False)
        assert any(v[2] == "bike" and v[1] == TR.BIKE_PARK for v in acc.values()), "自転車で駅へ行く候補がない"
        geo.rec().setdefault("veh", {})["bicycle"] = "station"
        eg = geo._ends("mall", wd, "egress", False)
        assert eg.get("station") and (eg["station"][2] in ("bike", "walk")), eg.get("station")
        bike_route = None
        geo.rec()["veh"]["bicycle"] = home
        for t in (wd, wd + 1800, wd + 3600):
            bike_route = next((x for x in geo.routes(home, dst, t) if any(lg["kind"] == "bike" for lg in x["legs"])), None)
            if bike_route:
                break
        if bike_route:
            lg = geo.route_leg(bike_route, bike_route["legs"][0]["t0"])
            geo.used(lg, dst)
            parked = next(x["to"] for x in bike_route["legs"] if x["kind"] == "bike")
            assert geo.veh_at("bicycle") == parked and parked.startswith("st") or parked == "station", parked
            print("自転車で駅へ: OK | %sに置いた" % app.places.label(parked))
        else:
            print("自転車で駅へ: (この町では歩くほうが早い. 候補があることだけ確かめた)")

        # ---- 6. 同じ乗り方の候補は 1 つ. タクシーの候補はタクシーだけより安い
        sigs = [tuple((lg["kind"], lg.get("line")) for lg in x["legs"] if lg["kind"] != "wait") for x in geo.routes(home, dst, wd)]
        assert len(sigs) == len(set(sigs))
        tx = next((x for x in geo.routes(home, dst, wd) if x["key"] == "route:2"), None)
        if tx:
            assert tx["fare"] < geo._taxi(geo.km(home, dst), wd)[1]

        # ---- 7. 昼間なら, いつ出ても経路がある (1.6.0 で直した): 乗り継ぎの悪い数分 (バスが出た直後など) に,
        # 降りる駅にも歩いて着くほうが早くなって電車・バスの着き方が消え, 経路が 0 件になっていた (20 分おきに数分ずつ)
        # 歩くより遅くても, 電車・バスの経路は出す. 行き先を変えて, いくつかの駅で 2 分おきに確かめる
        day0 = datetime.fromtimestamp(wd).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        gaps = {}
        for to in ("mall", "aquarium", dst):
            g = [m for m in range(10 * 60, 16 * 60, 2) if geo.options(home, to, day0 + m * 60)["modes"].get("transit")
                 and not geo.routes(home, to, day0 + m * 60)]
            if g:
                gaps[to] = ["%02d:%02d" % (m // 60, m % 60) for m in g[:5]]
        assert not gaps, gaps
        print("昼間はいつでも経路がある: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
