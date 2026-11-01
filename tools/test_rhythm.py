"""生活リズムの揺らぎ (一時データ, 画像生成なし).
- 寝坊 (起きる時刻を過ぎてもまだ寝ている) / 早起き / 早寝 / 夜ふかし (日付をまたいでも起きている) / 徹夜 (翌朝まで起きている) / 残業
- その日のずれは一度決めたら変わらない. 入れる前の日 (rhythm_since より前) は揺らさない
- ずれ幅は性格の時間の正確さしだい (ルーズな性格ほど夜ふかし・寝坊が多く, ずれも大きい)
- 疲れていると早寝しやすい

    python tools/test_rhythm.py
"""
import os
import shutil
import sys
import tempfile
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from core.engine import day_match  # noqa: E402
from core.rhythm import decide  # noqa: E402


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        st["rhythm_since"] = "2026-01-01"
        R = st.setdefault("rhythm", {})
        at = lambda d, h, m=0: app.scheduled_scene(char, datetime(2026, 11, d, h, m))     # noqa: E731
        none = {"wake": 0, "bed": 0, "all_night": False, "ot": 0}

        def plan(d, **kw):
            R["2026-11-%02d" % d] = dict(none, **kw)
        for d in range(1, 12):
            plan(d)
        # 平日 (11/2 月) は 6:30 起き, 夜は 24:00 に寝る
        assert at(2, 6, 45)["asleep"] is False and at(2, 23, 50)["asleep"] is False and at(3, 0, 10)["asleep"]
        # 寝坊: 6:30 を過ぎてもまだ寝ている
        plan(3, wake=40)
        assert at(3, 6, 50)["asleep"] and not at(3, 7, 15)["asleep"]
        # 早起き: 6:00 にはもう起きている
        plan(4, wake=-30)
        assert not at(4, 6, 5)["asleep"] and at(4, 5, 55)["asleep"]
        # 早寝: 23:00 にはもう寝ている
        plan(4, wake=-30, bed=-60)
        assert at(4, 23, 10)["asleep"] and not at(4, 22, 50)["asleep"]
        # 夜ふかし: 日付をまたいで 1:00 まで起きている
        plan(5, bed=60)
        s = at(6, 0, 30)
        print("夜ふかし:", s["label"], "/ 1:10 は", at(6, 1, 10)["label"])
        assert not s["asleep"] and "夜ふかし" in s["label"] and at(6, 1, 10)["asleep"]
        # 徹夜: 翌朝の起きる時刻まで起きている
        plan(9, all_night=True)
        s = at(10, 3, 0)
        print("徹夜:", s["label"])
        assert not s["asleep"] and "徹夜" in s["label"] and not at(10, 7, 0)["asleep"]
        # 残業: 土曜 (11/7) のバイト 10:00〜14:00 が延びる
        plan(7, ot=60)
        s = at(7, 14, 30)
        print("残業:", s["label"])
        assert s["away"] and "残業" in s["label"] and not at(7, 15, 10)["away"]

        # 一度決めたら変わらない. 入れる前の日は揺らさない
        R.clear()
        st["rhythm_since"] = "2026-11-05"
        p1 = app.rhythm.plan(char, date(2026, 11, 6))
        assert app.rhythm.plan(char, date(2026, 11, 6)) == p1 and app.rhythm.plan(char, date(2026, 11, 4)) is None

        # 性格: ルーズな性格ほど夜ふかし・寝坊が多い. 疲れていると早寝しやすい
        def stats(persona, energy=60):
            c = dict(char, persona_id=persona, id="x")
            s0 = {"params": dict(st["params"], energy=energy, health=90)}
            ds = [decide(app, c, s0, date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + i), day_match) for i in range(400)]
            late = sum(1 for x in ds if x["bed"] > 0 or x["all_night"]) / 400.0
            early = sum(1 for x in ds if x["bed"] < 0) / 400.0
            wake = sum(abs(x["wake"]) for x in ds) / 400.0
            allnight = sum(1 for x in ds if x["all_night"])
            return late, early, wake, allnight
        tight, loose = stats("jimuteki"), stats("rakuten")
        print("実務派 (夜ふかし %.2f, 早寝 %.2f, 起床のずれ %.0f分, 徹夜 %d) / 楽天家 (%.2f, %.2f, %.0f分, %d)" % (tight + loose))
        assert loose[0] > tight[0] * 2 and loose[2] > tight[2] * 1.5 and loose[3] <= 20
        tired = stats("teinei", energy=15)
        assert tired[1] > stats("teinei")[1] + 0.15, tired
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
