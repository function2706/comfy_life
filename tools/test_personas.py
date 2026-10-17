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
        assert len(app.personas) >= 13

        char = app.char()
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

        # 編集して保存 → 反映, 既定に戻す
        p = dict(app.personas["genki"])
        p["lines"] = dict(p["lines"], **{"talk.default": ["テスト用のセリフ！"], "talk.mood_ge_55": ["テスト用のセリフ！"],
                                         "talk.affection_ge_70": ["テスト用のセリフ！"]})
        app.save_persona(p)
        char["persona_id"] = "genki"
        assert app.act("talk")["entry"]["text"] == "テスト用のセリフ！"
        assert app.personas["genki"]["_custom"]
        app.reset_persona("genki")
        assert not app.personas["genki"]["_custom"]
        print("edit/reset: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
