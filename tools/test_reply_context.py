"""前のやりとりを踏まえた返事 (一時データ, 画像生成なし).
- 相手がしてくれたこと (誘い・約束を受けた・片付けた・祝ってくれた) は, お礼の心当たりになる
- 約束をすっぽかしたのを相手が謝ってきたら, 許すか まだ許さないかで答える
- 許してもらったお礼を言ったあとでも, まだお礼していない心当たりへのお礼は「もう聞いた」にならない
- 「会おう」にもう応じているのに, また「会おう」と送ると, その話の続きとして返す
- 誕生日を前にも教えた・聞いたのに, またやりとりすると「前にも」と返す
- 「今いい？」に「あとで」と言われてすぐ電話すると, そう言われる (喜ばない. お礼の心当たりにもならない)
- 謝ることが見当たらない謝罪は「続けて謝った」に数えない. 甘えて引かれた・からかって傷つけた などは謝る理由に残る
- お詫び (一度だけ): 「何のこと？」のあとの謝罪に「もういい」と返していた分を戻す

    python tools/test_reply_context.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(7)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        app.bonds.set_stage(cid, "contact")
        app.set_params({"affection": 70, "mood": 70, "trust": 60}, cid)
        M, C = app.manners, app.chat
        now = time.time()

        # ---- 誘いに乗ってくれた → お礼の心当たり. もう応じているのに, また誘う → 話の続き
        st["favors"] = []
        for _ in range(30):
            st.pop("date_promise", None)
            k = C.reply(char, st, "invite", now, {})[0]
            if k == "invite_yes":
                break
        assert k == "invite_yes" and [f["what"] for f in st["favors"]] == ["invite"], st["favors"]
        assert C.reply(char, st, "invite", now + 60, {})[0] == "invite_again"
        print("会おう: OK")

        # ---- すっぽかしたのを謝ってきた: 許すか, まだ許さないか (お礼の心当たりではない). 離れていればトークで
        Q = app.quarrel
        for choice, key in (("forgive", "appoint_forgiven"), ("not_yet", "appoint_not_forgiven")):
            st["appoint_sorry"] = time.time()
            pv = Q.pending()
            assert pv and pv["kind"] == "appoint_sorry", pv
            m0 = st["params"]["mood"]
            assert Q.respond(choice)["key"] == key and not Q.pending()
            assert (st["params"]["mood"] > m0) == (choice == "forgive")
            print("すっぽかしの謝罪に %s:" % choice, C.load(cid)["items"][-1]["text"])
        st["appoint_sorry"] = time.time() - 2 * 86400            # 答えないまま 1 日たてば, もう出さない
        assert not Q.pending()
        st.pop("appoint_sorry")

        # ---- 許してもらったお礼のあと, まだお礼していない心当たり (会ってくれた) へのお礼
        st["favors"] = []
        M.favor(st, "met", now - 3600)
        st["apology_last"] = {"t": now - 600, "action": "_x", "out": "quick", "s": 0.5}
        assert M.thanks(st, now, char)[0] == "thanks"            # 許してくれてありがとう
        assert M.thanks(st, now + 60, char)[0] == "thanks"       # 会ってくれてありがとう
        assert M.thanks(st, now + 120, char)[0] == "thanks_again"
        print("お礼: OK")

        # ---- 誕生日: 前にも教えた・聞いた
        A = app.anniv
        st.pop("bday_known", None)
        assert A.reply(char, st, "ask_bday", now)[0] == "bday_tell"
        k, eff, ex = A.reply(char, st, "ask_bday", now)
        assert k == "bday_tell_again" and ex["date"], k
        print("誕生日をまた聞く:", A.line(char, k, ex))
        app.player_profile()["birthday"] = "5-6"
        st.pop("knows_my_bday", None)
        assert A.reply(char, st, "tell_bday", now)[0] == "bday_noted"
        assert A.reply(char, st, "tell_bday", now)[0] == "bday_noted_again"
        st.pop("my_bday_told")                                   # 以前のセーブ (伝えた日を覚えていない): 改めて覚える
        assert A.reply(char, st, "tell_bday", now)[0] == "bday_noted"

        # ---- 「あとで」と言われてすぐ電話
        for _ in range(40):
            st["cooldowns"], st["contacts"], st["favors"] = {}, [], []
            st.pop("msg_pending", None)
            st["call_later_until"] = time.time() + 600
            m0 = st["params"]["mood"]
            r = app.act("call")
            if not r.get("missed"):
                break
        assert "あとで" in r["entry"]["text"] and not st["favors"], (r["entry"]["text"], st["favors"])
        assert st["params"]["mood"] <= m0 + 1.5, (m0, st["params"]["mood"])
        print("あとでと言われて電話:", r["entry"]["text"])

        # ---- 謝ることが見当たらない謝罪 (「何のこと？」) は, 続けて謝ったに数えない
        st["reasons"], st["apologies"], st["apology_last"] = [], [], None
        for _ in range(2):
            v = M.apology(char, st, time.time())
            assert v["out"] == "none", v
            M.apply_apology(char, st, v, time.time())
        # 嫌がったこと (甘えて引かれた) は理由に残り, 謝ればそのことへの謝罪になる
        app.set_params({"affection": 20}, cid)
        assert C.reply(char, st, "flirt", time.time(), {})[0] == "flirt_cold"
        st["msg_pending"] = {"kind": "flirt", "t": time.time(), "meta": {}}
        app._chat_reply(char, st, st.pop("msg_pending"), time.time())
        assert any(r["kind"] == "player" and r.get("action") == "_chat_flirt_cold" for r in st["reasons"]), st["reasons"]
        v = M.apology(char, st, time.time())
        assert v["out"] not in ("none", "enough", "irritated") and "甘え" in v["r"]["tell"], v
        print("甘えて引かれたあとの謝罪:", v["out"], v["r"]["tell"])

        # ---- お詫び: 「何のこと？」のあとの謝罪に「もういい」と返していた分を戻す (一度だけ)
        t0 = time.time() - 3600
        C.add(cid, "her", "x", kind="apology_confused", t=t0)
        C.add(cid, "her", "x", kind="apology_enough", t=t0 + 600)
        st["apologies"] = [t0, t0 + 600]
        app.life.player_state().setdefault("fix_comp", {}).pop("apology_count", None)
        m0 = st["params"]["mood"]
        got = M.apology_count_comp()
        assert got == {cid: 1} and abs(st["params"]["mood"] - m0 - 2) < 0.01 and st["apologies"] == [], (got, st["apologies"])
        assert M.apology_count_comp() == {}
        print("お詫び:", C.load(cid)["items"][-1]["text"])
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
