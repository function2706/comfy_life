"""お出かけ (帰宅・お出かけ着) と, 既存 data/ の既定追従の確認 (一時データディレクトリ, 画像生成なし).

    python tools/test_outing_migrate.py
"""
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)     # 時刻を昼に固定 (流す時刻に左右されないように)


def main():
    random.seed(5)
    # ---- 1. 最初のコミット時点の既定で data/ を作り, いまのコードで起動 → 未編集は更新・新規は追加
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    try:
        first = subprocess.check_output(["git", "-C", BASE, "rev-list", "--max-parents=0", "HEAD"]).decode().split()[0]
        os.makedirs(os.path.join(tmp, "characters"))
        for p in ("actions.json", "params.json", "world.json", "characters/hina.json"):
            data = subprocess.check_output(["git", "-C", BASE, "show", "%s:defaults/%s" % (first, p)])
            open(os.path.join(tmp, *p.split("/")), "wb").write(data)
        acts = json.load(io.open(os.path.join(tmp, "actions.json"), encoding="utf-8"))
        for a in acts:   # ユーザーが手を加えたコマンドを 1 つ作っておく
            if a["id"] == "talk":
                a["reactions"][0]["text"] = "（ユーザーが書き換えたセリフ）"
            if a["id"] == "photo":
                acts.remove(a)   # ユーザーが消したコマンド
                break
        io.open(os.path.join(tmp, "actions.json"), "w", encoding="utf-8").write(json.dumps(acts, ensure_ascii=False))
        store.DATA = tmp
        app = engine.App()
        ids = [a["id"] for a in app.actions]
        gift = app.action("gift")
        assert gift["category"] == "ふれあい", "未編集のコマンドは最新の既定に更新される"
        assert app.action("talk")["reactions"][0]["text"] == "（ユーザーが書き換えたセリフ）", "編集したものは残す"
        assert "picnic" in ids and "go_home" in ids and "peek_face" in ids, "新しい既定コマンドが追加される"
        assert ids.index("peek_face") == ids.index("look") + 1, "既定の並び位置に入る"
        assert "photo" in ids, "初回 (seen 無し) は既定にあって data に無いものも追加 (過去の版の data には photo がある想定)"
        assert app.action("walk")["override"].get("outing"), app.action("walk")
        c = app.char()
        assert c.get("outfit_outing") and any(o.get("outing_ok") for o in c["wardrobe"])
        print("migrate: OK (%d commands)" % len(ids))

        # 2 回目の起動: 追加・更新は繰り返されない
        app.save_actions([a for a in app.actions if a["id"] != "picnic"])   # ユーザーが消した
        app2 = engine.App()
        assert "picnic" not in [a["id"] for a in app2.actions], "消したものは戻さない"
        print("seen: OK")

        # ---- 2. お出かけ: 部屋着のまま出かけない / 外に着ていける服はそのまま / 家に帰れる
        app.save_settings({"auto_generate": False})
        st = app.state("hina")
        st["override"] = None
        app.set_params({"affection": 80, "mood": 70, "energy": 90, "sleepiness": 0})
        app.reload()
        st["dress"] = {"id": "pajamas"}
        st["override"] = {"activity": "relax", "label": "テスト", "location": "リビング", "until": 9e12}
        st["override"] = None
        import datetime as _dt
        now = _dt.datetime(2026, 10, 18, 11, 0)
        # 予定に左右されないよう, 散歩は直接 override を作って確認
        ov = dict(app.action("walk")["override"])
        ov["until"] = now.timestamp() + 3600
        st["override"] = ov
        s = app.scene_at(app.char(), st, now)
        assert "pajamas" not in s["outfit"] and s["outfit"] == app.char()["outfit_outing"], s["outfit"]
        st["dress"] = {"id": "onepiece"}
        s = app.scene_at(app.char(), st, now)
        assert "one-piece" in s["outfit"], s["outfit"]
        ctx = app.context(app.char(), st, now)
        assert ctx["outing"] and ctx["overriding"] and ctx["season"] == "autumn"
        print("outing outfit: OK")

        # 散歩 → 家に帰る / ゲーム → 切り上げる で予定に戻る
        st["override"], st["dress"] = None, None
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": 9e12}
        st["override"] = None
        r = app.act("walk")
        if st.get("override"):      # 夜など散歩できない時間帯は条件で弾かれる
            assert app.state_view()["available"]["go_home"]["ok"]
            r = app.act("go_home")
            assert st.get("override") is None, st.get("override")
            print("go_home:", r["entry"]["text"])
        r = app.act("game")
        assert app.state_view()["available"]["end_activity"]["ok"]
        app.act("end_activity")
        assert st.get("override") is None
        print("end_activity: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp + "_backup", ignore_errors=True)     # 移行前の自動バックアップ


if __name__ == "__main__":
    main()
