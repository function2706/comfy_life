"""外出先から操作する (A16) の残り 2 つ: 家の画面を閉じている間の, 同居相手との連絡と, 相手からの約束の連絡.

1. 同居相手: 閉じている間, 行動パターン・予定の「いまの枠」が仕事・外出なら, あなたは家にいない扱い. スマホ用の入り口から
   メッセージを送れ, 閉じている間の進行 (core/remote.py) で相手からも届く. 家にいる枠・家の画面を開いている・家の画面から
   見たとき・時刻を指定した計算 (閉じていた間のまとめ) は, 今までどおり「そばにいる」
2. 相手からの約束の連絡 (日を変えたい・取りやめ・誘い) は, 閉じている間の進行でも届く. あなたの側の判定 (すっぽかし・
   返事の期限切れ) は進めない (開いたときに, 今までどおり)
(一時データ)

    python tools/test_remote_rest.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, store  # noqa: E402
from core.offline import DAY_KEYS  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(11)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    real_random = random.random
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("閉じている間の残り")
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        R, C, B, A = app.remote, app.chat, app.bonds, app.appoint
        p = app.presence.rec()
        now = time.time()
        t0 = now - 3 * 3600                          # 3 時間前に家の画面を閉じた

        def closed():
            p["mode"], p["beat"], p["input"], p["since"] = "none", t0, t0, 0

        def routine(do, enabled=True, **kw):         # 一日じゅう同じ枠の行動パターン (いまの時刻によらない)
            app.save_settings({"offline": {"enabled": enabled, "days": {d: [dict({"at": "00:00", "do": do}, **kw)] for d in DAY_KEYS}}})

        def sure(fn):
            random.random = lambda: 0.0
            try:
                return fn()
            finally:
                random.random = real_random

        her = lambda: [x for x in C.load(cid)["items"] if x["who"] == "her"]      # noqa: E731

        # ================= 1. 同居相手
        B.set_stage(cid, "live")
        closed()
        assert B.living() == cid
        # 枠の種類 × 見ている所の総当たり
        AWAY = [("work", {}), ("parttime", {}), ("out", {"place": "park"}), ("jog", {}), ("meal", {"how": "out", "place": "teishoku"}),
                ("meal", {"how": "buy", "place": "convenience"})]
        HOME = [("rest", {}), ("home", {}), ("sleep", {}), ("chores", {}), ("meal", {"how": "cook"}), ("read", {}), ("practice", {})]
        n = 0
        for do, kw in AWAY + HOME:
            routine(do, **kw)
            away = (do, kw) in AWAY
            assert app.offline.away_closed(now) == away, (do, kw)
            app.via.phone = True
            assert B.together(cid) == (not away), ("スマホ用の入り口", do)
            assert (cid in [c["id"] for c in app._contacts_view()]) == away, do
            assert B.together(cid, now - 600) is True, "時刻を指定した計算は今までどおり"
            app.via.phone = False
            assert B.together(cid) is True, ("家の画面から見たときは今までどおり", do)
            R.active = True
            assert B.together(cid) == (not away), ("閉じている間の進行", do)
            R.active = False
            n += 1
        # 家の画面を開いている (心拍が新しい): 枠によらず, そばにいる
        routine("work")
        p["beat"] = p["input"] = now - 20
        app.via.phone = True
        assert B.together(cid) is True and not app.offline.away_closed(now)
        # 閉じてから間もない (まとめの対象にならない短さ): 家にいるまま
        p["beat"] = p["input"] = now - 10 * 60
        assert not app.offline.away_closed(now) and B.together(cid) is True
        # 行動パターンがオフで予定も無い: 家にいるまま
        closed()
        routine("work", enabled=False)
        assert not app.offline.away_closed(now) and B.together(cid) is True
        app.via.phone = False
        print("同居相手: 枠 %d 通り × 見ている所 4 つ OK" % n)

        # スマホ用の入り口から送れる・在席は動かない. 家にいる枠では送れない
        routine("work")
        app.via.phone = True
        st["msg_pending"] = None
        n0 = len(C.load(cid)["items"])
        C.send(cid, "ask_how")
        assert len(C.load(cid)["items"]) == n0 + 1 and st.get("msg_pending") and p["beat"] == t0, "仕事の枠: 送れる"
        routine("rest")
        st["msg_pending"] = None
        try:
            C.send(cid, "ask_how")
            raise AssertionError("家にいる枠では, 今までどおり送れない")
        except ValueError:
            pass
        app.via.phone = False

        # 閉じている間の進行: 仕事の枠なら, 同居相手からもメッセージが届く. 家にいる枠では届かない
        app.save_settings({"remote": {"live": True}})

        def ready():
            st["approach"], st["ap_quiet_until"], st["ap_last"], st["msg_pending"] = None, 0, {}, None
            st.pop("ap_ignored", None)
            st["ap_check"] = now - 600
            app.set_params({"affection": 75, "mood": 65, "loneliness": 70, "boredom": 60}, cid)
            d = C.load(cid)
            d["items"] = []
            C.save(cid, d)
        routine("rest")
        ready()
        sure(lambda: R.step(now))
        assert not her(), "家にいる枠: 届かない (そばにいる)"
        routine("work")
        ready()
        sure(lambda: R.step(now))
        assert her() and p["beat"] == t0, "仕事の枠: 同居相手からも届く"
        print("同居相手: スマホから送れる・相手からも届く OK")

        # ================= 2. 相手からの約束の連絡
        B.set_stage(cid, "contact")
        routine("rest")
        app.set_params({"affection": 70, "mood": 60, "trust": 60}, cid)

        def appt(**kw):
            x = dict({"id": "t%d" % len(A.all()), "cid": cid, "t": now + 10 * 3600, "place": "park", "do": "walk", "by": "me",
                      "status": "set", "made": now - 3600, "plan": {}}, **kw)
            A.all().append(x)
            return x

        def clear():
            del A.all()[:]
            ready()
            p["appoint_check"] = now

        # 2-1. 自分の都合で日を変えたい (前の日ごろ)
        clear()
        x = appt(plan={"move": True})
        R.step(now)
        assert x["status"] == "offered" and x["by"] == "her" and [i for i in her() if i["kind"] == "appoint_move_mine"], x
        assert R.news and R.news[-1]["cid"] == cid, "通知の控えに入る"
        # 2-2. 取りやめ (3 時間前)
        clear()
        x = appt(t=now + 2 * 3600)
        app.set_params({"health": 30}, cid)     # 体調不良の取りやめ (くじを全部当てると, 気分の取りやめは連絡なしのすっぽかしになる)
        sure(lambda: R.step(now))
        app.set_params({"health": 90}, cid)
        assert x["status"] == "cancelled" and [i for i in her() if i["kind"] == "appoint_cancel"], x
        # 2-3. 誘い
        clear()
        p["appoint_check"] = now - 600
        sure(lambda: R.step(now))
        offered = [y for y in A.all() if y["status"] == "offered" and y.get("by") == "her"]
        assert offered and her(), "誘いが届く"
        # 2-4. あなたの側の判定は進めない: 時刻を過ぎた約束 (すっぽかし)・期限の切れた返事待ち・約束の時刻のまわり
        clear()
        late = appt(t=now - 2 * 3600)
        asked = appt(status="asked", made=now - 30 * 3600, t=now + 5 * 3600)
        near = appt(t=now + 5 * 60)
        mood0 = st["params"]["mood"]
        for _ in range(3):
            sure(lambda: R.step(now))
        assert late["status"] == "set" and asked["status"] == "asked" and near["status"] == "set", (late, asked, near)
        assert st["params"]["mood"] >= mood0 - 0.01 and not [i for i in her() if (i.get("kind") or "").startswith("appoint")]
        # 開いたとき (今までどおりの判定) に進む
        A.live(now)
        assert asked["status"] == "lapsed" and late["status"] != "set", (asked["status"], late["status"])
        # 2-5. 設定がオフなら何もしない
        clear()
        app.save_settings({"remote": {"live": False}})
        x = appt(plan={"move": True})
        R.step(now)
        assert x["status"] == "set" and not her()
        print("相手からの約束の連絡: 日を変えたい・取りやめ・誘いが届く / あなたの側の判定は開いたとき OK")
        print("ALL OK")
    finally:
        random.random = real_random
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
