"""開発者向け: 不具合の報告で貼られた書き出し (KURASHI-DUMP) を読める形にする. 途中で切れた・化けたときは知らせて, 読めたところまで出す.
判断の記録 (worlds/<id>/trace.dat) を直接読むこともできる.

    python tools/debug_decode.py 貼られたテキストのファイル [-o 出力ファイル]
    python tools/debug_decode.py --trace data/worlds/<id>/trace.dat
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.debugdump import decode_block  # noqa: E402
from core.trace import dec  # noqa: E402


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "--trace":
        for ln in io.open(argv[1], encoding="ascii"):
            if ln.strip():
                print(dec(ln))
        return 0
    text, probs = decode_block(io.open(argv[0], encoding="utf-8", errors="replace").read())
    out = sys.stdout
    if "-o" in argv:
        out = io.open(argv[argv.index("-o") + 1], "w", encoding="utf-8")
    for p in probs:
        print("!! " + p, file=sys.stderr)
    out.write(text + "\n")
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
