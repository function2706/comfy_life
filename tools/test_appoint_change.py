"""決まった約束を, こちらから変える・取りやめる (1.6.0. core/appoint.py の change / cancel / change_reply).
- 変えたいと伝えると, 返事は時間差. 返事が来るまでは, もとの約束のまま
- 応じるか・受け取り方は, 相手のその時間の予定・伝えた時期 (直前ほど重い)・何回目か・お互いさま (相手が最近ずらした)・
  仲や機嫌・性格しだい. 前もって一度だけなら, たいていすんなり (何も変わらない)
- その時間に予定があれば, 別の時間を返すか, もとのままがいいと言う (もとの約束は残る)
- 取りやめは伝えた時点で決まる (断れない). 受け取り方は同じように変わる. 引っかかったら, 謝れる心当たりになる
- 約束の返事を待っている間に別のメッセージを送っても, 約束の返事は消えない
(一時データ)

    python tools/test_appoint_change.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
import uuid
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
GOOD = ("appoint_change_fine", "appoint_change_glad")


def main():
    random.seed(11)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("約束の変更")
        A, C = app.appoint, app.chat
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        sched = app.scheduled_scene
        free = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)   # noqa: E731
        app.scheduled_scene = free

        def day_at(days, hour=13):
            return datetime.fromtimestamp(time.time() + days * 86400).replace(hour=hour, minute=0, second=0, microsecond=0).timestamp()

        def mk(t, **kw):
            for y in A.all():
                if y["status"] in ("set", "asked", "offered", "waiting"):
                    y["status"] = "declined"
            x = dict({"id": uuid.uuid4().hex[:8], "cid": cid, "t": t, "place": "riverside", "do": "walk", "by": "me",
                      "status": "set", "made": time.time()}, **kw)
            x["plan"] = A._plan(char, st, x)
            A.all().append(x)
            return x

        def reset(**params):
            st.pop("msg_pending", None)
            st["my_moves"], st["her_moved"], st["contacts"] = [], 0, []
            st["reasons"] = []
            app.set_params(dict({"affection": 60, "mood": 60, "loneliness": 40}, **params), cid)

        def land():
            st["msg_pending"]["due"] = time.time() - 1
            app.deliver_due()
            return [i for i in C.load(cid)["items"] if i["who"] == "her" and i["kind"].startswith("appoint_")][-1]["kind"]   # 後ろに切り上げのひとことが付くことも

        # ---- 1. 決まりごと
        reset()
        x = mk(day_at(4))
        for bad in ((x["t"], None, None), (time.time() + 600, None, None), (time.time() + 15 * 86400, None, None)):
            try:
                A.change(x["id"], *bad)
                raise AssertionError("変えられてしまう: %s" % (bad,))
            except ValueError:
                pass
        x["status"] = "waiting"
        try:
            A.change(x["id"], day_at(5))
            raise AssertionError("着いて待っているのに変えられる")
        except ValueError as e:
            assert "待って" in str(e), e
        x["status"] = "set"
        y = mk(time.time() + 3600, now=True)
        assert not A.row(y)["can_change"] and A.row(y)["can_cancel"]
        try:
            A.change(y["id"], day_at(5))
            raise AssertionError("急な約束の日時を動かせる")
        except ValueError:
            pass
        print("決まりごと: OK")

        # ---- 2. 返事が来るまではもとのまま. 前もって一度だけなら, たいていすんなり
        reset()
        x = mk(day_at(4))
        t0 = x["t"]
        r = A.change(x["id"], day_at(5, 15))
        assert r["changing"] and A.get(x["id"])["t"] == t0 and st["msg_pending"]["kind"] == "appoint_change"
        k = land()
        x = A.get(x["id"])
        assert k.startswith("appoint_change_") and not x.get("change"), k
        if k in GOOD or k.startswith("appoint_change_s"):
            assert x["t"] == day_at(5, 15) and x["status"] == "set" and x.get("changes") == 1
            assert any(i["who"] == "sys" and "約束を変えた" in i["text"] for i in C.load(cid)["items"])
        print("返事は時間差・応じれば変わる: OK |", k)

        def rate(days, hours_before=None, n=60, changes=0, moves=0, mutual=False, busy=False, **params):
            got = {}
            for _ in range(n):
                reset(**params)
                t = time.time() + hours_before * 3600 if hours_before else day_at(days)
                x = mk(t, changes=changes)
                st["my_moves"] = [time.time() - 86400 * (i + 1) for i in range(moves)]
                if mutual:
                    st["her_moved"] = time.time() - 3 * 86400
                nt = t + 2 * 3600 if hours_before else t + 86400
                if busy:                  # 変えたい時間だけ予定がある (ほかの時間は空いている)
                    app.scheduled_scene = lambda c, d, nt=nt: dict(sched(c, d), away=abs(d.timestamp() - nt) < 1800, busy=False, asleep=False)
                A.change(x["id"], nt)
                k = land()
                app.scheduled_scene = free
                got[k] = got.get(k, 0) + 1
            return got

        def good(g):
            return sum(v for k, v in g.items() if k in GOOD) / float(sum(g.values()))

        # ---- 3. 伝えた時期: 何日も前ならすんなり, 当日の直前は悪く取られやすい
        early, late = rate(4), rate(0, hours_before=4)
        assert good(early) > 0.75 and good(late) < 0.35, (early, late)
        assert sum(v for k, v in late.items() if "sour_late" in k) > 0, late
        print("伝えた時期: OK | 4日前 すんなり %.2f / 当日 %.2f" % (good(early), good(late)))

        # ---- 4. 何回目か: 何度も動かすと悪くなる. お互いさまなら, すんなり応じやすい
        again = rate(2, changes=1, moves=2)
        base1 = rate(2)
        assert good(again) < good(base1) - 0.2, (again, base1)
        assert sum(v for k, v in again.items() if "sour_again" in k) > 0, again
        near, mut1 = rate(0, hours_before=20), rate(0, hours_before=20, mutual=True)     # 前日: ふつうは少し残念がる
        assert good(mut1) > good(near) + 0.3, (mut1, near)
        print("回数・お互いさま: OK | 2日前 %.2f / 何度も %.2f | 前日 %.2f / お互いさまなら %.2f" % (good(base1), good(again), good(near), good(mut1)))

        # ---- 5. 仲と機嫌: 浅い仲・機嫌が悪いと, 同じ時期でも悪く取られやすい
        cold = rate(2, affection=30, mood=30)
        assert good(cold) < good(base1) - 0.15, (cold, base1)
        print("仲と機嫌: OK | ふつう %.2f / 冷えている %.2f" % (good(base1), good(cold)))

        # ---- 6. その時間に予定がある: 別の時間を返すか, もとのままがいいと言う (もとの約束は残る)
        g = rate(4, n=30, busy=True)
        assert set(g) <= {"appoint_change_counter", "appoint_change_keep_busy"} and g.get("appoint_change_counter"), g
        reset()
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=True, busy=False, asleep=False)     # どの時間も空いていない
        for _ in range(20):
            reset()
            x = mk(day_at(4))
            t0 = x["t"]
            A.change(x["id"], t0 + 86400)
            if land() == "appoint_change_keep_busy":
                assert A.get(x["id"])["status"] == "set" and A.get(x["id"])["t"] == t0
                break
        app.scheduled_scene = free
        print("予定がある: OK |", g)

        # ---- 7. 取りやめ: 伝えた時点で決まる. 受け取り方は時期しだい. 引っかかれば謝れる心当たりに
        def cancel_rate(days=None, hours_before=None, n=60, again=0):
            got = {}
            for _ in range(n):
                reset()
                st["my_moves"] = [time.time() - 86400 * (i + 1) for i in range(again)]
                x = mk(time.time() + hours_before * 3600 if hours_before else day_at(days))
                A.cancel(x["id"])
                assert A.get(x["id"])["status"] == "cancelled"
                k = land()
                got[k] = got.get(k, 0) + 1
                if k in ("appoint_cancel_sour_late", "appoint_cancel_hurt"):
                    assert any("取りやめ" in r.get("tell", "") for r in st.get("reasons") or []), st.get("reasons")
            return got
        ce, cl = cancel_rate(days=5), cancel_rate(hours_before=3)
        fine = lambda g: g.get("appoint_cancel_fine", 0) / float(sum(g.values()))   # noqa: E731
        assert fine(ce) > 0.3 and set(ce) <= {"appoint_cancel_fine", "appoint_cancel_sad"} and fine(cl) < 0.1, (ce, cl)
        cr = cancel_rate(days=5, n=30, again=3)
        assert sum(v for k, v in cr.items() if "sour" in k or "hurt" in k) > 15, cr
        print("取りやめ: OK | 5日前 %s / 3時間前 %s / 続けて %s" % (ce, cl, cr))

        # ---- 8. 約束の返事を待っている間に別のメッセージ: 約束の返事も届く
        reset()
        x = mk(day_at(4))
        t_sent = time.time() - 1
        A.change(x["id"], day_at(5))
        C.send(cid, "smalltalk")
        pend = st.get("msg_pending") or {}
        if pend.get("kind") != "appoint_change":
            assert pend.get("appoint_first", {}).get("kind") == "appoint_change", pend
            pend["due"] = time.time() - 1
            app.deliver_due()
            kinds = [i["kind"] for i in C.load(cid)["items"] if i["who"] == "her" and i["t"] >= t_sent]
            assert any(k.startswith("appoint_change_") for k in kinds) and "smalltalk" in kinds, kinds
            print("返事が二つ: OK |", kinds)
        else:
            print("返事が二つ: (送れなかったので飛ばした)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK")


if __name__ == "__main__":
    main()
