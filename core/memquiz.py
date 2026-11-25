"""謝る・お礼の理由を, 記憶で選ぶ (A20). 出題はサーバーで作って覚え, 画面には文と札 (中身の分からない id) だけを渡す.

選択肢は「いつ・どこで・何を」まで書いた具体的な出来事の文. どれも記録から作る (作り物っぽくしない):
- 正解 (fault / favor / forgave): 相手が気にしていること (機嫌の理由. 選び方は manners.apology と同じ) / してくれたこと.
- その相手にした本当の行動 (real): 正解の前後 1 時間に, あなたがその相手に送ったメッセージ・電話・会っていたときのコマンド.
  どれも本当にあったので, 問いは「どれが気に障ったか」になる. 単独行動は混ぜない.
- 他の人との本当の出来事 (other): 同じころ, あなたがほかのキャラクターにした / してもらったこと (名前は出さない).
- 細部だけ違う外れ (shift): 本物から細部を 1 つだけずらす (日・時間帯・時刻・回数・中身).
細部の細かさは, 正解がどれだけ前かで変える (どの時点で謝っても同じくらい難しく):
  12 時間より前 = 曜日・時間帯 / 1〜12 時間前 = 時刻・回数 / 1 時間以内 = 時刻を書かず, 文言・回数だけ.
並びは開くたびに入れ替える. 同じ問いは 3 時間・答えるまで使い回す (開き直して入れ替わったものから答えが浮かないように.
外れの作り方は正解と外した回数から決まるので, 作り直しても同じ外れになる). 答えたら捨てる.
判定は manners.apology / thanks_pick (選んだものの type で).
"""
import hashlib
import random
import secrets
from datetime import datetime

from . import msgpick

N = 6                      # 選択肢の数 (目安)
NEIGHBOR = 3600            # 正解の前後, その相手にした行動を拾う幅
REAL_SPAN = 3 * 86400      # 送ったもの・コマンドを拾う古さ
OTHER_SPAN = 86400         # 他の人との出来事を拾う, 正解からの幅
TTL = 3 * 3600             # 同じ問いを使い回す長さ
GROUP_GAP = 600            # 続けて送った同じメッセージを 1 つにまとめる間
WEEK = "月火水木金土日"
SKIP_CMDS = ("message", "call")      # メッセージ・電話はトークの記録から

# 機嫌の理由 (メッセージ・コマンド以外) を, あなたがしたことの文に
FAULT_BODY = {
    "no_reply": "メッセージに返事をしなかった",
    "too_often": "続けて何度も連絡した",
    "late_night": "夜中にメッセージを送った",
    "stamp_spam": "スタンプを続けて送った",
    "selfie_pester": "自撮りを何度も頼んだ",
    "reply_manner": "もらったメッセージに、そっけなく返した",
    "greet_miss": "いつものあいさつを送らなかった",
    "appoint": "約束に遅れていった",
    "drop_in": "約束なしに家に行った",
    "drift": "しばらく会いに行かなかった",
    "street": "外で会ったのに、急いでいると流した",
    "anniv_forgot": "誕生日・記念日を忘れていた",
    "home": "散らかった家に呼んだ",
    "chores": "家事をためていた",
    "chores_scold": "家事のことで責めた",
    "borrow": "お金の貸し借りで困らせた",
    "pay": "支払いのことで困らせた",
    "help": "手伝ってもらったのに、そのままにした",
    "fight": "言い争いをした",
    "jealous": "ほかの人と親しくしているところを見られた",
    "call_silent": "電話の途中で、返事をしなくなった",
    "call_cut": "かけてきてくれた電話を、すぐ切った",
    "call_missed": "かけてきてくれた電話に出なかった",
    "face_silent": "話している途中で、上の空になった",
    "face_cut": "話の途中で、ほかのことを始めた",
}
# 送ったメッセージが元になる理由 (元のメッセージを探して, その文で出す)
FROM_MSG = {"late_night": None, "too_often": None, "stamp_spam": "stamp", "selfie_pester": "ask_selfie"}


def _band(h):
    return "朝" if 4 <= h < 10 else "昼" if 10 <= h < 15 else "夕方" if 15 <= h < 18 else "夜" if 18 <= h < 23 else "夜中"


def level_of(age):
    return "day" if age >= 12 * 3600 else "hour" if age >= 3600 else "none"


def when(t, now, level):
    if level == "none":
        return ""
    dt, dn = datetime.fromtimestamp(t), datetime.fromtimestamp(now)
    d = (dn.date() - dt.date()).days
    day = {0: "今日", 1: "きのう", 2: "おととい"}.get(d) or "%s曜" % WEEK[dt.weekday()]
    return day + ("の" + _band(dt.hour) if level == "day" else "の%d時ごろ" % dt.hour)


def body(app, ev):
    """出来事の「何を」の文 (いつ・どこで は label で)."""
    from .chat import KINDS
    s, n = ev["src"], ev.get("n", 1)
    if s == "msg":
        if ev["kind"] == "call":
            return "電話をかけた" if n == 1 else "%d回続けて電話をかけた" % n
        w = KINDS.get(ev["kind"], (ev["kind"],))[0]
        return "「%s」と送った" % w if n == 1 else "「%s」を%d回続けて送った" % (w, n)
    if s == "cmd":
        w = ("%sで" % ev["where"]) if ev.get("where") else ""
        return "%s「%s」をした" % (w, ev["name"]) if n == 1 else "%s「%s」を%d回した" % (w, ev["name"], n)
    if s == "fault":
        it = ev.get("item") or ""
        if it == "too_often":
            return "続けて%d回連絡した" % max(2, n)
        if ev.get("msg"):           # 元のメッセージがわかっている (夜中・スタンプ・自撮り・からかい など)
            return body(app, ev["msg"])
        if it.startswith("cmd:"):
            return body(app, {"src": "cmd", "name": ev.get("name") or it[4:], "where": ev.get("where"), "n": 1})
        if it.startswith("msg:"):
            return body(app, {"src": "msg", "kind": it[4:], "n": 1})
        return FAULT_BODY.get(it, "気に障ることをした")
    if s in ("favor", "forgave"):
        return "謝ったのを許してくれた" if s == "forgave" else dict(msgpick.FAVORS).get(ev["what"], ev["what"])
    return ""


def label(app, ev, now, level):
    w = when(ev["t"], now, level)
    return (w + "、" if w else "") + body(app, ev)


# ------------------------------------------------------------------ 記録から出来事を集める
def my_msgs(app, cid, lo, hi):
    """あなたがその相手に送ったメッセージ・かけた電話 (続けて送った同じものは 1 つにまとめて回数に)."""
    from .chat import KINDS
    out = []
    for it in app.chat.load(cid)["items"]:
        t = it.get("t", 0)
        if it.get("who") != "me" or not (lo <= t <= hi) or not it.get("kind"):
            continue
        k = "call" if (it.get("text") or "").startswith("（電話で") else it["kind"]
        if k != "call" and k not in KINDS:
            continue
        last = out[-1] if out else None
        if last and last["kind"] == k and t - last["t"] <= GROUP_GAP:
            last["n"] += 1
            last["t"] = t
            last["ts"].append(t)
            continue
        out.append({"src": "msg", "kind": k, "t": t, "n": 1, "ts": [t], "item": "call" if k == "call" else "msg:" + k})
    return out


def my_cmds(app, cid, lo, hi):
    """会っていたときに, その相手としたコマンド."""
    out = []
    for e in app.log(cid):
        t, a = e.get("t", 0), e.get("action") or ""
        if not (lo <= t <= hi) or e.get("apart") or not a or a.startswith("_") or a in SKIP_CMDS:
            continue
        last = out[-1] if out else None
        if last and last["action"] == a and t - last["t"] <= 1800:
            last["n"] += 1
            last["t"] = t
            last["ts"].append(t)
            continue
        out.append({"src": "cmd", "action": a, "name": e.get("action_name") or a, "where": e.get("location") or "",
                    "t": t, "n": 1, "ts": [t], "item": "cmd:" + a})
    return out


def fault_event(app, cid, r):
    """機嫌の理由 (あなたのせい) を, 出来事にする. 元のメッセージ・コマンドが分かればその細部で."""
    it = msgpick.reason_item(r) or ""
    ev = {"src": "fault", "t": r["t"], "rt": r["t"], "item": it, "n": 1, "ts": []}
    if it in FROM_MSG or it.startswith("msg:"):
        want = FROM_MSG.get(it) or (it[4:] if it.startswith("msg:") else None)
        ms = [m for m in my_msgs(app, cid, r["t"] - 3 * 3600, r["t"] + 60) if not want or m["kind"] == want]
        if it == "too_often":
            ev["n"] = sum(m["n"] for m in ms) or 2
            ev["ts"] = [t for m in ms for t in m["ts"]]
            if ms:
                ev["t"] = ms[-1]["t"]
        elif ms:
            ev["msg"] = dict(ms[-1])
            ev["t"] = ms[-1]["t"]
            ev["ts"] = list(ms[-1]["ts"])
    elif it.startswith("cmd:"):
        cs = [c for c in my_cmds(app, cid, r["t"] - 3 * 3600, r["t"] + 60) if c["item"] == it]
        if cs:
            ev.update(name=cs[-1]["name"], where=cs[-1]["where"], t=cs[-1]["t"], ts=list(cs[-1]["ts"]))
        else:
            try:
                ev["name"] = app.action(it[4:]).get("name", it[4:])
            except KeyError:
                ev["name"] = it[4:]
    return ev


def others(app, cid, kind, lo, hi):
    """あなたがほかのキャラクターにした / してもらった本当の出来事 (名前は文に出さない)."""
    out = []
    for o in list(app.chars):
        if o == cid:
            continue
        try:
            if kind == "thanks":
                out += [{"src": "favor", "what": f["what"], "t": f["t"], "n": 1, "ts": [f["t"]]}
                        for f in app.state(o).get("favors") or [] if lo <= f["t"] <= hi and f["what"] in dict(msgpick.FAVORS)]
            else:
                out += my_msgs(app, o, lo, hi) + my_cmds(app, o, lo, hi)
        except (KeyError, OSError, ValueError):
            continue
    return out


# ------------------------------------------------------------------ 細部をずらす
def shift(app, ev, now, level, rnd):
    """細部を 1 つだけずらした出来事 (なかったこと). 時刻を書かない段では, 中身・回数だけ."""
    from .chat import KINDS
    opts = []
    if level == "day":
        opts += ["day", "band"]
    elif level == "hour":
        opts += ["clock"]
    if ev.get("n", 1) >= 2 or ev["src"] in ("msg", "cmd") or ev.get("item") == "too_often":
        opts.append("count")
    opts.append("content")
    how = rnd.choice(opts)
    x = dict(ev, shift=True)
    x.pop("ts", None)
    if how in ("day", "band", "clock"):
        step = {"day": 86400, "band": 6 * 3600, "clock": rnd.choice((2, 3)) * 3600}[how]
        x["t"] = ev["t"] - step if ev["t"] + step > now or rnd.random() < 0.5 else ev["t"] + step
    elif how == "count":
        n = max(1, ev.get("n", 1))
        x["n"] = n + 1 if n == 1 or rnd.random() < 0.5 else n - 1
        if x.get("item") == "too_often":
            x["n"] = max(2, x["n"])
        if x.get("msg"):
            x["msg"] = dict(x["msg"], n=x["n"])
    else:
        s = ev["src"]
        m = ev.get("msg")
        if s == "msg" or m:
            src = m or ev
            ks = [k for k in msgpick.MSG_KINDS if k in KINDS and k != src.get("kind")]
            nm = dict(src, kind=rnd.choice(ks))
            if m:
                x["msg"] = nm
            else:
                x.update(kind=nm["kind"], item="msg:" + nm["kind"])
        elif s == "cmd" or (s == "fault" and (ev.get("item") or "").startswith("cmd:")):
            a0 = ev.get("action") or (ev.get("item") or "")[4:]
            try:
                cat = app.action(a0).get("category")
            except KeyError:
                cat = None
            cs = [a for a in app.actions if a.get("category") == cat and a["id"] != a0 and not a["id"].startswith("_")
                  and a.get("category") != "system"] or [a for a in app.actions if a["id"] != a0 and not a["id"].startswith("_")
                                                         and a.get("category") != "system"]
            a = rnd.choice(cs)
            x.update(action=a["id"], name=a.get("name", a["id"]))
            if s == "fault":
                x["item"] = "cmd:" + a["id"]
        elif s == "favor":
            x["what"] = rnd.choice([k for k, _ in msgpick.FAVORS if k not in (ev["what"], "forgave")])
        elif s == "fault":
            it = ev.get("item")
            grp = [g for g in msgpick.NEAR if it in g]
            cand = [k for g in grp for k in g if k != it and k in FAULT_BODY] or [k for k in FAULT_BODY if k != it]
            x["item"] = rnd.choice(sorted(cand))
            x.pop("msg", None)
        else:            # 許してくれた: 別のしてくれたことに
            x.update(src="favor", what=rnd.choice([k for k, _ in msgpick.FAVORS if k != "forgave"]))
    return x


# ------------------------------------------------------------------ 出題
def _rng(cid, kind, anchor_t, tries):
    h = hashlib.sha1(("%s:%s:%s:%s" % (cid, kind, round(anchor_t or 0), tries)).encode()).hexdigest()
    return random.Random(int(h[:12], 16))


def build(app, cid, kind, now, tries=0):
    """出題 {sig, level, items: [entry]}. entry = {label, type, ...判定に使うもの}."""
    st = app.state(cid)
    real, anchor = [], None
    if kind == "apology":
        fs = [r for r in app.manners._faults(st, now) if msgpick.reason_item(r)]
        if fs:
            active = [x for x in fs if now - x["t"] <= 12 * 3600]
            r = max(active or fs, key=lambda x: (abs(x.get("delta", 0)), x["t"]))
            anchor = dict(fault_event(app, cid, r), type="fault")
        own = my_msgs(app, cid, now - REAL_SPAN, now) + my_cmds(app, cid, now - REAL_SPAN, now)
        fitems = {msgpick.reason_item(x) for x in fs}
        used = set(anchor["ts"]) if anchor else set()
        own = [e for e in own if e["item"] not in fitems and not used.intersection(e["ts"])]
        center = anchor["t"] if anchor else max([e["t"] for e in own] or [now])
        near = sorted([e for e in own if abs(e["t"] - center) <= NEIGHBOR], key=lambda e: abs(e["t"] - center))
        if not anchor:          # 気にしていることが無い: 最近その相手にしたことが並ぶ (どれも「気にしてない」)
            near = sorted(own, key=lambda e: -e["t"])
        real = [dict(e, type="real") for e in near]
    else:
        fav = [f for f in st.get("favors") or [] if now - f["t"] < 2 * 86400 and f["what"] in dict(msgpick.FAVORS)]
        real = [{"src": "favor", "what": f["what"], "t": f["t"], "n": 1, "ts": [f["t"]], "type": "favor"} for f in fav]
        al = st.get("apology_last") or {}
        if al.get("t") and 0 <= now - al["t"] < 86400 and al.get("out"):
            real.append({"src": "forgave", "t": al["t"], "n": 1, "ts": [al["t"]], "type": "forgave"})
        real.sort(key=lambda e: -e["t"])
        fresh = [e for e in real if e["type"] == "favor" and not next(
            (f for f in fav if f["t"] == e["t"] and f["what"] == e["what"]), {}).get("thanked")]
        anchor = (fresh or real or [None])[0]
        if anchor:
            real = [e for e in real if e is not anchor]
    lv_t = anchor["t"] if anchor else max([e["t"] for e in real] or [now - 86400])
    level = level_of(now - lv_t)
    rnd = _rng(cid, kind, anchor["t"] if anchor else None, tries)
    items, seen = [], set()
    # 本当にあったことの文 (細部をずらした外れが, たまたま本当のことにならないように)
    if kind == "apology":
        allreal = my_msgs(app, cid, now - REAL_SPAN - 86400, now) + my_cmds(app, cid, now - REAL_SPAN - 86400, now)
    else:
        allreal = [{"src": "favor", "what": f["what"], "t": f["t"], "n": 1} for f in st.get("favors") or []]
    truth = {label(app, e, now, level) for e in allreal + ([anchor] if anchor else []) + real}

    def put(ev, typ, **extra):
        lb = label(app, ev, now, level)
        if not lb or lb in seen:
            return False
        seen.add(lb)
        e = {"label": lb, "type": typ, "t": ev["t"], "item": ev.get("item"), "what": ev.get("what")}
        if ev.get("rt") is not None:
            e["rt"] = ev["rt"]
        e.update(extra)
        items.append(e)
        return True

    if anchor:
        put(anchor, anchor["type"])
    n_real = 2 if anchor else 3
    for e in real[:6]:
        if sum(1 for x in items if x["type"] in ("real", "favor", "forgave")) >= n_real:
            break
        put(e, e["type"])
    if kind == "thanks":        # まだお礼していない「してくれたこと」は, 数を超えても全部出す (お礼を言いたいことが選べないのはおかしい)
        for e in fresh:
            put(e, "favor")
    center = anchor["t"] if anchor else lv_t
    oth = sorted(others(app, cid, kind, max(now - REAL_SPAN, center - OTHER_SPAN), min(now, center + OTHER_SPAN)),
                 key=lambda e: abs(e["t"] - center))
    n_oth = 2 if len(items) < 3 else 1
    for e in oth[:6]:
        if sum(1 for x in items if x["type"] == "other") >= n_oth:
            break
        if label(app, e, now, level) in truth:     # 文が本当のこと (この相手もしてくれた・した) と同じ: 人違いの札にしない (11/24)
            continue
        put(e, "other")
    # 足りない分は, 細部だけ違う外れ (正解から先に)
    srcs = ([anchor] if anchor else []) + real[:3] + ([] if anchor or real else oth[:2])
    for i in range(40):
        if len(items) >= N or not srcs:
            break
        ev = srcs[0] if i < 6 and anchor else srcs[i % len(srcs)]
        x = shift(app, ev, now, level, rnd)
        if label(app, x, now, level) in truth:
            continue
        put(x, "shift", of="fault" if ev is anchor and kind == "apology" else ev.get("type") or "other")
    # 思い当たる記録が何も無い: ありふれた出来事で「なかったこと」を並べる (選べば「何のこと？」「何のお礼？」)
    for i in range(30):
        if len(items) >= N // 2 or srcs:
            break
        t = now - rnd.uniform(3600, 2 * 86400)
        if kind == "apology":
            ev = {"src": "fault", "item": rnd.choice(sorted(FAULT_BODY)), "t": t, "n": 1}
        else:
            ev = {"src": "favor", "what": rnd.choice([k for k, _ in msgpick.FAVORS if k != "forgave"]), "t": t, "n": 1}
        if label(app, ev, now, level) not in truth:
            put(ev, "shift", of="none")
    return {"sig": [kind, anchor["t"] if anchor else None], "level": level, "items": items}


def ask(app, cid, kind, now):
    """謝る (apology) / お礼 (thanks) の問いを出す: {qid, choices: [{id, label}]}. 同じ問いは使い回し, 並びだけ入れ替える."""
    if kind not in ("apology", "thanks"):
        raise ValueError("選べるのは、謝る理由とお礼の理由だけです")
    st = app.state(cid)
    qs = st.setdefault("quiz", {})
    tries = sum(1 for t in st.get("apology_tries") or [] if now - t < 4 * 3600) if kind == "apology" else 0
    built = build(app, cid, kind, now, tries)
    q = qs.get(kind)
    if not q or now - q.get("t", 0) > TTL or q.get("sig") != built["sig"] or q.get("tries", 0) != tries:
        q = {"qid": secrets.token_hex(4), "t": now, "sig": built["sig"], "tries": tries, "level": built["level"],
             "items": {secrets.token_hex(4): e for e in built["items"]}}
        qs[kind] = q
    order = list(q["items"])
    random.shuffle(order)
    app.save_state(cid)
    return {"qid": q["qid"], "choices": [{"id": k, "label": q["items"][k]["label"]} for k in order]}


def resolve(app, cid, kind, tok):
    """選んだ札 → 出来事 (判定に使う). 問いは捨てる. 古い・違う札なら ValueError."""
    st = app.state(cid)
    q = (st.get("quiz") or {}).get(kind)
    if not q or tok not in q["items"]:
        raise ValueError("選びなおしてください（思い出していた内容が古くなりました）")
    e = dict(q["items"][tok])
    st["quiz"].pop(kind, None)
    return e
