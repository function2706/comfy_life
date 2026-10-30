"""向こうから来たメッセージへの返事 (選択肢. core/msgreply.py) と, 返事をしないで放っておいたときの確認 (一時データ).

    python tools/test_msgreply.py
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
from core import engine, msgreply as MR, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(5)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("メッセージ")
        cid = app.settings["active_character"]
        assert app.bonds.stage(cid) != "live"
        st = app.state(cid)
        char = app.char(cid)

        def fire(aid="msg_chat", **params):
            st["approach"] = None
            app.set_params(dict({"mood": 55, "affection": 50, "trust": 50, "loneliness": 50}, **params), cid)
            app.force_approach(aid, cid)
            return app.presence.pending_view(char, st)

        # ---- 1. 選択肢: メッセージの内容に合ったものが 3〜4 つ
        pv = fire("msg_miss")
        ids = [c["id"] for c in pv["choices"]]
        assert 3 <= len(ids) <= 4 and "worry" in ids, pv
        assert [c["id"] for c in fire("msg_today")["choices"]][0] == "expand"
        print("選択肢: OK", [c["label"] for c in pv["choices"]])

        # ---- 2. 返事をすれば必ず良くなる, ではない. 相手の返しとトーク
        res = {"good": 0, "neutral": 0, "bad": 0}
        more = 0
        for _ in range(60):
            fire()
            m0 = st["params"]["mood"]
            r = app.answer_approach("reply", cid, random.choice(["cheerful", "expand", "tease", "curt"]))
            res[r["entry"]["reply"]["result"]] += 1
            more += bool(r["entry"].get("more"))
            if r["entry"]["reply"]["result"] == "bad":
                assert st["params"]["mood"] <= m0
        assert all(res.values()), res
        assert 0 < more < 60
        th = app.chat.thread(cid)["items"]
        assert any(x["who"] == "me" and x["text"].startswith("（") for x in th) and th[-1]["who"] == "her"
        print("受け取り方:", res, "もう一言:", more)

        # ---- 3. 性格・仲・機嫌しだい (決め打ちではない)
        def rate(persona, kind, aid="msg_chat", n=300, ok_if=("good",), **params):
            char["persona_id"] = persona
            p = dict({"mood": 55, "affection": 50, "loneliness": 50}, **params)
            ok = 0
            for _ in range(n):
                st["params"].update(p)
                ok += MR.judge(char, st, aid, kind) in ok_if
            return ok / float(n)
        t_close, t_far = rate("itazura", "tease", affection=80), rate("itazura", "tease", affection=30)
        assert t_close > t_far + 0.3 and t_close < 0.97, (t_close, t_far)
        # 素っ気ない返事: 無口な人は気にしない (悪く取られにくい) が, 甘えたがりには刺さる
        c_amae, c_muk = rate("amaenbo", "curt", ok_if=("good", "neutral")), rate("mukuchi", "curt", ok_if=("good", "neutral"))
        assert c_muk > c_amae + 0.3, (c_muk, c_amae)
        assert 0 < rate("teinei", "cheerful") < 1 and rate("teinei", "cheerful", mood=20) < rate("teinei", "cheerful", mood=80)
        w = rate("byoujaku", "worry", aid="msg_miss")
        assert w > rate("byoujaku", "curt", aid="msg_miss") + 0.3
        char["persona_id"] = "teinei"
        print("からかい (仲が深い %.2f / 浅い %.2f), 素っ気ない (無口 %.2f / 甘えたがり %.2f)" % (t_close, t_far, c_muk, c_amae))

        # ---- 4. 放っておく: 既読のまま放っておくほうが重い. 気にしない性格もいる. 急ぎの内容ほど重い
        def ignored(persona, read, aid="msg_chat"):
            char["persona_id"] = persona
            fire(aid)
            ap = st["approach"]
            if read:
                app.chat.mark_seen(cid)
            else:
                d = app.chat.load(cid)
                d["seen_t"] = ap["t"] - 10
                app.chat.save(cid, d)
            st["params"].update({"mood": 60, "loneliness": 50})
            ap["until"] = time.time() - 1
            e = app.presence.live(char, st, time.time())
            return -e["deltas"].get("mood", 0), [x for x in app.chat.thread(cid)["items"] if not x.get("kind", "").startswith("close_")][-1]
        r_read, last = ignored("amaenbo", True)
        r_unread, _ = ignored("amaenbo", False)
        assert r_read > r_unread and last["kind"] == "ignored", (r_read, r_unread, last)
        r_cool, _ = ignored("cool", True)
        assert r_cool < r_read, (r_cool, r_read)
        r_miss, _ = ignored("amaenbo", True, "msg_miss")
        r_today, _ = ignored("amaenbo", True, "msg_today")
        assert r_miss > r_today, (r_miss, r_today)
        assert any("既読のまま" in x["tell"] for x in st.get("reasons") or [])
        char["persona_id"] = "teinei"
        print("放っておく: 既読 %.1f / 未読 %.1f / クール %.1f / 会いたい %.1f / 今日の出来事 %.1f" % (r_read, r_unread, r_cool, r_miss, r_today))

        # ---- 5. 自撮りを頼む (スマホのトーク): 仲・機嫌しだいで送ってくれる. 続けて頼むと嫌がられる
        def ask_selfie(**params):
            st["approach"], st["contacts"] = None, []
            st.pop("msg_pending", None)
            app.set_params(dict({"mood": 60, "loneliness": 40}, **params), cid)
            app.chat.send(cid, "ask_selfie")
            st["msg_pending"]["due"], st["msg_pending"]["reply"] = time.time() - 1, True
            app.deliver_due()
            return [x for x in app.chat.thread(cid)["items"] if not x.get("kind", "").startswith("close_")][-1]   # 切り上げのひとことは除く
        yes = 0
        for _ in range(40):
            st["selfie_asks"] = []
            it = ask_selfie(affection=85, mood=80)
            yes += bool(it.get("selfie"))
        low = 0
        for _ in range(40):
            st["selfie_asks"] = []
            low += bool(ask_selfie(affection=20, mood=40).get("selfie"))
        assert yes > low and yes < 40 and low < 15, (yes, low)
        st["selfie_asks"] = [time.time() - 60, time.time() - 30]
        it = ask_selfie(affection=85, mood=80)
        assert it["kind"] == "selfie_pester" and not it.get("selfie"), it
        print("自撮りを頼む: 仲が深い %d / 浅い %d (40 回中). 続けて頼むと嫌がられる" % (yes, low))

        # ---- 6. 選ばずに「返信する」(以前の形) でも受け付ける (先頭の選択肢)
        fire()
        r = app.answer_approach("accept", cid)
        assert r["entry"]["reply"]["kind"] == "cheerful"
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
