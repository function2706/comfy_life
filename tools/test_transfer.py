"""セーブの書き出し・読み込み (core/transfer.py) の確認 (一時データ, 画像生成なし).

    python tools/test_transfer.py
"""
import base64
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, transfer  # noqa: E402


def png(path):
    full = store.dpath("images", *path.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(b"\x89PNG fake " + path.encode())


def fresh(tmp):
    """別の PC のつもりで, まっさらな data を開く."""
    store.DATA, store.WORLD = tmp, None
    app = engine.App()
    app.save_settings({"auto_generate": False})
    return app


def main():
    a_dir, b_dir = tempfile.mkdtemp(prefix="kurashi_test_"), tempfile.mkdtemp(prefix="kurashi_test_")
    try:
        # ---- 書き出す側: 記録・お金・新しい人 (自作の性格プリセット)・画像
        app = fresh(a_dir)
        w1 = store.WORLD
        app.life.player_state()["money"] = 77777
        app.life.save_player()
        p = dict(app.personas[next(iter(app.personas))], id="my_persona", name="自作の性格")
        store.save_persona(p)
        app.reload()
        mio = app.new_character("みお", stage="contact", pos="1girl, solo, short hair", persona_id="my_persona")
        app.chat.send(mio["id"], "thanks")
        png("hina/a.png")
        png("%s/icon.png" % mio["id"])
        log = app.log("hina")
        log.append({"id": "e_img", "t": 1, "text": "画像つき", "image": "hina/a.png",
                    "images": [{"path": "hina/a.png", "pos": "p", "neg": "n", "t": 1}]})
        app.save_log("hina")
        c = store.all_characters()[mio["id"]]
        c["icon"] = "%s/icon.png" % mio["id"]
        store.save_character(c)
        app.img_index.setdefault("k1", []).append({"path": "hina/a.png", "seed": 1, "t": 1})
        store.save(store.dpath("images", "index.json"), app.img_index)

        fname, data = app.export_world(w1, images=False)
        assert fname.endswith(".zip") and "images" not in fname, fname
        z = zipfile.ZipFile(io.BytesIO(data))
        names = z.namelist()
        info = json.loads(z.read(transfer.MANIFEST))
        assert info["format"] == transfer.FORMAT and set(info["characters"]) == {"hina", mio["id"]}, info
        assert "world/player.json" in names and "world/chats/%s.json" % mio["id"] in names, names
        assert "characters/hina.json" in names and "personas/my_persona.json" in names, names
        assert not any(n.startswith("images/") for n in names), "画像を含めないとき"
        fname_i, data_i = app.export_world(w1, images=True)
        zi = zipfile.ZipFile(io.BytesIO(data_i))
        assert {"images/hina/a.png", "images/%s/icon.png" % mio["id"], "images_index.json"} <= set(zi.namelist()), zi.namelist()
        assert len(data_i) > len(data)
        print("書き出し: 画像なし %d バイト / あり %d バイト" % (len(data), len(data_i)))

        # ---- 別の PC で読み込む: 新しいワールドとして足す (切り替えない)
        app2 = fresh(b_dir)
        cur = store.WORLD
        r = app2.import_world(base64.b64encode(data_i).decode())
        assert store.WORLD == cur, "読み込んでも切り替えない"
        assert r["id"] != cur and r["id"] in [w["id"] for w in r["worlds"]["worlds"]], r
        assert r["added"] == [mio["id"]] and r["same"] == ["hina"] and not r["renamed"], r
        assert r["images"] == 2 and r["personas"] == ["my_persona"], r
        assert os.path.exists(store.dpath("images", "hina", "a.png"))
        assert any(im["path"] == "hina/a.png" for v in app2.img_index.values() for im in v), "索引にも足す"
        app2.switch_world(r["id"])
        assert app2.life.player_state()["money"] == 77777, "お金が引き継がれる"
        assert any(e.get("id") == "e_img" for e in app2.log("hina"))
        assert app2.chat.load(mio["id"])["items"], "トークも"
        assert app2.chat.face(mio["id"]) == "%s/icon.png" % mio["id"], "顔のアイコンも"
        assert app2.chars[mio["id"]]["persona_id"] == "my_persona" and "my_persona" in app2.personas
        app2.state_view()
        print("別の PC で読み込み: OK", r["name"])

        # ---- 画像なしの読み込み: 画像は足さない
        r0 = app2.import_world(data, name="画像なし")
        assert r0["images"] == 0 and not r0["with_images"] and r0["name"] == "画像なし"

        # ---- 同じ PC で, 定義を編集してから読み込む: 中身の違う定義は別の人 (こちらの定義は変えない)
        store.DATA, store.WORLD = a_dir, None
        app = engine.App()
        h = store.all_characters()["hina"]
        h["name"] = "ひな (編集)"
        store.save_character(h)
        r2 = app.import_world(data)
        new = r2["renamed"].get("hina")
        assert new and new != "hina" and r2["same"] == [mio["id"]], r2
        assert store.all_characters()["hina"]["name"] == "ひな (編集)", "こちらの定義はそのまま"
        assert store.all_characters()[new]["name"] == "ひな", "読み込んだほうは元の定義で別の人"
        wd = store.dpath("worlds", r2["id"])
        assert os.path.exists(os.path.join(wd, "log", new + ".json")) and not os.path.exists(os.path.join(wd, "log", "hina.json"))
        assert new in store.load_cast(r2["id"]) and "hina" not in store.load_cast(r2["id"])
        pj = store.load(os.path.join(wd, "player.json"))
        assert new in (pj.get("bonds") or {}) and "hina" not in (pj.get("bonds") or {}), pj.get("bonds")
        assert any(im.get("path") == "hina/a.png" for e in store.load(os.path.join(wd, "log", new + ".json")) for im in e.get("images") or []), "画像のパスは変えない"
        app.switch_world(r2["id"])
        assert app.chars[new]["name"] == "ひな" and app.life.player_state()["money"] == 77777
        app.state_view()
        print("中身の違う定義は別の人:", new)

        # ---- 壊れたもの・よそのもの・外へ出るパス
        for bad, msg in ((b"not a zip", "zip"), (_zip({"x.json": "{}"}), "comfy_life.json"),
                         (_zip({transfer.MANIFEST: json.dumps({"format": "other"})}), "セーブではありません"),
                         (_zip({transfer.MANIFEST: json.dumps({"format": transfer.FORMAT, "version": 99})}), "新しい版"),
                         (_zip({transfer.MANIFEST: json.dumps({"format": transfer.FORMAT, "version": 1}),
                                "world/../../evil.json": "{}"}), "パス")):
            try:
                app.import_world(bad)
                raise AssertionError("読めてしまった: %s" % msg)
            except ValueError as e:
                assert msg in str(e), (msg, e)
        assert not os.path.exists(os.path.join(a_dir, "evil.json"))
        print("ALL OK")
    finally:
        shutil.rmtree(a_dir, ignore_errors=True)
        shutil.rmtree(b_dir, ignore_errors=True)


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


if __name__ == "__main__":
    main()
