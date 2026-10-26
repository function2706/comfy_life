"""謝って消えるのは あなたのせいの理由だけ / 相談で和らぐのは出来事の理由だけ (一時データディレクトリ, 画像生成なし).

    python tools/test_apology_scope.py
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
    random.seed(1)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        L = app.life
        char, st = app.char(), app.state("hina")
        now = time.time()

        random.gauss = lambda m, s: 0.0         # 許し方の揺らぎ (幅は tools/test_manners.py). ここでは, すぐ許してくれる場合の範囲を見る

        def setup():
            st["reasons"], st["apologies"] = [], []
            st["params"].update(mood=55, affection=60, trust=60)
            L.add_reason(st, "event", "bad", "仕事で嫌なことがあった", now - 60, told=True, delta=-1.5)
            L.add_reason(st, "player", "bad", "連絡が多くて、少し疲れた", now, told=True, delta=-2.0, action="_too_often")

        def left():
            return sorted(r["kind"] for r in L.reasons(st, time.time()) if r["mood"] == "bad" and not r.get("resolved"))

        # メッセージで謝る (chat.reply): あなたのせいの理由だけ消える
        setup()
        assert L.dominant(st, now, "bad")["kind"] == "player"
        key, _, _ = app.chat.reply(char, st, "apology", now, {})
        assert key == "apology", key
        assert left() == ["event"], left()
        print("メッセージで謝る: 残った理由", left())

        # その場で謝る・相談にのる (反応のあとの理由の記録)
        setup()
        app._act_reasons(char, st, {"id": "apologize", "mood_action": "apologize"}, {}, {}, now)
        assert left() == ["event"], left()
        print("その場で謝る: 残った理由", left())
        st["reasons"] = []
        L.add_reason(st, "player", "bad", "からかわれた", now - 60, told=True, delta=-3.0)
        L.add_reason(st, "event", "bad", "仕事で嫌なことがあった", now, told=True, delta=-9.0)
        assert L.dominant(st, now, "bad")["kind"] == "event"
        app._act_reasons(char, st, {"id": "comfort", "mood_action": "comfort"}, {}, {}, now)
        assert left() == ["player"], left()
        print("相談にのる: 残った理由", left())
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
