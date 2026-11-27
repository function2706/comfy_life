"""出先で疲れた相手を休ませる・気づかう (S41 / A43).
- 「ひと休みする」: 30 分その場で休む. 相手の体力が戻り, あなたは疲れない. 移動中・休んでいる最中はできない (画面でも押せない)
  疲れているときに言えば喜ばれることがあり, 元気なのに続けて休もうとすると「さっき休んだばかり」
- 疲れているときにあなたから解散を言うと, 気づいてもらえたと受け取られることがある (性格と仲しだい. 確実ではない)
- 「タクシーで帰る」: 運賃はあなた持ち. 引き止められたら呼ばない. お金が足りなければできない. 同居相手と帰る予定だった帰りの運賃は戻る
(一時データ. 時刻を進めて確かめる)

    python tools/test_rest_out.py
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, geo as G, parting as PT, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
PT.FIXED = "ok"


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    real = time.time
    off = [0.0]
    time.time = lambda: real() + off[0]
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("休憩")
        cid = app.settings["active_character"]
        char = app.char(cid)
        B = app.bonds
        B.set_stage(cid, "visit")
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        st = app.state(cid)
        ps = app.life.player_state()

        def reset(energy=80, aid="walk"):
            st["cooldowns"], st["override"] = {}, None
            if B.mode(cid):
                B.end(go_home=False)
            app.presence.back(time.time())
            ps["money"] = 100000
            ps["stamina"] = 60.0
            ps["last_tick"] = time.time()
            app.body.rec()["satiety"] = 80.0
            app.set_params({"energy": energy, "affection": 70, "mood": 70}, cid)
            app.act(aid, cid, opts={"appointment": "test"})
            st["override"]["until"] = time.time() + 5 * 3600

        def run(minutes):
            for _ in range(int(minutes / 10)):
                off[0] += 600
                app.life.tick_world(time.time())
                app.tick(cid)

        picked = []                    # 選ばれた反応のキー (セリフは性格で違うので, 文言ではなくキーで見る)
        pick0 = app.pick_reaction

        def pick(a, ctx, invited=False):
            r = pick0(a, ctx, invited)
            picked.append(r.get("key", ""))
            return r
        app.pick_reaction = pick

        def avail(aid):
            from datetime import datetime
            return app.available(char, st, datetime.fromtimestamp(time.time()))[aid]

        # ---- 1. ひと休み: 30 分, 相手の体力が戻り, あなたは疲れない. 休んでいる最中はもう一度できない
        reset(energy=30)
        assert avail("rest_out")["ok"], avail("rest_out")
        e0, s0 = st["params"]["energy"], ps["stamina"]
        r = app.act("rest_out", cid)
        assert app.resting(st["override"], time.time()) and app.with_load(time.time()) == ("tire", 0.0)
        a = avail("rest_out")
        assert not a["ok"] and "ひと休み" in a.get("why", ""), a
        try:
            app.act("rest_out", cid)
            raise AssertionError("休んでいる最中にもう一度休めた")
        except ValueError:
            pass
        run(30)
        de, ds = st["params"]["energy"] - e0, ps["stamina"] - s0
        assert de >= 3, ("休んで相手の体力が戻っていない", de)
        assert ds >= -0.1, ("休んでいる間に疲れた", ds)
        assert not app.resting(st["override"], time.time())
        print("ひと休み: OK | 30 分で相手 %+.1f・あなた %+.1f / %s" % (de, ds, r["entry"]["text"].splitlines()[0][:40]))

        # ---- 2. 疲れているときは喜ばれる反応 / 元気なのに続けて休むと「さっき休んだばかり」(機嫌が少し下がる)
        reset(energy=25)
        app.act("rest_out", cid)
        assert picked[-1] == "tired", picked[-1]
        reset(energy=85)
        app.act("rest_out", cid)
        run(40)
        app.set_params({"energy": 85, "mood": 70}, cid)
        m0 = st["params"]["mood"]
        r = app.act("rest_out", cid)
        assert picked[-1] == "again", (picked[-1], r["entry"]["text"])
        assert st["params"]["mood"] < m0, (m0, st["params"]["mood"])
        print("続けて休む: OK | %s" % r["entry"]["text"].splitlines()[0])

        # ---- 3. 移動中は休めない (画面と act がそろう)
        reset()
        G.INSTANT = False
        try:
            st["override"]["arr"] = time.time() + 600       # まだ向かっている途中
            a = avail("rest_out")
            assert not a["ok"], a
            try:
                app.act("rest_out", cid)
                raise AssertionError("移動中に休めた")
            except ValueError:
                pass
            a = avail("taxi_home")
            assert not a["ok"], a
        finally:
            G.INSTANT = True
        print("移動中: OK | ひと休み・タクシーとも押せない")

        # ---- 4. 場所で相手の体力が変わる: 休んでいる間 > カフェ (座る) > 散歩 > 遊園地
        reset(aid="cafe")
        ec = app.with_energy(cid, time.time())
        reset(aid="walk")
        ew = app.with_energy(cid, time.time())
        reset(aid="amusement")
        ea = app.with_energy(cid, time.time())
        assert app.REST_ENERGY > ec >= 0 > ew > ea, (ec, ew, ea)
        assert app.with_energy(cid, time.time() + 9 * 3600) is None          # 出かけていなければ, ふだんどおり
        print("場所ごとの相手の体力: OK | カフェ %+.1f / 散歩 %+.1f / 遊園地 %+.1f（1 時間）" % (ec, ew, ea))

        # ---- 5. 疲れているときに解散: 気づいてもらえることがあるが, 確実ではない. 元気なときは起きない
        hit = 0
        for _ in range(60):
            reset(energy=25)
            app.act("go_home", cid)
            hit += picked[-1] == "noticed"
        assert 0 < hit < 60, hit
        n = 0
        for _ in range(20):
            reset(energy=80)
            app.act("go_home", cid)
            n += picked[-1] == "noticed"
        assert n == 0, n
        print("疲れているときの解散: OK | 60 回中 %d 回、気づいてもらえた（元気なときは 0）" % hit)

        # ---- 6. タクシー: 運賃はあなた持ち. 見込みは押す前に出る
        reset(energy=25)
        a = avail("taxi_home")
        assert a["ok"] and "円" in a.get("confirm", ""), a
        q = app.taxi_quote(cid, time.time())
        m0 = ps["money"]
        r = app.act("taxi_home", cid)
        assert ps["money"] == m0 - q["fare"], (m0, ps["money"], q)
        assert "タクシー" in r["entry"]["text"] and not st.get("override"), r["entry"]["text"]
        assert B.mode(cid) is None
        print("タクシー: OK | %s円 / %s" % (q["fare"], r["entry"]["text"].replace("\n", " ")[:80]))

        # ---- 7. 引き止められたら呼ばない (払わない). お金が足りなければ押せても断る
        reset(energy=60)
        PT.FIXED = "hold"
        m0 = ps["money"]
        r = app.act("taxi_home", cid)
        assert ps["money"] == m0 and st.get("override"), "引き止められたのに払った / 帰った"
        PT.FIXED = "ok"
        ps["money"] = 10
        try:
            app.act("taxi_home", cid)
            raise AssertionError("お金が足りないのにタクシーで帰れた")
        except ValueError as e:
            assert "足りません" in str(e), e
        assert st.get("override")
        print("引き止め・お金: OK")

        # ---- 8. 同居相手: 二人で家へ. 帰る予定だった運賃 (行きのときに払った分) は二人に戻る
        reset()
        st["override"], st["cooldowns"] = None, {}
        B.end(go_home=False)
        app.presence.back(time.time())
        B.set_stage(cid, "live")
        B.sync(cid, st, time.time())
        G.INSTANT = False
        try:
            app.act("amusement", cid)                          # 家から二人で (行きと帰りの運賃を払う)
            ov = st["override"]
            back = sum(int(t.get("fare") or 0) for t in ov.get("trips") or [] if t["dir"] == "home")
            assert back > 0, ov.get("trips")
            off[0] += (ov["arr"] - time.time()) + 60          # 着いた
            app.tick(cid)
            q = app.taxi_quote(cid, time.time())
            assert q["both"] and q["to"] == engine.places_mod.HOME_ME, q
            m0, h0 = ps["money"], app.life.her_money(st)["a"]
            app.act("taxi_home", cid)
            assert ps["money"] == m0 - q["fare"] + back, (m0, ps["money"], q, back)
            assert app.life.her_money(st)["a"] == h0 + back
        finally:
            G.INSTANT = True
            B.set_stage(cid, "visit")
        print("同居相手とタクシー: OK | 運賃 %s円・戻った帰りの運賃 %s円" % (q["fare"], back))
    finally:
        time.time = real
        PT.FIXED = None
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK")


if __name__ == "__main__":
    main()
