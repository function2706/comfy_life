"""「あなた」中心の作りの確認 (一時データ, 画像生成なし).
- いまそばにいる人 (company): 同居相手は, あなたも相手も家にいるときだけ. 外出中・仕事中は離れていて, 連絡はスマホ (時間差)
- 来客中は, 家にいる同居相手と二人がそばにいる. 寂しさが紛れるのは二人きりのときだけ
- 「誰かと」の相手 (target) はそばにいる人から. 誰もいなければ None (画面の with も None)
- 一人の行動 (戻る・仕事・内職・株) は誰にも告げずにでき, 記録はあなたの 1 本の時系列 (timeline) に並ぶ. 人で絞り込める
- 関係性: 最後に会った / 連絡した・渡してみて分かった好きなもの・本人から聞いた話. 相手の所持金は出さない

    python tools/test_company.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)     # 日曜の昼 (ひなは家で過ごしている)


def main():
    random.seed(5)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        B, P = app.bonds, app.presence
        now = time.time()
        P.rec()["beat"] = P.rec()["input"] = now

        # ---- 1. 家に一緒にいる同居相手がそばにいる. 「誰かと」の相手はその人
        assert B.living() == "hina" and B.company() == ["hina"], B.company()
        v = app.state_view()
        assert v["target"] == "hina" and v["with"]["name"] and [c["id"] for c in v["company"]] == ["hina"]
        assert "her_money" not in v["with"]["life"] and "her_money" not in v["you"], "相手の所持金は出さない"
        print("家で一緒:", v["with"]["bond"]["label"])

        # ---- 2. 一人で出かけたら, 同居相手とは離れている. メッセージは時間差, 戻れば家にいる
        r = app.solo.start("out", place="park")
        assert r["started"] == "out" and B.company() == [] and not B.together("hina")
        v = app.state_view()
        assert v["target"] is None and v["with"] is None and any(c["id"] == "hina" for c in v["contacts"])
        r = app.act("message", "hina")
        assert r.get("sent"), "外出中の同居相手へはメッセージ (時間差)"
        st = app.state("hina")
        assert st.get("last_contact"), "最後に連絡した"
        P.rec()["since"] -= 1800
        r = app.come_back()
        assert B.company() == ["hina"] and not r["entry"].get("mine"), r["entry"]
        assert st.get("last_met"), "戻ったら出迎え = 会った"
        print("外出 → 戻る:", r["entry"]["text"].split("\n")[0])

        # ---- 3. 来客中は二人がそばにいる. 寂しさが紛れるのは二人きりのときだけ
        mio = app.new_character("みお", stage="contact")["id"]
        B.set_stage(mio, "visit")
        B.start(mio, "guest")
        comp = B.company()
        assert comp == [mio, "hina"], comp
        assert app.target("hina") == "hina" and app.target(mio) == mio
        app.set_target(mio)
        assert app.state_view()["target"] == mio
        lon0 = st["params"]["loneliness"] = 60.0
        P.rec()["input"] = P.rec()["beat"] = time.time()          # そばで構っている (here: 寂しさ -3/時)
        app._step(app.chars["hina"], st, datetime.now(), 1.0)
        two = st["params"]["loneliness"] - lon0
        B.end()
        assert B.company() == ["hina"]
        st["params"]["loneliness"] = lon0
        app._step(app.chars["hina"], st, datetime.now(), 1.0)
        alone = st["params"]["loneliness"] - lon0
        assert alone < two - 2, ("二人きりのほうが寂しさが紛れる", alone, two)
        print("寂しさの動き 1 時間: 三人 %+.1f / 二人きり %+.1f" % (two, alone))
        try:
            app.set_target(mio)
            raise AssertionError("そばにいない人を相手に選べる")
        except ValueError:
            pass

        # ---- 4. 一人のときの行動は, あなたの記録に (誰にも告げない)
        app.solo.start("out", place="town")
        app.life.player_state()["money"] = 100000
        r = app.trade(app.life.assets()[0]["id"], 1)
        assert r["entry"].get("mine") and r["entry"]["who"] is None, r["entry"]
        assert app.task_ready() and "家にいない" in app.task_ready()["reason"]
        P.rec()["since"] -= 600
        app.come_back()
        assert app.task_ready() is None, app.task_ready()
        items, total = app.timeline()
        whos = {x["who"] for x in items}
        assert None in whos and "hina" in whos, whos
        assert all(x["who"] == "hina" for x in app.timeline("hina")[0])
        assert all(x.get("mine") for x in app.timeline("me")[0])
        assert [x["t"] for x in items] == sorted((x["t"] for x in items), reverse=True)
        print("時系列: %d 件 (あなた %d・ひな %d)" % (total, len(app.timeline("me")[0]), len(app.timeline("hina")[0])))

        # ---- 5. 関係性: 渡してみて分かった好きなもの・聞いた話
        app.items.add("cake", 1)
        st["params"].update(affection=70, mood=70)
        app.give_item("cake", "hina")
        pv = {p["id"]: p for p in app.people_view()}
        assert pv["hina"]["last_met"] and pv["hina"]["mode"] == "home"
        assert any(k["kind"] == "like" for k in pv["hina"]["known"]), pv["hina"]["known"]
        app.life.add_reason(st, "event", "good", "友だちと映画を観てきた", time.time(), told=True)
        pv = {p["id"]: p for p in app.people_view()}
        assert any(k["kind"] == "heard" and "映画" in k["text"] for k in pv["hina"]["known"]), pv["hina"]["known"]
        assert pv[mio]["mode"] is None and pv[mio]["stage"] == "visit"
        print("関係性:", [(k["kind"], k["text"]) for k in pv["hina"]["known"]])
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
