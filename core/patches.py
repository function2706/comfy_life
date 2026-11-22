"""緊急パッチ: アプリの更新 (core/update.py) で一緒に届いた, 一回限りのデータの直しを, 起動のときに当てて消す.

置き場: kurashi/patches/*.py (git で配る. 名前が _ で始まるものは読まない). 1 つのファイル = 1 つのパッチ. 中身:
    ID = "20261121_yakyuken_phone_ban"   # 重ならない名前 (日付から)
    DESC = "..."                          # 何を直すか (ログに出す)
    UNTIL = 1795000000                    # 任意. この時刻を過ぎたら当てずに終える (直すものがもう無い)
    def apply(ctx): ...                   # 当てる. 直したら結果の文 (str) を返す. ここにまだ対象が無ければ None (消さずに次の起動でまた見る)

ctx: store (core/store.py. dpath / load / save) と, worlds() (ワールドの id の一覧) と, log(文).
アプリの状態を読み込む前 (engine.App() の前) に当てるので, ファイルを直接書き換えてよい (メモリの状態で上書きされない).

当てた・期限を過ぎたパッチは, data/patches.json に記録 (id・時刻・結果) する. **ファイルは消さない** (記録にあれば次からは当てない).
以前はファイルを消していて, git の作業フォルダが「手元で消した」状態になり, 更新を止めた (11/21・11/22 の二度. アプリが自分で
git 管理のファイルを触らないこと). 当て終えた古いパッチは, 開発側のコミットで消す. 例外のときは記録せず, ログに残して次の起動でまた試す.
以前の版で消えたままのパッチは, 更新 (update.pull) が取り込む前に戻す (互換のため残している).
"""
import importlib.util
import os
import time
import traceback
from datetime import datetime

from . import store

DIR = os.path.join(store.BASE, "patches")
REL = "patches/"          # git の中での置き場 (update.py が見る)
RECORD = "patches.json"


def _log(msg, level="info"):
    line = "%s [%s] patch: %s" % (datetime.now().strftime("%m-%d %H:%M:%S"), level.upper(), msg)
    try:
        with open(store.dpath("server.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    try:
        print(line, flush=True)
    except (OSError, UnicodeEncodeError):
        pass


def files():
    if not os.path.isdir(DIR):
        return []
    return sorted(os.path.join(DIR, n) for n in os.listdir(DIR) if n.endswith(".py") and not n.startswith("_"))


def record():
    return store.load(store.dpath(RECORD), {}) or {}


class Ctx:
    store = store

    @staticmethod
    def worlds():
        d = store.dpath("worlds")
        return sorted(n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n))) if os.path.isdir(d) else []

    @staticmethod
    def log(msg):
        _log(msg)


def _load(path):
    spec = importlib.util.spec_from_file_location("kurashi_patch_" + os.path.basename(path)[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(now=None):
    """届いているパッチを当てる. [(id, 結果)] (この起動で終えたもの) を返す."""
    now = now or time.time()
    rec = record()
    done = []
    for path in files():
        name = os.path.basename(path)
        try:
            mod = _load(path)
            pid = str(getattr(mod, "ID", "") or name[:-3])
            if pid in rec:                 # 当てたことがある: 何もしない (ファイルは消さない. git の作業フォルダを汚さない)
                continue
            until = getattr(mod, "UNTIL", None)
            if until and now > float(until):
                res = "期限を過ぎたので当てなかった"
            else:
                res = mod.apply(Ctx)
                if res is None:            # まだ対象が無い (ワールド・キャラが無いなど). 次の起動でまた見る
                    continue
        except Exception:
            _log("%s を当てられませんでした（次の起動でまた試します）\n%s" % (name, traceback.format_exc()), "error")
            continue
        rec[pid] = {"t": now, "desc": str(getattr(mod, "DESC", "")), "result": str(res)}
        store.save(store.dpath(RECORD), rec)
        _log("%s: %s → %s" % (pid, getattr(mod, "DESC", ""), res))
        done.append((pid, str(res)))
    return done
