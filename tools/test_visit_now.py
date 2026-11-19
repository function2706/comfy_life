"""スマホで「今から家に行っていい？」(残件 A25. 一時データ, 画像生成なし).
- 聞けるのは家に行ける仲の, 離れている相手だけ (連絡先・同居・そばにいる・返事待ち・近くに約束があると, 理由つきで押せない)
- 返事はいつものメッセージの時間差. 受けるかは, 読んだときの相手の都合・時間帯・機嫌・仲で決まる (必ず通る道はない.
  続けて聞くほど通りにくい). 断る理由は, 出先・手が離せない・もう遅い・体調・読むのが遅れた・(気が乗らない)
- いいと言われたら, 相手の家へ出かけて着けば, すぐ迎えてくれる (訪問). 待っていると言った相手は, 着くまで家にいる
- いいと言われたのに行かなければ, 約束のすっぽかしより軽く受け取られる
- トークの「今から家に行っていい？」の押せる / 押せないは, 本当に聞ける / 聞けないと同じ

    python tools/test_visit_now.py
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
from core import engine, store  # noqa: E402
from core.appoint import GRACE, NOW_MISSED, NOW_STALE  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(11)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("今から")
        A, B, C = app.appoint, app.bonds, app.chat
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}
        sched = app.scheduled_scene

        def plan(**kw):
            app.scheduled_scene = lambda c, d: dict(sched(c, d), **dict({"away": False, "busy": False, "asleep": False}, **kw))
            st["override"] = None if kw else {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}
        plan()

        def can():
            """トークのボタン (押せるか) と, 本当に聞けるか."""
            v = C.thread(cid).get("visit_now")
            shown = v is not None
            ok = shown and not v["why"]
            try:
                x = A.ask_now(cid)
                real = True
                x = A.get(x["id"])
                x["status"] = "declined"
                st.pop("msg_pending", None)
            except ValueError:
                real = False
            assert ok == real, (v, real)
            return shown, ok, (v or {}).get("why")

        # ---- 1. 聞ける相手・聞けない相手 (画面で押せる = 本当に聞ける)
        B.set_stage(cid, "contact")
        assert can() == (False, False, None), "家に行ける仲の前は出さない"
        B.set_stage(cid, "live")
        assert can()[:2] == (False, False)
        B.set_stage(cid, "visit")
        assert can() == (True, True, None)
        B.start(cid, "meet")
        assert can()[2] == "いまそばにいます"
        B.end(go_home=False)
        x0 = A.propose(cid, time.time() + 3600, "riverside", "walk")
        assert can()[2].startswith("近くに約束"), can()
        A.get(x0["id"])["status"] = "declined"
        st.pop("msg_pending", None)
        assert can()[1]
        print("聞ける相手: OK")

        # ---- 2. 聞く → 時間差の返事 → いいよ
        def ask(**params):
            st.pop("msg_pending", None)
            st["contacts"] = []
            app.set_params(dict({"affection": 80, "mood": 70, "trust": 70, "health": 90}, **params), cid)
            x = A.ask_now(cid)
            assert x["status"] == "asked" and x["ask_now"] and st["msg_pending"]["kind"] == "appoint"
            assert C.thread(cid)["items"][-1]["who"] == "me" and "今から" in C.thread(cid)["items"][-1]["text"]
            try:
                A.ask_now(cid)
                raise AssertionError("返事待ちのうちに, もう一度聞ける")
            except ValueError as e:
                assert "返事を待って" in str(e)
            st["msg_pending"]["due"] = time.time() - 1
            out = app.deliver_due()
            return A.get(x["id"]), (out[0]["text"] if out else "")

        def drop(x):
            if x["status"] in ("asked", "set", "waiting"):
                x["status"] = "cancelled"
            st["now_refused"] = []

        yes = {"hi": 0, "lo": 0}
        for i in range(30):
            x, _ = ask()
            yes["hi"] += x["status"] == "set"
            drop(x)
            x, _ = ask(affection=40, mood=35, trust=40)
            yes["lo"] += x["status"] == "set"
            drop(x)
        assert yes["lo"] < yes["hi"] < 30 and yes["hi"] >= 15, yes
        print("返事: OK", yes)

        # ---- 3. 断る理由は, 相手の知りうるもの (読んだときの都合)
        def why(**kw):
            x = A.ask_now(cid)
            x = A.get(x["id"])
            st.pop("msg_pending", None)
            k, _, _ = A._now_reply(char, st, x, kw.pop("_at", time.time()), {"place": "", "when": ""})
            drop(x)
            return k
        app.set_params({"affection": 85, "mood": 75, "trust": 70, "health": 90}, cid)
        plan(away=True)
        assert why() == "visit_now_out"
        plan(asleep=True)
        assert why() == "visit_now_late"
        plan()
        ph = app.phase_at
        app.phase_at = lambda dt: {"id": "midnight", "label": "深夜", "pos": "", "neg": ""}
        assert why() == "visit_now_late", "深夜は聞けても断られる"
        app.phase_at = ph
        plan(busy=True)
        ks = [why() for _ in range(20)]
        assert ks.count("visit_now_busy") >= 8, ks
        plan()
        app.set_params({"health": 30}, cid)
        assert why() == "visit_now_unwell"
        app.set_params({"health": 90}, cid)
        x = A.ask_now(cid)
        x = A.get(x["id"])
        x["made"] -= NOW_STALE + 60
        st.pop("msg_pending", None)
        assert A._now_reply(char, st, x, time.time(), {"place": "", "when": ""})[0] == "visit_now_stale"
        assert x["status"] == "declined"
        drop(x)
        for k in ("visit_now_yes", "visit_now_no", "visit_now_out", "visit_now_busy", "visit_now_late", "visit_now_unwell",
                  "visit_now_stale", "visit_now_missed"):
            assert C.line(char, k, {"when": "12:30", "place": "家"}).startswith("📱『"), k
        print("断る理由: OK")

        # ---- 4. 続けて聞くほど通りにくい (回数で通る道はない)
        def rate(prior):
            n = 0
            for _ in range(200):
                x = A.ask_now(cid)
                x = A.get(x["id"])
                st.pop("msg_pending", None)
                st["now_refused"] = [time.time() - 600] * prior
                k, _, _ = A._now_reply(char, st, x, time.time(), {"place": "", "when": ""})
                n += k == "visit_now_yes"
                x["status"] = "cancelled"
            st["now_refused"] = []
            return n
        app.set_params({"affection": 70, "mood": 60, "trust": 60}, cid)
        r0, r2 = rate(0), rate(2)
        assert r2 < r0 * 0.75, (r0, r2)
        print("続けて聞く: OK", r0, r2)

        # ---- 5. いいよ → 待っている相手は家にいる → 出かけて着けば, すぐ訪問
        def get_yes():
            for _ in range(40):
                x, text = ask()
                if x["status"] == "set":
                    return x, text
                drop(x)
            raise AssertionError("いいと言ってもらえない")
        x, text = get_yes()
        th = C.thread(cid)
        assert any(it["who"] == "sys" and "🚪" in it["text"] for it in th["items"][-3:]), th["items"][-3:]
        row = next(r for r in th["appoints"] if r["id"] == x["id"])
        assert row["status"] == "set" and not row["can_change"] and row["can_cancel"], row
        assert th["visit_now"]["why"] == "もう行くことになっています"
        plan(away=True)
        sc = app.scene_at(char, st, datetime.now())
        assert not sc["away"], "待っていると言ったら, 着くまで家にいる: %s" % sc
        r = A.go(x["id"])
        A.live()
        assert B.mode(cid) == "visit", (B.with_rec(), A.get(x["id"])["status"], r)
        assert A.get(x["id"])["status"] == "met"
        last = app.log(cid)[-1]
        assert last["action"] == "visit_home", last
        print("向かって着く: OK |", text, "|", last["text"].split("\n")[0])
        B.end(go_home=False)
        app.presence.rec()["mode"] = "none"
        app.presence.save()
        plan()

        # ---- 6. いいと言われたのに行かない: 約束のすっぽかしより軽い
        x, _ = get_yes()
        app.set_params({"mood": 60, "trust": 60, "affection": 70}, cid)
        x["t"] = time.time() - GRACE - 0.5     # (上の確かめで, トークには直前の 1 分に 500 件を超えて並んでいる)
        p0 = dict(st["params"])
        A.live()
        assert A.get(x["id"])["status"] == "missed"
        dm, dtr = st["params"]["mood"] - p0["mood"], st["params"]["trust"] - p0["trust"]
        assert -9 < dm < 0 and -4 < dtr < 0, (dm, dtr, NOW_MISSED)
        assert any(it.get("kind") == "visit_now_missed" for it in C.load(cid)["items"]), "来なかったことを言ってくる"
        assert any("来ると言っていたのに" in (r.get("tell") or "") for r in st.get("reasons") or []), st.get("reasons")
        print("来なかった: OK | 機嫌 %.1f 信頼 %.1f" % (dm, dtr))

        # ---- 7. 返事待ちが流れた後に返事が届いても, 「今から」ではない
        x = A.ask_now(cid)
        x = A.get(x["id"])
        x["status"] = "lapsed"
        assert A.reply(char, st, st["msg_pending"], time.time(), {})[0] == "visit_now_stale"
        st.pop("msg_pending", None)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
