"""服の好み (S36. core/wardrobe.py): 初期値 (毎回同じ・性格の系統・範囲)・移行 (一度だけ)・服のタグの補い・合う度 (fit)・
贈ったときの反応 (love / plain / meh / fussy の割合・必ずではない・実際の反応と効き目)・本人が選ぶ / 買うの寄り方・保存の確かめ.

    python tools/test_fashion.py
"""
import collections
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
from core import engine, store, transfer, wardrobe as W_mod  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)

LIKE = {"styles": ["girly"], "colors": ["pink"], "bad_colors": ["green"], "types": {"skirt": 1, "sneakers": -1},
        "fuss": {"shoes": 2, "hat": 0}}


def main():
    random.seed(36)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        W = app.wardrobe
        cid = "hina"

        # ---- 1. 移行: 起動で全部の定義に初期値が書かれる. 二度目は何もしない. 消えていれば一度だけ書き直す
        defs = store.all_characters()
        assert defs and all(isinstance(c.get("fashion"), dict) for c in defs.values()), "起動で初期値が書かれる"
        assert W_mod.migrate_fashion() == 0, "二度目は何もしない"
        c = defs[cid]
        want = W_mod.default_fashion(c)
        assert c["fashion"] == want, (c["fashion"], want)
        c.pop("fashion")
        store.save(store.dpath("characters", cid + ".json"), c)
        assert W_mod.migrate_fashion() == 1 and store.all_characters()[cid]["fashion"] == want, "消えていれば同じ初期値を一度だけ"
        print("移行: OK", len(defs), "人")

        # ---- 2. 初期値: 毎回同じ・性格の 1 つ目の系統は必ず・範囲
        cnt = collections.Counter()
        for pid, (first, second) in W_mod.PERSONA_STYLE.items():
            for i in range(60):
                ch = {"id": "x%d" % i, "persona_id": pid, "age": 18 + i % 30}
                f = W_mod.default_fashion(ch)
                assert f == W_mod.default_fashion(dict(ch)), "毎回同じ"
                assert f["styles"][0] == first and 1 <= len(f["styles"]) <= 2 and len(set(f["styles"])) == len(f["styles"]), f
                assert 1 <= len(f["colors"]) <= 3 and len(f["bad_colors"]) <= 2 and not set(f["colors"]) & set(f["bad_colors"]), f
                assert all(v in (1, -1) for v in f["types"].values()) and all(v in (0, 2) for v in f["fuss"].values()), f
                assert 2 in f["fuss"].values() and 0 in f["fuss"].values(), f
                assert f == W_mod.norm_fashion(f), "初期値は確かめを通る"
                if len(f["styles"]) == 2:
                    cnt[f["styles"][1] == second] += 1
        assert cnt[True] > cnt[False], cnt
        assert W_mod.default_fashion({"id": "a", "persona_id": "genki"}) != W_mod.default_fashion({"id": "b", "persona_id": "genki"}) or \
            W_mod.default_fashion({"id": "c", "persona_id": "genki"}) != W_mod.default_fashion({"id": "a", "persona_id": "genki"}), "人で違う"
        likes_fashion = W_mod.default_fashion({"id": "q", "persona_id": "sadist"})      # 好きなものに服
        assert list(likes_fashion["fuss"].values()).count(2) == 2, likes_fashion
        print("初期値: OK 2 つ目が性格の寄せ %d / ほか %d" % (cnt[True], cnt[False]))

        # ---- 3. 確かめ: 知らない語・数の上限・好きと苦手の重なり
        n = W_mod.norm_fashion({"styles": ["x", "girly", "mode", "street"], "colors": ["red", "gold", "pink", "white", "blue"],
                                "bad_colors": ["red", "green", "yellow", "purple"], "types": {"skirt": "1", "x": 1, "mini": 0, "boots": -3},
                                "fuss": {"shoes": 2, "hat": 1, "top": 0, "bag": 2}})
        assert n == {"styles": ["girly", "mode"], "colors": ["red", "pink", "white"], "bad_colors": ["green", "yellow"],
                     "types": {"skirt": 1, "boots": -1}, "fuss": {"shoes": 2, "top": 0}}, n
        c = store.all_characters()[cid]
        c["fashion"] = {"styles": ["nope"], "colors": ["pink", "pink2"], "bad_colors": ["pink"]}
        app.save_definition(c)
        assert store.all_characters()[cid]["fashion"] == {"styles": [], "colors": ["pink"], "bad_colors": [], "types": {}, "fuss": {}}
        print("確かめ: OK")

        # ---- 4. 服のタグ: 既定に付いている. タグの無い以前の一覧は, 読むときに既定で補う (データは書き換えない)
        assert set(W.get("p_sneakers")["tags"]) >= {"sneakers", "sporty"} and W.get("maid")["tags"] == []
        raw = store.load(store.dpath("outfits.json"))
        for o in raw:
            o.pop("tags", None)
        raw.append({"id": "my_own", "name": "自作", "pos": "{color} vest", "slot": "top"})
        store.save(store.dpath("outfits.json"), raw)
        W.load()
        assert "skirt" in W.get("p_pleated")["tags"] and W.get("my_own")["tags"] == [], "既定のタグで補う"
        assert all("tags" not in o for o in store.load(store.dpath("outfits.json"))), "データは書き換えない"
        items = W.all()
        next(o for o in items if o["id"] == "my_own")["tags"] = ["girly", "nope", "mini"]
        W.save_all(items)
        assert W.get("my_own")["tags"] == ["girly", "mini"], "保存で知らない語は捨てる"
        assert "skirt" in next(o for o in store.load(store.dpath("outfits.json")) if o["id"] == "p_pleated")["tags"], "保存したら書かれる"
        assert set(W.catalog_view()["styles"]) == set(W_mod.STYLES) and W.catalog_view()["fuss"]
        print("服のタグ: OK")

        # ---- 5. 合う度: 系統・種類・色. こだわる部位は大きく, どうでもいい部位は小さく
        char = dict(store.all_characters()[cid], fashion=LIKE)
        good = W_mod.fit(char, W.get("p_pleated:pink"))
        bad = W_mod.fit(char, W.get("p_sneakers:green"))
        hat = W_mod.fit(char, W.get("p_beret:pink"))
        assert good > 0.5 and bad < -1.0 and 0 < hat <= 0.3, (good, bad, hat)
        assert W_mod.fit(char, W.get("p_pleated:green")) < good and W_mod.fit(char, W.get("p_pleated"), color="") > 0
        assert W_mod.fit(char, W.get("maid")) == 0, "タグの無い服は好みで動かない"
        assert W_mod.fuss_of(char, "onepiece") == W_mod.fuss_of(char, "top") == 1 and W_mod.fuss_of(char, "set") == 1
        print("合う度: OK", round(good, 2), round(bad, 2), round(hat, 2))

        # ---- 6. 贈られたとき: 割合 (合っても必ず love ではない・外れても必ず fussy ではない)
        st = app.state(cid)
        app.set_params({"affection": 70, "trust": 70, "mood": 70}, cid)
        now = time.time()
        r = random.Random(1)

        def share(key):
            return collections.Counter(W.gift_feel(char, st, key, now, rnd=r) for _ in range(2000))
        g = share("p_pleated:pink")
        assert 0.5 < g["love"] / 2000.0 < 0.98 and g["yes"] > 0 and not g["fussy"], g
        b = share("p_sneakers:green")
        assert 0.6 < b["fussy"] / 2000.0 < 0.99 and b["yes"] > 0 and not b["love"], b
        m = share("p_tshirt:green")                          # ふつうの部位の外れ
        assert m["meh"] > 0 and not m["fussy"], m
        assert share("p_beret:green") == {"plain": 2000}, "どうでもいい部位は何でも受け取る"
        assert set(share("maid")) == {"yes"} or share("maid")["bold_no"] >= 0
        print("贈られたときの割合: OK love %d / fussy %d / meh %d" % (g["love"], b["fussy"], m["meh"]))

        # ---- 7. 実際に贈る: 反応と効き目 (外れても受け取る = 持っている服に入る)
        store.save_character(dict(store.all_characters()[cid], fashion=LIKE))
        old = W.gift_feel
        try:
            for feel, key, word in (("love", "p_pleated:pink", "好きな感じ"), ("fussy", "p_sneakers:green", "自分で選びたい"),
                                    ("meh", "p_tshirt:green", "好みじゃなかった"), ("plain", "p_beret:green", "使わせて")):
                W.gift_feel = lambda *a, _f=feel, **k: _f
                st = app.state(cid)
                st["gifts"], st["cooldowns"] = [], {}
                app.set_params({"affection": 70, "trust": 70, "mood": 60}, cid)
                m0 = app.state(cid)["params"]["mood"]
                app.items.add("outfit:" + key)
                res = app.give_item("outfit:" + key, cid)
                text = (res.get("entry") or {}).get("text", "")
                assert word in text, (feel, text)
                assert key in W.owned_ids(store.all_characters()[cid]), "受け取って持っている (%s)" % feel
                m1 = app.state(cid)["params"]["mood"]
                assert (m1 > m0) if feel in ("love", "plain") else (m1 <= m0), (feel, m0, m1)
        finally:
            W.gift_feel = old
        print("贈る反応: OK")

        # ---- 8. 本人が選ぶ: 好みの部品が多く選ばれるが, 外れも選ばれる. 外れた贈り物は「贈られたから」で寄せない
        c = store.all_characters()[cid]
        c["fashion"] = LIKE
        c["clothes"] = [x for x in c.get("clothes") or [] if W.get(x.get("id")) and W.get(x["id"])["slot"] in ("set", "outer")]
        for key in ("p_pleated:pink", "p_wide_pants:green", "p_blouse:white", "p_sneakers:green", "p_mary_janes:pink"):
            i, col = W_mod.split_key(key)
            c["clothes"].append({"id": i, "color": col, "from": "default"})
        store.save_character(c)
        char = store.all_characters()[cid]
        st = app.state(cid)
        days = [datetime(2026, 4, 1, 12) + timedelta(days=d) for d in range(500)]
        picked = collections.Counter()
        for d in days:
            o = W.self_pick(char, st, d, outing=True)
            if o and o.get("coord"):
                for sl, key in o["coord"].items():
                    picked[key] += 1
        assert picked["p_pleated:pink"] > picked["p_wide_pants:green"] > 0, picked
        assert picked["p_mary_janes:pink"] > picked["p_sneakers:green"] > 0, picked
        print("本人が選ぶ: OK", dict(picked))

        # ---- 9. 本人が買う: 好きな色・系統に寄るが, ほかも買う
        app.life.her_money(st)["a"] = 10 ** 8
        bought = []
        for i in range(150):
            o = W.step(char, st, time.time(), 24 * 400)
            if o:
                bought.append(o)
            char = store.all_characters()[cid]
        cols = collections.Counter(o.get("color") for o in bought if o.get("color"))
        assert len(bought) > 100 and cols["pink"] > cols["green"] and cols["pink"] > 3 * cols.get("red", 0) / 2, cols
        sty = sum(1 for o in bought if "girly" in o.get("tags") or [])
        assert sty > len(bought) * 0.3 and sty < len(bought), (sty, len(bought))
        print("本人が買う: OK", len(bought), "着 色", dict(cols.most_common(4)), "ガーリー", sty)

        # ---- 10. 読み込みの「同じ人か」は服の好みの差を見ない. 未登録の人は初期値
        assert "fashion" in transfer.IGNORE_KEYS
        x = {"id": "zz", "persona_id": "cool"}
        assert W_mod.fashion_of(x) == W_mod.default_fashion(x) and "fashion" not in x
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
