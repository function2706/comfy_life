"""あなたの予定 (日ごと): 画面を閉じている間 (オフライン) の過ごし方を, ふだんの画面 (「一人で」タブの「予定」) で組む.

保存 (player.json の plan):
  items:    [{id, date "YYYY-MM-DD", at "HH:MM", do, place?, how?, skill?}]  1 つの予定は, 次の予定の時刻 (同じ日のうち) まで続く.
            過ぎた日の分は消える. 組める先の日数は, 段取りのスキル (仕事・やりくりの平均) しだい (horizon_days).
  fallback: [{do, place?, how?, skill?}]  未指定時コマンド (優先度の高い順).
  auto:     {street: chat/nod/decline (声をかけられた) | None, reply: cheerful/curt/... | None}  自動の応答の方針 (無料).
決まる順番 (閉じていた間, 予定の時刻・予定と予定の空き時間ごと): 予定のコマンド → できなければ (閉まっている・お金/体力が足りない・
時間外など) 未指定時コマンドを優先度の高い順に → それも無い・どれもできなければ設定の行動パターン → それもできなければ何もしない.
空き時間は未指定時コマンドから. 何も組んでいなければ, 今までどおり設定の行動パターンだけ. 相手との約束の時刻は約束が先.
画面を開いている間に予定の時刻が来たら, 知らせて記録するだけ (何もしない. 誘導もしない).
"""
import time
import uuid
from datetime import datetime, timedelta

from .places import OUT_PLACES, open_state

PLAN_DO = ("sleep", "rest", "home", "work", "out", "chores", "kakeibo", "practice", "meal", "parttime")
STREET_POLICY = ("chat", "nod", "decline")
NATURAL = {"chores": 3600, "practice": 3600, "kakeibo": 900}      # これより短ければ「切り上げた」
SHOP_NATURAL = 3600                                                  # 買い物 (店への外出) の目安
APPOINT_SPAN = 2 * 3600                                              # 約束で会う時間の目安


def _hm(s):
    h, m = str(s).split(":")
    return int(h) * 60 + int(m)


class Planner:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 保存
    def rec(self):
        ps = self.app.life.player_state()
        p = ps.setdefault("plan", {})
        p.setdefault("items", [])
        p.setdefault("fallback", [])
        p.setdefault("auto", {"street": None, "reply": None})
        return p

    def save(self):
        self.app.life.save_player()

    def purge(self, now=None):
        """過ぎた日の予定を消す."""
        today = datetime.fromtimestamp(now or time.time()).strftime("%Y-%m-%d")
        p = self.rec()
        keep = [x for x in p["items"] if x["date"] >= today]
        if len(keep) != len(p["items"]):
            p["items"] = keep
            self.save()

    def active(self):
        p = self.rec()
        return bool(p["items"] or p["fallback"])

    # ------------------------------------------------------------------ 組める日
    def plan_skill(self):
        L = self.app.life
        return (L.skill("work") + L.skill("budget")) / 2.0

    def horizon_days(self):
        """今日から何日先まで組めるか: 段取りのスキル 25 ごとに 1 日 (低くても翌日まで. 最大 5 日先)."""
        return min(5, 1 + int(self.plan_skill() // 25))

    def dates(self, now=None):
        d0 = datetime.fromtimestamp(now or time.time()).date()
        return [(d0 + timedelta(days=i)).isoformat() for i in range(self.horizon_days() + 1)]

    # ------------------------------------------------------------------ 組む
    def _norm(self, b):
        from .offline import normalize
        b = dict(b)
        if b.get("do") not in PLAN_DO:
            raise ValueError("予定にできないコマンドです: %s" % b.get("do"))
        if b.get("do") == "out" and b.get("place") not in OUT_PLACES:
            raise ValueError("行き先を選んでください")
        out = normalize({k: v for k, v in b.items() if k in ("do", "place", "how", "skill", "at")})
        if out["do"] == "practice" and b.get("skill"):
            out["skill"] = b["skill"]
        return out

    def appoint_at(self, t):
        """その時刻にかかっている約束 (約束の時刻の前後). 予定とぶつからないように見せる."""
        for x in self.app.appoint.all():
            if x["status"] in ("set", "waiting") and x["t"] - 1800 <= t < x["t"] + APPOINT_SPAN:
                return x
        return None

    def add(self, date, at, b, now=None):
        now = now or time.time()
        self.purge(now)
        if date not in self.dates(now):
            raise ValueError("その日の予定はまだ組めません（%d日先まで。段取りのスキルが上がると、先まで組めます）" % self.horizon_days())
        try:
            _hm(at)
        except (ValueError, TypeError):
            raise ValueError("時刻が違います: %s" % at)
        t = datetime.strptime("%s %s" % (date, at), "%Y-%m-%d %H:%M").timestamp()
        if t < now:
            raise ValueError("もう過ぎた時刻です")
        x = self.appoint_at(t)
        if x:
            raise ValueError("その時刻は%sとの約束があります" % self.app.chars.get(x["cid"], {}).get("name", ""))
        item = dict(self._norm(b), id=uuid.uuid4().hex[:8], date=date, at=at)
        p = self.rec()
        p["items"] = sorted([y for y in p["items"] if not (y["date"] == date and y["at"] == at)] + [item],
                            key=lambda y: (y["date"], _hm(y["at"])))
        self.save()
        return self.view(now)

    def remove(self, iid, now=None):
        p = self.rec()
        p["items"] = [x for x in p["items"] if x["id"] != iid]
        self.save()
        return self.view(now)

    def set_fallback(self, items, now=None):
        self.rec()["fallback"] = [self._norm(b) for b in items or []][:8]
        self.save()
        return self.view(now)

    def set_auto(self, street=None, reply=None, now=None):
        from .msgreply import KINDS
        if street not in (None, "") + STREET_POLICY:
            raise ValueError("ばったりの方針が違います")
        if reply not in (None, "") and reply not in KINDS:
            raise ValueError("返事の方針が違います")
        self.rec()["auto"] = {"street": street or None, "reply": reply or None}
        self.save()
        return self.view(now)

    def label(self, b):
        from .offline import DO_LABEL, MEAL_HOW
        app = self.app
        if b["do"] == "out":
            return "外出（%s）" % app.places.label(b.get("place"))
        if b["do"] == "meal":
            return "食事（%s%s）" % (MEAL_HOW.get(b.get("how") or "cook", ""), "・" + app.places.label(b["place"]) if b.get("place") else "")
        return DO_LABEL.get(b["do"], b["do"])

    def view(self, now=None):
        now = now or time.time()
        self.purge(now)
        p = self.rec()
        appts = [{"t": x["t"], "date": datetime.fromtimestamp(x["t"]).strftime("%Y-%m-%d"),
                  "at": datetime.fromtimestamp(x["t"]).strftime("%H:%M"), "name": self.app.chars.get(x["cid"], {}).get("name", ""),
                  "place": self.app.places.label(x["place"])}
                 for x in self.app.appoint.all() if x["status"] in ("set", "waiting") and x["t"] > now]
        return {"items": [dict(x, label=self.label(x)) for x in p["items"]],
                "fallback": [dict(x, label=self.label(x)) for x in p["fallback"]],
                "auto": p["auto"], "dates": self.dates(now), "horizon": self.horizon_days(),
                "skill": round(self.plan_skill(), 1), "appoints": appts}

    # ------------------------------------------------------------------ 画面を開いている間
    def live(self, now=None):
        """画面を開いている間に予定の時刻が来た: 知らせて記録するだけ (何もしない). 知らせた文の一覧を返す."""
        now = now or time.time()
        out = []
        changed = False
        for x in self.rec()["items"]:
            t = self.item_t(x)
            if t <= now and not x.get("noticed"):
                x["noticed"] = True
                changed = True
                if now - t < 15 * 60:          # 閉じていた間に過ぎた分は, 戻ったときの報告に任せる
                    msg = "予定の時刻になった（%s %s）" % (x["at"], self.label(x))
                    self.app.solo.note("plan", msg, now)
                    out.append(msg)
        if changed:
            self.save()
        return out

    @staticmethod
    def item_t(x):
        return datetime.strptime("%s %s" % (x["date"], x["at"]), "%Y-%m-%d %H:%M").timestamp()

    # ------------------------------------------------------------------ 閉じていた間
    def cannot(self, b, s, stamina):
        """そのコマンドを s にできない理由 (できれば None)."""
        app = self.app
        do = b["do"]
        dt = datetime.fromtimestamp(s)
        if do == "out":
            o = open_state(b.get("place") or "", dt)
            if not o["open"]:
                return "%sが閉まっていた" % app.places.label(b.get("place"))
            if stamina < 15:
                return "疲れきっていた"
            from .places import PLACES
            fee = int((PLACES.get(b.get("place") or "") or {}).get("fee", 0))
            if fee and app.life.player_state()["money"] < fee:
                return "お金が足りなかった（入場料）"
        if do == "meal" and (b.get("how") or "cook") != "cook":
            o = open_state(b.get("place") or "", dt)
            if not o["open"]:
                return "%sが閉まっていた" % app.places.label(b.get("place"))
            if app.life.player_state()["money"] < 1000:
                return "お金が足りなかった"
        if do == "work":
            lo, hi = (app.life.econ().get("work_hours") or [6, 23])[:2]
            if not (lo <= dt.hour < hi):
                return "仕事の時間外だった"
            if app.body.level() >= 3:
                return "体調が悪かった"
        if do == "parttime" and not app.earn.pt():
            return "アルバイトをしていない"
        if do in ("chores", "practice") and stamina < 25:
            return "疲れていた"
        return None

    def slots(self, t0, t1):
        """[t0, t1) を 約束 / 予定 / 空き に分ける [(開始, 終了, 種類, もの)]. 予定は次の予定 (同じ日のうち) まで."""
        app = self.app
        cuts = []
        for x in app.appoint.all():
            if x["status"] in ("set", "waiting") and t0 <= x["t"] < t1:
                cuts.append((x["t"], min(t1, x["t"] + APPOINT_SPAN), "appoint", x))
        items = sorted(((self.item_t(x), x) for x in self.rec()["items"]), key=lambda y: y[0])
        plan = []
        for i, (t, x) in enumerate(items):
            end_of_day = (datetime.fromtimestamp(t).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp()
            nxt = items[i + 1][0] if i + 1 < len(items) else 9e18
            s, e = max(t, t0), min(nxt, end_of_day, t1)
            if e > s:
                plan.append((s, e, "plan", x))
        out = []
        t = t0
        segs = sorted(plan, key=lambda y: y[0])
        for s, e, kind, x in segs:
            if s > t:
                out.append((t, s, "gap", None))
            out.append((max(s, t), e, kind, x))
            t = max(t, e)
        if t < t1:
            out.append((t, t1, "gap", None))
        # 約束の時間は約束が先: 重なるところを削る
        res = []
        for s, e, kind, x in out:
            pieces = [(s, e)]
            for a0, a1, _, _ in cuts:
                nxt = []
                for p0, p1 in pieces:
                    if a1 <= p0 or a0 >= p1:
                        nxt.append((p0, p1))
                        continue
                    if p0 < a0:
                        nxt.append((p0, a0))
                    if a1 < p1:
                        nxt.append((a1, p1))
                pieces = nxt
            res += [(p0, p1, kind, x) for p0, p1 in pieces if p1 - p0 >= 60]
        res += cuts
        return sorted(res, key=lambda y: y[0])
