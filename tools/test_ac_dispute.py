"""同居のエアコン争い (S58. core/aircon.py・core/season.py の pref_room / ac_fuss / ac_best).

好みの室温の向き (暑がりは低め・寒がりは高め)・合わない度合いの符号・いちばん合う使い方 × 性格 × 気温の総当たり・
変えても過ごしやすくならない季節は何もしない・一日に一度・1 時間に一度だけ見る・出方の割合 (言う / 変える / 我慢. 必ずではない)・
離れている / 寝ている / 同居でないときは起きない・言ってきたことへの出方 (合わせる・電気代・言い返す)・電気代の選択肢は高くなるときだけ・
答えないままはうやむや・あなたが変えたときの反応 (戻した・暑くなった・ありがとう・同じ使い方の二度押し・続けて押す)・開き直しで残る.

    python tools/test_ac_dispute.py
"""
import collections
import os
import random
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from core import engine, season, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def fixed(t):
    season.temp = lambda dt, wx=None: float(t)
    season.day_range.cache_clear()


def main():
    random.seed(58)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("エアコン")
        A, H = app.aircon, app.home
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        tr0 = dict(app.traits(char))

        def with_sense(heat, cold, approach=None):
            tr = dict(tr0, heat=heat, cold=cold)
            if approach is not None:
                tr["approach"] = approach
            app.traits = lambda c, tr=tr: tr

        # ---- 1. 好みの室温の向きと幅・合わない度合いの符号 (キャラごとの揺れ ±15% はこのテストでは外して, 性格の値どおりに)
        season._jitter = lambda cid, k: 1.0
        for t in (33, 30, 5, 0):
            with_sense(1.3, 0.9)
            hot_p = season.pref_room(app, char, t)
            with_sense(0.9, 1.3)
            cold_p = season.pref_room(app, char, t)
            with_sense(1.0, 1.0)
            mid = season.pref_room(app, char, t)
            assert hot_p < mid < cold_p, (t, hot_p, mid, cold_p)
            lo, hi = (23.5, 28.0) if season.warm_half(t) else (18.0, 24.0)
            assert all(lo <= x <= hi for x in (hot_p, mid, cold_p))
        with_sense(1.3, 1.1)            # 暑がり (やれやれ系): 真夏の控えめ (27℃) は暑い, しっかり (25℃) はちょうどいい
        assert season.ac_fuss(app, char, 33, "eco") > 0 and season.ac_fuss(app, char, 33, "strong") == 0
        assert season.ac_best(app, char, 33) == "strong"
        with_sense(1.0, 1.2)            # 寒がり: 真夏のしっかりは寒い, 控えめがいい
        assert season.ac_fuss(app, char, 33, "strong") < 0 and season.ac_fuss(app, char, 33, "eco") == 0
        assert season.ac_best(app, char, 33) == "eco"
        assert season.ac_fuss(app, char, 2, "eco") < 0 and season.ac_best(app, char, 2) == "strong"     # 真冬の控えめ (20℃) は寒い
        with_sense(1.3, 1.1)
        assert season.ac_fuss(app, char, 2, "strong") > 0 and season.ac_best(app, char, 2) == "eco"     # 暑がりに真冬のしっかり (22℃) は暑い
        with_sense(0.8, 0.8)            # 気にしない人: 冷暖房が動いていればどちらでも
        for t in (33, 2):
            assert season.ac_fuss(app, char, t, "eco") == 0 and season.ac_fuss(app, char, t, "strong") == 0
            assert season.ac_best(app, char, t) == "eco"          # 同じなら安い方 (使わないは暑い / 寒い)
        print("好みの室温: OK 真夏 暑がり %.1f / ふつう %.1f / 寒がり %.1f℃" % (
            (with_sense(1.3, 0.9), season.pref_room(app, char, 33))[1], (with_sense(1, 1), season.pref_room(app, char, 33))[1],
            (with_sense(0.9, 1.3), season.pref_room(app, char, 33))[1]))

        # ---- 2. 総当たり: 性格の値 × 気温 × 使い方. 符号は室温と好みの向き, いちばん合う使い方の度合いは, ほかより大きくない
        n = 0
        for heat in (0.7, 0.9, 1.0, 1.2, 1.4):
            for cold in (0.7, 0.9, 1.0, 1.2, 1.4):
                with_sense(heat, cold)
                for t in range(-4, 39, 2):
                    p = season.pref_room(app, char, t)
                    b = season.ac_best(app, char, t)
                    for m in season.AC_ORDER:
                        f = season.ac_fuss(app, char, t, m)
                        r = season.room(t, m)[0]
                        assert (f > 0) <= (r > p) and (f < 0) <= (r < p), (heat, cold, t, m, f, r, p)
                        assert abs(f) <= 0 or abs(r - p) > season.FUSS_OK
                        assert abs(season.ac_fuss(app, char, t, b)) <= abs(f) + 1e-9
                        n += 1
        print("総当たり: OK %d 通り" % n)

        # ---- 3. 毎時の出方: 同居して家で一緒・起きているときだけ. 1 時間に一度・一日に一度. 必ずではない
        app.bonds.set_stage(cid, "live")
        app.presence.declare("none")
        app.presence.beat(time.time(), 0)
        fixed(33)
        H.set_mode("eco")

        def reset():
            for k in ("ac_talk", "ac_day", "ac_check", "ac_self", "ac_note", "fight"):
                st.pop(k, None)
            H.set_mode("eco")
            st["params"]["mood"] = 60

        def tally(n=400, heat=1.3, cold=1.1, approach=1.0, persona=None):
            with_sense(heat, cold, approach)
            if persona:
                char["persona_id"] = persona
            c = collections.Counter()
            for _ in range(n):
                reset()
                A.tick(char, st, time.time())
                c["say" if st.get("ac_talk") else "self" if st.get("ac_self") else "none" if not st.get("ac_day") else "endure"] += 1
            return c
        assert A.awake_home(cid, time.time())
        c = tally()
        assert all(c[k] > 0 for k in ("say", "self", "endure", "none")), c        # どれも起きる. 何もしない日もある
        assert c["none"] > 100, c
        shy, bold = tally(1500, approach=0.5, persona="tenshin"), tally(1500, approach=1.4, persona="jimuteki")
        assert bold["say"] / float(bold["endure"]) > 1.3 * shy["say"] / float(shy["endure"]) and bold["self"] > 2 * shy["self"] and shy["endure"] > bold["endure"], (shy, bold)
        print("出方: OK 暑がり %s / 控えめ %s / 仕切る %s" % (dict(c), dict(shy), dict(bold)))
        with_sense(1.3, 1.1, 1.0)
        mild = tally(heat=1.1, cold=1.0)
        assert sum(mild[k] for k in ("say", "self", "endure")) < sum(c[k] for k in ("say", "self", "endure")), (mild, c)
        # 合わない度合いが小さい / 変えても良くならない / 気にしない人は何もしない
        for t, heat, cold in ((22, 1.4, 1.4), (33, 0.8, 0.8), (2, 0.8, 0.8)):
            fixed(t)
            k = tally(50, heat, cold)
            assert k["none"] == 50, (t, heat, cold, k)
        fixed(33)
        # 一日に一度・1 時間に一度
        with_sense(1.4, 1.0, 1.0)
        reset()
        now = time.time()
        k = 0
        for i in range(30):
            A.tick(char, st, now + i * 60)
            k += st.get("ac_check") == now + i * 60
        assert k == 1, k
        reset()
        st["ac_day"] = time.strftime("%Y-%m-%d")
        for i in range(10):
            st.pop("ac_check", None)
            A.tick(char, st, now)
        assert not st.get("ac_talk") and not st.get("ac_self")
        # 離れている・寝ている・同居でない
        reset()
        app.presence.declare("out")
        assert not A.awake_home(cid, time.time())
        app.presence.declare("sleep")
        assert not A.awake_home(cid, time.time())
        app.presence.declare("none")
        app.presence.beat(time.time(), 0)
        app.bonds.set_stage(cid, "visit")
        assert not A.awake_home(cid, time.time()) and A.pending() is None
        app.bonds.set_stage(cid, "live")
        assert A.awake_home(cid, time.time())
        print("起きる条件: OK")

        # ---- 4. 言ってきたことへの出方
        def ask(want="strong", hot=True):
            reset()
            st["ac_talk"] = {"t": time.time(), "want": want, "from": H.ac_mode(), "hot": hot}
        ask()
        pv = A.pending()
        assert pv and [x["id"] for x in pv["choices"]] == ["match", "bill", "push"], pv
        r = A.respond("match")
        assert H.ac_mode() == "strong" and r["key"] == "match" and not st.get("ac_talk")
        assert r["entry"]["text"].startswith("（冷暖房を「しっかり」にした）")
        try:
            A.respond("match")
            assert False, "二度答えられた"
        except ValueError:
            pass
        # 安い方へ変えたい (寒い): 電気代の選択肢は出ない
        ask("eco", hot=False)
        H.set_mode("strong")
        assert [x["id"] for x in A.pending()["choices"]] == ["match", "push"]
        try:
            A.respond("bill")
            assert False, "出ていない選択肢に答えられた"
        except ValueError:
            pass
        keys = collections.Counter()
        fights = 0
        for i in range(200):
            ask()
            r = A.respond("bill" if i % 2 else "push")
            keys[r["key"]] += 1
            assert H.ac_mode() == "eco"            # 断った・言い返したら変わらない
            fights += bool(st.get("fight"))
        assert all(keys[k] > 0 for k in ("bill_ok", "bill_meh", "push_unhappy", "push_fight")), keys
        assert fights == keys["push_fight"], (fights, keys)
        print("言ってきたことへの出方: OK %s" % dict(keys))
        # 答えないまま: うやむや
        ask()
        st["ac_talk"]["t"] -= 7 * 3600
        m0 = st["params"]["mood"]
        A.tick(char, st, time.time())
        assert not st.get("ac_talk") and st["params"]["mood"] < m0
        # 離れているときは選択肢を出さない (戻れば出る)
        ask()
        app.presence.declare("out")
        assert A.pending() is None
        app.presence.declare("none")
        app.presence.beat(time.time(), 0)
        assert A.pending()
        # 家の様子から叶えた: 言ってきたことは消える
        H.set_ac("strong")
        assert not st.get("ac_talk")
        print("答えないまま・離れている・先に叶えた: OK")

        # ---- 5. あなたが変えたとき
        with_sense(1.3, 1.1, 1.0)

        def press(old, new, self_t=None):
            reset()
            H.set_mode(old)
            if self_t is not None:
                st["ac_self"] = {"t": time.time() - self_t, "mode": old, "from": new}
            return H.set_ac(new)
        c = collections.Counter()
        for _ in range(200):
            r = press("strong", "eco", self_t=600)      # 相手が強くしたのを戻した
            c["undo" if r.get("entry") else "-"] += 1
            assert H.ac_mode() == "eco"
        assert 0.65 < c["undo"] / 200.0 < 0.95, c
        r0 = collections.Counter(bool(press("strong", "eco").get("entry")) for _ in range(200))
        assert 0.25 < r0[True] / 200.0 < 0.55, r0
        e = None
        while not e:
            e = press("strong", "eco").get("entry")
        assert e["aircon"] == "notice_hot", e["aircon"]
        e = None
        while not e:
            e = press("eco", "strong").get("entry")
        assert e["aircon"] == "thanks"
        # 同じ使い方の二度押し (二重に開いた画面): 何も起きない. 続けて押しても 30 分は言わない
        reset()
        H.set_mode("strong")
        st["ac_self"] = {"t": time.time(), "mode": "strong"}
        assert not H.set_ac("strong").get("entry")
        assert st.get("ac_self")
        random.seed(1)
        got = 0
        for _ in range(20):
            got += bool(H.set_ac("eco").get("entry"))
            got += bool(H.set_ac("strong").get("entry"))
        assert got <= 1, got
        # 離れている間に変えても, 何も言わない
        reset()
        H.set_mode("strong")
        app.presence.declare("out")
        assert all(not H.set_ac(m).get("entry") for m in ("eco", "strong", "eco"))
        app.presence.declare("none")
        app.presence.beat(time.time(), 0)
        print("あなたが変えたとき: OK 戻した %d/200・暑くなった %d/200" % (c["undo"], r0[True]))

        # ---- 6. 相手が自分で変えた: 家の使い方が変わる・開き直しで残る
        with_sense(1.4, 1.0, 0.1)
        char["persona_id"] = "jimuteki"
        done = False
        for _ in range(300):
            reset()
            A.tick(char, st, time.time())
            if st.get("ac_self"):
                done = True
                break
        assert done and H.ac_mode() == "strong"
        app.save_state(cid)
        app2 = engine.App()
        assert app2.home.ac_mode() == "strong" and app2.state(cid).get("ac_self", {}).get("mode") == "strong"
        print("自分で変えた・開き直し: OK")

        # ---- 7. 画面: 選択肢の箱が state_view に出る
        reset()
        st["ac_talk"] = {"t": time.time(), "want": "strong", "from": "eco", "hot": True}
        v = app.state_view(cid) if "cid" in app.state_view.__code__.co_varnames else app.state_view()
        assert v.get("ac_talk") and v["ac_talk"]["choices"], v.get("ac_talk")
        print("画面: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
