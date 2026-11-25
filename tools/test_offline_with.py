"""誰かと一緒にいるまま画面を閉じた (core/outdoor.py check_gap → offline.simulate の lead) と, 閉じていた間の仕事の早退 (offline._work).

- 相手の家に泊まったまま閉じた: 朝, 仕事に出る時刻まで相手の家にいて, そこから職場へ. 開いた時刻に改めて相手の家から帰らない (運賃なし)
- 泊まっていて, 朝より前に開いた: まだ一緒 (まとめは作らない)
- 泊まらずに相手の家にいた: いる時間の終わりまで一緒. 家に泊めた: 相手が帰ってから, 家から出勤
- 外で会っていた: 閉じた時刻にそこから帰った (開いた時刻に帰り道を組まない)
- 早退: 元気なときのまれな早退は「急な用事」で, その日の残りの勤めはふだんどおり. 体調が悪いときは「体調がすぐれず」でその日は休む
(一時データ, 画像生成なし. 移動は本物の経路で)

    python tools/test_offline_with.py
"""
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from core import places as places_mod  # noqa: E402


def main():
    random.seed(7)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False, "offline": {"enabled": True}})
        app.create_world("一緒に閉じる")
        B, S, L, O = app.bonds, app.stay, app.life, app.outdoor
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        d = datetime.now().replace(hour=23, minute=0, second=0, microsecond=0) - timedelta(days=2)
        while (d + timedelta(days=1)).weekday() > 4:          # 翌日が平日 (行動パターンで 9:00 から仕事)
            d -= timedelta(days=1)
        night = d.timestamp()
        nine = (d + timedelta(hours=10)).timestamp()
        noon1 = (d + timedelta(hours=14)).timestamp()
        B.set_stage(cid, "visit", night - 86400 * 40)

        def close_with(mode, stay=True, until=None):
            if B.with_rec():
                B.end(go_home=False)
            L.player_state().pop("offline_report", None)
            p = app.presence.rec()
            p["mode"], p["pos"] = "none", places_mod.HOME_ME
            p.pop("travel", None)
            st["override"] = None
            B.start(cid, mode, night - 3600)
            w = B.with_rec()
            if stay:
                S._begin(w, char, night)
            elif until:
                w["until"] = until
            p["beat"] = night
            L.player_state()["last_tick"] = night
            return w

        def fares_after(t):
            return [x for x in app.kakeibo.rec()["raw"] if x.get("c") == "transport" and x["t"] >= t and "あなたの家" in str(x.get("n"))]

        # ---- 1. 相手の家に泊まったまま閉じて, 翌日の昼に開いた
        close_with("visit")
        g = O.check_gap(noon1)
        rep = L.player_state()["offline_report"]
        tl = rep["timeline"]
        assert g and g.get("report") and B.with_rec() is None, (g, B.with_rec())
        assert tl[0]["do"] == "with" and "泊まった" in tl[0]["text"] and tl[0]["t"] == night, tl[0]
        assert tl[0]["end"] == nine, "仕事に出る 9:00 まで相手の家に (%s)" % datetime.fromtimestamp(tl[0]["end"])
        go = next(x for x in tl if x["do"] == "move")
        assert go["t"] == nine and go["text"].startswith(app.places.label("home:" + cid) + "から"), go
        assert any(x["do"] == "work" for x in tl) and rep["wage"] > 0
        assert not fares_after(noon1 - 1), "開いた時刻に相手の家から帰っていない: %s" % fares_after(noon1 - 1)
        assert rep["from"] == night and rep["stamina"][1] >= rep["stamina"][0] - 30
        print("泊まって閉じた: %s / %s / 給料 %s円" % (tl[0]["text"], go["text"], format(rep["wage"], ",")))

        # ---- 2. 泊まっていて, 朝より前 (夜中の 2 時) に開いた: まだ一緒
        close_with("visit")
        assert O.check_gap(night + 3 * 3600) is None and B.with_rec() and B.with_rec().get("stay")
        assert L.player_state().get("offline_report") is None
        print("夜中に開いた: まだ泊まっている")

        # ---- 3. 泊まらずに相手の家にいて閉じた (いる時間は 0:30 まで)
        close_with("visit", stay=False, until=night + 5400)
        O.check_gap(noon1)
        tl = L.player_state()["offline_report"]["timeline"]
        assert tl[0]["do"] == "with" and "家にいた" in tl[0]["text"] and tl[0]["end"] == night + 5400, tl[0]
        assert tl[1]["do"] == "move" and tl[1]["t"] == night + 5400 and "から家へ" in tl[1]["text"], tl[1]
        assert B.with_rec() is None and not fares_after(noon1 - 1)
        print("泊まらずにいた: %s → %s" % (tl[0]["text"], tl[1]["text"]))

        # ---- 4. 家に泊めた: 相手が帰って (9:00), 家から出勤
        close_with("guest")
        O.check_gap(noon1)
        tl = L.player_state()["offline_report"]["timeline"]
        assert tl[0]["do"] == "with" and "泊まっていった" in tl[0]["text"] and tl[0]["end"] == nine, tl[0]
        go = next(x for x in tl if x["do"] == "move")
        assert go["t"] == nine and not go["text"].startswith(app.places.label("home:" + cid)), go
        assert B.with_rec() is None
        print("家に泊めた: %s / %s" % (tl[0]["text"], go["text"]))

        # ---- 5. 外で会っていて閉じた: 閉じた時刻に, そこから帰った
        if B.with_rec():
            B.end(go_home=False)
        L.player_state().pop("offline_report", None)
        p = app.presence.rec()
        p["mode"], p["pos"] = "none", places_mod.HOME_ME
        B.start(cid, "meet", night - 3600)
        B.with_rec()["place"] = "cafe"
        st["override"] = {"outing": True, "until": night + 3600, "place": "cafe", "activity": "outing"}
        p["beat"] = night
        O.check_gap(noon1)
        tl = L.player_state()["offline_report"]["timeline"]
        assert B.with_rec() is None and app.presence.rec().get("mode") == "none"
        assert tl[0]["do"] == "move" and tl[0]["t"] == night and tl[0]["text"].startswith(app.places.label("cafe") + "から家へ"), tl[0]
        assert not fares_after(noon1 - 1)
        print("外で会っていた: %s" % tl[0]["text"])

        # ---- 6. 早退: 元気なときは急な用事 (その日はふだんどおり) / 体調が悪いときは体調で (その日は休む)
        orig = random.random
        try:
            random.random = lambda: 0.02
            hl = app.body.rec()["health"]
            hl["level"] = 0
            w = app.offline._work(nine, nine + 3 * 3600, 100)
            assert "急な用事ができて、途中で抜けた" in w["notes"] and not w["sick"] and w["end"] < nine + 3 * 3600, w
            hl["level"] = 1
            w2 = app.offline._work(nine, nine + 3 * 3600, 100)
            assert "体調がすぐれず、早退した" in w2["notes"] and w2["sick"], w2
            hl["level"] = 0
            w3 = app.offline._work(nine, nine + 3 * 3600, 30)          # 疲れているときも体調で
            assert w3["sick"], w3
            random.random = lambda: 0.5
            w4 = app.offline._work(nine, nine + 3 * 3600, 100)
            assert not any("早退" in n or "抜けた" in n for n in w4["notes"]), w4
        finally:
            random.random = orig
        print("早退: 元気 %s / 体調 %s" % (w["notes"], w2["notes"]))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
