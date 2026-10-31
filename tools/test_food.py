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
        # 献立は料理スキルで足切りしない (作り方は調べられる). 食材があればどれも作れる. 難しさは目安として出る
        L.player_state()["skills"]["cook"] = 10.0
        ds = {d["id"]: d for d in B.dishes()}
        assert all(d["ok"] for d in ds.values()), ds
        assert "初めて" in ds["curry"]["hint"] and "難しそう" in ds["nabe"]["hint"] and "難しそう" not in ds["rice"]["hint"], ds
        # 腕前が足りないほど崩れやすい (栄養の入り方が落ちる). 調べながら作ったことが書かれる
        def trial(skill, did, n=60):
            got = []
            for _ in range(n):
                L.player_state()["skills"]["cook"] = skill
                b["cooked"] = {}
                b["nutri"] = {k: 20.0 for k in b["nutri"]}
                b["satiety"] = 20.0
                I.add("rice", 2)
                I.add("veggies", 3)
                I.add("eggs_tofu", 2)
                r = B.cook_at(did, time.time())
                got.append((sum(b["nutri"].values()) - 60.0, r["text"]))
            return got
        low, high = trial(5, "nabe"), trial(70, "nabe")
        avg = lambda xs: sum(x for x, _ in xs) / len(xs)
        assert avg(low) < avg(high) * 0.85, (avg(low), avg(high))
        assert sum("いまいち" in t or "焦がして" in t for _, t in low) > sum("いまいち" in t or "焦がして" in t for _, t in high)
        assert all("調べながら" in t for _, t in low)
        # 作るたびに作り慣れていく (3 回でレパートリー). 慣れると崩れにくい
        L.player_state()["skills"]["cook"] = 20.0
        b["cooked"] = {}
        texts = []
        for _ in range(3):
            I.add("rice", 1)
            I.add("veggies", 1)
            I.add("eggs_tofu", 1)
            texts.append(B.cook("curry")["text"])
        assert "調べながら" in texts[0] and "調べながら" not in texts[1] and "作り慣れてきた" in texts[2], texts
        assert next(d for d in B.dishes() if d["id"] == "curry")["familiar"]
        assert B._skill_for("curry") > B._skill_for("stirfry"), "作り慣れた献立のほうが腕前が出る"
        # 自動で作るとき (行動パターン) は, 作り慣れたもの・腕前に合ったものを選ぶ
        b["nutri"] = {"staple": 30.0, "protein": 30.0, "veg": 30.0}
        I.add("rice", 3)
        I.add("veggies", 3)
        I.add("eggs_tofu", 3)
        pick = B.best_dish([d for d in B.dishes() if d["ok"]])
        assert pick["id"] == "curry", pick
        # 以前のセーブ: 食事の記録から, 作った回数を数える
        b.pop("cooked")
        b["meals"] = [{"t": 1, "how": "cook", "label": "焼き魚の定食"}] * 4 + [{"t": 2, "how": "out", "label": "カレーライス"}]
        assert B.rec()["cooked"] == {"teishoku": 4}, B.rec()["cooked"]
        L.player_state()["skills"]["cook"] = 45.0
        I.ps()["items"] = {}
        I.add("rice", 10)
        I.add("veggies", 3)
        I.add("eggs_tofu", 4)
        n0 = dict(b["nutri"])
        r = B.cook("teishoku")
        assert b["satiety"] > 50 and all(b["nutri"][k] > n0[k] for k in n0), (r, b)
        assert I.count("rice") == 9 and I.count("veggies") == 2 and I.count("eggs_tofu") == 3
        print("自炊:", r["text"], "| 腕前が足りない鍋 %.1f / 足りる鍋 %.1f" % (avg(low), avg(high)))

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
