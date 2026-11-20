"""相手の関心の揺らぎ (core/waves.py): 時期 (生活の波) と新鮮さ, 今ある仕組みへの効き.

    python tools/test_waves.py
"""
import os
import random
import shutil
import collections
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, waves as W  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
PERSONAS = ("amaenbo", "cool", "aneki", "tenshin", "teinei")
STAGES = ("contact", "visit", "live")


def main():
    random.seed(35)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("関心の揺らぎ")
        V = app.waves
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        p = st["params"]
        now = time.time()

        # ---- 1. 遡及: 無いときに一度だけ作る. 時期はふつう, 新鮮さは交流の頻度から
        st.pop("waves", None)
        st["touch_days"] = []
        r0 = V.rec(char, st, now)
        assert r0["p"] == "normal" and 35 <= r0["fresh"] <= 90 and now + 2 * 86400 - 1 <= r0["until"] <= now + 10 * 86400 + 1
        r0["fresh"] = 42.0
        assert V.rec(char, st, now)["fresh"] == 42.0            # 二重に作らない
        st.pop("waves", None)
        st["touch_days"] = [datetime.fromtimestamp(now - i * 86400).date().isoformat() for i in range(14)]
        busy_fresh = V.rec(char, st, now)["fresh"]
        st.pop("waves", None)
        st["touch_days"] = []
        idle_fresh = V.rec(char, st, now)["fresh"]
        assert idle_fresh > busy_fresh + 30, (idle_fresh, busy_fresh)
        ctx = app.context(char, st, datetime.now())
        assert {"wave", "wave_apart", "wave_near", "fresh"} <= set(ctx)
        print("遡及: OK | 毎日会っていた %.1f / 会っていない %.1f" % (busy_fresh, idle_fresh))

        # ---- 2. 時期 × 性格 × 仲 × 新鮮さ: 倍率はゼロにならず, 上限の内 (必ず増える・必ずゼロ, にしない)
        rows = 0
        for pid in PERSONAS:
            char["persona_id"] = pid
            st.pop("attach", None)
            for stage in STAGES:
                app.bonds.set_stage(cid, stage)
                for wv in W.WAVES:
                    for fr in (10.0, 50.0, 95.0):
                        V.rec(char, st).update(p=wv, fresh=fr)
                        c = V.ctx(char, st)
                        assert 0.4 <= c["wave_apart"] <= 1.8, (pid, stage, wv, fr, c)
                        assert 0.7 <= c["wave_near"] <= 1.35, (pid, stage, wv, fr, c)
                        assert 0.4 <= V.invite_factor(char, st) <= 1.8
                        rows += 1
        app.bonds.set_stage(cid, "contact")
        char["persona_id"] = "teinei"
        st.pop("attach", None)
        print("倍率の範囲: OK | %d 通り" % rows)

        # ---- 2b. 負の偏りが無い: 時期の倍率の時間平均は 1, 受けやすさの差・機嫌の落ち着く先は 0 (ほぼ)
        rows = collections.defaultdict(list)
        r = V.rec(char, st, now)
        r.update(p="normal", until=now)
        app.attach.rec(char, st)["dependence"] = 50.0
        for d in range(3000):
            t = now + d * 86400
            st["last_touch"] = t - 2 * 86400
            V.daily(char, st, t)
            for k in ("apart", "near", "invite", "lonely", "bored", "call"):
                rows[k].append(V.mult(char, st, k))
            rows["accept"].append(V.accept_shift(char, st))
            rows["mood"].append(V.mood_shift(char, st))
        means = {k: sum(v) / len(v) for k, v in rows.items()}
        assert all(0.95 <= means[k] <= 1.05 for k in ("apart", "near", "invite", "lonely", "bored", "call")), means
        assert abs(means["accept"]) < 0.015 and abs(means["mood"]) < 0.5, means
        print("時間平均: OK | " + " / ".join("%s %.3f" % (k, v) for k, v in sorted(means.items())))

        # ---- 3. 時期の向き: 忙しい・人付き合いは控え, 暇は増える. 落ち込みは依存度しだい
        def ap(wv, fresh=50.0):
            V.rec(char, st).update(p=wv, fresh=fresh)
            return V.ctx(char, st)["wave_apart"]
        assert ap("busy") < ap("hooked") < ap("normal") < ap("free")
        assert ap("social") < ap("normal")
        app.attach.rec(char, st)["dependence"] = 90.0
        down_hi = ap("down")
        app.attach.rec(char, st)["dependence"] = 20.0
        down_lo = ap("down")
        assert down_hi > ap("normal") > down_lo, (down_hi, down_lo)
        app.attach.rec(char, st)["dependence"] = 50.0
        assert ap("normal", 10.0) < ap("normal", 50.0) < ap("normal", 95.0)
        print("時期の向き: OK | 落ち込み 依存 高 %.2f / 低 %.2f" % (down_hi, down_lo))

        # presence の度合いが倍率を掛けている (閉じている間の連絡・着信も同じ関数)
        V.rec(char, st).update(p="normal", fresh=50.0)
        p.update(affection=70, loneliness=60, boredom=50, mood=55)
        e0 = app.presence.eagerness_apart(app.context(char, st, datetime.now()))
        n0 = app.presence.eagerness(app.context(char, st, datetime.now()))
        V.rec(char, st).update(p="busy")
        e1 = app.presence.eagerness_apart(app.context(char, st, datetime.now()))
        n1 = app.presence.eagerness(app.context(char, st, datetime.now()))
        assert 0 < e1 < e0 and 0 < n1 < n0, (e0, e1, n0, n1)
        print("連絡・話しかけの度合い: OK | 離れて %.2f → %.2f / そばで %.2f → %.2f" % (e0, e1, n0, n1))

        # ---- 4. 時期の移り: 期限を過ぎれば移る. 時期のあとは必ずふつう. 同じ時期は続かない
        seen = {}
        t = now
        r = V.rec(char, st, t)
        r.update(p="normal", until=t)
        prev = "normal"
        for _ in range(400):
            t = max(t + 86400, r["until"])
            V.daily(char, st, t)
            cur = r["p"]
            if prev != "normal":
                assert cur == "normal", (prev, cur)
            seen[cur] = seen.get(cur, 0) + 1
            assert 4 * 86400 - 1 <= r["until"] - r["from"] <= 18 * 86400 + 1
            prev = cur
        assert all(seen.get(k) for k in W.WAVES), seen
        print("時期の移り: OK | %s" % seen)

        # 重み: 会社員は 3・12 月に忙しくなりやすい. 夜型ははまりやすい. ストレスが高いと落ち込みやすい
        char.setdefault("life", {})["type"] = "office"
        w_dec = V.weights(char, st, datetime(2026, 12, 10).timestamp())
        w_jun = V.weights(char, st, datetime(2026, 6, 10).timestamp())
        assert w_dec["busy"] > w_jun["busy"] and w_dec["social"] > w_jun["social"]
        p["stress"] = 80
        assert V.weights(char, st, now)["down"] > w_jun["down"]
        p["stress"] = 20
        print("時期の起きやすさ: OK | 12 月 忙しい %.2f / 6 月 %.2f" % (w_dec["busy"], w_jun["busy"]))

        # ---- 5. 新鮮さ: 会うと下がる・離れると戻る・近い仲ほど下がりにくい
        def drop(stage, aff=50, n=200):
            app.bonds.set_stage(cid, stage)
            p["affection"] = aff
            tot = 0.0
            for _ in range(n):
                V.rec(char, st).update(fresh=60.0, until=now + 99 * 86400)
                st["last_touch"] = now - 3600
                V.daily(char, st, now)
                tot += 60.0 - V.fresh(char, st)
            return tot / n
        d_contact, d_visit, d_live, d_love = drop("contact"), drop("visit"), drop("live"), drop("live", 80)
        assert d_contact > d_visit > d_live > d_love > 0, (d_contact, d_visit, d_live, d_love)
        app.bonds.set_stage(cid, "contact")
        p["affection"] = 50
        V.rec(char, st).update(fresh=20.0)
        st["last_touch"] = now - 5 * 86400
        for i in range(30):
            V.daily(char, st, now + i * 86400)
        assert 55 <= V.fresh(char, st) <= W.FRESH_REST + 0.5, V.fresh(char, st)
        print("新鮮さ: OK | 下がる幅 連絡先 %.2f / 家に行ける %.2f / 同居 %.2f / 同居で好感度 80 %.2f, 離れて 20 → %.1f"
              % (d_contact, d_visit, d_live, d_love, V.fresh(char, st)))

        # 初めてのこと: 戻ることがある (必ずではない)
        ups = []
        for _ in range(300):
            V.rec(char, st).update(fresh=40.0)
            ups.append(V.novel(char, st, "place", now))
        hit = sum(1 for u in ups if u > 0) / len(ups)
        assert 0.45 < hit < 0.75 and max(ups) <= 6.0 + 1e-9, hit
        # 一緒に初めての行き先へ (appoint.remember) / 初めての話題 (topics.told)
        random.seed(1)
        got = 0
        for i in range(40):
            V.rec(char, st).update(fresh=40.0)
            app.appoint.remember(cid, "newplace_%d" % i, 2)
            got += V.fresh(char, st) > 40.0
        V.rec(char, st).update(fresh=40.0)
        app.appoint.remember(cid, "newplace_0", 2)               # 二度目の行き先では戻らない
        assert 10 < got < 40 and V.fresh(char, st) == 40.0, got
        print("初めてのこと: OK | 戻った割合 %.2f / 初めての行き先 %d/40" % (hit, got))

        # ---- 6. 依存度との釣り合い: 「一緒にいて寂しさが紛れた」の上がり幅が新鮮さで変わる
        def lean(fr, n=300):
            tot = 0.0
            for _ in range(n):
                V.rec(char, st).update(fresh=fr, until=now + 99 * 86400)
                a = app.attach.rec(char, st)
                a.update(dependence=50.0, day={})
                st["last_touch"] = now - 3600
                p["loneliness"] = 30
                app.attach.daily(char, st, now)
                tot += app.attach.get(char, st, "dependence") - 50.0
            return tot / n
        l_lo, l_hi = lean(15.0), lean(90.0)
        assert 0 < l_lo < l_hi, (l_lo, l_hi)
        print("依存度との釣り合い: OK | 慣れている %.2f / 新鮮 %.2f" % (l_lo, l_hi))

        # ---- 7. 誘いの断り方: 忙しい・人付き合いの時期は理由を言うことがある. ふつうは言わない
        # 「友達と約束がある」は, 誘われた日に本当に知り合いと会う予定があるときだけ (core/circle.py. 作り事にしない)
        noon = (datetime.fromtimestamp(now) + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0).timestamp()

        def keys(wv, n=300, plan=False):        # 明日の正午の予定と, 同じ日の 15 時の誘い (夜に流しても日をまたがない)
            V.rec(char, st).update(p=wv)
            cr = app.circle.rec(char, st, now)
            cr["plans"] = [{"t0": noon, "t1": noon + 7200, "pid": cr["people"][0]["pid"], "place": "cafe",
                            "kind": "meal"}] if plan else []
            return {V.decline_key(char, st, noon + 3 * 3600) for _ in range(n)}
        assert keys("busy") == {None, "appoint_no_busy"} and keys("social") == {None}
        assert keys("social", plan=True) == {None, "appoint_no_friends"} and keys("normal", plan=True) == {None, "appoint_no_friends"}
        assert keys("normal") == {None} and keys("free") == {None}
        app.circle.rec(char, st, now)["plans"] = []
        from core import chat as chat_mod
        for k in ("appoint_no_busy", "appoint_no_friends") + tuple("wave_" + w for w in W.SPECIAL):
            assert "chat." + k in chat_mod.LINES and k in chat_mod.SCENE_LABEL, k
            assert app.chat.line(char, k, {"when": "明日", "place": "カフェ"})
        V.rec(char, st).update(p="normal")
        a_norm = V.accept_shift(char, st)
        assert 0 <= a_norm < 0.05, a_norm            # ふつうはわずかに + (時期の平均を 0 にそろえた分)
        V.rec(char, st).update(p="busy")
        assert V.accept_shift(char, st) < 0 < a_norm
        print("断り方・セリフ: OK")

        # ---- 8. 口にする: 時期ごとに一度だけ. ふつうでは言わない
        V.rec(char, st).update(p="normal", told=False)
        assert all(V.tell_key(char, st) is None for _ in range(50))
        V.rec(char, st).update(p="hooked", told=False)
        said = [V.tell_key(char, st) for _ in range(50)]
        assert said.count("wave_hooked") == 1, said
        print("口にする: OK")

        # ---- 9. 寂しさ・退屈のたまる速さ: 忙しい時期は寂しさがたまりにくい (本人の _step)
        def lonely_gain(wv, n=24):
            V.rec(char, st).update(p=wv, fresh=50.0)
            p.update(loneliness=40.0, affection=60, boredom=40.0)
            for i in range(n):
                app._step(char, st, datetime(2026, 6, 10, 14, 0), 0.25)
            return p["loneliness"] - 40.0, p["boredom"] - 40.0
        random.seed(5)
        nl, nb = lonely_gain("normal")
        random.seed(5)
        sl, sb = lonely_gain("social")
        random.seed(5)
        hl, hb = lonely_gain("hooked")
        assert sl <= nl and hb <= nb, (nl, sl, nb, hb)
        print("たまる速さ: OK | 寂しさ ふつう %+.1f / 人付き合い %+.1f, 退屈 ふつう %+.1f / はまっている %+.1f" % (nl, sl, nb, hb))

        # ---- 10. 通しで: 相手から送るメッセージに近況が一度だけ添わる / 誘いの返事に時期の断り方が出る
        app.bonds.set_stage(cid, "contact")
        p.update(affection=60, mood=55, loneliness=50)
        W.TELL_CHANCE = 1.0
        V.rec(char, st).update(p="hooked", told=False, fresh=50.0)
        texts = []
        for i in range(2):
            st.pop("approach", None)
            st.pop("msg_pending", None)
            ctx = app.context(char, st, datetime.now())
            app.presence.fire(char, st, now + i, ctx, force="msg_today", phone=False)
            it = [x for x in app.chat.load(cid)["items"] if x.get("who") == "her"][-1]
            texts.append((it.get("wave"), it["text"]))
        assert texts[0][0] == "wave_hooked" and texts[1][0] is None, texts
        assert "はまって" in texts[0][1] and texts[0][1].count("『") == texts[0][1].count("』") <= 1, texts[0]
        W.TELL_CHANCE = 0.5
        from collections import Counter
        free = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(free(c, d), away=False, busy=False, asleep=False)
        V.rec(char, st).update(p="social")
        cr = app.circle.rec(char, st, now)          # その日の夜に知り合いと会う予定がある (誘いの時刻とは重ならない. 夜に流しても日をまたがない)
        day2 = noon + 86400 - 2 * 3600               # あさっての 10 時の誘い・14〜16 時の予定
        cr["plans"] = [{"t0": day2 + 4 * 3600, "t1": day2 + 6 * 3600, "pid": cr["people"][0]["pid"],
                        "place": "cafe", "kind": "meal"}]
        got = Counter()
        for i in range(120):
            x = {"id": "w%d" % i, "cid": cid, "t": day2, "place": "riverside", "do": "walk", "by": "me",
                 "status": "asked", "made": now, "rounds": 9}
            app.appoint.all().append(x)
            p.update(affection=35, mood=35)
            key = app.appoint.reply(char, st, {"appoint": x["id"]}, now, {"too_often": True})[0]
            got[key] += 1
            x["status"] = "cancelled"
        app.scheduled_scene = free
        assert got["appoint_no_friends"] > 0 and got["appoint_no"] > 0 and not got["appoint_no_busy"], got
        print("通し: OK | 添えた近況「%s」/ 断り方 %s" % (texts[0][1][-40:], dict(got)))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
