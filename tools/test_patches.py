"""緊急パッチ (core/patches.py) と, 更新 (core/update.py) での扱いの確かめ.

- 当てる: 対象だけ直す・記録する・ファイルを消す. 二度目は何もしない
- 対象が無い (None): 消さず, 記録もせず, 次の起動でまた見る
- 期限を過ぎた: 当てずに記録して消す
- 例外: 消さず, 記録もせず, server.log にエラー
- 当てたことがあるのに戻ってきた (更新の前に戻した): 当てずに消すだけ
- 更新: 当てて消したパッチは「書き換え」とみなさず, 取り込む前に戻す. ほかの書き換えがあれば今までどおり取り込まない
- 同じ名前 (patches/patch.py) で上書きしても, ID ごとに一度だけ当たる

    python tools/test_patches.py
"""
import os
import shutil
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
TMP = tempfile.mkdtemp(prefix="kurashi_patch_")
os.environ["KURASHI_DATA"] = os.path.join(TMP, "data")
os.makedirs(os.environ["KURASHI_DATA"])

from core import patches, store, update  # noqa: E402

PDIR = os.path.join(TMP, "patches")
os.makedirs(PDIR)
patches.DIR = PDIR


def put(name, body):
    p = os.path.join(PDIR, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    return p


def state(wid, cid, day):
    p = store.dpath("worlds", wid, "state", cid + ".json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    store.save(p, {"params": {}, "forfeit": {"owed": [], "tickets": {}, "day": day}})
    return p


def main():
    try:
        # ---------------------------------------------------------------- 同じ名前 (patch.py) で上書きしても, ID ごとに一度だけ当たる
        body = 'ID = "%s"\nDESC = "x"\ndef apply(ctx):\n    n = ctx.store.load(ctx.store.dpath("n.json"), 0) or 0\n    ctx.store.save(ctx.store.dpath("n.json"), n + 1)\n    return "当てた"\n'
        f = put("patch.py", body % "p1")
        assert patches.run() == [("p1", "当てた")] and os.path.exists(f) and "p1" in patches.record(), "当てたら記録する (ファイルは消さない)"
        assert patches.run() == [] and store.load(store.dpath("n.json")) == 1, "二度目は当てない"
        put("patch.py", body % "p2")
        assert patches.run() == [("p2", "当てた")] and store.load(store.dpath("n.json")) == 2, "上書きした次のパッチは当たる"
        os.remove(f)
        print("同じ名前で上書き: OK")

        # ---------------------------------------------------------------- 対象が無い・期限・例外
        g = put("a_none.py", 'ID = "a_none"\nDESC = "x"\ndef apply(ctx):\n    return None\n')
        assert patches.run() == [] and os.path.exists(g) and "a_none" not in patches.record(), "対象が無ければ残す"
        os.remove(g)
        g = put("b_old.py", 'ID = "b_old"\nDESC = "x"\nUNTIL = 1\ndef apply(ctx):\n    raise AssertionError("当てない")\n')
        assert patches.run() == [("b_old", "期限を過ぎたので当てなかった")] and os.path.exists(g)
        g = put("c_err.py", 'ID = "c_err"\nDESC = "x"\ndef apply(ctx):\n    raise ValueError("こわれた")\n')
        assert patches.run() == [] and os.path.exists(g) and "c_err" not in patches.record(), "例外なら残す"
        assert "c_err.py を当てられませんでした" in open(store.dpath("server.log"), encoding="utf-8").read()
        os.remove(g)
        put("_skip.py", 'raise SystemExit("読まない")\n')
        g = put("d_ok.py", 'ID = "d_ok"\nDESC = "x"\ndef apply(ctx):\n    ctx.log("w=%s" % ",".join(ctx.worlds()))\n    return "済"\n')
        assert patches.run() == [("d_ok", "済")] and os.path.exists(g)
        assert "w=" in open(store.dpath("server.log"), encoding="utf-8").read()
        print("対象なし・期限・例外: OK")

        # ---------------------------------------------------------------- 更新での扱い (本物の git で)
        # 以前は git の出力全体を strip していて, status の 1 行目 " D patches/…" の行頭の空白が消え,
        # 当てて消したパッチを「書き換えたファイル: atches/…」として更新を止めていた (下の差し替えたテストでは見えなかった)
        import subprocess
        repo = os.path.join(TMP, "repo")
        os.makedirs(os.path.join(repo, "patches"))
        os.makedirs(os.path.join(repo, "core"))
        for rel in ("patches/20261121_yakyuken_phone_ban.py", "core/engine.py"):
            with open(os.path.join(repo, rel), "w", encoding="utf-8") as f:
                f.write("x = 1\n")
        g = lambda *a: subprocess.run(["git", "-C", repo] + list(a), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)  # noqa: E731
        g("init", "-q")
        g("add", "-A")
        g("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init")
        base0 = store.BASE
        store.BASE = repo
        try:
            os.remove(os.path.join(repo, "patches", "20261121_yakyuken_phone_ban.py"))
            assert update._status() == [(" D", "patches/20261121_yakyuken_phone_ban.py")], update._status()
            assert update.dirty() == [], update.dirty()
            with open(os.path.join(repo, "core", "engine.py"), "a", encoding="utf-8") as f:
                f.write("y = 2\n")
            assert update.dirty() == ["core/engine.py"], update.dirty()
        finally:
            store.BASE = base0
        print("更新 (本物の git): OK | 当てて消したパッチは書き換えに入れない・ほかの書き換えは入れる")

        # ---------------------------------------------------------------- 更新での扱い (取り込みの流れ)
        st = [(" D", "patches/20261121_yakyuken_phone_ban.py")]
        calls = []
        update._status = lambda: st
        update._git = lambda *a, **k: (calls.append(a), (True, ""))[1]
        update.version = lambda: {"commit": "x"}
        assert update.dirty() == [], "当てて消したパッチは書き換えに入れない"
        r = update.pull()
        assert r["ok"] and calls[0] == ("checkout", "--", "patches/20261121_yakyuken_phone_ban.py") and calls[1][0] == "pull", calls
        st[:] = [(" D", "patches/x.py"), (" M", "core/engine.py")]
        calls[:] = []
        assert update.dirty() == ["core/engine.py"]
        assert not update.pull()["ok"] and not calls, "ほかの書き換えがあれば取り込まない"
        st[:] = [(" M", "patches/x.py")]
        assert update.dirty() == ["patches/x.py"], "パッチを書き換えたのは書き換え"
        print("更新: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
