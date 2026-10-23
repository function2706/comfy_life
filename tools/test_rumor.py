"""株の噂の確認 (一時データ, 画像生成なし).
- 会話・気配りのスキルが高いほど, 噂を聞ける頻度が上がり, 話の確かさ (実際に起きる向きと合う割合) が上がる. 上限 85% (確定しない)
- その業種の店で働いている人の話は少し確か
- 噂の出来事は, 後日の取引時間に公開のニュースとして表に出て, 本当の向きに値段が寄る
- 公開のニュースの当たりやすさは, スキルで変わらない (誰にも同じ)
- 聞いた話は関係性 (known: stock)・株の欄 (rumors)・トーク (メッセージのとき) に出所つき

    python tools/test_rumor.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, market  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(12)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("噂")
        R, M, L = app.rumors, app.market, app.life
        ps = L.player_state()
        cid = "hina" if "hina" in app.chars else next(iter(app.chars))
        char, st = app.chars[cid], app.state(cid)

        def set_skill(v):
            ps["skills"]["talk"] = ps["skills"]["care"] = v

        # ---- 頻度
        def freq(v, n=2000):
            set_skill(v)
            hits = 0
            for i in range(n):
                st.pop("rumor_day", None)
                hits += bool(R.from_talk(char, st))
            M.m()["pending"] = []
            return hits / float(n)
        lo, hi = freq(5), freq(95)
        print("噂を聞ける割合（1回の会話）: 低 %.3f / 高 %.3f" % (lo, hi))
        assert 0 < lo < hi < 0.2
        st.pop("rumor_day", None)
        set_skill(95)
        n1 = R.from_talk(char, st)
        while not n1:
            st.pop("rumor_day", None)
            n1 = R.from_talk(char, st)
        assert R.from_talk(char, st) is None, "一日に一人一度まで"

        # ---- 確かさ: 噂の向き と 本当の向き
        def acc(v, n=3000, who=None):
            set_skill(v)
            m = M.m()
            m["pending"], m["rumors"] = [], []
            ok = 0
            for i in range(n):
                r = R.hear(who or char, "talk")
                ok += r["dir"] == m["pending"][-1]["real"]
            m["pending"] = []
            return ok / float(n)
        plain = {"id": "x", "name": "x", "schedule": []}       # 勤め先のない人
        a_lo, a_hi = acc(5, who=plain), acc(95, who=plain)
        a_in = acc(95)                                          # ひなは本屋で働いている (半分ほどは勤め先の話)
        print("噂の確かさ: 低 %.2f / 高 %.2f / 高・本屋で働く人 %.2f" % (a_lo, a_hi, a_in))
        assert 0.45 < a_lo < a_hi <= 0.86 and a_in >= a_hi - 0.02
        set_skill(100)
        assert R.accuracy(True) <= 0.85, "確定にはしない"

        # ---- 公開のニュースの当たりやすさはスキルで変わらない
        def news_acc(v, n=3000):
            set_skill(v)
            m = M.m()
            ok = 0
            a = M.asset("super")
            for i in range(n):
                M._news(m, a, time.time(), True)
                ok += (M.state(a)["bias"] > 0) == (m["news"][-1]["dir"] > 0)
            return ok / float(n)
        n_lo, n_hi = news_acc(5), news_acc(95)
        print("公開のニュースの当たりやすさ: 低 %.2f / 高 %.2f" % (n_lo, n_hi))
        assert abs(n_lo - n_hi) < 0.05

        # ---- 噂の出来事が後日, ニュースとして表に出る
        m = M.m()
        m["pending"], m["news"] = [], []
        fixed, market.is_open = market.is_open, market.is_open_real        # ここは本物の取引時間で
        r = R.hear(char, "talk", datetime(2026, 10, 23, 12, 0).timestamp())
        p = m["pending"][0]
        assert market.is_open_real(datetime.fromtimestamp(p["at"])), datetime.fromtimestamp(p["at"])
        a = M.asset(p["asset"])
        M.step(p["at"])
        assert not m["pending"] and m["news"] and m["news"][-1]["asset"] == p["asset"]
        assert (M.state(a)["bias"] > 0) == (p["real"] > 0)
        market.is_open = fixed
        print("噂:", r["text"], "→ ニュース:", m["news"][-1]["text"])

        # ---- 関係性・株の欄・トーク
        pv = next(x for x in app.people_view() if x["id"] == cid)
        assert any(k["kind"] == "stock" for k in pv["known"])
        assert M.view()["rumors"] and M.view()["rumors"][0]["src_name"]
        set_skill(100)
        got = None
        for i in range(400):
            st.pop("rumor_day", None)
            got = R.from_message(char, st)
            if got:
                break
        assert got and got.startswith("（そういえば")
        # メッセージに添える (presence): トークの一行
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp + "_backup", ignore_errors=True)


if __name__ == "__main__":
    main()
