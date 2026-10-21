"""借金のあいだの暮らしの確認 (一時データ, 画像生成なし).
- 借金のあいだ (借金か, 誰かに借りたお金が残っている) は, 必需品 (食材・洗剤) しか買わない. 衝動買いもしない
- 借金には月はじめに少し利息がつく (知り合いに借りた分にはつかない)
- お金があるときに返せる. 借りた相手に返すと, 信頼が少し戻る (realize を通すので揺らぐ). 離れていれば返事は時間差で
- 事情を知っている相手 (貸した人・同居相手) は, 返済が遅いと心配したり不信感を持ったりする. 猶予のうちは何も言わない

    python tools/test_debt.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from core.items import CATALOG  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(97)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("借金")
        L, I, B = app.life, app.items, app.bonds
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        ps = L.player_state()

        # ---- 1. 借金のあいだは必需品だけ
        ps["money"] = 100000
        assert not L.in_debt()
        I.set_list("veggies", 1)
        I.set_list("novel", 1)
        I.set_list("detergent", 1)
        ps["debt"], ps["debt_t"] = 5000, time.time()
        assert L.in_debt() and I.view()["in_debt"]
        for _ in range(30):
            bought, missed = I.shop("mall", hours=3)
            assert all(CATALOG[b["id"]]["essential"] for b in bought)
            assert not any(b.get("impulse") for b in bought), "借金のあいだは衝動買いしない"
            assert not any(b["id"] == "novel" for b in bought)
            I.set_list("veggies", 1)
            I.set_list("detergent", 1)
        assert any("見送った" in m for m in missed)
        assert I.count("veggies") >= 1 and I.count("novel") == 0
        # 借金が無くなれば, また何でも買える
        ps["debt"] = 0
        for _ in range(5):
            bought, _ = I.shop("mall")
            if I.count("novel"):
                break
        assert I.count("novel") == 1
        print("essentials only: OK")

        # ---- 2. 利息 (借金だけ) と返済
        ps["debt"], ps["debt_t"] = 10000, time.time()
        ps["loans"] = {cid: 3000}
        ps["loan_t"] = {cid: time.time()}
        assert L.charge_interest(time.time()) == 150 and ps["debt"] == 10150 and ps["loans"][cid] == 3000
        ps["money"] = 2000
        try:
            L.repay("debt", 5000)
            raise AssertionError("お金が足りなければ返せない")
        except ValueError:
            pass
        ps["money"] = 20000
        r = app.repay("debt", 99999)
        assert r["amount"] == 10150 and r["left"] == 0 and ps["debt"] == 0 and "debt_t" not in ps
        assert L.in_debt(), "まだ借りたお金が残っている"
        her0 = L.her_money(st)["a"]
        app.set_params({"trust": 40, "mood": 50}, cid)
        st.pop("msg_pending", None)
        r = app.repay(cid, 1000)
        assert r["left"] == 2000 and L.her_money(st)["a"] == her0 + 1000
        r = app.repay(cid, 5000)
        assert r["amount"] == 2000 and r["left"] == 0 and cid not in ps["loans"] and not L.in_debt()
        assert st["params"]["trust"] > 40, "返したら信頼が少し戻る"
        assert st["msg_pending"]["kind"] == "repaid", "離れていれば, 返事はメッセージの時間差で"
        st["msg_pending"]["due"] = time.time() - 1
        out = app.deliver_due()
        assert out and "受け取り" in out[0]["text"]
        print("interest / repay: OK")

        # ---- 3. 返済が遅いと, 貸した相手は気にする (猶予のうちは何も言わない)
        def days(n, since):
            said = []
            t = since
            for _ in range(n):
                t += 86400
                k = L.money_concern(char, st, t)
                if k:
                    said.append(k)
            return said

        ps["loans"], ps["loan_t"] = {cid: 5000}, {cid: time.time()}
        assert days(13, time.time()) == [], "猶予 (14 日) のうちは何も言わない"
        app.set_params({"trust": 60, "affection": 60}, cid)
        ks = days(60, time.time() + 14 * 86400)
        assert ks and set(ks) <= {"money_worry", "money_distrust"}, ks
        assert st["params"]["trust"] < 60, "返済が遅いと信頼が下がっていく"
        assert any(r.get("action") == "_money_concern" for r in st["reasons"])
        assert any(x.get("kind") in ("money_worry", "money_distrust") for x in app.chat.load(cid)["items"])
        # 慎重な性格ほど不信感に傾く
        counts = {}
        for pid in ("hitonatsukko", "genki"):
            char["persona_id"] = pid
            n = {"money_worry": 0, "money_distrust": 0}
            for _ in range(300):
                app.set_params({"trust": 50, "affection": 50}, cid)
                k = L.money_concern(char, st, time.time() + 20 * 86400)
                if k:
                    n[k] += 1
            counts[pid] = n["money_distrust"] / float(max(1, sum(n.values())))
        assert counts["genki"] > counts["hitonatsukko"], counts
        # 借金を知っているのは同居相手だけ (連絡先の人は, 借金のことは知らない)
        ps["loans"], ps["loan_t"] = {}, {}
        ps["debt"], ps["debt_t"] = 20000, time.time() - 30 * 86400
        assert L.owed_since(cid, st, time.time()) is None
        B.set_stage(cid, "live")
        assert L.owed_since(cid, st, time.time()) == ps["debt_t"]
        # 一緒にいれば, その場で言われる (記録に残る)
        char["persona_id"] = "teinei"
        n0 = len(app.log(cid))
        for _ in range(200):
            if L.money_concern(char, st, time.time()) and len(app.log(cid)) > n0:
                break
        assert app.log(cid)[-1]["action"] == "_money_concern"
        print("late repayment: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
