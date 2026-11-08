"""向こうからの「話そう」の理由と, 返事の合い方 (1.6.0. core/msgreply.py).
以前は誘いの文に理由が無く, どの返事が効くかは画面に出ない性格の好みと揺らぎで決まって, 当てもののようになっていた.
- 理由 (退屈・疲れている・いいことがあった・寂しい) は相手のいまの状態から決まり, 誘いの文に出る. 選択肢も理由に合わせる
- 合い方は主に理由で決まる: 理由に合う返事は, どの性格でもだいたい効く. 外した返事 (疲れているのにからかう・寂しいのに素っ気ない
  など) は, だいたい悪く取られる. 性格の好みは少し傾ける程度 (なくしはしない)
- よくなかったときは, 相手が理由をにじませる
(一時データ)

    python tools/test_msg_why.py
"""
import glob
import os
import random
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, msgreply as MR, store  # noqa: E402
from testclock import fix_noon, landed  # noqa: E402

fix_noon(engine)
PERSONAS = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(os.path.dirname(HERE), "defaults", "personas", "*.json")))
BEST = {"bored": "cheerful", "tired": "worry", "happy": "expand", "lonely": "cheerful"}
WORST = {"bored": "curt", "tired": "tease", "happy": "tease", "lonely": "curt"}


def main():
    random.seed(8)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("話そうの理由")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        calm = {"boredom": 30, "energy": 70, "stress": 20, "mood": 55, "loneliness": 30, "affection": 60}

        # ---- 1. 理由は状態から
        for why, params in (("bored", {"boredom": 85}), ("tired", {"energy": 15}), ("happy", {"mood": 92}), ("lonely", {"loneliness": 85})):
            st["params"].update(dict(calm, **params))
            got = [MR.pick_why(char, st) for _ in range(50)]
            assert got.count(why) > 40, (why, got)
        print("理由は状態から: OK")

        # ---- 2. 誘いの文と選択肢が理由に合う
        st["params"].update(dict(calm, energy=15))
        st["approach"], st["ap_quiet_until"], st["ap_last"], st["msg_pending"] = None, 0, {}, None
        e = app.force_approach("msg_chat", cid)["entry"]
        why = st["approach"].get("why")
        assert why == "tired" and "疲れ" in e["text"], (why, e["text"])
        choices = MR.options("msg_chat", why)
        assert [c["id"] for c in choices][0] == "worry" and "お疲れ" in choices[0]["label"], choices
        print("誘いの文: OK |", e["text"], "/", " ".join(c["label"] for c in choices))

        # ---- 3. 合う返事はどの性格でもだいたい効く. 外した返事はだいたい悪い
        def rates(why, kind, n=40):
            g = b = 0
            for pid in PERSONAS:
                char["persona_id"] = pid
                for _ in range(n):
                    st["params"].update({"mood": 60, "affection": 60, "loneliness": 50})
                    r = MR.judge(char, st, "msg_chat", kind, why=why)
                    g += r == "good"
                    b += r == "bad"
            t = float(n * len(PERSONAS))
            return g / t, b / t
        rows = []
        for why in MR.WHY_FIT:
            gb, _ = rates(why, BEST[why])
            _, bw = rates(why, WORST[why])
            rows.append("%s: 合う %.2f 効く / 外す %.2f 悪い" % (MR.WHY_LABEL[why], gb, bw))
            assert gb > 0.7 and bw > 0.6, (why, gb, bw)
        print("合い方は理由で: OK |", " ・ ".join(rows))

        # ---- 4. 性格の好みは少し残る (無口は素っ気ない返事を気にしない. 甘えたがりには刺さる)
        def ok_rate(pid, kind, why, n=400):
            char["persona_id"] = pid
            c = 0
            for _ in range(n):
                st["params"].update({"mood": 60, "affection": 60, "loneliness": 50})
                c += MR.judge(char, st, "msg_chat", kind, why=why) != "bad"
            return c / float(n)
        muk, ama = ok_rate("mukuchi", "curt", "bored"), ok_rate("amaenbo", "curt", "bored")
        assert muk > ama + 0.15, (muk, ama)
        print("性格の好み: OK | 退屈なときの素っ気ない返事が悪くない割合 無口 %.2f / 甘えたがり %.2f" % (muk, ama))

        # ---- 5. よくなかったときは理由をにじませる
        char["persona_id"] = "teinei"
        got = None
        for _ in range(40):
            st["params"].update(dict(calm, energy=15, mood=40, affection=40))
            st["approach"], st["ap_quiet_until"], st["ap_last"], st["msg_pending"] = None, 0, {}, None
            app.force_approach("msg_chat", cid)
            if st["approach"].get("why") != "tired":
                continue
            r = landed(app, app.answer_approach("reply", cid, "tease"), cid)
            if r["entry"]["reply"]["result"] == "bad":
                got = r["entry"]["text"]
                break
        assert got and "疲れ" in got, got
        print("よくなかったとき: OK |", got)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK")


if __name__ == "__main__":
    main()
