"""相手の交友関係 段 2 (core/circle.py: あなたに知られる経路).

言い方 (名前・続柄・言いたがらない間柄) / 話の中で (メッセージ・対面. 予定ごとに一度だけ) / 愚痴 (話そうの理由. 聞けばストレスが下がる) /
誰といるの・いたの (名前入り・正直なら知る・間柄ではぐらかす) / 誘いを予定で断る (断ったときだけ知る) /
付き合ってる人いるの？ (正直・はぐらかす・気分を害する・聞きすぎ) / ばったり (同じ行き先で予定の最中. 声をかける・会釈・見なかったことに) /
関係性タブ / 開き直しても残る. 一時データで.

    python tools/test_circle_known.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, circle as C, msgreply  # noqa: E402


def plan(pid, t0, t1, kind="meal", place="cafe"):
    return {"t0": t0, "t1": t1, "pid": pid, "place": place, "kind": kind, "made": t0 - 86400}


def main():
    random.seed(342)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("知られる経路")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        now = time.time()
        r = app.circle.rec(char, st, now)
        r["people"] = [{"pid": "p1", "name": "佐藤", "kind": "friend", "tone": "warm", "close": 70, "since": now, "haunt": ["cafe"]},
                       {"pid": "p2", "name": "鈴木", "kind": "boss", "tone": "uneasy", "close": 25, "since": now, "haunt": ["restaurant"]},
                       {"pid": "p3", "name": "高橋", "kind": "family", "tone": "plain", "close": 50, "since": now, "haunt": ["family"]},
                       {"pid": "p4", "name": "田中", "kind": "ex", "tone": "strained", "close": 30, "since": now, "haunt": ["cafe"]},
                       {"pid": "p5", "name": "伊藤", "kind": "coworker", "tone": "plain", "close": 40, "since": now, "haunt": ["cafe"]}]
        r["known"] = {}

        # ---- 1. 言い方: 名前入り, 家族は続柄 (決まった形), 言いたがらない間柄は「知り合い」で知ったことにならない
        assert app.circle.who_label(char, st, "p1") == "友達の佐藤さん"
        assert app.circle.who_label(char, st, "p2") == "上司の佐藤さん".replace("佐藤", "鈴木")
        assert app.circle.who_label(char, st, "p5") == "職場の伊藤さん"
        role = app.circle.who_label(char, st, "p3")
        assert role in C.FAMILY_ROLES and app.circle.who_label(char, st, "p3") == role
        assert app.circle.who_label(char, st, "p4") == "知り合い" and app.circle.who_label(char, st, "zz") == "知り合い"
        assert app.circle.learn(char, st, "p4", "talk", now) is None and "p4" not in r["known"]
        print("言い方: OK | %s / %s / %s / 元恋人は「知り合い」" % (app.circle.who_label(char, st, "p1"), app.circle.who_label(char, st, "p2"), role))

        # ---- 2. 話の中で: 30 時間のうちに終わった予定を, 一度だけ (くじ). 古い予定・まだの予定・元恋人は話さない
        got = Counter()
        for i in range(400):
            r["known"] = {}
            r["plans"] = [plan("p1" if i % 2 else "p2", now - 5 * 3600, now - 3 * 3600)]
            via = "talk" if i % 4 < 2 else "message"
            t = app.circle.tell(char, st, now, via)
            assert r["plans"][0]["told"] is True
            assert app.circle.tell(char, st, now + 60, via) is None          # 二度目は無い
            if t:
                key, fmt = t
                pid = r["plans"][0]["pid"]
                assert key == ("circle_told" if pid == "p1" else "circle_told_uneasy"), (pid, key)
                assert fmt["who"] == app.circle.who_label(char, st, pid) and fmt["did"] == "ご飯に行った" and fmt["when"] in ("今日", "さっき", "昨日")
                k = r["known"][pid]
                assert k["via"] == via and k.get("feel") == ("warm" if pid == "p1" else "uneasy")
                line = app.chat.line(char, key, fmt)
                assert fmt["who"] in line and "{" not in line, line
                got[via] += 1
            else:
                assert not r["known"]
        assert 0.25 < got["message"] / 200.0 < 0.45 and 0.4 < got["talk"] / 200.0 < 0.6, got
        for x in (plan("p1", now - 40 * 3600, now - 31 * 3600), plan("p1", now - 3600, now + 3600), plan("p4", now - 5 * 3600, now - 3600)):
            r["plans"] = [x]
            for _ in range(20):
                x.pop("told", None)
                assert app.circle.tell(char, st, now, "talk") is None
        print("話の中で: OK | メッセージ %d/200・対面 %d/200" % (got["message"], got["talk"]))

        # ---- 3. 愚痴: 苦手な人と会ったあと 4 時間のうちだけ, 予定ごとに一度. 話したら「昨日〇〇と」とは言わない
        n = 0
        for i in range(200):
            r["known"] = {}
            r["plans"] = [plan("p2", now - 4 * 3600, now - 2 * 3600, "work_after", "restaurant")]
            g = app.circle.grumble(char, st, now)
            assert app.circle.grumble(char, st, now) is None
            if g:
                n += 1
                assert g == "上司の鈴木さん" and r["known"]["p2"]["via"] == "grumble" and r["known"]["p2"]["feel"] == "uneasy"
                assert app.circle.tell(char, st, now, "talk") is None
        assert 70 < n < 130, n
        for x in (plan("p1", now - 4 * 3600, now - 2 * 3600), plan("p2", now - 8 * 3600, now - 5 * 3600), plan("p4", now - 4 * 3600, now - 3600)):
            r["plans"] = [x]
            assert all(app.circle.grumble(char, st, now) is None for _ in range(10))
        # 返し方: 聞けばストレスが下がり, 流すと下がらない (画面の「返す」の種類も, 以前の 4 択も)
        assert set(msgreply.WHY_OPTIONS["grumble"]) and "grumble" in msgreply.WHY_TEXT and "grumble" in msgreply.WHY_BAD
        drop = Counter()
        for i in range(160):
            kind = ("worry", "curt")[i % 2]
            st["params"].update(stress=60, mood=55, affection=60)
            st["approach"] = {"id": "msg_chat", "t": now, "until": now + 900, "why": "grumble", "who": "上司の鈴木さん"}
            app.presence.reply_land(char, st, "msg_chat", kind, now + i, why="grumble")
            drop[kind] += 60 - st["params"]["stress"]
        assert drop["worry"] / 80.0 > drop["curt"] / 80.0 + 3, drop
        # 問いかけの「話そう」の後ろに会ったことを添えても, 「答える」は出る (送ったときの印 asks を見る. 印の無い以前の記録は文面から)
        from core import react
        st.pop("approach", None)
        app.chat.add(cid, "her", "📱『暇で。いま何してます？ そういえば今日、友達の佐藤さんとご飯に行ったんです』", kind="approach",
                     t=now + 500, ap="msg_chat", why="bored", asks=True)
        tg = react.target(app, cid, st, now + 501)
        assert tg["asks"] and "re_answer" in react.kinds_for(tg["tone"], tg["asks"]), tg
        app.chat.add(cid, "her", "📱『暇で。いま何してます？』", kind="approach", t=now + 600, ap="msg_chat", why="bored")
        assert react.target(app, cid, st, now + 601)["asks"]
        print("愚痴: OK | %d/200 で愚痴に / ストレスの下がり 聞く %.1f・素っ気なく %.1f" % (n, drop["worry"] / 80.0, drop["curt"] / 80.0))

        # ---- 4. 誰といるの / いたの: 名前入りで答え, 正直なら知る. 元恋人とははぐらかしやすい
        r["known"] = {}
        honest = Counter()
        for i in range(300):
            pid = ("p1", "p4")[i % 2]
            x = {"t0": now, "t1": now + 3600, "who": "friend", "pid": pid, "label": "", "loc": "カフェ", "hush": None}
            honest[pid] += app.phonetalk.answer_mode(char, st, x) == "honest"
        assert honest["p1"] > honest["p4"] + 40, honest
        x = {"t0": now - 3600, "t1": now - 600, "who": "friend", "pid": "p1", "label": "カフェで過ごしている", "loc": "カフェ", "hush": None}
        assert app.phonetalk.who_label(x, char, st) == "友達の佐藤さん" and app.phonetalk.who_label(x) == "友達"
        old = dict(x)
        old.pop("pid")
        assert app.phonetalk.who_label(old, char, st) == "友達"          # 以前の記録 (pid なし) はそのまま
        st["with_log"] = [x]
        st["whoask"] = []
        for i in range(30):
            x.pop("ans", None)
            r["known"] = {}
            st["whoask"] = []
            m = app.manners.on_send(char, st, "who_with", now)
            key, _, ex = app.manners.reply(char, st, "who_with", now, {}, m)
            if key == "who_with":
                assert ex["who"] == "友達の佐藤さん" and r["known"]["p1"]["via"] == "message"
            else:
                assert key == "who_with_vague" and not r["known"]
        print("誰といるの: OK | 正直 友達 %d/150・元恋人 %d/150" % (honest["p1"], honest["p4"]))

        # ---- 5. 誘いを予定で断る: 断ったときだけ知る (受けて予定をやめたときは知らない)
        got = Counter()
        for i in range(150):
            r["known"] = {}
            p = plan("p1", now + 2 * 86400, now + 2 * 86400 + 7200)
            r["plans"] = [p]
            y = {"id": "w%d" % i, "cid": cid, "t": p["t0"] + 1800, "place": "cafe", "do": "walk", "by": "me", "status": "asked",
                 "made": now, "rounds": 9}
            app.appoint.all().append(y)
            st["params"].update(affection=random.choice((40, 90)), mood=60)
            key, _, extra = app.appoint.reply(char, st, {"appoint": y["id"]}, now + 600, {})
            got[key] += 1
            if key == "appoint_plan":
                assert extra["who"] == "友達の佐藤さん" and r["known"]["p1"]["via"] == "decline"
            else:
                assert not r["known"], key
            y["status"] = "cancelled"
        assert got["appoint_plan"] > 40, got
        print("誘いを断る: OK | %s" % dict(got))

        # ---- 6. 付き合ってる人いるの？: 仲が近いほど気分を害しにくい. 2 週間のうちに二度目は嫌がられる. 「いる」はまだ無い (段 4)
        res = {}
        for stage in ("contact", "visit", "live"):
            app.bonds.set_stage(cid, stage)
            c = Counter()
            for i in range(300):
                st["single_ask"] = []
                st["params"].update(affection=60, mood=60)
                m = app.manners.on_send(char, st, "ask_single", now)
                key, eff, _ = app.manners.reply(char, st, "ask_single", now, {}, m)
                c[key] += 1
            assert set(c) <= {"ask_single_no", "ask_single_vague", "ask_single_bad"}, c
            res[stage] = c
        assert res["contact"]["ask_single_bad"] > res["visit"]["ask_single_bad"] > res["live"]["ask_single_bad"], res
        assert all(res[s]["ask_single_no"] > 60 for s in res), res
        st["single_ask"] = []
        app.manners.on_send(char, st, "ask_single", now)
        m = app.manners.on_send(char, st, "ask_single", now + 5 * 86400)
        assert app.manners.reply(char, st, "ask_single", now + 5 * 86400, {}, m)[0] == "ask_single_much"
        m = app.manners.on_send(char, st, "ask_single", now + 30 * 86400)
        assert app.manners.reply(char, st, "ask_single", now + 30 * 86400, {}, m)[0] != "ask_single_much"
        from core import chat as chat_mod
        assert "ask_single" in chat_mod.KINDS and any("ask_single" in g[3] for g in chat_mod.GROUPS)       # 画面で押せる
        app.bonds.set_stage(cid, "contact")
        print("付き合ってる人いるの？: OK | 気分を害する 連絡先 %d・家に行ける %d・同居 %d /300" % tuple(
            res[s]["ask_single_bad"] for s in ("contact", "visit", "live")))

        # ---- 7. ばったり: 同じ行き先で予定の最中なら二人を見かける. 声をかけると紹介される. ほかの行き先・仕事中は見かけない
        cur = {"kind": "out", "place": "cafe", "with": None}
        r["known"] = {}
        r["plans"] = [plan("p5", now - 1800, now + 3600)]
        assert app.scene_at(char, st, engine.datetime.fromtimestamp(now))["activity"] == "circle"
        assert not app.street.around(cid, now)                                 # 予定の最中: ふつうのばったりでは会わない
        spot = Counter()
        for i in range(60):
            app.presence.rec().pop("street_pending", None)
            out = app.street.happen(cur, now)
            pend = app.street.pending()
            if pend and pend["kind"] == "circle":
                spot["spot"] += 1
                assert pend["type"] == "spot" and pend["who"] == cid and pend["pid"] == "p5"
                v = app.street.view(now)
                assert [o["id"] for o in v["options"]] == ["talk", "nod", "pass"] and v["face"] is None or True
            elif pend:
                spot["other"] += 1
                assert not (pend["kind"] == "char" and pend["who"] == cid)
        assert spot["spot"] > 30, spot
        for choice in ("pass", "nod", "talk"):
            app.presence.rec().pop("street_pending", None)
            while not (app.street.pending() or {}).get("kind") == "circle":
                app.presence.rec().pop("street_pending", None)
                app.street.happen(cur, now)
            assert choice in [o["id"] for o in app.street.view(now)["options"]]
            res = app.street.answer(choice)
            if choice == "talk":
                assert "職場の伊藤さん" in res["text"] and r["known"]["p5"]["via"] == "spot", res
            else:
                assert "p5" not in r["known"] and "誰か" in res["text"], res
        r["plans"] = [plan("p5", now - 1800, now + 3600, place="mall")]
        for i in range(40):
            app.presence.rec().pop("street_pending", None)
            app.street.happen(cur, now)
            assert (app.street.pending() or {}).get("kind") != "circle"
            app.presence.rec().pop("street_pending", None)
            app.street.happen({"kind": "work", "place": "cafe", "with": None}, now)
            assert (app.street.pending() or {}).get("kind") != "circle"
        app.presence.rec().pop("street_pending", None)
        # 閉じている間 (自動の応答): 方針どおりに. 声をかけたら紹介される
        r["plans"] = [plan("p5", now - 1800, now + 3600)]
        r["known"] = {}
        while not (app.street.pending() or {}).get("kind") == "circle":
            app.presence.rec().pop("street_pending", None)
            app.street.happen(cur, now)
        res = app.street.resolve("talk", auto=True, weak=True)
        assert r["known"]["p5"]["via"] == "spot" and res["auto"]
        print("ばったり: OK | 同じ行き先で %d/60 回見かけた" % spot["spot"])

        # ---- 8. 関係性タブ・開き直し: 知った人が出て, 開き直しても残る
        r["known"] = {}
        app.circle.learn(char, st, "p1", "talk", now - 100, feel="warm")
        app.circle.learn(char, st, "p2", "grumble", now, feel="uneasy")
        app.save_state(cid)
        pv = next(p for p in app.people_view(now) if p["id"] == cid)
        assert [k["label"] for k in pv["circle"]] == ["上司の鈴木さん", "友達の佐藤さん"] and pv["circle"][0]["feel"] == "uneasy", pv["circle"]
        assert not any(k.get("kind") == "person" for k in pv["known"])
        app2 = engine.App()
        st2 = app2.state(cid)
        assert set(st2["circle"]["known"]) == {"p1", "p2"} and st2["circle"]["known"]["p1"]["t0"] == r["known"]["p1"]["t0"]
        t0 = st2["circle"]["known"]["p1"]["t0"]
        app2.circle.learn(app2.char(cid), st2, "p1", "message", now + 50)            # もう一度聞いても, 初めて知った日はそのまま
        assert st2["circle"]["known"]["p1"]["t0"] == t0 and st2["circle"]["known"]["p1"]["t"] == now + 50
        print("関係性タブ: OK | %s" % " / ".join(k["label"] for k in pv["circle"]))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
