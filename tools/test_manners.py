"""メッセージの受け止め方 (core/manners.py): 謝罪の許し方の幅・続けて謝る・謝ったばかりなのに・お礼の心当たり・
あいさつ (時間外・2 回目・習慣の途切れ)・スタンプ・今いい？・お疲れさま・大丈夫？・今何してる？・返事まだ？ (一時データ, 画像生成なし).

    python tools/test_manners.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def at(hm, days=0):
    d = datetime.now().replace(second=0, microsecond=0) + timedelta(days=days)
    h, m = hm.split(":")
    return d.replace(hour=int(h), minute=int(m)).timestamp()


def main():
    random.seed(7)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("受け止め方")
        M, L, C = app.manners, app.life, app.chat
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        now = time.time()

        def reply(kind, t=None, meta=None, ctx=None):
            c = dict(ctx or {}, _meta=meta or {})
            return C.reply(char, st, kind, t or now, c)

        def fault(delta, action="_x", t=None, tell="あなたのせい"):
            st["reasons"], st["apologies"], st["apology_last"] = [], [], None
            return L.add_reason(st, "player", "bad", tell, t or now, told=True, delta=delta, action=action)

        # ---- 1. 謝罪の許し方の幅: 怒りの大きさ・性格 (根に持つ)・同じ失敗の何度目かで割合が変わる
        def dist(delta, grudge=1.0, nth=1, mood=50, n=600):
            tr = app.traits(char)
            old = tr.get("grudge")
            tr["grudge"] = grudge
            c = {}
            for _ in range(n):
                fault(delta)
                for i in range(nth - 1):     # 前にも同じことをした (解決済みの理由として残っている)
                    st["reasons"].insert(0, {"kind": "player", "mood": "bad", "tell": "前%d" % i, "t": now - 86400 * (i + 1),
                                             "told": True, "delta": delta, "resolved": True, "action": "_x"})
                st["params"].update(mood=mood, affection=50, trust=50)
                out = M.apology(char, st, now)["out"]
                c[out] = c.get(out, 0) + 1
            if old is None:
                tr.pop("grudge")
            else:
                tr["grudge"] = old
            return {k: round(v / float(n), 2) for k, v in c.items()}
        small, big = dist(-2), dist(-12)
        assert small.get("quick", 0) > 0.6 and big.get("quick", 0) < 0.25, (small, big)
        assert big.get("deeds", 0) + big.get("refuse", 0) > small.get("deeds", 0) + small.get("refuse", 0)
        easy, hard = dist(-6, grudge=0.8), dist(-6, grudge=1.25)
        assert easy.get("quick", 0) > hard.get("quick", 0) + 0.2, (easy, hard)
        third = dist(-6, nth=3)
        assert third.get("quick", 0) < dist(-6).get("quick", 0), third
        moody = dist(-6, mood=20)
        assert moody.get("quick", 0) < dist(-6, mood=70).get("quick", 0)
        print("許し方: 小さな失敗", small, "/ 大きな失敗", big)
        print("        さっぱり", easy, "/ 根に持つ", hard, "/ 3 度目", third)

        # 結果ごとの反映: すぐ = 消える / 半分 = 弱まって残る / 態度で = 残る / 受け付けない = 残る
        for out, gone in (("quick", True), ("half", False), ("deeds", False), ("refuse", False)):
            r = fault(-6)
            M.apply_apology(char, st, {"out": out, "r": r}, now)
            assert r.get("resolved", False) == gone, out
            if out == "half":
                assert r["delta"] == -3.0 and r["half"]
        # 日が経ってから謝ると「今さら？」(理由は消える)
        r = fault(-6, t=now - 2 * 86400)
        assert M.apology(char, st, now)["out"] == "late"
        key, _, _ = reply("apology")
        assert key == "apology_late" and r["resolved"], key
        # 謝ることが見当たらない: 戸惑われる
        fault(-6)
        st["reasons"] = []
        assert reply("apology")[0] == "apology_confused"
        print("許し方の反映・今さら・心当たりなし: OK")

        # ---- 2. 数時間のうちに続けて謝ると「もういいって」, さらに続くと苛立たれる (間隔で見る. 連絡の回数には数えない)
        fault(-2)
        keys = [reply("apology", t=now + i * 600)[0] for i in range(3)]
        assert keys[1] == "apology_enough" and keys[2] == "apology_irritated", keys
        assert reply("apology", t=now + 6 * 3600)[0] != "apology_enough", "時間をあければ, 続けてではない"
        print("謝罪の連打:", keys)

        # ---- 3. 謝ったばかりなのに, また連絡しすぎ: ふつうより強く下がる
        r = fault(-2, action="_too_often")
        M.apply_apology(char, st, {"out": "quick", "r": r}, now)
        key, eff, _ = reply("smalltalk", t=now + 3600, ctx={"too_often": True})
        assert key == "too_often_again" and eff["mood"] < -2 and eff["trust"] < 0, (key, eff)
        assert reply("smalltalk", t=now + 7200, ctx={"too_often": True})[0] == "too_often", "一度だけ"
        # 「態度で」: 連絡しすぎなら, しばらく連絡を控えると消える
        r = fault(-6, action="_too_often")
        M.apply_apology(char, st, {"out": "deeds", "r": r}, now)
        st["contacts"] = []
        M.settle(char, st, now + 3 * 3600)
        assert not r.get("resolved")
        M.settle(char, st, now + 9 * 3600)
        assert r["resolved"], "連絡を控えたら消えた"
        r = fault(-6, action="_too_often")
        M.apply_apology(char, st, {"out": "deeds", "r": r}, now)
        st["contacts"] = [now + 3600]
        M.settle(char, st, now + 9 * 3600)
        assert not r.get("resolved"), "連絡を続けたら消えない"
        print("謝ったばかりなのに・態度で: OK")

        # ---- 4. その場で謝る: 同じ判定 (反応の条件 apology)
        app.bonds.set_stage(cid, "live")
        app.set_params({"mood": 50, "affection": 50, "trust": 50}, cid)
        seen = {}
        for i in range(40):
            fault(-12)
            st["cooldowns"], st["override"] = {}, None
            st["params"].update(mood=50, affection=50, trust=50)
            e = app.act("apologize", cid)["entry"]
            seen[e["text"][:8]] = seen.get(e["text"][:8], 0) + 1
        assert len(seen) >= 3, seen
        st["apologies"] = [time.time() - 60]
        st["cooldowns"] = {}
        e = app.act("apologize", cid)["entry"]
        assert "もういい" in e["text"], e["text"]
        print("その場で謝る:", seen)

        # ---- 5. お礼: 心当たりがあれば効く / なければ「え、何が？」/ 同じことに何度も言うと「何回言うの」
        st["favors"] = []
        assert reply("thanks")[0] == "thanks_what"
        M.favor(st, "lent", now - 3600)
        k1, e1, _ = reply("thanks")
        k2, e2, _ = reply("thanks")
        assert k1 == "thanks" and k2 == "thanks_again" and e2["mood"] < e1["mood"], (k1, k2)
        st["favors"] = [{"t": now - 2 * 86400, "what": "met", "thanked": 0}]
        assert reply("thanks")[0] == "thanks_what", "昔のことは心当たりにならない"
        # 会う・自撮りなどで心当たりが増える
        st["favors"] = []
        st["cooldowns"], st["override"] = {}, None
        app.act("talk", cid)
        assert any(f["what"] == "met" for f in st["favors"]), st["favors"]
        # 謝ったあとのお礼: 謝罪の結果しだい
        def after(out, s=0.6):
            st["favors"] = []
            st["apology_last"] = {"t": now - 600, "action": "_x", "out": out, "s": s}
            return reply("thanks")
        assert after("quick")[0] == "thanks" and reply("thanks")[0] == "thanks_again"
        assert after("late", 0.4)[0] == "thanks" and after("late", 0.1)[0] == "thanks_what"
        assert after("deeds")[0] == "thanks_unforgiven" and after("refuse")[0] == "thanks_unforgiven"
        assert after("broken")[1]["mood"] < 0
        tr = app.traits(char)
        half = {}
        for g in (0.8, 1.0, 1.25):
            tr["grudge"] = g
            half[g] = sum(after("half")[0] == "thanks" for _ in range(400)) / 400.0
        tr.pop("grudge")
        assert half[0.8] > half[1.0] > half[1.25] > 0.1, half
        st["apology_last"]["t"] = now - 2 * 86400
        st["apology_last"]["thanked"] = 0
        assert reply("thanks")[0] == "thanks_what", "1 日より前の謝罪は心当たりにならない"
        print("お礼: OK. 半分だけ許したあとのお礼が効く割合", half)

        # ---- 6. あいさつ: 時間外・同じ朝の 2 回目・習慣の途切れ
        st["greets"], st["greet_days"], st["greet_miss"] = {}, {}, {}
        m = M.on_send(char, st, "greet_morning", at("15:00"))
        assert reply("greet_morning", meta=m)[0] == "greet_odd_morning"
        m = M.on_send(char, st, "greet_night", at("09:00"))
        assert reply("greet_night", meta=m)[0] == "greet_odd_night"
        m1 = M.on_send(char, st, "greet_morning", at("07:00"))
        m2 = M.on_send(char, st, "greet_morning", at("08:30"))
        assert reply("greet_morning", meta=m1)[0] == "greet_morning" and reply("greet_morning", meta=m2)[0] == "greet_again"
        n1 = M.on_send(char, st, "greet_night", at("23:30"))
        n2 = M.on_send(char, st, "greet_night", at("00:40", days=1))
        assert not n1.get("greet") and n2.get("greet") == "again", "日付をまたいでも同じ夜"
        # 毎朝送っていたのが途切れると, 性格によっては気にする (機嫌の理由に残る)
        tr = app.traits(char)
        old = dict(tr)
        tr.update(approach=1.8, absence=1.8)
        missed = 0
        for i in range(60):
            st["reasons"], st["greet_miss"] = [], {}
            st["greet_days"] = {"greet_morning": [(datetime.fromtimestamp(at("08:00", days=-d))).strftime("%Y-%m-%d")
                                                  for d in range(1, 8)]}
            st["params"]["affection"] = 60
            M.settle(char, st, at("13:00"))
            missed += any(r.get("action") == "_greet_miss" for r in st["reasons"])
            M.settle(char, st, at("14:00"))      # 同じ日は一度だけ
        assert 20 < missed < 59, missed
        tr.clear()
        tr.update(old)
        st["reasons"], st["greet_miss"] = [], {}
        st["greet_days"] = {"greet_morning": [(datetime.fromtimestamp(at("08:00", days=-d))).strftime("%Y-%m-%d") for d in (1, 3)]}
        for _ in range(30):
            st["greet_miss"] = {}
            M.settle(char, st, at("13:00"))
        assert not any(r.get("action") == "_greet_miss" for r in st["reasons"]), "習慣になっていなければ気にしない"
        print("あいさつ: 習慣の途切れを気にした %d/60" % missed)

        # ---- 7. スタンプ: メッセージにスタンプだけで返す / 続けて送る
        st["stamps"] = []
        only = sum(reply("stamp", meta={"answering": True})[0] == "stamp_only" for _ in range(200))
        assert 20 < only < 180 and reply("stamp", meta={})[0] == "stamp", only
        assert reply("stamp", meta={"stamps": 2})[0] == "stamp_spam"
        for i in range(3):
            m = M.on_send(char, st, "stamp", now + i * 60)
        assert m["stamps"] == 2
        print("スタンプ: スタンプだけ？ %d/200" % only)

        # ---- 8. 今いい？: いいよ (すぐかけると出てもらいやすい. 少しだけ) / あとで
        st["params"].update(mood=60, stress=20)
        ks = [reply("may_call")[0] for _ in range(200)]
        assert 0.6 < ks.count("may_call_ok") / 200.0 < 0.97, ks.count("may_call_ok")
        st["params"]["stress"] = 90
        assert reply("may_call")[0] == "may_call_later"
        print("今いい？: いいよ %d/200" % ks.count("may_call_ok"))

        # ---- 9. お疲れさま: 予定を知っていて, ちょうど終わった頃なら効く / 的外れなら「？」
        from core import knowsched as ks_mod
        dt = datetime.now()
        e = {"days": "all", "from": "%02d:00" % ((dt.hour - 3) % 24), "to": "%02d:%02d" % ((dt.hour - 1) % 24, dt.minute),
             "label": "バイト中", "busy": True, "workplace": "cafe", "activity": "work"}
        if dt.hour < 3:
            e.update({"from": "00:00", "to": "%02d:%02d" % (dt.hour, dt.minute)})
        char.setdefault("schedule", []).append(e)
        st["known"] = []
        assert reply("otsukare")[0] == "otsukare_odd", "予定を知らなければ"
        app.knowsched.learn(cid, e, "talk", now)
        assert reply("otsukare")[0] == "otsukare"
        char["schedule"].remove(e)
        print("お疲れさま: OK")

        # ---- 10. 大丈夫？: 落ち込み・体調を知っていれば効く (気配りで効き方が変わる) / 知らなければ「何が？」
        st["reasons"], st["seen_down"] = [], 0
        st["params"].update(mood=60, health=90)
        assert reply("you_ok")[0] == "you_ok_what"
        L.add_reason(st, "event", "bad", "友だちとケンカした", now, told=True, delta=-6)
        L.player_state()["skills"]["care"] = 10
        lo = reply("you_ok")[1]["mood"]
        L.player_state()["skills"]["care"] = 90
        hi = reply("you_ok")[1]["mood"]
        assert hi > lo, (lo, hi)
        st["reasons"] = []
        st["params"]["health"] = 30
        M.saw_down(st, now)
        assert reply("you_ok")[0] == "you_ok"
        st["params"]["health"] = 90
        print("大丈夫？: 気配り 10 → %.1f / 90 → %.1f" % (lo, hi))

        # ---- 11. 今何してる？: 今のことが分かる / 聞きすぎると束縛っぽい
        st["whatdo"] = []
        m = M.on_send(char, st, "what_doing", now)
        key, _, ex = reply("what_doing", meta=m)
        assert key == "what_doing" and ex["doing"], ex
        M.on_send(char, st, "what_doing", now + 60)
        m = M.on_send(char, st, "what_doing", now + 120)
        assert reply("what_doing", meta=m)[0] == "what_doing_much"
        print("今何してる？:", C.line(char, key, ex))

        # ---- 12. 返事まだ？: ほぼ逆効果 / 急ぎの話なら多少許される / もう返しているのに
        st["reasons"] = []
        st.pop("msg_pending", None)
        st["contacts"], st["cooldowns"] = [], {}
        app.bonds.set_stage(cid, "contact")
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}
        C.send(cid, "smalltalk")
        C.send(cid, "nudge")
        assert st["msg_pending"]["nudge"] == "bad" and st["msg_pending"]["kind"] == "smalltalk"
        st["msg_pending"].update(due=time.time() - 1, reply=True)
        mood0 = st["params"]["mood"]
        app.deliver_due()
        items = C.thread(cid)["items"]
        assert any(it["kind"] == "nudge_bad" for it in items[-3:]), [it["kind"] for it in items[-3:]]
        assert any(r.get("action") == "_nudge" for r in st["reasons"])
        assert M.nudge_urgent(char, st, {"kind": "appoint"}, now)
        assert reply("nudge")[0] == "nudge_huh"
        print("返事まだ？: 気分 %.1f → %.1f" % (mood0, st["params"]["mood"]))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
