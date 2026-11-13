"""お礼「話してくれた」の心当たり (残件 F8).
以前は, 心当たりを残すのが誕生日を教えてもらったときだけで, 近況や出来事を話してもらった直後にお礼を言っても
「何のお礼？ 覚えがない」と返っていた.
- 「最近どう？」に出来事を話してくれた → 心当たりが残る. 特に変わりないとき (話していない) は残らない
- 相手の「話を聞かせてくれた」メッセージに返した → 残る
- 「もっと聞かせて」「ほんとに？」がよく効いた (話してくれた) → 残る. ふつう・よくなかったときは残らない
- 残った心当たりには, お礼が効く (thanks_pick が「何のお礼？」にならない)
(一時データ)

    python tools/test_told_thanks.py
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
from core import engine, react, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(8)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    judge = react.judge
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("話してくれた")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        app.set_params({"affection": 70, "mood": 60, "trust": 60}, cid)
        told = lambda: [f for f in st.get("favors") or [] if f["what"] == "told"]      # noqa: E731

        def ask_how():
            st["msg_pending"] = None
            app.chat.send(cid, "ask_how")
            pend = st["msg_pending"]
            pend["reply"], pend["unread"] = True, False
            app.deliver_due(pend["due"] + 1)

        # ---- 1. 「最近どう？」: 話すことが無ければ残らない. 出来事を話してくれたら残る
        for r in app.life.reasons(st, time.time()):
            r["told"] = True
        ask_how()
        assert not told(), "特に変わりないときは残らない"
        app.life.add_reason(st, "event", "bad", "友だちとケンカした", time.time(), told=False)
        ask_how()
        assert len(told()) == 1, st.get("favors")
        r = app.manners.thanks_pick(st, time.time() + 60, "told", char)
        assert "what" not in str(r), "話してくれたことへのお礼が「何のお礼？」にならない: %r" % (r,)

        # ---- 2. 相手のメッセージへの返し
        now = time.time()
        for kind, res, tone, want in (("re_more", "neutral", "bored", 0), ("re_more", "bad", "bored", 0), ("re_ok", "good", "happy", 0),
                                      ("re_more", "good", "bored", 1), ("re_really", "good", "happy", 1), ("re_ok", "neutral", "news", 1)):
            st["favors"] = []
            react.judge = lambda *a, _r=res, **k: (_r, 0.0)
            react.land(app, char, st, kind, {"to": {"tone": tone, "t": now - 60}, "sent": now}, now)
            assert len(told()) == want, (kind, res, tone, st["favors"])
        print("ok: 話してくれた、の心当たり (最近どう？・話を聞かせてくれた・もっと聞かせて)")
    finally:
        react.judge = judge
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
