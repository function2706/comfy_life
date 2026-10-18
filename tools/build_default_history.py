"""既定データの過去バージョンの指紋 (ハッシュ) を defaults/default_history.json に書き出す.

    python tools/build_default_history.py

起動時の移行で, data/ のコマンドやミニゲームが「過去の既定のまま (未編集)」かを判定し,
未編集なら最新の既定に更新するために使う. 既定の actions.json / minigames.json を変えたら
コミット前に実行すること (現在の作業中の版も含める).
"""
import io
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from core.store import obj_hash  # noqa: E402

FILES = {"actions": "defaults/actions.json", "minigames": "defaults/minigames.json", "events": "defaults/events.json"}


def versions(path):
    commits = subprocess.check_output(["git", "-C", BASE, "log", "--format=%H", "--", path]).decode().split()
    for c in commits:
        try:
            yield json.loads(subprocess.check_output(["git", "-C", BASE, "show", "%s:%s" % (c, path)]).decode("utf-8"))
        except subprocess.CalledProcessError:
            pass
    yield json.load(io.open(os.path.join(BASE, path), encoding="utf-8"))


def main():
    out = {}
    for kind, path in FILES.items():
        hashes = {}
        n = 0
        for items in versions(path):
            n += 1
            for it in items:
                hs = hashes.setdefault(it["id"], [])
                h = obj_hash(it)
                if h not in hs:
                    hs.append(h)
        out[kind] = hashes
        print("%s: %d 版, %d 項目" % (kind, n, len(hashes)))
    dst = os.path.join(BASE, "defaults", "default_history.json")
    io.open(dst, "w", encoding="utf-8", newline="\n").write(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print("->", dst)


if __name__ == "__main__":
    main()
