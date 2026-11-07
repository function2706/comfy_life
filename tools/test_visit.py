"""相手の家にいるとき (core/visit.py): お客の立場でできること・頼まれごとの手伝い (一時データ, 画像生成なし).
- 台所・お風呂・寝かしつけなど家主のすることはできない. 話す・ふれあう・一緒に遊ぶ・帰るはできる
- 頼まれごとの約束で着いても, すぐには始まらない. 「始める」で取りかかる
- 手伝いの最中: あなたは相手の家にいるまま (職場・仕事中にならない). 相手は自宅で手伝ってもらっている. コマンドは話すくらい
- ひと休みで終わりが延びる (回数に限り). 早く切り上げると「途中で帰った」扱い. 終わっても相手の家にいる

    python tools/test_visit.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import earn as EA, engine, store  # noqa: E402
from core import parting as _parting  # noqa: E402
_parting.FIXED = "ok"      # 別れぎわは必ず応じる (引き止めは test_parting で)
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(3)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("相手の家")
        B, E, V = app.bonds, app.earn, app.athome
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        B.set_stage(cid, "visit")
        st["params"].update(affection=70, trust=70, mood=60, energy=80, health=90)
        now = time.time()

        def av(t=None):
            return app.available(char, st, datetime.fromtimestamp(t or time.time()))

        def raises(aid):
            try:
                app.act(aid, cid)
            except ValueError as e:
                return str(e)
            return None

        # ---- 1. お客の立場: 家主のすることはできない
        B.start(cid, "visit", now)
        a = av()
        for aid in ("cook", "bath", "tuck_in", "clean", "sleep_together"):
            assert not a[aid]["ok"], aid
        assert a["talk"]["ok"] and a["leave_visit"]["ok"]
        assert "お客" in (raises("cook") or ""), raises("cook")
        st["params"]["health"] = 50
        assert av()["nurse"]["ok"], "具合が悪ければ看病はできる"
        st["params"]["health"] = 90
        assert app.person_view(cid)["visit"]["name"] == char.get("name")
        B.end(go_home=False)
        print("お客の立場 (料理・お風呂・掃除・添い寝はしない / 話す・帰る・看病はできる): OK")

        # ---- 2. 頼まれごとで着いた → 始める → 最中の様子
        k, name, h, tire = EA.FAVOR_KIND["clean"]
        f = {"id": "fv1", "cid": cid, "kind": "clean", "label": name, "h": h, "tire": tire, "t": now, "until": now + 86400}
        E.favors().append(f)
        V.favor_arrive(cid, f, now)
        assert B.mode(cid) == "visit" and V.favor_pending(cid) is f and not V.helping(cid)
        assert app.person_view(cid)["visit"]["favor"]["label"] == name
        for k in range(9):                      # 予定では出かける時刻でも, 来ているあいだは家にいる
            s0 = app.scene_at(char, st, datetime.fromtimestamp(now + k * 1800))
            assert s0["location"] == "自宅" and not s0["away"] and not s0["asleep"], (k, s0["label"], B.with_rec(), now, st.get("override"))
        V.start(cid, now)
        sc = app.scene_at(char, st, datetime.fromtimestamp(now + 60))
        assert sc["location"] == "自宅" and "手伝ってもらっている" in sc["label"], sc
        assert app.outdoor.current(now + 60) is None, "職場にいることにならない"
        assert app.geo.where(now + 60) == "home:" + cid
        assert app.presence.rec()["mode"] == "none"
        a = av(now + 60)
        assert a["talk"]["ok"] and not a["game"]["ok"] and not a["leave_visit"]["ok"]
        assert "手伝いの最中" in (raises("game") or "")
        print("始める (相手は自宅で手伝ってもらっている・あなたは相手の家・職場にならない・話すくらい): OK", sc["label"])

        # ---- 3. ひと休み (終わりが延びる・回数に限り) → 時間が来て終わる. 終わっても相手の家にいる
        u0 = V.helping(cid)["until"]
        V.rest(cid, now + 600)
        V.rest(cid, now + 1200)
        assert V.helping(cid)["until"] == u0 + 2 * 15 * 60
        try:
            V.rest(cid, now + 1800)
            raise AssertionError("何度でも休めた")
        except ValueError:
            pass
        assert V.live(cid, u0) is None, "延びた分はまだ終わらない"
        r = V.live(cid, u0 + 30 * 60)
        assert r and "終えた" in r["text"] and f not in E.favors() and B.mode(cid) == "visit" and not V.helping(cid), r
        assert (st.get("override") or {}).get("activity") != "favor"
        print("ひと休み・時間が来て終わる (家にはまだいる):", r["text"])
        B.end(go_home=False)

        # ---- 4. 早く切り上げる: 途中で帰った扱い (信頼・機嫌 -1)
        f2 = dict(f, id="fv2")
        E.favors().append(f2)
        V.favor_arrive(cid, f2, now)
        V.start(cid, now)
        tr0 = st["params"]["trust"]
        r = V.stop(cid, now + 600)
        assert "途中" in r["text"] and st["params"]["trust"] < tr0 and B.mode(cid) == "visit", r
        print("早く切り上げる:", r["text"])

        # ---- 5. 画面を閉じていた間に終わりが過ぎた: tick で終わりの時刻で済ませる
        B.end(go_home=False)
        f3 = dict(f, id="fv3")
        E.favors().append(f3)
        V.favor_arrive(cid, f3, now)
        V.start(cid, now)
        app.tick(cid, now + (h + 0.2) * 3600)
        assert f3 not in E.favors() and not V.helping(cid)
        print("閉じていた間に終わった: OK")

        # ---- 6. 始めずに帰る: 手伝わずに帰ったことになる (信頼・機嫌 −1). 頼まれごとは一覧から外れる
        B.end(go_home=False)
        f4 = dict(f, id="fv4")
        E.favors().append(f4)
        V.favor_arrive(cid, f4, now)
        tr0 = st["params"]["trust"]
        B.end(go_home=False)
        last = [it for it in app.chat.load(cid)["items"] if "手伝わずに" in it.get("text", "")][-1]
        assert f4 not in E.favors() and st["params"]["trust"] < tr0 and "手伝わずに" in last["text"], last
        # 最中に帰る: そこで切り上げ
        f5 = dict(f, id="fv5")
        E.favors().append(f5)
        V.favor_arrive(cid, f5, now)
        V.start(cid, now)
        B.end(go_home=False)
        assert f5 not in E.favors() and not V.rec() and (st.get("override") or {}).get("activity") != "favor"
        print("始めずに帰る / 最中に帰る:", last["text"])
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
