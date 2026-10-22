"""ミニゲームの単独版 (tools/minigame_lab.py) の確認.
- どのミニゲームも, 条件・クールダウンに関係なく始められ, 何度でも続けて遊べる
- 応答にセリフ・画像・ヒントを含まない (盤面と勝ち負けだけ)
- 本体の data/ には書かない (使い捨ての一時フォルダだけ)
- ページと本体が, 共通の画面 (static/minigames.js) を使う

    python tools/test_minigame_lab.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import minigame_lab as M  # noqa: E402
from core import store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def api(path, body=None, method="POST"):
    out, code = M.call_api(method, path, body)
    assert code == 200, (path, code, out)
    return out


def main():
    data = os.path.join(ROOT, "data")
    before = sorted(os.listdir(data)) if os.path.isdir(data) else None
    M.LAB = M.Lab()
    assert store.DATA == M.TMP and M.TMP != data
    v = api("/api/state", method="GET")
    assert v["name"] == M.OPPONENT and len(v["games"]["list"]) >= 10 and all(g["ok"] for g in v["games"]["list"])
    assert all("ひな" not in g["desc"] for g in v["games"]["list"]), "相手の名前は出さない"
    for g in v["games"]["list"]:
        for _ in range(2):                      # 続けて何度でも (クールダウン・機嫌に関係なく)
            r = api("/api/game/start", {"game": g["id"]})
            assert set(r) <= {"ended", "refused", "view"} and not r.get("refused"), (g["id"], r)
            assert r["view"]["games"]["current"]["kind"] == g["kind"]
            r = api("/api/game/quit", {})
            assert r["view"]["games"]["current"] is None
    # じゃんけんの手を打つ: 盤面と勝ち負けだけが返る (セリフ・ヒント・画像なし)
    yk = next(g for g in v["games"]["list"] if g["kind"] == "acchimuite")
    api("/api/game/start", {"game": yk["id"]})
    for _ in range(40):
        cur = api("/api/state", method="GET")["games"]["current"]
        if not cur:
            break
        r = api("/api/game/move", {"hand": "rock"} if cur["phase"] == "rps" else {"dir": "up"})
        assert "entry" not in r and "hint" not in r and "job" not in r
        if r.get("ended"):
            break
    assert M.LAB.app.logs.get(M.LAB.cid, []) == [], "記録 (セリフ) は残さない"
    assert M.call_api("POST", "/api/game/move", {"hand": "rock"})[1] in (200, 400)
    assert M.call_api("GET", "/api/nothing", None)[1] == 404
    after = sorted(os.listdir(data)) if os.path.isdir(data) else None
    assert before == after, "本体の data/ には書かない"
    print("lab api: OK")

    page = open(os.path.join(ROOT, "static", "minigame_lab.html"), encoding="utf-8").read()
    index = open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8").read()
    app_js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
    shared = open(os.path.join(ROOT, "static", "minigames.js"), encoding="utf-8").read()
    assert "/static/minigames.js" in page and "/static/minigames.js" in index
    assert "function renderGames" not in app_js and "function renderGames" in shared
    print("shared screen: OK")
    print("ALL OK")


if __name__ == "__main__":
    main()
