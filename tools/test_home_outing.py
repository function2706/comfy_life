"""家デートから二人で出かけて, 出た先からまたどちらかの家へ (一時データ, 画像生成なし).
- 相手の家に来ている (visit) / 招いている (guest) ときに「移動」のコマンドで出かけたら, 家を出たので「外で会っている」(meet) になる
  (以前は visit / guest のまま外にいて,「家に寄ってもいい？」/「うちに寄っていく？」が出ず, 押せるのは解散・その場での別れだけだった)
- 移動は出る前の家から. 来客の一時シーンは出かけた先のものに置き換わる. お泊りはそこで終わる
- 出た先で: 家に寄るコマンド 2 つが押せる (画面の available と act が一致), 「そろそろ帰るね」「送っていくね」は押せない
- 出た先から相手の家へ / あなたの家へ: 一緒に移動して上がる
- 出かけた先の時間が終わったら, ふつうの外デートと同じく別れる (以前は移動なしで家デートに戻っていた)
- 遡及: 1.7.0 までのセーブ (visit / guest のまま外に出ている) は, 次の時間の進みで外で会っているに直る (一度だけ. 二重にしない)

    python tools/test_home_outing.py
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
from core import engine, geo as G, store  # noqa: E402
from core import parting as _parting  # noqa: E402
_parting.FIXED = "ok"
from testclock import fix_noon  # noqa: E402
from test_home_trip import shift  # noqa: E402

fix_noon(engine)
G.INSTANT = False
HOME_CMDS = ("go_her_home", "bring_home")
END_CMDS = ("leave_visit", "see_off")


def at_home_date(app, cid, mode):
    """相手の家に来ている (visit) / あなたの家に招いている (guest)."""
    app.bonds.end(go_home=False)
    app.presence.rec()["mode"] = "none"
    app.presence.rec().pop("travel", None)
    app.presence.rec()["pos"] = ("home:" + cid) if mode == "visit" else "home:me"
    app.presence.save()
    st = app.state(cid)
    st["override"] = None
    st["cooldowns"] = {}
    st["gain_day"] = {}
    app.bonds.start(cid, mode)
    if mode == "guest":
        st["override"] = app._guest_override("invite_home", time.time())
    app.set_params({"affection": 85, "mood": 80, "trust": 75}, cid)
    return st


def go_cafe(app, cid):
    st = app.state(cid)
    r = app.act("cafe", cid, opts={"quarrel_ok": True})
    assert not r.get("disagree"), r
    return st, r


def arrive(app, cid, st):
    shift(st, st["override"]["arr"] - time.time() + 5)
    app.tick(cid)


def main():
    random.seed(11)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("家から外へ")
        cid = app.settings["active_character"]
        B = app.bonds
        B.set_stage(cid, "visit")
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        app.life.player_state()["money"] = 80000
        home = "home:" + cid

        for start in ("visit", "guest"):
            origin = home if start == "visit" else "home:me"
            # ---- 1. 出かけたら外で会っている. 移動は出る前の家から
            st = at_home_date(app, cid, start)
            assert app.geo.where() == origin, app.geo.where()
            st, r = go_cafe(app, cid)
            assert B.mode(cid) == "meet", (start, B.with_rec())
            ov = st["override"]
            assert ov.get("outing") and ov["place"] == "cafe" and ov.get("activity") != "guest", ov
            trip = app.outing_trip(st)
            assert trip and trip["from"] == origin and trip["to"] == "cafe", trip
            # ---- 2. 着いた先で押せるもの: 画面と act が一致
            arrive(app, cid, st)
            assert B.mode(cid) == "meet" and not app.outing_trip(st), (B.with_rec(), st["override"])
            av = app.person_view(cid)["available"]
            for k in HOME_CMDS:
                assert av[k]["ok"], (start, k, av[k])
            for k in END_CMDS:
                assert not av[k]["ok"], (start, k, av[k])
                try:
                    app.act(k, cid)
                    raise AssertionError("押せないはずの %s ができた" % k)
                except ValueError:
                    pass
            print("%s → カフェ: OK | 外で会っている, 家に寄る 2 つが押せる" % start)

            # ---- 3. 出た先から相手の家へ / あなたの家へ
            for cmd, dest, mode in (("go_her_home", home, "visit"), ("bring_home", "home:me", "guest")):
                st = at_home_date(app, cid, start)
                st, _ = go_cafe(app, cid)
                arrive(app, cid, st)
                st["cooldowns"] = {}
                r = app.act(cmd, cid)
                ov = st.get("override") or {}
                if dest == app.geo.where():          # 起きない (カフェにいる) が, 念のため
                    raise AssertionError(app.geo.where())
                assert ov.get("home_trip"), (start, cmd, r["entry"]["text"], ov)
                arrive(app, cid, st)
                assert B.mode(cid) == mode and app.geo.where() == dest, (start, cmd, B.with_rec(), app.geo.where())
                print("%s → カフェ → %s: OK | %s" % (start, cmd, app.log(cid)[-1]["text"].replace("\n", " / ")[:80]))

            # ---- 4. カフェの時間が終わったら別れる (家デートに戻らない)
            st = at_home_date(app, cid, start)
            st, _ = go_cafe(app, cid)
            arrive(app, cid, st)
            for k in ("until", "arr", "leave", "start"):
                if k in st["override"]:
                    st["override"][k] -= 6 * 3600
            app.tick(cid)
            assert B.mode(cid) is None and not B.with_rec(), (start, B.with_rec())
            print("%s → カフェ → 時間切れ: OK | 別れた" % start)

        # ---- 5. 招いた相手と出かけたら, 来客のあとの散らかりは出かけるときに (一度だけ)
        st = at_home_date(app, cid, "guest")
        calls = []
        orig_left = app.home.guest_left
        app.home.guest_left = lambda: (calls.append(1), orig_left())
        st, _ = go_cafe(app, cid)
        arrive(app, cid, st)
        app.tick(cid)
        assert B.mode(cid) == "meet" and len(calls) == 1, (B.with_rec(), calls)
        app.home.guest_left = orig_left
        print("招いた相手と出かける: OK | 来客のあとの散らかりは出るときに一度だけ")

        # ---- 6. お泊りは, 出かけたら終わる
        st = at_home_date(app, cid, "visit")
        B.with_rec()["stay"] = {"t": time.time()}
        B.save()
        assert app.stay.staying(cid)
        go_cafe(app, cid)
        assert B.mode(cid) == "meet" and not app.stay.staying(cid) and not (B.with_rec() or {}).get("stay"), B.with_rec()
        print("お泊りのあと出かける: OK | お泊りは終わり, 外で会っている")

        # ---- 7. 遡及: 1.7.0 までのセーブ (visit / guest のまま外にいる) は, 次の進みで直る. 二度目は何もしない
        for start in ("visit", "guest"):
            st = at_home_date(app, cid, start)
            st, _ = go_cafe(app, cid)
            w = B.with_rec()
            w["mode"] = start                        # 古い形に戻す
            w["until"] = time.time() + 3600
            B.save()
            assert B.mode(cid) == start
            app.tick(cid)
            assert B.mode(cid) == "meet" and st["override"].get("place") == "cafe", (start, B.with_rec(), st["override"])
            t0 = B.with_rec()["t"]
            app.tick(cid)
            assert B.mode(cid) == "meet" and B.with_rec()["t"] == t0
            av = app.person_view(cid)["available"]
            assert all(av[k]["ok"] or av[k]["cooldown"] for k in HOME_CMDS), {k: av[k] for k in HOME_CMDS}
        print("遡及: OK | 古いセーブは外で会っているに直る (一度だけ)")

        # ---- 8. 外で会っている相手と家へ向かう途中 (home_trip) は, 遡及の対象にしない (着いたら上がる)
        st = at_home_date(app, cid, "visit")
        st, _ = go_cafe(app, cid)
        arrive(app, cid, st)
        st["cooldowns"] = {}
        app.act("go_her_home", cid)
        assert st["override"].get("home_trip") and B.mode(cid) == "meet"
        arrive(app, cid, st)
        app.tick(cid)
        assert B.mode(cid) == "visit", B.with_rec()
        print("家へ向かう途中・着いたあと: OK | 相手の家にいる")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
