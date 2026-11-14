"""相手の中の「あなたの見立て」(core/regard.py): 初めの値・印の向きと強さ・読み違え・確かさ・実際の操作からの印・効き方.

    python tools/test_regard.py
"""
import json
import os
import random
import shutil
import sys
import tempfile
import time
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, msgreply as MR, react, regard as RG, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(33)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("見立て")
        G, B, P, C, A = app.regard, app.bonds, app.presence, app.chat, app.appoint
        G.rng.seed(33)
        cid = app.settings["active_character"]
        B.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        personas = sorted(app.personas)
        assert set(RG.READING) <= set(personas) and len(personas) >= 27, sorted(set(RG.READING) - set(personas))
        missing = sorted(set(personas) - set(RG.READING))
        assert not missing, "読み方の表に無い性格: %s" % missing

        def setv(v=50.0, sure=0.5, **kw):
            st["regard"] = dict({"v": float(v), "sure": float(sure), "day": {}, "since": time.time()}, **kw)

        def fresh():
            st["regard"]["day"] = {}

        # ---- 1. 初めの値: 範囲・同じ状態から同じ値・性格の読み方・はじめて使うときに入る・画面に出ない
        n = 0
        for pid in personas:
            char["persona_id"] = pid
            for stage in ("known", "contact", "visit", "live"):
                B.rec()["bonds"][cid]["stage"] = stage
                for aff, trust, days in ((20, 20, 0), (50, 50, 5), (90, 90, 14)):
                    st["params"].update(affection=aff, trust=trust)
                    st["touch_days"] = [B._day(time.time() - i * 86400) for i in range(days)]
                    st["last_touch"] = time.time() - (0 if days else 20) * 86400
                    b = G.baseline(char, st)
                    assert 0 <= b["v"] <= 100 and 0.1 <= b["sure"] <= G.sure_cap(char) + 1e-9, (pid, stage, b)
                    assert b == G.baseline(char, st)
                    n += 1
        B.rec()["bonds"][cid]["stage"] = "contact"
        st["params"].update(affection=55, trust=55)
        st["touch_days"] = [B._day(time.time() - i * 86400) for i in range(5)]
        st["last_touch"] = time.time()
        char["persona_id"] = "hikutsu"
        lo = G.baseline(char, st)
        char["persona_id"] = "sadist"
        hi = G.baseline(char, st)
        assert hi["v"] > lo["v"] + 8, (hi, lo)
        char["persona_id"] = "teinei"
        st.pop("regard", None)
        G.hold(char, st)
        assert "regard" in st and st["regard"]["v"] == G.baseline(char, st)["v"]
        view = json.dumps(app.state_view(cid), ensure_ascii=False)
        assert "regard" not in view and "思われている" not in view, "画面のデータに見立てが出ている"
        print("初めの値: OK | %d 通り・卑屈 %s / ドS %s" % (n, lo, hi))

        # ---- 2. 印: どの性格でも表の向きに動く. 一日の上限. 悪い印のほうが強い
        for pid in personas:
            char["persona_id"] = pid
            for kind, (d0, _) in RG.SIGNS.items():
                setv(50, 0.5)
                d = G.sign(char, st, kind)
                assert (d > 0) == (d0 > 0) and abs(d) > 0, (pid, kind, d)
        char["persona_id"] = "teinei"
        setv(50, 0.5)
        down = -sum(G.sign(char, st, "ignored_read") for _ in range(20))
        setv(50, 0.5)
        up = sum(G.sign(char, st, "invite_yes") for _ in range(20))
        assert 0 < up <= RG.DAY_CAP["+"] + 1e-6 and up < down <= RG.DAY_CAP["-"] + 1e-6, (up, down)
        setv(50, 0.5)
        G.sign(char, st, "invite_yes", time.time())
        used = dict(st["regard"]["day"])
        G.sign(char, st, "invite_yes", time.time() + 86400 * 2)          # 日が替われば, また動く
        assert st["regard"]["day"]["d"] != used["d"]
        assert sum(abs(v[0]) for v in RG.SIGNS.values() if v[0] < 0) > sum(v[0] for v in RG.SIGNS.values() if v[0] > 0)
        print("印の向き・一日の上限: OK | 上 %.1f / 下 %.1f" % (up, down))

        # 確かさ: 低いほど大きく揺れる. 同じ向きの印で固まり, 逆向きで揺らぐ. ツンデレは固まりにくい
        def mean_move(sure, kind, pid="teinei", n=300):
            char["persona_id"] = pid
            tot = 0.0
            for _ in range(n):
                setv(50, sure)
                tot += G.sign(char, st, kind)
            char["persona_id"] = "teinei"
            return tot / n
        assert abs(mean_move(0.1, "invite_no")) > abs(mean_move(0.9, "invite_no")) * 1.5
        setv(70, 0.5)
        G.sign(char, st, "invite_yes")
        s_up = st["regard"]["sure"]
        setv(70, 0.5)
        G.sign(char, st, "invite_no")
        s_dn = st["regard"]["sure"]
        assert s_up > 0.5 > s_dn and (0.5 - s_dn) > (s_up - 0.5), (s_up, s_dn)
        char["persona_id"] = "tsundere"
        setv(70, 0.3)
        for i in range(60):
            fresh()
            G.sign(char, st, "kept")
        assert st["regard"]["sure"] <= G.sure_cap(char) + 1e-9 < 0.55, st["regard"]
        # 読み違え: 卑屈は良い印を割り引き, 悪い印を重く取る. ドSは逆
        gh, gs = mean_move(0.5, "invite_yes", "hikutsu"), mean_move(0.5, "invite_yes", "sadist")
        bh, bs = mean_move(0.5, "invite_no", "hikutsu"), mean_move(0.5, "invite_no", "sadist")
        assert gs > gh * 1.4 and abs(bh) > abs(bs) * 1.4, (gh, gs, bh, bs)
        char["persona_id"] = "teinei"
        print("確かさ・読み違え: OK | 誘いに応じた 卑屈 %+.2f ドS %+.2f / 断った 卑屈 %+.2f ドS %+.2f" % (gh, gs, bh, bs))

        # ---- 3. 実際の操作から印が入る
        relax = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}

        def reset(aff=60):
            st.update(contacts=[], cooldowns={}, override=dict(relax), approach=None, ap_last={})
            for k in ("msg_pending", "ap_ignored_until", "ap_quiet_until", "phone_until", "ap_ignored"):
                st.pop(k, None)
            st["params"].update(mood=60, affection=aff, trust=55, loneliness=30, boredom=60, energy=70, stress=20)
            C.save(cid, {"seen_t": 0, "items": []})
            setv(50, 0.5)

        # 既読のまま返さない / 読まないまま
        got = {}
        for read in (True, False):
            reset()
            app.force_approach("msg_chat", cid)
            ap = st["approach"]
            if read:
                d = C.load(cid)
                d["seen_t"] = ap["t"] + 1
                C.save(cid, d)
            P.live(char, st, ap["until"] + 1)
            assert not st.get("approach")
            got[read] = st["regard"]["v"] - 50
        assert got[True] < got[False] < 0, got
        # 返事をする (速さ) と, その受け取られ方
        reset()
        app.force_approach("msg_chat", cid)
        st["approach"]["why"] = "lonely"
        now = time.time()
        P.answer(char, st, "reply", now=now, choice="cheerful")
        v1 = st["regard"]["v"]
        assert v1 > 50, v1
        reset()
        app.force_approach("msg_chat", cid)
        st["approach"]["t"] = time.time() - 3 * 3600
        P.answer(char, st, "reply", now=time.time(), choice="cheerful")
        assert 50 < st["regard"]["v"] < v1, (st["regard"]["v"], v1)
        print("既読のまま・返事の速さ: OK | 既読 %+.2f / 未読 %+.2f / すぐ返した %+.2f" % (got[True], got[False], v1 - 50))

        # あなたから連絡を始める (返事への返しは数えない)
        reset()
        C.send(cid, "smalltalk")
        assert st["regard"]["v"] > 50
        # 誘い・頼みごと・看病への答え (約束の種類 × 答え)
        when = time.time() + 2 * 86400
        res = {}
        for label, extra, kinds in (("誘い", {}, ("invite_yes", "invite_no")), ("看病", {"care": True, "want": []}, ("care_yes", "care_no"))):
            for yes in (True, False):
                reset()
                x = dict({"id": uuid.uuid4().hex[:8], "cid": cid, "t": when, "place": "cafe", "do": "cafe", "by": "her",
                          "status": "offered", "made": time.time()}, **extra)
                if extra:
                    x.update(place="home:" + cid, do="visit_home")
                A.all().append(x)
                A.answer(x["id"], yes)
                d = st["regard"]["v"] - 50
                assert (d > 0) == yes and abs(d) > 0, (label, yes, d)
                res[(label, yes)] = d
                A.all().remove(x)
        A.save()
        print("誘い・看病への答え: OK |", " ".join("%s%s %+.1f" % (k[0], "○" if k[1] else "×", v) for k, v in res.items()))

        # 謝る (届いた謝罪だけ) / 嫉妬 / 日ごと (会った日・音沙汰なし. 同居相手は音沙汰なしにならない)
        ups = 0
        for _ in range(12):
            reset()
            st["apologies"] = []
            st["reasons"] = []
            app.life.add_reason(st, "player", "bad", "テストの失敗", time.time(), told=True, delta=-6, action="_test")
            C.send(cid, "apology")
            st["msg_pending"].update(due=time.time() - 1, reply=True)
            app.deliver_due()
            assert any(it["who"] == "her" for it in C.load(cid)["items"])
            assert st["regard"]["v"] >= 50, st["regard"]         # 謝って見立てが下がることはない (連絡を始めた分にも数えない)
            ups += st["regard"]["v"] > 50
        assert ups >= 4, ups
        reset()
        st["reasons"] = []
        others = [o for o in app.chars if o != cid]
        if others:
            B.notice(char, st, others[0], time.time())
            assert st["regard"]["v"] < 50
        reset()
        st["last_met"] = st["last_touch"] = time.time()
        G.daily(char, st, time.time())
        assert st["regard"]["v"] > 50
        reset()
        st["last_met"] = st["last_touch"] = time.time() - 8 * 86400
        s0 = st["regard"]["sure"]
        G.daily(char, st, time.time())
        assert st["regard"]["v"] < 50 and st["regard"]["sure"] < s0
        reset()
        B.rec()["bonds"][cid]["stage"] = "live"
        G.daily(char, st, time.time())
        assert st["regard"]["v"] == 50
        B.rec()["bonds"][cid]["stage"] = "contact"
        st["last_met"] = st["last_touch"] = time.time()
        print("日ごと・嫉妬: OK")

        # ---- 4. 効き方: 控え (好きでなければ気にしない)・踏み出し・連絡 (依存度で向きが変わる)・段階の提案
        table = []
        for aff in (30, 44, 45, 60, 80, 95):
            for v in (5, 25, 50, 75, 95):
                st["params"]["affection"] = aff
                setv(v, 0.5)
                h, le, f = G.hold(char, st), G.lean(char, st), G.invite_factor(char, st)
                assert 0 <= h <= 1 and 0 <= le <= 1 and 0.39 <= f <= 1.2501, (aff, v, h, le, f)
                assert (h == 0) or (aff >= 45 and aff - v > 8), (aff, v, h)
                assert not (h > 0 and le > 0)
                table.append(f)
        st["params"]["affection"] = 80
        setv(20, 0.5)
        f_hold = G.invite_factor(char, st)
        st["attach"] = dict(app.attach.rec(char, st), dependence=90.0)
        c_dep = G.contact_factor(char, st)
        st["attach"]["dependence"] = 30.0
        c_ind = G.contact_factor(char, st)
        setv(90, 0.5)
        f_lean = G.invite_factor(char, st)
        assert f_hold <= 0.45 and f_lean > 1.1 and c_dep > 1.2 and c_ind < 0.75, (f_hold, f_lean, c_dep, c_ind)
        setv(90, 0.8)
        r_hi = sum(B.readiness(char, st, time.time()) for _ in range(300)) / 300
        setv(10, 0.8)
        r_lo = sum(B.readiness(char, st, time.time()) for _ in range(300)) / 300
        assert 12 < r_hi - r_lo < 26, (r_hi, r_lo)
        print("効き方: OK | 誘い ×%.2f (控え) / ×%.2f (踏み出し)・連絡 ×%.2f (依存) / ×%.2f・提案 %+.1f" % (
            f_hold, f_lean, c_dep, c_ind, r_hi - r_lo))

        # 誘ってくる多さ (実際の抽せん): 思われていないと感じていると減る
        def invites(v, n=4000):
            reset(aff=80)
            st["params"]["loneliness"] = 60
            setv(v, 0.5)
            k = 0
            for _ in range(n):
                x = A._maybe_invite(cid, time.time(), 1.0)
                if x:
                    k += 1
                    A.all().remove(x)
                    C.save(cid, {"seen_t": 0, "items": []})
            A.save()
            return k
        i_lo, i_mid = invites(20), invites(75)
        assert i_mid > 20 and i_lo < i_mid * 0.7, (i_lo, i_mid)
        print("誘ってくる多さ: OK | 思われていない %d / 思われている %d (4000 時間ぶん)" % (i_lo, i_mid))

        # ---- 5. 探り (「最近忙しい？」): 条件・間隔・文面と返し方・返事の効き
        keep = app.approaches
        app.approaches = [a for a in keep if a["id"] == "msg_chat"]
        real = random.random

        def fire(aff, v, probe_t=None):
            reset(aff=aff)
            setv(v, 0.5, **({"probe_t": probe_t} if probe_t else {}))
            ctx = app.context(char, st, datetime.now())
            random.random = lambda: 0.0
            try:
                P.fire(char, st, time.time(), ctx)
            finally:
                random.random = real
            return (st.get("approach") or {}).get("why")
        try:
            for aff, v, pt, want in ((80, 20, None, True), (80, 70, None, False), (40, 5, None, False),
                                     (80, 20, time.time() - 86400, False), (80, 20, time.time() - 4 * 86400, True)):
                assert (fire(aff, v, pt) == "unsure") == want, (aff, v, pt, want)
            assert fire(80, 20) == "unsure"
            text = [it for it in C.load(cid)["items"] if it["who"] == "her"][-1]["text"]
            assert "忙しい" in text, text
            assert react.ap_tone("msg_chat", "unsure") == "question" and "re_answer" in react.kinds_for("question")
            opts = [o["id"] for o in MR.options("msg_chat", "unsure")]
            assert opts[0] == "expand" and "curt" in opts
            # 返し方ごとに: ちゃんと返せば見立てが上がり, 流せば下がる. 放っておくと, ふつうの既読スルーより堪える
            outs = {}
            for kind in ("expand", "curt"):
                tot = 0.0
                for _ in range(40):
                    fire(80, 20)
                    v0 = st["regard"]["v"]
                    P.reply_land(char, st, "msg_chat", kind, time.time(), why="unsure")
                    tot += st["regard"]["v"] - v0
                outs[kind] = tot / 40
            assert outs["expand"] > 1.0 and outs["curt"] < -0.5, outs
            ig = {}
            for why in ("unsure", "lonely"):
                tot = 0.0
                for _ in range(40):
                    fire(80, 20)
                    st["approach"]["why"] = why
                    ap = st["approach"]
                    d = C.load(cid)
                    d["seen_t"] = ap["t"] + 1
                    C.save(cid, d)
                    v0 = st["regard"]["v"]
                    P.live(char, st, ap["until"] + 1)
                    tot += st["regard"]["v"] - v0
                ig[why] = tot / 40
            assert ig["unsure"] < ig["lonely"] < 0, ig
        finally:
            app.approaches = keep
        assert "unsure" not in {MR.pick_why(char, st) for _ in range(300)}          # ふつうの理由選びには出ない
        print("探り: OK | %s | 答えた %+.2f / 流した %+.2f / 既読のまま %+.2f (ふつうは %+.2f)" % (
            text, outs["expand"], outs["curt"], ig["unsure"], ig["lonely"]))

        # ---- 6. 保存して開き直しても同じ値 (初めの値を決め直さない)
        setv(37.5, 0.42)
        app.save_state(cid)
        app2 = engine.App()
        st2 = app2.state(cid)
        assert app2.regard.get(app2.char(cid), st2) == 37.5 and st2["regard"]["sure"] == 0.42
        print("開き直し: OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK")


if __name__ == "__main__":
    main()
