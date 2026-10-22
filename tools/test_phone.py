"""スマホでの連絡の確認: 外出中・仕事中・一人の時間でも, 相手が寝ていても送れる/かけられる. 電話は出ないことも・折り返しも.
連絡しすぎ・夜中の電話・仕事中の連絡の影響 (一時データ, 画像生成なし).

    python tools/test_phone.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)     # 時刻を昼に固定 (流す時刻に左右されないように)


def main():
    random.seed(31)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("スマホ")
        cid = app.settings["active_character"]
        B = app.bonds
        st = app.state(cid)
        app.set_params({"affection": 60, "trust": 60, "mood": 60}, cid)

        def scene(**kw):
            ov = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}
            ov.update(kw)
            st["override"] = ov

        def reset():
            st["cooldowns"], st["contacts"] = {}, []
            st.pop("msg_pending", None)

        # ---- 1. 相手が寝ていても, メッセージは送れるし電話もかけられる (出ないだけ)
        scene(activity="sleep", label="睡眠中", asleep=True)
        av = app.person_view()["available"]
        assert av["message"]["ok"] and av["call"]["ok"], av["call"]
        e = app.act("message")["entry"]
        assert e.get("sent") and st.get("msg_pending")
        reset()
        r = app.act("call")
        assert r.get("missed") and "出なかった" in r["entry"]["text"], r["entry"]["text"]
        # 手が離せないときの電話は, あとで折り返しがメッセージで来ることがある
        scene(activity="bath", label="入浴中", busy=True)
        for _ in range(30):
            reset()
            app.act("call")
            if st.get("msg_pending", {}).get("callback"):
                break
        assert st["msg_pending"]["callback"]
        scene()
        st["msg_pending"]["due"] = time.time() - 1
        out = app.deliver_due()
        e = app.log(cid)[-1]
        assert out and e["action_name"] == "折り返し" and "電話" in e["text"], e["text"]
        print("asleep / busy / callback: OK", e["text"])

        # ---- 2. 出たときは, 相手がいまどこで何をしているかが少しわかる
        for _ in range(20):
            reset()
            r = app.act("call")
            if not r.get("missed"):
                break
        assert not r.get("missed") and app.person_view()["peek"]
        st["peek_until"] = 0
        assert not app.person_view()["peek"]

        # ---- 3. 連絡しすぎは引かれる (許容は性格と間柄しだい). 夜中の電話は迷惑がられる
        char = app.char(cid)
        char["persona_id"] = "cool"
        reset()
        for _ in range(4):
            st["contacts"].append(time.time())
        assert B.ctx(cid, st)["too_often"], "クールは連絡が多いのが苦手"
        char["persona_id"] = "amaenbo"
        assert not B.ctx(cid, st)["too_often"], "甘えたがりは平気"
        char["persona_id"] = "cool"
        a0 = st["params"]["affection"]
        app.set_params({"mood": 70, "affection": 70}, cid)
        for _ in range(40):
            st["cooldowns"] = {}
            r = app.act("call")
            if not r.get("missed"):
                break
        assert "また電話" in r["entry"]["text"] or "また？" in r["entry"]["text"], r["entry"]["text"]
        reset()
        night = app.phase_at
        app.phase_at = lambda dt: {"id": "midnight", "label": "深夜", "pos": "", "neg": ""}
        for _ in range(40):
            st["cooldowns"], st["contacts"] = {}, []
            r = app.act("call")
            if not r.get("missed"):
                break
        assert "こんな時間" in r["entry"]["text"] or "何時" in r["entry"]["text"], r["entry"]["text"]
        app.phase_at = night
        print("too often / night: OK", a0)

        # ---- 4. 一人の時間 (研鑽など) は, スマホを使っても続く
        reset()
        app.solo.start("practice", "talk")
        app.act("message")
        assert app.presence.rec()["mode"] == "busy" and app.presence.rec().get("solo"), "スマホで連絡しても研鑽は続く"
        app.come_back()

        # ---- 5. 仕事中の連絡が多いと, 仕事に響く
        def work(n):
            app.life.player_state()["work_log"] = {}
            app.presence.declare("work", time.time() - 4 * 3600)
            for _ in range(n):
                reset()
                app.act("message")
            return app.come_back()
        calm = work(0)
        busy = work(6)
        p0 = calm["entry"].get("money", {}).get("p", 0)
        p1 = busy["entry"].get("money", {}).get("p", 0)
        assert p1 < p0 and "注意" in busy.get("work_note", ""), (p0, p1, busy.get("work_note"))
        print("work: OK", p0, "->", p1)

        # ---- 6. 連絡先を知らない相手には連絡できない. スマホの連絡先はそばにいない人だけ
        B.set_stage(cid, "known")
        assert not app.person_view()["available"]["message"]["ok"]
        assert app.state_view()["contacts"] == []
        B.set_stage(cid, "contact")
        assert [c["id"] for c in app.state_view()["contacts"]] == [cid]
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
