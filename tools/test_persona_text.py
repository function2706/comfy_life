"""性格の説明文の遡及 (engine.OLD_PERSONA_TEXT): キャラにコピーされた説明文が以前の既定のままなら, 起動時に今の既定へ.
書き換えていれば触らない. 令嬢のセリフに型どおりのお嬢様言葉が残っていない (一時データ).

    python tools/test_persona_text.py
"""
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("説明文")
        ids = list(app.chars)
        a, b = app.chars[ids[0]], app.chars[ids[1] if len(ids) > 1 else ids[0]]
        old = engine.App.OLD_PERSONA_TEXT["ojousama"][0]
        a.update(persona_id="ojousama", persona=old)
        store.save_character(a)
        if b is not a:
            b.update(persona_id="ojousama", persona=old + "（書き足し）")
            store.save_character(b)
        app2 = engine.App()
        new = app2.personas["ojousama"]["persona"]
        assert app2.chars[a["id"]]["persona"] == new and "ですわ" not in new
        if b is not a:
            assert app2.chars[b["id"]]["persona"] == old + "（書き足し）", "書き換えた説明文はそのまま"
        print("説明文の遡及: OK")
        stereo = re.compile(r"ですわ|ますわ|ですの|ますの|くださいまし|よろしくて|存じ|ごきげんよう|あそばせ|ませんこと|なくて[？?]")
        lines = [t for v in app2.personas["ojousama"]["lines"].values() for t in (v if isinstance(v, list) else [v])]
        left = [t for t in lines if stereo.search(t)]
        assert not left, left[:5]
        assert app2.personas["ojousama"]["first_person"] == "私"
        print("令嬢のセリフ: OK (%d 行)" % len(lines))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
