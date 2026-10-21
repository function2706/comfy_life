"""キャラクターの定義は全体で 1 つ, 各ワールドにはその個体 (顔ぶれ・状態・ログ・間柄・関係) の確認.
以前の形式 (ワールドごとの characters/, registry/characters/) からの移行, 定義の編集が全ワールドに反映されること,
削除はどこにも現れていない定義だけ, このワールドに出すこと (一時データ, 画像生成なし).

    python tools/test_definitions.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def put(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    j = lambda *p: os.path.join(tmp, *p)  # noqa: E731
    try:
        # ---- 1. 以前の形式: ワールドごとに characters/. w2 のひなだけ外見を変えてあった. 登録だけの人も
        hina = json.load(open(os.path.join(BASE, "defaults", "characters", "hina.json"), encoding="utf-8"))
        h2 = dict(hina, pos=hina["pos"] + ", glasses")
        put(j("worlds.json"), {"current": "w1", "worlds": [{"id": "w1", "name": "A", "created": 0},
                                                         {"id": "w2", "name": "B", "created": 0, "alone": True,
                                                          "start_bonds": {"hina": "contact"}}]})
        for w, c in (("w1", hina), ("w2", h2)):
            put(j("worlds", w, "characters", "hina.json"), c)
            put(j("worlds", w, "state", "hina.json"), {"params": {"mood": 11.0 if w == "w1" else 22.0}, "last_tick": 0,
                                                       "last_interaction": 0, "override": None, "cooldowns": {}, "created": 0})
            put(j("worlds", w, "local.json"), {"active_character": "hina"})
        put(j("worlds", "w2", "player.json"), {"money": 500, "last_tick": 0, "bonds": {"hina": {"stage": "visit", "t": 0}}})
        put(j("worlds", "w2", "relations.json"), {"hina": {}})
        put(j("registry", "characters", "cx.json"), dict(hina, id="cx", name="さき", pos="1girl, solo, red hair"))
        app = engine.App()
        app.save_settings({"auto_generate": False})
        defs = store.all_characters()
        assert set(defs) >= {"hina", "cx"} and len(defs) == 3, defs.keys()
        new = next(k for k in defs if k not in ("hina", "cx"))
        assert defs[new]["pos"].endswith("glasses") and defs["hina"]["pos"] == hina["pos"], "中身が違うものは別のキャラに"
        assert store.load_cast("w1") == ["hina"] and store.load_cast("w2") == [new]
        assert os.path.exists(j("worlds", "w2", "state", new + ".json")), "状態の付け替え"
        assert json.load(open(j("worlds", "w2", "player.json"), encoding="utf-8"))["bonds"] == {new: {"stage": "visit", "t": 0}}
        assert json.load(open(j("worlds", "w2", "local.json"), encoding="utf-8"))["active_character"] == new
        assert os.path.isdir(j("worlds", "w1", "characters.migrated")) and not os.path.isdir(j("registry", "characters"))
        assert app.state("hina")["params"]["mood"] == 11.0
        app.switch_world("w2")
        assert list(app.chars) == [new] and app.state(new)["params"]["mood"] == 22.0 and app.bonds.stage(new) == "visit"
        app.switch_world("w1")
        print("migrate: OK")

        # ---- 2. 定義の編集は全ワールドに反映. 状態・ログはワールドごと
        w3 = app.create_world("C", copy_from="w1")["id"]
        assert "hina" in app.chars and app.log("hina") == []
        c = dict(app.char("hina"), name="ひな（改）")
        app.save_character(c)
        app.switch_world("w1")
        assert app.char("hina")["name"] == "ひな（改）", "ほかのワールドから見ても変わっている"
        assert app.state("hina")["params"]["mood"] == 11.0
        print("shared definition: OK")

        # ---- 3. このワールドにいない定義: 一覧・編集・出す. 削除は, どこにも現れていない定義だけ
        others = {x["id"]: x for x in app.others_list()}
        assert set(others) == {"cx", new} and others[new]["_worlds"] == ["B"] and others["cx"]["_worlds"] == []
        app.save_definition({"id": "cx", "name": "さき2", "persona_id": "cool"})
        assert store.all_characters()["cx"]["name"] == "さき2" and store.all_characters()["cx"]["persona"], "性格の説明も合わせる"
        for cid in ("hina", new):
            try:
                app.delete_character(cid)
                raise AssertionError("現れているキャラの定義を消せてしまう: %s" % cid)
            except ValueError as e:
                assert "削除できません" in str(e)
        a = app.new_character("ゆき", stage="absent")
        assert a["id"] not in app.chars and a["id"] in [x["id"] for x in app.others_list()]
        assert app.delete_character(a["id"])["ok"] and a["id"] not in store.all_characters()
        app.place_character("cx", "known")
        assert "cx" in app.chars and "cx" in store.load_cast() and app.bonds.stage("cx") == "known"
        assert "cx" not in [x["id"] for x in app.others_list()]
        try:
            app.place_character("cx", "live")
            raise AssertionError("いきなり同居で出せてしまう")
        except ValueError:
            pass
        app.switch_world(w3)
        assert "cx" not in app.chars, "ほかのワールドの顔ぶれは変わらない"
        print("others / delete / place: OK")

        # ---- 4. 定義の一覧は, どのワールドから見ても同じ (いるかどうか・どこから来たかが分かる)
        app.switch_world("w1")
        d1 = {x["id"]: x for x in app.defs_list()}
        app.switch_world(w3)
        d3 = {x["id"]: x for x in app.defs_list()}
        assert set(d1) == set(d3) == set(store.all_characters()), "ワールドを切り替えても, 定義の一覧は変わらない"
        assert d1["cx"]["here"] and not d3["cx"]["here"] and d1["cx"]["worlds"] == d3["cx"]["worlds"]
        assert d1["hina"]["origin"] == "既定のキャラ" and "以前のデータ" in d1["cx"]["origin"]
        m = app.new_character("みく", stage="absent")
        assert "設定で追加" in {x["id"]: x for x in app.defs_list()}[m["id"]]["origin"]
        # このワールドにいない定義も編集できる (このワールドには現れない)
        c = dict(store.all_characters()[m["id"]], name="みく2")
        app.save_character(c)
        assert store.all_characters()[m["id"]]["name"] == "みく2" and m["id"] not in app.chars
        # 出会って登録した人は, いつ・どこで・どのワールドかが残る
        app.world["encounters"] = {"stranger_share": 1}
        for x in list(store.all_characters()):
            if x not in app.chars:
                store.save_cast(store.load_cast() + [x])         # 候補を空にして, 新しい人と出会う
        app.reload()
        app.encounters.happen("out", stranger=True)
        reg = app.answer_encounter(True)["registered"]
        o = {x["id"]: x for x in app.defs_list()}[reg["id"]]["origin"]
        assert o.startswith("出会って登録") and "C" in o, o
        print("defs list / origin: OK", o)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp + "_backup", ignore_errors=True)     # 移行前の自動バックアップ


if __name__ == "__main__":
    main()
