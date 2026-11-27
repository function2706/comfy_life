"""ポーズ・見せて (core/posing.py): 頼んだときの受け入れ・大人だけ・相手からの行動と感想・好みの学習・持ちかけと対価・一覧の既定の追従.

    python tools/test_posing.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, posing as PO, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(11)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        cid = "hina"
        st, char = app.state(cid), app.char(cid)
        assert char.get("age") == 20 and app.bonds.together(cid)
        W, P = app.wardrobe, app.posing

        # ---- 1. 一覧: 既定の項目 (服を着たまま. 裸・未成年を思わせる語は入れない)
        poses, shows = P.all("pose"), P.all("show")
        assert len(poses) >= 15 and len(shows) >= 10
        bad = ("nude", "nipple", "pussy", "loli", "child", "naked", "sex")
        assert not any(w in o["pos"].lower() for o in P.all() for w in bad)
        assert all(o["pos"].count("focus") or o["type"] == "pose" or "nape" in o["pos"] or "cleavage" in o["pos"]
                   or "collarbone" in o["pos"] for o in shows)
        print("一覧: ポーズ %d / 見せて %d" % (len(poses), len(shows)))

        # ---- 2. 頼む: 大胆なほど・仲が浅いほど断られる. 仲が深くても断られることがある. しつこいと怒る
        def ok_rate(pid, aff, trust, mood=60, outside=False):
            o = P.get(pid)
            n = 0
            for _ in range(300):
                st["pose_asks"] = []
                app.set_params({"affection": aff, "trust": trust, "mood": mood}, cid)
                n += W.accept(char, st, o, time.time(), outside=outside, asks_key="pose_asks") not in ("refuse", "angry")
            return n / 300.0
        assert ok_rate("v_sign", 10, 10) == 1.0, "ふつうのポーズは断られない"
        low, high = ok_rate("thighs", 30, 30), ok_rate("thighs", 85, 85)
        hips_high = ok_rate("hips", 85, 85)
        assert low < 0.1 and 0.5 < high < 1.0 and hips_high < high, (low, high, hips_high)
        st["pose_asks"] = []
        app.set_params({"affection": 20, "trust": 20, "mood": 40}, cid)
        seq = [W.accept(char, st, P.get("hips"), time.time(), asks_key="pose_asks") for _ in range(4)]
        assert seq[0] == "refuse" and "angry" in seq[2:], seq
        # コマンド: 受けてくれたら, そのポーズの画像. 断られたら画像のプロンプトは変わらない
        st["pose_asks"], st["cooldowns"] = [], {}
        app.set_params({"affection": 90, "trust": 90, "mood": 70}, cid)
        r = app.act("_pose", cid, opts={"pose": "v_sign"})
        assert "loli" not in r["entry"]["neg"], "Negative には何も足さない (判定は年齢だけ)"
        assert "double v" not in r["entry"]["pos"] and ", v," in ", " + r["entry"]["pos"] + ",", r["entry"]["pos"]
        app.set_params({"affection": 15, "trust": 15, "mood": 40}, cid)
        st["pose_asks"] = []
        r = app.act("_show", cid, opts={"pose": "hips"})
        assert "ass focus" not in r["entry"]["pos"] and not st.get("pose_asks")[-1]["ok"], r["entry"]["text"]   # 断られた
        try:
            app.act("_pose", cid, opts={"pose": "thighs"})
            raise AssertionError("見せてをポーズで頼めた")
        except KeyError:
            pass
        print("頼む: 太もも 浅い仲 %.2f / 深い仲 %.2f, お尻 深い仲 %.2f" % (low, high, hips_high))

        # ---- 3. 大人だけ: 判定は年齢の欄だけ. 18 未満ならできない (未入力は大人として扱う)
        c = store.all_characters()[cid]
        c["age"] = None
        app.save_character(c)
        assert app.person_view(cid)["posing"]["can"], "未入力は大人として扱う"
        for age in (17, "15"):
            c["age"] = age
            app.save_character(c)
            try:
                app.act("_pose", cid, opts={"pose": "v_sign"})
                raise AssertionError("年齢 %s でポーズを頼めた" % age)
            except ValueError as e:
                assert "18 歳未満" in str(e)
            assert not app.person_view(cid)["posing"]["can"]
        c["age"] = 20
        app.save_character(c)
        char = app.char(cid)
        print("大人だけ: OK")

        # ---- 4. 好みの学習: 頼んだもの (+1)・感想 (褒める・もっと見たい +, 止める −). 相手の選び方がそちらに寄る (確定しない)
        st["prefs"] = {}
        for _ in range(3):
            P.learn(st, "pose:paw_pose", 1.0)
        P.learn(st, "pose:waving", -3.0)
        app.set_params({"heart": 70, "affection": 85, "mood": 80}, cid)
        char["persona_id"] = "itazura"
        picks = Counter(P.pick(char, st).get("id") for _ in range(2000))
        assert picks["paw_pose"] > picks["v_sign"] * 2 and picks["waving"] < picks["v_sign"], picks.most_common(5)
        assert len(picks) > 8, "好みに寄るだけで, ほかも選ぶ"
        print("学習で寄る: 猫のポーズ %d / ピース %d / 手を振る %d" % (picks["paw_pose"], picks["v_sign"], picks["waving"]))

        # ---- 5. 相手から: その気 (ドキドキ・好感度・機嫌・恥じらい) しだい. 二人きりのときだけ
        assert P.eagerness(char, st) > 0.8
        app.set_params({"heart": 0, "affection": 30, "mood": 40}, cid)
        assert P.eagerness(char, st) == 0.0
        app.set_params({"heart": 80, "affection": 90, "mood": 90}, cid)
        char["persona_id"] = "uchiki"
        assert P.eagerness(char, st) < 1.5
        char["persona_id"] = "itazura"
        st["pose_offer"], st["approach"] = None, None
        fired = 0
        for k in range(400):
            st["pose_offer"] = None
            st["pose_check"] = time.time() - 600
            app.presence.beat(time.time(), 0)
            fired += bool(P.live(char, st, time.time()))
        assert 2 <= fired <= 60, fired
        print("相手から: 400 回の 10 分で %d 回" % fired)

        # ---- 6. 感想: 性格・機嫌・仲しだい. 止めると好みから外れる
        o = P.get("legs")
        res = Counter()
        for _ in range(60):
            app.set_params({"heart": 40, "affection": 50, "mood": 55}, cid)
            P.perform(char, st, o, time.time(), "pose.self.show")
            v = app._approach_item(cid)
            assert v and [c["id"] for c in v["choices"]][0] == "praise"
            r = app.answer_approach("reply", cid, random.choice(["praise", "shy", "more", "tease", "stop"]))
            res[r["entry"]["reply"]["result"]] += 1
        assert all(res[x] for x in ("good", "neutral", "bad")), res
        st["prefs"] = {}
        P.perform(char, st, o, time.time(), "pose.self.show")
        app.answer_approach("reply", cid, "stop")
        assert P.pref(st, "show:legs") < 0
        print("感想:", dict(res))

        # ---- 7. 持ちかけと対価: 払う・家事を代わる・断る. お金が足りなければ払えない
        app.life.her_money(st)["a"] = 2000
        app.set_params({"affection": 40}, cid)
        char["persona_id"] = "itazura"
        prices = [P.price(char, st, P.get("thighs")) for _ in range(500)]
        rich = 200000
        app.life.her_money(st)["a"] = rich
        app.set_params({"affection": 90}, cid)
        prices_rich = [P.price(char, st, P.get("thighs")) for _ in range(500)]
        n_poor, n_rich = sum(1 for x in prices if x), sum(1 for x in prices_rich if x)
        assert n_poor > n_rich and n_rich < 250 and n_poor < 500, (n_poor, n_rich)
        amts = [x["amount"] for x in prices if x and x["kind"] == "money"]
        assert amts and min(amts) >= 500
        print("対価を求める: 懐が寂しく仲が浅い %d / 余裕があり仲が深い %d (500 回中). 額 %d〜%d 円" % (n_poor, n_rich, min(amts), max(amts)))

        def offer(price):
            st["pose_offer"] = {"kind": "offer", "item": "legs", "price": price, "t": time.time(), "until": time.time() + 600, "entry": None}
        app.life.player_state()["money"] = 10000
        her0 = app.life.her_money(st)["a"]
        offer({"kind": "money", "amount": 3000})
        e = app.answer_approach("reply", cid, "yes")["entry"]
        assert app.life.player_state()["money"] == 7000 and app.life.her_money(st)["a"] == her0 + 3000
        assert st["pose_offer"]["kind"] == "did" and "leg focus" in e["pos"]
        st["pose_offer"] = None
        offer({"kind": "money", "amount": 99999})
        try:
            app.answer_approach("reply", cid, "yes")
            raise AssertionError("お金が足りないのに払えた")
        except ValueError:
            pass
        sta = app.life.player_state().get("stamina", 100)
        offer({"kind": "chore", "amount": 0})
        app.answer_approach("reply", cid, "yes")
        assert app.life.player_state()["stamina"] < sta
        st["pose_offer"] = None
        offer(None)
        m0 = st["params"]["mood"]
        r = app.answer_approach("reply", cid, "no")
        assert st["params"]["mood"] <= m0 and not st.get("pose_offer")
        print("持ちかけ: OK")

        # ---- 9. 組み合わせ (S44): 部位・型・組める型の整合. 大胆さは max + 0.5 × 残り. 合わないものは頼めない
        assert PO.combine([0, 0]) == 0 and PO.combine([1, 1]) == 1.5 and PO.combine([2, 1, 1]) == 3.0 and PO.combine([]) == 0
        for o in P.all():
            assert o["slot"] in PO.SLOTS and (o["slot"] == "show") == (o["type"] == "show"), o["id"]
            if o["slot"] == "body":
                assert o["group"] in PO.GROUPS, o["id"]
            if o["slot"] in ("hand", "show"):
                assert o["with"], o["id"]
        groups = {o["group"] for o in P.all() if o["slot"] == "body"}
        assert groups == set(PO.GROUPS), groups
        c = P.combo(["standing", "v_sign"], "pose")
        assert c["bold"] == 0 and c["pos"].count("looking at viewer") == 1 and "standing" in c["pos"] and ", v," in ", " + c["pos"] + ",", c
        assert c["name"] == "立つ・ピース" and c["outside_ok"]
        c = P.combo(["crossed_legs", "arms_behind_head"], "pose")
        assert c["bold"] == 1.5, c
        assert P.combo(["on_back", "arms_behind_head"], "pose")["bold"] == 2.5
        assert not P.combo(["wariza", "v_sign"], "pose")["outside_ok"], "外でよいのは全部が外でよいときだけ"
        s = P.combo(["legs", "sitting", "cheek_hand"], "show")
        assert s["name"] == "脚（座る・頬に手を添える）" and s["pos"].startswith("leg focus") and s["bold"] == 1, s
        bad = [(["v_sign", "double_v"], "pose"), (["standing", "sitting"], "pose"), (["hugging_legs", "v_sign"], "pose"),
               (["on_back", "salute"], "pose"), (["all_fours", "crossed_arms"], "pose"), (["on_back", "head_rest"], "pose"),
               (["feet", "standing"], "show"), (["hair", "v_sign"], "show"), (["thighs", "on_stomach"], "show")]
        for ids, typ in bad:
            try:
                P.combo(ids, typ)
                raise AssertionError("合わない組み合わせが通った: %s" % ids)
            except ValueError:
                pass
        for ids, typ in ((["legs"], "pose"), (["standing"], "show"), ([], "pose"), (["nope"], "pose")):
            try:
                P.combo(ids, typ)
                raise AssertionError("種類違い・空・無いものが通った: %s %s" % (ids, typ))
            except KeyError:
                pass
        # 画面で押せる組み合わせ = 本当に頼める (姿勢 × 手, 見せる × 姿勢 × 手 の総当たり)
        bodies = [None] + [o for o in P.all() if o["slot"] == "body"]
        hands = [None] + [o for o in P.all() if o["slot"] == "hand"]
        n_ok = 0
        for s_ in [None] + P.all("show"):
            for b in bodies:
                for hd in hands:
                    ids = [x["id"] for x in (s_, b, hd) if x]
                    if not ids:
                        continue
                    fits = not (b and hd and b["group"] not in hd["with"]) and not (b and s_ and b["group"] not in s_["with"]) \
                        and not (s_ and hd and not s_["hand_ok"])
                    try:
                        P.combo(ids, "show" if s_ else "pose")
                        assert fits, ids
                        n_ok += 1
                    except ValueError:
                        assert not fits, ids
        print("組み合わせ: 頼める組み合わせ %d 通り" % n_ok)

        # 服の大胆さ: ポーズが大胆なときだけ同じ式に入る (ピースは大胆な服でもふつう)
        assert P.with_clothes(0, 3) == 0 and P.with_clothes(1, 0) == 1 and P.with_clothes(1, 2) == 2.5
        assert W.accept(char, st, {"bold": 0.0}, time.time()) == "ok"
        # 着ている服の大胆さ: 部品の組み合わせは描かれる部品から同じ式 (キャミ 1 + ミニ 1 = 1.5). 一式はその服の大胆さ
        for k in ("p_camisole:white", "p_miniskirt:black"):
            W.give_to(char, k, "test")
        char = app.char(cid)
        st["dress"] = {"coord": {"top": "p_camisole:white", "bottom": "p_miniskirt:black"}, "t": time.time()}
        assert P.clothes_bold(char, st) == 1.5, P.clothes_bold(char, st)
        assert app.person_view(cid)["posing"]["clothes_bold"] == 1.5
        st["dress"] = {"id": "lingerie", "t": time.time()} if W.item(char, "lingerie") else None
        assert P.clothes_bold(char, st) == (3 if st["dress"] else 0)
        st["dress"] = None
        from core import wardrobe as WM
        assert WM.bold_need(1) == 12 and WM.bold_need(1.5) == 22 and WM.bold_need(2.5) == 42 and WM.bold_need(3.5) == 62

        def rate(o, persona, aff=60, trust=60, mood=60, n=400):
            char["persona_id"] = persona
            k = 0
            for _ in range(n):
                st["pose_asks"] = []
                app.set_params({"affection": aff, "trust": trust, "mood": mood}, cid)
                k += W.accept(char, st, o, time.time(), asks_key="pose_asks") not in ("refuse", "angry")
            return k / float(n)
        one, two, worn = rate({"bold": 1}, "teinei"), rate({"bold": 1.5}, "teinei"), rate({"bold": P.with_clothes(1, 2)}, "teinei")
        assert one > two > worn, (one, two, worn)
        print("大胆さ 1 / 1.5 / 服 2 込み: %.2f / %.2f / %.2f" % (one, two, worn))
        # 照れくささ: 恥じらいではなく, おどけへの平気さで効く (クール・気高いは嫌がり, 天真は平気)
        paw = P.combo(["paw_pose"], "pose")
        assert paw["bold"] == 0 and paw["silly"] == 2
        r_ten, r_uchi, r_cool, r_ked = (rate(paw, x, 45, 45, 50) for x in ("tenshin", "uchiki", "cool", "kedakai"))
        assert r_ten == 1.0 and r_uchi > r_cool + 0.15 and r_ked <= r_cool + 0.05, (r_ten, r_uchi, r_cool, r_ked)
        l_uchi, l_cool = rate(P.get("legs"), "uchiki", 45, 45, 50), rate(P.get("legs"), "cool", 45, 45, 50)
        assert l_uchi < l_cool, "肌の大胆さは恥じらいで効く (照れくささとは逆の並び): %.2f %.2f" % (l_uchi, l_cool)
        print("猫のポーズ (仲ふつう): 天真 %.2f / 恥ずかしがり %.2f / クール %.2f / 気高い %.2f. 脚を見せて: 恥ずかしがり %.2f / クール %.2f"
              % (r_ten, r_uchi, r_cool, r_ked, l_uchi, l_cool))
        char["persona_id"] = "cool"
        assert all(o["silly"] < 2 for o in [P.pick(char, dict(st, prefs={})) for _ in range(300)] if o), "クールは自分から猫のポーズをしない"
        char["persona_id"] = "itazura"

        # コマンド: 組み合わせで頼む. 好みは部位ごとに 0.5 ずつ
        st["pose_asks"], st["cooldowns"], st["prefs"] = [], {}, {}
        app.set_params({"affection": 90, "trust": 90, "mood": 70}, cid)
        r = app.act("_pose", cid, opts={"poses": ["standing", "v_sign"]})
        assert "standing" in r["entry"]["pos"] and ", v," in ", " + r["entry"]["pos"] + ",", r["entry"]["pos"]
        assert P.pref(st, "pose:standing") == 0.5 and P.pref(st, "pose:v_sign") == 0.5
        try:
            app.act("_pose", cid, opts={"poses": ["on_back", "salute"]})
            raise AssertionError("合わない組み合わせを頼めた")
        except ValueError:
            pass
        print("組み合わせのコマンド: OK")

        # 既定の直し: 前の既定のまま手を入れていないものは今の既定に. 書き換えたもの・部位の無い自作は残す
        olds = [dict(PO.OLD_DEFAULT["on_stomach"], id="on_stomach", type="pose", icon="🛏", outside_ok=False, neg=""),
                dict(PO.OLD_DEFAULT["seiza"], id="seiza", type="pose", pos="seiza, my own words", icon="", outside_ok=True, neg=""),
                {"id": "mine", "type": "pose", "name": "自作", "pos": "jumping", "bold": 0},
                {"id": "myshow", "type": "show", "name": "耳", "pos": "ear focus", "bold": 0}]
        app.posing.save_all(olds)
        raw = store.load(store.dpath("poses.json"))
        app.posing.load()
        g = P.get("on_stomach")
        assert g["name"] == "うつ伏せ" and "head rest" not in g["pos"] and g["slot"] == "body" and g["group"] == "lie", g
        assert P.get("seiza")["pos"] == "seiza, my own words" and P.get("seiza")["slot"] == "body"
        assert P.get("mine")["slot"] == "whole" and P.get("myshow")["slot"] == "show" and P.get("myshow")["with"] == []
        assert store.load(store.dpath("poses.json")) == raw, "データは書き換えない"
        try:
            P.combo(["myshow", "standing"], "show")
            raise AssertionError("組める型の無い見せるものに姿勢を添えられた")
        except (ValueError, KeyError):
            pass
        print("既定の直し: OK")

        # ---- 8. 一覧の既定の追従: 既定に増えたものは一度だけ足す. 消したものは戻さない
        app.posing.save_all([o for o in P.all() if o["id"] != "v_sign"])
        app.posing.load()
        assert not P.get("v_sign"), "消したものは戻さない"
        n = len(app.wardrobe.all())
        assert n >= 46 and app.wardrobe.get("lingerie")["bold"] == 3 and app.wardrobe.get("street_casual")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
