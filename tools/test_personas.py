"""性格プリセットの確認 (一時データディレクトリで実行, 画像生成なし).

    python tools/test_personas.py
"""
import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    random.seed(3)
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        st = app.state("hina")
        st["override"] = {"activity": "relax", "label": "テスト", "location": "リビング", "until": 9e12}
        app.set_params({"affection": 80, "mood": 70, "sleepiness": 0, "boredom": 10, "shyness": 5})
        print("personas:", ", ".join(p["name"] for p in app.boot_view()["personas"]))
        assert len(app.personas) >= 16

        char = app.char()
        app.life.player_state()["skills"]["talk"] = 50     # スキルしだいの反応 (盛り上がる / 沈黙) を出さない
        common = None
        for pid in [""] + list(app.personas):
            char["persona_id"] = pid
            r = app.act("talk")
            g = app.games.start("connect4")
            print("%-12s talk: %s ｜ コネクトフォー: %s" % (pid or "(共通)", r["entry"]["text"], g["entry"]["text"]))
            app.games.quit()
            st["cooldowns"] = {}
            if not pid:
                common = r["entry"]["text"]
            else:
                lines = app.personas[pid]["lines"]
                cands = [t.replace("{call}", "").replace("{name}", "") for t in lines.get("talk.default", []) +
                         lines.get("talk.mood_ge_55", []) + lines.get("talk.affection_ge_70", [])]
                assert r["entry"]["text"] != common or not cands, pid
        # 置換文字が残っていないこと
        for e in app.log("hina"):
            assert "{" not in e["text"], e["text"]

        # 一人称・呼び方: 固定していなければプリセット, 固定すればどの性格でもそれ
        def say(pid, key, fp="", call=""):
            char.update(persona_id=pid, first_person=fp, player_call=call)
            t = app.personas[pid]["lines"][key][0]
            return app.format_text(t, char, app.scene_at(char, st, __import__("datetime").datetime.now()),
                                   __import__("datetime").datetime.now())
        print("boyish プリセット:", say("boyish", "mg.yakyuken.start.mood_ge_60"))
        print("boyish 固定(私/ユウくん):", say("boyish", "mg.yakyuken.start.mood_ge_60", "私", "{player}くん"))
        assert "ボク" in say("boyish", "mg.yakyuken.start.mood_ge_60")
        assert "私" in say("boyish", "mg.yakyuken.start.mood_ge_60", "私") and "ボク" not in say("boyish", "mg.yakyuken.start.mood_ge_60", "私")
        k = next(k for k, v in app.personas["uchiki"]["lines"].items() if "{fp_st}" in v[0])
        assert "わ、私" in say("uchiki", k) and "うち、" not in say("uchiki", k, "うち")
        print("uchiki 言いよどみ:", say("uchiki", k), "→ 固定(うち):", say("uchiki", k, "うち"))
        k = next(k for k, v in app.personas["kedakai"]["lines"].items() if "{call}" in v[0])
        assert "ユウ" in say("kedakai", k) and "ユウ様" in say("kedakai", k, call="{player}様")
        print("kedakai 呼び方:", say("kedakai", k), "→ 固定:", say("kedakai", k, call="{player}様"))
        for pid, p in app.personas.items():   # 置換し忘れ (一人称の直書き) が残っていないか
            for key, v in p["lines"].items():
                for t in v:
                    assert not __import__("re").search(r"(?:わたくし|わたし|あたし|ボク)", t), (pid, key, t)
        # 移行: 性格プリセットと同じ呼び方がコピーされていたら空欄 (プリセットに従う) に戻す
        char.update(persona_id="tsundere", player_call="あんた", first_person="")
        store.save_character(char)
        app2 = engine.App()
        assert app2.char()["player_call"] == "", app2.char()["player_call"]
        char.update(player_call="")
        print("pronouns: OK")

        # 編集して保存 → 反映, 既定に戻す
        p = dict(app.personas["genki"])
        p["lines"] = dict(p["lines"], **{"talk.default": ["テスト用のセリフ！"], "talk.mood_ge_55": ["テスト用のセリフ！"],
                                         "talk.affection_ge_70": ["テスト用のセリフ！"]})
        app.save_persona(p)
        char["persona_id"] = "genki"
        assert app.act("talk")["entry"]["text"].startswith("テスト用のセリフ！")   # 繰り返しのうんざり (ナレーション) が付くことがある
        assert app.personas["genki"]["_custom"]
        app.reset_persona("genki")
        assert not app.personas["genki"]["_custom"]
        print("edit/reset: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
