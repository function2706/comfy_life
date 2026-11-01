"""前のやりとりを踏まえた返事 (一時データ, 画像生成なし).
- 相手がしてくれたこと (誘い・約束を受けた・片付けた・祝ってくれた) は, お礼の心当たりになる
- 約束をすっぽかしたのを相手が謝ってきたら, 許すか まだ許さないかで答える
- 許してもらったお礼を言ったあとでも, まだお礼していない心当たりへのお礼は「もう聞いた」にならない
- 「会おう」にもう応じているのに, また「会おう」と送ると, その話の続きとして返す
- 誕生日を前にも教えた・聞いたのに, またやりとりすると「前にも」と返す
- 「今いい？」に「あとで」と言われてすぐ電話すると, そう言われる (喜ばない. お礼の心当たりにもならない)

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
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
