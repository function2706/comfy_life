"""約束 (アポ) の確認 (一時データ, 画像生成なし).
- 同居していない相手とは, 約束してから会う (約束なしのお出かけ・訪問・招待はできない)
- こちらから: 日時・行き先・何をするか. 返事は時間差. 相手の予定・仲・機嫌しだいで断られる
- 相手から誘われる (仲が浅いうちは誘わない). 受ける / 断る / 返事をしないと流れる
- 当日: 会いに行く. 相手は来ることも, 遅れることも, 来ないことも (約束したときに決まる). 体調不良でキャンセルすることも
- あなたが行かなければ (画面を閉じていても), すっぽかしたことになる. 遅れて行けば少し機嫌を損ねる

    python tools/test_appoint.py
"""
import collections
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from core import places as places_mod  # noqa: E402
from core.appoint import COUNTER_MAX, GIVE_UP, GRACE, phase_ok  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(53)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("約束")
        A, B, C = app.appoint, app.bonds, app.chat
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}
        sched = app.scheduled_scene
        free = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)   # noqa: E731
        app.scheduled_scene = free
        now = time.time()

        # ---- 1. 約束なしにはお出かけできない. 約束の決まりごと
        try:
            app.act("aquarium", cid)
            raise AssertionError("約束なしにお出かけできる")
        except ValueError as e:
            assert "約束" in str(e)
        assert not app.person_view(cid)["available"]["aquarium"]["ok"]
        for bad in ((now + 600, "aquarium", "aquarium"), (now + 15 * 86400, "aquarium", "aquarium"),
                    (now + 7200, "park", "aquarium"), (now + 7200, "home:" + cid, "visit_home")):
            try:
                A.propose(cid, *bad)
                raise AssertionError("約束できてしまう: %s" % (bad,))
            except ValueError:
                pass
        ch = {c["place"]: [d["id"] for d in c["dos"]] for c in A.choices(cid)}
        assert "aquarium" in ch["aquarium"] and "walk" in ch["riverside"] and "home:" + cid not in ch
        print("rules: OK")

        # ---- 2. こちらから誘う: 返事は時間差. 仲・機嫌しだい. 予定があれば断られる
        def ask(t, **params):
            st.pop("msg_pending", None)
            st["contacts"] = []
            app.set_params(dict({"affection": 50, "mood": 60}, **params), cid)
            x = A.propose(cid, t, "riverside", "walk")
            assert x["status"] == "asked" and st["msg_pending"]["kind"] == "appoint"
            assert C.thread(cid)["items"][-1]["who"] == "me" and "河川敷" in C.thread(cid)["items"][-1]["text"]
            st["msg_pending"]["due"] = time.time() - 1
            out = app.deliver_due()
            return A.get(x["id"]), out[0]["text"] if out else None

        yes = {"hi": 0, "lo": 0}
        for i in range(12):
            x, _ = ask(now + (i + 1) * 4 * 3600, affection=80, mood=70)
            yes["hi"] += x["status"] == "set"
            x, _ = ask(now + (i + 1) * 4 * 3600 + 3 * 86400, affection=25, mood=40)
            yes["lo"] += x["status"] == "set"
        assert yes["lo"] < yes["hi"] and yes["hi"] >= 7, yes
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=True, busy=False, asleep=False)
        busy = 0
        for i in range(10):
            x, text = ask(now + 10 * 86400 + i * 4 * 3600, affection=90, mood=80)
            busy += x["status"] == "declined" and "予定" in text
        assert busy >= 5, "その時間に予定があれば断られる: %d" % busy
        app.scheduled_scene = free
        st["date_promise"] = 0
        for x in A.all():
            x["status"] = "declined" if x["status"] in ("asked", "set") else x["status"]
        print("propose: OK", yes)

        # ---- 3. 相手から誘われる / 断る / 流れる
        app.set_params({"affection": 30, "loneliness": 90}, cid)
        assert not any(A._maybe_invite(cid, time.time(), 100) for _ in range(5)), "仲が浅いうちは誘わない"
        app.set_params({"affection": 80, "loneliness": 80}, cid)
        x = None
        for _ in range(20):
            x = A._maybe_invite(cid, time.time(), 50)
            if x:
                break
        assert x and x["status"] == "offered" and C.thread(cid)["items"][-1]["kind"] == "appoint_invite"
        assert C.thread(cid)["appoints"][0]["status"] == "offered"
        A.answer(x["id"], True)
        assert A.get(x["id"])["status"] == "set" and A.get(x["id"])["plan"]
        A.get(x["id"])["status"] = "cancelled"
        x2 = None
        for _ in range(20):
            x2 = A._maybe_invite(cid, time.time(), 50)
            if x2:
                break
        m0 = st["params"]["mood"]
        A.live(time.time() + 25 * 3600)
        assert A.get(x2["id"])["status"] == "lapsed" and st["params"]["mood"] < m0, "誘いに返事をしないと, 流れる (少し寂しがる)"
        print("invited: OK")

        # ---- 3b. 誘いやすさは, その日の機嫌・ストレス・体調で変わる (補正はしない)
        mf = A.mood_factor
        assert mf({"mood": 80}) > mf({"mood": 50}) > mf({"mood": 20}) and mf({"mood": 50, "stress": 80}) < mf({"mood": 50})
        assert mf({"mood": 50, "health": 30}) < 0.5 * mf({"mood": 50})
        # 行き先は好みで少しだけ傾く. どの性格でも幅広く (決め打ちしない)
        day = datetime(2026, 10, 18, 13, 0)
        opts = [(pid, a) for pid in places_mod.OUT_PLACES for a in A.dos_at(cid, pid)
                if phase_ok(app, a, day) and places_mod.open_state(pid, day)["open"]]
        npl = len({p for p, _ in opts})
        saved = dict(char)
        for pid in sorted(app.personas):
            char["persona_id"] = pid
            char.pop("likes", None)
            char.pop("dislikes", None)
            st["place_fun"] = {}
            got = collections.Counter(A.pick(char, st, opts)[0] for _ in range(1500))
            w = [A.place_weight(char, st, p) for p, _ in opts]
            assert max(w) / min(w) <= 1.9, (pid, max(w), min(w))
            assert len(got) >= npl * 0.9, (pid, len(got), npl)
            share = max(got.values()) / 1500.0
            per = collections.Counter(p for p, _ in opts)
            assert share < 2.2 * max(per.values()) / len(opts), (pid, got.most_common(3))
        char.clear()
        char.update(saved)
        # 一緒に行って楽しかった行き先は, 少しだけ選ばれやすい
        st["place_fun"] = {}
        w0 = A.place_weight(char, st, "aquarium")
        A.remember(cid, "aquarium", 8)
        assert A.place_weight(char, st, "aquarium") > w0 - 0.1 and A.place_weight(char, st, "aquarium") <= 1.5
        print("invite mood / places: OK (%d places)" % npl)

        # ---- 3c. 誘いに「別の日時なら」と返す: 相手は受ける / 断る / さらに別の案 (回数の上限まで)
        outcomes = collections.Counter()
        for i in range(60):
            x = {"id": "c%d" % i, "cid": cid, "t": time.time() + 2 * 86400, "place": "riverside", "do": "walk", "by": "her",
                 "status": "offered", "made": time.time()}
            A.all().append(x)
            st.pop("msg_pending", None)
            A.counter(x["id"], time.time() + 3 * 86400 + 3600 * (i % 5))
            assert x["status"] == "asked" and x["rounds"] == 1 and st["msg_pending"]["kind"] == "appoint"
            busy = i % 2 == 0
            app.scheduled_scene = (lambda c, d: dict(sched(c, d), away=True, busy=False, asleep=False)) if busy else free
            app.set_params({"affection": 60, "mood": 60}, cid)
            key, _, extra = A.reply(char, st, st["msg_pending"], time.time(), app.context(char, st, datetime.now()))
            outcomes[(busy, key)] += 1
            if key == "appoint_counter":
                assert x["status"] == "offered" and x["rounds"] == 2 and extra["when"], x
            x["status"] = "cancelled"
        app.scheduled_scene = free
        assert outcomes[(False, "appoint_yes")] > 0 and outcomes[(True, "appoint_busy")] > 0, outcomes
        assert sum(v for (b, k), v in outcomes.items() if k == "appoint_counter") > 0, outcomes
        x = {"id": "cmax", "cid": cid, "t": time.time() + 2 * 86400, "place": "riverside", "do": "walk", "by": "her",
             "status": "offered", "made": time.time(), "rounds": COUNTER_MAX}
        A.all().append(x)
        try:
            A.counter("cmax", time.time() + 3 * 86400)
            raise AssertionError("やりとりが延々続く")
        except ValueError:
            pass
        x["status"] = "cancelled"
        st.pop("msg_pending", None)
        print("counter: OK", dict(outcomes))

        # ---- 4. 当日: 会いに行く. 来る / 遅れる / 来ない
        def make(t, plan, do="walk", place="riverside"):
            x = {"id": "x%d" % random.randint(0, 1 << 30), "cid": cid, "t": t, "place": place, "do": do, "by": "me",
                 "status": "set", "made": t - 86400, "plan": dict({"noshow": False, "late": 0, "cancel_checked": True}, **plan)}
            A.all().append(x)
            A.save()
            return x

        app.set_params({"affection": 70, "mood": 70, "energy": 80, "sleepiness": 0}, cid)
        P = app.presence
        # 自分で出向く: 約束の場所への外出. 早く着けばその場で待ち, 時刻を迎えると会える
        x = make(time.time() + 3600, {})
        r = A.go(x["id"])
        assert r["status"] == "going" and P.rec()["mode"] == "out" and P.rec()["place"] == "riverside", r
        assert A.view()[-1]["here"] and A.live(time.time()) == [] and x["status"] == "set" and x.get("arrived")
        x["t"] = time.time() - 1
        A.live(time.time())
        assert x["status"] == "met" and B.mode(cid) == "meet" and st["override"]["place"] == "riverside" and P.rec()["mode"] == "none"
        assert "遅れて" not in app.log(cid)[-1]["text"], "早く着いて待っていたので遅刻ではない"
        app.act("go_home", cid)
        # 別の用事で同じ場所に来ていても会える
        app.solo.start("out", place="riverside")
        x = make(time.time() - 1, {})
        A.live(time.time())
        assert x["status"] == "met" and B.mode(cid) == "meet"
        app.act("go_home", cid)
        # 相手が遅れる: 着いて待つ (外出中のまま). 来たら会える
        x = make(time.time() - 60, {"late": 20})
        A.go(x["id"])
        A.live(time.time())
        assert x["status"] == "waiting" and P.rec()["mode"] == "out" and B.mode(cid) is None
        x["arrived"], x["t"] = time.time() - 30 * 60, time.time() - 30 * 60        # 時間どおりに着いて, 相手が 20 分遅れた
        A.live(time.time())
        assert x["status"] == "met" and B.mode(cid) == "meet" and P.rec()["mode"] == "none"
        assert "遅れて来た" in app.log(cid)[-1]["text"], app.log(cid)[-1]["text"]
        app.act("go_home", cid)
        # 相手が来ない: 待ちぼうけ (しばらく待ってあきらめる)
        x = make(time.time(), {"noshow": True})
        A.go(x["id"])
        assert A.live(time.time()) == [] and x["status"] == "set"
        out = A.live(time.time() + GIVE_UP + 1)
        assert x["status"] == "stood_up" and any("来なかった" in t for t in out) and P.rec()["mode"] == "out"
        app.come_back()
        # 出かけても, 時刻の前に家に帰れば (画面を閉じても) 約束の場所にはいない
        x = make(time.time() + 600, {})
        A.go(x["id"])
        P.rec()["since"] -= 300
        app.come_back()
        A.live(time.time() + 700)
        assert x["status"] == "set" and not x.get("arrived")
        A.live(time.time() + 600 + GRACE + 1)
        assert x["status"] == "missed"
        print("go / wait / meet / late / no-show: OK")

        # ---- 5. 体調不良のキャンセル (健康しだい)
        cancels = {"sick": 0, "well": 0}
        for k, hp in (("sick", 30), ("well", 95)):
            for _ in range(30):
                x = make(time.time() + 2 * 3600, {"cancel_checked": False})
                app.set_params({"health": hp}, cid)
                A.live(time.time())
                cancels[k] += x["status"] == "cancelled"
                x["status"] = "cancelled"
        assert cancels["sick"] > cancels["well"] and cancels["sick"] >= 10, cancels
        assert any(i["kind"] == "appoint_cancel" for i in C.load(cid)["items"])
        app.set_params({"health": 90}, cid)
        print("cancel: OK", cancels)

        # ---- 6. あなたが行かない (画面を閉じていても) → すっぽかし. 遅れて行くと少し機嫌を損ねる
        app.set_params({"trust": 60, "mood": 60}, cid)
        x = make(time.time() - GRACE - 60, {})
        A.live(time.time())
        assert x["status"] == "missed" and st["params"]["trust"] < 60
        assert any(r.get("action") == "_appoint" and "すっぽかした" in r["tell"] for r in st["reasons"])
        assert any(i["kind"] == "appoint_missed" for i in C.load(cid)["items"])
        x = make(time.time() - 20 * 60, {})
        A.go(x["id"])
        A.live(time.time())
        assert x["status"] == "met" and "遅れてしまった" in app.log(cid)[-1]["text"]
        assert any("遅れてきた" in r["tell"] for r in st["reasons"])
        app.act("go_home", cid)
        print("missed / me late: OK")

        # ---- 7. 家に行ける仲なら, 相手の家・あなたの家も約束の行き先に
        B.set_stage(cid, "visit")
        ch = {c["place"]: [d["id"] for d in c["dos"]] for c in A.choices(cid)}
        assert ch["home:" + cid] == ["visit_home"] and ch["home:me"] == ["invite_home"]
        x = make(time.time() + 300, {}, do="visit_home", place="home:" + cid)
        r = A.go(x["id"])            # 相手の家へ出向く: 約束の前後なら, 約束なしの訪問ではなく玄関先で待つ
        assert app.presence.rec()["mode"] == "out" and app.presence.rec()["place"] == "home:" + cid and B.mode(cid) is None, r
        x["t"] = time.time() - 1
        A.live(time.time())
        assert x["status"] == "met" and B.mode(cid) == "visit" and "の部屋は" in app.log(cid)[-1]["text"], app.log(cid)[-1]["text"]
        B.end()
        x = make(time.time() - 1, {}, do="invite_home", place="home:me")      # あなたの家に招く: 家にいればよい
        assert A.go(x["id"])["status"] == "here"
        A.live(time.time())
        assert x["status"] == "met" and B.mode(cid) == "guest"
        B.end()
        # 同居相手とは約束はいらない
        B.set_stage(cid, "live")
        try:
            A.propose(cid, time.time() + 7200, "riverside", "walk")
            raise AssertionError("同居相手と約束している")
        except ValueError:
            pass
        print("homes: OK")
        app.scheduled_scene = sched
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
