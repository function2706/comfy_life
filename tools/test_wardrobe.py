"""服の一覧と持っている服 (core/wardrobe.py): 移行・着せ替えの一覧・大胆な服の受け入れ・服のプレゼント・本人の服選び・
本人が服を買う・サンプル画像.

    python tools/test_wardrobe.py         (ComfyUI もどきを中で立てる)
"""
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, BASE)
sys.path.insert(0, HERE)
import mock_comfy  # noqa: E402
from core import engine, items as items_mod, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def old_hina():
    """以前の形式 (キャラごとの wardrobe) のひな."""
    out = subprocess.run(["git", "show", "02356bf:defaults/characters/hina.json"], cwd=BASE, capture_output=True)
    return json.loads(out.stdout.decode("utf-8"))


def rate(fn, n=300):
    return sum(1 for _ in range(n) if fn()) / float(n)


def main():
    random.seed(7)
    mock_comfy.DELAY = 0.05
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mock_comfy.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        # ---- 1. 移行: キャラごとの wardrobe → 服の一覧 + 持っている服 (中身が同じものは 1 つに)
        os.makedirs(os.path.join(tmp, "characters"))
        h = old_hina()
        h["wardrobe"].append({"id": "casual", "name": "自作の赤いドレス", "icon": "❤", "when": "", "outing_ok": True,
                              "pos": "red dress", "neg": ""})
        store.save(os.path.join(tmp, "characters", "hina.json"), h)
        app = engine.App()
        app.save_settings({"auto_generate": False, "comfy": {"port": srv.server_address[1], "ckpt": "mock.safetensors"}})
        c = store.all_characters()["hina"]
        assert "wardrobe" not in c
        ids = [x["id"] for x in c["clothes"]]
        assert ids[:8] == ["casual", "lounge", "onepiece", "apron", "yukata", "maid", "swimsuit", "pajamas"], ids
        red = app.wardrobe.get(ids[8])
        assert red["name"] == "自作の赤いドレス" and ids[8] != "casual" and red["price"] == 0, red
        assert sum(1 for o in app.wardrobe.all() if o["id"] == "casual") == 1, "中身が同じものは 1 つに"
        assert os.path.exists(store.dpath("outfits.json"))
        app2 = engine.App()                      # 2 回目は何もしない
        assert [x["id"] for x in store.all_characters()["hina"]["clothes"]] == ids
        app = app2
        app.save_settings({"auto_generate": False})
        print("移行: OK", len(app.wardrobe.all()), "着")

        # ---- 2. 着せ替えに並ぶのは持っている服だけ. その人用の上書き
        cid = "hina"
        st = app.state(cid)
        view = app.state_view(cid)["with"]
        assert [o["id"] for o in view["wardrobe"]] == ids and "bikini" not in view["dress"]["items"]
        try:
            app.act("_dress", cid, dress="bikini")
            raise AssertionError("持っていない服に着替えられた")
        except KeyError:
            pass
        c = store.all_characters()[cid]
        c["clothes"][0]["pos"] = "casual clothes, plus size"
        app.save_character(c)
        assert app.wardrobe_item(app.char(cid), "casual")["pos"] == "casual clothes, plus size"
        print("持っている服だけ / 上書き: OK")

        # ---- 3. 大胆な服の受け入れ: 仲・機嫌・性格・場所しだい (仲が深くても断られることがある), しつこいと怒る
        W = app.wardrobe
        sw = W.get("swimsuit")
        char = app.char(cid)

        def ok_rate(aff, trust, mood=60, outside=False, bold_o=sw):
            def one():
                st["dress_asks"] = []
                app.set_params({"affection": aff, "trust": trust, "mood": mood}, cid)
                return W.accept(char, st, bold_o, time.time(), outside=outside) not in ("refuse", "angry")
            return rate(one)
        low, high = ok_rate(30, 30), ok_rate(85, 85)
        out = ok_rate(85, 85, outside=True)
        print("水着を着てくれる割合: 浅い仲 %.2f / 深い仲 %.2f / 深い仲で外 %.2f" % (low, high, out))
        assert low < 0.1 and 0.6 < high < 1.0 and out < high, (low, high, out)
        bik = W.get("bikini")
        hb = ok_rate(85, 85, bold_o=bik)
        assert hb < high, "大胆なほど断られやすい"
        assert W.accept(char, st, W.get("casual"), time.time()) == "ok"
        # 恥じらいの強い性格ほど断る (控えめな差)
        char["persona_id"] = "itazura"
        bold_p = ok_rate(70, 70)
        char["persona_id"] = "uchiki"
        shy_p = ok_rate(70, 70)
        char["persona_id"] = "teinei"
        assert shy_p < bold_p, (shy_p, bold_p)
        feels = set()
        for _ in range(200):
            st["dress_asks"] = []
            app.set_params({"affection": 90, "trust": 90, "mood": 80}, cid)
            feels.add(W.accept(char, st, sw, time.time()))
        assert {"eager", "shy"} <= feels, feels
        # 断られたのに続けて頼むと怒る
        st["dress_asks"] = []
        app.set_params({"affection": 20, "trust": 20, "mood": 40}, cid)
        seq = [W.accept(char, st, bik, time.time()) for _ in range(4)]
        assert seq[0] == "refuse" and "angry" in seq[2:], seq
        # 着せ替えのコマンド: 断られれば着替えない / 怒ると機嫌が下がる
        app.set_params({"affection": 20, "trust": 20, "mood": 50}, cid)
        st["dress"], st["dress_asks"], st["cooldowns"] = None, [], {}
        r = app.act("_dress", cid, dress="swimsuit")
        assert not st.get("dress"), r["entry"]["text"]
        st["dress_asks"] = [{"t": time.time(), "ok": False, "bold": 2}] * 2
        m0 = st["params"]["mood"]
        r = app.act("_dress", cid, dress="swimsuit")
        assert "嫌です" in r["entry"]["text"] and st["params"]["mood"] < m0, r["entry"]["text"]
        print("大胆な服: OK", sorted(feels))

        # ---- 4. 服のプレゼント: 店で買って贈る → 持っている服に. 大胆すぎると受け取らず手元に残る
        st["dress_asks"], st["gifts"], st["cooldowns"] = [], [], {}
        assert "outfit:winter_coat" in items_mod.CATALOG and items_mod.CATALOG["outfit:winter_coat"]["giftable"]
        app.items.add("outfit:winter_coat")
        app.set_params({"affection": 70, "trust": 70, "mood": 70}, cid)
        r = app.give_item("outfit:winter_coat", cid)
        assert "winter_coat" in W.owned_ids(store.all_characters()[cid]), r["entry"]["text"]
        assert next(x for x in store.all_characters()[cid]["clothes"] if x["id"] == "winter_coat")["from"] == "player"
        try:
            app.items.add("outfit:winter_coat")
            app.give_item("outfit:winter_coat", cid)
            raise AssertionError("持っている服を贈れた")
        except ValueError:
            app.items.add("outfit:winter_coat", -1)
        app.items.add("outfit:negligee")
        app.set_params({"affection": 25, "trust": 25, "mood": 50}, cid)
        st["gifts"], st["cooldowns"] = [], {}
        r = app.give_item("outfit:negligee", cid)
        assert "negligee" not in W.owned_ids(store.all_characters()[cid]) and app.items.count("outfit:negligee") == 1, r["entry"]["text"]
        print("服のプレゼント: OK")

        # ---- 5. 本人の服選び: 頼まれていなければ, 日によって普段着が変わる (見るたびには変わらない). 季節に合うものだけ
        st["dress"] = None
        char = app.char(cid)
        days = [datetime(2026, 1, 5, 12) + timedelta(days=i) for i in range(40)]
        picks = [W.self_pick(char, st, d) for d in days]
        names = {p["id"] if p else None for p in picks}
        assert None in names and len(names) >= 2, names
        assert W.self_pick(char, st, days[3]) == picks[3], "同じ日・同じ場面なら同じ"
        assert not any(p and p["seasons"] and "winter" not in p["seasons"] for p in picks), "冬に夏服は着ない"
        assert not any(p and p["bold"] > W.comfort(char, st) for p in picks)
        outs = [W.self_pick(char, st, d, outing=True) for d in days]
        assert all(p is None or p["outing_ok"] for p in outs)
        print("本人の服選び: OK", sorted(n for n in names if n))

        # ---- 6. 本人が自分で服を買う (まれ. お金しだい)
        app.life.her_money(st)["a"] = 200000
        n0 = len(W.owned_ids(store.all_characters()[cid]))
        bought = [W.step(app.char(cid), st, time.time(), 24.0) for _ in range(300)]
        got = [b for b in bought if b]
        assert got and len(got) < 60, len(got)
        c = store.all_characters()[cid]
        assert len(W.owned_ids(c)) > n0 and any(x.get("from") == "self" for x in c["clothes"])
        print("自分で買う: %d 回 / 300 日" % len(got))

        # ---- 7. サンプル画像 (服の一覧に保存)
        jid = app.make_sample("bikini")
        for _ in range(200):
            j = app.job_view(jid)
            if j["status"] in ("done", "error"):
                break
            time.sleep(0.05)
        assert j["status"] == "done", j
        assert W.get("bikini")["sample"] == j["image"] and store.load(store.dpath("outfits.json"))
        pos = app.jobs[jid]["pos"]
        assert pos.index("bikini") < pos.index("black hair") and "full body" in pos, pos
        app.save_settings({"images": {"sample_prompt": "{outfit}, 1boy, solo"}})
        assert W.sample_prompt(W.get("casual"))[0].endswith("1boy, solo")
        # 一覧を画面から保存しても, サンプル画像は消えない
        items = [{k: v for k, v in o.items() if k != "sample"} for o in W.all()]
        W.save_all(items)
        assert W.get("bikini")["sample"] == j["image"]
        print("サンプル画像: OK", j["image"])

        # ---- 8. 一式の靴 (S54): 家の中では描かず, 外では足す. 欄の無い一式は読むときに pos から shoes へ移す (一度だけ)
        from core import wardrobe as wmod
        dflt = store.load(os.path.join(store.DEFAULTS, "outfits.json"))
        bad = [o["id"] for o in dflt if wmod._norm(o)["slot"] == "set" and wmod.SHOE_RE.search(o["pos"])]
        assert not bad, "既定の一式の pos に靴の語が残っている: %s" % bad
        assert sum(1 for o in dflt if o.get("shoes")) == 26
        raw = store.load(store.dpath("outfits.json"))
        for o in raw:
            if o["id"] == "denim":                        # 以前の一覧 (shoes の欄が無い) の形に戻す
                o.pop("shoes", None)
                o["pos"] = "denim jacket, striped shirt, jeans, sneakers"
        raw.append({"id": "my_set", "name": "自作", "slot": "set", "kind": "casual", "outing_ok": True,
                    "pos": "red dress, Black Ankle Boots, ribbon"})
        raw.append({"id": "my_plain", "name": "自作 2", "slot": "set", "kind": "casual", "pos": "white dress, ribbon"})
        raw.append({"id": "my_part", "name": "部品", "slot": "shoes", "kind": "part", "pos": "{color} sneakers", "shoes": "x"})
        store.save(store.dpath("outfits.json"), raw)
        W.load()
        dn = W.get("denim")
        assert dn["pos"] == "denim jacket, striped shirt, jeans" and dn["shoes"] == "sneakers", dn
        assert W.get("my_set")["pos"] == "red dress, ribbon" and W.get("my_set")["shoes"] == "Black Ankle Boots"
        assert W.get("my_plain")["pos"] == "white dress, ribbon" and W.get("my_plain")["shoes"] == ""
        assert W.get("my_part")["pos"] == "{color} sneakers" and "shoes" not in W.get("my_part"), "部品の靴はそのまま"
        W.save_all(W.all())                               # 保存すると shoes の欄が付く
        raw = store.load(store.dpath("outfits.json"))
        for o in raw:
            if o["id"] == "my_set":                       # 欄があれば, あとで pos に靴の語を書いても移さない (二度はしない)
                o["pos"] = "red dress, ribbon, rain boots"
        store.save(store.dpath("outfits.json"), raw)
        W.load()
        assert W.get("my_set")["pos"] == "red dress, ribbon, rain boots" and W.get("my_set")["shoes"] == "Black Ankle Boots"
        # 着せた一式: 家の中は靴なし, 外は靴あり (部品の靴と同じ決まり). 描く場面 (_apply_dress) でも
        char = app.char(cid)
        W.give_to(char, "denim", "player")
        char = app.char(cid)
        st["dress"] = {"id": "denim"}
        assert "sneakers" not in W.worn(char, st, outing=False)["pos"]
        assert W.worn(char, st, outing=True)["pos"] == "denim jacket, striped shirt, jeans, sneakers"
        for outing in (False, True):
            s = {"outing": outing, "fixed_outfit": False, "asleep": False, "plain_outfit": False, "outfit": "casual clothes",
                 "outfit_neg": ""}
            s = app._apply_dress(char, st, s)
            assert ("sneakers" in s["outfit"]) == outing and "jeans" in s["outfit"], (outing, s["outfit"])
        # その人用の上書きの pos も, 靴の語を分ける
        c = store.all_characters()[cid]
        next(x for x in c["clothes"] if x["id"] == "denim")["pos"] = "denim jacket, jeans, white sneakers"
        app.save_character(c)
        char = app.char(cid)
        assert W.worn(char, st, outing=False)["pos"] == "denim jacket, jeans"
        assert W.worn(char, st, outing=True)["pos"] == "denim jacket, jeans, white sneakers"
        # 本人が選んだ一式も同じ (家の中で選んだ一式に靴の語が無い / 外で選んだ靴のある一式は靴を履く)
        st["dress"] = None
        for d in days:
            for outing in (False, True):
                p = W.self_pick(char, st, d, outing=outing)
                if p and p["slot"] == "set":
                    assert bool(wmod.SHOE_RE.search(p["pos"])) == bool(outing and p["shoes"]), (d, outing, p["id"], p["pos"])
        # サンプル画像は外の形 (靴も描く)
        assert "sneakers" in W.sample_prompt(W.get("denim"))[0]
        print("一式の靴: OK")
        print("ALL OK")
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
