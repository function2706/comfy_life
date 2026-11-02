"""相手からの誘い (core/appoint.py): 家に行ける仲なら家での約束も (相手の家に呼ぶ / あなたの家に行きたい. 慣れているほど家になりやすい).
急な誘い (_maybe_now): 相手がいま手すきで退屈・寂しい・機嫌がいいと「これから会わない？」. 待ち合わせは 40〜60 分先.
返事がないまま過ぎても, 急な誘いなら気にするのは少しだけ (一時データ, 画像生成なし).

    python tools/test_invite_home.py
"""
import collections
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
    random.seed(8)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("誘い")
        A, B, C = app.appoint, app.bonds, app.chat
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        now = time.time()

        def reset(**kw):
            A.all()[:] = [x for x in A.all() if x["cid"] != cid]
            st["params"].update(dict(affection=70, trust=65, mood=70, boredom=70, loneliness=60, stress=20, health=90, energy=80), **kw)
            st["override"] = None

        def places(fn, n=60, **kw):
            c = collections.Counter()
            for _ in range(n):
                reset(**kw)
                x = fn(cid, now, 1000.0)
                c[x["place"] if x else None] += 1
            return c

        # ---- 1. 連絡先の段階: 家は出てこない
        B.set_stage(cid, "contact", now)
        c = places(A._maybe_invite)
        assert not any(k and k.startswith("home:") for k in c), c
        # ---- 2. 家に行ける仲: 家での約束も. 慣れているほど家が多い
        B.set_stage(cid, "visit", now)
        st["home_fam"] = {"v": 0.0, "t": now, "n": 1}
        low = places(A._maybe_invite, 150)
        st["home_fam"] = {"v": 0.9, "t": now, "n": 8}
        high = places(A._maybe_invite, 150)
        home = lambda c: sum(v for k, v in c.items() if k and k.startswith("home:"))        # noqa: E731
        print("予定の誘いが家: 慣れなし %d/150・慣れている %d/150 (相手の家 %d・あなたの家 %d)" % (
            home(low), home(high), high["home:" + cid], high["home:me"]))
        assert 0 < home(low) < home(high) and high["home:" + cid] and high["home:me"]
        msgs = [it["text"] for it in C.load(cid)["items"] if it["kind"] == "appoint_invite"]
        mine = next(t for t in msgs if t.endswith("%sの家）" % char.get("name", "")))        # (文面は性格別. 添える行き先で見分ける)
        yours = next(t for t in msgs if t.endswith("（あなたの家）"))
        print("  ", mine, "/", yours)

        # ---- 3. 急な誘い: 待ち合わせは 40〜60 分先. 手すきでなければ誘わない. 退屈でも寂しくもなく機嫌も普通なら誘わない
        reset()
        x = A._maybe_now(cid, now, 1000.0)
        assert x and x["now"] and 40 * 60 <= x["t"] - now <= 60 * 60 and x["status"] == "offered", x
        print("急な誘い:", C.load(cid)["items"][-1]["text"])
        reset()
        st["override"] = {"activity": "game", "label": "ゲーム中", "until": now + 3600}
        assert A._maybe_now(cid, now, 1000.0) is None, "何かしている最中は誘わない"
        reset(boredom=20, loneliness=20, mood=50)
        assert A._maybe_now(cid, now, 1000.0) is None, "その気がなければ誘わない"
        hits = places(A._maybe_now, 150)
        print("急な誘いの行き先:", dict(hits.most_common(6)))
        assert home(hits) and sum(v for k, v in hits.items() if k and not k.startswith("home:"))

        # ---- 4. 答える: 受ければ約束 (set). 返事がないまま時間が過ぎると, 急な誘いは少しだけ気にする
        reset()
        x = A._maybe_now(cid, now, 1000.0)
        A.answer(x["id"], True, now)
        assert x["status"] == "set"
        reset()
        x = A._maybe_now(cid, now, 1000.0)
        m0 = st["params"]["mood"]
        app.presence.rec()["appoint_check"] = x["t"] + 1          # (このときは, ほかに誘ってこないように)
        A.live(x["t"] + 1)
        assert x["status"] == "lapsed" and m0 - st["params"]["mood"] < 2, (x["status"], m0, st["params"]["mood"])
        print("受ける / 返事なし (機嫌 %.1f → %.1f): OK" % (m0, st["params"]["mood"]))
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
