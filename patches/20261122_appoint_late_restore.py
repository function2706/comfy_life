"""緊急パッチ (core/patches.py): 11/22 の約束に遅れると伝える手段が無く, 約束の場所に遅れて着いたときには
「行かなかった (missed)」になって相手がいなかった. その約束を, 11/22 19:30 に, いまいる場所で約束し直した形に戻す.

- 対象: 11/22 のうちの約束で, あなたが行かなかった扱い (status missed. 相手のすっぽかしではない: plan.noshow が偽) のうち
  いちばん新しいもの (どのワールドでも, 当たるのは 1 件だけ). 頼まれごと・水やり・看病・手伝いの約束は対象外.
- 場所: あなたがいま外出していればその行き先 (現在地). 外出していなければ, もとの約束の場所.
- すっぽかしで下がった分を戻す: 機嫌 (理由に残っている分)・信頼 +4・好感度 +2, 見立て (regard) +5 ほど, 「すっぽかした」の理由は済みに.
  相手の側の当日の出方は, 遅れず来る (約束し直したばかりなので).
- トークに「📅 19:30 に約束し直した」を残す.
"""
import time

ID = "20261122_appoint_late_restore"
DESC = "11/22 に遅れると伝えられずに消えた約束を、19:30 にいまいる場所で約束し直した形に戻す"
DAY0 = time.mktime((2026, 11, 22, 0, 0, 0, 0, 0, -1))
NEW_T = time.mktime((2026, 11, 22, 19, 30, 0, 0, 0, -1))
UNTIL = NEW_T          # 19:30 を過ぎたら, もう約束し直す意味が無い
GRACE = 45 * 60


def _target(x):
    pl = x.get("plan") or {}
    return (x.get("status") == "missed" and not pl.get("noshow") and DAY0 <= float(x.get("t") or 0) < NEW_T
            and not (x.get("favor") or x.get("plants") or x.get("care") or x.get("help")))


def _clamp(v):
    return max(0.0, min(100.0, v))


def apply(ctx):
    best = None
    for wid in ctx.worlds():
        pp = ctx.store.dpath("worlds", wid, "player.json")
        ps = ctx.store.load(pp, None) or {}
        for x in ps.get("appoints") or []:
            if _target(x) and (best is None or x["t"] > best[2]["t"]):
                best = (wid, ps, x)
    if not best:
        return None          # このデータには無い (別のデータの置き場). 期限まで見る
    wid, ps, x = best
    old_t, old_place = x["t"], x.get("place")
    pres = ps.get("presence") or {}
    if pres.get("mode") == "out" and pres.get("place") and not pres.get("travel"):
        x["place"] = pres["place"]
    x.update(t=NEW_T, status="set", restored=ID)
    x.pop("arrived", None)
    x["plan"] = {"noshow": False, "late": 0, "cancel_checked": True, "move": False, "go": 0}
    ctx.store.save(ctx.store.dpath("worlds", wid, "player.json"), ps)

    cid = x["cid"]
    sp = ctx.store.dpath("worlds", wid, "state", cid + ".json")
    st = ctx.store.load(sp, None)
    back = ""
    if st:
        p = st.setdefault("params", {})
        mood = 0.0
        for r in st.get("reasons") or []:
            if r.get("action") == "_appoint" and r.get("mood") == "bad" and "すっぽかした" in str(r.get("tell", "")) \
                    and abs(float(r.get("t", 0)) - old_t) < 3 * 3600 and not r.get("resolved"):
                r["resolved"] = True
                mood -= float(r.get("delta") or 0)
        if not mood:
            mood = 8.0
        for k, v in (("mood", mood), ("trust", 4.0), ("affection", 2.0)):
            if k in p:
                p[k] = round(_clamp(float(p[k]) + v), 2)
        rg = st.get("regard")
        if rg and "v" in rg:
            rg["v"] = round(_clamp(float(rg["v"]) + 5.0), 2)
        ctx.store.save(sp, st)
        back = "（機嫌 +%.0f・信頼 +4・好感度 +2 を戻した）" % mood

    cp = ctx.store.dpath("worlds", wid, "chats", cid + ".json")
    ch = ctx.store.load(cp, None)
    if ch is not None:
        ch.setdefault("items", []).append({"who": "sys", "kind": "promise", "t": time.time(),
                                           "text": "📅 約束し直した: 今日 19:30（遅れると伝えて、待ち合わせを変えた）"})
        ctx.store.save(cp, ch)
    return "約束 %s を %s → 19:30 に戻した（場所 %s → %s）%s" % (x.get("id"), time.strftime("%H:%M", time.localtime(old_t)),
                                                     old_place, x["place"], back)
