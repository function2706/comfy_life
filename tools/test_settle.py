"""連絡しすぎの精算 (core/manners.py の settle_contacts) と, 詳しい状態 (チート, engine.cheat_view) の確認 (一時データ, 画像生成なし).
- 4 日より古い「連絡多くない？」でも, 今の決まりで多くなかったなら好感度を戻す
- 今も多かった「連絡多くない？」は, そのときの好感度 (下がった分を足し戻した見積もり) が 35 以上なら好感度だけ戻す
- 好感度が下がった「また電話？」は戻す. これまでの当て直しで戻した分は引く. 機嫌は戻さない. 二度は当てない
- 精算のあとは retro_contacts が以前の判定を当て直さない

    python tools/test_settle.py
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

fix_noon(engine)


def main():
    random.seed(3)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("精算")
        M, C = app.manners, app.chat
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        app.bonds.set_stage(cid, "contact")
        now = time.time()
        st.pop("contacts_settled", None)
        st["contacts_v3"] = now - 3600
        st["params"].update(affection=33.5, trust=50, mood=60)
        log = app.log(cid)

        def complaint(t, kind="too_often", d=None):
            C.add(cid, "her", "📱『……ちょっと、連絡多くないですか？』", kind=kind, t=t)
            log.append({"t": t, "action": "_chat", "text": "", "deltas": d or {"mood": -2, "affection": -1}})

        # B: 8 日前. 2 時間で 25 通 (今の決まりでも多い). そのときは好かれていた (35 以上) → 好感度は戻る
        tb = now - 8 * 86400
        for i in range(25):
            C.add(cid, "me", "ねえ", kind="smalltalk", t=tb - 7200 + i * 280)
        complaint(tb)
        # A: 6 日前. 2 通だけ (今の決まりなら多くない) → 戻る. 「謝ったばかりなのに」は信頼も
        ta = now - 6 * 86400
        C.add(cid, "me", "おはよう", kind="smalltalk", t=ta - 600)
        C.add(cid, "me", "元気？", kind="smalltalk", t=ta - 300)
        complaint(ta, "too_often_again", {"mood": -5, "trust": -2, "affection": -1})
        # 電話: 5 日前の「また電話？」で好感度が下がっていた → 戻る
        log.append({"t": now - 5 * 86400, "action": "call", "text": "……また電話ですか？", "deltas": {"mood": -2, "affection": -1}})
        # これまでの当て直しで好感度 +1 戻してあった → その分は引く
        C.add(cid, "sys", "（以前の「連絡が多い」を、今の数え方で受け止め直した：好感度 +1）", kind="rejudge", t=now - 3000)
        mood0 = st["params"]["mood"]
        r = M.settle_contacts()
        p = st["params"]
        print("精算:", r, {k: p[k] for k in ("affection", "trust", "mood")}, C.load(cid)["items"][-1]["text"])
        assert r == [(cid, "settled")]
        assert abs(p["affection"] - 35.5) < 0.05 and abs(p["trust"] - 52) < 0.05 and p["mood"] == mood0, p
        assert "精算" in C.load(cid)["items"][-1]["text"]
        # 二度は当てない. 精算のあとは retro_contacts も以前の判定を当て直さない
        assert M.settle_contacts() == [] and M.retro_contacts() == [] and abs(p["affection"] - 35.5) < 0.05

        # そのときも好かれていなかった (足し戻しても 35 未満): 多かった「連絡多くない？」の好感度は戻さない
        st.pop("contacts_settled")
        d = C.load(cid)
        d["items"] = [x for x in d["items"] if x["t"] < tb + 1]       # B だけ残す
        C.save(cid, d)
        log[:] = [e for e in log if e["t"] == tb]
        st["params"].update(affection=20)
        assert M.settle_contacts() == [] and st["params"]["affection"] == 20

        # ---- 詳しい状態 (チート): 離れていても見える. 判定に使う値がそろっている
        v = app.cheat_view(cid)
        assert any(x["id"] == "affection" and x["v"] == 20 for x in v["params"])
        assert any(x["id"] == "mood" and x["target"] is not None for x in v["params"]), "機嫌の向かう先"
        assert "誘いは断られる" in v["bond"]["会ってもらえるか"], v["bond"]
        assert {"24時間の連絡（重み）", "「多い」と言われる線", "電話に出る見込み"} <= set(v["contact"]), v["contact"]
        assert v["attach"] and "traits" in v
        print("詳しい状態:", v["bond"]["会ってもらえるか"], v["contact"])
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
