"""オフラインモード: 画面を閉じている間 (心拍が途絶えている間) の, あなたの過ごし方.

設定 (全体共通, settings.offline):
  {"enabled": true, "work": {"mon": {"on": true, "from": "09:00", "to": "18:00"}, ..., "sun": {"on": false, ...}}}
画面を閉じていた間は, この予定に沿って過ごしたことにする.
- 勤務時間帯: 仕事に出ていた. 給料・体力の消費・仕事スキル. 体力や仕事スキルしだいで, うまくいかない (給料が減る・叱られる)・
  早退・残業も起きる (現実的に: 毎回同じにはならない). 職場で同僚に会うこともある (気づけないので無難な対応)
- それ以外: 家で静かに過ごす (誰にも会わない. 体力が戻る. 夜は寝ているので早く戻る)
- 離れているキャラから, メッセージ (働きかけ) が届くこともある. すぐには返せない: 返事の遅れの受け止め方は性格・間柄しだい
短い離席 (min_minutes 未満) は対象にしない. 結果は player.json の offline_report にまとめ, 次に開いたとき一度だけ見せる.
"""
import math
import random
import time
from datetime import datetime, timedelta

DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULT = {"enabled": True, "min_minutes": 30,
           "work": {d: {"on": i < 5, "from": "09:00", "to": "18:00"} for i, d in enumerate(DAY_KEYS)}}


def _hm(s):
    h, m = str(s).split(":")
    return int(h) * 60 + int(m)


class Offline:
    def __init__(self, app):
        self.app = app

    def cfg(self):
        c = dict(DEFAULT)
        user = self.app.settings.get("offline") or {}
        c.update({k: v for k, v in user.items() if k != "work"})
        work = {d: dict(v) for d, v in DEFAULT["work"].items()}
        for d, v in (user.get("work") or {}).items():
            if d in work:
                work[d].update(v or {})
        c["work"] = work
        return c

    def segments(self, t0, t1):
        """[t0, t1) のうち, 予定の勤務時間 [(開始, 終了)]."""
        c = self.cfg()
        out = []
        day = datetime.fromtimestamp(t0).replace(hour=0, minute=0, second=0, microsecond=0)
        while day.timestamp() < t1:
            w = c["work"][DAY_KEYS[day.weekday()]]
            if w.get("on"):
                a, b = _hm(w.get("from", "09:00")), _hm(w.get("to", "18:00"))
                s = (day + timedelta(minutes=a)).timestamp()
                e = (day + timedelta(minutes=b if b > a else b + 1440)).timestamp()
                s, e = max(s, t0), min(e, t1)
                if e - s >= 900:
                    out.append((s, e))
            day += timedelta(days=1)
        return out

    @staticmethod
    def _night(t):
        h = datetime.fromtimestamp(t).hour
        return h >= 23 or h < 7

    # ------------------------------------------------------------------ 閉じていた間を過ごす
    def simulate(self, t0, t1):
        """画面を閉じていた t0 (最後の心拍) 〜 t1 (いま). 結果のまとめを返す (対象でなければ None)."""
        app, L = self.app, self.app.life
        c = self.cfg()
        if not c.get("enabled") or t1 - t0 < float(c.get("min_minutes", 30)) * 60:
            return None
        ps = L.player_state()
        econ = L.econ()
        rec = float(econ.get("stamina_recover", 5))
        rec_night = float(econ.get("stamina_recover_sleep", 12))
        per_h = float(econ.get("stamina_per_work_hour", 9))
        stamina = float(ps.get("stamina", 100))
        s0 = stamina
        L.tick_world(t1)                       # 市場・定期収入など (体力はこのあと, 過ごし方に合わせて決め直す)
        money0 = int(ps["money"])
        works, meets = [], []
        t = t0

        def rest(a, b):
            nonlocal stamina
            x = a
            while x < b:
                y = min(b, x + 1800)
                stamina = min(100.0, stamina + (rec_night if self._night(x) else rec) * (y - x) / 3600.0)
                x = y

        for s, e in self.segments(t0, t1):
            rest(t, s)
            w = self._work(s, e, stamina)
            stamina = max(0.0, stamina - per_h * w["hours"])
            works.append(w)
            meets += self._coworkers(w["start"], w["end"])
            t = w["end"]
        rest(t, t1)
        ps["stamina"] = round(stamina, 1)
        L.save_player()
        msgs = self._messages(t0, t1)
        rep = {"from": t0, "to": t1, "works": works, "pay": int(ps["money"]) - money0,
               "stamina": [round(s0, 1), round(stamina, 1)], "meets": meets, "messages": msgs, "seen": False}
        ps["offline_report"] = rep
        L.save_player()
        app.solo.note("offline", self._summary(rep), t1)
        return rep

    def _work(self, s, e, stamina):
        """予定の勤務 1 回. 体力・仕事スキルしだいで, うまくいかない・早退・残業."""
        L = self.app.life
        skill = L.skill("work")
        notes = []
        end = e
        if random.random() < 0.03 + (0.35 if stamina < 25 else 0.12 if stamina < 45 else 0.0):
            end = s + (e - s) * random.uniform(0.3, 0.8)                  # 体調が悪くて早退
            notes.append("体調がすぐれず、早退した")
        elif random.random() < 0.15:
            end = e + random.uniform(0.5, 2.0) * 3600                       # 残業
            notes.append("残業になった")
        pay, h, raw = L.work_pay(s, end, record=True)
        if random.random() < max(0.03, 0.12 + (0.2 if stamina < 40 else 0.0) - skill / 400.0):
            pay = int(pay * random.uniform(0.6, 0.85) / 10) * 10           # うまくいかない日も
            notes.append("仕事がうまくいかず、叱られた")
        if pay:
            L.player_state()["money"] += pay
        gain = L.train("work", 0.5 * h) if h >= 0.25 else 0
        return {"start": s, "end": end, "hours": round(raw, 2), "paid_h": round(h, 2), "pay": pay, "skill": gain, "notes": notes}

    def _coworkers(self, s, e):
        """職場での出会い. 画面を見ていないので, 声をかけられても気づけない (無難な対応)."""
        app = self.app
        out = []
        cur = {"kind": "work", "place": "office", "with": None}
        rate = float(app.outdoor.cfg()["rate_work"])
        if random.random() >= 1 - math.exp(-rate * (e - s) / 3600.0):
            return out
        if app.street.pending():
            return out
        r = app.street.happen(cur, s + random.random() * (e - s))
        if r:
            res = app.street.resolve("nod" if app.street.pending()["type"] == "call" else "pass", auto=True)
            out.append(((r.get("text") or "").strip("（）") + "。" + (res or {}).get("text", "").split("\n")[0].strip("（）")))
        return out

    def _messages(self, t0, t1):
        """離れているキャラから届いたメッセージ. 返事が遅れた受け止め方は, 性格 (absence) と信頼しだい."""
        app = self.app
        out = []
        h = (t1 - t0) / 3600.0
        for cid, char in app.chars.items():
            if app.bonds.together(cid) or app.bonds.stage(cid) == "known":
                continue
            st = app.state(cid)
            if st.get("approach"):
                continue
            ctx = app.context(char, st, datetime.fromtimestamp(t1))
            rate = float(app.presence.cfg().get("approach_apart_rate_per_hour", 0.25)) * app.presence.eagerness_apart(ctx) \
                * float(app.traits(char).get("approach", 1))
            if random.random() >= 1 - math.exp(-rate * min(h, 12)):
                continue
            sent = t0 + random.random() * (t1 - t0)
            e = app.presence.fire(char, st, t1, ctx)
            if not e:
                continue
            e["t"] = sent
            st["approach"]["until"] = t1 + 30 * 60          # 開いてから少しのあいだは, 返事ができる
            late = (t1 - sent) / 3600.0
            k = float(app.traits(char).get("absence", 1)) * max(0.2, 1.3 - st["params"].get("trust", 40) / 100.0)
            pen = -round(min(8.0, 0.6 * late) * k, 1)
            if pen <= -0.5:
                app.apply_effects(st, {"mood": pen})
                if pen <= -3:
                    app.life.add_reason(st, "player", "bad", "%sからメッセージの返事が来ない" % app.pronouns(char)[2], t1, told=False,
                                        action="_offline")
            app.save_log(cid)
            app.save_state(cid)
            out.append({"cid": cid, "name": char.get("name", ""), "t": sent, "text": e.get("text", ""), "mood": pen,
                        "approach": st["approach"]["id"]})
        return out

    @staticmethod
    def _summary(rep):
        parts = []
        for w in rep["works"]:
            parts.append("%s〜%s 仕事（%s円）%s" % (datetime.fromtimestamp(w["start"]).strftime("%m/%d %H:%M"),
                                              datetime.fromtimestamp(w["end"]).strftime("%H:%M"), format(w["pay"], ","),
                                              "・" + "・".join(w["notes"]) if w["notes"] else ""))
        if not parts:
            parts.append("家で静かに過ごした")
        if rep["messages"]:
            parts.append("メッセージ %d 件" % len(rep["messages"]))
        return "画面を閉じていたあいだ: " + "／".join(parts)

    def report(self):
        rep = self.app.life.player_state().get("offline_report")
        return rep if rep and not rep.get("seen") else None

    def ack(self):
        rep = self.app.life.player_state().get("offline_report")
        if rep:
            rep["seen"] = True
            self.app.life.save_player()
        return {"ok": True}
