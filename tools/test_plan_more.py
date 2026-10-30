"""予定・行動パターンに足したもの: 家事を一つだけ (洗い物・洗濯など)・ジョギング (走れる行き先)・本を読む・映画を観る・
資格の勉強. 閉じていた間も同じに過ごし, 資格の試験の時間 (10〜13 時) はふさがる.

    python tools/test_plan_more.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from core import engine, offline as OF, store  # noqa: E402


def at(date, hm):
    return datetime.strptime("%s %s" % (date, hm), "%Y-%m-%d %H:%M").timestamp()


def main():
    random.seed(5)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("予定のつづき")
        P, O, L = app.planner, app.offline, app.life
        L.player_state()["skills"].update(work=60, budget=60)
        tom = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        # ---- 1. 行動パターンの 1 行: 家事は一つだけも (無い家事は全部に), ジョギングは走れる行き先, 本・映画はそのまま
        assert OF.normalize({"do": "chores", "skill": "dishes"})["skill"] == "dishes"
        assert "skill" not in OF.normalize({"do": "chores", "skill": "nope"})
        assert OF.normalize({"do": "jog", "place": "mall"})["place"] == "park"
        assert OF.normalize({"do": "read", "place": "park"}) == {"do": "read"}
        assert {"jog", "read", "movie"} <= set(OF.DO_LABEL)
        print("行動パターンの 1 行: OK")

        # ---- 2. 予定に入れられる. 名前に中身が出る
        items = [("08:00", {"do": "chores", "skill": "laundry"}), ("09:00", {"do": "jog", "place": "riverside"}),
                 ("10:00", {"do": "read"}), ("12:00", {"do": "movie"}), ("15:00", {"do": "practice", "skill": "qual:boki"})]
        for hm, b in items:
            P.add(tom, hm, b)
        labels = [x["label"] for x in P.view()["items"]]
        assert labels == ["家事（洗濯）", "ジョギング（河川敷）", "本を読む", "映画を観る", "研鑽（簿記検定の勉強）"], labels
        try:
            P.add(tom, "20:00", {"do": "practice", "skill": "qual:nope"})
            raise AssertionError("無い資格の勉強を予定に入れられた")
        except ValueError:
            pass
        print("予定に入れる: OK |", labels)

        # ---- 3. 閉じていた間: 予定どおりに過ごす. 本が無ければ「読む本がなかった」
        L.player_state()["stamina"] = 100
        rep = O.simulate(at(tom, "07:59"), at(tom, "17:00"))
        tl = {x["label"]: x for x in rep["timeline"]}
        assert "家事（洗濯）" in tl and "ジョギング（河川敷）" in tl and "研鑽（簿記検定の勉強）" in tl, list(tl)
        why = [x for x in rep["timeline"] if (x.get("plan") or {}).get("orig") == "本を読む"]
        assert why and why[0]["plan"].get("why") == "読む本がなかった", why          # 本が無い: 行動パターンに切り替わる
        assert "を観た" in tl["映画を観る"]["text"] and "観始めた" not in tl["映画を観る"]["text"], tl["映画を観る"]
        assert app.quals.rec()["study"].get("boki", 0) > 1
        print("閉じていた間: OK |", [(x["label"], x["text"][:24]) for x in rep["timeline"]])

        # ---- 4. 資格の試験の時間は, 閉じていた間もふさがる
        d2 = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        app.quals.rec()["apps"]["biz"] = {"exam": d2, "status": "applied", "fee": 6000, "t": time.time()}
        rep = O.simulate(at(d2, "09:00"), at(d2, "14:00"))
        ex = [x for x in rep["timeline"] if x["do"] == "exam"]
        assert ex and "ビジネス実務検定" in ex[0]["text"] and ex[0]["t"] == at(d2, "10:00") and ex[0]["end"] == at(d2, "13:00"), rep["timeline"]
        assert not any(x["t"] < at(d2, "13:00") and x["end"] > at(d2, "10:00") for x in rep["timeline"] if x["do"] != "exam")
        print("試験の時間: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
