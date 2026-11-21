"""同じ種類の店を複数 (残件 A10) の確認 (一時データ, 画像生成なし).
- 1 店目は種類の id のまま, 2 店目以降は "<種類>:<番号>". 名前・営業時間・位置の決まり・値段・置いていない品・人の多さが店ごと
- 種類で引く表 (品ぞろえ・メニュー・話題・業種・買い物の長さ・好きな所・勤め先の絵) は 2 店目以降も引ける
- 位置: 店ごとの決まり (駅前店は駅のそば・住宅街店は家のそば). 以前のワールドの位置はそのまま, 足した店だけ決まる
- 「いちばん近い○○」(near:種類): 行動パターン・予定で選べ, 出るときに近い開いている店に決まる
- 勤め先: 新しく決める人は店ごと (別の乱数なので, 型・休み・時間帯はいままでと同じ)

    python tools/test_branches.py
"""
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import appoint, body, engine, geo, items, lifetype, offline, places, rumor, solo, store, topics  # noqa: E402

geo.INSTANT = True


def ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").timestamp()


def main():
    random.seed(71)
    # ---- 1. 表
    P = places.PLACES
    for bid, b in places.BRANCHES.items():
        k = bid.split(":")[0]
        assert bid in P and places.kind_of(bid) == k and places.kind_of(k) == k, bid
        assert P[bid]["label"] != P[k]["label"] and places.kind_label(bid) == places.kind_label(k), (P[bid]["label"], P[k]["label"])
        assert P[bid]["does"] == P[k]["does"] and P[bid]["group"] == P[k]["group"]
        assert bid in places.OUT_PLACES and bid in places.ROUTINE_OUT
        for tbl in (topics.PLACE_TAGS, rumor.PLACE_SECTOR, solo.SHOP_BASE, lifetype.SHOP_POS):
            assert (k in tbl) == (bid in tbl) and tbl.get(bid) == tbl.get(k), (bid, tbl.get(bid))
        assert any(bid in v for v in appoint.LIKE_PLACES.values()) == any(k in v for v in appoint.LIKE_PLACES.values()), bid
        assert places.solo_kind(bid) == places.solo_kind(k)
        # 並び: 2 店目以降は 1 店目のすぐあと
        order = list(P)
        assert order.index(bid) > order.index(k) and all(places.kind_of(x) == k for x in order[order.index(k):order.index(bid) + 1])
    assert places.kind_of("near:cafe") == "cafe" and places.kind_of("home:me") == "home:me" and places.kind_of("park") == "park"
    assert places.branches("supermarket") == ["supermarket", "supermarket:2"] and places.branches("park") == ["park"]
    assert places.near_label("near:supermarket") == "いちばん近いスーパー"
    assert "（" in P["supermarket"]["label"] and P["supermarket"]["label"].startswith("スーパー")
    assert places.from_location("スーパー") == "supermarket", "以前の場所の名前は 1 店目"
    # 営業時間: 店ごと (無ければ種類と同じ)
    wed_noon, mon_noon = datetime(2026, 10, 14, 12), datetime(2026, 10, 12, 12)
    assert not places.open_state("cafe:2", wed_noon)["open"] and places.open_state("cafe", wed_noon)["open"], "住宅街のカフェは水曜休み"
    assert places.open_state("cafe:2", mon_noon)["open"] and not places.open_state("cafe", mon_noon)["open"], "駅前のカフェは月曜休み"
    late = datetime(2026, 10, 12, 22, 30)
    assert places.open_state("supermarket:2", late)["open"] and not places.open_state("supermarket", late)["open"], "駅前のスーパーは遅くまで"
    assert places.hours_label("convenience:2") == "24時間" and places.hours_label("convenience:3") != "24時間"
    # 人の多さ: 駅前店は多め・住宅街店は少なめ
    assert P["convenience:2"]["crowd"]["noon"] > P["convenience"]["crowd"]["noon"] > P["convenience:3"]["crowd"]["noon"]
    # 品ぞろえ・値段
    rice, bread, med = items.CATALOG["rice"], items.CATALOG["bread"], items.CATALOG["cold_medicine"]
    assert items.sold_at(rice, "supermarket") and not items.sold_at(rice, "supermarket:2"), "駅前の小さなスーパーにお米は無い"
    assert items.sold_at(bread, "supermarket:2") and items.sold_at(med, "convenience") and not items.sold_at(med, "convenience:3")
    assert not items.sold_at(bread, "park")
    assert places.price_rate("supermarket:2") > 1.0 > places.price_rate("drugstore:2") and places.price_rate("supermarket") == 1.0
    print("tables: OK")

    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("店")
        G, I, B, O = app.geo, app.items, app.body, app.offline
        ps = app.life.player_state()
        ps["money"] = 200000

        # ---- 2. メニューの値段は店ごと
        m1 = {x["id"]: x["price"] for x in B.menu("cafe", ts("2026-10-14 12:00"))}
        m2 = {x["id"]: x["price"] for x in B.menu("cafe:2", ts("2026-10-12 12:00"))}
        assert m1 and set(m1) == set(m2) and all(m2[k] < m1[k] for k in m1), (m1, m2)
        assert B.menu("cafe:2", ts("2026-10-14 12:00")) == [], "定休日は食べられない"
        assert "convenience:2" in body.BUY_PLACES and "cafe:2" in body.EAT_OUT_PLACES
        print("menu: OK")

        # ---- 3. 位置: 店ごとの決まり. 以前のワールドの位置はそのまま, 足した店だけ決まる
        G.ensure()
        home = G.pt(places.HOME_ME)["xy"]
        dist = lambda a, b: ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
        for bid, b in places.BRANCHES.items():
            base, lo, hi = b["rule"]
            xy = G.pt(bid)["xy"]
            d = dist(xy, home if base == "home" else [0.0, 0.0])
            assert lo - 0.01 <= d <= hi + 0.01, (bid, d)
        r = G.rec()
        keep = {k: list(v["xy"]) for k, v in r["pts"].items() if k not in places.BRANCHES}
        for bid in places.BRANCHES:                 # 以前のワールド: 2 店目以降の位置が無い
            r["pts"].pop(bid, None)
        G.save()
        G.ensure()
        assert all(bid in G.rec()["pts"] for bid in places.BRANCHES)
        assert all(G.rec()["pts"][k]["xy"] == v for k, v in keep.items()), "前からある場所は動かない"
        assert G.parking("convenience:3") == 0 and G.parking("convenience:2") > 0, "住宅街の店は駐車場がただ"
        print("positions: OK")

        # ---- 4. 買い物: 置いていない品は買わない. 値段は店ごと
        I.set_list("rice", 1)
        bought, missed = I.shop("supermarket:2", 1.0, ts("2026-10-12 12:00"))
        assert not any(x["id"] == "rice" for x in bought) and I.ps()["shop_list"].get("rice"), (bought, missed)
        assert app.solo._shop_items_here("supermarket:2") == 0 and app.solo._shop_items_here("supermarket") == 1
        random.seed(5)
        p_hi = []
        for _ in range(60):
            I.set_list("bread", 1)
            b, _m = I.shop("supermarket:2", 0.01, ts("2026-10-12 12:00"))
            p_hi += [x["price"] for x in b if x["id"] == "bread" and not x.get("instead")]
        random.seed(5)
        p_lo = []
        for _ in range(60):
            I.set_list("bread", 1)
            b, _m = I.shop("supermarket", 0.01, ts("2026-10-12 12:00"))
            p_lo += [x["price"] for x in b if x["id"] == "bread" and not x.get("instead")]
        assert p_hi and p_lo and sum(p_hi) / len(p_hi) > sum(p_lo) / len(p_lo), (sum(p_hi) / len(p_hi), sum(p_lo) / len(p_lo))
        I.set_list("bread", 0)
        I.set_list("rice", 0)
        print("shop: OK")

        # ---- 5. いちばん近い○○: 近い順に, 開いている店. どこも閉まっていれば, いちばん近い店
        near = sorted(places.branches("cafe"), key=lambda p: G.km(places.HOME_ME, p))
        got = places.nearest(app, "near:cafe", places.HOME_ME, ts("2026-10-13 12:00"))
        assert got == near[0], (got, near)
        assert places.nearest(app, "near:cafe", places.HOME_ME, ts("2026-10-14 12:00")) == "cafe", "水曜は住宅街店が休み"
        assert places.nearest(app, "near:cafe", places.HOME_ME, ts("2026-10-12 12:00")) == "cafe:2", "月曜は駅前店が休み"
        assert places.nearest(app, "near:cafe", places.HOME_ME, ts("2026-10-13 23:00")) == near[0], "どちらも閉まっていれば近いほう"
        assert places.nearest(app, "park", places.HOME_ME, ts("2026-10-13 12:00")) == "park"
        sm = places.nearest(app, "near:supermarket", "station", ts("2026-10-13 12:00"))
        assert sm == min(places.branches("supermarket"), key=lambda p: G.km("station", p)), "出先 (駅) から近い店"
        assert app.places.label("near:convenience") == "いちばん近いコンビニ"
        v = app.places.view()
        assert "near:cafe" in v["near"] and "cafe:2" in v["places"] and "near:cafe" not in v["places"]
        assert "near:cafe" in app.outdoor.view()["routine_choices"] and "near:cafe" not in app.outdoor.view()["choices"]["out"]
        print("nearest: OK")

        # ---- 6. 行動パターン・予定: 選べて, 閉じていた間に店に決まる
        assert offline.normalize({"do": "out", "place": "near:supermarket"})["place"] == "near:supermarket"
        assert offline.normalize({"do": "out", "place": "supermarket:2"})["place"] == "supermarket:2"
        assert offline.normalize({"do": "meal", "how": "buy", "place": "near:convenience"})["place"] == "near:convenience"
        assert offline.normalize({"do": "meal", "how": "buy", "place": "near:cafe"})["place"] == "convenience", "買って食べる店でない"
        day = [{"at": "00:00", "do": "sleep"}, {"at": "10:00", "do": "out", "place": "near:cafe"},
               {"at": "12:00", "do": "meal", "how": "buy", "place": "near:convenience"}, {"at": "13:00", "do": "home"}]
        app.save_settings({"offline": {"enabled": True, "days": {"wed": day, "mon": day}}})
        ps["stamina"] = 100
        rep = O.simulate(ts("2026-10-14 09:00"), ts("2026-10-14 14:00"))       # 水曜: 住宅街のカフェは休み
        out = next(x for x in rep["timeline"] if x["do"] == "out")
        assert out["place"] == "cafe" and not out["skipped"], out
        meal = next(x for x in rep["timeline"] if x["do"] == "meal")
        assert "コンビニ（" in meal["label"], meal
        rep = O.simulate(ts("2026-10-12 09:00"), ts("2026-10-12 14:00"))       # 月曜: 駅前のカフェは休み
        out = next(x for x in rep["timeline"] if x["do"] == "out")
        assert out["place"] == "cafe:2" and not out["skipped"], out
        P_ = app.planner
        assert P_._norm({"do": "out", "place": "near:drugstore"})["place"] == "near:drugstore"
        assert "いちばん近いドラッグストア" in P_.label({"do": "out", "place": "near:drugstore"})
        assert P_.cannot({"do": "out", "place": "near:cafe"}, ts("2026-10-14 12:00"), 100) is None
        assert P_.cannot({"do": "out", "place": "near:cafe"}, ts("2026-10-14 22:00"), 100), "どこも閉まっている"
        rs = G.route_search("near:supermarket", ts("2026-10-13 12:00"), "depart", places.HOME_ME)
        assert rs is not None
        print("routine: OK")

        # ---- 7. 勤め先: 店ごと. 型・休み・時間帯の乱数の並びは変わらない
        seen = set()
        for i in range(300):
            c = {"id": "w%d" % i, "name": "w", "age": 22}
            life = lifetype.decide(c, {}, type_id="shift")
            wp = life["workplace"]
            seen.add(wp)
            assert wp in places.PLACES, wp
            k = places.kind_of(wp)
            assert set(lifetype.shop_hours(wp)[2]) <= {lifetype.DAYS.index(d) for d in life["off"]}, (wp, life["off"])
            ch = dict(c, life=life)
            sched = lifetype.build(ch)
            jobs = [e for e in sched if e.get("workplace")]
            assert jobs and all(e["workplace"] == wp and places.PLACES[wp]["label"] in e["label"] for e in jobs), (wp, jobs[:1])
            if k != wp:
                assert lifetype.SHOP_POS[k] in jobs[0]["pos"]
        assert any(":" in w for w in seen) and any(w in places.FIRST_NAME for w in seen), seen
        print("workplace: OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK")


if __name__ == "__main__":
    main()
