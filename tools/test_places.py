"""行き先の表の確認 (一時データ, 画像生成なし).
- 表は 1 つ (core/places.py): 公共の行き先 + あなたの家 + 家に行ける仲の相手の家
- 一人の外出は「外出」1 つ. 行き先しだいで, することが決まる (歩く・買い物・お茶・見て回る・訪ねる)
- 店ごとの品ぞろえ (買うものリストの品は, 売っている店でだけ買える)
- 誰かとのお出かけも表の行き先 (選べるものは選べる). 以前の一時シーン (日本語の場所だけ) も読み替える
- 約束なしに相手の家を訪ねる: 留守・出てこない・迎えてくれる・断られる (状況・仲・性格しだい. 補正なし)
- 行動パターンの 散歩・買い物・カフェ は, 起動時に 外出 + 行き先 に書き換える

    python tools/test_places.py
"""
import json
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, places, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(29)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        # ---- 0. 行動パターンの移行 (起動前の設定が以前の語彙)
        os.makedirs(tmp, exist_ok=True)
        with open(os.path.join(tmp, "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"offline": {"days": {"mon": [{"at": "00:00", "do": "sleep"}, {"at": "10:00", "do": "shopping"},
                                                    {"at": "12:00", "do": "walk", "place": "riverside"},
                                                    {"at": "15:00", "do": "cafe"}]}}}, f, ensure_ascii=False)
        assert any("外出" in x for x in store.pending_migrations(None))
        app = engine.App()
        app.save_settings({"auto_generate": False})
        mon = store.load(store.dpath("settings.json"))["offline"]["days"]["mon"]
        assert [(b["do"], b.get("place")) for b in mon] == [("sleep", None), ("out", "shopping_street"), ("out", "riverside"),
                                                             ("out", "cafe")], mon
        assert not any("外出" in x for x in store.pending_migrations(store.load_worlds()))
        print("routine migration: OK")

        # ---- 1. 表: 公共の行き先 + あなたの家 + 家に行ける仲の相手の家
        app.create_world("行き先")
        P, S, L, I, B = app.places, app.solo, app.life, app.items, app.bonds
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        t = P.table()
        assert places.HOME_ME in t and "home:" + cid not in t, "連絡先の人の家は, まだ知らない"
        for k in ("supermarket", "convenience", "electronics", "drugstore", "bookstore", "shopping_street", "mall",
                  "aquarium", "beach", "amusement", "hill", "mountain"):
            assert k in t, k
        B.set_stage(cid, "visit")
        assert "home:" + cid in P.table() and "home:" + cid in P.out_choices() and places.HOME_ME not in P.out_choices()
        assert "office" not in P.out_choices(), "職場は「仕事に行く」から"
        v = app.state_view()["outdoor"]
        assert "home:" + cid in v["choices"]["out"] and v["places"]["home:" + cid]["group"] == "home"
        print("table: OK")

        # ---- 2. 外出: 行き先しだいで, することが決まる
        ps = L.player_state()
        ps["money"] = 50000
        app.world["outdoor"] = {"rate_out": 0}
        assert places.solo_kind("park") == "walk" and places.solo_kind("supermarket") == "shopping" \
            and places.solo_kind("cafe") == "cafe" and places.solo_kind("aquarium") == "see" and places.solo_kind("home:x") == "visit"
        r = S.result("out", 2.0, time.time(), place="aquarium")
        assert r["kind"] == "see" and r["money"] == -2500 and "水族館" in r["text"], r
        # ---- 3. 店ごとの品ぞろえ: 本は本屋, 洗剤はドラッグストアやスーパー. スーパーに本は無い
        I.set_list("book_talk", 1)
        I.set_list("detergent", 1)
        for _ in range(10):
            I.shop("supermarket")
        assert I.count("book_talk") == 0 and I.count("detergent") >= 1
        for _ in range(10):
            I.shop("bookstore")
            if I.count("book_talk"):
                break
        assert I.count("book_talk") == 1
        print("out by place / shops: OK")

        # ---- 4. 約束なしに相手の家を訪ねる
        st["override"] = {"activity": "outing", "label": "出かけている", "location": "街", "until": time.time() + 9e6, "outing": True}
        r = S.start("out", place="home:" + cid)
        assert r["started"] == "out" and "留守" in r["text"] and app.presence.rec()["mode"] == "out", r
        assert B.mode(cid) is None
        app.come_back()
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}
        got = {"visit": 0, "out": 0}
        for i in range(40):
            app.set_params({"affection": 60, "trust": 55, "mood": 60}, cid)
            st["gain_day"] = {}
            r = app.drop_in(cid)
            got[r["started"]] += 1
            if r["started"] == "visit":
                assert B.mode(cid) == "visit"
                B.end()
            else:
                assert app.log(cid)[-1]["action"] == "_drop_in"
                app.come_back()
        assert got["visit"] and got["out"], "迎えてくれることが多いが, 必ずではない: %s" % got
        low = {"visit": 0, "out": 0}
        for i in range(40):
            app.set_params({"affection": 30, "trust": 30, "mood": 30}, cid)
            r = app.drop_in(cid)
            low[r["started"]] += 1
            if r["started"] == "visit":
                B.end()
            else:
                app.come_back()
        assert low["visit"] < got["visit"], (low, got)
        assert any(x.get("action") == "_drop_in" for x in st["reasons"]), "急に来られて断ったことは, 機嫌の理由に残る"
        B.set_stage(cid, "contact")
        try:
            app.drop_in(cid)
            raise AssertionError("家を知らない相手を訪ねられる")
        except ValueError:
            pass
        print("drop in: OK", got, low)

        # ---- 5. 誰かとのお出かけも表の行き先 (選べるものは選べる)
        app.create_world("同居", )
        cid = app.settings["active_character"]
        B.set_stage(cid, "live")
        st = app.state(cid)
        st["override"] = None
        app.set_params({"affection": 70, "mood": 70, "energy": 80, "sleepiness": 0}, cid)
        st["cooldowns"] = {}
        app.act("walk", cid, opts={"place": "riverside"})
        ov = st["override"]
        assert ov["place"] == "riverside" and ov["location"] == "河川敷" and app.outdoor.current()["place"] == "riverside", ov
        app.act("go_home", cid)
        st["cooldowns"] = {}
        app.act("walk", cid, opts={"place": "aquarium"})          # 散歩では選べない行き先: 既定に
        assert st["override"]["place"] == "park"
        app.act("go_home", cid)
        # 以前の一時シーン (場所の日本語だけ) は読み替える
        st["override"] = {"activity": "beach", "label": "海でのんびり中", "location": "海辺", "outing": True, "until": time.time() + 3600}
        assert app.outdoor.current()["place"] == "beach"
        st["override"] = None
        print("outings: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
