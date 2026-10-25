"""夜中・早朝の連絡の確認 (一時データ, 画像生成なし).
- 予定に睡眠が一つも無いキャラは, 1:00〜7:00 は寝ていることにする (一日中起きていることにしない)
- 離れている相手からのメッセージは, 起きていても夜中・早朝にはまず来ない (presence.hour_factor)
- 画面を閉じていた間に届くメッセージも, 相手が寝ている・手が離せない時間には届かない (offline._awake_slots)

    python tools/test_dawn.py
"""
import os
import random
import shutil
import sys
import tempfile
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, presence  # noqa: E402


def ts(*a):
    return datetime(*a).timestamp()


def main():
    random.seed(4)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("早朝")
        # ---- 睡眠の予定が無いキャラ
        bare = {"id": "x", "name": "x", "schedule": [{"days": "all", "from": "12:00", "to": "13:00", "activity": "lunch", "label": "お昼"}],
                "default_activity": {"activity": "relax", "label": "くつろぎ"}}
        assert app.scheduled_scene(bare, datetime(2026, 10, 26, 3, 0))["asleep"], "睡眠の予定が無くても, 夜中は寝ている"
        assert not app.scheduled_scene(bare, datetime(2026, 10, 26, 9, 0))["asleep"]
        assert app.scheduled_scene(bare, datetime(2026, 10, 26, 12, 30))["label"] == "お昼"
        hina = app.chars.get("hina")
        if hina:     # 睡眠の予定があるキャラはその予定どおり (既定の睡眠は足さない)
            assert app.scheduled_scene(hina, datetime(2026, 10, 25, 7, 30))["asleep"], "ひなの週末は 8 時まで寝ている"
            assert not app.scheduled_scene(hina, datetime(2026, 10, 26, 6, 45))["asleep"]

        # ---- 時刻の重み
        hf = presence.hour_factor
        assert hf(datetime(2026, 10, 26, 5, 0)) < 0.05 and hf(datetime(2026, 10, 26, 3, 0)) < 0.05
        assert hf(datetime(2026, 10, 26, 6, 30)) < hf(datetime(2026, 10, 26, 12, 0)) == 1.0

        # ---- 閉じていた間 (0:00〜12:00) に届くメッセージの時刻
        O = app.offline
        cid = next(c for c in app.chars if app.bonds.stage(c) in ("contact", "visit", "live"))
        char = dict(app.chars[cid], schedule=[e for e in app.chars[cid].get("schedule") or [] if not e.get("asleep")])   # 予定に睡眠が無い人でも
        st = app.state(cid)
        hours = Counter()
        for i in range(400):
            slots = O._awake_slots(char, st, ts(2026, 10, 26, 0, 0), ts(2026, 10, 26, 12, 0))
            t, w = zip(*slots)
            sent = random.choices(t, w)[0] + random.random() * 1800
            hours[datetime.fromtimestamp(sent).hour] += 1
        print("閉じていた間に届いた時刻:", dict(sorted(hours.items())))
        assert sum(v for h, v in hours.items() if 1 <= h < 6) == 0, "1:00〜7:00 は寝ている (既定の睡眠)"
        assert sum(v for h, v in hours.items() if h >= 8) > 300
        # ひなの予定 (平日は 6:30 まで寝ている): 起きる前には届かない
        if hina:
            slots = O._awake_slots(hina, app.state("hina"), ts(2026, 10, 26, 0, 0), ts(2026, 10, 26, 12, 0))
            assert all(datetime.fromtimestamp(t).hour * 60 + datetime.fromtimestamp(t).minute >= 6 * 60 + 30 for t, _ in slots)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp + "_backup", ignore_errors=True)


if __name__ == "__main__":
    main()
