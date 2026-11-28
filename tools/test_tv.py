"""テレビ (S61 段 2. core/tv.py): 時間帯の番組表・連続ドラマ・一人で観る・一緒に観る・相手が観た番組の話.

時間帯で番組が変わる (平日 / 週末・21 時の曜日・深夜は通販・24 時台は前の日の表)・番組の境目をまたいで観た分数・
連続ドラマの話数が曜日で進み休みの週と作品の替わり目があり, 見逃すと飛ぶ (あなた: 文で / 相手: 反応の条件)・
一人で観た番組が話題になる (20 分以上・2 つまで・同じ番組は一度)・一緒に観た回が記録と二人の話題になる・
覚える (prefs の tv:<種類>)・好みの遡及 (tv:<種類> を一度だけ)・相手が自分で観た番組をメッセージで振る (一度話したら繰り返さない)・
連続ドラマの時間の誘い (一緒に観続けていれば)・音楽はテレビの間は鳴らない・一緒に観る行動が通る.

    python tools/test_tv.py
"""
import copy
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, store, tv as tv_mod  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
D = datetime.fromisoformat


def main():
    random.seed(62)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        # ---- 1. 番組表: 時間帯・平日と週末・21 時の曜日・深夜
        P = tv_mod.program
        cases = {"2026-11-24 07:00": "news", "2026-11-24 09:30": "info", "2026-11-24 11:30": "cooking", "2026-11-24 12:30": "news",
                 "2026-11-24 15:00": "info", "2026-11-24 19:30": "animals", "2026-11-24 20:30": "variety", "2026-11-24 22:30": "news",
                 "2026-11-28 14:00": "sports", "2026-11-28 10:00": "animals", "2026-11-28 21:30": "drama", "2026-11-28 03:00": None,
                 "2026-11-26 21:30": "drama", "2026-11-27 21:30": "drama", "2026-11-23 21:30": "variety"}
        for s, k in cases.items():
            assert P(D(s))["kind"] == k, (s, P(D(s)))
        assert P(D("2026-11-29 00:30"))["key"] == "2026-11-28:23", "24 時台は前の日の表"
        assert P(D("2026-11-26 21:30")).get("serial") and not P(D("2026-11-27 21:30")).get("serial")
        assert P(D("2026-11-24 07:59"))["key"] != P(D("2026-11-24 08:00"))["key"]
        n = 0
        for day in range(14):                      # 総当たり: どの時刻も番組がある (深夜の通販を含む). 始まり <= 時刻 < 終わり
            for m in range(0, 24 * 60, 10):
                t = datetime(2026, 11, 23) + timedelta(days=day, minutes=m)
                p = P(t)
                assert p["start"] <= t < p["end"] and (p["kind"] in tv_mod.KINDS or p["kind"] is None), (t, p)
                n += 1
        print("番組表: OK %d 通り" % n)

        # ---- 2. 観ていた分数: 境目をまたぐ
        got = tv_mod.programs_between(D("2026-11-24 19:40").timestamp(), D("2026-11-24 21:10").timestamp())
        assert [(p["kind"], round(m)) for p, m in got] == [("animals", 20), ("variety", 60), ("drama", 10)], \
            [(p["kind"], p["title"], round(m)) for p, m in got]
        print("観ていた分数: OK")

        # ---- 3. 連続ドラマ: 木曜ごとに話数が進む. 10 話のあと休みの週, そのあと次の作品の第 1 話
        eps = []
        d = tv_mod.EPOCH
        for w in range(30):
            eps.append(tv_mod.serial_of(d + timedelta(days=7 * w)))
        assert eps[0] == (tv_mod.SERIALS[0], 1) and eps[9] == (tv_mod.SERIALS[0], 10) and eps[10] is None
        assert eps[11] == (tv_mod.SERIALS[1], 1) and eps[21] is None and eps[22] == (tv_mod.SERIALS[2], 1)
        assert tv_mod.serial_of(tv_mod.EPOCH + timedelta(days=1)) is None, "木曜だけ"
        assert P(datetime.combine(tv_mod.EPOCH + timedelta(days=70), datetime.min.time()) + timedelta(hours=21, minutes=5))["kind"] == "variety", "休みの週は特番"
        for w in (0, 5, 12, 40):
            dd = tv_mod.EPOCH + timedelta(days=7 * w)
            sr = tv_mod.serial_of(dd)
            if sr:
                assert tv_mod.TV.air_date(sr[0], sr[1], dd + timedelta(days=10)) == dd
        print("連続ドラマ: OK", eps[:3], eps[10:12])

        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("テレビ")
        T = app.tv
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        app.presence.declare("none")
        app.presence.beat(time.time(), 0)

        # ---- 4. 好みの遡及: tv:<種類> を一度だけ (いまの系統は変えない. 音楽・香りも先に足る)
        tv0 = copy.deepcopy(app.topics.tastes(char, st))
        tv1 = copy.deepcopy(T.tastes(char, st))
        assert all(tv1[k] == v for k, v in tv0.items()) and any(k.startswith("tv:") for k in tv1)
        assert st["tastes_fam"] == ["amb", "tv"]
        assert T.tastes(char, st) == tv1 and st["tastes_fam"] == ["amb", "tv"]
        print("好みの遡及: OK", {k: v for k, v in tv1.items() if k.startswith("tv:")})

        # ---- 5. 一人で観る: 観た番組が話題に (20 分以上・2 つまで). 連続ドラマの回 (30 分以上). 見逃した回は文で
        sr = tv_mod.serial_of(D("2026-11-26").date())
        ps = app.life.player_state()
        txt = T.watch_solo(D("2026-11-26 19:50").timestamp(), D("2026-11-26 21:50").timestamp())
        new = [x["text"] for x in app.topics.all() if x["src"] == "tv"]
        assert len(new) == 2 and "いきもの散歩" not in "".join(new), (txt, new)          # 動物番組は 10 分だけ
        assert ps["tv"]["serial"] == {"title": sr[0], "seen": [sr[1]], "with": []}
        assert "見逃していて" not in txt, ("初めて観た作品は「見逃した」にしない", txt)
        txt2 = T.watch_solo(D("2026-12-10 21:00").timestamp(), D("2026-12-10 21:55").timestamp())        # 翌週 (12/3) を飛ばした
        assert "見逃していて" in txt2 and ps["tv"]["serial"]["seen"] == [sr[1], sr[1] + 2], (txt2, ps["tv"]["serial"])
        txt3 = T.watch_solo(D("2026-11-24 21:00").timestamp(), D("2026-11-24 21:15").timestamp())
        assert "テレビを観た" in txt3 and ps["tv"]["serial"]["seen"] == [sr[1], sr[1] + 2], "15 分だけでは観た回にしない"
        assert T.watch_solo(D("2026-11-24 03:00").timestamp(), D("2026-11-24 03:03").timestamp()).startswith("テレビをつけたが")
        print("一人で観る: OK", txt, "/", txt2)

        # ---- 6. 一緒に観る: 反応の条件 (種類・受け止め・続き / 見逃し). 記録と二人の話題
        sr_d = D("2026-11-26 21:20")
        st["tv"] = {}
        ctx, opts = {}, {}
        T.together(char, st, opts, ctx, sr_d.timestamp())
        assert ctx["tv_kind"] == "drama" and opts["tv"]["ep"] == sr[1] and opts["extra"]["show"].startswith("『")
        follows = T.follows(char, st, sr[0])
        assert (ctx["tv_serial"] == "missed") == (not T.char_saw_ep(char, st, sr[0], sr[1] - 1, sr_d.date()))
        st["tv"] = {"serial": {"title": sr[0], "seen": [sr[1] - 1], "with": [sr[1] - 1]}}
        ctx, opts = {}, {}
        T.together(char, st, opts, ctx, sr_d.timestamp())
        assert ctx["tv_serial"] == "next", ctx
        x = T.after_together(char, st, opts, sr_d.timestamp())
        assert st["tv"]["serial"]["with"] == [sr[1] - 1, sr[1]] and sr[0] in x[0] and x[1] == ["romance"]
        feels = {"like": 0, "ok": 0, "dislike": 0}
        A0 = dict(T.tastes(char, st))
        T.tastes(char, st)["tv:variety"] = 0.8
        for _ in range(300):
            c = {}
            T.together(char, st, {}, c, D("2026-11-24 20:20").timestamp())
            feels[c["tv_feel"]] += 1
        assert feels["like"] > 200 and feels["dislike"] == 0 and feels["ok"] > 0, feels
        T.tastes(char, st).update(A0)
        c = {}
        T.together(char, st, {}, c, D("2026-11-24 03:20").timestamp())
        assert c["tv_kind"] == "none"
        print("一緒に観る: OK 追っている %s・好きな種類 %s" % (follows, feels))

        # ---- 7. 行動として: 通る・話題・覚える (いまの時刻の番組で)
        app.bonds.set_stage(cid, "live")
        app.presence.declare("none")
        app.presence.beat(time.time(), 0)
        st["cooldowns"] = {}
        st.pop("prefs", None)
        r = app.act("tv", cid)
        kind = tv_mod.program(datetime.now())["kind"]
        e = r.get("entry") or r
        assert e, r
        if kind and not (r.get("reaction") or {}).get("override"):
            assert st["prefs"].get("tv:" + kind, 0) > 0 and st["prefs"].get("act:tv", 0) > 0, st.get("prefs")
            assert any(x["src"] == "with" and "を観た話" in x["text"] for x in app.topics.all())
        assert app.ambience.watching(time.time()), "一緒にテレビを観ている間は音楽が鳴らない"
        st["override"] = None
        print("行動: OK いま %s" % tv_mod.program(datetime.now())["title"])

        # ---- 8. 相手が自分で観た番組: メッセージの話題 (前の晩の番組. 一度話したら繰り返さない)
        T.tastes(char, st).update({"tv:" + k: 0.9 for k in tv_mod.KINDS})
        T._seen = {}
        now = D("2026-11-25 12:00").timestamp()
        p = T.char_saw(char, st, now)
        if p:
            assert p["end"].timestamp() < now and 19 <= p["start"].hour <= 22
            assert T.seen_ctx(char, st, now) == 1
            lb = T.pick_seen(char, st, now)
            assert lb == tv_mod.label(p) and T.seen_ctx(char, st, now) == 0, "一度話したら繰り返さない"
        hits = 0
        for dd in range(30):
            T._seen = {}
            hits += bool(T.char_saw(char, st, (D("2026-11-01 12:00") + timedelta(days=dd)).timestamp()))
        assert hits >= 20, hits                  # どの種類も好きなら, たいていの晩は何か観ている (家にいない晩は観ない)
        T.tastes(char, st).update({"tv:" + k: -0.9 for k in tv_mod.KINDS})
        assert not any(T.char_saw(char, st, (D("2026-11-01 12:00") + timedelta(days=dd)).timestamp()) for dd in range(30)), "嫌いな番組は観ない"
        T.tastes(char, st).update({"tv:" + k: 0.9 for k in tv_mod.KINDS})
        # 働きかけで {show} が入る
        st.pop("tv", None)
        T._seen = {}
        ctx = app.context(char, st, datetime.now())
        ctx.update(apart=True, tv_seen=1, affection=80)
        e = app.presence.fire(char, st, time.time(), ctx, force="msg_tv")
        assert e and "{show}" not in (e.get("text") or ""), e
        print("相手が観た番組: OK 30 日のうち %d 日" % hits)

        # ---- 9. 連続ドラマの時間の誘い: 前の 2 回のどちらかを一緒に観ていれば
        on = D("2026-11-26 20:55").timestamp()
        st["tv"] = {"serial": {"title": sr[0], "seen": [], "with": []}}
        assert T.serial_on(char, st, on) == 0
        st["tv"]["serial"]["with"] = [sr[1] - 2]
        assert T.serial_on(char, st, on) == 1
        assert T.serial_on(char, st, D("2026-11-26 21:30").timestamp()) == 0, "始まって 20 分過ぎたら誘わない"
        assert T.serial_on(char, st, D("2026-11-25 20:55").timestamp()) == 0, "放送の日だけ"
        print("連続ドラマの誘い: OK")

        # ---- 10. 一人でテレビを観ている間は音楽が鳴らない
        app.ambience.you_music("jazz")
        app.solo.start("tv")
        assert app.ambience.music()["v"] == "jazz" and app.ambience.playing() is None
        app.presence.back()
        app.presence.declare("none")
        app.presence.beat(time.time(), 0)
        assert app.ambience.playing() == "jazz"
        print("音楽とテレビ: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
