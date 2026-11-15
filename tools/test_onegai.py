"""「お願い」まわり: 着替えられる場所・一緒の買い物で買ってあげる・買ったアウターをその場で着てもらう (一時データ, 画像生成なし).
- 着替えは家の中 (あなたの家・相手の家) だけ. 外で会っている間・お出かけ中はできない. 画面の「できる」と本当にできるかが一致する
- アウター (kind = outer) は着せ替えの一式に並ばない・選べない. 出かけるとき, 季節が合えば本人が羽織ることがある (その日ごと)
- 一緒にいる店で買ってあげる: 値札どおり払う・受け取れば相手のもの・断られたら手元に残る・足りない / 借金中 / 店にいないなら買えない
- 買ってあげたアウター: その場で「いま着てみて」と一度だけ聞ける. 着てくれれば, 外にいる間の服装に重なる (寝るまで). 開き直しても続く
- 着てくれるかは季節・機嫌・仲しだい (必ずではない)

    python tools/test_onegai.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, items as items_mod, store, wardrobe as wardrobe_mod  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
wardrobe_mod.Wardrobe.season = staticmethod(lambda dt: "autumn")      # 流す日の季節に左右されないように


def fails(fn, word=None):
    try:
        fn()
    except (ValueError, KeyError) as e:
        assert word is None or word in str(e), e
        return True
    return False


def fresh(app, cid):
    st = app.state(cid)
    st["cooldowns"], st["gifts"], st["dress_asks"] = {}, [], []
    return st


def go_mall(app, cid):
    """同居相手と, 家から一緒にショッピングモールへ (一緒にいる形は home のまま)."""
    st = fresh(app, cid)
    st["override"] = None
    r = app.act("shopping", cid, opts={"place": "mall"})
    assert (st.get("override") or {}).get("place") == "mall", r["entry"]["text"]
    return st


def main():
    random.seed(11)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        P = app.presence
        P.rec()["beat"] = P.rec()["input"] = time.time()
        cid = "hina"
        W = app.wardrobe
        char = app.char(cid)
        st = app.state(cid)
        app.set_params({"affection": 75, "trust": 75, "mood": 70, "energy": 80}, cid)
        ps = app.life.player_state()
        ps["money"] = 200000

        # ---- 1. 着替えられる場所: 一緒にいる形 × 「画面でできる」= 本当にできる
        assert app.bonds.mode(cid) == "home"
        want = {"home": True, "meet": False, "visit": True, "guest": True}
        for mode, ok in want.items():
            if mode == "meet":             # 外で会っている (お出かけの一時シーンがある間だけ続く)
                app.bonds.start(cid, mode)
                app.state(cid)["override"] = {"activity": "shopping", "label": "買い物中", "location": "商店街",
                                              "place": "shopping_street", "outing": True, "until": time.time() + 3600}
            elif mode != "home":
                app.bonds.start(cid, mode)
            st = fresh(app, cid)
            assert app.bonds.mode(cid) == mode, (mode, app.bonds.mode(cid))
            v = app.person_view(cid)["dress"]
            assert v["can"] == ok and v["place_ok"] == ok, (mode, v)
            done = not fails(lambda: app.act("_dress", cid, dress="casual"), "外では着替えられません")
            assert done == ok, (mode, done)
            st["dress"] = st["override"] = None
            if mode != "home":
                app.bonds.end(go_home=False)
        # お出かけ中 (同居相手と出かけた先) も同じ. ポーズ・見せても「外」として扱う
        st = go_mall(app, cid)
        assert app.bonds.mode(cid) == "home" and app.outside_with(cid) and app.posing.outside(cid)
        pv = app.person_view(cid)["posing"]
        assert pv["outside"] and any(not o["here"] for o in pv["items"]), "外では頼めないものがある"
        v = app.person_view(cid)["dress"]
        assert not v["can"] and not v["place_ok"] and "外では" in v["why"], v
        assert fails(lambda: app.act("_dress", cid, dress="casual"), "外では着替えられません")
        assert fails(lambda: app.act("_dress", cid, dress=""), "外では着替えられません"), "おまかせに戻すのも着替え"
        print("着替えられる場所: OK")

        # ---- 2. 一緒にいる店で買ってあげる
        sg = app.person_view(cid)["shopgift"]
        assert sg and sg["place"] == "mall", sg
        ids = [x["id"] for x in sg["items"]]
        assert all(items_mod.CATALOG[i]["giftable"] and "mall" in items_mod.CATALOG[i]["places"] for i in ids)
        assert "outfit:trench" in ids and "outfit:casual" not in ids, "持っている服は並ばない"
        assert "flowers" not in ids, "ここで売っていないものは並ばない"
        m0 = ps["money"]
        r = app.buy_for("cookies", cid)
        assert ps["money"] == m0 - 400 and app.items.count("cookies") == 0, (ps["money"], m0)
        assert "買って、渡した" in r["entry"]["text"] and r["entry"]["money"]["p"] == -400 and not r["bought"]["kept"], r["entry"]
        assert not r.get("tryon"), "アウターでなければ聞けない"
        # ここで売っていない・もう持っている・お金が足りない・借金中: 買えず, 何も変わらない
        m0, inv = ps["money"], dict(app.items.ps()["items"])
        assert fails(lambda: app.buy_for("flowers", cid), "売っていない")
        assert fails(lambda: app.buy_for("outfit:casual", cid), "もう持っています")
        ps["money"] = 100
        assert fails(lambda: app.buy_for("plush", cid), "お金が足りません")
        ps["money"] = m0
        ps["debt"] = 5000
        assert fails(lambda: app.buy_for("plush", cid), "借金")
        ps["debt"] = 0
        assert ps["money"] == m0 and dict(app.items.ps()["items"]) == inv
        # 大胆すぎる服は受け取らない: 払ったが, 品物は手元に残る
        app.set_params({"affection": 25, "trust": 25, "mood": 50}, cid)
        fresh(app, cid)
        r = app.buy_for("outfit:negligee", cid)
        assert "negligee" not in W.owned_ids(app.char(cid)) and app.items.count("outfit:negligee") == 1, r["entry"]["text"]
        assert ps["money"] == m0 - 7000 and r["bought"]["kept"] and "手元に残った" in r["entry"]["text"], r["entry"]["text"]
        app.items.add("outfit:negligee", -1)
        print("買ってあげる: OK /", r["entry"]["text"].replace("\n", " "))

        # ---- 3. アウターを買ってあげる → その場で「いま着てみて」(一度だけ)
        app.set_params({"affection": 90, "trust": 85, "mood": 80}, cid)
        fresh(app, cid)
        assert not app.person_view(cid)["tryon"]
        assert fails(lambda: app.act("_tryon", cid), "いまは頼めません")
        r = app.buy_for("outfit:trench", cid)
        assert "trench" in W.owned_ids(app.char(cid)), r["entry"]["text"]
        assert r["tryon"] and r["tryon"]["id"] == "trench" and app.person_view(cid)["tryon"]["name"] == "トレンチコート"
        assert next(x for x in store.all_characters()[cid]["clothes"] if x["id"] == "trench")["from"] == "player"
        assert not app.scene_at(app.char(cid), st, datetime.now())["outer"], "頼む前から羽織ってはいない (今日買ったばかり)"
        # 開き直しても (再起動しても) 聞ける
        app.save_state(cid)
        app2 = engine.App()
        P2 = app2.presence
        P2.rec()["beat"] = P2.rec()["input"] = time.time()
        assert app2.person_view(cid)["tryon"]["id"] == "trench"
        app, W, st, ps = app2, app2.wardrobe, app2.state(cid), app2.life.player_state()
        got = None
        for _ in range(40):                       # 着てくれるまで (断られたら, もう聞けない → 聞ける状態に戻して繰り返す)
            st["tryon"] = {"id": "trench", "t": time.time(), "place": "mall"}
            st.pop("outer", None)
            r = app.act("_tryon", cid)
            assert not app.person_view(cid)["tryon"], "聞けるのは一度だけ"
            assert fails(lambda: app.act("_tryon", cid), "いまは頼めません")
            if st.get("outer"):
                got = r
                break
        assert got, "仲がよく機嫌もよければ, たいてい着てくれる"
        sc = app.scene_at(app.char(cid), st, datetime.now())
        assert sc["outer"] == "トレンチコート" and sc["outfit"].startswith("beige trench coat"), sc["outfit"]
        assert app.person_view(cid)["dress"]["outer"] == "トレンチコート"
        print("その場で着てもらう: OK /", got["entry"]["text"].replace("\n", " "), "/", sc["outfit"])
        # 家に帰れば羽織っていない. 寝たらおしまい
        st["override"] = None
        sc = app.scene_at(app.char(cid), st, datetime.now())
        assert app.bonds.mode(cid) == "home" and not sc["outer"] and "trench coat" not in sc["outfit"], sc
        st["tryon"] = {"id": "trench", "t": time.time(), "place": "mall"}
        assert not app.person_view(cid)["tryon"], "家に帰ったあとは聞けない"
        sleep = dict(sc, asleep=True)
        orig = app.scene_at
        app.scene_at = lambda *a, **k: sleep
        try:
            app._step(app.char(cid), st, datetime.now(), 0.1)
        finally:
            app.scene_at = orig
        assert "outer" not in st and "tryon" not in st

        # ---- 4. 着てくれるか: 季節・機嫌・仲しだい (必ずではない)
        char = app.char(cid)
        tr, dj = W.get("trench"), W.get("down_jacket")
        now = datetime.now()

        def dist(aff, mood, o=tr, n=400):
            app.set_params({"affection": aff, "mood": mood}, cid)
            out = {}
            for _ in range(n):
                f = W.tryon_feel(char, st, o, now)
                out[f] = out.get(f, 0) + 1
            return out
        hi, lo = dist(90, 80), dist(35, 50)
        yes = lambda d: (d.get("yes", 0) + d.get("glad", 0)) / 400.0    # noqa: E731
        assert 0.6 < yes(hi) < 1.0 and yes(lo) < yes(hi) and lo.get("later", 0) > 0 and hi.get("later", 0) > 0, (hi, lo)
        assert set(dist(90, 80, dj)) == {"season"}, "秋にダウンは着ない"
        assert set(dist(90, 10)) == {"mood"}
        print("着てくれる割合: 深い仲 %.2f / 浅い仲 %.2f" % (yes(hi), yes(lo)))

        # ---- 5. アウターは着せ替えの一式ではない. 出かけるとき, 季節が合えば本人が羽織ることがある (その日ごと)
        app.set_params({"affection": 75, "mood": 70}, cid)
        v = app.person_view(cid)
        assert "trench" not in v["dress"]["items"] and any(o["id"] == "trench" for o in v["wardrobe"])
        assert fails(lambda: app.act("_dress", cid, dress="trench"), "アウターは")
        c = store.all_characters()[cid]
        next(x for x in c["clothes"] if x["id"] == "trench")["t"] = 0        # 前から持っていたことにする
        app.save_character(c)
        char = app.char(cid)
        days = [datetime(2026, 10, 1, 12) + timedelta(days=i) for i in range(60)]
        picks = [W.outer_pick(char, st, d) for d in days]
        n = sum(1 for p in picks if p)
        assert 10 < n < 50 and all(p["id"] == "trench" for p in picks if p), n
        assert W.outer_pick(char, st, days[5]) == picks[5], "同じ日なら同じ"
        W.give_to(char, "down_jacket", "self", 1.0)
        assert not any(p and p["id"] == "down_jacket" for p in (W.outer_pick(app.char(cid), st, d) for d in days)), "季節外は選ばない"
        assert all(W.self_pick(app.char(cid), st, d, outing=True) is None or
                   W.self_pick(app.char(cid), st, d, outing=True)["kind"] != "outer" for d in days), "一式としては選ばない"
        # 本人が羽織るのはお出かけの場面だけ
        base = {"outfit": "x", "outfit_neg": "", "fixed_outfit": False, "asleep": False, "outing": False}
        d = next(d for d, p in zip(days, picks) if p)
        assert not app._apply_outer(app.char(cid), st, dict(base), d)["outer"]
        s = app._apply_outer(app.char(cid), st, dict(base, outing=True), d)
        assert s["outer"] == "トレンチコート" and s["outfit"] == "beige trench coat, open coat, x", s
        assert not app._apply_outer(app.char(cid), st, dict(base, outing=True, fixed_outfit=True), d)["outer"]
        print("アウター: OK（60 日のうち %d 日羽織った）" % n)

        # ---- 6. 店にいなければ買えない (家・相手の家・移動中)
        assert app.person_view(cid)["shopgift"] is None and fails(lambda: app.buy_for("cookies", cid), "店にいません")
        app.bonds.start(cid, "visit")
        assert app.person_view(cid)["shopgift"] is None
        app.bonds.end(go_home=False)
        st = go_mall(app, cid)
        st["override"]["arr"] = time.time() + 600           # まだ向かっている途中
        assert app.person_view(cid)["shopgift"] is None and fails(lambda: app.buy_for("cookies", cid), "店にいません")
        st["tryon"] = {"id": "trench", "t": time.time(), "place": "mall"}
        assert not app.person_view(cid)["tryon"], "移動中は聞けない"
        st["override"]["arr"] = time.time() - 1
        assert app.person_view(cid)["shopgift"] and app.person_view(cid)["tryon"]
        st["tryon"]["t"] -= wardrobe_mod.TRYON_MIN * 60 + 1
        assert not app.person_view(cid)["tryon"], "時間がたてば聞けない"
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
