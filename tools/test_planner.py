"""あなたの予定 (core/planner.py) と, 画面を閉じていた間の決まる順番 (core/offline.py).

    python tools/test_planner.py
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

geo.INSTANT = True          # 移動の時間は tools/test_geo.py で


def at(date, hm):
    return datetime.strptime("%s %s" % (date, hm), "%Y-%m-%d %H:%M").timestamp()


def main():
    random.seed(4)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("予定")
        P, O, L = app.planner, app.offline, app.life
        now = time.time()
        d0 = datetime.fromtimestamp(now)
        tom = (d0 + timedelta(days=1)).strftime("%Y-%m-%d")
        day3 = (d0 + timedelta(days=3)).strftime("%Y-%m-%d")

        # ---- 1. 組める先の日数は段取りのスキルしだい. 何も組んでいなければ今までどおり
        assert not P.active()
        L.player_state()["skills"].update(work=10, budget=10)
        assert P.horizon_days() == 1
        try:
            P.add(day3, "10:00", {"do": "rest"})
            raise AssertionError("先の日まで組めてしまった")
        except ValueError as e:
            assert "まだ組めません" in str(e)
        L.player_state()["skills"].update(work=80, budget=70)
        assert P.horizon_days() == 4
        P.add(day3, "10:00", {"do": "rest"})
        print("組める日数: OK")

        # ---- 2. 過ぎた日の予定は消える
        yday = (d0 - timedelta(days=1)).strftime("%Y-%m-%d")
        P.rec()["items"].append({"id": "old", "date": yday, "at": "10:00", "do": "rest"})
        P.purge(now)
        assert not any(x["id"] == "old" for x in P.rec()["items"])
        P.rec()["items"] = []
        print("過ぎた日の予定: OK")

        # ---- 3. 決まる順番: 予定 → (できなければ) 未指定時コマンド (優先度順. できないものは飛ばす) → 設定の行動パターン → 何もしない
        P.add(tom, "03:00", {"do": "out", "place": "supermarket"})        # 夜中は閉まっている
        P.add(tom, "09:00", {"do": "out", "place": "supermarket"})        # 30 分で次の予定 → 切り上げ
        P.add(tom, "09:30", {"do": "chores"})
        P.set_fallback([{"do": "out", "place": "mall"}, {"do": "practice", "skill": "work"}])     # 夜中はモールも閉まっている
        t0, t1 = at(tom, "02:00"), at(tom, "12:00")
        L.player_state()["stamina"] = 100
        rep = O.simulate(t0, t1)
        tl = rep["timeline"]
        first = tl[0]
        assert first["plan"]["src"] == "fallback" and first["plan"]["why"] == "予定なし" and first["do"] == "practice", first
        night = next(x for x in tl if x["plan"] and x["plan"].get("at") == "03:00")
        assert night["plan"]["src"] == "fallback" and "閉まっていた" in night["plan"]["why"] and night["do"] == "practice", night
        shop = next(x for x in tl if x["plan"] and x["plan"].get("at") == "09:00")
        assert shop["plan"]["src"] == "plan" and shop["plan"]["cut"], shop
        ch = next(x for x in tl if x["plan"] and x["plan"].get("at") == "09:30")
        assert ch["plan"]["src"] == "plan" and ch["do"] == "chores"
        # 未指定時コマンドが無ければ設定の行動パターン. それも無ければ何もしない
        P.set_fallback([])
        P.rec()["items"] = []
        P.add(tom, "03:00", {"do": "out", "place": "supermarket"})
        rep = O.simulate(at(tom, "03:00"), at(tom, "05:00"))
        assert rep["timeline"][0]["plan"]["src"] == "routine", rep["timeline"][0]
        app.save_settings({"offline": {"enabled": False}})
        rep = O.simulate(at(tom, "03:00"), at(tom, "05:00"))
        assert rep and rep["timeline"][0]["plan"]["src"] == "none", rep
        app.save_settings({"offline": {"enabled": True}})
        print("決まる順番・切り上げ: OK")

        # ---- 4. 約束の時刻は約束が先 (組むときもぶつからないように). 閉じていた間に会えば, 良い影響は出にくい
        cid = next(c for c in app.chars if app.bonds.stage(c) != "live")
        app.bonds.set_stage(cid, "contact")
        x = {"id": "ap1", "cid": cid, "t": at(tom, "14:00"), "place": "cafe", "do": "cafe", "by": "me", "status": "set",
             "made": now, "plan": {"cancel_checked": True}}
        app.appoint.all().append(x)
        app.appoint.save()
        try:
            P.add(tom, "14:30", {"do": "rest"})
            raise AssertionError("約束とぶつかる予定を組めた")
        except ValueError as e:
            assert "約束" in str(e)
        P.rec()["items"] = []
        P.add(tom, "13:00", {"do": "out", "place": "park"})
        kinds = [(datetime.fromtimestamp(s).strftime("%H:%M"), k) for s, e, k, _ in P.slots(at(tom, "13:00"), at(tom, "18:00"))]
        assert ("14:00", "appoint") in kinds and kinds[0] == ("13:00", "plan"), kinds
        seen = {}
        real_act = app.act

        def spy(aid, cid=None, dress=None, opts=None):
            seen.update(opts or {})
            return real_act(aid, cid, dress=dress, opts=opts)
        app.act = spy
        rep = O.simulate(at(tom, "13:00"), at(tom, "18:00"))
        app.act = real_act
        ap = next(t for t in rep["timeline"] if t["do"] == "appoint")
        assert app.appoint.get("ap1")["status"] == "met" and seen.get("auto_weak"), (ap, seen)
        # 自動で過ごした分は, 良い影響が出にくい (効き目を 4 割に)
        real_realize = app.bonds.realize
        app.bonds.realize = lambda char, st, eff, aid, now, gift=None: (dict(eff), "")
        st = app.state(cid)
        gains = []
        for weak in (False, True):
            st["cooldowns"], st["override"], st["contacts"] = {}, None, []
            app.set_params({"mood": 50}, cid)
            app.act("message", cid, opts={"msg_kind": "thanks", "auto_weak": weak})
            st.pop("msg_pending", None)
            gains.append(st["params"]["mood"] - 50)
        app.bonds.realize = real_realize
        assert gains[1] <= gains[0], gains
        print("約束が先・自動で会う: OK", ap["text"][:30])

        # ---- 5. 画面を開いているとき: 予定の時刻になったら知らせて記録するだけ (何もしない)
        P.rec()["items"] = [{"id": "n1", "date": d0.strftime("%Y-%m-%d"), "at": (d0 - timedelta(minutes=3)).strftime("%H:%M"),
                             "do": "out", "place": "supermarket"}]
        mode0, money0 = app.presence.rec().get("mode"), L.player_state()["money"]
        msgs = P.live(time.time())
        assert msgs and "予定の時刻になった" in msgs[0], msgs
        assert app.presence.rec().get("mode") == mode0 and L.player_state()["money"] == money0, "何もしない"
        assert not P.live(time.time()), "一度だけ"
        assert any("予定の時刻になった" in e["text"] for e in app.solo.mylog()), "記録する"
        print("画面を開いているとき: OK")

        # ---- 6. 自動の応答: 方針どおり (効き目は弱く, 読み違えることも). 方針が無ければ無難な対応
        P.set_auto(street=None)
        assert O._auto_choice("call") == ("nod", False)
        P.set_auto(street="chat")
        picks = [O._auto_choice("call")[0] for _ in range(400)]
        assert 0.6 < picks.count("chat") / 400.0 < 0.9, picks.count("chat")
        assert O._auto_choice("sight")[0] in ("talk", "pass")
        # 弱さ: ばったりの効き目は半分
        app.bonds.realize = lambda char, st, eff, aid, now, gift=None: (dict(eff), "")
        st["params"]["mood"] = 50
        pend = {"kind": "char", "who": cid, "type": "call", "where": "公園", "with": None, "name": "", "t": now}
        app.street._weak = True
        app.street._resolve_char(pend, "chat", True, True, time.time())
        weak_gain = st["params"]["mood"] - 50
        st["params"]["mood"] = 50
        app.street._weak = False
        app.street._resolve_char(pend, "chat", True, False, time.time())
        full_gain = st["params"]["mood"] - 50
        app.bonds.realize = real_realize
        assert 0 < weak_gain < full_gain, (weak_gain, full_gain)
        # 届いたメッセージ: 返事の方針があれば自動で返す (トークに「自動」)
        P.set_auto(street="chat", reply="cheerful")
        app.state(cid)["approach"] = None
        app.presence.eagerness_apart = lambda ctx: 1.5
        app.presence.cfg()["approach_apart_rate_per_hour"] = 50
        out = []
        for _ in range(10):
            app.state(cid)["approach"] = None
            app.state(cid)["ap_last"] = {}
            app.set_params({"boredom": 70, "loneliness": 70, "affection": 60, "mood": 65}, cid)
            out = O._messages(at(tom, "10:00"), at(tom, "16:00"))
            if out:
                break
        assert out and out[0].get("auto_reply"), out
        assert any("自動" in it["text"] for it in app.chat.thread(cid)["items"] if it["who"] == "me")
        print("自動の応答: ばったりの効き目 %.1f / 手で %.1f, 読み違え %.0f%%" % (weak_gain, full_gain, 100 - picks.count("chat") / 4.0))

        # ---- 7. 何も組んでいなければ今までどおり (予定の印は付かない)
        P.rec()["items"], P.rec()["fallback"] = [], []
        P.set_auto(None, None)
        rep = O.simulate(at(tom, "15:00"), at(tom, "20:00"))
        assert rep and not any(t.get("plan") for t in rep["timeline"] if t["do"] != "appoint")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
