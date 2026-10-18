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
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
