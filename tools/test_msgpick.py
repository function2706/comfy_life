"""メッセージで「何について」を選ぶ (A1/A2. core/msgpick.py, manners.apology(pick) / thanks_pick, chat.consult_reply, スタンプ).

- 謝る: 相手が気にしていること → これまでの許し方 / 近いこと → 「それもだけど」/ あったが気にしていない → 「気にしてない」/
  心当たりなし → 「何のこと？」(気にしていることが別にあれば, ずれていて少し下がる)
- お礼: 最近してくれてまだ言っていないこと → 効く / もう言った → thanks_again / していない → 「何のお礼？」
- 相談: 中身しだい. スタンプ: 種類しだい. 送る欄の分類と, 選ぶ一覧 (分類しない) (一時データ).

    python tools/test_msgpick.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, memquiz, store  # noqa: E402


def main():
    random.seed(8)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("理由")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        L, M, C = app.life, app.manners, app.chat
        now = time.time()

        def reply(kind, **meta):
            ctx = dict(app.context(char, st, datetime.fromtimestamp(now)), phase="noon", too_often=False, _sent=now, _meta=meta)
            return C.reply(char, st, kind, now, ctx)

        def fresh():
            st["reasons"], st["apologies"], st["favors"] = [], [], []
            st.pop("apology_last", None)
            app.set_params({"mood": 55, "affection": 50, "trust": 50}, cid)

        # ---- 1. 送る欄: 謝る・お礼は記憶の問い (別の窓. A20. 中身は tools/test_memquiz.py)
        th = C.thread(cid)
        assert [g["id"] for g in th["groups"]] == ["chat", "feel", "invite", "photo", "call"] and set(th["pick"]) == {"apology", "thanks", "consult", "stamp"}
        assert th["pick"]["apology"] == "quiz" and th["pick"]["thanks"] == "quiz"
        grouped = {k for g in th["groups"] for k in g["kinds"]}
        from core import react      # 相手のメッセージへの返しは「返す」のまとまりにだけ (返していないメッセージがあるとき)
        assert grouped | {"stamp", "nudge"} | set(react.IDS) == set(k["id"] for k in th["kinds"]), set(k["id"] for k in th["kinds"]) - grouped
        print("一覧: OK | 分類 %d" % len(th["groups"]))

        # ---- 2. 謝る: 以前の形 (項目 id) で送ってあったもの: 的中ならこれまでの許し方 / 外れは「何のこと？」(気にしていることがあれば下がる)
        fresh()
        L.add_reason(st, "player", "bad", "連絡が多くて疲れた", now - 600, told=True, delta=-3.0, action="_too_often")
        key, eff, _ = reply("apology", reason="too_often")
        assert key in ("apology", "apology_half", "apology_deeds", "apology_refuse"), key
        fresh()
        L.add_reason(st, "player", "bad", "連絡が多くて疲れた", now - 600, told=True, delta=-4.0, action="_too_often")
        key, eff, _ = reply("apology", reason="home")
        assert key == "apology_confused" and eff == {"mood": -2}, (key, eff)
        # 選ばない (以前の呼び方) はこれまでどおり
        fresh()
        L.add_reason(st, "player", "bad", "連絡が多くて疲れた", now - 600, told=True, delta=-3.0, action="_too_often")
        key, _, _ = reply("apology")
        assert key.startswith("apology") and key not in ("apology_near", "apology_unminded"), key
        print("謝る (以前の形): OK")

        # ---- 3. お礼
        fresh()
        M.favor(st, "selfie", now - 1800)
        assert reply("thanks", reason="selfie")[0] == "thanks"
        assert reply("thanks", reason="selfie")[0] == "thanks_again"
        assert reply("thanks", reason="care")[0] == "thanks_what"
        assert reply("thanks", reason="forgave")[0] == "thanks_what"
        print("お礼: OK")

        # ---- 4. 相談: 中身しだい (世話焼きなら体調で頼りになることが多い)
        fresh()
        keys = {}
        for tp in ("health", "work", "people"):
            ks = [reply("consult", consult=tp)[0] for _ in range(30)]
            keys[tp] = {k: ks.count(k) for k in set(ks)}
            assert set(ks) <= {"consult", "consult_good", "consult_off", "consult_jealous"}, ks
        k, _, ex = reply("consult", consult="money")
        assert ex.get("topic") == "お金"
        print("相談:", keys)

        # ---- 5. スタンプ
        fresh()
        app.set_params({"affection": 30}, cid)
        assert reply("stamp", stamp="heart")[0] == "stamp_heart_cold"
        app.set_params({"affection": 80}, cid)
        assert reply("stamp", stamp="heart")[0] == "stamp_heart"
        L.add_reason(st, "player", "bad", "約束に来なかった", now - 600, told=False, delta=-8.0, action="_appoint")
        assert reply("stamp", stamp="sorry")[0] == "stamp_sorry_bad"
        fresh()
        M.favor(st, "call", now - 600)
        assert reply("stamp", stamp="thanks")[0] == "stamp_thanks"
        print("スタンプ: OK")

        # ---- 6. 送る: 要約に理由が残る. 違う理由は弾く
        fresh()
        st.pop("msg_pending", None)
        q = memquiz.ask(app, cid, "apology", now)
        C.send(cid, "apology", {"reason": q["choices"][0]["id"]})
        assert C.thread(cid)["items"][-1]["text"] == "（謝った: %s）" % q["choices"][0]["label"], C.thread(cid)["items"][-1]
        assert st["msg_pending"]["meta"]["reason"]["label"] == q["choices"][0]["label"]
        st.pop("msg_pending", None)
        C.send(cid, "stamp", {"stamp": "like"})
        assert C.thread(cid)["items"][-1]["text"] == "（👍 いいねのスタンプを送った）"
        for kind, ex in (("apology", {"reason": "nope"}), ("thanks", {"reason": "nope"}), ("consult", {"consult": "nope"}), ("stamp", {"stamp": "nope"})):
            try:
                C.send(cid, kind, ex)
                raise AssertionError("通ってしまった: %s" % kind)
            except ValueError:
                pass
        print("送る: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
