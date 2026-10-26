"""以前のセーブ (core/manners.py より前に記録された状態) でも, 新しい謝罪の判定がそのまま効くか (一時データ, 画像生成なし).

以前の「連絡が多くて、少し疲れた」(action "_too_often") の理由・返信待ちのメッセージ (meta なし)・action の無い古い理由があり,
新しい欄 (apologies・apology_last・favors・greets・greet_days・stamps・whatdo・seen_down・call_ok_until) が無い状態から:
謝る → 許し方の判定 / 「謝るなら態度で」の解消 / 謝りすぎ / 「謝ったばかりなのに」/ その場で謝る が, キーが無くて落ちず,
古い理由が「今さら？」や「何度目か」の判定で不当に扱われないこと.

    python tools/test_manners_oldsave.py
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

fix_noon(engine)

NEW_KEYS = ("apologies", "apology_last", "favors", "greets", "greet_days", "greet_miss", "stamps", "whatdo", "seen_down",
            "call_ok_until", "thanks_rejudged", "rejudge_noted")


def old_state(app, cid, now, pending=None, extra_reasons=()):
    """以前の形の状態を作って保存し, 読み直す (新しい欄は無い)."""
    st = app.state(cid)
    app.chat.save(cid, {"seen_t": 0, "items": []})
    for k in NEW_KEYS:
        st.pop(k, None)
    st["reasons"] = [
        # 以前の連絡しすぎ (同じ理由が続いてまとめられ, 効き目が足し合わさっている)
        {"kind": "player", "mood": "bad", "tell": "ユウさんからの連絡が多くて、少し疲れた", "t": now - 3600, "told": True,
         "delta": -4.0, "resolved": False, "action": "_too_often"},
    ] + list(extra_reasons)
    st["contacts"] = [now - 3600 - i * 600 for i in range(8)]
    st["params"].update(mood=50, affection=55, trust=55)
    if pending:
        st["msg_pending"] = pending
    else:
        st.pop("msg_pending", None)
    app.save_state(cid)
    app2 = engine.App()                      # 読み直す (別の PC で pull して起動したのと同じ)
    return app2, app2.state(cid)


def main():
    random.seed(3)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("以前のセーブ")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        app.state(cid)["override"] = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}
        app.save_state(cid)
        now = time.time()

        # ---- 1. 以前に送った「ごめんね」が返信待ち (meta なし) のまま: 新しい判定で返ってくる
        pend = {"aid": "message", "t": now - 600, "due": now - 1, "reply": True, "count": 1, "kind": "apology"}
        app, st = old_state(app, cid, now, pend)
        r = app.deliver_due()
        it = app.chat.thread(cid)["items"][-1]
        assert r and it["kind"] in ("apology", "apology_half", "apology_deeds", "apology_refuse"), it
        assert st["apologies"] and st["apology_last"]["action"] == "_too_often"
        print("以前の返信待ちの「ごめんね」:", it["kind"], it["text"])

        # ---- 2. 以前の連絡しすぎ (いま効いている) は「今さら？」にならない. 許し方の割合も新しいセーブと同じ
        outs = {}
        for _ in range(300):
            app, st = old_state(app, cid, now) if not outs else (app, st)
            st["reasons"][0]["resolved"] = False
            st["reasons"][0].pop("half", None)
            st["reasons"][0].pop("deeds", None)
            st.pop("apologies", None)
            o = app.manners.apology(app.char(cid), st, now)["out"]
            outs[o] = outs.get(o, 0) + 1
        assert "late" not in outs and outs.get("quick", 0) > 150, outs
        print("以前の連絡しすぎを謝る (300 回):", outs)

        # ---- 3. 古い理由で「何度目か」が不当に増えない: action の無い古い理由・2 週間より前の同じ失敗は数えない
        old_plain = [{"kind": "player", "mood": "bad", "tell": "からかわれた%d" % i, "t": now - 86400 * (i + 1), "told": True,
                      "delta": -4.0, "resolved": True} for i in range(6)]
        long_ago = [{"kind": "player", "mood": "bad", "tell": "ユウさんからの連絡が多くて、少し疲れた", "t": now - 86400 * (20 + i),
                     "told": True, "delta": -4.0, "resolved": True, "action": "_too_often"} for i in range(5)]
        app, st = old_state(app, cid, now, extra_reasons=old_plain + long_ago)
        random.gauss, g = (lambda m, s: 0.0), random.gauss
        v = app.manners.apology(app.char(cid), st, now)
        base = 0.75 - 4.0 / 25 + (55 - 50) / 250.0 + (55 - 50) / 300.0 - 0.8 * (float(app.traits(app.char(cid)).get("grudge", 1)) - 1)
        assert abs(v["s"] - base) < 1e-6, (v["s"], base)
        # action の無い古い理由を謝っても, ほかの action の無い理由とまとめて数えない
        plain_now = {"kind": "player", "mood": "bad", "tell": "以前のこと", "t": now - 1800, "told": True, "delta": -6.0, "resolved": False}
        app, st = old_state(app, cid, now, extra_reasons=old_plain + [plain_now])
        st["reasons"][0]["resolved"] = True
        v = app.manners.apology(app.char(cid), st, now)
        assert v["r"]["tell"] == "以前のこと" and abs(v["s"] - (base - 2.0 / 25)) < 1e-6, v
        random.gauss = g
        print("何度目か: 古い理由は数えない OK")

        # ---- 4. 半日より前の大きな理由があっても, いま効いている理由を先に謝る (「今さら？」は, いま効いている理由が無いときだけ)
        older = {"kind": "player", "mood": "bad", "tell": "約束を忘れられた", "t": now - 30 * 3600, "told": True, "delta": -12.0,
                 "resolved": False, "action": "_missed"}
        app, st = old_state(app, cid, now, extra_reasons=[older])
        v = app.manners.apology(app.char(cid), st, now)
        assert v["r"]["action"] == "_too_often" and v["out"] != "late", v["out"]
        st["reasons"][0]["resolved"] = True
        v = app.manners.apology(app.char(cid), st, now)
        assert v["out"] == "late" and v["r"]["action"] == "_missed"
        print("今さら？: いま効いている理由が先 OK")

        # ---- 5. 「謝るなら態度で」→ 連絡を控えると消える (以前の contacts のまま)
        app, st = old_state(app, cid, now)
        r = st["reasons"][0]
        app.manners.apply_apology(app.char(cid), st, {"out": "deeds", "r": r}, now)
        app.manners.settle(app.char(cid), st, now + 9 * 3600)
        assert r["resolved"], "連絡を控えたら消えた"
        print("態度で → 連絡を控えて解消: OK")

        # ---- 6. 謝りすぎ / 謝ったばかりなのに (以前の記録が無い状態から)
        app, st = old_state(app, cid, now)
        keys = []
        for i in range(3):
            k, _, _ = app.chat.reply(app.char(cid), st, "apology", now + i * 600, {"_meta": {}})
            keys.append(k)
        assert keys[1] == "apology_enough" and keys[2] == "apology_irritated", keys
        app, st = old_state(app, cid, now)
        random.gauss, g = (lambda m, s: 0.0), random.gauss
        k0, _, _ = app.chat.reply(app.char(cid), st, "apology", now, {})
        random.gauss = g
        k, eff, _ = app.chat.reply(app.char(cid), st, "smalltalk", now + 3600, {"too_often": True})
        assert k0 == "apology" and k == "too_often_again" and eff["mood"] <= -5, (k0, k)
        print("謝りすぎ・謝ったばかりなのに:", keys, k)

        # ---- 7. その場で謝る・お礼・あいさつ・スタンプも, 新しい欄が無い状態から落ちない
        app, st = old_state(app, cid, now)
        app.bonds.set_stage(cid, "live")
        st["cooldowns"], st["override"] = {}, None
        e = app.act("apologize", cid)["entry"]
        assert e["text"] and st["apologies"]
        app, st = old_state(app, cid, now)
        for kind in ("thanks", "greet_morning", "greet_night", "stamp", "may_call", "otsukare", "you_ok", "what_doing", "nudge"):
            meta = app.manners.on_send(app.char(cid), st, kind, now)
            app.chat.reply(app.char(cid), st, kind, now, {"_meta": meta})
        app.manners.settle(app.char(cid), st, now + 12 * 3600)
        print("その場で謝る:", e["text"])

        # ---- 8. この扱いより前に記録された謝罪 (apology_last に s・thanked が無い) のあとのお礼も, 謝罪の結果しだい
        for out, want in (("quick", "thanks"), ("late", "thanks"), ("half", None), ("deeds", "thanks_unforgiven"),
                          ("refuse", "thanks_unforgiven")):
            app, st = old_state(app, cid, now)
            st["apology_last"] = {"t": now - 3600, "action": "_too_often", "out": out}
            app.save_state(cid)
            k, _, _ = app.chat.reply(app.char(cid), st, "thanks", now, {"_meta": {}})
            assert (k in ("thanks", "thanks_not_yet")) if want is None else k == want, (out, k)
        app, st = old_state(app, cid, now)          # 謝罪の記録が無い (欄が無い) なら, 今までどおり
        assert app.chat.reply(app.char(cid), st, "thanks", now, {"_meta": {}})[0] == "thanks_what"
        print("以前の謝罪の記録のあとのお礼: OK")

        # ---- 9. pull する前に送ったお礼: 返事待ちのままなら, 新しい判定で返事が届く
        for out, want in (("quick", "thanks"), ("refuse", "thanks_unforgiven")):
            pend = {"aid": "message", "t": now - 300, "due": now - 1, "reply": True, "count": 1, "kind": "thanks"}
            app, st = old_state(app, cid, now, pend)
            st["apology_last"] = {"t": now - 3600, "action": "_too_often", "out": out}
            app.save_state(cid)
            app.deliver_due()
            assert app.chat.thread(cid)["items"][-1]["kind"] == want, (out, app.chat.thread(cid)["items"][-1])
        # すでに以前の判定で「え、何が？」と返っていたら: 起動したとき一度だけ当て直す (文面はそのまま)
        for out, sign in (("quick", 1), ("refuse", -1)):
            app, st = old_state(app, cid, now)
            st["apology_last"] = {"t": now - 3600, "action": "_too_often", "out": out}
            st["params"]["mood"] = 50
            app.chat.add(cid, "me", "（お礼を言った）", kind="thanks", t=now - 1800)
            app.chat.add(cid, "her", "📱『え、何がですか？』", kind="thanks_what", t=now - 1700)
            app.save_state(cid)
            app = engine.App()                   # 起動
            st = app.state(cid)
            m1 = st["params"]["mood"]
            assert (m1 - 50) * sign > 0 and st["thanks_rejudged"], (out, m1)
            its = app.chat.thread(cid)["items"]
            assert [x for x in its if x.get("kind") == "thanks_what"][-1]["text"] == "📱『え、何がですか？』", "トークの文面は書き換えない"
            assert its[-1]["kind"] == "rejudge" and "受け止め直した" in its[-1]["text"], its[-1]       # 当て直したことが分かる
            app = engine.App()                   # もう一度起動しても二重に当てない
            assert app.state(cid)["params"]["mood"] == m1
        # 謝罪より前の「何が？」・1 日より後の「何が？」は当て直さない
        app, st = old_state(app, cid, now)
        st["apology_last"] = {"t": now - 3600, "action": "_too_often", "out": "quick"}
        st["params"]["mood"] = 50
        app.chat.add(cid, "her", "📱『え、何がですか？』", kind="thanks_what", t=now - 7200)
        app.save_state(cid)
        app = engine.App()
        assert app.state(cid)["params"]["mood"] == 50
        print("pull する前のお礼 (返事待ち・すでに「何が？」): OK")

        # ---- 10. 許してもらった直後のお礼に, 以前の判定で「謝ったばかりなのに」「連絡多くない？」が返っていた: 起動したとき当て直す
        for kind, eff in (("too_often_again", -5), ("too_often", -2)):
            app, st = old_state(app, cid, now)
            t0 = now - 3600
            st["apology_last"] = {"t": t0, "action": "_too_often", "out": "broken" if kind == "too_often_again" else "quick"}
            st["params"]["mood"] = 50 + eff
            st["contacts"] = [t0 + 600]
            st["reasons"] = [{"kind": "player", "mood": "bad", "tell": "連絡", "t": t0 + 900, "told": True, "delta": -4.0,
                              "action": "_too_often"}]
            app.chat.add(cid, "her", "📱『……うん、もういいですよ』", kind="apology", t=t0)
            app.chat.add(cid, "me", "（お礼を言った）", kind="thanks", t=t0 + 600)
            app.chat.add(cid, "her", "📱『……謝ったばかりなのに』", kind=kind, t=t0 + 900)
            app.save_state(cid)
            app = engine.App()                   # 起動
            st = app.state(cid)
            m1 = st["params"]["mood"]
            assert m1 > 50, (kind, m1)           # 下がった分が戻り, お礼として小さく効く
            assert st["apology_last"]["out"] == "quick" and st["apology_last"].get("grace_used"), st["apology_last"]
            assert all(r.get("resolved") for r in st["reasons"]) and not st["contacts"], (st["reasons"], st["contacts"])
            its = app.chat.thread(cid)["items"]
            assert [x for x in its if x.get("kind") == kind][-1]["text"] == "📱『……謝ったばかりなのに』", "トークの文面は書き換えない"
            assert its[-1]["kind"] == "rejudge" and "機嫌 +" in its[-1]["text"], its[-1]
            print("トークの知らせ:", its[-1]["text"])
            app = engine.App()                   # もう一度起動しても二重に当てない (知らせも出ない)
            assert app.state(cid)["params"]["mood"] == m1
            assert sum(1 for x in app.chat.thread(cid)["items"] if x.get("kind") == "rejudge") == 1
        # 知らせを出す前の版で当て直し済みだった: 起動したとき, 済んだことだけ一度知らせる
        app, st = old_state(app, cid, now)
        st["apology_last"] = {"t": now - 3600, "action": "_too_often", "out": "quick", "grace_used": True}
        st["thanks_rejudged"] = [now - 1700]
        app.save_state(cid)
        app = engine.App()
        its = app.chat.thread(cid)["items"]
        assert its[-1]["kind"] == "rejudge" and "済み" in its[-1]["text"], its[-1]
        app = engine.App()
        assert sum(1 for x in app.chat.thread(cid)["items"] if x.get("kind") == "rejudge") == 1
        print("pull する前のお礼 (すでに「連絡多い」): OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
