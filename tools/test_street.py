"""出先でのばったりの確認: 顔なじみ (よく行く場所と時間帯), 段階的に知り合う, 声をかけられたときの反応と時間切れの無難な対応,
仕事中は同僚だけ (一時データ, 画像生成なし).

    python tools/test_street.py
"""
import collections
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, street  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)     # 時刻を昼に固定 (流す時刻に左右されないように)


def main():
    random.seed(17)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("街")
        S = app.street
        park = {"kind": "out", "place": "park", "with": None}

        # ---- 1. 習慣は人ごとに決まっていて, ワールドが違っても同じ
        c = {"name": "あおい", "pos": "1girl, solo, blue hair"}
        assert street.haunts_of(c) == street.haunts_of(dict(c)) and len(street.haunts_of(c)) >= 2

        # ---- 2. 初めての人: 新しい顔として people に入り, ここに来る習慣を持つ. 返事待ちの間は次は起きない
        r = S.happen(park)
        assert r and r["kind"] in ("call", "sight") and S.pending(), r
        assert S.happen(park) is None, "ばったりの返事待ちのうちは, 次は起きない"
        ppl = S.people()
        # ---- 3. 返事をしないまま時間が過ぎる: 声をかけられたなら無難に会釈, 見かけただけなら通り過ぎる
        S.pending()["until"] = time.time() - 1
        typ = S.pending()["type"]
        out = S.live()
        assert out["auto"] and out["choice"] == ("nod" if typ == "call" else "pass") and not S.pending(), out
        assert ("会釈して流した" if typ == "call" else "気づかずに通り過ぎた") in out["text"], out["text"]
        print("timeout:", out["text"].split("\n")[0])

        # ---- 4. 顔なじみ: 同じ場所・同じ時間帯に通えば, 同じ人によく会う
        ppl = S.people()
        reg = {"char": app.encounters.generate(), "stage": 0, "meets": 0, "last": 0, "haunts": [["park", "noon"]],
               "coworker": False, "src": {"type": "new"}}
        ppl["pREG"] = reg
        S.save_people(ppl)
        cnt = collections.Counter()
        for _ in range(60):
            S.happen(park)
            pend = S.pending()
            cnt[pend["who"]] += 1
            S.resolve("pass")
        top = [w for w, _ in cnt.most_common(3)]
        assert cnt["pREG"] >= 8 and all(["park", "noon"] in S.people()[w]["haunts"] for w in top), cnt
        cnt2 = collections.Counter()
        for _ in range(40):
            S.happen({"kind": "out", "place": "station", "with": None})
            cnt2[S.pending()["who"]] += 1
            S.resolve("pass")
        assert cnt2["pREG"] < cnt["pREG"] / 2, "よく行く場所でなければ, あまり会わない"
        print("regulars:", cnt.most_common(3))

        # ---- 5. 段階的に知り合う: 一度では知り合いにならない. 会釈だけでは「会釈する仲」まで. 断ると声をかけられにくくなる
        ppl = S.people()
        ppl["pREG"]["stage"] = 0
        S.save_people(ppl)

        def meet(choice, typ="call"):
            S.rec()["street_pending"] = {"kind": "person", "who": "pREG", "type": typ, "t": time.time(), "until": time.time() + 99,
                                         "where": "公園", "with": None, "name": "x", "text": "", "stage": 0}
            return S.resolve(choice)

        r = meet("chat")
        assert S.people()["pREG"]["stage"] <= 2, "一度では知り合いにならない"
        for _ in range(30):
            meet("nod")
        assert S.people()["pREG"]["stage"] == 2, "会釈だけでは, 会釈する仲より先に進まない"
        steps = 0
        while S.people()["pREG"]["stage"] < 4 and steps < 60:
            meet("chat")
            steps += 1
        assert S.people()["pREG"]["stage"] == 4 and steps >= 2, steps
        enc = app.encounters.pending()
        assert enc and enc.get("pid") == "pREG", "知り合いになったら, 登録するか尋ねる"
        reg_r = app.answer_encounter(True)["registered"]
        assert S.people()["pREG"]["cid"] == reg_r["id"] and reg_r["id"] in app.chars
        r = meet("decline")
        print("staged: OK (%d 回目で知り合い)" % (steps + 1))

        # ---- 6. 登録キャラに声をかけられる: 立ち話すればログに残り, 知り合いなら連絡先を交換することも
        cid = reg_r["id"]
        app.bonds.set_stage(cid, "known")
        exchanged = False
        for _ in range(20):
            S.rec()["street_pending"] = {"kind": "char", "who": cid, "type": "call", "t": time.time(), "until": time.time() + 99,
                                         "where": "公園", "with": None, "name": app.chars[cid]["name"], "text": "", "stage": 4}
            o = S.answer("chat")
            exchanged = exchanged or o["exchanged"]
            if exchanged:
                break
        assert exchanged and app.bonds.stage(cid) == "contact" and "立ち話" in app.log(cid)[-1]["text"]
        try:
            S.answer("chat")
            raise AssertionError("ばったりが無いのに答えられる")
        except ValueError:
            pass
        print("char: OK")

        # ---- 7. 仕事中に会うのは同僚だけ
        work = {"kind": "work", "place": "office", "with": None}
        for _ in range(30):
            S.happen(work)
            p = S.pending()
            if p["kind"] == "person":
                assert S.people()[p["who"]]["coworker"], p
            else:
                assert any(h[0] == "office" for h in street.haunts_of(app.chars[p["who"]])), p
            S.resolve("pass")
        print("coworkers: OK", sum(1 for x in S.people().values() if x.get("coworker")))

        # ---- 8. 外出中の判定から: 起きたら返事待ちになり, 画面に出る
        app.world["outdoor"] = {"rate_out": 1e6}
        app.solo.start("walk", place="park")
        app.presence.rec()["enc_check"] = time.time() - 600
        r = app.outdoor.live()
        v = app.state_view()["street_pending"]
        assert r and v and v["options"] and v["type"] in ("call", "sight"), (r, v)
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
