"""稼ぎ方その 2 (副業・頼まれごと・文章のスキル) の確認 (一時データ, 画像生成なし).
- 副業: スキルが届くと依頼が来はじめる (運と評判しだい. スキルと評判が高いほど来やすい). 取りかかって戻ると,
  時間と出来ばえで報酬と評判が決まる (途中でやめると減る・すぐやめると取り消し)
- 文章のスキル: 9 つ目. 研鑽・文章の書き方の本
- 頼まれごと: 知り合いから, ときどき (トークに一行). 引き受けて手伝うと仲が深まり, お礼 (お金のことも, そうでないことも).
  断ると少しがっかり, 返事をしないまま流れると信頼が少し下がる

    python tools/test_earn2.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, items, solo, life  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(5)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("副業")
        E, L = app.earn, app.life
        ps = L.player_state()
        P = app.presence

        # ---- 文章のスキル
        assert "write" in life.SKILLS and ps["skills"]["write"] == 10.0
        assert solo.SKILL_LABEL["write"] == "文章" and items.PRACTICE_BOOK["write"] in items.CATALOG
        del ps["skills"]["write"]
        L.player = None
        assert L.player_state()["skills"].get("write", 10.0) == 10.0
        ps = L.player_state()

        # ---- 副業の依頼: スキルが届くまでは来ない, 高いほど来やすい
        def offers(skill, rep, n=300):
            hits = 0
            for i in range(n):
                g = E.gigs()
                g["offers"], g["rep"] = [], {k: rep for k in g["rep"]}
                for k in ("house", "cook", "write"):
                    ps["skills"][k] = skill
                hits += len(E.gig_offers(time.time()))
            return hits / float(n)
        r0, r1, r2 = offers(10, 30), offers(40, 30), offers(90, 80)
        print("依頼の来やすさ（1日あたり件数）: スキル10 %.2f / 40 %.2f / 90・評判80 %.2f" % (r0, r1, r2))
        assert r0 == 0 and 0 < r1 < r2

        # ---- 取りかかる → 戻る
        g = E.gigs()
        g["offers"] = []
        while not g["offers"]:
            E.gig_offers(time.time())
        o = g["offers"][0]
        ps["stamina"] = 100
        P.rec()["beat"] = P.rec()["input"] = time.time()
        app.earn_api("gig", {"id": o["id"]})
        assert P.rec()["mode"] == "work" and P.rec()["job"] == "gig" and not g["offers"][:0]
        P.rec()["since"] -= o["h"] * 3600
        m0, rep0 = ps["money"], g["rep"][o["kind"]]
        r = app.come_back()
        print("副業:", r["entry"]["text"])
        assert ps["money"] > m0 and "円" in r["entry"]["text"]
        # 出来ばえの平均: スキルが高いほど評判が上がる
        def avg_rep(skill, n=300):
            out = []
            for i in range(n):
                g["rep"]["write"] = 50.0
                ps["skills"]["write"] = skill
                E.gig_done({"kind": "write", "client": "x", "h": 2, "pay": 3000}, 2.0, time.time())
                out.append(g["rep"]["write"] - 50)
            return sum(out) / n
        lo, hi = avg_rep(10), avg_rep(90)
        print("評判の動き（平均）: 文章10 %+.1f / 90 %+.1f" % (lo, hi))
        assert lo < hi and hi > 0
        pay, text, _ = E.gig_done({"kind": "house", "client": "x", "h": 3, "pay": 4500}, 1.0, time.time())
        assert "途中" in text and pay < 4500
        pay, text, _ = E.gig_done({"kind": "house", "client": "x", "h": 3, "pay": 4500}, 0.1, time.time())
        assert pay == 0 and "取り消し" in text

        # ---- 頼まれごと
        cid = next(c for c in app.chars if app.bonds.stage(c) in ("contact", "visit"))
        st = app.state(cid)
        fs = E.favors()
        for i in range(3000):
            if E.favor_offers(time.time()):
                break
        assert fs and fs[0]["cid"] in app.chars
        f = fs[0]
        # 頼まれ方はメッセージ (相手の発言). 日時のすり合わせは約束の欄で (core/appoint.py. 詳しくは tools/test_favor_appoint.py)
        assert any(x.get("kind") == "favor_ask" and x["who"] == "her" for x in app.chat.load(f["cid"])["items"])
        cst = app.state(f["cid"])
        a0 = cst["params"]["affection"]
        ps["stamina"] = 100
        x = app.appoint.find(f["appoint"])
        if x.get("plants"):                  # 水やりは会わないので, 手伝いの流れを見るために家での手伝いに
            x.update(plants=False, fixed=False)
            f["kind"] = "clean"
        if x.get("ask"):
            app.appoint.counter(x["id"], time.time() + 86400)
            x["status"] = "offered"
            x["ask"] = False
        app.appoint.answer(x["id"], True)
        assert x["status"] == "set"
        x["t"] = time.time() - 60          # 当日: 相手の家に出向くと, 会えて手伝いに取りかかる
        app.presence.declare("out", time.time())
        P.rec()["place"] = x["place"]
        app.appoint._tick(x, time.time(), [])
        assert P.rec()["job"] == "favor" and x["status"] == "met"
        P.rec()["since"] -= f["h"] * 3600
        r = app.come_back()
        print("頼まれごと:", r["entry"]["text"])
        assert "終えた" in r["entry"]["text"] and app.state(f["cid"])["params"]["affection"] >= a0 and not E.favors()
        # お礼: お金のことも, そうでないことも
        moneys = 0
        for i in range(200):
            m0 = ps["money"]
            L.her_money(cst)["a"] = 50000
            E.favor_done({"cid": f["cid"], "label": "荷物運び", "h": 1.5, "tire": 0}, 1.5, time.time())
            moneys += ps["money"] > m0
        print("お礼にお金をもらえた: %d/200" % moneys)
        assert 10 < moneys < 190
        # 断る / 流れる
        fs.append({"id": "fx", "cid": f["cid"], "label": "大掃除の手伝い", "h": 3, "tire": 20, "t": time.time(), "until": time.time() + 3600})
        m1 = cst["params"]["mood"]
        r = app.earn_api("favor", {"id": "fx", "yes": False})
        assert "断った" in r["text"] and app.state(f["cid"])["params"]["mood"] <= m1
        fs.append({"id": "fy", "cid": f["cid"], "label": "大掃除の手伝い", "h": 3, "tire": 20, "t": time.time() - 4 * 86400, "until": time.time() - 1})
        t1 = app.state(f["cid"])["params"]["trust"]
        E.favor_offers(time.time())
        assert not any(x["id"] == "fy" for x in E.favors()) and app.state(f["cid"])["params"]["trust"] <= t1
        v = app.state_view()["earn"]
        assert "gigs" in v and "favors" in v
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp + "_backup", ignore_errors=True)


if __name__ == "__main__":
    main()
