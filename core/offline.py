"""オフラインモード: 画面を閉じている間 (心拍が途絶えている間) の, あなたの過ごし方 = 曜日ごとの行動パターン.

設定 (全体共通, settings.offline):
  {"enabled": true, "days": {"mon": [{"at": "00:00", "do": "sleep"}, {"at": "07:00", "do": "rest"},
                                    {"at": "09:00", "do": "work"}, {"at": "18:00", "do": "shopping", "place": "shopping_street"}, ...],
                             ..., "sun": [...]}}
  各行動はその時刻から, 次の行動の時刻まで. 行動は 寝る・休む・家で静かに・仕事・買い物・散歩・カフェ・家事・研鑽 (一人の時間と同じ).
  以前の設定 (曜日ごとの勤務時間 work) は, この流れの「仕事」に読み替える.
画面を閉じていた間は, この流れに沿って過ごしたことにする (次に開いたとき, 時系列のまとめを一度だけ見せる).
- 仕事: 給料・体力・仕事スキル. 体力や仕事スキルしだいで, うまくいかない (給料が減る・叱られる)・早退・残業も起きる.
  職場で同僚に会うこともある (気づけないので無難な対応)
- 買い物・散歩・カフェ: 一人の時間と同じ結果 (買うものリストの品を買う など). 出先での出会いも (気づけないので無難な対応)
- 家事・研鑽: 一人の時間と同じ (洗剤・本があるとはかどる)
- 予定どおりにいかないこともある: 雨や雪で散歩をやめる, 疲れて家事や研鑽を飛ばす, 疲れきっていて出かけるのをやめる
- 寝る・休む・家で静かに: 体力が戻る (寝ていると早い). 家では誰にも会わない
- 離れているキャラから, メッセージ (働きかけ) が届くこともある. すぐには返せない: 返事の遅れの受け止め方は性格・間柄しだい
短い離席 (min_minutes 未満) は対象にしない. 結果は player.json の offline_report にまとめ, 次に開いたとき一度だけ見せる.
"""
import math
import random
import time
from datetime import datetime, timedelta

DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DO_LABEL = {"sleep": "寝る", "rest": "休む", "home": "家で静かに過ごす", "work": "仕事", "shopping": "買い物", "walk": "散歩",
            "cafe": "カフェで過ごす", "chores": "家事", "practice": "研鑽"}
WEEKDAY = [{"at": "00:00", "do": "sleep"}, {"at": "07:00", "do": "rest"}, {"at": "09:00", "do": "work"},
           {"at": "18:00", "do": "shopping", "place": "shopping_street"}, {"at": "19:00", "do": "rest"}, {"at": "23:00", "do": "sleep"}]
WEEKEND = [{"at": "00:00", "do": "sleep"}, {"at": "09:00", "do": "rest"}, {"at": "11:00", "do": "chores"},
           {"at": "13:00", "do": "walk", "place": "park"}, {"at": "15:00", "do": "home"},
           {"at": "17:00", "do": "shopping", "place": "mall"}, {"at": "18:30", "do": "rest"}, {"at": "23:30", "do": "sleep"}]
DEFAULT_DAYS = {d: [dict(b) for b in (WEEKDAY if i < 5 else WEEKEND)] for i, d in enumerate(DAY_KEYS)}
DEFAULT = {"enabled": True, "min_minutes": 30}


def _hm(s):
    h, m = str(s).split(":")
    return int(h) * 60 + int(m)


def from_work(work):
    """以前の設定 (曜日ごとの勤務時間) を, 行動パターンに読み替える."""
    days = {}
    for i, d in enumerate(DAY_KEYS):
        w = (work or {}).get(d) or {}
        on = w.get("on", i < 5)
        if on:
            days[d] = [{"at": "00:00", "do": "sleep"}, {"at": "07:00", "do": "rest"}, {"at": w.get("from", "09:00"), "do": "work"},
                       {"at": w.get("to", "18:00"), "do": "rest"}, {"at": "23:00", "do": "sleep"}]
        else:
            days[d] = [dict(b) for b in WEEKEND]
    return days


class Offline:
    def __init__(self, app):
        self.app = app

    def cfg(self):
        user = self.app.settings.get("offline") or {}
        c = dict(DEFAULT)
        c.update({k: v for k, v in user.items() if k not in ("work", "days")})
        days = user.get("days") or (from_work(user["work"]) if user.get("work") else DEFAULT_DAYS)
        c["days"] = {d: sorted([dict(b) for b in (days.get(d) or DEFAULT_DAYS[d]) if b.get("do") in DO_LABEL],
                               key=lambda b: _hm(b.get("at", "00:00"))) for d in DAY_KEYS}
        return c

    def blocks(self, t0, t1):
        """[t0, t1) に重なる行動 [(開始, 終了, 行動)] (その日の最初の行動の前は, 前の日の最後の行動の続き)."""
        days = self.cfg()["days"]
        starts = []
        day = datetime.fromtimestamp(t0).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        while day.timestamp() < t1 + 86400:
            for b in days[DAY_KEYS[day.weekday()]]:
                starts.append(((day + timedelta(minutes=_hm(b["at"]))).timestamp(), b))
            day += timedelta(days=1)
        out = []
        for i, (s, b) in enumerate(starts[:-1]):
            e = starts[i + 1][0]
            s2, e2 = max(s, t0), min(e, t1)
            if e2 > s2:
                out.append((s2, e2, b))
        return out

    def segments(self, t0, t1):
        """[t0, t1) のうち, 仕事の時間 [(開始, 終了)] (15 分以上)."""
        return [(s, e) for s, e, b in self.blocks(t0, t1) if b["do"] == "work" and e - s >= 900]

    @staticmethod
    def _night(t):
        h = datetime.fromtimestamp(t).hour
        return h >= 23 or h < 7

    # ------------------------------------------------------------------ 閉じていた間を過ごす
    def simulate(self, t0, t1):
        """画面を閉じていた t0 (最後の心拍) 〜 t1 (いま). 行動パターンに沿って過ごした結果のまとめを返す (対象でなければ None)."""
        app, L = self.app, self.app.life
        c = self.cfg()
        if not c.get("enabled") or t1 - t0 < float(c.get("min_minutes", 30)) * 60:
            return None
        ps = L.player_state()
        econ = L.econ()
        rec = float(econ.get("stamina_recover", 5))
        rec_rest = float(econ.get("stamina_recover_rest", 9))
        rec_night = float(econ.get("stamina_recover_sleep", 12))
        per_h = float(econ.get("stamina_per_work_hour", 9))
        stamina = float(ps.get("stamina", 100))
        s0 = stamina
        L.tick_world(t1)                       # 市場・定期収入など (体力はこのあと, 過ごし方に合わせて決め直す)
        money0 = int(ps["money"])
        works, meets, timeline = [], [], []
        t = t0

        def recover(a, b, rate):
            nonlocal stamina
            x = a
            while x < b:
                y = min(b, x + 1800)
                r = rate if rate is not None else (rec_night if self._night(x) else rec)
                stamina = min(100.0, stamina + r * (y - x) / 3600.0)
                x = y

        for s, e, b in self.blocks(t0, t1):
            s = max(s, t)                          # 残業などで, 前の行動が延びたぶんは後ろへ
            if e - s < 60:
                continue
            do, h = b["do"], (e - s) / 3600.0
            ent = {"t": s, "end": e, "do": do, "label": DO_LABEL[do], "text": "", "skipped": False}
            if do == "sleep":
                recover(s, e, rec_night)
                ent["text"] = "寝ていた"
            elif do in ("rest", "home"):
                recover(s, e, rec_rest if do == "rest" else None)
                ent["text"] = "家で休んでいた" if do == "rest" else "家で静かに過ごしていた"
            elif do == "work":
                w = self._work(s, e, stamina)
                stamina = max(0.0, stamina - per_h * w["hours"])
                works.append(w)
                m = self._coworkers(w["start"], w["end"])
                meets += m
                ent.update(end=w["end"], text="仕事（%s円）%s" % (format(w["pay"], ","), "・" + "・".join(w["notes"]) if w["notes"] else ""),
                           meets=m)
                t = w["end"]
                timeline.append(ent)
                continue
            else:
                skip = self._skip(do, b, s, stamina)
                if skip:
                    recover(s, e, None)
                    ent.update(text=skip, skipped=True)
                else:
                    ps["stamina"] = stamina
                    res = app.solo.result(do, h, e, b.get("skill"), b.get("place"))
                    stamina = float(ps.get("stamina", stamina))
                    ent["text"] = res["text"].strip("（）")
                    if res.get("bought"):
                        ent["bought"] = res["bought"]
                    if do in ("shopping", "walk", "cafe"):
                        m = self._outing_meets(b.get("place") or {"cafe": "cafe"}.get(do, "town"), s, e)
                        meets += m
                        ent["meets"] = m
            t = max(t, e)
            timeline.append(ent)
        ps["stamina"] = round(stamina, 1)
        L.save_player()
        msgs = self._messages(t0, t1)
        rep = {"from": t0, "to": t1, "works": works, "timeline": timeline, "pay": int(ps["money"]) - money0,
               "bought": [x for ent in timeline for x in ent.get("bought") or []],
               "stamina": [round(s0, 1), round(stamina, 1)], "meets": meets, "messages": msgs, "seen": False}
        ps["offline_report"] = rep
        L.save_player()
        app.solo.note("offline", self._summary(rep), t1)
        return rep

    def _skip(self, do, b, s, stamina):
        """予定どおりにいかないこと: 雨・雪で散歩をやめる, 疲れて家事・研鑽を飛ばす, 疲れきって出かけない. やめた理由 or None."""
        from .outdoor import PLACES, weather
        w = weather(datetime.fromtimestamp(s))
        place = PLACES.get(b.get("place") or "") or {}
        if do == "walk" and w["id"] in ("rain", "snow") and place.get("outdoor", True) and random.random() < 0.7:
            return "%sなので散歩はやめて、家で過ごした" % w["label"]
        if do in ("shopping", "walk", "cafe") and stamina < 15 and random.random() < 0.6:
            return "疲れきっていて、%sには出かけなかった" % DO_LABEL[do]
        if do in ("chores", "practice") and stamina < 25 and random.random() < 0.6:
            return "疲れていて、%sは飛ばした" % DO_LABEL[do]
        return None

    def _outing_meets(self, place, s, e):
        """出先での出会い. 画面を見ていないので, 声をかけられても気づけない (無難な対応)."""
        app = self.app
        cur = {"kind": "out", "place": place, "with": None}
        rate = app.outdoor.rate(cur, datetime.fromtimestamp(s))
        if app.street.pending() or random.random() >= 1 - math.exp(-rate * (e - s) / 3600.0):
            return []
        r = app.street.happen(cur, s + random.random() * (e - s))
        if not r:
            return []
        res = app.street.resolve("nod" if app.street.pending()["type"] == "call" else "pass", auto=True)
        return [(r.get("text") or "").strip("（）") + "。" + (res or {}).get("text", "").split("\n")[0].strip("（）")]

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
        for x in rep.get("timeline") or []:
            if x["do"] in ("sleep", "rest", "home"):
                continue
            parts.append("%s〜%s %s" % (datetime.fromtimestamp(x["t"]).strftime("%m/%d %H:%M"),
                                       datetime.fromtimestamp(x["end"]).strftime("%H:%M"), x["text"]))
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
