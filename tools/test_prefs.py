"""あなたの好みの記憶と, 相手からの働きかけ (A44 段 1. core/prefs.py・core/presence.py・engine.learn_request / movie_genre).

覚える・薄れる (半減 30 日)・時刻の無い古い鍵が消えない・機嫌が悪いと効かない・世話焼きほど汲む・
頼んだことを覚える (ふれあい・映画・ジャンル・行き先・ゲーム) / 相手からの誘いに応じたときは覚えない・
覚えてはじめて出る働きかけ・多く頼むほど出やすいが確定しない・直近に出たものは下がる・
一緒に観る映画のジャンルで受け止めが揺れる・誘う映画は相手の苦手を選ばない・「もう一回」で覚えたゲームが始まる・
よく誘う行き先・疲れていると座れる店に寄る・本人の服選びが一日の中で変わらない.

    python tools/test_prefs.py
"""
import collections
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from core import engine, prefs, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
DAY = 86400.0


def main():
    random.seed(44)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        P = app.presence
        cid = "hina"
        char, st = app.chars[cid], app.state(cid)
        free = lambda: st.update(override={"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": 9e12})  # noqa: E731
        free()
        app.set_params({"affection": 90, "trust": 80, "heart": 60, "mood": 70, "sleepiness": 0, "health": 90,
                        "loneliness": 60, "boredom": 60, "energy": 80})
        assert app.bonds.together(cid)
        now = time.time()

        # ---- 1. 覚える・薄れる・上限・古い鍵
        s = {"params": {"mood": 60}}
        prefs.learn(s, "act:kiss", 1.0, now)
        prefs.learn(s, "act:kiss", 1.0, now)
        assert prefs.pref(s, "act:kiss", now) == 2.0
        assert abs(prefs.pref(s, "act:kiss", now + 30 * DAY) - 1.0) < 1e-6, "半減期 30 日"
        prefs.learn(s, "act:kiss", 1.0, now + 30 * DAY)          # 薄れた値に足す
        assert abs(prefs.pref(s, "act:kiss", now + 30 * DAY) - 2.0) < 1e-6
        for _ in range(30):
            prefs.learn(s, "act:hug", 1.0, now)
        assert prefs.pref(s, "act:hug", now) == 10.0, "上限 10"
        s2 = {"prefs": {"pose:peace": 4.0}}                       # この仕組みより前に覚えた鍵 (時刻なし)
        assert prefs.pref(s2, "pose:peace", now) == 4.0, "古い鍵はいきなり消えない"
        t0 = s2["prefs_t"]["pose:peace"]
        prefs.pref(s2, "pose:peace", now + 5)
        assert s2["prefs_t"]["pose:peace"] == t0, "時刻は一度だけ入れる"
        assert abs(prefs.pref(s2, "pose:peace", now + 30 * DAY) - 2.0) < 1e-6, "今日から薄れ始める"
        assert prefs.pref(s, "act:*", now) == 10.0 and prefs.best(s, "act:", now)[0] == "act:hug"
        print("覚える・薄れる: ok")

        # ---- 2. 汲み方: 機嫌が悪いと効かない・世話焼きほど汲む・範囲
        st.setdefault("prefs", {})
        prefs.learn(st, "act:shoulder_rub", 10.0, now)
        f_good = prefs.factor(app, char, st, "act:shoulder_rub", now)
        st["params"]["mood"] = 30
        assert prefs.factor(app, char, st, "act:shoulder_rub", now) == 1.0, "機嫌が悪いと汲まない"
        st["params"]["mood"] = 70
        assert 1.0 < f_good <= prefs.F_MAX
        carer = app.traits(char).get("carer", 0.3)
        app.traits(char)["carer"] = 0.9
        f_carer = prefs.factor(app, char, st, "act:shoulder_rub", now)
        app.traits(char)["carer"] = 0.1
        assert prefs.factor(app, char, st, "act:shoulder_rub", now) < f_carer, "世話焼きほど汲む"
        app.traits(char)["carer"] = carer
        st["prefs"].pop("act:shoulder_rub")
        print("汲み方: ok (好み 10 で x%.2f)" % f_good)

        # ---- 3. 頼んだことを覚える
        st["cooldowns"] = {}
        app.act("shoulder_rub", cid)
        assert round(prefs.pref(st, "act:shoulder_rub"), 3) == 1.0
        free()
        st["cooldowns"] = {}
        app.act("hold_hands", cid)
        assert round(prefs.pref(st, "act:hold_hands"), 3) == 1.0
        free()
        st["cooldowns"] = {}
        st["tastes"] = {"horror": -0.9, "romance": 0.9}
        r = app.act("movie", cid, opts={"pick": "romance"})
        assert round(prefs.pref(st, "act:movie"), 3) == 1.0 and round(prefs.pref(st, "genre:romance"), 3) == 1.0
        assert "恋愛" in (r["entry"]["text"] + str(app.topics.view(cid))), "一緒に観たジャンルが話題に"
        free()
        st["cooldowns"] = {}
        app.act("movie", cid)                                # おまかせ: ジャンルは覚えない (相手が選んだ)
        assert round(prefs.pref(st, "act:movie"), 3) == 2.0 and round(sum(v for k, v in st["prefs"].items() if k.startswith("genre:")), 3) == 1.0
        free()
        st["cooldowns"] = {}
        app.act("movie", cid, opts={"approach": True, "genre": "romance"})     # 相手からの誘いに応じた: 覚えない
        assert round(prefs.pref(st, "act:movie"), 3) == 2.0
        free()
        print("頼んだことを覚える: ok")

        # ---- 4. 一緒に観る映画の受け止め: 好みで揺れるが確定しない
        tally = {}
        for taste in (0.9, 0.3, -0.9):
            st["tastes"] = {"action": taste}
            c = collections.Counter()
            for _ in range(400):
                ctx, o = {}, {"pick": "action"}
                app.movie_genre(char, st, o, ctx)
                c[ctx["movie_feel"]] += 1
            tally[taste] = c
        assert tally[0.9]["like"] > 300 and tally[-0.9]["dislike"] > 300
        assert tally[0.3]["like"] > 50 and tally[0.3]["ok"] > 50, "ほどほどに好きなら, 日によって揺れる"
        assert tally[0.9]["like"] < 400 or tally[0.9]["ok"] + tally[0.9]["dislike"] == 0
        print("映画の受け止め:", {k: dict(v) for k, v in tally.items()})

        # ---- 5. 誘う映画のジャンルは, 相手の苦手を選ばない. あなたの好みに寄る
        st["tastes"] = {"horror": -0.8, "sports": -0.5}
        st["prefs"]["genre:anime"] = 10.0
        st.setdefault("prefs_t", {})["genre:anime"] = now
        picks = collections.Counter(P._pick_genre(char, st, now)[0] for _ in range(600))
        assert not picks["horror"] and not picks["sports"], picks
        assert picks["anime"] > 600 / 7, picks
        print("誘う映画のジャンル:", dict(picks))

        # ---- 6. 覚えてはじめて出る働きかけ (min_pref) と, 相手からするふれあいの条件
        ctx = app.context(char, st, datetime.fromtimestamp(now))
        fs = P.find("fond_shoulder")
        st["prefs"]["act:shoulder_rub"] = 1.0
        assert not P._likes_ok(char, st, fs, ctx, now), "好みが浅いうちは出ない"
        st["prefs"]["act:shoulder_rub"] = 3.0
        assert P._likes_ok(char, st, fs, ctx, now)
        fk = P.find("fond_kiss")
        st["prefs"]["act:kiss"] = 5.0
        st["prefs_t"]["act:kiss"] = now
        assert P._likes_ok(char, st, fk, ctx, now)
        age = char.get("age")
        char["age"] = 16
        assert not P._likes_ok(char, st, fk, ctx, now), "キスは大人どうしだけ"
        char["age"] = age
        print("覚えてはじめて出る: ok")

        # ---- 7. 多く頼むほど出やすいが, 確定しない. 直近に出たものは下がる
        def share(pv, n=160):
            hit = 0
            for _ in range(n):
                st["approach"] = None
                st["ap_last"] = {}
                st["prefs"]["act:shoulder_rub"] = pv
                st["prefs_t"]["act:shoulder_rub"] = time.time()
                e = P.fire(char, st, time.time(), ctx)
                hit += bool(e and st["approach"] and st["approach"]["id"] == "fond_shoulder")
            st["approach"] = None
            return hit / float(n)
        lo, hi = share(2.5), share(10.0)
        print("肩をもんでほしい の出る割合: 好み 2.5 → %.2f / 10 → %.2f" % (lo, hi))
        assert 0 < hi < 0.6 and hi > lo, "多く頼むほど出やすいが, ほかの働きかけも出る"
        st["ap_last"] = {}                  # 上のくじで出た印を消してから
        w0 = P.like_weight(char, st, fs, now)
        st["ap_last"] = {"fond_shoulder": now - 3600}
        assert abs(P.like_weight(char, st, fs, now) - w0 * P.RECENT_W) < 1e-9, "直近に出たものは下げる"
        st["ap_last"] = {}

        # ---- 8. 「この前の〇〇、もう一回」: 覚えたゲームを始める (応じても覚えない)
        free()
        st["game"] = None
        app.games.start("reversi", cid)
        st["game"] = None
        app.games.start("reversi", cid)
        st["game"] = None
        assert round(prefs.pref(st, "game:reversi"), 3) == 2.0
        st["params"]["boredom"] = 70
        ctx = app.context(char, st, datetime.now())
        assert P._pick_game(char, st, ctx, now) == "reversi"
        st["approach"] = None
        e = P.fire(char, st, time.time(), ctx, force="play_again")
        assert e and "リバーシ" in e["text"] or "reversi" in str(st["approach"]), e and e["text"]
        r = app.answer_approach("accept", cid)
        assert st.get("game") and st["game"]["id"] == "reversi", r
        assert round(prefs.pref(st, "game:reversi"), 3) == 2.0, "誘いに応じて始めたゲームは覚えない"
        st["game"] = None
        print("もう一回:", e["text"])

        # ---- 9. 映画の誘いに応じると, そのジャンルで観る
        free()
        st["approach"] = None
        st["cooldowns"] = {}
        st["prefs"]["act:movie"] = 3.0
        st["tastes"] = {"food": 1.0}
        for k in [k for k in st["prefs"] if k.startswith("genre:")]:
            st["prefs"].pop(k)
        random.seed(3)
        e = P.fire(char, st, time.time(), ctx, force="movie_invite")
        g = st["approach"]["genre"]
        print("映画の誘い:", e["text"])
        assert st["approach"]["genre_label"] in e["text"]
        m0 = round(prefs.pref(st, "act:movie"), 3)
        app.answer_approach("accept", cid)
        assert round(prefs.pref(st, "act:movie"), 3) == m0, "誘いに応じた映画は覚えない"
        top = app.topics.view(cid)
        print("  観た話題:", str(top)[:120], "/ ジャンル", g)
        free()

        # ---- 10. よく誘う行き先・疲れていると座れる店
        st["place_fun"] = {"cafe": 0.0, "walk": 0.0}
        w0 = app.appoint.place_weight(char, st, "cafe")
        st["prefs"]["place:cafe"] = 10.0
        st["prefs_t"]["place:cafe"] = now
        w1 = app.appoint.place_weight(char, st, "cafe")
        assert w1 > w0 and w1 <= 1.8, (w0, w1)
        st["params"]["mood"] = 20
        assert app.appoint.place_weight(char, st, "cafe") == w0 or app.appoint.place_weight(char, st, "cafe") <= w0 + 1e-9
        st["params"]["mood"] = 70
        dn = P.find("date_next")
        octx = dict(app.context(char, st, datetime.now()), outing=True)
        rest = {a["id"]: w for a, w in P._next_places(char, st, dn, dict(octx, energy=80))}
        tired = {a["id"]: w for a, w in P._next_places(char, st, dn, dict(octx, energy=30))}
        print("次の場所の重み (元気 / 疲れ):", {k: (round(rest[k], 2), round(tired.get(k, 0), 2)) for k in rest})
        if "cafe" in rest and "walk" in rest:
            assert tired["cafe"] / rest["cafe"] > tired["walk"] / rest["walk"], "疲れていると座れる店に寄る"
        assert any(tired[k] > rest[k] for k in tired) and any(tired[k] < rest[k] for k in tired)

        # ---- 11. 約束で誘った行き先を覚える (同居していない相手と. 本人の服選びは 12. で hina のまま)
        char0, st0 = char, st
        app.create_world("好みの記憶と約束")
        cid2 = app.settings["active_character"]
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        st2 = app.state(cid2)
        day = datetime.fromtimestamp(time.time() + DAY).replace(hour=13, minute=0, second=0, microsecond=0)
        app.appoint.propose(cid2, day.timestamp(), "aquarium", "aquarium")
        assert round(prefs.pref(st2, "place:aquarium"), 3) == 1.0
        app.scheduled_scene = sched
        char, st = char0, st0
        print("約束で誘った行き先: ok")

        # ---- 12. 本人の服選びは, 一日の中で変わらない (好みの薄れはその日の 0 時で読む)
        st["prefs"]["outfit:casual_a"] = 6.0
        st["prefs_t"]["outfit:casual_a"] = now - 10 * DAY
        d1 = datetime.now().replace(hour=9, minute=0)
        d2 = d1.replace(hour=21)
        assert app.wardrobe.self_pick(char, st, d1) == app.wardrobe.self_pick(char, st, d2)
        print("ok: 全部通った")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
