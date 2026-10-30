"""予定を組んでいない日の, 閉じていた間の仕事 (core/offline.py の _plan_blocks / _gap_blocks) と, 以前の取りこぼしの払い
(retro_missed_work) と, 日記の組み立て (core/solo.py の day_mine / _template / rewrite_diaries).

- 未指定時コマンドがあっても, 予定を組んでいない日は行動パターンどおり (仕事をして給料が入る). 予定を組んだ日も, 勤めの時間は仕事.
- 以前の取りこぼし: 行動パターンでは仕事の時間に, 未指定時コマンドの行動をしていた分だけ, 一度だけ払う (二重に払わない).
  休みの日・稼ぎが入っている・仕事をしていた日には払わない. 置き換わった記録は日記に出さない.
- 日記: 始めたときの一行・同じ一行の重複を出さない, 文の途中で切らない, 閉じていた間のまとめはそれぞれの日に.

    python tools/test_offline_fallback.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402


def at(d, hm):
    return datetime.strptime("%s %s" % (d.strftime("%Y-%m-%d"), hm), "%Y-%m-%d %H:%M").timestamp()


def main():
    random.seed(3)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("取りこぼし")
        P, O, L, S = app.planner, app.offline, app.life, app.solo
        ps = L.player_state()
        now = time.time()
        today = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
        P.rec()["fallback"] = [{"do": "practice", "skill": "cook"}]
        assert P.active()

        # ---- 1. 予定を組んでいない日: 未指定時コマンドがあっても, 行動パターンの仕事をする (給料が入る)
        wd = next(today + timedelta(days=i) for i in range(1, 8) if (today + timedelta(days=i)).weekday() < 5)
        ps["stamina"] = 100
        m0 = ps["money"]
        rep = O.simulate(at(wd, "07:00"), at(wd, "20:00"))
        works = [x for x in rep["timeline"] if x["do"] == "work"]
        assert works and rep["works"] and sum(w["pay"] for w in rep["works"]) > 0, [x["label"] for x in rep["timeline"]]
        assert any(x["n"] == "給料" for x in app.kakeibo.rec()["raw"]), [(x["n"], x["a"]) for x in app.kakeibo.rec()["raw"]]
        assert not any(x["do"] == "practice" for x in rep["timeline"]), "予定の無い日に未指定時コマンドで埋まった"
        print("予定を組んでいない日: OK |", " / ".join(x["text"][:20] for x in works))

        # ---- 2. 予定を組んだ日: 勤めの時間は仕事. それ以外の空き時間は未指定時コマンド
        wd2 = next(wd + timedelta(days=i) for i in range(1, 8) if (wd + timedelta(days=i)).weekday() < 5)
        P.rec()["items"] = [{"id": "p1", "date": wd2.strftime("%Y-%m-%d"), "at": "21:00", "do": "rest"}]
        ps["stamina"] = 100
        rep = O.simulate(at(wd2, "06:30"), at(wd2, "22:00"))
        dos = [x["do"] for x in rep["timeline"]]
        assert "work" in dos and "practice" in dos, dos
        assert all(x["do"] == "work" for x in rep["timeline"] if 10 <= datetime.fromtimestamp(x["t"]).hour < 12), dos
        P.rec()["items"] = []
        print("予定を組んだ日: OK |", dos)

        # ---- 3. 以前の取りこぼし: 一度だけ, 払うべき日だけ
        past = [today - timedelta(days=i) for i in range(2, 20)]
        w1, w2, w3 = [d for d in past if d.weekday() < 5][:3]
        sat = next(d for d in past if d.weekday() == 5)

        def summary(d, parts, t_end):
            txt = "画面を閉じていたあいだ: " + "／".join("%s %s〜%s %s" % (d.strftime("%m/%d"), a, b, x) for a, b, x in parts)
            return S.note("offline", txt, t_end)
        prac = "16時間ほど料理の練習をした。料理が少し伸びた"
        summary(w1, [("07:00", "23:00", prac)], at(w1, "23:30"))
        S.note("practice", prac, at(w1, "23:00"), hours=16.0)                 # その結果の一行 (閉じていた間に残ったもの)
        summary(w2, [("07:00", "23:00", prac)], at(w2, "23:30"))
        L.ledger(at(w2, "18:30"), 7000, "income", "給料")                     # この日は仕事をしていた: 払わない
        summary(w3, [("09:00", "18:00", "仕事（7,000円）")], at(w3, "23:30"))  # 仕事をしていた
        summary(sat, [("07:00", "23:00", prac)], at(sat, "23:30"))           # 休みの日 (行動パターンに仕事が無い)
        ps.pop("retro_work_v1", None)
        m0 = ps["money"]
        paid = O.retro_missed_work(now)
        assert paid and {d for d, _ in paid} == {w1.strftime("%Y-%m-%d")}, paid
        total = sum(p for _, p in paid)
        assert ps["money"] == m0 + total
        raw = [x for x in app.kakeibo.rec()["raw"] if "あとから" in x["n"]]
        assert len(raw) == len(paid) and all("%d/%d の分" % (w1.month, w1.day) in x["n"] for x in raw), raw
        assert O.retro_missed_work(now) == [] and ps["money"] == m0 + total, "二重に払った"
        log = S.mylog()
        assert any(e.get("retro") for e in log) and any(e.get("kind") == "money" and "あとから" not in e["text"] and "抜けていた分" in e["text"] for e in log)
        assert any(e.get("void") == "retro_work" and e["text"] == prac for e in log)
        print("以前の取りこぼし: OK | %s %s円（%d 回分）" % (w1.strftime("%m/%d"), format(total, ","), len(paid)))

        # ---- 4. 日記: その日の仕事が出る. 置き換わった練習は出ない. 休みの日の練習はその日に
        d1 = S.write_diary(w1.strftime("%Y-%m-%d"), regen=True)["text"]
        assert "仕事" in d1 and "料理の練習" not in d1, d1
        ds = S.write_diary(sat.strftime("%Y-%m-%d"), regen=True)["text"]
        assert "料理の練習" in ds, ds
        # まとめは戻った日の記録だが, 中身は前の日の出来事
        S.note("offline", "画面を閉じていたあいだ: %s 19:00〜20:00 1時間ほど商店街で一人で買い物をした。買うものリストの品は見つからず" %
               w2.strftime("%m/%d"), at(w2, "23:59") + 8 * 3600)
        d2 = S.write_diary(w2.strftime("%Y-%m-%d"), regen=True)["text"]
        assert "商店街" in d2, d2
        d2n = S.write_diary((w2 + timedelta(days=1)).strftime("%Y-%m-%d"), regen=True)["text"]
        assert "商店街" not in d2n, d2n
        print("日記の振り分け: OK |", d1.replace("\n", " ")[:80])

        # ---- 5. 日記: 始めたときの一行・同じ一行の重複を出さない. 文の途中で切らない
        t = time.time() - 3600
        S.note("practice", "料理の練習を始めた", t)
        S.note("practice", "35分ほど料理の練習をした。料理が少し伸びた", t + 2100, hours=0.58)
        S.note("back", "35分ほど料理の練習をした。料理が少し伸びた", t + 2101)
        S.note("kakeibo", "家計簿をつけた（4日分）。日が空いていたので、何日か前の分はうろ覚えで、ところどころ抜けているかもしれない", t + 2400)
        txt = S.write_diary()["text"]
        assert txt.count("35分ほど料理の練習をした") == 1 and "始めた" not in txt, txt
        assert "何日か前の分は／" not in txt and "何日か前の分は\n" not in txt and not txt.rstrip().endswith("何日か前の分は"), txt
        assert "家計簿をつけた（4日分）" in txt, txt
        print("日記の重複・切れ: OK |", txt.replace("\n", " "))

        # ---- 6. 以前の日記 (定型) を一度だけ書き直す. 書いた時刻はそのまま. LLM の日記は書き直さない
        lst = [x for x in S.diary_list() if x["day"] != sat.strftime("%Y-%m-%d")]
        lst.append({"day": sat.strftime("%Y-%m-%d"), "t": 123.0, "text": "今日は一人で過ごした。\n一人の時間: 料理の練習を始めた／35分ほど", "src": "template"})
        lst.append({"day": (sat - timedelta(days=1)).strftime("%Y-%m-%d"), "t": 99.0, "text": "LLM の日記", "src": "llm"})
        store.save(store.wpath("diary.json"), sorted(lst, key=lambda x: x["day"]))
        ps.pop("diary_fix_v1", None)
        done = S.rewrite_diaries()
        dd = {x["day"]: x for x in S.diary_list()}
        assert sat.strftime("%Y-%m-%d") in done and dd[sat.strftime("%Y-%m-%d")]["t"] == 123.0
        assert "始めた" not in dd[sat.strftime("%Y-%m-%d")]["text"]
        assert dd[(sat - timedelta(days=1)).strftime("%Y-%m-%d")]["text"] == "LLM の日記"
        assert S.rewrite_diaries() == [], "二度書き直した"
        print("以前の日記の書き直し: OK |", len(done), "日")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
