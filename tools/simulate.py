"""長期シミュレーション: 一時データで数週間ぶんを自動で進めて, 数値の推移と偏りを見る (数値の調整はしない. 所見は docs/DESIGN.md へ).

時計を差し替えて, 次のような「あなた」を演じる:
- 画面を閉じている間は, あなたの行動パターン (offline.days. 既定は平日 仕事・買い物, 休日 家事・散歩・買い物) どおり
- 画面を開く時間帯 (平日は夜, 休日は昼と夜. 開かない日もある) には, 心拍を送りながら, ときどきランダムな操作をする
  (そばにいる相手へのコマンド・メッセージ・電話・誘い・段階の提案・働きかけへの返事・ばったりへの反応・一人で出かける・プレゼント)
- ときどき何日か放置する. 閉じるときは「寝る」と告げることも, 黙って閉じることもある
集計: お金・体力・スキル・各キャラのパラメータと間柄の推移, 出会い・メッセージ・働きかけ・出来事の回数, 偏りの候補.
何も起きない時間が長いのは仕様 (このアプリの真髄) なので, 偏りとしては扱わない.

    python tools/simulate.py                       # 一人暮らしで始めるワールド, 21 日
    python tools/simulate.py --start live --days 28 --seed 3
    python tools/simulate.py --json out.json       # 日ごとの記録も書き出す
"""
import argparse
import collections
import datetime as _dtm
import json
import os
import random
import shutil
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from core import engine, store  # noqa: E402
from core import bonds as bonds_mod, chat as chat_mod, life as life_mod, offline as offline_mod  # noqa: E402
from core import outdoor as outdoor_mod, presence as presence_mod, solo as solo_mod, street as street_mod  # noqa: E402
from core import encounters as encounters_mod, items as items_mod, games as games_mod  # noqa: E402


# ---------------------------------------------------------------------- 時計
class Clock:
    t = 0.0


CLOCK = Clock()
_REAL_DT, _REAL_DATE = _dtm.datetime, _dtm.date


class FakeDatetime(_REAL_DT):
    @classmethod
    def now(cls, tz=None):
        return _REAL_DT.fromtimestamp(CLOCK.t)


class FakeDate(_REAL_DATE):
    @classmethod
    def today(cls):
        return _REAL_DATE.fromtimestamp(CLOCK.t)


def install_clock(start):
    CLOCK.t = start
    time.time = lambda: CLOCK.t
    for m in (engine, store, bonds_mod, chat_mod, life_mod, offline_mod, outdoor_mod, presence_mod, solo_mod, street_mod,
              encounters_mod, items_mod, games_mod):
        if getattr(m, "datetime", None) is _REAL_DT:
            m.datetime = FakeDatetime
        if getattr(m, "date", None) is _REAL_DATE:
            m.date = FakeDate


def ts(d, h=0, m=0):
    return _REAL_DT(d.year, d.month, d.day, h, m).timestamp()


# ---------------------------------------------------------------------- 集計
class Stats:
    def __init__(self):
        self.n = collections.Counter()
        self.acts = collections.Counter()
        self.refused = collections.Counter()
        self.stage_changes = []
        self.days = []

    def wrap(self, obj, name, key, pred=None):
        """obj.name を呼ぶたびに数える (pred(戻り値) が真のときだけ)."""
        f = getattr(obj, name)

        def g(*a, **k):
            r = f(*a, **k)
            if pred is None or pred(r):
                self.n[key] += 1
            return r
        setattr(obj, name, g)


SOCIAL_W = {"会話": 5, "ふれあい": 3, "お世話": 3, "あそび": 2, "見る": 1, "おでかけ": 1.5, "お金": 0.3, "会う": 1, "連絡": 1}
SKIP = {"move_out", "side_job", "gift", "expensive_gift", "end_activity", "go_home", "leave_visit"}
SHOP_LIST = {"veggies": 2, "meat_fish": 1, "tea_leaves": 1, "detergent": 1, "cookies": 1}


class Player:
    """ランダムな「あなた」."""

    def __init__(self, app, st, rng):
        self.app, self.S, self.rng = app, st, rng

    def pick_char(self):
        app = self.app
        near = app.solo.near()
        if near and self.rng.random() < 0.75:
            return near
        return self.rng.choice(list(app.chars))

    def act_random(self):
        app, rng = self.app, self.rng
        cid = self.pick_char()
        char, st = app.char(cid), app.state(cid)
        av = app.available(char, st, _REAL_DT.fromtimestamp(CLOCK.t))
        cands = []
        for a in app.actions:
            if a["id"] in SKIP or a.get("category") in ("system", "あなたの予定") or a.get("presence_set"):
                continue
            ok = av.get(a["id"]) or {}
            if ok.get("ok") and not ok.get("cooldown"):
                cands.append(a)
        if not cands:
            return
        a = rng.choices(cands, [SOCIAL_W.get(x.get("category"), 1) for x in cands])[0]
        try:
            r = app.act(a["id"], cid)
            self.S.acts[a["id"]] += 1
            if r.get("missed"):
                self.S.n["call_missed"] += 1
        except (ValueError, KeyError):
            self.S.refused[a["id"]] += 1

    def message(self):
        app = self.app
        cs = [c for c in app._contacts_view()]
        if not cs:
            return
        c = self.rng.choice(cs)
        try:
            app.chat.send(c["id"], self.rng.choice(list(chat_mod.KINDS)))
            self.S.n["msg_sent"] += 1
        except (ValueError, KeyError):
            self.S.refused["message"] += 1

    def gift(self):
        app = self.app
        have = [i for i, n in app.items.ps()["items"].items() if n > 0 and items_mod.CATALOG.get(i, {}).get("giftable")]
        near = app.solo.near()
        if not have or not near:
            return
        try:
            app.give_item(self.rng.choice(have), near)
            self.S.n["gift"] += 1
        except (ValueError, KeyError):
            self.S.refused["gift_item"] += 1

    def answer_pending(self):
        """働きかけ・ばったり・知り合った人の登録・おねだりに (ときどき放っておきながら) 答える."""
        app, rng = self.app, self.rng
        cid = app.settings.get("active_character")
        st = app.state(cid)
        if st.get("approach") and rng.random() < 0.6:
            ans = "accept" if rng.random() < 0.7 else "later"
            try:
                app.answer_approach(ans, cid)
                self.S.n["approach_" + ans] += 1
            except (ValueError, KeyError):
                pass
        if app.street.pending() and rng.random() < 0.7:
            opts = [o[0] for o in street_mod.OPTIONS[app.street.pending()["type"]]]
            app.street.answer(rng.choice(opts))
            self.S.n["street_answered"] += 1
        if app.encounters.pending() and rng.random() < 0.5:
            yes = rng.random() < 0.6
            app.answer_encounter(yes)
            self.S.n["register_" + ("yes" if yes else "no")] += 1
        for c in list(app.chars):
            s = app.state(c)
            if s.get("request") and app.bonds.together(c) and rng.random() < 0.3:
                try:
                    app.act("_req_yes" if rng.random() < 0.5 else "_req_no", c)
                    self.S.n["request_answered"] += 1
                except (ValueError, KeyError):
                    pass

    def solo_out(self):
        kind = self.rng.choice(["walk", "shopping", "cafe", "practice", "chores", "rest"])
        place = self.rng.choice(outdoor_mod.CHOICES[kind]) if kind in outdoor_mod.CHOICES else None
        skill = self.rng.choice(list(solo_mod.SKILL_LABEL)) if kind == "practice" else None
        try:
            self.app.solo.start(kind, skill=skill, place=place)
            self.S.n["solo_" + kind] += 1
            return CLOCK.t + self.rng.uniform(0.4, 2.0) * 3600
        except (ValueError, KeyError):
            return None


def snapshot(app, day):
    ps = app.life.player_state()
    row = {"day": day.isoformat(), "money": int(ps["money"]), "stamina": round(float(ps.get("stamina", 0)), 1),
           "invest": app.life.portfolio_value(), "skills": {k: round(v, 1) for k, v in ps["skills"].items()},
           "items": sum(ps.get("items", {}).values()), "debt": int(ps.get("debt", 0)),
           "loans": sum((ps.get("loans") or {}).values()), "chars": {}}
    for cid, c in app.chars.items():
        app.tick(cid)
        p = app.state(cid)["params"]
        row["chars"][cid] = {"name": c.get("name", cid), "stage": app.bonds.stage(cid),
                             "her_money": app.life.her_money(app.state(cid))["a"],
                             **{k: round(p.get(k, 0), 1) for k in ("affection", "trust", "mood", "loneliness", "stress", "boredom")}}
    ppl = app.street.people()
    row["people"] = collections.Counter(street_mod.STAGES[int(pr.get("stage", 0))] for pr in ppl.values() if not pr.get("cid"))
    return row


def run(args):
    rng = random.Random(args.seed)
    random.seed(args.seed)
    start_day = _REAL_DATE(2026, 10, 19)                 # 月曜
    install_clock(ts(start_day, 7, 0))
    tmp = tempfile.mkdtemp(prefix="kurashi_sim_")
    store.DATA = tmp
    S = Stats()
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False, "llm": {"enabled": False}})
        if args.start == "alone":
            app.create_world("シミュレーション")
        # 回数を数える (中身は変えない)
        S.wrap(app.presence, "fire", "approach_fired", lambda r: r)
        S.wrap(app.presence, "_expire", "approach_ignored", lambda r: r)
        S.wrap(app.street, "happen", "street_meet", lambda r: r)
        S.wrap(app.encounters, "bump", "bump")
        S.wrap(app.life, "happen", "char_event", lambda r: r)
        S.wrap(app.bonds, "notice", "jealousy")
        S.wrap(app, "_chat_reply", "msg_replied")
        S.wrap(app.offline, "simulate", "offline_runs", lambda r: r)
        orig_set = app.bonds.set_stage

        def set_stage(cid, stage, now=None):
            old = app.bonds.stage(cid)
            orig_set(cid, stage, now)
            if old != stage:
                S.stage_changes.append((_REAL_DT.fromtimestamp(CLOCK.t).strftime("%m/%d %H:%M"),
                                        app.chars.get(cid, {}).get("name", cid), old, stage))
        app.bonds.set_stage = set_stage
        orig_offline = app.offline.simulate

        def offline_sim(t0, t1):
            rep = orig_offline(t0, t1)
            if rep:
                S.n["offline_msgs"] += len(rep.get("messages") or [])
                S.n["offline_meets"] += len(rep.get("meets") or [])
                S.n["offline_bought"] += len(rep.get("bought") or [])
            return rep
        app.offline.simulate = offline_sim

        P = Player(app, S, rng)
        app.items.ps()["shop_list"] = dict(SHOP_LIST)
        app.items.save()
        S.days.append(snapshot(app, start_day - _dtm.timedelta(days=1)))
        neglect_until = None
        for i in range(args.days):
            day = start_day + _dtm.timedelta(days=i)
            weekend = day.weekday() >= 5
            if i % 7 == 0:                                   # 週に一度, 買うものリストを足す
                sl = app.items.ps()["shop_list"]
                for k, v in SHOP_LIST.items():
                    sl[k] = max(sl.get(k, 0), v)
                app.items.save()
            if neglect_until is None and rng.random() < args.neglect:
                neglect_until = day + _dtm.timedelta(days=rng.randint(2, 6))
                S.n["neglect_spells"] += 1
            if neglect_until and day < neglect_until:
                S.n["neglect_days"] += 1
                sessions = []
            else:
                neglect_until = None
                if weekend:
                    sessions = [(10, 12.5, 0.5), (14, 17, 0.5), (20, 23.5, 0.7)]
                else:
                    sessions = [(19.5, 23.5, 0.75)]
                sessions = [(a, b) for a, b, p in sessions if rng.random() < p]
            for a, b in sessions:
                session(app, P, S, rng, ts(day, int(a), int((a % 1) * 60)), ts(day, int(b) % 24, int((b % 1) * 60)))
            CLOCK.t = max(CLOCK.t, ts(day, 23, 59))
            S.days.append(snapshot(app, day))
        CLOCK.t += 6 * 3600                                    # 最後の閉じていた間も
        app.state_view(beat=True, idle=0)
        return S, app
    finally:
        app_dir = tmp
        if not args.keep:
            shutil.rmtree(app_dir, ignore_errors=True)
            shutil.rmtree(app_dir + "_backup", ignore_errors=True)
        else:
            print("データ:", app_dir)


def session(app, P, S, rng, t0, t1):
    """画面を開いている時間. 3 分ごとに心拍. ときどき操作する."""
    CLOCK.t = max(CLOCK.t, t0)
    S.n["sessions"] += 1
    app.state_view(beat=True, idle=0)
    try:
        app.visit()
    except (ValueError, KeyError):
        pass
    back_at = None
    idle = 0
    while CLOCK.t < t1:
        CLOCK.t += 180
        idle += 180
        v = app.state_view(beat=True, idle=idle)
        if v.get("street"):
            S.n["street_live"] += 1
        p = app.presence.rec()
        if back_at and CLOCK.t >= back_at:
            try:
                app.come_back()
            except (ValueError, KeyError):
                pass
            back_at = None
            continue
        if p.get("mode") not in ("none", None):
            if rng.random() < 0.5:
                P.answer_pending()       # 出先でも, ばったりやメッセージには反応する
            continue
        if rng.random() > 0.18:
            continue
        idle = 0
        P.answer_pending()
        r = rng.random()
        if r < 0.55:
            P.act_random()
        elif r < 0.72:
            P.message()
        elif r < 0.78:
            P.gift()
        elif r < 0.92:
            back_at = P.solo_out()
        else:
            pass                         # 眺めているだけ
    if app.presence.rec().get("mode") not in ("none", None):
        try:
            app.come_back()
        except (ValueError, KeyError):
            pass
    # 閉じる: 夜なら半分は「寝る」と告げてから. それ以外は黙って閉じる
    if _REAL_DT.fromtimestamp(CLOCK.t).hour >= 22 and rng.random() < 0.5:
        try:
            app.solo.start("sleep")
            S.n["declared_sleep"] += 1
        except (ValueError, KeyError):
            pass


# ---------------------------------------------------------------------- 報告
def report(S, app, args):
    d = S.days
    first, last = d[0], d[-1]
    out = []
    w = out.append
    w("== kurashi 長期シミュレーション: %s で開始, %d 日, seed %d ==" % ({"alone": "一人暮らし", "live": "同居"}[args.start], args.days, args.seed))
    w("画面を開いた回数 %d / 放置 %d 回 (%d 日) / 閉じていた間のまとめ %d 回" % (
        S.n["sessions"], S.n["neglect_spells"], S.n["neglect_days"], S.n["offline_runs"]))
    money = [x["money"] for x in d]
    w("\n[お金] %s → %s 円 (最小 %s, 最大 %s) / 株 %s 円" % (
        f(money[0]), f(money[-1]), f(min(money)), f(max(money)), f(last["invest"])))
    w("  借金 %s 円 / 知り合いに借りている %s 円 / お金のできごと: %s" % (f(last["debt"]), f(last["loans"]),
      " / ".join(x["text"] for x in (app.life.player_state().get("money_notes") or [])[-3:]) or "なし"))
    w("  週ごとの増減: " + ", ".join(f(money[min(i + 7, len(money) - 1)] - money[i]) for i in range(0, len(money) - 1, 7)))
    st = [x["stamina"] for x in d]
    w("[体力] 23:59 時点 平均 %.0f / 最小 %.0f / 20 未満の日 %d" % (sum(st) / len(st), min(st), sum(1 for x in st if x < 20)))
    w("[スキル] " + ", ".join("%s %.1f→%.1f" % (k, first["skills"][k], last["skills"][k]) for k in first["skills"]))
    w("[持ち物] 合計 %d 個 / 閉じていた間に買った %d 回" % (last["items"], S.n["offline_bought"]))
    w("\n[キャラ] (日ごとの 23:59 時点)")
    for cid in last["chars"]:
        rows = [x["chars"][cid] for x in d if cid in x["chars"]]
        a = [r["affection"] for r in rows]
        t = [r["trust"] for r in rows]
        mo = [r["mood"] for r in rows]
        lo = [r["loneliness"] for r in rows]
        w("  %s (%s, %d 日): 好感度 %.0f→%.0f [%.0f〜%.0f] 信頼 %.0f→%.0f 機嫌 平均 %.0f [%.0f〜%.0f] 寂しさ 平均 %.0f / 相手のお金 %s→%s" % (
            rows[-1]["name"], rows[-1]["stage"], len(rows), a[0], a[-1], min(a), max(a), t[0], t[-1],
            sum(mo) / len(mo), min(mo), max(mo), sum(lo) / len(lo), f(rows[0]["her_money"]), f(rows[-1]["her_money"])))
    w("  間柄の変化: " + ("; ".join("%s %s %s→%s" % x for x in S.stage_changes) or "なし"))
    w("  出先の人 (未登録): " + (", ".join("%s %d" % kv for kv in sorted(last["people"].items())) or "なし"))
    n = S.n
    w("\n[回数] ばったり %d (画面を開いて %d・閉じていた間 %d) / 知り合いの登録 する %d・しない %d" % (
        n["street_meet"], n["street_live"], n["offline_meets"], n["register_yes"], n["register_no"]))
    w("  メッセージ 送った %d・返信 %d / 電話に出なかった %d / 閉じていた間に届いた %d" % (
        n["msg_sent"], n["msg_replied"], n["call_missed"], n["offline_msgs"]))
    w("  働きかけ %d (応じた %d・あとで %d・返事なし %d) / キャラの出来事 %d / 嫉妬 %d / プレゼント %d" % (
        n["approach_fired"], n["approach_accept"], n["approach_later"], n["approach_ignored"], n["char_event"], n["jealousy"],
        n["gift"]))
    w("  一人の時間: " + ", ".join("%s %d" % (k[5:], v) for k, v in sorted(n.items()) if k.startswith("solo_")))
    w("  コマンド (多い順): " + ", ".join("%s %d" % kv for kv in S.acts.most_common(12)))
    if S.refused:
        w("  断られた/できなかった: " + ", ".join("%s %d" % kv for kv in S.refused.most_common(8)))
    w("\n[偏りの候補] (何も起きない時間の長さは仕様なので数えない)")
    for x in biases(S, args) or ["目立った偏りなし"]:
        w("  - " + x)
    return "\n".join(out)


def f(v):
    return format(int(v), ",")


def biases(S, args):
    d = S.days
    out = []
    money = [x["money"] for x in d]
    if min(money) <= 0 or d[-1]["debt"] or d[-1]["loans"]:
        out.append("お金が尽きた (最小 %s 円, 借金 %s 円, 借りている %s 円)" % (f(min(money)), f(d[-1]["debt"]), f(d[-1]["loans"])))
    elif money[-1] > money[0] * 3 and money[-1] - money[0] > 100000:
        out.append("お金が増えすぎ (%s → %s 円, 使い道が追いつかない)" % (f(money[0]), f(money[-1])))
    weeks = [money[min(i + 7, len(money) - 1)] - money[i] for i in range(0, len(money) - 1, 7)]
    if len(weeks) >= 2 and all(x < 0 for x in weeks):
        out.append("お金が毎週減り続けている (週 %s 円前後)" % f(sum(weeks) / len(weeks)))
    st = [x["stamina"] for x in d]
    if sum(1 for x in st if x < 20) > len(st) / 3:
        out.append("体力が慢性的に低い")
    for k in d[0]["skills"]:
        if d[-1]["skills"][k] - d[0]["skills"][k] > 40:
            out.append("スキル %s の伸びが速い (%.0f → %.0f)" % (k, d[0]["skills"][k], d[-1]["skills"][k]))
    for cid in d[-1]["chars"]:
        rows = [x["chars"][cid] for x in d if cid in x["chars"]]
        if len(rows) < 7:
            continue
        a = [r["affection"] for r in rows]
        name = rows[-1]["name"]
        if max(a) - min(a) < 2:
            out.append("%s の好感度がほとんど動かない (%.0f 前後, 間柄 %s)" % (name, a[-1], rows[-1]["stage"]))
        downs = sum(1 for x, y in zip(a, a[1:]) if y < x - 0.5)
        if a[-1] - a[0] > 25 and downs <= len(a) // 10:
            out.append("%s の好感度が一方的に深まる (%.0f → %.0f, 下がった日 %d)" % (name, a[0], a[-1], downs))
        if a[0] - a[-1] > 25:
            out.append("%s の好感度が下がり続ける (%.0f → %.0f)" % (name, a[0], a[-1]))
        hm = [r["her_money"] for r in rows]
        if hm[-1] - hm[0] > 30000:
            out.append("%s のお金がたまり続ける (%s → %s 円)" % (name, f(hm[0]), f(hm[-1])))
        if min(hm) < 0:
            out.append("%s のお金がマイナス (%s 円)" % (name, f(min(hm))))
        mo = [r["mood"] for r in rows]
        if sum(1 for x in mo if x < 30) > len(mo) / 2:
            out.append("%s の機嫌が低いままの日が多い" % name)
    n = S.n
    if n["msg_sent"] >= 10 and n["msg_replied"] / float(n["msg_sent"]) < 0.3:
        out.append("メッセージの返信率が低い (%d / %d)" % (n["msg_replied"], n["msg_sent"]))
    if n["approach_fired"] >= 5 and n["approach_ignored"] / float(n["approach_fired"]) > 0.6:
        out.append("働きかけの多くが返事なしで終わる (%d / %d)" % (n["approach_ignored"], n["approach_fired"]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--start", choices=("alone", "live"), default="alone", help="一人暮らしの新しいワールド / 最初のワールド (同居)")
    ap.add_argument("--neglect", type=float, default=0.06, help="その日から何日か放置する確率")
    ap.add_argument("--json", help="日ごとの記録を書き出す")
    ap.add_argument("--keep", action="store_true", help="一時データを消さずに残す")
    args = ap.parse_args()
    t0 = _REAL_DT.now()
    S, app = run(args)
    text = report(S, app, args)
    print(text)
    print("\n(%.0f 秒)" % (_REAL_DT.now() - t0).total_seconds())
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fp:
            json.dump({"days": S.days, "counts": S.n, "acts": S.acts, "stage_changes": S.stage_changes, "report": text},
                      fp, ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    main()
