"""応じて決まった約束へのお礼 (1.6.0).
相手が出し返した日時・相手からの誘いに, あなたが応じて約束が決まったとき, お礼の心当たりを記録していなかった
(直後に「約束してくれた」とお礼を言うと「え、何がだ？」と返っていた. 11/08 の報告).
- 応じて決まった約束: 「約束してくれた」が効く
- 相手からの誘いなら: 「会おうと言ってくれた」も効く
- 遡及 (一度だけ): 2 日のうちにスマホで応じて決まった約束に, 心当たりを足す
(一時データ)

    python tools/test_appoint_thanks.py
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("約束のお礼")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        A, M = app.appoint, app.manners
        st = app.state(cid)

        def offered(i, **kw):
            x = dict({"id": "x%d" % i, "cid": cid, "t": time.time() + 3 * 86400, "place": "ramen", "do": "ramen",
                      "status": "offered", "made": time.time(), "rounds": 1}, **kw)
            A.all().append(x)
            return x

        # ---- 1. 相手が出し返した日時に応じた → 「約束してくれた」が効く. 「会おうと言ってくれた」は心当たりなし
        st["favors"] = []
        x = offered(1)
        A.answer(x["id"], True)
        assert A.get(x["id"])["status"] == "set"
        k1, _ = M.thanks_pick(st, time.time() + 60, "appoint", app.char(cid))
        k2, _ = M.thanks_pick(st, time.time() + 60, "invite", app.char(cid))
        assert k1 == "thanks" and k2 == "thanks_what", (k1, k2)
        print("出し返しに応じた: OK | 約束してくれた → %s / 会おうと言ってくれた → %s" % (k1, k2))

        # ---- 2. 相手からの誘いに応じた → 両方効く
        st["favors"] = []
        x = offered(2, by="her", rounds=0)
        A.answer(x["id"], True)
        k1, _ = M.thanks_pick(st, time.time() + 60, "appoint", app.char(cid))
        k2, _ = M.thanks_pick(st, time.time() + 60, "invite", app.char(cid))
        assert k1 == "thanks" and k2 == "thanks", (k1, k2)
        print("誘いに応じた: OK | 約束してくれた → %s / 会おうと言ってくれた → %s" % (k1, k2))

        # ---- 3. 断ったら心当たりはない
        st["favors"] = []
        x = offered(3)
        A.answer(x["id"], False)
        k1, _ = M.thanks_pick(st, time.time() + 60, "appoint", app.char(cid))
        assert k1 == "thanks_what", k1
        print("断った: OK")

        # ---- 4. 遡及: 心当たりの無い, 応じて決まった約束 (1 時間前と 3 日前) → 1 時間前の分だけ足す. 二度目はしない
        st["favors"] = []
        now = time.time()
        app.chat.add(cid, "me", "（11/11（水） 19:00、ラーメン屋の約束をした）", kind="appoint", t=now - 3600)
        app.chat.add(cid, "me", "（11/02（月） 19:00、カフェの約束をした）", kind="appoint", t=now - 3 * 86400)
        app.save_state(cid)
        app.life.player_state().setdefault("fix_comp", {}).pop("appoint_favor", None)
        n = app.appoint_favor_comp(now)
        st = app.state(cid)
        ts = [f["t"] for f in st.get("favors") or [] if f["what"] == "appoint"]
        assert n >= 1 and any(abs(t - (now - 3600)) < 1 for t in ts) and not any(t < now - 2 * 86400 for t in ts), (n, ts)
        k1, _ = M.thanks_pick(st, now, "appoint", app.char(cid))
        assert k1 == "thanks", k1
        st["favors"] = []
        assert app.appoint_favor_comp(now) == 0, "二度目も足した"
        print("遡及: OK | 足した %d 件（1 時間前の分は入り、3 日前の分は足さない）" % n)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK")


if __name__ == "__main__":
    main()
