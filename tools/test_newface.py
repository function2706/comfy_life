"""初めて見る顔の選び方の確認 (一時データ, 画像生成なし).
- このワールドにまだ現れていない定義の人が n 人いれば, その一人一人と「新しく作る人」が 1/(n+1) ずつ
  (定義の人が残っていても, 新しい人に会うことがある). n = 0 なら必ず新しく作る
- 出先のばったり (street) と, 偶然の出会い (encounters.meet_stranger) の両方で同じ

    python tools/test_newface.py
"""
import os
import random
import shutil
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(21)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("新しい顔")
        E = app.encounters
        # まだ現れていない定義を 3 人にする
        extra = 3 - len(E.candidates())
        for i in range(max(0, extra)):
            g = E.generate()
            g["id"] = "cx%d" % i
            store.save_character(g)
        cands = E.candidates()
        n = len(cands)
        assert n >= 3, n
        cnt = Counter()
        N = 6000
        for i in range(N):
            c, src = E.pick_new_face(cands)
            cnt[src.get("id") or "new"] += 1
            assert "id" not in c
        print("n = %d: %s" % (n, {k: round(v / float(N), 3) for k, v in sorted(cnt.items())}))
        for k, v in cnt.items():
            assert abs(v / float(N) - 1.0 / (n + 1)) < 0.03, (k, v)
        assert len(cnt) == n + 1
        # n = 0 なら必ず新しく作る
        assert all(E.pick_new_face([])[1]["type"] == "new" for _ in range(50))

        # 出先のばったり: 新しい人の出どころが両方出る
        srcs = Counter()
        for i in range(300):
            ppl = {}
            pid = app.street._new_person(ppl, "park", "noon", False, 0)
            srcs[ppl[pid]["src"]["type"]] += 1
        print("出先の初めての顔:", dict(srcs))
        assert srcs["new"] and srcs["def"] and abs(srcs["new"] / 300.0 - 1.0 / (n + 1)) < 0.1
        # 偶然の出会い (meet_stranger) も
        srcs = Counter()
        ps = app.life.player_state()
        for i in range(300):
            ps["encounter"] = None
            E.meet_stranger("out", None, "街", 0)
            srcs[ps["encounter"]["src"]["type"]] += 1
        print("偶然の出会いの初めての顔:", dict(srcs))
        assert srcs["new"] and srcs["def"]
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp + "_backup", ignore_errors=True)


if __name__ == "__main__":
    main()
