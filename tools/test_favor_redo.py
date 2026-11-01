"""頼まれごとの手伝い: 対面の記録・画像と, 早く着いたときの知らせ, 途中で切り上げた分のお詫びと頼み直し (一時データ, 画像生成なし).
- 会えて手伝いに取りかかると, 相手の記録に「一緒に取りかかった」場面が残る (離れている扱いでない. 画像を作る対象). 相手は手伝いをして家にいる
- 手伝いから戻ると, 終えた場面も相手の記録に残る
- 約束の場所に早く着くと「時間まで待つ」と知らせる (時刻になれば会える)
- お詫び (一度だけ): 途中で切り上げた手伝いの罰を戻し, 相手から すぐ 明日の同じ時刻で頼み直してくる. 一覧から外れていても拾う. 終えた手伝いは対象外

    python tools/test_favor_redo.py
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


def main():
    random.seed(5)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        app.bonds.set_stage(cid, "contact")
        A, E = app.appoint, app.earn
        now = time.time()

        def favor(kind="clean", t=None, label="大掃除の手伝い"):
            f = {"id": "f%d" % random.randint(0, 10 ** 9), "cid": cid, "kind": kind, "label": label, "h": 3.0, "tire": 20,
                 "t": now, "until": now + 3 * 86400}
            E.favors().append(f)
            x = {"id": "a%d" % random.randint(0, 10 ** 9), "cid": cid, "place": "home:" + cid, "do": "_favor", "by": "her",
                 "status": "set", "made": now, "favor": f["id"], "fkind": kind, "label": f["label"], "t": t or now}
            f["appoint"] = x["id"]
            A.all().append(x)
            return f, x

        # ---- 会えて取りかかる: 相手の記録に場面が残る. 戻ると終えた場面も
        f, x = favor()
        n0 = len(app.log(cid))
        r = A._meet(x, now)
        e = r.get("entry_her")
        assert e and e["action"] == "_favor" and not e.get("apart") and "cleaning" in e["pos"], e
        assert st["override"]["activity"] == "favor" and app.presence.rec()["mode"] == "work"
        app.presence.rec()["since"] -= 3.2 * 3600
        app.come_back()
        ends = [x_ for x_ in app.log(cid)[n0:] if x_["action"] == "_favor"]
        print("手伝いの場面:", [x_["text"] for x_ in ends])
        assert len(ends) == 2 and "終えた" in ends[1]["text"] and (st.get("override") or {}).get("activity") != "favor"
        assert app.life.player_state().get("fix_comp", {}).get("favor_redo") is None, "終えた手伝いはお詫びの対象でない"

        # ---- 早く着いた: 時間まで待つと知らせる
        f, x = favor(t=now + 3600)
        A.here = lambda place, now_=None: True
        out = []
        A._tick(x, now, out)
        print("早く着いた:", out)
        assert out and "待つ" in out[0] and x["status"] == "set"
        del A.here
        A.all().remove(x)
        E.favors().remove(f)

        # ---- 途中で切り上げた: 罰を戻し, 明日の同じ時刻で頼み直してくる
        f, x = favor(t=now - 1800)
        A._meet(x, now - 1800)
        app.presence.rec()["since"] -= 0.5 * 3600
        tr0 = st["params"]["trust"]
        app.come_back()                                    # 途中で帰る → その場でお詫びと頼み直し
        nx = A.find(f["appoint"])
        last = app.chat.load(cid)["items"][-1]
        print("頼み直し:", nx["status"], A.when_of(nx, time.time()), last["text"])
        assert nx["status"] == "offered" and nx["by"] == "her" and abs(nx["t"] - (x["t"] + 86400)) < 1
        assert last["kind"] == "favor_ask" and "続き" in last["text"] and abs(st["params"]["trust"] - tr0) < 0.01
        assert app.favor_redo_comp() is None, "一度だけ"

        # ---- 以前のアプリで切り上げて, 一覧から外れていた: 起動時に拾って頼み直す
        app.life.player_state()["fix_comp"].pop("favor_redo")
        nx["status"] = "lapsed"
        E.favors().remove(E.favor(f["id"]))
        f2, x2 = favor("furniture", t=now - 7200, label="家具の組み立て")
        x2["status"] = "met"
        E.favors().remove(f2)
        nx2 = app.favor_redo_comp()
        assert nx2 and nx2["favor"] == f2["id"] and E.favor(f2["id"]) and E.favor(f2["id"])["appoint"] == nx2["id"], nx2
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
