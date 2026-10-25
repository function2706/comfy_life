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
        assert "double v" not in r["entry"]["pos"] and ", v," in ", " + r["entry"]["pos"] + ",", r["entry"]["pos"]
        app.set_params({"affection": 15, "trust": 15, "mood": 40}, cid)
        st["pose_asks"] = []
        r = app.act("_show", cid, opts={"pose": "hips"})
        assert "ass focus" not in r["entry"]["pos"] and "できない" in r["entry"]["text"], r["entry"]["text"]
        try:
            app.act("_pose", cid, opts={"pose": "thighs"})
            raise AssertionError("見せてをポーズで頼めた")
        except KeyError:
            pass
        print("頼む: 太もも 浅い仲 %.2f / 深い仲 %.2f, お尻 深い仲 %.2f" % (low, high, hips_high))

        # ---- 3. 大人だけ: 年齢が無い・18 未満ならできない
        c = store.all_characters()[cid]
        for age in (None, 17):
            c["age"] = age
            app.save_character(c)
            try:
                app.act("_pose", cid, opts={"pose": "v_sign"})
                raise AssertionError("年齢 %s でポーズを頼めた" % age)
            except ValueError as e:
                assert "大人" in str(e)
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
