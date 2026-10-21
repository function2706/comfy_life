"""自宅の状態の確認: 暮らしているうちにたまり, 家事で片付く. 一人暮らしでは「作業する」が無い.
家に招いた相手は家の様子に (性格しだいで) 反応し, 同居相手は日々の家の様子に反応する (一時データ, 画像生成なし).

    python tools/test_home.py
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

fix_noon(engine)     # 時刻を日曜の昼に固定 (流す日時に左右されないように)


def main():
    random.seed(17)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        H, B = app.home, app.bonds
        live = B.living()
        assert live, "最初のワールドは同居から"

        # ---- 1. 暮らしているうちにたまり, 家事で片付く (洗剤があるとはかどる)
        s0 = H.score()
        H.rec()["last_t"] = time.time() - 3 * 86400
        H.tick()
        s1 = H.score()
        assert s1 > s0 + 10, (s0, s1)
        v = app.state_view()["home"]
        assert v["label"] and len(v["parts"]) == 4 and all(p["word"] for p in v["parts"]), v
        app.items.add("detergent", 3)
        r = app.solo.result("chores", 1.5, time.time())
        assert H.score() < s1 and "家は「" in r["text"], (s1, H.score(), r["text"])
        print("accumulate / chores: OK", s0, "->", s1, "->", H.score(), r["text"])

        # 料理をすれば洗い物, 一緒に掃除すれば片付く (家にいるときだけ)
        cid = live
        st = app.state(cid)
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": 9e12}
        app.set_params({"mood": 60, "sleepiness": 0, "energy": 80, "satiety": 30}, cid)
        d0 = H.rec()["dishes"]
        app.act("cook", cid)
        assert H.rec()["dishes"] > d0
        for k in ("mess", "dishes", "laundry", "trash"):
            H.rec()[k] = 70.0
        st["cooldowns"] = {}
        before = H.score()
        app.act("clean", cid)
        assert H.score() < before
        print("cook / clean: OK")

        # ---- 2. 一人暮らしでは「作業する」は無い. 同居相手がいるときは「ちょっと作業するね」
        assert any(x["id"] == "busy" for x in app.solo.view()["plain"])
        w = app.create_world("一人暮らし")
        assert not app.bonds.living()
        assert not any(x["id"] == "busy" for x in app.solo.view()["plain"]), "一人暮らしなのに「作業する」がある"
        try:
            app.solo.start("busy")
            raise AssertionError("一人暮らしで「作業する」ができてしまう")
        except ValueError:
            pass
        print("no busy when alone: OK")

        # ---- 3. 家に招く: 来た相手は家の様子に反応する. 性格しだい, 必ず好印象になるとは限らない
        g = next(c for c in app.chars if B.stage(c) == "contact")
        B.set_stage(g, "visit")
        gst = app.state(g)
        gst["override"] = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": 9e12}
        app.select_character(g)

        def invite(score_parts, persona):
            app.char(g)["persona_id"] = persona
            for k in ("mess", "dishes", "laundry", "trash"):
                H.rec()[k] = score_parts
            gst["cooldowns"] = {}
            B.end()
            app.set_params({"mood": 70, "affection": 60, "trust": 55, "sleepiness": 0}, g)
            H.last_key = None
            e = app.act("invite_home", g)["entry"]
            e["home_key"] = H.last_key
            assert B.mode(g) == "guest" and app.state_view(g)["bond"]["label"] == "あなたの家に来ている", app.state_view(g)["bond"]
            return e

        def seen(e, key):
            return e.get("home_key") == key

        clean = [invite(3.0, "kedakai") for _ in range(12)]
        n_clean = sum(seen(e, "home.guest_clean") for e in clean)
        assert 0 < n_clean < 12, "片付いていれば好印象になりやすいが, いつもではない: %d" % n_clean
        messy = [invite(90.0, "kedakai") for _ in range(12)]
        assert sum(seen(e, "home.guest_messy_mind") for e in messy) >= 6, "きれい好きは散らかりを気にしやすい"
        assert any(r["tell"].endswith("家が散らかっていた") for r in app.life.reasons(gst, time.time()))
        messy2 = [invite(90.0, "tenshin") for _ in range(12)]
        assert sum(seen(e, "home.guest_messy_ok") for e in messy2) >= 6, "気にしない人もいる"
        H.rec()["mess"] = 90.0
        helped = False
        for _ in range(12):
            e = invite(90.0, "aneki")
            if seen(e, "home.guest_messy_help"):
                helped = True
                break
        assert helped and H.score() < 90.0, "世話焼きは片付けを手伝い出す"
        # 帰ってもらう: 来客のあとは少し散らかる
        assert gst["override"]["location"] == "あなたの家", "来ている間は, あなたの家にいる"
        m0 = H.rec()["mess"]
        app.act("see_off", g)
        assert B.mode(g) is None and H.rec()["mess"] > m0
        assert not gst.get("override"), "帰ったら, あなたの家にいることにはならない"
        print("guest: OK (きれい: %d/12)" % n_clean)

        # ---- 4. 同居相手は, 日々の家の様子に反応する (一日に一度ほど, 気づいたときだけ)
        app.switch_world(next(x["id"] for x in store.load_worlds()["worlds"] if x["id"] != w["id"]))
        cid = app.bonds.living()
        st = app.state(cid)
        app.char(cid)["persona_id"] = "aneki"
        got = {"mind": 0, "help": 0}
        for _ in range(60):
            for k in ("mess", "dishes", "laundry", "trash"):
                H.rec()[k] = 90.0
            H.rec()["live_seen"] = {}
            H.last_key = None
            line, eff = H.live_check(app.char(cid), st, time.time())
            if line and H.last_key == "home.live_messy":
                got["mind"] += 1
            if line and H.last_key == "home.live_messy_help":
                got["help"] += 1
                assert H.score() < 90.0
        assert got["mind"] and got["help"], got
        H.rec()["live_seen"] = {cid: time.time()}
        assert H.live_check(app.char(cid), st, time.time()) == (None, {}), "一日に何度も言わない"
        print("housemate: OK", got)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
