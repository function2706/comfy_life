"""対面の会話 (A23 段 4. core/facetalk.py): 会って「話したい」が弾む / ふつうのとき, 電話と同じ切れ目で話が続く.
上の空・うたた寝 (そっとしておく / 掛けてあげる / 起こす)・ほかのことを始めた・電話・離れた で終わる.
絵は様子 (表情・服・場面・状態) が変わったときだけ作り, この会話の生成が終わっていなければ積まない. 電話では絵を作らない (一時データ).

    python tools/test_facetalk.py
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
from core import engine, facetalk as F, hima as H, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(7)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("対面の会話")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "visit")
        char, st = app.char(cid), app.state(cid)
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        FT = app.facetalk
        HIMA = {"res": "hit"}
        real_judge = H.judge

        def judge(a, c, s, now):
            real_judge(a, c, s, now)
            return HIMA["res"], {}
        engine.hima_mod.judge = judge
        jobs = []

        def enqueue(c, eid, pos, neg, seed=None, kind="entry", bg=False):
            jid = "j%d" % len(jobs)
            app.jobs[jid] = {"id": jid, "status": "queued", "kind": kind}
            jobs.append((jid, eid, pos))
            return jid
        app.enqueue = enqueue
        app.make_icon = lambda *a, **k: None
        HAVE = {"imgs": []}
        app.existing_images = lambda pos, neg: list(HAVE["imgs"])

        def fresh(mode="guest", gen=False, **p):
            app.presence.rec().pop("face", None)
            app.presence.rec().pop("call", None)
            st["cooldowns"], st["hima"] = {}, {}
            st.pop("nori", None)
            st.pop("face_doze", None)
            st["reasons"] = []
            if app.bonds.together(cid):
                app.bonds.end(go_home=False)
            app.bonds.start(cid, mode, time.time())
            vals = {"mood": 70, "affection": 75, "trust": 60, "boredom": 50, "loneliness": 50, "sleepiness": 10, "energy": 80}
            vals.update(p)
            app.set_params(vals, cid)
            app.save_settings({"auto_generate": gen})
            HIMA["res"] = "hit"

        def faces():
            return [e for e in app.log(cid) if e.get("action") == "_face"]

        # ---- 1. 始まる / 始まらない: hit・ok は続く, flat は一言で終わり
        for res, want in (("flat", False), ("hit", True), ("ok", True)):
            fresh()
            HIMA["res"] = res
            r = app.act("talk", cid)
            assert bool(r.get("face")) == want, (res, r.get("face"))
            assert bool(FT.rec()) == want
        v = app.face_view()
        assert v["beat"]["kind"] == "reply" and [x["id"] for x in v["returns"]] == ["aizuchi", "dig", "mine", "change", "bye"], v
        assert v["returns"][-1]["label"] == "話を切り上げる"
        assert app.blocked("social") is None and app.blocked("solo") is None        # 会話は何も止めない
        print("始まる: hit / ok は続く・flat は終わり。返し方:", [x["label"] for x in v["returns"]])

        # ---- 2. 返す → 次の切れ目 → 話を切り上げる
        fresh()
        app.act("talk", cid)
        t = time.time()
        out = app.face_reply("dig", t + 2)
        assert out.get("face"), out
        nx = FT.rec()["next"]
        app.face_view(nx + 1)
        assert FT.rec()["beat"]["kind"] in ("topic", "ask", "lull", "quiet"), FT.rec()["beat"]
        e = app.face_end(nx + 3)
        assert e["why"] == "bye" and not FT.rec(), e
        ends = [x for x in app.log(cid) if x.get("action") == "_face_end"]
        assert ends and "話した" in ends[-1]["text"], ends[-1:]
        print("切り上げ:", ends[-1]["text"].replace("\n", " "))

        # ---- 3. 上の空: ねえ、聞いてる？ → 話をやめる. 機嫌の理由 _face_silent
        fresh()
        app.act("talk", cid)
        b = FT.rec()["beat"]
        app.face_view(b["due"] + 0.5)
        hb = FT.rec()["beat"]
        assert hb["stage"] == 1 and "聞いてます" in hb["hello"], hb
        m0 = st["params"]["mood"]
        app.face_view(hb["due"] + 1)
        assert not FT.rec()
        last = FT.last_end()
        assert last and last["why"] == "silent", last
        assert any(x.get("action") == "_face_silent" for x in st.get("reasons") or []) and st["params"]["mood"] < m0
        print("上の空:", last["last"], "| 機嫌 %.1f → %.1f" % (m0, st["params"]["mood"]))

        # ---- 4. うたた寝: 近い仲・家 → 眠い → 眠った. 返し方 3 つ (家なら掛けてあげる). 外 (meet) なら眠いと言って終わる
        for how in ("keep", "cover", "wake"):
            fresh(sleepiness=90)
            app.act("talk", cid)
            app.face_reply("aizuchi", time.time() + 1)
            for _ in range(4):
                c = FT.rec()
                if not c or (c.get("beat") or {}).get("kind") == "asleep":
                    break
                if c.get("beat"):
                    app.face_reply("aizuchi", c["beat"]["t"] + 1)
                else:
                    app.face_view(c["next"] + 1)
            c = FT.rec()
            assert c and c["beat"]["kind"] == "asleep", c and c.get("beat")
            ids = [x["id"] for x in app.face_view(c["beat"]["t"] + 1)["returns"]]
            assert ids == ["keep", "cover", "wake"], ids
            r = app.face_reply(how, c["beat"]["t"] + 2)
            assert r["ended"]["why"] == how, r
            if how == "wake":
                assert r["ended"]["last"] and not st.get("face_doze")
            else:
                dz = st["face_doze"]
                assert FT.wake(char, st, dz["due"] + 1)
                woke = [x for x in app.log(cid) if x.get("action") == "_face_doze"]
                assert woke, "起きた一言が無い"
                print("うたた寝 (%s):" % how, woke[-1]["text"])
        fresh(sleepiness=90)
        ow = app.outside_with
        app.outside_with = lambda c, now=None: True                          # 外で一緒にいる (店・公園など)
        app.act("talk", cid)
        app.face_reply("aizuchi", time.time() + 1)
        for _ in range(4):
            c = FT.rec()
            if not c:
                break
            if c.get("beat"):
                app.face_reply("aizuchi", c["beat"]["t"] + 1)
            else:
                app.face_view(c["next"] + 1)
        app.outside_with = ow
        assert not FT.rec() and FT.last_end()["why"] == "sleepy", FT.last_end()
        print("外では うたた寝しない:", FT.last_end()["last"])

        # ---- 5. ほかのことを始めた / 電話 / 離れた
        fresh()
        app.act("talk", cid)
        m0 = st["params"]["mood"]
        try:
            app.act("ask_mood", cid)
        except ValueError:
            pass
        assert not FT.rec() and FT.last_end()["why"] == "other", FT.last_end()
        fresh()
        app.act("talk", cid)
        m0 = st["params"]["mood"]
        FT.interrupt(time.time() + 1, "phone")
        assert FT.last_end()["why"] == "phone" and st["params"]["mood"] < m0
        assert any(x.get("action") == "_face_cut" for x in st.get("reasons") or [])
        fresh()
        app.act("talk", cid)
        app.face_after({"ok": True})
        assert not FT.rec() and FT.last_end()["why"] == "other"
        fresh()
        app.act("talk", cid)
        n = len(app.log(cid))
        app.bonds.end(go_home=False)
        assert app.face_view() is None and FT.last_end()["why"] == "apart"
        assert len(app.log(cid)) == n, "離れたのに記録が増えた"
        print("終わり方: ほかのこと・電話・ゲーム / 一人のこと・離れた OK")

        # ---- 6. 絵: 様子が変わったときだけ. 生成中は積まない. 使い回し. 自動生成オフでは作らない
        fresh(gen=True)
        app.act("talk", cid)
        c = FT.rec()
        assert c["job"] and app.jobs[c["job"]]["status"] == "queued"         # 「話したい」の絵を作っている
        FT.judge = lambda ch, s, cc, kind, now: ("bad", -30)
        n0 = len(faces())
        app.face_reply("aizuchi", time.time() + 1)
        assert len(faces()) == n0, "生成中なのに積んだ"
        app.jobs[c["job"]]["status"] = "done"
        c = FT.rec()
        app.face_view(c["next"] + 1)                                         # 次の切れ目: sulk に変わる → 作る
        c = FT.rec()
        assert len(faces()) == n0 + 1 and c["look"] in ("sulk", "quiet"), (len(faces()), c["look"])
        lk, j1 = c["look"], c["job"]
        app.jobs[j1]["status"] = "done"
        FT.judge = lambda ch, s, cc, kind, now: ("neutral", 0)
        k0 = len(faces())
        for _ in range(3):                                                    # 様子が同じなら作らない
            c = FT.rec()
            if c.get("beat"):
                app.face_reply("aizuchi", c["beat"]["t"] + 1)
            else:
                app.face_view(c["next"] + 1)
            c = FT.rec()
            if not c:
                break
        same = sum(1 for e in faces()[k0:] if e["pos"] == faces()[k0 - 1]["pos"])
        assert same == 0, "同じ様子で作り直した"
        print("絵: 生成中は積まない / 変わったら作る (%s) / 同じなら作らない (作った数 %d)" % (lk, len(faces()) - n0))
        fresh(gen=True)
        HAVE["imgs"] = [{"path": "x/y.png", "seed": 1}]
        app.settings.setdefault("images", {})["mode"] = "reuse"
        app.act("talk", cid)
        FT.rec()["job"] = None
        FT.judge = lambda ch, s, cc, kind, now: ("good", 30)
        FT.set_look(char, st, FT.rec(), "sulk", "……", time.time())
        e = faces()[-1]
        assert e.get("reused") and e["image"] == "x/y.png", e
        HAVE["imgs"] = []
        fresh(gen=False)
        app.act("talk", cid)
        k0 = len(faces())
        FT.set_look(char, st, FT.rec(), "sulk", "……", time.time())
        assert len(faces()) == k0 and FT.rec()["look"] == "sulk"
        print("絵: 使い回し・自動生成オフ OK")
        del FT.judge

        # ---- 7. 電話は声だけ: 通話の切れ目では絵を作らない
        fresh(gen=True)
        app.bonds.end(go_home=False)
        j0 = len(jobs)
        now = time.time()
        app.phonetalk.begin(char, st, "もしもし", True, now)
        for i in range(4):
            cc = app.phonetalk.rec()
            if not cc:
                break
            if cc.get("beat"):
                app.phonetalk.reply("aizuchi", cc["beat"]["t"] + 1)
            else:
                app.phonetalk.tick(cc["next"] + 1)
        assert len(jobs) == j0, "電話で絵を作った"
        print("電話では絵を作らない OK")
        app.scheduled_scene = sched
        engine.hima_mod.judge = real_judge
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
