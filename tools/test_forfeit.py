"""罰ゲームと勝負の形 (残件 A12 / S14. core/forfeit.py). 一時データ.

- 組み合わせの確かめ (罰・形・n・お金の額・行き先・未成年は脱衣と着せ替えを選べない)
- 勝負の形 5 つ × 勝ち負けの並び: 決着の時と結果, 脱衣の枚数 (n 回勝負・先に n 勝は n 回負ければ必ず全部, 一発勝負は全部,
  持ち点は減った割合, 脱ぎきるまでは 1 枚ずつ = 以前の脱衣ゲーム. あなたの側も同じ)
- 罰 11 種 × 向き (相手が払う / あなたが払う): お金・約束・券・呼び方・禁止・本音・家事・写真・ポーズ・スキンシップ
- 約束の行方: 家事は家にいるときに果たす・デートは行き先に出かければ果たす・お金は払えるようになったら・おごりは次の支払い
  (plan_payment)・3 日前の催促・期限 (あなたが果たさなければ機嫌と信頼が下がる / 相手ならうやむや)
- 渋る (律儀でない性格は渋ることがある. 券・脱衣は渋らない)・受けるかの判定 (重いほど・同じ日に何度も頼むほど渋る. 既定の組み合わせは定義の when だけ)
- 券: 受ける / 断る (券は残る)・相手が持っている券を使ってくる
- 場所: 画面で押せる (一覧の pub_why と options.private_ok) = 本当に始まる (人前でできない罰は二人きりの家だけ)
- 通しで遊ぶ: 野球拳 + お金 + 先に 2 勝 / コネクトフォー + 2 回勝負 (盤面を見せたまま「次の勝負へ」) / あっち向いてホイ + 3 回勝負
- 開き直し: 試合の途中で作り直しても続く / 以前の版で始めた途中のゲーム (bout なし) は既定の組み合わせで続く / 試合の合間のやめるは記録を残す

    python tools/test_forfeit.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, forfeit as FF, games as G, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
DAY = 86400.0


def main():
    random.seed(7)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        cid = "hina"
        char = app.chars[cid]
        st = app.state(cid)
        st["override"] = {"activity": "relax", "label": "テスト", "location": "リビング", "until": 9e12}
        app.set_params({"affection": 90, "trust": 90, "mood": 80, "energy": 80}, cid)
        F = app.forfeit
        gdef = {g["id"]: g for g in app.minigames}
        yk, c4 = gdef["yakyuken"], gdef["connect4"]
        assert app.bonds.together(cid) and app.games.spot(cid)["private"], "二人きりの家で始める"

        # ---------------------------------------------------------------- 組み合わせの確かめ
        assert F.normalize(yk, char, None) == F.preset(yk) == {"pens": ["strip"], "form": "strip", "n": 0, "opt": {}}
        assert F.preset(gdef["blackjack"])["form"] == "first" and F.preset(gdef["koikoi"])["form"] == "n"
        assert F.preset(c4) == {"pens": [], "form": "one", "n": 1, "opt": {}}
        bad = [{"pens": ["nope"]}, {"pens": ["money"], "form": "strip"}, {"pens": [], "form": "n", "n": 1},
               {"pens": [], "form": "first", "n": 10}, {"pens": ["money"], "opt": {"money": 777}},
               {"pens": ["date"], "opt": {"date": "moon"}}, {"pens": ["ban"], "opt": {"ban": "tv"}}, {"form": "x"}]
        for b in bad:
            try:
                F.normalize(c4, char, b)
                raise AssertionError("通ってはいけない: %r" % b)
            except ValueError:
                pass
        ok = F.normalize(c4, char, {"pens": ["money", "money", "callname"], "form": "points", "n": "5",
                                    "opt": {"money": "treat", "call": ""}})
        assert ok["pens"] == ["money", "callname"] and ok["n"] == 5 and ok["opt"]["money"] == "treat" and ok["opt"]["call"]
        minor = dict(char, age=16)
        for p in ("strip", "pose"):
            try:
                F.normalize(c4, minor, {"pens": [p]})
                raise AssertionError("未成年に %s" % p)
            except ValueError:
                pass
        assert not any(x["id"] in ("strip", "pose") for x in F.options(minor, st, cid)["pens"])
        assert FF.privacy_of(["money", "ticket"]) == "public" and FF.privacy_of(["money", "skinship"]) == "private"
        assert G.privacy_of(yk) == "private" and G.privacy_of(yk, []) == "public" and G.privacy_of(c4, ["strip"]) == "private"
        print("組み合わせの確かめ: OK")

        # ---------------------------------------------------------------- 勝負の形 × 勝ち負けの並び
        S = len(app.games._stages(yk))

        def bout(form, n, pens=("strip",), seq=(), steps=None, g=yk):
            game = {"stage": 0, "lives": 3, "lives_max": 3,
                    "bout": F.normalize(g, char, {"pens": list(pens), "form": form, "n": n})}
            game["outfit"] = app.games.stage_outfit(g, char, st, 0)
            out = []
            for i, w in enumerate(seq):
                e = F.unit(cid, char, st, g, game, w, (steps or {}).get(i, 1))
                out.append((game["stage"], game["lives"], e))
                if e:
                    break
            return out, game

        # 脱ぎきるまで (以前の脱衣ゲーム): 相手は段階の数だけ, あなたは 3 回で
        o, _ = bout("strip", 0, seq=["p"] * 9)
        assert len(o) == S and o[-1][2] == "win" and [x[0] for x in o] == list(range(1, S)) + [S - 1], o
        o, _ = bout("strip", 0, seq=["a"] * 9)
        assert len(o) == 3 and o[-1] == (0, 0, "lose"), o
        o, _ = bout("strip", 0, seq=["a", None, "p"], steps={2: 2})          # 麻雀の翻: 2 枚
        assert o[-1][0] == 2 and o[-1][1] == 2 and o[-1][2] is None, o
        # 一発勝負: 引き分けはやり直し, 決まれば全部
        o, _ = bout("one", 1, seq=[None, None, "p"])
        assert o[-1][2] == "win" and len(o) == 3, o
        o, _ = bout("one", 1, seq=["a"])
        assert o[-1] == (0, 0, "lose"), o
        for pens, want in (((), "draw"), (("money",), None)):     # 1 ゲームものの引き分け: 罰なしは以前どおり引き分けで終わる
            game = {"stage": 0, "lives": 3, "bout": F.normalize(c4, char, {"pens": list(pens), "form": "one"})}
            assert F.unit(cid, char, st, c4, game, None, 1, whole=True) == want, pens
        # n 回勝負: n 回負ければ必ず全部 (途中で勝っても)
        for n in (2, 3, 5, 9):
            for seq in (["p"] * n, ["a", "p"] * n, [None] + ["p"] * n):
                o, game = bout("n", n, seq=seq[:n])
                wins = seq[:n].count("p")
                if wins == n:
                    assert o[-1][2] == "win" and game["stage"] == S - 1 and game.get("outfit"), (n, seq, o)
                assert len(o) == n or o[-1][2], (n, seq, o)
            o, _ = bout("n", n, seq=["a"] * n)
            assert o[-1] == (0, 0, "lose"), (n, o)
        o, _ = bout("n", 3, seq=["p", "a", None])
        assert o[-1][2] == "draw", o
        # 先に n 勝: n 回負けたら全部
        for n in (2, 3, 4):
            o, _ = bout("first", n, seq=["p", "a"] * 9)
            assert o[-1][2] in ("win",) and len(o) == 2 * n - 1, (n, o)
            o, _ = bout("first", n, seq=["a"] * 9)
            assert o[-1] == (0, 0, "lose") and len(o) == n, (n, o)
        o, _ = bout("first", 3, pens=(), seq=["p", "p"], steps={0: 2})        # 重み 2 で 2 勝ぶん
        assert o[-1][2] == "win" and len(o) == 2, o
        # 持ち点: 減った割合だけ脱ぐ
        o, _ = bout("points", 4, seq=["a", "a"])
        assert o[-1][1] == 1 and o[-1][2] is None, o                       # 3 枚 × 2/4 = 2 枚 (切り上げ)
        o, _ = bout("points", 4, seq=["a"] * 9)
        assert o[-1] == (0, 0, "lose") and len(o) == 4, o
        o, _ = bout("points", 3, pens=(), seq=["p", "p", "p"])
        assert o[-1][2] == "win" and len(o) == 3, o
        # 役満 (重み 99) はどの形でもその場で脱ぎきる
        for form, n in (("n", 5), ("first", 5), ("points", 9), ("strip", 0)):
            o, _ = bout(form, n, seq=["p"], steps={0: 99})
            assert o[-1][2] == "win", (form, o)
        print("勝負の形: OK | 段階 %d・あなた 3" % S)

        # ---------------------------------------------------------------- 罰 × 向き
        def fresh():
            st.pop("forfeit", None)
            st["params"].update(affection=90, trust=90, mood=80)
            ps = app.life.player_state()
            ps["money"] = 50000
            app.life.her_money(st)["a"] = 50000

        app.traits = (lambda orig: lambda c: dict(orig(c), repay=1.0))(app.traits)      # 渋らない (別に確かめる)
        trust0 = st["params"]["trust"]
        for p in [x["id"] for x in FF.PENALTIES if x["id"] != "strip"]:
            for who in ("her", "me"):
                fresh()
                opt = F.normalize(c4, char, {"pens": [p], "opt": {"money": 3000, "date": "aquarium", "ban": "phone",
                                                                  "call": "先輩"}})["opt"]
                n0 = len(app.log(cid))
                pm, hm = app.life.player_state()["money"], app.life.her_money(st)["a"]
                r = F.pay(cid, char, st, c4, who, p, opt, time.time())
                assert r == "paid", (p, who, r)
                assert len(app.log(cid)) > n0, (p, who, "記録が残る")
                rec = F.rec(st)
                if p == "money":
                    d = 3000 if who == "her" else -3000
                    assert app.life.player_state()["money"] - pm == d and app.life.her_money(st)["a"] - hm == -d, (who,)
                if p == "date":
                    x = rec["owed"][0]
                    assert x["who"] == who and x["place"] in FF.DATE_PLACES and (who == "me" or x["place"] == "aquarium")
                if p == "ticket":
                    assert rec["tickets"] == ({"mine": 1, "hers": 0} if who == "her" else {"mine": 0, "hers": 1})
                if p == "callname":
                    call = app.pronouns(char)[2]
                    assert (call == "先輩") == (who == "her"), (who, call)
                if p == "ban":
                    msg = F.allows(app.action("message"), cid)
                    assert bool(msg) == (who == "me"), (who, msg)
                    assert bool(F.phone_ban_until(st)) == (who == "her")
                if p == "chores":
                    assert not rec["owed"], "家にいれば, その場で"
        fresh()
        F._pay_ban(cid, char, st, c4, "her", {"ban": "snack"}, time.time(), "", "")
        assert F.allows(app.action("snack"), cid) and not F.allows(app.action("message"), cid)
        fresh()
        F._pay_ban(cid, char, st, c4, "me", {"ban": "snack"}, time.time(), "", "")
        assert "あなた" in F.allows(app.action("snack"), cid)
        # スマホ禁止の相手は, 返事が明けてから
        fresh()
        F._pay_ban(cid, char, st, c4, "her", {"ban": "phone"}, time.time(), "", "")
        dl, _, _ = app.reply_delay(char, st, time.time(), app.scene_at(char, st, engine.datetime.now()), {})
        assert dl > DAY - 60, dl
        print("罰 × 向き: OK | %d 種 × 2" % (len(FF.PENALTIES) - 1))

        # ---------------------------------------------------------------- 約束の行方
        now = time.time()
        fresh()
        F._owe(st, "her", "chores", {}, now)
        app.home.add(**{k: 40 for k, _, _ in __import__("core.home", fromlist=["PARTS"]).PARTS})
        sc0 = app.home.score()
        assert F.tick(char, st, now + 60) and not F.rec(st)["owed"], "家にいれば家事は果たされる"
        assert app.home.score() < sc0, "片付いた"
        # デート: 行き先へ出かけたら
        fresh()
        F._owe(st, "her", "date", {}, now, place="cafe")
        F.tick(char, st, now + 60)
        assert F.rec(st)["owed"], "まだ出かけていない"
        ov = st["override"]
        st["override"] = {"outing": True, "activity": "cafe", "until": now + 3600}
        F.tick(char, st, now + 120)
        st["override"] = ov
        assert not F.rec(st)["owed"], "カフェに来た"
        # お金: 払えるようになったら
        fresh()
        app.life.her_money(st)["a"] = 100
        F._pay_money(cid, char, st, c4, "her", {"money": 3000}, now, "", "")
        assert F.rec(st)["owed"] and F.rec(st)["owed"][0]["pen"] == "money"
        # 約束には, 誰がするかと, どの勝負で負けた分か (きっかけ) が付き, 関係性にも同じものが出る (勝っても前の分・相手の分が残るため)
        fv = F.view(char, st, now)["owed"][0]
        assert fv["who"] == "her" and c4.get("name", "") in fv["from"] and "/" in fv["from"], fv
        pv = next(p for p in app.people_view(now) if p["id"] == cid)
        assert pv["forfeit"] and pv["forfeit"]["owed"][0]["from"] == fv["from"], pv.get("forfeit")
        assert "勝負" in F._from({"t": now}) and "券" in F._from({"t": now, "src": "券"}), "古いセーブ・券のきっかけ"
        F.tick(char, st, now + DAY / 2)
        assert F.rec(st)["owed"], "まだ払えない"
        app.life.her_money(st)["a"] = 9000
        pm = app.life.player_state()["money"]
        F.tick(char, st, now + DAY)
        assert not F.rec(st)["owed"] and app.life.player_state()["money"] == pm + 3000
        # おごり: 次の支払いは負けた方
        for who in ("her", "me"):
            fresh()
            F._pay_money(cid, char, st, c4, who, {"money": "treat"}, now, "", "")
            assert F.treat_policy(char, st) == who
            for _ in range(5):
                assert app.life.plan_payment(char, st, 2000)["payer"] == who
            assert F.treat_paid(char, st, who, now) and F.treat_policy(char, st) is None
            assert app.life.plan_payment(char, st, 2000, "me")["payer"] == "me", "決め打ちの払い方はそのまま"
        # 期限: あなたが果たさない → 機嫌と信頼, 3 日前に催促 (離れているとき)
        fresh()
        x = F._owe(st, "me", "date", {}, now, place="aquarium")
        tog = app.bonds.together
        app.bonds.together = lambda c, t=None: False
        n_chat = len(app.chat.load(cid)["items"])
        F.tick(char, st, x["due"] - 2 * DAY)
        assert len(app.chat.load(cid)["items"]) == n_chat + 1 and x["reminded"], "3 日前に一度"
        F.tick(char, st, x["due"] - DAY)
        assert len(app.chat.load(cid)["items"]) == n_chat + 1, "催促は一度だけ"
        m0, t0 = st["params"]["mood"], st["params"]["trust"]
        F.tick(char, st, x["due"] + 1)
        assert not F.rec(st)["owed"] and st["params"]["mood"] < m0 and st["params"]["trust"] < t0
        assert F.rec(st).get("grumble"), "離れていたら, 次に会ったときに言う"
        app.bonds.together = tog
        n0 = len(app.log(cid))
        F.tick(char, st, x["due"] + 60)
        assert not F.rec(st).get("grumble") and len(app.log(cid)) == n0 + 1
        # 相手が果たさない → うやむや (記録だけ. あなたの側の値は作らない)
        fresh()
        x = F._owe(st, "her", "date", {}, now, place="beach")
        m0 = st["params"]["mood"]
        F.tick(char, st, x["due"] + 1)
        assert not F.rec(st)["owed"] and st["params"]["mood"] == m0
        print("約束の行方: OK")

        # ---------------------------------------------------------------- 渋る・受けるか
        tr0 = app.traits
        app.traits = lambda c: dict(tr0(c), repay=0.0, greed=1.0)
        fresh()
        res = [F.pay(cid, char, st, c4, "her", "money", {"money": 500}, now) for _ in range(200)]
        assert 0 < res.count("renege") < 200, res.count("renege")
        assert all(F.pay(cid, char, st, c4, "her", "ticket", {}, now) == "paid" for _ in range(30)), "券は渋らない"
        assert all(F.pay(cid, char, st, c4, "me", "money", {"money": 500}, now) in ("paid",) for _ in range(5)), "あなたは渋らない"
        app.traits = tr0
        fresh()
        light = F.normalize(c4, char, {"pens": ["chores"]})
        heavy = F.normalize(c4, char, {"pens": ["strip", "skinship", "ticket"], "form": "one"})
        assert F.accept_chance(char, st, light) > F.accept_chance(char, st, heavy)
        st["params"].update(affection=30, trust=30, mood=40)
        low = F.accept_chance(char, st, heavy)
        assert low < 0.3, low
        st["params"].update(affection=90, trust=90, mood=80)
        hi = F.accept_chance(char, st, heavy)
        F.rec(st)["asks"] = [now, now]
        assert F.accept_chance(char, st, heavy, now) < hi, "同じ日に何度も頼むほど渋る"
        assert F.judge(char, st, F.preset(yk), True)[0] and F.judge(char, st, F.preset(c4), False)[0]
        fresh()
        st["params"].update(affection=20, trust=20, mood=20)
        n_ref = sum(not F.judge(char, st, heavy, False, now)[0] for _ in range(50))
        assert n_ref >= 45, n_ref
        print("渋る・受けるか: OK | 渋った %d/200, 重い罰で断った %d/50" % (res.count("renege"), n_ref))

        # ---------------------------------------------------------------- 券
        fresh()
        F.rec(st)["tickets"]["mine"] = 3
        r = F.use_ticket(cid, "massage")
        assert r["accepted"] and F.rec(st)["tickets"]["mine"] == 2
        st["params"].update(affection=0, trust=0, mood=0)
        F.rec(st)["asks"] = [now] * 6
        F.rec(st)["tickets"]["mine"] = 20
        got = [F.use_ticket(cid, "lap")["accepted"] for _ in range(20)]
        assert 0 < got.count(False) and got.count(False) >= 8 and F.rec(st)["tickets"]["mine"] == 20 - got.count(True), ("断られたら券は残る", got)
        try:
            F.use_ticket(cid, "nope")
            raise AssertionError
        except ValueError:
            pass
        fresh()
        F.rec(st)["tickets"]["hers"] = 1
        st0 = app.life.player_state()["stamina"]
        F.rec(st)["tick_t"] = now
        for i in range(1, 200):
            F.tick(char, st, now + i * 3600)
            if not F.rec(st)["tickets"]["hers"]:
                break
        assert not F.rec(st)["tickets"]["hers"], "そばにいれば, そのうち使ってくる"
        assert app.life.player_state()["stamina"] <= st0 or F.treat_policy(char, st) == "me"
        print("券: OK | 相手が使うまで %d 時間" % i)

        # ---------------------------------------------------------------- 場所 (画面で押せる = 本当に始まる)
        fresh()
        st["game"] = None
        combos = [[], ["money"], ["ticket", "date"], ["strip"], ["skinship"], ["money", "pose"]]
        sp0 = app.games.spot

        def place_case(label, sp):
            app.games.spot = lambda c, t=None: dict(sp)
            row = []
            for gid in ("acchimuite", "connect4", "yakyuken"):
                g = gdef[gid]
                gv = {x["id"]: x for x in app.games.view(char, st, app.context(char, st, engine.datetime.now()))["list"]}
                opts = app.games.view(char, st, app.context(char, st, engine.datetime.now()))["options"]
                for pens in combos:
                    priv = FF.privacy_of(pens) == "private"
                    screen_ok = not gv[gid]["pub_why"] and not (priv and not opts["private_ok"])
                    st["game"] = None
                    try:
                        F.always = True
                        app.games.start(gid, cid, {"pens": pens, "form": "one"})
                        started = bool(st.get("game"))
                    except ValueError:
                        started = False
                    finally:
                        F.always = False
                    assert screen_ok == started, (label, gid, pens, screen_ok, started)
                    st["game"] = None
                    row.append("○" if started else "×")
            app.games.spot = sp0
            print("場所 %s: OK | %s" % (label, "".join(row)))

        place_case("二人きりの家", {"spot": "home", "indoor": True, "tools": True, "private": True})
        place_case("ほかの人もいる家", {"spot": "home", "indoor": True, "tools": True, "private": False})
        place_case("カフェ", {"spot": "shop", "indoor": True, "tools": False, "private": False})
        place_case("公園", {"spot": "outdoor", "indoor": False, "tools": False, "private": False})

        # ---------------------------------------------------------------- おまかせ (相手が罰を決める)
        try:
            F.normalize(c4, char, {"omakase": True, "form": "strip"})
            raise AssertionError("おまかせで脱ぎきるまでは選べない")
        except ValueError:
            pass
        assert F.normalize(c4, char, {"omakase": True, "form": "n", "n": 3}) ==             {"pens": [], "form": "n", "n": 3, "opt": {}, "pts": False, "omakase": True}

        def omakase_case(label, sp, params, ch=None, trials=60):
            app.games.spot = lambda c, t=None: dict(sp)
            if ch is not None:
                app.chars[cid] = ch
            seen, none = {}, 0
            for _ in range(trials):
                fresh()
                st["params"].update(params)
                st["game"] = None
                r = app.games.start("connect4", cid, {"omakase": True, "form": "first", "n": 2})
                assert not r.get("refused") and st.get("game"), "おまかせは断らない"
                assert not F.rec(st)["asks"], "持ちかけた回数に数えない"
                b = st["game"]["bout"]
                assert b["omakase"] and len(b["pens"]) <= 2
                if not b["pens"]:
                    none += 1
                for p in b["pens"]:
                    seen[p] = seen.get(p, 0) + 1
                    if not (sp["indoor"] and sp["private"] and sp["tools"]):
                        assert FF.PEN[p]["privacy"] == "public", (label, p)
                    if ch is not None and FF.PEN[p].get("adult"):
                        raise AssertionError("未成年に %s" % p)
                if b["pens"]:       # 決めた中身は, 自分で選んだときと同じ確かめを通る
                    nb = F.normalize(c4, app.chars[cid], {"pens": b["pens"], "form": "first", "n": 2, "opt": b["opt"]})
                    assert nb["opt"] == b["opt"], (b["opt"], nb["opt"])
                assert app.games.view(app.chars[cid], st, app.context(app.chars[cid], st, engine.datetime.now()))[
                    "current"]["bout"]["omakase"]
                st["game"] = None
            app.games.spot = sp0
            app.chars[cid] = char
            print("おまかせ %s: OK | 罰なし %d/%d・%s" % (label, none, trials,
                                                   " ".join("%s%d" % (k, v) for k, v in sorted(seen.items(), key=lambda x: -x[1]))))
            return none, seen

        home = {"spot": "home", "indoor": True, "tools": True, "private": True}
        n_hi, s_hi = omakase_case("仲がよい・二人きり", home, {})
        n_lo, s_lo = omakase_case("仲が悪い", home, {"affection": 10, "trust": 15, "mood": 15})
        assert n_lo > n_hi and n_lo >= 40, (n_lo, n_hi)
        omakase_case("仲がよい・人前", {"spot": "home", "indoor": True, "tools": True, "private": False}, {})
        omakase_case("未成年", home, {}, ch=dict(char, age=16))
        # 相手が決めた罰で負けると, あなたが払う (お互いさま)
        fresh()
        app.games.spot = lambda c, t=None: dict(home)
        for _ in range(50):
            st["game"] = None
            app.games.start("connect4", cid, {"omakase": True, "form": "one"})
            if st["game"]["bout"]["pens"] and "strip" not in st["game"]["bout"]["pens"]:
                break
        n0 = len(app.log(cid))
        assert F.unit(cid, char, st, c4, st["game"], "a", whole=True) == "lose" and len(app.log(cid)) > n0
        st["game"] = None
        app.games.spot = sp0

        # ---------------------------------------------------------------- 通しで遊ぶ
        fresh()
        F.always = True
        pm = app.life.player_state()["money"]
        app.games.start("yakyuken", cid, {"pens": ["money"], "form": "first", "n": 2, "opt": {"money": 1000}})
        assert not st["game"].get("outfit"), "脱衣なしなら服はそのまま"
        for _ in range(20):
            her = st["game"]["next"]
            r = app.games.move(cid, {"hand": next(h for h in G.HANDS if G.BEATS[h] == her)})
            if r["ended"]:
                break
        assert r["ended"] == "win" and st.get("game") is None and app.life.player_state()["money"] == pm + 1000, r["ended"]
        # コネクトフォー 2 回勝負: 1 ゲーム目の盤面を見せたまま待つ → 次の勝負へ → 2 ゲーム目で決着
        app.games.start("connect4", cid, {"pens": ["ticket"], "form": "n", "n": 2})
        units = []
        for _ in range(400):
            gm = st.get("game")
            if not gm:
                break
            if gm.get("between"):
                v = app.games.view(char, st, app.context(char, st, engine.datetime.now()))["current"]
                assert v["bout"]["between"] and v["board"]["over"], "決着の盤面を見せたまま"
                try:
                    app.games.move(cid, {"col": 0})
                    raise AssertionError("合間は打てない")
                except ValueError:
                    pass
                app.games.move(cid, {"act": "next_unit"})
                assert not st["game"].get("over") and not any(st["game"]["board"]), "盤面を作り直す"
                continue
            from core import boardgames as BG
            r = app.games.move(cid, {"col": random.choice(BG.c4_moves(gm["board"]))})
            if r.get("unit"):
                units.append(r["unit"]["result"])
            if r.get("ended"):
                break
        assert len(units) == 1 and r["ended"] in ("win", "lose", "draw") and st["game"]["over"], (units, r)
        b = st["game"]["bout"]
        assert b["units"] == 2
        app.games.quit(cid)
        # あっち向いてホイ 3 回勝負 (決着の盤面がないので, そのまま次へ)
        app.games.start("acchimuite", cid, {"pens": [], "form": "n", "n": 3})
        for _ in range(500):
            gm = st.get("game")
            if not gm:
                break
            if gm["phase"] == "rps":
                r = app.games.move(cid, {"hand": next(h for h in G.HANDS if G.BEATS[h] == gm["next"])})
            else:
                r = app.games.move(cid, {"dir": random.choice(G.DIRS)})
            if r.get("ended"):
                break
        assert r["ended"] in ("win", "lose", "draw") and st.get("game") is None, r
        print("通しで遊ぶ: OK | コネクトフォー %s → %s" % (units, r["ended"]))

        # ---------------------------------------------------------------- 開き直し・以前の版
        fresh()
        app.games.start("poker", cid, {"pens": ["strip", "photo"], "form": "first", "n": 2})
        st["game"]["bout"]["me"] = 1
        app.save_state(cid)
        app2 = engine.App()
        st2 = app2.state(cid)
        assert st2["game"]["bout"]["me"] == 1 and st2["game"]["bout"]["pens"] == ["strip", "photo"], "作り直しても続く"
        v = app2.games.view(app2.chars[cid], st2, app2.context(app2.chars[cid], st2, engine.datetime.now()))["current"]
        assert v["strip"] and v["bout"]["label"] == "先に 2 勝（試合に負けた方に罰）", v["bout"]["label"]
        # 選ぶ欄: 罰がいつ来るかを添える (n 回勝負は勝ち越しても負けた回の罰が来るので, 選ぶ前に分かるように)
        fl = {f["id"]: f["label"] for f in F.options(char, st, cid)["forms"]}
        assert fl["n"] == "n 回勝負（負けるたびに罰）" and fl["first"] == "先に n 勝（試合に負けた方に罰）", fl
        assert all("（" in x for x in fl.values()), fl
        st2["game"] = None
        app2.save_state(cid)
        # 以前の版で始めた途中の脱衣麻雀 (bout なし)
        st["game"] = {"id": "mahjong", "round": 0, "phase": "mj", "stage": 1, "lives": 2, "me": 0, "her": 0}
        b = F.bout(gdef["mahjong"], st["game"])
        assert b["pens"] == ["strip"] and b["form"] == "strip"
        e = F.unit(cid, char, st, gdef["mahjong"], st["game"], "a", 2)
        assert e == "lose" and st["game"]["lives"] == 0
        # 試合の合間にやめる: 記録を残す (決着後の「閉じる」とは別)
        st["game"] = None
        app.games.start("connect4", cid, {"pens": [], "form": "n", "n": 3})
        st["game"].update(over="win", between=True)
        n0 = len(app.log(cid))
        assert app.games.quit(cid)["ended"] == "quit" and len(app.log(cid)) == n0 + 1
        F.always = False
        print("開き直し・以前の版: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
