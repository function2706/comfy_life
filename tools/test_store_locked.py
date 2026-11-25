"""ほかのプロセス (BOX などの同期ソフト・ウイルス対策ソフト) がファイルを一瞬つかんでいるときの読み書き.
- 読み込み: 共有なしで開かれている間は待ち, 放されたら読める (以前は PermissionError で画面の取得が落ちた)
- ずっと放されなければ, 待ちすぎずに PermissionError を返す
- 書き込みも同じく, 放されたら置き換えられる

Windows の本物のロック (CreateFileW の共有なし) で確かめる. Windows 以外では飛ばす.

    python tools/test_store_locked.py
"""
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import store  # noqa: E402

fails = []


def check(cond, msg):
    print(("OK  " if cond else "NG  ") + msg)
    if not cond:
        fails.append(msg)


def lock(path):
    """共有なし (読みも書きも消しも不可) で開く. 同期ソフトがアップロード中につかむのと同じ状態."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                              wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    h = k.CreateFileW(path, 0x80000000, 0, None, 3, 0x80, None)   # GENERIC_READ, 共有 0, OPEN_EXISTING
    assert h != wintypes.HANDLE(-1).value, ctypes.get_last_error()
    return lambda: k.CloseHandle(wintypes.HANDLE(h))


def later(sec, fn):
    t = threading.Timer(sec, fn)
    t.start()
    return t


def main():
    if os.name != "nt":
        print("Windows 以外なので飛ばす")
        return
    d = tempfile.mkdtemp()
    p = os.path.join(d, "chats", "hina.json")
    store.save(p, {"msgs": [1, 2, 3]})

    # 読み込み: 0.3 秒つかまれていても読める
    release = lock(p)
    try:
        open(p, encoding="utf-8").close()
        check(False, "ロック中は素の open が失敗する (前提)")
    except PermissionError:
        check(True, "ロック中は素の open が失敗する (前提)")
    t = later(0.3, release)
    got = store.load(p)
    t.join()
    check(got == {"msgs": [1, 2, 3]}, "つかまれていても放されたら読める")

    # 書き込み: 0.3 秒つかまれていても置き換えられる
    release = lock(p)
    t = later(0.3, release)
    store.save(p, {"msgs": [4]})
    t.join()
    check(store.load(p) == {"msgs": [4]}, "つかまれていても放されたら書ける")

    # ずっと放されない: 待ちすぎずに PermissionError
    release = lock(p)
    t0 = time.time()
    try:
        store.load(p)
        check(False, "放されなければ PermissionError")
    except PermissionError:
        check(True, "放されなければ PermissionError")
    check(time.time() - t0 < 5, "あきらめるまで 5 秒未満 (%.1f 秒)" % (time.time() - t0))
    release()

    # 無いファイルは既定値のまま (待たない)
    t0 = time.time()
    check(store.load(os.path.join(d, "none.json"), {"x": 1}) == {"x": 1} and time.time() - t0 < 0.1,
          "無いファイルはすぐ既定値")

    print("\n%s" % ("すべて OK" if not fails else "NG %d 件" % len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
