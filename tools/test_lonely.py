"""寂しさと好感度 (一時データ, 画像生成なし).
- 寂しさが 85 以上でも, 連絡先の相手の好感度は時間だけでは下がらない. 家に行ける仲・同居は弱く下がる (下限で止まる)
- 以前の決まり (間柄にかかわらず 1 時間に 0.3) が残っているワールドは, 起動したとき今の決まりに置き換わる
- お詫び (一度だけ): 記録に残る出来事から見積もった値を下回る分を戻す (連絡先は全部・同居は 2/3)

    python tools/test_lonely.py
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
    random.seed(4)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)

        def drain(stage):
            app.bonds.set_stage(cid, stage)
            st["params"].update(affection=50, loneliness=95)
            st["last_touch"] = time.time()           # ご無沙汰で冷めるのとは分ける
            t = datetime.now()
            for _ in range(24):
                st["params"]["loneliness"] = 95
                app._step(char, st, t, 1.0)
            return 50 - st["params"]["affection"]
        c, v = drain("contact"), drain("visit")
        print("寂しさ 95 で 24 時間: 連絡先 -%.1f / 家に行ける仲 -%.1f" % (c, v))
        assert c == 0 and 0 < v <= 3, (c, v)

        # 以前の決まりが残っているワールド: 起動で置き換わる (ほかの決まりは残す)
        ps = store.load(store.wpath("params.json"))
        a = next(p for p in ps if p["id"] == "affection")
        a["rate_rules"] = [{"when": "loneliness>=85", "rate": -0.3}, {"when": "boredom>=99", "rate": -0.01}]
        store.save(store.wpath("params.json"), ps)
        app = engine.App()
        a = next(p for p in app.params if p["id"] == "affection")
        print("置き換え後:", a["rate_rules"])
        assert {"when": "loneliness>=85", "rate": -0.3} not in a["rate_rules"] and len(a["rate_rules"]) == 2
        assert any("stage=visit|live" in r["when"] for r in a["rate_rules"])

        # お詫び: 記録では 40 + 3 = 43 のはずが 25.5 → 連絡先なので全部戻す. 二度は戻さない
        st = app.state(cid)
        app.bonds.set_stage(cid, "contact")
        app.life.player_state().setdefault("fix_comp", {}).pop("lonely_drain", None)
        app.log(cid)[:] = [{"t": time.time() - 86400, "action": "talk", "deltas": {"affection": 3}}]
        st["params"]["affection"] = 25.5
        got = app.lonely_comp()
        print("お詫び:", got, app.chat.load(cid)["items"][-1]["text"])
        assert abs(got[cid] - 17.5) < 0.05 and abs(st["params"]["affection"] - 43) < 0.05
        assert app.lonely_comp() == {}
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
