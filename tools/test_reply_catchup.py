"""画面を閉じていた間に読めたはずの返事待ちは, その時刻にさかのぼって届く (F17. engine._due_time / _deliver_due).

以前は, 閉じていた間は返事待ちが進まず, 開いた時刻でまとめて届いていた (22:53 に送った分が翌日 13:53 に届く.
相手が朝に起きてから仕事を始めるまでに読めたはずなのに). 期限を大きく過ぎてから見に来たときは, 期限の時刻から
「寝ている・手が離せない」を飛ばして, 手が空いた最初の時刻で読んで返す.
- 夜に送って期限は夜中 → 昼に開く: 起きてから仕事までの間 (7〜9 時) の時刻で届く. トーク・既読・記録もその時刻
- 夜の「おやすみ」を朝に読んだ扱いになる (「おはよう」で返す. 昼に読んだ扱いの既読だけ, にはならない)
- 閉じていた間ずっと寝ている・仕事中: いまの様子で決める (手が離せなければ延期. 今までどおり)
- ふだん (期限から 2 分以内に見に来る): いまの時刻で届く (今までどおり)
- 一日を超えて閉じていても, 一日のうちに読めていたなら届く. 読める時刻が一日を超えるなら, もう来ない
- 開く時刻の総当たり (期限 × 開いた時刻): 届く時刻は 期限以上・開いた時刻以下・相手の手が空いている時刻. 二度は届かない
- 全体の乱数の順をずらさない
(一時データ)

    python tools/test_reply_catchup.py
"""
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
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
        app.create_world("閉じていた間の返事")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        char, st = app.char(cid), app.state(cid)
        C = app.chat
        sched = app.scheduled_scene

        # 相手の一日: 23〜7 時は寝ている, 9〜18 時は仕事 (手が離せない), ほかは手が空いている
        def free(ts):
            h = datetime.fromtimestamp(ts).hour
            return not (h >= 23 or h < 7) and not (9 <= h < 18)

        def scene(c, d):
            h = d.hour
            return dict(sched(c, d), away=False, asleep=h >= 23 or h < 7, busy=9 <= h < 18)
        app.scheduled_scene = scene

        day0 = (datetime.now() - timedelta(days=3)).replace(hour=0, minute=0, second=0, microsecond=0)

        def at(h, m=0):
            return (day0 + timedelta(hours=h, minutes=m)).timestamp()

        def fresh(kind="smalltalk", sent=at(22, 53), due=at(26, 16)):
            st.pop("msg_pending", None)
            st["last_tick"] = sent
            st["override"] = None
            app.set_params({"affection": 60, "mood": 60, "trust": 55}, cid)
            d = C.load(cid)
            d["items"], d["seen_t"] = [], 0
            C.save(cid, d)
            C.add(cid, "me", "（送った）", kind=kind, t=sent)
            st["msg_pending"] = {"aid": "message", "t": sent, "due": due, "reply": True, "count": 1, "kind": kind,
                                 "kind_t": sent, "meta": {}, "quick": False}

        def her():
            return [x for x in C.load(cid)["items"] if x["who"] == "her"]

        # ---- 1. 報告の形: 22:53 に送り, 期限は 02:16. 翌日の 12:27 に開いた (相手は仕事中)
        fresh()
        out = app.deliver_due(at(36, 27))
        hs = her()
        assert out and "msg_pending" not in st, (out, st.get("msg_pending"))
        t = hs[0]["t"]
        assert at(31, 0) <= t < at(33, 0) and free(t), datetime.fromtimestamp(t)          # 起きてから仕事までの間
        assert all(abs(x["t"] - t) < 5 for x in hs), "切り上げなどもその時刻に並ぶ"
        lg = [e for e in app.log(cid) if e.get("reply")]
        assert lg and abs(lg[-1]["t"] - t) < 5, "記録もその時刻"
        assert app.deliver_due(at(36, 28)) == [] and len(her()) == len(hs), "二度は届かない"
        print("翌日の昼に開いた: 届いた時刻", datetime.fromtimestamp(t).strftime("%H:%M"), "OK")

        # ---- 2. 夜の「おやすみ」: 朝に読んだ扱い (「おはよう」で返す)
        fresh(kind="greet_night")
        app.deliver_due(at(36, 27))
        ks = [x["kind"] for x in her()]
        assert ks and ks[0] == "greet_morning" and "greet_night" not in ks, ks
        print("夜のおやすみ → 朝に読んで「おはよう」: OK")

        # ---- 3. 閉じていた間ずっと寝ている / 仕事中: いまの様子で決める (延期)
        fresh()
        assert app.deliver_due(at(29, 0)) == [] and st["msg_pending"]["due"] > at(29, 0) and not her(), "夜中の 5 時: まだ寝ている"
        fresh(sent=at(9, 30), due=at(10, 0))
        assert app.deliver_due(at(15, 0)) == [] and st["msg_pending"]["due"] > at(15, 0) and not her(), "仕事中のまま"
        print("ずっと手が離せない: 延期 OK")

        # ---- 4. ふだん (期限のすぐあとに見に来る): いまの時刻で
        fresh(sent=at(19, 0), due=at(19, 30))
        out = app.deliver_due(at(19, 30) + 20)
        assert out and abs(her()[0]["t"] - (at(19, 30) + 20)) < 1
        print("ふだん: いまの時刻 OK")

        # ---- 5. 一日を超えて閉じていた: 一日のうちに読めていたなら届く. 読める時刻が一日を超えるなら来ない
        fresh()
        out = app.deliver_due(at(22 + 48, 0))
        assert out and at(31, 0) <= her()[0]["t"] < at(33, 0), "2 日後に開いても, 翌朝の時刻で届いている"
        fresh(sent=at(9, 30), due=at(10, 0))
        real = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(scene(c, d), busy=d.timestamp() < at(40, 0))     # 一日以上ずっと手が離せなかった
        assert app.deliver_due(at(48, 0)) == [] and "msg_pending" not in st and not her(), "一日たっても読めなかった: 来ない"
        app.scheduled_scene = real
        print("一日を超えて閉じていた: OK")

        # ---- 6. 総当たり: 期限 × 開いた時刻. 届く時刻は 期限以上・開いた時刻以下・手が空いている時刻
        n = 0
        for due_h in (19, 22, 23.5, 26, 30.9, 32, 33.5, 40, 42.5):
            for open_h in (19.2, 23, 27, 31.5, 32.5, 35, 42.2, 44, 46.5):
                if open_h < due_h:
                    continue
                for seed in range(3):
                    random.seed(seed)
                    sent = at(18, 0)
                    fresh(sent=sent, due=at(0, int(due_h * 60)))
                    now = at(0, int(open_h * 60))
                    if now - sent > 24 * 3600:
                        continue
                    state = random.getstate()
                    tt = app._due_time(char, st, st["msg_pending"], now)
                    assert random.getstate() == state, "全体の乱数の順をずらさない"
                    out = app.deliver_due(now)
                    hs = her()
                    if hs:
                        t = hs[0]["t"]
                        assert at(0, int(due_h * 60)) - 1 <= t <= now + 1 and free(t), (due_h, open_h, datetime.fromtimestamp(t))
                        assert "msg_pending" not in st and out
                    else:                                   # 延期: 開いた時刻に手が離せない
                        assert not free(now) and st["msg_pending"]["due"] > now and tt == now, (due_h, open_h)
                    assert app.deliver_due(now + 30) == [] and len(her()) == len(hs)
                    n += 1
        print("総当たり %d 通り: OK" % n)

        # ---- 7. 閉じていた間のまとめのメッセージ (さかのぼって入る) より前の時刻なら, トークでも前に並ぶ
        fresh()
        C.add(cid, "her", "📱『あとから来たメッセージ』", kind="ap", t=at(35, 0))
        app.deliver_due(at(36, 27))
        its = C.load(cid)["items"]
        assert [x["t"] for x in its] == sorted(x["t"] for x in its) and its[-1]["text"].endswith("あとから来たメッセージ』"), "時刻の順"
        print("トークの並び: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
