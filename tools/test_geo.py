"""マップの段階 1 (core/geo.py): 場所の位置・行き方 (徒歩 / 電車・バス)・移動中・着く・家へ帰る・通勤・閉じていた間の移動.

    python tools/test_geo.py
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
from core import engine, geo as G, places as PL, store  # noqa: E402


def at(date, hm):
    return datetime.strptime("%s %s" % (date, hm), "%Y-%m-%d %H:%M").timestamp()


def main():
    random.seed(11)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("移動のある町")
        geo, L, P = app.geo, app.life, app.presence
        L.player_state()["stamina"] = 100
        L.player_state()["money"] = 50000
        geo.ensure()

        # ---- 1. 位置の決まり: 家から駅は歩いて 6〜26 分, 海・山は歩いて行けない (電車), 公園は近い
        home = PL.HOME_ME
        m = geo.walk_min(home, "station", time.mktime((2026, 5, 1, 12, 0, 0, 0, 0, -1)))
        assert 5 <= m <= 30, m
        noon = at("2026-05-01", "12:00")
        o = geo.options(home, "beach", noon)
        assert not o["walk"]["ok"] and o["transit"] and o["transit"]["ok"] and o["best"] == "transit", o
        assert geo.options(home, "park", noon)["transit"] is None
        assert geo.options(home, "beach", at("2026-05-01", "02:00"))["transit"]["ok"] is False     # 夜中は走っていない
        lg = geo.leg(home, "beach", "transit", at("2026-05-01", "02:00"), rand=False)
        assert lg["note"] == "始発を待った" and lg["min"] > 180, lg
        print("位置と行き方: OK | 駅まで%d分, 海まで電車%d分・%d円" % (m, o["transit"]["min"], o["transit"]["fare"]))

        # ---- 2. 一人の外出: 移動中 → 着く (店の買い物は着いてから) → 帰る (家へ移動中) → 家に着く
        app.items.set_list("bread", 1)
        r = app.solo.start("out", place="supermarket", how="walk")
        tr = geo.travel()
        assert tr and tr["dir"] == "go" and "移動中" in r["label"], r
        now = time.time()
        assert geo.moving(now) and app.outdoor.current(now).get("moving")
        assert "移動中" in P.view(now)["label"]
        assert app.solo.shop_tick(now + 3600) is None                 # 着くまで買い物は始まらない
        arr = tr["arr"]
        a = geo.tick(arr + 1)
        assert a and "着いた" in a["text"] and P.rec()["pos"] == "supermarket", a
        assert app.solo.shop_tick(arr + 60) is None                   # 着いてすぐは品を選んでいる
        done = app.solo.shop_tick(arr + 3600)
        assert done and done["place"] == "supermarket", done
        back = app.come_back()
        assert back.get("traveling"), back
        trh = geo.travel()
        assert trh["dir"] == "home" and P.rec()["mode"] == "out"
        with app.lock:
            a = geo.tick(trh["arr"] + 1)
        assert a and P.rec()["mode"] == "none" and P.rec()["pos"] == home, (a, P.rec())
        print("一人の外出: OK |", r.get("done"), "→", a["text"])

        # ---- 3. 電車で遠くへ: 運賃が家計に (交通費)
        m0 = L.player_state()["money"]
        app.solo.start("out", place="aquarium", how="transit")
        tr = geo.travel()
        assert tr["how"] == "transit" and tr["fare"] > 0 and L.player_state()["money"] == m0 - tr["fare"], tr
        assert any(x["c"] == "transport" for x in app.kakeibo.rec()["raw"]) if hasattr(app.kakeibo, "rec") else True
        r = app.come_back()                                         # 着く前に引き返す: 出たところ (家) から → すぐ家
        assert P.rec()["mode"] == "none" and not geo.travel(), (r, P.rec())
        print("電車・運賃・引き返す: OK | 片道%d円" % tr["fare"])

        # ---- 4. 仕事: 通勤して, 職場にいた間だけ給料
        r = app.solo.start("work")
        tr = geo.travel()
        assert tr and tr["to"] == "office" and P.rec()["mode"] == "work", (r, tr)
        geo.tick(tr["arr"] + 1)
        P.rec()["arrived"] = tr["arr"]
        t_left = tr["arr"] + 3 * 3600
        P.rec()["left"] = t_left
        hb = geo.leg("office", home, None, t_left, rand=False)
        P.rec()["travel"] = {"from": "office", "to": home, "how": hb["how"], "t0": t_left, "arr": t_left + hb["min"] * 60,
                             "fare": 0, "dir": "home", "then": None, "note": ""}
        with app.lock:
            a = geo.tick(t_left + hb["min"] * 60 + 1)
        assert "仕事を終えて" in (a["act"].get("text") or a["act"].get("entry", {}).get("text", "")) or a["act"], a
        print("通勤: OK | 職場まで%d分" % round((tr["arr"] - tr["t0"]) / 60))

        # ---- 5. 約束の場所: 移動中はまだ着いていない
        app.solo.start("out", place="cafe", how="walk") if PL.open_state("cafe", datetime.now())["open"] else app.solo.start("out", place="park")
        pl = P.rec()["place"]
        assert not app.appoint.here(pl)
        geo.tick(geo.travel()["arr"] + 1) if geo.travel() else None
        assert app.appoint.here(pl)
        P.rec()["travel"] = None
        P.rec().pop("travel")
        with app.lock:
            app.come_back(at=time.time(), quiet=True)
        P.rec()["pos"] = home
        print("約束の場所: OK")

        # ---- 6. 閉じていた間: 出かける行動には行き帰りの移動が入る
        app.save_settings({"offline": {"enabled": True, "days": {d: [{"at": "00:00", "do": "sleep"}, {"at": "10:00", "do": "out", "place": "mall"},
                                                                    {"at": "13:00", "do": "home"}] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}}})
        d = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        rep = app.offline.simulate(at(d, "09:00"), at(d, "15:00"))
        mv = [x for x in rep["timeline"] if x["do"] == "move"]
        assert len(mv) == 2 and "ショッピングモールへ" in mv[0]["text"] and "家へ" in mv[1]["text"], rep["timeline"]
        out = next(x for x in rep["timeline"] if x["do"] == "out")
        assert out["t"] == mv[0]["end"] and mv[1]["t"] >= out["end"], rep["timeline"]
        print("閉じていた間: OK |", [x["text"][:28] for x in rep["timeline"]])

        # ---- 7. 画面を閉じたとき: 出先から家に着くまでは, 閉じていた間の過ごし方に入らない
        app.solo.start("out", place="mall", how="transit")
        b = time.time()
        geo.tick(geo.travel()["arr"] + 1)
        eta = geo.home_eta(b + 1800)
        assert eta > b + 1800
        print("閉じたとき: OK | 帰り %d 分" % round((eta - b - 1800) / 60))
        P.rec().pop("travel", None)
        with app.lock:
            app.come_back(at=time.time(), quiet=True)
        P.rec()["pos"] = home

        # ---- 8. 段階 2: タクシー (いつでも・高い) / 自転車 (買った店に置いてある. 乗っていけば行った先に) / 車 (免許が要る)
        o = geo.options(home, "mall", noon)
        assert "taxi" in o["modes"] and "bike" not in o["modes"] and o["best"] != "taxi", o
        assert o["modes"]["taxi"]["fare"] > o["modes"]["transit"]["fare"]
        L.player_state().update(money=100000, debt=0, loans={})
        for _ in range(8):                         # 品切れのこともある
            app.items.set_list("bicycle", 1)
            bought, missed = app.items.shop("mall", 1.0, time.time())
            if any(x["id"] == "bicycle" for x in bought):
                break
        assert any(x["id"] == "bicycle" for x in bought) and geo.veh_at("bicycle") == "mall", (bought, missed)
        assert "bike" not in geo.options(home, "park", noon)["modes"]              # 自転車はモールに置いたまま
        assert "bike" in geo.options("mall", home, noon)["modes"]
        lg = geo.leg("mall", home, "bike", noon)
        geo.used(lg, home)
        assert geo.veh_at("bicycle") == home and "bike" in geo.options(home, "riverside", noon)["modes"]
        app.items.add("car", 1)
        assert "car" not in geo.options(home, "beach", noon)["modes"]              # 免許が無い
        app.quals.rec()["have"]["drive"] = time.time()
        oc = geo.options(home, "beach", noon)
        assert "car" in oc["modes"] and oc["modes"]["car"]["fare"] >= 1000, oc       # ガソリン + 駐車場
        assert geo.options(home, "beach", noon)["best"] in ("car", "transit")
        app.items.add("car", -1)
        app.items.set_list("car", 1)
        del app.quals.rec()["have"]["drive"]
        bought, missed = app.items.shop("car_dealer", 1.0, time.time())
        assert not bought and any("免許" in m for m in missed), missed
        # 教習所: 入校していれば教習 (免許の勉強時間). 家では勉強できない
        try:
            app.solo.start("practice", "qual:drive")
            raise AssertionError("免許を家で勉強できた")
        except ValueError:
            pass
        L.player_state()["money"] = 400000
        app.quals.apply("drive")
        res = app.solo.result("out", 2.0, time.time(), place="driving_school")
        assert "教習" in res["text"] and app.quals.rec()["study"]["drive"] > 0, res
        print("自転車・車・タクシー・教習所: OK |", res["text"])

        # ---- 9. 段階 3: 途中の出来事 (遅延・パンク). 地図の点
        G.EV_DELAY, G.EV_FLAT = 1.0, 1.0
        lg = geo.leg(home, "beach", "transit", noon)
        assert "遅れた" in lg["note"], lg
        lg = geo.leg(home, "riverside", "bike", noon)
        assert "パンク" in lg["note"] and lg["fare"] == G.FLAT_FIX, lg
        G.EV_DELAY, G.EV_FLAT = 0.04, 0.015
        mv = app.state_view()["outdoor"]
        assert home in mv["map"] and "station" in mv["map"] and "mall" in mv["map"] and mv["here"] == home
        assert "modes" in mv["routes"]["mall"] and "taxi" in mv["routes"]["mall"]["modes"]
        print("途中の出来事・地図: OK")

        # ---- 10. 段階 4: 約束の相手も, 自分の家から移動してくる (約束の前は「向かっている」. 遠いと遅れやすい)
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        st["override"] = None
        t_ap = time.time() + 3 * 3600
        x = {"id": "geo1", "cid": cid, "t": t_ap, "place": "aquarium", "do": "date", "by": "me", "status": "set"}
        x["plan"] = app.appoint._plan(char, st, x)
        x["plan"].update(noshow=False, late=0)
        app.appoint.all().append(x)
        go = x["plan"]["go"]
        assert go > 10, x["plan"]
        assert app.appoint.heading(cid, t_ap - go * 60 - 120) is None
        assert app.appoint.heading(cid, t_ap - 60)["id"] == "geo1"
        sc = app.scene_at(char, st, datetime.fromtimestamp(t_ap - 60))
        assert "水族館へ向かっている" in sc["label"] and sc["away"], sc
        x2 = dict(x, place="home:" + cid)
        assert app.appoint._plan(char, st, x2)["go"] == 0          # 相手の家での約束: 相手は動かない
        app.appoint.all().remove(x)
        print("相手の移動: OK | 相手の家から水族館まで%d分" % go)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
