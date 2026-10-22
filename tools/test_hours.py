"""行き先の営業時間の確認 (一時データ, 画像生成なし).
- 営業時間・定休日・季節がある行き先と, いつでも行ける行き先 (公園・河川敷・駅前・街・コンビニ・丘)
- 閉まっている行き先には, 一人の外出でも誰かとのお出かけでも行けない (画面の選択肢にも「〇時から」)
- いる行き先が閉まったら出される (一人なら街へ. 誰かとなら切り上げて帰る)
- 約束は会う時刻に開いていること. 行動パターンの外出も, 閉まっていれば行かず, 閉まる時刻までしかいない

    python tools/test_hours.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, offline, places, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
REAL = places.open_state_real


def at(dt):
    """営業時間だけ, その時刻で判定させる."""
    places.open_state = offline.open_state = lambda pid, _dt: REAL(pid, dt)


def main():
    random.seed(71)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        # ---- 1. 営業時間・定休日・季節
        tue23, tue8, mon12, jan12 = (datetime(2026, 10, 20, 23, 0), datetime(2026, 10, 20, 8, 0),
                                     datetime(2026, 10, 19, 12, 0), datetime(2027, 1, 12, 12, 0))
        assert not REAL("amusement", tue23)["open"] and "明日09:00から" in REAL("amusement", tue23)["note"]
        assert not REAL("aquarium", tue8)["open"] and REAL("aquarium", tue8)["note"] == "09:30から"
        assert not REAL("cafe", mon12)["open"] and "定休日" in REAL("cafe", mon12)["note"], "カフェは月曜休み"
        assert not REAL("beach", jan12)["open"] and "季節外" in REAL("beach", jan12)["note"]
        for pid in ("park", "riverside", "station", "town", "convenience", "hill", "home:me", "home:x"):
            assert REAL(pid, tue23)["open"] and REAL(pid, datetime(2026, 10, 21, 3, 0))["open"], pid
        o = REAL("mall", datetime(2026, 10, 20, 20, 30))
        assert o["open"] and datetime.fromtimestamp(o["until"]).strftime("%H:%M") == "21:00"
        assert places.hours_label("cafe") == "8:00〜21:00・月曜休み" and places.hours_label("park") == "24時間"
        print("hours: OK")

        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.world["outdoor"] = {"rate_out": 0, "rate_outing": 0}
        S, B = app.solo, app.bonds
        cid = app.bonds.living()
        assert cid, "最初のワールドは同居から"
        st = app.state(cid)

        # ---- 2. 閉まっている行き先には行けない (一人でも, 誰かとでも). 画面にも「〇時から」
        at(tue23)
        try:
            S.start("out", place="amusement")
            raise AssertionError("夜の遊園地に行ける")
        except ValueError as e:
            assert "閉まって" in str(e)
        v = app.state_view(cid)
        assert v["outdoor"]["places"]["amusement"]["open"] is False and v["outdoor"]["places"]["amusement"]["note"]
        assert v["outdoor"]["places"]["park"]["open"]
        assert app.person_view(cid)["available"]["aquarium"]["closed"] and not app.person_view(cid)["available"]["aquarium"]["ok"]
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": time.time() + 9e6}
        app.set_params({"affection": 70, "mood": 70, "energy": 80, "sleepiness": 0}, cid)
        try:
            app.act("aquarium", cid)
            raise AssertionError("閉まっている水族館に出かけられる")
        except ValueError as e:
            assert "閉まって" in str(e)
        try:
            app.act("shopping", cid, opts={"place": "mall"})
            raise AssertionError("閉まっているモールに買い物に出かけられる")
        except ValueError:
            pass
        st["cooldowns"] = {}
        app.act("walk", cid, opts={"place": "riverside"})        # 夜の河川敷は行ける (人がほとんどいないだけ)
        assert B.mode(cid) == "home" and st["override"]["place"] == "riverside"
        app.act("go_home", cid)
        print("closed places: OK")

        # ---- 3. いる行き先が閉まったら出される
        at(datetime(2026, 10, 20, 20, 0))
        S.start("out", place="mall")
        assert app.outdoor.closing() is None, "まだ開いている"
        at(datetime(2026, 10, 20, 21, 0))
        r = app.outdoor.closing()
        assert r and "閉まる時間" in r["text"] and app.presence.rec()["mode"] == "out" and app.presence.rec()["place"] == "town"
        assert r["solo"] and "モール" in r["solo"]["text"], "それまでの結果は出る"
        app.come_back()
        at(datetime(2026, 10, 20, 17, 0))
        st["cooldowns"] = {}
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": time.time() + 9e6}
        app.act("aquarium", cid)
        assert app.outdoor.current()["place"] == "aquarium"
        at(datetime(2026, 10, 20, 17, 30))
        r = app.outdoor.closing()
        assert r and "切り上げて帰った" in r["text"] and not app.outdoor.current() and B.mode(cid) == "home"
        assert app.log(cid)[-1]["action"] == "_closing"
        print("kicked out at closing: OK")

        # ---- 4. 約束は, 会う時刻に開いていること
        w = app.create_world("約束と営業時間")
        cid2 = app.settings["active_character"]
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        places.open_state = offline.open_state = REAL
        night = datetime.fromtimestamp(time.time() + 86400).replace(hour=22, minute=0, second=0, microsecond=0)
        day = night.replace(hour=13)
        try:
            app.appoint.propose(cid2, night.timestamp(), "aquarium", "aquarium")
            raise AssertionError("閉まっている時間に水族館の約束ができる")
        except ValueError as e:
            assert "閉まって" in str(e)
        if REAL("aquarium", day)["open"]:
            assert app.appoint.propose(cid2, day.timestamp(), "aquarium", "aquarium")["status"] == "asked"
        assert app.appoint.propose(cid2, night.timestamp() + 7200, "riverside", "walk")["status"] == "asked", "夜の河川敷は約束できる"
        print("appointments: OK")

        # ---- 5. 行動パターンの外出: 閉まっていれば行かない. 閉まる時刻まで
        O = app.offline
        tue = datetime(2026, 10, 20)
        app.save_settings({"offline": {"days": {"tue": [{"at": "00:00", "do": "sleep"}, {"at": "18:00", "do": "out", "place": "aquarium"},
                                                        {"at": "19:30", "do": "out", "place": "mall"}, {"at": "23:00", "do": "sleep"}]}}})
        app.life.player_state()["stamina"] = 100
        rep = O.simulate(tue.replace(hour=17).timestamp(), tue.replace(hour=23, minute=30).timestamp())
        tl = {x.get("place"): x for x in rep["timeline"] if x["do"] == "out"}
        assert tl["aquarium"]["skipped"] and "閉まっていた" in tl["aquarium"]["text"], tl["aquarium"]
        assert not tl["mall"]["skipped"] and "閉まる時間" in tl["mall"]["text"] and "1時間30分" in tl["mall"]["text"], tl["mall"]
        print("routine: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
