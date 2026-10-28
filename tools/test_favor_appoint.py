"""頼まれごとを, 日時をすり合わせてから相手の家へ行く形で (core/appoint.py の favor_* と core/earn.py の favors).
引っ越し (日時決め打ち)・大掃除など (案 / 都合を聞く)・植木の水やり (留守中に自分で行く)・当日・すっぽかし (重め)・流れる・
日がずれる / 取りやめ・連絡先の段階でも相手の家・以前から頼まれていたもの・閉じていた間・対面で頼まれる (一時データ, 画像生成なし).

    python tools/test_favor_appoint.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import appoint as AP, earn as EA, engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(12)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("頼まれごと")
        A, E, C, B = app.appoint, app.earn, app.chat, app.bonds
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        B.set_stage(cid, "contact")
        now = time.time()

        def offer(kind):
            k, name, h, tire = EA.FAVOR_KIND[kind]
            f = {"id": "f%s%d" % (kind, random.randrange(10 ** 6)), "cid": cid, "kind": kind, "label": name, "h": h, "tire": tire,
                 "t": now, "until": now + 3 * 86400}
            E.favors().append(f)
            return f, A.favor_offer(f, now)

        # ---- 1. 引っ越し: 相手が日時を決めてくる. 受けるか断るかだけ (別の日時は返せない). 頼まれ方はメッセージ (相手の発言)
        f, x = offer("move")
        assert x["status"] == "offered" and x["fixed"] and x["place"] == "home:" + cid
        last = C.load(cid)["items"][-1]
        assert last["who"] == "her" and last["kind"] == "favor_ask" and "引っ越し" in last["text"], last
        try:
            A.counter(x["id"], now + 86400)
            raise AssertionError("決め打ちの日に別の日時を返せた")
        except ValueError:
            pass
        A.answer(x["id"], True, now)
        assert x["status"] == "set" and not x["plan"]["noshow"]
        # 連絡先の段階でも, 頼まれごとの約束がある間は相手の家が行き先にある
        assert "home:" + cid in app.places.table()
        print("引っ越し (決め打ち・受けるだけ・連絡先でも家へ): OK", last["text"])

        # ---- 2. 当日: 相手の家に出向いて会えたら, 手伝いに取りかかる → 戻るとお礼の判定
        x["t"] = now - 60
        app.presence.declare("out", now)
        pr = app.presence.rec()
        pr["place"] = x["place"]
        app.presence.save()
        out = []
        A._tick(x, now, out)
        p = app.presence.rec()
        assert x["status"] == "met" and p.get("job") == "favor" and p["task"]["id"] == f["id"], (x["status"], p)
        pay, text = E.favor_done(f, f["h"], now + f["h"] * 3600)
        assert f not in E.favors() and "終えた" in text
        app.presence.declare("none", now)
        print("当日 (家で会って手伝い・戻ってお礼):", text)

        # ---- 3. 大掃除など: 都合を聞かれたら, 日時を返すまで受けられない. 返した日時に相手の予定があれば, 別の日時か断り
        x = None
        for _ in range(30):
            f, x = offer("clean")
            if x.get("ask"):
                break
            A.answer(x["id"], False, now)
        assert x.get("ask") and any(it.get("appoint") == x["id"] and it["kind"] == "favor_ask" for it in C.load(cid)["items"])
        try:
            A.answer(x["id"], True, now)
            raise AssertionError("都合を聞かれているのに, 日時なしで受けられた")
        except ValueError:
            pass
        A.counter(x["id"], now + 2 * 86400)
        assert x["status"] == "asked"
        key, eff, extra = A.reply(char, st, {"appoint": x["id"]}, now, {})
        assert key == "favor_yes" and x["status"] == "set", key
        # 相手の予定と重なれば, 別の日時を返してくるか断る
        f2, y = offer("furniture")
        y["ask"] = False
        A.counter(y["id"], now + 3 * 86400)
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), busy=True)
        key, _, _ = A.reply(char, st, {"appoint": y["id"]}, now, {})
        app.scheduled_scene = sched
        assert key in ("favor_counter", "favor_busy") and y["status"] in ("offered", "declined"), (key, y["status"])
        print("大掃除など (都合を聞かれる → 日時を返す → 受けてくれる / 予定が重なれば %s): OK" % key)

        # ---- 4. 植木の水やり: 相手の留守中に, 自分で家へ行く (会わない). 行かなければ枯れてがっかり
        f, x = offer("plants")
        assert x["plants"] and x["until"] > x["t"]
        A.answer(x["id"], True, now)
        x["t"] = now - 3600
        app.presence.declare("none", now)
        r = app.solo.start("out", place=x["place"])
        assert "水" in r["done"] or "植木" in r["done"] and x["status"] == "met" and f not in E.favors(), r
        app.presence.declare("none", now)
        f, x = offer("plants")
        A.answer(x["id"], True, now)
        x["t"], x["until"] = now - 4 * 86400, now - 60
        m0 = st["params"]["mood"]
        A.live(now)
        assert x["status"] == "missed" and any(it["kind"] == "favor_plants_dead" for it in C.load(cid)["items"]) and st["params"]["mood"] < m0
        print("植木 (留守中に自分で行く・行かなければ枯れる): OK", r["done"])

        # ---- 5. 返事を放っておくと流れる (ほかの人に頼んで済む. 信頼が少し下がる)
        f, x = offer("pc")
        x["made"] = now - 25 * 3600
        tr0 = st["params"]["trust"]
        A.live(now)
        assert x["status"] == "lapsed" and f not in E.favors() and any(it["kind"] == "favor_lapsed" for it in C.load(cid)["items"])
        assert st["params"]["trust"] < tr0
        # ---- 6. すっぽかしは普段の約束より重い
        def missed(favor):
            st["params"].update(mood=60, trust=60, affection=60)
            if favor:
                f, x = offer("carry")
                x["ask"] = False
                A.answer(x["id"], True, now)
            else:
                x = {"id": "n%d" % random.randrange(10 ** 6), "cid": cid, "t": now, "place": "cafe", "do": "cafe", "by": "me",
                     "status": "set", "made": now, "plan": {"noshow": False, "late": 0, "cancel_checked": True}}
                A.all().append(x)
            x["t"] = now - AP.GRACE - 60
            x.setdefault("plan", {})["cancel_checked"] = True
            app.presence.declare("none", now)
            A._tick(x, now, [])
            assert x["status"] == "missed"
            return 60 - st["params"]["mood"], 60 - st["params"]["trust"]
        fav, plain = missed(True), missed(False)
        assert fav[0] > plain[0] and fav[1] > plain[1], (fav, plain)
        print("流れる・すっぽかし (頼まれごと 機嫌 -%.1f 信頼 -%.1f / 普段の約束 機嫌 -%.1f 信頼 -%.1f): OK" % (fav + plain))

        # ---- 7. 相手の都合で日がずれる / 取りやめになる (まれ)
        AP.FAVOR_RESCHED = 1.0
        seen = set()
        for _ in range(20):
            f, x = offer("furniture")
            x["ask"] = False
            A.answer(x["id"], True, now)
            x["t"] = now + 2 * 3600
            A.live(now)
            seen.add(x["status"])
            if {"offered", "cancelled"} <= seen:
                break
        AP.FAVOR_RESCHED = 0.04
        assert seen <= {"offered", "cancelled"} and seen, seen
        print("日がずれる / 取りやめ:", sorted(seen))

        # ---- 8. 以前から頼まれていたもの: 日時のすり合わせで答えられるように (都合を聞かれている形)
        old = {"id": "fold", "cid": cid, "label": "大掃除の手伝い", "h": 3.0, "tire": 20, "t": now, "until": now + 86400}
        E.favors().append(old)
        assert E.migrate_favors(now) == 1 and old.get("appoint")
        x = A.find(old["appoint"])
        assert x["status"] == "offered" and x["ask"] and old["kind"] == "clean"
        assert any("答えられるようになった" in it["text"] for it in C.load(cid)["items"])
        assert E.migrate_favors(now) == 0, "二度は置き換えない"
        # 稼ぎ方の「頼まれごと」は, 約束の状態を出す (トークの約束の欄へ案内)
        v = E.view(now)
        row = next(r for r in v["favors"] if r["id"] == "fold")
        assert row["appoint"] == x["id"] and "都合" in row["status_label"]
        try:
            E.favor_answer("fold", True, now)
            raise AssertionError("日時なしで引き受けられた")
        except ValueError:
            pass
        print("以前の頼まれごと・稼ぎ方の表示:", row["status_label"])

        # ---- 9. 閉じていた間の約束 (行動パターンの予定と同じ): 自動でひと通り済ませる
        f, x = offer("carry")
        x["ask"] = False
        A.answer(x["id"], True, now)
        txt = app.offline._appoint(x["id"], now)
        assert x["status"] == "met" and f not in E.favors() and "終えた" in txt, txt
        # ---- 10. そばにいるときは対面で頼まれる (記録にも残る)
        B.set_stage(cid, "live")
        app.presence.declare("none", now)
        n0 = len(app.log(cid))
        f, x = offer("clean")
        assert len(app.log(cid)) == n0 + 1 and app.log(cid)[-1]["action_name"] == "頼まれごと", app.log(cid)[-1]
        print("閉じていた間・対面で頼まれる: OK |", app.log(cid)[-1]["text"])
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
