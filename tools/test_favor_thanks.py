"""手伝いのお礼がお金になるか (earn.favor_done): 近しい仲では基本はお金のやりとりなし. 律儀な性格 (traits.repay) は近くても
ときどきお金で返す (気持ち程度の額). 仲が浅いうちはお金で返しやすい (一時データ, 画像生成なし).

    python tools/test_favor_thanks.py
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
    random.seed(9)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("お礼")
        E, B, L = app.earn, app.bonds, app.life
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        now = time.time()

        def rate(persona, stage, aff, trust, n=300):
            char["persona_id"] = persona
            B.set_stage(cid, stage, now)
            got, amts = 0, []
            for i in range(n):
                st["params"].update(affection=aff, trust=trust)
                L.her_money(st)["a"] = 50000
                pay, _ = E.favor_done({"id": "f%d" % i, "cid": cid, "kind": "clean", "label": "大掃除の手伝い", "h": 3.0, "tire": 0},
                                      3.0, now)
                if pay:
                    got += 1
                    amts.append(pay)
            return got / float(n), (sum(amts) / len(amts) if amts else 0)

        far = {p: rate(p, "contact", 52, 50) for p in ("osananajimi", "teinei", "jimuteki")}
        near = {p: rate(p, "visit", 85, 80) for p in ("osananajimi", "teinei", "jimuteki")}
        live = {p: rate(p, "live", 90, 85) for p in ("osananajimi", "jimuteki")}
        show = lambda d: " ".join("%s %.0f%%(%d円)" % (k, v[0] * 100, v[1]) for k, v in d.items())      # noqa: E731
        print("仲が浅い:", show(far))
        print("近しい  :", show(near))
        print("同居    :", show(live))
        assert far["jimuteki"][0] > far["teinei"][0] > far["osananajimi"][0] > 0.1
        assert near["osananajimi"][0] < 0.03 and near["teinei"][0] < 0.08 and near["jimuteki"][0] > 0.1
        assert live["osananajimi"][0] == 0 and live["jimuteki"][0] > 0.08
        assert near["jimuteki"][1] < far["jimuteki"][1], "近しい仲なら気持ち程度の額"
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
