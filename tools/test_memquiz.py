"""謝る・お礼の理由を記憶で選ぶ (A20. core/memquiz.py) の出題の整合性と, 外れ方ごとの判定 (一時データ).

- 出題: 正解は必ず 1 つ (謝る) / 外れが本物と同じ文にならない / 他の人の件はあなたが関わったものだけ (名前は出ない) /
  直後の件に時刻が出ない / 経過時間で細部の細かさが変わる / 画面には札と文だけ (どれが正解か出ない) /
  開き直すと並びは変わるが中身は同じ / 札は 1 回きり
- 判定: 的中 / 細部違い →「それじゃなくて」/ 本当にしたが気にしていない →「気にしてない」/ 人違い → 重い (嫉妬で更に) /
  なかったこと →「何のこと？」/ 外すのが 3 回目 → 苛立つ. お礼も同じ形
- 時刻 × 種類の総当たり: どの組でも正解 1 つ・文が重ならない・時刻の書き方がそろう

    python tools/test_memquiz.py
"""
import os
import random
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, memquiz, store  # noqa: E402

TIME_RE = re.compile(r"(今日|きのう|おととい|[月火水木金土日]曜)の")


def main():
    random.seed(20)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("記憶")
        cid = app.settings["active_character"]
        other = app.new_character("みお", stage="contact")["id"]
        for c in (cid, other):
            app.bonds.set_stage(c, "contact")
        char, st = app.char(cid), app.state(cid)
        L, M, C = app.life, app.manners, app.chat
        now = time.time()

        def fresh():
            for c in (cid, other):
                s = app.state(c)
                s["reasons"], s["apologies"], s["favors"] = [], [], []
                s.pop("apology_last", None), s.pop("quiz", None), s.pop("apology_tries", None)
                d = C.load(c)
                d["items"] = []
                C.save(c, d)
                app.log(c)[:] = []
            app.set_params({"mood": 55, "affection": 50, "trust": 50}, cid)

        def quiz(kind="apology", at=None):
            q = memquiz.ask(app, cid, kind, at or now)
            items = st["quiz"][kind]["items"]
            return q, items

        def tok(items, typ, of=None):
            return next(k for k, e in items.items() if e["type"] == typ and (of is None or e.get("of") == of))

        def reply(kind, entry, at=None):
            t = at or now
            ctx = dict(app.context(char, st, datetime.fromtimestamp(t)), phase="noon", too_often=False, _sent=t, _meta={"reason": entry})
            return C.reply(char, st, kind, t, ctx)

        def check(q, items, level):
            labels = [c["label"] for c in q["choices"]]
            assert len(labels) == len(set(labels)), labels
            assert all(set(c) == {"id", "label"} for c in q["choices"]), "画面には札と文だけ"
            assert sum(1 for e in items.values() if e["type"] == "fault") <= 1, "正解は 1 つまで"
            for lb in labels:
                has_time = bool(TIME_RE.search(lb))
                assert has_time == (level != "none"), (level, lb)
                if level == "day":
                    assert "時ごろ" not in lb, lb
            for e in items.values():
                if e["type"] == "other":
                    assert app.chars[other].get("name", "@@") not in e["label"]

        # ---- 1. 夜中の連絡 (30 分前): 直後なので時刻は出ない. 前後の本当の行動・人違い・細部違いが並ぶ
        fresh()
        C.add(cid, "me", "（話したいと送った）", kind="smalltalk", t=now - 3000)
        C.add(cid, "me", "（おやすみと送った）", kind="greet_night", t=now - 1800)
        C.add(cid, "me", "（からかった）", kind="tease", t=now - 1500)
        C.add(other, "me", "（お疲れさまと送った）", kind="otsukare", t=now - 2400)
        L.add_reason(st, "player", "bad", "夜中に連絡が来た", now - 1800, told=True, delta=-4.0, action="_chat_late_night")
        q, items = quiz()
        assert st["quiz"]["apology"]["level"] == "none"
        check(q, items, "none")
        types = sorted(e["type"] for e in items.values())
        assert types.count("fault") == 1 and "real" in types and "other" in types and "shift" in types, types
        fault = items[tok(items, "fault")]
        assert fault["label"] == "「おやすみ」と送った", fault
        assert any(e["label"] == "「からかう」と送った" and e["type"] == "real" for e in items.values())
        assert any(e["label"] == "「お疲れさま」と送った" and e["type"] == "other" for e in items.values())
        print("直後:", [c["label"] for c in q["choices"]])
        # 開き直すと並びは変わりうるが, 中身は同じ. 札は 1 回きり
        q2, _ = quiz()
        assert sorted(c["label"] for c in q2["choices"]) == sorted(c["label"] for c in q["choices"])
        assert q2["qid"] == q["qid"]
        e = memquiz.resolve(app, cid, "apology", q2["choices"][0]["id"])
        try:
            memquiz.resolve(app, cid, "apology", q2["choices"][1]["id"])
            raise AssertionError("札が 2 回使えた")
        except ValueError:
            pass
        print("使い回し・札 1 回: OK", e["type"])

        # ---- 2. 判定: 的中 / 細部違い / 気にしていない / 人違い / なかったこと
        def setup():
            fresh()
            C.add(cid, "me", "（おやすみと送った）", kind="greet_night", t=now - 5 * 3600)
            C.add(cid, "me", "（からかった）", kind="tease", t=now - 5 * 3600 + 900)
            C.add(other, "me", "（お疲れさまと送った）", kind="otsukare", t=now - 5 * 3600 - 600)
            L.add_reason(st, "player", "bad", "夜中に連絡が来た", now - 5 * 3600, told=True, delta=-4.0, action="_chat_late_night")
            return quiz()

        q, items = setup()
        assert st["quiz"]["apology"]["level"] == "hour"
        check(q, items, "hour")
        key, eff, _ = reply("apology", memquiz.resolve(app, cid, "apology", tok(items, "fault")))
        assert key in ("apology", "apology_half", "apology_deeds", "apology_refuse", "apology_late"), key
        q, items = setup()
        key, eff, _ = reply("apology", memquiz.resolve(app, cid, "apology", tok(items, "shift", "fault")))
        assert key == "apology_near", key
        q, items = setup()
        key, eff, _ = reply("apology", memquiz.resolve(app, cid, "apology", tok(items, "real")))
        assert key == "apology_unminded", key
        q, items = setup()
        app.traits(char)["jealousy"] = 1.0
        key, eff, _ = reply("apology", memquiz.resolve(app, cid, "apology", tok(items, "other")))
        assert key == "apology_wrong" and eff["mood"] == -3, (key, eff)
        q, items = setup()
        app.traits(char)["jealousy"] = 1.6
        key, eff2, _ = reply("apology", memquiz.resolve(app, cid, "apology", tok(items, "other")))
        assert key == "apology_wrong" and eff2["mood"] < -3 and eff2.get("affection", 0) < 0, eff2
        app.traits(char).pop("jealousy", None)
        print("判定: 的中・近い・気にしてない・人違い (嫉妬で %s) OK" % eff2)

        # なかったこと: 気にしていることが無いときの細部違い
        fresh()
        C.add(cid, "me", "（おやすみと送った）", kind="greet_night", t=now - 2 * 86400)
        q, items = quiz()
        assert st["quiz"]["apology"]["level"] == "day", (st["quiz"]["apology"]["level"], items)
        assert not any(e["type"] == "fault" for e in items.values())
        check(q, items, "day")
        key, eff, _ = reply("apology", memquiz.resolve(app, cid, "apology", tok(items, "shift")))
        assert key == "apology_confused", key
        print("なかったこと: OK", [c["label"] for c in q["choices"]])

        # 外すのが 3 回目 (4 時間のうち) → 苛立つ
        q, items = setup()
        outs = []
        for i in range(3):
            q, items = quiz()
            outs.append(reply("apology", memquiz.resolve(app, cid, "apology", tok(items, "real")))[0])
        assert outs[:2] == ["apology_unminded", "apology_unminded"] and outs[2] == "apology_irritated", outs
        print("外し続け:", outs)

        # ---- 3. お礼: してくれたこと / 細部違い / 人違い
        fresh()
        M.favor(st, "care", now - 20 * 3600)
        M.favor(app.state(other), "treat", now - 22 * 3600)
        q, items = quiz("thanks")
        check(q, items, "day")
        assert any(e["type"] == "favor" for e in items.values()) and any(e["type"] == "other" for e in items.values())
        assert reply("thanks", memquiz.resolve(app, cid, "thanks", tok(items, "favor")))[0] == "thanks"
        q, items = quiz("thanks")
        assert reply("thanks", memquiz.resolve(app, cid, "thanks", tok(items, "shift")))[0] == "thanks_what"
        q, items = quiz("thanks")
        assert reply("thanks", memquiz.resolve(app, cid, "thanks", tok(items, "other")))[0] == "thanks_wrong"
        print("お礼:", [c["label"] for c in q["choices"]])

        # ---- 4. 以前の形 (更新前に送った, 項目 id の文字列) も読める
        fresh()
        L.add_reason(st, "player", "bad", "連絡が多くて疲れた", now - 600, told=True, delta=-3.0, action="_too_often")
        assert reply("apology", "too_often")[0] in ("apology", "apology_half", "apology_deeds", "apology_refuse")
        fresh()
        M.favor(st, "selfie", now - 1800)
        assert reply("thanks", "selfie")[0] == "thanks"
        print("以前の形: OK")

        # ---- 5. 送る: 札で送り, 要約に文が残る. 古い札は弾く
        fresh()
        C.add(cid, "me", "（からかった）", kind="tease", t=now - 3600)
        L.add_reason(st, "player", "bad", "からかわれて傷ついた", now - 3500, told=True, delta=-3.0, action="_chat_tease_hurt")
        q, items = quiz()
        k = tok(items, "fault")
        C.send(cid, "apology", {"reason": k})
        assert C.thread(cid)["items"][-1]["text"] == "（謝った: %s）" % items[k]["label"], C.thread(cid)["items"][-1]
        assert st["msg_pending"]["meta"]["reason"]["type"] == "fault"
        st.pop("msg_pending", None)
        for kind in ("apology", "thanks"):
            try:
                C.send(cid, kind, {"reason": "nope"})
                raise AssertionError("通ってしまった")
            except ValueError:
                pass
        print("送る: OK")

        # ---- 6. 総当たり: 気にしていること (種類) × 経過時間. 正解 1 つ・重ならない・時刻の書き方
        acts = [("_chat_late_night", "greet_night"), ("_too_often", "what_doing"), ("_chat_stamp_spam", "stamp"),
                ("_chat_tease_hurt", "tease"), ("_greet_miss", None), ("_appoint", None), ("_drift", None), ("_home", None),
                ("_chores_scold", None), ("_jealous", None)]
        cmd = next(a for a in app.actions if a.get("category") not in ("system",) and not a["id"].startswith("_")
                   and a["id"] not in ("message", "call"))
        n = 0
        for action, mk in acts:
            for age in (300, 2 * 3600, 9 * 3600, 30 * 3600, 3 * 86400):
                fresh()
                t0 = now - age
                if mk:
                    for i in range(3 if action == "_too_often" else 1):
                        C.add(cid, "me", "（送った）", kind=mk, t=t0 - 120 * i)
                C.add(cid, "me", "（話したいと送った）", kind="smalltalk", t=t0 - 1500)
                app.log(cid).append({"id": "x%d" % n, "t": t0 + 600, "action": cmd["id"], "action_name": cmd.get("name", ""),
                                     "location": "あなたの家"})
                C.add(other, "me", "（おはようと送った）", kind="greet_morning", t=t0 - 3000)
                L.add_reason(st, "player", "bad", "理由%d" % n, t0, told=True, delta=-3.0, action=action)
                q, items = quiz()
                lv = st["quiz"]["apology"]["level"]
                assert lv == memquiz.level_of(now - items[tok(items, "fault")]["t"]) or lv in ("none", "hour", "day")
                check(q, items, lv)
                assert sum(1 for e in items.values() if e["type"] == "fault") == 1, (action, age)
                assert len(q["choices"]) >= 4, (action, age, [c["label"] for c in q["choices"]])
                n += 1
        print("総当たり: %d 組 OK" % n)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
