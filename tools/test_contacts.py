"""連絡しすぎの判定 (core/bonds.py の contact_weight / tolerance / _contacts): 挨拶・スタンプは軽く, 電話は重め.
会話の返事は数えず, 返事がないのに続けて送ると重め. 相手からよく来る相手は多めでも平気, 仕事中は早く「多い」.
以前の記録 (時刻だけ) は 1 回ずつ. 性格・間柄・状況ごとの目安も出す (一時データ, 画像生成なし).

    python tools/test_contacts.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(9)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("連絡")
        B, C = app.bonds, app.chat
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        B.set_stage(cid, "contact")
        relax = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}

        def reset(persona="cool", mood=50, lonely=30):
            char["persona_id"] = persona
            st.update(contacts=[], cooldowns={}, override=dict(relax), approach=None)
            st.pop("msg_pending", None)
            st["params"].update(mood=mood, loneliness=lonely)
            C.save(cid, {"seen_t": 0, "items": []})

        def send(kind):
            st["cooldowns"] = {}
            C.send(cid, kind)

        def reply(t=None):          # 相手から返事が来た
            st.pop("msg_pending", None)
            C.add(cid, "her", "📱『うん』", kind="reply", t=t or time.time())

        def over():
            return B.ctx(cid, st)["too_often"]

        # ---- 1. 挨拶だけでは「多い」にならない (控えめな性格でも)
        reset()
        send("greet_morning")
        reply()
        send("greet_night")
        assert not over(), (B._contacts(st, time.time()), B.tolerance(char, cid, st))
        # ---- 2. 会話の往復は数えない (返事が来たあとの 1 通は 0)
        reset()
        for _ in range(12):
            send("smalltalk")
            reply()
        assert not over() and B._contacts(st, time.time()) <= 1.0, B._contacts(st, time.time())
        # ---- 3. 返事がないのに続けて送ると「多い」(追いメッセージは重め)
        reset()
        n = 0
        while not over():
            send("smalltalk")
            n += 1
        assert n <= 3, n
        ws = [x["w"] for x in st["contacts"]]
        assert ws[0] == 1.0 and all(w == 1.5 for w in ws[1:]), ws
        print("控えめ (クール・連絡先): 返事のないまま %d 通で「多い」/ 挨拶 2 回・会話 12 往復は平気" % n)
        # 電話は重め
        reset()
        st["cooldowns"] = {}
        assert B.contact_weight(char, st, None, time.time(), phone=True) == 1.5
        # ---- 4. 相手からよく来る相手は, 多めでも平気 (上限あり)
        reset()
        t0 = B.tolerance(char, cid, st)
        for i in range(6):
            C.add(cid, "her", "📱『ねえねえ』", kind="approach", t=time.time() - 3600 * (i + 1))
        t1 = B.tolerance(char, cid, st)
        assert abs(t1 - t0 - B.HER_BONUS_MAX) < 1e-6, (t0, t1)
        # ---- 5. 仕事中・手が離せないと早く「多い」. 機嫌がいい・寂しいと少し平気
        reset()
        calm = B.tolerance(char, cid, st)
        st["override"] = dict(relax, activity="work", label="仕事中", busy=True)
        busy = B.tolerance(char, cid, st)
        reset(mood=80, lonely=80)
        happy = B.tolerance(char, cid, st)
        assert busy < calm - 1 and happy == calm + 2, (busy, calm, happy)
        # ---- 6. 以前の記録 (時刻だけ) は 1 回ずつ数え, 新しい記録とまぜても落ちない
        reset()
        now = time.time()
        st["contacts"] = [now - 100, now - 200, {"t": now - 50, "w": 0.5}]
        assert B._contacts(st, now) == 2.5
        send("stamp")
        assert isinstance(st["contacts"][-1], dict) and len(st["contacts"]) == 4
        print("相手から 6 回来ていると +%d / 仕事中 %.1f → 機嫌がよく寂しいと %.1f (ふつう %.1f) / 以前の記録: OK" % (B.HER_BONUS_MAX, busy, happy, calm))

        # ---- 目安: 何回で「多い」になるか (その日の揺らぎ ±0.75 を除く. 返事のないまま送るふつうのメッセージは 1 通目 1・2 通目から 1.5)
        print("我慢できる連絡の多さ (揺らぎを除く) と, 返事のないまま送って「多い」になる通数:")
        for persona in ("cool", "teinei", "amaenbo"):
            char["persona_id"] = persona
            ap = float(app.traits(char).get("approach", 1))
            for stage in ("contact", "visit", "live"):
                B.set_stage(cid, stage)
                row = []
                for label, busy_ in (("ふつう", False), ("仕事中", True)):
                    tol = (2 + 2 * ap + {"contact": 0, "visit": 2, "live": 4}[stage]) * (0.6 if busy_ else 1)
                    k, w = 0, 0.0
                    while w <= tol:
                        k += 1
                        w += 1.0 if k == 1 else 1.5
                    row.append("%s %.1f（%d 通）" % (label, tol, k))
                print("  %-8s approach %.1f %-7s %s" % (persona, ap, stage, " / ".join(row)))
        B.set_stage(cid, "contact")

        # ---- 7. 以前の記録にも遡る (起動したとき一度): contacts の置き換えと, 以前の「連絡多くない？」の判定し直し
        def old_save(lines, contacts, rejudged=()):
            """以前の形で保存して起動し直す. lines: [(何秒前, who, kind)] (her の too_often は「連絡多くない？」)."""
            reset()
            now = time.time()
            for ago, who, kind in lines:
                C.add(cid, who, "📱『……』" if who == "her" else "（送った）", kind=kind, t=now - ago)
                if kind in ("too_often", "too_often_again"):
                    app.life.add_reason(st, "player", "bad", "連絡が多くて、少し疲れた", now - ago, told=True, delta=-2.0, action="_too_often")
            st["contacts"] = [now - a for a in contacts]
            for k in ("contacts_rejudged", "contacts_v2", "thanks_rejudged"):
                st.pop(k, None)
            if rejudged:
                st["thanks_rejudged"] = [now - a for a in rejudged]
            st["params"].update(mood=40, affection=50, trust=50)
            app.save_state(cid)
            return now

        def restart():
            a2 = engine.App()
            return a2, a2.state(cid)
        # 挨拶とひと言だけで「多い」と言われていた (以前の数え方): 戻る. 時刻だけの contacts は置き換わる
        now = old_save([(7200, "me", "greet_morning"), (7100, "her", "reply"), (3600, "me", "smalltalk"),
                        (3500, "her", "too_often")], [7200, 3600, 99999 % 80000])
        app, st = restart()
        B, C = app.bonds, app.chat
        cs = st["contacts"]
        assert cs[0]["w"] == 0.5 and cs[0]["k"] == "greet_morning" and cs[1]["w"] == 0.0 and not isinstance(cs[2], dict), cs
        assert st["params"]["mood"] > 40 and st["params"]["affection"] > 50, st["params"]
        assert all(r["resolved"] for r in st["reasons"] if r.get("action") == "_too_often")
        note = [it for it in C.load(cid)["items"] if it.get("kind") == "rejudge"]
        assert len(note) == 1 and "受け止め直した" in note[0]["text"], note
        mood1 = st["params"]["mood"]
        app, st = restart()                      # 二重に当てない
        assert st["params"]["mood"] == mood1 and len([it for it in app.chat.load(cid)["items"] if it.get("kind") == "rejudge"]) == 1
        print("以前の記録の置き換え・挨拶だけで「多い」と言われた分が戻る (%s)・二重に当てない: OK" % note[0]["text"])
        # 本当に多かった (返事のないまま続けて 5 通): 戻らない
        B, C = app.bonds, app.chat
        old_save([(9000 - 300 * i, "me", "smalltalk") for i in range(5)] + [(7000, "her", "too_often")], [])
        app, st = restart()
        assert st["params"]["mood"] == 40 and not all(r["resolved"] for r in st["reasons"] if r.get("action") == "_too_often")
        assert not [it for it in app.chat.load(cid)["items"] if it.get("kind") == "rejudge"]
        # お礼の当て直しで戻した分とは重ならない
        B, C = app.bonds, app.chat
        old_save([(3700, "me", "greet_morning"), (3500, "her", "too_often")], [], rejudged=[3500])
        app, st = restart()
        assert st["params"]["mood"] == 40, "お礼の当て直しで戻した分は当てない"
        print("本当に多かった分は戻らない・お礼の当て直しと重ならない: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
