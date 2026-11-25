"""F13: 目の前にいる相手からは, スマホで返事が来ない (一時データ).
デート中・家に来ている間に返事の期限が来ても届かず, 既読も付かない. 別れたら届く. 一日を越えたら消える.
別の相手からの返事は, デート中でも届く. 手伝いのお礼の催促も, 目の前にいる間は送ってこない.

    python tools/test_deliver_together.py
"""
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def hers(app, cid):
    return [x for x in app.chat.load(cid)["items"] if x["who"] == "her"]


def pend(app, cid, back=0):
    st = app.state(cid)
    st.pop("msg_pending", None)
    st["contacts"] = []
    app.chat.send(cid, "may_call")
    st["msg_pending"]["due"] = time.time() - 1
    st["msg_pending"]["t"] = time.time() - back
    st["msg_pending"]["reply"] = True
    st["msg_pending"].pop("forgot", None)
    st["msg_pending"].pop("unread", None)
    app.save_state(cid)


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("返信")
        a = app.settings["active_character"]
        b = app.new_character("もう一人")["id"]
        for cid in [a] + ([b] if b else []):
            app.bonds.set_stage(cid, "contact")
            st = app.state(cid)
            st["override"] = {"activity": "relax", "label": "くつろいでいる", "location": "自宅", "until": time.time() + 9e6}
            app.save_state(cid)
        for mode in ("meet", "visit", "guest"):
            pend(app, a)
            if b:
                pend(app, b)
            n0 = len(hers(app, a))
            nb = len(hers(app, b)) if b else 0
            app.bonds.start(a, mode)
            app.deliver_due()
            assert len(hers(app, a)) == n0, (mode, "一緒にいる相手から返事が来た", hers(app, a)[-1:])
            assert app.state(a).get("msg_pending"), (mode, "持ち越していない")
            assert not app.chat.load(a)["items"][-1].get("read_t") or app.chat.load(a)["items"][-1]["who"] != "me", (mode, "既読が付いた")
            if b:
                assert len(hers(app, b)) == nb + 1, (mode, "別の相手の返事が届かない")
            app.bonds.wrec()["with"] = None
            app.bonds.save()
            app.state(a)["msg_pending"]["due"] = time.time() - 1
            app.deliver_due()
            assert len(hers(app, a)) == n0 + 1, (mode, "別れたあとに届かない")
            assert not app.state(a).get("msg_pending")
            print("%s: 一緒の間は届かず, 別れたら届く: OK" % mode)
        # 一日を越えたら消える (一緒にいたままでも)
        pend(app, a, back=25 * 3600)
        app.bonds.start(a, "meet")
        app.deliver_due()
        assert not app.state(a).get("msg_pending"), "一日を越えた返事が残った"
        app.bonds.wrec()["with"] = None
        app.bonds.save()
        print("一日を越えたら消える: OK")
        # 手伝いのお礼の催促
        st = app.state(a)
        st["iou"] = {"t": time.time() - 6 * 86400, "what": "引っ越し"}
        app.bonds.start(a, "meet")
        n0 = len(hers(app, a))
        app.askhelp.tick(app.chars[a], st, time.time())
        assert len(hers(app, a)) == n0, "目の前で催促のメッセージ"
        app.bonds.wrec()["with"] = None
        app.bonds.save()
        print("お礼の催促は一緒の間は送らない: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
