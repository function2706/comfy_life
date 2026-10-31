"""お金・機嫌の理由・おねだり・留守中の変化の確認 (一時データディレクトリ, 画像生成なし).

    python tools/test_life.py
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

fix_noon(engine)     # 予定・時間帯・行き先の営業時間が, 流す日時に左右されないように


def main():
    random.seed(2)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        L = app.life
        st = app.state("hina")
        char = app.char()
        free = lambda: st.update(override={"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": 9e12})  # noqa: E731
        free()
        app.set_params({"affection": 70, "mood": 60, "energy": 90, "sleepiness": 0, "health": 90})
        me = lambda: L.player_state()["money"]    # noqa: E731
        her = lambda: L.her_money(st)["a"]          # noqa: E731
        print("start: あなた %d / %s %d" % (me(), char["name"], her()))

        # ---- 稼ぐ・渡す・借りる・投資
        app.world["economy"]["work_hours"] = [0, 24]            # テストは時刻に左右されないように
        app.action("go_work")["when"] = "presence=here|idle|busy"
        m0 = me()
        app.act("go_work")
        app.presence.rec()["since"] -= 3 * 3600        # 3 時間働いたことにする
        r = app.come_back()
        assert me() > m0 and r["entry"]["money"]["p"] > 0
        print("work:", r["entry"]["money"], r["entry"]["text"])
        m0, h0 = me(), her()
        app.act("allowance")
        assert me() == m0 - 5000 and her() == h0 + 5000
        m0, h0 = me(), her()
        r = app.act("borrow")
        print("borrow:", r["entry"]["text"], r["entry"].get("money"))
        app.trade("idx", 10)
        assert L.player_state()["market"]["holdings"]["idx"]["qty"] == 10
        L.player_state()["market"]["assets"]["idx"]["price"] *= 1.1          # 値上がりしたことにする
        r = app.trade("idx", -10)
        print("invest:", r["entry"]["text"], r["entry"].get("money"))
        assert "idx" not in L.player_state()["market"]["holdings"] and r["entry"]["money"]["p"] > 0

        # ---- お出かけの支払い方針 (カフェは夜には行けないので, 時間帯を昼にしておく)
        phase_at = app.phase_at
        app.phase_at = lambda dt: {"id": "noon", "label": "昼", "pos": "", "neg": ""}
        for pol in ("me", "split", "her"):
            char["pay_policy"] = pol
            m0, h0 = me(), her()
            free()
            st["cooldowns"] = {}
            r = app.act("cafe")
            print("cafe (%s): あなた %+d / %s %+d | %s" % (pol, me() - m0, char["name"], her() - h0, r["entry"]["text"]))
            assert {"me": (-2000, 0), "split": (-1000, -1000), "her": (0, -2000)}[pol] == (me() - m0, her() - h0)
        app.phase_at = phase_at
        L.player_state()["money"], L.her_money(st)["a"] = 100, 100
        free()
        st["cooldowns"] = {}
        try:
            app.act("date")
            raise AssertionError("お金が足りないのにデートできた")
        except ValueError as e:
            print("足りない:", e)
        L.player_state()["money"], L.her_money(st)["a"] = 50000, 20000

        # ---- 機嫌の理由: 理由も知らずに謝ると悪化 → 聞く → 謝ると和らぐ / 相談で解決
        app.set_params({"mood": 40})
        L.player_state()["skills"]["care"] = 100.0      # 気づくかは出来事の時刻しだいなので, 気配りを高くして
        t_ev = time.time()
        while int(t_ev * 1000) % 997 / 997.0 >= 0.9:     # 気配り 100 でも 95% なので, 必ず気づく時刻にする (life._noticed)
            t_ev -= 0.001
        L.happen(char, st, t_ev, app.context(char, st, __import__("datetime").datetime.now()), force="argument")
        assert app.life.view(char, st)["hint"], "何かあったみたい のヒント"
        mood0 = st["params"]["mood"]
        r = app.act("apologize")
        print("いきなり謝る:", r["entry"]["text"], "機嫌 %+.0f" % (st["params"]["mood"] - mood0))
        assert st["params"]["mood"] < mood0
        st["cooldowns"] = {}
        r = app.act("ask_mood")
        print("何かあった？:", r["entry"]["text"])
        assert "ケンカ" in r["entry"]["text"]
        st["cooldowns"] = {}
        r = app.act("apologize")
        print("理由を知って謝る:", r["entry"]["text"])
        mood0 = st["params"]["mood"]
        r = app.act("comfort")
        print("相談にのる:", r["entry"]["text"], "機嫌 %+.0f" % (st["params"]["mood"] - mood0))
        assert st["params"]["mood"] > mood0 and not L.dominant(st, time.time(), "bad")

        # あなたが原因: からかって機嫌を損ねる → 相談は逆効果 / 謝ると許してもらえる
        app.set_params({"mood": 30})
        st["cooldowns"] = {}
        app.act("tease")
        rs = [x for x in L.reasons(st, time.time()) if x["kind"] == "player"]
        print("理由に記録:", [(x["mood"], x["tell"]) for x in rs])
        assert rs and rs[0]["mood"] == "bad"     # 新しい順
        assert len([x for x in rs if "カフェ" in x["tell"]]) == 1, "同じ理由はまとめる"
        r = app.act("comfort")
        print("原因なのに相談:", r["entry"]["text"])
        st["cooldowns"] = {}
        # 許し方には幅がある (半分だけ・態度で・受け付けない. 割合は tools/test_manners.py). ここでは, すぐ許してくれる場合
        st["apologies"] = []            # 上で謝ったばかり (続けて謝ると「もういいって」)
        app.set_params({"mood": 55, "affection": 60, "trust": 60})
        for x in rs:
            x["delta"] = max(x["delta"], -3.0)
        g, random.gauss = random.gauss, lambda m, sd: 0.0
        r = app.act("apologize")
        random.gauss = g
        print("謝る:", r["entry"]["text"])
        assert not L.dominant(st, time.time(), "bad")
        # 良い理由も記録される
        app.set_params({"mood": 50})
        st["cooldowns"] = {}
        app.act("praise")
        assert any(x["mood"] == "good" and x["kind"] == "player" for x in L.reasons(st, time.time()))

        # ---- おねだり
        L.her_money(st)["a"] = 1000
        L.happen(char, st, time.time(), app.context(char, st, __import__("datetime").datetime.now()), force="money_tight")
        req = st.get("request")
        assert req and req["kind"] == "money", req
        m0 = me()
        r = app.act("_req_yes")
        print("お金を貸して → いいよ:", r["entry"]["text"], r["entry"].get("money"))
        assert me() == m0 - req["amount"] and st.get("request") is None

        # ---- 留守中: 日をまたいだ収入・生活費, 留守中の出来事をおかえりで話す
        now = time.time()
        st["last_interaction"] = now - 30 * 3600
        st["last_tick"] = now - 30 * 3600
        L.player_state()["last_tick"] = now - 30 * 3600
        m0 = me()
        L.happen(char, st, now - 20 * 3600, app.context(char, st, __import__("datetime").datetime.now()), force="cat")
        r = app.visit()
        print("おかえり:", r["entry"]["text"])
        print("留守中のお金: あなた %+d" % (me() - m0))
        assert any(w in r["entry"]["text"] for w in ("猫", "久しぶり", "留守", "いない間")), r["entry"]["text"]
        # 日をまたいだ数だけ, 日々の収入と生活費 (一人なら折半の半分). 月をまたげば家賃・光熱費・通信費も (払いきれなければ払える分).
        # 流す時刻で, またぐ日数・月が変わる (夜中なら 2 日, 月初めなら月も) ので, 記録で確かめる
        from datetime import date
        days = (date.fromtimestamp(now) - date.fromtimestamp(now - 30 * 3600)).days
        raw = [x for x in app.kakeibo.rec()["raw"] if x["t"] >= now - 31 * 3600]
        assert sum(1 for x in raw if x["n"] == "日々の収入") == days and sum(1 for x in raw if x["n"] == "生活費") == days, raw
        month = date.fromtimestamp(now - 30 * 3600).month != date.fromtimestamp(now).month
        assert month == any("家賃" in x["n"] for x in raw), raw
        v = dict(app.state_view()["you"], **app.person_view("hina")["life"])
        print("view:", {k: v[k] for k in ("my_money", "pay_policy", "hint")}, [x["tell"] for x in v["reasons"]])
        for e in app.log("hina"):
            assert "{" not in e["text"], e["text"]
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
