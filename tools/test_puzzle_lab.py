"""内職のパズルの単独版 (tools/puzzle_lab.py) の確認.
- 盤面を返す (同じ seed なら同じ盤面), 答え合わせができる, 答えを表示できる, 終えたら本体ならいくらかの試算
- ゲームのデータ (data/) には何も書かない. 何度でも続けて遊べる (休憩・体力は無い)
- ページと共通の画面 (static/puzzles.js) を配る

    python tools/test_puzzle_lab.py
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="kurashi_lab_")
os.environ["KURASHI_DATA"] = TMP          # 万一書いたら分かるように, 空の一時フォルダを指しておく
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import puzzle_lab as L  # noqa: E402
from core import puzzles as P  # noqa: E402


def api(path, body=None, method="POST"):
    out, code = L.call_api(method, path, body)
    assert code == 200, (path, code, out)
    return out


def main():
    cat = api("/api/catalog", method="GET")
    assert [k["id"] for k in cat["kinds"]] == list(P.KINDS) and cat["rate"] == P.RATE_PER_MIN

    # 同じ seed なら同じ盤面. seed を入れなければ毎回ちがう
    a = api("/api/task/start", {"kind": "sudoku", "level": "easy", "seed": 42})
    b = api("/api/task/start", {"kind": "sudoku", "level": "easy", "seed": "42"})
    c = api("/api/task/start", {"kind": "sudoku", "level": "easy"})
    assert a["view"]["given"] == b["view"]["given"] and a["seed"] == 42 and c["seed"] != 42
    assert P.sudoku_count(a["view"]["given"]) == 1
    # 答え合わせはサーバ: 違う数字はミス, 正しい数字は入る. 解ききれば試算
    sol = api("/api/task/answer", {"token": b["token"]})["view"]["cur"]
    i = a["view"]["given"].index(0)
    wrong = next(v for v in range(1, 10) if v != sol[i])
    assert api("/api/task/move", {"token": a["token"], "move": {"r": i // 9, "c": i % 9, "v": wrong}})["wrong"]
    for j, v in enumerate(sol):
        if not a["view"]["given"][j]:
            r = api("/api/task/move", {"token": a["token"], "move": {"r": j // 9, "c": j % 9, "v": v}})
    assert r["solved"]
    k = api("/api/task/finish", {"token": a["token"]})["task"]
    assert k["solved"] and k["miss"] == 1 and k["pay"] > 0 and k["seed"] == 42
    # 仕事スキルで試算が変わる. 解けずにやめたら少しだけ
    hi = api("/api/task/start", {"kind": "slide", "level": "easy", "seed": 7, "skill": 100})
    lo = api("/api/task/start", {"kind": "slide", "level": "easy", "seed": 7, "skill": 0})
    assert hi["base"] > lo["base"] and hi["view"]["board"] == lo["view"]["board"]
    assert api("/api/task/finish", {"token": lo["token"]})["task"]["pay"] < lo["base"]
    # マインスイーパ: 同じ seed・同じ最初の一手なら, 地雷の位置も同じ. 答えは一手目の前でも見られる
    m1 = api("/api/task/start", {"kind": "mines", "level": "mid", "seed": 3})
    m2 = api("/api/task/start", {"kind": "mines", "level": "mid", "seed": 3})
    v1 = api("/api/task/move", {"token": m1["token"], "move": {"r": 5, "c": 5}})["view"]["grid"]
    v2 = api("/api/task/move", {"token": m2["token"], "move": {"r": 5, "c": 5}})["view"]["grid"]
    assert v1 == v2
    m3 = api("/api/task/start", {"kind": "mines", "level": "easy"})
    assert sum(1 for row in api("/api/task/answer", {"token": m3["token"]})["view"]["grid"] for x in row if x == "m") == 10
    # 何度でも続けて (休憩なし). 終えた盤面には打てない. 知らない盤面・パスはお断り
    for _ in range(5):
        api("/api/task/finish", {"token": api("/api/task/start", {"kind": "picross", "level": "easy"})["token"]})
    out, code = L.call_api("POST", "/api/task/move", {"token": a["token"], "move": {"r": 0, "c": 0, "v": 1}})
    assert code == 400
    assert L.call_api("POST", "/api/task/move", {"token": "nope", "move": {}})[1] == 400
    assert L.call_api("GET", "/api/nothing", None)[1] == 404
    assert os.listdir(TMP) == [], "ゲームのデータには何も書かない"
    print("lab api: OK")

    # ページと共通の画面: 単独版のページは static/puzzles.js を使い, 本体も同じものを使う
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    page = open(os.path.join(root, "static", "puzzle_lab.html"), encoding="utf-8").read()
    index = open(os.path.join(root, "static", "index.html"), encoding="utf-8").read()
    app_js = open(os.path.join(root, "static", "app.js"), encoding="utf-8").read()
    assert "/static/puzzles.js" in page and "/static/puzzles.js" in index
    assert "function renderTask" not in app_js and "function renderTask" in open(os.path.join(root, "static", "puzzles.js"), encoding="utf-8").read()
    print("shared screen: OK")
    print("ALL OK")


if __name__ == "__main__":
    main()
