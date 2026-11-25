"""ランダムに作る人の性格 (A48) と, 出会ったまだ登録していない人の編集 (A49) の確認 (一時データ, 画像生成なし).

- A48: 設定「出会いで新しく作る人には、すでにいる性格を使わない」(既定は入). 入なら, 全体の定義・このワールドの未登録の人・
  登録を尋ねている人の性格を避ける. 全部埋まっていたら, そのときだけ重なる. 切なら今までどおり (重なることがある)
- A49: 未登録の人 (people.json) を定義と同じ形で直せる → 出先の記録・登録を尋ねている定義・登録した定義が直したものになる.
  よく会う所は変わらない. 他ワールドの定義の人は, ここでは直せず, 全体の定義を直すと写しが合う. 登録した人は一覧から外れる

    python tools/test_people_edit.py
"""
import json
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
        E, St = app.encounters, app.street
        pool = [p["id"] for p in app.personas.values() if not p.get("_custom")]
        assert len(pool) >= 4, pool

        # ---- A48: 既定は入. 全体の定義の性格は避ける
        assert app.settings.get("unique_random_persona") is True
        hina_p = store.all_characters()["hina"]["persona_id"]
        assert hina_p in pool
        for _ in range(40):
            assert E.generate()["persona_id"] != hina_p
        print("A48 default on, avoids definitions: OK")

        # 出先で出会った未登録の人の性格も避ける (候補の定義が無いので新しく作る人になる)
        ppl = St.people()
        pid = St._new_person(ppl, "park", "noon", False, time.time())
        pr = St.people()[pid]
        assert pr["src"]["type"] == "new" and pr["char"]["persona_id"] not in (hina_p, ""), pr["src"]
        p_person = pr["char"]["persona_id"]
        assert E.taken_personas() >= {hina_p, p_person}
        for _ in range(40):
            assert E.generate()["persona_id"] not in (hina_p, p_person)
        print("A48 avoids unregistered people: OK")

        # 登録を尋ねている人の性格も避ける
        c_ask = E.generate()
        E.ask_register(c_ask, "公園", None, {"type": "new"}, now=time.time())
        assert c_ask["persona_id"] in E.taken_personas()
        app.life.player_state()["encounter"] = None
        app.life.save_player()

        # 全部埋まったら, そのときだけ重なる (作らないことはない)
        for i, p in enumerate(pool):
            store.save_character({"id": "fill%d" % i, "name": "埋め%d" % i, "persona_id": p, "pos": "1girl", "prompt_history": []})
        assert set(pool) <= E.taken_personas()
        got = {E.generate()["persona_id"] for _ in range(40)}
        assert got and got <= set(pool), got
        print("A48 all filled -> overlap allowed: OK")
        for i in range(len(pool)):
            store.delete_character("fill%d" % i)

        # 切なら今までどおり (すでにいる性格も出る)
        app.save_settings({"unique_random_persona": False})
        got = [E.generate()["persona_id"] for _ in range(200)]
        assert hina_p in got and p_person in got, "切なら重なることがある"
        app.save_settings({"unique_random_persona": True})
        print("A48 off -> as before: OK")

        # ---- A49: 一覧に出る (登録した人・他ワールドの定義の人の扱い)
        lst = app.boot_view()["people"]
        assert [x["pid"] for x in lst] == [pid] and lst[0]["def"] is None and lst[0]["stage"] == "まだ知らない", lst
        assert lst[0]["haunts"] and any("公園" in hh for hh in lst[0]["haunts"]), lst[0]["haunts"]

        # 直す: 名前・外見・性格・服・年齢. よく会う所は変わらない. アイコンは人の記録の側
        haunts0 = json.loads(json.dumps(pr["haunts"]))
        c = app.get_person(pid)
        assert c["_pid"] == pid and "id" not in c
        new_p = next(p for p in pool if p not in (p_person,))
        c.update({"name": "なおした", "pos": "1girl, solo, green hair", "persona_id": new_p, "age": 27, "outfit_default": "white blouse", "icon": "x/y.png"})
        r = app.save_person(pid, c)
        pr2 = St.people()[pid]
        assert pr2["char"]["name"] == "なおした" and pr2["char"]["pos"] == "1girl, solo, green hair" and pr2["char"]["persona_id"] == new_p
        assert pr2["char"]["age"] == 27 and pr2["char"]["outfit_default"] == "white blouse"
        assert "_pid" not in pr2["char"] and "icon" not in pr2["char"] and not pr2.get("icon")
        assert pr2["haunts"] == haunts0 and pr2["stage"] == pr["stage"]
        assert pr2["char"]["prompt_history"][0]["pos"] == "1girl, solo, green hair" and len(pr2["char"]["prompt_history"]) >= 2
        assert pr2["char"].get("life"), "暮らし方は保つ"
        assert r["name"] == "なおした" and r["_pid"] == pid
        assert new_p in E.taken_personas() and p_person not in E.taken_personas(), "直した性格が重なりの判定に効く"
        print("A49 edit unregistered person: OK")

        # 登録を尋ねている最中に直しても, 登録したら直した定義で入る
        E.ask_register(pr2["char"], "公園", None, pr2["src"], pid=pid, now=time.time())
        c = app.get_person(pid)
        c["name"] = "とうろくまえ"
        app.save_person(pid, c)
        assert E.pending()["char"]["name"] == "とうろくまえ"
        res = app.answer_encounter(True)
        nid = res["registered"]["id"]
        d = store.all_characters()[nid]
        assert d["name"] == "とうろくまえ" and d["pos"] == "1girl, solo, green hair" and d["persona_id"] == new_p, d
        assert St.people()[pid]["cid"] == nid
        assert app.boot_view()["people"] == [], "登録した人は一覧から外れる"
        try:
            app.get_person(pid)
            raise AssertionError("登録した人は people から直さない")
        except KeyError:
            pass
        try:
            app.save_person(pid, {"name": "x"})
            raise AssertionError("登録した人は people から直さない")
        except KeyError:
            pass
        print("A49 edit while asking -> registered with edits: OK")

        # 他ワールドの定義の人: ここでは直せない. 全体の定義を直すと写しが合う
        other = app.new_character("みお", stage="absent")
        oid = other["id"]
        assert oid not in app.chars
        ppl = St.people()
        cpy = {k: v for k, v in json.loads(json.dumps(store.all_characters()[oid])).items() if k not in ("prompt_history", "met", "id")}
        ppl["pdef"] = {"char": cpy, "stage": 1, "meets": 1, "last": 0, "haunts": [["cafe", "noon"]], "coworker": False,
                       "src": {"type": "def", "id": oid}, "first": time.time()}
        St.save_people(ppl)
        lst = app.boot_view()["people"]
        assert [x["def"] for x in lst if x["pid"] == "pdef"] == [oid], lst
        try:
            app.save_person("pdef", app.get_person("pdef"))
            raise AssertionError("他ワールドの定義の人は定義の側で直す")
        except ValueError:
            pass
        app.save_definition({"id": oid, "name": "みお改"})
        assert St.people()["pdef"]["char"]["name"] == "みお改"
        d = store.all_characters()[oid]
        d["pos"] = "1girl, solo, red hair"
        app.save_character(d)
        assert St.people()["pdef"]["char"]["pos"] == "1girl, solo, red hair" and "prompt_history" not in St.people()["pdef"]["char"]
        assert St.people()["pdef"]["haunts"] == [["cafe", "noon"]]
        print("A49 definition person follows the definition: OK")

        # 無い人
        for bad in ("nope", ""):
            try:
                app.get_person(bad)
                raise AssertionError("無い人")
            except KeyError:
                pass
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
