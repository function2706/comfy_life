"""別れぎわ (解散して家に帰る・相手の家から帰る・送っていく): 相手が応じるか (core/parting.py).
- もっと一緒にいたいかは, 機嫌・好感度・寂しさ・依存度・会ってからの長さ・疲れ・時間帯で決まる
- いたくても口に出すかは, 性格と仲. 献身的なほど飲み込む (応じて, 名残惜しそう)
- 口に出せば引き止める (その場は別れない). そのあと 30 分のうちにもう一度言えば, それでも帰る (寂しがる)
- 引き止めの返事は, 同じ会っている間だけ (会い直したら, また初めから)
- 別れて離れると, 離席の画面に最後のやりとりが出る (移動中の画面がセリフを覆わない)
(一時データ)

    python tools/test_parting.py
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
from core import engine, parting as PT, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
APPT = {"appointment": "test"}


def main():
    random.seed(11)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("別れぎわ")
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        B = app.bonds
        B.set_stage(cid, "visit")
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        app.life.player_state()["money"] = 100000

        def meet(**params):
            PT.FIXED = None
            st["cooldowns"], st["override"] = {}, None
            st.pop("part_hold", None)
            if B.mode(cid):
                B.end(go_home=False)
            app.presence.back(time.time())
            app.set_params(dict({"affection": 75, "mood": 75, "energy": 80, "loneliness": 30, "trust": 60}, **params), cid)
            app.act("cafe", cid, opts=APPT)
            assert B.mode(cid) == "meet"

        def ago(sec):                   # 会ってから sec 秒たったことに
            B.rec()["with"]["t"] = time.time() - sec

        # ---- 1. もっといたいか: 会ったばかりで機嫌がいい / 長く会って疲れている / くたくた
        meet()
        ago(10 * 60)
        w_fresh = app.parting.want(char, st, "go_home", time.time())
        meet(energy=30, mood=55)
        ago(5 * 3600)
        w_long = app.parting.want(char, st, "go_home", time.time())
        meet(energy=15)
        w_done = app.parting.want(char, st, "go_home", time.time())
        assert w_fresh > 0.6 and w_long < 0.1 and w_done == 0, (w_fresh, w_long, w_done)
        print("いたいか: OK | 会ったばかり %.2f / 5 時間で疲れ %.2f / くたくた %.2f" % (w_fresh, w_long, w_done))

        # ---- 2. 口に出すか: 献身的なほど飲み込む. 同じ人でも, 遠慮がちな性格ほど言わない
        att = app.attach.rec(char, st)
        att["devotion"] = 20
        v_low = app.parting.voice(char, st)
        att["devotion"] = 90
        v_high = app.parting.voice(char, st)
        att["devotion"] = 50
        pid = char.get("persona_id")
        char["persona_id"] = "genki"
        v_genki = app.parting.voice(char, st)
        char["persona_id"] = "uchiki"
        v_uchiki = app.parting.voice(char, st)
        char["persona_id"] = pid
        assert v_low > v_high + 0.1 and v_genki > v_uchiki + 0.2, (v_low, v_high, v_genki, v_uchiki)
        print("口に出すか: OK | 献身 低 %.2f / 高 %.2f, 元気 %.2f / 人見知り %.2f" % (v_low, v_high, v_genki, v_uchiki))

        # ---- 3. 分かれ方の割合: 会ったばかりの楽しいデートなら, 多くは引き止めるか名残惜しい. 疲れた長いデートなら, ほとんど応じる
        def dist(n=400):
            c = {"ok": 0, "hold": 0, "reluctant": 0}
            for _ in range(n):
                st.pop("part_hold", None)
                c[app.parting.decide(char, st, "go_home", time.time())] += 1
            return c
        meet()
        ago(10 * 60)
        d_fresh = dist()
        meet(energy=30, mood=55)
        ago(5 * 3600)
        d_long = dist()
        assert d_fresh["ok"] < 160 and d_fresh["hold"] > 60 and d_fresh["reluctant"] > 30, d_fresh
        assert d_long["ok"] > 360, d_long
        print("割合: OK | 楽しい会ったばかり %s / 疲れた長いデート %s" % (d_fresh, d_long))

        # ---- 4. 引き止め → その場は別れない → もう一度言えば, それでも帰る (寂しがる)
        meet()
        PT.FIXED = "hold"
        r = app.act("go_home", cid)
        PT.FIXED = None
        assert B.mode(cid) == "meet" and (st["override"] or {}).get("outing"), "引き止められたのに解散した"
        assert app.presence.rec()["mode"] == "none"
        hold_text = r["entry"]["text"]
        conf = app.available(char, st, __import__("datetime").datetime.now())["go_home"].get("confirm") or ""
        assert "それでも" in conf, conf
        m0 = st["params"]["mood"]
        r = app.act("go_home", cid)
        assert B.mode(cid) is None and not st.get("part_hold"), "もう一度言っても帰れない"
        assert st["params"]["mood"] < m0, (m0, st["params"]["mood"])
        insist_text = r["entry"]["text"]
        print("引き止め: OK | 「%s」→ それでも帰る「%s」（機嫌 %.0f → %.0f）" % (hold_text, insist_text, m0, st["params"]["mood"]))

        # ---- 5. 会い直したら, 引き止めの返事は持ち越さない
        meet()
        PT.FIXED = "hold"
        app.act("go_home", cid)
        PT.FIXED = None
        B.end(go_home=False)
        st["override"] = None
        app.presence.back(time.time())
        st["cooldowns"] = {}
        app.act("cafe", cid, opts=APPT)
        B.rec()["with"]["t"] += 1
        assert not app.parting.pending(char, st, "go_home", time.time())
        assert not app.available(char, st, __import__("datetime").datetime.now())["go_home"].get("confirm")
        print("会い直し: OK")

        # ---- 6. 飲み込んで応じる: 別れる. 名残惜しいセリフ
        meet()
        PT.FIXED = "reluctant"
        r = app.act("go_home", cid)
        assert B.mode(cid) is None
        rel_text = r["entry"]["text"]
        print("名残惜しい: OK | 「%s」" % rel_text)

        # ---- 7. 相手の家から帰る / あなたの家から送っていく: 引き止めればその場にいる
        for aid, mode, start in (("leave_visit", "visit", "visit"), ("see_off", "guest", "guest")):
            PT.FIXED = None
            st["cooldowns"], st["override"] = {}, None
            st.pop("part_hold", None)
            if B.mode(cid):
                B.end(go_home=False)
            app.presence.back(time.time())
            B.start(cid, start, time.time())
            PT.FIXED = "hold"
            r = app.act(aid, cid)
            assert B.mode(cid) == mode, (aid, B.mode(cid))
            PT.FIXED = None
            r2 = app.act(aid, cid)
            assert B.mode(cid) is None, aid
            print("%s: OK | 「%s」→「%s」" % (aid, r["entry"]["text"], r2["entry"]["text"]))

        # ---- 8. 別れて家へ向かうと, 離席の画面に最後のやりとり
        from core import geo as G
        G.INSTANT = False
        meet()
        PT.FIXED = "ok"
        r = app.act("go_home", cid)
        pv = app.presence.view(time.time())
        assert pv["mode"] == "out" and pv.get("travel"), pv
        lw = pv.get("last_words") or {}
        assert lw.get("text") == r["entry"]["text"] and lw.get("name") == char["name"], (lw, r["entry"]["text"])
        app.presence.back(time.time())
        app.presence.declare("out", time.time() + 10)
        assert not app.presence.view(time.time() + 11).get("last_words"), "あとの外出にまで出る"
        print("最後のやりとり: OK | %s「%s」" % (lw["name"], lw["text"]))
    finally:
        PT.FIXED = None
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK")


if __name__ == "__main__":
    main()
