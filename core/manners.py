"""メッセージの受け止め方 (現実的に, めんどくさく): 謝罪・お礼・あいさつ・スタンプと, 「今いい？」などの短い連絡.

- 謝罪: 許し方に幅がある. すぐ許す (quick) / 半分だけ (half: 理由は消さず弱める) / 「謝るなら態度で」(deeds: 理由は残る.
  連絡しすぎなら, しばらく連絡を控えると消える) / 受け付けない (refuse). 決め手は 性格 (traits.grudge 根に持つ↔さっぱり.
  控えめ)・怒りの大きさ (理由の delta)・同じ失敗の何度目か・謝るまでの間 (日が経つと「今さら？」= late)・その日の機嫌・揺らぎ.
  数時間のうちに続けて謝ると「もういいって」(enough), さらに続くと苛立たれる (irritated). 謝ったばかりなのに同じことをすると強く響く.
  メッセージの謝罪 (chat.apology_*) も, その場で謝る (コマンド apologize. 反応の条件 apology=...) も同じ判定.
- お礼: 最近 (1 日) 相手が何かしてくれた (favors: 会った・お金を貸した・相談にのった・自撮りを送った・おごった・看病した・
  電話に出た・誕生日を教えた・誘いや約束を受けた・祝ってくれた・片付けてくれた) なら効く.
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
import re
import time
from datetime import datetime, timedelta

from . import knowsched as ks
from . import msgpick

COUNTED_APOLOGY = ("quick", "late", "enough", "irritated")
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
THANKS_GRACE = FAVOR_SPAN  # 謝罪の返事のあと, 連絡が多いうちに数えないお礼の間 (お礼が効く「最近」と同じ 1 日)
APOLOGY_EFF = {"quick": {"mood": 4, "trust": 1}, "half": {"mood": 1}, "deeds": {}, "refuse": {"mood": -1},
               "enough": {"mood": -2}, "irritated": {"mood": -4, "stress": 3, "affection": -1}, "confused": {"mood": -1},
               "near": {"mood": 1}, "unminded": {"trust": 0.5}}


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
    # メッセージへの返事で嫌がったこと → 機嫌の理由 (あなたのせい). 連絡しすぎ・何度も「今何してる？」などは別に残している
    BAD_REPLY_TELL = {"flirt_cold": "%sに軽々しく甘えられた", "tease_hurt": "%sにからかわれて、傷ついた",
                      "late_night": "%sから夜中に連絡が来た", "stamp_spam": "%sにスタンプばかり続けて送られた",
                      "selfie_pester": "%sに何度も自撮りをせがまれた",
                      # 約束を変えられた・取りやめられた (core/appoint.py の change_reply)
                      "appoint_change_sour": "%sに約束を変えられた", "appoint_change_sour_late": "%sに、間際になって約束を変えられた",
                      "appoint_change_sour_again": "%sに、何度も約束を変えられた", "appoint_cancel_sour": "%sに約束を取りやめられた",
                      "appoint_cancel_sour_late": "%sに、間際になって約束を取りやめられた",
                      "appoint_cancel_sour_again": "%sに、また約束を取りやめられた", "appoint_cancel_hurt": "%sに約束を取りやめられた",
                      "appoint_cancel_favor_sour": "当てにしていたのに、%sに頼みごとを取りやめられた"}

    def _faults(self, st, now):
        return [r for r in st.get("reasons") or [] if r["kind"] == "player" and r["mood"] == "bad"
                and not r.get("resolved") and now - r["t"] <= FAULT_DAYS * 86400]

    def happened(self, char, st, pick, now):
        """選んだ理由にあたることが, 実際にあったか (相手は気にしていなくても): 機嫌の理由 (良い・悪い・済んだもの) /
        送ったメッセージ (3 日のうち) / したコマンド (3 日のうち)."""
        span = 3 * 86400
        if any(msgpick.reason_item(r) == pick and now - r["t"] <= REPEAT_DAYS * 86400 for r in st.get("reasons") or []):
            return True
        if pick.startswith("msg:"):
            return any(it.get("who") == "me" and it.get("kind") == pick[4:] and 0 <= now - it.get("t", 0) <= span
                       for it in self.app.chat.load(char["id"])["items"])
        if pick.startswith("cmd:"):
            return any(e.get("action") == pick[4:] and 0 <= now - e.get("t", 0) <= span for e in self.app.log(char["id"]))
        return False

    def apology(self, char, st, now, face=False, pick=None):
        """謝った. 結果 {out, r, late} を決める (状態はまだ変えない. apply_apology で反映).
        out: quick / half / deeds / refuse / late / enough / irritated / none (謝ることが見当たらない).
        pick: 謝る理由を選んだ (メッセージ. core/msgpick.py). そのときは理由で決まる:
          相手が気にしていること → これまでどおりの許し方 / 近いこと → near (「それもだけど……」少し効く) /
          あったが気にしていないこと → unminded (「気にしてない」) / 心当たりなし → none (気にしていることがあれば, ずれていて少し下がる: miss)."""
        prev = [t for t in st.get("apologies") or [] if now - t < APOLOGY_SPAN]
        fs = self._faults(st, now)
        if pick is not None and not prev:
            hit = [x for x in fs if msgpick.reason_item(x) == pick]
            if not hit:
                nr = [x for x in fs if msgpick.reason_item(x) is None or msgpick.near(pick, msgpick.reason_item(x), self.app)]
                out = "near" if nr else "unminded" if self.happened(char, st, pick, now) else "none"
                self.app.trace.add("manners", "謝罪の判定 (理由を選んだ): %s" % out, char.get("id"), now, pick=pick,
                                   faults=[msgpick.reason_item(x) for x in fs])
                if out == "near":
                    return {"out": "near", "r": max(nr, key=lambda x: (abs(x.get("delta", 0)), x["t"]))}
                return {"out": out, "r": None, "miss": bool(fs)}
            fs = hit
        if len(prev) >= 2 or prev or not fs:
            out = "irritated" if len(prev) >= 2 else "enough" if prev else "none"
            self.app.trace.add("manners", "謝罪の判定: %s" % out, char.get("id"), now, prev=len(prev), faults=len(fs))
            return {"out": out, "r": None}
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
        out = "late" if late else "quick" if s >= 0.55 else "half" if s >= 0.3 else "deeds" if s >= 0.1 else "refuse"
        self.app.trace.add("manners", "謝罪の判定: %s" % out, char.get("id"), now, s=s, reason=r.get("tell"), delta=r.get("delta"),
                           nth=nth, late=late, face=face, mood=p.get("mood"), affection=p.get("affection"), trust=p.get("trust"),
                           grudge=self.grudge(char))
        return {"out": out, "r": r, "s": s}

    def apply_apology(self, char, st, v, now):
        """謝罪の結果を反映する (理由を消す・弱める・残す. 謝罪の間隔)."""
        L = self.app.life
        r, out = v.get("r"), v["out"]
        st["apologies"] = [t for t in st.get("apologies") or [] if now - t < 86400]
        if out in COUNTED_APOLOGY:     # 「もういいって」と言えるのは, 許したあと (何のことかわからない・まだ許していないなら数えない)
            st["apologies"].append(now)
        if out in ("quick", "late"):
            L.resolve(st, "bad", now, kind="player")            # 謝って消えるのは あなたのせいの理由だけ
            if r:
                r["resolved"] = True
        elif out == "half" and r:
            r["delta"] = round(r.get("delta", 0) * 0.5, 1)      # 半分だけ: 理由は残るが弱まる
            r["half"] = True
        elif out == "deeds" and r:
            r["deeds"] = now                                    # 態度で: 理由は残る (連絡しすぎなら, 控えれば消える)
        elif out == "near" and r:
            r["delta"] = round(r.get("delta", 0) * 0.75, 1)     # それもだけど……: 本当のことは残るが, 少し和らぐ
            return
        if r:
            st["apology_last"] = {"t": now, "action": r.get("action"), "out": out, "s": round(v.get("s", 0.0), 3)}

    def again(self, st, action, now):
        """謝ったばかり (1 日以内. 受け入れてもらえた) なのに, また同じこと."""
        al = st.get("apology_last") or {}
        return al.get("action") == action and now - al.get("t", 0) < 86400 and al.get("out") in ("quick", "half", "late", "deeds")

    def thanks_grace(self, st, sent):
        """謝罪の返事が来てから 1 日のうちに送った「ありがとう」1 通目: 連絡が多いうちに数えない
        (許してくれたことへのお礼で「謝ったばかりなのに」まで言われないように. 2 通目からは今までどおり)."""
        al = st.get("apology_last") or {}
        return bool(al.get("t")) and 0 <= sent - al["t"] < THANKS_GRACE and not al.get("grace_used")

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

    def thanks_pick(self, st, now, pick, char=None):
        """お礼の理由を選んだ (メッセージ. core/msgpick.py): 最近してくれて, まだお礼していないこと → 効く /
        前のこと・もうお礼したこと → thanks_again / していないこと → thanks_what (「何のお礼？」)."""
        al = st.get("apology_last") or {}
        if pick == "forgave":
            if al and 0 <= now - al.get("t", 0) < FAVOR_SPAN and al.get("out"):
                got = self._thanks_forgave(st, al, char)
                if got:
                    return got
                return "thanks_again", {"mood": 0.5}
            return "thanks_what", {}
        fs = [f for f in st.get("favors") or [] if f["what"] == pick and now - f["t"] < FAVOR_SPAN * 2]
        self.app.trace.add("manners", "お礼の判定 (理由を選んだ)", (char or {}).get("id"), now, pick=pick,
                           favors=[f["what"] for f in st.get("favors") or []])
        if not fs:
            return "thanks_what", {}
        fresh = [f for f in fs if not f["thanked"] and now - f["t"] < FAVOR_SPAN]
        for f in fs:
            f["thanked"] += 1
        if fresh:
            return "thanks", {"mood": 3, "trust": 1, "affection": 0.5}
        return "thanks_again", {"mood": 0.5}

    def thanks(self, st, now, char=None):
        """お礼を言った: (場面, 効き目). 謝ったあと (1 日のうち) なら, 謝罪の結果しだい (forgave)."""
        fs = [f for f in st.get("favors") or [] if now - f["t"] < FAVOR_SPAN]
        al = st.get("apology_last") or {}
        fresh = [f for f in fs if not f["thanked"]]
        # 許してくれたことへのお礼. もう言ったあとで, まだお礼していない心当たりがあれば そちらへのお礼
        if al and 0 <= now - al.get("t", 0) < FAVOR_SPAN and al.get("out") and \
                al["t"] >= max([f["t"] for f in fresh] or [0]) and not (al.get("thanked") and fresh):
            got = self._thanks_forgave(st, al, char)
            if got:
                return got
        self.app.trace.add("manners", "お礼の判定", (char or {}).get("id"), now, favors=[f["what"] for f in fs], fresh=len(fresh),
                           apology_last=al.get("out"))
        if not fs:
            return "thanks_what", {}
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
            done = st.setdefault("thanks_rejudged", [])
            before = {k: float(st["params"].get(k, 0)) for k in ("mood", "trust", "affection")}
            items = [it for it in app.chat.load(cid)["items"] if it.get("who") == "her" and it.get("kind") == "thanks_what"
                     and 0 <= it["t"] - al["t"] < FAVOR_SPAN and it["t"] not in done] if al.get("out") and al.get("t") else []
            for it in items:
                got = self._thanks_forgave(st, al, char)
                done.append(it["t"])
                if not got:
                    continue
                eff, _ = app.bonds.realize(char, st, got[1], "_chat_thanks", it["t"])
                app.apply_effects(st, app.trait_effects(char, eff))
                out.append((cid, got[0]))
            # 許してもらったあと (1 日のうち) のお礼 1 通目に, 以前の判定で「連絡多くない？」「謝ったばかりなのに」が返っていた:
            # その分の機嫌の下がり・理由・連絡の回数を戻し, お礼として当て直す (文面は書き換えない)
            regrace = self._regrace(cid, char, st, al, done)
            out += regrace
            if items or regrace:
                del done[:-20]
                self._rejudge_note(cid, st, before)
                app.save_state(cid)
            elif done and not st.get("rejudge_noted"):      # 知らせを出す前の版で当て直し済み: 済んだことだけ知らせる
                st["rejudge_noted"] = True
                app.chat.add(cid, "sys", "（以前に送った「ありがとう」は、今の決まりで受け止め直し済み）", kind="rejudge", t=time.time())
                app.save_state(cid)
        return out

    PARAM_LABEL = {"mood": "機嫌", "trust": "信頼", "affection": "好感度"}

    COUNTED_KEYS = {"apology": "quick", "apology_late": "late", "apology_enough": "enough", "apology_irritated": "irritated"}

    def apology_count_comp(self, now=None):
        """不具合のお詫び (一度だけ. ワールドごと): 謝ることが見当たらなかった (「何のこと？」)・まだ許していない謝罪まで
        「続けて謝った」に数えていた. 2 日のうちのトークを見て, 許したあとでないのに「もういいって」(enough / irritated) と
        返していた分の効き目を戻し, 数え直す (トークの文面は書き換えない). 戻した {cid: 回数} を返す."""
        app = self.app
        now = now or time.time()
        done = app.life.player_state().setdefault("fix_comp", {})
        if done.get("apology_count"):
            return {}
        done["apology_count"] = now
        app.life.save_player()
        out = {}
        for cid, char in app.chars.items():
            st = app.state(cid)
            replies = sorted((it for it in app.chat.load(cid)["items"] if it.get("who") == "her" and now - it["t"] < 2 * 86400
                              and (it.get("kind") or "").startswith("apology")), key=lambda it: it["t"])
            counted, drop, before, n = [], [], {k: float(st["params"].get(k, 0)) for k in self.PARAM_LABEL}, 0
            for it in replies:
                out_ = self.COUNTED_KEYS.get(it["kind"])
                if out_ in ("enough", "irritated") and not [t for t in counted if 0 <= it["t"] - t < APOLOGY_SPAN]:
                    app.apply_effects(st, {k: -v for k, v in APOLOGY_EFF[out_].items()})
                    n += 1
                    out_ = None
                if out_:
                    counted.append(it["t"])
                else:
                    drop.append(it["t"])
            if not drop:
                continue
            st["apologies"] = [t for t in st.get("apologies") or [] if not any(abs(t - d) < 2 for d in drop)]
            if n:
                diff = ["%s %+.1f" % (self.PARAM_LABEL[k], float(st["params"].get(k, 0)) - v) for k, v in before.items()
                        if abs(float(st["params"].get(k, 0)) - v) >= 0.05]
                app.chat.add(cid, "sys", "（不具合のお詫び: 許したあとでないのに「もういい」と返していた分を戻した%s）"
                             % ("：" + "・".join(diff) if diff else ""), kind="rejudge", t=now)
                out[cid] = n
            app.save_state(cid)
        return out

    def _rejudge_note(self, cid, st, before):
        """当て直したことを, その人のトークとサーバのログに残す (効いたかが分かるように)."""
        diff = [(k, float(st["params"].get(k, 0)) - v) for k, v in before.items()]
        parts = ["%s %+.1f" % (self.PARAM_LABEL[k], d) for k, d in diff if abs(d) >= 0.05]
        text = "（以前に送った「ありがとう」を、今の決まりで受け止め直した%s）" % ("：" + "・".join(parts) if parts else "")
        st["rejudge_noted"] = True
        self.app.chat.add(cid, "sys", text, kind="rejudge", t=time.time())
        self.app.logq.put("%s [INFO] お礼の当て直し %s: %s" % (datetime.now().strftime("%m-%d %H:%M:%S"), cid, "・".join(parts) or "変化なし"))

    TOO_OFTEN_EFF = {"too_often": {"mood": -2, "affection": -1}, "too_often_again": {"mood": -5, "trust": -2, "affection": -1},
                     "too_often_mild": {"mood": -2}}
    RETRO_DAYS = 4           # 以前の「連絡多くない？」を判定し直す古さ (これより前でも, 理由がまだ解決していなければ)

    def retro_contacts(self):
        """起動したとき一度: 連絡しすぎの数え方 (重み) を以前の記録にも遡って効かせる.
        1. 以前の contacts (時刻だけ) を, トークの記録と突き合わせて {t, w, k} に置き換える (突き合わせられない分は 1 回のまま).
        2. 以前の判定で返った「連絡多くない？」「謝ったばかりなのに」(今も効いている分) を, その時点の記録で今の判定にかけ直し,
           「多い」にならなかったものは 下がった機嫌・信頼・好感度を戻し, そのとき足された理由を解決済みにする
           (トークの文面は書き換えず, 知らせを一度. contacts_rejudged に覚えて二重に当てない. お礼の当て直しで戻した分は除く).
        3. 数え方の 3 版目 (contacts_v3: 好感度・信頼で許容が変わる / 手が離せなくても許容を減らさない / 許容の 1.5 倍で「多い」
           / 返事を待って 1 通送るのはふつう / 好かれていれば好感度は下がらない) でも同じように判定し直す. 2 版目で戻した分は除く.
           今の決まりでも多かった「連絡多くない？」は, いまの好感度が低くなければ, 下がった好感度だけ戻す."""
        app, B = self.app, self.app.bonds
        now = time.time()
        out = []
        for cid, char in app.chars.items():
            st = app.state(cid)
            items = app.chat.load(cid)["items"]
            hist = B.history_weights(items)
            changed = False
            cs = st.get("contacts") or []
            if any(not isinstance(x, dict) for x in cs):
                new = []
                for x in cs:
                    if isinstance(x, dict):
                        new.append(x)
                        continue
                    hit = next((h for h in hist if abs(h[0] - float(x)) < 2), None)
                    new.append({"t": float(x), "w": round(hit[1], 2), "k": hit[2], "retro": True} if hit else x)
                st["contacts"] = new
                changed = True
            if st.get("contacts_settled"):          # 精算済み (settle_contacts): 以前の判定はもう当て直さない
                if changed:
                    app.save_state(cid)
                continue
            done = st.setdefault("contacts_rejudged", [])           # 2 版目で判定し直したもの
            done3 = st.setdefault("contacts_rejudged3", [])
            since = st.setdefault("contacts_v3", now)       # この数え方になった時刻: これより前の判定だけ判定し直す
            graced = set(st.get("thanks_rejudged") or [])
            before = {k: float(st["params"].get(k, 0)) for k in ("mood", "trust", "affection")}
            fixed = 0
            for it in items:
                if it.get("who") != "her" or it.get("kind") not in self.TOO_OFTEN_EFF or it["t"] in done3 or it["t"] in graced \
                        or it["t"] >= since:
                    continue
                live = [r for r in st.get("reasons") or [] if r.get("action") == "_too_often" and abs(r.get("t", 0) - it["t"]) < 2]
                unresolved = any(not r.get("resolved") for r in live)
                if it["t"] in done and not unresolved:
                    continue                                  # 2 版目で戻した (か, 謝って済んだ) 分
                if now - it["t"] > self.RETRO_DAYS * 86400 and not unresolved:
                    continue
                done3.append(it["t"])
                changed = True
                total = sum(w for t, w, _ in hist if it["t"] - 86400 < t <= it["t"])
                if total > B.TOO_OFTEN_RATIO * B.tolerance(char, cid, st, it["t"]):
                    if it["kind"] == "too_often" and st["params"].get("affection", 50) >= 35:
                        app.apply_effects(st, {"affection": 1})       # 今の決まりなら, 好かれていれば好感度は下がらなかった
                        fixed += 1
                        out.append((cid, "too_often_mild"))
                    continue                                  # 今の数え方でも多かった: そのまま
                app.apply_effects(st, {k: -v for k, v in self.TOO_OFTEN_EFF[it["kind"]].items()})
                for r in live:
                    r["resolved"] = True
                al = st.get("apology_last") or {}
                if it["kind"] == "too_often_again" and al.get("out") == "broken" and al.get("out_before"):
                    al["out"] = al["out_before"]
                fixed += 1
                out.append((cid, it["kind"]))
            if fixed:
                diff = {k: round(float(st["params"].get(k, 0)) - before[k], 1) for k in before}
                names = {"mood": "機嫌", "trust": "信頼", "affection": "好感度"}
                parts = ["%s %+g" % (names[k], v) for k, v in diff.items() if v]
                app.chat.add(cid, "sys", "（以前の「連絡が多い」を、今の数え方で受け止め直した%s）" % ("：" + "・".join(parts) if parts else ""),
                             kind="rejudge", t=now)
                app.logq.put("%s [INFO] 連絡しすぎの当て直し %s: %d 件 %s" % (datetime.now().strftime("%m-%d %H:%M:%S"), cid, fixed, "・".join(parts)))
            if changed or since == now:
                del done[:-40]
                del done3[:-40]
                app.save_state(cid)
        return out
    REFUND_RE = re.compile(r"(好感度|信頼) ([+-][\d.]+)")

    def settle_contacts(self):
        """起動したとき一度 (contacts_settled): 連絡しすぎの判定で下がりすぎていた好感度・信頼を, 今の決まりで精算する.
        retro_contacts は 4 日より古い判定・その時点で好感度 35 未満なら好感度を戻さない・電話の「また電話？」は見ない, ので取りこぼしていた.
        ・以前 (contacts_v3 より前) の「連絡多くない？」「謝ったばかりなのに」の全部と, 好感度が下がった「また電話？」について,
          実際に下がった分 (ログの記録. なければ決まりの値) と, 今の決まりで下がるはずの分を比べる
          (多くなかった → 0. 多かった「連絡多くない？」→ そのとき好感度 35 未満なら好感度だけ. 「謝ったばかりなのに」→ そのまま)
        ・そのときの好感度は, いまの値に, その後に下がった分を足し戻して見積もる (下がったせいで 35 を切った分を「嫌われていた」にしない)
        ・これまでの当て直し (トークの「連絡が多い」を受け止め直した知らせ) で戻した分を引いて, 足りない分だけ戻す.
          お礼の当て直しで戻した分 (thanks_rejudged) は済んでいるので数えない
        ・機嫌は時間で戻っているので戻さない. 好感度・信頼だけ. 知らせを一度."""
        app, B = self.app, self.app.bonds
        now = time.time()
        out = []
        for cid, char in app.chars.items():
            st = app.state(cid)
            if st.get("contacts_settled"):
                continue
            st["contacts_settled"] = now
            since = st.get("contacts_v3") or now
            items = app.chat.load(cid)["items"]
            hist = B.history_weights(items)
            log = {e["t"]: e for e in app.log(cid) if e.get("action") in ("_chat", "call")}
            graced = set(st.get("thanks_rejudged") or [])
            hits = []           # (時刻, 実際に下がった好感度, 信頼, 今の決まりで下がる信頼, 好感度を残すのは好かれていなかったときだけか, 多かったか)
            for it in items:
                if it.get("who") != "her" or it.get("kind") not in ("too_often", "too_often_again") or it["t"] >= since                         or it["t"] in graced:
                    continue
                d = (log.get(it["t"]) or {}).get("deltas") or self.TOO_OFTEN_EFF[it["kind"]]
                total = sum(w for t, w, _ in hist if it["t"] - 86400 < t <= it["t"])
                over = total > B.TOO_OFTEN_RATIO * B.tolerance(char, cid, st, it["t"])
                hits.append((it["t"], -min(0.0, float(d.get("affection", 0))), -min(0.0, float(d.get("trust", 0))),
                             -min(0.0, float(d.get("trust", 0))) if over else 0.0, it["kind"] == "too_often", over))
            for e in log.values():
                d = e.get("deltas") or {}
                if e["action"] == "call" and e["t"] < since and float(d.get("affection", 0)) < 0 and float(d.get("mood", 0)) < 0:
                    hits.append((e["t"], -float(d["affection"]), 0.0, 0.0, False, False))    # 今の決まりでは電話で好感度は下がらない
            back = {"affection": 0.0, "trust": 0.0}
            for it in items:
                if it.get("kind") == "rejudge" and "連絡が多い" in it.get("text", ""):
                    for name, v in self.REFUND_RE.findall(it["text"]):
                        back["affection" if name == "好感度" else "trust"] += float(v)
            aff = float(st["params"].get("affection", 50)) - back["affection"]
            owed = {"affection": -back["affection"], "trust": -back["trust"]}
            for t, a, tr, keep_tr, mild, over in sorted(hits, key=lambda x: -x[0]):
                aff += a                          # この判定の直前の好感度 (の見積もり)
                keep_a = a if over and (not mild or aff < 35) else 0.0
                owed["affection"] += a - keep_a
                owed["trust"] += tr - keep_tr
            eff = {k: round(v, 1) for k, v in owed.items() if v >= 0.1}
            if eff:
                got = app.apply_effects(st, eff)
                parts = ["%s %+g" % (self.PARAM_LABEL[k], v) for k, v in got.items()]
                app.chat.add(cid, "sys", "（以前の「連絡多くない？」「また電話？」で下がりすぎていた分を、今の決まりで精算した%s）"
                             % ("：" + "・".join(parts) if parts else ""), kind="rejudge", t=now)
                app.logq.put("%s [INFO] 連絡しすぎの精算 %s: %d 件 %s" % (datetime.now().strftime("%m-%d %H:%M:%S"), cid, len(hits), "・".join(parts)))
                out.append((cid, "settled"))
            app.save_state(cid)
        return out

    APOLOGY_KEY_OUT = {"apology": "quick", "apology_half": "half", "apology_deeds": "deeds", "apology_late": "late"}

    def _regrace(self, cid, char, st, al, done):
        """許してもらった直後のお礼に, 以前の判定で「連絡多くない？」「謝ったばかりなのに」が返っていたら当て直す.
        ・謝罪の返事のあと 1 日のうちに送ったお礼 1 通目
        ・謝罪の返事を待っている間に送ったお礼 (以前は謝罪が上書きされて, 謝罪そのものが判定されていなかった):
          謝罪をいま判定し直してから, お礼として当て直す."""
        app = self.app
        items = app.chat.load(cid)["items"]
        seq, out = [], []                 # 相手の返事のあとに続けて送ったもの
        for it in items:
            if it.get("who") == "me":
                seq.append(it)
                continue
            if it.get("who") != "her":
                continue
            run, seq = seq, []
            if it.get("kind") not in self.TOO_OFTEN_EFF or it["t"] in done or it["t"] in (st.get("contacts_rejudged") or []) \
                    or it["t"] in (st.get("contacts_rejudged3") or []) \
                    or not run or run[-1].get("kind") != "thanks":
                continue
            last_me = run[-1]
            lost = any(x.get("kind") == "apology" for x in run[:-1])
            graced = al.get("t") and 0 <= last_me["t"] - al["t"] < THANKS_GRACE and not al.get("grace_used")
            if not (lost or graced):
                continue
            done.append(it["t"])
            if it["kind"] == "too_often_again" and al.get("out") == "broken":
                before = al.get("out_before")
                if not before:            # 以前の記録: 謝罪への返信の種類から
                    prev = [x for x in items if x.get("who") == "her" and x["t"] <= al["t"] + 1
                            and (x.get("kind") or "") in self.APOLOGY_KEY_OUT]
                    before = self.APOLOGY_KEY_OUT[prev[-1]["kind"]] if prev else "quick"
                al["out"] = before
            app.apply_effects(st, {k: -v for k, v in self.TOO_OFTEN_EFF[it["kind"]].items()})
            for r in st.get("reasons") or []:
                if r.get("action") == "_too_often" and abs(r.get("t", 0) - it["t"]) < 2:
                    r["resolved"] = True
            st["contacts"] = [x for x in st.get("contacts") or [] if abs(app.bonds.contact_t(x) - last_me["t"]) >= 1]
            if lost:                      # 判定されていなかった謝罪を, 届いた時刻のこととして判定する (バグで遅れた分を「今さら」にしない)
                ap_t = [x for x in run[:-1] if x.get("kind") == "apology"][-1]["t"]
                v = self.apology(char, st, ap_t)
                self.apply_apology(char, st, v, ap_t)
                eff, _ = app.bonds.realize(char, st, dict(APOLOGY_EFF.get(v["out"], {})), "_chat_apology", ap_t)
                app.apply_effects(st, app.trait_effects(char, eff))
                al = st.get("apology_last") or al
            al["grace_used"] = True
            if al.get("out"):
                got = self._thanks_forgave(st, al, char)
                if got:
                    eff, _ = app.bonds.realize(char, st, got[1], "_chat_thanks", it["t"])
                    app.apply_effects(st, app.trait_effects(char, eff))
                    out.append((cid, got[0]))
            break                         # 当て直すのは 1 通目だけ
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

    def greet_fits(self, char, kind, dt):
        """時計では変な時刻のあいさつでも, 本人の暮らしには合っているか (夜勤・夜型の人): 「おはよう」は起きて 3 時間のうち,
        「おやすみ」はこれから 3 時間のうちに寝るなら, 変ではない. 基本の予定で見る."""
        app = self.app
        if app._base_scene(char, dt).get("asleep"):
            return False
        step = -1 if kind == "greet_morning" else 1
        return any(app._base_scene(char, dt + timedelta(minutes=step * m)).get("asleep") for m in range(15, 181, 15))

    # ------------------------------------------------------------------ 送ったとき (時刻・続け方の記録)
    def on_send(self, char, st, kind, now, to=None):
        """送った時点のこと (返信を決めるときに使う). pend["meta"] に入れる."""
        app = self.app
        dt = datetime.fromtimestamp(now)
        meta = {}
        if kind in GREET_OK:
            g = st.setdefault("greets", {})
            key = period(kind, dt)
            if GREET_ODD[kind](dt.hour) and not self.greet_fits(char, kind, dt):
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
            # 相手のメッセージへの返事か (以前は, 送ったスタンプをトークに足したあとで最後の発言を見ていたので,
            # 相手から来た働きかけへの返事のときしか「スタンプだけ？」にならなかった. 送る前に見た「何に返したか」で)
            meta["answering"] = bool(st.get("approach")) or bool(to and now - float(to.get("t", 0)) < 6 * 3600)
            if to:
                meta["to_tone"] = to.get("tone")           # 何にスタンプで返したか (大事な話にスタンプだけだと, 軽く流された)
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
        if pend and pend.get("kind") in ("appoint", "appoint_change", "appoint_cancel_me"):
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
            v = self.apology(char, st, now, pick=meta.get("reason"))
            self.apply_apology(char, st, v, now)
            out = "confused" if v["out"] == "none" else v["out"]
            if out == "late":
                return "apology_late", ({"mood": 1, "trust": 0.5} if v.get("s", 0) >= 0.3 else {"mood": -1}), {}
            eff = dict(APOLOGY_EFF[out])
            if out == "confused" and v.get("miss"):      # 気にしていることは別にある: ずれていて, 少し下がる
                eff = {"mood": -2}
            return ("apology" if out == "quick" else "apology_" + out), eff, {}
        if kind == "thanks":
            key, eff = self.thanks_pick(st, now, meta["reason"], char) if meta.get("reason") else self.thanks(st, now, char)
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
            sk = meta.get("stamp")
            if sk == "heart":                    # ハート: 近い仲ならうれしい. 浅い仲だと, なれなれしい
                if app.bonds.stage(char["id"]) in ("visit", "live") or p.get("affection", 0) >= 65:
                    return "stamp_heart", {"heart": 2, "affection": 0.5}, {}
                return "stamp_heart_cold", {"shyness": 3, "affection": -1}, {}
            if sk == "sorry" and any(abs(r.get("delta", 0)) >= 6 for r in self._faults(st, now)):
                return "stamp_sorry_bad", {"mood": -2}, {}          # 本当に怒っているときに, スタンプで済ませる
            if sk == "thanks":                   # お礼のスタンプ: 最近してくれたことがあれば, 軽いお礼
                fresh = [f for f in st.get("favors") or [] if now - f["t"] < FAVOR_SPAN and not f["thanked"]]
                if fresh:
                    fresh[-1]["thanked"] += 1
                    return "stamp_thanks", {"mood": 1.5, "trust": 0.5}, {}
            want = float(app.traits(char).get("approach", 1))       # 話したがりほど「スタンプだけ？」と思う
            # 何に返したか: 沈んだ話・寂しい・問いかけ・聞かせてくれた話 にスタンプだけだと, 軽く流されたと受け取りやすい.
            # うれしい話・用件の連絡・あいさつ・切り上げ には, スタンプで十分
            heavy = {"down": 0.35, "lonely": 0.35, "upset": 0.3, "question": 0.3, "where": 0.45, "news": 0.2, "advice": 0.15}
            light = ("happy", "notice", "greet", "close")
            tone = meta.get("to_tone")
            base = 0.2 + 0.3 * (want - 0.5)
            base = base * 0.3 if tone in light else base + heavy[tone] if tone in heavy else base * 0.6
            if meta.get("answering") and random.random() < min(0.85, base):
                return "stamp_only", {"mood": -2, "loneliness": 2}, {}
            return None
        if kind == "may_call":
            busy = ctx.get("busy") or p.get("stress", 0) > 70 or random.random() < 0.15 + max(0.0, 40 - p.get("mood", 50)) / 100.0
            if busy:
                st.pop("call_ok_until", None)
                st["call_later_until"] = now + 30 * 60        # 「あとで」と言ったばかり: すぐかかってきたら, そう言う
                return "may_call_later", {}, {}
            st.pop("call_later_until", None)
            st["call_ok_until"] = now + 30 * 60
            return "may_call_ok", {"mood": 1}, {}
        if kind == "otsukare":
            if self.just_finished(char, st, now):
                return "otsukare", {"mood": 3, "stress": -4, "loneliness": -3, "trust": 1}, {}
            return "otsukare_odd", {}, {}
        if kind == "you_ok":
            # 沈んだ話・寂しい と言われたあとの「大丈夫？」は, 流れとして通じる (気づいてくれた)
            if self.knows_down(st, now) or (meta.get("to") or {}).get("tone") in ("down", "lonely"):
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
                    and not any(app.bonds.contact_t(x) > r["deeds"] for x in st.get("contacts") or []):
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
