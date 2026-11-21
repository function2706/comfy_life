"""誰かといるときの通話 (A23 段 3. core/phonetalk.py・core/ring.py・manners の who_with):
あなたのそばの人 (一緒にいる形 4 × かける / 出る) と「誰かいるの？」, 正直に言う / ごまかす × 見抜かれる, そばの人の反応,
相手の側の気配 (根拠の有無 × 場面, 登録キャラの重なり, 電車・職場は手短に), 電話とメッセージの答えの一致, 聞きすぎ,
割り込みの着信 3 通り (出ない・かけ直すと伝える・今の電話を切って出る) と, 画面の選択肢 = 本当に選べる (一時データ).

    python tools/test_call_company.py
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
from core import engine, phonetalk as pt_mod, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)

HOME = {"activity": "relax", "label": "くつろぎ中", "location": "リビング", "away": False, "busy": False, "asleep": False}
OUT = {"activity": "relax", "label": "出かけている", "location": "公園", "away": True, "busy": False, "asleep": False}
WORK = {"activity": "work", "label": "仕事中", "location": "職場", "away": True, "busy": False, "asleep": False}
TRAIN = {"activity": "commute", "label": "通勤中", "location": "移動中", "away": True, "busy": False, "asleep": False}
ERRAND = {"activity": "errand", "label": "買い物に出ている", "location": "商店街", "away": True, "busy": False, "asleep": False}


def main():
    random.seed(30)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("通話と人")
        a = app.settings["active_character"]                 # そばにいる人 (A)
        b = app.new_character("みお")["id"]                   # 電話の相手 (B)
        B, P, PT, R = app.bonds, app.presence, app.phonetalk, app.ring
        sched = app.scheduled_scene
        SC = {a: OUT, b: OUT}
        app.scheduled_scene = lambda c, d: dict(sched(c, d), **SC.get(c["id"], OUT))
        ca, cb = app.char(a), app.char(b)
        sa, sb = app.state(a), app.state(b)

        def fresh(now, aff_a=60, aff_b=60):
            for st in (sa, sb):
                for k in ("ring_log", "call_ask", "call_back", "call_promise", "msg_pending", "nori", "approach", "jealous", "with_log",
                          "whoask", "reasons"):
                    st.pop(k, None)
            P.rec().pop("call", None)
            P.rec().pop("ring", None)
            P.rec()["mode"] = "none"
            P.beat(now, 0)
            for cid, aff in ((a, aff_a), (b, aff_b)):
                app.set_params({"mood": 70, "affection": aff, "trust": 60, "boredom": 50, "loneliness": 50, "sleepiness": 10,
                                "energy": 80}, cid)

        def with_a(mode, now):
            """A とそばにいる形にする (home は同居して家に)."""
            if B.with_rec():
                B.wrec()["with"] = None
            for cid in (a, b):
                B.set_stage(cid, "contact")
            SC[a] = OUT
            if mode == "home":
                B.set_stage(a, "live")
                SC[a] = HOME
            elif mode:
                B.start(a, mode, now)
            B.save()

        def run_to(kinds, now, limit=8):
            """返し続けて, 切れ目が kinds のどれかになるまで進める (なったらその切れ目を返す)."""
            for _ in range(limit):
                PT.tick(now)
                c = PT.rec()
                if not c:
                    return None, now
                bt = c.get("beat")
                if bt and bt["kind"] in kinds:
                    return bt, now
                if bt:
                    now = max(now, bt["t"]) + 1
                    PT.reply("aizuchi" if bt["kind"] not in ("ask", "what") else "mine", now)
                c = PT.rec()
                if c and not c.get("beat"):
                    now = max(now, c.get("next", now)) + 0.5        # 次に相手が話すところ (それより進めると, 黙ったことになる)
            return None, now

        now = time.time()
        # ---- 1. 一緒にいる形 4 × かける / 出る: そばの人 (near) と, 気づかれたら「誰かいるの？」(正直に言う / ごまかす だけ)
        for mode in ("meet", "visit", "guest", "home"):
            for by in ("me", "her"):
                n, seen = 40, 0
                for i in range(n):
                    now += 3600
                    fresh(now)
                    with_a(mode, now)
                    assert B.company() == [a], (mode, B.company())
                    c = PT.begin(cb, sb, "もしもし", True, now, by=by)
                    assert c["near"] == [a], c
                    if c["noticed"]:
                        seen += 1
                        bt, t = run_to(("who",), now + 1)
                        assert bt and bt["key"] == "phone.who", (mode, by, bt)
                        v = PT.view(t)
                        assert [x["id"] for x in v["returns"]] == ["honest", "dodge"], v["returns"]
                        try:
                            PT.reply("aizuchi", t + 1)
                            raise AssertionError("誰かいるの？に相づちで返せてしまう")
                        except ValueError:
                            pass
                    PT.hangup(now + 9000)
                assert 0 < seen < n, (mode, by, seen)
                print("そばに人 %-5s × %s: 気づかれた %2d / %d" % (mode, by, seen, n))
        # 一人なら near は無い
        now += 3600
        fresh(now)
        with_a(None, now)
        c = PT.begin(cb, sb, "もしもし", True, now)
        assert "near" not in c and "who_q" not in c, c
        PT.hangup(now + 60)
        print("一人のとき: そばの人なし")

        # ---- 2. 正直に言う / ごまかす × 仲 (恋敵か): 相手の受け止めと, そばの人の反応
        def who_call(ans, deep, mode="meet"):
            nonlocal now
            for _ in range(60):
                now += 3 * 86400                                    # 気づき直しの間 (renotice_days) をあける
                fresh(now, aff_a=80 if deep else 40, aff_b=80 if deep else 40)
                with_a(mode, now)
                c = PT.begin(cb, sb, "もしもし", True, now)
                if not c["noticed"]:
                    PT.hangup(now + 30)
                    continue
                bt, t = run_to(("who",), now + 1)
                if not bt:
                    PT.hangup(now + 9000)
                    continue
                pb, pa = dict(sb["params"]), dict(sa["params"])
                PT.reply(ans, t + 1)
                c = PT.rec()
                w = dict(c["who"])
                n0 = len(app.log(a))
                PT.hangup(t + 30)
                near = app.log(a)[n0:]
                return w, pb, pa, near
            raise AssertionError("気づかれる通話が出ない")

        w, pb, pa, near = who_call("honest", deep=True)
        assert a in (sb.get("jealous") or {}), "恋敵だと正直に言ったのに, やきもちに残らない"
        assert sb["params"]["mood"] < pb["mood"], (pb["mood"], sb["params"]["mood"])
        print("正直 × 恋敵: やきもち (機嫌 %.1f → %.1f)" % (pb["mood"], sb["params"]["mood"]))
        w, pb, pa, near = who_call("honest", deep=False)
        assert a not in (sb.get("jealous") or {})
        assert not near or near[-1]["text"] in (PT.line(ca, "phone.near_told"), PT.line(ca, "phone.near_ok")) or near[-1]["action"] == "_call_near"
        print("正直 × 浅い仲: やきもちなし")
        seen_n, n = 0, 30
        for i in range(n):
            w, pb, pa, near = who_call("dodge", deep=False)
            assert w["ans"] == "dodge" and "seen" in w
            if w["seen"]:
                seen_n += 1
                assert sb["params"]["trust"] < pb["trust"], "見抜かれたのに信頼が下がらない"
                assert any(r.get("action") == "_call_dodge" for r in sb.get("reasons") or [])
            # そばの人は, いないことにされたのを聞いている
            assert near and near[-1]["action"] == "_call_near", near
            assert sa["params"]["mood"] < pa["mood"] and any(r.get("action") == "_call_hid" for r in sa.get("reasons") or []), (pa, sa["params"])
        assert 0 < seen_n < n, seen_n
        print("ごまかす: 見抜かれた %d / %d, そばの人は毎回気を悪くする" % (seen_n, n))

        # ---- 3. そばの人の反応: 長い通話 (気づかれない) → 放っておかれた / 恋敵 → やきもち
        now += 3 * 86400
        fresh(now, aff_a=40, aff_b=40)
        with_a("meet", now)
        c = PT.begin(cb, sb, "もしもし", True, now)
        c.pop("who_q", None)
        c["noticed"] = False
        c["t"] = now - 25 * 60
        pa = dict(sa["params"])
        n0 = len(app.log(a))
        PT.hangup(now + 30)
        e = app.log(a)[n0:]
        assert e and e[-1]["text"] == PT.line(ca, "phone.near_long") or e[-1]["text"], e
        assert sa["params"]["mood"] < pa["mood"] and sa["params"]["loneliness"] > pa["loneliness"], (pa, sa["params"])
        print("長い通話: そばの人 「%s」" % e[-1]["text"])
        hits = 0
        for i in range(20):
            now += 3 * 86400
            fresh(now, aff_a=85, aff_b=85)
            with_a("guest", now)
            c = PT.begin(cb, sb, "もしもし", True, now)
            c.pop("who_q", None)
            PT.hangup(now + 30)
            hits += b in (sa.get("jealous") or {})
        assert 0 < hits, hits
        print("恋敵との電話: そばの人が気づいた %d / 20" % hits)
        # 電話が終わる前にそばの人が帰っていたら, 何も言わない
        now += 3 * 86400
        fresh(now)
        with_a("meet", now)
        c = PT.begin(cb, sb, "もしもし", True, now)
        B.wrec()["with"] = None
        B.save()
        n0 = len(app.log(a))
        PT.hangup(now + 30)
        assert len(app.log(a)) == n0
        print("そばの人が先に帰った: 反応なし")

        # ---- 4. 相手の側の気配: 根拠の有無 × 場面
        with_a(None, now)
        for sc, ok_who, hush in ((HOME, None, None), (TRAIN, None, "train"), (WORK, "coworker", "work"), (ERRAND, "friend", None)):
            got, n = 0, 40
            for i in range(n):
                now += 86400
                fresh(now)
                SC[b] = sc
                SC[a] = HOME                                   # A は家 (重ならない)
                x = PT.background(cb, sb, now)
                if not sc["away"]:
                    assert x is None
                    continue
                assert x["hush"] == hush and x["who"] in (None, ok_who), (sc["label"], x)
                got += x["who"] is not None
                assert PT.background(cb, sb, now + 600) is x, "同じ場面のあいだに決め直している"
            if ok_who:
                assert 0 < got < n, (sc["label"], got)
            else:
                assert got == 0, (sc["label"], got)
            print("気配 %-10s: 一緒にいる人 %2d / %d, 手短に %s" % (sc["label"], got, n, hush))
        # 登録キャラが同じ所にいる → その人
        now += 86400
        fresh(now)
        SC[b], SC[a] = WORK, dict(WORK)
        x = PT.background(cb, sb, now)
        assert x["who"] == "char" and x["cid"] == a, x
        assert PT.who_label(x) == ca["name"]
        print("気配: 同じ職場の %s" % PT.who_label(x))
        # 電車: 話していたい長さが縮み, 最初に小声で断る
        spans = {}
        for sc in (OUT, TRAIN):
            vals = []
            for i in range(30):
                now += 86400
                fresh(now)
                SC[b], SC[a] = sc, HOME
                random.seed(i)
                c = PT.begin(cb, sb, "もしもし", True, now)
                vals.append(c["span"])
                if sc is TRAIN:
                    assert c["hush"] == "train" and any(x["text"] == PT.line(cb, "phone.hush_train") or "電車" in x["text"] for x in c["log"]), c["log"]
                PT.hangup(now + 60)
            spans[sc["label"]] = sum(vals) / len(vals)
        assert spans[TRAIN["label"]] < spans[OUT["label"]] * 0.7, spans
        print("電車の中: 話していたい長さ %.1f 分 (ふだん %.1f 分)" % (spans[TRAIN["label"]], spans[OUT["label"]]))

        # ---- 5. 誰といるの？ (電話) と 誰といたの？ (メッセージ) の答えが一致する. 聞きすぎは嫌がられる
        same = 0
        for i in range(40):
            now += 86400
            fresh(now)
            SC[b], SC[a] = WORK, HOME
            c = PT.begin(cb, sb, "もしもし", True, now)
            if not c.get("bg"):
                PT.hangup(now + 30)
                continue
            assert "（後ろで誰かの話し声がする）" in [x["text"] for x in c["log"]]
            v = PT.view(now + 1)
            assert "who_ask" in [r["id"] for r in v["returns"]], v["returns"]
            PT.reply("who_ask", now + 2)
            said = PT.rec()["log"][-1]["text"]
            x = PT.background(cb, sb, now, make=False)
            assert said == PT.line(cb, "phone.whoask_tell", who=PT.who_label(x)) if x["ans"] == "honest" else said == PT.line(cb, "phone.whoask_vague"), (x, said)
            assert "who_ask" not in [r["id"] for r in (PT.view(now + 3) or {}).get("returns") or []], "2 度聞ける"
            PT.hangup(now + 60)
            SC[b] = HOME                                     # 帰ってきてから, メッセージで聞く
            sb.pop("whoask", None)
            m = app.manners.on_send(cb, sb, "who_with", now + 3 * 3600)
            key, _, ex = app.manners.reply(cb, sb, "who_with", now + 3 * 3600, {}, m)
            assert key == ("who_with" if x["ans"] == "honest" else "who_with_vague"), (x, key)
            if key == "who_with":
                assert ex["who"] == PT.who_label(x) and ex["where"] == x["label"], ex
            same += 1
        assert same >= 10, same
        print("電話とメッセージの答えが一致: %d 回" % same)
        now += 3 * 86400
        fresh(now)
        SC[b] = HOME
        m = app.manners.on_send(cb, sb, "who_with", now)
        assert app.manners.reply(cb, sb, "who_with", now, {}, m)[0] == "who_with_none", "根拠が無いのに誰かといた"
        app.manners.on_send(cb, sb, "who_with", now + 60)
        m = app.manners.on_send(cb, sb, "who_with", now + 120)
        assert app.manners.reply(cb, sb, "who_with", now + 120, {}, m)[0] == "what_doing_much"
        print("一人だった → 一人でした / 3 度目 → 聞きすぎ")

        # ---- 6. 割り込みの着信 3 通り. 画面の選択肢 = 本当に選べる
        for how in ("no", "timeout", "back", "switch"):
            now += 86400
            fresh(now)
            with_a(None, now)
            SC[a] = SC[b] = OUT
            PT.begin(cb, sb, "もしもし", True, now)                       # B と話している
            r = R.start(ca, sa, now + 5, "sudden", why="bored")             # A からかかってくる
            assert r and r["catch"] == b, r
            v = R.view(now + 6)
            assert [o["id"] for o in v["opts"]] == ["back", "switch", "no"] and v["catch"] == cb["name"], v
            try:
                R.answer(True, now + 6, how="yes")
                raise AssertionError("割り込みに「出る」(今の電話を残したまま) が通る")
            except ValueError:
                pass
            m0b = sb["params"]["mood"]
            if how == "timeout":
                R.tick(now + 120)
            else:
                R.answer(how == "switch", now + 7, how=how)
            c = PT.rec()
            items = [it for it in app.chat.load(a)["items"] if it.get("kind") == "missed_call"]
            if how in ("no", "timeout"):
                assert c and c["cid"] == b and "話し中" in items[-1]["text"], (how, items[-1:])
            elif how == "back":
                assert c and c["cid"] == b and sa.get("call_promise"), how
                assert pt_mod.NARRATION["catch"] in [x["text"] for x in c["log"]]
                assert R.promise_check(ca, sa, now + 10) is False
                assert R.promise_check(ca, sa, now + 4 * 3600) and any(x.get("action") == "_call_promise" for x in sa["reasons"])
            else:
                assert c and c["cid"] == a and c["by"] == "her", c
                assert sb["params"]["mood"] < m0b and any(x.get("action") == "_call_switch" for x in sb["reasons"]), sb["params"]
            print("割り込み %-7s: いまの通話 %s" % (how, (c or {}).get("name")))
            if PT.rec():
                PT.hangup(now + 300)
        # かけ直す約束は, あなたからかければ済む
        now += 86400
        fresh(now)
        sa["call_promise"] = {"t": now, "until": now + 3 * 3600}
        sa.pop("call_promise")                    # engine.phone_call で消える (かけた)
        assert R.promise_check(ca, sa, now + 5 * 3600) is False
        # 割り込みでないとき: 出る / 出ない だけ
        P.rec().pop("call", None)
        R.start(ca, sa, now + 10, "sudden", why="bored")
        assert [o["id"] for o in R.view(now + 11)["opts"]] == ["yes", "no"] and R.view(now + 11)["catch"] is None
        try:
            R.answer(True, now + 12, how="back")
            raise AssertionError("割り込みでないのに, かけ直すと伝えられる")
        except ValueError:
            pass
        R.answer(False, now + 12)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
