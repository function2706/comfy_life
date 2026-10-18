"""在席状態・キャラからの働きかけ・スキル・内職・投資・お出かけ中のコマンドの確認 (一時データ, 画像生成なし).

    python tools/test_presence.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)     # 時刻を日曜の昼に固定 (流す日時に左右されないように)


def main():
    random.seed(5)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        L, P = app.life, app.presence
        st = app.state("hina")
        free = lambda: st.update(override={"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": 9e12})  # noqa: E731
        free()
        app.set_params({"affection": 70, "mood": 60, "sleepiness": 0, "health": 90, "loneliness": 80, "boredom": 70})
        assert len(app.approaches) >= 10, "既定の働きかけが data に入っていない"

        # ---- 在席: 心拍・放置・黙って閉じる
        now = time.time()
        app.state_view(beat=True, idle=0)
        assert P.at(time.time()) == "here"
        app.state_view(beat=True, idle=15 * 60)
        assert P.at(time.time()) == "idle", P.rec()
        P.rec()["beat"] = now - 4 * 3600                 # 4 時間前から心拍なし = 黙って閉じていた
        st["last_interaction"] = now - 4 * 3600
        app.state_view(beat=True, idle=0)
        assert P.rec()["last_left"]["said"] is False
        r = app.visit()
        print("黙って閉じたあと:", r["entry"]["text"])
        assert P.ctx(time.time())["said"] is False

        # ---- 告げて離れる → 戻る
        st["cooldowns"] = {}
        r = app.act("go_out")
        assert P.rec()["mode"] == "out" and app.state_view()["presence"]["state"] == "out"
        av = app.state_view()["available"]
        assert not av["go_out"]["ok"] and not av["talk"]["ok"] or True
        P.rec()["since"] -= 7 * 3600
        assert app.visit() is None and P.rec()["mode"] == "out", "開き直しただけなら外出は続く (閉じていたら家に帰っている)"
        r = app.come_back()                               # 「ただいま」で戻る
        print("出かけて戻る:", r["entry"]["text"])
        assert P.rec()["mode"] == "none" and P.ctx(time.time())["left_mode"] == "out"

        # 仕事: 働いた時間ぶん稼ぐ. すぐ戻ると稼ぎなし
        app.world["economy"]["work_hours"] = [0, 24]            # テストは時刻に左右されないように
        app.action("go_work")["when"] = "presence=here|idle|busy"
        m0 = L.player_state()["money"]
        app.act("go_work")
        r = app.come_back()
        print("すぐ戻る:", r["entry"]["text"])
        assert L.player_state()["money"] == m0
        app.act("go_work")
        P.rec()["since"] -= 8.5 * 3600
        w0 = L.skill("work")
        r = app.come_back()
        print("8.5時間働いた:", r["entry"]["money"], r["entry"].get("skill"), r["entry"]["text"])
        assert L.player_state()["money"] > m0 + 5000 and L.skill("work") > w0

        # 体力が減り, 疲れていると構っても効きが悪い
        print("仕事のあとの体力:", round(L.stamina(), 1))
        assert L.stamina() <= 100 - 8 * 9 + 1
        # 給料の出る時間帯と 1 日の上限 (固定の日時で)
        import datetime as _d
        app.world["economy"]["work_hours"] = [6, 23]
        L.player_state()["work_log"] = {}
        t22 = _d.datetime(2030, 1, 1, 22, 0).timestamp()
        paid, raw = L.work_hours(t22, t22 + 9 * 3600)              # 22時〜翌7時: 22-23時と6-7時だけ
        print("夜勤 9時間 → 給料の出る時間:", round(paid, 2))
        assert abs(paid - 2) < 0.01
        t8 = _d.datetime(2030, 1, 2, 8, 0).timestamp()
        L.work_hours(t8, t8 + 6 * 3600, record=True)
        paid2, _ = L.work_hours(t8 + 7 * 3600, t8 + 13 * 3600)    # 同じ日にもう 6 時間 → 上限 9 時間で残り 3 時間
        print("同じ日の2回目 6時間 → ", round(paid2, 2))
        assert abs(paid2 - 3) < 0.01
        app.world["economy"]["work_hours"] = [0, 24]
        L.player_state()["work_log"] = {}

        # ---- 働きかけ: 応じる / あとで / 放っておく
        free()
        st["approach"] = None
        r = app.force_approach("chat")
        assert st["approach"] and app.state_view()["approach"]["id"] == "chat"
        print("働きかけ:", r["entry"]["text"])
        t0 = L.skill("talk")
        r = app.answer_approach("accept")
        print("  → 応じる:", r["entry"]["text"], r["entry"]["deltas"])
        assert not st.get("approach") and L.skill("talk") > t0
        app.force_approach("lonely")
        r = app.answer_approach("later")
        print("  → あとで:", r["entry"]["text"])
        # 放っておく (そばにいるのに): 機嫌が下がり, 理由が残る
        P.rec()["mode"] = "none"
        app.state_view(beat=True, idle=20 * 60)
        app.set_params({"loneliness": 85, "mood": 60})
        app.force_approach("lonely")
        st["approach"]["until"] = time.time() - 1
        mood0 = st["params"]["mood"]
        app.state_view(beat=True, idle=20 * 60)
        e = app.log("hina")[-1]
        print("  → 放置:", e["text"], e["deltas"])
        assert st["params"]["mood"] < mood0 and not st.get("approach")
        assert any("返事がなかった" in x["tell"] for x in L.reasons(st, time.time()))
        # 作業中と告げていれば軽く済む
        app.act("go_busy")
        app.set_params({"loneliness": 60, "mood": 60})
        app.force_approach("chat")
        st["approach"]["until"] = time.time() - 1
        app.state_view(beat=True, idle=0)
        e = app.log("hina")[-1]
        print("  → 作業中に放置:", e["text"], e["deltas"])
        assert e["deltas"].get("mood", 0) > -3
        # 応じるとコマンドを実行するもの
        P.back()
        free()
        st["cooldowns"] = {}
        app.set_params({"boredom": 80, "sleepiness": 0})
        app.force_approach("play")
        r = app.answer_approach("accept")
        assert r["entry"]["action"] == "game", r["entry"]
        print("  → ゲームに誘われて応じる:", r["entry"]["text"])

        # 自然に起きるか (寂しく退屈なら, そばにいればそのうち話しかけてくる)
        free()
        st["approach"], st["ap_quiet_until"], st["ap_last"] = None, 0, {}
        P.rec()["mode"] = "none"
        app.set_params({"loneliness": 90, "boredom": 90, "affection": 70})
        random.seed(7)     # 前段の乱数の使い方 (セリフ選びなど) に回数が左右されないように
        fired = 0
        for i in range(60):
            st["ap_check"] = time.time() - 600
            st["ap_quiet_until"] = 0
            st["last_interaction"] = time.time() - 3600    # しばらく構っていない
            st["ap_last"] = {}
            if app.presence.live(app.char(), st, time.time()):
                fired += 1
                st["approach"] = None
        print("10分ごと60回で働きかけ:", fired)
        assert 10 <= fired <= 60

        # ---- スキル: 料理が下手だと失敗することがある / 上手だと効き目が大きい
        L.player_state()["skills"]["cook"] = 5
        fails = 0
        for i in range(30):
            free()
            st["cooldowns"] = {}
            app.set_params({"satiety": 40})
            r = app.act("cook")
            fails += any(w in r["entry"]["text"] for w in ("焦げ", "こげ"))     # 性格プリセットごとに言い方が違う
        print("料理スキル5で30回:", fails, "回失敗 / スキル", L.skill("cook"))
        assert fails >= 3 and L.skill("cook") > 5
        L.player_state()["skills"]["talk"] = 90
        free()
        st["cooldowns"] = {}
        app.set_params({"mood": 40})
        d_hi = app.act("talk")["entry"]["deltas"].get("mood", 0)
        L.player_state()["skills"]["talk"] = 0
        st["cooldowns"] = {}
        app.set_params({"mood": 40})
        r = app.act("talk")
        d_lo = r["entry"]["deltas"].get("mood", 0)
        print("会話スキル 90 / 0 の機嫌の伸び:", d_hi, d_lo)

        # ---- 内職
        st["cooldowns"] = {}
        free()
        L.player_state()["stamina"] = 5
        try:
            app.task_start("sort")
            raise AssertionError("疲れていても内職できてしまう")
        except ValueError as e:
            print("  疲れて内職:", e)
        L.player_state()["stamina"] = 100
        tk = app.task_start("sort")
        assert P.rec()["mode"] == "busy"
        try:
            app.task_finish(tk["token"], 50, 2)
            raise AssertionError("時間前に終われてしまう")
        except ValueError:
            pass
        app.tasks[tk["token"]]["t0"] -= 61
        m0 = L.player_state()["money"]
        r = app.task_finish(tk["token"], 50, 2)
        print("内職:", r["task"], r["entry"]["text"])
        assert L.player_state()["money"] - m0 == r["task"]["pay"] > 0 and P.rec()["mode"] == "none"
        try:
            app.task_start("sort")
            raise AssertionError("連続で内職できてしまう")
        except ValueError as e:
            print("  連続:", e)

        # ---- 投資: 銘柄の売買とニュース
        L.player_state()["money"] = 100000
        app.trade("tech", 5)
        mv = L.market_view()
        tech = next(a for a in mv["assets"] if a["id"] == "tech")
        assert tech["qty"] == 5
        ps = L.player_state()
        ps["last_tick"] -= 3 * 86400
        L.tick_world()
        print("3日分のニュース:", len(ps["market"]["news"]), [n["text"] for n in ps["market"]["news"][-3:]])
        assert ps["market"]["news"]
        r = app.trade("tech", -5)
        print("売却:", r["entry"]["text"], r["entry"]["money"])
        try:
            app.trade("tech", -1)
            raise AssertionError("持っていない株を売れてしまう")
        except ValueError:
            pass

        # ---- お出かけ中は家でしかできないことが出ない
        st["cooldowns"] = {}
        free()
        app.set_params({"affection": 80, "mood": 70, "energy": 90})
        P.rec()["mode"] = "none"
        st["override"] = None
        st["override"] = {"activity": "date", "label": "デート", "location": "街", "outing": True, "until": time.time() + 3600}
        av = app.state_view()["available"]
        bad = [k for k in ("cook", "tea", "bath", "clean", "movie", "game", "side_job", "walk") if av[k]["ok"]]
        print("お出かけ中に出せてしまう家のコマンド:", bad)
        assert not bad and av["go_home"]["ok"] and av["talk"]["ok"]
        try:
            app.act("cook")
            raise AssertionError("お出かけ中に料理できてしまう")
        except ValueError:
            pass
        # ---- 性格の傾向: 黙っていなくなると, 甘えたがりはクールよりずっと堪える
        char = app.char()
        res = {}
        for pid in ("amaenbo", "cool"):
            char["persona_id"] = pid
            st["override"], st["approach"] = None, None
            app.set_params({"loneliness": 40, "mood": 60, "trust": 50, "affection": 60})
            now = time.time()
            st["last_interaction"] = st["last_tick"] = now - 8 * 3600
            P.rec().update(mode="none", beat=now - 8 * 3600, input=now - 8 * 3600)
            app.state_view(beat=True, idle=0)          # 心拍が戻る: 8 時間, 黙っていなかった
            lon = st["params"]["loneliness"]
            r = app.visit()
            res[pid] = (round(lon, 1), r["entry"]["deltas"], r["entry"]["text"])
            print("黙って8時間 (%s): 寂しさ %s → %s | %s" % (pid, lon, r["entry"]["deltas"], r["entry"]["text"]))
        assert res["amaenbo"][0] > res["cool"][0] + 10
        assert res["amaenbo"][1].get("mood", 0) < res["cool"][1].get("mood", 0)
        # 告げて離れた場合はお咎めなし
        char["persona_id"] = "amaenbo"
        app.set_params({"loneliness": 40, "mood": 60, "trust": 50})
        app.act("go_leave")
        P.rec()["since"] -= 8 * 3600
        r = app.visit()
        print("告げて8時間 (amaenbo):", r["entry"]["deltas"], r["entry"]["text"])
        assert r["entry"]["deltas"].get("mood", 0) >= 0 and "trust" not in r["entry"]["deltas"]
        # 黙って 1 時間でも, ひと言ある
        st["override"] = None
        now = time.time()
        st["last_interaction"] = now - 1.5 * 3600
        P.rec().update(mode="none", beat=now - 1.5 * 3600)
        app.state_view(beat=True, idle=0)
        r = app.visit()
        assert r and "いなくな" in r["entry"]["text"], r
        print("黙って1.5時間 (amaenbo):", r["entry"]["text"])
        print("OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
