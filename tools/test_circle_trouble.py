"""相手の交友関係 段 3 (core/circle.py: 負の出来事と人の移り).

遡及 (v1 の記録に元恋人・言い寄る人を一度だけ・決まった形で) / 元恋人・言い寄る人とは予定を作らない /
予定のあとの仲の動き (喧嘩・和解・効き目は終わってすぐだけ) / 疎遠で抜ける (知っている人は関係性タブに残る・予定も消える) /
新しい人 (上限) / 言い寄る人 (連絡でストレス・好意が冷めて諦める) / 元恋人 (こじれていれば迷惑・未練なら揺れる) /
相談 (話そうの理由・電話の切れ目・一度だけ・1 日で消える・聞けばストレスが下がる) / 日締めの二重・追いつき. 一時データで.

    python tools/test_circle_trouble.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, circle as C, msgreply  # noqa: E402
from core import phonetalk as PT  # noqa: E402


def person(pid, name, kind, tone, close, since, **flags):
    p = {"pid": pid, "name": name, "kind": kind, "tone": tone, "close": close, "since": since, "haunt": ["cafe"]}
    if flags:
        p["flags"] = dict(flags)
    return p


def main():
    random.seed(353)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("負の出来事")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        now = time.time()

        # ---- 1. 遡及: 段 1・2 の記録 (v1) に, 元恋人・言い寄る人を一度だけ決まった形で足す. 新しく作るときも同じ
        st.pop("circle", None)
        r = app.circle.rec(char, st, now)
        base = [p for p in r["people"] if p["kind"] not in C.HIDE_KINDS]
        extra = [(p["name"], p["kind"], p["tone"]) for p in r["people"] if p["kind"] in C.HIDE_KINDS]
        old = {"v": 1, "people": [dict(p) for p in base], "plans": [], "partner": None, "made_to": "2026-01-01",
               "known": {base[0]["pid"]: {"t0": now, "t": now, "via": "talk"}}}
        st["circle"] = old
        r = app.circle.rec(char, st, now)
        assert r is old and r["v"] == C.V and r["known"] and r["made_to"] == "2026-01-01"
        assert [(p["name"], p["kind"], p["tone"]) for p in r["people"] if p["kind"] in C.HIDE_KINDS] == extra
        n = len(r["people"])
        assert len(app.circle.rec(char, st, now)["people"]) == n                     # 二度足さない
        assert len({p["pid"] for p in r["people"]}) == n and len({p["name"] for p in r["people"]}) == n
        cnt, flags_ok = Counter(), True
        for i in range(600):
            c2 = dict(char, id="y%d" % i, age=17 if i % 3 == 0 else 26)
            ex = app.circle._extra_people(c2, base, now)
            assert ex == app.circle._extra_people(c2, base, now)                     # 決まった形
            for p in ex:
                cnt[(p["kind"], "minor" if i % 3 == 0 else "adult")] += 1
                assert p["name"] not in {q["name"] for q in base} and int(p["pid"][1:]) > len(base)
                fl = p["flags"]
                flags_ok &= 0 <= fl["pull"] <= 35 and (p["kind"] != "suitor" or 55 <= fl["interest"] <= 85)
        assert flags_ok
        assert 0.35 < cnt[("ex", "adult")] / 400.0 < 0.55 and cnt[("ex", "minor")] / 200.0 < 0.25, cnt
        assert 0.04 < (cnt[("suitor", "adult")] + cnt[("suitor", "minor")]) / 600.0 < 0.22, cnt
        print("遡及: OK | 足した %s / 元恋人 大人 %d/400・未成年 %d/200 / 言い寄る人 %d/600" % (
            extra or "なし", cnt[("ex", "adult")], cnt[("ex", "minor")], cnt[("suitor", "adult")] + cnt[("suitor", "minor")]))

        # ---- 2. 元恋人・言い寄る人とは予定を作らない (段 4 まで)
        r["people"] = [person("p1", "佐藤", "friend", "warm", 70, now), person("p2", "田中", "ex", "warm", 40, now, interest=50, pull=20),
                       person("p3", "伊藤", "suitor", "uneasy", 20, now, interest=70, persist=0.6, pull=5)]
        r["plans"], r["made_to"] = [], ""
        for d in range(40):
            app.circle.daily(char, st, now + d * 86400)
        assert r["plans"] and all(x["pid"] == "p1" for x in r["plans"]), r["plans"]
        print("予定は会う人だけ: OK | %d 件" % len(r["plans"]))

        # ---- 3. 予定のあとの仲: 喧嘩はまれ (親しい 1.2%)・こじれた人とは和解することも. 効き目は終わってすぐだけ
        q = Counter()
        for i in range(3000):
            p = person("p1", "佐藤", "friend", "warm", 70, now - 86400)
            r["people"] = [p]
            st["params"].update(stress=30, mood=60)
            x = {"t0": now - 7200, "t1": now - 600, "pid": "p1", "place": "cafe", "kind": "meal"}
            app.circle._after(char, st, r, x, now)
            assert p["flags"]["last"] == x["t1"]
            if p["tone"] == "strained":
                q["quarrel"] += 1
                assert st["params"]["stress"] > 30 and st["params"]["mood"] < 60 and p["close"] < 70
        assert 15 < q["quarrel"] < 60, q
        for i in range(1000):
            p = person("p1", "佐藤", "friend", "strained", 20, now - 86400)
            r["people"] = [p]
            st["params"].update(stress=30, mood=60)
            old = i % 2 == 0                                    # 閉じていた間の古い予定: 仲だけ動かす
            x = {"t0": now - 30 * 3600, "t1": now - 28 * 3600, "pid": "p1", "place": "cafe", "kind": "meal"} if old else \
                {"t0": now - 7200, "t1": now - 600, "pid": "p1", "place": "cafe", "kind": "meal"}
            app.circle._after(char, st, r, x, now)
            if p["tone"] == "plain":
                q["mend"] += 1
                assert (st["params"]["stress"] == 30) == old, (old, st["params"])
        assert 180 < q["mend"] < 320, q
        print("仲の動き: OK | 喧嘩 %d/3000・和解 %d/1000" % (q["quarrel"], q["mend"]))

        # ---- 4. 疎遠で抜ける: 印だけ (知っている人は関係性タブに残る). 先の予定も消える. 久しく知らない人は記録から消える
        r["people"] = [person("p1", "佐藤", "friend", "plain", 10, now - 200 * 86400, last=now - 90 * 86400),
                       person("p4", "高橋", "friend", "plain", 10, now - 200 * 86400, last=now - 90 * 86400),
                       person("p5", "山田", "coworker", "plain", 40, now - 200 * 86400),
                       person("p6", "森", "family", "plain", 5, now - 400 * 86400, last=now - 300 * 86400)]
        r["known"] = {"p1": {"t0": now, "t": now, "via": "talk", "feel": "warm"}}
        r["plans"] = [{"t0": now + 86400, "t1": now + 90000, "pid": "p1", "place": "cafe", "kind": "meal"}]
        r["d3"] = ""
        app.circle._daily3(char, st, r, now)
        gone = {p["pid"] for p in r["people"] if p.get("gone")}
        assert gone >= {"p1", "p4"} and "p6" not in gone, gone             # 家族は抜けない
        assert not r["plans"]
        kv = app.circle.known_view(char, st)
        assert [k["label"] for k in kv] == ["友達の佐藤さん"], kv           # 抜けたことは見せない
        assert app.circle.who_label(char, st, "p1") == "友達の佐藤さん"
        app.circle._daily3(char, st, r, now + 121 * 86400)
        pids = {p["pid"] for p in r["people"]}
        assert "p1" in pids and "p4" not in pids, pids                     # 知っている人は残す / 知らない人は消す
        print("疎遠: OK | 抜けた %s / 関係性タブ %s" % (sorted(gone), [k["label"] for k in kv]))

        # ---- 5. 新しい人: 人が多いほど加わりにくく, 上限で止まる. 名前・pid は重ならない
        r["people"] = [person("p%d" % i, C.SURNAMES[i], "friend", "plain", 50, now, last=now) for i in range(1, 4)]
        r["known"], r["plans"] = {}, []
        sizes = []
        for d in range(3000):
            app.circle._daily3(char, st, r, now + d * 86400)
            for p in app.circle.alive(r):
                p.setdefault("flags", {})["last"] = now + d * 86400     # 会っていることにする (疎遠で抜けない)
            sizes.append(len(app.circle.alive(r)))
        assert max(sizes) <= C.PEOPLE_MAX and sizes[-1] >= 7, (max(sizes), sizes[-1])
        assert len({p["pid"] for p in r["people"]}) == len(r["people"])
        al = app.circle.alive(r)
        assert len({p["name"] for p in al}) == len(al)
        print("新しい人: OK | 3 人から %d 人 (上限 %d)" % (sizes[-1], C.PEOPLE_MAX))

        # ---- 6. 言い寄る人: 連絡でストレスが上がり, 応じないので好意が冷めて, いずれ諦める
        sui = person("p9", "伊藤", "suitor", "uneasy", 20, now, interest=80, persist=0.8, pull=5)
        r["people"], r["events"], r["plans"] = [person("p1", "佐藤", "friend", "warm", 70, now, last=now), sui], [], []
        st["params"].update(stress=20, mood=60, affection=60)
        app.circle._event(char, st, r, {"t": now - 60, "kind": "pester", "pid": "p9"}, now)
        assert st["params"]["stress"] > 26 and st["params"]["mood"] < 60 and sui["flags"]["interest"] < 80
        days, pings = 0, 0
        t = now
        while not sui.get("gone") and days < 400:
            t += 86400
            days += 1
            r["d3"] = ""
            app.circle._daily3(char, st, r, t)
            for e in list(r.get("events") or []):
                pings += 1
                r["events"].remove(e)
                app.circle._event(char, st, r, e, e["t"])
        assert sui.get("gone") and 20 <= days <= 200 and pings >= 5, (days, pings)
        assert not any(e["pid"] == "p9" for e in r.get("events") or [])
        print("言い寄る人: OK | %d 日・連絡 %d 回で諦めた" % (days, pings))

        # ---- 7. 元恋人: こじれていれば迷惑 (ストレス), 未練があれば揺れる (寂しさ・pull が少し. 上限)
        exs = person("p7", "田中", "ex", "strained", 30, now, interest=50, pull=0)
        exw = person("p8", "中村", "ex", "warm", 40, now, interest=50, pull=58)
        r["people"] = [exs, exw]
        st["params"].update(stress=20, mood=60, loneliness=30)
        app.circle._event(char, st, r, {"t": now, "kind": "ex", "pid": "p7"}, now)
        assert st["params"]["stress"] > 24 and st["params"]["loneliness"] == 30
        st["params"].update(stress=20, mood=60, loneliness=30)
        for _ in range(20):
            app.circle._event(char, st, r, {"t": now, "kind": "ex", "pid": "p8"}, now)
        assert st["params"]["loneliness"] > 30 and 58 <= exw["flags"]["pull"] <= 60 and exw["flags"]["interest"] < 50
        print("元恋人: OK | こじれて迷惑・未練で揺れる (pull %.1f)" % exw["flags"]["pull"])

        # ---- 8. 相談: 話そうの理由 (言い寄られている / 元恋人) に. 一度だけ・1 日で消える・愚痴が先. 好感度が低いと話しにくい
        told = Counter()
        for i in range(1000):
            r.pop("talk", None)
            ck = ("pester", "ex", "ex")[i % 3]
            pid = {"pester": "p9", "ex": "p7" if i % 3 == 1 else "p8"}[ck]
            r["people"] = [exs, exw, dict(sui, flags=dict(sui["flags"], interest=80))]
            r["people"][2].pop("gone", None)
            st["params"]["affection"] = 20 if i >= 900 else 60
            app.circle._event(char, st, r, {"t": now, "kind": ck, "pid": pid}, now)
            key = "low" if i >= 900 else ("pester" if ck == "pester" else "ex_strained" if pid == "p7" else "ex")
            told[key] += bool(r.get("talk"))
        for k, lo, hi in (("pester", 0.45, 0.65), ("ex_strained", 0.35, 0.55), ("ex", 0.12, 0.3)):
            seen = sum(1 for i in range(900) if (("pester" if i % 3 == 0 else "ex_strained" if i % 3 == 1 else "ex") == k))
            assert lo < told[k] / float(seen) < hi, (k, told[k], seen)
        assert told["low"] < 30, told
        r["talk"] = {"why": "pester", "t": now, "pid": "p9"}
        r["plans"] = []
        assert app.circle.confide(char, st, now + 600) == ("pester", "") and app.circle.confide(char, st, now + 700) is None
        r["talk"] = {"why": "ex", "t": now - C.CONFIDE_SPAN - 60, "pid": "p7"}
        assert app.circle.confide(char, st, now) is None and "talk" not in r
        # 愚痴 (苦手な人と会ったあと) が先. 相談は残る
        r["people"].append(person("p2", "鈴木", "boss", "uneasy", 25, now))
        r["talk"] = {"why": "ex", "t": now, "pid": "p7"}
        C.GRUMBLE_P, gp = 1.0, C.GRUMBLE_P
        r["plans"] = [{"t0": now - 3 * 3600, "t1": now - 3600, "pid": "p2", "place": "restaurant", "kind": "work_after"}]
        assert app.circle.confide(char, st, now) == ("grumble", "上司の鈴木さん") and r.get("talk")
        assert app.circle.confide(char, st, now) == ("ex", "")
        C.GRUMBLE_P = gp
        print("相談のくじ: OK | 言い寄られている %d/300・こじれた元恋人 %d/300・揺れている %d/300・好感度が低い %d/100" % (
            told["pester"], told["ex_strained"], told["ex"], told["low"]))

        # ---- 9. メッセージの「話そう」: 理由が相談になり, 電話にしない・近況を添えない. 聞けばストレスが下がる
        aps = app.approaches
        app.approaches = [dict(a, when="") for a in aps if a["id"] == "msg_chat"]       # いつ流しても出せるように
        try:
            for why in ("pester", "ex"):
                ok = False
                for _ in range(30):
                    st["approach"], st["ap_last"], st["ap_ignored_until"] = None, {}, 0
                    r["talk"] = {"why": why, "t": time.time(), "pid": "p9"}
                    r["plans"] = []
                    ctx = dict(app.context(char, st, datetime.now()), apart=True)
                    e = app.presence.fire(char, st, time.time(), ctx)
                    if e and (st.get("approach") or {}).get("why") == why:
                        assert "{" not in e["text"] and e["text"].startswith("📱"), e["text"]
                        assert not (st.get("approach") or {}).get("wave")
                        assert (st.get("ring") or {}).get("state") not in ("ringing",)
                        ok = True
                        break
                assert ok, why
        finally:
            app.approaches = aps
        drop = Counter()
        for i in range(200):
            why = ("pester", "ex")[i % 2]
            kind = ("worry", "curt")[(i // 2) % 2]
            st["params"].update(stress=60, mood=55, affection=60)
            st["approach"] = {"id": "msg_chat", "t": now, "until": now + 900, "why": why, "who": ""}
            app.presence.reply_land(char, st, "msg_chat", kind, now + i, why=why)
            drop[kind] += 60 - st["params"]["stress"]
        assert drop["worry"] / 100.0 > drop["curt"] / 100.0 + 3, drop
        print("話そう: OK | ストレスの下がり 聞く %.1f・素っ気なく %.1f" % (drop["worry"] / 100.0, drop["curt"] / 100.0))

        # ---- 10. 電話・対面の会話の切れ目にも. 一度だけ. 相づち・掘り下げるで聞けばストレスが下がる
        for why in ("pester", "ex"):
            r["talk"] = {"why": why, "t": time.time(), "pid": "p9"}
            r["plans"] = []
            kd, key, text = app.phonetalk._topic(char, st, {}, time.time())
            assert kd == "topic" and key == PT.CONFIDE_KEYS[why] and "{" not in text and "📱" not in text, (key, text)
            assert app.phonetalk._topic(char, st, {}, time.time())[1] != key
        drop = Counter()
        for i in range(80):
            kind = ("dig", "change")[i % 2]
            app.presence.rec().pop("call", None)
            app.phonetalk.begin(char, st, "もしもし", True, time.time())
            c = app.phonetalk.rec()
            app.phonetalk._new_beat(char, st, c, "topic", PT.CONFIDE_KEYS["pester"], "（相談）", time.time())
            st["params"]["stress"] = 60
            app.phonetalk.reply(kind)
            drop[kind] += 60 - st["params"]["stress"]
            app.presence.rec().pop("call", None)
        assert drop["dig"] / 40.0 > drop["change"] / 40.0 + 2, drop
        print("電話の相談: OK | ストレスの下がり 掘り下げる %.1f・話を変える %.1f" % (drop["dig"] / 40.0, drop["change"] / 40.0))

        # ---- 11. 日締めの二重・追いつき: 同じ日に二度呼んでも段 3 は一度. 閉じていた 5 日を tick で追いついても落ちない・人は上限内
        r["people"] = [person("p1", "佐藤", "friend", "warm", 70, now, last=now), sui]
        sui.pop("gone", None)
        sui["flags"]["interest"] = 80
        r["d3"] = ""
        app.circle.daily(char, st, now)
        i0 = sui["flags"]["interest"]
        app.circle.daily(char, st, now + 3600)
        assert sui["flags"]["interest"] == i0
        st["last_tick"] = time.time() - 5 * 86400
        app.tick(cid)
        app.tick(cid)
        assert len(app.circle.alive(st["circle"])) <= C.PEOPLE_MAX
        assert all(e["t"] > time.time() - 60 for e in st["circle"].get("events") or [])          # 過ぎた出来事は残らない
        app.circle.step(char, {"params": {}}, now, now + 300)                                   # 記録の無い相手でも落ちない
        print("二重・追いつき: OK | 人 %d" % len(app.circle.alive(st["circle"])))

        # ---- 12. 寂しさ・退屈のならし: 予定の最中は 1, ほかの時間は予定にいる割合でわずかに上げる. ほかのパラメータは 1
        x = {"t0": now + 3600, "t1": now + 3 * 3600, "pid": "p1", "place": "cafe", "kind": "meal"}
        st["circle"]["plans"] = [x]
        sh = app.circle.in_share(char, st)
        for pid in ("loneliness", "boredom"):
            assert app.circle.fill_f(char, st, now + 7200, pid) == 1.0
            f = app.circle.fill_f(char, st, now, pid)
            assert 1 < f < 1.6 and abs(f - (1 + sh / (1 - sh) * C.FILL_RELIEF[pid])) < 1e-3, (pid, f)
        assert app.circle.fill_f(char, st, now, "stress") == 1.0
        print("ならし: OK | 寂しさ %.3f・退屈 %.3f 倍 (予定の割合 %.3f)" % (
            app.circle.fill_f(char, st, now, "loneliness"), app.circle.fill_f(char, st, now, "boredom"), sh))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
