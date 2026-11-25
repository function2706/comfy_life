"""服屋の多様化の確認 (一時データ, 画像生成なし).
- 服屋 5 種 (ブティック・古着屋・スポーツ用品店・衣装の店・呉服屋) が行き先・営業時間・位置・買い物の時間・話題にそろっている
- 既定の服の「売っている店」は実在する行き先だけ. 値段のある服は, どれも一人の外出で行ける店のどこかで買える (画面で選べる = 本当に買える)
- 店ごとの品ぞろえの性格 (着物・振袖は呉服屋だけ, 衣装はほぼ衣装の店, ブティックに部屋着・下着なし など)
- 古着屋は 6 割の値段. 一人で古着屋へ行くと, 買うものリストの服がその値段で買える. 売っていない店では買わない
- 一緒に買い物に誘うときの行き先にも並ぶ. 誘える行き先 = 行き先の表にあるもの
- いまのセーブの服の一覧へ一度だけ当てる: 以前の既定 (モール・商店街だけ) のままの服は新しい店に, 自分で変えた服・自作の服はそのまま.
  二度目は当てない (あとで自分で店を戻しても, 戻されない)

    python tools/test_clothes_shops.py
"""
import json
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, places, geo, solo, topics, items as items_mod  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
NEW = ("boutique", "used_clothes", "sports_shop", "costume_shop", "kimono_shop")


def defaults():
    return json.load(open(os.path.join(store.DEFAULTS, "outfits.json"), encoding="utf-8"))


def main():
    random.seed(5)
    # ---- 1. 行き先の表
    for k in NEW:
        assert k in places.PLACES and places.PLACES[k]["group"] == "shop" and "shop" in places.PLACES[k]["does"], k
        assert k in places.HOURS and k in geo.RULES and k in solo.SHOP_BASE and "shopping" in topics.PLACE_TAGS[k], k
        assert k in places.OUT_PLACES and places.from_location(places.PLACES[k]["label"]) == k, k
    real = getattr(places, "open_state_real", places.open_state)
    assert not real("boutique", datetime(2026, 10, 21, 13, 0))["open"], "ブティックは水曜休み"
    assert real("boutique", datetime(2026, 10, 22, 13, 0))["open"]
    assert not real("used_clothes", datetime(2026, 10, 22, 11, 0))["open"], "古着屋は昼から"
    assert places.price_rate("used_clothes") == 0.6 and places.price_rate("boutique") == 1.0 and places.price_rate("mall") == 1.0

    # ---- 2. 既定の服の店
    ds = defaults()
    by = {d["id"]: d for d in ds}
    for d in ds:
        assert d["places"] and all(p in places.PLACES for p in d["places"]), d["id"]
        if d["price"] > 0:
            assert any(p in places.OUT_PLACES for p in d["places"]), d["id"]
    sold = {k: [d for d in ds if k in d["places"]] for k in NEW + ("mall", "shopping_street")}
    for k in NEW:
        assert len(sold[k]) >= 4, (k, len(sold[k]))
    assert by["kimono"]["places"] == ["kimono_shop"] and by["furisode"]["places"] == ["kimono_shop"]
    assert all(d["kind"] not in ("lounge", "pajamas", "swim", "costume") and d.get("slot") != "lingerie" for d in sold["boutique"])
    assert all(d["kind"] in ("costume", "work", "pajamas") for d in sold["costume_shop"])
    assert all("costume_shop" in d["places"] for d in ds if d["kind"] == "costume")
    assert all("sports_shop" in d["places"] for d in ds if d["kind"] == "swim")
    assert all(d["kind"] in ("part", "outer", "casual") for d in sold["used_clothes"])
    assert not any("jirai" in d.get("tags", []) for d in sold["shopping_street"])
    print("店ごとの数:", {k: len(v) for k, v in sold.items()})

    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        S, I, P = app.solo, app.items, app.presence
        P.rec()["beat"] = P.rec()["input"] = time.time()
        app.life.player_state()["money"] = 100000
        assert os.path.exists(store.dpath("outfits.json.shops")), "新しいデータにも印"

        # ---- 3. 位置
        for k in NEW:
            base, lo, hi = geo.RULES[k]
            km = app.geo.km(places.HOME_ME if base == "home" else "station", k)
            assert km < hi * 2.5 + 1.0, (k, km)

        # ---- 4. 古着屋で買う (6 割) / 売っていない店では買わない
        iid = next(k for k in items_mod.CATALOG if k == "outfit:p_jeans" or k.startswith("outfit:p_jeans:"))
        it = items_mod.CATALOG[iid]
        assert items_mod.sold_at(it, "used_clothes") and not items_mod.sold_at(it, "costume_shop")
        assert not items_mod.sold_at(items_mod.CATALOG["outfit:maid"], "mall") and items_mod.sold_at(items_mod.CATALOG["outfit:maid"], "costume_shop")
        I.ps()["shop_list"] = {iid: 1}
        bought, _ = I.shop("costume_shop", 1.0, time.time())
        assert not any(b["id"] == iid for b in bought), bought
        I.ps()["shop_list"] = {iid: 1}
        bought, missed = I.shop("used_clothes", 1.0, time.time())
        b = next((b for b in bought if b["id"] == iid), None)
        assert b and b["price"] <= int(it["price"] * 0.6 * 1.15), (bought, missed, it["price"])
        print("古着屋:", it["name"], it["price"], "→", b["price"])

        # ---- 5. 一人でブティックへ (買い物が済む)
        o = next(v for k, v in items_mod.CATALOG.items() if k.startswith("outfit:") and "boutique" in v["places"])
        I.ps()["shop_list"] = {o["id"]: 1}
        S.start("out", place="boutique")
        sl = P.rec()["solo"]
        sl["t"] -= sl["shop_need"] * 60 + 1
        res = S.shop_tick()
        assert res and res["label"] == "ブティック" and any(x["id"] == o["id"] for x in res["bought"]), res
        app.come_back()

        # ---- 6. 一緒の買い物の行き先
        a = next(a for a in app.actions if a["id"] == "shopping")
        assert all(k in a["places"] for k in NEW) and all(p in places.PLACES for p in a["places"]), a["places"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- 7. いまのセーブへ一度だけ
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        old = []
        for d in ds:
            d = dict(d)
            d["places"] = ["mall"] if d["id"] in ("maid", "kimono", "boutique_none") else ["mall", "shopping_street"]
            old.append(d)
        by_old = {d["id"]: d for d in old}
        by_old["p_tshirt"]["places"] = ["bookstore"]                    # 自分で変えた
        by_old["p_jeans"]["places"] = ["mall", "shopping_street", "drugstore"]
        old.append(dict(by_old["p_knit"], id="mine1", places=["mall"]))   # 自作
        os.makedirs(tmp, exist_ok=True)
        store.save(store.dpath("outfits.json"), old)
        store.save(store.dpath("outfits.json.seen"), [d["id"] for d in ds])
        app = engine.App()
        W = app.wardrobe
        got = {o["id"]: o for o in W.all()}
        for k in ("maid", "kimono", "p_knit", "casual", "furisode"):
            assert got[k]["places"] == by[k]["places"], (k, got[k]["places"])
        assert got["p_tshirt"]["places"] == ["bookstore"] and got["p_jeans"]["places"] == ["mall", "shopping_street", "drugstore"]
        assert got["mine1"]["places"] == ["mall"]
        assert json.load(open(store.dpath("outfits.json.shops")))["n"] > 100
        assert "costume_shop" in items_mod.CATALOG["outfit:maid"]["places"], "店の品物にも"
        # 二度目は当てない
        items = store.load(store.dpath("outfits.json"))
        next(o for o in items if o["id"] == "maid")["places"] = ["mall"]
        store.save(store.dpath("outfits.json"), items)
        app2 = engine.App()
        assert app2.wardrobe.get("maid")["places"] == ["mall"]
        print("遡及: 一度だけ当たる")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("OK")


if __name__ == "__main__":
    main()
