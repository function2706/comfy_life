"""キャラクターの移行で, 古いフォルダを改名できない (Windows で使用中) ときの確認.
- 改名できなくても起動は止まらず, 「移行済み」の印を置いて次回から移行しない
- 前回の移行が途中で止まっていた (定義は書けたが改名で落ちた) データを開き直しても, キャラが二重にならない

    python tools/test_migrate_locked.py
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


def old_data(tmp):
    """以前の形式: w1 と w2 にひな. w2 のひなは外見を変えてある (= 移行で別のキャラになる)."""
    j = lambda *p: os.path.join(tmp, *p)  # noqa: E731
    hina = json.load(open(os.path.join(BASE, "defaults", "characters", "hina.json"), encoding="utf-8"))
    put(j("worlds.json"), {"current": "w1", "worlds": [{"id": "w1", "name": "A", "created": 0},
                                                     {"id": "w2", "name": "B", "created": 0}]})
    for w, c in (("w1", hina), ("w2", dict(hina, pos=hina["pos"] + ", glasses"))):
        put(j("worlds", w, "characters", "hina.json"), c)
        put(j("worlds", w, "local.json"), {"active_character": "hina"})


def main():
    real_replace = os.replace
    for case in ("locked", "half_done"):
        tmp = tempfile.mkdtemp(prefix="kurashi_test_")
        store.DATA = tmp
        old_data(tmp)
        try:
            def locked(src, dst):
                if os.path.isdir(src):
                    raise PermissionError(5, "アクセスが拒否されました。", src)
                return real_replace(src, dst)
            if case == "locked":
                os.replace = locked              # いつ起動しても改名できない
                engine.App()
                engine.App()                     # 2 回目の起動
            else:
                # 以前のコード: 定義と顔ぶれを書いたあと, 改名で例外 → 起動失敗. その状態から新しいコードで開き直す
                os.replace = locked
                orig = store._retire
                store._retire = lambda d: (_ for _ in ()).throw(PermissionError(5, "アクセスが拒否されました。", d))
                try:
                    engine.App()
                except PermissionError:
                    pass
                store._retire = orig
                os.replace = real_replace
                engine.App()
            os.replace = real_replace
            defs = store.all_characters()
            print(case, "→ 定義:", sorted(defs), "w1:", store.load_cast("w1"), "w2:", store.load_cast("w2"))
            assert len(defs) == 2, "キャラが二重にできている"
            assert store.load_cast("w1") == ["hina"] and len(store.load_cast("w2")) == 1 and store.load_cast("w2") != ["hina"]
            for w in ("w1", "w2"):
                d = os.path.join(tmp, "worlds", w, "characters")
                assert not os.path.isdir(d) or os.path.exists(os.path.join(d, store.MIGRATED_MARK)) or case == "half_done"
        finally:
            os.replace = real_replace
            shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK")


if __name__ == "__main__":
    main()
