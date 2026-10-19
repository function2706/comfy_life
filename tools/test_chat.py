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
        app.set_params({"mood": 30}, cid)
        assert "もういい" in send("apology") and not L.dominant(st, time.time(), "bad")
        L.add_reason(st, "event", "bad", "電車に傘を忘れた", time.time(), told=False)
        assert "傘を忘れた" in send("ask_how", mood=60), "近況を聞くと, まだ話していない出来事を話す"
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
        night = app.phase_at
        app.phase_at = lambda dt: {"id": "midnight", "label": "深夜", "pos": "", "neg": ""}
        assert "こんな時間" in send("smalltalk", mood=60), "夜中は迷惑"
        app.phase_at = night
        print("kinds x situations: OK")

        # ---- 3. 会おう → 会う約束. そのあいだのお出かけの誘いは, 好感度が低めでも断られない
        for _ in range(10):
            if "会いましょう" in (send("invite", affection=50, mood=70) or ""):
                break
        assert st.get("date_promise", 0) > time.time() and any(x["who"] == "sys" and "約束" in x["text"] for x in C.thread(cid)["items"])
        assert C.thread(cid)["promise"]
        app.set_params({"affection": 20}, cid)
        st["cooldowns"] = {}
        app.act("cafe")
        assert B.mode(cid) == "meet" and "date_promise" not in st, "約束していたので, 会えた"
        app.act("go_home")
        print("invite -> promise: OK")

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
        assert e and C.thread(cid)["items"][-1]["who"] == "her", "相手から届いたメッセージ"
        assert ctx["apart"]
        lst = C.list_view()
        assert lst[0]["id"] == cid and lst[0]["unread"] >= 1
        print("calls / approaches: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
