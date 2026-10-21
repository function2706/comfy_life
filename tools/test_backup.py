"""データ移行の前の自動バックアップの確認 (一時データ, 画像生成なし).
- まっさらな data/ や, 移行の済んだ data/ では写さない
- 旧形式 (data 直下にキャラ・状態・ログ) を最初のワールドへ移す前に, data_backup/<日時>/ へ移行前の形のまま写す
  (画像フォルダは除き, 画像の索引だけ含める)
- ワールドごとの characters/ を全体の定義へ移す前にも写す
- 古いバックアップは BACKUP_KEEP 世代だけ残す (バックアップの印のないフォルダには触らない)

    python tools/test_backup.py
"""
import json
import os
import shutil
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from core import engine, store  # noqa: E402


def put(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def backups():
    root = store.backup_dir()
    return sorted(os.listdir(root)) if os.path.isdir(root) else []


def fresh():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    return tmp


def cleanup(tmp):
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmp + "_backup", ignore_errors=True)


def main():
    hina = json.load(open(os.path.join(BASE, "defaults", "characters", "hina.json"), encoding="utf-8"))

    # ---- 1. まっさらな data/: 移行はないので写さない. 2 回目の起動でも写さない
    tmp = fresh()
    try:
        engine.App()
        engine.App()
        assert backups() == [], backups()
    finally:
        cleanup(tmp)

    # ---- 2. 旧形式 (data 直下): 移す前の形のまま写す. 画像は索引だけ
    tmp = fresh()
    try:
        j = lambda *p: os.path.join(tmp, *p)  # noqa: E731
        put(j("characters", "hina.json"), hina)
        put(j("state", "hina.json"), {"params": {"mood": 77}, "last_tick": 0})
        put(j("log", "hina.json"), [{"id": "x", "t": 0, "text": "むかしの記録"}])
        put(j("player.json"), {"money": 12345})
        put(j("settings.json"), {"active_character": "hina", "player_name": "テスト"})
        put(j("images", "index.json"), {"k": ["a.png"]})
        with open(j("images", "a.png"), "wb") as f:
            f.write(b"\x89PNG" + b"0" * 1000)
        os.makedirs(j("images", "sub"))
        with open(j("images", "sub", "b.png"), "wb") as f:
            f.write(b"\x89PNG")
        app = engine.App()
        assert app.state("hina")["params"]["mood"] == 77, "移行そのものは従来どおり"
        bs = backups()
        assert len(bs) == 1, bs
        b = os.path.join(store.backup_dir(), bs[0])
        print("バックアップ:", b, sorted(os.listdir(b)))
        assert json.load(open(os.path.join(b, "state", "hina.json"), encoding="utf-8"))["params"]["mood"] == 77
        assert json.load(open(os.path.join(b, "player.json"), encoding="utf-8"))["money"] == 12345
        assert os.path.exists(os.path.join(b, "characters", "hina.json")) and not os.path.exists(os.path.join(b, "worlds")), \
            "移行の前の形のまま"
        assert "active_character" in json.load(open(os.path.join(b, "settings.json"), encoding="utf-8"))
        assert os.listdir(os.path.join(b, "images")) == ["index.json"], os.listdir(os.path.join(b, "images"))
        assert os.path.exists(os.path.join(b, store.BACKUP_MARK))
        assert os.path.exists(j("images", "a.png")), "元の画像はそのまま"
        engine.App()
        assert len(backups()) == 1, "移行が済んだあとの起動では写さない"
    finally:
        cleanup(tmp)

    # ---- 3. ワールドごとの characters/ (以前の形式) を全体の定義へ移す前にも
    tmp = fresh()
    try:
        j = lambda *p: os.path.join(tmp, *p)  # noqa: E731
        put(j("worlds.json"), {"current": "w1", "worlds": [{"id": "w1", "name": "A", "created": 0}]})
        put(j("worlds", "w1", "characters", "hina.json"), hina)
        put(j("worlds", "w1", "local.json"), {"active_character": "hina"})
        engine.App()
        bs = backups()
        assert len(bs) == 1 and os.path.exists(os.path.join(store.backup_dir(), bs[0], "worlds", "w1", "characters", "hina.json")), bs
        assert store.all_characters().get("hina"), "移行そのものは従来どおり"

        # ---- 4. 古いバックアップは数世代だけ残す. 印のないフォルダは消さない
        root = store.backup_dir()
        for i in range(8):
            d = os.path.join(root, "20200101-0000%02d" % i)
            os.makedirs(d)
            open(os.path.join(d, store.BACKUP_MARK), "w").close()
        os.makedirs(os.path.join(root, "mine"))          # 自分で置いたもの
        store._backed_up.discard(store.DATA)
        new = store.backup("テスト")
        left = [d for d in backups() if d != "mine"]
        print("残った世代:", left)
        assert len(left) == store.BACKUP_KEEP and os.path.basename(new) in left and "mine" in backups(), backups()
        assert "20200101-000000" not in left, "古いものから消える"
        assert store.backup("もう一度") is None, "一回の起動で一度だけ"
    finally:
        cleanup(tmp)
    print("ALL OK")


if __name__ == "__main__":
    main()
