"""出先での合流と, 互いの家へ (一時データ, 画像生成なし).
- 一人で出かけて, 連絡先の相手と立ち話をしたら, そのまま一緒に過ごす話になることがある
  (相手から誘われる / こちらから誘う. 受けるか・誘うかは仲・機嫌・性格しだいで, 断られることも)
- 会釈だけ・誰かと一緒・誰とも知らない相手なら, その話にはならない
- 合流したら一人の外出はそこまで (結果は残る). 相手と同じ行き先で, 外で会っている (meet)
- 外で会っている家に行ける仲の相手とは, 互いの家へ (「うちに寄っていく？」「家に寄ってもいい？」. 断られることも)
  相手の家では暮らしぶりが見える. あなたの家なら家の様子に反応する

    python tools/test_join.py
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
    random.seed(41)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("合流")
        S, B, St = app.solo, app.bonds, app.street
        app.world["outdoor"] = {"rate_out": 0}
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        st["override"] = {"activity": "walk", "label": "散歩中", "location": "公園", "until": time.time() + 9e6}

        def meet(choice, **params):
            if app.presence.rec().get("mode") != "out":
                S.start("out", place="park")
            app.set_params(dict({"affection": 50, "mood": 60, "loneliness": 50}, **params), cid)
            st["gain_day"] = {}
            St._meet("char", cid, "公園", None, time.time(), "park")
            return St.resolve(choice)

        # ---- 1. 会釈だけなら, 一緒に過ごす話にはならない
        r = meet("nod")
        assert not r.get("join") and St.join_view() is None
        # ---- 2. 立ち話をすると: 相手から誘われることも. 仲が深く寂しいほど誘われやすい (必ずではない)
        offers = {"low": 0, "high": 0}
        for lv, params in (("low", {"affection": 42, "loneliness": 20}), ("high", {"affection": 80, "loneliness": 90})):
            for _ in range(40):
                r = meet("chat", **params)
                assert r["join"] and St.join_view()["cid"] == cid
                offers[lv] += r["join"]["offer"]
                St.join(False)
        assert offers["low"] < offers["high"] < 40, offers
        r = meet("chat", affection=30)
        assert not r["join"]["offer"], "仲が浅いと, 相手からは誘わない"
        St.join(False)
        # ---- 3. こちらから誘う: 受けるかは相手しだい
        res = {"yes": 0, "no": 0}
        for _ in range(30):
            r = meet("chat", affection=55, mood=55, loneliness=10)
            if r["join"]["offer"]:
                St.join(False)
                continue
            j = St.join(True)
            if j["joined"]:
                res["yes"] += 1
                assert B.mode(cid) == "meet" and st["override"]["place"] == "park" and app.outdoor.current()["kind"] == "outing"
                assert app.presence.rec()["mode"] == "none", "一人の外出はそこまで"
                assert j["solo"] and "公園" in j["solo"]["text"], "一人で過ごした分の結果は残る"
                app.act("go_home", cid)
                assert B.mode(cid) is None
            else:
                res["no"] += 1
                assert app.presence.rec()["mode"] == "out", "断られたら, そのまま一人で外にいる"
        assert res["yes"] and res["no"], res
        if app.presence.rec().get("mode") == "out":
            app.come_back()
        print("join: OK", offers, res)

        # ---- 4. 外で会っている家に行ける仲の相手と, 互いの家へ
        B.set_stage(cid, "visit")

        def joined():
            for _ in range(50):
                r = meet("chat", affection=85, mood=80, loneliness=80)
                if St.join(True)["joined"]:
                    return
            raise AssertionError("合流できない")

        joined()
        app.set_params({"affection": 40, "mood": 70}, cid)
        st["cooldowns"] = {}
        e = app.act("go_her_home", cid)["entry"]
        assert B.mode(cid) == "meet", "仲がまだ浅いと断られる"
        app.set_params({"affection": 80, "mood": 70}, cid)
        st["cooldowns"] = {}
        e = app.act("go_her_home", cid)["entry"]
        assert B.mode(cid) == "visit" and "の部屋は" in e["text"], e["text"]
        print("her home:", e["text"].split("\n")[-1])
        B.end()
        joined()
        for k in ("mess", "dishes", "laundry", "trash"):
            app.home.rec()[k] = 5.0
        st["cooldowns"] = {}
        app.set_params({"affection": 80, "mood": 70}, cid)
        e = app.act("bring_home", cid)["entry"]
        assert B.mode(cid) == "guest" and st["override"]["location"] == "あなたの家" and not app.outdoor.current()
        print("bring home: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
