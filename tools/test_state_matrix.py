"""状態 × 行動の突き合わせ (整合性): いろいろな状態で, 押せるものを 1 つずつ押して,
画面で押せるものは本当にでき, 押せないものは本当にできない (ValueError) ことを確かめる.
- 「誰かと」のコマンド (available の ok. 一緒にお出かけ中の移動のコマンドは, 画面と同じく /api/outing/move に)
- 「一人で」の行動 (static/app.js の renderSoloTab と同じ判定: 在席・blocked.solo・寝る / 席を外す・plain の ok)
- ミニゲーム (games.view の ok と blocked.game)
あわせて, 状態ごとの決まり (離れている相手とはできない・お出かけ先では家でのことはできない など) も見る.
押すたびに, その状態のデータの写しから App を作り直す (押したことで次の判定が変わらないように).
相手から断られる (その場の受け答え) のは「できた」に数える. できない理由が入力の不足 (読む本がない) なのは除く.

    python tools/test_state_matrix.py            # すべての状態
    python tools/test_state_matrix.py meet       # 名前に meet を含む状態だけ

食い違いがあれば一覧を出して落ちる. 入力の要るもの (謝る中身・行き先など) は, 画面と同じく 1 つ選んで押す.
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, geo as G, msgpick, places as P, solo as S, store  # noqa: E402
from testclock import NOON, fix_noon  # noqa: E402

REAL_PHASE = engine.App.phase_at
fix_noon(engine)
# 時刻を変えた状態 (夜・朝) も: CLK があればその時刻 (時間帯・時刻の条件・行き先の営業). 無ければ昼 (fix_noon)
CLK = {"dt": None}
_noon_phase, _noon_ctx, _noon_you = engine.App.phase_at, engine.App.context, engine.App.you_context
_open_real = P.open_state_real


def _clk_fix(self, c):
    d = CLK["dt"]
    if d:
        c.update(hour=d.hour, time=d.hour * 60 + d.minute, phase=REAL_PHASE(self, d).get("id", ""))
    return c


engine.App.phase_at = lambda self, dt: REAL_PHASE(self, CLK["dt"]) if CLK["dt"] else _noon_phase(self, dt)
engine.App.context = lambda self, char, st, dt, scene=None, **kw: _clk_fix(self, _noon_ctx(self, char, st, dt, scene, **kw))
engine.App.you_context = lambda self, dt=None, roll=True: _clk_fix(self, _noon_you(self, dt, roll)) if dt is None else _noon_you(self, dt, roll)
P.open_state = lambda pid, dt: _open_real(pid, CLK["dt"] or NOON)
from core import offline as _off  # noqa: E402
_off.open_state = P.open_state

SKIP_CAT = ("system", "あなたの予定")      # あなたの予定 (作業する・出かける…) は「一人で」から (solo_probes で見る)
INPUT_ONLY = ("読む本がない",)
FORCE = {}                                  # 相手の予定の上書き (寝ている・出かけている)


def opts_for(app, a):
    """画面で押すときに添えるもの (static/app.js の cmdButton と同じ): 謝る中身などは一覧の 1 つめ, 行き先は開いているところの 1 つめ."""
    o = {}
    if a.get("pick") and a.get("mood_action"):
        picks = {"apology": msgpick.apology_choices(app), "thanks": msgpick.thanks_choices(),
                 "consult": [{"id": k, "label": w} for k, w, _ in msgpick.CONSULT]}
        lst = picks.get(a["pick"]) or []
        if lst:
            o["pick"] = lst[0]["id"]
    if len(a.get("places") or []) > 1:
        op = [p for p in a["places"] if P.open_state(p, datetime.now())["open"]]
        if op:
            o["place"] = op[0]
    return o


# ------------------------------------------------------------------ 状態をつくる (関数は app, cid を受け取り, 状態にする)
def _base(app, cid, stage):
    B = app.bonds
    if B.with_rec():
        B.end(go_home=False)
    st = app.state(cid)
    st["override"], st["cooldowns"] = None, {}
    app.presence.declare("none", time.time())
    app.presence.rec()["pos"] = "home:me"
    app.presence.save()
    B.set_stage(cid, stage)
    app.set_params({"affection": 70, "mood": 70, "energy": 80, "sleepiness": 0, "trust": 70}, cid)
    app.life.player_state()["money"] = 200000
    app.life.save_player()
    app.presence.beat(time.time(), 0)       # 画面を開いている (心拍がないと「いない」扱いになる)
    app.save_state(cid)
    return st


def s_alone(app, cid):            # 一人で家にいる (相手は離れている. 連絡先を知っている仲)
    _base(app, cid, "contact")


def s_live_home(app, cid):        # 同居相手と家にいる
    _base(app, cid, "live")


def s_guest(app, cid):            # 家に来てもらっている
    _base(app, cid, "visit")
    app.bonds.start(cid, "guest")


def s_visit(app, cid):            # 相手の家に来ている
    _base(app, cid, "visit")
    app.bonds.start(cid, "visit")


def s_stay(app, cid):             # 相手の家に泊まっている
    s_visit(app, cid)
    app.bonds.with_rec()["stay"] = {"t": time.time()}
    app.bonds.save()


def s_meet(app, cid):             # 外で会っている (約束の場所: 水族館)
    st = _base(app, cid, "contact")
    app.bonds.start(cid, "meet")
    st["override"] = {"outing": True, "place": "aquarium", "location": "水族館", "until": time.time() + 3600, "from_action": "aquarium"}
    app.presence.rec()["pos"] = "aquarium"
    app.save_state(cid)


def _outing(app, cid):
    st = _base(app, cid, "live")
    G.INSTANT = False
    try:
        app.act("aquarium", cid)
    finally:
        G.INSTANT = True
    return st


def _shift(ov, d):
    for tr in ov.get("trips") or []:
        tr["t0"] -= d
        tr["arr"] -= d
        for lg in tr.get("legs") or []:
            lg["t0"] -= d
            lg["t1"] -= d
    for k in ("arr", "leave", "until"):
        if ov.get(k):
            ov[k] -= d


def s_outing_moving(app, cid):    # 同居相手と一緒に出かけて, 行きの移動中
    st = _outing(app, cid)
    assert app.outing_trip(st, time.time()), st["override"]


def s_outing_there(app, cid):     # 同居相手と一緒に出かけて, 着いている
    st = _outing(app, cid)
    ov = st["override"]
    _shift(ov, ov["arr"] - time.time() + 1)
    ov["until"] = max(ov["until"], time.time() + 3600)
    if ov.get("leave"):
        ov["leave"] = max(ov["leave"], time.time() + 1800)
        for tr in ov["trips"]:
            if tr["dir"] == "home":
                d = ov["leave"] - tr["t0"]
                _shift({"trips": [tr]}, -d)
    ov.pop("arrive", None)
    app.save_state(cid)
    assert not app.outing_trip(st, time.time()) and app.outing_now()[0] == cid


def s_outing_home(app, cid):      # 同居相手と一緒に出かけて, 帰りの移動中
    st = _outing(app, cid)
    ov = st["override"]
    home = [tr for tr in ov.get("trips") or [] if tr["dir"] == "home"]
    assert home, ov
    _shift(ov, home[0]["t0"] - time.time() + 1)
    ov.pop("arrive", None)
    app.save_state(cid)
    tr = app.outing_trip(st, time.time())
    assert tr and tr["dir"] == "home", ov


def s_solo_out(app, cid):         # 一人で外出中 (公園. 相手は離れている)
    _base(app, cid, "contact")
    app.solo.start("out", None, "park")
    tr = app.geo.travel()
    if tr:
        app.geo.tick(tr["arr"] + 1)


def s_live_busy(app, cid):        # 同居相手は家にいて, あなたは家事の途中
    _base(app, cid, "live")
    app.solo.start("chores")


def s_asleep(app, cid):           # 同居相手と家にいて, 相手は寝ている
    _base(app, cid, "live")
    FORCE["asleep"] = True


def s_live_away(app, cid):        # 同居だが, 相手は自分の予定で出かけている (離れている)
    _base(app, cid, "live")
    FORCE["away"] = True


def s_helping(app, cid):          # 相手の家で, 頼まれごとの手伝いの最中
    s_visit(app, cid)
    now = time.time()
    app.bonds.with_rec()["helping"] = {"fid": "x", "t0": now, "until": now + 3600, "rest": 0}
    app.bonds.save()


def s_sick(app, cid):             # 同居相手が風邪で寝込んでいる (家で)
    st = _base(app, cid, "live")
    st["ill"] = {"t": time.time() - 3600, "until": time.time() + 86400, "level": 2}
    app.set_params({"health": 40}, cid)
    app.save_state(cid)


def s_fight(app, cid):            # 同居相手と言い争いの最中 (家で)
    st = _base(app, cid, "live")
    app.quarrel.start(app.char(cid), st, time.time(), "chores", False)
    app.save_state(cid)


def s_appt_wait(app, cid):        # 約束の場所 (水族館) に先に着いて, 約束の時刻を待っている
    _base(app, cid, "contact")
    A = app.appoint
    t = time.time() + 1800
    x = {"id": "xw", "cid": cid, "t": t, "place": "aquarium", "do": "aquarium", "by": "me", "status": "set", "made": t - 86400,
         "plan": {"noshow": False, "late": 0, "cancel_checked": True}}
    A.all().append(x)
    A.save()
    G.INSTANT = False
    try:
        A.go("xw")
        tr = app.geo.travel()
        if tr:
            app.geo.tick(tr["arr"] + 1)
    finally:
        G.INSTANT = True
    A.live(time.time())


def _at(h):
    def deco(fn):
        def run(app, cid):
            fn(app, cid)
        run.clock = datetime(NOON.year, NOON.month, NOON.day, h, 0)
        return run
    return deco


s_night_home = _at(22)(s_live_home)       # 夜 22 時, 同居相手と家に
s_morning_home = _at(7)(s_live_home)      # 朝 7 時, 同居相手と家に
s_night_alone = _at(22)(s_alone)          # 夜 22 時, 一人で家に
s_night_guest = _at(22)(s_guest)          # 夜 22 時, 家に来てもらっている

STATES = [("alone", s_alone), ("live_home", s_live_home), ("guest", s_guest), ("visit", s_visit), ("stay", s_stay), ("meet", s_meet),
          ("outing_moving", s_outing_moving), ("outing_there", s_outing_there), ("outing_home", s_outing_home),
          ("solo_out", s_solo_out), ("live_busy", s_live_busy), ("asleep", s_asleep), ("live_away", s_live_away),
          ("helping", s_helping), ("sick", s_sick), ("fight", s_fight), ("appt_wait", s_appt_wait),
          ("night_home", s_night_home), ("morning_home", s_morning_home), ("night_alone", s_night_alone), ("night_guest", s_night_guest)]
APART = ("alone", "solo_out", "live_away", "appt_wait", "night_alone")
OUTING = ("meet", "outing_moving", "outing_there", "outing_home")
MOVING = ("outing_moving", "outing_home")


# ------------------------------------------------------------------ 押すもの: (区分, id, 名前, 画面で押せるか, 押せない理由, 押す関数, 行動, available)
def person_probes(app, cid):
    av = app.person_view(cid)["available"]
    out = []
    for a in app.actions:
        if a.get("category") in SKIP_CAT or a["id"] == "side_job" or a["id"] not in av:      # 内職は「一人で」から
            continue
        ui = av[a["id"]]

        def run(app2, aid=a["id"], move_on=bool(ui.get("move_on"))):
            o = opts_for(app2, app2.action(aid))
            if move_on:                       # 一緒にお出かけ中: 画面は /api/outing/move へ (応じるかは相手しだい)
                return app2.outing_move(o.get("place"), None, aid)
            return app2.act(aid, cid, opts=o)
        out.append(("誰かと", a["id"], a.get("name"), bool(ui["ok"]), ui.get("why") or "", run, a, ui))
    return out


def solo_probes(app, cid):
    so = app.solo.view()
    bl = app.blocked("solo")
    free = app.presence.rec().get("mode") == "none"

    def ui_ok(out_ok=False, extra=True):
        b = "" if (out_ok and bl and bl == so.get("out_with")) else bl
        return bool(free and not b and extra), b or ("" if free else "在席でない")
    gv = app.topics.genres_view()
    args = {"practice": ("talk", None), "out": (None, "park"), "jog": (None, "park"),
            "read": (gv["books"][0]["id"], None), "movie": (gv["movies"][0]["id"], None)}
    out = []
    for k in list(S.KINDS) + ["kakeibo"]:
        sk, pl = args.get(k, (None, None))
        ok, why = ui_ok()
        out.append(("一人で", k, k, ok, why, lambda app2, k=k, sk=sk, pl=pl: app2.solo.start(k, sk, pl), {}, {}))
    for p in so["plain"]:
        ok, why = ui_ok(p.get("out_ok"), p["ok"])
        out.append(("一人で", p["id"], p["label"], ok, why or (p.get("why") or ""), lambda app2, k=p["id"]: app2.solo.start(k), {}, {}))
    return out


def game_probes(app, cid):
    char, st = app.char(cid), app.state(cid)
    gv = app.games.view(char, st, app.context(char, st, datetime.now()))
    bl = app.blocked("game")
    return [("ゲーム", g["id"], g["name"], bool(g["ok"]) and not bl, bl or g.get("require", ""),
             lambda app2, gid=g["id"]: app2.games.start(gid, cid), {}, {}) for g in gv["list"]]


def map_probes(app, cid):
    """外出の地図: 行き先ごとの「行く」ボタン (static/app.js の renderMap の can と mapGo と同じ)."""
    od = app.outdoor.view(time.time())
    pres = app.presence.rec()
    tv = od.get("travel")
    work_away = pres.get("mode") == "work" and (bool(tv) or (od.get("here") and od["here"] != "home:me"))
    free = pres.get("mode") in ("none", "out") or work_away
    wo = od.get("with_outing")
    out_choices = od["choices"].get("out") or []
    routes = od.get("routes") or {}
    out = []
    for pid in sorted(set(out_choices) | {"home:me"}):
        pl = od["places"].get(pid) or {}
        r = routes.get(pid) or {}
        here = pid == od.get("here") and not tv and not (wo and wo.get("moving"))
        heading = bool(wo) and wo.get("to") == pid
        no_with = bool(wo) and pid != "home:me" and pid not in (wo.get("spots") or [])
        goable = (pid not in ("office", "station")) or pid in out_choices
        modes_ok = any(m.get("ok") for m in (r.get("modes") or {}).values())
        ok = bool(free and goable and not here and not heading and not no_with and not od.get("out_with") and pl.get("open") is not False
                  and not (wo and pid == "home:me") and modes_ok)
        why = "free=%s here=%s heading=%s open=%s modes=%s" % (free, here, heading, pl.get("open"), modes_ok)

        def run(app2, pid=pid):
            pres2 = app2.presence.rec()
            od2 = app2.outdoor.view(time.time())
            if od2.get("with_outing") and pid != "home:me":
                return app2.outing_move(pid, None)
            if pid == "home:me" and pres2.get("mode") in ("out", "work"):
                return app2.come_back()
            if pres2.get("mode") in ("out", "work"):
                return app2.solo.move(pid)
            return app2.solo.start("out", None, pid)
        out.append(("地図", pid, pl.get("label") or pid, ok, why, run, {}, {}))
    return out


def phone_probes(app, cid):
    """スマホ: 連絡先 (そばにいない人) にメッセージ・電話. そばにいる相手は連絡先に出ない."""
    listed = any(c["id"] == cid for c in app._contacts_view())
    return [("スマホ", "message", "メッセージ", listed, "連絡先にいない", lambda app2: app2.chat.send(cid, "smalltalk"), {}, {}),
            ("スマホ", "call", "電話", listed, "連絡先にいない", lambda app2: app2.phone_call(cid, "smalltalk"), {}, {})]


def rules(sname, probes):
    """状態ごとの決まり (画面で押せるものについて)."""
    bad = []
    for kind, pid, name, ok, why, _, a, ui in probes:
        if not ok:
            continue
        if kind == "誰かと" and sname in APART and a.get("category") not in ("連絡", "会う"):
            bad.append((sname, pid, name, "離れているのに押せる", ""))
        if kind == "誰かと" and sname in OUTING and a.get("home_only") and not ui.get("move_on"):
            bad.append((sname, pid, name, "お出かけ先なのに家でのことが押せる", ""))
        if kind == "誰かと" and sname in MOVING and not (engine.App.moving_ok(a) or ui.get("move_on")):
            bad.append((sname, pid, name, "移動中なのに押せる", ""))
        if kind == "一人で" and sname in OUTING + ("visit", "stay") and pid not in S.OUT_WITH_OK:
            bad.append((sname, pid, name, "誰かと出かけている途中なのに一人のことが押せる", ""))
        if kind == "ゲーム" and sname in APART:
            bad.append((sname, pid, name, "離れているのにゲームが押せる", ""))
    return bad


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    base = tempfile.mkdtemp(prefix="kurashi_matrix_")
    bad = []
    n_checked = 0
    sched = engine.App.scheduled_scene
    try:
        store.DATA = os.path.join(base, "w")
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("突き合わせ")
        cid = app.settings["active_character"]
        engine.App.scheduled_scene = lambda self, c, d: dict(sched(self, c, d), **dict({"away": False, "busy": False, "asleep": False}, **FORCE))
        snap0 = os.path.join(base, "snap0")
        shutil.copytree(store.DATA, snap0)
        for sname, fn in STATES:
            if only and only not in sname:
                continue
            FORCE.clear()
            CLK["dt"] = getattr(fn, "clock", None)
            shutil.rmtree(store.DATA)
            shutil.copytree(snap0, store.DATA)
            random.seed(1)
            app = engine.App()
            fn(app, cid)
            app.save_state(cid)
            app.life.save_player()
            snap = os.path.join(base, "snap_" + sname)
            shutil.copytree(store.DATA, snap)
            probes = person_probes(app, cid) + solo_probes(app, cid) + game_probes(app, cid) + map_probes(app, cid) + phone_probes(app, cid)
            bad += rules(sname, probes)
            counts = {}
            for kind, pid, name, ok, why, run, a, ui in probes:
                shutil.rmtree(store.DATA)
                shutil.copytree(snap, store.DATA)
                random.seed(2)
                app2 = engine.App()
                err = None
                try:
                    r = run(app2)
                    if not isinstance(r, dict) or not any(r.get(k) for k in ("entry", "job", "started", "done", "label", "refused", "act")):
                        err = "（記録なし）"
                except ValueError as e:
                    err = str(e)
                except Exception as e:  # noqa: BLE001
                    bad.append((sname, pid, name, "%s: 例外" % kind, "%s: %s" % (type(e).__name__, e)))
                    continue
                n_checked += 1
                counts[kind] = counts.get(kind, 0) + 1
                if err and any(w in err for w in INPUT_ONLY):
                    continue
                if ok and err:
                    bad.append((sname, pid, name, "%s: 押せるのにできない" % kind, err))
                elif not ok and not err:
                    bad.append((sname, pid, name, "%s: 押せないのにできた" % kind, why))
            print("%s: %s" % (sname, " / ".join("%s %d" % kv for kv in counts.items())), flush=True)
    finally:
        CLK["dt"] = None
        engine.App.scheduled_scene = sched
        shutil.rmtree(base, ignore_errors=True)
    for b in bad:
        print("  ✗ [%s] %s（%s）: %s — %s" % b)
    print("確かめた組み合わせ %d / 食い違い %d" % (n_checked, len(bad)))
    assert not bad
    print("ALL OK")


if __name__ == "__main__":
    main()
