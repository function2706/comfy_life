"""相手からかかってくる電話 (A23 段 2. core/ring.py): 流れ 3 つ (急に / 電話していい？ / またかけるね) × 出る / 出ない / 鳴っている間に閉じる,
頼みごと (急な誘い・看病・頼まれごと) × 受ける / 保留 / 断る / 出ない, 出る時間帯の癖での受け取り方, 閉じている間の着信 × あなたの過ごし方,
話し中・寝ている, 頻度の上限 (一時データ).

    python tools/test_ring.py
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
from core import engine, ring as ring_mod, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(29)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("着信")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        app.bonds.end() if app.bonds.together(cid) else None
        char, st = app.char(cid), app.state(cid)
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=True, busy=False, asleep=False)    # 離れていて, 手が空いている
        C, R, P = app.chat, app.ring, app.presence

        def fresh(now):
            for k in ("ring_log", "call_ask", "call_back", "msg_pending", "nori", "approach"):
                st.pop(k, None)
            P.rec().pop("call", None)
            P.rec().pop("ring", None)
            P.rec()["mode"] = "none"
            P.beat(now, 0)
            app.set_params({"mood": 70, "affection": 65, "trust": 60, "boredom": 60, "loneliness": 60, "sleepiness": 10, "energy": 80}, cid)

        def last(kind):
            return [it for it in C.load(cid)["items"] if it.get("kind") == kind]

        now = time.time()
        # ---- 1. 急に: 出る → by=her の通話 (最初のひとことは理由のセリフ)
        fresh(now)
        r = R.start(char, st, now, "sudden", why="lonely")
        assert r and R.view(now + 1)["cid"] == cid
        out = R.answer(True, now + 3)
        c = app.phonetalk.rec()
        assert out["call"] and c["by"] == "her" and c["via"] == "sudden" and c["beat"]["kind"] == "reply", c
        assert "話したくなって" in c["beat"]["text"] or c["beat"]["text"], c["beat"]
        assert not R.rec() and last("call")[-1]["text"].startswith("📞"), last("call")[-1]
        app.call_end(now + 600)
        print("急に → 出る:", c["beat"]["text"])

        # ---- 2. 急に: 出ない (鳴り終わる) / 「出ない」(拒否) / 鳴っている間に閉じた (あとで見たら鳴り終わっていた)
        for how, act in (("missed", "wait"), ("declined", "no"), ("missed", "close")):
            now += 3 * 3600
            fresh(now)
            m0 = st["params"]["mood"]
            R.start(char, st, now, "sudden", why="bored")
            if act == "no":
                R.answer(False, now + 5)
            elif act == "close":
                P.rec()["beat"] = now                       # 画面を閉じた (心拍が途絶えた) まま, 時間がたった
                R.view(now + 3600)
            else:
                R.view(now + 60)
            assert not R.rec(), how
            assert last("missed_call") and ring_mod.HOW_LABEL[how] in last("missed_call")[-1]["text"], last("missed_call")[-1]
            assert st["params"]["mood"] < m0, (how, m0, st["params"]["mood"])
            print("急に → %s (%s): 機嫌 %.1f → %.1f" % (how, act, m0, st["params"]["mood"]))

        # ---- 3. 電話していい？ → いいよ → 少しして鳴る / いまはちょっと / 返事しない
        now += 3 * 3600
        fresh(now)
        R.ask(char, st, "happy", now)
        assert last("call_ask") and C.thread(cid)["call_ask"], "電話していい？が出ていない"
        R.ask_answer(cid, True, now + 10)
        assert not C.thread(cid)["call_ask"]
        assert R.live(char, st, now + 11) is None or True
        r = R.live(char, st, now + 60)
        assert r and r["via"] == "asked", r
        R.answer(True, now + 62)
        assert app.phonetalk.rec()["via"] == "asked"
        app.call_end(now + 900)
        now += 3 * 3600
        fresh(now)
        R.ask(char, st, "bored", now)
        m0 = st["params"]["mood"]
        R.ask_answer(cid, False, now + 10)
        assert "call_ask" not in st and st["params"]["mood"] < m0 and last("call_ask_no"), "いまはちょっと"
        try:
            R.ask_answer(cid, True, now + 20)
            raise AssertionError("答えたあとにまた答えられた")
        except ValueError:
            pass
        now += 3 * 3600
        fresh(now)
        R.ask(char, st, "bored", now)
        R.live(char, st, now + ring_mod.ASK_WAIT + 5)
        assert "call_ask" not in st and not R.rec(), "返事しないまま鳴った"
        print("電話していい？: いいよ → 鳴る / いまはちょっと / 返事なし OK")

        # ---- 4. またかけるね → 30〜150 分あとに鳴る (相手の手が空いていれば). 出なければ消える
        now += 3 * 3600
        fresh(now)
        st["call_back"] = {"t": now, "why": "次の用事"}
        assert R.live(char, st, now + 60) is None and st["call_back"].get("due")
        P.beat(st["call_back"]["due"] + 1, 0)              # 画面を開いている (心拍)
        r = R.live(char, st, st["call_back"]["due"] + 1)
        assert r and r["via"] == "back", r
        R.answer(True, r["t"] + 2)
        assert "かけ直し" in "かけ直し" and app.phonetalk.rec()["via"] == "back" and "call_back" not in st
        app.call_end(r["t"] + 600)
        now += 3 * 3600
        fresh(now)
        st["call_back"] = {"t": now - ring_mod.BACK_KEEP - 10, "why": "x"}
        assert R.live(char, st, now) is None and "call_back" not in st, "古いまたかけるねでかけてきた"
        print("またかけるね: OK")

        # ---- 5. 頼みごと × 受ける / 保留 / 断る / 出ない (約束の記録はいまのもの)
        ring_mod.REQ_P.update(care=5.0, now=5.0, favor=5.0)
        for ans in ("yes", "later", "no", "missed"):
            now += 3 * 3600
            fresh(now)
            for x in app.appoint.all():
                if x.get("cid") == cid and x["status"] in ("offered", "set"):
                    x["status"] = "refused"
            n0 = len(last("appoint_invite"))
            x = app.appoint.care_call(char, st, now, ["okayu"])
            assert x.get("phone") and R.rec() and R.rec()["req"] == x["id"], x
            assert len(last("appoint_invite")) == n0, "電話なのにメッセージでも来た"
            if ans == "missed":
                R.view(now + 120)
                assert x["status"] == "offered" and len(last("appoint_invite")) == n0 + 1, "出なかったのに誘いがメッセージで来ない"
                print("頼みごと × 出ない: メッセージで届いた")
                continue
            R.answer(True, now + 3)
            v = app.phonetalk.view(now + 4)
            assert v["beat"]["kind"] == "req" and [b["id"] for b in v["returns"]] == ["yes", "later", "no"], v
            app.call_reply(ans, now + 6)
            want = {"yes": "set", "later": "offered", "no": "refused"}[ans]
            assert x["status"] == want, (ans, x["status"])
            assert (len(last("appoint_invite")) == n0 + 1) == (ans == "later"), ans
            assert app.phonetalk.rec() and app.phonetalk.rec().get("next"), "答えたあとも電話は続く"
            app.call_end(now + 900)
            print("頼みごと × %s: %s" % (ans, x["status"]))
        # 答えないまま切れた → メッセージで届く
        now += 3 * 3600
        fresh(now)
        for x in app.appoint.all():
            if x.get("cid") == cid and x["status"] in ("offered", "set"):
                x["status"] = "refused"
        n0 = len(last("appoint_invite"))
        x = app.appoint.care_call(char, st, now, [])
        R.answer(True, now + 3)
        app.call_end(now + 5)
        assert x["status"] == "offered" and len(last("appoint_invite")) == n0 + 1, "答えずに切ったのに誘いが残らない"
        ring_mod.REQ_P.update(care=0.55, now=0.35, favor=0.2)
        print("頼みごと × 答えずに切る: メッセージで届いた")

        # ---- 6. 出る時間帯の癖: 覚える前は重め, ふだん出ないなら軽く, ふだん出るのに出ないと重く. かけてくる時間も寄る
        st["regard"]["habit"]["call"] = {}
        assert R.app.regard.call_ease(char, st, now, now) == app.regard.call_ease(char, st, now, now) > 1.0
        for i in range(12):
            app.regard.note_call(char, st, now - i * 7 * 86400 / 12, False)
        lo = app.regard.call_ease(char, st, now, now)
        st["regard"]["habit"]["call"] = {}
        for i in range(12):
            app.regard.note_call(char, st, now - i * 7 * 86400 / 12, True)
        hi = app.regard.call_ease(char, st, now, now)
        assert lo < 1.0 < hi, (lo, hi)
        random.seed(5)
        n_hi = sum(1 for _ in range(400) if (fresh(now), R.want_call(char, st, "lonely", now))[1])
        st["regard"]["habit"]["call"] = {}
        for i in range(12):
            app.regard.note_call(char, st, now - i * 7 * 86400 / 12, False)
        random.seed(5)
        n_lo = sum(1 for _ in range(400) if (fresh(now), R.want_call(char, st, "lonely", now))[1])
        assert n_lo < n_hi, (n_lo, n_hi)
        print("出る時間帯の癖: 不在着信の重さ 出ない枠 %.2f / 出る枠 %.2f, 電話にする数 出ない枠 %d / 出る枠 %d" % (lo, hi, n_lo, n_hi))

        # ---- 7. 話し中 (ほかの人と通話中)・寝ると告げている → 鳴らずに不在着信 (軽め)
        now += 3 * 3600
        fresh(now)
        P.rec()["call"] = {"cid": "someone", "beat": None, "next": now + 999, "t": now}
        assert R.start(char, st, now, "sudden", why="bored") is None and "話し中" in last("missed_call")[-1]["text"]
        P.rec().pop("call", None)
        now += 3 * 3600
        fresh(now)
        P.declare("sleep", now)
        assert R.start(char, st, now, "sudden", why="bored") is None and "寝ていて" in last("missed_call")[-1]["text"]
        P.back(now + 10)
        print("話し中・寝ている: OK")

        # ---- 8. 頻度の上限: 着信どうしの間・1 日の上限 (かけ直しは別)
        now += 3 * 3600
        fresh(now)
        R.start(char, st, now, "sudden", why="bored")
        R.answer(False, now + 2)
        assert R.why_not(char, st, now + 600) and not R.why_not(char, st, now + 600, strict=False), "間をあけずにまたかけてくる"
        st["ring_log"] = [now - 3 * 3600, now - 6 * 3600]
        assert "今日はもう" in (R.why_not(char, st, now) or ""), R.why_not(char, st, now)
        print("頻度の上限: OK")

        # ---- 9. 閉じている間: 寝ていた・仕事中 → 不在着信 / それ以外 → 短く出たことに
        now += 3 * 3600
        for do, res in (("sleep", "missed"), ("work", "missed"), ("rest", "auto"), ("out", "auto")):
            fresh(now)
            st["call_back"] = {"t": now, "why": "x", "due": now + 60}
            tl = [{"t": now, "end": now + 6 * 3600, "do": do}]
            out = R.offline(now, now + 6 * 3600, tl)
            assert out and out[0]["res"] == res and out[0]["via"] == "back", (do, out)
            assert "call_back" not in st
            now += 7 * 3600
        print("閉じている間の着信: 寝ていた・仕事 → 不在着信 / 休む・外出 → 短く出た")

        # ---- 10. 心拍から: 電話していい？のいいよ → state_view で鳴る
        now = time.time()
        fresh(now)
        st["call_ask"] = {"t": now - 30, "until": now + 600, "why": "bored", "ok": True, "ring_at": now - 1}
        app.save_state(cid)
        v = app.state_view(beat=True)
        assert v.get("ring") and v["ring"]["cid"] == cid, v.get("ring")
        R.answer(False)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
