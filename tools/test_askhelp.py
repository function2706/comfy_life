"""あなたから手伝いを頼む (core/askhelp.py): 約束の欄の「あなたの家」に出る・頼む・返事 (受ける / 予定があれば別の日時か断り)・
当日来てくれる・始める・最中の様子・時間が来て終わる・出方 (お金を求める → 払う / 断る, 今度おごって → 貸し, 何も求めない)・
お礼を渡す・貸しの催促とうやむや・おごって返す・途中で帰る・閉じていた間 (一時データ, 画像生成なし).

    python tools/test_askhelp.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(6)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("手伝いを頼む")
        A, B, H, C = app.appoint, app.bonds, app.askhelp, app.chat
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        B.set_stage(cid, "contact")
        st["params"].update(affection=60, trust=55, mood=60)
        now = time.time()
        ps = app.life.player_state()
        ps["money"] = 100000

        # ---- 1. 約束の欄の「あなたの家」に出る
        home = next(c for c in A.choices(cid) if c["place"] == "home:me")
        assert any(d["id"] == "_help:clean" for d in home["dos"]), home
        print("約束の欄:", [d["name"] for d in home["dos"]])

        # ---- 2. 頼む → 返事 (受ける / 断る / その時間は予定がある)
        def ask(kind="clean", accept=None, t=None):
            A.all()[:] = []
            x = A.propose(cid, t or now + 86400, "home:me", "_help:" + kind, now)
            x = A.get(x["id"])
            if accept is not None:
                H.accept_chance = lambda c, s: 1.0 if accept else 0.0
            key, eff, extra = A.reply(char, st, {"appoint": x["id"]}, now, {})
            H.__dict__.pop("accept_chance", None)
            return x, key
        x, key = ask(accept=True)
        assert key == "help_yes" and x["status"] == "set", (key, x["status"])
        print("頼んで受けた:", C.line(char, "chat.help_yes"[5:], {"when": "明日 13:00", "what": x["label"]}))
        x, key = ask(accept=False)
        assert key == "help_no" and x["status"] == "declined"
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, dt: dict(sched(c, dt), away=True)
        x, key = ask()
        app.scheduled_scene = sched
        assert key in ("help_counter", "help_busy"), key
        print("予定がある:", key, x["status"])

        # ---- 3. 当日: 来てくれる → 始める → 最中 → 終わる (何も求めない)
        def visit(outcome=(0.0, 0.0)):
            if B.with_rec():
                B.end(go_home=False)
            x, _ = ask(accept=True)
            x["t"] = now
            H.outcome_chances = lambda c, s: outcome
            e = A._meet(x, now)["entry"]
            return x, e
        x, e = visit()
        assert B.mode(cid) == "guest" and H.view(cid, now)["ready"], H.view(cid, now)
        print("来てくれた:", e["text"])
        H.start(cid, now)
        sc = app.scene_at(char, st, datetime.fromtimestamp(now + 60))
        assert "手伝ってくれている" in sc["label"] and sc["location"] == "あなたの家", sc
        av = app.available(char, st, datetime.fromtimestamp(now + 60))
        assert av["talk"]["ok"] and not av["game"]["ok"], "最中は話すくらい"
        lv0 = app.home.score() if hasattr(app.home, "score") else None
        r = H.live(cid, now + 3 * 3600 + 1)
        assert r["outcome"] == "none" and B.mode(cid) == "guest", r
        print("終わった (何も求めない):", r["entry"]["text"].replace("\n", " / "))
        assert H.view(cid, now)["can_offer"]

        # ---- 4. お礼を渡す (受け取る / 水くさい)
        H.offer_chance = lambda c, s: 1.0
        m0 = ps["money"]
        r = H.offer(cid, now)
        assert r["taken"] and ps["money"] == m0 - r["amount"]
        print("お礼を渡した (受け取る):", r["entry"]["text"])
        x, e = visit()
        H.start(cid, now)
        H.live(cid, now + 3 * 3600 + 1)
        H.offer_chance = lambda c, s: 0.0
        r = H.offer(cid, now)
        assert not r["taken"] and ps["money"] == m0 - 3000
        print("お礼を渡した (受け取らない):", r["entry"]["text"])
        del H.offer_chance

        # ---- 5. お金を求められる → 払う / 断る
        x, e = visit((1.0, 0.0))
        H.start(cid, now)
        r = H.live(cid, now + 3 * 3600 + 1)
        amt = H.view(cid, now)["ask_money"]
        assert r["outcome"] == "money" and amt, r
        print("お金を求められた:", r["entry"]["text"].split("\n")[-1])
        m0 = ps["money"]
        H.pay(cid, True, now)
        assert ps["money"] == m0 - amt and not H.view(cid, now)["can_offer"]
        x, e = visit((1.0, 0.0))
        H.start(cid, now)
        H.live(cid, now + 3 * 3600 + 1)
        tr0 = st["params"]["trust"]
        r = H.pay(cid, False, now)
        assert st["params"]["trust"] < tr0 and any(rr["tell"] == "手伝ったのに、お礼を断られた" for rr in app.life.reasons(st, now))
        print("断った:", r["entry"]["text"])

        # ---- 6. 今度おごって → 貸し → 5 日で催促 → おごって返す / 14 日でうやむや
        x, e = visit((0.0, 1.0))
        H.start(cid, now)
        r = H.live(cid, now + 3 * 3600 + 1)
        assert r["outcome"] == "treat" and st.get("iou"), r
        print("今度おごって:", r["entry"]["text"].split("\n")[-1])
        B.end(go_home=False)
        t0 = st["iou"]["t"]
        assert H.tick(char, st, t0 + 5.1 * 86400) and st["iou"]["reminded"]
        print("催促:", C.load(cid)["items"][-1]["text"])
        said = H.iou_paid(char, st, t0 + 6 * 86400)
        assert said and not st.get("iou")
        print("おごって返した:", said)
        st["iou"] = {"t": t0, "what": "大掃除", "reminded": True}
        tr0 = st["params"]["trust"]
        assert H.tick(char, st, t0 + 14.1 * 86400) and not st.get("iou") and st["params"]["trust"] < tr0
        print("うやむや: 信頼 %.1f → %.1f" % (tr0, st["params"]["trust"]))

        # ---- 7. 最中に帰ってもらう: そこで切り上げ (見返りの話にならない)
        x, e = visit((1.0, 0.0))
        H.start(cid, now)
        B.end(go_home=False)
        assert not H.rec() and "help_you" != (st.get("override") or {}).get("activity")

        # ---- 8. 閉じていた間 / 約束の一覧の表示
        if B.with_rec():
            B.end(go_home=False)
        x, _ = ask(accept=True)
        H.outcome_chances = lambda c, s: (0.0, 1.0)
        st.pop("iou", None)
        txt = A._meet(x, now, extra_opts={"auto_weak": True})["entry"]["text"]
        assert "手伝ってもらった" in txt and st.get("iou"), txt
        assert A.row(x, now)["do_label"] == "大掃除を手伝ってもらう"
        print("閉じていた間:", txt)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
