"""あなたの癖 (core/regard.py の habit. 残件 A15 の段 2〜3): 時間帯ごとの返信の傾向を覚える・ふだんどおりなら軽く / ふだんと違えば重く・
「何かあった？」・からかいの多さ・薄れ方・実際の操作 (時間切れ・返事・遅れて返す・既読のまま) からの記録と効き方.

    python tools/test_habit.py
"""
import json
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, keys, msgreply as MR, react, regard as RG, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)

DAYS = {"w": datetime(2026, 10, 19), "h": datetime(2026, 10, 18)}        # 月曜 / 日曜
HOURS = (2, 7, 12, 17, 21)                                                # 夜中・朝・昼・夕方・夜
SLOTS = [d + str(i) for d in "wh" for i in range(5)]


def ts(key, minute=0):
    d = DAYS[key[0]]
    return datetime(d.year, d.month, d.day, HOURS[int(key[1])], minute).timestamp()


def main():
    random.seed(41)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("癖")
        G, B, P, C = app.regard, app.bonds, app.presence, app.chat
        G.rng.seed(41)
        cid = app.settings["active_character"]
        B.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        char["persona_id"] = "genki"                 # 覚えやすさ 1.0 (マメでも, 気にしない人でもない)
        personas = sorted(app.personas)

        def setv(v=50.0, sure=0.5, **kw):
            st["regard"] = dict({"v": float(v), "sure": float(sure), "day": {}, "since": time.time()}, **kw)

        def dep(v):
            st["attach"] = dict(app.attach.rec(char, st), dependence=float(v))

        def teach(key, n, share, slow=None, t=None, also_all=True):
            """枠に n 件 (返した割合 share・返すまで slow 分) を覚えさせる (薄れを入れずに, 値を直接)."""
            h = G.habit(char, st)
            b = {"n": float(n), "r": round(n * share, 3), "slow": float(slow or 0), "t": t or ts(key) + 86400}      # 既定では薄れを入れない
            h["reply"][key] = dict(b)
            if also_all:
                h["all"] = dict(b)

        # ---- 0. 枠: 時刻 → 10 個の枠. 祝日は休日
        assert [RG.slot(ts(k)) for k in SLOTS] == SLOTS
        edges = {0: "w0", 4: "w0", 5: "w1", 9: "w1", 10: "w2", 15: "w2", 16: "w3", 18: "w3", 19: "w4", 23: "w4"}
        for hh, want in edges.items():
            assert RG.slot(datetime(2026, 10, 19, hh, 59).timestamp()) == want, (hh, want)
        assert RG.slot(datetime(2026, 11, 3, 12).timestamp()) == "h2" and RG.slot(datetime(2026, 11, 4, 12).timestamp()) == "w2"   # 文化の日 (火)
        lr = {pid: G.learn(dict(char, persona_id=pid)) for pid in personas}
        assert all(0.59 <= v <= 1.51 for v in lr.values()), lr
        assert lr["seijitsu"] < 0.75 and lr["aneki"] < 0.75 and lr["tenshin"] > 1.4 and lr["genki"] == 1.0, lr
        print("枠・覚えやすさ: OK | 誠実 %.2f / 元気 %.2f / 天真爛漫 %.2f" % (lr["seijitsu"], lr["genki"], lr["tenshin"]))

        # ---- 1. 総当たり: 枠 10 × (返さない / 返した・ふだんの遅さ / 返した・ずっと遅い) × ふだん (返さない人 / よく返す人 / 遅い人)
        #         × 慣れ (記録なし / 少ない / 十分) × 依存度 (ふつう / 高い)
        n = 0
        dep(50)
        for key in SLOTS:
            t0 = ts(key)
            for d_ in (50, 90):
                dep(d_)
                half = 0.5 if d_ == 90 else 1.0
                # 記録なし・少ない (4 件未満): いままでと同じ
                for cnt in (0, 3.9):
                    setv()
                    if cnt:
                        teach(key, cnt, 0.1, 30)
                    for waited in (None, 5, 80, 400):
                        assert G.ease(char, st, t0, t0 + 5400, waited=waited) == 1.0, (key, cnt, waited)
                        n += 1
                    assert "odd" not in G.habit(char, st)
                for cnt, fam in ((4, 0.5), (8, 1.0), (20, 1.0)):
                    # ふだん返さない枠 (2 割): 返ってこなくても軽い
                    setv()
                    teach(key, cnt, 0.2, 30)
                    e = G.ease(char, st, t0, t0 + 5400)
                    assert abs(e - (1 - RG.EASE * fam * half)) < 1e-9, (key, cnt, d_, e)
                    assert "odd" not in G.habit(char, st)
                    # よく返す枠 (9 割・5 分): 返ってこないと重い. ふだんの遅さなら軽く, ずっと遅いと重い
                    setv()
                    teach(key, cnt, 0.9, 5)
                    e = G.ease(char, st, t0, t0 + 5400)
                    assert abs(e - (1 + RG.ODD * fam)) < 1e-9, (key, cnt, e)
                    assert G.habit(char, st).pop("odd") == t0 + 5400
                    assert abs(G.ease(char, st, t0, t0 + 400, waited=6) - (1 - RG.EASE * fam * half)) < 1e-9
                    assert G.ease(char, st, t0, t0 + 900, waited=12) == 1.0                 # ふだんの 1.5 倍〜3 倍: どちらでもない
                    assert G.ease(char, st, t0, t0 + 1100, waited=18) == 1.0                # 3 倍より遅くても, 20 分に満たなければ言わない
                    assert "odd" not in G.habit(char, st)
                    assert abs(G.ease(char, st, t0, t0 + 4800, waited=80) - (1 + RG.ODD * fam)) < 1e-9
                    assert G.habit(char, st).pop("odd")
                    assert G.ease(char, st, t0, t0 + 5400, mark=False) > 1 and "odd" not in G.habit(char, st)     # mark=False は覚えない
                    # いつも遅く返す人 (9 割・120 分): 90 分で時間切れになっても, ふだんどおり
                    setv()
                    teach(key, cnt, 0.9, 120)
                    assert abs(G.ease(char, st, t0, t0 + 5400) - (1 - RG.EASE * fam * half)) < 1e-9
                    assert abs(G.ease(char, st, t0, t0 + 9000, waited=150) - (1 - RG.EASE * fam * half)) < 1e-9
                    assert "odd" not in G.habit(char, st)
                    # どちらでもない (6 割・返ってこない): そのまま
                    setv()
                    teach(key, cnt, 0.6, 5)
                    assert G.ease(char, st, t0, t0 + 5400) == 1.0
                    n += 9
        dep(50)
        # 枠の記録が少なければ全体の記録で. 枠に十分あれば, 枠のほう (夜は返すが朝は返さない)
        setv()
        teach("w4", 10, 0.95, 4)
        teach("w1", 10, 0.1, 40, also_all=False)
        assert G.known(char, st, ts("w4"), ts("w4"))[4] == "w4" and G.known(char, st, ts("w1"), ts("w1"))[4] == "w1"
        assert G.known(char, st, ts("h2"), ts("h2"))[4] == "all"
        assert G.ease(char, st, ts("w1"), ts("w1") + 5400, mark=False) < 1 < G.ease(char, st, ts("w4"), ts("w4") + 5400, mark=False)
        # 覚えやすさ: 同じ 5 件でも, マメな人は慣れが深く, 気にしない人は浅い
        es = {}
        for pid in ("seijitsu", "genki", "tenshin"):
            char["persona_id"] = pid
            setv()
            teach("w2", 5, 0.1, 30)
            es[pid] = G.ease(char, st, ts("w2"), ts("w2") + 5400)
        char["persona_id"] = "genki"
        assert es["seijitsu"] < es["genki"] < es["tenshin"] < 1, es
        print("総当たり: OK | %d 通り・同じ 5 件での軽さ 誠実 ×%.2f / 元気 ×%.2f / 天真爛漫 ×%.2f" % (n, es["seijitsu"], es["genki"], es["tenshin"]))

        # ---- 2. 覚える・薄れる
        setv()
        t = ts("w4")
        for i in range(12):
            G.note_reply(char, st, t + i, t + i + 300, waited=5)
        b = G.habit(char, st)["reply"]["w4"]
        n12 = b["n"]
        assert 9 < b["n"] < 12 and abs(b["r"] - b["n"]) < 0.01 and abs(b["slow"] - 5) < 0.01, b
        assert set(G.habit(char, st)["reply"]) == {"w4"} and abs(G.habit(char, st)["all"]["n"] - b["n"]) < 1e-6
        for i in range(12):
            G.note_reply(char, st, t + 100 + i, t + 6000 + i)                 # 返さないのが続く: 割合が下がる
        k = G.known(char, st, t, t + 6100)
        assert 0.3 < k[1] < 0.5, k
        # 時間切れのあとに返した: 数は増やさず, 返した数と遅さを直す
        n0, r0 = b["n"], b["r"]
        G.note_reply(char, st, t + 111, t + 20000, waited=300, late=True)
        assert n0 - 0.1 < b["n"] <= n0 and abs(b["r"] - (r0 + 1)) < 0.05 and b["slow"] > 50, b       # 数はふえない (時間のぶん, わずかに薄れる)
        setv()
        G.note_reply(char, st, t, t + 9000, waited=150, late=True)          # 覚えはじめる前のメッセージに返した: 数えない
        assert not G.habit(char, st)["all"]
        # 日がたつと薄れる: 30 日で半分・半年で「覚えていない」に戻る
        setv()
        teach("w4", 10, 0.1, 30, t=t)
        k30 = G.known(char, st, t, t + 30 * 86400)
        assert abs(k30[0] - 5) < 0.01 and abs(k30[1] - 0.1) < 0.01, k30
        assert G.ease(char, st, t, t + 5400, mark=False) < G.ease(char, st, t + 30 * 86400, t + 30 * 86400 + 5400, mark=False) < 1
        assert G.known(char, st, t, t + 180 * 86400) is None and G.ease(char, st, t + 180 * 86400, t + 180 * 86400 + 5400) == 1.0
        # 遅さの上限・1 件めはそのまま・2 件め以降はならす
        setv()
        G.note_reply(char, st, t, t + 1, waited=5000)
        assert G.habit(char, st)["all"]["slow"] == RG.HABIT_SLOW_CAP
        G.note_reply(char, st, t, t + 2, waited=0)
        assert 0 < G.habit(char, st)["all"]["slow"] < RG.HABIT_SLOW_CAP
        print("覚える・薄れる: OK | 12 件で %.1f 件ぶん・30 日後は 10 件が %.1f 件ぶん" % (n12, k30[0]))

        # ---- 3. 実際の操作
        relax = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}
        keep = app.approaches
        app.approaches = [a for a in keep if a["id"] == "msg_chat"]

        def reset(aff=60):
            st.update(contacts=[], cooldowns={}, override=dict(relax), approach=None, ap_last={})
            for k_ in ("msg_pending", "ap_ignored_until", "ap_quiet_until", "phone_until", "ap_ignored", "await_ignored", "react_since"):
                st.pop(k_, None)
            st["params"].update(mood=60, affection=aff, trust=55, loneliness=50, boredom=60, energy=70, stress=20)
            st["reasons"] = []
            dep(50)
            C.save(cid, {"seen_t": 0, "items": []})
            setv(50, 0.5)

        def approach():
            app.force_approach("msg_chat", cid)
            return st["approach"]

        def expire(habit=None, read=True, n_=40):
            """時間切れを n_ 回: (機嫌の動きの平均, 見立ての動きの平均, 最後の ap_ignored)."""
            dm = dv = 0.0
            for _ in range(n_):
                reset()
                ap = approach()
                if habit:
                    teach(RG.slot(ap["t"]), *habit, t=ap["t"])
                if read:
                    d = C.load(cid)
                    d["seen_t"] = ap["t"] + 1
                    C.save(cid, d)
                m0, v0 = st["params"]["mood"], st["regard"]["v"]
                P.live(char, st, ap["until"] + 1)
                assert not st.get("approach")
                dm += st["params"]["mood"] - m0
                dv += st["regard"]["v"] - v0
            return dm / n_, dv / n_, dict(st["ap_ignored"])

        try:
            # 3a. 時間切れ: 記録なし = いままでと同じ / 返さないのがふつうの枠 = 軽い / よく返す枠 = 重い + 気づく
            base = expire()
            usual = expire((10, 0.1, 30))
            odd = expire((10, 0.95, 5))
            assert base[2]["ease"] == 1.0 and abs(usual[2]["ease"] - 0.4) < 1e-6 and abs(odd[2]["ease"] - 1.3) < 1e-6
            assert odd[0] < base[0] < usual[0] < 0 and odd[1] < base[1] < usual[1] < 0, (base, usual, odd)
            assert abs(usual[0] / base[0] - 0.4) < 0.1 and abs(odd[0] / base[0] - 1.3) < 0.15, (base, usual, odd)
            assert G.habit(char, st).get("odd")
            # 時間切れは「返さなかった」として覚える (判定のあとで: 数が 1 件ふえ, 返した数はふえない)
            reset()
            ap = approach()
            key = RG.slot(ap["t"])
            P.live(char, st, ap["until"] + 1)
            b = G.habit(char, st)["reply"][key]
            assert b["n"] == 1 and b["r"] == 0 and G.habit(char, st)["all"]["n"] == 1, b
            # 記録がたまるまで (1 件ごとに薄めるので, 5 回の時間切れまで) は ease = 1, そのあとから効きはじめる
            eases = []
            reset()
            for i in range(7):
                st["approach"] = None
                st.pop("ap_ignored", None)
                st["ap_last"] = {}
                ap = approach()
                P.live(char, st, ap["until"] + 1)
                eases.append(st["ap_ignored"]["ease"])
                G.rec(char, st)["day"] = {}
            assert eases[:5] == [1.0] * 5 and eases[6] <= eases[5] < 1, eases
            # 依存度が高いと, 軽くなり方が半分
            reset()
            ap = approach()
            teach(RG.slot(ap["t"]), 10, 0.1, 30, t=ap["t"])
            dep(90)
            P.live(char, st, ap["until"] + 1)
            assert abs(st["ap_ignored"]["ease"] - 0.7) < 1e-6
            print("時間切れ: OK | 機嫌 いままで %+.2f / ふだんどおり %+.2f / ふだんと違う %+.2f・覚えはじめ %s" % (
                base[0], usual[0], odd[0], eases))

            # 3b. 既読のまま放っておく重さ (ignore_tick): 時間切れのときの倍率がそのまま掛かる
            def tick(ease):
                reset()
                st["params"]["mood"] = 60
                t0 = ts("h2")
                C.save(cid, {"seen_t": t0 + 1, "items": [{"who": "her", "text": "x", "t": t0, "kind": "approach", "ap": "msg_chat"}]})
                st["react_since"] = t0 - 10
                st["ap_ignored"] = {"t": t0 + 5400, "t_msg": t0, "aid": "msg_chat", "read": True, "applied": 0.0, "urgency": 1.0}
                if ease is not None:
                    st["ap_ignored"]["ease"] = ease
                react.ignore_tick(app, char, st, t0 + 5400 + 4 * 3600)
                return st["ap_ignored"]["applied"]
            a_old, a_1, a_lo, a_hi = tick(None), tick(1.0), tick(0.4), tick(1.3)
            assert a_old == a_1 > 0 and abs(a_lo / a_1 - 0.4) < 0.02 and abs(a_hi / a_1 - 1.3) < 0.02, (a_old, a_1, a_lo, a_hi)
            # 相手の問いかけを既読のまま: 気にしはじめたときの癖で決まり, 「いつもと違う」には数えない
            def await_(habit):
                reset()
                t0 = ts("h2")
                C.save(cid, {"seen_t": t0 + 1, "items": [{"who": "me", "text": "a", "t": t0 - 60, "kind": "smalltalk"},
                                                          {"who": "her", "text": "📱『どう思います？』", "t": t0, "kind": "smalltalk"}]})
                st["react_since"] = t0 - 100
                if habit:
                    teach("h2", *habit)
                react.ignore_tick(app, char, st, t0 + 8 * 3600)
                assert "odd" not in G.habit(char, st)
                return st["await_ignored"]
            w0, w1, w2 = await_(None), await_((10, 0.1, 30)), await_((10, 0.95, 5))
            assert w0["ease"] == 1.0 and w1["ease"] < 1 < w2["ease"] and w1["applied"] < w0["applied"] < w2["applied"], (w0, w1, w2)
            print("既読のまま: OK | 働きかけ ×1 %.2f / ふだんどおり %.2f / 違う %.2f・問いかけ %.2f / %.2f / %.2f" % (
                a_1, a_lo, a_hi, w0["applied"], w1["applied"], w2["applied"]))

            # 3c. 返事: 速さの印と記録. ふだんどおりの遅い返事は「返事が来た」と同じに, ふだんよりずっと遅いと薄い
            def answer(wait_min, habit=None, n_=60):
                tot = 0.0
                for _ in range(n_):
                    reset()
                    ap = approach()
                    ap["t"] = time.time() - wait_min * 60
                    if habit:
                        teach(RG.slot(ap["t"]), *habit, t=ap["t"])
                    v0 = st["regard"]["v"]
                    G.replied(char, st, ap["t"], time.time())
                    tot += st["regard"]["v"] - v0
                return tot / n_
            s_fast, s_mid, s_slow = answer(3), answer(30), answer(80)
            assert s_fast > s_mid > s_slow > 0, (s_fast, s_mid, s_slow)
            s_slow_usual = answer(80, (10, 0.9, 70))
            s_slow_odd = answer(80, (10, 0.9, 5))
            s_mid_odd = answer(30, (10, 0.9, 5))
            s_fast_h = answer(3, (10, 0.9, 5))
            assert abs(s_slow_usual - s_mid) < 0.25 and s_slow_usual > s_slow * 1.8, (s_slow_usual, s_mid, s_slow)
            assert s_slow_odd == 0 and s_mid_odd == 0 and abs(s_fast_h - s_fast) < 0.3, (s_slow_odd, s_mid_odd, s_fast_h)
            assert G.habit(char, st).get("odd") is None           # すぐ返したのは, いつもどおり
            # 画面の操作から: 返すと, 枠に「返した」が入り, 返しの種類も数える. 自動の返事は数えない
            reset()
            ap = approach()
            ap["t"] = time.time() - 240
            st["approach"]["why"] = "lonely"
            key = RG.slot(ap["t"])
            P.answer(char, st, "reply", now=time.time(), choice="tease")
            h = G.habit(char, st)
            assert h["reply"][key]["n"] == 1 and h["reply"][key]["r"] == 1 and abs(h["reply"][key]["slow"] - 4) < 0.1, h
            assert h["tease"] == {"n": 1, "k": 1}, h
            reset()
            ap = approach()
            P._reply(char, st, app.presence.find("msg_chat"), "cheerful", time.time(), auto=True)
            assert not G.habit(char, st)["all"] and not G.habit(char, st)["tease"]
            # 別のメッセージを送って済ませた (働きかけは流れる): それも「返した」
            reset()
            ap = approach()
            C.send(cid, "smalltalk")
            h = G.habit(char, st)
            assert not st.get("approach") and h["all"]["n"] == 1 and h["all"]["r"] == 1, h
            assert not h["start"]                                    # 相手のメッセージへの返事は, 「あなたから始めた」に数えない
            reset()
            t_ = time.time()
            C.send(cid, "smalltalk")
            h = G.habit(char, st)
            assert sum(h["start"].values()) == 1 and list(h["start"]) in ([RG.slot(t_)], [RG.slot(time.time())]), h      # 連絡を始めた時間帯
            assert not h["all"]
            print("返事: OK | すぐ %+.2f / 30 分 %+.2f / 80 分 %+.2f → ふだんどおりの 80 分 %+.2f・ふだんよりずっと遅い %+.2f" % (
                s_fast, s_mid, s_slow, s_slow_usual, s_slow_odd))

            # 3d. 遅れて返す (時間切れのあと): 遅れの減点が, ふだんどおりなら軽く / 違えば重く. 「返さなかった」の記録を直す
            class Fixed:
                def uniform(self, a, b):
                    return 0.0

                def random(self):
                    return 0.5
            st["params"].update(mood=50, affection=45)
            p0 = react.judge(app, char, st, "bored", "re_more", 0.0, rng=Fixed())[1]
            pen = {e: p0 - react.judge(app, char, st, "bored", "re_more", 5.0, rng=Fixed(), ease=e)[1] for e in (1.0, 0.4, 1.3)}
            assert abs(pen[1.0] - 6.0) < 1e-6 and abs(pen[0.4] - 2.4) < 1e-6 and abs(pen[1.3] - 7.8) < 1e-6, pen
            assert react.judge(app, char, st, "notice", "re_ok", 5.0, rng=Fixed(), ease=0.4)[1] == \
                react.judge(app, char, st, "notice", "re_ok", 5.0, rng=Fixed())[1]            # 返事を待っていない話には, 関係ない

            def late(habit):
                reset()
                ap = approach()
                t0 = ap["t"]
                key_ = RG.slot(t0)
                if habit:
                    teach(key_, *habit, t=t0)
                d = C.load(cid)
                d["seen_t"] = t0 + 1
                C.save(cid, d)
                P.live(char, st, ap["until"] + 1)
                before = dict(G.habit(char, st)["reply"][key_])
                G.habit(char, st).pop("odd", None)
                sent = t0 + 5 * 3600
                to = react.target(app, cid, st, sent)
                assert to and to["ap"] == "msg_chat", to
                react.land(app, char, st, "re_more", {"to": to, "sent": sent}, sent + 60)
                after = G.habit(char, st)["reply"][key_]
                assert before["n"] - 0.05 < after["n"] <= before["n"] and after["slow"] > before["slow"], (before, after)
                assert after["r"] > before["r"] + 0.9 or after["r"] == after["n"], (before, after)
                tr = [x for x in app.trace.items if x.get("what", "").startswith("返しの受け取り方")] if hasattr(app.trace, "items") else []
                return G.habit(char, st).get("odd"), tr
            o1, _ = late(None)
            o2, _ = late((10, 0.9, 200))
            o3, _ = late((10, 0.9, 5))
            assert o1 is None and o2 is None and o3, (o1, o2, o3)
            # 相手の返事 (働きかけそのものではない) に遅れて返しても, 働きかけの記録は直さない
            reset()
            t0 = ts("h2")
            C.save(cid, {"seen_t": t0 + 1, "items": [{"who": "me", "text": "a", "t": t0 - 60, "kind": "smalltalk"},
                                                      {"who": "her", "text": "📱『そうなんです』", "t": t0, "kind": "approach"}]})
            to = react.target(app, cid, st, t0 + 7200)
            assert to and not to.get("ap")
            react.land(app, char, st, "re_glad", {"to": to, "sent": t0 + 7200}, t0 + 7260)
            assert not G.habit(char, st)["all"] and G.habit(char, st)["tease"]["n"] == 1
            print("遅れて返す: OK | 5 時間遅れの減点 いままで %.1f / ふだんどおり %.1f / 違う %.1f" % (pen[1.0], pen[0.4], pen[1.3]))

            # 3e. からかい: よくからかう人だと分かっていれば, からかいの点に足す (からかい以外には足さない)
            reset()
            st["params"].update(mood=50, affection=60)
            base_t = react.judge(app, char, st, "bored", "tease", rng=Fixed())[1]
            base_m = react.judge(app, char, st, "bored", "re_more", rng=Fixed())[1]
            for kinds, want in ((["tease"] * 2 + ["re_more"] * 1, False),                 # 3 件: まだ分からない
                                (["tease", "re_more", "re_more", "re_lol", "re_glad", "re_more"] * 2, True),      # 12 件・3 割ちょっと
                                (["re_more"] * 11 + ["tease"], False)):                    # 1 割: そういう人ではない
                setv()
                for k_ in kinds:
                    G.note_kind(char, st, k_)
                assert G.teaser(char, st) == want, (kinds, G.habit(char, st)["tease"])
                for kind in ("tease", "re_lol"):
                    b0 = react.judge(app, char, dict(st, regard={"v": 50, "sure": 0.5, "day": {}}), "bored", kind, rng=Fixed())[1]
                    assert abs(react.judge(app, char, st, "bored", kind, rng=Fixed())[1] - b0 - (RG.TEASE_BONUS if want else 0)) < 1e-6
                assert react.judge(app, char, st, "bored", "re_more", rng=Fixed())[1] == base_m
            assert base_t == react.judge(app, char, dict(st, regard={"v": 50, "sure": 0.5, "day": {}}), "bored", "tease", rng=Fixed())[1]
            print("からかい: OK | よくからかう人だと分かっていると +%d" % RG.TEASE_BONUS)

            # ---- 4. 「何かあった？」: 気づいたあとだけ・3 日に一度まで・古い気づきでは聞かない・好きでなければ聞かない・探りが先
            real = random.random

            def fire(aff=60, v=60, now=None, **habit):
                reset(aff=aff)
                setv(v, 0.5)
                G.habit(char, st).update(habit)
                ctx = app.context(char, st, datetime.now())
                random.random = lambda: 0.0
                try:
                    P.fire(char, st, now or time.time(), ctx)
                finally:
                    random.random = real
                return (st.get("approach") or {}).get("why")
            now = time.time()
            assert fire() != "changed"
            assert fire(odd=now - 3600) == "changed"
            h = G.habit(char, st)
            assert "odd" not in h and h["asked"] <= time.time()
            text = [it for it in C.load(cid)["items"] if it["who"] == "her"][-1]["text"]
            assert "あった" in text and "いつも" in text, text
            assert fire(odd=now - 3600, asked=now - 2 * 86400) != "changed"
            assert G.habit(char, st).get("odd")                              # 聞けなかった気づきは, 残る (間があけば聞く)
            assert fire(odd=now - 3600, asked=now - 4 * 86400) == "changed"
            assert fire(odd=now - 4 * 86400) != "changed" and "odd" not in G.habit(char, st)
            assert fire(aff=30, odd=now - 3600) != "changed"
            assert fire(aff=80, v=20, odd=now - 3600) == "unsure" and G.habit(char, st).get("odd")     # 探りが先. 気づきは残る
            st["approach"] = None
            assert app.force_approach("msg_chat", cid) and st["approach"].get("why") not in ("changed", "unsure")     # 手で起こした分には出ない
            assert "changed" not in {MR.pick_why(char, st) for _ in range(300)}
            # 文面・返し方・合う / 外す・セリフのキー
            assert react.ap_tone("msg_chat", "changed") == "question" and "re_answer" in react.kinds_for("question")
            opts = [o["id"] for o in MR.options("msg_chat", "changed")]
            assert opts[0] == "expand" and "curt" in opts and len(opts) == 4, opts
            assert MR.said("msg_chat", "expand", "changed").endswith("返した")
            st["params"].update(mood=55, affection=60, loneliness=40)
            good = sum(MR.judge(char, st, "msg_chat", "expand", why="changed") == "good" for _ in range(300))
            bad = sum(MR.judge(char, st, "msg_chat", "curt", why="changed") == "bad" for _ in range(300))
            assert good > 240 and bad > 240, (good, bad)
            reg = keys.all_keys(app.actions, app.minigames, app.approaches)
            assert "ap.msg_chat.call_changed" in reg and "msgr.why.changed.bad" in reg
            # 流されたとき: 理由のにじむ返し
            fire(odd=now - 3600)
            random.seed(5)
            got = set()
            for _ in range(30):
                st["params"].update(mood=30, affection=40)
                e = P.reply_land(char, st, "msg_chat", "curt", time.time(), why="changed")
                got.add(e["reply"]["result"])
            assert "bad" in got
            # 一連の流れ: よく返す枠を覚えさせる → 返さない → 気づく → 次の「話そう」が「何かあった？」→ 3 日は聞かない
            reset()
            ap = approach()
            teach(RG.slot(ap["t"]), 10, 0.95, 5, t=ap["t"])
            P.live(char, st, ap["until"] + 1)
            assert G.habit(char, st).get("odd")
            st.update(approach=None, ap_last={})
            st.pop("ap_quiet_until", None)
            ctx = app.context(char, st, datetime.now())
            random.random = lambda: 0.0
            try:
                P.fire(char, st, ap["until"] + 7200, ctx)
                assert st["approach"]["why"] == "changed"
                G.habit(char, st)["odd"] = ap["until"] + 7300
                st.update(approach=None, ap_last={})
                P.fire(char, st, ap["until"] + 86400, ctx)
                assert st["approach"]["why"] != "changed"
            finally:
                random.random = real
            print("何かあった？: OK | %s | 合う %d/300・外す %d/300" % (text, good, bad))
        finally:
            app.approaches = keep

        # ---- 5. 画面に出ない・開き直しても残る・以前のセーブ (habit なし) はそのまま動く
        reset()
        teach("w4", 9, 0.8, 12)
        G.note_kind(char, st, "tease")
        G.habit(char, st)["odd"] = 123.0
        view = json.dumps(app.state_view(cid), ensure_ascii=False)
        assert "habit" not in view and '"odd"' not in view and "癖" not in view, "画面のデータに癖が出ている"
        app.save_state(cid)
        app2 = engine.App()
        st2, ch2 = app2.state(cid), app2.char(cid)
        h2 = app2.regard.habit(ch2, st2)
        assert h2["reply"]["w4"]["n"] == 9 and h2["tease"]["k"] == 1 and h2["odd"] == 123.0, h2
        assert app2.regard.known(ch2, st2, ts("w4"), ts("w4")) and st2["regard"]["v"] == 50
        st2["regard"] = {"v": 40.0, "sure": 0.4, "day": {}, "since": 1.0}        # 段 1 のセーブ: habit が無い
        assert app2.regard.ease(ch2, st2, ts("w4"), ts("w4") + 5400) == 1.0 and not app2.regard.teaser(ch2, st2)
        assert not app2.regard.ask_changed(ch2, st2, time.time()) and st2["regard"]["v"] == 40.0
        st2["regard"]["habit"] = "x"                                                # 壊れていても落ちない
        app2.regard.note_reply(ch2, st2, ts("w4"), time.time(), waited=1)
        assert "癖: 平日の夜" in app2.regard.debug(ch2, st2)                       # 開発・確認用の表示 (設定の showApart) にだけ出る
        print("画面に出ない・開き直し・以前のセーブ: OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK")


if __name__ == "__main__":
    main()
