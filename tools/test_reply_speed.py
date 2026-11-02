"""メッセージの返信の早さ (core/replyspeed.py): 性格の早さ・場面・依存度・機嫌・言い争いで, すぐ返る割合と待ちが変わる.
最初の 1 通でもすぐ返ることがある. 近い仲でもときどき後回し (一様に早くならない). 実際の送信で返信の予定が入る (一時データ).

    python tools/test_reply_speed.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, replyspeed as R, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def summary(traits, place="home", aff=60, mood=55, dv=0.0, dep=0.0, close=0.2, n=3000, seed=3, **kw):
    rnd = random.Random(seed)
    xs = [R.plan(traits, place, dv, dep, aff, mood, close, rnd=rnd, **kw) for _ in range(n)]
    quick = sum(1 for s, h in xs if h) / float(n)
    ss = sorted(s for s, _ in xs)
    return quick, ss[n // 2] / 60.0, sum(1 for s in ss if s >= 3600) / float(n)


def main():
    # ---- 1. 性格の早さ: 早い人ほどすぐ返り, 待ちも短い
    fast, slow = summary({"reply": 1.5}), summary({"reply": 0.5})
    print("早い人 %s / 遅い人 %s" % (fast, slow))
    assert fast[0] > slow[0] * 2 and fast[1] < slow[1] / 2

    # ---- 2. 場面: 家でくつろいでいる > 移動中 > 外
    h, m, o = summary({}, "home"), summary({}, "moving"), summary({}, "out")
    assert h[0] > m[0] > o[0] and h[1] < o[1], (h, m, o)

    # ---- 3. 依存度が高いと早く, 低いと遅い. 機嫌が悪い・言い争いのあと・連絡が多いと遅い
    base = summary({})
    hi, lo = summary({}, dep=0.8), summary({}, dep=-0.6)
    assert hi[0] > base[0] > lo[0] and hi[1] < base[1] < lo[1]
    for kw in ({"mood": 30}, {"fight": True}, {"many": True}, {"aff": 30}):
        x = summary({}, **kw)
        assert x[0] < base[0] and x[1] > base[1], (kw, x, base)
    print("状態ごと: OK")

    # ---- 4. 依存度が高くても毎回すぐではない (上限). 近い仲でもときどき後回しで, 1 時間以上空くことが増える
    top = summary({"reply": 1.6}, dep=1.0, dv=1.0, aff=90)
    assert top[0] <= 0.5 + 0.02
    near, mid = summary({}, close=0.9, seed=5), summary({}, close=0.4, seed=5)
    assert near[2] > mid[2], (near, mid)
    # 待ちのばらつき: 事務的 (狭い) は 1 時間以上空くことがほぼ無い. 気ままな人 (広い) はたまに
    assert summary({"reply": 1.0, "reply_spread": 0.6})[2] < summary({"reply": 1.0, "reply_spread": 1.3})[2]
    print("上限・後回し・ばらつき: OK")

    # ---- 5. 実際の送信: 最初の 1 通でも, すぐ返ることも時間がかかることもある. 性格の値はプリセットに入っている
    random.seed(4)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("返信")
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        assert all("reply" in (app.personas.get(p) or {}).get("traits", {}) for p in app.personas), "全ての性格に返信の早さ"
        st["override"] = {"activity": "relax", "label": "くつろいでいる", "location": "自宅", "until": time.time() + 9e6}
        dues = []
        for _ in range(60):
            st.pop("msg_pending", None)
            st["contacts"], st["phone_until"] = [], 0
            st.pop("nori", None)
            app.chat.send(cid, "smalltalk")
            dues.append(st["msg_pending"]["due"] - time.time())
        q = sum(1 for d in dues if d <= 180)
        print("60 通中, 3 分以内 %d 通 / 最長 %.0f 分" % (q, max(dues) / 60))
        assert 3 <= q <= 45 and max(dues) > 600
        print("送信: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
