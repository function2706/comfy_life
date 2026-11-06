"""出先で画面を閉じたとき (offline.simulate の start): 家に寄らずに, その場所から行動パターン・予定の次の場所へ向かう
(すぐ始まるなら). 次が家でのことなら家へ帰る. 向かう途中で閉じたら, 着いてふだんどおりの長さを過ごしてから (outdoor.check_gap) (一時データ).

    python tools/test_closed_away.py
"""
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402


def main():
    random.seed(3)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("出先")
        O = app.offline
        d = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        d = next(d + timedelta(days=i) for i in range(1, 8) if (d + timedelta(days=i)).weekday() < 5)    # 平日 (09:00 から仕事)

        # 09:05 (仕事の時間) にスーパーで閉じた: 家に寄らずに, スーパーから職場へ
        rep = O.simulate(d.replace(hour=9, minute=5).timestamp(), d.replace(hour=11).timestamp(), start="supermarket")
        moves = [x["text"] for x in rep["timeline"] if x["do"] == "move"]
        print("09:05 スーパー:", moves[:2])
        assert moves and moves[0].startswith(app.places.label("supermarket") + "から" + app.places.label("office") + "へ"), moves
        assert not any(m.startswith(app.places.label("supermarket") + "から家へ") for m in moves), "家に寄った"

        # 20:30 に公園で閉じた: 次は家でのこと (休む・寝る) → 公園から家へ
        rep = O.simulate(d.replace(hour=20, minute=30).timestamp(), d.replace(hour=23, minute=30).timestamp(), start="park")
        moves = [x["text"] for x in rep["timeline"] if x["do"] == "move"]
        print("20:30 公園:", moves[:1])
        assert moves and moves[0].startswith(app.places.label("park") + "から家へ"), moves

        # 家から始める (これまでどおり): 出先の文は出ない
        rep = O.simulate(d.replace(hour=8, minute=40).timestamp(), d.replace(hour=11).timestamp())
        assert not any(x["text"].startswith(app.places.label("supermarket")) for x in rep["timeline"])
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
