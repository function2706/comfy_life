"""電話の対話 (A23 段 1. core/phonetalk.py): 話している間, 切れ目ごとに返して電話が続く. 時計は実時間 (一時データ).

- 通話中: ほかの連絡・誰かとすること・内職・ゲームはできない. 手が空く一人のこと (家事・休む・歩き / 電車) は, ながらでできる
- 切れ目 × 返し方 × 性格 × 仲: よく合う返しでも必ず「よい」にはならない / 外した返しでも必ず「よくない」にはならない
- 返事を待つ時間の幅 (5〜25 秒. 文が長いほど延びる)
- 黙ったとき: もしもし？ → 相手から切る. 機嫌の理由 (謝れる心当たり)・見立て. あなたからかけたときのほうが重い
- 切る理由ごとの謝り方 (用事 → 謝る・またかけるね / 乗らない → 謝らない) / あなたの約束で切る
- 寝落ち: 眠そう → 寝息 → 切る / おやすみ / つないだまま → 翌朝のひとこと
- 相手からかけてきたのに, すぐ切る → 気にする
- 開き直し・再起動で通話が残る / 以前の形 (until) の通話は終わったことに / 閉じていた間は, 時刻をさかのぼって切れる
- _call_limit (約束・予定・相手の寝る時刻・次の用事・あなたの体力) はそのまま

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
from core import engine, phonetalk, planner, store  # noqa: E402
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
        C, PT = app.chat, app.phonetalk

        def fresh(**params):
            if PT.rec() and "beat" in PT.rec() or PT.rec() and "next" in PT.rec():
                app.call_end()                             # 前の通話は切っておく (トークの行が「話している…」のまま残らないように)
            st["contacts"], st["cooldowns"] = [], {}
            for k in ("msg_pending", "nori", "call_doze", "call_back", "reasons", "call_sorries"):
                st.pop(k, None)
            app.presence.rec().pop("call", None)
            app.presence.rec().pop("solo", None)
            app.presence.rec()["mode"] = "none"
            app.set_params(dict({"mood": 75, "affection": 65, "trust": 60, "boredom": 60, "loneliness": 70, "sleepiness": 10,
                                 "energy": 80}, **params), cid)

        def call():
            r = app.phone_call(cid, "smalltalk")
            assert r.get("call") and r["call"]["beat"]["kind"] == "reply", r
            return PT.rec()

        # ---- 1. つながる: 最初の切れ目は相手の受け答え. 通話中は, 連絡・誰かとすること・内職・ゲームはできない. 一人のことは, ながらで
        fresh()
        t0 = time.time()
        c = call()
        assert c["cid"] == cid and c["t"] >= t0 and c["by"] == "me" and "until" not in c, c
        v = app.call_view()
        assert v["name"] == char["name"] and [x["id"] for x in v["returns"]] == ["aizuchi", "dig", "mine", "change", "bye"], v
        assert 5 <= v["beat"]["left"] <= 25, v["beat"]
        for w in ("social", "side_job", "game"):
            assert "電話で話している途中" in (app.blocked(w) or ""), (w, app.blocked(w))
        assert app.blocked("solo") is None and app.blocked("cook") is None, "ながら電話: 一人のことは止めない"
        must_fail(lambda: app.phone_call(cid, "smalltalk"), "電話で話している途中")
        must_fail(lambda: C.send(cid, "smalltalk"), "電話で話している途中")
        must_fail(lambda: app.solo.start("practice"), "電話で話している途中")
        must_fail(lambda: app.solo.start("read"), "電話で話している途中")
        must_fail(lambda: app.solo.start("work"), "電話で話している途中")
        must_fail(lambda: app.solo.start("sleep"), "電話で話している途中")
        assert PT.nagara_why("out", "car") and PT.nagara_why("out", "bike") and not PT.nagara_why("out", "walk") \
            and not PT.nagara_why("out", "transit"), "運転・自転車はできない / 歩き・電車はできる"
        r = app.solo.start("chores")                       # 家事: 電話しながら
        assert r.get("started") == "chores" or app.presence.rec().get("solo", {}).get("kind") == "chores", r
        assert PT.doing_now(time.time()) == "chores"
        print("通話中: 止めるもの / ながらでできるもの OK")

        # 画面で押せる = 本当にできる: 一人の行動の一覧で押せるもの (ok) が, 通話中に始められるかと合う
        for k in ("rest", "chores", "practice", "read", "movie", "jog"):
            app.presence.rec().pop("solo", None)
            app.presence.rec()["mode"] = "none"
            ok = k in phonetalk.NAGARA
            try:
                app.solo.start(k, skill="talk" if k == "practice" else None)
                started = True
            except ValueError as e:
                started = "電話" not in str(e)          # 電話以外の理由 (本が無い など) は数えない
            assert started == ok, (k, ok, started)
        app.presence.rec().pop("solo", None)
        app.presence.rec()["mode"] = "none"
        print("通話中の一人の行動: 家事・休む だけ始められる OK")

        # ---- 2. 返す: 切れ目が消えて「話している」. 次の切れ目は数分のうち (ノリが高いほど早い)
        c = PT.rec()
        now = c["beat"]["t"] + 3
        out = app.call_reply("dig", now)
        assert "call" in out or "ended" in out, out
        if "call" in out:
            c = PT.rec()
            assert "beat" not in c and phonetalk.GAP[0] * 0.7 - 1 <= c["next"] - now <= phonetalk.GAP[1] * 1.3 + 1, c
            must_fail(lambda: app.call_reply("dig", now + 1), "返すところではありません")
            v = app.call_view(c["next"] + 0.5)
            assert v.get("beat") and v["beat"]["kind"] in ("topic", "ask", "lull", "quiet", "what", "sleepy"), v
        print("返す → 話している → 次の切れ目 OK")

        # ---- 3. 返事を待つ時間: 5〜25 秒. 文が長いほど延びる
        ws = [PT.wait_secs(char, st, "あ" * n, "lull", time.time()) for n in (5, 120) for _ in range(30)]
        short, long_ = ws[:30], ws[30:]
        assert all(phonetalk.WAIT_MIN <= w <= phonetalk.WAIT_MAX for w in ws)
        assert sum(long_) > sum(short) + 30 * 5, (sum(short) / 30, sum(long_) / 30)
        print("待つ時間: 短い文 %.1f 秒 / 長い文 %.1f 秒" % (sum(short) / 30, sum(long_) / 30))

        # ---- 4. 黙ったとき: もしもし？ → 切る. 機嫌の理由 (謝れる心当たり)・トークに相手の最後のひとこと
        fresh()
        c = call()
        b = c["beat"]
        v = app.call_view(b["due"] + 0.1)
        assert v["beat"]["stage"] == 1 and v["beat"]["text"] in (PT.line(char, "phone.hello"), PT.line(char, "phone.hello_asleep")) \
            or v["beat"]["stage"] == 1, v
        mood0 = st["params"]["mood"]
        due2 = PT.rec()["beat"]["due"]
        assert app.call_view(due2 + 0.1) is None and app.call_now(due2 + 0.1) is None
        e = PT.last_end()
        assert e["why"] == "silent" and e["who"] == "her", e
        assert st["params"]["mood"] < mood0, (mood0, st["params"]["mood"])
        rs = [r for r in st.get("reasons") or [] if r.get("action") == "_call_silent"]
        assert rs and rs[-1]["mood"] == "bad", st.get("reasons")
        from core import msgpick
        assert msgpick.reason_item(rs[-1]) == "call_silent"
        last = [it for it in C.load(cid)["items"] if it.get("who") == "her"][-1]
        assert last["kind"] == "call_end" and last["text"].startswith("📞『"), last
        sysl = [it for it in C.load(cid)["items"] if it.get("who") == "sys" and it["text"].startswith("📞 電話で話した（")]
        assert sysl and "返事をしなくなり" in sysl[-1]["text"], sysl[-1:]
        print("黙った:", sysl[-1]["text"], "/", last["text"])

        # 重さ: あなたからかけて黙ったほうが, 相手からかけて黙ったより重い (平均で)
        def silent_drop(by, mine, n=60):
            tot = 0.0
            for _ in range(n):
                fresh(mood=70)
                c = call()
                c["by"] = by
                c["beat"]["mine"] = mine
                b = c["beat"]
                app.call_view(b["due"] + 0.1)
                app.call_view(PT.rec()["beat"]["due"] + 0.1)
                tot += 70 - st["params"]["mood"]
            return tot / n
        me, her, mine = silent_drop("me", False), silent_drop("her", False), silent_drop("me", True)
        assert me > her * 1.15 and mine > me * 1.15, (me, her, mine)
        print("黙った重さ: あなたから %.1f / 相手から %.1f / 相手の話の最中 %.1f" % (me, her, mine))

        # ---- 5. 閉じていた間: 開いたときに時刻をさかのぼって切れる (要約の時刻は切れた時刻)
        fresh()
        c = call()
        later = c["beat"]["due"] + 3600
        assert app.call_now(later) is None
        e = PT.last_end()
        assert e["why"] == "silent", e
        it = [x for x in C.load(cid)["items"] if x.get("who") == "her"][-1]
        assert it["t"] < c["beat"]["due"] + 60, "切れたのは, 閉じていた間 (期限のすぐあと)"
        print("閉じていた間に切れた: OK")

        # ---- 6. 切れ目 × 返し方 × 性格 × 仲の総当たり: よくても必ずではない / 悪くても必ずではない
        fresh()
        c = call()
        tally = {}
        for pid in sorted(app.personas):
            char["persona_id"] = pid
            for aff in (35, 65, 85):
                app.set_params({"affection": aff, "mood": 60}, cid)
                for bk in phonetalk.FIT:
                    c["beat"]["kind"] = bk
                    for k in phonetalk.BASE:
                        if k in phonetalk.STANCE_KIND:        # 意見への返し (そうだね / それはちょっと) は stance.fit で. tools/test_stance.py
                            continue
                        res = [PT.judge(char, st, c, k, time.time())[0] for _ in range(40)]
                        tally.setdefault((bk, k), []).extend(res)
        rate = {key: (res.count("good") / float(len(res)), res.count("bad") / float(len(res))) for key, res in tally.items()}
        for (bk, k), (g, b_) in rate.items():
            fit = phonetalk.FIT[bk][k]
            if fit >= 8:
                assert g < 1, (bk, k, "よく合う返しが必ずよい", g, b_)
            if fit <= -8:
                assert b_ < 1 and g > 0, (bk, k, "外した返しが必ずよくない", g, b_)
                assert g < 0.4, (bk, k, "外した返しがよく効きすぎる", g)
        for bk, fits in phonetalk.FIT.items():
            best, worst = max(fits, key=fits.get), min(fits, key=fits.get)
            assert rate[(bk, best)][0] > rate[(bk, worst)][0] + 0.25, (bk, best, worst, rate[(bk, best)], rate[(bk, worst)])
        char["persona_id"] = app.char(cid).get("persona_id")
        app.presence.rec().pop("call", None)
        print("総当たり: %d 性格 × 3 仲 × %d 切れ目 × %d 返し OK" % (len(app.personas), len(phonetalk.FIT), len(phonetalk.BASE)))

        # ---- 7. 同じ返しばかりは効きが落ちる
        fresh()
        c = call()
        c["beat"]["kind"] = "topic"
        a = sum(PT.judge(char, st, dict(c, last=None, rep=0), "aizuchi", time.time())[1] for _ in range(300))
        b2 = sum(PT.judge(char, st, dict(c, last="aizuchi", rep=3), "aizuchi", time.time())[1] for _ in range(300))
        assert a > b2 + 300 * 8, (a / 300, b2 / 300)
        app.presence.rec().pop("call", None)
        print("相づちばかり: %.1f → %.1f OK" % (a / 300, b2 / 300))

        # ---- 8. 切る理由: 相手の用事 → 謝る (ことがある)・またかけるね / あなたの約束 → あなたから / 乗らない → 謝らない
        sorry = back = 0
        for _ in range(40):
            fresh()
            c = call()
            c.pop("beat")
            c["next"] = c["t"] + 3
            c["lim"], c["cut"], c["mine_cut"] = c["t"] + 2, "%sに次の用事がある" % char["name"], False
            app.call_now(c["t"] + 5)
            e = PT.last_end()
            assert e["why"] == "limit" and e["who"] == "her", e
            last = next(it for it in C.load(cid)["items"] if it.get("who") == "her" and abs(it["t"] - (c["t"] + 2)) < 0.01)
            sorry += last["kind"] == "call_sorry"
            back += bool(st.get("call_back"))
            if last["kind"] == "call_sorry":
                from core import react
                assert react.tone_of(app, st, last) == "sorry", "謝られた: 「気にしないで」で返せる"
        assert 5 < sorry < 40 and 0 < back <= sorry, (sorry, back)
        print("用事で切る: 40 回中 謝った %d・またかけるね %d" % (sorry, back))
        fresh()
        c = call()
        c.pop("beat")
        c["next"] = c["t"] + 3
        c["lim"], c["cut"], c["mine_cut"] = c["t"] + 2, "約束がある", True
        app.call_now(c["t"] + 5)
        e = PT.last_end()
        assert e["who"] == "you" and e["why"] == "limit" and not e["last"] and "約束がある" in e["note"], e
        fresh()
        c = call()
        st["nori"]["v"] = 21.0
        st["nori"]["turns"] = 5
        c["beat"]["kind"] = "topic"
        for _ in range(20):
            out = app.call_reply("change")
            if "ended" in out:
                break
            c = PT.rec()
            c.pop("next", None)
            PT._new_beat(char, st, c, "topic", "call.topic_plain", "x", time.time())
            st["nori"]["v"] = 21.0
        assert "ended" in out and out["ended"]["why"] in ("cold", "silent"), out
        if out["ended"]["why"] == "cold":
            last = [it for it in C.load(cid)["items"] if it.get("who") == "her" and it["t"] >= c["t"]
                    and it["text"] == "📞『%s』" % out["ended"]["last"]]
            assert last and last[-1]["kind"] == "call_end", last          # 乗らなくて切るときは, 謝らない
        print("切る理由: あなたの約束 / 乗らない OK")

        # ---- 9. そろそろ切る (あなたから): 応じる. 相手からかけてきてすぐなら, 気にする
        fresh()
        c = call()
        out = app.call_reply("bye")
        assert out["ended"]["who"] == "you" and out["ended"]["why"] == "bye", out
        fresh()
        c = call()
        c["by"] = "her"
        e = app.call_end()
        assert e["why"] == "hangup"
        assert any(r.get("action") == "_call_cut" for r in st.get("reasons") or []), "相手からかけてきたのに, すぐ切った"
        print("あなたから切る: OK")

        # ---- 10. 寝落ち: 近い仲で眠い → 眠そう → 寝息 → つないだまま → 翌朝のひとこと
        app.bonds.set_stage(cid, "visit")
        fresh(sleepiness=90, affection=80)
        c = call()
        c.pop("beat")
        c["next"] = time.time() - 1
        app.call_now()
        assert PT.rec()["beat"]["kind"] == "sleepy", PT.rec()["beat"]
        app.call_reply("aizuchi")
        c = PT.rec()
        if c:
            c["next"] = time.time() - 1
            app.call_now()
            v = app.call_view()
            assert v["beat"]["kind"] == "asleep" and [x["id"] for x in v["returns"]] == ["hang", "night", "keep"], v
            assert v["beat"]["left"] is None, "寝息は待たない (黙っていても切れない)"
            must_fail(lambda: app.call_reply("dig"), "寝息")
            out = app.call_reply("keep")
            assert out["ended"]["why"] == "keep" and st.get("call_doze"), out
            dz = st["call_doze"]
            assert datetime.fromtimestamp(dz["due"]).hour in (7, 8), dz
            assert not PT.morning(char, st, dz["due"] - 60)
            assert PT.morning(char, st, dz["due"] + 60) and "call_doze" not in st
            last = [it for it in C.load(cid)["items"] if it.get("who") == "her"][-1]
            assert last["kind"] == "call_morning" and last["text"].startswith("📱『"), last
            print("寝落ち → つないだまま → 翌朝:", last["text"])
        # 浅い仲は, 眠いと言って切る
        app.bonds.set_stage(cid, "contact")
        fresh(sleepiness=90, affection=50)
        c = call()
        c.pop("beat")
        c["next"] = time.time() - 1
        app.call_now()
        assert PT.last_end()["why"] == "sleepy", PT.last_end()
        print("浅い仲で眠い: 切り上げる OK")

        # ---- 11. 開き直し・再起動: 通話は残る (二重にならない) / 以前の形 (until) は終わったことに
        # 出てもらえなかった電話のすぐあとにかけ直しても, 前の電話の行は書き換えない
        fresh()
        st["override"] = {"activity": "class", "label": "講義中", "location": "大学", "away": True, "until": time.time() + 600}
        t1 = time.time()
        app.phone_call(cid, "smalltalk")
        assert not PT.rec()
        st.pop("override")
        fresh()
        c = call()
        mine = [it for it in C.load(cid)["items"] if it.get("who") == "sys" and it.get("kind") == "call" and it["t"] >= t1]
        assert [it["text"] for it in mine].count("📞 電話で話している…") == 1 and \
            next(it for it in mine if it["text"] == "📞 電話で話している…")["t"] == c["sys_t"], [it["text"] for it in mine]
        app2 = engine.App()
        assert app2.call_now() and app2.call_now()["cid"] == cid and app2.call_view()["beat"]["id"] == app.call_view()["beat"]["id"]
        must_fail(lambda: app2.phone_call(cid, "smalltalk"), "電話で話している途中")
        app.presence.rec()["call"] = {"cid": cid, "name": char["name"], "t": time.time(), "until": time.time() + 600, "mins": 10}
        app.presence.save()
        assert app.call_now() is None and "call" not in app.presence.rec(), "以前の形の通話は, その場で終わったことに"
        print("開き直し・以前の形 OK")

        # ---- 12. 運転中はかけられない / 研鑽の途中はかけられない
        fresh()
        app.presence.rec()["travel"] = {"how": "car", "arr": time.time() + 600, "t0": time.time(), "to": "station"}
        assert "運転中" in (PT.start_why(time.time()) or "")
        app.presence.rec()["travel"]["how"] = "transit"
        assert PT.start_why(time.time()) is None
        app.presence.rec().pop("travel")
        app.presence.rec().update(mode="busy", solo={"kind": "practice", "t": time.time()})
        must_fail(lambda: app.phone_call(cid, "smalltalk"), "研鑽")
        app.presence.rec().update(mode="none")
        app.presence.rec().pop("solo")
        print("かけられないとき OK")

        # ---- 13. 長さの切り上げ (_call_limit): いままでどおり
        now = time.time()
        assert app._call_limit(char, st, now, 40) == (40, None)
        ap = app.appoint.all()
        lead = planner.APPOINT_LEAD
        ap.append({"id": "t1", "cid": cid, "t": now + lead + 15 * 60, "status": "set"})
        mins, cut = app._call_limit(char, st, now, 40)
        assert mins == 15 and cut == "約束がある", (mins, cut)
        ap[-1]["status"] = "cancelled"
        assert app._call_limit(char, st, now, 40) == (40, None)
        ap.pop()
        items = app.planner.rec()["items"]
        at = datetime.fromtimestamp(now + 12 * 60 + 30)
        items.append({"id": "p1", "date": at.date().isoformat(), "at": at.strftime("%H:%M"), "do": "rest"})
        mins, cut = app._call_limit(char, st, now, 40)
        assert 11 <= mins <= 13 and cut == "予定の時刻が近い", (mins, cut)
        items.pop()
        app.scheduled_scene = lambda c, d: dict(free(c, d), asleep=d.timestamp() >= now + 10 * 60 - 1)
        mins, cut = app._call_limit(char, st, now, 40)
        assert mins == 10 and cut == "%sが寝る時間になる" % char["name"], (mins, cut)
        app.scheduled_scene = free
        ps = app.life.player_state()
        s0 = ps.get("stamina", 100)
        ps["stamina"] = 10
        mins, cut = app._call_limit(char, st, now, 40)
        assert mins == 24 and cut == "あなたが疲れていた", (mins, cut)
        ps["stamina"] = s0
        # つながったときに, 相手の寝る時刻を切り上げとして持つ (相手から切る)
        fresh()
        app.scheduled_scene = lambda c, d: dict(free(c, d), asleep=d.timestamp() >= time.time() + 15 * 60)
        c = call()
        assert c["lim"] and not c["mine_cut"] and "寝る" in c["cut"], c
        app.scheduled_scene = free
        print("切り上げ OK")

        # ---- 14. 出なかった電話は, 通話中にならない
        fresh()
        app.scheduled_scene = lambda c, d: dict(free(c, d), asleep=True)
        del app._call_missed
        r = app.phone_call(cid, "smalltalk")
        assert not r.get("call") and app.call_now() is None, r
        app.scheduled_scene = free
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
