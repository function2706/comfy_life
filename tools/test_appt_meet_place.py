"""約束の場所で会ったお出かけ (1.5.0 の直し):
- 会ったら二人ともその場所にいる: 家からの移動は入らない (移動中にならない・余計な運賃を払わない). 手をつなぐ・移動のコマンドもすぐできる
- 遡及 (engine.appt_travel_comp): 以前の作りで入っていた余計な移動の運賃を二人に返し, その「移動中」のまま「家に帰る」で解散した
  デートは, 本来の終わりがまだなら元に戻す (一時データ).

    python tools/test_appt_meet_place.py
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
from core import engine, geo as G, store  # noqa: E402
from core import parting as _parting  # noqa: E402
_parting.FIXED = "ok"      # 別れぎわは必ず応じる (引き止めは test_parting で)
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
G.INSTANT = False


def main():
    random.seed(8)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("約束の場所")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        if app.bonds.with_rec():
            app.bonds.end(go_home=False)
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        A, B, P, L = app.appoint, app.bonds, app.presence, app.life
        st = app.state(cid)
        app.set_params({"affection": 70, "mood": 70, "energy": 80, "sleepiness": 0}, cid)
        L.player_state()["money"] = 100000

        def make(t, place="aquarium", do="aquarium"):
            x = {"id": "x%d" % random.randint(0, 1 << 30), "cid": cid, "t": t, "place": place, "do": do, "by": "me",
                 "status": "set", "made": t - 86400, "plan": {"noshow": False, "late": 0, "cancel_checked": True}}
            A.all().append(x)
            A.save()
            return x

        def arrive(x):
            A.go(x["id"])
            tr = app.geo.travel()
            if tr:
                with app.lock:
                    app.geo.tick(tr["arr"] + 1)
            for r in app.kakeibo.rec()["raw"]:                   # 向かったときの交通費は, 会うより前 (本当の遊びでは数十分前)
                if r["t"] > time.time() - 600:
                    r["t"] -= 1800
            x["t"] = time.time() - 1
            n0 = len(app.kakeibo.rec()["raw"])
            A.live(time.time())
            assert x["status"] == "met" and B.mode(cid) == "meet", x["status"]
            return [r for r in app.kakeibo.rec()["raw"][n0:] if r["c"] == "transport"]       # 会ったときに払った交通費

        # ---- 1. 直したあと: 会ったらそこにいる. 移動は入らない
        x = make(time.time() + 3600)
        fares = arrive(x)
        ov = st["override"]
        now = time.time()
        assert ov["place"] == "aquarium" and not ov.get("trips") and not app.outing_trip(st, now) and not app.outing_moving(st, now), ov
        assert app.geo.where() == "aquarium"
        assert not fares, fares
        av = app.person_view(cid)["available"]
        assert av["hold_hands"]["ok"] and av["cafe"].get("move_on") and av["cafe"]["ok"], (av["hold_hands"], av["cafe"])
        print("約束の場所で会う: OK | 移動なし・手をつなぐ ○・移動のコマンド ○")
        app.act("go_home", cid)
        for e in app.log(cid):                                   # この 1 回目は, 数時間前のことに (2 回目と取り違えないように)
            e["t"] -= 5 * 3600
        x["t"] -= 5 * 3600
        for r in app.kakeibo.rec()["raw"]:
            r["t"] -= 5 * 3600

        # ---- 2. 遡及: 以前の作りの状態 (会ったときに家からの移動と運賃が入っていた) → 運賃を返し, 解散したデートを戻す
        if app.geo.travel():
            app.geo.cut(time.time())
        P.rec()["pos"] = "home:me"
        x = make(time.time() + 3600)
        arrive(x)
        e = next(e for e in reversed(app.log(cid)) if e.get("action") == "aquarium")
        ov = st["override"]
        ov["arr"] = time.time() + 70 * 60                        # 以前の作り: 家から水族館への移動 (あと 70 分は移動中) と運賃
        ov["until"] += 70 * 60
        paid = 740
        L.move(None, dp=-paid, cat="transport", note="交通費（水族館）")
        app.kakeibo.rec()["raw"][-1]["t"] = e["t"]                 # 会ったときの記録と同じ時刻
        L.her_money(st)["a"] -= paid
        L.save_player()
        app.save_state(cid)
        assert app.outing_moving(st, time.time())
        app.act("go_home", cid)                                    # 「移動中」で「家に帰る」しか無く, 解散した
        assert not B.with_rec() and not (st.get("override") or {}).get("outing")
        L.player_state()["fix_comp"].pop("appt_travel", None)
        m0, h0 = L.player_state()["money"], L.her_money(app.state(cid))["a"]
        notes = app.appt_travel_comp()
        st = app.state(cid)
        assert any("交通費" in n for n in notes) and any("戻した" in n for n in notes), notes
        assert L.player_state()["money"] - m0 >= paid and L.her_money(st)["a"] - h0 == paid, (L.player_state()["money"] - m0, L.her_money(st)["a"] - h0)
        assert B.mode(cid) == "meet" and st["override"]["place"] == "aquarium" and app.geo.where() == "aquarium"
        assert not app.outing_moving(st, time.time()) and app.person_view(cid)["available"]["hold_hands"]["ok"]
        assert app.appt_travel_comp() == []                        # 一度だけ
        print("遡及: OK |", " / ".join(notes))
        app.scheduled_scene = sched
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
