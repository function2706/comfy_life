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

        # メッセージ: 画像は出さない. テンションしだいで自撮り
        r = app.act("message")
        assert r["job"] is None
        lo = B.selfie_chance({"mood": 30, "affection": 40, "stress": 70})
        hi = B.selfie_chance({"mood": 95, "affection": 90, "heart": 60})
        assert lo < 0.05 < hi <= 0.35, (lo, hi)
        B.selfie_chance = lambda ctx: 1.0
        st["cooldowns"] = {}
        r = app.act("message")
        e = r["entry"]
        assert e.get("selfie") and "selfie" in e["pos"] and "自撮り" in e["text"], e
        B.selfie_chance = lambda ctx: 0.0
        st["cooldowns"] = {}
        e = app.act("message")["entry"]
        assert not e.get("selfie") and e["text"].startswith("📱"), e
        print("apart / message / selfie: OK")

        # 離れているときのあなたの予定: 見送りはなく, あなたの行動だけ
        e = app.act("go_out")["entry"]
        assert e["text"].startswith("（") and not e["deltas"], e
        app.presence.back()
        print("narration: OK")

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
        app.delete_character(mio["id"])
        assert mio["id"] not in B.rec()["bonds"]
        print("move out / delete: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
