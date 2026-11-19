"""「話したい」(core/hima.py) と, 返し忘れ (engine._forgot) の確認 (一時データ, 画像生成なし).

- 判定: 状態しだいで弾む / ふつう / 乗らない. よい状態でも必ず弾むわけではなく, 悪い状態でも必ず外れるわけではない.
  同じ日に続けると乗りにくい. 日が変われば戻る.
- 会って (コマンド talk) × 結果 × 仲 (近い / 浅い) × 機嫌: 選ばれるセリフが結果と食い違わない. 断られたら結果の効き目なし.
- メッセージ・電話 (smalltalk): 結果 → 返事の鍵. 乗らないときは一言を返す (近い仲ははっきり, 浅い仲は取り繕う). 電話の様子も結果に合う.
- 弾んだときの好き・苦手: 「知っていること」に残り, 同じことは二度言わない.
- 返事をしない (既読だけ) のは, 機嫌・好感度・ストレス・送りすぎのときだけ. 何もないときは必ず返す.
- 返し忘れ: 読んで既読が付き, 数時間後に謝ってから返す. その間に次のメッセージが届けば, 通知で気づいて早まる.
- 性格別のセリフのキー (talk.*) は, 名前を変えても全部いまのコマンドの反応に当たる.

    python tools/test_hima.py
"""
import glob
import json
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store, hima, react  # noqa: E402
from core.keys import line_keys  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    random.seed(7)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    real_judge, real_close = hima.judge, hima.close
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("話したい")
        C, B = app.chat, app.bonds
        cid = app.settings["active_character"]
        char = app.char(cid)
        st = app.state(cid)
        char["persona_id"] = "teinei"
        now = time.time()

        # ---- 1. 判定の傾き (揺らぎはあるが, 状態で偏る)
        def dist(params, n_today=0, sk=30.0, persona="teinei", k=300):
            char["persona_id"] = persona
            app.life.player_state()["skills"]["talk"] = sk
            out = {"hit": 0, "ok": 0, "flat": 0}
            for _ in range(k):
                st["params"].update(params)
                st["hima"] = {"day": time.strftime("%Y%m%d", time.localtime(now)), "n": n_today}
                st.pop("nori", None)
                out[real_judge(app, char, st, now)[0]] += 1
            char["persona_id"] = "teinei"
            return out
        good = dist({"mood": 85, "boredom": 80, "loneliness": 70, "energy": 70, "sleepiness": 10}, sk=70, persona="genki")
        bad = dist({"mood": 35, "boredom": 10, "loneliness": 10, "energy": 15, "sleepiness": 80}, n_today=3, persona="uchiki")
        mid = dist({"mood": 55, "boredom": 40, "loneliness": 40, "energy": 60, "sleepiness": 20})
        assert good["hit"] > good["flat"] * 4 and good["flat"] + good["ok"] > 0, good       # よくても必ずではない
        assert bad["flat"] > bad["hit"] * 4 and bad["ok"] + bad["hit"] > 0, bad               # 悪くても必ず外れるわけではない
        assert mid["ok"] >= max(mid["hit"], mid["flat"]) * 0.8, mid
        tired = dist({"mood": 55, "boredom": 40, "loneliness": 40, "energy": 60, "sleepiness": 20}, n_today=4)
        assert tired["flat"] > mid["flat"] and tired["hit"] < mid["hit"], (mid, tired)          # 同じ日に続けると乗りにくい
        st["hima"] = {"day": "19990101", "n": 9}
        real_judge(app, char, st, now)
        assert st["hima"]["n"] == 1, "日が変われば数え直す"
        print("judge:", good, bad, mid, tired, "OK")

        # ---- 2. 会って × 結果 × 仲 × 機嫌: セリフが結果に合う
        char["persona_id"] = ""              # 共通のセリフで (性格別は check_persona)
        B.set_stage(cid, "live")
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}
        for res in hima.RESULTS:
            for close in (False, True):
                for mood in (25, 60):
                    hima.judge = lambda a, c, s, t, _r=res: (_r, {})
                    hima.close = lambda a, c, s, _c=close: _c          # 同居 (そばにいる) のまま, 仲の近さだけ切り替える
                    seen = set()
                    for _ in range(40):
                        st["cooldowns"]["talk"] = []
                        app.set_params({"mood": mood, "affection": 50, "sleepiness": 10, "boredom": 30, "energy": 70}, cid)
                        before = dict(st["params"])
                        r = app.act("talk", cid)
                        txt = r["entry"]["text"].split("\n")[0]
                        seen.add(txt)
                        if mood < 35:
                            assert "そっとして" in txt, ("機嫌が悪いと断る", res, txt)
                            assert st["params"]["boredom"] >= before["boredom"] - 0.01, "断られたら, 結果の効き目はない"
                        else:
                            if res != "hit":
                                assert "話は、なかなか止まらなかった" not in txt and "話し込んでいた" not in txt, (res, txt)
                            if res != "flat":
                                assert "話す気分じゃない" not in txt and "続かなかった" not in txt and "沈黙" not in txt, (res, txt)
                            if res == "flat":
                                assert ("話す気分じゃない" in txt) == close or "眠くて" in txt, ("近い仲だけ, はっきり断る", close, txt)
                    assert seen
        hima.judge, hima.close = real_judge, real_close
        B.set_stage(cid, "contact")
        print("face x result x close x mood: OK")

        # ---- 3. メッセージ: 結果 → 返事の鍵
        def reply_key(res, close):
            hima.judge = lambda a, c, s, t, _r=res: (_r, {})
            B.set_stage(cid, "visit" if close else "contact")
            st["contacts"] = []
            app.set_params({"mood": 60, "affection": 50, "stress": 0}, cid)
            k, eff, ex = C.reply(char, st, "smalltalk", now, {"_meta": {}, "_sent": now, "phase": "noon"})
            hima.judge = real_judge
            return k, eff
        assert reply_key("hit", False)[0] == "smalltalk_hit"
        assert reply_key("ok", True)[0] == "smalltalk"
        assert reply_key("flat", False)[0] == "smalltalk_flat"
        assert reply_key("flat", True)[0] == "smalltalk_flat_close"
        assert reply_key("hit", False)[1] == hima.EFFECT["hit"] and reply_key("flat", False)[1] == hima.EFFECT["flat"]
        B.set_stage(cid, "contact")
        print("message keys: OK")

        # ---- 4. 弾んで, 好き・苦手が口に出る (知っていることに残る. 二度は言わない)
        st["known"] = []
        st["params"].update({"trust": 90, "mood": 90})
        tv = app.topics.tastes(char, st)
        n_cand = sum(1 for v in tv.values() if abs(v) >= 0.3)
        said = [hima.settle(app, char, st, "hit", now) for _ in range(200)]
        got = [s for s in said if s]
        assert got and len(got) <= n_cand, (len(got), n_cand)
        assert len({(k["kind"], k["text"]) for k in st["known"]}) == len(got), "同じことは二度言わない"
        assert all(hima.settle(app, char, st, r, now) is None for r in ("ok", "flat") for _ in range(30)), "弾んだときだけ"
        st["known"] = []
        hima.judge = lambda a, c, s, t: ("hit", {})
        random.seed(3)
        txt = None
        for _ in range(60):
            st["known"] = []
            k, eff, ex = C.reply(char, st, "smalltalk", now, {"_meta": {}, "_sent": now, "phase": "noon"})
            if ex.get("said"):
                txt = C.line(char, k, ex)
                break
        hima.judge = real_judge
        assert txt and ex["said"] in txt and txt.endswith("』"), txt
        print("reveal: OK")

        # ---- 5. 電話: 乗らなければ「楽しそう」にはならない
        char["persona_id"] = "teinei"
        for res in ("flat", "hit"):
            hima.judge = lambda a, c, s, t, _r=res: (_r, {})
            hows = set()
            for _ in range(6):
                st.pop("msg_pending", None)
                st["contacts"] = []
                st.pop("call_later_until", None)
                app.set_params({"mood": 70, "affection": 60, "sleepiness": 0, "energy": 70, "stress": 0}, cid)
                st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}
                r = app.phone_call(cid, "smalltalk")
                if r.get("call"):
                    hows.add(r["call"]["how"])
                    assert r["call"]["key"] == ("smalltalk_hit" if res == "hit" else "smalltalk_flat"), r["call"]
            hima.judge = real_judge
            assert hows, res
            if res == "flat":
                assert "楽しそうだった" not in hows and "落ち着いて話してくれた" not in hows, hows
        print("phone: OK")

        # ---- 6. 返事をしないのは, 関門のときだけ
        ctx = {"too_often": False}
        app.set_params({"mood": 60, "affection": 60, "stress": 10}, cid)
        assert app._reply_chance(st, ctx, "smalltalk", now) == 1.0, "何もないのに返さないことは無い"
        for params, c in (({"mood": 20}, {}), ({"affection": 20}, {}), ({"stress": 90}, {}), ({}, {"too_often": True})):
            app.set_params(dict({"mood": 60, "affection": 60, "stress": 10}, **params), cid)
            assert app._reply_chance(st, dict(ctx, **c), "smalltalk", now) < 1.0, params
        print("reply chance: OK")

        # ---- 7. 返し忘れ: 既読 → 数時間後に (謝ってから / 何も言わずに) 返す
        app.set_params({"mood": 60, "affection": 60, "stress": 10}, cid)
        f0, fs0 = app._forgot, app._forgot_sorry

        def forgot_round(sorry, kind="smalltalk"):
            """返し忘れて, 気づいて返すまで. 返ってきた相手の発言 (届いた順) を返す."""
            app._forgot = lambda c, s, k: True
            app._forgot_sorry = lambda c, s, p_, t: sorry
            st.pop("msg_pending", None)
            st["contacts"] = []
            st.pop("nori", None)
            st["phone_until"] = 0
            C.send(cid, kind)
            app._forgot = f0
            pend = st["msg_pending"]
            assert pend.get("forgot"), pend
            pend["due"] = time.time() - 1
            n0 = len(C.load(cid)["items"])
            assert not app.deliver_due(), "まだ返さない"
            items = C.load(cid)["items"]
            assert len(items) == n0 and items[-1]["who"] == "me" and items[-1].get("read_t"), "既読だけ付く"
            assert st["msg_pending"]["due"] - time.time() > 2.5 * 3600
            st["msg_pending"]["due"] = time.time() - 1
            out = app.deliver_due()
            app._forgot_sorry = fs0
            assert out
            return [it for it in C.load(cid)["items"][n0:] if it["who"] == "her"]
        her = forgot_round(True)
        assert her[0]["kind"] == "forgot" and "返したつもり" in her[0]["text"] and len(her) >= 2, her
        assert her[0]["t"] < her[1]["t"] and her[-1].get("sorry") and not her[0].get("sorry"), "謝ったあとの返事に印"
        tg = react.target(app, cid, st, time.time())
        assert tg and tg["tone"] == "sorry_late", tg
        her = forgot_round(False)
        assert all(it["kind"] != "forgot" and not it.get("sorry") for it in her), "謝らないときは, ふつうに返すだけ"
        assert react.target(app, cid, st, time.time())["tone"] != "sorry_late"
        # 返し忘れている間に次のメッセージ: 通知で気づいて, 早まる
        app._forgot = lambda c, s, k: True
        st.pop("msg_pending", None)
        st["contacts"] = []
        st["phone_until"] = 0
        C.send(cid, "smalltalk")
        app._forgot = f0
        st["msg_pending"]["due"] = time.time() - 1
        app.deliver_due()
        assert st["msg_pending"]["due"] - time.time() > 2.5 * 3600
        C.send(cid, "what_doing")
        assert st["msg_pending"]["due"] - time.time() <= 1800 + 1, "次のメッセージで気づく"
        # 返し忘れの見込み: 軽い話だけ, マメな人ほど少ない
        assert not any(app._forgot(char, st, "smalltalk") for _ in range(300)), "テストでは忘れない (testclock)"
        app.FORGET_RATE = engine.App.FORGET_RATE_real
        assert not any(app._forgot(char, st, "consult") for _ in range(300)), "相談は忘れない"
        k = sum(app._forgot(char, st, "smalltalk") for _ in range(3000))
        assert 30 < k < 300, k
        print("forgot: OK")

        # ---- 7b. 謝るかは状況しだい: マメな人・浅い仲・遅れが長いほど謝る
        char["persona_id"] = "teinei"

        def sorry_rate(persona, stage, late_h, k=600):
            char["persona_id"] = persona
            B.set_stage(cid, stage)
            n = sum(app._forgot_sorry(char, st, {"t": now - late_h * 3600}, now) for _ in range(k))
            char["persona_id"] = "teinei"
            return n / float(k)
        hi = sorry_rate("seijitsu", "contact", 7)
        lo = sorry_rate("tenshin", "visit", 3)
        assert hi > lo + 0.25 and lo > 0.05 and hi < 0.99, (hi, lo)
        assert sorry_rate("teinei", "contact", 8) > sorry_rate("teinei", "contact", 3), "遅れが長いほど謝る"
        B.set_stage(cid, "contact")
        print("sorry rate: %.2f / %.2f OK" % (hi, lo))

        # ---- 7c. 謝られたときの返し: 並ぶ種類 x 受け取り方
        assert react.kinds_for("sorry_late")[-2:] == ["re_nevermind", "re_late"]
        assert "re_nevermind" in react.kinds_for("sorry") and "re_late" not in react.kinds_for("sorry"), "遅れていない謝りに「遅いよ」は出ない"
        for tone in ("happy", "down", "question", "notice", "plain", "upset"):
            ks = react.kinds_for(tone)
            assert "re_nevermind" not in ks and "re_late" not in ks, tone
        assert react.TONE_OF["appoint_sorry"] == "sorry"

        def rate(kind, aff, tone="sorry_late", k=400):
            app.set_params({"mood": 60, "affection": aff, "trust": 50}, cid)
            st.pop("nori", None)
            out = {"good": 0, "neutral": 0, "bad": 0}
            for _ in range(k):
                out[react.judge(app, char, st, tone, kind)[0]] += 1
            return out
        nv = rate("re_nevermind", 50)
        assert nv["good"] > nv["bad"] * 5 and nv["good"] > 0.5 * sum(nv.values()), nv
        gl = rate("re_glad", 50)
        assert gl["bad"] > gl["good"], ("謝られて「よかったね」は外れ", gl)
        sk = rate("re_sokka", 50)
        assert sk["good"] < nv["good"] / 3, ("「そっか」は冷たい", sk, nv)
        late_close, late_far = rate("re_late", 85), rate("re_late", 35)
        assert late_close["good"] > late_far["good"] * 2 and late_far["bad"] > late_close["bad"] * 2, ("「遅いよ」は仲しだい", late_close, late_far)
        assert late_close["neutral"] + late_close["bad"] > 0 and late_far["good"] + late_far["neutral"] > 0, ("どちらも確定しない", late_close, late_far)
        # 送って, 相手の返事まで (トークに残る・セリフが返し方と結果に合う)
        for kind in ("re_nevermind", "re_late"):
            her = forgot_round(True)
            app.set_params({"mood": 60, "affection": 60}, cid)
            st["contacts"] = []
            st.pop("msg_pending", None)
            st["phone_until"] = 0
            C.send(cid, kind)
            pend = st["msg_pending"]
            assert pend["kind"] == kind and pend["meta"]["to"]["tone"] == "sorry_late", pend
            pend["due"], pend["reply"] = time.time() - 1, True
            out = app.deliver_due()
            last = [it for it in C.load(cid)["items"] if it["who"] == "her" and not (it.get("kind") or "").startswith("close_")][-1]     # 切り上げが続くことも
            assert out and last["who"] == "her" and last["kind"].startswith("react_%s_" % kind[3:]), last
        # 謝ったのに返さない: 少し気にする (問いかけ・話と同じ扱い)
        her = forgot_round(True)
        t_msg = C.load(cid)["items"][-1]["t"]
        C.mark_seen(cid)
        st.pop("await_ignored", None)
        st["react_since"] = 0
        m0 = st["params"]["mood"]
        react.ignore_tick(app, char, st, t_msg + 10 * 3600)
        assert st.get("await_ignored") and st["params"]["mood"] < m0, (st.get("await_ignored"), m0, st["params"]["mood"])
        st.pop("await_ignored", None)
        print("sorry replies: OK", nv, late_close, late_far)

        # ---- 8. 性格別のセリフのキー (talk.*) は全部, いまの反応に当たる
        have = set(line_keys(app.action("talk")["reactions"]))
        for p in glob.glob(os.path.join(BASE, "defaults", "personas", "*.json")):
            lines = json.load(open(p, encoding="utf-8")).get("lines") or {}
            miss = [k for k in lines if k.startswith("talk.") and k[5:] not in have]
            assert not miss, (os.path.basename(p), miss)
        print("persona keys: OK")
        print("ALL OK")
    finally:
        hima.judge, hima.close = real_judge, real_close
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
