"""性格プリセット用に, 全セリフのキー・元のセリフ・条件を書き出す.

    python tools/dump_line_keys.py [出力先.json]   (省略時は標準出力)

既定データ (defaults/) を対象にする. セリフ集を書くときの台本として使う.
"""
import io
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from core.keys import all_keys  # noqa: E402


def main():
    load = lambda name: json.load(io.open(os.path.join(BASE, "defaults", name), encoding="utf-8"))  # noqa: E731
    keys = all_keys(load("actions.json"), load("minigames.json"))
    text = json.dumps(keys, ensure_ascii=False, indent=1)
    if len(sys.argv) > 1:
        io.open(sys.argv[1], "w", encoding="utf-8").write(text)
        print("%d keys -> %s" % (len(keys), sys.argv[1]))
    else:
        print(text)


if __name__ == "__main__":
    main()
