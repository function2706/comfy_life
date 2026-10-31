"""オフラインモード: 画面を閉じている間 (心拍が途絶えている間) の, あなたの過ごし方 = 曜日ごとの行動パターン.

設定 (全体共通, settings.offline):
  {"enabled": true, "days": {"mon": [{"at": "00:00", "do": "sleep"}, {"at": "07:00", "do": "rest"},
                                    {"at": "09:00", "do": "work"}, {"at": "18:00", "do": "out", "place": "supermarket"}, ...],
                             ..., "sun": [...]}}
  各行動はその時刻から, 次の行動の時刻まで. 行動は 寝る・休む・家で静かに・仕事・外出 (行き先しだいで, 歩く・買い物・お茶など)・家事・研鑽
  (一人の時間と同じ). 以前の設定 (曜日ごとの勤務時間 work) は, この流れの「仕事」に読み替える.
  以前の「散歩・買い物・カフェ」(walk / shopping / cafe) は「外出 + 行き先」に読み替える (起動時に設定も書き換える: store.migrate_routine).
画面を閉じていた間は, この流れに沿って過ごしたことにする (次に開いたとき, 時系列のまとめを一度だけ見せる).
- 仕事: 給料・体力・仕事スキル. 体力や仕事スキルしだいで, うまくいかない (給料が減る・叱られる)・早退・残業も起きる.
  職場で同僚に会うこともある (気づけないので無難な対応)
- 外出: 一人の時間と同じ結果 (店なら買うものリストの品を買う など). 出先での出会いも (気づけないので無難な対応)
- 家事・研鑽: 一人の時間と同じ (洗剤・本があるとはかどる)
- 予定どおりにいかないこともある: 雨や雪で散歩をやめる, 疲れて家事や研鑽を飛ばす, 疲れきっていて出かけるのをやめる
- 寝る・休む・家で静かに: 体力が戻る (寝ていると早い). 家では誰にも会わない
- 離れているキャラから, メッセージ (働きかけ) が届くこともある. すぐには返せない: 返事の遅れの受け止め方は性格・間柄しだい
短い離席 (min_minutes 未満) は対象にしない. 結果は player.json の offline_report にまとめ, 次に開いたとき一度だけ見せる.
"""
import math
import random
import re
import time
from datetime import datetime, timedelta

from .places import LEGACY_DO, OUT_PLACES, open_state, solo_kind
from .places import effort as effort_of
from .places import HOME_ME
from . import geo as geo_mod
from .geo import HOW_LABEL

DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DO_LABEL = {"sleep": "寝る", "rest": "休む", "home": "家で静かに過ごす", "work": "仕事", "out": "外出", "chores": "家事",
            "kakeibo": "家事（家計簿をつける）", "practice": "研鑽", "meal": "食事",
            "parttime": "アルバイト", "jog": "ジョギング", "read": "本を読む", "movie": "映画を観る"}
CHORE_PARTS = {"": "全部", "mess": "部屋の片付け", "dishes": "洗い物", "laundry": "洗濯", "trash": "ゴミ出し"}
JOG_AT = ("park", "riverside", "town")
MEAL_HOW = {"cook": "自炊", "out": "外食", "buy": "買って食べる"}
MEAL_PLACES = {"out": ["teishoku", "ramen", "fastfood", "family", "restaurant", "cafe"], "buy": ["convenience", "supermarket", "station"]}
WEEKDAY = [{"at": "00:00", "do": "sleep"}, {"at": "07:00", "do": "meal", "how": "cook"}, {"at": "07:30", "do": "rest"},
           {"at": "09:00", "do": "work"}, {"at": "12:00", "do": "meal", "how": "buy", "place": "convenience"}, {"at": "12:45", "do": "work"},
           {"at": "18:00", "do": "out", "place": "supermarket"}, {"at": "19:00", "do": "meal", "how": "cook"}, {"at": "19:45", "do": "rest"},
           {"at": "23:00", "do": "sleep"}]
WEEKEND = [{"at": "00:00", "do": "sleep"}, {"at": "09:00", "do": "meal", "how": "cook"}, {"at": "09:45", "do": "rest"},
           {"at": "11:00", "do": "chores"}, {"at": "12:30", "do": "meal", "how": "out", "place": "teishoku"},
           {"at": "13:30", "do": "out", "place": "park"}, {"at": "15:00", "do": "home"},
           {"at": "17:00", "do": "out", "place": "mall"}, {"at": "18:30", "do": "meal", "how": "cook"}, {"at": "19:15", "do": "rest"},
           {"at": "23:30", "do": "sleep"}]


def _peek(it):
    """(いまの行動, 次の行動 or None) を順に (次の行動の時刻を見て, 残業を打ち切る)."""
    it = iter(it)
    cur = next(it, None)
    while cur is not None:
        nxt = next(it, None)
        yield cur, nxt
        cur = nxt


def normalize(b):
    """行動パターンの 1 行を今の語彙に (以前の 散歩・買い物・カフェ → 外出 + 行き先. 行き先は公共の表から)."""
    b = dict(b)
    if b.get("do") in LEGACY_DO:
        b["place"] = b.get("place") or LEGACY_DO[b["do"]]
        b["do"] = "out"
    if b.get("do") == "out" and b.get("place") not in OUT_PLACES:
        b["place"] = "park"
    if b.get("do") == "meal":                 # 食事: 自炊 / 外食 (食べに行く店) / 買って食べる (コンビニなど)
        b["how"] = b.get("how") if b.get("how") in MEAL_HOW else "cook"
        if b["how"] == "cook":
            b.pop("place", None)
        elif b.get("place") not in MEAL_PLACES[b["how"]]:
            b["place"] = MEAL_PLACES[b["how"]][0]
        return b
    b.pop("how", None)
    if b.get("do") == "jog":                   # ジョギング: 走れる行き先
        b["place"] = b.get("place") if b.get("place") in JOG_AT else "park"
        return b
    if b.get("do") == "chores" and b.get("skill") not in CHORE_PARTS:     # 家事: 全部か一つ (skill に家事の名前)
        b.pop("skill", None)
    if b.get("do") not in ("practice", "chores"):
        b.pop("skill", None)
    if b.get("do") != "out":
        b.pop("place", None)
    return b
DEFAULT_DAYS = {d: [dict(b) for b in (WEEKDAY if i < 5 else WEEKEND)] for i, d in enumerate(DAY_KEYS)}
DEFAULT = {"enabled": True, "min_minutes": 30}


def _hm(s):
    h, m = str(s).split(":")
    return int(h) * 60 + int(m)


SUMMARY_HEAD = "画面を閉じていたあいだ: "
_PART = re.compile(r"(\d\d)/(\d\d) (\d\d):(\d\d)〜(\d\d):(\d\d) ")


def parse_summary(note):
    """閉じていた間のまとめ (一人の時間の記録 kind offline. Offline._summary) を, 行動ごと [{s, e, text}] に戻す.
    まとめは戻った日の記録だが, 中身はそれぞれの日の出来事 (日記はこれで, その日に振り分ける). 寝る・休む・家で静かには載っていない."""
    text = note.get("text") or ""
    if not text.startswith(SUMMARY_HEAD):
        return []
    body = text[len(SUMMARY_HEAD):]
    ms = list(_PART.finditer(body))
    out = []
    t1 = datetime.fromtimestamp(note["t"])
    for i, m in enumerate(ms):
        seg = body[m.end():ms[i + 1].start() if i + 1 < len(ms) else len(body)]
        seg = re.sub(r"／メッセージ \d+ 件$", "", seg).rstrip("／")
        mo, d, h, mi, h2, mi2 = (int(x) for x in m.groups())
        y = t1.year - (1 if (mo, d) > (t1.month, t1.day) else 0)          # 年をまたいだまとめ
        try:
            s = datetime(y, mo, d, h, mi)
        except ValueError:
            continue
        e = s.replace(hour=h2, minute=mi2)
        if e <= s:
            e += timedelta(days=1)
        out.append({"s": s.timestamp(), "e": e.timestamp(), "text": seg})
    return out


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
        c["days"] = {d: sorted([normalize(b) for b in (days.get(d) or DEFAULT_DAYS[d]) if normalize(b).get("do") in DO_LABEL],
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
        use_plan = app.planner.active()          # 予定・未指定時コマンドを組んでいれば, そちらが先 (core/planner.py)
        if (not c.get("enabled") and not use_plan) or t1 - t0 < float(c.get("min_minutes", 30)) * 60:
            return None
        ps = L.player_state()
        econ = L.econ()
        rec = float(econ.get("stamina_recover", 5))
        rec_rest = float(econ.get("stamina_recover_rest", 9))
        rec_night = float(econ.get("stamina_recover_sleep", 12))
        per_h = float(econ.get("stamina_per_work_hour", 9))
        stamina = float(ps.get("stamina", 100))
        s0 = stamina
        cap = app.body.stamina_cap()
        money0 = int(ps["money"])
        # 市場・定期収入・お腹と栄養などは, 行動の順に時間を進めながら (食事の前に空腹になる. 体力はこのあと, 過ごし方に合わせて決め直す)
        works, meets, timeline = [], [], []
        t = t0

        def recover(a, b, rate):
            nonlocal stamina
            x = a
            while x < b:
                y = min(b, x + 1800)
                r = rate if rate is not None else (rec_night if self._night(x) else rec)
                stamina = min(cap, stamina + r * (y - x) / 3600.0)
                x = y

        app.trace.add("offline", "閉じていた間を過ごす", None, t1, start=t0, end=t1, use_plan=use_plan, routine=c.get("enabled"),
                      fallback=[app.planner.label(f) for f in app.planner.rec()["fallback"]], plans=len(app.planner.rec()["items"]),
                      stamina=stamina, money=money0)
        source = self._plan_blocks(t0, t1, lambda: stamina, c.get("enabled")) if use_plan else self.blocks(t0, t1)
        back_leg = None

        def go_home():
            """出先から家へ (前の行動の帰り道. 終わった時刻 t から)."""
            nonlocal t, stamina, back_leg
            if not back_leg:
                return
            lg, dest = back_leg
            back_leg = None
            stamina = self._pay_leg(lg, HOME_ME, t, stamina, dest)
            timeline.append({"t": t, "end": t + lg["min"] * 60, "do": "move", "label": "移動",
                             "text": "%sから家へ（%s・%d分%s）%s" % (app.places.label(dest), HOW_LABEL[lg["how"]], round(lg["min"]),
                                                               "・%s円" % format(lg["fare"], ",") if lg["fare"] else "",
                                                               "。" + lg["note"] if lg.get("note") else ""), "skipped": False, "plan": None})
            t += lg["min"] * 60

        for (s, e, b), nb in _peek(source):
            fixed = nb[0] if nb and nb[2]["do"] in ("exam", "appoint") else None     # 次が時刻の決まったこと (試験・約束): 残業はその前まで
            # 出先にいるまま続ける: 同じ場所での次の行動 (昼休みのあとも職場) / 出先のすぐあとの食事 (近くで食べる)
            stay = bool(back_leg) and (self._dest(b) == back_leg[1] or (
                b["do"] == "meal" and b.get("how") in ("out", "buy") and max(s, t) - t < 1800))
            if not stay:
                go_home()
            s = max(s, t)                          # 残業などで, 前の行動が延びたぶんは後ろへ
            if e - s < 60:
                continue
            L.tick_world(s)
            do, h = b["do"], (e - s) / 3600.0
            pre_skip = self._skip(do, b, s, stamina) if do in ("out", "jog") else None
            dest = None if pre_skip or stay or geo_mod.INSTANT else self._dest(b)
            if dest:                               # 出かける行動: 行き帰りの移動 (core/geo.py. 予定の時刻は出る時刻)
                try:
                    go = app.geo.leg(HOME_ME, dest, "run" if do == "jog" else None, s)
                except ValueError:
                    go = None
                if go and go["min"] >= 1:
                    stamina = self._pay_leg(go, dest, s, stamina, HOME_ME)
                    try:                           # 帰り: 乗っていった自転車・車があれば, それで
                        back = app.geo.leg(dest, HOME_ME, "run" if do == "jog" else go["how"] if go["how"] in ("bike", "car") else None,
                                           e)
                    except ValueError:
                        back = app.geo.leg(dest, HOME_ME, "taxi", e, rand=False)
                    timeline.append({"t": s, "end": s + go["min"] * 60, "do": "move", "label": "移動",
                                     "text": "%sへ（%s・%d分%s）%s" % (app.places.label(dest), HOW_LABEL[go["how"]], round(go["min"]),
                                                                   "・%s円" % format(go["fare"], ",") if go["fare"] else "",
                                                                   "。" + go["note"] if go.get("note") else ""), "skipped": False, "plan": None})
                    s = s + go["min"] * 60
                    e = max(e, s + 600)
                    h = (e - s) / 3600.0
                    back_leg = (back, dest)
            if do == "exam":                       # 資格の試験 (受けたかどうかは quals.daily. ここでは時間がふさがるだけ)
                recover(s, e, None)
                timeline.append({"t": s, "end": e, "do": "exam", "label": "資格の試験", "text": "%sの試験を受けた" % b.get("label", ""),
                                 "skipped": False, "plan": b.get("_plan")})
                t = max(t, e)
                continue
            if do == "appoint":                    # 相手との約束: 約束が先 (自動で過ごした分は, 良い影響が出にくい)
                text = self._appoint(b["appoint"], s)
                recover(s, e, None)
                timeline.append({"t": s, "end": e, "do": "appoint", "label": "約束", "text": text, "skipped": False,
                                 "plan": b.get("_plan")})
                t = max(t, e)
                continue
            ent = {"t": s, "end": e, "do": do, "label": DO_LABEL[do], "text": "", "skipped": False}
            if b.get("_plan"):
                ent["plan"] = b["_plan"]
            if do in ("chores", "jog") or (do == "practice" and b.get("skill")):
                ent["label"] = app.planner.label(b)
            if do == "out":
                ent["place"] = b.get("place")
                ent["label"] = "外出（%s）" % app.places.label(b.get("place"))
            if do == "meal":
                how = b.get("how") or "cook"
                ent["label"] = "%s（%s%s）" % (self._meal_name(s), MEAL_HOW[how], "・" + app.places.label(b["place"]) if b.get("place") else "")
                text, ok = app.body.routine_meal(b, s)
                ent.update(text=text, skipped=not ok)
                recover(s, e, None)
                t = max(t, e)
                timeline.append(ent)
                continue
            if do == "sleep":
                recover(s, e, rec_night)
                ent["text"] = "寝ていた"
            elif do == "kakeibo":                 # 家計簿: 15 分ほどで書いて, あとは家で過ごす
                ps["stamina"] = stamina
                recover(s, e, None)
                if stamina < 15 and random.random() < 0.5:
                    ent.update(text="疲れていて、家計簿は明日にした", skipped=True)
                else:
                    ent["text"] = app.kakeibo.write(min(e, s + 900))["text"]
            elif do in ("rest", "home"):
                recover(s, e, rec_rest if do == "rest" else None)
                ent["text"] = "家で休んでいた" if do == "rest" else "家で静かに過ごしていた"
            elif do == "parttime":            # アルバイト: シフトと重なった分だけ (シフトが無ければ家で過ごす)
                if not app.earn.pt() or app.body.level() >= 3:
                    recover(s, e, None)
                    ent.update(text="アルバイトはしていないので、家で過ごした" if not app.earn.pt() else "体調が悪くて、バイトを休んだ", skipped=True)
                else:
                    ps["stamina"] = stamina
                    pay, ph, _ = app.earn.pt_pay(s, e)
                    stamina = float(ps.get("stamina", stamina))
                    if pay:
                        ps["money"] += pay
                        L.ledger(e, pay, "income", "バイト代")
                    app.body.add_exercise(2.0 * ph)
                    ent["text"] = "%s（%s円）" % (app.earn.job(app.earn.pt()["job"])["label"], format(pay, ",")) if ph \
                        else "シフトの時間ではなかったので、家で過ごした"
                    if not ph:
                        recover(s, e, None)
            elif do == "work":
                w = self._work(s, e, stamina, fixed)
                stamina = max(0.0, stamina - per_h * w["hours"])
                app.body.add_exercise(2.0 * w["hours"])
                works.append(w)
                m = self._coworkers(w["start"], w["end"])
                meets += m
                ent.update(end=w["end"], text="仕事（%s円）%s" % (format(w["pay"], ","), "・" + "・".join(w["notes"]) if w["notes"] else ""),
                           meets=m)
                t = w["end"]
                timeline.append(ent)
                continue
            else:
                skip = pre_skip if do in ("out", "jog") else self._skip(do, b, s, stamina)
                if skip:
                    recover(s, e, None)
                    ent.update(text=skip, skipped=True)
                else:
                    ps["stamina"] = stamina
                    if do == "out":                 # 閉まる時刻までしかいられない
                        until = open_state(b.get("place") or "", datetime.fromtimestamp(s))["until"]
                        if until and until < e:
                            h = max(0.0, (until - s) / 3600.0)     # もう閉まっていた (until が始めより前) なら 0
                            ent["text_extra"] = "閉まる時間になったので帰った"
                    res = app.solo.result(do, h, e, b.get("skill"), b.get("place"))
                    app.body.add_exercise(self._move(do, b.get("place")) * h)          # 体を動かした分 (閉じていた間)
                    stamina = float(ps.get("stamina", stamina))
                    ent["text"] = res["text"].strip("（）") + ("。" + ent.pop("text_extra") if ent.get("text_extra") else "")
                    if res.get("bought"):
                        ent["bought"] = res["bought"]
                    if do == "out":
                        m = self._outing_meets(b.get("place") or "town", s, e)
                        meets += m
                        ent["meets"] = m
            t = max(t, e)
            timeline.append(ent)
        go_home()
        for x in timeline:
            app.trace.add("offline", "%s: %s" % (x.get("label"), (x.get("text") or "")[:80]), None, x["t"], end=x.get("end"), do=x["do"],
                          skipped=x.get("skipped"), plan=x.get("plan"))
        for w in works:
            app.trace.add("offline", "仕事の結果", None, w["start"], end=w["end"], pay=w["pay"], paid_h=w["paid_h"], notes=w["notes"])
        L.tick_world(t1)
        if use_plan:
            app.planner.purge(t1)                 # 過ぎた日の予定を消す
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

    def _plan_blocks(self, t0, t1, stamina_now, routine_on):
        """予定の順番で, 閉じていた間の行動を決める: 予定 → できなければ未指定時コマンド (優先度順) → 設定の行動パターン → 何もしない.
        約束の時間は約束. 体力は過ごしながら変わるので, 決めるたびに今の値を見る.
        空き時間 (予定の無い時間) は, 行動パターンの仕事・アルバイト (勤め) があればそれが先. 予定を一つも組んでいない日は,
        行動パターンどおり (未指定時コマンドは, 予定を組んだ日の空き時間と, 予定ができなかったときのため)."""
        app = self.app
        P = app.planner
        fb = P.rec()["fallback"]
        planned = {x["date"] for x in P.rec()["items"]}
        for s, e, kind, x in P.slots(t0, t1):
            if kind == "appoint":
                yield s, e, {"do": "appoint", "appoint": x["id"], "_plan": {"src": "appoint"}}
                continue
            if kind == "exam":
                yield s, e, {"do": "exam", "label": x, "_plan": {"src": "exam"}}
                continue
            if kind == "gap" and routine_on:
                for s2, e2, b2 in self._gap_blocks(s, e, planned, stamina_now):
                    yield s2, e2, b2
                continue
            why = None
            meta = {"orig": P.label(x), "at": x["at"]} if x else {"orig": None, "at": None}
            if kind == "plan":
                b = {k: v for k, v in x.items() if k in ("do", "place", "how", "skill")}
                why = P.cannot(b, s, stamina_now())
                if not why:
                    yield s, e, dict(b, _plan=dict(meta, src="plan", cut=self._cut(b, s, e, t1)))
                    continue
            f = next((f for f in fb if not P.cannot(f, s, stamina_now())), None)
            if f:
                yield s, e, dict(f, _plan=dict(meta, src="fallback", why=why or "予定なし", label=P.label(f)))
                continue
            if routine_on:
                first = True
                for s2, e2, b2 in self.blocks(s, e):
                    yield s2, e2, dict(b2, _plan=dict(meta, src="routine", why=why or "予定なし") if (x and first) else None)
                    first = False
                continue
            yield s, e, {"do": "home", "_plan": dict(meta, src="none", why=why or "予定なし")}

    def _gap_blocks(self, s, e, planned, stamina_now):
        """予定の無い時間 [s, e): 行動パターンの勤め (仕事・アルバイト) はそのとおり. 予定を組んでいない日は行動パターンどおり.
        予定を組んだ日の, 勤め以外の空き時間は, 未指定時コマンド (できるもの) → 行動パターン."""
        P = self.app.planner
        fb = P.rec()["fallback"]
        meta = {"orig": None, "at": None}
        for s2, e2, b2 in self.blocks(s, e):
            day = datetime.fromtimestamp(s2).strftime("%Y-%m-%d")
            if b2["do"] in ("work", "parttime") or day not in planned or not fb:
                yield s2, e2, dict(b2, _plan=None)
                continue
            # 同じ日に予定があるときの空き時間: 未指定時コマンドから (体力はその場の値で見る)
            f = next((f for f in fb if not P.cannot(f, s2, stamina_now())), None)
            if f:
                yield s2, e2, dict(f, _plan=dict(meta, src="fallback", why="予定なし", label=P.label(f)))
            else:
                yield s2, e2, dict(b2, _plan=None)

    def _cut(self, b, s, e, t1):
        """次の予定の時刻で切り上げたか (家事・研鑽などの目安・その店でのふだんの買い物の長さより短い)."""
        from .planner import NATURAL
        nat = NATURAL.get(b["do"]) or (self.app.solo.shop_typical(b.get("place")) * 60
                                       if b["do"] == "out" and solo_kind(b.get("place")) == "shopping" else 0)
        return bool(nat) and e - s < nat and e < t1

    def _appoint(self, aid, s):
        """閉じていた間の約束: 約束の場所へ行って会う. 自動で過ごした分は, 良い影響が出にくく, 仲の深まりも小さい."""
        app = self.app
        try:
            x = app.appoint.get(aid)
        except KeyError:
            return "約束はもう無かった"
        char = app.chars.get(x["cid"]) or {}
        if x["status"] not in ("set", "waiting"):
            return "%sとの約束は%s" % (char.get("name", ""), x["status"])
        if (x.get("plan") or {}).get("noshow"):
            x["status"] = "stood_up"
            x["sorry_at"] = s + random.uniform(30, 180) * 60
            app.appoint.save()
            return "%sで待っていたが、%sは来なかった" % (app.places.label(x["place"]), char.get("name", ""))
        try:
            r = app.appoint._meet(x, s, extra_opts={"auto_weak": True})
        except ValueError as ex:                 # 会えたが, いっしょにすることはできなかった
            x["status"] = "met"
            app.appoint.save()
            return "%sで%sと会った（約束。%s）" % (app.places.label(x["place"]), char.get("name", ""), ex)
        return "%sで%sと会った（約束）。%s" % (app.places.label(x["place"]), char.get("name", ""),
                                         ((r.get("entry") or {}).get("text") or "").split("\n")[0])

    def _auto_choice(self, typ):
        """出先で声をかけられた・見かけた: 予定の欄の方針 (無ければ無難な対応). その場にいないので, 読み違えることもある."""
        pol = self.app.planner.rec()["auto"].get("street")
        if not pol:
            return "nod" if typ == "call" else "pass", False
        choice = pol if typ == "call" else {"chat": "talk", "nod": "nod", "decline": "pass"}[pol]
        if random.random() < 0.25:              # その場にいないので, 相手の様子を読み違える
            choice = "nod" if typ == "call" else "pass"
        return choice, True

    def _dest(self, b):
        """行動パターンの 1 行で出かける先 (家でする行動なら None)."""
        do = b["do"]
        if do in ("out", "jog"):
            return b.get("place") or ("park" if do == "jog" else None)
        if do == "work":
            return "office"
        if do == "parttime":
            pt = self.app.earn.pt()
            return self.app.earn.job(pt["job"])["place"] if pt else None
        if do == "meal" and b.get("how") in ("out", "buy"):
            return b.get("place") or ("teishoku" if b["how"] == "out" else "convenience")
        return None

    def _pay_leg(self, lg, dest, t, stamina, frm):
        """閉じていた間の移動 1 回 (frm → dest): 運賃・歩いた分の疲れと運動・乗り物の置き場所. 体力を返す."""
        from .geo import FARE_NOTE
        app, L = self.app, self.app.life
        if lg["fare"]:
            L.player_state()["money"] -= lg["fare"]
            L.ledger(t, -lg["fare"], "transport", "%s（%s）" % (FARE_NOTE[lg["how"]], app.places.label(dest if dest != HOME_ME else frm)))
        ex, tired = app.geo.body_cost(lg, frm, dest)
        app.body.add_exercise(ex)
        app.geo.used(lg, dest)
        return max(0.0, stamina - tired)

    def _move(self, do, place):
        """行動パターンの行動で体を動かす量 (1 時間あたり)."""
        from .body import MOVE_PER_H
        if do == "chores":
            return MOVE_PER_H["chores"]
        if do == "jog":
            return MOVE_PER_H["jog"] * effort_of(place)
        if do == "out":
            from .places import effort
            k = solo_kind(place)
            return effort(place) * (MOVE_PER_H["walk"] if k == "walk" else MOVE_PER_H["see"] if k == "see" else
                                    MOVE_PER_H["shop"] if k == "shopping" else MOVE_PER_H["other"])
        return 0.0

    @staticmethod
    def _meal_name(t):
        h = datetime.fromtimestamp(t).hour
        return "朝食" if 4 <= h < 10 else "昼食" if 10 <= h < 15 else "夕食" if 15 <= h < 22 else "夜食"

    def _skip(self, do, b, s, stamina):
        """予定どおりにいかないこと: 雨・雪で散歩をやめる, 疲れて家事・研鑽を飛ばす, 疲れきって出かけない. やめた理由 or None."""
        from .outdoor import PLACES, weather
        w = weather(datetime.fromtimestamp(s))
        place = PLACES.get(b.get("place") or "") or {}
        if do == "out" and solo_kind(b.get("place")) == "walk" and w["id"] in ("rain", "snow") and place.get("outdoor", True) \
                and random.random() < 0.7:
            return "%sなので%sに出かけるのはやめて、家で過ごした" % (w["label"], place.get("label", ""))
        if do == "out":
            o = open_state(b.get("place") or "", datetime.fromtimestamp(s))
            if not o["open"]:
                return "%sは閉まっていた（%s）ので、家で過ごした" % (place.get("label", ""), o["note"])
        if do == "out" and stamina < 15 and random.random() < 0.6:
            return "疲れきっていて、%sには出かけなかった" % place.get("label", "")
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
        choice, weak = self._auto_choice(app.street.pending()["type"])
        res = app.street.resolve(choice, auto=True, weak=weak)
        return [(r.get("text") or "").strip("（）") + "。" + (res or {}).get("text", "").split("\n")[0].strip("（）")]

    def _work(self, s, e, stamina, limit=None):
        """予定の勤務 1 回. 体力・仕事スキルしだいで, うまくいかない・早退・残業. limit: 残業はこの時刻まで (次の試験・約束)."""
        L = self.app.life
        skill = L.skill("work")
        notes = []
        end = e
        lv = self.app.body.level()
        if lv >= 3 or (lv == 2 and random.random() < 0.4):           # 体調が悪くて休んだ
            return {"start": s, "end": s, "hours": 0.0, "paid_h": 0.0, "pay": 0, "skill": 0, "notes": ["体調が悪くて、仕事を休んだ"]}
        if random.random() < 0.03 + (0.35 if stamina < 25 else 0.12 if stamina < 45 else 0.0) + (0.3 if lv == 2 else 0.1 if lv == 1 else 0.0):
            end = s + (e - s) * random.uniform(0.3, 0.8)                  # 体調が悪くて早退
            notes.append("体調がすぐれず、早退した")
        elif random.random() < 0.15:
            end = e + random.uniform(0.5, 2.0) * 3600                       # 残業
            if limit:
                end = max(e, min(end, limit))
            if end > e:
                notes.append("残業になった")
        pay, h, raw = L.work_pay(s, end, record=True)
        if random.random() < max(0.03, 0.12 + (0.2 if stamina < 40 else 0.0) - skill / 400.0):
            pay = int(pay * random.uniform(0.6, 0.85) / 10) * 10           # うまくいかない日も
            notes.append("仕事がうまくいかず、叱られた")
        if pay:
            L.player_state()["money"] += pay
            L.ledger(end, pay, "income", "給料")
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
            choice, weak = self._auto_choice(app.street.pending()["type"])
            res = app.street.resolve(choice, auto=True, weak=weak)
            out.append(((r.get("text") or "").strip("（）") + "。" + (res or {}).get("text", "").split("\n")[0].strip("（）")))
        return out

    def _awake_slots(self, char, st, t0, t1):
        """t0〜t1 の 30 分ごとの, メッセージを送ってくる見込み [(時刻, 重み)] (寝ている・手が離せない時間は除く)."""
        from .presence import hour_factor
        app = self.app
        out = []
        t = t0
        while t < t1:
            d = datetime.fromtimestamp(t)
            sc = app.scheduled_scene(char, d)
            if not (sc.get("asleep") or sc.get("busy")):
                out.append((t, hour_factor(d)))
            t += 1800
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
            if st.get("approach") or st.get("msg_pending"):     # あなたのメッセージに返していないうちは, 別の話を送ってこない
                continue
            ctx = app.context(char, st, datetime.fromtimestamp(t1))
            # 送ってくるのは, 相手が起きていて手が空いている時間. 夜中・早朝にはまず送らない (presence.hour_factor)
            slots = self._awake_slots(char, st, t0, t1)
            if not slots:
                continue
            avail = sum(w for _, w in slots) / float(len(slots))
            rate = float(app.presence.cfg().get("approach_apart_rate_per_hour", 0.25)) * app.presence.eagerness_apart(ctx) \
                * float(app.traits(char).get("approach", 1)) * avail
            if random.random() >= 1 - math.exp(-rate * min(h, 12)):
                continue
            ts, ws = zip(*slots)
            sent = min(t1 - 60, random.choices(ts, ws)[0] + random.random() * 1800)
            e = app.presence.fire(char, st, t1, ctx)
            if not e:
                continue
            e["t"] = sent
            app.chat.retime_last(cid, sent)            # 届いた時刻に
            pol = app.planner.rec()["auto"].get("reply")
            a = app.presence.find(st["approach"]["id"]) or {}
            if pol and a.get("apart"):
                from .msgreply import options
                ids = [o["id"] for o in options(a["id"])]
                choice = pol if pol in ids else ids[0]
                rt = min(t1 - 30, sent + random.uniform(5, 40) * 60)
                re_ = app.presence._reply(char, st, a, choice, rt, auto=True)
                app.save_log(cid)
                app.save_state(cid)
                out.append({"cid": cid, "name": char.get("name", ""), "t": sent, "text": e.get("text", ""), "mood": 0,
                            "approach": None, "auto_reply": {"choice": choice, "result": re_["reply"]["result"], "text": re_["text"]}})
                continue
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

    # ------------------------------------------------------------------ 以前の取りこぼし (起動時に一度だけ)
    def retro_missed_work(self, now=None):
        """以前は, 予定の欄に未指定時コマンドがあると, 予定を組んでいない日も未指定時コマンドで埋まり, 行動パターンの仕事をしなかった.
        その取りこぼしを一度だけ払う. 閉じていた間のまとめ (一人の時間の記録. 残っている分だけ) から, 行動パターンでは仕事だった時間に,
        未指定時コマンドの行動をしていた (か, 何も載っていない) ところを探す. 払わないもの:
        給料・バイト代など稼ぎがその時間 (〜3 時間後) に入っている / その時間に仕事・約束をしていた / 未指定時コマンドに無い行動をしていた
        (自分で組んだ予定かもしれない) / 働ける時間帯の外・1 日の上限を超える分 (work_hours) / 家計簿の裏の記録が残っていないほど前.
        払った分は家計簿 (いまの日付で「給料（◯/◯ の分。あとから）」) と, 一人の時間の記録 (その日の仕事として. 日記に出る) に残す.
        その時間にしたことになっていた未指定時コマンドの記録は, 仕事に置き換わったので, 日記に出さない (void). 伸びたスキルはそのまま.
        返り値: [(日付, 額)]."""
        from .kakeibo import RAW_DAYS
        from .solo import PRACTICE_TEXT
        app, L = self.app, self.app.life
        now = now or time.time()
        ps = L.player_state()
        if ps.get("retro_work_v1"):
            return []
        ps["retro_work_v1"] = now
        c = self.cfg()
        fb = app.planner.rec()["fallback"]
        if not c.get("enabled") or not fb:
            L.save_player()
            return []
        raw = app.kakeibo.rec()["raw"]
        cut = now - RAW_DAYS * 86400
        incomes = [x["t"] for x in raw if x.get("c") == "income" and x.get("a", 0) > 0]
        day_of = lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d")          # noqa: E731
        worked = {day_of(x["t"]) for x in raw if x.get("c") == "income" and x.get("a", 0) > 0 and str(x.get("n", "")).startswith(("給料", "バイト"))}
        worked |= {d for d, h in (ps.get("work_log") or {}).items() if h > 0}

        def fb_like(text):
            for f in fb:
                d = f.get("do")
                if d == "practice" and PRACTICE_TEXT.get(f.get("skill") or "talk", "@") in text:
                    return True
                if d == "chores" and "家事をした" in text or d == "kakeibo" and "家計簿" in text:
                    return True
                if d == "out" and app.places.label(f.get("place")) in text:
                    return True
            return False
        quiet_fb = any(f.get("do") in ("rest", "home") for f in fb)
        log = app.solo.mylog()
        paid, voids = [], []
        for sm in [e for e in log if e.get("kind") == "offline"]:
            parts = parse_summary(sm)
            if not parts:
                continue
            p0, t1 = min(p["s"] for p in parts), sm["t"]
            if p0 < cut:
                continue
            for s, e, b in self.blocks(p0, t1):
                if b["do"] != "work" or e - s < 900:
                    continue
                if day_of(s) in worked or any(p["text"].startswith("仕事") and day_of(p["s"]) == day_of(s) for p in parts):
                    continue                        # その日は働いていた (給料・バイト代が入っている / 仕事をした記録がある)
                over = [p for p in parts if p["s"] < e and p["e"] > s]
                if any("約束" in p["text"] for p in over):
                    continue
                if over and not all(fb_like(p["text"]) for p in over):
                    continue
                if not over and not quiet_fb:
                    continue
                if any(s - 1800 <= t <= e + 3 * 3600 for t in incomes):
                    continue
                pay, h, _ = L.work_pay(s, e, record=True)
                if not pay:
                    continue
                day = datetime.fromtimestamp(s)
                ps["money"] += pay
                L.train("work", 0.5 * h)
                paid.append((day.strftime("%Y-%m-%d"), pay, s, e))
                app.trace.add("offline", "取りこぼしの仕事を払った", None, s, end=e, pay=pay, paid_h=h, parts=[p["text"][:40] for p in over])
                voids += [(sm["t"], p["s"], p["e"], p["text"]) for p in over]
        L.save_player()
        if not paid:
            return []
        for d, pay, s, e in paid:
            app.solo.note("work", "%s〜%s 仕事（%s円。記録から抜けていた分を、あとから受け取った）" % (
                datetime.fromtimestamp(s).strftime("%H:%M"), datetime.fromtimestamp(e).strftime("%H:%M"), format(pay, ",")),
                e, icon="💼", name="仕事", money={"p": pay}, retro=True)
        log = app.solo.mylog()                      # 仕事に置き換わった記録 (まとめの中の行動と, その結果の一行) は日記に出さない
        for e in log:
            if e.get("kind") == "offline":
                vs = [[s, t] for t0, s, t, _ in voids if t0 == e["t"]]
                if vs:
                    e["void_parts"] = (e.get("void_parts") or []) + vs
            elif not e.get("retro") and any(s <= e["t"] <= t + 60 and (x.startswith(e.get("text", "@")) or e.get("text", "@").startswith(x))
                                             for _, s, t, x in voids):
                e["void"] = "retro_work"
        from . import store
        store.save(store.wpath("mylog.json"), log)
        total = sum(p for _, p, _, _ in paid)
        by_day = {}
        for d, p, _, _ in paid:
            by_day[d] = by_day.get(d, 0) + p
        for d, p in sorted(by_day.items()):          # 家計簿: いまの日付で, その日の分ごとに (次に家計簿をつけると載る)
            L.ledger(now, p, "income", "給料（%d/%d の分。あとから）" % (int(d[5:7]), int(d[8:])))
        L.save_player()
        app.solo.note("money", "画面を閉じていた間の仕事が抜けていた分の給料を受け取った（%s。合計 %s円）" % (
            "・".join("%d/%d %s円" % (int(d[5:7]), int(d[8:]), format(p, ",")) for d, p in sorted(by_day.items())), format(total, ",")), now,
            icon="💼", name="給料（あとから）", money={"p": total})
        return sorted(by_day.items())

    def report(self):
        rep = self.app.life.player_state().get("offline_report")
        return rep if rep and not rep.get("seen") else None

    def ack(self):
        rep = self.app.life.player_state().get("offline_report")
        if rep:
            rep["seen"] = True
            self.app.life.save_player()
        return {"ok": True}
