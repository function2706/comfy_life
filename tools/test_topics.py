"""話題のたくわえ (core/topics.py): 話題の元・相手が乗るか (好み・隠れた好み・飽き・前も聞いた・知ってる・思い出話)・
会って / メッセージで振る・以前のセーブから拾う・古い話題は消える.

    python tools/test_topics.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, topics as TP  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(41)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("話題")
        T = app.topics
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)

        # ---- 1. 以前のセーブ: はじめて使うとき, 一人の時間の記録から直近 2 週間の体験を拾う (一度だけ. 古いものは拾わない)
        now = time.time()
        app.solo.note("out", "水族館を見て回った", now - 3 * 86400, hours=2, place="aquarium")
        app.solo.note("out", "海を歩いた", now - 30 * 86400, hours=2, place="beach")
        texts = [x["text"] for x in T.all()]
        assert any("水族館" in t for t in texts) and not any("海に行った" in t for t in texts), texts
        n0 = len(T.all())
        app.life.player_state()["topics_v1"] = True
        T.ps()
        assert len(T.all()) == n0
        print("以前の記録から拾う: OK", texts)

        # ---- 2. 話題の元: 一人で出かけた先・読んだ本 (小説を使う)・観た映画. 短く切り上げたら話題にならない
        r = app.solo.result("out", 2.0, time.time(), place="park")
        assert any("公園" in x["text"] for x in T.all())
        try:
            app.solo.start("read")
            raise AssertionError("本が無いのに読み始められた")
        except ValueError as e:
            assert "読む本" in str(e)
        app.items.add("novel", 1)
        k = len(T.all())
        app.solo.result("read", 0.5, time.time())
        assert len(T.all()) == k and app.items.count("novel") == 1
        app.solo.result("read", 2.0, time.time())
        assert len(T.all()) == k + 1 and app.items.count("novel") == 0 and T.all()[-1]["src"] == "book"
        app.solo.result("movie", 2.5, time.time())
        assert T.all()[-1]["src"] == "movie"
        print("話題の元: OK |", [x["text"] for x in T.all()[-3:]], r["text"][:20])

        # ---- 3. 好み: 性格の既定 + キャラごとの隠れた好み (同じ性格でも違う. キャラごとに固定)
        a = {"id": "a1", "persona_id": "teinei"}
        b = {"id": "b2", "persona_id": "teinei"}
        ta, tb = T.tastes(a, {}), T.tastes(b, {})
        assert ta != tb and T.tastes(a, {}) == ta
        many = [T.tastes({"id": "c%d" % i, "persona_id": "teinei"}, {}) for i in range(40)]
        avg = lambda k: sum(m.get(k, 0) for m in many) / 40.0      # noqa: E731
        assert avg("books") > avg("games") + 0.3            # 丁寧な人の既定の好き (本) が土台にある (隠れた好みで揺れる)
        print("好み: OK | 同じ性格でも %s / %s" % (ta, tb))

        # ---- 4. 乗るか: 好きな系統ほど盛り上がる. 同じ系統が続くと飽きる. 同じ話は「前も聞いた」. 思い出話は乗りやすい
        st["tastes"] = {"animals": 1.0, "work": -1.0}
        app.set_params({"mood": 55, "energy": 60}, cid)

        def rate(tags, n=200, with_=None, src="solo"):
            hits = 0
            for _ in range(n):
                st["topic_tags"] = []
                x = {"id": "x", "t": time.time(), "src": src, "text": "t", "tags": tags, "told": {}}
                if with_:
                    x["with"] = with_
                hits += T.judge(char, st, x, time.time())[0] == "hit"
            return hits / float(n)
        r_like, r_dis = rate(["animals"]), rate(["work"])
        assert r_like > r_dis + 0.5 and r_like < 0.97, (r_like, r_dis)          # 好きでも必ずではない
        assert rate(["books"], with_=[cid]) > rate(["books"]) + 0.1
        st["topic_tags"] = [{"tag": "animals", "t": time.time()}] * 3
        tired = sum(T.judge(char, st, {"id": "y", "t": time.time(), "src": "solo", "text": "t", "tags": ["animals"], "told": {}},
                            time.time())[0] == "hit" for _ in range(200)) / 200.0
        assert tired < r_like - 0.3, (tired, r_like)
        again = [T.judge(char, st, {"id": "z", "t": time.time(), "src": "solo", "text": "t", "tags": ["animals"],
                                    "told": {cid: time.time()}}, time.time())[0] for _ in range(100)]
        assert again.count("again") > 60
        known = sum(T.judge(char, st, {"id": "r%d" % i, "t": time.time(), "src": "rumor", "text": "t", "tags": ["gossip"], "told": {}},
                            time.time())[0] == "known" for i in range(200))
        assert 30 < known < 120, known
        print("乗るか: OK | 好き %.2f / 苦手 %.2f / 飽き %.2f・前も聞いた %d/100・噂を知ってた %d/200" % (r_like, r_dis, tired, again.count("again"), known))

        # ---- 5. 会って振る: 話した記録・何の話をしたか・盛り上がれば好きなものの覚えに
        app.bonds.set_stage(cid, "visit")
        app.bonds.start(cid, "visit")
        st = app.state(cid)
        st["tastes"] = {"animals": 1.0}
        st["topic_tags"] = []
        x = T.add("solo", "水族館に行った話", ["animals", "sea"])
        res = None
        for _ in range(10):
            x["told"] = {}
            st["topic_tags"] = []
            r = T.tell(x["id"], cid)
            res = r["topic_res"]
            if res == "hit":
                break
        assert res == "hit" and cid in x["told"] and r["entry"]["text"].startswith("（水族館に行った話をした）")
        assert any(k.get("kind") == "like" and k.get("text") == "動物" for k in st.get("known") or []), st.get("known")
        r2 = T.tell(x["id"], cid)
        assert r2["topic_res"] in ("again", "hit", "ok", "bored")
        print("会って振る: OK |", r["entry"]["text"].replace("\n", " "))

        # 一緒に出かけた先は, 思い出話になる
        app.act("leave_visit", cid)
        st = app.state(cid)
        st["cooldowns"] = {}
        x2 = T.from_act(char, app.action("aquarium"), {}, {}, time.time())
        assert x2 and cid in x2["with"] and char["name"] in x2["text"]
        print("思い出話: OK |", x2["text"])

        # ---- 6. メッセージで振る: 返事は時間差. トークには何の話をしたか
        app.bonds.set_stage(cid, "contact")
        y = T.add("book", "恋愛小説を読んだ話", ["books"])
        st["msg_pending"] = None
        st["contacts"] = []
        T.send(y["id"], cid)
        st = app.state(cid)
        st["msg_pending"].update(due=time.time() - 1, reply=True)
        out = app.deliver_due()
        items = app.chat.load(cid)["items"]
        assert any(i["text"] == "（恋愛小説を読んだ話をした）" for i in items) and out and out[0]["text"].startswith("📱『")
        assert cid in y["told"]
        print("メッセージで振る: OK |", out[0]["text"])

        # ---- 7. 古い話題は消える
        old = T.add("solo", "昔の話", ["nature"], time.time() - (TP.KEEP_DAYS + 1) * 86400)
        assert old["id"] not in [z["id"] for z in T.all()]
        print("古い話題は消える: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
