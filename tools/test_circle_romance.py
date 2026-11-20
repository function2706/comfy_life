"""相手の交友関係 段 4 (core/circle.py: 恋愛).

記録の版 (v2 → v3. 付き合っている人は遡及で作らない) / あなたとの関係の自覚 (段階・好感度・見立て) /
誘いへの返事 (自覚あり・ふつうならほぼ受けない・好かれていなければ受けうる) / 会ったあとの傾きと付き合い始め (secret = 自覚) /
付き合っている人とのデートの予定 (仕事・寝ている時間に重ならない・二重にならない) / 別れる (元恋人になる・予定が消える) /
付き合ってる人いるの？ (正直に yes・隠していれば no / はぐらかす. メッセージと会って) / 誰といるの？ のはぐらかし / デートは話さない /
段階の提案・誘いへの効き方 / ばったり見かけて発覚 → 問い詰める (コマンドの出る条件・3 つの結末) /
同居を申し込んで受けてもらえたら別れる / あなたからの「同居をやめる」/ 冷え切った同居で相手から出ていく (メッセージ) /
セリフ (全性格). 一時データで.

    python tools/test_circle_romance.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, circle as C  # noqa: E402

NEW_KEYS = ("chat.ask_single_yes", "ask_single.yes", "confront.default", "confront.defiant", "confront.leave",
            "circle.confess", "circle.move_out")


def person(pid, name, kind, tone, close, now, **flags):
    p = {"pid": pid, "name": name, "kind": kind, "tone": tone, "close": close, "since": now, "haunt": ["cafe", "restaurant"]}
    if flags:
        p["flags"] = dict(flags)
    return p


def main():
    random.seed(404)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("恋愛")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        now = time.time()

        # ---- 1. 記録の版: v2 の記録は v3 に (人はそのまま. 付き合っている人は作らない). 二度は動かさない
        r = app.circle.rec(char, st, now)
        n = len(r["people"])
        r["v"] = 2
        r.pop("partner", None)
        r = app.circle.rec(char, st, now)
        assert r["v"] == C.V == 3 and r["partner"] is None and len(r["people"]) == n
        print("記録の版: OK | v3・人 %d" % n)

        # ---- 2. 自覚: 連絡先 = なし / 家に行ける仲 + 好感度・見立て = あり / 同居 = あり
        st["params"]["affection"] = 80
        assert not app.circle.aware(char, st)
        app.bonds.set_stage(cid, "visit")
        app.regard.rec(char, st)["v"] = 70
        assert app.circle.aware(char, st)
        app.regard.rec(char, st)["v"] = 40
        assert not app.circle.aware(char, st)
        app.bonds.set_stage(cid, "live")
        assert app.circle.aware(char, st)
        app.bonds.set_stage(cid, "contact")
        print("自覚: OK")

        # ---- 3. 誘いへの返事: 自覚あり・ふつうなら, 傾きが高くてもほぼ受けない. 好かれていなければ受けうる
        def invites(aware, neg, aff, pull, k=600):
            ra, rn = C.Circle.aware, C.Circle._neglect
            C.Circle.aware = lambda self, c, s: aware
            C.Circle._neglect = lambda self, c, s, t: neg
            got = Counter()
            try:
                for i in range(k):
                    rr = app.circle.rec(char, st, now)
                    rr["people"] = [person("p1", "佐藤", "suitor", "plain", 30, now, interest=70, persist=0.5, pull=pull)]
                    rr["plans"], rr["partner"] = [], None
                    st["params"]["affection"] = aff
                    o = app.circle._invite(char, st, rr, rr["people"][0], now)
                    got[o] += 1
                    assert len(rr["plans"]) == (0 if o == "no" else 1), (o, rr["plans"])     # 会うなら 2〜6 日のうちに 1 件
                    for x in rr["plans"]:
                        assert x["t0"] > now + 86400 and x["kind"] == ("date" if o == "date" else "meal")
            finally:
                C.Circle.aware, C.Circle._neglect = ra, rn
            return got
        free = invites(False, 0, 30, 70)
        liked = invites(False, 0, 80, 70)
        faith = invites(True, 0, 80, 70)
        lonely = invites(True, 3, 45, 70)
        assert free["date"] > 150, free
        assert liked["date"] < free["date"] * 0.6, (liked, free)
        assert faith["date"] <= 12, faith
        assert faith["date"] < lonely["date"] < free["date"], (faith, lonely, free)
        print("誘いへの返事: OK | デート 好かれていない %d・好かれている %d・自覚あり %d・ご無沙汰がそろう %d (/600)" % (
            free["date"], liked["date"], faith["date"], lonely["date"]))

        # ---- 4. 会ったあと: 傾きは揺らぐ (必ず深まらない). 条件がそろえば付き合い始める (secret = 自覚)
        ups = Counter()
        for i in range(400):
            rr = app.circle.rec(char, st, now)
            p = person("p1", "佐藤", "friend", "warm", 70, now, interest=70, pull=60)
            rr["people"], rr["partner"] = [p], None
            st["params"]["affection"] = 30
            app.circle._romance_after(char, st, rr, p, {"t0": now - 7200, "t1": now - 60, "pid": "p1", "kind": "date"}, now)
            ups["up" if p["flags"]["pull"] > 60 else "down"] += 1
            ups["start"] += bool(rr["partner"])
            if rr["partner"]:
                assert rr["partner"]["pid"] == "p1" and rr["partner"]["secret"] is False
        assert ups["down"] > 30 and ups["up"] > 150 and 60 < ups["start"] < 300, ups      # 必ず深まらない (下がることもある)
        app.bonds.set_stage(cid, "live")
        st["params"]["affection"] = 80
        rr = app.circle.rec(char, st, now)
        p = rr["people"][0]
        rr["partner"] = None
        app.circle._start(char, st, rr, p, now)
        assert rr["partner"]["secret"] is True
        app.bonds.set_stage(cid, "contact")
        print("会ったあと: OK | %s" % dict(ups))

        # ---- 5. 付き合っている人とのデート: 予定ができる. 寝ている・手が離せない時間に重ならない. 同じ日を二度作らない
        rr = app.circle.rec(char, st, now)
        rr["people"] = [person("p1", "佐藤", "friend", "warm", 70, now, interest=70, pull=70)]
        rr["partner"] = {"pid": "p1", "since": now, "secret": False, "found": None}
        rr["plans"], rr["made_to"] = [], ""
        C.SPLIT_P, sp = 0.0, C.SPLIT_P
        seen = {}
        for d in range(28):
            t = now + d * 86400
            app.circle.daily(char, st, t)
            app.circle.daily(char, st, t + 60)                      # 開き直し: 二重にしない
            for x in rr["plans"]:
                seen[(x["t0"], x["pid"])] = x
        C.SPLIT_P = sp
        dates = [x for x in seen.values() if x["kind"] == "date"]
        assert 2 <= len(dates) <= 16, len(dates)
        for x in dates:
            for tt in range(int(x["t0"]), int(x["t1"]), 1800):
                sc = app.own_scene(char, datetime.fromtimestamp(tt))
                assert not (sc["asleep"] or sc["busy"]), (x, sc)
        assert len({x["t0"] for x in dates}) == len(dates)
        rr["plans"] = [dates[-1]]
        sc = app.circle.scene(char, st, {"asleep": False}, datetime.fromtimestamp(dates[-1]["t0"] + 600))
        assert sc["label"].startswith("知り合いと") and sc["effects"]["loneliness"] < 0
        print("デートの予定: OK | 4 週で %d 件" % len(dates))

        # ---- 6. 別れる: 元恋人になり, 先のデートの予定は消える
        rr["plans"] = [x for x in seen.values() if x["t0"] > now + 2 * 86400]
        app.circle._split(char, st, rr, now, "テスト")
        p = rr["people"][0]
        assert rr["partner"] is None and p["kind"] == "ex" and p["flags"]["pull"] <= 35
        assert not [x for x in rr["plans"] if x["pid"] == "p1"]
        print("別れる: OK | %s" % p["tone"])

        # ---- 7. 付き合ってる人いるの？: 正直なら yes (メッセージ・会って). 隠していれば no / はぐらかす だけ
        def ask_msg(k=200):
            got = Counter()
            for i in range(k):
                st["single_ask"] = []
                m = app.manners.on_send(char, st, "ask_single", now)
                got[app.manners.reply(char, st, "ask_single", now, {}, m)[0]] += 1
            return got
        st["params"].update(affection=70, mood=70, trust=70)
        rr["people"] = [person("p1", "佐藤", "suitor", "plain", 40, now, interest=70, pull=70)]
        rr["partner"] = {"pid": "p1", "since": now, "secret": False, "found": None}
        open_ = ask_msg()
        assert open_["ask_single_yes"] > 100 and set(open_) <= {"ask_single_yes", "ask_single_vague", "ask_single_bad"}, open_
        rr["partner"]["secret"] = True
        hid = ask_msg()
        assert not hid["ask_single_yes"] and hid["ask_single_no"] > 60 and hid["ask_single_vague"] > 40, hid
        rr["partner"] = None
        none = ask_msg()
        assert not none["ask_single_yes"], none
        print("付き合ってる人いるの？: OK | 隠していない %s / 隠している %s" % (dict(open_), dict(hid)))

        # ---- 8. 誰といるの？ のはぐらかし・デートは話さない・段階の提案と誘いへの効き方
        rr["partner"] = {"pid": "p1", "since": now, "secret": True, "found": None}
        assert app.circle.hide_shift(char, st, "p1") >= C.HIDE_SHIFT["suitor"] + 0.35
        rr["plans"] = [{"t0": now - 5 * 3600, "t1": now - 3 * 3600, "pid": "p1", "place": "cafe", "kind": "date", "made": now - 86400}]
        assert app.circle.tell(char, st, now, "talk") is None
        assert app.circle.ready_shift(char, st) == -6.0 and app.circle.invite_f(char, st) == 0.85
        rr["partner"]["secret"] = False
        assert app.circle.ready_shift(char, st) == -22.0 and app.circle.invite_f(char, st) == 0.55
        rr["partner"] = None
        assert app.circle.ready_shift(char, st) == 0.0 and app.circle.invite_f(char, st) == 1.0
        print("効き方: OK")

        # ---- 9. ばったり見かけて発覚 → 問い詰める (会って). 出る条件と 3 つの結末
        app.bonds.set_stage(cid, "live")
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        rr["partner"] = {"pid": "p1", "since": now - 30 * 86400, "secret": True, "found": None}
        ids = lambda: [k for k, v in app.available(char, st, datetime.now()).items() if v["ok"]]         # noqa: E731
        assert "confront" not in ids()
        x = {"t0": now - 600, "t1": now + 3600, "pid": "p1", "place": "cafe", "kind": "date"}
        assert app.circle.spotted(char, st, x, now) and app.circle.found(char, st)
        assert "confront" in ids()
        assert not app.circle.spotted(char, st, dict(x, kind="meal"), now)
        out = Counter()
        rx = {r["key"]: r for r in app.action("confront")["reactions"]}
        assert set(rx) == {"default", "defiant", "leave"}
        for i in range(300):
            app.bonds.set_stage(cid, "live")
            rr["people"] = [person("p1", "佐藤", "suitor", "plain", 40, now, interest=70, pull=random.choice((30, 60, 80)))]
            rr["partner"] = {"pid": "p1", "since": now - 30 * 86400, "secret": True, "found": now}
            st["params"]["affection"] = random.choice((40, 70))
            o = app.circle.confront(char, st, now)
            out[o] += 1
            if o == "sorry":
                assert rr["partner"] is None and rr["people"][0]["kind"] == "ex" and app.bonds.stage(cid) == "live"
            elif o == "defiant":
                assert rr["partner"]["secret"] is False and not app.circle.found(char, st) and app.bonds.stage(cid) == "live"
            else:
                assert rr["partner"]["secret"] is False and app.bonds.stage(cid) == "contact"
        assert all(out[k] > 20 for k in ("sorry", "defiant", "leave")) and out["sorry"] > out["leave"] * 0.6, out
        # コマンドとして (反応の条件 confront)
        app.bonds.set_stage(cid, "live")
        rr["people"] = [person("p1", "佐藤", "suitor", "plain", 40, now, interest=70, pull=40)]
        rr["partner"] = {"pid": "p1", "since": now - 30 * 86400, "secret": True, "found": now}
        st["params"]["affection"] = 70
        st["cooldowns"] = {}
        e = app.act("confront", cid)["entry"]
        assert e["text"] and not app.circle.found(char, st)
        try:
            app.act("confront", cid)
            raise AssertionError("問い詰めることが無いのに通った")
        except ValueError:
            pass
        print("問い詰める: OK | %s" % dict(out))

        # ---- 10. 同居を申し込んで受けてもらえたら, 付き合っている人とは別れる (あなたを選んだ)
        app.bonds.set_stage(cid, "visit")
        rr["people"] = [person("p1", "佐藤", "friend", "warm", 70, now, interest=70, pull=60)]
        rr["partner"] = {"pid": "p1", "since": now, "secret": False, "found": None}
        app.bonds.apply({"bond": "to_live"}, cid, now)
        assert app.bonds.stage(cid) == "live" and rr["partner"] is None and rr["people"][0]["kind"] == "ex"
        print("あなたを選ぶ: OK")

        # ---- 11. あなたからの「同居をやめる」(コマンド move_out) と, 冷え切った同居で相手から出ていく
        st["cooldowns"] = {}
        app.act("move_out", cid)
        assert app.bonds.stage(cid) == "visit" and not app.bonds.living()
        app.bonds.set_stage(cid, "live")
        st["params"]["affection"] = 10
        C.COLD_OUT_P, cp = 1.0, C.COLD_OUT_P
        for d in range(C.COLD_DAYS - 1):
            app.circle._cold_live(char, st, now + d * 86400)
            st["params"]["affection"] = 10
        assert app.bonds.stage(cid) == "live" and st["cold_live"] == C.COLD_DAYS - 1
        st["params"]["affection"] = 50
        app.circle._cold_live(char, st, now)
        assert "cold_live" not in st                          # 一日でも戻れば数え直し
        st["params"]["affection"] = 10
        for d in range(C.COLD_DAYS):
            app.circle._cold_live(char, st, now + d * 86400)
        C.COLD_OUT_P = cp
        assert app.bonds.stage(cid) == "contact" and not app.bonds.living()
        logs = [e for e in app.log(cid) if e.get("circle") == "circle.move_out"] if hasattr(app, "log") else []
        print("同居をやめる: OK | あなたから → 家に行ける仲 / 相手から → 連絡先%s" % (" (メッセージ %d)" % len(logs) if logs else ""))
        app.scheduled_scene = sched

        # ---- 12. 予定の最中に付き合っている人と別れる / その人が抜けても, 付き合いの記録は残らない
        rr["people"] = [person("p1", "佐藤", "coworker", "warm", 70, now, interest=70, pull=60)]
        rr["partner"] = {"pid": "p1", "since": now, "secret": False, "found": None}
        app.circle._leave(char, st, rr, rr["people"][0], now, "異動・退職")
        assert rr["partner"] is None and rr["people"][0].get("gone")
        print("抜ける: OK")

        # ---- 13. セリフ: 全性格に新しいキー
        miss = [(pid, k) for pid, p in app.personas.items() for k in NEW_KEYS if not (p.get("lines") or {}).get(k)]
        assert not miss, miss[:10]
        print("セリフ: OK | %d 性格 × %d キー" % (len(app.personas), len(NEW_KEYS)))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
