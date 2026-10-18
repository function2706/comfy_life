"""あなたと各キャラの間柄 (連絡先 → 家に行ける → 同居), 外で会う・遊びに行く, 自撮り, 嫉妬の確認 (一時データ, 画像生成なし).

    python tools/test_bonds.py
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



def main():
    random.seed(7)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        B = app.bonds
        # ---- 1. 最初のワールド (以前からの続き) は, 選んでいたキャラと暮らしている
        assert B.stage("hina") == "live" and B.mode("hina") == "home", B.rec()
        assert app.state_view()["bond"]["label"] == "一緒に暮らしている"

        # ---- 2. 新しいワールドは, 誰とも暮らしていない
        app.create_world("ひとり暮らし")
        B = app.bonds
        B.readiness = lambda *a: 90.0          # 提案の受け方の揺らぎは test_realism で見る. ここでは受けてもらう
        assert B.stage("hina") == "contact" and B.mode("hina") is None
        st = app.state("hina")
        free = lambda: st.update(override={"activity": "relax", "label": "くつろぎ", "location": "ひなの部屋", "until": 9e12})  # noqa: E731
        free()
        app.set_params({"affection": 40, "trust": 40, "mood": 60, "sleepiness": 0, "energy": 80, "health": 90})
        av = app.state_view()["available"]
        assert not av["talk"]["ok"] and not av["hug"]["ok"] and not av["cook"]["ok"], "離れていると話しかけ・ふれあいはできない"
        assert av["message"]["ok"] and av["call"]["ok"] and av["cafe"]["ok"], "連絡と, お出かけに誘うことはできる"
        assert not av["visit_home"]["ok"] and not av["ask_visit"]["ok"]
        try:
            app.act("talk")
            raise AssertionError("離れているのに話しかけられた")
        except ValueError as e:
            assert "一緒にいません" in str(e)
        assert app.visit() is None, "離れている相手は「おかえり」しない"

        # メッセージ: 送るだけ. 返信は相手の状況しだいで, しばらくしてから (画像なし. テンションしだいで自撮り)
        def reply(will=True):
            st["msg_pending"]["due"], st["msg_pending"]["reply"] = time.time() - 1, will
            return app.deliver_due()

        e = app.act("message")["entry"]
        assert e["text"].startswith("（📱") and e.get("sent") and not e["deltas"] and st["msg_pending"], e
        st["cooldowns"] = {}
        app.act("message")
        assert st["msg_pending"]["count"] == 2, "返信前に送り重ねても, 返信は 1 回"
        st["msg_pending"]["due"] = time.time() + 3600
        assert app.deliver_due() == [], "まだ返ってこない"
        lo = B.selfie_chance({"mood": 30, "affection": 40, "stress": 70})
        hi = B.selfie_chance({"mood": 95, "affection": 90, "heart": 60})
        assert lo < 0.05 < hi <= 0.35, (lo, hi)
        B.selfie_chance = lambda ctx: 1.0
        out = reply()
        assert len(out) == 1 and out[0]["name"] == "ひな", out
        e = app.log("hina")[-1]
        assert e.get("reply") and e.get("selfie") and "selfie" in e["pos"] and "自撮り" in e["text"], e
        assert "msg_pending" not in st and st["last_touch"] > time.time() - 60, "返信が来た = 交流した"
        B.selfie_chance = lambda ctx: 0.0
        st["cooldowns"] = {}
        app.act("message")
        assert reply(will=False) == [] and "msg_pending" not in st, "返信が来ないこともある"
        st["cooldowns"] = {}
        app.act("message")
        st["override"] = {"activity": "bath", "label": "入浴中", "location": "浴室", "until": time.time() + 3600, "busy": True}
        assert reply() == [] and st["msg_pending"]["due"] > time.time(), "入浴中は出てから"
        free()
        st["msg_pending"]["due"] = time.time() - 1
        e = app.state_view()["replies"]
        assert e and e[0]["text"].startswith("📱"), e
        st["cooldowns"] = {}
        app.act("message")
        st["msg_pending"]["t"] -= 25 * 3600
        st["msg_pending"]["due"] = time.time() - 1
        assert app.deliver_due() == [] and "msg_pending" not in st, "一日たっても来なければ, もう来ない"
        print("apart / message / selfie: OK")

        # 離れているときのあなたの予定: 見送りはなく, あなたの行動だけ
        e = app.act("go_out")["entry"]
        assert e["text"].startswith("（") and not e["deltas"], e
        app.presence.back()
        print("narration: OK")

        # 離れている相手からの働きかけ: "apart": true のメッセージだけ. 画像なし. 仲が浅く寂しくなければほとんど来ない
        def tries(n):
            ids = []
            for i in range(n):
                free()
                st["approach"], st["ap_quiet_until"], st["ap_last"] = None, 0, {}
                st["ap_check"] = time.time() - 600
                e = app.presence.live(app.char(), st, time.time())
                if e:
                    ids.append(e["approach"])
                    assert e["text"].startswith("📱") and not e.get("job"), e
            return ids
        app.presence.beat()
        app.set_params({"loneliness": 10, "affection": 30, "mood": 40, "boredom": 60})
        few = tries(200)
        app.set_params({"loneliness": 90, "affection": 80, "mood": 70, "boredom": 60})
        many = tries(200)
        assert all(i.startswith("msg_") for i in few + many), few + many
        assert len(few) < len(many) and 5 <= len(many) <= 60, (len(few), len(many))
        free()
        st["approach"], st["ap_last"] = None, {}
        e = app.presence.fire(app.char(), st, time.time(), app.context(app.char(), st, __import__("datetime").datetime.now()))
        assert e["approach"].startswith("msg_")
        r = app.answer_approach("accept")
        assert r["entry"]["text"].startswith("📱") and r["entry"]["deltas"].get("loneliness", 0) < 0 and not r["job"], r
        print("apart approach: %d -> %d / 200, OK" % (len(few), len(many)))

        # ---- 3. お出かけに誘う = 外で会う. 帰れば別れる
        app.set_params({"affection": 20})
        e = app.act("cafe")["entry"]
        assert B.mode("hina") is None and "ちょっと" in e["text"], "好感度が低いと断られる"
        app.set_params({"affection": 50})
        st["cooldowns"] = {}
        app.act("cafe")
        assert B.mode("hina") == "meet" and app.state_view()["available"]["talk"]["ok"], "外で会っている間は話せる"
        app.act("go_home")
        assert B.mode("hina") is None, "家に帰ると別れる"
        print("meet: OK")

        # ---- 4. 家に行ってもいい？ → 遊びに行く → 帰る / 時間切れ
        free()
        app.set_params({"affection": 60, "trust": 60})
        app.act("ask_visit")
        assert B.stage("hina") == "visit"
        app.act("visit_home")
        assert B.mode("hina") == "visit" and app.state_view()["available"]["cook"]["ok"], "相手の家では家のこともできる"
        app.act("leave_visit")
        assert B.mode("hina") is None
        st["cooldowns"] = {}
        app.act("visit_home")
        B.rec()["with"]["until"] = time.time() - 1
        app.tick("hina")
        assert B.mode("hina") is None, "遊びに来ていた時間が過ぎたら帰る"
        print("visit: OK")

        # ---- 5. 一緒に住まない？ (一人だけ)
        st["cooldowns"] = {}
        app.act("visit_home")
        app.set_params({"affection": 85, "trust": 85, "mood": 70})
        app.act("ask_live")
        assert B.stage("hina") == "live" and B.mode("hina") == "home" and B.living() == "hina"
        mio = app.new_character("みお")
        app.select_character("hina")
        B.set_stage(mio["id"], "visit")
        sm = app.state(mio["id"])
        sm["override"] = {"activity": "relax", "label": "くつろぎ", "location": "みおの部屋", "until": 9e12}
        app.set_params({"affection": 90, "trust": 90}, mio["id"])
        app.select_character(mio["id"])
        app.act("visit_home", mio["id"])
        assert B.mode(mio["id"]) == "visit" and B.mode("hina") is None, "みおの家にいる間, ひなとは離れている"
        assert not app.state_view(mio["id"])["available"]["ask_live"]["ok"], "同居は一人だけ"
        try:
            B.set_stage(mio["id"], "live")
            raise AssertionError("二人目と同居できてしまう")
        except ValueError:
            pass
        app.act("leave_visit", mio["id"])
        assert B.mode("hina") == "home", "帰ればひなと一緒"
        print("live: OK")

        # ---- 6. 嫉妬: ひなは, あなたとみおの深い仲に気づく (性格で強さが違う)
        app.select_character("hina")
        hina = app.char("hina")
        before = dict(st["params"])
        d1 = B.notice(hina, st, mio["id"], time.time())
        assert d1.get("mood", 0) < 0 and d1.get("trust", 0) < 0, d1
        assert any("みお" in x["tell"] for x in app.life.reasons(st, time.time())), "機嫌の理由に残る"
        assert app.relation("hina", mio["id"])["knows"], "相手のことを知る"
        assert st["params"]["mood"] < before["mood"]
        hina["persona_id"] = "amaenbo"
        app.set_params({"mood": 60, "trust": 60})
        da = B.notice(hina, st, mio["id"], time.time())
        hina["persona_id"] = "cool"
        app.set_params({"mood": 60, "trust": 60})
        dc = B.notice(hina, st, mio["id"], time.time())
        assert da["mood"] < dc["mood"] < 0, (da, dc)
        hina["persona_id"] = ""
        # 時間経過でも気づく (気づいてから日が浅ければ繰り返さない)
        st["jealous"] = {}
        app.world.setdefault("bonds", {})["jealousy_per_day"] = 200
        st["last_tick"] = time.time() - 3600
        app.tick("hina")
        assert mio["id"] in st["jealous"], "一緒に暮らしていて, ほかの人と深い仲だと気づく"
        t0 = st["jealous"][mio["id"]]
        st["last_tick"] = time.time() - 3600
        app.tick("hina")
        assert st["jealous"][mio["id"]] == t0, "すぐには繰り返さない"
        app.world["bonds"]["jealousy_per_day"] = 0.6
        print("jealousy: OK")

        # ---- 7. 同居をやめる / キャラを消す
        app.set_params({"mood": 70, "trust": 70, "affection": 70})
        app.act("move_out")
        assert B.stage("hina") == "visit" and B.living() is None and B.mode("hina") is None
        assert st["params"]["trust"] < 60
        # 同居していない相手: 同居前提のセリフを出さない / 相手の家から出かければ別れる
        from datetime import datetime
        ctx = app.context(hina, st, datetime.now())
        greet, home = app.action("greet"), app.action("go_home")
        for ph, mode in (("noon", "meet"), ("noon", "visit"), ("evening", "meet")):
            ctx.update(phase=ph, stage="visit", with_mode=mode, repeat=0)
            t = app.pick_reaction(greet, ctx).get("text", "")
            assert t and "一緒に住" not in t and "晩ごはん" not in t, (ph, mode, t)
        ctx.update(energy=10, with_mode="meet")
        assert "ただいま" not in app.pick_reaction(home, ctx)["text"]
        free()
        app.set_params({"mood": 70})
        st["cooldowns"] = {}
        app.act("visit_home")
        assert B.mode("hina") == "visit" and app.visit() is None, "遊びに来ている間は「おかえり」しない"
        e = app.act("go_work")["entry"]
        assert e["text"].startswith("（ひなと別れて") and B.mode("hina") is None, e["text"]
        assert app.come_back()["entry"]["text"].startswith("（"), "離れている相手は出迎えない"
        app.delete_character(mio["id"])
        assert mio["id"] not in B.rec()["bonds"]
        print("move out / delete: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
