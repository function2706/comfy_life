"""ふれあい方を増やす (S57. defaults/actions.json の touch を持つ行動・core/engine.py の touch_feel / touch_ng・
core/wardrobe.py の accept の bonus・defaults/approaches.json の arm_link / lap_wish).

段が高いものほど仲が浅いと断られる・外 / 人前では控えられる・続けると嫌がる・必ず通る道が無い・
できる場所 (家の中だけ / 外だけ / 寝ていても) の総当たり・18 歳未満にはキスをしない・反応の選ばれ方と効き目・セリフの鍵.

    python tools/test_touch.py
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
from core import cond, engine, keys, store  # noqa: E402

NEW = ("lean_close", "shoulder_rub", "back_rub", "arm_in_arm", "touch_hair", "tickle", "touch_cheek", "pull_close",
       "lap_give", "lap_rest", "kiss")
IN_ONLY = ("shoulder_rub", "tickle", "lap_give", "lap_rest")
OUT_ONLY = ("arm_in_arm",)
SLEEP_OK = ("lean_close", "touch_hair", "touch_cheek")


def with_mode(app, cid, mode):
    app.bonds.wrec()["with"] = {"cid": cid, "mode": mode, "t": time.time()} if mode else None


def main():
    random.seed(57)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        cid = app.settings["active_character"]
        char = app.chars[cid]
        st = app.state(cid)
        A = {a["id"]: a for a in app.actions}

        # ---- 1. 定義: 11 個そろう. 受け入れの段・反応の鍵 (性格プリセットの差し替え先) が揃っている
        for aid in NEW:
            a = A[aid]
            assert a["category"] == "ふれあい" and a["skill"] == "touch" and a.get("with_player"), aid
            assert 1 <= a["touch"]["bold"] <= 2.5, aid
            ks = keys.line_keys(a["reactions"])
            assert len(set(ks)) == len(ks), (aid, ks)
            assert {"default", "eager", "reluctant", "refuse", "angry"} <= set(ks), (aid, ks)
            for r in a["reactions"]:
                if r["key"] in ("refuse", "angry", "too_much"):
                    assert r.get("override"), (aid, r["key"])
            assert ("asleep" in ks) == (aid in SLEEP_OK), aid
        assert A["kiss"]["touch"].get("adult") and not any(A[x]["touch"].get("adult") for x in NEW if x != "kiss")
        assert A["tickle"]["touch"].get("silly") == 1
        ak = keys.all_keys(app.actions, [], app.approaches)
        for k in ("kiss.refuse", "lean_close.asleep", "tickle.too_much", "ap.arm_link.call", "ap.lap_wish.accept"):
            assert k in ak, k
        print("定義: OK (11 個・反応の鍵)")

        # ---- 2. できる場所の総当たり: when を ctx で (外か・寝ているか・離れているか・手が離せないか)
        for aid in NEW:
            for outside in (True, False):
                for asleep in (True, False):
                    for busy in (True, False):
                        for away in (True, False):
                            c = {"outside": outside, "asleep": asleep, "busy": busy, "away": away}
                            ok = cond.check(A[aid]["when"], c)
                            want = not busy and not away and (asleep is False or aid in SLEEP_OK) \
                                and not (outside and aid in IN_ONLY) and not (not outside and aid in OUT_ONLY)
                            assert ok == want, (aid, c, ok)
        assert app.cond_why("outside=false", {"outside": True}) == "家の中でのことです（外ではできません）"
        assert app.cond_why("outside=true", {"outside": False}) == "外にいるときにすることです"
        print("できる場所: OK (家の中だけ %s / 外だけ %s / 寝ていても %s)" % (len(IN_ONLY), len(OUT_ONLY), len(SLEEP_OK)))

        # ---- 3. 受け入れ: 段が高いほど・外ほど・人前ほど断られる. 仲が深いほど通る. 必ず通る道は無い
        app.bonds.set_stage(cid, "visit")
        with_mode(app, cid, "guest")

        def refused(aid, aff, trust=None, outside=False, others=False, n=400, feel=""):
            bad = 0
            orig = app.bonds.company
            if others:
                app.bonds.company = lambda now: [cid, "x"]
            try:
                for _ in range(n):
                    st["touch_asks"] = []
                    app.set_params({"affection": aff, "trust": aff if trust is None else trust, "mood": 55}, cid)
                    ctx = {"outside": outside, "asleep": False, "feel": feel}
                    f = app.touch_feel(char, st, A[aid], ctx, time.time())
                    bad += f in ("refuse", "angry")
            finally:
                app.bonds.company = orig
            return bad

        rows = {}
        for aid in ("lean_close", "touch_hair", "touch_cheek", "lap_give", "kiss"):
            rows[aid] = [refused(aid, aff) for aff in (30, 50, 70, 90)]
        print("  断った数 / 400 (好感度・信頼 30, 50, 70, 90):", rows)
        order = ("lean_close", "touch_hair", "touch_cheek", "lap_give", "kiss")
        for i in range(len(order) - 1):
            lo, hi = rows[order[i]], rows[order[i + 1]]
            assert sum(lo) < sum(hi), (order[i], order[i + 1], lo, hi)
        for aid, r in rows.items():
            assert r[0] >= r[-1], (aid, r)                       # 仲が深いほど通る
        assert rows["kiss"][0] >= 380, rows["kiss"]             # 仲が浅いうちのキスは, まず断られる
        assert rows["lean_close"][-1] <= 20, rows["lean_close"]   # 仲が深ければ, 肩を寄せるくらいはほぼ通る
        assert rows["kiss"][-1] > 0, "仲が深くてもキスが必ず通る道はない"
        # 外・人前
        for aid in ("touch_cheek", "kiss"):
            inn, out, crowd = refused(aid, 70), refused(aid, 70, outside=True), refused(aid, 70, outside=True, others=True)
            assert inn < out <= crowd, (aid, inn, out, crowd)
            print("  %s 好感度 70: 家 %d / 外 %d / 外で人前 %d" % (aid, inn, out, crowd))
        # 体感: 寒い日は受けやすい・暑い日は嫌がる (S59 の考えを受け入れの式に)
        c, n_, h = refused("touch_cheek", 55, feel="cold"), refused("touch_cheek", 55), refused("touch_cheek", 55, feel="hot")
        assert c <= n_ + 25 and n_ <= h + 25 and c < h, (c, n_, h)
        print("  頬 好感度 55: 寒い %d / ふつう %d / 暑い %d" % (c, n_, h))
        print("受け入れ: OK")

        # ---- 4. しつこさ: 断られても続けると怒る. ふれあいどうしで数える. 時間が経てば忘れる
        app.set_params({"affection": 20, "trust": 20, "mood": 40}, cid)
        st["touch_asks"] = []
        feels = [app.touch_feel(char, st, A["kiss"], {"outside": False, "asleep": False, "feel": ""}, time.time()) for _ in range(4)]
        assert feels[:2] == ["refuse", "refuse"] and feels[2:] == ["angry", "angry"], feels
        st["touch_asks"] = [dict(x, t=x["t"] - 3 * 3600) for x in st["touch_asks"]]
        assert app.touch_feel(char, st, A["kiss"], {"outside": False, "asleep": False, "feel": ""}, time.time()) == "refuse"
        assert not st.get("dress_asks") and not st.get("pose_asks"), "服・ポーズのしつこさとは別に数える"
        # 寝ていれば気づかない (断りもしない. 数えない)
        n0 = len(st["touch_asks"])
        assert app.touch_feel(char, st, A["touch_cheek"], {"outside": False, "asleep": True}, time.time()) == "sleep"
        assert len(st["touch_asks"]) == n0
        print("しつこさ: OK (断る → 怒る. 2 時間で忘れる. 寝ていれば数えない)")

        # ---- 5. 18 歳未満にはキスをしない (押せない理由・act でも止める). ほかのふれあいは年齢を問わない
        kid = dict(char, age=16)
        assert app.touch_ng(A["kiss"], kid) and not app.touch_ng(A["kiss"], char)
        assert all(app.touch_ng(A[x], kid) is None for x in NEW if x != "kiss")
        old = char.get("age")
        char["age"] = 16
        try:
            av = app.available(char, st, datetime.now())
            assert not av["kiss"]["ok"] and av["kiss"].get("why") == "18 歳未満のキャラにはできません", av["kiss"]
            try:
                app.act("kiss", cid)
                raise AssertionError("18 歳未満にキスができた")
            except ValueError as e:
                assert "18 歳未満" in str(e) or "今は" in str(e), e
        finally:
            if old is None:
                char.pop("age", None)
            else:
                char["age"] = old
        print("年齢: OK")

        # ---- 6. act で通しで: 断られれば基本の効き目は付かない / 受ければ付く. 反応の条件 touch_feel が効く
        orig_ctx, orig_tick = app.context, app.tick
        app.tick = lambda *a, **k: None
        app.context = lambda *a, **k: dict(orig_ctx(*a, **k), free=True, asleep=False, busy=False, away=False, outside=False)
        orig_tf = app.touch_feel
        seen = {}
        try:
            for want in ("eager", "shy", "reluctant", "refuse", "angry"):
                app.touch_feel = lambda *a, w=want: w
                for aid in NEW:
                    if aid in OUT_ONLY:
                        continue
                    st["cooldowns"] = {}
                    with_mode(app, cid, "guest")
                    app.set_params({"affection": 60, "trust": 60, "heart": 10, "shyness": 10, "mood": 70, "stress": 20,
                                    "loneliness": 30, "energy": 80}, cid)
                    try:
                        e = app.act(aid, cid)["entry"]
                    except ValueError as ex:
                        raise AssertionError((aid, want, str(ex)))
                    d = e.get("deltas") or {}
                    a = A[aid]
                    r = next(r for r in a["reactions"] if r["text"].replace("{call}", "") in (e.get("text") or "").replace(app.call_name(char) if hasattr(app, "call_name") else "", "")) \
                        if False else None
                    if want in ("refuse", "angry"):
                        assert d.get("heart", 0) <= 0 and d.get("affection", 0) <= 0, (aid, want, d)
                    else:
                        assert d.get("heart", 0) > 0 or d.get("stress", 0) < 0 or d.get("mood", 0) > 0 \
                            or d.get("loneliness", 0) < 0 or d.get("trust", 0) > 0, (aid, want, d)
                    seen[(aid, want)] = d
        finally:
            app.touch_feel = orig_tf
            app.context, app.tick = orig_ctx, orig_tick
        print("act: OK (%d 通り. 断る・怒るは効き目なし / 受ければ効く)" % len(seen))

        # 反応の選ばれ方: 寝ていれば寝顔, 怒るは断るより強い, くすぐりは続けると本気で嫌がる
        for aid in NEW:
            a = A[aid]
            base = {"asleep": False, "repeat": 0, "stress": 20, "mood": 60, "loneliness": 20, "energy": 80, "player_sick": 0}
            for f in ("eager", "shy", "reluctant", "refuse", "angry"):
                r = app.pick_reaction(a, dict(base, touch_feel=f))
                k = r.get("key")
                if f in ("refuse", "angry"):
                    assert k == f, (aid, f, k)
                elif f == "shy":
                    assert k == "default", (aid, f, k)
                else:
                    assert k == f, (aid, f, k)
            if aid in SLEEP_OK:
                assert app.pick_reaction(a, dict(base, asleep=True, touch_feel="sleep")).get("key") == "asleep"
        t = A["tickle"]
        assert app.pick_reaction(t, {"touch_feel": "eager", "repeat": 2}).get("key") == "too_much"
        assert app.pick_reaction(t, {"touch_feel": "angry", "repeat": 2}).get("key") == "angry"
        assert app.pick_reaction(A["back_rub"], {"touch_feel": "shy", "mood": 30, "stress": 20}).get("key") == "down"
        assert app.pick_reaction(A["back_rub"], {"touch_feel": "refuse", "mood": 30, "stress": 20}).get("key") == "refuse"
        print("反応の選ばれ方: OK")

        # ---- 7. 相手から: 腕を組んでくる (出先) / 膝枕してほしそう (家の中・疲れ). 応じればふれあいの重み (体感) が効く
        AP = {a["id"]: a for a in app.approaches}
        from core import presence
        for aid in ("arm_link", "lap_wish"):
            assert (AP[aid]["accept"] or {}).get("skill") == "touch"
            assert presence.feel_weight(AP[aid], {"feel": "cold"}) == 1.5
        for outing in (True, False):
            for outside in (True, False):
                for aff in (60, 75):
                    for energy in (20, 60):
                        for trust in (40, 60):
                            c = {"outing": outing, "outside": outside, "affection": aff, "energy": energy, "trust": trust, "mood": 60}
                            assert cond.check(AP["arm_link"]["when"], c) == (outing and aff >= 70)
                            assert cond.check(AP["lap_wish"]["when"], c) == (not outside and energy < 35 and aff >= 70 and trust >= 55)
        print("相手から: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
