"""セーブエディタ (core/saveedit.py): 入れ物の一覧・読む・書き換える・消す. 書いたものは保存され, 起動し直しても残る.
無い場所・いちばん上そのものは書けない (一時データ).

    python tools/test_saveedit.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("エディタ")
        E = app.saveedit
        cid = app.settings["active_character"]
        roots = [r["path"] for r in E.roots()]
        assert ["player"] in roots and ["state", cid] in roots and ["char", cid] in roots and ["settings"] in roots

        assert isinstance(E.get(["player"])["value"], dict)
        E.set(["player", "money"], 200000)
        E.set(["player", "debt"], 0)
        E.set(["state", cid, "params", "affection"], 80)
        E.set(["char", cid, "name"], "テスト")
        app.items.ps()["shop_list"]["bread"] = 2
        E.delete(["player", "shop_list", "bread"])
        assert E.get(["player", "money"])["value"] == 200000 and E.get(["state", cid, "params", "affection"])["value"] == 80
        for bad in (lambda: E.set(["player"], 1), lambda: E.get(["player", "nothing", "here"]), lambda: E.delete(["player", "nothing"]),
                    lambda: E.get(["state", "nobody"]), lambda: E.get(["world"])):
            try:
                bad()
                raise AssertionError("通ってはいけない")
            except ValueError:
                pass
        print("読む・書く・消す: OK")

        app2 = engine.App()
        assert app2.life.player_state()["money"] == 200000 and app2.state(cid)["params"]["affection"] == 80
        assert app2.chars[cid]["name"] == "テスト" and "bread" not in app2.life.player_state()["shop_list"]
        print("保存: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
