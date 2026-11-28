"""部屋の設定: 音楽・お香 / アロマ (S61. core/ambience.py). 冷暖房の反応は同じ土台 (tools/test_ac_dispute.py・test_aircon.py).

音楽をかけたままほかのことができる・出かける / 相手の家・外で会うと止まる・映画の間は鳴らず観終えると戻る・
お香は時間で終わり, 閉じていた間に終わっても効き目を二重に数えない・品物が要る・二重に焚けない・
好き / 苦手で効きが揺れるが確定しない・苦手で言ってくる / 我慢する (来ている相手は自分で変えない)・答え (合わせる / 断る)・
答える前に家の様子から叶えた・あなたがかけた曲に気づく・同じ値の二度押しは何も起きない・
遡及の好みが一度だけ足される (いまある系統は変えない)・あなたがかけた曲を覚える (prefs)・夜中の音楽で寝ている同居相手の眠り・
相手の家で流れている音楽 (一度の訪問で一度)・絵の雰囲気 (設定で外せる)・開き直しで残る.

    python tools/test_ambience.py
"""
import collections
import copy
import os
import random
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import ambience as amb_mod, engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(61)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("音楽")
        A, M, S = app.ambience, app.ambience.musicr, app.ambience.scentr
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        app.life.player_state()["money"] = 10 ** 6
        app.presence.declare("none")
        app.presence.beat(time.time(), 0)

        # ---- 1. 遡及の好み: いまある系統は変えず, 音楽・香り・煙を一度だけ足す
        tv0 = copy.deepcopy(app.topics.tastes(char, st))
        assert not any(k.startswith(("music:", "scent:")) or k == "smoke" for k in tv0)
        tv = A.tastes(char, st)
        assert all(tv[k] == v for k, v in tv0.items()), "いまある系統は変えない"
        added = {k: v for k, v in tv.items() if k not in tv0}
        assert any(k.startswith("music:") for k in added) and any(k.startswith("scent:") for k in added), added
        assert st["tastes_fam"] == ["amb"]
        again = copy.deepcopy(A.tastes(char, st))
        assert again == tv and st["tastes_fam"] == ["amb"], "二重に足さない"
        st2 = {"tastes": copy.deepcopy(tv0), "params": {}}           # 同じキャラなら同じ値 (id で決まる)
        assert A.tastes(char, st2) == tv
        print("遡及の好み: OK 足したもの %s" % added)

        # ---- 2. 音楽: かける・止める・知らないジャンル・二度押し. かけたままほかのことができる
        assert A.music() is None
        try:
            A.you_music("enka")
            raise AssertionError("知らないジャンルを受けた")
        except ValueError:
            pass
        A.you_music("jazz")
        assert A.music()["v"] == "jazz" and A.playing() == "jazz"
        t_jazz = A.music()["t"]
        A.you_music("jazz")                                       # 二重に開いた画面から同じ操作
        assert A.music()["t"] == t_jazz, "同じジャンルの二度押しで, かけ直さない"
        app.solo.start("chores")
        assert app.presence.rec()["mode"] == "busy" and A.playing() == "jazz", "家事をしている間も流れている"
        app.presence.back()
        app.presence.declare("none")
        app.presence.beat(time.time(), 0)
        assert A.playing() == "jazz"
        H = app.home
        H._rec = None
        assert engine.App().ambience.music()["v"] == "jazz", "開き直しても残る"
        print("音楽をかけたまま: OK")

        # ---- 3. 出かけると止まる (外出・仕事・相手の家・外で会う). 家にいないとかけられない
        for how in ("out", "work"):
            A.you_music("pop")
            app.presence.declare(how)
            assert A.music() is None and "music" not in A.rec(), how
            try:
                A.you_music("pop")
                raise AssertionError("出かけているのにかけられた")
            except ValueError:
                pass
            app.presence.declare("none")
            app.presence.beat(time.time(), 0)
        for mode in ("visit", "meet"):
            A.you_music("pop")
            app.bonds.wrec()["with"] = {"cid": cid, "mode": mode, "t": time.time(), "until": time.time() + 3600}
            assert A.music() is None, mode
            app.bonds.wrec()["with"] = None
        print("出かけると止まる: OK")

        # ---- 4. 映画の間は鳴らず, 観終えると戻る (一緒に観る・一人で観る)
        A.you_music("rock")
        st["override"] = {"activity": "movie", "until": time.time() + 3600}
        assert A.music()["v"] == "rock" and A.playing() is None and A.view()["music"]["paused"]
        st["override"] = None
        assert A.playing() == "rock"
        app.presence.declare("busy")
        app.presence.rec()["solo"] = {"kind": "movie", "t": time.time()}
        assert A.playing() is None
        app.presence.declare("none")
        app.presence.beat(time.time(), 0)
        assert A.playing() == "rock"
        A.you_music("")
        assert A.music() is None
        print("映画の間: OK")

        # ---- 5. お香 / アロマ: 品物が要る・使うと減る・二重に焚けない・時間で終わる
        try:
            A.you_scent("lavender", "incense")
            raise AssertionError("お香が無いのに焚けた")
        except ValueError:
            pass
        assert amb_mod.HOW["incense"][1] == "incense"
        app.items.add("incense", 10)
        app.items.add("aroma_oil", 6)
        n0 = app.items.count("incense")
        A.you_scent("lavender", "incense")
        s = A.scent()
        assert s and app.items.count("incense") == n0 - 1 and 30 * 60 - 1 <= s["end"] - s["t"] <= 40 * 60 + 1, s
        try:
            A.you_scent("rose", "incense")
            raise AssertionError("二重に焚けた")
        except ValueError:
            pass
        assert app.items.count("incense") == n0 - 1
        assert A.scent(s["end"] + 1) is None and A.view(s["end"] + 1)["scent"]["on"] == ""
        A.you_scent("")
        assert A.scent() is None
        A.you_scent("citrus", "aroma")
        s = A.scent()
        assert 180 * 60 - 1 <= s["end"] - s["t"] <= 240 * 60 + 1 and app.items.count("aroma_oil") == 5
        A.you_scent("")
        print("お香 / アロマ: OK")

        # ---- 6. 効き: 同居して家で一緒・起きている相手に. 好き / 苦手で揺れるが確定しない. 二重に数えない
        app.bonds.set_stage(cid, "live")
        assert M.awake_home(cid, time.time())

        def with_taste(key, v):
            A.tastes(char, st)[key] = v

        def run_music(g, v, n=300):
            with_taste("music:" + g, v)
            c = collections.Counter()
            for _ in range(n):
                A.rec()["music"] = {"v": g, "t": time.time() - 7200, "by": "me"}
                st["amb_t"] = {"music": time.time() - 3600}
                st["mu_seen"] = A.rec()["music"]["t"]
                st["params"]["mood"] = 50
                st["params"]["stress"] = 50
                st["mu_check"] = time.time()                     # 反応は見ない (効きだけ)
                A.tick(char, st, time.time())
                d = st["params"]["mood"] - 50
                c["up" if d > 0.2 else "down" if d < -0.2 else "same"] += 1
            return c
        like, dislike = run_music("jazz", 0.8), run_music("rock", -0.8)
        assert like["up"] > 200 and like["down"] == 0 and like["same"] > 0, like
        assert dislike["down"] > 200 and dislike["up"] == 0 and dislike["same"] > 0, dislike
        # 二重に数えない: 数えたところから先だけ
        A.rec()["music"] = {"v": "jazz", "t": time.time() - 7200, "by": "me"}
        st["amb_t"] = {"music": time.time()}
        m0 = st["params"]["mood"]
        A.tick(char, st, time.time())
        assert st["params"]["mood"] == m0
        A.rec().pop("music")
        # お香: 閉じていた間に終わった → 終わりまでを一度だけ
        with_taste("scent:lavender", 0.9)
        with_taste("smoke", 0.0)
        t0 = time.time() - 3 * 3600
        A.rec()["scent"] = {"v": "lavender", "how": "incense", "t": t0, "end": t0 + 1800, "by": "me"}
        st["amb_t"] = {"scent": t0}
        st["sc_seen"] = t0
        st["sc_check"] = time.time()
        gains = []
        for _ in range(2):
            st["params"]["stress"] = 50
            A.tick(char, st, time.time())
            gains.append(50 - st["params"]["stress"])
        assert gains[1] == 0 and st["amb_t"]["scent"] == t0 + 1800, gains
        print("効き: OK 好き %s / 苦手 %s・お香の効き %s" % (dict(like), dict(dislike), gains))

        # ---- 7. 苦手な曲: 言ってくる / 自分で変える / 我慢する. 来ている相手は自分で変えない
        with_taste("music:rock", -0.9)
        with_taste("music:jazz", 0.9)

        def reset():
            for k in ("mu_talk", "mu_day", "mu_check", "mu_self", "mu_note"):
                st.pop(k, None)
            A.rec()["music"] = {"v": "rock", "t": time.time(), "by": "me"}
            st["mu_seen"] = A.rec()["music"]["t"]
            st["params"]["mood"] = 60

        def tally(n=400):
            c = collections.Counter()
            for _ in range(n):
                reset()
                M.tick(char, st, time.time())
                c["say" if st.get("mu_talk") else "self" if st.get("mu_self") else "none" if not st.get("mu_day") else "endure"] += 1
            return c
        c = tally()
        assert all(c[k] > 0 for k in ("say", "self", "endure", "none")), c
        reset()
        st["mu_self"] = None
        # 来ている相手 (同居でない): 自分では変えない
        app.bonds.set_stage(cid, "visit")
        app.bonds.wrec()["with"] = {"cid": cid, "mode": "guest", "t": time.time() - 60, "until": time.time() + 3600}
        st["override"] = app._guest_override("invite", time.time())
        assert M.awake_home(cid, time.time()) and app.aircon.awake_home(cid, time.time())
        g = tally()
        assert g["self"] == 0 and g["say"] > 0 and g["endure"] > 0, g
        # 冷暖房も, 来ている相手は自分で変えない (S58 の反応を来客にも)
        import core.season as season
        season.temp = lambda dt, wx=None: 34.0
        season.day_range.cache_clear()
        tr = dict(app.traits(char), heat=1.4, cold=1.0)
        traits0 = app.traits
        app.traits = lambda ch, tr=tr: tr
        ac = collections.Counter()
        for _ in range(400):
            for k in ("ac_talk", "ac_day", "ac_check", "ac_self"):
                st.pop(k, None)
            app.home.set_mode("eco")
            app.aircon.tick(char, st, time.time())
            ac["say" if st.get("ac_talk") else "self" if st.get("ac_self") else "none" if not st.get("ac_day") else "endure"] += 1
        assert ac["self"] == 0 and ac["say"] > 0 and app.home.ac_mode() == "eco", ac
        st["ac_talk"] = {"t": time.time(), "want": "strong", "from": "eco", "hot": True}
        assert app.aircon.pending() and app.aircon.pending()["cid"] == cid, "来ている相手の言ってきたことにも答えられる"
        app.traits = traits0
        st.pop("ac_talk", None)
        print("出方: OK 同居 %s / 来ている %s / 来ている相手の冷暖房 %s" % (dict(c), dict(g), dict(ac)))

        # ---- 8. 言ってきたことへの答え・答える前に叶えた・画面の箱
        reset()
        st["mu_talk"] = {"t": time.time(), "want": "jazz", "from": "rock"}
        pv = A.pending()
        assert pv and pv["kind"] == "mu" and [x["id"] for x in pv["choices"]] == ["match", "push"], pv
        v = app.state_view()
        assert v.get("amb_talk") and v["amb_talk"]["kind"] == "mu"
        r = A.respond("mu", "match")
        assert A.music()["v"] == "jazz" and r["key"] == "match" and not st.get("mu_talk")
        try:
            A.respond("mu", "match")
            raise AssertionError("二度答えられた")
        except ValueError:
            pass
        reset()
        st["mu_talk"] = {"t": time.time(), "want": "jazz", "from": "rock"}
        r = A.respond("mu", "push")
        assert A.music()["v"] == "rock" and r["key"] == "push"
        reset()
        st["mu_talk"] = {"t": time.time(), "want": "off", "from": "rock"}
        A.you_music("pop")                           # 答える前に家の様子から変えた
        assert not st.get("mu_talk")
        # かけたい (相手の好きな曲): いいよ → 流れる / 答えないままはうやむや (機嫌は下げない)
        A.you_music("")
        st["mu_talk"] = {"t": time.time(), "want": "jazz", "from": "off", "play": True, "sour": False}
        assert [x["label"] for x in A.pending()["choices"]] == ["かけていいよ", "いまはやめておいてもらう"]
        A.respond("mu", "match")
        assert A.music()["v"] == "jazz"
        st["mu_talk"] = {"t": time.time() - 7 * 3600, "want": "jazz", "from": "off", "play": True, "sour": False}
        m0 = st["params"]["mood"]
        M.tick(char, st, time.time())
        assert not st.get("mu_talk") and st["params"]["mood"] == m0
        # 香り: 苦手 → 止めて窓を開ける
        with_taste("scent:rose", -0.9)
        A.you_scent("")
        A.rec()["scent"] = {"v": "rose", "how": "aroma", "t": time.time(), "end": time.time() + 3600, "by": "me"}
        st["sc_talk"] = {"t": time.time(), "want": "off", "from": "rose"}
        assert A.pending() is None or A.pending()["kind"] in ("mu", "sc")
        r = S.respond("match")
        assert A.scent() is None and r["key"] == "match"
        print("答え: OK")

        # ---- 9. あなたがかけた曲に気づく (好き / 苦手). 覚える (prefs). 続けて押しても 30 分は言わない
        A.you_music("")
        st.pop("mu_note", None)
        st.pop("prefs", None)
        keys = collections.Counter()
        for i in range(200):
            st.pop("mu_note", None)
            A.you_music("")
            r = A.you_music("jazz" if i % 2 else "rock")
            if r.get("entry"):
                keys[r["entry"]["ambience"]] += 1
        assert keys["mu.like"] > 0 and keys["mu.notice"] > 0, keys
        assert st["prefs"].get("music:jazz", 0) > 0 and st["prefs"].get("music:rock", 0) > 0
        got = 0
        for i in range(20):
            got += bool(A.you_music("jazz" if i % 2 else "rock").get("entry"))
        assert got <= 1, got
        print("気づく・覚える: OK %s" % dict(keys))

        # ---- 10. 夜中の音楽: 寝ている同居相手の眠りが浅くなる (一晩に一度だけ理由を残す)
        app.bonds.wrec()["with"] = None
        st["override"] = None
        app.bonds.set_stage(cid, "live")
        scene0 = app.scene_at
        app.scene_at = lambda ch, s, dt: dict(scene0(ch, s, dt), asleep=True, away=False)
        A.rec()["music"] = {"v": "jazz", "t": time.time() - 7200, "by": "me"}
        st["amb_t"] = {"music": time.time() - 3600}
        st["params"]["energy"] = 50
        st.pop("mu_night", None)
        A.tick(char, st, time.time())
        assert st["params"]["energy"] < 50 and st.get("mu_night"), st["params"]["energy"]
        app.scene_at = scene0
        A.rec().pop("music")
        print("夜中の音楽: OK 体力 %.1f" % st["params"]["energy"])

        # ---- 11. 相手の家で流れている音楽 (一度の訪問で一度. 好きなものとして分かる)
        app.bonds.set_stage(cid, "visit")
        n = 0
        for i in range(60):
            app.bonds.wrec()["with"] = {"cid": cid, "mode": "visit", "t": 1000 + i, "until": time.time() + 3600}
            e1 = A.at_theirs(char, st, time.time())
            e2 = A.at_theirs(char, st, time.time())
            assert e2 is None
            if e1:
                n += 1
                assert e1["ambience"] == "mu.theirs"
        assert 5 < n < 45, n
        assert any(k["kind"] == "like" and k["text"] in amb_mod.MUSIC_LABEL.values() for k in st.get("known") or [])
        app.bonds.wrec()["with"] = None
        print("相手の家の音楽: OK %d/60" % n)

        # ---- 12. 絵の雰囲気: あなたの家にいる相手の絵だけ. 設定で外せる
        from datetime import datetime
        app.bonds.set_stage(cid, "live")
        A.you_music("lofi")
        A.rec()["scent"] = {"v": "forest", "how": "incense", "t": time.time(), "end": time.time() + 1800, "by": "me"}
        part = A.prompt_part(char, st, datetime.now())
        assert part and "speaker" in part["pos"] and "incense" in part["pos"], part
        pos, _, parts = app.build_prompt(char, st, datetime.now(), {"id": "x", "name": "x", "pos": "", "neg": ""})
        assert "speaker" in pos and any(p["src"].startswith("部屋") for p in parts)
        A.set_prompt(False)
        assert A.prompt_part(char, st, datetime.now()) is None
        A.set_prompt(True)
        app.presence.declare("out")
        assert A.prompt_part(char, st, datetime.now()) is None or "speaker" not in A.prompt_part(char, st, datetime.now())["pos"]
        print("絵: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
