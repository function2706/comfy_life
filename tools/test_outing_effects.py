"""一人の外出の, あなたへの効き目の確認 (一時データ, 画像生成なし).
- 行き先の体の使い方: 山・遊園地・海・丘は, 同じ時間でも疲れて, 運動にもなる (places.effort)
- 雨・雪の日に屋外で過ごすと体が冷え, その日は体調を崩しやすい (body.risk の weather). 屋内なら濡れない
- カフェで座って一息つくと, 体力が少し戻る
- 出先の知らない人と立ち話をすると, 会話の練習になる

    python tools/test_outing_effects.py
"""
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, places, outdoor  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def find_day(want):
    d = datetime(2026, 10, 1, 13, 0)
    for i in range(400):
        x = d + timedelta(days=i)
        if outdoor.weather(x)["id"] in want and outdoor.weather(x - timedelta(hours=1))["id"] in want:
            return x
    raise AssertionError(want)


def main():
    random.seed(6)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("外出")
        L, S, B = app.life, app.solo, app.body
        ps = L.player_state()
        sunny = find_day(("sunny",)).timestamp()
        rainy = find_day(("rain", "snow")).timestamp()

        # ---- 山道は公園より疲れる
        def tired(place, now=sunny):
            ps["stamina"] = 100
            S.result("out", 2.0, now, None, place)
            return 100 - ps["stamina"]
        park, mountain = tired("park"), tired("mountain")
        print("2 時間で減った体力: 公園 %.1f / 山 %.1f" % (park, mountain))
        assert mountain > park * 1.5
        app.presence.rec().update(mode="out", place="mountain")
        m_mt = B.move_rate("out", {"kind": "out"})
        app.presence.rec()["place"] = "park"
        m_pk = B.move_rate("out", {"kind": "out"})
        assert m_mt > m_pk, (m_mt, m_pk)
        app.presence.rec().update(mode="none")

        # ---- 雨の日の屋外
        B.rec()["today"] = {}
        r = S.result("out", 1.5, rainy, None, "park")
        assert "体が冷えた" in r["text"] and B.rec()["today"].get("wet", 0) >= 1.5, r["text"]
        risk_wet, why = B.risk(rainy)
        assert why.get("weather", 0) >= 0.03, why
        B.rec()["today"] = {}
        r = S.result("out", 1.5, rainy, None, "aquarium")        # 屋内は濡れない
        assert "冷えた" not in r["text"] and not B.rec()["today"].get("wet")
        B.rec()["today"] = {}
        r = S.result("out", 1.5, sunny, None, "park")
        assert "冷えた" not in r["text"]
        print("雨の公園: 体が冷えた → その日の崩しやすさ +%.2f" % why["weather"])

        # ---- カフェで一息
        ps["stamina"], ps["money"] = 50, 10000
        r = S.result("out", 1.0, sunny, None, "cafe")
        assert ps["stamina"] > 50 and "一息" in r["text"], (ps["stamina"], r["text"])

        # ---- 出先の立ち話は会話の練習
        t0 = ps["skills"]["talk"]
        ppl = {}
        pid = app.street._new_person(ppl, "park", "noon", False, 0)
        app.street.save_people(ppl)
        pend = {"kind": "person", "who": pid, "type": "call", "t": 0, "until": 9e12, "where": "公園", "with": None,
                "name": "知らない人", "text": "", "stage": 0, "place": "park"}
        app.street._resolve_person(pend, "chat", True, False, 0)
        assert ps["skills"]["talk"] > t0
        t1 = ps["skills"]["talk"]
        app.street._resolve_person(pend, "nod", False, True, 0)
        assert ps["skills"]["talk"] == t1, "気づかずに流したときは練習にならない"
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp + "_backup", ignore_errors=True)


if __name__ == "__main__":
    main()
