"""キャラメイキング (core/charmake.py): 質問は決める値ごとに 1 つ (聞き方はくじ・順番も混ぜる). 答えでスキル (鈍りの目安も)・貯金・
運動・免許が決まる. 答えなかった項目はそのまま. 知らない質問・番号は弾く (一時データ).

    python tools/test_charmake.py
"""
import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import charmake as CM, engine, store  # noqa: E402


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("キャラメイク")
        M = app.charmake
        qs = M.questions(random.Random(1))
        assert sorted(q["target"] for q in qs) == sorted(CM.TARGETS), "決める値ごとに 1 つずつ"
        for qid, t, _, opts in CM.QUESTIONS:
            assert len(opts) == len(CM.TARGETS[t][1]), qid
        seen = {q["id"] for s in range(30) for q in M.questions(random.Random(s))}
        assert len(seen) == len(CM.QUESTIONS), "どの聞き方も出うる"
        print("質問 %d 問 (リスト %d)" % (len(qs), len(CM.QUESTIONS)))

        ps = app.life.player_state()
        house0 = ps["skills"]["house"]
        r = M.apply({"talk1": 3, "money2": 4, "ex2": 0, "drive1": 1, "cook1": 4})
        assert ps["skills"]["talk"] == 50 and ps["skill_peak"]["talk"] == 50 and ps["skills"]["cook"] == 65
        assert ps["money"] == 1000000 and app.body.rec()["exercise"] == 20 and app.quals.has("drive")
        assert ps["skills"]["house"] == house0, "答えなかった項目はそのまま"
        print("反映:", ", ".join("%s %s→%s" % (c["label"], c["old"], c["new"]) for c in r["changes"]))
        M.apply({"drive1": 0})
        assert not app.quals.has("drive")
        for bad in ({"nope": 1}, {"talk1": 9}):
            try:
                M.apply(bad)
                raise AssertionError("通ってはいけない")
            except ValueError:
                pass
        app2 = engine.App()
        assert app2.life.player_state()["money"] == 1000000 and app2.life.player_state()["skills"]["talk"] == 50
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
