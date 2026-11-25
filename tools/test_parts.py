"""服の部品と色 (S30. core/wardrobe.py): 区分の補い・色ごとの品・文の服装の色の固定・いつもの服の部品・部品の組み合わせ (コーデ)・
着せ替え・贈る・一緒の店で買う・本人の組み合わせ・本人が買う・画面で押せる = できる.

    python tools/test_parts.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, BASE)
sys.path.insert(0, HERE)
from core import engine, items as items_mod, store, wardrobe as W_mod  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(11)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        W = app.wardrobe
        cid = "hina"

        # ---- 1. 区分の補い (データは書き換えない) と, 色ごとの品
        allo = W.all()
        slots = {o["id"]: o["slot"] for o in allo}
        assert slots["casual"] == "set" and slots["trench"] == "outer" and slots["bikini"] == "set", slots
        assert sum(1 for o in allo if o["slot"] == "outer") == 14 and sum(1 for o in allo if o["slot"] == "set") == 63
        parts = [o for o in allo if o["slot"] not in ("set", "outer")]
        assert len(parts) == 106 and all(o["kind"] == "part" for o in parts)
        # 既定の服の形 (S37): 区分・タグ・色・季節が正しい. 色付きの部品は {color} を持つ. id は重ならない
        raw_def = store.load(os.path.join(store.DEFAULTS, "outfits.json"))
        assert len({o["id"] for o in raw_def}) == len(raw_def), "既定の id が重なっている"
        for o in raw_def:
            n = W_mod._norm(o)
            assert o.get("kind") in W_mod.KINDS and n["tags"] == list(o.get("tags") or []), ("タグ・種類", o["id"])
            assert all(c in W_mod.COLORS for c in o.get("colors") or []) and all(x in W_mod.SEASONS for x in o.get("seasons") or []), o["id"]
            if o.get("kind") == "part":
                assert o.get("slot") in W_mod.SLOTS and o["slot"] not in ("set", "outer"), o["id"]
                assert not o.get("colors") or "{color}" in o["pos"], ("売る色を絞るなら {color} が要る", o["id"])
        # 部品の名前が別の部品に横取りされない: 各部品の名前 (pos の先頭) だけの文は, その部品に当たる
        for o in parts:
            for t in W_mod._base_tags(o):
                hit = W.find_parts(t)[0][1]
                assert hit and hit["id"] == o["id"], ("名前の横取り", t, o["id"], hit and hit["id"])
        raw = store.load(store.dpath("outfits.json"))
        assert "slot" not in next(o for o in raw if o["id"] == "casual"), "以前の服のデータは書き換えない"
        assert "outfit:p_pleated:navy" in items_mod.CATALOG and "outfit:p_pleated" not in items_mod.CATALOG
        it = items_mod.CATALOG["outfit:p_pleated:navy"]
        assert it["name"] == "プリーツスカート（紺）" and it["variant_of"] == "outfit:p_pleated" and it["giftable"], it
        assert "navy blue pleated skirt" == W.get("p_pleated:navy")["pos"]
        jeans = [k for k in items_mod.CATALOG if k.startswith("outfit:p_jeans:")]
        assert len(jeans) == 6 and "outfit:p_jeans:pink" not in items_mod.CATALOG, "売る色を絞れる"
        assert len({items_mod.CATALOG[k]["price"] for k in items_mod.CATALOG if k.startswith("outfit:p_knit:")}) == 1, "値段は色で変えない"
        assert "outfit:casual" in items_mod.CATALOG and "outfit:trench" in items_mod.CATALOG
        assert W.get("p_pleated:gold") is None and W.get("casual:navy") is None
        print("区分と色の品: OK", len(parts), "部品 /", sum(1 for k in items_mod.CATALOG if k.startswith("outfit:")), "品")

        # ---- 2. 文の服装の色: 部品の語に, その人の色を付ける (毎回同じ・色の語があればそのまま・語の途中では当たらない)
        char = app.char(cid)
        a = W.resolve(char, "casual clothes, knit sweater, long skirt")
        assert a == W.resolve(char, "casual clothes, knit sweater, long skirt"), "毎回同じ"
        toks = a.split(", ")
        assert toks[0] == "casual clothes" and toks[1] != "knit sweater" and toks[1].endswith("knit sweater"), a
        assert W.resolve(char, "white blouse, maid headdress") == "white blouse, maid headdress", "色の語・語の途中"
        assert W.resolve(char, "turtleneck sweater").endswith("turtleneck sweater") and \
            W.find_parts("turtleneck sweater")[0][1]["id"] == "p_turtleneck", "長く当たるものを優先"
        assert W.find_parts("black mini skirt")[0][1]["id"] == "p_miniskirt", "別名"
        assert W.find_parts("plaid mini skirt")[0][1]["id"] == "p_plaid_mini", "長い名前が優先 (S37)"
        assert W.find_parts("pantyhose")[0][1]["id"] == "p_pantyhose" and W.find_parts("pants")[0][1]["id"] == "p_wide_pants"
        assert W.find_parts("sports bra")[0][1] is None, "ランジェリーは文からは当てない"
        other = dict(char, id="someone_else", clothes=[])
        cols = {W.resolve(dict(other, id="x%d" % i), "pleated skirt") for i in range(40)}
        assert len(cols) >= 4, "人によって色は違う"
        neutral = sum(1 for i in range(400) if W_mod.COLORS[W._color({"id": "n%d" % i}, W.get("p_pleated"))][2])
        assert 0.55 < neutral / 400.0 < 0.8, neutral
        print("文の服装の色: OK", a)

        # ---- 3. いつもの服・お出かけ着の文の部品を, その色で持たせる (文ごとに一度だけ)
        c = store.all_characters()[cid]
        own = {x["id"]: x.get("color") for x in c["clothes"]}
        for pid in ("p_knit", "p_long_skirt", "p_blouse", "p_cardigan", "p_shoulder_bag"):
            assert pid in own and own[pid] in W_mod.COLORS, (pid, own)
        assert own["p_blouse"] == "white", "文に色があればその色"
        n = len(c["clothes"])
        assert W.seed_usual(c) == 0 and len(store.all_characters()[cid]["clothes"]) == n, "二度は足さない"
        app2 = engine.App()                       # 起動し直しても増えない
        assert len(store.all_characters()[cid]["clothes"]) == n
        app = app2
        W = app.wardrobe
        char = app.char(cid)
        # 持っている色が, 文の色になる
        assert W.resolve(char, "long skirt") == "%s long skirt" % W_mod.COLORS[own["p_long_skirt"]][1]
        sc = app.scene_at(char, app.state(cid), datetime(2026, 1, 6, 12))
        print("いつもの服の部品: OK", sorted(own))

        # ---- 4. 組み合わせ (コーデ): 区分の確かめ・ワンピースは上下を外す・靴は外だけ・ランジェリーは上が無いときだけ・大胆さ
        W.give_to(char, "p_sneakers:white", "default")
        W.give_to(char, "p_lingerie:black", "default")
        W.give_to(char, "p_dress:navy", "default")
        W.give_to(char, "p_miniskirt:black", "default")
        char = app.char(cid)
        top = "p_blouse:white"
        skirt = "p_long_skirt:" + own["p_long_skirt"]
        co = W.norm_coord(char, {"top": top, "bottom": skirt, "shoes": "p_sneakers:white", "lingerie": "p_lingerie:black"})
        for bad, err in (({"top": "p_pleated:navy"}, KeyError), ({"bottom": top}, KeyError), ({"outer": "trench"}, ValueError),
                         ({}, ValueError), ({"top": "casual"}, KeyError)):
            try:
                W.norm_coord(char, bad)
                raise AssertionError("通ってしまった: %s" % bad)
            except err:
                pass
        assert W.norm_coord(char, {"top": top, "onepiece": "p_dress:navy"}) == {"onepiece": "p_dress:navy"}
        home = W.coord_view(char, co, outing=False)
        out = W.coord_view(char, co, outing=True)
        assert "sneakers" not in home["pos"] and "white sneakers" in out["pos"], (home["pos"], out["pos"])
        assert "bra" not in home["pos"] and home["bold"] == 0 and home["outing_ok"], home
        under = W.coord_view(char, {"bottom": skirt, "lingerie": "p_lingerie:black"})
        assert "black bra" in under["pos"] and under["bold"] == 3 and not under["outing_ok"], under
        assert W.coord_bold(char, {"top": top, "bottom": "p_miniskirt:black"}) == 1
        assert home["pos"].index("blouse") < home["pos"].index("skirt"), "区分の順"
        print("組み合わせ: OK", home["name"])

        # ---- 5. 着せ替え: 部品で合わせる (画面の形のまま) → 描く服装・反応の条件・寝たら戻る
        st = app.state(cid)
        app.set_params({"affection": 70, "trust": 70, "mood": 70}, cid)
        st["dress"], st["dress_asks"], st["cooldowns"] = None, [], {}
        v = app.state_view(cid)["with"]
        assert {o["key"] for o in v["wardrobe"]} >= {top, skirt, "p_sneakers:white"}
        assert not any(o["slot"] != "set" and o["kind"] != "outer" and o["key"] not in v["dress"]["items"] for o in v["wardrobe"])
        app.act("_dress", cid, dress={"coord": {"top": top, "bottom": skirt, "shoes": "p_sneakers:white"}})
        assert st["dress"]["coord"] == {"top": top, "bottom": skirt, "shoes": "p_sneakers:white"}, st["dress"]
        sc = app.scene_at(char, st, datetime.now())
        assert "white blouse" in sc["outfit"] and "long skirt" in sc["outfit"] and "sneakers" not in sc["outfit"], sc["outfit"]
        v = app.state_view(cid)["with"]
        assert v["dress"]["current"] == "coord" and v["dress"]["coord"] == st["dress"]["coord"]
        ctx = app.context(char, st, datetime.now())
        assert ctx["outfit"] == "coord"
        try:
            app.act("_dress", cid, dress="p_blouse:white")
            raise AssertionError("部品を一式として着られた")
        except ValueError:
            pass
        # 一式は今までどおり
        app.act("_dress", cid, dress="pajamas")
        assert st["dress"] == {"id": "pajamas", "t": st["dress"]["t"]}
        # 下着だけの組み合わせは大胆 (仲が浅いと断られ, 着替えない)
        app.set_params({"affection": 20, "trust": 20, "mood": 50}, cid)
        st["dress"], st["dress_asks"], st["cooldowns"] = None, [], {}
        app.act("_dress", cid, dress={"coord": {"lingerie": "p_lingerie:black"}})
        assert not st.get("dress"), "断られたら着替えない"
        print("着せ替え（部品）: OK", sc["outfit"])

        # ---- 6. 外: 組み合わせは外では靴まで. 下着だけでは外に着ていかない
        st["dress"] = {"coord": {"top": top, "bottom": skirt, "shoes": "p_sneakers:white"}, "t": time.time()}
        s = app._apply_dress(char, st, dict(app._norm_scene({"outing": True, "outfit": "x"}, char, "override"), plain_outfit=False),
                             datetime.now())
        assert "white sneakers" in s["outfit"], s["outfit"]
        st["dress"] = {"coord": {"bottom": skirt, "lingerie": "p_lingerie:black"}, "t": time.time()}
        s = app._apply_dress(char, st, dict(app._norm_scene({"outing": True, "outfit": "x"}, char, "override"), plain_outfit=False),
                             datetime.now())
        assert "bra" not in s["outfit"], "下着だけで外へは出ない (お出かけ着のまま)"
        st["dress"] = None
        print("外の組み合わせ: OK")

        # ---- 7. 贈る: 色を選んで買った部品 → 持っている服に. 同じ色は贈れない・別の色は贈れる
        app.set_params({"affection": 70, "trust": 70, "mood": 70}, cid)
        st["gifts"], st["cooldowns"] = [], {}
        app.items.add("outfit:p_pleated:navy")
        app.give_item("outfit:p_pleated:navy", cid)
        c = store.all_characters()[cid]
        x = next(x for x in c["clothes"] if x["id"] == "p_pleated")
        assert x["color"] == "navy" and x["from"] == "player", x
        assert "p_pleated:navy" in W.owned_ids(c)
        app.items.add("outfit:p_pleated:navy")
        try:
            app.give_item("outfit:p_pleated:navy", cid)
            raise AssertionError("持っている色を贈れた")
        except ValueError:
            app.items.add("outfit:p_pleated:navy", -1)
        st["gifts"], st["cooldowns"] = [], {}
        app.items.add("outfit:p_pleated:red")
        app.give_item("outfit:p_pleated:red", cid)
        assert {"p_pleated:navy", "p_pleated:red"} <= set(W.owned_ids(store.all_characters()[cid])), "同じ部品の別の色も持てる"
        # 一緒の店の一覧: 持っている色は出ず, 持っていない色は出る (まとめるための印つき)
        old_here = app.here_shop
        app.here_shop = lambda _cid, _now=None: "mall"
        import core.places as places_mod
        old_open = places_mod.open_state
        places_mod.open_state = lambda pl, dt: {"open": True}
        try:
            gv = app.shop_gift_view(app.char(cid), st)
        finally:
            app.here_shop = old_here
            places_mod.open_state = old_open
        ids = {x["id"] for x in gv["items"]}
        assert "outfit:p_pleated:navy" not in ids and "outfit:p_pleated:white" in ids, "持っている色は並べない"
        y = next(x for x in gv["items"] if x["id"] == "outfit:p_pleated:white")
        assert y["variant_of"] == "outfit:p_pleated" and y["color"] == "white" and y["slot"] == "bottom", y
        print("贈る（色）: OK")

        # ---- 8. 本人の組み合わせ (頼まれていないとき): 持っている部品から組む. 色の合わせ・季節・大胆さの上限
        char = app.char(cid)
        st["dress"] = None
        days = [datetime(2026, 4, 6, 12) + timedelta(days=i) for i in range(160)]
        picks = [W.self_pick(char, st, d, outing=True) for d in days]
        cos = [p for p in picks if p and p.get("id") == "coord"]
        assert len(cos) >= 10, len(cos)
        for p in cos:
            ps = W.coord_items(char, p["coord"])
            sl = [o["slot"] for o in ps]
            assert ("onepiece" in sl) or ("top" in sl and "bottom" in sl), sl
            assert "lingerie" not in sl and all(o["bold"] <= W.comfort(char, st) for o in ps), sl
            assert p["outing_ok"]
        assert any("sneakers" in p["pos"] for p in cos), "外では靴も"
        homes = [W.self_pick(char, st, d) for d in days]
        assert not any(p and p.get("id") == "coord" and "sneakers" in p["pos"] for p in homes), "家では靴を描かない"
        assert W.self_pick(char, st, days[5], outing=True) == picks[5], "同じ日・同じ場面なら同じ"
        # 色の合わせ: 違う有彩色どうしは選ばれにくい (赤の上に, 青と黒のジーンズのどちらを合わせるか)
        test_c = {"id": "mixer", "clothes": [{"id": "p_tshirt", "color": "red"}, {"id": "p_jeans", "color": "black"},
                                               {"id": "p_jeans", "color": "blue"}], "persona_id": char.get("persona_id")}
        lows = [W._pick_coord(test_c, st, random.Random(i), "spring", False, 1, 40)["coord"]["bottom"] for i in range(400)]
        red = lows.count("p_jeans:blue") / 400.0
        assert 0.12 < red < 0.35, red
        print("本人の組み合わせ: OK %d / %d 日, 赤と青の組み合わせ %.2f" % (len(cos), len(days), red))

        # ---- 9. 本人が買う: 部品も色つきで. 持っている色は買わない
        app.life.her_money(st)["a"] = 300000
        got = [W.step(app.char(cid), st, time.time(), 24.0) for _ in range(800)]
        got = [g for g in got if g]
        c = store.all_characters()[cid]
        mine = [x for x in c["clothes"] if x.get("from") == "self"]
        assert got and any(x.get("color") for x in mine), mine
        keys = W.owned_ids(c)
        assert len(keys) == len(set(keys)), "同じ品を二つ持たない"
        assert not any(x["id"] == "p_lingerie" and x.get("from") == "self" for x in c["clothes"])
        print("本人が買う: OK", len(got), "回")

        # ---- 10. いつもの服が空のキャラでも服装が入る
        c = store.all_characters()[cid]
        keep = c.get("outfit_default")
        char = dict(app.char(cid), outfit_default="", schedule=[], default_activity={})
        s = app._base_scene(char, datetime(2026, 1, 6, 15))
        assert s["outfit"] == W.get("casual")["pos"], s
        assert keep
        print("いつもの服が空: OK", s["outfit"])

        # ---- 11. 設定から一覧を保存しても, 区分・色・別名は残る
        items = [dict(o) for o in W.all()]
        W.save_all(items)
        assert W.get("p_jeans")["colors"] and W.get("p_miniskirt")["match"] == ["mini skirt"] and W.get("p_tote")["slot"] == "acc"
        assert "outfit:p_jeans:blue" in items_mod.CATALOG
        print("一覧の保存: OK")

        # ---- 12. 書き出し・読み込み: この版より前に書き出した同じ人 (いつもの服の部品が無い) を, 別の人にしない
        from core import transfer
        c = store.all_characters()[cid]
        before = dict(c, clothes=[x for x in c["clothes"] if not (x.get("color") and x.get("from") == "default" and not x.get("t"))])
        before.pop("usual_seen", None)
        assert len(before["clothes"]) < len(c["clothes"]) and transfer.same_person(c, before)
        assert not transfer.same_person(c, dict(before, clothes=before["clothes"][:-1])), "持っている服が本当に違えば別の人"
        print("読み込みの同じ人: OK")

        # ---- 13. 画面 (S35): 色の見本・衣装の区別・部品のサンプル画像は無地の既定で上下をそろえる
        cv = W.catalog_view()
        assert all(v.get("hex", "").startswith("#") for v in cv["colors"].values()) and set(cv["colors"]) == set(W_mod.COLORS)
        assert items_mod.CATALOG["outfit:p_jeans:blue"]["okind"] == "part"
        cos = next(o for o in W.all() if o["kind"] == "costume" and o["price"] > 0)
        assert items_mod.CATALOG["outfit:" + cos["id"]]["okind"] == "costume"
        for oid, want, no in (("p_jeans", "t-shirt", "long pants"), ("p_miniskirt", "t-shirt", "long pants")):
            pos, _ = W.sample_prompt(W.get(oid))
            assert want in pos and no not in pos and "{color}" not in pos, (oid, pos)
        tops = [o for o in W.all() if o["slot"] == "top"]
        pos, _ = W.sample_prompt(tops[0])
        assert "long pants" in pos and "t-shirt" not in pos.replace(tops[0]["pos"].replace("{color}", "white"), ""), pos
        for sl in ("hat", "shoes", "acc", "legwear"):
            o = next(o for o in W.all() if o["slot"] == sl)
            pos, _ = W.sample_prompt(o)
            assert "t-shirt" in pos and "long pants" in pos, (sl, pos)
        for o in (cos, next(o for o in W.all() if o["slot"] == "onepiece"), next(o for o in W.all() if o["slot"] == "outer")):
            pos, _ = W.sample_prompt(o)
            assert "plain grey t-shirt" not in pos and "plain black long pants" not in pos, (o["id"], pos)
        print("画面の色の見本・サンプル画像: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
