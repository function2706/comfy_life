"""メッセージの受け止め方 (現実的に, めんどくさく): 謝罪・お礼・あいさつ・スタンプと, 「今いい？」などの短い連絡.

- 謝罪: 許し方に幅がある. すぐ許す (quick) / 半分だけ (half: 理由は消さず弱める) / 「謝るなら態度で」(deeds: 理由は残る.
  連絡しすぎなら, しばらく連絡を控えると消える) / 受け付けない (refuse). 決め手は 性格 (traits.grudge 根に持つ↔さっぱり.
  控えめ)・怒りの大きさ (理由の delta)・同じ失敗の何度目か・謝るまでの間 (日が経つと「今さら？」= late)・その日の機嫌・揺らぎ.
  数時間のうちに続けて謝ると「もういいって」(enough), さらに続くと苛立たれる (irritated). 謝ったばかりなのに同じことをすると強く響く.
  メッセージの謝罪 (chat.apology_*) も, その場で謝る (コマンド apologize. 反応の条件 apology=...) も同じ判定.
- お礼: 最近 (1 日) 相手が何かしてくれた (favors: 会った・お金を貸した・相談にのった・自撮りを送った・おごった・看病した) なら効く.
  心当たりがなければ「え、何が？」, 同じことに何度も言うと「何回言うの」で効き目も薄い.
  謝ったあと (1 日のうち) のお礼は, 謝罪の結果しだい: 許してもらえた (quick・受け入れた late) → 心当たり (小さく効く) /
  半分だけ (half) → 効くことも「……まだ許したわけじゃないけど」(thanks_not_yet) のことも / 態度で・受け付けない・また同じこと
  (deeds・refuse・broken) → 「許してないけど」(thanks_unforgiven). 記録は apology_last (この扱いより前の謝罪の記録にも効く).
- あいさつ: 時間外 (昼のおはよう・朝のおやすみ) は戸惑われる / からかわれる. 同じ朝・同じ夜の 2 回目は「さっきも言ったよね」.
  毎朝 (毎晩) 送っていると当たり前になり, 急に途切れると性格によっては気にする (機嫌の理由に残る. settle).
- スタンプ: 相手からのメッセージにスタンプだけで返すと, 性格によっては「スタンプだけ？」. 続けて送ると嫌がられる.
- 今いい？ (may_call) / お疲れさま (otsukare) / 大丈夫？ (you_ok) / 今何してる？ (what_doing) / 返事まだ？ (nudge).
どれも確定的にはしない (効き目は bonds.realize を通る).
"""
import random
from datetime import datetime, timedelta

from . import knowsched as ks

APOLOGY_SPAN = 4 * 3600          # この間に続けて謝ると「もういいって」
LATE_AFTER = 12 * 3600           # これより前のことを謝ると「今さら？」
FAULT_DAYS = 4                   # 謝る対象として見る, あなたのせいの理由の古さ
REPEAT_DAYS = 14                 # 「同じ失敗の何度目か」に数える古さ
FAVOR_SPAN = 24 * 3600           # お礼が効く「最近」
DEEDS_QUIET = 8 * 3600           # 「態度で」: 連絡しすぎなら, これだけ連絡を控えると消える
GREET_OK = {"greet_morning": lambda h: 4 <= h < 12, "greet_night": lambda h: h >= 18 or h < 4}
GREET_ODD = {"greet_morning": lambda h: 13 <= h < 18 or h >= 21, "greet_night": lambda h: 5 <= h < 17}
GREET_WORD = {"greet_morning": "おはよう", "greet_night": "おやすみ"}
# 謝罪の結果ごとの効き目 (メッセージ. その場で謝るのは反応の effects)
APOLOGY_EFF = {"quick": {"mood": 4, "trust": 1}, "half": {"mood": 1}, "deeds": {}, "refuse": {"mood": -1},
               "enough": {"mood": -2}, "irritated": {"mood": -4, "stress": 3, "affection": -1}, "confused": {"mood": -1}}


def period(kind, dt):
    """あいさつの「その朝・その夜」の目印 (夜は日付をまたいでも同じ夜)."""
    d = dt - timedelta(hours=6) if kind == "greet_night" else dt
    return d.strftime("%Y-%m-%d")


class Manners:
    def __init__(self, app):
        self.app = app

    def grudge(self, char):
        """根に持つ (>1) ↔ さっぱり (<1). 控えめに効かせる."""
        return float(self.app.traits(char).get("grudge", 1.0))

    # ------------------------------------------------------------------ 謝罪
    def _faults(self, st, now):
        return [r for r in st.get("reasons") or [] if r["kind"] == "player" and r["mood"] == "bad"
                and not r.get("resolved") and now - r["t"] <= FAULT_DAYS * 86400]

    def apology(self, char, st, now, face=False):
        """謝った. 結果 {out, r, late} を決める (状態はまだ変えない. apply_apology で反映).
        out: quick / half / deeds / refuse / late / enough / irritated / none (謝ることが見当たらない)."""
        prev = [t for t in st.get("apologies") or [] if now - t < APOLOGY_SPAN]
        if len(prev) >= 2:
            return {"out": "irritated", "r": None}
        if prev:
            return {"out": "enough", "r": None}
        fs = self._faults(st, now)
        if not fs:
            return {"out": "none", "r": None}
        # いま効いている理由 (半日のうち) を先に謝る. それが無いときだけ, 前のことを謝る (「今さら？」)
        active = [x for x in fs if now - x["t"] <= LATE_AFTER]
        r = max(active or fs, key=lambda x: (abs(x.get("delta", 0)), x["t"]))
        p = st["params"]
        late = not active
        # 同じ失敗の何度目か: 同じ action の理由 (2 週間のうち). action の無い理由 (以前のセーブ・一度きりのこと) は数えない
        nth = sum(1 for x in st.get("reasons") or [] if x["kind"] == "player" and x["mood"] == "bad" and r.get("action")
                  and x.get("action") == r.get("action") and now - x["t"] <= REPEAT_DAYS * 86400) or 1
        L = self.app.life
        s = 0.75 - abs(r.get("delta", 0)) / 25.0 - 0.15 * max(0, nth - 1) + (p.get("mood", 50) - 50) / 120.0 \
            + (p.get("affection", 50) - 50) / 250.0 + (p.get("trust", 50) - 50) / 300.0 - (self.grudge(char) - 1) * 0.8 \
            + (0.08 * L.skill_soft("talk") if face else 0.0) - (0.1 if r.get("half") else 0.0) + random.gauss(0, 0.15)
        if late:
            return {"out": "late", "r": r, "s": s}
        out = "quick" if s >= 0.55 else "half" if s >= 0.3 else "deeds" if s >= 0.1 else "refuse"
        return {"out": out, "r": r, "s": s}

    def apply_apology(self, char, st, v, now):
        """謝罪の結果を反映する (理由を消す・弱める・残す. 謝罪の間隔)."""
        L = self.app.life
        st["apologies"] = [t for t in st.get("apologies") or [] if now - t < 86400] + [now]
        r, out = v.get("r"), v["out"]
        if out in ("quick", "late"):
            L.resolve(st, "bad", now, kind="player")            # 謝って消えるのは あなたのせいの理由だけ
            if r:
                r["resolved"] = True
        elif out == "half" and r:
            r["delta"] = round(r.get("delta", 0) * 0.5, 1)      # 半分だけ: 理由は残るが弱まる
            r["half"] = True
        elif out == "deeds" and r:
            r["deeds"] = now                                    # 態度で: 理由は残る (連絡しすぎなら, 控えれば消える)
        if r:
            st["apology_last"] = {"t": now, "action": r.get("action"), "out": out, "s": round(v.get("s", 0.0), 3)}

    def again(self, st, action, now):
        """謝ったばかり (1 日以内. 受け入れてもらえた) なのに, また同じこと."""
        al = st.get("apology_last") or {}
        return al.get("action") == action and now - al.get("t", 0) < 86400 and al.get("out") in ("quick", "half", "late", "deeds")

    # ------------------------------------------------------------------ お礼
    def favor(self, st, what, now):
        """相手が何かしてくれた (お礼の心当たり). 同じことが続けば一つにまとめる (6 時間)."""
        fs = [f for f in st.get("favors") or [] if now - f["t"] < FAVOR_SPAN * 2]
        last = next((f for f in reversed(fs) if f["what"] == what), None)
        if last and now - last["t"] < 6 * 3600:
            last["t"] = now
        else:
            fs.append({"t": now, "what": what, "thanked": 0})
        st["favors"] = fs[-12:]

    def thanks(self, st, now, char=None):
        """お礼を言った: (場面, 効き目). 謝ったあと (1 日のうち) なら, 謝罪の結果しだい (forgave)."""
        fs = [f for f in st.get("favors") or [] if now - f["t"] < FAVOR_SPAN]
        al = st.get("apology_last") or {}
        if al and 0 <= now - al.get("t", 0) < FAVOR_SPAN and al.get("out") and \
                al["t"] >= max([f["t"] for f in fs if not f["thanked"]] or [0]):
            got = self._thanks_forgave(st, al, char)
            if got:
                return got
        if not fs:
            return "thanks_what", {}
        fresh = [f for f in fs if not f["thanked"]]
        for f in fs:
            f["thanked"] += 1
        if fresh:
            return "thanks", {"mood": 3, "trust": 1, "affection": 0.5}
        return "thanks_again", {"mood": 0.5}

    def rejudge_thanks(self):
        """起動したとき一度: 謝ったあとのお礼が, 以前の判定で「え、何が？」(thanks_what) と返っていたら, 謝罪の結果しだいの
        本来の効き目を当て直す (トークの文面は書き換えない. 当て直した返信は thanks_rejudged に覚えて二重に当てない)."""
        app = self.app
        out = []
        for cid, char in app.chars.items():
            st = app.state(cid)
            al = st.get("apology_last") or {}
            if not al.get("out") or not al.get("t"):
                continue
            done = st.setdefault("thanks_rejudged", [])
            items = [it for it in app.chat.load(cid)["items"] if it.get("who") == "her" and it.get("kind") == "thanks_what"
                     and 0 <= it["t"] - al["t"] < FAVOR_SPAN and it["t"] not in done]
            for it in items:
                got = self._thanks_forgave(st, al, char)
                done.append(it["t"])
                if not got:
                    continue
                eff, _ = app.bonds.realize(char, st, got[1], "_chat_thanks", it["t"])
                app.apply_effects(st, app.trait_effects(char, eff))
                out.append((cid, got[0]))
            if items:
                del done[:-20]
                app.save_state(cid)
        return out

    def _thanks_forgave(self, st, al, char):
        """謝ったあとのお礼 (許してくれてありがとう). 謝罪の結果ごと. 扱わない結果 (enough など) なら None."""
        out = al["out"]
        n = int(al.get("thanked", 0))
        al["thanked"] = n + 1
        accepted = out == "quick" or (out == "late" and al.get("s", 0.3) >= 0.3)    # 以前の記録 (s なし) の late は受け入れたもの
        if accepted:
            return ("thanks", {"mood": 1.5, "trust": 0.5}) if not n else ("thanks_again", {"mood": 0.5})
        if out == "half":
            if n:
                return "thanks_again", {}
            g = self.grudge(char) if char else 1.0
            if random.random() < 0.5 - (g - 1) * 1.0:
                return "thanks", {"mood": 1, "trust": 0.5}
            return "thanks_not_yet", {"mood": -1}
        if out in ("deeds", "refuse", "broken"):
            return "thanks_unforgiven", {"mood": -2, "affection": -0.5}
        return None

    # ------------------------------------------------------------------ 送ったとき (時刻・続け方の記録)
    def on_send(self, char, st, kind, now):
        """送った時点のこと (返信を決めるときに使う). pend["meta"] に入れる."""
        app = self.app
        dt = datetime.fromtimestamp(now)
        meta = {}
        if kind in GREET_OK:
            g = st.setdefault("greets", {})
            key = period(kind, dt)
            if GREET_ODD[kind](dt.hour):
                meta["greet"] = "odd"
            elif g.get(kind) == key:
                meta["greet"] = "again"
            if GREET_OK[kind](dt.hour):
                g[kind] = key
                days = st.setdefault("greet_days", {}).setdefault(kind, [])
                if key not in days:
                    days.append(key)
                    del days[:-14]
        if kind == "stamp":
            d = app.chat.load(char["id"])
            items = [it for it in d["items"] if it["who"] in ("me", "her")]
            last = items[-1] if items else None
            meta["answering"] = bool(st.get("approach")) or bool(last and last["who"] == "her" and now - last["t"] < 6 * 3600)
            sts = [t for t in st.get("stamps") or [] if now - t < 3600]
            meta["stamps"] = len(sts)
            st["stamps"] = sts + [now]
        if kind == "what_doing":
            ws = [t for t in st.get("whatdo") or [] if now - t < 12 * 3600]
            meta["asked"] = len(ws)
            st["whatdo"] = ws + [now]
        return meta

    def nudge_urgent(self, char, st, pend, now):
        """催促が多少は許される急ぎの話か (約束の誘いの返事待ち・約束の直前)."""
        if pend and pend.get("kind") == "appoint":
            return True
        return any(x["cid"] == char["id"] and x.get("status") in ("set", "waiting") and 0 <= x["t"] - now < 3 * 3600
                   for x in self.app.appoint.all())

    # ------------------------------------------------------------------ 返信
    def reply(self, char, st, kind, now, ctx, meta):
        """chat.reply から: この種類の返信 (場面, 効き目, 置き換え). 扱わない種類なら None."""
        app, L = self.app, self.app.life
        p = st["params"]
        meta = meta or {}
        if kind == "apology":
            v = self.apology(char, st, now)
            self.apply_apology(char, st, v, now)
            out = "confused" if v["out"] == "none" else v["out"]
            if out == "late":
                return "apology_late", ({"mood": 1, "trust": 0.5} if v.get("s", 0) >= 0.3 else {"mood": -1}), {}
            return ("apology" if out == "quick" else "apology_" + out), dict(APOLOGY_EFF[out]), {}
        if kind == "thanks":
            key, eff = self.thanks(st, now, char)
            return key, eff, {}
        if kind in GREET_OK:
            g = meta.get("greet")
            if g == "odd":
                return ("greet_odd_morning" if kind == "greet_morning" else "greet_odd_night"), {"boredom": -2}, {}
            if g == "again":
                return "greet_again", {}, {}
            return None
        if kind == "stamp":
            if meta.get("stamps", 0) >= 2:
                return "stamp_spam", {"mood": -3, "boredom": 2}, {}
            want = float(app.traits(char).get("approach", 1))       # 話したがりほど「スタンプだけ？」と思う
            if meta.get("answering") and random.random() < min(0.8, 0.2 + 0.3 * (want - 0.5)):
                return "stamp_only", {"mood": -2, "loneliness": 2}, {}
            return None
        if kind == "may_call":
            busy = ctx.get("busy") or p.get("stress", 0) > 70 or random.random() < 0.15 + max(0.0, 40 - p.get("mood", 50)) / 100.0
            if busy:
                return "may_call_later", {}, {}
            st["call_ok_until"] = now + 30 * 60
            return "may_call_ok", {"mood": 1}, {}
        if kind == "otsukare":
            if self.just_finished(char, st, now):
                return "otsukare", {"mood": 3, "stress": -4, "loneliness": -3, "trust": 1}, {}
            return "otsukare_odd", {}, {}
        if kind == "you_ok":
            if self.knows_down(st, now):
                c = L.skill_soft("care")
                return "you_ok", {"mood": 2 + 4 * c, "trust": 1 + c, "loneliness": -4, "stress": -2 - 3 * c}, {}
            return "you_ok_what", {"mood": -0.5}, {}
        if kind == "what_doing":
            if meta.get("asked", 0) >= 2:
                L.add_reason(st, "player", "bad", "%sに何度も「今何してる？」と聞かれた" % app.pronouns(char)[2], now, told=True,
                             delta=-2.0, action="_what_doing")
                return "what_doing_much", {"mood": -3, "trust": -1, "affection": -1}, {}
            dt = datetime.fromtimestamp(now)
            sc = app.scene_at(char, st, dt)
            e = next((x for x in ks.notable(char) if x.get("label") == sc.get("label")), None)
            if e and random.random() < 0.6:
                app.knowsched.learn(char["id"], e, "message", now)
            return "what_doing", {"loneliness": -3, "boredom": -2}, {"doing": sc.get("label") or "のんびり"}
        if kind == "nudge":         # 返事を待たせていない (もう返した・何も来ていない) のに催促
            return "nudge_huh", {"mood": -2, "trust": -0.5}, {}
        return None

    def nudge_effect(self, char, st, pend, now):
        """返事を待っている間に「返事まだ？」と送った: 返信の前に一言 (場面, 効き目)."""
        if pend.get("nudge") == "ok":
            return "nudge_ok", {}
        self.app.life.add_reason(st, "player", "bad", "%sに返事を急かされた" % self.app.pronouns(char)[2], now, told=True,
                                 delta=-2.5, action="_nudge")
        return "nudge_bad", {"mood": -4, "affection": -1, "stress": 2}

    # ------------------------------------------------------------------ 知っていること
    def just_finished(self, char, st, now):
        """あなたが知っている予定 (knowsched) で, 相手の仕事・用事が少し前 (3 時間以内) に終わったか."""
        from .engine import day_match
        dt = datetime.fromtimestamp(now)
        mins = dt.hour * 60 + dt.minute
        known = self.app.knowsched.known_keys(st)
        return any(ks.key_of(e) in known and day_match(e.get("days"), dt) and 0 <= mins - ks._hm(e.get("to")) <= 180
                   for e in ks.notable(char))

    def saw_down(self, st, now):
        """相手の体調が悪い・落ち込んでいるのを, あなたが見聞きした (会った・やりとりした)."""
        p = st["params"]
        if p.get("health", 90) < 50 or p.get("mood", 50) < 35:
            st["seen_down"] = now

    def knows_down(self, st, now):
        p = st["params"]
        L = self.app.life
        told = any(r["kind"] == "event" and r["mood"] == "bad" and r["told"] for r in L.reasons(st, now))
        seen = now - st.get("seen_down", 0) < 36 * 3600 and (p.get("health", 90) < 60 or p.get("mood", 50) < 45)
        return told or seen

    # ------------------------------------------------------------------ ときどき (life.step から)
    def settle(self, char, st, now):
        """「態度で」の理由が, 連絡を控えたことで消える. あいさつの習慣が途切れたのを気にする."""
        app, L = self.app, self.app.life
        for r in self._faults(st, now):
            if r.get("deeds") and r.get("action") == "_too_often" and now - r["deeds"] >= DEEDS_QUIET \
                    and not any(t > r["deeds"] for t in st.get("contacts") or []):
                r["resolved"] = True
        dt = datetime.fromtimestamp(now)
        for kind in GREET_OK:
            if kind == "greet_morning":
                if dt.hour < 12:
                    continue
                key = period(kind, dt)
            else:
                if not 6 <= dt.hour < 18:
                    continue
                key = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
            noted = st.setdefault("greet_miss", {})
            days = (st.get("greet_days") or {}).get(kind) or []
            if noted.get(kind) == key or key in days:
                continue
            noted[kind] = key
            d0 = datetime.strptime(key, "%Y-%m-%d")
            before = {(d0 - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 8)}
            if len(before & set(days)) < 5:
                continue                            # まだ習慣になっていない
            tr = app.traits(char)
            p = st["params"]
            chance = 0.2 + 0.25 * (float(tr.get("approach", 1)) - 1) + 0.3 * (float(tr.get("absence", 1)) - 1) \
                + (p.get("affection", 50) - 50) / 150.0
            if random.random() < max(0.05, min(0.8, chance)):
                L.add_reason(st, "player", "bad", "今日は%sから「%s」がなかった" % (app.pronouns(char)[2], GREET_WORD[kind]), now,
                             told=True, delta=-1.5, action="_greet_miss")
