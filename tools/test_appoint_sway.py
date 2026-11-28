"""約束の相手のブレ (A41・S34. core/appoint.py・core/parting.py・core/ring.py の tell).
- 一月分の試算: ふつうの性格で, 遅刻・早く着く・変えたい・直前の取りやめ・切り上げの起きやすさが目安に収まる. 続けて起こしにくい
- 遅れる連絡は理由で時期と文が変わる (電車・寝坊・支度). 電話で来て出なければメッセージで届く
- 早く着く: 二人とも着いていれば, 時刻を待たずに会える. 「着いちゃった」の知らせ
- 直前の取りやめ: 理由の文で届く / 連絡なしならすっぽかし / 代わりの日は誘いとして返せる
- 相手からの変えたい: 受ければ変わる. 断れば もとのまま来る・渋々・やめる のどれか (もとの約束に戻る)
- 相手からの切り上げ: 会うたびに一度決まり, 時刻に言い出す. 「うん」で別れる (引き止めない) / 引き止めると 応じる・それでも帰る
(一時データ)

    python tools/test_appoint_sway.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, parting, store  # noqa: E402
from core.appoint import HER_LATE_KEY  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
APPT = {"appointment": "test"}


def main():
    random.seed(34)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("ブレ")
        A, C = app.appoint, app.chat
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        app.ring.why_not = lambda *a, **k: None

        def reset(**params):
            st.pop("msg_pending", None)
            st["her_moves"], st["cuts"] = [], []
            st.pop("her_moved", None)
            app.set_params(dict({"affection": 60, "mood": 60, "trust": 60, "energy": 80, "health": 90, "stress": 20}, **params), cid)

        def make(t, place="cafe", do=None, **plan):
            for y in A.all():
                if y["status"] in ("set", "waiting", "offered"):
                    y["status"] = "declined"
            do = do or A.dos_at(cid, place)[0]["id"]
            x = {"id": "x%d" % random.randint(0, 1 << 30), "cid": cid, "t": t, "place": place, "do": do, "by": "me",
                 "status": "set", "made": t - 86400, "rounds": 0,
                 "plan": dict({"noshow": False, "late": 0, "cancel_checked": True, "go": 30}, **plan)}
            A.all().append(x)
            A.save()
            return x

        def last(kind=None):
            its = [i for i in C.load(cid)["items"] if i.get("who") == "her" or i.get("from") == "her" or kind]
            its = [i for i in C.load(cid)["items"] if (kind is None or i.get("kind") == kind)]
            return its[-1] if its else None

        # ---- 1. 一月分の試算 (ふつうの性格・ふつうの日)
        reset()
        now = time.time()
        N = 2000
        late = early = chg = 0
        whys = {}
        for i in range(N):
            x = {"t": now + 3 * 86400 + (i % 8) * 3600, "place": "cafe", "made": now}
            p = A._plan(char, st, x)
            late += p["late"] >= 10
            early += bool(p.get("early"))
            chg += "chg_at" in p
            whys[p.get("late_why")] = whys.get(p.get("late_why"), 0) + 1
        drop = A.drop_chance(char, st, make(now + 4 * 3600), now)[0]
        cut = app.parting.cut_chance(char, st, now)
        print("一月分の試算 (%d 件): 10 分以上の遅れ %.0f%% / 早く着く %.0f%% / 変えたい %.1f%% / 直前の取りやめ %.1f%% / 切り上げ %.1f%% | 理由 %s"
              % (N, 100.0 * late / N, 100.0 * early / N, 100.0 * chg / N, 100 * drop, 100 * cut, whys))
        assert 0.05 <= late / N <= 0.3 and 0.02 <= early / N <= 0.3 and chg / N <= 0.08, (late, early, chg)
        assert drop <= 0.04 and cut <= 0.06, (drop, cut)
        reset(mood=25, stress=80, energy=25, health=40)
        bad_drop, bad_cut = A.drop_chance(char, st, make(now + 4 * 3600), now)[0], app.parting.cut_chance(char, st, now)
        st["her_moves"], st["cuts"] = [now - 86400, now - 2 * 86400], [now - 86400, now - 2 * 86400]
        again_drop, again_cut = A.drop_chance(char, st, make(now + 4 * 3600), now)[0], app.parting.cut_chance(char, st, now)
        assert bad_drop > drop and bad_cut > cut and again_drop < bad_drop / 3 and again_cut < bad_cut / 3
        print("調子が悪いと上がる・続けて起こしにくい: OK | 取りやめ %.1f%%→%.1f%% / 切り上げ %.1f%%→%.1f%%"
              % (100 * bad_drop, 100 * again_drop, 100 * bad_cut, 100 * again_cut))

        # ---- 2. 遅れる連絡: 理由で時期と文が変わる
        reset()
        orig_p = engine.appoint_mod.TELL_PHONE if hasattr(engine, "appoint_mod") else None
        import core.appoint as AM
        AM.TELL_PHONE = 0.0
        for why in ("slow", "traffic", "oversleep"):
            t = time.time() + 3600
            x = make(t, late=30, late_why=why, tell_jit=0)
            st["params"]["affection"] = 90
            app.traits = (lambda f: (lambda c: dict(f(c), punctual=1.0)))(engine.App.traits.__get__(app))
            come, leave = A.her_eta(x)
            sends = {"slow": t - 30 * 60, "traffic": leave + 12 * 60, "oversleep": leave - 5 * 60}
            A._her_late_tell(x, char, st, sends[why] - 120)
            assert "told" not in x["plan"], (why, "早すぎる")
            rr = random.random
            random.random = lambda: 0.0           # 連絡するか (上限 95%) のくじは外さない. ここで見るのは時期と文
            try:
                r = A._her_late_tell(x, char, st, sends[why] + 1)
            finally:
                random.random = rr
            assert r and x["plan"]["told"], why
            it = [i for i in C.load(cid)["items"] if i.get("appoint") == x["id"] and i.get("kind") == "appoint_her_late"][-1]
            want = C.line(char, HER_LATE_KEY.get(why, "appoint_her_late"), {"min": str(x["plan"]["told_min"]), "place": app.places.label("cafe")})
            assert it["text"] == want, (why, it["text"])
            print("遅れる連絡 (%s): OK | %s" % (why, it["text"]))
        app.traits = engine.App.traits.__get__(app)

        # 電話で来て, 出なければメッセージで
        AM.TELL_PHONE = 9.0
        app.presence.at = lambda t: "here"
        x = make(time.time() + 3600, late=30, late_why="slow", tell_jit=0)
        n0 = len(C.load(cid)["items"])
        A._tell(char, st, x, "appoint_her_late", {"min": "30", "place": "カフェ"}, time.time(), kind="appoint_her_late")
        r = app.ring.rec()
        assert r and r.get("tell") and not [i for i in C.load(cid)["items"][n0:] if i.get("kind") == "appoint_her_late"]
        app.ring.tick(r["until"] + 1)
        assert any(i.get("kind") == "appoint_her_late" for i in C.load(cid)["items"][n0:]) and not app.ring.rec()
        print("電話の連絡に出ないと, メッセージで届く: OK")
        A._tell(char, st, x, "appoint_her_late", {"min": "30", "place": "カフェ"}, time.time(), kind="appoint_her_late")
        res = app.ring.answer(True)
        assert res.get("call") and "30分" in str(res["call"]), res
        app.phonetalk.hang_up() if hasattr(app.phonetalk, "hang_up") else app.presence.rec().pop(app.phonetalk.KEY, None)
        app.presence.rec().pop(app.phonetalk.KEY, None)
        print("電話に出れば, 最初のひとことが知らせ: OK")
        AM.TELL_PHONE = 0.0
        del app.presence.at

        # ---- 3. 早く着く: 二人とも着いていれば, 時刻を待たずに会える
        reset()
        t = time.time() + 20 * 60
        x = make(t, early=15, go=10)
        here = A.here
        A.here = lambda place, now=None: place == "cafe"
        out = []
        A._tick(x, time.time(), out)          # 着いた (まだ相手は来ていない)
        assert x["status"] == "set" and "arrived" in x
        A._tick(x, t - 10 * 60, out)          # 相手は 15 分前に着いている
        A.here = here
        assert x["status"] == "met", (x["status"], out)
        print("早く着いた相手と, 時刻前に会えた: OK |", out[-1][:40])
        if app.bonds.mode(cid):
            app.act("go_home")
        app.presence.back()
        st.pop("override", None)
        A.here = lambda place, now=None: False
        x = make(time.time() + 20 * 60, early=20, go=10)
        got = None
        for _ in range(30):
            x.get("plan", {}).pop("early_sent", None)
            got = A._her_notes(x, char, st, time.time())
            if got:
                break
        A.here = here
        assert got and last("appoint_her_early"), got
        print("着いちゃったの知らせ: OK |", last("appoint_her_early")["text"])

        # ---- 4. 直前の取りやめ
        reset()
        for why in ("work", "urgent", "family", "mood", "weather"):
            x = make(time.time() + 2 * 3600, drop={"why": why, "say": why, "at": time.time() - 1, "silent": False})
            A.live()
            assert x["status"] in ("cancelled", "offered"), (why, x["status"])
            assert last("appoint_drop_" + why), why
            if x["status"] == "offered":
                assert last("appoint_drop_alt") and x["by"] == "her"
        print("直前の取りやめ (理由ごとの文): OK |", last("appoint_drop_mood")["text"])
        x = make(time.time() + 2 * 3600, drop={"why": "mood", "say": "urgent", "at": time.time() - 1, "silent": True})
        A.live()
        assert x["status"] == "set" and x["plan"]["noshow"], "連絡なし = すっぽかし"
        x = make(time.time() + 4 * 3600, cancel_checked=False)
        st["params"]["health"] = 30
        cnt = 0
        for _ in range(60):
            x["plan"]["cancel_checked"] = False
            x["plan"].pop("drop", None)
            cnt += (A._drop_plan(x, char, st, time.time()) or {}).get("why") == "sick"
        assert 20 <= cnt <= 50, cnt
        print("連絡なしはすっぽかしに・体調は今までどおり: OK | 体調 %d / 60" % cnt)

        # ---- 5. 相手からの変えたい
        reset()
        res = {}
        for i in range(40):
            x = make(time.time() + 2 * 86400 + 3600 * (i % 3), chg_at=time.time() - 1)
            old = (x["t"], x["place"], x["do"])
            A.live()
            if x["status"] != "offered":
                continue
            assert x.get("her_chg") and (x["t"], x["place"], x["do"]) != old, x
            k = x["her_chg"]["kind"]
            assert any(i.get("kind") == "appoint_chg_" + k for i in C.load(cid)["items"] if i.get("appoint") == x["id"])
            if i % 2:
                A.answer(x["id"], True)
                assert x["status"] == "set" and "her_chg" not in x and (x["t"], x["place"], x["do"]) != old
                res["yes"] = res.get("yes", 0) + 1
            else:
                A.answer(x["id"], False)
                assert (x["t"], x["place"], x["do"]) == old and x["status"] in ("set", "cancelled"), x
                kk = [i for i in C.load(cid)["items"] if i.get("appoint") == x["id"]][-1]["kind"]
                assert kk in ("appoint_chg_keep", "appoint_chg_grudge", "appoint_chg_drop"), kk
                res[kk] = res.get(kk, 0) + 1
        assert res.get("yes") and len([k for k in res if k != "yes"]) >= 2, res
        print("相手からの変えたい (受ける / 断る): OK |", res, "|", last("appoint_chg_keep")["text"] if last("appoint_chg_keep") else "")

        # ---- 6. 相手からの切り上げ
        reset()
        parting.CUT_FIXED = 1.0
        app.life.player_state()["money"] = 1000000
        got = {}
        for i in range(30):
            if app.bonds.mode(cid):
                app.act("go_home")
            app.presence.back()
            st.pop("override", None)
            st["approach"] = None
            st.pop("part_her", None)
            reset(energy=30 if i % 2 else 80)
            app.act("cafe", opts=APPT)
            assert app.bonds.mode(cid) == "meet"
            now = time.time()
            app.parting.cut_live(char, st, now)          # 会ったときに決まる
            at = st["cut"]["at"]
            assert app.parting.cut_live(char, st, at - 60) is None
            e = app.parting.cut_live(char, st, at + 1)
            assert e and st["approach"]["id"].startswith("leave_"), st.get("approach")
            if i % 3 == 0:
                r = app.answer_approach("accept", cid)
                assert not app.bonds.mode(cid), "うんで別れる"
                got["accept"] = got.get("accept", 0) + 1
            else:
                r = app.answer_approach("later", cid)
                k = "stay" if app.bonds.mode(cid) else "go"
                got[k] = got.get(k, 0) + 1
            got[st["cut"]["why"]] = got.get(st["cut"]["why"], 0) + 1
        parting.CUT_FIXED = None
        assert got.get("accept") and got.get("stay") and got.get("go") and got.get("tired"), got
        print("相手からの切り上げ: OK |", got)
        # ひと休みの直後は言い出さない
        if app.bonds.mode(cid):
            app.act("go_home")
        app.presence.back()
        st.pop("override", None)
        st["approach"] = None
        parting.CUT_FIXED = 1.0
        app.act("cafe", opts=APPT)
        app.parting.cut_live(char, st, time.time())
        at = st["cut"]["at"]
        st["override"]["rests"] = [at - 600]
        assert app.parting.cut_live(char, st, at + 1) is None and st["cut"]["at"] > at
        parting.CUT_FIXED = None
        print("ひと休みの直後は切り上げを延ばす: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
