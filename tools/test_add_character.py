"""既存ワールドに, 設定からキャラを追加したときの「現れるか・間柄」の確認 (一時データ, 画像生成なし).

    python tools/test_add_character.py
"""
import collections
import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402


def main():
    random.seed(4)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        B, E = app.bonds, app.encounters
        w1 = store.WORLD

        # ---- 1. 連絡先 / 知り合い: このワールドに現れ, 選んだ間柄で始まる (外見・性格も入る)
        c = app.new_character("みお", stage="contact", pos="1girl, solo, black hair", persona_id="cool")
        assert c["id"] in app.chars and B.stage(c["id"]) == "contact" and app.settings["active_character"] == c["id"]
        assert app.chars[c["id"]]["pos"] == "1girl, solo, black hair" and app.chars[c["id"]]["persona_id"] == "cool"
        k = app.new_character("ゆかり", stage="known")
        assert B.stage(k["id"]) == "known"
        assert not app.state_view(k["id"])["available"]["message"]["ok"], "知り合いには連絡できない"
        assert B.stage("hina") == "live", "もとの同居はそのまま"
        try:
            app.new_character("x", stage="live")
            raise AssertionError("いきなり同居を選べてしまう")
        except ValueError:
            pass

        # ---- 2. 現れない: このワールドにはいないが登録キャラ. 偶然の出会いの候補になる
        n0 = len(app.chars)
        a = app.new_character("さき", stage="absent", pos="1girl, solo, red hair")
        assert a["_stage"] == "absent" and a["id"] not in app.chars and len(app.chars) == n0
        assert os.path.exists(store.dpath("registry", "characters", a["id"] + ".json"))
        assert "さき" in [x["name"] for _, x in E.candidates()], "このワールドでは知らない人の候補"
        app.world["encounters"] = {"stranger_share": 1}
        seen = set()
        for _ in range(40):
            r = E.happen("out")
            if r:
                seen.add(r["name"])
                app.answer_encounter(False)
        assert "さき" in seen, seen
        while True:                                           # 会えたら登録できる
            r = E.happen("out")
            if r and r["name"] == "さき":
                break
            if r:
                app.answer_encounter(False)
        reg = app.answer_encounter(True)["registered"]
        assert app.chars[reg["id"]]["pos"] == "1girl, solo, red hair" and B.stage(reg["id"]) == "contact"
        assert "さき" not in [x["name"] for _, x in E.candidates()]
        print("contact / known / absent: OK")

        # ---- 3. ほかのワールドでも登録キャラ (新しいワールドの顔ぶれの候補)
        names = sorted(x["name"] for _, x in E.registered(include_defaults=True))
        assert names == sorted(["ひな", "みお", "ゆかり", "さき"]), names
        app.world["encounters"] = {"start_contact": 1, "start_known": 0}
        app.create_world("B")
        assert sorted(x["name"] for x in app.chars.values()) == names
        app.switch_world(w1)

        # ---- 4. くじ: 新しいワールドを作るときと同じ割合で, 連絡先・知り合い・現れない
        app.world["encounters"] = {"start_contact": 0.4, "start_known": 0.35}
        cnt = collections.Counter(app.new_character("r%d" % i, stage="random")["_stage"] for i in range(60))
        assert set(cnt) == {"contact", "known", "absent"} and all(v >= 8 for v in cnt.values()), cnt
        print("random:", dict(cnt))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
