"""季節と気温のつながり (S39. core/season.py の「つながり」): 行き先の季節の向き不向き (誘いの乗り気・相手が誘う所・そこでの機嫌)・
移動と力仕事の疲れ (猛暑・極寒)・雪の遅れ・熱帯夜 (あなたの眠りと体力の戻り・相手の寝起き)・冬の日の短さで沈みやすい性格・
贈り物の冷たいもの / 温かいもの / 旬 (条件の割合と, 実際に渡したときの反応)・洗濯の乾き・株の売れ行き.
どれも確率と重みだけで, 必ずそうなる道は無いことも確かめる.

    python tools/test_season_link.py
"""
import collections
import os
import random
import shutil
import statistics
import sys
import tempfile
import time
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from core import engine, market, rhythm, season, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)          # 時刻は昼 (寝ていない). 季節の効きは下で本物に戻す
for _k in ("place_ask", "place_fun", "winter_blue", "gift_season"):
    setattr(season, _k, getattr(season, _k + "_real"))
REAL_TEMP = season.temp_real


def fixed(t):
    season.temp = lambda dt, wx=None: float(t)
    season.day_range.cache_clear()


def real():
    season.temp = REAL_TEMP
    season.day_range.cache_clear()


def main():
    random.seed(39)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        mk = lambda pid, cid=None: {"id": cid or "t_" + pid, "persona_id": pid, "name": "x"}      # noqa: E731
        SUM, WIN, SPR, AUT = datetime(2026, 8, 1, 12), datetime(2026, 1, 15, 12), datetime(2026, 4, 5, 12), datetime(2026, 10, 25, 12)

        # ---- 1. 行き先の季節の向き不向き: 海は夏・星は冬・公園は春秋・山は秋. 屋内と遊園地は季節によらない
        f = season.place_fit
        assert f("beach", SUM) > 0 > f("beach", WIN) and f("hill", WIN) > 0 and f("park", SPR) > 0 < f("park", AUT) \
            and f("mountain", AUT) > 0 > f("mountain", WIN) and f("amusement", SUM) == f("cafe", WIN) == 0
        assert all(-1 <= v <= 1 for p in season.PLACE_SEASON.values() for v in p.values())
        assert all((app.places.get(pid) or {}).get("outdoor") for pid in season.PLACE_SEASON), "表は屋外の行き先だけ"
        ch = mk("seijitsu")
        fixed(22)                         # 同じ気温で比べる (季節の向き不向きだけの差)
        A = app.appoint
        season.out_factor = season.out_factor_real
        b_s, b_w = A.out_factor(ch, "beach", SUM), A.out_factor(ch, "beach", WIN)
        assert b_s > b_w and 0.8 < b_w and b_s < 1.4, (b_s, b_w)
        assert A.out_factor(ch, "cafe", WIN) == 1.0, "屋内は 1"
        # 相手が誘う行き先: 夏は海が, 冬は少し減る (くじなので必ずではない)
        opts = [("beach", {}), ("park", {})]
        st = app.state("hina")
        cnt = {}
        for dt in (SUM, WIN):
            c = collections.Counter(A.pick(ch, st, opts, dt)[0] for _ in range(3000))
            cnt[dt.month] = c["beach"] / 3000.0
        assert cnt[8] > cnt[1] and 0.2 < cnt[1] and cnt[8] < 0.8, cnt
        # そこでの機嫌: 夏の海は少し楽しい / 冬の海は少し下がる. くじなので揺れる・大きくない
        fs = [season.place_fun("beach", SUM) for _ in range(500)]
        fw = [season.place_fun("beach", WIN) for _ in range(500)]
        assert statistics.mean(fs) > 0.5 and statistics.mean(fw) < 0 and len(set(fs)) > 5 and max(fs) <= 3.0 and min(fw) >= -1.5
        assert season.place_fun("amusement", SUM) == 0
        # 行き先のお出かけ (海) で, そこの向き不向きが機嫌に入る (着いてから効くときも, 効き目に含まれる)
        called = []
        pf = season.place_fun
        season.place_fun = lambda pid, dt, rnd=None: called.append(pid) or 0.0
        app.set_params({"mood": 50, "affection": 70, "trust": 70, "energy": 80, "sleepiness": 0}, "hina")
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": 9e12}
        app.act("beach", "hina")
        season.place_fun = pf
        assert called == ["beach"], called
        print("行き先の季節: OK 海の乗り気 夏 %.2f / 冬 %.2f, 相手が海を選ぶ 夏 %.0f%% / 冬 %.0f%%" % (b_s, b_w, cnt[8] * 100, cnt[1] * 100))

        # ---- 2. 移動と力仕事: 猛暑・極寒で歩く・こぐ疲れが増える. 車・タクシーは変わらない. 雪は雨より遅い
        assert season.tire_mult(20) == season.tire_mult(28) == season.tire_mult(3) == 1.0
        assert season.tire_mult(35) > season.tire_mult(31) > 1 and season.tire_mult(-3) > 1 and season.tire_mult(60) == 1.6
        G = app.geo
        lg = {"how": "walk", "min": 30}
        fixed(20)
        w20 = G.body_cost(lg, "home", "park", time.time())[1]
        fixed(35)
        w35 = G.body_cost(lg, "home", "park", time.time())[1]
        c35 = G.body_cost({"how": "car", "min": 30}, "home", "park", time.time())[1]
        fixed(20)
        c20 = G.body_cost({"how": "car", "min": 30}, "home", "park", time.time())[1]
        assert w35 > w20 * 1.3 and c35 == c20, (w20, w35, c20, c35)
        legs = {"how": "transit", "min": 40, "legs": [{"kind": "walk", "t0": 0, "t1": 900}, {"kind": "ride", "t0": 900, "t1": 2400}]}
        fixed(-2)
        assert G.body_cost(legs, "a", "b")[1] > 2.5 * 0.25 * 1.1, "経路の歩く区間も"
        assert season.slow("walk", "snow") > season.slow("walk", "rain") > season.slow("walk", "sunny") == 1.0
        assert season.slow("bike", "snow") > season.slow("bike", "rain") > 1.0
        wx0 = G._weather
        mins = {}
        for wx in ("sunny", "rain", "snow"):
            G._weather = lambda t, wx=wx: wx
            mins[wx] = G.walk_min("home", "station")
        G._weather = wx0
        assert mins["snow"] > mins["rain"] > mins["sunny"], mins
        # 頼まれごとの力仕事 (引っ越し・荷物運び) は猛暑でこたえる. パソコンの設定は変わらない
        L = app.life
        ps = L.player_state()
        tired = {}
        for kind, tc in (("move", 20), ("move", 35), ("pc", 20), ("pc", 35)):
            fixed(tc)
            ps["stamina"] = 100
            fv = {"cid": "hina", "kind": kind, "h": 2.0, "tire": 20, "label": kind}
            app.earn.favor_done(fv, 2.0, time.time())
            tired[(kind, tc)] = 100 - ps["stamina"]
        assert tired[("move", 35)] > tired[("move", 20)] and tired[("pc", 35)] == tired[("pc", 20)], tired
        print("移動と力仕事: OK 歩く 30 分 20℃ %.2f / 35℃ %.2f, 徒歩 晴 %.0f / 雨 %.0f / 雪 %.0f 分" % (w20, w35, mins["sunny"], mins["rain"], mins["snow"]))

        # ---- 3. 熱帯夜: あなたの眠り (眠れた時間・体力の戻り)
        assert season.sleep_mult(24) == 1.0 and season.sleep_mult(28) < 1.0 and season.sleep_mult(40) == 0.7
        B = app.body
        rec = {}
        app.home.set_mode("off")            # 冷暖房を使わない家 (使っていれば寝苦しくない. S39. 下で確かめる. 同居相手の反応 S58 は通さない)
        for tc in (20, 29, "eco"):
            if tc == "eco":
                app.home.set_mode("eco")
                tc = 29.5
            fixed(tc)
            B.rec()["today"] = {}
            B.step(time.time(), 1.0, "sleep")
            ps["stamina"], ps["last_tick"] = 40.0, time.time() - 3600
            at0 = app.presence.at
            app.presence.at = lambda t: "sleep"
            L.tick_world(time.time())
            app.presence.at = at0
            rec[tc] = (B.rec()["today"]["slept"], ps["stamina"] - 40.0)
        assert rec[29][0] < rec[20][0] * 0.85 and 0 < rec[29][1] < rec[20][1], rec
        assert abs(rec[29.5][0] - rec[20][0]) < 1e-6 and abs(rec[29.5][1] - rec[20][1]) < 0.05, ("冷房を使っていれば寝苦しくない", rec)
        # 相手の寝起き: 熱帯夜の翌朝は早く目が覚めることがある (暑がりほど. 必ずではない)
        hot, weak = mk("genki", "h1"), mk("yareyare", "h2")      # 暑さに強い / 暑がり
        days = [date(2026, 7, 1) + timedelta(days=i) for i in range(200)]
        wk = {}
        for who in (hot, weak):
            for tc in (20, 29):
                fixed(tc)
                wk[(who["id"], tc)] = [rhythm.decide(app, who, {}, d, engine.day_match, use_state=False)["wake"] for d in days]
        for who in ("h1", "h2"):
            early = sum(1 for a, b in zip(wk[(who, 29)], wk[(who, 20)]) if a < b) / float(len(days))
            assert 0.15 < early < 0.95, (who, early)
        e1 = statistics.mean(wk[("h1", 20)]) - statistics.mean(wk[("h1", 29)])
        e2 = statistics.mean(wk[("h2", 20)]) - statistics.mean(wk[("h2", 29)])
        assert e2 > e1 > 0, (e1, e2)
        print("熱帯夜: OK 眠れた時間 20℃ %.2f・29℃ %.2f / 体力の戻り 20℃ %.1f・29℃ %.1f, 相手の早起き 平均 %.0f 分 (暑さに強い) / %.0f 分 (暑がり)"
              % (rec[20][0], rec[29][0], rec[20][1], rec[29][1], e1, e2))

        # ---- 4. 冬の日の短さ: 気分の沈みやすい性格 (hurt.mood > 1) だけ, 機嫌の落ち着く先が下がる. 夏はどの性格も 0
        wb = lambda pid, dt: season.winter_blue(app, mk(pid), dt)      # noqa: E731
        assert wb("hikutsu", datetime(2026, 12, 21)) < wb("tsundere", datetime(2026, 12, 21)) < wb("hikutsu", datetime(2026, 11, 1)) < 0
        assert wb("genki", datetime(2026, 12, 21)) == 0 and wb("hikutsu", datetime(2026, 7, 1)) == 0
        assert wb("hikutsu", datetime(2026, 12, 21)) > -6, "大きく沈ませない"
        # 毎時の変化に入っている: 同じ冬至の日・同じ値から, 沈みがあると機嫌が下がる方へ (日付のほかの違いを混ぜない)
        ch2 = app.char("hina")
        ch2["persona_id"] = "hikutsu"
        st2 = app.state("hina")
        got = {}
        dt = datetime(2026, 12, 21, 12)
        for on in (False, True):
            season.winter_blue = season.winter_blue_real if on else (lambda app_, char, dt_: 0.0)
            st2["params"]["mood"] = 50.0
            random.seed(7)
            app._step(ch2, st2, dt, 6.0)
            got[on] = st2["params"]["mood"]
        season.winter_blue = season.winter_blue_real
        assert -6 < got[True] - got[False] < -0.5, got
        print("冬の日の短さ: OK 冬至 卑屈 %.1f / ツンデレ %.1f / 元気 0, 冬至に 6 時間で機嫌 %+.1f (沈みなしと比べて)"
              % (wb("hikutsu", datetime(2026, 12, 21)), wb("tsundere", datetime(2026, 12, 21)), got[True] - got[False]))

        # ---- 5. 贈り物: 暑い日の冷たいもの・寒い日の温かいもの・旬の果物. 合っても口に出るのはくじ
        def share(iid, tc, pid="seijitsu", n=2000):
            fixed(tc)
            c = collections.Counter(season.gift_season(app, mk(pid), iid, SUM) for _ in range(n))
            return {k: v / float(n) for k, v in c.items()}
        s_ice_hot, s_ice_cool = share("ice_cream", 32), share("ice_cream", 18)
        assert 0.3 < s_ice_hot.get("cool", 0) < 0.75 and not s_ice_cool.get("cool"), (s_ice_hot, s_ice_cool)
        assert share("ice_cream", 32, "yareyare").get("cool", 0) > share("ice_cream", 32, "genki").get("cool", 0), "暑がりほど"
        assert 0.3 < share("tea_leaves", 3).get("warm", 0) < 0.75 and not share("tea_leaves", 25).get("warm")
        assert not share("ice_cream", 2).get("cool") and set(share("cookies", 33)) == {""}, "季節に関係ない品は空"
        assert 0.25 < share("fruit", 20).get("shun", 0) < 0.6
        assert season.fruit_name(SUM) == "すいか" and season.fruit_name(WIN) == "みかん"
        # 実際に渡す: 反応に季節のセリフが出る (好きなものと同じ重さで, 出ないこともある). 果物は旬の名前で
        char = app.char("hina")
        char["persona_id"] = "seijitsu"          # 甘いもの好きでない (好きの反応と分けて数える)
        app.set_params({"mood": 60, "affection": 70, "trust": 70, "energy": 80, "sleepiness": 0}, "hina")
        ps["money"] = 10 ** 6
        texts = collections.Counter()
        fixed(33)
        for i in range(30):
            ps["items"] = {"ice_cream": 1}
            st["cooldowns"], st["gifts"] = {}, []
            e = app.give_item("ice_cream", "hina")["entry"]
            texts["cool" if "冷た" in e["text"] or "暑" in e["text"] else "other"] += 1     # 性格別のセリフは「暑かったので」とも言う
            assert app.items.count("ice_cream") == 0
        assert 5 < texts["cool"] < 26, texts
        season.season_real = season.season
        season.season = lambda dt: "winter"
        fixed(15)
        ps["items"] = {"fruit": 1}
        st["cooldowns"], st["gifts"] = {}, []
        names = set()
        for i in range(12):
            ps["items"] = {"fruit": 1}
            st["cooldowns"], st["gifts"] = {}, []
            names.add("みかん" in app.give_item("fruit", "hina")["entry"]["text"])
        season.season = season.season_real
        assert True in names, "旬の果物は旬の名前で"
        act = next(a for a in app.actions if a["id"] == "gift")
        keys = {r.get("key") for r in act["reactions"]}
        assert {"season_cool", "season_warm", "season_shun"} <= keys
        print("贈り物: OK 32℃ のアイスで冷たいもの %.0f%% (暑がり %.0f%% / 暑さに強い %.0f%%), 実際に 30 回渡して %d 回"
              % (s_ice_hot["cool"] * 100, share("ice_cream", 32, "yareyare")["cool"] * 100,
                 share("ice_cream", 32, "genki").get("cool", 0) * 100, texts["cool"]))

        # ---- 6. 洗濯: 最高 8℃ 以下の日は乾きにくい (雨の部屋干しはそのまま). ほかの家事は変わらない
        H = app.home
        out = {}
        for tc in (20, 5):
            fixed(tc)
            H.wet = lambda now=None: False
            r = H.rec()
            for k in ("mess", "dishes", "laundry", "trash"):
                r[k] = 50.0
            _, _, notes = H.clean(40.0, ["laundry", "mess"], time.time())
            out[tc] = (r["laundry"], r["mess"], notes)
        assert out[5][0] > out[20][0] and out[5][1] == out[20][1] and "寒くて乾きにくい" in out[5][2] and not out[20][2], out
        print("洗濯: OK", out[5][2])

        # ---- 7. 株: 猛暑日はコンビニ・家電, 冷え込む日はドラッグストア・カフェが少し上向きの目標. 遊園地は下向き
        fixed(33)
        c = market.conditions(datetime(2026, 8, 3, 12))
        assert c.get("hot") and not c.get("cold"), c
        fixed(0)
        c2 = market.conditions(datetime(2026, 1, 20, 12))
        assert c2.get("cold") and not c2.get("hot"), c2
        M = app.market
        tg = lambda sec, dt: M.sector_target({"sector": sec}, dt)       # noqa: E731
        fixed(33)
        hot_c, hot_a = tg("convenience", datetime(2026, 8, 3, 12)), tg("amusement", datetime(2026, 8, 3, 12))
        fixed(27)
        warm_c, warm_a = tg("convenience", datetime(2026, 8, 3, 12)), tg("amusement", datetime(2026, 8, 3, 12))
        assert hot_c > warm_c and hot_a < warm_a, (hot_c, warm_c, hot_a, warm_a)
        print("株: OK 猛暑日のコンビニ %+.3f (ふつうの夏 %+.3f)" % (hot_c, warm_c))
        real()

        # ---- 8. 本物の気温で: 1 年のうち熱帯夜・洗濯が乾きにくい日・猛暑日 / 冷え込む日の数が極端でない
        d0 = date(2025, 1, 1)
        nights = sum(1 for i in range(365) if season.hot_night(d0 + timedelta(days=i)) >= 25)
        dry = sum(1 for i in range(365) if season.dry_mult(datetime.combine(d0 + timedelta(days=i), datetime.min.time()))[1])
        hotd = sum(1 for i in range(365) if season.day_conds(d0 + timedelta(days=i)).get("hot"))
        cold = sum(1 for i in range(365) if season.day_conds(d0 + timedelta(days=i)).get("cold"))
        assert 5 <= nights <= 70 and 3 <= dry <= 60 and 10 <= hotd <= 80 and 10 <= cold <= 90, (nights, dry, hotd, cold)
        print("1 年の数: OK 熱帯夜 %d / 乾きにくい日 %d / 猛暑日 (株) %d / 冷え込む日 %d" % (nights, dry, hotd, cold))
        print("ALL OK")
    finally:
        real()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
