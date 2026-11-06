"""読書と映画 (A3): ジャンルを選ぶ・技能の本は研鑽・ジャンルの好みが本人の口から分かる・移動中に読む / 観る (一時データ).

    python tools/test_reading.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from core import engine, geo as G, store, topics as T  # noqa: E402
from testclock import fix_noon, run_at  # noqa: E402

fix_noon(engine)
run_at(11)                # 時刻表の電車・バスが走っている平日の昼前 (core/transit.py)
G.INSTANT = False


def main():
    random.seed(12)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("読書")
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        L, ps = app.life, app.life.player_state()
        ps["money"], ps["stamina"] = 50000, 100
        now = time.time()

        # ---- 1. ジャンルを選んで読む・観る
        app.items.add("novel", 2)
        app.topics.read(0.3, now, 1.5, genre="romance")
        assert ps["reading"]["tags"] == ["books", "romance"], ps["reading"]
        app.topics.read(2.0, now, 1.5)                       # 続き (ジャンルは最初に選んだまま)
        x = max(app.topics.all(), key=lambda x: x["t"])
        assert x["src"] == "book" and "romance" in x["tags"], x
        app.topics.watch(2.5, now, 2.0, genre="horror")
        x = next(x for x in app.topics.all() if x["src"] == "movie")
        assert "horror" in x["tags"], x
        v = app.solo.view()
        assert [g["id"] for g in v["genres"]["books"]][:2] == ["mystery", "romance"] and v["novels"] == 1
        print("ジャンル: OK |", x["text"])

        # ---- 2. 技能の本を読む = その技能の研鑽
        try:
            app.solo.start("read", skill="book:cook")
            raise AssertionError("本が無いのに読めた")
        except ValueError:
            pass
        app.items.add("book_cook", 1)
        assert any(b["skill"] == "cook" for b in app.solo.view()["skill_books"])
        r = app.solo.start("read", skill="book:cook")
        assert app.presence.rec()["solo"]["kind"] == "practice" and app.presence.rec()["solo"]["skill"] == "cook", r
        with app.lock:
            app.come_back()
        print("技能の本: OK")

        # ---- 3. ジャンルの好みが本人の口から分かる (仲・機嫌・性格しだい. 聞いたことは覚える)
        st["tastes"] = {"romance": 0.9, "horror": -0.8}
        app.bonds.set_stage(cid, "visit")
        app.set_params({"trust": 85, "mood": 70}, cid)
        rom = {"id": "t1", "src": "book", "text": "恋愛小説を読んだ話", "tags": ["books", "romance"], "t": now}
        hor = {"id": "t2", "src": "movie", "text": "ホラー映画を観た話", "tags": ["movies", "horror"], "t": now}
        said = [app.topics.reveal(char, st, rom, "hit", now) for _ in range(40)]
        assert any(said) and not all(said), said
        assert any(k["kind"] == "like" and k["text"] == T.TAGS["romance"] for k in st["known"]), st["known"]
        bad = [app.topics.reveal(char, st, hor, "bored", now) for _ in range(40)]
        assert any(b and "ホラー" in b for b in bad)
        assert any(k["kind"] == "dislike" and k["text"] == "ホラー" for k in st["known"])
        app.set_params({"trust": 20, "mood": 30}, cid)
        app.bonds.set_stage(cid, "contact")
        few = sum(1 for _ in range(200) if app.topics.reveal(char, st, rom, "hit", now))
        print("好みが分かる: 近い仲 %d/40, 浅い仲・不機嫌 %d/200 | %s" % (sum(1 for x in said if x), few, next(x for x in said if x)))
        assert few < 40

        # ---- 4. 移動中に読む (電車・バス・タクシーだけ. 座っていられた時間ぶん)
        ps.pop("reading", None)
        with app.lock:
            app.solo.start("out", place="mall", how="transit")
        tr = app.geo.travel()
        assert app.geo.view()["can_read"]
        app.geo.set_doing("read:mystery")
        span = tr["arr"] - tr["t0"]
        tr["t0"] -= span + 60
        tr["arr"] -= span + 60
        tr["doing"]["t"] = tr["t0"]                      # 乗ってすぐ読み始めた
        with app.lock:
            a = app.geo.tick(time.time())
        seated = app.geo.seated_h(dict(tr, t0=tr["t0"], arr=tr["arr"]), tr["t0"], tr["arr"])
        assert "移動中に" in a["text"] and ("推理" in a["text"] or "洋館" in a["text"]), a
        assert 0 < seated < span / 3600.0, (seated, span)
        print("移動中に読む: OK |", a["text"])
        with app.lock:
            app.presence.back(time.time())
        app.presence.rec()["pos"] = "home:me"
        with app.lock:
            app.solo.start("out", place="park", how="walk")
        try:
            app.geo.set_doing("movie")
            raise AssertionError("歩きながら観られた")
        except ValueError as e:
            assert "徒歩" in str(e), e
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
