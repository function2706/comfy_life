"""相手のメッセージへの返し (1.6.0. core/react.py) と, 返さないことの重さ.
- 相手の最後のメッセージに返していないときだけ「返す」が出る (「答える」は問いかけのときだけ)
- 何の話か (向き) と返し方の合い方: うれしい話に「よかったね」, 沈んだ話に「大変だったね」, 問いかけに「答える」が効きやすく,
  外すと悪い (謝れる心当たり). 決め打ちではない (性格・機嫌・揺らぎ). 返事を待っていた話に遅れて返すと響きにくい
- 「了解」で話が終わるのは自然: 相手が返さないこともあるが, 受け取り方は決まる
- 相手から来たメッセージ (働きかけ) にも, 同じ返し方で返す (以前の 4 択の代わり. 相手の返しは時間差)
- 大事な話にスタンプだけだと, 軽く流されたと受け取られやすい (用件の連絡なら, スタンプで十分)
- 働きかけを既読のまま放っておくと, 起きている時間に応じて少しずつ重くなる (上限あり). 遅れてでも返せば一部戻る
- 相手の問いかけを既読のまま放っておくと, 少し気にする. 以前のセーブの古いメッセージは数えない
(一時データ)

    python tools/test_react.py
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
from core import engine, react as R, store  # noqa: E402
from testclock import fix_noon, landed  # noqa: E402

fix_noon(engine)


def main():
    random.seed(7)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("返し")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        st, char = app.state(cid), app.char(cid)
        C = app.chat

        def reset(**params):
            st.pop("msg_pending", None)
            st["approach"] = None
            st["contacts"], st["reasons"] = [], []
            for k in ("ap_ignored", "await_ignored"):
                st.pop(k, None)
            app.set_params(dict({"mood": 60, "affection": 60, "trust": 50, "loneliness": 40}, **params), cid)

        def her(kind, text, t=None, **kw):
            return C.add(cid, "her", text, kind=kind, t=t or time.time(), **kw)

        # ---- 1. 向きの見分け・「返す」が出るとき
        assert R.tone_of(app, st, {"kind": "appoint_busy", "text": "📱『その日は空いてないです』"}) == "notice"
        assert R.tone_of(app, st, {"kind": "smalltalk", "text": "📱『ふふ、それって何の話ですか？』"}) == "question"
        assert R.tone_of(app, st, {"kind": "tease_hurt", "text": "📱『……なんでそういうこと言うんですか？』"}) == "upset"
        assert R.tone_of(app, st, {"kind": "approach", "ap": "msg_chat", "why": "tired", "text": "x"}) == "down"
        assert R.tone_of(app, st, {"kind": "approach", "ap": "msg_where", "text": "x"}) == "where"
        reset()
        C.add(cid, "me", "（他愛ない話をした）", kind="smalltalk")
        assert C.thread(cid)["react"] is None and C.thread(cid)["groups"][0]["id"] != "react"
        her("ask_how", "📱『最近ですか？ 仕事が忙しいんです。』")
        th = C.thread(cid)
        assert th["react"] and th["groups"][0]["id"] == "react" and "re_answer" not in th["groups"][0]["kinds"], th["groups"][0]
        her("smalltalk", "📱『{call}は、週末なにしてました？』")
        assert "re_answer" in C.thread(cid)["groups"][0]["kinds"]
        print("向き・返すが出るとき: OK")

        # ---- 2. 合い方 (判定だけを何度も)
        def rate(tone, kind, n=400, ok=("good",), late_h=0.0, **params):
            got = 0
            p = dict({"mood": 55, "affection": 55, "loneliness": 40}, **params)
            for _ in range(n):
                st["params"].update(p)
                got += R.judge(app, char, st, tone, kind, late_h)[0] in ok
            return got / float(n)
        bad = ("bad",)
        assert rate("happy", "re_glad") > rate("happy", "re_hard") + 0.4
        assert rate("down", "re_hard") > rate("down", "re_lol") + 0.4 and rate("down", "re_lol", ok=bad) > 0.6
        assert rate("question", "re_answer") > rate("question", "re_sokka") + 0.4
        assert rate("notice", "re_ok") > 0.4 and rate("notice", "re_ok", ok=bad) < 0.05
        assert 0.05 < rate("happy", "re_glad") < 0.97                       # 決め打ちではない
        assert rate("happy", "re_glad", mood=25, affection=35) < rate("happy", "re_glad") - 0.2
        assert rate("news", "re_more", late_h=8) < rate("news", "re_more") - 0.2          # 遅れて返すと響きにくい
        print("合い方: OK | うれしい話によかったね %.2f / 沈んだ話に笑 (よくない) %.2f / 問いかけに答える %.2f" %
              (rate("happy", "re_glad"), rate("down", "re_lol", ok=bad), rate("question", "re_answer")))

        # ---- 3. ふつうのメッセージとして返す: 時間差で届く・合わなければ謝れる心当たり
        got = {}
        for i in range(40):
            reset()
            her("approach" if False else "money_worry", "📱『今月ちょっと苦しくて』")
            k = random.choice(["re_hard", "re_lol"])
            C.send(cid, k)
            pend = st["msg_pending"]
            assert pend["kind"] == k and pend["meta"]["to"]["tone"] == "down", pend
            pend["due"], pend["reply"] = time.time() - 1, True
            app.deliver_due()
            last = [x for x in C.load(cid)["items"] if x["who"] == "her" and x["kind"].startswith("react_")][-1]   # 切り上げが続くことも
            assert last["kind"].startswith("react_" + k[3:] + "_"), last
            res = last["kind"].rsplit("_", 1)[1]
            got.setdefault(k, {}).setdefault(res, 0)
            got[k][res] += 1
            if res == "bad":
                assert any(r.get("action") == "_react" for r in st.get("reasons") or [])
                from core import msgpick
                assert msgpick.reason_item(next(r for r in st["reasons"] if r.get("action") == "_react")) == "reply_manner"
        assert got["re_lol"].get("bad", 0) > got["re_lol"].get("good", 0), got
        print("ふつうの返し: OK |", got)

        # ---- 4. 「了解」に相手は返さないことがあるが, 受け取り方は決まる
        reset()
        her("appoint_busy", "📱『その日は空いてないです』")
        C.send(cid, "re_ok")
        pend = st["msg_pending"]
        pend["due"], pend["reply"] = time.time() - 1, False
        n0 = len(C.load(cid)["items"])
        app.deliver_due()
        assert len(C.load(cid)["items"]) == n0 and "msg_pending" not in st
        assert any(x["c"] == "react" and "受け取り方" in x["m"] and x["v"].get("silent") for x in app.trace.read(cid=cid)), "受け取り方が決まっていない"
        print("返さない了解: OK")

        # ---- 5. 相手から来たメッセージ (働きかけ) にも, 同じ返し方で
        res = {}
        for _ in range(30):
            reset()
            app.force_approach("msg_today", cid)
            items = C.load(cid)["items"]
            assert [x for x in items if x["who"] == "her"][-1].get("ap") == "msg_today"
            grp = C.thread(cid)["groups"][0]
            assert grp["id"] == "react", grp
            k = random.choice(["re_more", "re_sokka"])
            r = landed(app, C.send(cid, k), cid)
            assert not st.get("approach")
            res.setdefault(k, {}).setdefault(r["entry"]["reply"]["result"], 0)
            res[k][r["entry"]["reply"]["result"]] += 1
        good = lambda g: g.get("good", 0) / float(sum(g.values()) or 1)   # noqa: E731
        assert good(res["re_more"]) > good(res["re_sokka"]) + 0.3, res
        mine = [x for x in C.load(cid)["items"] if x["who"] == "me"][-1]
        assert mine["text"] in (R.said("re_more"), R.said("re_sokka")), mine
        reset()
        app.force_approach("msg_where", cid)
        assert "re_answer" in C.thread(cid)["groups"][0]["kinds"]
        r = landed(app, C.send(cid, "re_answer"), cid)
        assert r["entry"]["text"] == (app.persona_text(char, "msgr.msg_where." + r["entry"]["reply"]["result"])
                                      or __import__("core.msgreply", fromlist=["x"]).LINES["msgr.msg_where." + r["entry"]["reply"]["result"]])
        print("働きかけへの返し: OK |", res)

        # ---- 6. 大事な話にスタンプだけ: 軽く流されたと受け取られやすい
        def stamp_rate(kind, text, n=60):
            only = 0
            for _ in range(n):
                reset()
                st["stamps"] = []
                her(kind, text)
                C.send(cid, "stamp", {"stamp": "like"})
                pend = st["msg_pending"]
                pend["due"], pend["reply"] = time.time() - 1, True
                app.deliver_due()
                only += [x for x in C.load(cid)["items"] if x["who"] == "her" and not x["kind"].startswith("close_")][-1]["kind"] == "stamp_only"
            return only / float(n)
        heavy, light = stamp_rate("money_worry", "📱『今月ちょっと苦しくて』"), stamp_rate("appoint_busy", "📱『その日は空いてないです』")
        assert heavy > light + 0.25, (heavy, light)
        print("スタンプだけ: OK | 沈んだ話 %.2f / 用件の連絡 %.2f" % (heavy, light))

        # ---- 7. 働きかけを既読のまま: 少しずつ重くなる (上限あり). 返せば一部戻る
        reset()
        st["react_since"] = time.time() - 3600
        app.force_approach("msg_miss", cid)
        C.mark_seen(cid)
        st["approach"]["until"] = time.time() - 1
        now = time.time()
        app.presence.live(char, st, now)
        rec = st["ap_ignored"]
        assert rec["read"] and rec["applied"] == 0
        m0 = st["params"]["mood"]
        R.ignore_tick(app, char, st, now + 3 * 3600)
        a3 = st["ap_ignored"]["applied"]
        R.ignore_tick(app, char, st, now + 30 * 3600)
        a30 = st["ap_ignored"]["applied"]
        assert 0 < a3 < a30 <= R.IGNORE_CAP * 3, (a3, a30)
        assert st["params"]["mood"] < m0
        assert any("ずっと放っておかれた" in r.get("tell", "") for r in st["reasons"])
        m1 = st["params"]["mood"]
        for _ in range(20):          # 遅れてでも返す (よくない返事でなければ, 一部戻る)
            C.send(cid, "re_hard")
            pend = st["msg_pending"]
            pend["due"], pend["reply"] = time.time() - 1, True
            app.deliver_due()
            if [x for x in C.load(cid)["items"] if x["who"] == "her" and x["kind"].startswith("react_")][-1]["kind"] != "react_hard_bad":
                break
            st["ap_ignored"] = dict(rec, applied=a30)       # 試し直し
        assert "ap_ignored" not in st
        print("働きかけを既読のまま: OK | 3 時間 %.1f / 30 時間 %.1f (上限あり) / 返したあと 機嫌 %.1f → %.1f" % (a3, a30, m1, st["params"]["mood"]))

        # ---- 8. 相手の問いかけを既読のまま: 少し気にする. 以前のメッセージ (更新より前) は数えない
        reset()
        t_q = time.time()
        C.add(cid, "me", "（他愛ない話をした）", kind="smalltalk", t=t_q - 10)
        her("smalltalk", "📱『{call}は、週末なにしてました？』", t=t_q)
        C.mark_seen(cid)
        st["react_since"] = t_q - 60
        m0 = st["params"]["mood"]
        R.ignore_tick(app, char, st, t_q + 3600)
        assert not (st.get("await_ignored") or {}).get("applied"), st.get("await_ignored")      # 2 時間までは何も起きない
        R.ignore_tick(app, char, st, t_q + 20 * 3600)
        aw = st["await_ignored"]["applied"]
        assert 0 < aw <= R.AWAIT_CAP * 2 and st["params"]["mood"] < m0
        assert any("聞いたのに" in r.get("tell", "") for r in st["reasons"])
        reset()
        st["react_since"] = t_q + 1               # 更新したのがこのメッセージより後: 数えない
        R.ignore_tick(app, char, st, t_q + 20 * 3600)
        assert not st.get("await_ignored")
        print("問いかけを既読のまま: OK | 20 時間 %.1f / 更新前のメッセージ 0" % aw)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK")


if __name__ == "__main__":
    main()
