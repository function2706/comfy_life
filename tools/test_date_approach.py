"""そばで話しかけられたときの返し方と, デート中の働きかけ (1.6.0).
- 家で過ごしているときのもの (お茶・ごはん・ゲーム・かまって・眠そう など) は, お出かけ中には出ない
- デート中は, あれ見て・楽しいね・寒い/暑い・休憩・お腹すいた・次あそこ・そろそろ帰ろう・写真・手をつなぐ が出る.
  デート中は話しかけてくるきっかけが多い (家で構っている最中より来やすい)
- 「次, あそこ行かない？」は, いまの場所以外で行ける所 (好みで選ぶ). 応じればそこへ移る. 「そろそろ帰ろう」に応じれば帰る
- 話しかけられたら (話そう・見せたい・あれ見て・楽しいね), メッセージの「返す」と同じ返し方・同じ判定で返す.
  合えば応じたときの効き目, 外せば下がる. 相手の返しはメッセージの返しのセリフを対面の言い方で
(一時データ)

    python tools/test_date_approach.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import cond, engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
APPT = {"appointment": "test"}


def main():
    random.seed(9)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("デート中")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        st, char = app.state(cid), app.char(cid)

        def ctx_now():
            d = datetime.fromtimestamp(time.time())
            return app.context(char, st, d, app.scene_at(char, st, d))

        def cands():
            c = ctx_now()
            return {a["id"] for a in app.approaches if not a.get("apart") and cond.check(a.get("when", ""), c)}

        def date(**params):
            st["cooldowns"] = {}
            st["approach"] = None
            if app.bonds.mode(cid):
                app.act("go_home")
            app.presence.back()                  # 家に着いたことに (別れたあとの帰り道は飛ばす)
            st.pop("override", None)             # 相手も家に着いたことに
            app.set_params(dict({"affection": 70, "mood": 70, "boredom": 70, "loneliness": 70, "energy": 60, "sleepiness": 80}, **params), cid)
            st["cooldowns"] = {}
            app.act("cafe", opts=APPT)
            assert app.bonds.mode(cid) == "meet"

        # ---- 1. 家で過ごしているときのものは, お出かけ中には出ない. デート中のものが出る
        date()
        c = cands()
        assert not c & {"tea", "bored", "lonely", "cook_for", "play", "sleepy", "need_you"}, c
        assert {"date_look", "date_fun", "date_next", "date_photo", "date_hands"} <= c, c
        print("家向けは出ない・デートのものが出る: OK |", sorted(c))

        # ---- 2. デート中は話しかけてくるきっかけが多い
        now = time.time()
        hits = 0
        for _ in range(200):
            st["approach"], st["ap_quiet_until"], st["ap_last"], st["ap_check"] = None, 0, {}, now - 600
            hits += bool(app.presence.live(char, st, now))
        assert hits >= 25, hits
        print("頻度: OK | 10 分ごとの抽せん 200 回で %d 回" % hits)

        # ---- 3. 「次, あそこ行かない？」: いまの場所以外. 応じれば, そこへ移る
        date()
        st["approach"] = None
        e = app.force_approach("date_next", cid)["entry"]
        act = st["approach"]["act"]
        assert act and act != "cafe" and "{place}" not in e["text"], (act, e["text"])
        app.answer_approach("accept", cid)
        place = (app.action(act).get("override") or {}).get("place")
        assert (st.get("override") or {}).get("place") == place, (st.get("override"), place)
        print("次の場所: OK |", e["text"], "→", place)

        # ---- 4. 「そろそろ帰ろう」に応じれば帰る / もう少し, なら不満
        date(energy=20)
        st["approach"] = None
        app.force_approach("date_home", cid)
        app.answer_approach("accept", cid)
        assert app.bonds.mode(cid) is None
        date(energy=20)
        st["approach"] = None
        app.force_approach("date_home", cid)
        m0 = st["params"]["mood"]
        app.answer_approach("later", cid)
        assert app.bonds.mode(cid) == "meet" and st["params"]["mood"] < m0
        print("そろそろ帰ろう: OK")

        # ---- 5. 話しかけられたら, 返し方を選んで返す (メッセージと同じ判定)
        got = {}
        for _ in range(60):
            date()
            st["approach"] = None
            app.force_approach("date_look", cid)
            pv = app.presence.pending_view(char, st)
            ids = [x["id"] for x in pv["choices"]]
            assert "re_glad" in ids and "re_answer" not in ids, ids
            k = random.choice(["re_glad", "re_hard"])
            r = app.answer_approach("reply", cid, k)
            res = r["entry"]["reply"]["result"]
            got.setdefault(k, {}).setdefault(res, 0)
            got[k][res] += 1
            assert not st.get("approach") and "📱" not in r["entry"]["text"] and not r["entry"]["text"].startswith("（"), r["entry"]["text"]
        good = lambda g: g.get("good", 0) / float(sum(g.values()) or 1)   # noqa: E731
        assert good(got["re_glad"]) > good(got["re_hard"]) + 0.3, got
        print("そばで話しかけられて返す: OK |", got, "|", r["entry"]["text"].replace("\n", " / "))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK")


if __name__ == "__main__":
    main()
