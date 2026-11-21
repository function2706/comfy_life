"""アプリの更新 (設定 → データ の「アプリの更新」): git で取ってきて (pull), サーバを起動し直す.

- 確認 (check): origin から取ってきて (fetch), 手元より新しいコミットの数と一覧, 手元で書き換えたファイル (追跡しているもの) を返す.
- 更新 (pull): 早送りできるときだけ取り込む (git pull --ff-only). 手元で書き換えたファイルがあれば取り込まない (上書きしない).
- 起動し直すのは server.py (更新のあと・「再起動」). データ (data/) は git の外なので, 更新では変わらない.
- 緊急パッチ (patches/. core/patches.py) は, 当てたあと手元で消すので, 消したものは書き換えとみなさず, 取り込む前に戻す.
git が無い・リポジトリでないときは, そう伝えるだけ.
"""
import os
import subprocess

from . import patches, store


def _git(*args, timeout=60):
    """git を kurashi の場所で動かす. (成功したか, 出力) を返す."""
    try:
        r = subprocess.run(["git", "-C", store.BASE] + list(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout, encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        return False, "git が見つかりません（git をインストールすると、ここから更新できます）"
    except subprocess.TimeoutExpired:
        return False, "git の応答がありません（ネットワークを確かめてください）"
    return r.returncode == 0, (r.stdout or "").strip()


def number():
    """版の番号 (kurashi 直下の VERSION. 例 1.0.0 / 1.1.0beta). 無ければ空."""
    try:
        with open(os.path.join(store.BASE, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def version():
    """いまの版: {number, commit, date, branch} (git でなければ None)."""
    ok, out = _git("log", "-1", "--format=%h\t%cd", "--date=format:%Y-%m-%d %H:%M")
    if not ok or "\t" not in out:
        return None
    h, d = out.split("\t", 1)
    okb, br = _git("rev-parse", "--abbrev-ref", "HEAD")
    return {"number": number(), "commit": h, "date": d, "branch": br if okb else ""}


def _status():
    ok, out = _git("status", "--porcelain", "--untracked-files=no")
    return [(ln[:2], ln[3:]) for ln in out.splitlines() if ln.strip()] if ok else []


def _patch_gone(code, f):
    """当てて消した緊急パッチ (手元で消しただけ)."""
    return code == " D" and f.startswith(patches.REL)


def dirty():
    """手元で書き換えた (追跡している) ファイル. data/ などは git の外なので入らない. 当てて消した緊急パッチは入れない."""
    return [f for code, f in _status() if not _patch_gone(code, f)]


def check():
    """新しい版があるか: {ok, version, behind, commits: [{hash, subject, when}], dirty, error}."""
    v = version()
    if not v:
        return {"ok": False, "error": "git のリポジトリではないので、ここからは更新できません"}
    ok, out = _git("fetch", "--quiet", timeout=60)
    if not ok:
        return {"ok": False, "version": v, "error": "取ってこられませんでした: %s" % out[-300:]}
    ok, out = _git("log", "--format=%h\t%s\t%cr", "HEAD..@{u}")
    if not ok:
        return {"ok": False, "version": v, "error": "追いかける先 (upstream) が分かりません: %s" % out[-200:]}
    commits = [dict(zip(("hash", "subject", "when"), ln.split("\t", 2))) for ln in out.splitlines() if ln.count("\t") >= 2]
    return {"ok": True, "version": v, "behind": len(commits), "commits": commits[:30], "dirty": dirty()}


def pull():
    """取り込む (早送りだけ). {ok, changed, text, version}. 書き換えたファイルがあれば取り込まない."""
    d = dirty()
    if d:
        return {"ok": False, "changed": False, "text": "手元で書き換えたファイルがあるので、更新しませんでした: %s" % "、".join(d[:8])}
    gone = [f for code, f in _status() if _patch_gone(code, f)]
    if gone:                     # 当てて消したパッチを戻してから取り込む (次の起動で, 記録を見て消すだけ)
        _git("checkout", "--", *gone)
    before = version()
    ok, out = _git("pull", "--ff-only", "--quiet", timeout=180)
    if not ok:
        return {"ok": False, "changed": False, "text": "更新できませんでした: %s" % out[-400:]}
    after = version()
    return {"ok": True, "changed": (before or {}).get("commit") != (after or {}).get("commit"), "text": out, "version": after}


RESTART_FLAG = "restart.flag"


def restart_flag_path():
    return os.path.join(store.DATA, RESTART_FLAG)
