"""画像の再利用と着せ替えの確認 (一時データディレクトリで実行).

    python tools/mock_comfy.py --port 8189 --delay 0.3   (別ターミナル)
    python tools/test_reuse_dress.py --comfy-port 8189
"""
import argparse
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)     # 同居相手が家にいる時刻に (平日の昼は出かけていて, そばにいない)


def wait(app, jid):
    for _ in range(60):
        j = app.job_view(jid)
        if j["status"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.2)
    raise AssertionError("job timeout")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comfy-port", type=int, required=True)
    a = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"comfy": {"port": a.comfy_port, "ckpt": "mock.safetensors"},
                           "images": {"mode": "reuse", "max_per_prompt": 2}})
        app.set_params({"mood": 70, "affection": 50})
        st = app.state("hina")
        st["override"] = {"activity": "relax", "label": "テスト", "location": "リビング", "until": time.time() + 3600}

        # 同じプロンプトになるよう, 毎回同じ反応になる「様子を見る」を mood 固定で繰り返す
        def look():
            app.set_params({"mood": 70, "sleepiness": 0, "satiety": 60, "shyness": 5, "heart": 0})
            r = app.act("photo")
            return r
        r1 = look()
        assert r1["job"] and not r1["entry"].get("reused"), r1["entry"]
        wait(app, r1["job"])
        r2 = look()
        same = r1["entry"]["pos"] == r2["entry"]["pos"]
        print("same prompt:", same)
        if same:
            assert r2["entry"]["reused"] and r2["entry"]["image"], "既存画像がすぐ表示されること"
            assert r2["job"], "上限未満なので新規生成も行う"
            wait(app, r2["job"])
            r3 = look()
            assert r3["entry"]["reused"] and r3["job"] is None, "上限 (2) に達したら生成しない"
            print("reuse: OK (same_prompt=%d)" % r3["entry"]["same_prompt"])
            rr = app.reroll(r3["entry"]["id"])
            print("reroll ->", rr["entry"]["image"])

        app.save_settings({"images": {"mode": "always"}})
        r4 = look()
        assert r4["job"] and not r4["entry"].get("reused"), "毎回生成モード"
        wait(app, r4["job"])
        print("always: OK")

        # 生成中: 既存があれば即表示して生成しない / なければ待ち行列へ (毎回生成モードでも)
        busy_job = app.snapshot()["job"]
        assert app.generating()
        r5 = look()
        assert r5["entry"].get("busy_skip") and r5["entry"]["image"] and r5["job"] is None, r5["entry"]
        r6 = app.act("_dress", dress="yukata")   # 浴衣は初めてなので既存画像なし
        assert r6["job"] and not r6["entry"].get("reused"), "既存が無ければキューに積む"
        wait(app, busy_job)
        wait(app, r6["job"])
        app.act("_dress", dress="")
        print("busy reuse: OK")

        # 着せ替え (メイド服は少し大胆: 仲がよく機嫌もいいときに頼む)
        app.set_params({"affection": 90, "trust": 90, "mood": 70})
        r = app.act("_dress", dress="maid")
        print("dress maid:", r["entry"]["text"], "|", app.person_view()["dress"]["wearing"])
        assert "maid" in r["entry"]["pos"]
        app.set_params({"affection": 10, "trust": 10})
        r = app.act("_dress", dress="swimsuit")
        print("dress swimsuit (affection 10):", r["entry"]["text"], "| wearing:", app.person_view()["dress"]["wearing"])
        assert app.state("hina")["dress"]["id"] == "maid", "拒否されたら着替えない"
        try:
            app.act("_dress", dress="maid")   # maid は affection>=40 が必要
            raise AssertionError("条件を満たさない服に着替えられてしまった")
        except ValueError as e:
            print("gated:", e)
        st["override"] = {"activity": "sleep", "label": "就寝中", "asleep": True, "outfit": "pajamas",
                          "until": time.time() + 3600}
        assert "pajamas" in app.prompt_preview()["pos"] and "maid" not in app.prompt_preview()["pos"], "睡眠中は服装固定"
        print("fixed outfit while asleep: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
