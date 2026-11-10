"""電話 (A4): 話すことを選んでかける. 受け答えはメッセージと同じ判定 (理由・中身を選んだ謝罪・お礼・相談・話題).
通話の長さと相手の様子をトークに残す. 楽しかったときは, あとで相手からひとこと (一時データ).

    python tools/test_phone_talk.py
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
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)      # 流す時刻に左右されないように (平日の昼に流すと, ひなは大学の講義中で電話に出られなかった)


def main():
    random.seed(21)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("電話")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        app.bonds.end() if app.bonds.together(cid) else None
        char, st = app.char(cid), app.state(cid)
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=True, busy=False, asleep=False)    # 離れていて, 手が空いている
        app._call_missed = lambda *a, **k: None                                                      # 必ず出る
        C, M = app.chat, app.manners

        def fresh():
            st["contacts"], st["cooldowns"] = [], {}
            st.pop("msg_pending", None)
            st.pop("nori", None)
            app.set_params({"mood": 70, "affection": 60, "trust": 60, "boredom": 60, "loneliness": 60, "sleepiness": 10, "energy": 80}, cid)

        # ---- 1. お礼を選んでかける: 受け答えはお礼の判定 (自撮りを送ってくれた → 効く)
        fresh()
        M.favor(st, "selfie", time.time() - 600)
        r = app.phone_call(cid, "thanks", {"reason": "selfie"})
        assert r.get("call"), r
        items = C.load(cid)["items"]
        sysl = [it for it in items if it.get("who") == "sys" and it["text"].startswith("📞 電話で話した（")]
        assert sysl and "分ほど" in sysl[-1]["text"], [it["text"] for it in items[-5:]]
        mine = [it for it in items if it.get("who") == "me"]
        assert mine[-1]["text"] == "（電話で: お礼を言った: 自撮りを送ってくれた）", mine[-1]
        assert r["call"]["key"] == "thanks" and r["call"]["text"].startswith("📞"), r["call"]
        print("お礼:", sysl[-1]["text"], "|", r["call"]["text"])

        # ---- 2. 謝る (理由を選ぶ) / 相談 / 話題
        fresh()
        app.life.add_reason(st, "player", "bad", "連絡が多くて疲れた", time.time() - 600, told=True, delta=-3.0, action="_too_often")
        r = app.phone_call(cid, "apology", {"reason": "late_night"})
        assert r["call"]["key"] == "apology_near", r["call"]
        fresh()
        r = app.phone_call(cid, "consult", {"consult": "health"})
        assert r["call"]["key"].startswith("consult"), r["call"]
        fresh()
        app.topics.add("book", "恋愛小説を読んだ話", ["books", "romance"], time.time())
        x = app.topics.all()[-1]
        r = app.phone_call(cid, "topic", {"topic": x["id"]})
        assert r["call"]["key"].startswith("topic_") and C.load(cid)["items"][-4]["text"] in ("（電話で: 恋愛小説を読んだ話をした）",) or \
            any(it["text"] == "（電話で: 恋愛小説を読んだ話をした）" for it in C.load(cid)["items"]), r["call"]
        print("謝る・相談・話題: OK")

        # ---- 3. 長さはノリしだい: ノリが高いほど長い
        fresh()
        lo, hi = [], []
        for i in range(12):
            fresh()
            st["nori"] = {"v": 15.0, "t": time.time(), "turns": 0}
            lo.append(app.phone_call(cid, "smalltalk")["call"]["mins"])
            fresh()
            st["nori"] = {"v": 90.0, "t": time.time(), "turns": 0}
            hi.append(app.phone_call(cid, "smalltalk")["call"]["mins"])
        assert sum(hi) > sum(lo) * 1.5, (lo, hi)
        print("通話の長さ: ノリ低 %s / 高 %s" % (sorted(lo), sorted(hi)))

        # ---- 4. 楽しかった: あとで相手からひとこと (時間差の仕組みで届く)
        fresh()
        st["msg_pending"] = {"aid": "message", "t": time.time(), "due": time.time() - 1, "reply": True, "count": 1,
                             "kind": "after_call", "meta": {}, "quick": False}
        out = app.deliver_due()
        assert out and "楽しかった" in out[0]["text"], out
        print("電話のあと:", out[0]["text"])

        # ---- 5. 違う話・違う理由は弾く
        for talk, ex in (("tease", {}), ("apology", {"reason": "nope"}), ("consult", {"consult": "nope"})):
            try:
                app.phone_call(cid, talk, ex)
                raise AssertionError("通ってしまった: %s" % talk)
            except (ValueError, KeyError):
                pass
        app.scheduled_scene = sched
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
