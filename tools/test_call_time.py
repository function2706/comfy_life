"""電話の分だけ時間を使う (S8 / A23 の 1 段目): 話している間 (実時間) は, ほかのことができない.
長さは, あなたの約束・組んだ予定・相手の次の用事や寝る時刻・あなたの体力の手前で切り上げる. 「電話を切る」で早めに終えられる (一時データ).

    python tools/test_call_time.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, planner, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def must_fail(fn, word):
    try:
        fn()
    except ValueError as e:
        assert word in str(e), e
        return str(e)
    raise AssertionError("通ってしまった: %s" % word)


def main():
    random.seed(8)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("電話の時間")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        app.bonds.end() if app.bonds.together(cid) else None
        char, st = app.char(cid), app.state(cid)
        sched = app.scheduled_scene
        free = lambda c, d: dict(sched(c, d), away=True, busy=False, asleep=False)       # noqa: E731
        app.scheduled_scene = free
        app._call_missed = lambda *a, **k: None
        C = app.chat

        def fresh():
            st["contacts"], st["cooldowns"] = [], {}
            st.pop("msg_pending", None)
            st.pop("nori", None)
            app.presence.rec().pop("call", None)
            app.set_params({"mood": 75, "affection": 65, "trust": 60, "boredom": 60, "loneliness": 70, "sleepiness": 10, "energy": 80}, cid)

        # ---- 1. かけると, 話している間は通話中: ほかの連絡・一人ですること・ゲームはできない
        fresh()
        t0 = time.time()
        r = app.phone_call(cid, "smalltalk")
        assert r.get("call"), r
        m = r["call"]["mins"]
        c = app.call_now()
        assert c and c["cid"] == cid and abs(c["until"] - (c["t"] + m * 60)) < 1 and c["t"] >= t0, c
        v = app.call_view()
        assert v["left"] in (m, m + 1) and v["name"] == char["name"], v
        for w in engine.App.BLOCK_KINDS:
            assert "電話で話している途中" in (app.blocked(w) or ""), (w, app.blocked(w))
        must_fail(lambda: app.phone_call(cid, "smalltalk"), "電話で話している途中")
        must_fail(lambda: C.send(cid, "smalltalk"), "電話で話している途中")
        must_fail(lambda: app.solo.start("rest"), "電話で話している途中")
        print("通話中:", m, "分 /", app.blocked("social"))

        # ---- 2. 電話を切る: トークの通話時間を実際の分に直す. 切ったあとは連絡できる
        sys_t = c["sys_t"]
        app.presence.rec()["call"]["t"] -= 4 * 60          # 4 分話したところで
        out = app.call_end()
        assert out["mins"] == 4, out
        it = next(x for x in C.load(cid)["items"] if x.get("who") == "sys" and x.get("t") == sys_t)
        assert it["text"].startswith("📞 電話で話した（4分ほど。") and it["text"].endswith("あなたから切り上げた）"), it["text"]
        assert app.call_now() is None and app.call_view() is None
        assert not any("電話" in (app.blocked(w) or "") for w in engine.App.BLOCK_KINDS)
        must_fail(app.call_end, "途中ではありません")
        print("切った:", it["text"])

        # ---- 3. 話し終えた (時刻が過ぎた): 何もしなくても通話中ではなくなる
        fresh()
        r = app.phone_call(cid, "smalltalk")
        app.presence.rec()["call"]["until"] = time.time() - 1
        assert app.call_now() is None and app.blocked("social") is None
        must_fail(app.call_end, "途中ではありません")
        assert "call" not in app.presence.rec()
        print("話し終えた: OK")

        # ---- 4. 長さの切り上げ (_call_limit)
        now = time.time()
        mins, cut = app._call_limit(char, st, now, 40)
        assert (mins, cut) == (40, None), (mins, cut)
        # 約束: 出かける支度 (APPOINT_LEAD) の手前まで
        ap = app.appoint.all()
        lead = planner.APPOINT_LEAD
        ap.append({"id": "t1", "cid": cid, "t": now + lead + 15 * 60, "status": "set"})
        mins, cut = app._call_limit(char, st, now, 40)
        assert mins == 15 and cut == "約束がある", (mins, cut)
        ap[-1]["t"] = now + lead + 60                      # すぐ支度: ひとことふたことだけ
        mins, cut = app._call_limit(char, st, now, 40)
        assert mins <= 2 and cut == "約束がある", (mins, cut)
        ap[-1]["status"] = "cancelled"                     # 取りやめた約束は見ない
        assert app._call_limit(char, st, now, 40) == (40, None)
        ap.pop()
        # 組んだ予定の時刻
        items = app.planner.rec()["items"]
        at = datetime.fromtimestamp(now + 12 * 60 + 30)
        items.append({"id": "p1", "date": at.date().isoformat(), "at": at.strftime("%H:%M"), "do": "rest"})
        mins, cut = app._call_limit(char, st, now, 40)
        assert 11 <= mins <= 13 and cut == "予定の時刻が近い", (mins, cut)
        items.pop()
        # 相手が寝る時刻・次の用事
        app.scheduled_scene = lambda c, d: dict(free(c, d), asleep=d.timestamp() >= now + 10 * 60 - 1)
        mins, cut = app._call_limit(char, st, now, 40)
        assert mins == 10 and cut == "%sが寝る時間になる" % char["name"], (mins, cut)
        app.scheduled_scene = lambda c, d: dict(free(c, d), busy=d.timestamp() >= now + 20 * 60 - 1)
        mins, cut = app._call_limit(char, st, now, 40)
        assert mins == 20 and cut == "%sに次の用事がある" % char["name"], (mins, cut)
        app.scheduled_scene = free
        # あなたの体力
        ps = app.life.player_state()
        s0 = ps.get("stamina", 100)
        ps["stamina"] = 10
        mins, cut = app._call_limit(char, st, now, 40)
        assert mins == 24 and cut == "あなたが疲れていた", (mins, cut)
        assert app._call_limit(char, st, now, 8) == (8, None)      # 短い電話は, そのまま
        ps["stamina"] = s0
        print("切り上げ: 約束・予定・相手の寝る時刻・次の用事・体力 OK")

        # ---- 5. かけたときに切り上げが付くと, トークにも残る
        fresh()
        ap.append({"id": "t2", "cid": cid, "t": time.time() + lead + 5 * 60, "status": "set"})
        r = app.phone_call(cid, "smalltalk")
        assert r["call"]["cut"] == "約束がある" and r["call"]["mins"] <= 5, r["call"]
        it = [x for x in C.load(cid)["items"] if x.get("who") == "sys" and x["text"].startswith("📞 電話で話した（")][-1]
        assert "約束があるので、早めに切り上げた" in it["text"], it["text"]
        ap.pop()
        print("トーク:", it["text"])

        # ---- 6. 出なかった電話は, 通話中にならない
        fresh()
        app.scheduled_scene = lambda c, d: dict(free(c, d), asleep=True)
        del app._call_missed
        r = app.phone_call(cid, "smalltalk")
        assert not r.get("call") and app.call_now() is None, r
        app.scheduled_scene = free
        print("出なかった: 通話中にならない OK")

        # ---- 7. 開き直し (保存から読み直し) でも通話中のまま
        fresh()
        app._call_missed = lambda *a, **k: None
        r = app.phone_call(cid, "smalltalk")
        app2 = engine.App()
        assert app2.call_now() and app2.call_now()["cid"] == cid
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
