"""生活の型の割り当て (予定の作り直し) のあとの, 決まっている約束の点検と打診の確認 (一時データ, 画像生成なし).
- 状態 (asked / offered / set / waiting / 頼まれごと / 日時の決まった頼まれごと / 看病 / 手伝い) × 都合 (つく / つかない / 空きが無い)
  × 約束までの時間 (1 時間未満 / 3 時間未満 / それ以上) で, 打診する・しないが決まりどおり
- 打診の一言はトークに 1 通だけ・やりとりの回数は増えない・相手が動かした記録が付く・受ける / 断る / 別の日時が通る
- 複数人の打診が同じ時刻に固まらない・相手が寝ている / 仕事中には来ない (約束が近ければすぐ)・開き直しても二重に送らない
- 空きがどこにも無ければ, 相手からの取りやめ (あなたへの悪影響なし)

    python tools/test_relife.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, lifetype, store  # noqa: E402
from core import appoint as appoint_mod  # noqa: E402


def next_sat():
    """来週の土曜 13:10 (流す日時に左右されないように, 曜日と時刻を決める)."""
    d = datetime.now().replace(hour=13, minute=10, second=0, microsecond=0) + timedelta(days=7)
    while d.weekday() != 5:
        d += timedelta(days=1)
    return d


def person(app, cid, tid, **life):
    c = {"id": cid, "name": cid, "age": 26, "persona": "", "persona_id": "teinei", "pos": "1girl", "neg": "", "outfit_default": "",
         "outfit_outing": "coat", "clothes": [], "prompt_history": []}
    c["life"] = dict(lifetype.decide(c, {"chrono": 0}, type_id=tid), chrono=0, **life)
    c["schedule"] = lifetype.build(c)
    c["schedule_old"] = []                  # 移行で予定を作り直した人
    c["default_activity"] = lifetype.default_activity()
    app.save_character(c)
    app.place_character(cid, "contact")
    return app.chars[cid]


def main():
    random.seed(3)
    assert lifetype.FIXED is None
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        A = app.appoint
        T0 = next_sat()
        T = T0.timestamp()
        at = lambda days, h, m=0: (T0.replace(hour=h, minute=m) + timedelta(days=days)).timestamp()      # noqa: E731
        off = person(app, "c_office", "office")                       # 平日 9〜18 時ごろが仕事. 土日は休み
        svc = person(app, "c_service", "service", slot=0, workplace="mall", off=["tue", "wed"])     # 土日 10:00〜18:30 が仕事
        ngt = person(app, "c_night", "night", off=["tue", "wed"])     # 金曜の晩から働いて, 土曜の昼は寝ている
        full = person(app, "c_full", "office")
        full["schedule"] = [{"days": "all", "from": "00:00", "to": "24:00", "activity": "work", "label": "出張中", "away": True}]
        store.save_character(full)                                    # 空きがどこにも無い人
        kept = person(app, "c_kept", "office")
        kept.pop("schedule_old")                                      # 予定を作り直していない人 (手書きなど)
        store.save_character(kept)
        assert lifetype.remade_here(app) == ["c_office", "c_service", "c_night", "c_full"]
        do = A.dos_at("c_office", "park")[0]["id"]
        mon10, sun14 = at(2, 10), at(1, 14)
        assert A.clash(off, mon10) and not A.clash(off, sun14)
        assert A.clash(svc, at(0, 15)) and A.clash(ngt, at(2, 23)) and A.clash(full, sun14)
        assert not app.scene_at(svc, app.state("c_service"), T0)["asleep"] and app.scene_at(svc, app.state("c_service"), T0)["away"]
        assert app.scene_at(ngt, app.state("c_night"), T0)["asleep"]

        def ap(aid, cid, t, status, **kw):
            x = {"id": aid, "cid": cid, "t": t, "place": "park", "do": do, "by": "me", "status": status, "made": T - 600, "rounds": 1}
            if status in ("set", "waiting"):
                x["plan"] = {"noshow": False, "late": 0, "cancel_checked": True, "move": False, "go": 0}
            x.update(kw)
            return x
        fav = dict(place="home:c_office", do=appoint_mod.FAVOR_DO, by="her", label="大掃除", fkind="clean")
        ps = app.life.player_state()
        ps["appoints"] = [
            ap("set_clash", "c_office", mon10, "set"), ap("set_free", "c_office", sun14, "set"),
            ap("off_clash", "c_office", at(3, 10), "offered", by="her"), ap("off_free", "c_office", at(8, 14), "offered", by="her"),
            ap("ask_clash", "c_office", at(4, 10), "asked"), ap("wait_clash", "c_office", T - 300, "waiting"),
            ap("fav_clash", "c_office", at(5, 10), "set", favor="f1", **fav), ap("fav_free", "c_office", at(7, 14), "set", favor="f2", **fav),
            ap("fav_fixed", "c_office", at(6, 10), "set", favor="f3", fixed=True, **fav),
            ap("fav_plants", "c_office", at(9, 10), "set", favor="f4", fixed=True, plants=True, until=at(11, 10), **fav),
            ap("care", "c_office", at(10, 10), "set", care=True, by="her"), ap("help", "c_office", at(11, 10), "set", help="clean"),
            ap("svc_soon", "c_service", at(0, 15), "set"),            # 1 時間 50 分後: すぐ打診
            ap("svc_near", "c_service", at(0, 13, 50), "set"),        # 40 分後: 打診しない (そのまま来る)
            ap("svc_far", "c_service", at(1, 12), "set"),
            ap("ngt_far", "c_night", at(2, 23), "set"),
            ap("full_far", "c_full", sun14, "set"),
            ap("kept_clash", "c_kept", mon10, "set"),
        ]
        ps.pop("life_v", None)
        app.life.save_player()
        before = {cid: dict(app.state(cid)["params"]) for cid in app.chars}
        ids = lifetype.world_step(app, T)
        assert ids == ["c_office", "c_service", "c_night", "c_full"], ids
        marked = {x["id"]: x["relife"] for x in A.all() if x.get("relife")}
        want = {"set_clash", "off_clash", "fav_clash", "svc_soon", "svc_far", "ngt_far", "full_far"}
        assert set(marked) == want, sorted(set(marked) ^ want)
        # 3 時間を切っている約束はすぐ. ほかは人ごとに 5〜90 分, 同じ人は同じ時刻, 別の人とは固まらない
        assert marked["svc_soon"] == T
        due = {"c_office": marked["set_clash"], "c_service": marked["svc_far"], "c_night": marked["ngt_far"], "c_full": marked["full_far"]}
        assert marked["off_clash"] == marked["fav_clash"] == due["c_office"]
        assert all(T + 5 * 60 <= d <= T + 90 * 60 for d in due.values()), due
        ds = sorted(due.values())
        assert all(b - a >= 60 for a, b in zip(ds, ds[1:])), "複数人の打診が同じ時刻に固まらない: %s" % [(d - T) / 60 for d in ds]
        print("mark: OK", {k: round((v - T) / 60) for k, v in sorted(marked.items())})

        def moves(cid):
            return [i for i in app.chat.load(cid)["items"] if i.get("kind") in ("appoint_move_mine", "favor_resched")]
        # すぐ: 約束が近い人 (仕事中でも) だけ届く. 近すぎる約束は, そのまま
        app.presence.rec()["appoint_check"] = T
        out = A.live(T + 60)
        x = A.get("svc_soon")
        assert x["status"] == "offered" and x["by"] == "her" and x["rounds"] == 1 and "relife" not in x, x
        assert x["t"] > T + 3600
        assert len(moves("c_service")) == 1 and any("c_service" in o for o in out), out
        assert app.state("c_service").get("her_moved") == T + 60
        assert A.get("svc_near")["status"] == "set" and A.get("svc_near")["t"] == at(0, 13, 50)
        assert not moves("c_office") and not moves("c_night") and A.get("svc_far").get("relife")
        # 90 分後: 起きていて手が空いている人から届く. 仕事中の人・寝ている人からは, まだ
        app.presence.rec()["appoint_check"] = T + 95 * 60
        A.live(T + 95 * 60)
        assert len(moves("c_office")) == 3, [i["text"] for i in moves("c_office")]
        for aid, t0 in (("set_clash", mon10), ("off_clash", at(3, 10)), ("fav_clash", at(5, 10))):
            x = A.get(aid)
            assert x["status"] == "offered" and x["by"] == "her" and x["t"] != t0 and x["rounds"] == 1 and "relife" not in x, x
            sc = app.scheduled_scene(off, datetime.fromtimestamp(x["t"]))
            assert not (sc["away"] or sc["busy"] or sc["asleep"]), "打診の日時は, 新しい予定で空いている"
        assert [i["kind"] for i in moves("c_office")].count("favor_resched") == 1
        assert app.state("c_office").get("her_moved") == T + 95 * 60
        for aid, t0, stt in (("set_free", sun14, "set"), ("off_free", at(8, 14), "offered"), ("ask_clash", at(4, 10), "asked"),
                             ("fav_free", at(7, 14), "set"), ("fav_fixed", at(6, 10), "set"), ("fav_plants", at(9, 10), "set"),
                             ("care", at(10, 10), "set"), ("help", at(11, 10), "set"), ("kept_clash", mon10, "set")):
            x = A.get(aid)
            assert x["status"] == stt and x["t"] == t0 and "relife" not in x, (aid, x)
        assert A.get("svc_far").get("relife") and A.get("ngt_far").get("relife"), "仕事中・寝ている相手からは, まだ来ない"
        assert not moves("c_night") and len(moves("c_service")) == 1
        assert A.get("full_far")["status"] == "set" and A.get("full_far").get("relife"), "ずっと手が離せない相手からは, まだ来ない"
        # 夕方: 仕事の終わった人・起きた人から届く
        t2 = at(0, 19, 30)
        app.presence.rec()["appoint_check"] = t2
        A.live(t2)
        assert A.get("svc_far")["status"] == "offered" and A.get("ngt_far")["status"] == "offered"
        assert len(moves("c_service")) == 2 and len(moves("c_night")) == 1
        sc = app.scheduled_scene(ngt, datetime.fromtimestamp(A.get("ngt_far")["t"]))
        assert not (sc["away"] or sc["busy"] or sc["asleep"]), "夜勤の人にも, 空いている日時が見つかる"
        # もう一度進めても, 開き直しても, 二重に送らない
        counts = {cid: len(moves(cid)) for cid in app.chars}
        app.presence.rec()["appoint_check"] = t2 + 300
        A.live(t2 + 300)
        assert lifetype.world_step(app, t2 + 300) is None
        app.life.save_player()
        app2 = engine.App()
        app2.save_settings({"auto_generate": False})
        assert [x["id"] for x in app2.appoint.all() if x.get("relife")] == ["full_far"], "印は保存されていて, 済んだものには残らない"
        app2.presence.rec()["appoint_check"] = t2 + 600
        app2.appoint.live(t2 + 600)
        assert {cid: len([i for i in app2.chat.load(cid)["items"] if i.get("kind") in ("appoint_move_mine", "favor_resched")])
                for cid in app2.chars} == counts
        print("offers: OK", counts)
        # 受ける / 断る / 別の日時は, いつもの流れ
        A2 = app2.appoint
        r = A2.answer("set_clash", True, now=t2 + 700)
        assert r["status"] == "set" and A2.get("set_clash").get("plan") is not None
        assert A2.answer("off_clash", False, now=t2 + 700)["status"] == "refused"
        assert A2.answer("fav_clash", True, now=t2 + 700)["status"] == "set"
        x = A2.get("svc_far")
        A2.counter("svc_far", x["t"] + 86400, now=t2 + 700)
        assert A2.get("svc_far")["status"] == "asked" and A2.get("svc_far")["rounds"] == 2
        # 相手が動かしたあとは, こちらが動かすときに「お互いさま」が効く
        s_with, _, _ = A2.change_score(app2.chars["c_office"], app2.state("c_office"), A2.get("set_clash"), t2 + 800)
        st0 = dict(app2.state("c_office"), her_moved=0)
        s_without, _, _ = A2.change_score(app2.chars["c_office"], st0, A2.get("set_clash"), t2 + 800)
        assert s_with < s_without, (s_with, s_without)
        print("answer / counter / mutual: OK")
        # 空きがどこにも無い人 (ずっと手が離せない): 約束の 3 時間前を切ったところで, 相手からの取りやめ. あなたへの悪影響はない
        t3 = at(1, 11, 30)
        app2.presence.rec()["appoint_check"] = t3
        A2.live(t3)
        x = A2.get("full_far")
        assert x["status"] == "cancelled" and "relife" not in x, x
        items = app2.chat.load("c_full")["items"]
        assert len([i for i in items if i.get("kind") == "appoint_cancel"]) == 1
        pf = app2.state("c_full")["params"]
        assert all(pf[k] >= before["c_full"][k] for k in ("affection", "trust")), "取りやめで, 仲は下がらない"
        assert app2.state("c_full").get("her_moved") == t3
        print("no slot -> cancelled by her: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp + "_backup", ignore_errors=True)


if __name__ == "__main__":
    main()
