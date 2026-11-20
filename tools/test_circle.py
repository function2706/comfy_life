"""相手の交友関係 (core/circle.py. A34 段 1: 人と予定).

    python tools/test_circle.py
"""
import os
import random
import shutil
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, circle as C  # noqa: E402

T0 = datetime(2026, 11, 23, 0, 0)          # 月曜の 0 時 (時刻を固定しない: 予定は本当の時刻で作る)
DAYS = 60


def busy_at(app, char, t):
    sc = app.own_scene(char, datetime.fromtimestamp(t))
    return sc["away"] or sc["busy"] or sc["asleep"]


def main():
    random.seed(34)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("交友関係")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        t0 = T0.timestamp()

        # ---- 1. 人: 決まった形で一度だけ作る (遡及). 3〜7 人, 苦手は 2 人まで
        st.pop("circle", None)
        r = app.circle.rec(char, st, t0)
        names = [(p["name"], p["kind"], p["tone"]) for p in r["people"]]
        r["people"][0]["close"] = 1.0
        assert app.circle.rec(char, st, t0)["people"][0]["close"] == 1.0          # 二重に作らない
        st.pop("circle", None)
        assert [(p["name"], p["kind"], p["tone"]) for p in app.circle.rec(char, st, t0)["people"]] == names     # 同じ形
        assert r["made_to"] == T0.date().isoformat() and not app.circle.rec(char, st, t0)["plans"]     # 予定は次の日から
        tones, kinds, sizes = Counter(), Counter(), []
        lifes = Counter()
        for i in range(200):
            c2 = dict(char, id="x%d" % i, life=dict(char.get("life") or {}, type=random.choice(("office", "student", "freelance", "service"))))
            ppl = app.circle._make_people(c2, t0)
            sizes.append(len(ppl))
            assert 3 <= len(ppl) <= 7, ppl
            assert sum(1 for p in ppl if p["tone"] in ("uneasy", "strained")) <= 2
            assert len({p["name"] for p in ppl}) == len(ppl)
            lt = c2["life"]["type"]
            if lt == "student":
                assert not any(p["kind"] in ("coworker", "boss") for p in ppl)
            if lt == "freelance":
                assert not any(p["kind"] in ("coworker", "boss", "classmate") for p in ppl)
            tones.update(p["tone"] for p in ppl)
            kinds.update(p["kind"] for p in ppl)
            lifes[sum(1 for p in ppl if p["tone"] in ("uneasy", "strained")) > 0] += 1
        assert lifes[True] > 60 and lifes[False] > 20, lifes          # 苦手な人がいる人が多いが, いない人もいる
        print("人: OK | 人数 %.1f 人 / 向き %s / 苦手な人がいる %d/200" % (sum(sizes) / 200.0, dict(tones), lifes[True]))

        # ---- 2. 予定: 60 日ぶん. 本人の予定・寝ている時間・日またぎ・あなたとの約束と重ならない. 日締めを繰り返しても二重にならない
        x = {"id": "ap1", "cid": cid, "t": t0 + 5 * 86400 + 19 * 3600, "place": "cafe", "do": "walk", "by": "me",
             "status": "set", "made": t0, "rounds": 0}
        app.appoint.all().append(x)
        allp = []
        seen = set()
        for d in range(DAYS):
            t = t0 + d * 86400 + 60
            app.circle.daily(char, st, t)
            n = len(st["circle"]["plans"])
            app.circle.daily(char, st, t + 3600)         # 同じ日にもう一度 (開き直し・追いつき): 増えない
            assert len(st["circle"]["plans"]) == n
            for p in st["circle"]["plans"]:              # 古い予定は消えていくので, 日ごとに拾って数える
                k = (p["t0"], p["pid"])
                if k not in seen:
                    seen.add(k)
                    allp.append(p)
        assert allp, "予定が一つもできない"
        per_day = Counter(datetime.fromtimestamp(p["t0"]).date() for p in allp)
        assert max(per_day.values()) == 1, per_day
        for p in allp:
            assert datetime.fromtimestamp(p["t0"]).date() == datetime.fromtimestamp(p["t1"] - 1).date(), p
            assert p["t1"] - p["t0"] >= 3600
            tt = p["t0"] + 600
            while tt < p["t1"]:
                assert not busy_at(app, char, tt), (p, datetime.fromtimestamp(tt))
                tt += 1800
            assert not (x["t"] - 7200 < p["t1"] and p["t0"] < x["t"] + 4 * 3600), p      # あなたとの約束の前後は避ける
            from core import places as P
            assert P.open_state(p["place"], datetime.fromtimestamp(p["t0"]))["open"]
            per = app.circle.person(char, st, p["pid"])
            if p["kind"] == "work_after":
                assert per["kind"] in ("coworker", "boss") and datetime.fromtimestamp(p["t0"]).weekday() < 5
        weeks = DAYS / 7.0
        kinds_p = Counter(p["kind"] for p in allp)
        print("予定: OK | %d 件 / 週 %.2f 件 / 種類 %s" % (len(allp), len(allp) / weeks, dict(kinds_p)))
        x["status"] = "cancelled"

        # ---- 3. 場面: 予定の最中は外で, 会う人で効き目が違う. 風邪なら家で寝ている
        st["circle"]["plans"] = [dict(q) for q in allp if q["t1"] > t0 + (DAYS - 3) * 86400] or [dict(allp[-1])]
        p = st["circle"]["plans"][0]
        mid = datetime.fromtimestamp((p["t0"] + p["t1"]) / 2)
        sc = app.scene_at(char, st, mid)
        assert sc["activity"] == "circle" and sc["away"] and sc["outing"] and sc["location"], sc
        per = app.circle.person(char, st, p["pid"])
        for tone, sign in (("warm", 1), ("strained", -1)):
            per["tone"] = tone
            fx = app.scheduled_scene(char, mid)["effects"]
            assert (fx.get("mood", 0) > 0) == (sign > 0) and (fx.get("stress", 0) > 0) == (sign < 0), (tone, fx)
        before = app.scene_at(char, st, datetime.fromtimestamp(p["t0"] - 1800))
        assert before["activity"] != "circle"
        st["ill"] = {"level": 1, "until": p["t1"] + 3600, "since": p["t0"] - 86400}
        assert app.scene_at(char, st, mid)["activity"] == "sick"
        st.pop("ill")
        print("場面: OK | %s / %s" % (sc["label"], sc["location"]))

        # ---- 4. 電話の気配: 予定の最中は, その人が後ろにいる
        st["with_log"] = []
        bg = app.phonetalk.background(char, st, mid.timestamp())
        assert bg and bg.get("pid") == p["pid"] and bg["who"] == C.WHO[per["kind"]] and bg["t1"] <= p["t1"], bg
        assert app.phonetalk.who_label(bg) in ("友達", "職場の人", "家族")
        assert app.phonetalk.background(char, st, mid.timestamp() + 600) is bg          # 同じ場面は決め直さない
        print("気配: OK | %s" % app.phonetalk.who_label(bg))

        # ---- 5. あなたの誘いが予定と重なる: 断る (予定を理由に) / 予定をやめてあなたを選ぶ. 予定を残したまま約束しない
        got = Counter()
        for i in range(150):
            st["circle"]["plans"] = [dict(p)]
            y = {"id": "w%d" % i, "cid": cid, "t": p["t0"] + 1800, "place": "cafe", "do": "walk", "by": "me",
                 "status": "asked", "made": p["t0"] - 86400, "rounds": 9}
            app.appoint.all().append(y)
            st["params"].update(affection=random.choice((40, 70, 90)), mood=60)
            key, eff, extra = app.appoint.reply(char, st, {"appoint": y["id"]}, p["t0"] - 86400 + 600, {})
            got[key] += 1
            left = app.circle.plan_over(char, st, y["t"], y["t"] + 7200)
            if y["status"] == "set":
                assert not left, (key, y)
            if key == "appoint_plan":
                assert extra.get("who") and left
                assert extra["who"] in app.chat.line(char, "appoint_plan", extra)
            y["status"] = "cancelled"
        assert got["appoint_plan"] > 60 and got["appoint_plan"] + got.get("appoint_rearranged", 0) + got.get("appoint_yes", 0) \
            + got.get("appoint_no", 0) + got.get("appoint_no_friends", 0) + got.get("appoint_counter", 0) == 150, got
        print("誘いと重なる: OK | %s" % dict(got))

        # ---- 6. 連絡の多さ: 予定の最中は下がり, ほかの時間でならして, 時間平均はほぼ 1
        st["circle"]["plans"] = [dict(p)]
        assert app.circle.contact_f(char, st, mid.timestamp()) == C.CONTACT_IN
        out = app.circle.contact_f(char, st, p["t0"] - 7200)
        sh = app.circle.in_share(char, st)
        avg = sh * C.CONTACT_IN + (1 - sh) * out
        assert out > 1 and abs(avg - 1) < 1e-3, (out, sh, avg)
        ctx = app.context(char, st, mid)
        ctx2 = app.context(char, st, datetime.fromtimestamp(p["t0"] - 7200))
        assert ctx["wave_apart"] < ctx2["wave_apart"], (ctx["wave_apart"], ctx2["wave_apart"])
        print("連絡の多さ: OK | 最中 %.2f / ほか %.3f / 平均 %.4f" % (C.CONTACT_IN, out, avg))

        # ---- 7. セリフ: 全性格で, 予定を理由に断るセリフに相手 (who) が入る
        import glob
        n = 0
        for f in sorted(glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "defaults", "personas", "*.json"))):
            char["persona_id"] = os.path.basename(f)[:-5]
            for who in ("友達", "職場の人", "家族"):
                t = app.chat.line(char, "appoint_plan", {"who": who})
                assert who in t and "{" not in t and t.startswith("📱"), (char["persona_id"], t)
            n += 1
        print("セリフ: OK | %d 性格" % n)

        # ---- 8. 時間の追いつき: 閉じていた 5 日ぶんを tick で追いついても, 予定が日に 2 つにならない
        st["circle"]["plans"] = []
        st["circle"]["made_to"] = ""
        st["last_tick"] = st["last_tick"] - 5 * 86400 if st.get("last_tick") else None
        app.tick(cid)
        app.tick(cid)
        pd = Counter(datetime.fromtimestamp(q["t0"]).date() for q in st["circle"]["plans"])
        assert not pd or max(pd.values()) == 1, pd
        print("追いつき: OK | 予定 %d 件" % len(st["circle"]["plans"]))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
