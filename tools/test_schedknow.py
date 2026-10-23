"""相手の予定の知り方の確認 (一時データ, 画像生成なし).
- 遊んでいる画面 (関係性) には, 聞いた・見かけた予定だけが出る (最初は何も知らない)
- 話のついでに聞ける (必ずではない. 会話・気配りのスキルが高いほど聞きやすい)
- 人づて: 話している相手が知っている人の予定を聞くことがある
- 職場で: 勤め先のある予定の時間に, その行き先へ行くと, 店員として働いているのに出会う (行き先ごとに一度)
- メッセージ: 今日のことが添えられることがある (一日に一度まで)
- 予定が変わると「もう違うかも」, 古くなると「前に聞いた話」

    python tools/test_schedknow.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, knowsched  # noqa: E402
from testclock import fix_noon  # noqa: E402

REAL_SCHED = engine.App.scheduled_scene
fix_noon(engine)


def main():
    random.seed(7)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("予定")
        K = app.knowsched
        cid = "hina" if "hina" in app.chars else next(iter(app.chars))
        char = app.chars[cid]
        st = app.state(cid)
        pv = next(p for p in app.people_view() if p["id"] == cid)
        assert pv["sched"] == [], "最初は相手の予定を知らない"
        assert all(k.get("kind") != "schedule" for k in pv["known"])

        # ---- 言い方
        e = {"days": "tue", "from": "17:00", "to": "20:00", "label": "バイト中", "workplace": "supermarket", "away": True}
        assert knowsched.phrase(app, e) == "火曜の夕方はスーパーでバイトらしい", knowsched.phrase(app, e)
        assert knowsched.phrase(app, dict(e, days="tue,thu")).startswith("火曜と木曜の")
        job = next(x for x in char["schedule"] if x.get("workplace")) if cid == "hina" else None
        if job:
            assert knowsched.phrase(app, job) == "土曜の午前は本屋でバイトらしい", knowsched.phrase(app, job)
        assert all(x.get("activity") not in ("sleep", "dinner", "commute") for x in knowsched.notable(char))

        # ---- 話のついで: スキルが高いほど聞きやすい (必ずではない)
        def rate(skill, n=400):
            hits = 0
            for _ in range(n):
                st["known"] = []
                app.life.player_state()["skills"]["talk"] = skill
                app.life.player_state()["skills"]["care"] = skill
                hits += bool(K.from_talk(char, st))
            return hits / float(n)
        lo, hi = rate(5), rate(95)
        print("話のついでに聞ける割合: 低 %.2f / 高 %.2f" % (lo, hi))
        assert 0 < lo < hi < 0.6, (lo, hi)
        st["known"] = []
        t = None
        for _ in range(200):
            t = K.from_talk(char, st)
            if t and "話のついで" in t:
                break
        assert t and "らしい" in t, t
        assert len(app.people_view()[0]["sched"]) or any(p["sched"] for p in app.people_view())

        # ---- 人づて
        others = [b for b in app.chars if b != cid]
        if others:
            b = others[0]
            app.save_relations(cid, {b: {"knows": True, "kind": "友だち", "affinity": 60}})
            app.chars[b].setdefault("schedule", []).append(dict(e))
            got = None
            st["known"] = [{"kind": "schedule", "key": knowsched.key_of(x), "text": "", "t": 0} for x in knowsched.notable(char)]
            for _ in range(800):
                got = K.from_talk(char, st)
                if got:
                    break
            assert got and "から、" in got and app.chars[b]["name"] in got, got
            assert any(k.get("via", "").startswith("secondhand") for k in app.state(b)["known"])

        # ---- 職場で出会う (行き先ごとに一度)
        if job:
            st["known"] = []
            P = app.presence
            sat = datetime(2026, 10, 24, 11, 0).timestamp()
            P.rec().update(mode="out", place="bookstore", since=sat - 600)
            P.rec().pop("work_seen", None)
            orig = app.scheduled_scene
            app.scheduled_scene = lambda c, dt: REAL_SCHED(app, c, datetime(2026, 10, 24, 11, 0))   # 土曜の 11 時
            lines = K.at_workplace(sat)
            assert len(lines) == 1 and "店員として働いていた" in lines[0] and "本屋" in lines[0], lines
            assert K.at_workplace(sat) == [], "同じ外出で二度は出会わない"
            P.rec()["place"] = "supermarket"
            P.rec().pop("work_seen", None)
            assert K.at_workplace(sat) == [], "勤め先でない行き先では出会わない"
            app.scheduled_scene = orig
            pv = next(p for p in app.people_view() if p["id"] == cid)
            assert any(k["via"] == "workplace" for k in pv["sched"]), pv["sched"]
            P.rec().update(mode="none")

        # ---- メッセージ: 一日に一度まで
        st["known"] = []
        st.pop("sched_told", None)
        eve = datetime(2026, 10, 22, 20, 0).timestamp()     # 木曜の夜 (平日の講義は終わっている)
        told = [K.from_message(char, st, eve) for _ in range(60)]
        told = [x for x in told if x]
        assert len(told) == 1 and told[0].startswith("（今日は"), told

        # ---- 予定が変わると外れる / 古くなる
        K.learn(cid, e, "talk", time.time() - 90 * 86400)
        v = K.view(char, st)
        x = next(k for k in v if "スーパー" in k["text"])
        assert x["stale"] and x["old"], x
        print("関係性:", [k["text"] for k in K.view(char, st)])
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp + "_backup", ignore_errors=True)


if __name__ == "__main__":
    main()
