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


def contiguous(legs):
    return all(a["t1"] <= b["t0"] + 1 for a, b in zip(legs, legs[1:]))


def delays(app, geo, T, home, dst, wd):
    """A11 段 1: 遅れは路線・日ごとの出来事. 調べるときは分かっている遅れだけ見込む. 実際の移動は本当の遅れで,
    乗り継ぎを逃せばその駅から探し直す. 乗り過ごせば次の駅で降りて戻る."""
    day = TR.service_day(wd)
    base = T.day_base(day)
    mod = lambda t: (t - base) / 60.0   # noqa: E731  運行日の 0 時からの分

    # ---- 8a. 出来事はワールド・路線・日で決まる (開き直し・再起動で同じ). 倍率 0 なら起きない. 朝夕に多い
    inc = T.incidents(day)
    assert TR.Transit(geo).incidents(day) == inc
    lines = T.net()["lines"]
    n_all = sum(len(T.incidents(day + timedelta(days=k))) for k in range(60))
    assert 0.1 * 60 * len(lines) < n_all < 0.7 * 60 * len(lines), (n_all, len(lines))
    ev = G.EV_DELAY
    G.EV_DELAY = 0.0
    assert T.incidents(day) == [] and T.known(day, "all") == []
    G.EV_DELAY = ev
    for k in range(60):
        for x in T.incidents(day + timedelta(days=k)):
            assert x["s"] < x["e"] and 5 <= x["d"] <= 30 and x["dirs"] and x["cause"], x
    print("遅れの出来事: OK | 60 日で %d 件（%d 路線）" % (n_all, len(lines)))

    # 以下は出来事を決め打ちにして確かめる
    real = T.incidents
    fake = []
    T.incidents = lambda d: [x for x in fake if x.get("day", day) == d]
    T._conn.clear()
    T._stops.clear()
    T._csa.clear()
    try:
        # ---- 8b. 分かっている遅れ: 始まる前は知らない. 遅れた便は, その駅から先が遅れる
        rail = next(ln for ln in lines if ln["kind"] == "rail")
        fake[:] = [{"id": "t1", "line": rail["id"], "s": mod(wd) + 30, "e": mod(wd) + 60, "d": 12, "dirs": ("out", "in"), "cause": "テスト"}]
        assert T.known(day, wd) == [] and len(T.known(day, wd + 31 * 60)) == 1 and len(T.known(day, "all")) == 1
        conns = T.connections(day, None)
        trip = next(c[4] for c in conns if c[5] == rail["id"] and c[2] == "station" and wd + 35 * 60 <= c[0] <= wd + 50 * 60)
        plan, real_ = T.trip_stops(trip, None), T.trip_stops(trip, "all")
        assert [s for s, _ in plan] == [s for s, _ in real_]
        assert all(abs((b - a) - 12 * 60) < 1 for (_, a), (_, b) in zip(plan, real_)), (plan, real_)
        early = next(c[4] for c in conns if c[5] == rail["id"] and c[2] == "station" and c[0] < wd)
        assert T.trip_stops(early, None) == T.trip_stops(early, "all")          # 出来事より前に出た便は遅れない
        dn = T.delays_now(wd + 40 * 60)
        assert [x["line"] for x in dn] == [rail["id"]] and dn[0]["d"] == 12 and T.delays_now(wd) == []
        assert T.delays_now(wd + (60 + 12 + 1) * 60) == []                       # 出来事が終わって遅れが戻れば消える
        print("分かっている遅れ: OK | %s 12分遅れ（始まる前は経路に出ない）" % rail["name"])

        # ---- 8c. 経路を調べる: 分かっている遅れを見込んで, 遅れた便の到着で並べる. 画面に「○分遅れ」
        t_q = wd + 40 * 60
        on = [r for r in geo.routes("station", rail["seq"][-1], t_q, known=t_q) if r["key"] == "route:0"][0]
        off = [r for r in geo.routes("station", rail["seq"][-1], t_q) if r["key"] == "route:0"][0]
        # 見込んだ経路の便の時刻 = 遅れを効かせた時刻表 (遅れた便に乗れて, 時刻表どおりより早く着くこともある)
        for y, kn in ((on, t_q), (off, None)):
            for x in y["legs"]:
                if x["kind"] == "ride":
                    st = dict(T.trip_stops(x["trip"], kn))
                    assert abs(st[x["from"]] - x["t0"]) < 1 and abs(st[x["to"]] - x["t1"]) < 1 and x["t0"] >= t_q, (x, st)
        steps = [s for s in geo.route_view(on, t_q)["steps"] if s["kind"] == "ride"]
        for s, x in zip(steps, [x for x in on["legs"] if x["kind"] == "ride"]):
            plan = dict(T.trip_stops(x["trip"], None))[x["from"]]
            assert s["late"] == max(0, round((x["t0"] - plan) / 60)), (s, plan)
        assert any(s["late"] == 12 for s in steps) or not any(x["line"] == rail["id"] for x in on["legs"] if x["kind"] == "ride"), steps
        rs = geo.route_search(rail["seq"][-1], t_q, "depart", frm="station")
        assert "delays" in rs
        print("遅れを見込んだ経路: OK | 時刻表どおり %s着 → 見込み %s着" % (
            datetime.fromtimestamp(off["t_arr"]).strftime("%H:%M"), datetime.fromtimestamp(on["t_arr"]).strftime("%H:%M")))

        # ---- 8d. 乗り継ぎを逃す: 乗った便が (出たあとで) 遅れ, 中央駅で乗り継ぐ便に間に合わない → 中央駅から探し直す
        other = next((ln for ln in lines if ln["id"] != rail["id"] and len(ln["seq"]) >= 3), None)
        if other:
            conns = T.connections(day, None)
            a_trip = next(c for c in conns if c[5] == rail["id"] and c[3] == "station" and c[0] >= wd + 90 * 60)
            a_arr = a_trip[1]
            b_conn = next(c for c in conns if c[5] == other["id"] and c[2] == "station" and c[0] >= a_arr + TR.TRANSFER_BUF * 60)
            goal = b_conn[3]
            ride_a = {"kind": "ride", "from": a_trip[2], "to": "station", "t0": a_trip[0], "t1": a_arr, "line": rail["id"], "trip": a_trip[4]}
            ride_b = {"kind": "ride", "from": "station", "to": goal, "t0": b_conn[0], "t1": b_conn[1], "line": other["id"], "trip": b_conn[4]}
            r = {"key": "route:0", "label": "おまかせ", "legs": [ride_a, ride_b], "t_arr": b_conn[1], "min": 1, "fare": 0, "transfers": 1, "note": ""}
            t0 = a_trip[0] - 60
            delay = (b_conn[0] - a_arr) / 60.0 + 10                           # 乗り継ぐ便より 10 分あと
            fake[:] = [{"id": "t2", "line": rail["id"], "s": mod(a_trip[0]) - 0.5, "e": mod(a_trip[0]) + 5, "d": round(delay),
                        "dirs": ("out", "in"), "cause": "テスト"}]
            assert T.known(day, t0) == []                                      # 出るときはまだ知らない
            ev = G.EV_DOZE
            G.EV_DOZE = 0.0
            got = geo.ride_out(r, goal, t0)
            G.EV_DOZE = ev
            assert any("間に合わず" in e for e in got["events"]), got["events"]
            assert any("遅れた" in e for e in got["events"]), got["events"]
            assert contiguous(got["legs"]) and got["legs"][-1]["to"] == goal, got["legs"]
            assert next(x for x in got["legs"] if x["kind"] == "ride")["t1"] >= a_arr + (delay - 1) * 60
            assert got["t_arr"] > b_conn[1] and got["t_arr"] == got["legs"][-1]["t1"]
            assert all(x["trip"] != b_conn[4] for x in got["legs"] if x["kind"] == "ride")      # 逃した便には乗っていない
            print("乗り継ぎを逃す: OK |", "。".join(got["events"]), "| %s着（予定 %s）" % (
                datetime.fromtimestamp(got["t_arr"]).strftime("%H:%M"), datetime.fromtimestamp(b_conn[1]).strftime("%H:%M")))

            # 遅れが小さく, 乗り継ぎに間に合う: そのまま乗る (遅れの文だけ)
            fake[:] = [dict(fake[0], id="t2b", d=max(1, round((b_conn[0] - a_arr) / 60.0 - TR.TRANSFER_BUF - 1)))]   # id ごとに中身は決まる (キャッシュの鍵)
            if fake[0]["d"] >= 3:
                got = geo.ride_out(r, goal, t0)
                assert not any("間に合わず" in e for e in got["events"]) and got["t_arr"] == b_conn[1], got["events"]

        # ---- 8e. 乗り過ごし (疲れているとき): 次の駅で降り, そこから戻る
        fake[:] = []
        conns = T.connections(day, None)
        c = next(c for c in conns if c[5] == rail["id"] and c[2] == "station" and c[0] >= wd + 60 * 60)
        stops = T.trip_stops(c[4], None)
        names = [s for s, _ in stops]
        if len(names) >= 3:
            to = names[1]
            r = {"key": "route:0", "label": "おまかせ", "legs": [{"kind": "ride", "from": "station", "to": to, "t0": c[0], "t1": stops[1][1],
                                                               "line": rail["id"], "trip": c[4]}],
                 "t_arr": stops[1][1], "min": 1, "fare": 0, "transfers": 0, "note": ""}
            ev = G.EV_DOZE
            G.EV_DOZE = 1.0
            app.life.stamina = lambda: 10
            try:
                got = geo.ride_out(r, to, c[0] - 60)
            finally:
                G.EV_DOZE = ev
                del app.life.stamina
            assert any("乗り過ごし" in e for e in got["events"]), got["events"]
            assert any(x["kind"] == "ride" and x["to"] == names[2] for x in got["legs"]), got["legs"]
            assert got["legs"][-1]["to"] == to and contiguous(got["legs"]) and got["t_arr"] > stops[1][1]
            print("乗り過ごし: OK |", "。".join(got["events"]), "| %s着（予定 %s）" % (
                datetime.fromtimestamp(got["t_arr"]).strftime("%H:%M"), datetime.fromtimestamp(stops[1][1]).strftime("%H:%M")))

        # ---- 8f. 実際に出かける (geo.leg. 揺らぎあり): 区間はつながり, 着く時刻 = 最後の区間の終わり. 遅れは文に
        fake[:] = [{"id": "t3", "line": ln["id"], "s": 0, "e": 27 * 60, "d": 15, "dirs": ("out", "in"), "cause": "テスト"} for ln in lines]
        T._csa.clear()
        lg = geo.leg(home, dst, "transit", wd)
        assert contiguous(lg["legs"]) and abs(wd + lg["min"] * 60 - lg["legs"][-1]["t1"]) < 2, lg
        assert "遅れ" in lg["note"] or not any(x["kind"] == "ride" for x in lg["legs"]), lg["note"]
        print("遅れの中を出かける: OK |", lg["note"])
    finally:
        T.incidents = real
        T._conn.clear()
        T._stops.clear()
        T._csa.clear()


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

        delays(app, geo, T, home, dst, wd)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
