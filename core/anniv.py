"""誕生日と記念日 (相手ごと. 知るのも, カレンダーに書くのも自分).

- 誕生日: キャラの定義の birthday ("MM-DD"). 無ければキャラごとに決まった日 (揺らぎ. 起動し直しても同じ).
  知るのは, 聞く (「誕生日いつ？」. 教えないのはよっぽど険悪なときだけ) か, 仲が深まると 1 か月前ごろにたまに自分から触れてくるとき.
  知ったことは関係性の「知っていること」に. カレンダーには自分で書く (core/calview.py のメモ).
- 記念日: 出会った日 (連絡先を交換した日)・家に行けるようになった日・一緒に住み始めた日 (bonds の hist). 一周年は多くの人が,
  月ごと (1〜11 か月) は甘えたがりや依存度の高い人だけが気にする. 相手から言ってくることもある.
- 当日の受け止め: 期待 (関係の深さ・好感度・性格の気にする度合い・依存度) と, あなたがしたこと (おめでとう・会った・贈り物・外食)
  を, その日の終わりに見る. 届かなければ, 性格しだいでがっかり (教えていたのに忘れられたら重く, 知らなかったなら軽く).
  遅れたおめでとう (3 日以内) は少し戻る. 効き目は bonds.realize を通す (必ず喜ぶ, にはしない).
- あなたの誕生日: 設定の「あなた」. 伝えた相手だけが知っていて, 覚えていて祝ってくれるかは相手の献身度・好感度・依存度しだい.
  変わるのは相手の振る舞いだけ (あなたの値は変わらない).
- 予約: レストランで会う約束は, 曜日・時間・何日前に決めたか・祝日年末と揺らぎで「予約でいっぱい」になることがある.

以前のセーブ: はじめて使うときに, 段階が変わった日をログから拾って記念日にする (分からない段階は無し). 誕生日は誰のものもまだ知らない
状態から. 使い始める前の日の誕生日・記念日で「忘れていた」にはしない.
"""
import calendar
import random
import time
from datetime import date, datetime, timedelta

from . import market as market_mod

STAGE_WHAT = {"contact": "出会って", "visit": "家に行けるようになって", "live": "一緒に住み始めて"}
# 誕生日・記念日を気にする度合い (性格. 無ければ 1)
CARE = {"amaenbo": 1.3, "ojousama": 1.3, "hitonatsukko": 1.2, "teinei": 1.1, "tsundere": 1.1, "genki": 1.1, "kedakai": 1.1,
        "byoujaku": 1.0, "uchiki": 1.0, "ottori": 1.0, "sadist": 1.0, "itazura": 1.0, "hikutsu": 0.9, "aneki": 0.9,
        "osananajimi": 0.9, "mukuchi": 0.8, "tenshin": 0.8, "boyish": 0.7, "otokomae": 0.7, "jimuteki": 0.6, "rikejo": 0.6,
        "cool": 0.5, "fushigi": 0.5}
MONTHLY = ("amaenbo", "hitonatsukko", "ojousama")          # 月ごとの記念日も気にする性格 (ほかは依存度が高ければ)
STAGE_W = {"contact": 0.3, "visit": 0.6, "live": 1.0}
LATE_DAYS = 3
KINDS = ("ask_bday", "tell_bday", "congrats")
# 共通のセリフ (性格プリセットの anniv.<場面> があればそちら). メッセージでは 📱 で包む
LINES = {
    "anniv.bday_tell": "{date}です。……覚えててくれたら、うれしいです",
    "anniv.bday_refuse": "……今、それを聞きます？ 教えたくないです",
    "anniv.bday_hint": "そういえば、来月の{date}、{fp}の誕生日なんです",
    "anniv.bday_noted": "{date}ですね。覚えておきます",
    "anniv.congrats_yes": "えっ……覚えててくれたんですか？ ありがとうございます、すごくうれしいです",
    "anniv.congrats_anniv": "{what}ですもんね。……ふふ、ありがとうございます",
    "anniv.congrats_late": "……遅いですよ。でも、ありがとうございます",
    "anniv.congrats_what": "……え？ 何がおめでとうなんですか？",
    "anniv.bday_forgot": "……昨日、何の日だったか知ってました？ ……いいです、別に",
    "anniv.anniv_her": "今日で{what}なんですよ。……覚えてました？",
    "anniv.your_bday": "{call}、お誕生日おめでとうございます！ 今日、覚えてましたよ",
}
SCENE_LABEL = {"bday_tell": "誕生日を聞かれて教える ({date})", "bday_refuse": "誕生日を聞かれたが, 険悪で教えない",
               "bday_hint": "1 か月前ごろ, 自分の誕生日に触れる ({date})", "bday_noted": "あなたの誕生日を教わる ({date})",
               "congrats_yes": "誕生日当日のおめでとうへの返事", "congrats_anniv": "記念日のおめでとうへの返事 ({what})",
               "congrats_late": "遅れたおめでとうへの返事", "congrats_what": "何でもない日のおめでとうに",
               "bday_forgot": "誕生日を忘れられていたことに, 翌日触れる", "anniv_her": "記念日を自分から言ってくる ({what})",
               "your_bday": "あなたの誕生日を祝う"}


def parse_md(s):
    try:
        m, d = (int(x) for x in str(s or "").strip().split("-"))
        date(2000, m, d)                     # うるう年で確かめる (2/29 も可)
        return m, d
    except (ValueError, TypeError):
        return None


def fmt_md(md):
    return "%d月%d日" % md if md else ""


def same_md(md, d):
    """md (月, 日) が d の日か. 2/29 生まれは, うるう年でなければ 2/28 に."""
    m, dd = md
    if m == 2 and dd == 29 and not calendar.isleap(d.year):
        dd = 28
    return d.month == m and d.day == dd


def reserve_full(t, now, rnd=random):
    """レストランの予約が取れないか (True = いっぱい). 曜日・時間・何日前・祝日年末・揺らぎ."""
    dt = datetime.fromtimestamp(t)
    d = dt.date()
    night = dt.hour >= 17
    if dt.weekday() in (4, 5) and night:
        base = 0.55
    elif night:
        base = 0.3 if dt.weekday() == 6 else 0.2
    else:
        base = 0.2 if dt.weekday() >= 5 else 0.05
    if d in market_mod.holidays(d.year) or (d.month == 12 and d.day >= 20):
        base *= 1.4
    days = (datetime(d.year, d.month, d.day) - datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)).days
    lead = 1.5 if days <= 0 else 1.1 if days == 1 else 0.8 if days <= 3 else 0.5 if days <= 6 else 0.3
    return rnd.random() < min(0.9, base * lead * rnd.uniform(0.7, 1.3))


class Anniv:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 日付
    def birthday(self, char):
        md = parse_md(char.get("birthday"))
        if md:
            return md
        rnd = random.Random("bday:%s" % char.get("id"))
        m = rnd.randint(1, 12)
        return m, rnd.randint(1, calendar.monthrange(2001, m)[1])

    def my_birthday(self):
        return parse_md(self.app.player_profile().get("birthday"))

    def ps(self):
        ps = self.app.life.player_state()
        if not ps.get("anniv_v1"):
            ps["anniv_v1"] = True
            ps["anniv_since"] = time.time()
            self._retro()
            self.app.life.save_player()
        return ps

    def hist(self, cid):
        b = self.app.bonds.rec()["bonds"].get(cid) or {}
        return b.get("hist") or {}

    def events_on(self, char, st, d):
        """その日の誕生日・記念日 [{kind, what, months}]. kind: birthday / anniv."""
        self.ps()
        out = []
        if same_md(self.birthday(char), d):
            out.append({"kind": "birthday", "what": "誕生日"})
        fd = self.app.attach.factor(char, st, "dependence")
        for stage, t in self.hist(char["id"]).items():
            s = datetime.fromtimestamp(t).date()
            if s >= d or stage not in STAGE_WHAT:
                continue
            months = (d.year - s.year) * 12 + d.month - s.month
            if same_md((s.month, s.day), d) and months >= 12:
                out.append({"kind": "anniv", "what": "%s%d年" % (STAGE_WHAT[stage], months // 12), "months": months, "stage": stage})
            elif d.day == s.day and 1 <= months < 12 and (char.get("persona_id") in MONTHLY or fd >= 0.4):
                out.append({"kind": "anniv", "what": "%s%dか月" % (STAGE_WHAT[stage], months), "months": months, "stage": stage})
        return out

    def care(self, char, st, ev):
        """その日をどれだけ気にするか (期待. 0〜1.2)."""
        stage = self.app.bonds.stage(char["id"])
        aff = st["params"].get("affection", 50)
        e = CARE.get(char.get("persona_id") or "", 1.0) * STAGE_W.get(stage, 0.0) * max(0.0, min(1.2, (aff - 30) / 50.0)) \
            * (1 + 0.3 * self.app.attach.factor(char, st, "dependence"))
        if ev["kind"] == "anniv":
            e *= 0.7 if ev.get("months", 12) >= 12 else 0.35
        return round(max(0.0, min(1.2, e)), 3)

    # ------------------------------------------------------------------ 毎日
    def daily(self, char, st, t):
        """日付が替わったとき: 前の日の受け止め / 今日の誕生日・記念日 / 1 か月前の話 / 相手から言ってくる / あなたの誕生日."""
        ps = self.ps()
        if t < ps.get("anniv_since", 0):
            return
        d = datetime.fromtimestamp(t).date()
        cel = st.get("celeb")
        if cel and cel.get("date") < d.isoformat():
            self._evaluate(char, st, cel, t)
            st.pop("celeb", None)
        evs = self.events_on(char, st, d)
        if evs:
            st["celeb"] = {"date": d.isoformat(), "events": evs, "E": max(self.care(char, st, e) for e in evs), "done": {}}
            an = [e for e in evs if e["kind"] == "anniv"]
            if an and self.care(char, st, an[0]) >= 0.45 and random.random() < 0.6:
                self._schedule(st, t, "anniv_her", {"what": an[0]["what"]})
        stage = self.app.bonds.stage(char["id"])
        p = st["params"]
        # 1 か月前ごろ, 仲が深まっていれば, たまに自分の誕生日に触れる (まだ教えていなければ)
        bd = self.birthday(char)
        soon = d + timedelta(days=30)
        if same_md(bd, soon) and not st.get("bday_known") and stage in ("visit", "live") and p.get("affection", 50) >= 55 \
                and random.random() < 0.5:
            self._schedule(st, t, "bday_hint", {"date": fmt_md(bd)})
        # あなたの誕生日: 伝えた相手が, 覚えていれば祝ってくれる
        mine = self.my_birthday()
        if mine and same_md(mine, d) and st.get("knows_my_bday") and stage != "known":
            A = self.app.attach
            pr = 0.25 + 0.35 * max(0.0, min(1.0, (p.get("affection", 50) - 30) / 50.0)) \
                + 0.2 * A.factor(char, st, "devotion") + 0.1 * A.factor(char, st, "dependence")
            if random.random() < max(0.05, min(0.95, pr)):
                self._schedule(st, t, "your_bday", {}, early=True)
            self.app.trace.add("anniv", "あなたの誕生日: 覚えているか", char["id"], t, pr=round(pr, 2))

    def _schedule(self, st, t, key, extra, early=False):
        d0 = datetime.fromtimestamp(t).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        at = d0 + random.uniform(7, 10) * 3600 if early else d0 + random.uniform(11, 21) * 3600
        st.setdefault("anniv_msgs", []).append({"at": at, "key": key, "extra": extra})

    def tick(self, char, st, now):
        """予定していた, 相手から言ってくること (記念日・誕生日の話・あなたの誕生日・忘れられていた) を届ける."""
        due = [m for m in st.get("anniv_msgs") or [] if m["at"] <= now]
        if not due:
            return
        st["anniv_msgs"] = [m for m in st.get("anniv_msgs") or [] if m["at"] > now]
        for m in due:
            if now - m["at"] > 24 * 3600:
                continue
            cel = st.get("celeb") or {}
            if m["key"] == "anniv_her" and (cel.get("done") or {}).get("congrats"):
                continue                               # もうあなたから言われた
            if m["key"] == "bday_hint":
                st["bday_known"] = True
                self.app.bonds.learn(st, "heard", "誕生日は%s" % m["extra"]["date"], now)
            self.speak(char, st, m["key"], m["extra"], m["at"])

    def speak(self, char, st, key, extra, t):
        """相手から言う: そばにいれば記録に, 離れていればメッセージで."""
        app = self.app
        cid = char["id"]
        if app.bonds.together(cid):
            self._entry(char, st, t, key, self.line(char, key, extra), {})
        else:
            app.chat.add(cid, "her", self.line(char, key, extra, phone=True), kind=key, t=t)
            app.picked_up_phone(char, st, t)
        app.trace.add("anniv", "相手から: " + key, cid, t, extra=extra)

    # ------------------------------------------------------------------ その日の受け止め
    def mark(self, char, st, what, now=None):
        """その日 (誕生日・記念日) にあなたがしたこと: congrats / met / gift / meal."""
        cel = st.get("celeb")
        now = now or time.time()
        if cel and cel.get("date") == datetime.fromtimestamp(now).date().isoformat():
            cel.setdefault("done", {})[what] = now

    def _evaluate(self, char, st, cel, t):
        app = self.app
        done = cel.get("done") or {}
        D = min(1.0, 0.4 * bool(done.get("congrats")) + 0.3 * bool(done.get("met")) + 0.3 * bool(done.get("gift"))
                + 0.2 * bool(done.get("meal")))
        E = float(cel.get("E", 0))
        bday = any(e["kind"] == "birthday" for e in cel.get("events") or [])
        call = app.pronouns(char)[2]
        out = "none"
        if D > 0 and (D >= 0.6 * E or D >= 0.4):
            eff = {"mood": 3 + 6 * D, "affection": 1 + 2 * D, "loneliness": -5}
            eff, _ = app.bonds.realize(char, st, eff, "_anniv", t)
            deltas = app.apply_effects(st, app.trait_effects(char, eff))
            app.life.add_reason(st, "player", "good", "%sが%sを祝ってくれた" % (call, "誕生日" if bday else "記念日"), t,
                                told=True, delta=deltas.get("mood", 0), action="_anniv")
            out = "good"
        elif E >= 0.35:
            k = E * (1.0 if not bday else 1.4 if st.get("bday_known") else 0.4) * (1 - D)
            eff = {"mood": -6 * k, "affection": -2 * k, "trust": -1 * k}
            deltas = app.apply_effects(st, app.trait_effects(char, eff))
            app.life.add_reason(st, "player", "bad", "%sに%sを忘れられていた" % (call, "誕生日" if bday else "記念日"), t,
                                told=False, delta=deltas.get("mood", 0), action="_anniv_forgot")
            out = "bad"
            if bday and E >= 0.6 and random.random() < 0.6:
                self._schedule(st, t, "bday_forgot", {})
        st["celeb_last"] = {"date": cel["date"], "out": out, "bday": bday, "what": (cel.get("events") or [{}])[0].get("what", ""),
                            "E": E, "D": D}
        app.trace.add("anniv", "その日の受け止め", char["id"], t, date=cel["date"], E=E, D=D, out=out, done=sorted(done))

    # ------------------------------------------------------------------ あなたから (聞く・伝える・おめでとう)
    def reply(self, char, st, kind, now):
        """(場面の鍵, 効果, 置き換え). 会って言ったときもメッセージで送ったときも同じ判定."""
        app = self.app
        p = st["params"]
        if kind == "ask_bday":
            bad = app.life.dominant(st, now, "bad")
            if p.get("affection", 50) < 20 or (p.get("mood", 50) < 25 and bad and bad.get("kind") == "player"):
                return "bday_refuse", {"mood": -1}, {}
            md = self.birthday(char)
            st["bday_known"] = True
            app.bonds.learn(st, "heard", "誕生日は%s" % fmt_md(md), now)
            return "bday_tell", {}, {"date": fmt_md(md)}
        if kind == "tell_bday":
            md = self.my_birthday()
            st["knows_my_bday"] = True
            return "bday_noted", {"mood": 1}, {"date": fmt_md(md)}
        # おめでとう
        today = datetime.fromtimestamp(now).date().isoformat()
        cel = st.get("celeb")
        if cel and cel.get("date") == today:
            first = not (cel.get("done") or {}).get("congrats")
            self.mark(char, st, "congrats", now)
            bday = [e for e in cel["events"] if e["kind"] == "birthday"]
            if bday:
                return "congrats_yes", ({"mood": 4, "affection": 1} if first else {}), {}
            return "congrats_anniv", ({"mood": 3} if first else {}), {"what": cel["events"][0]["what"]}
        last = st.get("celeb_last") or {}
        if last.get("date") and (datetime.fromisoformat(today) - datetime.fromisoformat(last["date"])).days <= LATE_DAYS \
                and last.get("out") == "bad" and not last.get("late"):
            last["late"] = now
            for r in st.get("reasons") or []:                 # 忘れられていた, は和らぐ (全部は戻らない)
                if r.get("action") == "_anniv_forgot" and not r.get("resolved"):
                    r["resolved"] = True
            return "congrats_late", {"mood": 2}, {}
        return "congrats_what", {}, {}

    def say(self, kind, cid=None, phone=False):
        """会って言う (phone=False) / メッセージで送る (phone=True. 返事は時間差)."""
        app = self.app
        if kind not in KINDS:
            raise ValueError("言うことが違います: %s" % kind)
        if kind == "tell_bday" and not self.my_birthday():
            raise ValueError("あなたの誕生日が決まっていません（設定 → あなた）")
        if phone:
            return app.chat.send(cid, kind)
        char = app.char(cid)
        st = app.state(char["id"])
        if not app.bonds.together(char["id"]):
            raise ValueError("そばにいないので、メッセージで伝えましょう")
        now = time.time()
        with app.lock:
            key, eff, extra = self.reply(char, st, kind, now)
            eff, _ = app.bonds.realize(char, st, eff, "_anniv_" + kind, now)
            deltas = app.apply_effects(st, app.trait_effects(char, eff))
            said = {"ask_bday": "（誕生日を聞いた）", "tell_bday": "（自分の誕生日を伝えた）", "congrats": "（おめでとうと伝えた）"}[kind]
            e = self._entry(char, st, now, key, said + "\n" + self.line(char, key, extra), deltas)
            app.save_state(char["id"])
        app.trace.add("anniv", "会って: " + kind, char["id"], now, key=key)
        return {"entry": e, "job": None, "llm_error": None}

    def _entry(self, char, st, t, key, text, deltas):
        app = self.app
        dt = datetime.fromtimestamp(t)
        scene = app.scene_at(char, st, dt)
        act = {"id": "_anniv", "name": "誕生日・記念日", "icon": "🎂", "pos": "smile, looking at viewer", "neg": ""}
        pos, neg, parts = app.build_prompt(char, st, dt, act)
        e = app._new_entry(char["id"], t, act, text, deltas, scene, dt, pos, neg, parts)
        e["anniv"] = key
        app.save_log(char["id"])
        return e

    def line(self, char, key, extra, phone=False):
        app = self.app
        t = app.persona_text(char, "anniv." + key) or LINES["anniv." + key]
        fp, _, call = app.pronouns(char)
        for k, v in dict(extra or {}, fp=fp, call=call, name=char.get("name", "")).items():
            t = t.replace("{%s}" % k, str(v))
        return "📱『%s』" % t if phone else t

    # ------------------------------------------------------------------ カレンダーのメモ
    def memos(self):
        return self.ps().setdefault("memos", [])

    def memo_add(self, day, text, yearly=False):
        text = str(text or "").strip()[:60]
        try:
            d = date.fromisoformat(str(day))
        except ValueError:
            raise ValueError("日付が違います")
        if not text:
            raise ValueError("メモが空です")
        x = {"id": "m%d" % int(time.time() * 1000), "date": d.isoformat(), "text": text, "yearly": bool(yearly)}
        self.memos().append(x)
        self.app.life.save_player()
        return x

    def memo_del(self, mid):
        ms = self.memos()
        ms[:] = [m for m in ms if m["id"] != mid]
        self.app.life.save_player()
        return {"ok": True}

    def memos_on(self, d):
        out = []
        for m in self.memos():
            md = date.fromisoformat(m["date"])
            if md == d or (m.get("yearly") and same_md((md.month, md.day), d) and d >= md):
                out.append(m)
        return out

    # ------------------------------------------------------------------ 以前のセーブ
    def _retro(self):
        """段階が変わった日を, ログから拾う (一度だけ). 出会った日 = その人との最初の記録. 分からない段階は無し."""
        app = self.app
        rec = app.bonds.rec()
        n = 0
        for cid in app.chars:
            b = rec["bonds"].get(cid)
            if not b or b.get("stage") in (None, "known"):
                continue
            hist = b.setdefault("hist", {})
            log = app.log(cid)
            ts = [e["t"] for e in log] + [i["t"] for i in app.chat.load(cid)["items"]]
            if ts and "contact" not in hist:
                hist["contact"] = min(ts)
            for stage, aid in (("visit", "ask_visit"), ("live", "ask_live")):
                if stage in hist:
                    continue
                ok = [e["t"] for e in log if e.get("action") == aid and not e.get("override")]
                if ok:
                    hist[stage] = max(ok)
                elif b.get("stage") == stage and b.get("t"):
                    hist[stage] = b["t"]
            n += len(hist)
        app.bonds.save()
        app.trace.add("retro", "記念日を以前の記録から拾った", None, time.time(), n=n)
