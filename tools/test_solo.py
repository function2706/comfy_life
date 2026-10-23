"""一人の時間 (休む・家事・研鑽・散歩・買い物・日記) の確認 (一時データ, 画像生成なし).

    python tools/test_solo.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)     # 時刻を昼に固定 (流す時刻に左右されないように)



def back_after(app, hours):
    """一人の時間を hours 時間過ごしたことにして戻る."""
    p = app.presence.rec()
    p["since"] -= hours * 3600
    app.life.player_state()["last_tick"] = time.time() - hours * 3600
    app.life.tick_world()
    return app.come_back()


def main():
    random.seed(9)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        S, L = app.solo, app.life
        st = app.state("hina")
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": 9e12}
        app.set_params({"mood": 60, "sleepiness": 0})

        # ---- 1. 同居していても「ちょっと一人になる」: 既存の「ちょっと作業するね」と同じく声をかける
        L.player_state()["stamina"] = 30
        r = S.start("rest")
        assert r["act"] and r["act"]["entry"]["action"] == "go_busy", r
        assert app.presence.rec()["mode"] == "busy" and app.state_view()["presence"]["solo"]["kind"] == "rest"
        try:
            S.start("walk", place="park")
            raise AssertionError("一人の時間の最中に, 別のことを始められてしまう")
        except ValueError:
            pass
        r = back_after(app, 2)
        assert r["solo"]["kind"] == "rest" and "休んだ" in r["solo"]["text"]
        assert L.player_state()["stamina"] >= 30 + 2 * 9 - 1, L.player_state()["stamina"]
        assert app.presence.rec()["mode"] == "none" and not app.presence.rec().get("solo")
        print("rest: OK", round(L.player_state()["stamina"], 1))

        # ---- 2. 研鑽: スキルが伸びる (はかどり具合は揺らぐ). 家事: 同居相手が気づくかは偶然
        old = L.skill("cook")
        S.start("practice", "cook")
        r = back_after(app, 2)
        assert r["solo"]["skill"]["cook"] > 0 and L.skill("cook") > old
        try:
            S.start("practice")
            raise AssertionError("何を練習するか決めずに始められる")
        except ValueError:
            pass
        noticed = 0
        for _ in range(12):
            S.start("chores")
            noticed += "気づいて" in back_after(app, 1)["solo"]["text"]
        assert 0 < noticed < 12, noticed
        # 一人の時間の最中に相手を構うと, 一人の時間はおしまい (結果は出ない)
        S.start("rest")
        st["cooldowns"] = {}
        app.act("talk")
        assert app.presence.rec()["mode"] == "none" and not app.presence.rec().get("solo")
        print("practice / chores: OK", noticed, "/ 12")

        # そばに同居相手がいる: 告げる形 (既存の go_* と同じ)
        v = S.view()
        assert v["near"]["cid"] == "hina" and v["plain"][0]["label"] == "ちょっと作業するね", v["plain"]
        r = S.start("busy")
        assert r["act"]["entry"]["action"] == "go_busy"
        app.come_back()
        print("plain (near): OK")

        # ---- 3. 誰とも暮らしていない: 一人で外出 (行き先しだいで, 歩く・買い物). 出会いは偶然 (補正なし)
        app.create_world("ひとり")
        S, L = app.solo, app.life
        cid = app.settings["active_character"]
        assert not app.bonds.together(cid)
        r = S.start("out", place="park")
        assert r["act"] is None and app.presence.rec()["mode"] == "out"
        r = back_after(app, 1)
        assert "公園" in r["solo"]["text"] and r["solo"]["kind"] == "walk" and r["entry"]["text"].startswith("（") \
            and "encounter" not in r, "出会いは外出中に (帰ったときではない)"
        app.world["economy"]["player_daily_income"] = 0       # 日付をまたいでも, 定期収入・生活費・家賃が混ざらないように
        app.world["economy"]["living_cost_per_day"] = app.world["economy"]["home_cost_per_month"] = 0
        app.items.set_list("cookies", 3)                     # 買い物は, 買うものリストの品を買う
        m0 = L.player_state()["money"]
        S.start("out", place="shopping_street")
        r = back_after(app, 1)
        assert L.player_state()["money"] == m0 + r["solo"]["money"] < m0 and r["solo"]["bought"], r["solo"]
        try:
            S.start("out")
            raise AssertionError("行き先を選ばずに出かけられる")
        except ValueError:
            pass
        # 以前の「一人で散歩」は, 外出 + 行き先に読み替える
        S.start("walk", place="riverside")
        assert app.presence.rec()["solo"]["kind"] == "out" and app.presence.rec()["place"] == "riverside"
        r = back_after(app, 1)
        assert "河川敷" in r["solo"]["text"]
        print("out (walk / shopping): OK")

        # 告げる相手がいない: 一人で「仕事に行く」など. 一人暮らしに「作業する」は無い (同居相手に作業中と伝えるためのもの)
        v = S.view()
        assert v["near"] is None and [x["label"] for x in v["plain"]][:1] == ["仕事に行く"] and not any(x["id"] in ("out", "busy") for x in v["plain"]), v["plain"]
        try:
            S.start("busy")
            raise AssertionError("一人暮らしで「作業する」ができてしまう")
        except ValueError:
            pass
        assert not any(x["id"] == "leave" for x in v["plain"]), "一人のときに「席を外す」が出ている"
        try:
            S.start("leave")
            raise AssertionError("一人で「席を外す」ができてしまう")
        except ValueError:
            pass
        app.world["encounters"] = {"rate_out": 0}
        assert S.start("out", place="cafe")["act"] is None and app.presence.rec()["mode"] == "out"
        assert [k["id"] for k in v["kinds"]] == ["rest", "chores", "practice", "out", "jog"], "散歩・買い物・カフェは外出に吸収 (ジョギングは別)"
        app.come_back()
        print("plain (alone): OK")

        # ---- 4. 日記: その日の出来事から (LLM が無ければ定型)
        d = S.write_diary()
        assert d["src"] == "template" and d["text"].startswith("今日は一人で過ごした") and "カフェ" in d["text"], d["text"]
        d2 = S.write_diary()
        assert len(S.diary_list()) == 1 and d2["day"] == d["day"], "同じ日は書き直し"
        assert app.state_view()["solo"]["diary_today"]
        assert any(e["kind"] == "diary" for e in S.mylog())
        print("diary: OK\n" + d["text"])
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
