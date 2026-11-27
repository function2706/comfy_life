"""「裏で描いた画像に切り替える」(images.swap_after_gen) が, 画像を出すどの経路でも効くかの確認 (F23).

    python tools/mock_comfy.py --port 8189 --delay 0.3   (別ターミナル)
    python tools/test_swap_after_gen.py --comfy-port 8189

経路 × 設定:
  行動の絵 (act) / 📷 スナップ (snapshot, 指定なし) は「画像の出し方」に従う:
    切 → 既存があればすぐ出し, 裏で描き終えても記録の image は変わらない (shown False). 描いた分は候補に入る
    入 → 描き終えたら新しい画像に切り替わる (shown True)
    上限 (max_per_prompt) に達したら描かない
  ⟳ 描き直し (snapshot に記録を指定) とプロンプト欄の生成 (pos/neg 指定) は明示の操作: 設定によらず描いて切り替える
画面: ジョブの完了で, 記録の画像でないもの (顔・人のアイコン・服のサンプル) をステージに出さない.
"""
import argparse
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)     # 同居相手が家にいる時刻に


def wait(app, jid):
    for _ in range(150):
        j = app.job_view(jid)
        if j["status"] in ("done", "error", "cancelled"):
            assert j["status"] == "done", j
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

        def images(swap, limit=8):
            app.save_settings({"comfy": {"port": a.comfy_port, "ckpt": "mock.safetensors"},
                               "images": {"mode": "reuse", "max_per_prompt": limit, "busy_reuse": False,
                                          "swap_after_gen": swap}})

        def still():         # 同じプロンプトになるよう, 様子を固定する
            app.set_params({"mood": 70, "affection": 50, "sleepiness": 0, "satiety": 60, "shyness": 5, "heart": 0})
            st = app.state("hina")
            st["override"] = {"activity": "relax", "label": "テスト", "location": "リビング", "until": time.time() + 3600}

        def by_act():
            still()
            r = app.act("photo", "hina")
            return r["entry"], r["job"]

        def by_snap():
            still()
            r = app.snapshot("hina")
            return r["entry"], r["job"]

        for name, make in (("act", by_act), ("snap", by_snap)):
            images(False)
            e1, j1 = make()
            assert j1 and not e1.get("reused") and not e1.get("image"), (name, e1)
            assert wait(app, j1)["shown"] is True, name          # 何も出していなかった: 描いた画像を出す
            assert app.find_entry("hina", e1["id"])["image"], name
            # 切: 既存をすぐ出し, 裏で描いても切り替えない
            e2, j2 = make()
            assert e2["pos"] == e1["pos"], (name, "同じプロンプトにならない")
            assert e2.get("reused") and e2["image"] and j2, (name, e2)
            before = e2["image"]
            v2 = wait(app, j2)
            s2 = app.find_entry("hina", e2["id"])
            assert v2["shown"] is False and s2["image"] == before, (name, v2, s2["image"])
            assert len(s2.get("images") or []) == 1 and s2["images"][0]["path"] == v2["image"], name   # 描いた分は残る
            assert len(app.existing_images(e1["pos"], e1["neg"])) >= 2, name                         # 次からの候補にも
            # 入: 描き終えたら切り替える
            images(True)
            e3, j3 = make()
            assert e3.get("reused") and j3, (name, e3)
            before = e3["image"]
            v3 = wait(app, j3)
            s3 = app.find_entry("hina", e3["id"])
            assert v3["shown"] is True and s3["image"] == v3["image"] != before, (name, v3, s3["image"])
            # 上限に達したら描かない (すぐ出すだけ)
            n = len(app.existing_images(e1["pos"], e1["neg"]))
            images(False, limit=n)
            e4, j4 = make()
            assert e4.get("reused") and e4["image"] and j4 is None, (name, e4, j4)
            print("%s: 切=切り替えない / 入=切り替える / 上限で描かない: OK" % name)

        # ⟳ 描き直し: 明示の操作なので, 設定が切でも描いて切り替える
        images(False)
        e5, _ = by_snap()
        e5 = app.find_entry("hina", e5["id"])
        before = e5["image"]
        assert before, e5
        r = app.snapshot("hina", entry_id=e5["id"])
        v5 = wait(app, r["job"])
        assert v5["shown"] is True and app.find_entry("hina", e5["id"])["image"] == v5["image"] != before, v5
        # プロンプト欄の生成 (pos/neg 指定): 新しい記録に描く
        r = app.snapshot("hina", pos=e5["pos"], neg=e5["neg"])
        v6 = wait(app, r["job"])
        assert v6["shown"] is True and app.find_entry("hina", r["entry"]["id"])["image"] == v6["image"], v6
        print("regenerate / drawer: 設定によらず切り替える: OK")

        # 画面: 記録の画像でないジョブ (顔・人のアイコン・服のサンプル) はステージに出さない
        js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
        body = js[js.index("async function pollJobsOnce"):js.index("const secs =")]
        assert "j.kind && j.kind !== 'entry'" in body and "j.shown === false" in body, "pollJobsOnce の見逃しが崩れた"
        assert "if (r.job) trackJob(r.job)" in js[js.index("'#btn-snap'"):js.index("'#btn-snap'") + 300], "スナップ: ジョブなしで追いかけない"
        print("app.js: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
