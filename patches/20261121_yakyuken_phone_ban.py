"""緊急パッチ (core/patches.py): 11/21 16:54 の野球拳 (おまかせ・3 回勝負. 2-1 で勝ち) の 1 回戦で付いた, あなたの「一日スマホ禁止」を外す.

n 回勝負のルール (負けるたびに罰) は変えていないので, ほかの禁止には触らない.
外すのは, 相手 c036592b9 の, あなたのスマホ禁止で, 期限が 11/22 16:50〜17:00 のものだけ (どのワールドでも).
"""
import time

ID = "20261121_yakyuken_phone_ban"
DESC = "11/21 の野球拳 3 回勝負（2-1 で勝ち）で付いた、あなたのスマホ禁止を外す"
CID = "c036592b9"
LO = time.mktime((2026, 11, 22, 16, 50, 0, 0, 0, -1))
HI = time.mktime((2026, 11, 22, 17, 0, 0, 0, 0, -1))
UNTIL = HI           # 期限が過ぎれば, もう外すものは無い


def target(x):
    return x.get("who") == "me" and x.get("what") == "phone" and LO <= float(x.get("until") or 0) <= HI


def apply(ctx):
    hit = 0
    for wid in ctx.worlds():
        p = ctx.store.dpath("worlds", wid, "state", CID + ".json")
        st = ctx.store.load(p, None)
        day = ((st or {}).get("forfeit") or {}).get("day") or []
        keep = [x for x in day if not target(x)]
        if len(keep) == len(day):
            continue
        hit += len(day) - len(keep)
        st["forfeit"]["day"] = keep
        ctx.store.save(p, st)
    if not hit:
        return None          # このデータには無い (別のデータの置き場・まだ届いていない). 期限まで見る
    return "外した（%d 件）" % hit
