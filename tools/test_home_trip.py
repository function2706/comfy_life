"""相手の家へ・あなたの家へ, 移動して着く (残件 F16・F17. 一時データ, 画像生成なし).
- 外で会っていて「家に寄ってもいい？」/「うちに寄っていく？」を受けてくれたら, その家まで一緒に移動してから上がる
  (以前は移動なしで, その場で家にいることになっていた). 出たときは「一緒に…へ向かった」だけ. 迎えの文・暮らしぶり・効き目は着いたとき
- 移動中は話す・手をつなぐくらい. 移動中の居場所は途中の地点. 断られたら移動しない (外で会ったまま)
- 着いたら相手の家 (visit) / あなたの家 (guest). 来客の一時シーンは着いたあとも残る
- 約束なしに訪ねて, 留守・出てこない・断られたら, 玄関先にいる (外出中・場所は相手の家). 結果は外出の画面に残る (閉じるまで)
  ほかへ行けば消える. 迎えてくれたらいままでどおり訪問になる
- 「外出」の画面で押せるもの (帰る・ほかへ・閉じる) は, 本当にできる

    python tools/test_home_trip.py
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
_parting.FIXED = "ok"
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
G.INSTANT = False


def shift(st, d):
    """一緒の移動を d 秒前に出たことにする (着いた時刻まで進める代わり)."""
    ov = st["override"]
    for k in ("arr", "until", "start"):
        if k in ov:
            ov[k] -= d
    for tr in ov.get("trips") or []:
        tr["t0"] -= d
        tr["arr"] -= d
        for lg in tr.get("legs") or []:
            lg["t0"] -= d
            lg["t1"] -= d


def meet_at(app, cid, place="cafe"):
    """外で会っている (cafe で)."""
    app.bonds.end(go_home=False)
    app.presence.rec()["mode"] = "none"
    app.presence.rec().pop("travel", None)
    app.presence.save()
    st = app.state(cid)
    app.bonds.start(cid, "meet")
    st["override"] = {"outing": True, "activity": "outing", "label": "カフェ", "location": app.places.label(place), "place": place,
                      "until": time.time() + 3 * 3600, "start": time.time(), "pos": "", "neg": ""}
    st["cooldowns"] = {}


def main():
    random.seed(7)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("家まで")
        cid = app.settings["active_character"]
        B = app.bonds
        B.set_stage(cid, "visit")
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        st = app.state(cid)
        app.life.player_state()["money"] = 50000
        name = app.char(cid)["name"]
        home = "home:" + cid

        # ---- 1. 断られたら移動しない
        meet_at(app, cid)
        app.set_params({"affection": 40, "mood": 70, "trust": 60}, cid)
        r = app.act("go_her_home", cid)
        assert B.mode(cid) == "meet" and st["override"]["place"] == "cafe" and not app.outing_trip(st), st["override"]
        print("断られた: OK |", r["entry"]["text"])

        # ---- 2. 家に寄ってもいい？ → 一緒に相手の家まで移動 → 着いたら上がる
        meet_at(app, cid)
        app.set_params({"affection": 85, "mood": 75, "trust": 70}, cid)
        aff0 = st["params"]["affection"]
        r = app.act("go_her_home", cid)
        e = r["entry"]
        now = time.time()
        assert B.mode(cid) == "meet", "出たときは, まだ外で会っている"
        ov = st["override"]
        assert ov.get("home_trip") == "visit_start" and ov["place"] == home and ov["arr"] > now, ov
        ls = e["text"].split(chr(10))
        assert not ls[0].startswith("（") and ls[1].startswith("（%sと一緒に" % name) and "分ほど" in ls[2], e["text"]
        assert "の部屋は" not in e["text"], "返事はその場で (向かう前). 部屋の様子は着いてから: %s" % e["text"]
        assert abs(st["params"]["affection"] - aff0) < 1e-9, "効き目は着いてから"
        trip = app.outing_trip(st, now)
        assert trip and trip["to"] == home and trip["dir"] == "go", trip
        mid = app.geo.where(trip["t0"] + (trip["arr"] - trip["t0"]) * 0.5)
        assert mid not in (home, "cafe"), mid
        pv = app.person_view(cid)
        assert pv["scene"]["label"].startswith("一緒に") and app.places.label(home) in pv["scene"]["label"], pv["scene"]["label"]
        av = pv["available"]
        assert av["hold_hands"]["ok"] and not av["hug"]["ok"], (av["hold_hands"], av["hug"])
        assert av["go_her_home"]["cooldown"] > 0, "続けては押せない (間隔)"
        print("向かう: OK |", e["text"], "|", pv["scene"]["label"], "|", round((ov["arr"] - now) / 60), "分")
        shift(st, ov["arr"] - now + 5)
        app.tick(cid)
        assert B.mode(cid) == "visit", B.with_rec()
        last = app.log(cid)[-1]
        assert last.get("arrived") and last["action"] == "go_her_home" and "の部屋は" in last["text"] and "に着いた" in last["text"], last
        assert last.get("deltas"), "着いたときに効き目が出る"
        assert app.geo.where() == home, app.geo.where()
        assert not (st.get("override") or {}).get("home_trip"), st.get("override")
        print("着いた: OK |", last["text"].replace("\n", " / "))
        B.end(go_home=False)

        # ---- 3. うちに寄っていく？ → 一緒にあなたの家まで → 来客 (一時シーンは着いたあとも残る)
        meet_at(app, cid)
        app.set_params({"affection": 85, "mood": 75, "trust": 70}, cid)
        r = app.act("bring_home", cid)
        assert B.mode(cid) == "meet" and st["override"].get("home_trip") == "guest_start", st["override"]
        assert "一緒に" in r["entry"]["text"] and "あなたの家" in r["entry"]["text"], r["entry"]["text"]
        shift(st, st["override"]["arr"] - time.time() + 5)
        app.tick(cid)
        assert B.mode(cid) == "guest", B.with_rec()
        assert (st.get("override") or {}).get("activity") == "guest" and st["override"]["until"] > time.time(), st.get("override")
        assert app.geo.where() == "home:me" and not app.outdoor.current()
        print("うちへ: OK |", app.log(cid)[-1]["text"].replace("\n", " / "))
        B.end(go_home=False)

        # ---- 4. 途中で「家に帰る」(切り上げ) は, いままでどおり押せる (解散)
        meet_at(app, cid)
        app.set_params({"affection": 85, "mood": 75, "trust": 70}, cid)
        app.act("go_her_home", cid)
        assert app.outing_trip(st)
        av = app.person_view(cid)["available"]
        ends = [k for k, v in av.items() if v["ok"] and (app.action(k).get("bond") == "visit_end" or app.action(k).get("end_override"))]
        assert ends, "移動中でも, 切り上げることはできる"
        B.end(go_home=False)
        st["override"] = None

        # ---- 5. 約束なしに訪ねる: 留守 → 玄関先 (外出中・場所は相手の家). 知らせは閉じるまで残る
        app.presence.rec()["mode"] = "none"
        app.presence.rec().pop("travel", None)
        app.presence.rec()["pos"] = home
        app.presence.save()
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=True, busy=False, asleep=False)
        r = app.drop_in(cid)
        assert r["started"] == "out", r
        pv = app.presence.view(time.time())
        d = pv.get("door")
        assert d and d["kind"] == "absent" and d["cid"] == cid and not d["seen"] and "留守" in d["text"], pv
        assert app.presence.rec()["place"] == home and app.places.label(home) in pv["label"], pv["label"]
        assert app.geo.where() == home
        app.solo.door_ack()
        assert app.presence.view(time.time())["door"]["seen"]
        print("留守: OK |", pv["label"], "|", d["text"])
        # ほかへ行けば消える (外出の画面の「ほかへ行く」)
        r = app.solo.move("park")
        assert not app.presence.view(time.time()).get("door")
        app.come_back()

        # ---- 6. 断られた (玄関先で) / 寝ている / 出てこない: どれも残る. 迎えてくれたら訪問 (知らせは無い)
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        kinds = set()
        for i in range(60):
            app.presence.rec().update(mode="none", pos=home)
            app.presence.rec().pop("travel", None)
            app.set_params({"affection": 45, "trust": 40, "mood": 40}, cid)
            st["gain_day"] = {}
            r = app.drop_in(cid)
            if r["started"] == "visit":
                assert not app.presence.view(time.time()).get("door")
                B.end(go_home=False)
                kinds.add("visit")
            else:
                d = app.presence.view(time.time())["door"]
                assert d["kind"] == "refused" and d["text"], d
                kinds.add("refused")
                app.come_back()
            if kinds == {"visit", "refused"}:
                break
        assert kinds == {"visit", "refused"}, kinds
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=True)
        app.presence.rec().update(mode="none", pos=home)
        r = app.drop_in(cid)
        assert app.presence.view(time.time())["door"]["kind"] == "asleep"
        app.come_back()
        print("玄関先: OK", sorted(kinds))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
