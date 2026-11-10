"""家の画面を閉じている間も, 相手の側を時間どおりに進める (A16 の 2 段目. core/remote.py).
設定 (settings.remote.live) がオンのとき, サーバが 1 分おきに Remote.step を呼ぶ.
- 設定がオフなら何もしない (今までどおり)
- 家の画面が開いている (心拍が新しい) 間は何もしない (そちらが進める)
- 閉じている間: 離れている相手からのメッセージが, その時刻に届く. 在席 (心拍) は動かない. 進めた時間を覚える
- 間が空いたら (PC のスリープ), 続きにしない (空いた間は, まとめの計算に任せる)
- 返事待ちの返信も届く
- 返事の待ち時間は届いた時から: 返さなければ時間切れ (返事がなかった). 予定の「自動の応答」があれば, 自動の返事
- 届いたものの控え (通知・スマホの取り寄せ用) に入る. まとめの計算でさかのぼって入るものは入らない
- 閉じていた間のまとめのメッセージは, 進めた時間を除いて数える (二重に届かない)
(一時データ)

    python tools/test_remote_live.py
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
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(16)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    real_random = random.random
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("閉じている間")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        R, C = app.remote, app.chat
        p = app.presence.rec()
        now = time.time()
        t0 = now - 3 * 3600                          # 3 時間前に家の画面を閉じた
        p["mode"], p["beat"], p["input"] = "none", t0, t0

        def ready():
            st["approach"], st["ap_quiet_until"], st["ap_last"], st["msg_pending"] = None, 0, {}, None
            st.pop("ap_ignored", None)
            app.set_params({"affection": 75, "mood": 65, "loneliness": 70, "boredom": 60}, cid)

        def sure(fn):                                # 抽せんを必ず当てる
            random.random = lambda: 0.0
            try:
                return fn()
            finally:
                random.random = real_random

        her = lambda: [x for x in C.load(cid)["items"] if x["who"] == "her"]      # noqa: E731

        # ---- 1. 設定がオフ: 何もしない
        ready()
        st["ap_check"] = now - 600
        assert sure(lambda: R.step(now)) == [] and not her() and not p.get("remote_spans"), "オフなら今までどおり"

        # ---- 2. オン・家の画面が開いている: 何もしない
        app.save_settings({"remote": {"live": True}})
        p["beat"] = now - 30
        assert sure(lambda: R.step(now)) == [] and not her() and not p.get("remote_spans")
        p["beat"] = t0

        # ---- 3. オン・閉じている: その時刻にメッセージが届く. 在席は動かない
        st["ap_check"] = now - 600
        sure(lambda: R.step(now))
        hs = her()
        assert len(hs) == 1 and abs(hs[0]["t"] - now) < 2, hs
        ap = st.get("approach")
        assert ap and (app.presence.find(ap["id"]) or {}).get("apart") and ap["until"] > now + 40 * 60, ap
        assert p["beat"] == t0 and p["input"] == t0 and app.presence.at(now) == "gone", "在席は動かない"
        assert p["remote_spans"] == [[now, now]], p["remote_spans"]
        assert R.news and R.news[-1]["cid"] == cid and R.news[-1]["text"], "届いたものの控えに入る"
        assert R.news_since(R.news[-1]["id"]) == [] and R.news_since(0)
        assert not R.active

        # ---- 4. 続けて進める: 同じ区間が延びる. 返事待ちの間は, 次を送ってこない
        sure(lambda: R.step(now + 60))
        sure(lambda: R.step(now + 120))
        assert p["remote_spans"] == [[now, now + 120]] and len(her()) == 1
        # 間が空いた (PC のスリープ): 続きにしない
        R.step(now + 120 + 3600)
        assert len(p["remote_spans"]) == 2 and p["remote_spans"][1] == [now + 3720, now + 3720], p["remote_spans"]
        assert R.covered(now + 60) and not R.covered(now + 1800)
        assert abs(R.uncovered(now, now + 3720) - 3600) < 1

        # ---- 5. 待ち時間は届いた時から: 返さなければ時間切れ
        until = st["approach"]["until"]
        n_news = len(R.news)
        R.step(until + 1)
        assert not st.get("approach") and st.get("ap_ignored"), "返事がなかった"
        assert len(R.news) == n_news, "時間切れは通知しない"

        # ---- 6. 予定の「自動の応答」があれば, 待ち時間が切れたときに自動の返事
        ready()
        p["remote_spans"] = []
        st["ap_check"] = now - 600
        sure(lambda: R.step(now))
        ap = st["approach"]
        from core import msgreply
        pol = msgreply.options(ap["id"], ap.get("why"))[0]["id"]
        app.planner.rec()["auto"]["reply"] = pol
        n_me = len([x for x in C.load(cid)["items"] if x["who"] == "me"])
        R.step(ap["until"] + 1)
        mine = [x for x in C.load(cid)["items"] if x["who"] == "me"]
        assert len(mine) == n_me + 1 and "自動" in mine[-1]["text"], mine[-1:]
        assert not st.get("approach") and not st.get("ap_ignored"), "時間切れにはしない"
        app.planner.rec()["auto"]["reply"] = None

        # ---- 7. 返事待ちの返信も届く
        ready()
        t = ap["until"] + 4000
        app.via.phone = True
        C.send(cid, "ask_how")
        app.via.phone = False
        pend = st["msg_pending"]
        pend["reply"], pend["unread"] = True, False
        out = R.step(max(t, pend["due"] + 1))
        assert out and out[0]["cid"] == cid and not st.get("msg_pending"), out
        assert p["beat"] == t0

        # ---- 8. 閉じていた間のまとめのメッセージ: 進めた時間は除く
        ready()
        a, b = now - 6 * 3600, now
        p["remote_spans"] = [[a, b]]
        assert sure(lambda: app.offline._messages(a, b)) == [], "ずっと進めていたなら, まとめでは届かない"
        assert not st.get("approach")
        p["remote_spans"] = [[a, a + 5.8 * 3600]]
        assert sure(lambda: app.offline._messages(a, b)) == [], "残りが 30 分に満たなければ届かない"
        p["remote_spans"] = [[a, a + 3 * 3600]]      # 後ろの 3 時間は進めていない (スリープしていた)
        ms = sure(lambda: app.offline._messages(a, b))
        assert len(ms) == 1 and ms[0]["t"] >= a + 3 * 3600 - 1, ms
        n_news = len(R.news)
        assert len(R.news) == n_news and all(n["t"] != ms[0]["t"] for n in R.news), "さかのぼって入るものは控えに入れない"
        ready()
        p["remote_spans"] = []
        assert len(sure(lambda: app.offline._messages(a, b))) == 1, "進めていなければ今までどおり"
        print("ok: 閉じている間の進行 (届く・在席は動かない・待ち時間・自動の応答・まとめと二重にしない)")
    finally:
        random.random = real_random
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
