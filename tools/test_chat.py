"""メッセージアプリの確認: 種類 × 状況で変わる返信 (時間差・既読・来ないことも), トーク (自分は要約・相手は本文・時刻),
未読の数, 電話や相手からのメッセージも同じトークに, 「会おう」から会う約束 (一時データ, 画像生成なし).

    python tools/test_chat.py
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
    random.seed(61)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("トーク")
        C, B, L = app.chat, app.bonds, app.life
        cid = app.settings["active_character"]
        st = app.state(cid)
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}
        app.char(cid)["persona_id"] = "teinei"

        def send(kind, reply=True, **params):
            st["contacts"] = []
            st.pop("msg_pending", None)
            if params:
                app.set_params(params, cid)
            C.send(cid, kind)
            st["msg_pending"]["due"], st["msg_pending"]["reply"] = time.time() - 1, reply
            out = app.deliver_due()
            return out[0]["text"] if out else None

        # ---- 1. 送る: トークには要約が残り, 返信は時間差 (読んだら既読)
        app.set_params({"affection": 50, "trust": 50, "mood": 60}, cid)
        C.send(cid, "greet_morning")
        th = C.thread(cid)
        assert th["items"][-1]["who"] == "me" and th["items"][-1]["text"] == "（おはようと送った）" and th["waiting"]
        assert not th["items"][-1].get("read_t")
        st["msg_pending"]["due"] = time.time() - 1
        out = app.deliver_due()
        th = C.thread(cid)
        assert out and th["items"][-2].get("read_t") and th["items"][-1]["who"] == "her" and "おはよう" in th["items"][-1]["text"], th["items"][-2:]
        assert C.unread(cid) == 1 and C.unread_total() == 1
        C.mark_seen(cid)
        assert C.unread(cid) == 0
        # 既読だけ付いて, 返事が来ないことも
        assert send("smalltalk", reply=False) is None and C.thread(cid)["items"][-1].get("read_t")
        print("send / read / unread: OK")

        # ---- 2. 種類 x 状況
        assert "急に" in send("flirt", affection=50), "浅い仲で甘えると引かれる"
        B.set_stage(cid, "visit")
        assert "会いたい" in send("flirt", affection=70)
        B.set_stage(cid, "contact")
        assert "何が" in send("apology"), "理由を知らずに謝ると戸惑われる"
        L.add_reason(st, "player", "bad", "ユウさんが約束を忘れていた", time.time(), told=True)
        app.set_params({"mood": 45, "affection": 60, "trust": 60}, cid)
        st["apologies"] = []            # 続けて謝ると「もういいって」になるので, 間をあけたことに (許し方の幅は test_manners)
        g, random.gauss = random.gauss, lambda m, s: 0.0
        assert "もういいですよ" in send("apology") and not L.dominant(st, time.time(), "bad")
        random.gauss = g
        L.add_reason(st, "event", "bad", "電車に傘を忘れた", time.time(), told=False)
        assert "傘を忘れた" in send("ask_how", mood=60), "近況を聞くと, まだ話していない出来事を話す"
        # 近況の中身は性格ごとの言い方 (無ければ共通の「〜んです。」/「特に変わりないですよ。」など)
        t = send("ask_how", mood=60)
        assert any(x in t for x in ("変わりない", "相変わらず", "ぼちぼち")), t
        P = app.personas["teinei"].setdefault("lines", {})
        saved = {k: P.get(k) for k in ("chat.ask_how_news", "chat.ask_how_nothing")}
        P["chat.ask_how_news"], P["chat.ask_how_nothing"] = ["実はね、{tell}の！"], ["なんにもないよー。"]
        L.add_reason(st, "event", "bad", "電車に傘を忘れた", time.time() + 1, told=False)
        assert "実はね、電車に傘を忘れたの！" in send("ask_how", mood=60), "出来事は性格の言い方で"
        assert "なんにもないよー。" in send("ask_how", mood=60), "何もないときも性格の言い方で"
        for k, v in saved.items():
            if v is None:
                P.pop(k, None)
            else:
                P[k] = v
        texts = [send("tease", affection=80, mood=80) for _ in range(6)]
        assert any("からかわないで" in t for t in texts)
        assert "傷つき" in send("tease", affection=30, mood=40), "仲が浅い・機嫌が悪いと, からかいは逆効果"
        for _ in range(4):
            st["contacts"] = [time.time()] * 10                 # 送りすぎ
            st.pop("msg_pending", None)
            C.send(cid, "smalltalk")
            st["contacts"] = [time.time()] * 10
            st["msg_pending"].update(due=time.time() - 1, reply=True)
            r = app.deliver_due()
            if r:
                assert "連絡多く" in r[0]["text"], r
                break
        # 連絡しすぎたことを謝る: 謝るのは「連絡が多い」に数えない. 疲れさせた理由は, 謝れば和らぐ
        assert any(x["tell"].endswith("少し疲れた") for x in L.reasons(st, time.time())), "連絡しすぎは, あなたのせいの理由として残る"
        app.set_params({"mood": 35}, cid)
        n0 = len(st.get("contacts") or [])
        st.pop("msg_pending", None)
        st["apologies"] = []
        C.send(cid, "apology")
        assert len(st.get("contacts") or []) == n0, "謝るメッセージは数えない"
        st["msg_pending"].update(due=time.time() - 1, reply=True)
        r = app.deliver_due()
        assert r and "連絡多く" not in r[0]["text"] and C.thread(cid)["items"][-1]["kind"].startswith("apology"), r
        st["contacts"], st["reasons"] = [], []
        night = app.phase_at
        app.phase_at = lambda dt: {"id": "midnight", "label": "深夜", "pos": "", "neg": ""}
        assert "こんな時間" in send("smalltalk", mood=60), "夜中は迷惑"
        app.phase_at = night
        print("kinds x situations: OK")

        # ---- 3. 会おう → 会おうという話になる. そのあいだに約束を持ちかけると, 受けてもらいやすい
        for _ in range(10):
            if "会いましょう" in (send("invite", affection=50, mood=70) or ""):
                break
        assert st.get("date_promise", 0) > time.time() and any(x["who"] == "sys" and "会おう" in x["text"] for x in C.thread(cid)["items"])
        assert C.thread(cid)["promise"]
        st["override"] = None
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        ok = 0
        for i in range(20):         # 受けてもらえるかは運しだい (半分ほど). 回数を多めに
            st.pop("msg_pending", None)
            st["contacts"] = []
            st["date_promise"] = time.time() + 3600
            app.set_params({"affection": 45, "mood": 60}, cid)
            for y in app.appoint.open_with(cid):
                if y["status"] == "offered":     # 断るときに返ってきた別の日時の案は, 答えずに流す (次の誘いとぶつからないように)
                    y["status"] = "lapsed"
            x = app.appoint.propose(cid, time.time() + (i + 1) * 4 * 3600, "cafe", "cafe")
            st["msg_pending"]["due"] = time.time() - 1
            app.deliver_due()
            if app.appoint.get(x["id"])["status"] == "set":
                ok += 1
                assert "date_promise" not in st
        app.scheduled_scene = sched
        assert ok >= 6, ok
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}
        print("invite -> promise: OK", ok)

        # ---- 4. 電話・相手からのメッセージも同じトークに
        st["override"] = {"activity": "sleep", "label": "睡眠中", "location": "部屋", "until": time.time() + 9e6, "asleep": True}
        st["cooldowns"], st["contacts"] = {}, []
        st.pop("msg_pending", None)
        app.act("call")
        assert C.thread(cid)["items"][-1]["who"] == "sys" and "出なかった" in C.thread(cid)["items"][-1]["text"]
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": time.time() + 9e6}
        ctx = app.context(app.char(cid), st, __import__("datetime").datetime.now())
        st.pop("approach", None)
        st["ap_last"] = {}
        app.set_params({"loneliness": 90, "affection": 80}, cid)
        e = app.presence.fire(app.char(cid), st, time.time(), app.context(app.char(cid), st, __import__("datetime").datetime.now()))
        # 今日のこと・噂が添えられることがある (流す時刻しだい) ので, 最後の 1 件ではなく本文で探す
        assert e and any(it["who"] == "her" and it["text"] == e["text"] for it in C.thread(cid)["items"][-3:]), "相手から届いたメッセージ"
        assert ctx["apart"]
        lst = C.list_view()
        assert lst[0]["id"] == cid and lst[0]["unread"] >= 1
        print("calls / approaches: OK")

        # ---- 5. すぐの返信: 相手がメッセージを送った直後 (まだスマホを見ている) に返すと, すぐ返ってくることがある
        app.set_params({"mood": 70, "affection": 70, "loneliness": 40}, cid)
        assert st.get("phone_until", 0) > time.time(), "送ってきた相手は, しばらくスマホを見ている"
        quick = slow = 0
        for i in range(40):
            st["contacts"] = []
            st.pop("msg_pending", None)
            st["phone_until"], st["phone_turns"] = time.time() + 300, 0
            C.send(cid, "smalltalk")
            if st["msg_pending"]["due"] - time.time() <= 90:
                quick += 1
            else:
                slow += 1
        assert quick and slow, "すぐ返ることが多いが, 必ずではない (%d / %d)" % (quick, slow)
        # すぐ返すと決まれば, 1 分半以内に届き, 届いたらまたしばらくスマホを見ている
        for _ in range(20):
            st["contacts"] = []
            st.pop("msg_pending", None)
            st["phone_until"], st["phone_turns"] = time.time() + 300, 0
            C.send(cid, "thanks")
            if st["msg_pending"].get("quick"):
                break
        pend = st["msg_pending"]
        pend["reply"] = True
        assert app.deliver_due(time.time()) == [], "まだ届かない (数十秒後)"
        out = app.deliver_due(pend["due"] + 1)
        assert out and not out[0]["late"] and st["phone_until"] > pend["due"]
        # 時間がたってから返すと, いつもの時間差
        st["contacts"] = []
        st["phone_until"] = time.time() - 1
        C.send(cid, "smalltalk")
        assert st["msg_pending"]["due"] - time.time() >= 3 * 60 - 1 and not st["msg_pending"]["quick"]
        # 寝ている・手が離せない相手は, スマホを見ていても (直前に送ってきていても) すぐには返さない
        st.pop("msg_pending", None)
        st["phone_until"] = time.time() + 300
        st["override"] = {"activity": "sleep", "label": "睡眠中", "location": "部屋", "until": time.time() + 9e6, "asleep": True}
        C.send(cid, "smalltalk")
        assert not st["msg_pending"]["quick"]
        print("quick replies: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
