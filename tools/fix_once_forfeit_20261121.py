"""一回限りの直し (2026-11-21): 野球拳 3 回勝負で 2-1 で勝ったのに残った, あなたの「一日スマホ禁止」を外す.

11/21 16:54 の野球拳 (おまかせ・3 回勝負) の 1 回戦で負けて付いた禁止 (11/22 16:54 まで). n 回勝負のルール (負けるたびに罰) は
変えていないので, ほかの禁止には触らない. 外すのは, 相手 c036592b9 の, あなたのスマホ禁止で, 期限が 11/22 16:50〜17:00 のものだけ.

使い方 (サーバーを止めてから. 動いたままだと, サーバーが覚えている状態で上書きされる):
    python tools/fix_once_forfeit_20261121.py            # 外す
    python tools/fix_once_forfeit_20261121.py --dry-run  # 外すものを見るだけ
別のデータの置き場で動かしているなら, KURASHI_DATA を同じにして実行する. 二度目は何もしない.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CID = "c036592b9"
LO = time.mktime((2026, 11, 22, 16, 50, 0, 0, 0, -1))
HI = time.mktime((2026, 11, 22, 17, 0, 0, 0, 0, -1))


def target(x):
    return x.get("who") == "me" and x.get("what") == "phone" and LO <= float(x.get("until") or 0) <= HI


def fix(app, cid=CID, dry=False):
    """外した数を返す."""
    if cid not in app.chars:
        print("キャラ %s が、いまのワールドにいません（ワールドを切り替えてから実行してください）" % cid)
        return 0
    st = app.state(cid)
    day = (st.get("forfeit") or {}).get("day") or []
    hit = [x for x in day if target(x)]
    for x in hit:
        print("外す: あなたのスマホ禁止（%s まで）" % time.strftime("%m/%d %H:%M", time.localtime(x["until"])))
    if not hit:
        print("外すものはありません（もう外した・期限が過ぎた）")
        return 0
    if dry:
        return len(hit)
    st["forfeit"]["day"] = [x for x in day if not target(x)]
    app.save_state(cid)
    app.solo.note("forfeit", "（11/21 の野球拳の罰のスマホ禁止は、取り消しになった）", time.time())
    print("外しました")
    return len(hit)


def main(argv):
    from core import engine
    app = engine.App()
    fix(app, dry="--dry-run" in argv)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
