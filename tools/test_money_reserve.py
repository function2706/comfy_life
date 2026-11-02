"""先の支払いを見た買い物 (life.reserve / items.shop) と, 財布をマイナスにしない払い方・相手の最初の所持金 (一時データ).
- 家賃が近いと, 必需品以外は見送ってリストに残す (必需品は買う). 気づくか・どこまで見越すかはやりくりのスキルしだい.
- 車の月額・運賃も pay を通す (足りなければ借りる・借金). 以前マイナスになっていた財布は借金に移す.
- 相手の最初の所持金は性格 (traits.savings) と揺らぎ. 以前の一律 2 万円で始めた相手には差額を一度だけ.

    python tools/test_money_reserve.py
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

END = time.mktime(datetime(2026, 10, 31, 15, 0).timetuple())      # 月末の前の日 (家賃は翌日)
MID = time.mktime(datetime(2026, 10, 10, 15, 0).timetuple())      # 月の半ば


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("家計")
        L, I = app.life, app.items
        ps = L.player_state()

        # ---- 1. 取っておく額: やりくりがうまいと月末は家賃込み, 月の半ばは生活費だけ. 下手だと気づかないことが多い
        ps["skills"]["budget"] = 90
        keep, why = L.reserve(END, random.Random(1))
        assert why == "家賃" and keep >= 60000, (keep, why)
        keep2, why2 = L.reserve(MID, random.Random(1))
        assert why2 == "生活費" and keep2 < 30000, (keep2, why2)
        ps["skills"]["budget"] = 10
        miss = sum(1 for s in range(400) if L.reserve(END, random.Random(s))[0] == 0) / 400.0
        ps["skills"]["budget"] = 90
        miss_hi = sum(1 for s in range(400) if L.reserve(END, random.Random(s))[0] == 0) / 400.0
        print("気づかない割合: やりくり 10 → %.0f%% / 90 → %.0f%%" % (100 * miss, 100 * miss_hi))
        assert miss > 0.5 and miss_hi < 0.15

        # ---- 2. 家賃の前日, 手元 7 万円: 自転車は見送ってリストに残す. 必需品のパンは買う
        def shop_at(place, t, skill, money, items):
            ps["skills"]["budget"] = skill
            ps["money"] = money
            I.ps()["items"].pop("bicycle", None)             # 乗り物は一台まで: 持っていたら手放しておく
            I.ps()["shop_list"] = dict(items)
            return I.shop(place, 1.0, t)
        random.seed(3)
        bought, missed = shop_at("mall", END, 90, 70000, {"bicycle": 1})
        assert not bought and "bicycle" in I.ps()["shop_list"] and any("家賃が近いので" in m and "自転車" in m for m in missed), (bought, missed)
        bought, missed = shop_at("supermarket", END, 90, 70000, {"bread": 1})
        assert [b["id"] for b in bought if not b.get("impulse")] == ["bread"]
        print("家賃の前日:", missed[0] if missed else "")
        # 月の半ばなら買える
        bought, _ = shop_at("mall", MID, 90, 70000, {"bicycle": 1})
        assert any(b["id"] == "bicycle" for b in bought)
        # やりくりが下手だと, 家賃の前日でもけっこう買ってしまう
        n = 0
        for s in range(60):
            random.seed(100 + s)
            bought, _ = shop_at("mall", END, 10, 70000, {"bicycle": 1})
            n += any(b["id"] == "bicycle" for b in bought)
        print("やりくり 10 で家賃の前日に自転車を買った: %d/60" % n)
        assert 25 <= n <= 58

        # ---- 3. 財布をマイナスにしない: 車の月額は pay (借金に). 以前のマイナスは借金へ
        ps["money"], ps["debt"] = 5000, 0
        L.pay(18000, END, "10月の駐車場・保険（車）", cat="transport")
        assert ps["money"] == 0 and ps["debt"] > 0
        d0 = ps["debt"]
        ps["money"] = -3000
        L.player_state()
        assert ps["money"] == 0 and ps["debt"] == d0 + 3000
        print("マイナスの財布 → 借金: OK")

        # ---- 4. 相手の最初の所持金: 性格で差 (お嬢様 > 甘えん坊), 揺らぐ. 以前の 2 万円の相手には差額を一度だけ
        char = dict(next(iter(app.chars.values())))
        rich = sorted(L.her_start_money(dict(char, persona_id="ojousama"), random.Random(s)) for s in range(200))[100]
        poor = sorted(L.her_start_money(dict(char, persona_id="amaenbo"), random.Random(s)) for s in range(200))[100]
        print("最初の所持金のまんなか: お嬢様 %s円 / 甘えん坊 %s円" % (format(rich, ","), format(poor, ",")))
        assert rich > 4 * poor and 30000 <= poor <= 100000
        cid = next(iter(app.chars))
        st = app.state(cid)
        assert st.get("start_money_v2")
        st.pop("start_money_v2")
        st["money"] = {"a": 21000}
        assert L.init_her_money(cid, st) and st["money"]["a"] >= 21000 and st["start_money_v2"]
        a1 = st["money"]["a"]
        assert not L.init_her_money(cid, st) and st["money"]["a"] == a1, "一度だけ"
        print("以前の相手: 21,000円 → %s円" % format(a1, ","))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
