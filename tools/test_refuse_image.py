"""F14: 断られたのに, 画像では受け取って飲み食いしている・お金を持っている, をなくす (一時データ).
actions.json の全行動 × 全反応を回し, 断る反応 (override. taken = 受け取りはした, を除く) では行動の絵 (pos) が入らず,
受け取った反応では今までどおり入ること. お小遣い・高価な贈り物・お金を借りる・飲み物・お菓子は, タグでも確かめる.

    python tools/test_refuse_image.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from core.engine import split_tags  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)

# 断ったときに, 絵に出てはいけないタグ
NOT_WHEN_REFUSED = {"allowance": ["holding money", "envelope"], "expensive_gift": ["holding jewelry box", "necklace"],
                    "borrow": ["holding wallet"], "water": ["drinking"], "snack": ["eating"], "cook": ["eating"]}


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("断る")
        cid = app.settings["active_character"]
        char, st = app.chars[cid], app.state(cid)
        dt = datetime.now()
        base = {t.lower() for t in split_tags(app.build_prompt(char, st, dt)[0])}
        n_ref = n_ok = 0
        for a in app.actions:
            if not a.get("pos"):
                continue
            for r in a.get("reactions") or []:
                pos, neg, parts = app.build_prompt(char, st, dt, a, r)
                act_part = next((p for p in parts if p["src"].startswith("行動: ")), None)
                refused = bool(r.get("override") and not r.get("taken"))
                got = {t.lower() for t in split_tags(pos)}
                if refused:
                    n_ref += 1
                    assert act_part is None or not act_part["pos"], (a["id"], r.get("when"), "断ったのに行動の絵", act_part)
                    keep = {t.lower() for t in split_tags(r.get("pos", ""))} | base
                    for t in NOT_WHEN_REFUSED.get(a["id"], []):
                        assert t not in got or t in keep, (a["id"], r.get("when"), "断ったのに", t, pos)
                else:
                    n_ok += 1
                    want = {t.lower() for t in split_tags(a["pos"])} - {t.lower() for t in scene_rm(app, char, st, dt)}
                    miss = {t for t in want - got if "blush" not in t}     # 照れの赤らみは照れやすさで外す (_blush_by_shyness)
                    assert not miss, (a["id"], r.get("when"), "受け取ったのに行動の絵が無い", miss)
        print("断る反応 %d 本は行動の絵なし, 受け取る反応 %d 本は今までどおり: OK" % (n_ref, n_ok))
        assert n_ref >= 30 and n_ok >= 30
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def scene_rm(app, char, st, dt):
    return app.scene_at(char, st, dt).get("remove_tags") or []


if __name__ == "__main__":
    main()
