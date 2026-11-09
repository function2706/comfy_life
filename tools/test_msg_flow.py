"""続けて送ったメッセージのつながり (1.6.0).
- 返事待ちの間に重ねて送った: 読んだときに, 前のメッセージにも順に返す (以前は最新の 1 通だけ). 同じ種類は 1 つ, 3 通まで
  (軽いものから落とす). 切り上げのひとことは最後の返事のあとだけ. 連絡が多すぎるときは, 最新の 1 通への返し方だけ
- 全部に返すか, 最後の 1 通にだけ返すかは, マメさ・機嫌・ノリしだい. 最後が軽いもの (スタンプなど) なら, その前の
  中身のあるメッセージにだけ返して, 最後には触れないことも
- 相手の返事は, どのメッセージへのものかを覚えている. 引用を付けるかはマメさしだい
- 相手から来たメッセージへの返事の返しを待っている間に別のメッセージを送っても, 返事の返しは消えない
- ノリ: 乗っているほど冗談・からかい・軽い返しが通じ, 冷めていると空回りしやすい
- 流れ: 沈んだ話のあとのからかいは外れやすく, 「大丈夫？」は通じる. 不満を言われたあとの甘えは, ごまかしに取られる
(一時データ)

    python tools/test_msg_flow.py
"""
import json
import os
import random
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, react as R, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(3)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("つながり")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        st, char = app.state(cid), app.char(cid)
        C = app.chat
        tol = app.bonds.tolerance
        app.bonds.tolerance = lambda *a, **k: 99.0      # 連絡の多さは, 3 の項目でだけ見る (重ねて送ると, ふつうは多すぎになりやすい)
        all_chance = R.answer_all_chance
        R.answer_all_chance = lambda *a, **k: 1.0          # 1・2 は「一つずつ返す」とき (どちらになるかは 7 で)

        def reset(**params):
            st.pop("msg_pending", None)
            st.pop("nori", None)
            st["approach"] = None
            st["contacts"], st["reasons"], st["stamps"], st["whatdo"] = [], [], [], []
            st["phone_until"] = 0
            app.set_params(dict({"mood": 60, "affection": 60, "trust": 50, "loneliness": 40, "stress": 10}, **params), cid)

        def deliver():
            pend = st["msg_pending"]
            pend["due"], pend["reply"] = time.time() - 1, True
            pend["unread"] = False
            app.deliver_due()

        def hers(since):
            return [x for x in C.load(cid)["items"] if x["who"] == "her" and x["t"] >= since]

        # ---- 1. 重ねて送った分に順に返す. どのメッセージへの返事かを覚えている
        reset()
        t0 = time.time() - 0.001
        C.send(cid, "ask_how")
        C.send(cid, "otsukare")
        C.send(cid, "what_doing")
        assert [x["kind"] for x in st["msg_pending"]["queue"]] == ["ask_how", "otsukare"]
        deliver()
        hs = [x for x in hers(t0) if not x["kind"].startswith("close_")]
        mine = {x["t"]: x["kind"] for x in C.load(cid)["items"] if x["who"] == "me" and x["t"] >= t0}
        got = [mine[x["re"]["t"]] for x in hs]
        assert got == ["ask_how", "otsukare", "what_doing"], (got, [x["kind"] for x in hs])
        assert all(not x["kind"].startswith("close_") for x in hers(t0)[:-1]), "切り上げが途中に入った"
        print("順に返す: OK |", [x["kind"] for x in hs])

        # ---- 2. 同じ種類は 1 つ. 4 通以上なら軽いものから落として 3 通まで
        reset()
        t0 = time.time() - 0.001
        for k in ("greet_morning", "ask_how", "greet_morning", "you_ok", "otsukare", "what_doing"):
            C.send(cid, k)
        deliver()
        hs = [x for x in hers(t0) if not x["kind"].startswith("close_")]
        got = [mine for mine in (C.load(cid)["items"]) if mine["who"] == "me" and mine["t"] >= t0]
        kinds = {x["t"]: x["kind"] for x in got}
        rk = [kinds[x["re"]["t"]] for x in hs]
        assert len(hs) == 3 and rk[-1] == "what_doing" and "ask_how" in rk and "you_ok" in rk, rk
        print("まとめ方: OK |", rk)

        # ---- 7. 全部に返すか, 最後の 1 通にだけか. 最後が軽いなら, その前にだけ返すことも
        R.answer_all_chance = lambda *a, **k: 0.0
        seen = set()
        for _ in range(30):
            reset()
            t0 = time.time() - 0.001
            C.send(cid, "ask_how")
            C.send(cid, "stamp", {"stamp": "like"})
            deliver()
            hs = [x for x in hers(t0) if not x["kind"].startswith("close_")]
            mine = {x["t"]: x["kind"] for x in C.load(cid)["items"] if x["who"] == "me" and x["t"] >= t0}
            got = tuple(mine[x["re"]["t"]] for x in hs if x.get("re"))
            assert got in (("stamp",), ("ask_how",)), got        # どちらか 1 通 (最後の 👍 には触れず, 近況にだけ答えることも)
            seen.add(got)
            if len(seen) == 2:
                break
        assert seen == {("stamp",), ("ask_how",)}, seen
        reset()
        t0 = time.time() - 0.001
        C.send(cid, "ask_how")
        C.send(cid, "what_doing")                 # 最後が中身のあるメッセージ: 最後を飛ばすことはない
        deliver()
        hs = [x for x in hers(t0) if not x["kind"].startswith("close_")]
        assert len(hs) == 1 and hs[0]["kind"] == "what_doing", [x["kind"] for x in hs]
        R.answer_all_chance = all_chance
        rates = {}
        for pid in ("seijitsu", "fushigi"):
            tr = json.load(open(os.path.join(os.path.dirname(HERE), "defaults", "personas", pid + ".json"), encoding="utf-8"))["traits"]
            app.traits = lambda c, tr=tr: tr
            rates[pid] = (R.answer_all_chance(app, char, st, time.time()), R.quote_chance(app, char, st))
        app.traits = engine.App.traits.__get__(app)
        assert rates["seijitsu"][0] > rates["fushigi"][0] + 0.3 and rates["seijitsu"][1] > rates["fushigi"][1] + 0.5, rates
        print("返す範囲・引用: OK | 最後だけ %s | 一つずつ返す・引用 誠実 %.2f/%.2f 不思議さん %.2f/%.2f" % (
            sorted(seen), rates["seijitsu"][0], rates["seijitsu"][1], rates["fushigi"][0], rates["fushigi"][1]))
        R.answer_all_chance = lambda *a, **k: 1.0

        # ---- 8. 引用を付けたかを覚えている (付けない人の返事は, 何への返事かを読み取るしかない)
        for want in (True, False):
            qc = R.quote_chance
            R.quote_chance = lambda *a, **k: 1.0 if want else 0.0
            reset()
            t0 = time.time() - 0.001
            C.send(cid, "ask_how")
            C.send(cid, "what_doing")
            deliver()
            hs = [x for x in hers(t0) if x.get("re")]
            assert hs and all(x["re"]["q"] is want for x in hs), [x["re"] for x in hs]
            R.quote_chance = qc
        print("引用の印: OK")

        # ---- 3. 連絡が多すぎるときは, 最新の 1 通への返し方だけ
        reset()
        app.bonds.tolerance = tol
        st["contacts"] = [time.time() - 60 * i for i in range(40)]
        t0 = time.time() - 0.001
        C.send(cid, "ask_how")
        C.send(cid, "smalltalk")
        deliver()
        assert len([x for x in hers(t0) if not x["kind"].startswith("close_")]) == 1, [x["kind"] for x in hers(t0)]
        print("多すぎるときは 1 通: OK")
        app.bonds.tolerance = lambda *a, **k: 99.0

        # ---- 4. 相手から来たメッセージへの返事の返しは, 別のメッセージを重ねても消えない
        reset()
        st["msg_pending"] = None
        app.force_approach("msg_today", cid)
        t0 = time.time() - 0.001
        C.send(cid, "re_more")
        assert st["msg_pending"]["kind"] == "ap_reply"
        C.send(cid, "ask_how")
        deliver()
        ks = [x for x in hers(t0) if not x["kind"].startswith("close_")]
        assert any(x["kind"] == "approach" for x in ks) and ks[-1]["kind"].startswith("ask_how"), [x["kind"] for x in ks]
        print("働きかけへの返事の返し: OK |", [x["kind"] for x in ks])

        # ---- 5. ノリ: 乗っているほど冗談・軽い返しが通じる
        def rate(kind, tone, nori_v=None, n=400, ok=("good",)):
            got = 0
            for _ in range(n):
                st["params"].update({"mood": 55, "affection": 55, "loneliness": 40})
                if nori_v is None:
                    st.pop("nori", None)
                else:
                    st["nori"] = {"v": nori_v, "t": time.time(), "turns": 3}
                got += R.judge(app, char, st, tone, kind)[0] in ok
            return got / float(n)
        hi, lo = rate("re_lol", "bored", 95), rate("re_lol", "bored", 10)
        assert hi > lo + 0.25, (hi, lo)
        print("ノリ: OK | 退屈な話に「笑」 乗っている %.2f / 冷めている %.2f" % (hi, lo))

        # ---- 6. 流れ: 沈んだ話のあとのからかいは外れやすく, 「大丈夫？」は通じる
        def reply_rate(kind, prev_kind, prev_text, n=60, want=None):
            hit = 0
            for _ in range(n):
                reset(mood=65, affection=70)
                C.add(cid, "her", prev_text, kind=prev_kind)
                t0 = time.time() - 0.001
                C.send(cid, kind)
                deliver()
                k = [x for x in hers(t0) if not x["kind"].startswith("close_")][-1]["kind"]
                hit += k == want
            return hit / float(n)
        t_down = reply_rate("tease", "money_worry", "📱『今月ちょっと苦しくて』", want="tease")
        t_happy = reply_rate("tease", "photo", "📱『見てください、きれいでしょう』", want="tease")
        assert t_happy > t_down + 0.3, (t_happy, t_down)
        ok_down = reply_rate("you_ok", "money_worry", "📱『今月ちょっと苦しくて』", n=20, want="you_ok")
        assert ok_down == 1.0, ok_down
        st["reasons"] = []
        f_up = reply_rate("flirt", "tease_hurt", "📱『……なんでそういうこと言うんですか』", n=20, want="flirt_cold")
        assert f_up == 1.0, f_up
        print("流れ: OK | からかい 沈んだ話のあと %.2f / 楽しい話のあと %.2f | 大丈夫？ %.2f | 不満のあとの甘え → 冷たい %.2f"
              % (t_down, t_happy, ok_down, f_up))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK")


if __name__ == "__main__":
    main()
