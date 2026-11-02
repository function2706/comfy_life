"""相手の風邪と看病 (core/care.py): かかりやすさ (季節・体の弱さ)・かかっている間は家で寝ている・看病に呼ぶか (具合・仲・性格)・
頼まれた品・来てくれた・品を渡す・看病する (治りが早まる)・断る (あなたの様子しだい)・呼ばなかったら治ったあとに理由が残る
(一時データ, 画像生成なし).

    python tools/test_care.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import care as CA, engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(11)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("看病")
        A, B, K = app.appoint, app.bonds, app.care
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        now = time.time()
        B.set_stage(cid, "visit", now)

        def as_persona(pid):
            return dict(char, persona_id=pid)

        # ---- 1. かかりやすさ: 冬 > 夏, 病弱 > 元気, 疲れていると多い
        p0 = dict(st["params"])
        w = K.rate(char, st, time.mktime((2026, 1, 15, 12, 0, 0, 0, 0, -1)))
        s = K.rate(char, st, time.mktime((2026, 7, 15, 12, 0, 0, 0, 0, -1)))
        weak = K.rate(as_persona("byoujaku"), st, now)
        strong = K.rate(as_persona("genki"), st, now)
        st["params"]["energy"] = 10
        tired = K.rate(char, st, now)
        st["params"].update(p0)
        print("1日にひく割合: 冬 %.4f 夏 %.4f / 病弱 %.4f 元気 %.4f / 疲れ %.4f" % (w, s, weak, strong, tired))
        assert w > s and weak > strong and tired > K.rate(char, st, now)

        # ---- 2. かかっている間: 予定の外出は休んで家で寝ている. 健康は抑えられる
        st["ill"] = {"level": 2, "t0": now, "until": now + 2 * 86400}
        app.tick(cid, now + 60)
        sc = app.scene_at(char, st, datetime.fromtimestamp(now + 120))
        assert sc["location"] == "自宅" and "寝込んで" in sc["label"] and not sc["away"] and st["params"]["health"] <= 25, sc
        print("寝込んでいる:", sc["label"], "健康", st["params"]["health"])

        # ---- 3. 看病に呼ぶか: 寝込むほど・仲がいいほど. 自分から来ない人・照れ屋は具合が悪いくらいでは呼ばない
        st["params"].update(affection=75, trust=70)
        c = {pid: (K.call_chance(as_persona(pid), st, 1), K.call_chance(as_persona(pid), st, 2))
             for pid in ("amaenbo", "teinei", "cool", "kedakai", "uchiki")}
        print("呼ぶ割合 (具合が悪い / 寝込む):", {k: "%.2f/%.2f" % v for k, v in c.items()})
        assert c["amaenbo"][0] > c["teinei"][0] > c["cool"][0] and c["cool"][0] < 0.05 and c["kedakai"][0] < 0.05
        assert all(v[1] > v[0] for v in c.values()) and c["cool"][1] > 0.05
        st["params"].update(affection=40)
        assert K.call_chance(char, st, 2) == 0.0, "仲が浅ければ呼ばない"
        st["params"].update(affection=75)

        # ---- 4. 呼ぶ (品を頼むことも) → 行くと返す → 着くと看病の場面
        x = None
        for _ in range(200):
            A.all()[:] = []
            st["ill"] = {"level": 2, "t0": now, "until": now + 2 * 86400}
            x = K.live_call(cid, now)
            if x and x["want"]:
                break
        assert x and x["care"] and x["place"] == "home:" + cid and x["want"], x
        msg = [it for it in app.chat.load(cid)["items"] if it.get("appoint") == x["id"]][-1]["text"]
        print("呼ばれた:", msg)
        assert K.live_call(cid, now) is None, "一度だけ"
        A.answer(x["id"], True, now)
        assert x["status"] == "set" and x["plan"] == {}
        r = A._meet(x, now + 1800)
        assert B.mode(cid) == "visit" and app.athome.rec(cid)["care"]["want"] == x["want"], r
        print("着いた:", r["entry"]["text"])
        v = app.person_view(cid)["visit"]
        assert v["care"]["want"] and not v["care"]["have"]
        assert app.available(char, st, datetime.fromtimestamp(now + 1900))["nurse"]["ok"]

        # ---- 5. 品を渡す (頼まれた品はよく効く・治りが早まる) / 看病する (一度だけ早まる)
        u0 = st["ill"]["until"]
        want = x["want"][0]
        app.items.add(want, 1)
        app.items.add("pudding", 1)
        assert any(h_["wanted"] for h_ in app.person_view(cid)["visit"]["care"]["have"])
        a0 = st["params"]["affection"]
        e = K.give(cid, want, now + 1900)["entry"]
        assert st["ill"]["until"] < u0 and st["params"]["affection"] > a0 and app.items.count(want) == 0
        print("頼まれた品:", e["text"])
        if want != "pudding":
            print("ほかの品:", K.give(cid, "pudding", now + 1950)["entry"]["text"])
        u1 = st["ill"]["until"]
        r = app.act("nurse", cid)
        u2 = st["ill"]["until"]
        assert u2 < u1 and "楽に" in r["entry"]["text"], r["entry"]["text"]
        app.act("nurse", cid)
        assert st["ill"]["until"] == u2, "看病で早まるのは一度"
        print("看病:", r["entry"]["text"].split("\n")[-1])
        B.end(go_home=False)

        # ---- 6. 断る: 家にいて断ると信頼も下がる. 仕事・外出中なら仕方ない
        def refuse(mode):
            A.all()[:] = []
            st["ill"] = {"level": 2, "t0": now, "until": now + 86400}
            y = A.care_call(char, st, now, [])
            app.presence.declare(mode, now)
            t0, m0 = st["params"]["trust"], st["params"]["mood"]
            A.answer(y["id"], False, now)
            app.presence.declare("none", now)
            return t0 - st["params"]["trust"], m0 - st["params"]["mood"]
        home, work = refuse("none"), refuse("work")
        print("断った: 家にいて (信頼 -%.1f 機嫌 -%.1f) / 仕事中 (信頼 -%.1f 機嫌 -%.1f)" % (home + work))
        assert home[0] > 0 and work[0] == 0 and home[1] > work[1]

        # ---- 7. 呼ばなかった: 治ったあと, 言っていない理由として残る
        st["ill"] = {"level": 1, "t0": now - 86400, "until": now - 1}
        K.tick(char, st, now, 0.1)
        rs = [r_ for r_ in app.life.reasons(st, now) if r_["tell"] == "風邪で寝込んでいた"]
        assert rs and not rs[0]["told"] and "ill" not in st
        print("呼ばなかった: 治ったあと「何かあった？」で聞ける理由に:", rs[0]["tell"])
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
