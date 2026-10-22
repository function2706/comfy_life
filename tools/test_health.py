"""あなたの体調の確認 (一時データ, 画像生成なし).
- 栄養の偏り・寝不足・働きすぎ・空腹などが重なると崩しやすい (何もなければ, まれ)
- 段階: 軽い不調 → 風邪 → 寝込む. 休めば治ることも, 無理をすればこじらせることも. 薬は治りやすくする. 病院で軽いところまで戻る
- 体調が悪い間: 体力が戻りにくい・給料が下がる・スキルが伸びにくい. 寝込んでいると仕事に行けない. 行動パターンの仕事も休む

    python tools/test_health.py
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

fix_noon(engine)


def main():
    random.seed(11)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        B, L = app.body, app.life
        b = B.rec()
        t = time.mktime((2026, 10, 20, 0, 1, 0, 0, 0, -1))
        app.presence.rec()["beat"] = app.presence.rec()["input"] = time.time()

        def good_day():
            b["nutri"] = {"staple": 70.0, "protein": 70.0, "veg": 70.0}
            b["today"] = {"slept": 7.5}
            L.player_state()["work_log"] = {}
            L.player_state()["stamina"] = 80.0

        def bad_day():
            b["nutri"] = {"staple": 50.0, "protein": 12.0, "veg": 8.0}
            b["today"] = {"slept": 4.0, "hungry": 5.0}
            L.player_state()["stamina"] = 10.0

        # ---- 1. 崩しやすさ: 重なるほど高い. 何もなくても, まれ
        good_day()
        r_good, _ = B.risk(t)
        bad_day()
        r_bad, why = B.risk(t)
        assert r_good < 0.02 and r_bad > 0.15 and "sleep" in why and "nutri_veg" in why, (r_good, r_bad, why)
        sick = {"good": 0, "bad": 0}
        for kind, f in (("good", good_day), ("bad", bad_day)):
            for _ in range(300):
                b["health"] = {"level": 0, "since": None}
                f()
                B.daily(t)
                sick[kind] += b["health"]["level"] > 0
        assert sick["good"] < 20 and sick["bad"] > 3 * sick["good"] + 30, sick
        print("崩した回数 (300 日): ふつうの日 %d / 無理した日 %d" % (sick["good"], sick["bad"]))

        # ---- 2. 休めば治る. 無理をするとこじらせる. 薬は治りやすい
        def days_to_heal(f, med=False, n=200):
            tot = 0
            for _ in range(n):
                b["health"] = {"level": 2, "since": t}
                d = 0
                while b["health"]["level"] > 0 and d < 60:
                    f()
                    if med:
                        b["health"]["med_until"] = t + 86400
                    B.daily(t)
                    d += 1
                tot += d
            return tot / float(n)
        rest = days_to_heal(good_day)
        medd = days_to_heal(good_day, med=True)
        hard = days_to_heal(bad_day)
        assert medd < rest < hard, (medd, rest, hard)
        print("風邪が治るまで: 休む %.1f 日 / 薬 %.1f 日 / 無理を続ける %.1f 日" % (rest, medd, hard))

        # ---- 3. 体調が悪い間の不利. 寝込むと仕事に行けない
        good_day()
        b["health"] = {"level": 0}
        pay0 = L.work_pay(t + 9 * 3600, t + 12 * 3600)[0]
        b["health"] = {"level": 2}
        assert L.work_pay(t + 9 * 3600, t + 12 * 3600)[0] < pay0 and B.stamina_mult() < 1.0 and B.train_mult() < 1.0
        b["health"] = {"level": 3}
        try:
            app.solo.start("work")
            raise AssertionError("寝込んでいるのに仕事に行けた")
        except ValueError as e:
            assert "仕事に行けそうにない" in str(e)
        w = app.offline._work(t + 9 * 3600, t + 18 * 3600, 80.0)
        assert w["pay"] == 0 and "休んだ" in w["notes"][0]

        # ---- 4. 薬・病院
        app.items.add("cold_medicine", 1)
        b["health"] = {"level": 2}
        r = B.medicine()
        assert "風邪薬を飲んだ" in r["text"] and b["health"]["med_until"] > time.time() and app.items.count("cold_medicine") == 0
        b["health"] = {"level": 3}
        L.player_state()["money"] = 10000
        r = B.clinic()
        assert b["health"]["level"] == 1 and app.items.count("cold_medicine") == 2 and L.player_state()["money"] < 10000, r
        assert any(x["c"] == "medical" for x in app.kakeibo.rec()["raw"])
        print("病院:", r["text"])
        assert B.view()["health"]["word"] == "少しだるい"

        # ---- 5. キャラの反応: そばにいる人が顔色に気づいて看病してくれる (bonds.realize を通る). 一緒に外食すると, あなたも食べる
        st = app.state("hina")
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": time.time() + 9e6}
        b["health"] = {"level": 2}
        e = app.force_approach("worry_you", "hina")["entry"]
        assert "顔色" in e["text"], e["text"]
        sat0 = b["satiety"] = 20.0
        r = app.answer_approach("accept", "hina")
        assert b["health"].get("care_until", 0) > time.time() and b["satiety"] > sat0, r
        print("看病:", r["entry"]["text"])
        b["health"] = {"level": 0}
        app.set_params({"energy": 80, "sleepiness": 0, "mood": 60, "affection": 60}, "hina")
        L.player_state()["money"] = 50000
        b["satiety"] = 20.0
        n0 = len(b["meals"])
        r = app.act("eat_out", "hina", opts={"place": "ramen"})
        assert len(b["meals"]) == n0 + 1 and b["satiety"] > 40, (r["entry"]["text"], b["satiety"])
        assert any(x["c"] == "eatout" and x["a"] < 0 for x in app.kakeibo.rec()["raw"]) or r["entry"].get("money", {}).get("p") is None
        print("一緒に外食:", " / ".join(r["entry"]["text"].splitlines()))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
