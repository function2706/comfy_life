"""行動パターン (曜日ごとの 1 日の流れ) の確認: 画面を閉じている間はこの流れに沿って過ごす. 仕事・買い物 (買うものリスト)・
家事・研鑽・散歩, 予定どおりにいかないこと (雨で散歩をやめる・疲れて家事を飛ばす), 時系列のまとめ (一時データ, 画像生成なし).

    python tools/test_routine.py
"""
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, offline, outdoor, store  # noqa: E402


def ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").timestamp()


def main():
    random.seed(53)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("流れ")
        O, L, I = app.offline, app.life, app.items
        ps = L.player_state()
        ps["money"] = 100000

        # ---- 1. 既定の流れ: 平日は 起床 → 朝食 → 仕事 (昼食を挟む) → 買い物 → 夕食 → 休む → 寝る. 休日は別
        mon = [b["do"] for b in O.cfg()["days"]["mon"]]
        sun = [b["do"] for b in O.cfg()["days"]["sun"]]
        assert mon == ["sleep", "meal", "rest", "work", "meal", "work", "out", "meal", "rest", "sleep"] and "work" not in sun, (mon, sun)
        bl = O.blocks(ts("2026-10-12 06:00"), ts("2026-10-12 20:00"))
        assert [(datetime.fromtimestamp(s).strftime("%H:%M"), b["do"]) for s, e, b in bl] == [
            ("06:00", "sleep"), ("07:00", "meal"), ("07:30", "rest"), ("09:00", "work"), ("12:00", "meal"), ("12:45", "work"),
            ("18:00", "out"), ("19:00", "meal"), ("19:45", "rest")], bl

        # ---- 2. 閉じていた間を, 流れに沿って過ごす: 仕事の給料, 買い物で買うものリストの品を買う, 時系列のまとめ
        I.set_list("veggies", 1)
        L.player_state()["work_log"] = {}
        rep = O.simulate(ts("2026-10-12 06:00"), ts("2026-10-12 22:00"))
        dos = [x["do"] for x in rep["timeline"]]
        assert dos[:7] == ["sleep", "meal", "rest", "work", "meal", "work", "out"], dos
        shop = next(x for x in rep["timeline"] if x["do"] == "out")
        assert shop["place"] == "supermarket" and "スーパー" in shop["label"], shop
        assert I.count("veggies") >= 1 or "品切れ" in shop["text"] or shop["skipped"], shop     # 野菜は 1 個 3 回分 (夕食の自炊で使う)
        assert rep["works"] and rep["works"][0]["pay"] > 0
        print("timeline:", [(datetime.fromtimestamp(x["t"]).strftime("%H:%M"), x["text"][:24]) for x in rep["timeline"]])

        # ---- 3. 自分で決めた流れ (曜日ごと). 家事・研鑽・散歩. 予定どおりにいかないことも
        # (以前の「散歩」は, 外出 + 行き先に読み替える)
        day = [{"at": "00:00", "do": "sleep"}, {"at": "08:00", "do": "chores"}, {"at": "10:00", "do": "practice", "skill": "cook"},
               {"at": "12:00", "do": "walk", "place": "riverside"}, {"at": "14:00", "do": "home"}]
        app.save_settings({"offline": {"days": {"mon": day}}})
        assert [b["do"] for b in O.cfg()["days"]["mon"]] == ["sleep", "chores", "practice", "out", "home"]
        assert O.cfg()["days"]["mon"][3]["place"] == "riverside"
        assert [b["do"] for b in O.cfg()["days"]["tue"]] == mon, "ほかの曜日は既定のまま"
        ps["items"]["book_cook"] = 1
        ps["stamina"] = 100
        sk0 = L.skill("cook")
        real_w = outdoor.weather
        outdoor.weather = lambda dt: dict(real_w(dt), id="sunny", label="晴れ", outdoor=1.0, indoor=1.0)
        rep = O.simulate(ts("2026-10-12 07:00"), ts("2026-10-12 15:00"))
        dos = [x["do"] for x in rep["timeline"]]
        assert dos == ["sleep", "chores", "practice", "out", "home"], dos
        assert L.skill("cook") > sk0 and "本を見ながら" in rep["timeline"][2]["text"], rep["timeline"][2]
        # 雨の日は散歩をやめることがある. 疲れていると家事を飛ばすことがある
        outdoor.weather = lambda dt: dict(real_w(dt), id="rain", label="雨", outdoor=0.35, indoor=0.85)
        skipped = {"out": 0, "chores": 0}
        for _ in range(20):
            ps["stamina"] = 10
            rep = O.simulate(ts("2026-10-12 07:00"), ts("2026-10-12 15:00"))
            for x in rep["timeline"]:
                if x["do"] in skipped and x["skipped"]:
                    skipped[x["do"]] += 1
        assert skipped["out"] >= 8 and skipped["chores"] >= 5, skipped
        outdoor.weather = real_w
        print("custom / skip: OK", skipped)

        # ---- 4. 以前の設定 (勤務時間) の読み替え
        days = offline.from_work({"mon": {"on": True, "from": "10:00", "to": "16:00"}, "sat": {"on": False}})
        assert [(b["at"], b["do"]) for b in days["mon"] if b["do"] == "work"] == [("10:00", "work")]
        assert "work" not in [b["do"] for b in days["sat"]]
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
