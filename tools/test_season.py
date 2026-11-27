"""季節と気温 (S38. core/season.py): 一年の気温の並び・季節の表が 1 つ・服の暖かさ・気温 × 暑がり寒がり × 本人の選ぶ服・
アウターを羽織る割合・着せ替えの寒い断り・外出の気分 (効きすぎていない)・誘いの返事・体調の内訳.
気温は本物を使う (testclock の fix_noon は気温を 20℃ に固定するので使わない. 必要な所だけ気温を差し替える).

    python tools/test_season.py
"""
import collections
import os
import random
import shutil
import statistics
import sys
import tempfile
import time
import uuid
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from core import engine, market, outdoor, places as places_mod, season, store, wardrobe as W_mod  # noqa: E402

REAL_TEMP = season.temp


def fixed(t):
    season.temp = lambda dt, wx=None: float(t)
    season.day_range.cache_clear()


def real():
    season.temp = REAL_TEMP
    season.day_range.cache_clear()


def main():
    random.seed(38)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        W = app.wardrobe

        # ---- 1. 一年の気温: 月の平均が平年値に近い・極端すぎない・同じ日時は同じ値・雪の日は寒い
        mon, hi, lo = collections.defaultdict(list), [], []
        d0 = date(2025, 1, 1)
        for i in range(365 * 3):
            d = d0 + timedelta(days=i)
            ts = [season.temp(datetime(d.year, d.month, d.day, h)) for h in range(0, 24, 2)]
            mon[d.month].append(statistics.mean(ts))
            hi.append(max(ts))
            lo.append(min(ts))
        for m in range(1, 13):
            assert abs(statistics.mean(mon[m]) - season.NORMAL[m - 1]) < 1.5, (m, statistics.mean(mon[m]))
        assert max(hi) < 39 and min(lo) > -9, (max(hi), min(lo))
        hot35 = sum(1 for x in hi if x >= 35) / 3.0
        hot30 = sum(1 for x in hi if x >= 30) / 3.0
        frost = sum(1 for x in lo if x < 0) / 3.0
        assert 0 < hot35 < 12 and 15 < hot30 < 70 and 3 < frost < 50, (hot35, hot30, frost)
        dt = datetime(2026, 8, 3, 14, 20)
        assert season.temp(dt) == season.temp(dt) and season.temp(dt) != season.temp(dt + timedelta(days=1)) \
            and season.temp(dt) > season.temp(dt.replace(hour=5)), "同じ日時は同じ値・昼は朝より暖かい"
        snow = []
        for i in range(365 * 3):
            d = d0 + timedelta(days=i)
            for h in (8, 15, 21):
                x = datetime(d.year, d.month, d.day, h)
                if outdoor.weather(x)["id"] == "snow":
                    snow.append(season.temp(x))
        assert snow and max(snow) <= season.SNOW_MAX + 0.5, ("雪は寒い日だけ", len(snow), max(snow or [0]))
        print("気温: OK 猛暑日 %.1f / 真夏日 %.1f / 冬日 %.1f 日・年, 雪 %d 回 (最高 %.1f℃)" % (hot35, hot30, frost, len(snow), max(snow)))

        # ---- 2. 季節の表は 1 つ (ほかの所が同じ答え)
        for m in range(1, 13):
            x = datetime(2026, m, 10, 12)
            s = season.season(x)
            assert engine.SEASONS[m] == outdoor.SEASONS[m] == s == W.season(x), m
            assert s in market.conditions(x), (m, market.conditions(x))
        assert app.outdoor.view()["season"] == season.season(datetime.now())
        wv = app.outdoor.view()["weather"]
        assert {"temp", "lo", "hi"} <= set(wv) and wv["lo"] <= wv["hi"], wv
        print("季節の表: OK")

        # ---- 3. 服の暖かさ: 夏服 < 冬服・重ね着は足し算
        g = lambda oid: season.warmth(W.get(oid))      # noqa: E731
        assert g("bikini") < g("offshoulder") < g("casual") < g("winter_coat"), [g(x) for x in ("bikini", "offshoulder", "casual", "winter_coat")]
        assert g("trench") < g("long_coat") <= g("down_jacket"), [g(x) for x in ("trench", "long_coat", "down_jacket")]
        assert g("p_tank") < g("p_tshirt") < g("p_knit") <= g("p_turtleneck"), [g(x) for x in ("p_tank", "p_tshirt", "p_knit", "p_turtleneck")]
        assert g("p_denim_shorts") <= g("p_miniskirt") < g("p_pleated") < g("p_long_skirt") < g("p_jeans")
        assert g("p_scarf") > 0 and g("p_necklace") == 0 and g("p_beanie") > g("p_cap")
        assert season.warmth(dict(W.get("p_tshirt"), warmth=2.5)) == 2.5, "書いてあればその値"
        raw = store.load(store.dpath("outfits.json"))
        assert not any("warmth" in o for o in raw), "服のデータは書き換えない"
        assert season.total([W.get("p_tshirt"), W.get("p_jeans")]) < season.total([W.get("p_knit"), W.get("p_jeans"), W.get("p_scarf")])
        assert season.total([W.get("p_lingerie")]) == 0
        print("服の暖かさ: OK")

        # ---- 4. 暑がり・寒がり (性格 × キャラごとの揺れ). 編集した性格に無い値は既定から
        mk = lambda pid, cid=None: {"id": cid or "t_" + pid, "persona_id": pid, "name": "x"}      # noqa: E731
        weak, strong = mk("byoujaku"), mk("genki")
        sw, ss = season.sense(app, weak), season.sense(app, strong)
        assert sw["cold"] > ss["cold"] and sw["heat"] > ss["heat"] and sw["outdoorsy"] < ss["outdoorsy"], (sw, ss)
        assert season.sense(app, mk("genki", "a")) != season.sense(app, mk("genki", "b")), "キャラごとの揺れ"
        assert all(0.5 < v < 1.8 for p in app.personas.values() for v in season.sense(app, mk(p["id"])).values())
        p = app.personas["genki"]
        store.save_persona(dict(p, traits={k: v for k, v in p["traits"].items() if k not in ("heat", "cold", "outdoorsy")}))
        assert store.load_personas()["genki"]["traits"]["outdoorsy"] == p["traits"]["outdoorsy"], "既定から補う"
        os.remove(store.dpath("personas", "genki.json"))
        assert season.gap(app, weak, 3.0, 5) < season.gap(app, strong, 3.0, 5), "寒がりは寒い側に"
        assert season.gap(app, weak, 2.0, 33) > season.gap(app, strong, 2.0, 33), "暑がりは暑い側に"
        assert season.gap(app, weak, 2.0, 0, inside=True) > season.gap(app, weak, 2.0, 0), "家の中はやわらぐ"
        assert season.fit_weight(0.5) == 1.0 and season.fit_weight(-4) >= 0.08 and season.fit_weight(3) < 0.2
        print("暑がり寒がり: OK", sw, ss)

        # ---- 5. 本人が選ぶ服: 同じ季節でも, 寒い日はニット・暑い日は T シャツ (必ずではない)
        ch = mk("seijitsu", "s38")
        ch["clothes"] = [{"id": "p_tshirt", "color": "white", "t": 0}, {"id": "p_knit", "color": "navy", "t": 0},
                         {"id": "p_jeans", "color": "black", "t": 0}, {"id": "p_sneakers", "color": "white", "t": 0}]
        st = {"params": {"affection": 50, "mood": 50}}
        share = {}
        for tc in (8, 27):
            fixed(tc)
            got = collections.Counter()
            for i in range(400):
                o = W.self_pick(ch, st, datetime(2026 + i // 50, 4, 1, 15) + timedelta(days=i % 50), outing=True)
                if o:
                    got["knit" if "knit" in o["pos"] else "t"] += 1
            share[tc] = got["knit"] / float(sum(got.values()))
        real()
        assert share[8] > 0.75 and share[27] < 0.3 and share[27] > 0.0, share
        print("本人が選ぶ服: OK ニットの割合 8℃ %.2f / 27℃ %.2f" % (share[8], share[27]))

        # ---- 6. アウター: 足りないほど羽織る (11 月. 秋冬のアウターを持っている)
        ch["clothes"] += [{"id": "trench", "t": 0}, {"id": "long_coat", "t": 0}]
        rate, which = {}, {}
        for tc in (3, 13, 24):
            fixed(tc)
            n, kinds = 0, collections.Counter()
            for i in range(300):
                o = W.outer_pick(ch, st, datetime(2026 + i // 29, 11, 1, 13) + timedelta(days=i % 29))
                if o:
                    n += 1
                    kinds[o["id"]] += 1
            rate[tc], which[tc] = n / 300.0, kinds
        real()
        assert rate[3] > 0.85 and 0.35 < rate[13] < 0.98 and rate[24] < 0.25 and rate[3] > rate[13] > rate[24], rate
        assert which[3]["long_coat"] > which[3]["trench"], which[3]
        fixed(26)
        assert W.temp_gap(ch, W.get("p_tshirt"), datetime(2026, 7, 1, 13), outing=True) > -1.2
        fixed(2)
        assert W.temp_gap(ch, W.get("p_tshirt"), datetime(2026, 1, 1, 13), outing=True) > \
            W.temp_gap(dict(ch, clothes=ch["clothes"][:4]), W.get("p_tshirt"), datetime(2026, 1, 1, 13), outing=True), "アウターで補える"
        real()
        print("アウター: OK", {k: round(v, 2) for k, v in rate.items()})

        # ---- 7. 着せ替えのお願い: 寒い日に薄着は断ることがある (寒がりほど). 暑い日・ふつうの服は断らない
        bik = W.get("bikini")
        fixed(1)
        cold = {c["id"]: sum(W.temp_feel(c, bik, datetime.now()) == "cold" for _ in range(400)) / 400.0 for c in (weak, strong)}
        assert 0.2 < cold[strong["id"]] < cold[weak["id"]] <= 0.85, cold
        assert not any(W.temp_feel(weak, W.get("fleece_lounge"), datetime.now()) for _ in range(50))
        fixed(30)
        assert not any(W.temp_feel(weak, bik, datetime.now()) for _ in range(50))
        real()
        dr = next(a for a in app.actions if a["id"] == "_dress")
        r = next(r for r in dr["reactions"] if r.get("when") == "dress_temp=cold")
        assert r.get("override") and r["priority"] >= 3
        print("着せ替えの寒い断り: OK", cold)

        # ---- 8. 外出の気分: ふつうの日はほぼ 1・猛暑日と雨で下がる・屋内の行き先は変わらない (効かせすぎない)
        norm = mk("seijitsu", "n38")
        f_ok, f_hot, f_rain = [], [], []
        for i in range(365 * 2):
            d = d0 + timedelta(days=i)
            x = datetime(d.year, d.month, d.day, 14)
            w = outdoor.weather(x)["id"]
            t = season.temp(x)
            f = season.out_factor(app, norm, x)
            if w in ("rain", "snow"):
                f_rain.append(f)
            elif t >= 34:
                f_hot.append(f)
            elif 8 <= t <= 28:
                f_ok.append(f)
        assert statistics.mean(f_ok) > 0.97 and statistics.mean(f_rain) < 0.85 and (not f_hot or max(f_hot) < 0.8), \
            (statistics.mean(f_ok), statistics.mean(f_rain), f_hot)
        allf = f_ok + f_hot + f_rain
        assert statistics.mean(allf) > 0.85, ("一年を通して効きすぎない", statistics.mean(allf))
        outs = [k for k, v in places_mod.PLACES.items() if v.get("outdoor")]
        ins = [k for k, v in places_mod.PLACES.items() if not v.get("outdoor")]
        fixed(37)
        x = datetime(2026, 8, 9, 14)
        assert app.appoint.out_factor(norm, ins[0], x) == 1.0 and app.appoint.out_factor(norm, outs[0], x) < 0.8
        assert season.out_factor(app, weak, x) < season.out_factor(app, strong, x), "暑がりほど下がる"
        assert season.out_why(app, norm, x) == "hot"
        fixed(-3)
        assert season.out_why(app, norm, x) == "cold"
        fixed(18)
        assert season.out_why(app, norm, x) is None
        real()
        print("外出の気分: OK ふつう %.2f / 雨 %.2f / 猛暑 %s" % (statistics.mean(f_ok), statistics.mean(f_rain),
                                                         round(statistics.mean(f_hot), 2) if f_hot else "-"))

        # ---- 9. 誘いへの返事: 猛暑日の屋外の行き先は受けにくく, 断るときは暑さを言う (必ずではない)
        cid = app.settings["active_character"]
        char, cst = app.chars[cid], app.state(cid)
        app.bonds.set_stage(cid, "contact")
        app.set_params({"affection": 60, "mood": 60, "trust": 60}, cid)
        park = next(k for k in places_mod.OUT_PLACES if (places_mod.PLACES.get(k) or {}).get("outdoor"))
        res = {}
        for tc in (20, 38):
            fixed(tc)
            keys = collections.Counter()
            for i in range(200):
                day = datetime.now().replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=3 + i % 20)
                x = {"id": uuid.uuid4().hex[:8], "cid": cid, "t": day.timestamp(), "place": park, "do": "walk", "by": "me",
                     "status": "asked", "made": time.time(), "rounds": 9}
                app.appoint.all().append(x)
                k = app.appoint.reply(char, cst, {"appoint": x["id"]}, time.time(), {})[0]
                keys[k] += 1
                app.appoint.all().remove(x)
            res[tc] = keys
        real()
        yes20, yes38 = res[20]["appoint_yes"], res[38]["appoint_yes"]
        assert yes38 < yes20 * 0.85 and yes38 > 0, (res[20], res[38])
        assert res[38]["appoint_no_hot"] > 0 and not res[20]["appoint_no_hot"], res
        for k in ("appoint_no_hot", "appoint_no_cold"):
            assert app.chat.line(char, k, {"when": "明日", "place": "公園"}), k
        print("誘いの返事: OK 受けた 20℃ %d / 38℃ %d (暑さで断る %d)" % (yes20, yes38, res[38]["appoint_no_hot"]))

        # ---- 10. 体調 (あなた): 寒い日・暑い外・寒い外が内訳に. 暑い外に長くいた日は体力の戻りが遅い
        B = app.body
        b = B.rec()
        t = time.mktime((2026, 7, 20, 23, 0, 0, 0, 0, -1))
        b["today"] = {"slept": 7.5}
        fixed(25)
        r0, why0 = B.risk(t)
        assert not ({"winter", "heat", "cold"} & set(why0)), why0
        fixed(1)
        _, why = B.risk(t)
        assert "winter" in why, why
        b["today"] = {"slept": 7.5, "hot": 3.0}
        fixed(25)
        r1, why = B.risk(t)
        assert why.get("heat", 0) > 0 and r1 > r0, why
        m_hot = B.stamina_mult()
        b["today"] = {"slept": 7.5, "cold": 4.0}
        assert B.risk(t)[1].get("cold", 0) > 0 and B.stamina_mult() > m_hot
        # 暑い外にいた時間を数える (一人の外出で屋外の行き先)
        b["today"] = {}
        pr = app.presence.rec()
        cur0 = app.outdoor.current
        app.outdoor.current = lambda now=None: {"kind": "out", "place": park}
        fixed(34)
        B.step(t, 1.0, "out")
        fixed(20)
        B.step(t, 1.0, "out")
        app.outdoor.current = lambda now=None: {"kind": "out", "place": ins[0]}
        fixed(34)
        B.step(t, 1.0, "out")
        app.outdoor.current = cur0
        real()
        assert abs(b["today"].get("hot", 0) - 1.3) < 1e-6 and "cold" not in b["today"], b["today"]
        del pr
        print("体調 (あなた): OK", why)

        # ---- 11. 相手の風邪: 寒い時期・寒がりほど起きやすく, 暑い時期は少ない. 寒暖差で上がる
        C = app.care
        jan = [C.temp_factor(norm, date(2026, 1, 1) + timedelta(days=i)) for i in range(28)]
        jul = [C.temp_factor(norm, date(2026, 7, 15) + timedelta(days=i)) for i in range(28)]
        assert statistics.mean(jan) > 1.5 and statistics.mean(jul) < 0.9, (statistics.mean(jan), statistics.mean(jul))
        assert statistics.mean(C.temp_factor(weak, date(2026, 1, 1) + timedelta(days=i)) for i in range(28)) > \
            statistics.mean(C.temp_factor(strong, date(2026, 1, 1) + timedelta(days=i)) for i in range(28))
        print("相手の風邪: OK 1 月 %.2f / 7 月 %.2f" % (statistics.mean(jan), statistics.mean(jul)))
        print("ALL OK")
    finally:
        real()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
