"""画面の JS の名前の重なりの確認: 同じページで読み込む JS (index.html の puzzles.js・minigames.js・app.js, 単独版のページ) の
いちばん外の関数・定数の名前が重なっていないこと. 重なると後から読んだほうが上書きして, 別の機能が呼ばれる
(以前: 買うものリストの slSet が, スリザーリンクの slSet を上書きして, 線を引くたびに HTTP 404 になっていた).

    python tools/test_js_names.py
"""
import io
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(BASE, "static")
TOP = re.compile(r"^(?:async\s+)?function\s+(\w+)|^(?:const|let|var|class)\s+(\w+)\b", re.M)


def names(text):
    return {m.group(1) or m.group(2) for m in TOP.finditer(text)}


def page_scripts(page):
    """ページが読み込む JS: (名前, 中身) の並び (外の JS ファイルと, ページの中に書いた script)."""
    html = io.open(os.path.join(STATIC, page), encoding="utf-8").read()
    out = []
    for m in re.finditer(r"<script([^>]*)>(.*?)</script>", html, re.S):
        src = re.search(r'src="/static/([^"]+)"', m.group(1))
        if src:
            out.append((src.group(1), io.open(os.path.join(STATIC, src.group(1)), encoding="utf-8").read()))
        elif m.group(2).strip():
            out.append((page + " の中", m.group(2)))
    return out


def main():
    bad = []
    for page in ("index.html", "puzzle_lab.html", "minigame_lab.html"):
        seen = {}
        for name, text in page_scripts(page):
            for n in names(text):
                if n in seen:
                    bad.append("%s: %s が %s と %s で重なっている" % (page, n, seen[n], name))
                seen[n] = name
        print("%s: %d 個の名前, 重なりなし" % (page, len(seen)) if not bad else "%s: 重なりあり" % page)
    assert not bad, "\n".join(bad)
    print("ALL OK")


if __name__ == "__main__":
    sys.exit(main())
