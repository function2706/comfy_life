"""ミニゲームのできる場所 (A12 の 1 行目 / S10).
道具の要るゲーム (麻雀・盤・サイコロ・花札・トランプ) は家 (あなたの家・相手の家) だけ, 脱衣 (野球拳・脱衣麻雀・脱衣ポーカー) は
二人きりの家だけ, 道具なしで罰の軽いもの (あっち向いてホイ・数当て) はどこでも.
場所 × すべてのゲームで, 一覧の ok (画面で押せる) と start (本当に始まる) を突き合わせる. 途中で外に出たら打ち切り. 一時データ.

    python tools/test_game_place.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, games as G, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)

FREE = {"acchimuite", "numeron"}                       # どこでも
STRIP = {"yakyuken", "mahjong", "poker"}               # 二人きりの家だけ


def main():
    random.seed(5)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("できる場所")
        cid = app.settings["active_character"]
        other = app.new_character("ゆい", stage="contact")["id"]
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        B = app.bonds
        st = app.state(cid)
        for g in app.minigames:
            g.pop("hidden", None)                         # ダウトも並べて確かめる
        ids = [g["id"] for g in app.minigames]
        assert {g["kind"] for g in app.minigames} == set(G.KINDS), "既定のゲームで kind をすべて覆う"
        for c in (cid, other):
            app.set_params({"affection": 90, "trust": 90, "mood": 80, "energy": 80}, c)

        def reset():
            for c in (cid, other):
                app.state(c)["game"] = None
                app.state(c)["override"] = None
            if B.with_rec():
                B.end(go_home=False)
            app.presence.declare("none", time.time())
            app.presence.rec()["pos"] = "home:me"
            app.presence.rec().pop("travel", None)

        def outing(place):
            B.start(cid, "meet")
            now = time.time()
            st["override"] = {"outing": True, "place": place, "location": place, "until": now + 3600, "arr": now - 60,
                              "leave": now + 3000, "from_action": place}

        def expect(gid, spot):
            if spot in ("home", "her_home"):
                return True
            if spot == "home_crowd":
                return gid not in STRIP
            return gid in FREE

        def check(label, spot, who=cid):
            char = app.chars[who]
            sw = app.state(who)
            sp = app.games.spot(who)
            want_spot = "home" if spot == "home_crowd" else spot
            assert sp and sp["spot"] == want_spot, (label, sp)
            gv = {x["id"]: x for x in app.games.view(char, sw, app.context(char, sw, engine.datetime.now()))["list"]}
            row = []
            for gid in ids:
                want = expect(gid, spot)
                assert gv[gid]["ok"] == want, (label, gid, gv[gid])
                assert bool(gv[gid]["why"]) == (not want), (label, gid, gv[gid])
                sw["game"] = None
                try:
                    r = app.games.start(gid, who)
                    started = bool(sw.get("game")) and not r.get("refused")
                    assert want and started, (label, gid, "始まった", r.get("entry", {}).get("text"))
                except ValueError as e:
                    assert not want, (label, gid, str(e))
                    assert gv[gid]["why"] in str(e), (label, gid, str(e), gv[gid]["why"])
                sw["game"] = None
                row.append("%s%s" % (gid, "○" if want else "×"))
            print("%s: OK | %s" % (label, " ".join(row)))

        # ---- 家: 同居相手と二人 / 来てもらっている / 相手の家 / 泊まり
        B.set_stage(cid, "live")
        reset()
        check("同居相手と家で二人", "home")
        B.set_stage(cid, "visit")
        reset()
        B.start(cid, "guest")
        check("家に来てもらっている", "home")
        reset()
        B.start(cid, "visit")
        check("相手の家", "her_home")
        B.with_rec()["stay"] = True
        check("相手の家に泊まり", "her_home")

        # ---- 家だが二人きりでない: 同居相手のいる家に, ほかの人を招いている
        reset()
        B.set_stage(cid, "live")
        B.set_stage(other, "contact")
        B.start(other, "guest")
        assert B.company() == [other, cid], B.company()
        check("家に同居相手と来客（来客と遊ぶ）", "home_crowd", who=other)
        check("家に同居相手と来客（同居相手と遊ぶ）", "home_crowd", who=cid)

        # ---- 外: 店 (屋内・人目あり) / 屋外 / 移動中
        reset()
        B.set_stage(cid, "contact")
        outing("cafe")
        check("外で会ってカフェ", "shop")
        reset()
        outing("restaurant")
        check("外で会ってレストラン", "shop")
        reset()
        outing("park")
        check("外で会って公園", "outdoor")
        reset()
        outing("park")
        st["override"]["arr"] = time.time() + 600       # まだ向かっている途中
        check("一緒に移動中", "moving")

        # ---- 同居相手と一緒にお出かけ (形は home のまま)
        reset()
        B.set_stage(cid, "live")
        now = time.time()
        st["override"] = {"outing": True, "place": "beach", "location": "海", "until": now + 3600, "arr": now - 60,
                          "leave": now + 3000, "from_action": "beach"}
        check("同居相手と海へお出かけ", "outdoor")

        # ---- 途中で外に出たら打ち切り (脱衣を相手の家で始めて, 外で会う形になった)
        reset()
        B.set_stage(cid, "contact")
        B.start(cid, "visit")
        r = app.games.start("yakyuken", cid)
        assert st.get("game"), r
        B.end(go_home=False)
        outing("park")
        r = app.games.move(cid, {"hand": "rock"})
        assert r.get("ended") == "interrupted" and not st.get("game"), r
        print("途中で外に出た: OK | %s" % r["entry"]["text"])

        # ---- 定義で上書き: トランプを道具なしにすれば外でも / 数当てを private にすれば外では不可
        reset()
        outing("park")
        saved = [dict(g) for g in app.minigames]
        for g in app.minigames:
            if g["id"] == "oldmaid":
                g["needs"] = "none"
            if g["id"] == "numeron":
                g["privacy"] = "private"
        app.save_minigames(app.minigames)
        gv = {x["id"]: x for x in app.games.view(app.chars[cid], st, app.context(app.chars[cid], st, engine.datetime.now()))["list"]}
        assert gv["oldmaid"]["ok"] and not gv["numeron"]["ok"], (gv["oldmaid"], gv["numeron"])
        for bad in ({"needs": "ball"}, {"privacy": "secret"}):
            try:
                app.save_minigames([dict(saved[0], **bad)] + saved[1:])
                raise AssertionError("不正な %s が通った" % bad)
            except ValueError as e:
                print("定義の検査: OK | %s" % e)
        app.save_minigames(saved)
        print("定義で上書き: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
