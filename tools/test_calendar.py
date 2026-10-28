"""スマホのカレンダー (core/calview.py): 約束 (全員分・状態つき)・頼まれごと (決まったもの / すり合わせ中 / 水やりの期間)・
自分の予定・知っている相手の予定 (知らないものは出さない. 食い違えば「もう違うかも」)・以前のセーブの記録・/api/calendar (一時データ, 画像生成なし).

    python tools/test_calendar.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402
from core import earn as EA, engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def main():
    random.seed(5)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("カレンダー")
        A, E, CV = app.appoint, app.earn, app.calview
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        app.bonds.set_stage(cid, "contact")
        now = time.time()
        day = lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d")      # noqa: E731

        def month_of(t):
            d = datetime.fromtimestamp(t)
            return CV.month(d.year, d.month, now)

        # ---- 1. 約束: こちらから誘った (返事待ち) と, 終わったもの (会えた). 状態つき
        t1 = (datetime.fromtimestamp(now) + timedelta(days=3)).replace(hour=14, minute=0).timestamp()
        A.propose(cid, t1, "park", "walk", now)
        A.all().append({"id": "old1", "cid": cid, "t": now - 86400, "place": "cafe", "do": "cafe", "status": "met"})  # by の無い以前の記録
        r = month_of(t1)
        es = [e for e in r["days"].get(day(t1), []) if e["kind"] == "appoint"]
        assert es and es[0]["appoint"]["status_label"] == "返事待ち" and es[0]["at"] == "14:00", es
        r0 = month_of(now - 86400)
        assert any(e["kind"] == "appoint" and e["appoint"]["status_label"] == "会えた" for e in r0["days"].get(day(now - 86400), []))
        assert r["people"] and r["people"][0]["id"] == cid
        print("約束: OK |", es[0]["appoint"]["name"], es[0]["at"], es[0]["appoint"]["status_label"])

        # ---- 2. 頼まれごと: 日時の決まったもの (その日) / 都合を聞かれている (日付の無い欄) / 水やり (留守の毎日)
        def offer(kind, ask=None):
            k, name, h, tire = EA.FAVOR_KIND[kind]
            f = {"id": "f" + kind, "cid": cid, "kind": kind, "label": name, "h": h, "tire": tire, "t": now, "until": now + 3 * 86400}
            E.favors().append(f)
            x = A.favor_offer(f, now)
            if ask is not None and not x.get("fixed"):
                x["ask"] = ask
            return x
        xm = offer("move")
        assert any(e["kind"] == "favor" and e["appoint"]["id"] == xm["id"] for e in month_of(xm["t"])["days"].get(day(xm["t"]), []))
        xc = offer("clean", ask=True)
        assert any(e["appoint"]["id"] == xc["id"] for e in month_of(now)["undated"])
        assert not any(e.get("appoint", {}).get("id") == xc["id"] for es in month_of(xc["t"])["days"].values() for e in es)
        xp = offer("plants")
        d, n = datetime.fromtimestamp(xp["t"]).date(), 0
        while d <= datetime.fromtimestamp(xp["until"]).date():
            ts = datetime(d.year, d.month, d.day, 12).timestamp()
            n += any(e.get("appoint", {}).get("id") == xp["id"] for e in month_of(ts)["days"].get(d.isoformat(), []))
            d += timedelta(days=1)
        assert n >= 2, n
        # すり合わせ: 都合を聞かれている頼まれごとに日時を返すと (既存の counter), その日に載る
        A.counter(xc["id"], t1 + 86400, now=now)
        assert any(e.get("appoint", {}).get("id") == xc["id"] for e in month_of(t1 + 86400)["days"].get(day(t1 + 86400), []))
        print("頼まれごと: OK | 決め打ち・都合を聞かれている・水やり %d 日・日時を返すとその日に" % n)

        # ---- 3. 自分の予定 (既存の /api/plan/add で足したもの)
        dd = app.planner.dates(now)[-1]
        app.planner.add(dd, "20:00", {"do": "chores"}, now)
        ts = datetime.strptime(dd, "%Y-%m-%d").timestamp() + 3600
        pe = [e for e in month_of(ts)["days"].get(dd, []) if e["kind"] == "plan"]
        assert pe and pe[0]["at"] == "20:00" and pe[0]["text"], pe
        print("予定: OK |", pe[0]["text"])

        # ---- 4. 知っている相手の予定: 知らなければ出さない. 聞いたら曜日の合う日に. いまの予定と食い違えば「もう違うかも」
        def scheds(r):
            return [e for es in r["days"].values() for e in es if e["kind"] == "sched"]
        st["known"] = [k for k in st.get("known") or [] if k.get("kind") != "schedule"]
        assert not scheds(month_of(now)), "知らない予定が出ている"
        char["schedule"] = (char.get("schedule") or []) + [{"days": "all", "from": "18:00", "to": "21:00", "label": "アルバイト中",
                                                               "activity": "parttime", "away": True, "workplace": "cafe"}]
        e0 = char["schedule"][-1]
        app.knowsched.learn(cid, e0, "talk", now)
        ss = scheds(month_of(now))
        assert ss and all(not e["stale"] for e in ss) and ss[0]["at"] == "18:00" and "カフェ" in ss[0]["text"], ss[:1]
        assert min(d for d, es in month_of(now)["days"].items() if any(e["kind"] == "sched" for e in es)) >= day(now)   # 今日から先だけ
        char["schedule"] = char["schedule"][:-1]                               # 予定が変わった
        ss = scheds(month_of(now))
        assert ss and all(e["stale"] for e in ss), ss[:1]
        st["known"].append({"kind": "schedule", "text": "古い形", "t": now})    # key の無い以前の記録は飛ばす
        st["known"].append({"kind": "note", "text": "予定ではない"})
        month_of(now)
        print("相手の予定: OK |", ss[0]["name"], ss[0]["at"], ss[0]["text"], "（もう違うかも）")

        # ---- 5. 以前のセーブ: 状態の無い記録・知らない人の約束があっても表示できる. /api/calendar
        A.all().append({"id": "old2", "cid": cid, "t": now + 3600, "place": "park", "do": "walk"})
        A.all().append({"id": "old3", "cid": "nobody", "t": now + 3600, "place": "park", "do": "walk", "status": "set"})
        server.APP = app
        r, code = server.call_api("GET", "/api/calendar", {"y": [str(datetime.now().year)], "m": [str(datetime.now().month)]}, None)
        assert code == 200 and r["ndays"] >= 28 and 0 <= r["first_wd"] <= 6 and r["plan_dates"], r.keys()
        assert month_of(now)["y"] == datetime.fromtimestamp(now).year and CV.month(0, 0, now)["m"] == datetime.fromtimestamp(now).month
        assert CV.month(2026, 12, now)["next"] == [2027, 1] and CV.month(2026, 1, now)["prev"] == [2025, 12]
        print("以前のセーブ・月送り: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
