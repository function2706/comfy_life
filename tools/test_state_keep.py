"""状態の重ねがけ (整合性): いろいろな状態で押せるものを 1 つずつ押し, 前から続いていた状態が, 押したことで消えていないかを見る.
test_state_matrix の状態と押すもの (誰かと・一人で・ゲーム・地図・電話) をそのまま使い, 状態をいくつか足す.
続いている状態: 泊まる約束・「今日はもう聞いた」・頼まれた手伝い (待っている / 最中)・招いた手伝い・看病の記録・
病気・言い争い・約束・一緒のお出かけ・一人の外出や作業・一緒にいる相手.
消えてよいもの (そのことを終える行動) は ENDS に書く. それ以外で消えたら食い違いとして落ちる.
以前の不具合: 泊まるのを受けてもらってから一緒に外へ出て戻ると, 泊まる約束が消えていた (core/bonds.py go_out).

    python tools/test_state_keep.py            # すべての状態
    python tools/test_state_keep.py stay       # 名前に stay を含む状態だけ
    python tools/test_state_keep.py --report   # 落とさずに, 消えたものを全部並べる (スクリーニング用)
"""
import os
import random
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import test_state_matrix as M  # noqa: E402  (時刻の固定など, 突き合わせと同じ前提)
from core import engine, geo as G, store  # noqa: E402


# ------------------------------------------------------------------ 足す状態
def s_stay_guest(app, cid):       # あなたの家に泊めている
    M.s_guest(app, cid)
    w = app.bonds.with_rec()
    w["stay"], w["stay_asked"] = {"t": time.time()}, True
    app.bonds.save()


def s_stay_asked(app, cid):       # 相手の家で, 泊まる約束をした (聞いて受けてもらった)
    M.s_visit(app, cid)
    w = app.bonds.with_rec()
    w["stay"], w["stay_asked"] = {"t": time.time()}, True
    w["until"] = app.stay.morning(time.time())
    app.bonds.save()


def s_stay_out(app, cid):         # 相手の家に泊まる約束をして, 二人で水族館に出かけて着いている
    s_stay_asked(app, cid)
    st = app.state(cid)
    G.INSTANT = False
    try:
        app.act("aquarium", cid)
    finally:
        G.INSTANT = True
    ov = st["override"]
    M._shift(ov, ov["arr"] - time.time() + 1)
    ov["until"] = max(ov["until"], time.time() + 3600)
    if ov.get("leave"):
        d = max(ov["leave"], time.time() + 1800) - ov["leave"]
        for tr in ov["trips"]:
            if tr["dir"] == "home":
                M._shift({"trips": [tr]}, -d)
        ov["leave"] += d
    ov.pop("arrive", None)
    app.save_state(cid)
    assert app.bonds.stay_back(cid) == "visit", app.bonds.with_rec()


def s_favor_wait(app, cid):       # 相手の家に, 頼まれた手伝いをしに来て, まだ始めていない
    M._base(app, cid, "visit")
    now = time.time()
    f = {"id": "fw", "cid": cid, "kind": "clean", "label": "掃除の手伝い", "h": 1.0, "tire": 5, "t": now, "until": now + 3 * 86400}
    app.earn.favors().append(f)
    app.life.save_player()
    app.athome.favor_arrive(cid, f, now)


def s_guest_help(app, cid):       # あなたの家に, 手伝いに来てもらって, まだ始めていない
    M.s_guest(app, cid)
    w = app.bonds.with_rec()
    w["help"] = {"kind": "clean", "label": "掃除の手伝い", "h": 1.0}
    app.bonds.save()


def s_care_visit(app, cid):       # 風邪の相手の家に看病に来ている
    st = M._base(app, cid, "visit")
    st["ill"] = {"t": time.time() - 3600, "until": time.time() + 86400, "level": 2}
    app.set_params({"health": 40}, cid)
    app.save_state(cid)
    app.bonds.start(cid, "visit")
    app.bonds.with_rec()["care"] = {"want": [], "given": [], "nursed": False}
    app.bonds.save()


EXTRA = [("stay_guest", s_stay_guest), ("stay_asked", s_stay_asked), ("stay_out", s_stay_out),
         ("favor_wait", s_favor_wait), ("guest_help", s_guest_help), ("care_visit", s_care_visit)]
STATES = M.STATES + EXTRA


# ------------------------------------------------------------------ 続いている状態
def lasting(app, cid):
    B = app.bonds
    w = B.with_rec() or {}
    b = w.get("base") or {}
    st = app.state(cid)
    now = time.time()
    p = app.presence.rec()
    out = {}
    if w.get("cid"):
        out["一緒にいる"] = w["cid"]
    if B.stay_home(cid, now):
        out["泊まる約束"] = B.stay_home(cid, now)
    if w.get("stay_asked") or b.get("stay_asked"):
        out["今日はもう聞いた"] = True
    fid = w.get("favor") or b.get("favor")
    if fid and app.earn.favor(fid):
        out["頼まれた手伝い"] = fid
    if w.get("helping"):
        out["手伝いの最中"] = True
    if w.get("help") or b.get("help"):
        out["招いた手伝い"] = True
    if w.get("care") or b.get("care"):
        out["看病の記録"] = True
    if st.get("ill"):
        out["病気"] = True
    if app.quarrel.active(st, now):
        out["言い争い"] = True
    for x in app.appoint.all():
        if x.get("status") in ("set", "offered") and x["t"] > now - 3600:
            out["約束:" + x["id"]] = True
    if app.outing_now(now)[0]:
        out["一緒のお出かけ"] = True
    if p.get("mode") not in (None, "none"):
        out["あなた:" + p["mode"]] = True
    if app.geo.moving(now):
        out["移動中"] = True
    if app.phonetalk.view(now):
        out["通話中"] = True
    if app.facetalk.view(now):
        out["会って話している"] = True
    if st.get("game"):
        out["ゲームの途中"] = True
    fr = app.forfeit.rec(st)
    for i, x in enumerate(fr["owed"]):
        out["罰の約束:%d" % i] = True
    ov = st.get("override") or {}
    if ov.get("until", 0) > now:
        out["相手の過ごし方:" + str(ov.get("activity") or ov.get("from_action"))] = True
    return out


def ends(app, cid):
    """終わる時刻が分かっている続く状態: その時刻より前に, 時間が進んだだけで消えたら食い違い."""
    B = app.bonds
    w = B.with_rec() or {}
    st = app.state(cid)
    out = {}
    if w.get("stay"):
        out["泊まる約束"] = float(w.get("until", 0))
    elif B.stay_back(cid):
        out["泊まる約束"] = float(w["base"]["night_end"])
    if w.get("mode") in ("visit", "guest"):
        out["一緒にいる"] = float(w.get("until", 0))
    elif w.get("mode") == "meet":
        out["一緒にいる"] = float((st.get("override") or {}).get("until", 0))
    for x in app.appoint.all():
        if x.get("status") in ("set", "offered"):
            out["約束:" + x["id"]] = float(x["t"]) - 600
    return out


def time_probe(d):
    def run(app2, d=d):
        real = time.time
        time.time = lambda: real() + d
        try:
            app2.tick(app2.settings["active_character"])
        finally:
            time.time = real
        return {"done": True}
    return run


# 消えてよい (その行動がそのことを終える). (状態の名前の頭 / "*", 続いている状態の頭, 行動 id の集合)
LEAVE = {"leave_visit", "see_off", "go_home", "end_activity", "visit_end"}
ENDS = [
    ("*", "一緒にいる", LEAVE),
    ("*", "一緒のお出かけ", LEAVE | {"outing_cancel"}),
    ("*", "あなた:", set()),     # あなたの予定は「一人で」の行動・誰かとのことで切り替わる (下の solo/other で個別に許す)
]


def allowed(sname, key, pid, kind):
    if key.startswith("あなた:") and (kind == "一人で" or kind == "誰かと" or kind == "ゲーム"):
        return True           # 一人のこと・誰かとのことを始めれば, いまのあなたの予定は終わる (相手を待つ約束は別)
    if key == "会って話している" and kind != "時間":
        return True           # ほかのことを始めれば, 話は終わる (core/facetalk.py の決まり)
    if key.startswith("相手の過ごし方:") and kind in ("誰かと", "ゲーム", "地図"):
        return True           # 相手と次のことをすれば, 一時的な過ごし方は置き換わる (時間が進んだだけで消えるのは見る)
    for s, k, ids in ENDS:
        if (s == "*" or sname.startswith(s)) and key.startswith(k) and pid in ids:
            return True
    return False


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    report = "--report" in sys.argv
    only = args[0] if args else None
    base = tempfile.mkdtemp(prefix="kurashi_keep_")
    found = []
    n = 0
    sched = engine.App.scheduled_scene
    try:
        store.DATA = os.path.join(base, "w")
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("重ねがけ")
        cid = app.settings["active_character"]
        engine.App.scheduled_scene = lambda self, c, d: dict(sched(self, c, d), **dict({"away": False, "busy": False, "asleep": False}, **M.FORCE))
        snap0 = os.path.join(base, "snap0")
        shutil.copytree(store.DATA, snap0)
        for sname, fn in STATES:
            if only and only not in sname:
                continue
            M.FORCE.clear()
            M.CLK["dt"] = getattr(fn, "clock", None)
            shutil.rmtree(store.DATA)
            shutil.copytree(snap0, store.DATA)
            random.seed(1)
            app = engine.App()
            fn(app, cid)
            app.save_state(cid)
            app.life.save_player()
            snap = os.path.join(base, "snap_" + sname)
            shutil.copytree(store.DATA, snap)
            before = lasting(app, cid)
            probes = M.person_probes(app, cid) + M.solo_probes(app, cid) + M.game_probes(app, cid) + M.map_probes(app, cid) \
                + M.phone_probes(app, cid)

            probes.append(("時間", "_tick", "時間が進む (いま)", True, "", time_probe(0), {}, {}))
            ex = ends(app, cid)
            TIMES = (600, 3 * 3600)
            for d in TIMES:
                probes.append(("時間", "_t%d" % d, "%d 分たつ" % (d // 60), True, "", time_probe(d), {}, {"d": d}))
            k = 0
            for kind, pid, name, ok, why, run, a, ui in probes:
                if not ok:
                    continue
                shutil.rmtree(store.DATA)
                shutil.copytree(snap, store.DATA)
                random.seed(2)
                app2 = engine.App()
                try:
                    run(app2)
                except ValueError:
                    continue
                except Exception as e:  # noqa: BLE001
                    found.append((sname, pid, name, "例外", "%s: %s" % (type(e).__name__, e)))
                    continue
                n += 1
                k += 1
                if kind == "時間" and ui.get("d"):
                    real = time.time
                    time.time = lambda: real() + ui["d"]
                    try:
                        after = lasting(app2, cid)
                    finally:
                        time.time = real
                    t1 = time.time() + ui["d"] + 60
                    for key, te in ex.items():
                        if key not in after and te > t1:
                            found.append((sname, pid, name, "終わる前に消えた: %s (あと %d 分あったはず)" % (key, (te - t1) // 60), kind))
                    continue
                after = lasting(app2, cid)
                for key in before:
                    if key in after or allowed(sname, key, pid, kind):
                        continue
                    found.append((sname, pid, name, "消えた: " + key, kind))
            print("%s: %d 件 (続いている: %s)" % (sname, k, ", ".join(before) or "なし"), flush=True)
    finally:
        M.CLK["dt"] = None
        engine.App.scheduled_scene = sched
        shutil.rmtree(base, ignore_errors=True)
    for f in found:
        print("  ✗ [%s] %s（%s）: %s — %s" % f)
    print("確かめた組み合わせ %d / 消えた %d" % (n, len(found)))
    if not report:
        assert not found
    print("ALL OK" if not found else "（--report: 落とさずに終える）")


if __name__ == "__main__":
    main()
