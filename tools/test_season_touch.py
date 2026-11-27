"""寒い日の寄り添い・相合傘・季節の話題と気遣い (S59. core/season.py の feel / day_feel・core/presence.py の feel_weight・
core/engine.py の act (ふれあいの反応)・core/topics.py の from_weather・core/manners.py の take_care).

体感の境目 (外 / 家の中 × 冷暖房 × 寒がり・暑がり)・条件式の値・働きかけの候補と重み・ふれあいの断られやすさ (総当たり)・
話題が極端な日だけ一度足される・気遣いのメッセージの 3 通りと印.

    python tools/test_season_touch.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from core import cond, engine, outdoor, presence, season, store  # noqa: E402

REAL_TEMP = season.temp
REAL_RANGE = season.day_range
REAL_WX = outdoor.weather


def fixed(t, hi=None):
    season.temp = lambda dt, wx=None: float(t)
    h = float(t if hi is None else hi)
    season.day_range = lambda d: (h - 6, h, None)


def real():
    season.temp = REAL_TEMP
    season.day_range = REAL_RANGE
    outdoor.weather = REAL_WX


def with_mode(app, cid, mode):
    app.bonds.wrec()["with"] = {"cid": cid, "mode": mode, "t": time.time()} if mode else None


def main():
    random.seed(59)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        cid = app.settings["active_character"]
        char = app.chars[cid]
        st = app.state(cid)
        tr = app.traits(char)
        flat = {"id": "flat"}            # 揺れのない人 (寒がり・暑がり 1) で境目を見る
        app_flat = type("A", (), {"traits": lambda self, c: {}})()

        # ---- 1. 体感の境目: 外はふつうの人で 8℃ 以下 cold・30℃ 以上 hot. 家の中は室温しだい (冷暖房を使えば出ない)
        dt = datetime(2026, 1, 15, 14)
        jit = season._jitter
        season._jitter = lambda c, k: 1.0          # キャラごとの揺れを止めて境目を見る
        res = {}
        for t in range(-5, 41):
            fixed(t)
            f = season.feel(app_flat, flat, dt)
            res[t] = f
            assert f == ("cold" if t <= 7 else "hot" if t >= 30 else ""), (t, f)
            for m in ("eco", "strong"):
                assert season.feel(app_flat, flat, dt, inside=m) == "", (t, m)      # 冷暖房の幅は過ごしやすい幅の中
            r = season.room(t, "off")[0]
            fi = season.feel(app_flat, flat, dt, inside="off")
            assert fi == ("cold" if r <= season.ROOM_OK[0] - season.FEEL_ROOM else "hot" if r >= season.ROOM_OK[1] + season.FEEL_ROOM else ""), (t, r, fi)
        # 寒がりは早く寒く, 暑がりは早く暑く
        cold_p = type("A", (), {"traits": lambda self, c: {"cold": 1.6, "heat": 1.6}})()
        fixed(8.5)
        assert season.feel(cold_p, flat, dt) == "cold" and season.feel(app_flat, flat, dt) == ""
        fixed(29)
        assert season.feel(cold_p, flat, dt) == "hot" and season.feel(app_flat, flat, dt) == ""
        season._jitter = jit
        print("体感の境目: OK (外 8℃ 以下 / 30℃ 以上. 家は冷暖房を使えば出ない)")

        # ---- 2. その日の極端さ: 最高気温で決まる. 一年のうち数週間ほど
        real()
        for t in (31.9, 32.0, 8.0, 8.1, 20):
            season.day_range = lambda d, t=t: (t - 6, t, None)
            assert season.day_feel(date(2026, 1, 1)) == ("hot" if t >= 32 else "cold" if t <= 8 else ""), t
        real()
        cnt = {"hot": 0, "cold": 0, "": 0}
        for i in range(365):
            cnt[season.day_feel(date(2026, 1, 1) + timedelta(days=i))] += 1
        assert 3 <= cnt["hot"] <= 40 and 10 <= cnt["cold"] <= 60, cnt
        print("その日の極端さ: OK 2026 年", cnt)

        # ---- 3. 条件式の値: そばにいるときだけ feel. 離れていれば "" (day_feel・wx はいつも)
        app.bonds.set_stage(cid, "visit")
        app.home.set_ac("off")
        fixed(-2, hi=3)
        with_mode(app, cid, "guest")
        now_dt = datetime.now()
        ctx = app.context(char, st, now_dt)
        assert ctx["feel"] == "cold" and ctx["day_feel"] == "cold" and ctx["wx"] in outdoor.WEATHER, (ctx["feel"], ctx["day_feel"])
        app.home.set_ac("eco")
        assert app.context(char, st, now_dt)["feel"] == "", "暖房の効いた家では寒くない"
        with_mode(app, cid, "meet")            # 外で会っている: 外の気温
        assert app.context(char, st, now_dt)["feel"] == "cold"
        with_mode(app, cid, None)
        app.bonds.set_stage(cid, "friend") if "friend" in getattr(app.bonds, "STAGES", ()) else None
        c2 = app.context(char, st, now_dt)
        if c2["apart"]:
            assert c2["feel"] == "" and c2["day_feel"] == "cold"
        fixed(20)
        app.bonds.set_stage(cid, "visit")
        with_mode(app, cid, "meet")
        assert app.context(char, st, now_dt)["feel"] == ""
        print("条件式の値: OK")

        # ---- 4. 働きかけ: 新しい 4 つは条件どおりにだけ候補. date_cold / date_hot は体感で. 重みはふれあいだけ動く
        A = {a["id"]: a for a in app.approaches}
        for k in ("huddle", "umbrella", "msg_cold", "msg_hot"):
            assert k in A, k
        base = {"affection": 60, "asleep": False, "outing": False, "feel": "", "wx": "sunny", "day_feel": ""}
        for feel in ("cold", "hot", ""):
            for wx in ("sunny", "rain", "snow"):
                for day in ("cold", "hot", ""):
                    for outing in (True, False):
                        for aff in (30, 45, 60):
                            c = dict(base, feel=feel, wx=wx, day_feel=day, outing=outing, affection=aff)
                            assert cond.check(A["huddle"]["when"], c) == (feel == "cold" and aff >= 50)
                            assert cond.check(A["umbrella"]["when"], c) == (outing and wx == "rain" and aff >= 40)
                            assert cond.check(A["msg_cold"]["when"], c) == (day == "cold" and aff >= 40)
                            assert cond.check(A["msg_hot"]["when"], c) == (day == "hot" and aff >= 40)
                            assert cond.check(A["date_cold"]["when"], c) == (outing and feel == "cold")
                            assert cond.check(A["date_hot"]["when"], c) == (outing and feel == "hot")
        assert A["msg_cold"]["apart"] and A["msg_hot"]["apart"] and not A["huddle"].get("apart") and not A["umbrella"].get("apart")
        touch = [a for a in app.approaches if (a.get("accept") or {}).get("skill") == "touch"
                 or (a.get("accept") or {}).get("action") in presence.TOUCH_ACTS]
        other = [a for a in app.approaches if a not in touch]
        assert {"lean", "huddle", "umbrella", "date_hands", "lonely"} <= {a["id"] for a in touch}
        for a in touch:
            assert presence.feel_weight(a, {"feel": "cold"}) == 1.5 and presence.feel_weight(a, {"feel": "hot"}) == 0.4
            assert presence.feel_weight(a, {"feel": ""}) == 1.0
        for a in other:
            assert all(presence.feel_weight(a, {"feel": f}) == 1.0 for f in ("cold", "hot", ""))
        for k in ("msg_cold", "msg_hot"):            # 返事の選択肢: 気づかい返すのがいちばん合う
            from core import msgreply
            assert [o["id"] for o in msgreply.options(k)] == ["worry", "cheerful", "tease", "curt"]
            assert max(msgreply.FIT[k], key=msgreply.FIT[k].get) == "worry"
        print("働きかけ: OK (候補の総当たり・重み)")

        # ---- 5. 実際に抽せん: 寒い家では huddle が出る. 暑い日はふれあいの働きかけが減る
        def draw(n, feel):
            got = {}
            for _ in range(n):
                st["approach"] = None
                st["ap_last"] = {}
                c = app.context(char, st, now_dt)
                c.update(feel=feel, affection=70, loneliness=50, boredom=50, asleep=False, busy=False)
                a = app.presence.fire(char, st, time.time(), c)
                if a:
                    k = st["approach"]["id"] if st.get("approach") else None
                    got[k] = got.get(k, 0) + 1
            st["approach"] = None
            return got
        app.set_params({"affection": 70, "loneliness": 50, "boredom": 20, "mood": 50}, cid)
        with_mode(app, cid, "guest")
        g_cold, g_hot = draw(200, "cold"), draw(200, "hot")
        tc = lambda g: sum(v for k, v in g.items() if k in {a["id"] for a in touch})
        assert g_cold.get("huddle", 0) > 0 and g_hot.get("huddle", 0) == 0, (g_cold, g_hot)
        assert tc(g_cold) > tc(g_hot) and sum(g_hot.values()) - tc(g_hot) > 0, (g_cold, g_hot)
        print("抽せん: OK ふれあいの働きかけ 寒い %d / 暑い %d (200 回)" % (tc(g_cold), tc(g_hot)))

        orig_ctx = app.context             # 時刻によらず, 起きていて手が空いている形で確かめる
        app.context = lambda *a, **k: dict(orig_ctx(*a, **k), free=True, asleep=False, busy=False, away=False)
        # ---- 6. あなたからのふれあい: 断られる境目が, 寒い日は下がり暑い日は上がる (ハグ: 好感度 35 未満で断る)
        def hug_refused(aff, mode, t, n=300):
            fixed(t)
            app.home.set_ac(mode)
            bad = 0
            for _ in range(n):
                st["cooldowns"] = {}
                app.set_params({"affection": aff, "mood": 60, "stress": 20}, cid)
                ctx = app.context(char, st, datetime.now())
                if not ctx.get("free"):
                    return None
                a = next(x for x in app.actions if x["id"] == "hug")
                sn = season.sense(app, char)
                rctx = dict(ctx)
                if ctx["feel"]:
                    rctx["affection"] = ctx["affection"] + engine.TOUCH_FEEL_AFF * (sn["cold"] if ctx["feel"] == "cold" else -sn["heat"])
                r = app.pick_reaction(a, rctx)
                bad += 1 if r.get("override") else 0
            return bad
        rows = []
        for aff in (28, 33, 38, 43):
            row = (aff, hug_refused(aff, "off", -3), hug_refused(aff, "eco", 20), hug_refused(aff, "off", 39))
            rows.append(row)
            if None in row:
                continue
            _, cold_b, norm_b, hot_b = row
            assert cold_b <= norm_b + 30 and norm_b <= hot_b + 30, row       # くじの揺れの分だけ緩める
        r33 = rows[1]
        if None not in r33:
            assert r33[1] < r33[2], "好感度 33 は寒い日だけ受け入れられやすい: %s" % (r33,)
        r38 = rows[2]
        if None not in r38:
            assert r38[3] > r38[2], "好感度 38 は暑い日に断られやすい: %s" % (r38,)
        print("ふれあいの断られやすさ: OK (好感度, 寒い, ふつう, 暑い) 300 回のうち断った数", rows)

        # 実際に act でハグ: 暑い日は効き目が弱く, ときどき地の文が添わる / 寒い日は強い
        def hug_heart(mode, t, n=12):
            fixed(t)
            app.home.set_ac(mode)
            tot, notes = 0.0, 0
            for _ in range(n):
                with_mode(app, cid, "guest")
                st["cooldowns"] = {}
                app.set_params({"affection": 80, "heart": 10, "mood": 50, "shyness": 10, "loneliness": 70}, cid)
                if not app.context(char, st, datetime.now()).get("free"):
                    return None, 0
                e = app.act("hug", cid)["entry"]
                tot += (e.get("deltas") or {}).get("loneliness", 0)
                notes += "暑いからか" in (e.get("text") or "")
            return tot / n, notes
        orig_tick = app.tick                # 時間を進めない (相手の予定で帰ってしまわないように)
        app.tick = lambda *a, **k: None
        hc, nc = hug_heart("off", -3)
        hn, nn = hug_heart("eco", 20)
        hh, nh = hug_heart("off", 39)
        if hc is not None:
            assert hc < hn < hh, (hc, hn, hh)       # 寂しさの下がり方 (負の値ほど効いている)
            assert nc == 0 and nn == 0 and nh > 0, (nc, nn, nh)
            print("ハグの効き目: OK 寂しさの動き 寒い %.1f / ふつう %.1f / 暑い %.1f. 暑い日の地の文 %d/12" % (hc, hn, hh, nh))
        else:
            print("ハグの効き目: いまの時刻は相手の手が空いていないので略")
        app.home.set_ac("eco")
        app.context = orig_ctx
        app.tick = orig_tick

        # ---- 7. 話題: 極端な日だけ, 日の変わり目に一度足される. 二度足さない. 暑がりほど乗る
        T = app.topics
        n0 = len(T.all())
        fixed(20, hi=20)
        assert T.from_weather(time.time()) is None and len(T.all()) == n0
        fixed(35, hi=35)
        x = T.from_weather(time.time())
        assert x and x["text"] == "猛暑の日の話" and x["src"] == "weather" and x["ref"] == "hot"
        T.from_weather(time.time() + 60)
        assert len(T.all()) == n0 + 1, "同じ日には二度足さない"
        fixed(0, hi=3)
        y = T.from_weather(time.time())
        assert y and y["text"] == "冷え込んだ日の話" and len(T.all()) == n0 + 2
        _, v = T.judge(char, st, x, time.time())
        assert v.get("shared") is True
        # tick_world の日の変わり目で足される
        L = app.life
        fixed(35, hi=35)
        for k in [k for k in T.all() if k["src"] == "weather"]:
            T.all().remove(k)
        t0 = datetime.combine(date.today(), datetime.min.time()).timestamp() - 1800
        L.player_state()["last_tick"] = t0
        L.tick_world(now=t0 + 3600)
        assert sum(1 for k in T.all() if k["src"] == "weather") == 1
        print("話題: OK (極端な日だけ・一日一度・日の変わり目)")

        # ---- 8. あなたからの気遣い: 極端な日は届く (印も動く), ふつうの日は的外れ, 同じ日の 2 通目は流される
        M = app.manners
        st.pop("take_care_day", None)
        fixed(20, hi=20)
        k, eff, _ = M.reply(char, st, "take_care", time.time(), {"_sent": time.time()}, {})
        assert k == "take_care_odd" and eff == {}
        fixed(0, hi=4)
        rv0 = app.regard.get(char, st)
        k, eff, _ = M.reply(char, st, "take_care", time.time(), {"_sent": time.time()}, {})
        assert k == "take_care" and eff["mood"] > 0 and eff["loneliness"] < 0
        rv1 = app.regard.get(char, st)
        assert rv1 != rv0, (rv0, rv1)
        k, eff, _ = M.reply(char, st, "take_care", time.time(), {"_sent": time.time()}, {})
        assert k == "take_care_again" and eff == {}
        # 送る欄に出る・ふつうに送れる
        from core import chat as chat_mod
        assert "take_care" in chat_mod.KINDS and any("take_care" in g[3] for g in chat_mod.GROUPS)
        assert all(("chat." + s) in chat_mod.LINES for s in ("take_care", "take_care_odd", "take_care_again"))
        print("あなたからの気遣い: OK (極端な日 / ふつうの日 / 同じ日の 2 通目)")
        print("ALL OK")
    finally:
        real()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
