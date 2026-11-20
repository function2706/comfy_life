"""自転車と一緒の移動 (S20: F13 + F14).
F13: 相手と一緒の移動では自転車を使わない (おまかせで選ばない・手で選べば断る・駅まで自転車の経路も無い). 自転車は置いた所に残る. 車は二人で乗れる.
F14: 出先に置いてきた自転車・車を, 家から取りに行く (店が閉まっていても). 着いたらそれに乗って家へ. 途中でやめれば置いたまま (一時データ).

    python tools/test_pair_bike.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, geo as G, places as P, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
G.INSTANT = False
HOME = P.HOME_ME


def must_fail(fn, word):
    try:
        fn()
    except ValueError as e:
        assert word in str(e), e
        return str(e)
    raise AssertionError("通ってしまった: %s" % word)


def bike_legs(rs):
    return [lg for r in rs for lg in r["legs"] if lg.get("veh") == "bicycle"]


def main():
    random.seed(20)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("自転車")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "live")
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        st = app.state(cid)
        L, g = app.life, app.geo
        app.items.add("bicycle")
        veh = g.rec().setdefault("veh", {})
        noon = time.time()

        # ---- 1. geo: 一緒 (pair) なら自転車の行き方は無い. 一人なら, 出先の自転車に乗って帰る (carry)
        veh["bicycle"] = "cafe"
        solo_o = g.options("cafe", "mall", noon)
        pair_o = g.options("cafe", "mall", noon, pair=True)
        assert "bike" in solo_o["modes"] and solo_o["best"] == "bike", solo_o["best"]
        assert "bike" not in pair_o["modes"] and pair_o["best"] != "bike", pair_o
        must_fail(lambda: g.leg("cafe", "mall", "bike", noon, pair=True), "二人では自転車に乗れません")
        for to in ("aquarium", "mall", "riverside", "station", "amusement"):
            for frm in ("cafe", HOME):
                veh["bicycle"] = frm
                for how in (None, "transit"):
                    try:
                        lg = g.leg(frm, to, how, noon, rand=False, pair=True)
                    except ValueError:
                        continue
                    assert lg["how"] != "bike" and not [x for x in lg.get("legs") or [] if x.get("veh") == "bicycle"], (frm, to, lg)
                assert not bike_legs(g.routes(frm, to, noon, pair=True)), (frm, to)
        veh["bicycle"] = HOME
        print("geo: 一緒なら自転車を使わない OK")

        # ---- 2. 同居相手と家から出かける: 家に自転車があっても, 自転車にはならない. 自転車は家に残る
        L.player_state()["money"] = 100000
        for aid in ("aquarium", "cafe", "eat_out", "movie"):
            st["override"], st["cooldowns"] = None, {}
            app.set_params({"affection": 80, "mood": 75, "energy": 80, "trust": 70}, cid)
            try:
                app.act(aid, cid)
            except (ValueError, KeyError):
                continue
            ov = st.get("override") or {}
            assert ov.get("how") != "bike", (aid, ov.get("how"))
            assert all(t.get("how") != "bike" for t in ov.get("trips") or []), (aid, ov.get("trips"))
            assert g.veh_at("bicycle") == HOME, (aid, g.veh_at("bicycle"))
        print("家から一緒に: 自転車にならない OK")

        # ---- 3. 出先に自転車を停めてある所で, 一緒に次の場所へ: おまかせでも自転車にならず, 手で選べば断る. 自転車はそこに残る
        st["override"], st["cooldowns"], st["move_log"] = None, {}, []
        app.set_params({"affection": 85, "mood": 80, "energy": 85, "trust": 70}, cid)
        app.act("aquarium", cid)
        ov = st["override"]
        for tr in ov.get("trips") or []:
            if tr["dir"] == "go":
                d = tr["arr"] - time.time() + 1
                tr["t0"] -= d
                tr["arr"] -= d
                for lg in tr.get("legs") or []:
                    lg["t0"] -= d
                    lg["t1"] -= d
        ov["arr"] = time.time() - 1
        assert g.where() == "aquarium"
        veh["bicycle"] = "aquarium"                     # 前に一人で来て, 停めてあった
        od = app.outdoor.view(time.time())
        assert od.get("with_outing") and all("bike" not in (r.get("modes") or {}) for r in od["routes"].values()), "一緒なのに自転車の行き方が出る"
        must_fail(lambda: app.outing_move("cafe", "bike"), "二人では自転車に乗れません")
        ok = None
        for _ in range(12):
            r = app.outing_move("cafe")
            if not r.get("refused"):
                ok = r
                break
            st["cooldowns"], st["move_log"] = {}, []
        assert ok, "何度誘っても応じない"
        assert st["override"].get("how") != "bike", st["override"].get("how")
        assert g.veh_at("bicycle") == "aquarium", g.veh_at("bicycle")
        assert not app.outdoor.view(time.time())["vehicles"]["own"]["bicycle"]["fetch"], "一緒にいる間に取りに行ける"
        print("出先から一緒に: 自転車は置いたまま OK", st["override"].get("how"))

        # ---- 4. 解散して家に帰った: 閉まっている店 (ラーメン屋) に停めた自転車を取りに行く
        veh["bicycle"] = "ramen"
        st["override"] = None
        app.bonds.end() if app.bonds.together(cid) else None
        pr = app.presence.rec()
        pr["mode"] = "none"
        pr.pop("travel", None)
        pr["pos"] = HOME
        app.presence.save()
        assert g.where() == HOME, g.where()
        real_open = P.open_state
        P.open_state = lambda pid, dt: {"open": False, "note": "閉店"} if pid == "ramen" else real_open(pid, dt)
        try:
            must_fail(lambda: app.solo.start("out", place="ramen"), "閉まっています")       # 行き先としては行けない
            vv = g.vehicles_view()["own"]["bicycle"]
            assert vv["fetch"] and vv["at"] == "ramen" and not vv["here"], vv
            must_fail(lambda: app.solo.fetch("bicycle", how="bike"), "歩き・電車・バス・タクシー")
            must_fail(lambda: app.solo.fetch("car"), "持っていません")
            t0 = time.time()
            r = app.solo.fetch("bicycle", how="walk")
            assert "取りに" in r["done"] and "ラーメン屋" in r["done"], r
            tr = pr["travel"]
            assert tr["to"] == "ramen" and tr["then"] == "fetch:bicycle" and tr["how"] == "walk", tr
            assert app.solo.fetch_why("bicycle") is not None            # 向かっている途中は, もう一度は押せない
            n0 = len(app.solo.rec().get("log") or []) if hasattr(app.solo, "rec") else 0
            out = g.tick(tr["arr"] + 1)                                   # 着いた: すぐ自転車で家へ
            tr2 = pr["travel"]
            assert tr2["dir"] == "home" and tr2["how"] == "bike" and tr2["from"] == "ramen", tr2
            assert "自転車に乗って家へ向かった" in out["text"], out
            out2 = g.tick(tr2["arr"] + 1)                                 # 家に着いた
            assert pr["mode"] == "none" and g.where() == HOME and g.veh_at("bicycle") == HOME, (pr["mode"], g.where(), g.veh_at("bicycle"))
            txt = (out2.get("act") or {}).get("entry", {}).get("text", "") + str((out2.get("act") or {}).get("solo"))
            assert "取ってきた" in txt and "には行かなかった" not in txt, txt
            assert t0 <= tr2["arr"]
            print("取りに行く:", txt.split("\n")[0][:80])

            # ---- 5. 取りに向かう途中で引き返す: 自転車は置いたまま
            veh["bicycle"] = "ramen"
            r = app.solo.fetch("bicycle", how="walk")
            go = pr["travel"]
            half = (go["arr"] - go["t0"]) / 2                             # 半分ほど歩いたところで
            go["t0"] -= half
            go["arr"] -= half
            r = app.come_back()                                           # 戻る (途中から家へ)
            back = pr["travel"]
            assert back["dir"] == "home" and back["how"] != "bike", back
            out3 = g.tick(back["arr"] + 1)
            txt = str((out3.get("act") or {}).get("solo"))
            assert g.veh_at("bicycle") == "ramen" and "乗って帰らなかった" in txt, (g.veh_at("bicycle"), txt)
            assert go["then"] == "fetch:bicycle"
            print("途中でやめた: 置いたまま OK")

            # ---- 6. 家にあるとき・出かけているときは取りに行けない
            veh["bicycle"] = HOME
            assert app.solo.fetch_why("bicycle") == "家にあります"
            # 遠い所 (水族館) に置いた自転車: 取りに行けるが, 家までは乗らず, おまかせで (駅まで乗って停めることも)
            veh["bicycle"] = "aquarium"
            r = app.solo.fetch("bicycle", how="transit")
            out = g.tick(pr["travel"]["arr"] + 1)
            assert "家まで自転車で帰るには遠いので" in out["text"], out["text"]
            out2 = g.tick(pr["travel"]["arr"] + 1)
            txt = str((out2.get("act") or {}).get("solo"))
            assert pr["mode"] == "none" and ("乗ってきた" in txt or "乗って帰らなかった" in txt), txt
            print("遠い所:", out["text"][:70], "/", txt[:90])
            veh["bicycle"] = "aquarium"
            app.solo.start("out", place="cafe")
            assert app.solo.fetch_why("bicycle") == "家にいるときに取りに行けます"
            must_fail(lambda: app.solo.fetch("bicycle"), "家にいるときに")
        finally:
            P.open_state = real_open
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
