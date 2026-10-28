"""スマホのカレンダー (アプリ内. 実のカレンダーや .ics とはつながない): 月の表と, 選んだ日の一覧.

載せるもの (どれも, もとの記録をそのまま読むだけ. カレンダー用の記録は持たない):
- 約束 (core/appoint.py): 全員分・状態つき (返事待ち / 誘われている / 約束した / 会えた / 流れた など). 終わったものも記録の残っている間 (30 日).
- 頼まれごと: 約束と同じ記録 (favor). 日時の決まったもの・すり合わせ中のもの. 水やりは留守の期間の毎日に.
  都合を聞かれている (ask) ものは日時がまだ無いので, 日付の無い欄に.
- 自分の予定 (core/planner.py の items): 画面を閉じている間の過ごし方.
- 知っている相手の予定 (core/knowsched.py の known): 聞いて知っている分だけ (知らないものは出さない). 今日から先の, 曜日の合う日に.
  いまの予定と食い違っていれば「もう違うかも」.
登録は新しい仕組みを作らず, 画面から既存の処理 (/api/appoint・/api/appoint/answer・/api/plan/add) を呼ぶ.
"""
import time
from datetime import date, datetime, timedelta

from . import knowsched as ks

WEEK = "月火水木金土日"


def _d(t):
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d")


def _hm(t):
    d = datetime.fromtimestamp(t)
    return "%d:%02d" % (d.hour, d.minute)


class CalView:
    def __init__(self, app):
        self.app = app

    def month(self, y=0, m=0, now=None):
        app = self.app
        now = now or time.time()
        today = datetime.fromtimestamp(now).date()
        if not (1 <= m <= 12) or y < 1970:
            y, m = today.year, today.month
        first = date(y, m, 1)
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        t0 = datetime(first.year, first.month, 1).timestamp()
        t1 = datetime(nxt.year, nxt.month, 1).timestamp()
        days = {}

        def put(d, e):
            if first.isoformat() <= d < nxt.isoformat():
                days.setdefault(d, []).append(e)

        undated = []
        A = app.appoint
        for x in A.all():
            if x.get("cid") not in app.chars or "t" not in x:
                continue
            r = A.row(x, now)
            kind = "favor" if x.get("favor") else "appoint"
            if x.get("favor") and x.get("ask") and x.get("status") in ("offered", "asked"):
                undated.append({"kind": kind, "at": "", "appoint": r})            # 都合を聞かれている: 日時はまだ
                continue
            if x.get("plants") and x.get("until"):                                 # 留守の期間の毎日
                d, end = datetime.fromtimestamp(x["t"]).date(), datetime.fromtimestamp(x["until"]).date()
                while d <= end:
                    put(d.isoformat(), {"kind": kind, "at": "", "appoint": r})
                    d += timedelta(days=1)
                continue
            if t0 <= x["t"] < t1:
                put(_d(x["t"]), {"kind": kind, "at": _hm(x["t"]), "appoint": r})
        P = app.planner
        P.purge(now)
        for it in P.rec().get("items") or []:
            put(it["date"], {"kind": "plan", "at": it["at"], "text": P.label(it), "id": it["id"]})
        # 知っている相手の予定 (今日から先の, 曜日の合う日)
        from .engine import day_match
        for cid, char in app.chars.items():
            st = app.state(cid)
            cur = {ks.key_of(e): e for e in char.get("schedule") or []}
            for k in st.get("known") or []:
                if k.get("kind") != "schedule" or not k.get("key"):
                    continue
                e = cur.get(k["key"])
                if e is None:                       # いまの予定には無い: 聞いたときの中身で (もう違うかも)
                    p = k["key"].split("|")
                    if len(p) < 5:
                        continue
                    e = {"days": p[0], "from": p[1], "to": p[2], "label": "|".join(p[3:-1]), "workplace": p[-1]}
                what = ks.at_work(app, e, (e.get("label") or e.get("activity") or "").replace("中", "")) or "予定"
                old = (now - k.get("t", now)) / 86400.0 > ks.STALE_DAYS
                ent = {"kind": "sched", "at": e.get("from") or "", "to": e.get("to") or "", "cid": cid, "name": char.get("name", ""),
                       "text": what, "stale": k["key"] not in cur, "old": old, "heard": k.get("text", "")}
                d = max(today, first)
                while d < nxt:
                    if day_match(e.get("days"), datetime(d.year, d.month, d.day)):
                        put(d.isoformat(), ent)
                    d += timedelta(days=1)
        for d in days:
            days[d].sort(key=lambda e: (e["at"] == "", self._mins(e["at"])))
        people = [{"id": cid, "name": c.get("name", ""), "stage": app.bonds.stage(cid)} for cid, c in app.chars.items()
                  if app.bonds.stage(cid) in ("contact", "visit")]
        prev = date(y - (m == 1), (m - 2) % 12 + 1, 1)
        return {"y": y, "m": m, "today": today.isoformat(), "first_wd": first.weekday(), "ndays": (nxt - first).days,
                "prev": [prev.year, prev.month], "next": [nxt.year, nxt.month], "days": days, "undated": undated,
                "plan_dates": P.dates(now), "invite_to": (today + timedelta(days=13)).isoformat(), "people": people}

    @staticmethod
    def _mins(at):
        try:
            h, mm = str(at).split(":")
            return int(h) * 60 + int(mm)
        except ValueError:
            return 0
