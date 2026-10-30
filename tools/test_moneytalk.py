"""お金のこと (core/moneytalk.py): 使い方への口出し (管理傾向・額・続け方)・出方 (説明・謝る・言い返す・聞き流す)・
どっちが出すか (性格の好みとずれると, 言わないまま冷めることも)・資格の試験の時間はふさがる.

    python tools/test_moneytalk.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(91)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("お金")
        M, L = app.moneytalk, app.life
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "live")
        char, st = app.char(cid), app.state(cid)
        ps = L.player_state()

        # ---- 1. 使ったお金を覚える: 宝くじ・株・5,000 円以上の買い物だけ
        ps["spend_log"] = []
        L.ledger(time.time(), -900, "fun", "宝くじ 3枚")
        L.ledger(time.time(), -30000, "invest", "株Aを買った")
        L.ledger(time.time(), -1200, "shopping", "小説")
        L.ledger(time.time(), -8000, "shopping", "マフラー")
        assert [x["what"] for x in ps["spend_log"]] == ["宝くじ", "株", "高い買い物（マフラー）"], ps["spend_log"]
        print("使ったお金を覚える: OK")

        # ---- 2. 口を出すか: 管理傾向 (性格 + 依存度) が高いほど・額が大きいほど
        def rate(persona, amount, n=200):
            char["persona_id"] = persona
            k = 0
            for _ in range(n):
                st.pop("money_talk", None)
                st.pop("money_day", None)
                st["money_seen"] = 0
                ps["spend_log"] = [{"t": time.time() - 60, "what": "株", "amount": amount}]
                ps["money"] = 50000
                M.tick(char, st, time.time())
                k += bool(st.get("money_talk"))
            return k / float(n)
        hi, lo, small = rate("jimuteki", 40000), rate("tenshin", 40000), rate("jimuteki", 1000)
        assert hi > lo + 0.3 and hi > small + 0.15, (hi, lo, small)
        print("口を出すか: OK | 実務派で大きな額 %.2f / 天真爛漫 %.2f / 実務派で小さな額 %.2f" % (hi, lo, small))

        # 一日に一度まで. 見た分は二度言わない
        char["persona_id"] = "jimuteki"
        st.pop("money_talk", None)
        st["money_day"] = datetime.now().date().isoformat()
        ps["spend_log"] = [{"t": time.time(), "what": "宝くじ", "amount": 90000}]
        M.tick(char, st, time.time())
        assert not st.get("money_talk")
        print("一日に一度: OK")

        # ---- 3. 出方
        def talk():
            st.pop("money_day", None)
            st["money_seen"] = 0
            ps["spend_log"] = [{"t": time.time() - 60, "what": "宝くじ", "amount": 90000}]
            ps["money"] = 10000
            for _ in range(50):
                st.pop("money_day", None)
                st["money_seen"] = 0
                M.tick(char, st, time.time())
                if st.get("money_talk"):
                    return
            raise AssertionError("口を出さなかった")
        seen = {}
        for ch in ("explain", "sorry", "push", "ignore"):
            for _ in range(15):
                talk()
                st.pop("fight", None)
                seen.setdefault(ch, set()).add(M.respond(ch)["key"])
        assert seen["explain"] == {"explain_ok", "explain_meh"} and seen["sorry"] == {"sorry_ok"} and seen["ignore"] == {"ignore"}
        talk()
        M.respond("push")
        assert st.get("fight") and st["fight"]["about"] == "お金"
        print("出方: OK |", {k: sorted(v) for k, v in seen.items()})

        # ---- 4. どっちが出すか: おごられたい人に割り勘が続くと, ときどき言わないまま冷める. 割り勘がいい人は, いつも出されると気が引ける
        char["persona_id"] = "ojousama"
        cooled = 0
        for _ in range(100):
            a0 = st["params"]["affection"]
            M.after_pay(char, st, "split", time.time())
            cooled += st["params"]["affection"] < a0
        assert 10 < cooled < 45, cooled
        assert any(r.get("action") == "_pay" and not r.get("told") for r in st["reasons"])
        a0 = st["params"]["affection"]
        for _ in range(30):
            M.after_pay(char, st, "me", time.time())
        assert st["params"]["affection"] >= a0
        char["persona_id"] = "jimuteki"
        owe = 0
        for _ in range(60):
            st["pay_hist"] = ["me", "me", "me"]
            owe += M.after_pay(char, st, "me", time.time()) is not None
        assert 5 < owe < 30, owe
        char["persona_id"] = "teinei"
        assert all(M.after_pay(char, st, "split", time.time()) is None for _ in range(30))       # 気にしない性格
        print("どっちが出すか: OK | おごられたい人が冷めた %d / 100・割り勘がいい人が気が引けた %d / 60" % (cooled, owe))

        # ---- 5. 資格の試験の時間はふさがる (10〜13 時)
        today = date.today().isoformat()
        app.quals.rec()["apps"]["biz"] = {"exam": today, "status": "applied", "fee": 6000, "t": time.time()}
        h = datetime.now().hour
        if 10 <= h < 13:
            assert app.quals.exam_now() and "試験" in app.blocked("social") and "試験" in app.blocked("solo")
        noon = datetime.now().replace(hour=11, minute=0, second=0, microsecond=0).timestamp()
        eve = datetime.now().replace(hour=15, minute=0, second=0, microsecond=0).timestamp()
        assert app.quals.exam_now(noon) == "ビジネス実務検定" and app.quals.exam_now(eve) is None
        app.quals.rec()["apps"]["biz"]["exam"] = "2000-01-01"
        assert app.quals.exam_now(noon) is None
        print("試験の時間はふさがる: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
