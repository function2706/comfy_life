"""キャラクターの所持金の収支 (core/purse.py. 残件 A17 の段 3) の確認 (一時データディレクトリ, 画像生成なし).

    python tools/test_purse.py
"""
import copy
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, lifetype, purse, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
D0 = date(2026, 1, 1)
SEEDS = 12


def person(base, tid, seed, age=28, persona="tsundere"):
    """型 tid の人 (定義だけ. 性格の savings は 1.0 のツンデレを既定に)."""
    c = copy.deepcopy(base)
    c.update(id="p_%s_%d" % (tid, seed), age=age, persona_id=persona, persona="")
    if tid:
        c["life"] = lifetype.decide(c, {}, seed="s%d" % seed, type_id=tid)
        c["schedule"] = lifetype.build(c)
    else:
        c.pop("life", None)
    return c


def state(money):
    return {"money": {"a": money}, "params": {"affection": 60, "trust": 60, "mood": 50}}


def run(P, c, st, d0, days, log=None):
    P.rec(c, st, d0)
    for i in range(days):
        d = d0 + timedelta(days=i)
        a0 = st["money"]["a"]
        short = P.close(c, st, d)
        if log is not None:
            log.append((d + timedelta(days=1), st["money"]["a"] - a0, short))
    return st["money"]["a"]


def main():
    random.seed(4)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        P, L = app.purse, app.life
        base = app.char()
        S, out = P.base()
        assert abs(S - 2500 * 30.4) < 1 and out == 1500

        # ---- 1. 型ごとに 1 年: 貯まり方・0 円を下回らない・給料日に増える・在宅は月ごとに揺れる
        target = (2500 - 1500) * 30.4
        tot_w = tot = 0.0
        for tid, T in lifetype.TYPES.items():
            saves, lows, avgs = [], [], []
            for seed in range(SEEDS):
                c = person(base, tid, seed)
                st, log = state(300000), []
                run(P, c, st, D0, 365, log)
                saves.append((st["money"]["a"] - 300000) / 12.0)
                bal, a = [], 300000
                for _, da, _s in log:
                    a += da
                    bal.append(a)
                lows.append(min(bal))
                pd = P.payday(c, T["pay"])
                on = [da for d, da, _s in log if d.day == pd]
                off = [da for d, da, _s in log if d.day != pd and d.day != 1]
                assert len(on) == 12 and sum(on) / 12.0 > sum(off) / len(off) + 10000 or T["pay"]["kind"] == "irregular", (tid, on)
                assert max(off) <= 0 or T["pay"].get("allowance"), (tid, "給料日・仕送りの日のほかに増える日がある", max(off))
                if T["pay"]["kind"] == "irregular":
                    assert len({int(x) for x in on}) >= 6 and min(on) < 0.6 * max(on), ("在宅は月ごとに揺れる", on)
                inc, sp = P.average(c)
                avgs.append((inc - sp) * 30.4)
            m = sum(saves) / len(saves)
            am = sum(avgs) / len(avgs)          # 平均 (追いつけなかった分に使う) が, 実際の 1 年とだいたい合う (型の平均どうしで)
            assert abs(am - m) < (0.5 if T["pay"]["kind"] == "irregular" else 0.25) * target, (tid, am, m)
            assert min(lows) >= 0 and m > 0, (tid, m, min(lows))
            print("  %-9s 月の貯まり方 %7d 円 (%d〜%d)" % (tid, m, min(saves), max(saves)))
            tot += m * T["weight"]
            tot_w += T["weight"]
        avg = tot / tot_w
        assert 0.8 * target <= avg <= 1.2 * target, ("全員の平均は以前と同じ (月に +3 万円ほど)", avg, target)
        print("型ごとの収支: OK | 全員の平均 月 %d 円 (目標 %d)" % (avg, target))

        # ---- 2. 所持金が少なくても 0 円で止まる (借金は作らない). 払いきれない日は True
        c = person(base, "student", 1, age=20)
        st, log = state(0), []
        run(P, c, st, D0, 120, log)
        assert st["money"]["a"] >= 0 and any(s for _, _, s in log)
        print("0 円で止まる: OK | 払いきれなかった日 %d / 120" % sum(1 for _, _, s in log if s))

        # ---- 3. 同じ日を二度締めない・まとめて締めても同じ・状態を保存して読み直しても同じ
        for tid in lifetype.TYPES:
            c = person(base, tid, 3)
            a, b, e = state(80000), state(80000), state(80000)
            run(P, c, a, D0, 60)
            P.rec(c, b, D0)
            for i in range(60):
                d = D0 + timedelta(days=i)
                P.close(c, b, d)
                assert P.close(c, b, d) is False and P.close(c, b, d - timedelta(days=3)) is False
            run(P, c, e, D0, 30)
            e = copy.deepcopy(e)
            for i in range(30, 60):
                P.close(c, e, D0 + timedelta(days=i))
            assert a["money"] == b["money"] == e["money"], (tid, a["money"], b["money"], e["money"])
        print("二重に締めない・途中で読み直しても同じ: OK")

        # ---- 4. 風邪で休んだ日は収入が減る (月給・時給)
        for tid in ("office", "shift"):
            c = person(base, tid, 5)
            well, sick = state(100000), state(100000)
            t0 = datetime(2026, 1, 5).timestamp()
            sick["ill"] = {"level": 2, "t0": t0, "until": t0 + 5 * 86400}
            la, lb = [], []
            run(P, c, well, D0, 31, la)
            run(P, c, sick, D0, 31, lb)
            pd = P.payday(c, lifetype.TYPES[tid]["pay"])
            ia = [da for d, da, _s in la if d.day == pd][0]
            ib = [da for d, da, _s in lb if d.day == pd][0]
            assert ib < ia - 3000, (tid, ia, ib)
        print("風邪で休むと減る: OK")

        # ---- 5. 同居相手: 住まい・暮らしは引かない (あなたの家の分は pay_home). 買い物だけ
        c = person(base, "office", 7)
        alone, live = state(200000), state(200000)
        run(P, c, alone, D0, 90)
        liv0 = app.bonds.living
        app.bonds.living = lambda: c["id"]
        try:
            run(P, c, live, D0, 90)
            assert P.average(c)[1] < 0.4 * out
        finally:
            app.bonds.living = liv0
        diff = live["money"]["a"] - alone["money"]["a"]
        want = out * (purse.LIVING + purse.HOME * 1.1) * 90
        assert 0.7 * want < diff < 1.3 * want, (diff, want)
        print("同居相手は住まい・暮らしを引かない: OK | 差 %d 円 / 90 日" % diff)

        # ---- 6. 型の無い人は以前のまま (毎日 +2,500 / −1,500)
        c = person(base, None, 0)
        st = state(10000)
        for i in range(10):
            P.close(c, st, D0 + timedelta(days=i))
        assert st["money"]["a"] == 10000 + 10 * 1000 and "pay" not in st["money"]
        print("型の無い人は以前のまま: OK")

        # ---- 7. 既存の人の所持金は変えない / 時給の人は, それまで働いた分が入っている / 新しい人は型と年齢で
        c = person(base, "shift", 2)
        st = state(43210)
        p = P.rec(c, st, date(2026, 11, 14))
        assert st["money"]["a"] == 43210 and p["last"] == "2026-11-13" and p["h"] > 20, p
        c2 = person(base, "office", 2)
        assert P.rec(c2, state(1), date(2026, 11, 14))["h"] == 0
        hina = app.state("hina")
        a0 = L.her_money(hina)["a"]
        assert L.init_her_money("hina", hina) is False and L.her_money(hina)["a"] == a0
        assert abs(P.start_mult(person(base, "student", 0, age=20)) - 0.2) < 1e-9 and abs(P.start_mult(person(base, "office", 0, age=30)) - 1.2) < 1e-9
        assert purse.age_mult(None) == 1.0 and purse.age_mult(70) == 2.0
        print("既存の人の所持金はそのまま・新しい人は型と年齢で: OK")

        # ---- 8. 追いつけなかった分 (14 日を超えた分) は平均でまとめて
        c = person(base, "office", 4)
        st = state(50000)
        inc, sp = P.average(c)
        add = P.skip(c, st, 16)
        assert add == int(round((inc - sp) * 16, -2)) > 0 and st["money"]["a"] == 50000 + add and P.skip(c, st, 0) == 0
        calls = []
        sk0 = P.skip
        P.skip = lambda ch, s, days: calls.append(days) or sk0(ch, s, days)
        hina["last_tick"] = time.time() - 30 * 86400
        app.tick("hina")
        P.skip = sk0
        assert calls == [16], calls
        last = L.her_money(hina)["pay"]["last"]
        assert last == (date.today() - timedelta(days=1)).isoformat(), last          # 日締めが life.step から呼ばれている
        print("追いつけなかった分: OK | 16 日ぶん %d 円" % add)

        # ---- 9. 苦しいとき: その場の残高で決まる・おごらない・割り勘の申し出・断り・誘い・お金の受け取り
        char = app.char()
        st = app.state("hina")
        hm = L.her_money(st)
        lim = purse.TIGHT_DAYS * P.living_per_day(char)
        hm["a"] = int(lim) - 100
        assert P.tight(char, st)
        hm["a"] = int(lim) + 100
        assert not P.tight(char, st)
        L.player_state()["money"] = 100000
        char["pay_policy"] = "auto"
        hm["a"] = 9000                          # 苦しいが, 割り勘なら払える
        got = {L.plan_payment(char, st, 2000)["payer"] for _ in range(400)}
        assert got == {"split", "me"}, got
        hm["a"] = 500000
        assert "her" in {L.plan_payment(char, st, 2000)["payer"] for _ in range(400)}
        hm["a"] = 9000
        char["pay_policy"] = "her"
        pl = L.plan_payment(char, st, 2000)
        assert pl["payer"] == "split" and pl["note"] == "tight_split", pl
        hm["a"] = 500000
        assert L.plan_payment(char, st, 2000)["payer"] == "her"
        hm["a"] = 9000
        L.player_state()["money"] = 100
        for pol in ("auto", "her", "split", "me"):
            char["pay_policy"] = pol
            try:
                L.plan_payment(char, st, 2000)
                raise AssertionError("苦しい相手に出させている: " + pol)
            except ValueError as ex:
                assert "きびしく" in str(ex), ex
        hm["a"] = 500000
        char["pay_policy"] = "auto"
        assert L.plan_payment(char, st, 2000)["payer"] == "her"      # 苦しくなければ, 今までどおり出してくれる
        L.player_state()["money"] = 100000
        # 誘う行き先: お金のかかることを避ける
        A = app.appoint
        opts = [("park", {"id": "walk"}), ("cafe", {"id": "tea", "cost": 1500})]
        w0 = A.place_weight
        A.place_weight = lambda ch, s, pid: 1.0
        try:
            hm["a"] = 9000
            n_t = sum(1 for _ in range(2000) if A.pick(char, st, opts)[0] == "cafe")
            hm["a"] = 500000
            n_f = sum(1 for _ in range(2000) if A.pick(char, st, opts)[0] == "cafe")
        finally:
            A.place_weight = w0
        assert n_t < 0.65 * n_f and 380 < n_t < 560 and 900 < n_f < 1100, (n_t, n_f)
        # お金の受け取り (お小遣い): 苦しいと受け取りやすい. 誇りの高い性格は, それでも断ることが多い
        B = app.bonds
        res = {}
        for pid in ("tsundere", "amaenbo", "kedakai"):
            char["persona_id"] = pid
            for label, money in (("tight", 3000), ("fine", 500000)):
                hm["a"] = money
                app.set_params({"affection": 45, "trust": 45, "mood": 50})
                st["gifts"] = []
                res[pid, label] = sum(1 for _ in range(1500) if B.gift_feel(char, st, time.time(), money=True) >= 45) / 1500.0
            assert res[pid, "fine"] + 0.1 < res[pid, "tight"] < 0.97, (pid, res)
            hm["a"] = 3000                      # 物の贈り物の受け止めは変えない
            g1 = sum(B.gift_feel(char, st, time.time()) for _ in range(1500)) / 1500.0
            hm["a"] = 500000
            g2 = sum(B.gift_feel(char, st, time.time()) for _ in range(1500)) / 1500.0
            assert abs(g1 - g2) < 2.5, (pid, g1, g2)
        assert res["kedakai", "tight"] < res["tsundere", "tight"] < res["amaenbo", "tight"], res
        print("苦しいとき: OK | お小遣いを受け取る割合 (苦しい / ふつう) " + " ".join(
            "%s %.2f/%.2f" % (pid, res[pid, "tight"], res[pid, "fine"]) for pid in ("amaenbo", "tsundere", "kedakai")))

        # ---- 10. お小遣い: 苦しい相手に渡すと, その場で苦しくなくなる (残高から見る)
        char["persona_id"] = "amaenbo"
        app.set_params({"affection": 95, "trust": 95, "mood": 80, "energy": 90, "sleepiness": 0, "health": 90})
        st.update(override={"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": 9e12})
        hm["a"] = int(lim) - 3000
        st["gifts"], st["cooldowns"] = [], {}
        assert P.tight(char, st)
        e = app.act("allowance")["entry"]
        assert e.get("money") == {"p": -5000, "a": 5000} and not P.tight(char, st), e.get("money")
        print("お小遣いで苦しさが抜ける: OK")

        # ---- 11. 画面のデータに相手の所持金・苦しさが出ない
        import json
        blob = json.dumps(app.state_view(), ensure_ascii=False, default=str)
        assert '"tight"' not in blob and '"pay": {"last"' not in blob
        print("画面に出ない: OK")

        # ---- 12. 苦しいことが, 聞けば分かる話になる (性格・仲しだいで 言う / 濁す / 言わない. 一日ごとに決める)
        now = time.time()
        today = datetime.fromtimestamp(now).date().isoformat()

        def mine():
            return [r for r in st.get("reasons") or [] if r.get("ev") == "purse_tight" and not r.get("resolved")]

        def fresh(money):
            st["reasons"] = []
            hm.pop("hint", None)
            hm["a"] = money
            return P.surface(char, st, now)

        rate = {}
        for pid in ("amaenbo", "tsundere", "kedakai"):
            char["persona_id"] = pid
            for aff in (45, 85):
                app.set_params({"affection": aff, "trust": aff, "mood": 50})
                n = {"plain": 0, "vague": 0, "none": 0}
                for _ in range(600):
                    fresh(int(lim) - 3000)
                    n[hm["hint"]["how"]] += 1
                    assert bool(mine()) == (hm["hint"]["how"] != "none"), hm["hint"]      # 言わない日は何も置かない
                rate[pid, aff] = n
            assert sum(rate[pid, 45].values()) == 600
            open45 = 1 - rate[pid, 45]["none"] / 600.0
            open85 = 1 - rate[pid, 85]["none"] / 600.0
            assert open45 < open85, (pid, rate)                                           # 仲が深いほど打ち明ける
        op = {k: 1 - v["none"] / 600.0 for k, v in rate.items()}
        assert op["kedakai", 45] < op["tsundere", 45] < op["amaenbo", 45], op            # 誇りの高い性格ほど隠す
        assert op["kedakai", 85] > 0.1 and op["amaenbo", 85] < 1.0, op                   # 必ずではない (公理)
        assert rate["amaenbo", 85]["plain"] > rate["amaenbo", 85]["vague"] and rate["kedakai", 45]["vague"] > rate["kedakai", 45]["plain"], rate
        # 苦しくなければ何も置かない
        assert fresh(int(lim) + 3000) is None and not mine() and "hint" not in hm
        # 同じ日は決め直さない (言わない日はその日ずっと言わない)
        char["persona_id"] = "amaenbo"
        app.set_params({"affection": 85, "trust": 85, "mood": 50})
        fresh(int(lim) - 3000)
        hm["hint"] = {"d": today, "how": "none", "tell": ""}
        st["reasons"] = []
        for _ in range(50):
            assert P.surface(char, st, now) is None and not mine()
        # 言う日: 置くのは一つ. 苦しさが抜けると, その場で解決済み
        hm["hint"] = {"d": today, "how": "plain", "tell": purse.TELL["plain"][0]}
        P.surface(char, st, now)
        P.surface(char, st, now + 60)
        assert len(mine()) == 1 and mine()[0]["kind"] == "event" and mine()[0]["mood"] == "bad" and not mine()[0]["told"]
        hm["a"] = int(lim) + 3000
        P.surface(char, st, now + 120)
        assert not mine(), "苦しさが抜けたら消える"
        # 相談などで解決済みにされたら, 12 時間は置き直さない
        hm["a"] = int(lim) - 3000
        st["reasons"] = []
        P.surface(char, st, now)
        L.resolve(st, "bad", now + 60)
        assert P.surface(char, st, now + 120) is None and not mine()
        assert P.surface(char, st, now + 13 * 3600) and mine()
        # 出来事「お金がピンチ」が話せるうちは, 重ねて置かない
        st["reasons"] = []
        L.add_reason(st, "event", "bad", "今月ちょっとお金が厳しい", now, told=False, ev="money_tight")
        assert P.surface(char, st, now + 60) is None and not mine()
        # 聞けば分かる: 「最近どう？」で話す. 話したあとは「ようす」に出る
        C = app.chat
        st["reasons"] = []
        hm["hint"] = {"d": today, "how": "plain", "tell": purse.TELL["plain"][0]}     # その日の打ち明け方はくじ (はっきり言う日に固定)
        P.surface(char, st, now)
        key, eff, extra = C.reply(char, st, "ask_how", now + 60, {})       # 届いた「最近どう？」への返事の中身 (同居なので送る経路は通らない)
        assert key == "ask_how" and any(t in extra.get("news", "") for t in purse.TELL["plain"]), (key, extra)   # 言い方は 2 通りのどちらか
        assert any(r["tell"] in purse.TELL["plain"] for r in app.life.partner_view(char, st)["reasons"])
        # 電話の話題: お金のことは「今日、」の包みにしない
        st["reasons"] = []
        hm["hint"] = {"d": today, "how": "vague", "tell": purse.TELL["vague"][0]}
        P.surface(char, st, now)
        r0 = random.random
        random.random = lambda: 0.0
        try:
            kind, key, text = app.phonetalk._topic(char, st, {"deep": 0}, now + 60)
        finally:
            random.random = r0
        assert purse.TELL["vague"][0] in text and "今日" not in text, text
        blob = json.dumps(app.state_view(), ensure_ascii=False, default=str)
        assert not any('"how": "%s"' % h in blob for h in ("plain", "vague", "none")) and '"a": %d' % hm["a"] not in blob   # その日の決め・所持金の額は出ない (香りの欄の how は別物)
        print("苦しいことの打ち明け: OK | 打ち明ける割合 (好感度 45 / 85) " + " ".join(
            "%s %.2f/%.2f" % (pid, op[pid, 45], op[pid, 85]) for pid in ("amaenbo", "tsundere", "kedakai")))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
