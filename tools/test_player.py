"""設定「あなた」(プレイヤー情報) の確認: 名前の一本化・置換文字・条件・画像のあなたの外見 (一時データ, 画像生成なし).

    python tools/test_player.py
"""
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)     # 同居相手が家にいる時刻に (平日の昼は出かけていて, そばにいない)


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        # 古い player_name だけでも名前になる
        app.save_settings({"player_name": "ユウ"})
        assert app.player_name() == "ユウ" and app.settings["player"]["name"] == "ユウ"
        app.save_settings({"player": {"name": "カイ", "gender": "male", "age": 27, "job": "エンジニア",
                                      "likes": "コーヒー, 猫", "dislikes": "ピーマン", "looks": "1boy, short black hair"}})
        assert app.player_name() == "カイ" and app.settings["player_name"] == "カイ"
        char = app.char()
        st = app.state(char["id"])
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": 9e12}
        d = __import__("datetime").datetime.now()
        sc = app.scene_at(char, st, d)
        t = app.format_text("{player}は{player_job}、{player_like}が好きで{player_dislike}が苦手", char, sc, d)
        print(t)
        assert "カイはエンジニア" in t and ("コーヒー" in t or "猫" in t) and "ピーマン" in t
        ctx = app.context(char, st, d)
        assert ctx["player_gender"] == "male" and ctx["player_age"] == 27 and ctx["player_has_job"] and ctx["player_likes"] == 2
        # あなたも写るコマンドだけ, あなたの外見が画像に入る
        pos, _, parts = app.build_prompt(char, st, d, app.action("hug"))
        assert "1boy" in pos and any(p["src"] == "あなた" for p in parts)
        pos, _, parts = app.build_prompt(char, st, d, app.action("tea"))
        assert "1boy" not in pos
        assert "エンジニア" in app.player_text()
        # 職業があれば, 見送りで触れることがある
        app.world["economy"]["work_hours"] = [0, 24]
        app.action("go_work")["when"] = "presence=here|idle|busy"
        seen = set()
        for i in range(20):
            r = app.act("go_work")
            seen.add(r["entry"]["text"])
            app.presence.back()
            st["last_interaction"] = time.time()
        print([x for x in seen if "エンジニア" in x][:1])
        assert any("エンジニア" in x for x in seen)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
