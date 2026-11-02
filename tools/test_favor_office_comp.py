"""手伝いが職場になっていた件の直し (App.favor_office_comp. 一度だけ):
- 以前の形 (在席 work) で手伝っている最中 → 相手の家での手伝いに切り替える (始めた時刻のまま. 途中で帰った扱いにしない)
- 途中で切り上げていた → 罰を戻して頼み直してもらう (前のお詫び favor_redo をもう使っていても)
- 手伝いの間に「職場で」知り合った人 → 同僚の印を外す (手伝いの時間の外で知り合った同僚はそのまま)
(一時データ, 画像生成なし)

    python tools/test_favor_office_comp.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import earn as EA, engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(2)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("職場の直し")
        A, B, E = app.appoint, app.bonds, app.earn
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        B.set_stage(cid, "contact")
        now = time.time()
        done = app.life.player_state().setdefault("fix_comp", {})

        def favor(t, fid):
            k, name, h, tire = EA.FAVOR_KIND["clean"]
            f = {"id": fid, "cid": cid, "kind": "clean", "label": name, "h": h, "tire": tire, "t": t, "until": t + 86400}
            E.favors().append(f)
            x = {"id": "a" + fid, "cid": cid, "place": "home:" + cid, "do": "_favor", "by": "her", "status": "met", "made": t - 86400,
                 "favor": fid, "fkind": "clean", "label": name, "t": t}
            f["appoint"] = x["id"]
            A.all().append(x)
            return f, x

        # ---- 1. 以前の形で手伝っている最中 → 相手の家での手伝いへ (1 時間前に始めた)
        f, x = favor(now - 3600, "fa")
        app._go_task("favor", f, "（以前の形）")
        app.presence.rec()["since"] = now - 3600
        done.pop("favor_office", None)
        r = app.favor_office_comp(now)
        hp = app.athome.helping(cid)
        assert r.get("converted") == cid and app.presence.rec()["mode"] == "none" and B.mode(cid) == "visit", r
        assert hp and abs(hp["t0"] - (now - 3600)) < 1 and abs(hp["until"] - (now - 3600 + f["h"] * 3600)) < 1, hp
        assert app.outdoor.current(now) is None and app.geo.where(now) == "home:" + cid, "職場にいない"
        assert "手伝ってもらっている" in app.scene_at(char, st, __import__("datetime").datetime.fromtimestamp(now))["label"]
        tr0 = st["params"]["trust"]
        r2 = app.athome.live(cid, hp["until"] + 1)
        assert "終えた" in r2["text"] and st["params"]["trust"] >= tr0, r2["text"]
        print("最中 → 相手の家での手伝いに:", r2["text"])
        assert app.favor_office_comp(now) is None, "一度だけ"
        B.end(go_home=False)

        # ---- 2. 途中で切り上げていた (前のお詫びはもう使った) → 罰を戻して頼み直してもらう
        done.pop("favor_office", None)
        done["favor_redo"] = now - 86400
        f2, x2 = favor(now - 5 * 3600, "fb")
        E.favor_done(f2, 0.5, now - 4 * 3600)                   # 途中で帰った: 信頼・機嫌 -1 (一覧には残る)
        tr0 = st["params"]["trust"]
        r = app.favor_office_comp(now)
        nx = A.find(f2["appoint"])
        assert r.get("redo") == nx["id"] and nx["status"] == "offered" and st["params"]["trust"] > tr0, r
        print("切り上げていた → 頼み直し:", A.when_of(nx, now))
        assert app.favor_redo_comp(now, key="favor_office_redo") is None
        done.pop("favor_office_redo", None)
        assert app.favor_redo_comp(now, key="favor_office_redo") is None, "もう頼み直してもらっていれば二度はしない"

        # ---- 3. 手伝いの間に「職場で」知り合った人の同僚の印を外す (時間の外の同僚はそのまま)
        done.pop("favor_office", None)
        ppl = app.street.people()
        plain = {"name": "テスト太郎", "pos": "short hair"}
        while any(h_[0] == "office" for h_ in __import__("core.street", fromlist=["x"]).haunts_of(plain)):
            plain["name"] += "朗"
        ppl["pin"] = {"char": plain, "stage": 0, "haunts": [["park", "noon"], ["office", None]], "coworker": True, "first": x2["t"] + 1800}
        ppl["pout"] = {"char": dict(plain, name=plain["name"] + "二"), "stage": 0, "haunts": [["office", None]], "coworker": True,
                       "first": x2["t"] - 3 * 86400}
        app.street.save_people(ppl)
        r = app.favor_office_comp(now)
        ppl = app.street.people()
        assert not r.get("redo") and r.get("coworkers") == 1 and not ppl["pin"]["coworker"] and ppl["pin"]["haunts"] == [["park", "noon"]] and ppl["pout"]["coworker"], r
        print("手伝いの間の同僚の印を外した:", r)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
