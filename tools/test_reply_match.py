"""返信の速さを, あなたに合わせる (残件 A15 の段 4. core/regard.py の match_shift・engine.reply_delay):
覚えたあなたのふだんの返す速さに, 性格しだいで相手の待ちを寄せる.

    python tools/test_reply_match.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, regard as RG, replyspeed as R, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)

SPEEDS = {"fast": 2.0, "mid": 40.0, "slow": 240.0}      # あなたのふだんの返すまでの分
DEPS = {"low": 20.0, "mid": 50.0, "high": 90.0}          # 依存度


def main():
    random.seed(12)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("合わせ")
        G = app.regard
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        st["override"] = {"activity": "relax", "label": "くつろいでいる", "location": "自宅", "until": time.time() + 9e6}
        now = time.time()

        def dep(v):
            st["attach"] = dict(app.attach.rec(char, st), dependence=float(v))

        def teach(slow, n=12.0, r=None):
            h = G.habit(char, st)
            h["all"] = {"n": float(n), "r": float(n if r is None else r), "slow": float(slow), "t": now}

        def forget():
            G.habit(char, st)["all"] = {}

        # ---- 1. 記録が無い・少ないうちは寄せない (以前と同じ待ち)
        char["persona_id"] = "tsundere"
        dep(20)
        forget()
        assert G.match_shift(char, st, 600, now) == 0
        teach(240, n=3.0)
        assert G.match_shift(char, st, 600, now) == 0, "数が HABIT_MIN 未満"
        teach(240, n=12.0, r=1.0)
        assert G.match_shift(char, st, 600, now) == 0, "返した数が 2 件未満"
        print("覚えるまでは寄せない: OK")

        # ---- 2. 性格 27 × あなたの速さ 3 × 依存度 3 × 相手の待ち 4 の総当たり
        rows = 0
        for pid in sorted(app.personas):
            char["persona_id"] = pid
            for dname, dv in DEPS.items():
                dep(dv)
                for sname, slow in SPEEDS.items():
                    teach(slow)
                    for base in (30, 600, 3600, 4 * 3600):
                        sh = G.match_shift(char, st, base, now)
                        rows += 1
                        assert abs(sh) <= RG.MATCH_CAP + 1e-6, (pid, sname, base, sh)
                        gap = slow * 60 - base
                        assert sh == 0 or (sh > 0) == (gap > 0), "あなたの速さの向きにだけ寄せる"
                        assert abs(sh) <= abs(gap) + 1e-6, "あなたの速さを越えて寄せない"
                        if pid in ("fushigi", "tenshin") or dname == "high":
                            assert sh == 0, ("気にしない性格・依存度が高いと寄せない", pid, dname, sh)
        print("総当たり %d 通り: ±30 分まで・向き・越えない・気にしない人は 0: OK" % rows)

        # 張り合う性格は, ふつうの性格より大きく寄る (同じ条件で)
        dep(20)
        teach(40)                                    # 待ち 10 分に対して 40 分 (上限に当たらない差)
        sh = {}
        for pid in ("tsundere", "sadist", "genki", "fushigi", "tenshin"):
            char["persona_id"] = pid
            sh[pid] = G.match_shift(char, st, 600, now)
        assert sh["tsundere"] > sh["genki"] > 0 and sh["sadist"] > sh["genki"], sh
        assert sh["fushigi"] == 0 and sh["tenshin"] == 0, sh
        teach(2)
        char["persona_id"] = "tsundere"
        assert G.match_shift(char, st, 1800, now) < 0, "あなたが速ければ, 張り合う人も速く返す"
        print("張り合う > ふつう > 気にしない: OK", {k: round(v / 60, 1) for k, v in sh.items()})

        # 依存度が上がるほど弱まる
        char["persona_id"] = "tsundere"
        teach(40)
        seq = []
        for dv in (30, 50, 60, 70, 80):
            dep(dv)
            seq.append(G.match_shift(char, st, 600, now))
        assert all(a >= b for a, b in zip(seq, seq[1:])) and seq[0] > 0 and seq[-1] == 0, seq
        print("依存度で弱まる: OK")

        # 慣れが浅いと弱く
        dep(20)
        teach(40, n=4.0)
        weak = G.match_shift(char, st, 600, now)
        teach(40, n=16.0)
        full = G.match_shift(char, st, 600, now)
        assert 0 < weak < full, (weak, full)
        print("慣れが浅いと弱い: OK")

        # traits.reply_match があればそちら
        char["persona_id"] = "genki"
        tr = app.traits(char)
        old = tr.get("reply_match")
        tr["reply_match"] = 0.0
        assert G.match_shift(char, st, 600, now) == 0
        if old is None:
            tr.pop("reply_match", None)
        else:
            tr["reply_match"] = old
        print("traits.reply_match: OK")

        # ---- 3. reply_delay: quick (まだスマホを見ている) は寄せない・下限上限・乱数の順をずらさない
        char["persona_id"] = "tsundere"
        dep(20)
        teach(240)
        sc = app.scene_at(char, st, engine.datetime.fromtimestamp(now))
        orig = app._still_on_phone
        app._still_on_phone = lambda *a, **k: True
        try:
            d, quick, _ = app.reply_delay(char, st, now, sc, {})
            assert quick and d <= 90, "quick のときは寄せない"
        finally:
            app._still_on_phone = orig
        app._still_on_phone = lambda *a, **k: False
        try:
            def draws(learned):
                if learned:
                    teach(240)
                else:
                    forget()
                random.seed(77)
                out = []
                for _ in range(200):
                    d, q, hand = app.reply_delay(char, st, now, sc, {})
                    out.append(d)
                    assert R.MIN_S <= d <= R.MAX_S
                    if hand:
                        assert d <= R.QUICK[1]
                return out, random.random()
            a, ra = draws(False)
            b, rb = draws(True)
            assert ra == rb, "全体の乱数の順をずらさない"
            diff = [y - x for x, y in zip(a, b)]
            assert all(abs(x) <= RG.MATCH_CAP + 1e-6 for x in diff), "30 分まで"
            assert all(x == 0 or (x > 0) == (240 * 60 > y) for x, y in zip(diff, a)), "あなたの 4 時間に向かって寄る"
            assert sum(1 for x in diff if x > 0) > 150, "ほとんどの返事が寄る"
            print("reply_delay: quick は寄せない・下限上限・乱数の順: OK (平均 +%.1f 分)" % (sum(diff) / len(diff) / 60))
        finally:
            app._still_on_phone = orig

        # ---- 4. 実際の送信: 覚える前と後で, 張り合う人の待ちが延びる
        def sent(learned, n=40):
            if learned:
                teach(240)
            else:
                forget()
            random.seed(5)
            dues = []
            for _ in range(n):
                st.pop("msg_pending", None)
                st["contacts"], st["phone_until"] = [], 0
                st.pop("nori", None)
                app.chat.send(cid, "smalltalk")
                dues.append(st["msg_pending"]["due"] - time.time())
            return sum(dues) / len(dues)
        before, after = sent(False), sent(True)
        assert after > before, (before, after)
        print("送信: 平均 %.1f 分 → %.1f 分: OK" % (before / 60, after / 60))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
