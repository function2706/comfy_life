"""相手の言い分に, 肯定・否定で返す (A21. core/stance.py).
- 言い分 (好き・苦手・意見・相談への答え) のあるメッセージ / 電話・対面の切れ目にだけ「そうだね」「それはちょっと」が並ぶ.
  言い分の無い話・以前のトーク (印が無い) には並ばない. 画面で押せる = 本当に返せる, 押せないものは返せない.
- 合う・外す: 思い入れ × 肯定 / 否定, 苦手なものへの否定は軽い, 正直さを好む性格 / 否定に弱い性格, 仲, 軽い話で乗っているとき.
  合わせてばかりだと肯定が効かなくなり, 否定・3 日の間で数え直す. 必ず効く返しにならない.
- よく効いた否定は信頼が上がる. よくなかったら機嫌の理由 (謝れる心当たり).
- 話したい (メッセージ) で好み・意見が口に出ると, トークに言い分が残る. 知らない好みが先, 知っていれば意見として.
(一時データ)

    python tools/test_stance.py
"""
import glob
import os
import random
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, hima as H, react as R, stance as S, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
PERSONAS = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(os.path.dirname(HERE), "defaults", "personas", "*.json")))


def main():
    random.seed(11)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("肯定と否定")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        st, char = app.state(cid), app.char(cid)
        C = app.chat
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        LIKE, DISLIKE, LIGHT = S.make(1, 0.9, "books"), S.make(-1, 0.9, "horror"), S.make(1, 0.3, "games")

        def reset(**params):
            st.pop("msg_pending", None)
            st["approach"] = None
            st["contacts"], st["reasons"] = [], []
            st.pop("stance", None)
            st.pop("nori", None)
            for k in ("ap_ignored", "await_ignored"):
                st.pop(k, None)
            app.set_params(dict({"mood": 55, "affection": 55, "trust": 50, "loneliness": 40}, **params), cid)

        def her(kind, text, **kw):
            return C.add(cid, "her", text, kind=kind, t=time.time(), **kw)

        def rate(sv, kind, n=500, ok=("good",), persona=None, keep_run=False, **params):
            pid = char.get("persona_id")
            if persona:
                char["persona_id"] = persona
            got = 0
            for _ in range(n):
                if not keep_run:
                    st.pop("stance", None)
                st["params"].update(dict({"mood": 55, "affection": 55, "loneliness": 40}, **params))
                got += R.judge(app, char, st, "happy", kind, stance=sv)[0] in ok
            char["persona_id"] = pid
            return got / float(n)

        # ---- 1. 並ぶとき・並ばないとき (メッセージ)
        reset()
        assert "re_yes" not in R.kinds_for("happy") and "re_no" not in R.kinds_for("happy")
        assert "re_yes" in R.kinds_for("happy", stance=LIKE) and "re_no" in R.kinds_for("plain", stance=LIKE)
        her("smalltalk_hit", "📱『ふふ、楽しいです』")                          # 以前のトーク・言い分の無い話
        g = C.thread(cid)["groups"][0]
        assert g["id"] == "react" and "re_yes" not in g["kinds"], g
        try:
            C.send(cid, "re_no")
            raise AssertionError("言い分の無いメッセージに否定できた")
        except ValueError:
            pass
        her("smalltalk_hit", "📱『ふふ、楽しいです 本って、やっぱりいいですよね。』", stance=LIKE)
        g = C.thread(cid)["groups"][0]
        assert "re_yes" in g["kinds"] and "re_no" in g["kinds"], g
        her("consult_good", "📱『それなら、まず話してみたらどうですか？』")        # 相談への答えも言い分
        assert "re_no" in C.thread(cid)["groups"][0]["kinds"]
        print("並ぶとき (メッセージ): OK")

        # ---- 2. 合い方
        y, n_ = rate(LIKE, "re_yes"), rate(LIKE, "re_no")
        assert y > n_ + 0.3, (y, n_)
        assert rate(LIKE, "re_no", ok=("bad",)) > rate(DISLIKE, "re_no", ok=("bad",)) + 0.1      # 好きなものの否定は, 苦手なものの否定より重い
        fine = ("good", "neutral")
        assert rate(LIKE, "re_no", ok=fine, persona="jimuteki") > rate(LIKE, "re_no", ok=fine, persona="hikutsu") + 0.3   # 正直さを好む / 否定に弱い
        assert rate(LIKE, "re_no", persona="jimuteki", affection=80, mood=70) > 0.05                                      # 率直な性格・深い仲なら, 否定がよく効くことも
        assert rate(LIKE, "re_no", ok=("bad",), persona="hikutsu") > rate(LIKE, "re_no", ok=("bad",), persona="jimuteki") + 0.2
        assert rate(LIKE, "re_no", ok=fine, affection=85) > rate(LIKE, "re_no", ok=fine, affection=40) + 0.1      # 仲が深いほど受け止められる
        st["nori"] = {"t": time.time(), "v": 0.9, "turns": 3}
        lv_hi = S.fit(app, char, st, LIGHT, "re_no", lv=0.9) - S.fit(app, char, st, LIGHT, "re_no", lv=0.3)
        assert lv_hi == 6, lv_hi                                                                  # 軽い話で乗っている: 掛け合い
        assert S.fit(app, char, st, LIKE, "re_no", lv=0.9) == S.fit(app, char, st, LIKE, "re_no", lv=0.3)   # 思い入れが強ければ効かない
        st.pop("nori", None)
        for pid in PERSONAS:                                                                      # どの性格でも決め打ちにならない
            r_ = rate(LIKE, "re_yes", n=200, persona=pid)
            assert 0.05 < r_ < 0.97, (pid, r_)
            b_ = rate(LIKE, "re_no", n=200, persona=pid, ok=("good",), affection=90, mood=80)
            assert b_ < 0.95, (pid, b_)
        print("合い方: OK | 好きに肯定 (よく効いた) %.2f / 好きに否定 (よく効いた) %.2f / 悪く取られない: 事務的 %.2f・卑屈 %.2f" %
              (y, n_, rate(LIKE, "re_no", ok=fine, persona="jimuteki"), rate(LIKE, "re_no", ok=fine, persona="hikutsu")))

        # ---- 3. 合わせてばかり: 肯定が効かなくなる. 否定・3 日空くと数え直す
        reset()
        now = time.time()
        for _ in range(6):
            S.note(app, char, st, "re_yes", "good", now)
        assert S.run(st, now) == 6
        many = rate(LIKE, "re_yes", keep_run=True)
        assert many < y - 0.3, (many, y)
        assert S.run(st, now + 4 * 86400) == 0
        S.note(app, char, st, "re_no", "neutral", now)
        assert S.run(st, now) == 0
        assert S.note(app, char, st, "re_no", "good", now) == {"trust": 1.0} and S.note(app, char, st, "re_yes", "good", now) == {}
        print("合わせてばかり: OK | 6 回続けたあとの肯定 %.2f" % many)

        # ---- 4. メッセージで返す: 時間差で届く・印・心当たり
        got = {}
        for i in range(60):
            reset(affection=45)
            her("smalltalk_hit", "📱『本って、やっぱりいいですよね。』", stance=LIKE)
            k = random.choice(["re_yes", "re_no"])
            C.send(cid, k)
            pend = st["msg_pending"]
            assert pend["meta"]["to"]["stance"]["sign"] == 1, pend
            pend["due"], pend["reply"] = time.time() - 1, True
            t0 = st["params"]["trust"]
            app.deliver_due()
            last = [x for x in C.load(cid)["items"] if x["who"] == "her" and (x.get("kind") or "").startswith("react_")][-1]
            assert last["kind"].startswith("react_" + k[3:] + "_"), last
            res = last["kind"].rsplit("_", 1)[1]
            got.setdefault(k, {}).setdefault(res, 0)
            got[k][res] += 1
            if res == "bad":
                rs = [r for r in st.get("reasons") or [] if r.get("action") == "_react"]
                assert rs and ("否定" in rs[-1]["tell"] or "合わせて" in rs[-1]["tell"]), rs
            if k == "re_no" and res == "good":
                assert st["params"]["trust"] > t0, (t0, st["params"]["trust"])
            assert (st.get("stance") or {}).get("run") == (1 if k == "re_yes" else 0)
        assert got["re_no"].get("bad", 0) > got["re_yes"].get("bad", 0), got
        print("メッセージで返す: OK |", got)

        # ---- 5. 話したい: 好み・意見が口に出ると, トークに言い分が残る
        reset()
        st["known"] = []
        tv = app.topics.tastes(char, st)
        from core.topics import TAGS
        strong = [k for k, v in tv.items() if abs(v) >= 0.3 and k in TAGS]      # 音楽・香りなど話題でない好みは口にしない
        assert strong, tv
        seen = []
        rng = random.Random(3)
        for _ in range(len(strong)):
            t, key, sv = H.speak(app, char, st, time.time(), rng=rng)
            assert key.startswith("hima.reveal_") and sv["tag"] in strong, key
            seen.append(sv["tag"])
        assert sorted(seen) == sorted(strong), (seen, strong)                    # まだ知らないものが先, 一つずつ
        ops = [H.speak(app, char, st, time.time(), rng=rng) for _ in range(60)]
        ks = [o[1] for o in ops if o]
        assert ks and all(k.startswith("hima.opinion_") for k in ks) and 15 < len(ks) < 45, len(ks)      # 知っていれば, ときどき意見として
        for o in ops:
            if o:
                assert o[2]["sign"] == (1 if tv[o[2]["tag"]] > 0 else -1) and "{genre}" not in o[0]
        real_judge, real_settle = H.judge, H.speak
        H.judge = lambda a, c, s, now: ("hit", {})
        engine.hima_mod.judge = H.judge
        hit = 0
        for _ in range(40):
            reset(mood=80, trust=80)
            C.send(cid, "smalltalk")
            pend = st["msg_pending"]
            pend["due"], pend["reply"] = time.time() - 1, True
            app.deliver_due()
            it = [x for x in C.load(cid)["items"] if x["who"] == "her"][-1]
            if it.get("stance"):
                hit += 1
                g = C.thread(cid)["groups"][0]
                assert g["id"] == "react" and "re_yes" in g["kinds"], g
        H.judge = engine.hima_mod.judge = real_judge
        assert hit >= 3, hit
        print("話したいで言い分が残る: OK | %d / 40" % hit)

        # ---- 6. 電話・対面: 言い分のある切れ目にだけ並ぶ
        for mode in ("call", "face"):
            reset(mood=70, affection=70)
            if app.bonds.together(cid):
                app.bonds.end(go_home=False)
            app.presence.rec().pop("call", None)
            app.presence.rec().pop("face", None)
            now = time.time()
            if mode == "call":
                T = app.phonetalk
                T.begin(char, st, "もしもし", True, now)
            else:
                app.bonds.set_stage(cid, "visit")
                app.bonds.start(cid, "guest", now)
                T = app.facetalk
                T.begin(char, st, "話そう", None, now)
            c = T.rec()
            ids = [x["id"] for x in T.view(now)["returns"]]
            assert "yes" not in ids and "no" not in ids, ids
            try:
                T.reply("yes", now + 1)
                raise AssertionError("言い分の無い切れ目に肯定できた")
            except ValueError:
                pass
            for want in ("yes", "no", "aizuchi"):
                c = T.rec()
                c.pop("beat", None)
                c["sv"] = dict(LIKE)
                T._new_beat(char, st, c, "topic", "hima.opinion_like", "本って、やっぱりいいですよね。", now)
                v = T.view(now)
                ids = [x["id"] for x in v["returns"]]
                assert ids[:2] == ["yes", "no"], ids
                assert T.rec()["beat"]["stance"]["tag"] == "books"
                n0 = len(T.rec().get("log") or [])
                if st.get("nori"):                       # 否定で冷えて話が終わることもあるので (意図どおり), ここではノリを保つ
                    st["nori"].update(v=80, t=now)
                out = T.reply(want, now + 1)
                assert "ended" not in out, out
                if want != "aizuchi":
                    assert (st.get("stance") or {}).get("t") == now + 1
                log = T.rec().get("log") or []
                assert log[n0]["who"] == "me", log[n0:]
                now += 5
            c = T.rec()
            c.pop("beat", None)
            c.pop("sv", None)
            T._new_beat(char, st, c, "lull", "phone.lull", "……", now)
            assert "yes" not in [x["id"] for x in T.view(now)["returns"]]          # 言い分を持ち越さない
            # 本物の切れ目: 長く話して掘り下げると, 好み・意見の切れ目が出て, 肯定・否定が並ぶ
            st["known"] = []
            c["deep"] = 5
            seen = 0
            for _ in range(60):
                k, key, txt = T._topic(char, st, c, now)
                if key.startswith("hima."):
                    assert c.get("sv"), key
                    T._new_beat(char, st, c, k, key, txt, now)
                    assert T.rec()["beat"].get("stance") and [x["id"] for x in T.view(now)["returns"]][:2] == ["yes", "no"]
                    seen += 1
                c.pop("sv", None)
            assert seen >= 5, seen
            if mode == "call":
                T.hangup(now + 1)
            else:
                T.end(now + 1)
                app.bonds.end(go_home=False)
                app.bonds.set_stage(cid, "contact")
            print("%s: 並ぶとき・返す OK | 好み・意見の切れ目 %d / 60" % ("電話" if mode == "call" else "対面", seen))

        # ---- 7. セリフ: 全性格に肯定・否定の返しと意見がある
        miss = []
        for pid in PERSONAS:
            char["persona_id"] = pid
            for key in ["chat.react_%s_%s" % (k, r) for k in ("yes", "no") for r in ("good", "neutral", "bad")] + \
                    ["hima.opinion_like", "hima.opinion_dislike"]:
                if not app.persona_text(char, key):
                    miss.append((pid, key))
        print("性格別のセリフが無いもの:", len(miss))
        app.scheduled_scene = sched
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
