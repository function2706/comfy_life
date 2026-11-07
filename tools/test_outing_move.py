"""相手と一緒にお出かけ中に, そのまま一緒に次の場所へ (engine.outing_move).
- 応じるかは関係 (間柄・好感度・依存度・献身度)・機嫌・性格 (話したがり) で決まり, 疲れていれば・夜遅ければ断る
- 応じれば, いまいる場所から一緒に移動して (一緒の移動), 着いたらその場所で過ごす
- 移動の途中・いまいる場所へは行けない (一時データ).

    python tools/test_outing_move.py
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
from core import engine, geo as G, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
G.INSTANT = False


def main():
    random.seed(6)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("次の場所")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "live")
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        st = app.state(cid)
        L = app.life

        def start():
            st["override"], st["cooldowns"], st["move_log"] = None, {}, []
            L.player_state()["money"] = 100000
            app.set_params({"affection": 80, "mood": 75, "energy": 80, "trust": 70}, cid)
            app.act("aquarium", cid)
            ov = st["override"]
            for tr in ov.get("trips") or []:          # 着いたことに (行きの移動を過去へ)
                if tr["dir"] == "go":
                    d = tr["arr"] - time.time() + 1
                    tr["t0"] -= d
                    tr["arr"] -= d
                    for lg in tr.get("legs") or []:
                        lg["t0"] -= d
                        lg["t1"] -= d
            ov["arr"] = time.time() - 1
            assert app.geo.where() == "aquarium" and not app.outing_trip(st, time.time())

        # ---- 1. 応じる: 水族館からカフェへ一緒に移動して, カフェで過ごす
        start()
        try:
            app.outing_move("aquarium")
            raise AssertionError("いまいる場所へ行けた")
        except ValueError:
            pass
        ok = None
        for _ in range(10):
            r = app.outing_move("cafe")
            if not r.get("refused"):
                ok = r
                break
            st["cooldowns"] = {}
        assert ok, "何度誘っても応じない"
        ov = st["override"]
        assert ov["place"] == "cafe" and ov["from_action"] == "cafe", ov
        trip = app.outing_trip(st, time.time())
        assert trip and trip["from"] == "aquarium" and trip["to"] == "cafe", trip
        try:
            app.outing_move("cafe")
            raise AssertionError("向かっている先へ行き先を変えられた")
        except ValueError as e:
            assert "向かって" in str(e)
        print("応じる: OK |", (ok.get("entry") or {}).get("text", "").split("\n")[0], "|", app.person_view(cid)["scene"]["label"])

        # ---- 1a. 出たときは「向かった」と移動の絵 (カフェの反応・絵は, 着いたときに). 移動中はまだカフェにいない
        e0 = ok["entry"]
        assert "向かった" in e0["text"] and "latte" not in e0["pos"] and ("walking" in e0["pos"] or "train" in e0["pos"]
                                                                       or "station" in e0["pos"] or "car" in e0["pos"]), (e0["text"], e0["pos"])
        assert ov.get("arrive") and ov["arrive"]["aid"] == "cafe"
        said = ov["arrive"]["text"]
        cur = app.outdoor.current(time.time())
        assert cur["moving"] and cur["place"] != "cafe" and cur["dest"] == "cafe" and app.body.here() is None, cur
        n0 = len(app.log(cid))
        app.tick(cid, time.time())
        assert len(app.log(cid)) == n0                         # まだ着いていない
        app.tick(cid, trip["arr"] + 1)                          # 着いた: カフェでの反応と絵
        e1 = app.log(cid)[-1]
        assert e1.get("arrived") and e1["action"] == "cafe" and e1["text"] == said, e1
        assert "向かった" not in e1["text"] and not st["override"].get("arrive") and abs(e1["t"] - trip["arr"]) < 1, e1
        assert not e0.get("money") and (e1.get("money") or {}) and any(v < 0 for v in e1["money"].values()), (e0.get("money"), e1.get("money"))   # カフェの費用は着いてから
        cur = app.outdoor.current(trip["arr"] + 1)
        assert not cur.get("moving") and cur["place"] == "cafe", cur
        print("出たとき・着いたとき: OK |", e0["text"].split("\n")[0], "→", e1["text"].split("\n")[0][:40])

        # ---- 1b. 「誰かと」の移動のコマンドから (分類は「移動」): お出かけ中も押せて, 一緒に次の場所へ
        start()
        av = app.person_view(cid)["available"]
        assert app.action("cafe")["category"] == "移動" and av["cafe"]["ok"] and av["cafe"]["move_on"], av["cafe"]
        assert not av["aquarium"]["ok"] and av["aquarium"]["why"] == "いまここにいます", av["aquarium"]
        r = None
        for _ in range(10):
            r = app.outing_move("park", None, "walk")
            if not r.get("refused"):
                break
            st["cooldowns"] = {}
        assert not r.get("refused") and st["override"]["place"] == "park" and st["override"]["from_action"] == "walk", st["override"]
        print("移動のコマンドから: OK | 散歩で公園へ")

        # ---- 1c. 移動の途中で行き先を変える: いまの地点から新しい行き先へ. 乗らなかった運賃・まだの帰りの運賃は戻る
        def to_cafe():
            start()
            for _ in range(20):
                st["move_log"] = []
                r = app.outing_move("cafe")
                if not r.get("refused"):
                    return app.outing_trip(st, time.time())
            raise AssertionError("カフェへ応じない")
        trip = to_cafe()
        st["move_log"] = []
        av = app.person_view(cid)["available"]
        assert av["walk"]["ok"] and av["walk"]["move_on"] and not av["cafe"]["ok"] and av["cafe"]["why"] == "いま向かっています", (av["walk"], av["cafe"])
        r = None
        for _ in range(20):
            m0, h0 = L.player_state()["money"], L.her_money(st)["a"]
            st["move_log"] = []
            r = app.outing_move("park", None, "walk")
            if not r.get("refused"):
                break
            assert "そのまま" in r["entry"]["text"] and app.outing_trip(st, time.time())["to"] == "cafe", r["entry"]["text"]
        assert not r.get("refused"), r
        t2 = app.outing_trip(st, time.time())
        ov = st["override"]
        assert ov["place"] == "park" and ov["arrive"]["aid"] == "walk" and (not t2 or t2["to"] == "park"), (ov["place"], t2)
        assert "行き先を変えて" in r["entry"]["text"], r["entry"]["text"]
        assert any("途中で行き先を変えた" in x.get("n", "") and x["a"] > 0 for x in app.kakeibo.rec()["raw"]), "運賃が戻っていない"
        print("移動の途中で行き先を変える: OK |", r["entry"]["text"].replace(chr(10), " "))

        # ---- 1d. 何度も変える・連れ回すと, うんざりされる (応じにくく, 機嫌も少し下がる)
        def change_rate(log_n):
            n, why = 0, {}
            for _ in range(40):
                to_cafe()
                st["move_log"] = [[time.time() - 600 * (i + 1), True] for i in range(log_n)]
                r = app.outing_move("park", None, "walk")
                n += 0 if r.get("refused") else 1
                if r.get("refused"):
                    w = r["entry"]["text"]
                    why[w[w.find("「"):w.find("」") + 1]] = 1
            return n, why
        fresh, _ = change_rate(0)
        tired_of, lines = change_rate(4)
        assert fresh > tired_of + 8, (fresh, tired_of)
        assert any("また変える" in w for w in lines), lines
        to_cafe()
        st["move_log"] = [[time.time() - 600 * (i + 1), True] for i in range(3)]
        m0 = st["params"]["mood"]
        r = app.outing_move("park", None, "walk")
        assert st["params"]["mood"] < m0 and ("あきれた" in r["entry"]["text"] or r.get("refused")), (m0, st["params"]["mood"], r["entry"]["text"])
        print("何度も変えると: OK | はじめて %d/40・4 回変えたあと %d/40 |" % (fresh, tired_of), " ".join(lines))

        # ---- 2. 疲れていれば断る
        start()
        app.set_params({"energy": 10}, cid)
        r = app.outing_move("cafe")
        assert r.get("refused") and "疲れ" in r["entry"]["text"], r
        print("疲れていれば: OK |", r["entry"]["text"].split("\n")[-1])

        # ---- 3. 関係・機嫌で応じやすさが変わる
        def rate(**params):
            n = 0
            for _ in range(60):
                start()
                app.set_params(params, cid)
                r = app.outing_move("cafe")
                n += 0 if r.get("refused") else 1
            return n
        hi = rate(affection=90, mood=85, energy=80)
        lo = rate(affection=30, mood=25, energy=80)
        assert hi > lo + 10, (hi, lo)
        print("関係・機嫌: OK | 仲よく機嫌がいい %d/60・仲が浅く不機嫌 %d/60" % (hi, lo))
        app.scheduled_scene = sched
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
