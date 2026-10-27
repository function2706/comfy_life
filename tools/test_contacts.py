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
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
