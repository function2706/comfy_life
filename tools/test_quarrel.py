"""意見が割れる・言い争い・仲直り (core/quarrel.py): 行き先で言い返される・押す / 譲る / 折衷案 / そらす・言い争いの間の
素っ気なさ・謝罪で収まる・時間で収まる・家事で反発されたら言い争いに・相手から謝る (許す / まだ許さない).

    python tools/test_quarrel.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, nori, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(81)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("言い合い")
        Q, A = app.quarrel, app.attach
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "live")
        char, st = app.char(cid), app.state(cid)
        a = app.action("walk")
        places = a["places"]
        hers = places[1]
        st["place_fun"] = {p: -10 for p in places}
        st["place_fun"][hers] = 10
        mine = min((p for p in places if p != hers), key=lambda p: app.appoint.place_weight(char, st, p))   # 相手の好みからいちばん遠い所
        assert app.bonds.together(cid)

        def home():                                  # お出かけから帰る
            st_ = app.state(cid)
            st_["cooldowns"] = {}
            try:
                app.act("go_home", cid)
            except ValueError:
                pass

        def setup(dev, mood):
            A.rec(char, st)["devotion"] = dev
            app.set_params({"mood": mood, "affection": 60}, cid)
            st["place_fun"] = {p: -10 for p in places}
            st["place_fun"][hers] = 10
            st.pop("disagree_last", None)
            st.pop("disagree", None)
            st["cooldowns"] = {}

        # ---- 1. 行き先: 相手の好みとずっと違えば, 言い返されることがある (自分優先・機嫌が悪いほど)
        dt = datetime.now()

        def rate(dev, mood, n=200):
            k = 0
            for _ in range(n):
                setup(dev, mood)
                k += Q.disagree(char, st, a, mine, time.time(), dt) is not None
            return k / float(n)
        r_hi, r_lo = rate(5, 30), rate(95, 75)
        assert r_hi > r_lo + 0.25, (r_hi, r_lo)
        none = 0
        for _ in range(30):                          # 相手のいちばん行きたい所を選べば, 言い返さない
            setup(5, 30)
            none += Q.disagree(char, st, a, hers, time.time(), dt) is None
        assert none == 30
        print("言い返される: OK | 自分優先で機嫌が悪い %.2f / 献身的で機嫌がいい %.2f" % (r_hi, r_lo))

        # 実際にお出かけを選ぶと, 言い返されたら出かけずに止まる (知らせが出る)
        for _ in range(50):
            setup(0, 20)
            r = app.act("walk", cid, opts={"place": mine})
            if r.get("disagree"):
                break
        assert r.get("disagree") and Q.pending()["kind"] == "disagree"
        print("お出かけが止まる: OK |", r["entry"]["text"].replace("\n", " "))

        # ---- 2. 出方: 譲る (相手の行き先で出かける・帳簿にあなたが尽くした) / 押す (渋々か言い争い) / 折衷案 / そらす
        led = A.rec(char, st)["ledger"]["me"]
        out = Q.respond("yield")
        assert out["key"] == "yield_happy" and out.get("act") and A.rec(char, st)["ledger"]["me"] > led
        home()
        seen = set()
        for _ in range(40):
            setup(0, 20)
            st.pop("fight", None)
            if not Q.disagree(char, st, a, mine, time.time(), dt):
                continue
            seen.add(Q.respond("push")["key"])
            home()
        assert {"push_unhappy", "push_fight"} <= seen, seen
        setup(0, 20)
        while not Q.disagree(char, st, a, mine, time.time(), dt):
            setup(0, 20)
        out = Q.respond("compromise")
        assert out["key"] in ("compromise_ok", "compromise_meh") and out.get("act")
        home()
        setup(0, 20)
        while not Q.disagree(char, st, a, mine, time.time(), dt):
            setup(0, 20)
        n0 = len(app.log(cid))
        out = Q.respond("dodge")
        assert out["key"] == "dodge" and not out.get("act")
        print("出方: OK |", sorted(seen))

        # ---- 3. 言い争いの間: 話しかけてこない・ノリが低い・返事が素っ気ない
        st = app.state(cid)
        st.pop("fight", None)
        ctx = app.context(char, st, datetime.now())
        app.set_params({"mood": 70, "boredom": 60, "loneliness": 60}, cid)
        ctx = app.context(char, st, datetime.now())
        e0, n_0 = app.presence.eagerness(ctx), sum(nori.base(app, char, st, time.time()) for _ in range(100))
        Q.start(char, st, time.time(), "行き先", her_fault=False)
        ctx = app.context(char, st, datetime.now())
        assert ctx["fight"] and app.presence.eagerness(ctx) < e0 * 0.5
        assert sum(nori.base(app, char, st, time.time()) for _ in range(100)) < n_0 - 1000
        cold = sum(Q.cold_reply(st, "smalltalk", time.time()) for _ in range(200))
        assert 80 < cold < 160 and not Q.cold_reply(st, "apology", time.time())
        print("言い争いの間: OK | 素っ気ない返事 %d / 200" % cold)

        # ---- 4. 収まる: 謝って言い争いの理由が解決した / 時間がたった
        for r_ in st["reasons"]:
            if r_.get("action") == "_fight":
                r_["resolved"] = True
        Q.tick(char, st, time.time())
        assert not st.get("fight")
        Q.start(char, st, time.time(), "行き先", her_fault=False)
        Q.tick(char, st, st["fight"]["until"] + 1)
        assert not st.get("fight") and all(r_.get("resolved") for r_ in st["reasons"] if r_.get("action") == "_fight")
        print("収まる: OK")

        # ---- 5. 家事でたしなめて反発された → 言い争い (相手に非). 献身的なら相手から謝ってくる: 許す / まだ許さない
        A.rec(char, st)["devotion"] = 100.0
        got = 0
        for _ in range(30):
            st.pop("fight", None)
            st["chores_fight"] = time.time()
            Q.tick(char, st, time.time())
            got += bool(st["fight"].get("sorry_at"))
        assert got > 15 and st["fight"]["about"] == "家事" and st["fight"]["her_fault"]
        st["fight"]["sorry_at"] = time.time() - 1
        Q.tick(char, st, time.time())
        assert Q.pending()["kind"] == "sorry"
        out = Q.respond("not_yet")
        assert out["key"] == "not_forgiven" and st.get("fight")
        st["fight_sorry"] = time.time()
        out = Q.respond("forgive")
        assert out["key"] == "forgiven" and not st.get("fight")
        print("相手から謝る: OK | 献身的な相手が謝ってくる %d / 30" % got)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
