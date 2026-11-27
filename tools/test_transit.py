"""路線と時刻表・経路探索 (A8. core/transit.py と geo.routes).

- 路線網: 遠い行き先には鉄道の駅, 近めの行き先にはバス停. 時刻表 (始発・終電・平日と土休日).
- 経路: 時刻表どおり (始発を待つ・終電のあとは翌朝). 到着時刻を決めて, 間に合ういちばん遅い出発.
- 自転車で駅まで行けば駅に置く (駐輪代). 駅に置いた自転車で行き先まで行ける. 同じ乗り方の候補は 1 つ (一時データ).

    python tools/test_transit.py
"""
import math
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


def upgrade(geo, T, v4_old_part):
    """版 3 のセーブ: 路線網を作ったあとに遠い相手の家が増えていても, 版 4 へ上げるとき いまの駅・路線はそのまま (土台にして足す).
    確かめたあと, もとの路線網に戻す."""
    import copy
    r = geo.rec()
    keep_net, keep_pts = copy.deepcopy(r["net"]), copy.deepcopy(r["pts"])
    try:
        old3 = copy.deepcopy(v4_old_part)
        old3.pop("roads", None)
        old3["v"] = 3
        old3["stations"]["st:fake:old"] = {"name": "旧終点駅", "xy": [20.0, 0.0], "for": None}   # 作り直しでは出てこない駅 (いまのセーブにだけある)
        old3["lines"][0]["seq"].append("st:fake:old")
        r["pts"]["home:zzfar"] = {"xy": [-14.0, 9.0], "acc": 0.5}       # 版 3 を作ったあとに増えた遠い家
        r["net"] = old3
        T._conn.clear(); T._stops.clear(); T._inc.clear(); T._csa.clear(); T.roads.clear()   # noqa: E702
        net = T.net()
        assert net["v"] == TR.NET_V and net["roads"]
        for sid, v in old3["stations"].items():
            assert net["stations"].get(sid, {}).get("name") == v["name"] and net["stations"][sid]["xy"] == v["xy"], sid
        for ol in old3["lines"]:
            nl = next(x for x in net["lines"] if x["id"] == ol["id"])
            it = iter(nl["seq"])
            assert all(s in it for s in ol["seq"]), ol["id"]
        names = [v["name"] for v in net["stations"].values()]
        assert len(names) == len(set(names)), "駅の名前が重ならない"
        assert any(ln.get("rapid") for ln in net["lines"]) and any(ln.get("night") for ln in net["lines"])
        print("版 3 からの移行: OK | 増えた場所があっても旧駅 %d がそのまま, 足した路線 %d" % (len(old3["stations"]), len(net["lines"]) - len(old3["lines"])))
    finally:
        r["net"], r["pts"] = keep_net, keep_pts
        T._conn.clear(); T._stops.clear(); T._inc.clear(); T._csa.clear(); T.roads.clear()   # noqa: E702


def roads_lines(app, geo, T, home):
    """A11: 道 (川と橋・踏切・大通りの混み) と, 増えた路線 (環状線・支線・快速・深夜バス), バスの朝夕, 混雑."""
    from core import roads as RD
    net = T.net()
    st = net["stations"]
    lines = net["lines"]
    wd8, wd13 = weekday_at(8, 10), weekday_at(13)
    hd13 = wd13 + (5 - datetime.fromtimestamp(wd13).weekday()) * 86400
    R = T.roads

    # ---- 作り直しても旧駅 (NET_V 3 の作り方) は残る: 同じ id・名前. 旧路線の並びは, 乗り換え駅が差し込まれただけ
    ext = T._extend
    T._extend = lambda *a, **k: None
    try:
        old = T._build()
    finally:
        T._extend = ext
    for sid, v in old["stations"].items():
        assert sid in st and st[sid]["name"] == v["name"] and st[sid]["xy"] == v["xy"], sid
    for ol in old["lines"]:
        nl = next(x for x in lines if x["id"] == ol["id"])
        it = iter(nl["seq"])
        assert all(s in it for s in ol["seq"]), ol["id"]                    # 部分列
        assert all(s in ol["seq"] or s.startswith("st:ring:") for s in nl["seq"]), ol["id"]
    assert [ln["id"] for ln in lines[:len(old["lines"])]] == [ln["id"] for ln in old["lines"]], "旧路線が先 (便の番号がずれない)"
    print("作り直し: OK | 旧駅 %d・旧路線 %d がそのまま" % (len(old["stations"]), len(old["lines"])))
    upgrade(geo, T, old)

    # ---- 川と橋: 川を挟めば橋を通る (直線 × 1.3 より長い). 同じ側なら直線 × 1.3
    rv = net["roads"]["river"]
    nx, ny = -rv["u"][1], rv["u"][0]
    bs = net["roads"]["bridges"]
    i = min(range(len(bs) - 1), key=lambda k: abs(bs[k]))
    mid = (bs[i] + bs[i + 1]) / 2.0
    c = R.bridge_xy(mid)
    a, b = [c[0] + nx * 0.3, c[1] + ny * 0.3], [c[0] - nx * 0.3, c[1] - ny * 0.3]
    p = R.path(a, b)
    straight = 0.6 * RD.ROAD
    assert R.side(a) != R.side(b) and p["bridge"] and p["km"] > straight + 0.5, p
    a2 = [c[0] + nx * 0.3 + rv["u"][0] * 0.4, c[1] + ny * 0.3 + rv["u"][1] * 0.4]
    q = R.path(a, a2)
    assert not q["bridge"] and abs(q["km"] - 0.4 * RD.ROAD) < 1e-3, q
    print("川と橋: OK | 向こう岸まで 0.6 km の所が 道のり %.1f km（橋 %.1f km ごと）" % (p["km"], bs[i + 1] - bs[i]))

    # ---- 踏切: 線路を駅から離れた所で横切れば待つ (平日朝夕は長い). 駅のそばは自由通路で待たない
    rail = next(ln for ln in lines if ln["kind"] == "rail" and not ln.get("of") and not ln.get("loop"))
    s0, s1 = next((x, y) for x, y in zip(rail["seq"], rail["seq"][1:]) if math.dist(st[x]["xy"], st[y]["xy"]) > 1.5)
    pa, pb = st[s0]["xy"], st[s1]["xy"]
    L = math.dist(pa, pb)
    m = [(pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2]
    ux, uy = (pb[0] - pa[0]) / L, (pb[1] - pa[1]) / L
    p1 = R.path([m[0] - uy * 0.2, m[1] + ux * 0.2], [m[0] + uy * 0.2, m[1] - ux * 0.2])
    assert p1["cross"] >= 1, p1
    near = [pa[0] + ux * 0.1, pa[1] + uy * 0.1]
    p2 = R.path([near[0] - uy * 0.1, near[1] + ux * 0.1], [near[0] + uy * 0.1, near[1] - ux * 0.1])
    assert p2["cross"] == 0, p2
    assert geo.cross_min(p1, wd8) > geo.cross_min(p1, wd13) > 0 and geo.cross_min(p1, hd13) == geo.cross_min(p1, wd13)
    assert R.cross_wait(3.0) == 0
    print("踏切: OK | 平日朝 %.0f分・昼 %.0f分（駅のそばは 0）" % (geo.cross_min(p1, wd8), geo.cross_min(p1, wd13)))

    # ---- 車: 平日の朝夕は大通りほど混む. 深夜は空いている. 土休日の朝は平日ほど混まない
    ra = math.radians(net["roads"]["radials"][0])                 # 大通り (放射) 沿いに 0.5 km → 9 km
    pf = R.path([0.5 * math.cos(ra), 0.5 * math.sin(ra)], [9.0 * math.cos(ra), 9.0 * math.sin(ra)])
    assert pf["art"] > 0.3, pf
    d8, d13, dh8 = geo.drive(pf, wd8), geo.drive(pf, wd13), geo.drive(pf, hd13 - 5 * 3600 + 600)
    d23 = geo.drive(pf, wd13 + 10 * 3600)
    assert d8 > dh8 > d13 > d23, (d8, dh8, d13, d23)
    print("車の混み: OK | 平日朝 %.0f分・土休日朝 %.0f分・昼 %.0f分・夜中 %.0f分" % (d8, dh8, d13, d23))

    # ---- 環状線: 一周 (始めと終わりが同じ駅). 放射の鉄道と乗り換え駅を共有. 外回り・内回り. 一周の終わりをまたぐ区間も進められる
    ring = next((ln for ln in lines if ln.get("loop")), None)
    radial = [ln for ln in lines if ln["kind"] == "rail" and not ln.get("of") and not ln.get("loop") and not ln["id"].startswith("branch")]
    if len(radial) >= 2:
        assert ring and ring["seq"][0] == ring["seq"][-1], ring
        shared = [s for s in set(ring["seq"]) if any(s in ln["seq"] for ln in radial)]
        assert len(shared) >= 2, shared
        tt = T.timetable(ring["seq"][1], wd13)
        labs = {x["dir_label"] for x in tt["lines"] if x["line"] == ring["id"]}
        assert labs == {"外回り", "内回り"}, labs
        # 一周の終わりをまたぐ: 終わりの 1 つ手前の駅 → 2 つ目の駅 (外回りなら 始め=終わりの駅 を通る)
        a_, b_ = ring["seq"][-2], ring["seq"][1]
        rs = geo.routes(a_, b_, wd13)
        assert rs, "環状線の経路"
        rides = [lg for lg in rs[0]["legs"] if lg["kind"] == "ride"]
        assert rides and rides[0]["line"] == ring["id"], [lg.get("line") for lg in rides]
        r2 = geo.ride_out(rs[0], b_, wd13)
        assert r2["legs"] and r2["t_arr"] >= wd13, r2
        lg = rides[0]
        tr = {"legs": rs[0]["legs"], "arr": rs[0]["t_arr"], "t0": wd13, "from": a_, "to": b_, "how": "transit"}
        here = geo.midway((lg["t0"] + lg["t1"]) / 2, trip=tr)
        assert here in ring["seq"], here
        print("環状線: OK | %d駅・乗り換え %d駅, %s→%s %d分" % (len(ring["seq"]) - 1, len(shared), st[a_]["name"], st[b_]["name"], rs[0]["min"]))

    # ---- 支線: 鉄道の駅から分かれる
    br = next((ln for ln in lines if ln["id"].startswith("branch")), None)
    if br:
        assert any(br["seq"][0] in ln["seq"] for ln in lines if ln is not br and ln["kind"] == "rail")
        assert T.departures(br, "wd", "out"), br
        print("支線: OK | %s（%s から %d駅）" % (br["name"], st[br["seq"][0]]["name"], len(br["seq"]) - 1))

    # ---- 快速: 昼だけ. 止まる駅は元の路線の一部. 元の路線より速い. 遅れは元の路線の出来事で
    rp = [ln for ln in lines if ln.get("rapid")]
    assert rp, "快速"
    for ln in rp:
        base = T.line(ln["of"])
        assert set(ln["seq"]) < set(base["seq"]) and ln["seq"][0] == base["seq"][0] and ln["seq"][-1] == base["seq"][-1]
        dep = T.departures(ln, "wd", "out")
        assert dep and min(dep) >= 600 and max(dep) <= 960, (min(dep), max(dep))
        assert sum(T.run_min(ln)) < sum(T.run_min(base)), ln["id"]
    day = TR.service_day(wd13)
    inc = [{"id": "x", "line": rp[0]["of"], "s": 700, "e": 760, "d": 20, "dirs": ("out", "in"), "cause": "t"}]
    late = [s for lid, dr, s in T.trips(day, inc) if lid == rp[0]["id"] and 700 <= s[0][1] <= 760]
    plain = [s for lid, dr, s in T.trips(day) if lid == rp[0]["id"] and 700 <= s[0][1] <= 760]
    assert late and late[0][-1][1] - plain[0][-1][1] >= 19, "快速も元の路線の遅れで遅れる"
    at8 = [r for r in geo.routes("station", rp[0]["seq"][-1], wd8)]
    assert all(lg.get("line") != rp[0]["id"] for r in at8 for lg in r["legs"]), "朝は快速が無い"
    print("快速: OK | %s %d分（各駅 %d分）" % (rp[0]["name"], sum(T.run_min(rp[0])), sum(T.run_min(T.line(rp[0]["of"])))))

    # ---- 深夜バス: 平日の駅前発だけ, 23:40〜翌 0:50. 運賃 2 倍
    nb = next(ln for ln in lines if ln.get("night"))
    dep = T.departures(nb, "wd", "out")
    assert dep and min(dep) >= 1420 and max(dep) <= 1490 and not T.departures(nb, "wd", "in") and not T.departures(nb, "hd", "out")
    leg = {"kind": "ride", "line": nb["id"], "from": nb["seq"][0], "to": nb["seq"][1]}
    assert geo._route_fare([leg]) == 2 * TR.BUS_FARE
    late_t = weekday_at(23, 50) + 45 * 60              # 平日の翌 0:35 (電車の終電のあと)
    rs = geo.routes("station", nb["seq"][-1], late_t)
    assert any(lg.get("line") == nb["id"] for r in rs for lg in r["legs"]), [[lg.get("line") for lg in r["legs"]] for r in rs]
    print("深夜バス: OK | %s〜%s・%d円" % (TR._hm(min(dep)), TR._hm(max(dep)), 2 * TR.BUS_FARE))

    # ---- バス: 平日の朝夕は遅い, 深夜は速い
    bus = next(ln for ln in lines if ln["kind"] == "bus" and not ln.get("of") and len(ln["seq"]) >= 3)
    tr = {(dr, s[0][1]): s[-1][1] - s[0][1] for lid, dr, s in T.trips(day) if lid == bus["id"]}
    m8 = next(v for (dr, d0), v in tr.items() if 7 * 60 <= d0 < 9 * 60)
    m13 = next(v for (dr, d0), v in tr.items() if 12 * 60 <= d0 < 15 * 60)
    assert m8 > m13 * 1.3, (m8, m13)
    print("バスの朝夕: OK | 朝 %.0f分・昼 %.0f分" % (m8, m13))

    # ---- 混雑: 平日朝夕の途中の駅からは立つ (読めない・疲れる). 始発駅からは座れる. 昼・土休日は座れる
    trips = [(lid, dr, s) for lid, dr, s in T.trips(day) if T.line(lid)["kind"] == "rail" and not T.line(lid).get("of")]
    base = T.day_base(day)
    lid, dr, s = next(x for x in trips if 7.5 * 60 <= x[2][1][1] < 9 * 60)
    ti = next(i for i, x in enumerate(T.trips(day)) if x[0] == lid and x[1] == dr and x[2] == s)
    trip = "%s:%s:%s:%d" % (day.isoformat(), lid, dr, ti)
    mid_lg = {"kind": "ride", "line": lid, "trip": trip, "from": s[1][0], "to": s[2][0], "t0": base + s[1][1] * 60, "t1": base + s[2][1] * 60}
    first_lg = dict(mid_lg, **{"from": s[0][0], "t0": base + s[0][1] * 60})
    assert T.crowded(mid_lg) and not T.crowded(first_lg)
    lid2, dr2, s2 = next(x for x in trips if 12 * 60 <= x[2][1][1] < 14 * 60)
    ti2 = next(i for i, x in enumerate(T.trips(day)) if x[0] == lid2 and x[1] == dr2 and x[2] == s2)
    noon = {"kind": "ride", "line": lid2, "trip": "%s:%s:%s:%d" % (day.isoformat(), lid2, dr2, ti2), "from": s2[1][0], "to": s2[2][0],
            "t0": base + s2[1][1] * 60, "t1": base + s2[2][1] * 60}
    assert not T.crowded(noon)
    lg = {"how": "transit", "min": 30, "legs": [dict(mid_lg, crowd=True)]}
    segs = geo.segs(lg, home, "station")
    assert segs[0][0] == "stand" and "立って" in segs[0][2], segs
    trv = {"segs": segs, "t0": mid_lg["t0"], "arr": mid_lg["t1"]}
    assert geo.seated_h(trv, mid_lg["t0"], mid_lg["t1"]) == 0
    seat = {"segs": geo.segs({"how": "transit", "min": 30, "legs": [dict(mid_lg, crowd=False)]}, home, "station"), "t0": mid_lg["t0"], "arr": mid_lg["t1"]}
    assert geo.seated_h(seat, mid_lg["t0"], mid_lg["t1"]) > 0
    assert geo.body_cost(lg, home, "station")[1] > geo.body_cost({"how": "transit", "min": 30, "legs": [dict(mid_lg, crowd=False)]}, home, "station")[1]
    rs = geo.routes(rail["seq"][-2], "station", wd8)          # 朝, 途中の駅から都心へ (始発駅ではない)
    assert rs and any(lg.get("crowd") for lg in rs[0]["legs"]), [(lg.get("line"), lg.get("crowd")) for lg in rs[0]["legs"]]
    rs0 = geo.routes("station", rail["seq"][-1], wd8)         # 中央駅は放射の路線の始発駅: 座れる
    assert rs0 and not any(lg.get("crowd") for lg in rs0[0]["legs"] if lg.get("from") == "station"), rs0[0]["legs"]
    v = geo.route_view(rs[0], wd8)
    assert any(x["crowd"] for x in v["steps"]), v["steps"]
    print("混雑: OK | 平日朝の途中駅から立つ（始発駅・昼は座れる）, 立っている間は読めない")

    # ---- 地図: 道 (川・橋・大通り) と, 重なる路線 (快速・深夜バス) の印
    mv = T.map_view()
    assert mv["roads"]["river"] and mv["roads"]["bridges"] and mv["roads"]["radials"] and mv["roads"]["ring"]
    assert {ln["id"] for ln in mv["lines"] if ln["over"]} == {ln["id"] for ln in lines if ln.get("of")}
    print("地図: OK")


def no_detour(app):
    """F21: 歩いて行き先に着ける駅・停留所からは乗りに行かない. 以前は, 自転車で行き先の停留所まで行き, バスで 1 つ離れて
    歩いて戻る経路ができ, 自転車が行き先の停留所 (モール前) に置かれていた. 町をいくつか作り, 全行き先 × 時刻で確かめる."""
    bad, n = [], 0
    for k in range(6):
        random.seed(100 + k)
        app.create_world("寄り道%d" % k)
        geo = app.geo
        app.items.add("bicycle", 1)
        home = "home:me"
        dests = [pid for pid in app.places.table() if pid != home]
        for h in (10, 17):
            t = weekday_at(h, 5)
            for b in dests:
                geo.rec()["veh"] = {"bicycle": home}
                near = {s for s, e in geo._ends(b, t, "egress", False).items() if e[2] == "walk"}
                for r in geo.routes(home, b, t):
                    n += 1
                    rides = [lg for lg in r["legs"] if lg["kind"] == "ride"]
                    if rides and rides[0]["from"] in near:
                        bad.append((k, h, b, [(lg["kind"], lg["to"]) for lg in r["legs"] if lg["kind"] != "wait"]))
    assert not bad, bad[:5]
    print("行き先の停留所から乗りに行かない: OK | %d 経路" % n)


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
        far = [pid for pid in ("aquarium", "beach", "mountain", "amusement") if math.hypot(*geo.pt(pid)["xy"]) >= TR.RAIL_FAR]
        for pid in far:
            sid = T.station_of(pid)
            assert sid and any(sid in ln["seq"] and ln["kind"] == "rail" for ln in net["lines"]), pid
        assert all(ln["seq"][0] == "station" for ln in net["lines"] if not (ln.get("loop") or ln["id"].startswith("branch")))
        print("路線網: OK |", ", ".join("%s(%d駅)" % (ln["name"], len(ln["seq"])) for ln in net["lines"]))

        # ---- 2. 時刻表: 始発は早朝, 終電は深夜. 平日と土休日で本数が違うことも
        wd, hd = weekday_at(10), weekday_at(10) + (5 - datetime.fromtimestamp(weekday_at(10)).weekday()) * 86400
        tt = T.timetable("station", wd)
        assert tt["lines"] and not tt["holiday"]
        for ln in tt["lines"]:
            if T.line(ln["line"]).get("of"):           # 快速 (昼だけ)・深夜バス は別に確かめる (roads_lines)
                continue
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
            assert tx["fare"] < geo._taxi(geo.road(home, dst), wd)[1]

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
        roads_lines(app, geo, T, home)
        no_detour(app)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
