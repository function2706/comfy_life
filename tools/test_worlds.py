"""ワールド別セーブとキャラ同士の関係の確認 (一時データ, 画像生成なし).

    python tools/test_worlds.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def w(*p):
    return os.path.join(*p)


def put(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        # ---- 1. 旧形式 (data 直下) からの移行
        shutil.copytree(w(BASE, "defaults", "characters"), w(tmp, "characters"))
        put(w(tmp, "state", "hina.json"), {"params": {"mood": 12.0}, "last_tick": 0, "last_interaction": 0,
                                           "override": None, "cooldowns": {}, "created": 0})
        put(w(tmp, "log", "hina.json"), [{"id": "e1", "t": 1, "text": "古いログ",
                                          "images": [{"path": "hina/old.png", "pos": "p", "neg": "n", "t": 1}]}])
        put(w(tmp, "player.json"), {"money": 12345, "last_tick": 0})
        put(w(tmp, "settings.json"), {"player_name": "ユウ", "active_character": "hina", "seen_actions": ["talk"]})
        app = engine.App()
        app.save_settings({"auto_generate": False})
        assert not os.path.exists(w(tmp, "characters")) and not os.path.exists(w(tmp, "player.json"))
        w1 = store.WORLD
        assert os.path.exists(w(tmp, "worlds", w1, "characters", "hina.json"))
        assert app.state("hina")["params"]["mood"] == 12.0, "状態が引き継がれる"
        assert app.log("hina")[0]["text"] == "古いログ"
        assert app.life.player_state()["money"] == 12345, "お金が引き継がれる"
        g = store.load(w(tmp, "settings.json"))
        assert "active_character" not in g and not any(k.startswith("seen_") for k in g), g
        assert g["player_name"] == "ユウ"
        loc = store.load(w(tmp, "worlds", w1, "local.json"))
        assert loc["active_character"] == "hina" and "seen_actions" in loc, loc
        assert "old.png" in json.dumps(app.img_index) or os.path.exists(w(tmp, "images", "index.json"))
        print("migrate: OK", app.worlds_view())

        # ---- 2. 既定から新しいワールド: 同じ hina でも無関係
        r = app.create_world("ワールドB")
        w2 = r["id"]
        assert store.WORLD == w2 and app.worlds_view()["current"] == w2
        assert app.log("hina") == [], "ログは別"
        assert app.state("hina")["params"]["mood"] != 12.0, "状態は別"
        assert app.life.player_state()["money"] != 12345, "お金は別"
        app.set_params({"mood": 99}, "hina")
        app.life.player_state()["money"] = 1
        app.life.save_player()
        app.save_settings({"player_name": "ユウ2"})          # 主人公の名前は全体共通
        app.switch_world(w1)
        assert app.state("hina")["params"]["mood"] == 12.0 and app.life.player_state()["money"] == 12345
        assert app.settings["player_name"] == "ユウ2"
        print("separate: OK")

        # ---- 3. キャラ同士の関係
        b = app.new_character("みお")
        app.select_character("hina")
        app.save_relations("hina", {b["id"]: {"knows": True, "kind": "幼なじみ", "affinity": 85}, "nobody": {"knows": True}})
        app.save_relations(b["id"], {"hina": {"knows": False}})
        assert app.relation("hina", b["id"])["knows"] and not app.relation(b["id"], "hina")["knows"], "向きごとに別"
        assert "nobody" not in app.relations["hina"], "存在しないキャラは保存しない"
        txt = app.relations_text(app.char("hina"))
        assert "みお" in txt and "幼なじみ" in txt and "大好き" in txt, txt
        assert app.relations_text(app.char(b["id"])) == ""
        app.change_affinity(b["id"], "hina", 15)
        rb = app.relation(b["id"], "hina")
        assert rb["knows"] and rb["affinity"] == 65, rb
        assert "relations" in app.boot_view() and "worlds" in app.boot_view()

        # 今のワールドを複製: キャラと関係は引き継ぎ, 状態・ログ・お金は引き継がない
        r = app.create_world("複製", copy_from=w1)
        w3 = r["id"]
        assert b["id"] in app.chars and app.relation("hina", b["id"])["kind"] == "幼なじみ"
        assert app.log("hina") == [] and app.life.player_state()["money"] != 12345
        app.switch_world(w1)
        app.delete_character(b["id"])
        assert b["id"] not in app.relations.get("hina", {}), "削除したキャラの関係も消える"
        print("relations: OK")

        # ---- 4. 生成中にワールドを切り替えても, 画像は元のワールドのログに入る
        app.log("hina").append({"id": "e2", "t": 2, "text": "生成待ち", "job": "J1"})
        app.save_log("hina")
        job = {"id": "J1", "cid": "hina", "entry": "e2", "wid": w1}
        app.switch_world(w2)
        app._job_entry(job, lambda e: e.update(image="hina/new.png"))
        assert not any(e.get("id") == "e2" for e in app.log("hina")), "切替先のログには入らない"
        app._clear_entry_job(job, "失敗テスト")
        lg = store.load(w(tmp, "worlds", w1, "log", "hina.json"))
        e2 = next(e for e in lg if e["id"] == "e2")
        assert e2["image"] == "hina/new.png" and "job" not in e2 and e2["error"] == "失敗テスト", e2
        print("job across switch: OK")

        # ---- 5. 名前変更・削除
        app.rename_world(w2, "  ")
        app.rename_world(w2, "B改")
        assert [x["name"] for x in app.worlds_view()["worlds"] if x["id"] == w2] == ["B改"]
        app.delete_world(w2)                               # 開いているワールドを消すと別のワールドへ
        assert store.WORLD != w2 and not os.path.exists(w(tmp, "worlds", w2))
        app.delete_world(w3)
        try:
            app.delete_world(store.WORLD)
            raise AssertionError("最後のワールドが消せてしまう")
        except ValueError:
            pass
        app2 = engine.App()                                # 再起動しても最後に開いたワールド
        assert store.WORLD == w1 and app2.state("hina")["params"]["mood"] == 12.0
        print("rename/delete: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
