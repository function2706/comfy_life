"""献身度・依存度の新しい振る舞い (第 2 段階): 引き止め・束縛・「今どこ？」・離れたくない・距離を置く/気づかう・
予定をずらして合わせる・自分の都合で日を動かす・しょっちゅうのおねだり.

    python tools/test_attach2.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import appoint as APm, engine, msgreply, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(33)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("関わり方2")
        A = app.attach
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        char["persona_id"] = "teinei"

        def setv(**kw):
            r = A.rec(char, st)
            r.update(kw)
            r["day"] = {}

        def reaction(aid, **params):
            ctx = app.context(char, st, datetime.now())
            ctx.update(params)
            return app.pick_reaction(app.action(aid), ctx)

        # ---- 1. 帰り際・出かけるとき: 依存しているほど引き止める. 依存して自分優先なら, 出かける先を詮索する
        setv(dependence=85.0, devotion=30.0)
        base = {"asleep": False, "away": False, "loneliness": 30}
        assert "誰と" in reaction("go_out", **base)["text"]
        assert "もうちょっとだけ" in reaction("go_leave", **base)["text"]
        assert "泊まって" in reaction("leave_visit", **base)["text"]
        assert "帰りたくない" in reaction("see_off", **base)["text"]
        setv(dependence=85.0, devotion=60.0)
        assert "誰と" not in reaction("go_out", **base)["text"]          # 献身的なら詮索しない (引き止めはする)
        setv(dependence=40.0, devotion=30.0)
        assert "もうちょっとだけ" not in reaction("go_leave", **base)["text"]
        print("引き止め・出かける先の詮索: OK")

        # ---- 2. 離れたくない (そばで): 依存度がとても高いときだけ
        from core import cond
        need = app.presence.find("need_you")
        ctx = app.context(char, st, datetime.now())
        ctx.update(loneliness=60, affection=70, dependence=85)
        assert cond.check(need["when"], ctx)
        ctx.update(dependence=60)
        assert not cond.check(need["when"], ctx)
        print("離れたくない: OK")

        # ---- 3. 「今どこ？誰と？」(離れていて, あなたが出かけている・仕事中): 依存していて自分優先なとき. 返事は専用の受け止め
        app.bonds.set_stage(cid, "contact")
        where = app.presence.find("msg_where")
        ctx = app.context(char, st, datetime.now())
        ctx.update(dependence=80, devotion=30, affection=60, presence="out")
        assert cond.check(where["when"], ctx)
        ctx.update(presence="here")
        assert not cond.check(where["when"], ctx)
        st["approach"] = None
        app.set_params({"mood": 60, "affection": 60, "trust": 55}, cid)
        app.force_approach("msg_where", cid)
        ids = [c["id"] for c in app.presence.pending_view(char, st)["choices"]]
        assert ids[0] == "expand" and "curt" in ids
        r = app.answer_approach("reply", cid, "expand")
        res = r["entry"]["reply"]["result"]
        assert r["entry"]["text"] == (app.persona_text(char, "msgr.msg_where." + res) or msgreply.LINES["msgr.msg_where." + res])
        good = {"expand": 0, "curt": 0}
        for k in good:
            for _ in range(40):
                good[k] += msgreply.judge(char, st, "msg_where", k) == "good"
        assert good["expand"] > good["curt"] + 10, good
        print("「今どこ？」: OK | 正直に答えて良く受け止められた %d / なんで？ %d (40 回中)" % (good["expand"], good["curt"]))

        # ---- 4. 連絡が続いたとき: 依存度が低いと距離を置く / 献身的で依存度が低いと気づかう (一日に一度まで)
        def space(dep, dev, n=1):
            setv(dependence=dep, devotion=dev)
            got = []
            for _ in range(n):
                st.pop("space_day", None)
                ctx = app.context(char, st, datetime.now())
                ctx["contacts_24h"] = 99
                got.append(app.chat._space(char, st, "smalltalk", time.time(), ctx))
            return got
        assert "want_space" in space(10, 40, 30) and "own_time" not in space(10, 40, 30)
        assert "own_time" in space(20, 80, 30)
        assert not any(space(60, 50, 30))
        st.pop("space_day", None)
        setv(dependence=10, devotion=40)
        ctx = app.context(char, st, datetime.now())
        ctx["contacts_24h"] = 99
        first = [app.chat._space(char, st, "smalltalk", time.time(), ctx) for _ in range(30)]
        assert sum(1 for x in first if x) == 1, first
        print("距離を置く・気づかう: OK")

        # ---- 5. 約束: 献身的なら予定をずらして合わせた (専用の返事) / 自分優先なら, 前の日ごろに日を動かしたいと言ってくる
        AP = app.appoint
        DO = AP.dos_at(cid, "cafe")[0]["id"]
        real = app.scheduled_scene
        app.scheduled_scene = lambda c, d: {"away": True, "busy": True, "asleep": False}
        try:
            setv(devotion=100.0)
            keys = []
            for i in range(40):
                x = {"id": "r%d" % i, "cid": cid, "t": time.time() + 86400, "place": "cafe", "do": DO,
                     "by": "me", "status": "asked", "made": time.time(), "rounds": APm.COUNTER_MAX}
                AP.all().append(x)
                keys.append(AP.reply(char, st, {"appoint": x["id"]}, time.time(), {})[0])
        finally:
            app.scheduled_scene = real
        # 予定と重なっても 2 割は気にせず受ける (以前どおりの appoint_yes). 合わせてくれたときは専用の返事
        assert keys.count("appoint_rearranged") >= 8 and all(x.get("rearranged") for x in AP.all() if x["id"].startswith("r")
                                                             and x["status"] == "set" and keys[int(x["id"][1:])] == "appoint_rearranged"), keys
        print("予定をずらして合わせた: OK | %d / 40" % keys.count("appoint_rearranged"))

        setv(devotion=0.0)
        moves = sum(AP._plan(char, st)["move"] for _ in range(400))
        setv(devotion=80.0)
        assert sum(AP._plan(char, st)["move"] for _ in range(400)) == 0 and moves > 60, moves
        now = time.time()
        x = {"id": "mv", "cid": cid, "t": now + 10 * 3600, "place": "cafe", "do": DO, "by": "me", "status": "set",
             "made": now, "rounds": 0, "plan": {"noshow": False, "late": 0, "cancel_checked": False, "move": True}}
        AP.all()[:] = [x]
        app.appoint.live(now) if hasattr(app.appoint, "live") else None
        moved = x["status"] == "offered"
        if moved:
            it = [i for i in app.chat.load(cid)["items"] if i.get("kind") == "appoint_move_mine"]
            assert it and x["by"] == "her" and x["t"] != now + 10 * 3600
        print("自分の都合で日を動かす: OK | 自分優先 %d / 400・動かせる別の時間があれば %s" % (moves, moved))

        # ---- 6. しょっちゅうのおねだり: 2 週間以内にも頼んでいれば, 頼み方が変わる
        evs = [{"id": "borrow", "weight": 1, "tell": "お金を貸してほしい", "request": {"kind": "money", "amount": 3000}}]
        realev = app.events
        app.events = evs
        try:
            st["events"], st["request"] = [], None
            app.life.happen(char, st, time.time(), {}, "borrow")
            first = st["request"]["text"]
            st["request"] = None
            for e in st["events"]:
                e["t"] -= 3 * 86400
            app.life.happen(char, st, time.time(), {}, "borrow")
            again = st["request"]["text"]
        finally:
            app.events = realev
        assert first == "お金を貸してほしい" and again != first, (first, again)
        print("しょっちゅうのおねだり: OK |", again)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
