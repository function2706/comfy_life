"""誕生日と記念日 (core/anniv.py): 誕生日の決まり方・聞く (険悪なら教えない)・記念日 (年・月)・期待・その日の受け止め・
遅れたおめでとう・メッセージで・相手から言ってくる・あなたの誕生日・カレンダーのメモ・予約・以前のセーブ.

    python tools/test_anniv.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import anniv as AN, engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(51)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("記念日")
        N = app.anniv
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        today = datetime.now().date()

        # ---- 1. 以前のセーブ: はじめて使うとき, ログから段階が変わった日を拾う (家に行けるようになった日 = 受け入れられた「家に行ってもいい？」)
        t_visit = time.time() - 400 * 86400
        app.log(cid).append({"id": "x1", "t": t_visit, "action": "ask_visit", "text": "いいですよ"})
        app.log(cid).append({"id": "x0", "t": t_visit - 30 * 86400, "action": "talk", "text": "…"})
        app.bonds.rec()["bonds"][cid] = {"stage": "visit", "t": t_visit}
        app.life.player_state().pop("anniv_v1", None)
        N.ps()
        h = N.hist(cid)
        assert abs(h["visit"] - t_visit) < 1 and h["contact"] <= t_visit - 30 * 86400 + 1, h
        print("以前の記録から記念日を拾う: OK", {k: datetime.fromtimestamp(v).date().isoformat() for k, v in h.items()})

        # 段階が変わると, その日が残る
        app.bonds.set_stage(cid, "live")
        assert "live" in N.hist(cid) and "visit" in N.hist(cid)
        app.bonds.set_stage(cid, "visit")

        # ---- 2. 誕生日: キャラごとに決まった日 (起動し直しても同じ). 定義にあればそれ. 2/29 は平年 2/28
        a, b = N.birthday({"id": "a"}), N.birthday({"id": "b"})
        assert a == N.birthday({"id": "a"}) and (a != b or True)
        assert N.birthday({"id": "a", "birthday": "03-14"}) == (3, 14) and N.birthday({"id": "a", "birthday": "13-40"}) == a
        assert AN.same_md((2, 29), date(2027, 2, 28)) and AN.same_md((2, 29), date(2028, 2, 29))
        print("誕生日の決まり方: OK")

        # ---- 3. 聞く: ふつうは教えてくれ, 知っていることに残る. 教えないのはよっぽど険悪なときだけ
        app.bonds.start(cid, "visit")
        app.set_params({"affection": 60, "mood": 60}, cid)
        r = N.say("ask_bday", cid)
        assert "%d月" % N.birthday(char)[0] in r["entry"]["text"] and st.get("bday_known")
        assert any("誕生日は" in k["text"] for k in st.get("known") or [])
        app.set_params({"affection": 10}, cid)
        assert N.reply(char, st, "ask_bday", time.time())[0] == "bday_refuse"
        app.set_params({"affection": 30, "mood": 40}, cid)
        assert N.reply(char, st, "ask_bday", time.time())[0] == "bday_tell"
        print("聞く: OK |", r["entry"]["text"].replace("\n", " "))

        # ---- 4. 記念日: 一周年は多くの人, 月ごとは甘えたがり (か依存度が高い人) だけ
        bd = N.birthday(char)
        day = date(today.year + 1, 1, 15) if bd != (1, 15) else date(today.year + 1, 1, 16)
        N.hist(cid)["live"] = datetime(day.year - 1, day.month, day.day, 12).timestamp()
        N.hist(cid)["visit"] = datetime(day.year, day.month - 1 if day.month > 1 else 12, day.day, 12).timestamp() \
            if day.month > 1 else datetime(day.year - 1, 12, day.day, 12).timestamp()
        char["persona_id"] = "teinei"
        A = app.attach
        A.rec(char, st)["dependence"] = 40.0
        evs = N.events_on(char, st, day)
        assert any(e["what"] == "一緒に住み始めて1年" for e in evs) and not any("か月" in e["what"] for e in evs), evs
        char["persona_id"] = "amaenbo"
        assert any(e["what"] == "家に行けるようになって1か月" for e in N.events_on(char, st, day))
        char["persona_id"] = "teinei"
        print("記念日: OK |", [e["what"] for e in N.events_on(char, st, day)])

        # ---- 5. 期待: 関係が深いほど・好感度が高いほど・気にする性格ほど
        app.set_params({"affection": 80}, cid)
        ev = {"kind": "birthday"}
        app.bonds.set_stage(cid, "live")
        e_live = N.care(char, st, ev)
        app.bonds.set_stage(cid, "contact")
        e_contact = N.care(char, st, ev)
        app.bonds.set_stage(cid, "visit")
        char["persona_id"] = "cool"
        e_cool = N.care(char, st, ev)
        char["persona_id"] = "amaenbo"
        e_amae = N.care(char, st, ev)
        char["persona_id"] = "teinei"
        assert e_live > e_contact * 2 and e_amae > e_cool * 2, (e_live, e_contact, e_amae, e_cool)
        print("期待: OK | 同居 %.2f / 連絡先 %.2f・甘えたがり %.2f / クール %.2f" % (e_live, e_contact, e_amae, e_cool))

        # ---- 6. その日の受け止め: 何もしなければがっかり (教えていたのに忘れたら重く, 知らなかったなら軽く). 祝えば喜ぶ
        app.bonds.set_stage(cid, "live")
        char["birthday"] = "%02d-%02d" % (today.month, today.day)

        def day_of(known, done):
            app.set_params({"affection": 80, "mood": 60, "trust": 60}, cid)
            st["bday_known"] = known
            st["reasons"] = []
            st.pop("celeb", None)
            N.daily(char, st, time.time())
            assert st["celeb"]["E"] > 0.5
            for w in done:
                N.mark(char, st, w)
            m0 = st["params"]["mood"]
            N._evaluate(char, st, st["celeb"], time.time())
            return st["celeb_last"]["out"], st["params"]["mood"] - m0
        out_k, dk = day_of(True, [])
        out_u, du = day_of(False, [])
        assert out_k == "bad" and dk < du <= 0, (dk, du)
        assert any(r.get("action") == "_anniv_forgot" for r in st["reasons"])
        out_g, dg = day_of(True, ["congrats", "met", "gift"])
        assert out_g == "good" and dg > 0
        print("その日の受け止め: OK | 教えていたのに忘れた %.1f / 知らなかった %.1f / 祝った %+.1f" % (dk, du, dg))

        # 遅れたおめでとう (3 日以内): 少し戻り, 忘れられていた理由は和らぐ
        day_of(True, [])
        st.pop("celeb", None)
        key, eff, _ = N.reply(char, st, "congrats", time.time() + 86400)
        assert key == "congrats_late" and all(r.get("resolved") for r in st["reasons"] if r.get("action") == "_anniv_forgot")
        assert N.reply(char, st, "congrats", time.time() + 86400)[0] == "congrats_what"       # 2 度目は「何が？」
        print("遅れたおめでとう: OK")

        # ---- 7. メッセージで: 送った日で見る (読むのが翌日でも当日のおめでとう)
        app.bonds.set_stage(cid, "contact")
        app.bonds.end()                          # 遊びに来ていたのが終わって, 離れている
        st.pop("celeb", None)
        N.daily(char, st, time.time())
        st["msg_pending"] = None
        st["contacts"] = []
        app.chat.send(cid, "congrats")
        st["msg_pending"].update(due=time.time() - 1, reply=True)
        out = app.deliver_due()
        assert out and "覚えて" in out[0]["text"] and out[0]["text"].startswith("📱『") and st["celeb"]["done"].get("congrats")
        print("メッセージで: OK |", out[0]["text"])

        # ---- 8. 相手から言ってくる (予定していたことを届ける)
        st["anniv_msgs"] = [{"at": time.time() - 10, "key": "anniv_her", "extra": {"what": "一緒に住み始めて1年"}}]
        st.pop("celeb", None)
        app.tick(cid)
        assert any(i.get("kind") == "anniv_her" for i in app.chat.load(cid)["items"])
        print("相手から言ってくる: OK")

        # ---- 9. あなたの誕生日: 伝えた相手だけが知っていて, 覚えていれば祝ってくれる
        try:
            N.say("tell_bday", cid, phone=True)
            raise AssertionError("自分の誕生日が無いのに伝えられた")
        except ValueError:
            pass
        app.save_settings({"player": dict(app.settings.get("player") or {}, birthday="%02d-%02d" % (today.month, today.day))})
        assert N.my_birthday() == (today.month, today.day)
        assert N.reply(char, st, "tell_bday", time.time())[0] == "bday_noted" and st["knows_my_bday"]
        app.set_params({"affection": 90}, cid)
        A.rec(char, st)["devotion"] = 90.0
        got = 0
        for _ in range(40):
            st["anniv_msgs"] = []
            st.pop("celeb", None)
            N.daily(char, st, time.time())
            got += any(m["key"] == "your_bday" for m in st["anniv_msgs"])
        st["knows_my_bday"] = False
        st["anniv_msgs"] = []
        N.daily(char, st, time.time())
        assert 25 <= got < 40 and not any(m["key"] == "your_bday" for m in st["anniv_msgs"]), got
        print("あなたの誕生日: OK | 献身的で仲がいい相手が覚えていた %d / 40" % got)

        # ---- 10. カレンダーのメモ (毎年くり返す)
        m = N.memo_add(today.isoformat(), "ひなの誕生日", True)
        assert m in N.memos_on(today) and m in N.memos_on(date(today.year + 1, today.month, today.day if not (today.month == 2 and today.day == 29) else 28))
        cal = app.calview.month() if hasattr(app, "calview") else None
        if cal:
            assert any(e["kind"] == "memo" for e in cal["days"].get(today.isoformat(), []))
        N.memo_del(m["id"])
        assert not N.memos_on(today)
        print("カレンダーのメモ: OK")

        # ---- 11. 予約: 金曜・土曜の夜の当日はいっぱいになりやすく, 平日の昼を前もってなら取りやすい
        now = time.time()
        d0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        fri = d0 + timedelta(days=(4 - d0.weekday()) % 7)
        tue = d0 + timedelta(days=7 + (1 - d0.weekday()) % 7)
        rnd = random.Random(3)
        hot = sum(AN.reserve_full((fri + timedelta(hours=19)).timestamp(), (fri + timedelta(hours=10)).timestamp(), rnd) for _ in range(400)) / 400.0
        cool = sum(AN.reserve_full((tue + timedelta(hours=12)).timestamp(), now, rnd) for _ in range(400)) / 400.0
        assert hot > 0.5 and cool < 0.05, (hot, cool)
        print("予約: OK | 当日の金曜の夜 %.2f / 前もっての平日の昼 %.2f" % (hot, cool))

        # ---- 12. 使い始める前の日は「忘れていた」にしない
        st.pop("celeb", None)
        st["reasons"] = []
        N.daily(char, st, app.life.player_state()["anniv_since"] - 86400)
        assert "celeb" not in st
        print("使い始める前の日: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
