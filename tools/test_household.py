"""暮らしのお金と, 離れている相手の過ごし方の確認 (一時データ, 画像生成なし).
- 離れている相手: あなたから見れば「そばにいない」が, 本人は自分の予定どおりに過ごす (家にいれば外出中の体の動きにならない)
- 時間の経過だけで冷める好感度・信頼は, ご無沙汰の下限 (cool_floor) で止まる
- 生活費は家ごと: あなたが払うのはあなたの家の分だけ (一人なら半分, 同居相手とは方針で分ける). 一緒に暮らしていない人は自分で払う
- 月はじめの家賃・光熱費・通信費. 足りなければ連絡先の人に借りる (断られることも. 印象が変わる) か, 借金
- 離れている連絡先の人は, 選んでいなくてもメッセージを送ってくる

    python tools/test_household.py
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
from testclock import fix_noon  # noqa: E402

fix_noon(engine)     # 予定は日曜の昼 (ひなは家で過ごしている)


def ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").timestamp()


def main():
    random.seed(83)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("家計")
        L, B = app.life, app.bonds
        cid = "hina"
        B.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        now = time.time()
        d = datetime.fromtimestamp(now)

        # ---- 1. 視点と本人の状態: あなたから見れば away, 本人は家にいる
        assert not B.together(cid)
        assert app.context(char, st, d)["away"] is True, "あなたから見れば, そばにいない"
        own = app.context(char, st, d, view=False)
        assert own["away"] is False and own["apart"] is True, own
        app.set_params({"boredom": 20, "stress": 15}, cid)
        st["last_tick"] = now - 3 * 3600
        app.tick(cid, now)
        print("離れていて家で 3 時間:", {k: round(st["params"][k], 1) for k in ("boredom", "stress")})
        assert st["params"]["boredom"] > 25, "家で過ごしていれば退屈は増える (外出中のように減らない)"
        assert st["params"]["stress"] < 25, "外出中のストレスの目標 (+25) は効かない"

        # ---- 2. 寂しさが続いても, 時間だけでは下限で止まる (はっきりした出来事なら下がる)
        floor = float(B.cfg()["cool_floor"])
        app.set_params({"affection": 45, "trust": 45, "loneliness": 100}, cid)
        st["last_tick"] = now - 12 * 86400
        st["last_touch"] = now - 12 * 86400
        app.tick(cid, now)
        a = st["params"]["affection"]
        print("寂しいまま 12 日: 好感度 45 →", round(a, 1), "信頼", round(st["params"]["trust"], 1))
        assert floor <= a < 45, a
        app.set_params({"affection": 10, "loneliness": 100}, cid)
        st["last_tick"] = now - 5 * 86400
        app.tick(cid, now)
        assert abs(st["params"]["affection"] - 10) < 0.01, "下限より下にいれば, 時間だけではそれ以上下がらない"
        B.notice(char, st, cid, now)                     # 出来事 (嫉妬) ならさらに下がりうる
        assert st["params"]["affection"] < 10

        # ---- 3. 生活費は家ごと: 一人暮らしのあなたは半分だけ, 離れている相手は自分の分を自分で
        ps = L.player_state()
        ps["money"], L.her_money(st)["a"] = 50000, 20000
        e = L.econ()
        day0 = ts("2026-10-20 23:50")
        ps["last_tick"], st["last_tick"] = day0, day0
        L.tick_world(day0 + 1200)
        app.life.step(char, st, day0, day0 + 1200, 1200 / 3600.0)
        assert ps["money"] == 50000 + int(e["player_daily_income"]) - int(e["living_cost_per_day"]) // 2, ps["money"]
        assert L.her_money(st)["a"] == 20000 + int(e["her_daily_income"]) - int(e["her_living_cost_per_day"]), L.her_money(st)

        # 同居: 二人分を方針 (折半) で分ける. 相手の生活費は二重に引かない
        B.set_stage(cid, "live")
        ps["money"], L.her_money(st)["a"] = 50000, 20000
        ps["last_tick"] = day0
        L.tick_world(day0 + 1200)
        app.life.step(char, st, day0, day0 + 1200, 1200 / 3600.0)
        half = int(e["living_cost_per_day"]) // 2
        assert ps["money"] == 50000 + int(e["player_daily_income"]) - half, ps["money"]
        assert L.her_money(st)["a"] == 20000 + int(e["her_daily_income"]) - half, L.her_money(st)
        print("生活費: 一人なら半分, 同居なら折半, 離れている人は自分で: OK")

        # ---- 4. 月はじめの家賃・光熱費・通信費 (同居なら折半)
        m0 = ts("2026-10-31 23:50")
        ps["money"], L.her_money(st)["a"] = 200000, 200000
        ps["last_tick"] = m0
        L.tick_world(m0 + 1200)
        rent = int(e["home_cost_per_month"])
        assert ps["money"] == 200000 + int(e["player_daily_income"]) - half - rent // 2, ps["money"]

        # 足りなければ借りる: 仲が深く, 懐に余裕のある人は貸してくれやすい. 貸すと信頼が少し下がり, 理由に残る
        B.set_stage(cid, "contact")
        app.set_params({"affection": 80, "trust": 80, "mood": 60}, cid)
        L.her_money(st)["a"] = 500000
        assert L.lend_chance(char, st, 30000, m0) >= 0.5
        lent = 0
        for i in range(20):
            ps["money"] = half - int(e["player_daily_income"])     # その日の生活費までは払える
            trust0 = st["params"]["trust"]
            ps["last_tick"] = ts("2026-11-30 23:50")
            L.tick_world(ts("2026-12-01 00:10"))
            if ps.get("loans", {}).get(cid, 0) > lent:
                lent = ps["loans"][cid]
                assert st["params"]["trust"] < trust0, "貸してくれても, 信頼は少し下がる"
                assert any("貸した" in r["tell"] for r in st["reasons"])
                break
            st["lent"] = []
        assert lent == rent and ps["money"] == 0, (lent, ps.get("loans"), ps["money"])
        print("借りた:", ps["loans"], ps["money_notes"][-1]["text"])

        # 誰も貸してくれない (懐に余裕がない) → 借金. 残高が残り, 画面にも出る
        L.her_money(st)["a"] = 1000
        assert L.lend_chance(char, st, 30000, m0) == 0.0
        ps["money"], ps["debt"] = half - int(e["player_daily_income"]), 0
        ps["last_tick"] = ts("2026-12-31 23:50")
        L.tick_world(ts("2027-01-01 00:10"))
        assert ps["debt"] == rent and ps["money"] == 0, (ps["debt"], ps["money"])
        v = app.state_view(cid)["life"]
        assert v["debt"] == ps["debt"] and v["loans"] and v["money_notes"], v
        print("借金:", v["debt"], v["money_notes"][-1]["text"])

        # ---- 5. 離れている連絡先の人は, 選んでいなくてもメッセージを送ってくる
        other = app.new_character("みお", stage="contact")["id"]
        app.select_character(other)
        app.world.setdefault("presence", {})["approach_apart_rate_per_hour"] = 500
        app.set_params({"boredom": 80, "loneliness": 70, "affection": 60, "mood": 70, "sleepiness": 0}, cid)
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}
        st.pop("approach", None)
        st["ap_quiet_until"] = 0
        fired = False
        for _ in range(5):
            st["ap_check"] = time.time() - 600
            app.state_view(other, beat=True, idle=0)
            if st.get("approach"):
                fired = True
                break
        assert fired, "選んでいない相手からも届く"
        assert app.chat.unread(cid) >= 1
        app.chat.send(cid, "smalltalk")
        assert not st.get("approach"), "メッセージを送れば, それが返事になる"
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp + "_backup", ignore_errors=True)


if __name__ == "__main__":
    main()
