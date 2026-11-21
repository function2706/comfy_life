"""家での約束ごとは, 二人で出かけても続く (一時データ, 画像生成なし).
以前は, 相手の家 / あなたの家から二人で出かけると「一緒にいる記録」を作り直していて, その家での約束ごとが消えていた:
泊まるのを受けてもらってから一緒に外へ出て戻ると泊まる話が無かったことになり, 頼まれた手伝いは出かけた途端に「手伝わずに帰った」になっていた.
- 泊まる約束: 出かけている間も続く. 出かけた先の時間が終わる /「帰る」で, 別れずに一緒にその家へ戻る (帰りの移動も組む). 戻れば泊まっている
- 泊まる約束をしたまま出かけている間は, その家に「寄る」話は出さない (画面と act が一致). もう一方の家へ寄るのはできて, 泊まる話はそこで終わる
- 「今日はもう聞きました」も持ち越す (出かけて戻れば聞き直せる, にはしない)
- 何度出かけても続く. 朝になったら, 外で別れる
- 泊まる約束が無ければ, これまでどおり外で別れる
- 頼まれた手伝い (始める前): 出かけても罰にならない. 戻れば手伝える. 戻らずに別れたら, そこで一度だけ「手伝わずに帰った」
- 招いた相手の手伝い (始める前)・看病の記録も, 戻れば戻る

    python tools/test_stay_outing.py
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
_parting.FIXED = None
from testclock import fix_noon  # noqa: E402
from test_home_outing import at_home_date, go_cafe, arrive  # noqa: E402

fix_noon(engine)
G.INSTANT = False


def expire(app, cid, st):
    """出かけた先の時間を終わらせて, 時間を進める."""
    for k in ("until", "arr", "leave", "start"):
        if k in (st.get("override") or {}):
            st["override"][k] -= 6 * 3600
    for tr in (st.get("override") or {}).get("trips") or []:
        for k in ("t0", "arr"):
            tr[k] -= 6 * 3600
    app.tick(cid)


def main():
    random.seed(7)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("約束ごとと外出")
        cid = app.settings["active_character"]
        char = app.char(cid)
        B, S = app.bonds, app.stay
        B.set_stage(cid, "visit")
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        app.life.player_state()["money"] = 200000
        home = "home:" + cid
        other = {"visit": "bring_home", "guest": "go_her_home"}
        same = {"visit": "go_her_home", "guest": "bring_home"}

        def staying_date(mode):
            st = at_home_date(app, cid, mode)
            w = B.with_rec()
            w["stay_asked"] = True
            S._begin(w, char, time.time())
            assert S.staying(cid)
            return st

        for mode in ("visit", "guest"):
            origin = home if mode == "visit" else "home:me"
            # ---- 1. 泊まる約束をして出かける: 外で会っている間も約束は続き, 帰りはその家へ
            st = staying_date(mode)
            until0 = B.with_rec()["until"]
            st, _ = go_cafe(app, cid)
            assert B.mode(cid) == "meet" and B.stay_back(cid) == mode, B.with_rec()
            trips = st["override"].get("trips") or []
            assert trips and trips[-1]["dir"] == "home" and trips[-1]["to"] == origin, (mode, trips)
            arrive(app, cid, st)
            av = app.person_view(cid)["available"]
            assert not av[same[mode]]["ok"] and av[other[mode]]["ok"], (mode, av[same[mode]], av[other[mode]])
            try:
                app.act(same[mode], cid)
                raise AssertionError("泊まる家に「寄る」話ができた")
            except ValueError:
                pass
            # ---- 2. 時間が終わったら, 別れずに一緒に戻る. 戻れば泊まっている
            expire(app, cid, st)
            w = B.with_rec()
            assert B.mode(cid) == mode and S.staying(cid) and w.get("stay_asked") and w["until"] >= until0, (mode, w)
            assert app.geo.where() == origin, (mode, app.geo.where())
            try:
                S.ask(cid)
                raise AssertionError("戻ったら泊まる話を聞き直せた")
            except ValueError:
                pass
            print("%s で泊まる約束 → カフェ → 時間切れ: OK | 一緒に戻って泊まっている (帰りは %s へ)" % (mode, trips[-1]["to"]))

            # ---- 3. 出かけた先で「帰る」: 別れではなく一緒に戻る. 二度目の外出でも続く
            for n in (1, 2):
                st, _ = go_cafe(app, cid)
                arrive(app, cid, st)
                st["cooldowns"] = {}
                app.act("go_home", cid)
                assert B.mode(cid) == mode and S.staying(cid), (mode, n, B.with_rec())
            print("%s で泊まる約束 → カフェ →「帰る」(2 回): OK | 一緒に戻って泊まっている" % mode)

            # ---- 4. 出かけた先から, もう一方の家へ寄る: 泊まる話はそこで終わる (ほかの家に移った)
            st = staying_date(mode)
            st, _ = go_cafe(app, cid)
            arrive(app, cid, st)
            st["cooldowns"] = {}
            app.act(other[mode], cid, opts={"quarrel_ok": True})
            if (st.get("override") or {}).get("home_trip"):
                arrive(app, cid, st)
            w = B.with_rec() or {}
            assert not w.get("stay") and not w.get("base"), (mode, w)
            print("%s で泊まる約束 → カフェ → もう一方の家へ: OK | 泊まる話は終わり (%s)" % (mode, B.mode(cid)))

            # ---- 5. 朝になったら, 外で別れる
            st = staying_date(mode)
            st, _ = go_cafe(app, cid)
            arrive(app, cid, st)
            B.base(cid)["night_end"] = time.time() - 1
            expire(app, cid, st)
            assert not B.with_rec(), (mode, B.with_rec())
            print("%s で泊まる約束 → カフェ → 朝を過ぎて時間切れ: OK | 別れた" % mode)

            # ---- 6. 泊まる約束が無ければ, これまでどおり別れる
            st = at_home_date(app, cid, mode)
            st, _ = go_cafe(app, cid)
            assert not B.stay_back(cid) and not [t for t in st["override"].get("trips") or [] if t["dir"] == "home"]
            arrive(app, cid, st)
            expire(app, cid, st)
            assert not B.with_rec(), (mode, B.with_rec())
            print("%s (泊まる約束なし) → カフェ → 時間切れ: OK | 別れた" % mode)

        # ---- 7. 相手の家で頼まれた手伝い (始める前): 出かけても罰にならず, 戻れば手伝える
        def favor_visit():
            at_home_date(app, cid, "visit")
            B.end(go_home=False)
            f = {"id": "fx%d" % random.randint(0, 10 ** 6), "cid": cid, "kind": "clean", "label": "掃除の手伝い", "h": 1.0,
                 "tire": 5, "t": time.time(), "until": time.time() + 3 * 86400}
            app.earn.favors().append(f)
            app.athome.favor_arrive(cid, f, time.time())
            assert app.athome.favor_pending(cid)
            return app.state(cid), f

        def abandoned():
            return [it for it in app.chat.load(cid)["items"] if "手伝わずに帰って" in it.get("text", "")]

        n0 = len(abandoned())
        st, f = favor_visit()
        trust0 = st["params"]["trust"]
        st, _ = go_cafe(app, cid)
        assert len(abandoned()) == n0 and app.earn.favor(f["id"]), "出かけただけで手伝わずに帰ったことになった"
        arrive(app, cid, st)
        st["cooldowns"] = {}
        app.act("go_her_home", cid, opts={"quarrel_ok": True})
        if (st.get("override") or {}).get("home_trip"):
            arrive(app, cid, st)
        if B.mode(cid) == "visit":
            assert app.athome.favor_pending(cid) and app.athome.favor_pending(cid)["id"] == f["id"], B.with_rec()
            print("頼まれた手伝い → カフェ → 相手の家へ戻る: OK | 手伝いはまだできる (信頼 %.0f → %.0f)" % (trust0, st["params"]["trust"]))
        else:
            print("頼まれた手伝い → カフェ → 相手の家へ: 断られた (確かめはスキップ)")
        # 戻らずに別れた: 一度だけ「手伝わずに帰った」
        st, f = favor_visit()
        n0 = len(abandoned())
        st, _ = go_cafe(app, cid)
        arrive(app, cid, st)
        expire(app, cid, st)
        assert not B.with_rec() and len(abandoned()) == n0 + 1 and not app.earn.favor(f["id"]), (B.with_rec(), len(abandoned()) - n0)
        print("頼まれた手伝い → カフェ → 時間切れで別れた: OK | 手伝わずに帰った (一度だけ)")

        # ---- 8. 招いた相手の手伝い (始める前)・看病の記録: 戻れば戻る
        for key, val, mode in (("help", {"kind": "clean", "label": "掃除の手伝い", "h": 1.0}, "guest"),
                               ("care", {"want": ["pocari"], "given": ["pocari"], "nursed": True}, "visit")):
            st = staying_date(mode)
            B.with_rec()[key] = dict(val)
            st, _ = go_cafe(app, cid)
            arrive(app, cid, st)
            expire(app, cid, st)
            w = B.with_rec()
            assert B.mode(cid) == mode and w.get(key) == val, (key, w)
            print("%s の記録 (%s) → カフェ → 戻る: OK | 残っている" % (key, mode))
        # ---- 9. 遡及 (一度だけ): 以前の版で, 受けてもらった泊まる約束が外出で消えていた → 起動時に戻す. 二度目はしない
        from core import stay as stay_mod
        for mode, enter, ask in (("visit", "go_her_home", "泊まっていい？"), ("guest", "bring_home", "泊まっていく？")):
            app.life.player_state().setdefault("fix_comp", {}).pop("stay_lost", None)
            st = at_home_date(app, cid, mode)
            now = time.time()
            app.note_entry(char, st, now - 7200, enter, "", "", "（家に）")
            app.note_entry(char, st, now - 3600, "_stay_ask", ask, "🌙", "いいよ", {"loneliness": -6, "mood": 2})
            st, _ = go_cafe(app, cid)
            B.with_rec().pop("base", None)       # 以前の版: 出かけたら消えていた
            assert not B.stay_back(cid)
            real = stay_mod.Stay.morning
            stay_mod.Stay.morning = lambda self, t: t + 12 * 3600      # (テストの時刻は昼: 受けたのが今夜扱いになるように)
            try:
                assert app.stay.restore_lost(now) == cid and B.stay_back(cid) == mode, B.with_rec()
                B.with_rec().pop("base", None)
                assert app.stay.restore_lost(now) is None and not B.stay_back(cid), "二度戻した"
            finally:
                stay_mod.Stay.morning = real
            print("遡及 (%s): OK | 消えていた泊まる約束を一度だけ戻した" % mode)
        # 断られた記録だけなら戻さない
        app.life.player_state()["fix_comp"].pop("stay_lost", None)
        st = at_home_date(app, cid, "visit")
        app.note_entry(char, st, time.time() - 60, "_stay_ask", "泊まっていい？", "🌙", "ちょっと", {"mood": -1})
        assert app.stay.restore_lost() is None and not app.stay.staying(cid)
        print("遡及 (断られていた): OK | 戻さない")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
