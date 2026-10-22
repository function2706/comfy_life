"""あなたの食事と栄養の確認 (一時データ, 画像生成なし).
- お腹は時間で減る (寝ている間はゆっくり). 栄養 (主食・たんぱく質・野菜) は数日分の蓄えで, 食べたものの中身で戻る
- 自炊: 食材 (1 個 = 何回分か) を使う. 料理スキルで作れる献立が増える. 食材がなければ作れない. 家でだけ
- 外食・買って食べる: いる行き先のメニュー (営業時間つき). 値段と栄養は店しだい. 家計簿の記録にも残る
- 外食の行き先に出かけて食べずに帰ると, 帰る前に何か食べる
- 行動パターンの食事: 自炊 (食材がなければ買い置き, それも無ければ食べない)・外食 (閉まっていれば食べない)・買って食べる
- お腹がすいていると体力が戻りにくい

    python tools/test_food.py
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
    random.seed(7)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        B, L, I = app.body, app.life, app.items
        now = time.time()
        app.presence.rec()["beat"] = app.presence.rec()["input"] = now

        # ---- 1. お腹と栄養は時間で減る (寝ている間はゆっくり)
        b = B.rec()
        b["satiety"], b["nutri"] = 80.0, {"staple": 60.0, "protein": 60.0, "veg": 60.0}
        B.step(now, 5.0, "here")
        awake = 80.0 - b["satiety"]
        b["satiety"] = 80.0
        B.step(now, 5.0, "sleep")
        asleep = 80.0 - b["satiety"]
        assert awake > 2 * asleep > 0 and b["nutri"]["veg"] < 60, (awake, asleep)
        b["satiety"] = 5.0
        assert B.stamina_mult() < 1.0 and "ぺこぺこ" in B.view()["hunger"]

        # ---- 2. 自炊: 食材がなければ作れない. 買えば回数ぶん. スキルで献立が増える
        assert not any(d["ok"] for d in B.dishes()), "食材なしで作れる"
        try:
            B.cook("rice")
            raise AssertionError("食材なしで作れた")
        except ValueError:
            pass
        I.add("rice", 10)
        I.add("veggies", 3)
        I.add("eggs_tofu", 4)
        L.player_state()["skills"]["cook"] = 10.0
        ok = {d["id"] for d in B.dishes() if d["ok"]}
        assert {"rice", "tkg", "miso"} <= ok and "curry" not in ok, ok
        L.player_state()["skills"]["cook"] = 45.0
        ok = {d["id"] for d in B.dishes() if d["ok"]}
        assert {"curry", "teishoku"} <= ok, ok
        n0 = dict(b["nutri"])
        r = B.cook("teishoku")
        assert b["satiety"] > 50 and all(b["nutri"][k] > n0[k] for k in n0), (r, b)
        assert I.count("rice") == 9 and I.count("veggies") == 2 and I.count("eggs_tofu") == 3
        print("自炊:", r["text"])

        # ---- 3. 外食: 行き先のメニュー. 払ったお金は家計簿の元の記録にも
        app.solo.start("out", place="ramen")
        m = B.view()["menu"]
        assert m and m[0]["name"] == "ラーメン", m
        money0 = L.player_state()["money"]
        r = B.eat("out", "tanmen")
        assert L.player_state()["money"] < money0 and any(x["c"] == "eatout" for x in app.kakeibo.rec()["raw"])
        print("外食:", r["text"])
        app.presence.rec()["since"] -= 1800
        res = app.come_back()["solo"]
        assert "食事をした" in res["text"], res
        # 食べに行って食べずに帰ると, 帰る前に何か食べる
        b["satiety"] = 10.0
        app.solo.start("out", place="family")
        app.presence.rec()["since"] -= 1800
        res = app.come_back()["solo"]
        assert "ドリア" in res["text"] and b["satiety"] > 30, res
        # 閉まっている店では食べられない
        assert B.menu("teishoku", time.mktime((2026, 10, 18, 12, 0, 0, 0, 0, -1))) == [], "日曜は休み"

        # ---- 4. 行動パターンの食事
        from core import offline
        I.ps()["items"] = {}
        days = {k: [{"at": "00:00", "do": "rest"}, {"at": "08:00", "do": "meal", "how": "cook"},
                    {"at": "12:00", "do": "meal", "how": "buy", "place": "convenience"}, {"at": "13:00", "do": "rest"}]
                for k in offline.DAY_KEYS}
        app.save_settings({"offline": {"enabled": True, "days": days}})
        t1 = time.time()
        rep = app.offline.simulate(t1 - 30 * 3600, t1)
        meals = [x for x in rep["timeline"] if x["do"] == "meal"]
        assert meals and any("食材がなくて" in x["text"] for x in meals), [x["text"] for x in meals]
        assert any("お弁当" in x["text"] or "おにぎり" in x["text"] or "サラダ" in x["text"] or "サンドイッチ" in x["text"] for x in meals), \
            [x["text"] for x in meals]
        print("行動パターン:", [x["label"] + ": " + x["text"] for x in meals][:3])
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
