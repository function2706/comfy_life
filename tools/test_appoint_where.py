"""相手が約束に遅れる: 自分から連絡してくる / 「今どこ？」(core/appoint.py の _her_late_tell / where_target / where_reply).
- 相手が 10 分以上遅れるとき, 本来出る時刻のころに「◯分くらい遅れそう」と連絡してくるかを一度だけ決める
  (時間にきっちりな性格ほど連絡してくる). すっぽかすつもり・少しの遅れ・相手の家での約束では連絡しない. 閉じていても届く
- 「今どこ？」は, 相手が出向いてくる約束の 30 分前〜待ってくれる時刻まで. 画面の送る欄にもそのときだけ出る
- 返事は読んだときの様子: これから出る / 向かっている (時間どおり・遅れて) / まだ家で遅れる / もう着いている /
  来るつもりがなかった (行けないと言い, 約束はなくなる) / 何度も聞かれて (遅れていないのに) / もう会えた
- 遅れると伝わったら, あとから改めて連絡しない. 会えたときの記録に「連絡はあった」
(一時データ)

    python tools/test_appoint_where.py
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
from core.appoint import GRACE  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(7)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("今どこ")
        A, C = app.appoint, app.chat
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        traits = app.traits
        punct = {"v": None}
        app.traits = lambda c: dict(traits(c), punctual=punct["v"]) if punct["v"] is not None else traits(c)

        def make(dt_min, place="riverside", **plan):
            for y in A.all():
                if y["status"] in ("set", "waiting"):
                    y["status"] = "declined"
            t = time.time() + dt_min * 60
            x = {"id": "x%d" % random.randint(0, 1 << 30), "cid": cid, "t": t, "place": place, "do": "walk", "by": "me",
                 "status": "set", "made": t - 86400, "plan": dict({"noshow": False, "late": 0, "cancel_checked": True, "go": 30}, **plan)}
            A.all().append(x)
            A.save()
            return x

        def reset():
            st.pop("msg_pending", None)
            st["reasons"], st["contacts"] = [], []
            app.set_params({"affection": 60, "mood": 60, "trust": 60, "energy": 80, "sleepiness": 0}, cid)

        def kinds():
            return [k for g in C.thread(cid)["groups"] for k in g["kinds"]]

        def her_items(prefix):
            return [i for i in C.load(cid)["items"] if i["who"] == "her" and str(i.get("kind", "")).startswith(prefix)]

        def ask():
            n = len(her_items("appoint_where"))
            for _ in range(8):
                reset()
                C.send(cid, "where_appoint")
                st["msg_pending"]["due"] = time.time() - 1
                app.deliver_due()
                its = her_items("appoint_where")
                if len(its) > n:
                    return its[-1]
            raise AssertionError("返事が来ない: %s" % [(i["who"], i.get("kind"), i["text"][:40]) for i in C.load(cid)["items"][-6:]])

        # ---- 1. 聞けるとき (送る欄に出る = 本当に送れる)
        reset()
        x = make(40)
        assert "where_appoint" not in kinds() and A.where_target(cid) is None, "30 分より前は出さない"
        try:
            C.send(cid, "where_appoint")
            raise AssertionError("30 分より前に聞けてしまう")
        except ValueError:
            pass
        x["t"] = time.time() + 20 * 60
        assert "where_appoint" in kinds()
        x["t"] = time.time() - GRACE + 60
        assert "where_appoint" in kinds(), "待ってくれる時刻までは聞ける"
        x["t"] = time.time() - GRACE - 60
        assert "where_appoint" not in kinds(), "待ってくれる時刻を過ぎたら聞けない"
        for status in ("met", "cancelled", "missed"):
            x["t"], x["status"] = time.time() + 600, status
            assert "where_appoint" not in kinds(), status
        make(10, place="home:" + cid)
        assert "where_appoint" not in kinds(), "相手の家での約束 (相手は家にいる) では聞かない"
        make(10, place="home:me")
        assert "where_appoint" in kinds(), "あなたの家に来てもらう約束では聞ける"
        print("いつ聞けるか: OK")

        # ---- 2. 返事は読んだときの相手の様子
        cases = [("soon", dict(dt_min=25, go=10)),                      # 出るのは 15 分後: これから出る
                 ("coming", dict(dt_min=20, go=30)),                    # もう出た. 時間どおり
                 ("notyet", dict(dt_min=20, go=10, late=30)),           # まだ家. 30 分遅れる
                 ("coming_late", dict(dt_min=-5, go=30, late=20)),      # 向かっている. 遅れている
                 ("here", dict(dt_min=-20, go=30))]                    # もう着いている
        for want, kw in cases:
            dt_min = kw.pop("dt_min")
            x = make(dt_min, **kw)
            it = ask()
            assert it["kind"] == "appoint_where_" + want, (want, it)
            assert "{" not in it["text"], it
            if want in ("notyet", "coming_late"):
                assert x["plan"].get("told"), "遅れると伝わった"
            print("  %s: %s" % (want, it["text"]))
        x = make(10, noshow=True)
        it = ask()
        assert it["kind"] == "appoint_where_cant" and x["status"] == "cancelled", (it, x["status"])
        assert "where_appoint" not in kinds()
        print("  cant: %s" % it["text"])
        x = make(20, go=30)
        assert [ask()["kind"] for _ in range(3)] == ["appoint_where_coming"] * 2 + ["appoint_where_much"]
        x = make(-5, go=30, late=20)
        assert [ask()["kind"] for _ in range(3)] == ["appoint_where_coming_late"] * 3, "遅れている側は, 何度聞かれても文句を言わない"
        x = make(20, go=30)
        reset()
        C.send(cid, "where_appoint")
        x["status"] = "met"
        st["msg_pending"]["due"] = time.time() - 1
        app.deliver_due()
        assert her_items("appoint_where")[-1]["kind"] == "appoint_where_gone"
        print("返事: OK")

        # ---- 3. 相手から「遅れそう」と連絡してくる (一度だけ. 性格しだい)
        def trial(p, **kw):
            punct["v"] = p
            x = make(kw.pop("dt_min", 10), **dict({"late": 30, "go": 20}, **kw))
            n = len(her_items("appoint_her_late"))
            out = A.live(time.time())
            A.live(time.time())                       # 二度目は何もしない
            m = len(her_items("appoint_her_late")) - n
            assert m in (0, 1) and (m == 1) == bool(x["plan"].get("told")), (m, x["plan"])
            assert (m == 1) == any("遅れそう" in o for o in out), out
            return m

        hi = sum(trial(0.95) for _ in range(120))
        lo = sum(trial(0.4) for _ in range(120))
        print("連絡してきた: きっちり %d/120, ルーズ %d/120" % (hi, lo))
        assert hi > lo + 20 and hi > 80, (hi, lo)
        assert sum(trial(0.95, late=5) for _ in range(30)) == 0, "少しの遅れでは連絡しない"
        assert sum(trial(0.95, noshow=True, late=0) for _ in range(30)) == 0, "すっぽかすつもりなら連絡しない"
        assert sum(trial(0.95, place="home:" + cid) for _ in range(30)) == 0, "相手の家での約束では連絡しない"
        punct["v"] = 0.95
        x = make(120, late=30, go=20)                     # まだ出る時刻の前: 連絡しない
        A.live(time.time())
        assert "told" not in x["plan"]
        x = make(10, late=30, go=20, told=True)           # もう伝わっている (今どこ？で・「こっちも遅れる」で)
        n = len(her_items("appoint_her_late"))
        A.live(time.time())
        assert len(her_items("appoint_her_late")) == n
        # 閉じていても届く (相手からの連絡)
        x = make(10, late=30, go=20)
        punct["v"] = 0.95
        for _ in range(20):
            x["plan"].pop("told", None)
            A.live(time.time(), contact_only=True)
            if x["plan"]["told"]:
                break
        assert x["plan"]["told"] and "{" not in her_items("appoint_her_late")[-1]["text"]
        print("  連絡: %s" % her_items("appoint_her_late")[-1]["text"])
        # 会えたときの記録に「連絡はあった」
        x = make(-25, late=20, go=30, told=True)
        x["status"] = "waiting"
        A.go(x["id"])
        x["status"] = "waiting"
        A.live(time.time())
        assert x["status"] == "met", x["status"]
        assert any("遅れると連絡はあった" in e.get("text", "") for e in app.log(cid)[-3:]), [e.get("text", "")[:60] for e in app.log(cid)[-3:]]
        print("連絡: OK")

        # ---- 4. 約束で会えたら, 疲れていても約束のお出かけを断らない (以前は「今日は人混みはちょっと……」で断り,
        #         あなたの外出だけが終わって家に戻っていた. 相手が遅れて来たときに実機で起きた)
        for do, place in (("shopping", "mall"), ("walk", "park"), ("cafe", "cafe")):
            if app.bonds.with_rec():
                app.bonds.end()
            st["override"] = None
            x = make(-25, place=place, late=20, go=30)
            x["do"] = do
            A.go(x["id"])
            x["status"] = "waiting"
            app.set_params({"energy": 10}, cid)
            ev = A.live(time.time())
            # 画面の知らせ: 遅れて来た注のあとに, 相手のひとことも出る (以前は注の 1 行だけで, ひとことが見えなかった)
            e = next((m for m in ev if "遅れて来た" in m), "")
            assert e and not (e.startswith("（") and e.endswith("）")), ev
            ov = st.get("override") or {}
            assert x["status"] == "met" and (app.bonds.with_rec() or {}).get("mode") == "meet" and ov.get("outing") and ov.get("place") == place, \
                (do, x["status"], app.bonds.with_rec(), ov, [e.get("text", "")[:40] for e in app.log(cid)[-2:]])
        print("疲れていても約束のお出かけは始まる: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
