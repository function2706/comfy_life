"""ずっとあとで読んだあいさつ・一度の読みでまとめて返したときの切り上げ (manners.greet_stale / nori.after_reply の turn) (一時データ).

- 夜の「おやすみ」を翌日の昼に読んだ: 「おやすみなさい。また明日」とは返さない (既読だけ). 朝に読んだなら「おはよう」で返す.
- 同じ夜のうちに読んだなら, 今までどおり「おやすみ」で返す. 時間外に送ったあいさつ (戸惑いの返事) は, 遅れてもそのまま.
- 重ねて届いた前のメッセージ・先の謝罪にまとめて返しただけでは, 往復に数えない: 会話もしていないのに切り上げない.
  会話が続いていてノリが下がりきったときは, 今までどおり切り上げる (最後の返事のあとに一度だけ).

    python tools/test_greet_late.py
"""
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, nori, store  # noqa: E402


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("あいさつ")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        C, M = app.chat, app.manners
        d0 = (datetime.now() + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)      # あさっての 0 時

        def at(h, m=0, day=0):
            return (d0 + timedelta(days=day, hours=h, minutes=m)).timestamp()

        def fresh(**kw):
            app.set_params(dict({"mood": 60, "affection": 60, "trust": 55, "loneliness": 50, "boredom": 50, "stress": 10}, **kw), cid)
            for k in ("msg_pending", "nori", "approach", "greets", "greet_days"):
                st.pop(k, None)
            st["contacts"] = []
            st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "部屋", "until": at(0, day=9)}
            d = C.load(cid)
            d["items"] = []
            C.save(cid, d)

        def her():
            return [x["kind"] for x in C.thread(cid)["items"] if x["who"] == "her"]

        # ---- 1. 判定の表 (送った時刻 → 読んだ時刻)
        table = [
            ("greet_night", at(22, 53), at(23, 20), None),           # すぐ読んだ
            ("greet_night", at(22, 53), at(27, 30), None),           # 夜中の 3 時半: まだ同じ夜
            ("greet_night", at(22, 53), at(31, 30), "morning"),      # 翌朝 7 時半
            ("greet_night", at(22, 53), at(37, 53), "skip"),         # 翌日の 13:53 (報告のあった形)
            ("greet_night", at(22, 53), at(45, 0), "skip"),          # 翌日の夜
            ("greet_night", at(3, 50), at(4, 5), None),              # 15 分後 (時刻の境をまたいだだけ)
            ("greet_morning", at(7, 0), at(8, 0), None),
            ("greet_morning", at(7, 0), at(11, 30), None),           # 遅れたが, まだ朝
            ("greet_morning", at(7, 0), at(14, 0), "skip"),
            ("greet_morning", at(7, 0), at(31, 0), "skip"),          # 次の日の朝
            ("smalltalk", at(7, 0), at(20, 0), None),                # あいさつ以外は対象外
        ]
        for kind, sent, now, want in table:
            got = M.greet_stale(char, kind, {}, sent, now)
            assert got == want, (kind, datetime.fromtimestamp(sent), datetime.fromtimestamp(now), got, want)
        assert M.greet_stale(char, "greet_night", {"greet": "odd"}, at(10, 0), at(15, 0)) is None, "時間外のあいさつは, 戸惑いの返事のまま"
        print("判定の表: OK (%d 通り)" % (len(table) + 1))

        # ---- 2. 翌日の昼に読んだ「おやすみ」: 返さない (既読だけ). 前に送っていた雑談への返事は届く. 切り上げも付かない
        real_base = nori.base
        nori.base = lambda *a, **k: 5.0            # 乗っていない (切り上げが付きうる低さ)
        for seed in range(12):
            random.seed(seed)
            fresh()
            C.add(cid, "me", "（雑談を送った）", kind="smalltalk", t=at(22, 50))
            C.add(cid, "me", "（おやすみと送った）", kind="greet_night", t=at(22, 53))
            st["msg_pending"] = {"aid": "message", "t": at(22, 50), "due": at(37, 52), "reply": True, "count": 2, "kind": "greet_night",
                                 "kind_t": at(22, 53), "meta": {}, "quick": False,
                                 "queue": [{"kind": "smalltalk", "meta": {}, "t": at(22, 50)}]}
            out = app.deliver_due(at(37, 53))
            ks = her()
            assert "msg_pending" not in st and "greet_night" not in ks and "greet_morning" not in ks, (seed, ks)
            assert not any(k.startswith("close_") for k in ks), (seed, ks)
            assert all(x.get("read_t") for x in C.thread(cid)["items"] if x["who"] == "me"), "既読は付く"
            assert len(ks) <= 1 and len(out) <= len(ks), (seed, out, ks)      # 返ってくるとしても, 雑談への 1 通だけ
        print("翌日の昼に読んだおやすみ: OK (返さない・切り上げない)")

        # ---- 3. 翌朝に読んだ「おやすみ」: 「おはよう」で返す
        random.seed(1)
        fresh()
        C.add(cid, "me", "（おやすみと送った）", kind="greet_night", t=at(22, 53))
        st["msg_pending"] = {"aid": "message", "t": at(22, 53), "due": at(31, 29), "reply": True, "count": 1, "kind": "greet_night",
                             "kind_t": at(22, 53), "meta": {}, "quick": False}
        out = app.deliver_due(at(31, 30))
        assert her() == ["greet_morning"] and len(out) == 1, (her(), out)
        print("翌朝に読んだおやすみ: OK |", out[0]["text"])

        # ---- 4. 同じ夜のうちに読んだ: 今までどおり
        random.seed(1)
        fresh()
        C.add(cid, "me", "（おやすみと送った）", kind="greet_night", t=at(22, 53))
        st["msg_pending"] = {"aid": "message", "t": at(22, 53), "due": at(23, 10), "reply": True, "count": 1, "kind": "greet_night",
                             "kind_t": at(22, 53), "meta": {}, "quick": False}
        out = app.deliver_due(at(23, 20))
        assert her() == ["greet_night"] and len(out) == 1, (her(), out)
        print("同じ夜に読んだおやすみ: OK |", out[0]["text"])

        # ---- 5. まとめて返しただけでは切り上げない (重ねた 3 通・先の謝罪). 乱数の種を変えても同じ
        for seed in range(20):
            random.seed(seed)
            fresh()
            # 最後は「最近どう？」(「話したい」は乗らないとノリが下がって切り上げることがある. それは束ねたせいではない)
            st["msg_pending"] = {"aid": "message", "t": at(12, 0), "due": at(12, 20), "reply": True, "count": 3, "kind": "ask_how",
                                 "kind_t": at(12, 4), "meta": {}, "quick": False,
                                 "queue": [{"kind": "otsukare", "meta": {}, "t": at(12, 0)}, {"kind": "photo", "meta": {}, "t": at(12, 2)}]}
            app.deliver_due(at(12, 30))
            ks = her()
            assert ks and not any(k.startswith("close_") for k in ks), (seed, ks)
            assert (st.get("nori") or {}).get("turns") == 1, (seed, st.get("nori"))
            fresh()
            st["msg_pending"] = {"aid": "message", "t": at(12, 0), "due": at(12, 20), "reply": True, "count": 2, "kind": "thanks",
                                 "kind_t": at(12, 4), "meta": {}, "quick": False, "apology_first": {"t": at(12, 0), "meta": {}}}
            app.deliver_due(at(12, 30))
            ks = her()
            assert len(ks) >= 2 and not any(k.startswith("close_") for k in ks), (seed, ks)
        print("まとめて返しただけでは切り上げない: OK")

        # ---- 6. 会話が続いていて下がりきった: 切り上げる. 重ねた分があっても, 最後の返事のあとに一度だけ
        for seed in range(20):
            random.seed(seed)
            fresh()
            st["nori"] = {"v": 12, "t": at(12, 25), "turns": 3}
            st["msg_pending"] = {"aid": "message", "t": at(12, 26), "due": at(12, 28), "reply": True, "count": 2, "kind": "smalltalk",
                                 "kind_t": at(12, 27), "meta": {}, "quick": False,
                                 "queue": [{"kind": "photo", "meta": {}, "t": at(12, 26)}]}
            app.deliver_due(at(12, 30))
            ks = her()
            assert sum(k.startswith("close_") for k in ks) == 1 and ks[-1].startswith("close_"), (seed, ks)
            assert "nori" not in st
        nori.base = real_base
        print("会話の途中で下がりきれば切り上げる (最後に一度): OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
