"""冷暖房と光熱費 (S39. core/season.py の room / ac_yen・core/home.py の使い方と電気代・core/life.py の tick_world).

室温の式・使い方 3 つ × 暑い / ふつう / 寒い日の動きと電気代・月はじめに一度だけ払う・家にいない間は動かない・
体力の戻り・眠り・体調の内訳・着せ替えの寒い断り・家に呼んだときの乗り気・家にいる相手の機嫌・開き直しで使い方が残る.

    python tools/test_aircon.py
"""
import collections
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from core import engine, places as places_mod, season, store  # noqa: E402

REAL_TEMP = season.temp


def fixed(t):
    season.temp = lambda dt, wx=None: float(t)
    season.day_range.cache_clear()


def real():
    season.temp = REAL_TEMP
    season.day_range.cache_clear()


def run(app, t0, t1):
    """t0 から t1 まで tick_world を進める (払った記録を返す)."""
    paid = []
    L = app.life
    orig = L.ledger
    L.ledger = lambda t, amount, cat, note="": (paid.append((cat, note, amount)), orig(t, amount, cat, note))
    try:
        L.player_state()["last_tick"] = t0
        L.tick_world(now=t1)
    finally:
        L.ledger = orig
    return paid


def main():
    random.seed(39)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        H, L = app.home, app.life
        L.player_state()["money"] = 10 ** 7

        # ---- 1. 室温の式: 冷暖房なしは外をやわらげた値. 使い方ごとに設定の幅へ寄せる. 幅の中では動かない
        assert abs(season.indoor(35) - 29.8) < 0.01 and abs(season.indoor(5) - 11.8) < 0.01
        for t in range(-5, 40):
            n = season.indoor(t)
            for m, sp in season.AC_MODES.items():
                r, run_ = season.room(t, m)
                if not sp:
                    assert run_ is None and abs(r - n) < 0.06
                    assert season.ac_yen(t, m) == 0
                    continue
                assert sp[0] - 1e-6 <= r <= sp[1] + 1e-6, (t, m, r)
                assert run_ == ("cool" if n > sp[1] else "heat" if n < sp[0] else None), (t, m, run_)
                assert (season.ac_yen(t, m) > 0) == bool(run_)
            if season.room(t, "eco")[1]:
                assert season.ac_yen(t, "strong") > season.ac_yen(t, "eco"), t       # しっかりほど高い
        print("室温の式: OK 35℃ → %.1f℃ (控えめ %s) / 5℃ → %.1f℃ (控えめ %s)" % (
            season.indoor(35), season.room(35, "eco"), season.indoor(5), season.room(5, "eco")))

        # ---- 2. 電気代の目安 (家に 1 日 14 時間 × 30 日): 夏の控えめは数千円・冬のしっかりは 1〜3 万円ほど
        def month(t, m):
            return 14 * 30 * season.ac_yen(t, m)
        assert 1500 < month(33, "eco") < 9000, month(33, "eco")
        assert 8000 < month(3, "strong") < 30000, month(3, "strong")
        assert month(24, "eco") == 0 and month(24, "strong") == 0 and month(20, "eco") == 0
        print("電気代の目安: OK 夏 33℃ 控えめ %d 円 / しっかり %d 円・冬 3℃ 控えめ %d 円 / しっかり %d 円" % (
            month(33, "eco"), month(33, "strong"), month(3, "eco"), month(3, "strong")))

        # ---- 3. 使い方: 既定は控えめ. 決まった名前だけ. 開き直しても残る
        assert H.ac_mode() == "eco"
        try:
            H.set_ac("max")
            raise AssertionError("知らない使い方を受けた")
        except ValueError:
            pass
        assert H.ac_mode() == "eco"
        H.set_ac("off")
        H.set_ac("off")              # 二つの画面から同じ操作が来ても同じ
        H._rec = None
        assert H.ac_mode() == "off"
        app2 = engine.App()
        assert app2.home.ac_mode() == "off", "開き直しても使い方が残る"
        v = H.view()["aircon"]
        assert v["mode"] == "off" and len(v["modes"]) == 3 and "room" in v and v["bill"] == 0
        print("使い方: OK", [m["label"] for m in v["modes"]])

        # ---- 4. 家にいる間だけ動き, 電気代がたまる. 月はじめに一度だけ払う (同じ時間を進め直しても二重にならない)
        fixed(34)
        t0 = datetime(2026, 7, 31, 18, 0).timestamp()
        t1 = datetime(2026, 8, 1, 2, 0).timestamp()
        H.set_ac("off")
        H.rec().pop("ac_bill", None)
        paid = run(app, t0, t1)
        assert not [p for p in paid if "冷暖房" in p[1]] and not (H.rec().get("ac_bill") or {}).get("yen"), "使わなければ 0"
        H.set_ac("eco")
        H.rec().pop("ac_bill", None)
        run(app, t0, datetime(2026, 7, 31, 23, 55).timestamp())
        b = H.rec()["ac_bill"]
        assert b["month"] == "2026-07" and 20 < b["yen"] < 120 and 5.5 < b["hours"] < 6.1, b
        paid = run(app, datetime(2026, 7, 31, 23, 55).timestamp(), t1)
        ac = [p for p in paid if "冷暖房" in p[1]]
        assert len(ac) == 1 and ac[0][0] == "fixed" and "7月" in ac[0][1] and -120 < ac[0][2] < -20, ac
        assert H.rec()["ac_bill"]["month"] == "2026-08" and H.rec()["ac_bill"]["carry"] == 0
        paid = run(app, t0, t1)         # 同じ月替わりを進め直す (止まっていた画面の追いつきなど)
        ac2 = [p for p in paid if "冷暖房" in p[1]]
        assert not ac2, ("二重に払わない (数えた時間・払った月は済んでいる)", ac2)
        # 外出・仕事中は動かない
        H.rec().pop("ac_bill", None)
        app.presence.declare("work", t0)
        run(app, t0, t0 + 4 * 3600)
        assert not (H.rec().get("ac_bill") or {}).get("yen"), "仕事中は動かない"
        app.presence.declare("none", t0)
        print("電気代: OK 7 月末の 6 時間 %d 円 → 8/1 に「%s」" % (-ac[0][2], ac[0][1]))

        # ---- 5. 体力の戻り (起きて家にいる): 暑い日に使わないと戻りにくい・眠り: 冷房が動いていれば熱帯夜でも寝苦しくない
        def recover(mode, tc, sleep=False):
            fixed(tc)
            H.set_ac(mode)
            app.presence.declare("sleep" if sleep else "none", t0 - 7200)
            ps = L.player_state()
            ps["stamina"] = 20.0
            app.body.rec()["satiety"] = 80.0
            run(app, t0, t0 + 3600)
            return ps["stamina"] - 20.0
        hot_off, hot_eco, mild = recover("off", 36), recover("eco", 36), recover("off", 22)
        assert hot_off < hot_eco * 0.95 and abs(hot_eco - mild) < 0.01, (hot_off, hot_eco, mild)
        s_off, s_eco = recover("off", 30, True), recover("eco", 30, True)
        assert s_off < s_eco * 0.85, (s_off, s_eco)
        assert season.sleep_mult(30, "eco") == 1.0 and season.sleep_mult(30) < 0.75 and season.sleep_mult(30, "off") < 0.75
        cold_off, cold_eco = recover("off", 0), recover("eco", 0)
        assert cold_off < cold_eco * 0.9, (cold_off, cold_eco)
        app.presence.declare("none", t0)
        print("体力の戻り: OK 36℃ 使わない %.1f / 控えめ %.1f・30℃ の夜 %.1f / %.1f・0℃ %.1f / %.1f" % (
            hot_off, hot_eco, s_off, s_eco, cold_off, cold_eco))

        # ---- 6. 体調: 暑すぎ・寒すぎの部屋に長くいた日だけ, 体調の崩しやすさに入る (寝ている間の寒さは数えない)
        for mode, tc, key, on in (("off", 36, "room_heat", True), ("eco", 36, "room_heat", False),
                                  ("off", -2, "room_cold", True), ("strong", -2, "room_cold", False)):
            fixed(tc)
            H.set_ac(mode)
            app.body.rec()["today"] = {}
            run(app, t0, t0 + 5 * 3600)
            why = app.body.risk(t0 + 5 * 3600)[1]
            assert (key in why) == on, (mode, tc, why)
        fixed(-2)
        H.set_ac("off")
        app.body.rec()["today"] = {}
        app.presence.declare("sleep", t0 - 60)
        run(app, t0, t0 + 5 * 3600)
        assert "room_cold" not in app.body.risk(t0 + 5 * 3600)[1], "寝ている間の寒さは数えない"
        app.presence.declare("none", t0)
        print("体調: OK")

        # ---- 7. 着せ替えの寒い断り: あなたの家にいる人は, 暖房を使っていないと断りやすい. 本人の家は控えめのまま
        cid = app.settings["active_character"]
        char = app.chars[cid]
        thin = next(o for o in app.wardrobe.owned(char) if season.warmth(o) < 1.5) if any(
            season.warmth(o) < 1.5 for o in app.wardrobe.owned(char)) else {"id": "x", "slot": "set", "kind": "swim"}
        fixed(2)
        app.bonds.set_stage(cid, "visit")
        app.bonds.wrec()["with"] = {"cid": cid, "mode": "guest", "t": t0}
        dt = datetime.now()
        res = {}
        for mode in ("off", "eco", "strong"):
            H.set_ac(mode)
            assert app.wardrobe.ac_of(char, dt) == mode
            res[mode] = sum(1 for _ in range(300) if app.wardrobe.temp_feel(char, thin, dt) == "cold")
        assert res["off"] > res["eco"] >= res["strong"], res
        app.bonds.wrec()["with"] = None
        H.set_ac("off")
        assert app.wardrobe.ac_of(char, dt) == season.AC_DEFAULT, "本人の家は控えめ"
        print("着せ替えの寒い断り: OK (300 回のうち)", res)

        # ---- 8. 家に呼んだときの乗り気: 過ごしにくい家は下がり, 暑い日に冷房の効いた家は少し上がる. ふつうの日は変わらない
        fixed(36)
        ask = {m: season.home_ask(app, char, dt, m) for m in season.AC_MODES}
        assert ask["off"] < 0.95 and ask["eco"] >= 1.0 and ask["strong"] >= 1.0 and ask["off"] >= 0.6, ask
        assert app.appoint.out_factor(char, places_mod.HOME_ME, dt) == season.home_ask(app, char, dt, H.ac_mode())
        fixed(21)
        assert all(abs(season.home_ask(app, char, dt, m) - 1.0) < 1e-9 for m in season.AC_MODES)
        fixed(-1)
        assert season.home_ask(app, char, dt, "off") < 0.95 <= season.home_ask(app, char, dt, "eco")
        print("家に呼ぶ乗り気: OK 36℃", ask)

        # ---- 9. 家にいる相手の機嫌の落ち着く先: 過ごしにくい室温ほど下がる (暑がりは暑い側でこたえる). 快適なら 0
        assert season.room_mood(app, char, 24.0) == 0 and season.room_mood(app, char, 22.0) == 0
        assert season.room_mood(app, char, 30.0) < 0 and season.room_mood(app, char, 11.0) < season.room_mood(app, char, 15.0) < 0
        hot_p = {"id": "t1", "persona_id": "yareyare"}
        cold_p = {"id": "t2", "persona_id": "genki"}
        if season.sense(app, hot_p)["heat"] > season.sense(app, cold_p)["heat"]:
            assert season.room_mood(app, hot_p, 30.0) < season.room_mood(app, cold_p, 30.0)
        # 招いている間の機嫌: 36℃ で使わないと, 控えめより下がる (同じ状態から 1 時間ずつ)
        import copy
        st = app.state(cid)
        app.bonds.wrec()["with"] = {"cid": cid, "mode": "guest", "t": t0}
        st["override"] = app._guest_override("invite", time.time())     # 招いている間の一時シーン (本物の流れと同じ. 予定の外出で外さない)
        app.set_params({"mood": 60}, cid)
        snap = copy.deepcopy(st)
        moods = {}
        fixed(36)
        for mode in ("off", "eco", "strong"):
            H.set_ac(mode)
            st.clear()
            st.update(copy.deepcopy(snap))
            random.seed(9)
            app._step(char, st, datetime.now(), 1.0)
            moods[mode] = st["params"]["mood"]
        app.bonds.wrec()["with"] = None
        st["override"] = None
        assert moods["off"] < moods["eco"] - 0.3 and abs(moods["eco"] - moods["strong"]) < 1e-6, moods
        print("家にいる相手の機嫌: OK 30℃ の部屋 %.1f・11℃ の部屋 %.1f / 36℃ で 1 時間 使わない %.2f・控えめ %.2f" % (
            season.room_mood(app, char, 30.0), season.room_mood(app, char, 11.0), moods["off"], moods["eco"]))

        real()
        print("ALL OK")
    finally:
        real()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
