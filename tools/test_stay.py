"""お泊り (core/stay.py): 夜に聞く・受けるかは仲と性格しだい・相手から言い出す・泊まると朝まで一緒・寝ても別れない・
相手も寝る時間には寝ている・添い寝は泊まっていて親密なときだけ・あなたの家に泊める・朝になれば別れる (一時データ, 画像生成なし).

    python tools/test_stay.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(4)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("お泊り")
        B, S = app.bonds, app.stay
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        night = (today + timedelta(hours=23)).timestamp()
        noon = (today + timedelta(hours=13)).timestamp()
        B.set_stage(cid, "visit", night - 86400 * 40)
        close = dict(affection=85, trust=80, mood=65)

        def fresh(mode="visit", t=night, **params):
            if B.with_rec():
                B.end(go_home=False)
            st["params"].update(params or close)
            st["override"] = None
            B.start(cid, mode, t - 3600)
            w = B.with_rec()
            w["until"] = t + 3600
            return w

        # ---- 1. 受ける見込み: 仲が深いほど. 慎重な性格ほど低い. 昼は聞けない
        w = fresh()
        hi = S.chance(char, st, w, night)
        st["params"].update(affection=70, trust=62)
        lo = S.chance(char, st, w, night)
        careful = S.chance(dict(char, persona_id="kedakai"), st, w, night)
        print("受ける見込み: 親しい %.2f / まだ浅い %.2f (気高い %.2f)" % (hi, lo, careful))
        assert hi > lo + 0.3 and careful < lo and hi <= 0.9
        try:
            S.ask(cid, noon)
            raise AssertionError("昼に聞けた")
        except ValueError:
            pass

        # ---- 2. 聞く → 受けてくれる (断られることもある). 一晩に一度だけ
        res = []
        for _ in range(40):
            fresh()
            r = S.ask(cid, night)
            res.append(r["stay"])
            if r["stay"]:
                ok = r
        assert any(res) and not all(res), res
        print("泊まっていい？ (親しい相手で %d/40 受けてくれた): %s" % (sum(res), ok["entry"]["text"]))
        try:
            S.ask(cid, night)
            raise AssertionError("二度聞けた")
        except ValueError:
            pass

        # ---- 3. 泊まる: 朝 9:30 まで一緒. 寝ても別れない. 相手も寝る時間には寝ている
        while True:
            fresh()
            if S.ask(cid, night)["stay"]:
                break
        w = B.with_rec()
        assert datetime.fromtimestamp(w["until"]).hour == 9 and w["until"] > night
        app.phase_at = lambda dt: {"id": "night", "label": "夜", "pos": "", "neg": ""}
        app.act("go_sleep", cid)
        del app.phase_at
        assert B.mode(cid) == "visit" and app.presence.rec()["mode"] == "sleep", "寝ても別れない"
        app.presence.declare("none", night)
        s3 = app.athome.host_scene(char, {}, 0) or S.scene(char, {"asleep": True, "label": "就寝中"}, night + 4 * 3600)
        assert s3["asleep"] and s3["location"] == "自宅", s3
        print("泊まっている: 朝 %s まで・寝ても別れない・夜中の相手は %s" % (datetime.fromtimestamp(w["until"]).strftime("%H:%M"), s3["label"]))

        # ---- 4. 添い寝: 泊まっていて親密なときだけ
        sl = app.action("sleep_together")
        assert app.guest_ng(sl, cid) is None
        st["params"].update(affection=70)
        assert "別々" in app.guest_ng(sl, cid)
        st["params"].update(close)
        fresh()
        assert "泊まっていない" in app.guest_ng(sl, cid)
        print("添い寝: 泊まっていて親密なら / 親密でなければ別々 / 泊まっていなければしない: OK")

        # ---- 5. 相手から言い出す (22 時過ぎに一度だけ) → 答える
        got = None
        for _ in range(60):
            fresh()
            got = S.live(cid, night)
            assert S.live(cid, night + 600) is None, "一度だけ"
            if got:
                break
        assert got and S.view(cid, night)["offered"], "親しければ, いつかは言い出す"
        print("相手から:", got["text"])
        S.answer(cid, True, night)
        assert S.staying(cid)

        # ---- 6. あなたの家に泊める: 招いた場面から, 泊まっている場面へ
        while True:
            fresh("guest")
            st["override"] = {"activity": "guest", "label": "遊びに来ている", "until": night + 3600}
            r = S.ask(cid, night)
            if r["stay"]:
                break
        assert st["override"] is None
        s6 = S.scene(char, {"asleep": False, "label": "x"}, night + 60)
        print("あなたの家に泊める:", r["entry"]["text"], "/", s6["label"], s6["location"])
        assert s6["location"] == "あなたの家" and "泊まり" in s6["label"]

        # ---- 7. 朝になれば別れる
        B.sync(cid, st, B.with_rec()["until"] + 1)
        assert not B.with_rec()
        print("朝になって帰った: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
