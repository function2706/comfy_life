"""対面の会話 (A5): 謝る・お礼を言う・相談するで, 何についてかを選ぶ. 判定はメッセージと同じ (core/msgpick.py) (一時データ).

    python tools/test_face_talk.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, memquiz, store  # noqa: E402


def main():
    random.seed(31)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("対面")
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        app.bonds.set_stage(cid, "live")                  # 同居: 家でそばにいる
        assert app.bonds.together(cid), "そばにいる前提"
        ids = [a["id"] for a in app.actions]
        assert "thank" in ids and "consult_me" in ids and app.action("apologize").get("pick") == "apology"
        assert set(app.state_view()["picks"]) == {"apology", "thanks", "consult"}
        L, M = app.life, app.manners

        def fresh():
            st["reasons"], st["apologies"], st["favors"], st["cooldowns"] = [], [], [], {}
            st.pop("quiz", None), st.pop("apology_tries", None)
            st.pop("apology_last", None)
            app.set_params({"mood": 55, "affection": 55, "trust": 55}, cid)

        def text(r):
            return (r.get("entry") or {}).get("text", "")

        def pick(kind, typ, of=None):
            memquiz.ask(app, cid, kind, time.time())
            its = st["quiz"][kind]["items"]
            return next(k for k, e in its.items() if e["type"] == typ and (of is None or e.get("of") == of))

        # ---- 1. 謝る (記憶の問いから選ぶ. A20): 細部違い / 気にしていない / 人違いなし / 的中
        fresh()
        app.chat.add(cid, "me", "（おやすみと送った）", kind="greet_night", t=time.time() - 2 * 3600)
        app.chat.add(cid, "me", "（からかった）", kind="tease", t=time.time() - 2 * 3600 + 600)
        L.add_reason(st, "player", "bad", "夜中に連絡が来た", time.time() - 2 * 3600, told=True, delta=-4.0, action="_chat_late_night")
        t = text(app.act("apologize", cid, opts={"pick": pick("apology", "shift", "fault")}))
        assert "それだけじゃない" in t, t
        st["cooldowns"] = {}
        t = text(app.act("apologize", cid, opts={"pick": pick("apology", "real")}))
        assert "気にしてない" in t, t
        st["cooldowns"] = {}
        app.act("apologize", cid, opts={"pick": pick("apology", "fault")})
        r0 = next(r for r in st["reasons"] if r.get("action") == "_chat_late_night")
        assert r0.get("resolved") or r0.get("half") or r0.get("deeds") or st.get("apology_last"), r0
        try:
            app.act("apologize", cid, opts={"pick": "nope"})
            raise AssertionError("違う理由で謝れた")
        except ValueError:
            pass
        print("謝る: OK")

        # ---- 2. お礼を言う
        fresh()
        M.favor(st, "treat", time.time() - 600)
        t = text(app.act("thank", cid, opts={"pick": pick("thanks", "favor")}))
        assert "うれしい" in t, t
        st["cooldowns"] = {}
        t = text(app.act("thank", cid, opts={"pick": pick("thanks", "shift")}))
        assert "心当たり" in t, t
        try:
            app.act("thank", cid)
            raise AssertionError("何のお礼か選ばずに言えた")
        except ValueError:
            pass
        print("お礼: OK")

        # ---- 3. 相談する ({topic} に中身)
        fresh()
        ts = []
        for i in range(8):                  # 返し方は揺らぐ ({topic} の無い返しもある)
            st["cooldowns"] = {}
            ts.append(text(app.act("consult_me", cid, opts={"pick": "money"})))
        t = next((x for x in ts if "お金" in x or "仲いい" in x), None)
        assert t, ts
        print("相談:", t)
        app.scheduled_scene = sched
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
