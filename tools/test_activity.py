"""「いつ・どこで・何を・誰と」の読み出し (core/activity.py. A24) の確認 (一時データ, 画像生成なし).

状態 (家・一人の外出・移動中・仕事・外で会っている・一緒に移動中・相手の家・招いている・同居相手と家・作業中・寝ている・玄関先)
× 読み出し (player / outdoor.current / home_free / out_with / bonds.mode / company) を, 置き換える前の式と突き合わせる.
「誰と」(with) の置き場の移行 (player.json 直下 → presence) と, 閉じている間の「家を空けている枠」も.

    python tools/test_activity.py
"""
import json
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from core import places as places_mod  # noqa: E402
from core.bonds import migrate_with  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
PLACES = places_mod.PLACES
HOME_ME = places_mod.HOME_ME


# ---------------------------------------------------------------- 置き換える前の式 (1.7.0beta 5f8eb93 の写し)
def old_current(app, now):
    p = app.presence.rec()
    tr = p.get("travel")
    if tr and p.get("mode") in ("out", "work"):
        return {"kind": "out", "place": "station" if tr.get("how") == "transit" else "town", "with": None, "moving": True,
                "inside": tr.get("how") in ("car", "taxi"),
                "dest": tr["to"] if tr.get("dir") == "go" else HOME_ME, "how": tr.get("how")}
    if p.get("mode") == "out":
        pl = p.get("place") or "town"
        if places_mod.is_home(pl):
            return {"kind": "out", "place": pl, "with": None}
        return {"kind": "out", "place": pl if pl in PLACES else "town", "with": None}
    if p.get("mode") == "work":
        return {"kind": "work", "place": "office", "with": None}
    for cid in app.chars:
        if not app.bonds.together(cid):
            continue
        ov = app.state(cid).get("override") or {}
        if ov.get("outing") and ov.get("until", 0) > now:
            trip = app.outing_trip(app.state(cid), now)
            if trip:
                return {"kind": "outing", "place": "station" if trip.get("legs") or trip.get("how") == "transit" else "town",
                        "with": cid, "moving": True, "inside": trip.get("how") in ("car", "taxi"), "how": trip.get("how"),
                        "dest": trip["to"] if trip["dir"] == "go" else HOME_ME}
            pl = ov.get("place") if ov.get("place") in PLACES else places_mod.from_location(ov.get("location"))
            return {"kind": "outing", "place": pl, "with": cid}
    return None


def old_home_free(app, now):
    w = app.bonds.with_rec()
    return app.presence.rec().get("mode") in ("none", "busy") and not old_current(app, now) \
        and not (w and w["mode"] in ("meet", "visit"))


def old_out_with(app, now):
    w = app.bonds.with_rec()
    if w and w.get("mode") in ("meet", "visit"):
        return w["cid"]
    for cid in app.bonds.company():
        ov = app.state(cid).get("override") or {}
        if ov.get("outing") and ov.get("until", 0) > now:
            return cid
    return None


def old_away_closed(app, t):
    off = app.offline
    beat = app.presence.rec().get("beat", 0)
    if not beat or t <= beat or not off.will_run(beat, t):
        return False
    b = None
    if app.planner.active():
        for s, e, kind, x in app.planner.slots(t, t + 60):
            if not (s <= t < e):
                continue
            if kind == "appoint":
                return x.get("place") != HOME_ME
            if kind == "exam":
                return True
            if kind == "plan":
                b = x
            break
    if b is None:
        if not off.cfg().get("enabled"):
            return False
        b = next((bb for s, e, bb in off.blocks(t, t + 60) if s <= t < e), None)
    if not b:
        return False
    return b.get("do") in ("work", "parttime", "out", "jog", "exam") or (b.get("do") == "meal" and b.get("how") in ("out", "buy"))


# ---------------------------------------------------------------- 状態を作る
def reset(app):
    """家で一人 (同居相手の予定も家に)."""
    B = app.bonds
    if B.with_rec():
        B.wrec()["with"] = None
    p = app.presence.rec()
    for k in ("travel", "arrived", "left", "solo", "place"):
        p.pop(k, None)
    p["mode"], p["since"] = "none", time.time()
    p["beat"] = p["input"] = time.time()
    for cid in app.chars:
        st = app.state(cid)
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": 9e12}
    app.presence.save()


def outing(app, cid, place, trip=None):
    st = app.state(cid)
    now = time.time()
    st["override"] = {"activity": "together", "label": "一緒", "location": PLACES[place]["label"], "place": place,
                      "until": now + 3600, "outing": True, "start": now}
    if trip:
        st["override"]["trips"] = [dict(trip, t0=now - 60, arr=now + 600)]


def check(app, name, expect):
    now = time.time()
    A = app.activity
    act = A.player(now)
    cur = app.outdoor.current(now)
    assert cur == old_current(app, now), (name, cur, old_current(app, now))
    assert A.home_free(now) == old_home_free(app, now), (name, A.home_free(now))
    assert A.out_with(now) == old_out_with(app, now), (name, A.out_with(now))
    assert app.outing_now(now)[0] == (cur or {}).get("with") if (cur or {}).get("kind") == "outing" else True, name
    for k, v in expect.items():
        assert act[k] == v, (name, k, act[k], v, act)
    # 外にいるなら, 外出の画面の現在地と Activity の kind がそろう
    assert (cur is None) == (act["kind"] is None), (name, cur, act)
    # 同居相手・招いた人・外で会っている人は company と with がそろう (相手の家・外で会っている人は, 一緒でなくてもよい)
    assert set(act["with"]) <= set(app.bonds.company()) | {(app.bonds.with_rec() or {}).get("cid")}, (name, act)
    for cid in act["with"]:
        ca = A.char(cid, now)
        assert ca["do"] == "with" and "player" in ca["with"] and ca["place"] == act["place"], (name, ca)
    print("  %-16s do=%-5s place=%-10s with=%s how=%s kind=%s free=%s" % (
        name, act["do"], act["place"], act["with"], act["how"], act["kind"], A.home_free(now)))


def main():
    random.seed(3)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        B = app.bonds
        live = B.living()
        assert live == "hina"
        P = app.presence
        other = live           # 同居していない相手としては, 新しいワールドでのひな (4. から)

        # ---- 1. 同居相手と家 (最初のワールド)
        reset(app)
        check(app, "同居相手と家", {"place": HOME_ME, "with": [live], "how": "home", "kind": None})
        P.rec()["mode"] = "busy"
        check(app, "作業中", {"do": "busy", "place": HOME_ME, "kind": None})
        P.rec()["mode"] = "sleep"
        check(app, "寝ている", {"do": "sleep", "place": HOME_ME, "kind": None})
        assert not app.activity.home_free()

        # ---- 2. 一人の外出・移動中・仕事・玄関先
        reset(app)
        P.declare("out")
        P.rec()["place"] = "park"
        check(app, "一人で公園", {"do": "out", "place": "park", "with": [], "kind": "out"})
        P.rec()["travel"] = {"how": "transit", "dir": "go", "to": "mall", "t0": time.time() - 60, "arr": time.time() + 600}
        check(app, "移動中(行き)", {"place": "mall", "kind": "out", "moving": True})
        P.rec()["travel"] = {"how": "taxi", "dir": "back", "to": HOME_ME, "t0": time.time() - 60, "arr": time.time() + 600}
        check(app, "移動中(帰り)", {"place": HOME_ME, "kind": "out", "moving": True})
        assert not app.activity.at_home(), "家へ向かっているあいだは, まだ家ではない"
        P.rec().pop("travel")
        P.rec()["place"] = "home:x"
        check(app, "玄関先", {"place": "home:x", "kind": "out"})
        P.rec()["place"] = "nowhere"
        check(app, "表に無い行き先", {"place": "town"})
        reset(app)
        P.declare("work")
        check(app, "仕事", {"do": "work", "place": "office", "kind": "work"})

        # ---- 3. 同居相手とお出かけ (with は無い)
        reset(app)
        outing(app, live, "cafe")
        check(app, "同居相手と外", {"place": "cafe", "with": [live], "how": "live", "kind": "outing"})
        outing(app, live, "aquarium", trip={"dir": "go", "to": "aquarium", "how": "transit", "legs": [1]})
        check(app, "同居相手と移動", {"place": "aquarium", "kind": "outing", "moving": True})

        # ---- 4. 外で会っている・相手の家・招いている (同居していない相手: 新しいワールドのひな)
        app.create_world("ひとり暮らし")
        B, P = app.bonds, app.presence
        assert B.living() is None and B.stage(other) != "live"
        reset(app)
        check(app, "一人で家", {"place": HOME_ME, "with": [], "how": None, "kind": None})
        B.start(other, "meet")
        outing(app, other, "park")
        check(app, "外で会っている", {"place": "park", "with": [other], "how": "meet", "kind": "outing"})
        app.state(other)["override"]["until"] = time.time() - 1          # お出かけの記録が切れた (sync で別れる前)
        check(app, "会う記録が切れ", {"with": [other], "how": "meet", "kind": None})
        assert app.activity.player()["place"] != HOME_ME and not app.activity.home_free()
        reset(app)
        B.start(other, "visit")
        check(app, "相手の家", {"place": "home:" + other, "with": [other], "how": "visit", "kind": None})
        assert not app.activity.at_home() and not app.activity.home_free()
        reset(app)
        B.start(other, "guest")
        check(app, "招いている", {"place": HOME_ME, "how": "guest", "kind": None})
        assert other in app.activity.player()["with"]
        assert app.activity.home_free(), "家に来てもらっている間も, 声をかければ一人のことができる"
        reset(app)
        print("states: OK")

        # ---- 5. 相手の Activity (本人の予定どおり)
        # (テストの時計は日曜の昼に固定なので, 場面を差し替えて, 場面 × あなたと一緒か の組み合わせで見る)
        from datetime import datetime as _dt
        st = app.state(other)
        st["override"] = None
        real_scene = app.scene_at
        sc0 = real_scene(app.chars[other], st, _dt.now())
        for flags, do in (({"asleep": True, "away": False, "busy": False}, "sleep"),
                          ({"asleep": False, "away": True, "busy": True}, "out"),
                          ({"asleep": False, "away": False, "busy": True}, "busy"),
                          ({"asleep": False, "away": False, "busy": False}, "home")):
            sc = dict(sc0, **flags)
            app.scene_at = lambda char, st_, dt, sc=sc: sc
            try:
                a = app.activity.char(other)
                assert a["do"] == do and a["with"] == [] and (a["place"] == "home:" + other) == (do != "out"), (flags, a)
                ctx = app.context(app.chars[other], st, _dt.now(), view=True)
                assert ctx["out"] == flags["away"] and ctx["away"], "out は本人の予定. away はあなたから見てそばにいない (離れている相手は常に)"
                ctx = app.context(app.chars[other], st, _dt.now(), view=False)
                assert ctx["out"] == ctx["away"] == flags["away"]
            finally:
                del app.scene_at
        B.start(other, "visit")
        a = app.activity.char(other)
        assert a["do"] == "with" and a["with"] == ["player"] and a["place"] == "home:" + other, a
        reset(app)
        print("char: OK")

        # ---- 6. 閉じている間の「家を空けている枠」は以前と同じ
        reset(app)
        beat = time.time()
        P.rec()["beat"] = beat
        diff = 0
        for m in range(40, 7 * 24 * 60, 37):
            t = beat + m * 60
            n, o = app.offline.away_closed(t), old_away_closed(app, t)
            diff += n != o
            if n:
                assert app.activity.planned(t)["do"] in ("work", "parttime", "out", "jog", "exam", "meal"), app.activity.planned(t)
        assert diff == 0, diff
        print("away_closed: OK")

        # ---- 7. 「誰と」の置き場の移行 (player.json 直下 → presence)
        ps = {"bonds": {}, "with": {"cid": other, "mode": "visit", "t": 1, "until": 9e12}, "presence": {"mode": "none"}}
        assert migrate_with(ps) and "with" not in ps and ps["presence"]["with"]["cid"] == other
        assert not migrate_with(ps), "二度目は何もしない"
        ps2 = {"with": None}
        assert migrate_with(ps2) and "with" not in ps2 and not ps2["presence"].get("with")
        # ワールドの player.json を以前の形に戻して, 起動時の移行で移るか (バックアップの理由に出るか)
        app.life.save_player()
        path = store.dpath("worlds", store.WORLD, "player.json")
        raw = json.load(open(path, encoding="utf-8"))
        raw["presence"].pop("with", None)
        raw["with"] = {"cid": other, "mode": "visit", "t": time.time(), "until": time.time() + 3600}
        json.dump(raw, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        meta = store.load(store.dpath("worlds.json"))
        assert any("誰と" in x for x in store.pending_migrations(meta)), store.pending_migrations(meta)
        store.bootstrap()
        assert not any("誰と" in x for x in store.pending_migrations(meta))
        raw = json.load(open(path, encoding="utf-8"))
        assert "with" not in raw and raw["presence"]["with"]["cid"] == other
        app2 = engine.App()
        assert app2.bonds.mode(other) == "visit" and app2.activity.player()["place"] == "home:" + other, "相手の家にいる途中から続く"
        print("migrate: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
