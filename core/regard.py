"""相手の中の「あなたの見立て」: 思われている度と確かさ (相手ごと. 画面には出さない).

- 思われている度 (v. 0〜100): 相手が「あなたに好かれている」と思っている度合い. 好感度 (相手 → あなた) とは別の値.
- 確かさ (sure. 0〜1): その見立てにどれだけ自信があるか. 低いほど, 出来事ごとに大きく揺れる.

動かすのは, 相手から見える あなたの振る舞いだけ (sign): どちらから連絡を始めるか・返事の速さ・既読のまま・誘いに応じた / 断った・
約束を守った / すっぽかした・誕生日や記念日を覚えていた / 忘れていた・贈り物・謝った・会っている日 / ご無沙汰・ほかの人との深い仲.
悪い印のほうが強く効く (SIGNS の大きさと, 一日に動く幅の上限). あなた (プレイヤー) の側の値は持たない.

性格で読み違える (READING): 卑屈・内気は低く見積もり (良い印を割り引き, 悪い印を重く取る), ドS・お嬢様・気高いは高めに取る.
ツンデレ・不思議さんは確かさが上がりにくい. 性格の traits に regard_bias / regard_sure があればそちら.

効き方 (相手の気持ち = 好感度 と, 見立てのずれ):
- hold (好きなのに, 思われていないと感じる): 誘いを控える (appoint._maybe_invite / _maybe_now). 自分からの連絡は,
  依存度が高ければ不安で増え, そうでなければ減る (presence.live). ときどき探りを入れる (「話そう」の理由 unsure: 最近忙しい？).
- lean (思われていると感じる): 誘い・連絡に少し踏み出しやすい. 段階の提案を受ける気持ち (bonds.readiness) にも足す.

あなたの癖 (habit. 1.7.0 の段 2〜3): 相手は, あなたの返信の傾向を時間帯 (夜中・朝・昼・夕方・夜) × 平日 / 休日 の枠ごとに覚える
(来たメッセージの数・返した数・返すまでの分). 覚えた枠で ふだんどおりの遅さ・返ってこなさ は「無視されたわけではない」と軽く受け取り
(ease < 1), ふだんよく返す枠で返ってこない・ふだんよりずっと遅いと, いつもより気にして (ease > 1), ときどき「何かあった？」と聞く
(「話そう」の理由 changed). 覚えるまで (枠の記録が少ないうち) は, いままでと同じ. からかいの多さ・連絡を始める時間帯も覚える.
記録は 1 件ごと・日がたつごとに薄れる (古い癖は 1 か月ほどで薄れる). 遡及はしない (これからの分から覚える).

初めの値は, はじめて使うとき (以前のセーブなら更新後の最初) に, 今の関係と最近のやりとりから一度だけ決める (baseline).
公理: 確定させない (揺らぎ・一日の上限). 見立ては相手の頭の中のもので, 当たっているとは限らない.
"""
import random
import time
from datetime import datetime

from . import market

DAY_CAP = {"+": 6.0, "-": 10.0}       # 一日に動く幅の上限 (悪いほうが大きい)
SURE_MAX = 0.9
PROBE_GAP = 3 * 86400                 # 探りを入れる間隔
APOLOGY_OUTS = ("quick", "half", "deeds", "late", "near")     # 謝ったことが相手に届いた結果 (心当たりのない謝罪・しつこい謝罪は数えない)
# 印: 種類 → (動かす量, 何を見たか). 量は「確かさ 0.7・読み違えなし」のときの目安
SIGNS = {
    "start": (0.8, "あなたから連絡してきた"),
    "reply_fast": (1.2, "すぐに返事が来た"),
    "reply": (0.6, "返事が来た"),
    "reply_slow": (0.2, "だいぶ経ってから返事が来た"),
    "warm": (1.0, "返事があたたかかった"),
    "cold": (-1.2, "返事がよくなかった"),
    "probe_warm": (2.5, "探りにちゃんと返してくれた"),
    "probe_cold": (-2.0, "探りを流された"),
    "ignored_read": (-3.0, "既読のまま返事が来なかった"),
    "ignored_unread": (-0.8, "読まれないまま返事が来なかった"),
    "ignored_long": (-2.0, "既読のまま, ずっと放っておかれた"),
    "invite_yes": (2.5, "誘いに応じてくれた"),
    "invite_no": (-2.0, "誘いを断られた"),
    "favor_yes": (1.5, "頼みを引き受けてくれた"),
    "favor_no": (-1.0, "頼みを断られた"),
    "care_yes": (3.0, "看病に来てくれると言った"),
    "care_no": (-2.5, "看病に来てくれなかった"),
    "care_no_busy": (-0.8, "仕事・外出中で看病に来られなかった"),
    "kept": (1.5, "約束どおり会えた"),
    "missed": (-5.0, "約束をすっぽかされた"),
    "missed_favor": (-6.0, "当てにしていた頼みごとに来なかった"),
    "remembered": (4.0, "誕生日・記念日を祝ってくれた"),
    "forgot": (-4.0, "誕生日・記念日を忘れられた"),
    "gift": (2.0, "贈り物をくれた"),
    "apology": (1.0, "謝ってくれた"),
    "met_day": (0.8, "会った日"),
    "no_contact": (-0.5, "何日も音沙汰がない"),
    "rival": (-4.0, "ほかの人と親しくしている"),
    "call_long": (1.0, "電話で長く付き合ってくれた"),
    "call_silent": (-1.5, "電話の途中で黙られた"),
    "call_cut": (-1.2, "かけた電話を早く切られた"),
    "call_answered": (0.4, "かけた電話に出てくれた"),
    "call_missed": (-1.0, "かけた電話に出てもらえなかった"),
    "call_dodge": (-2.0, "電話で, 誰かいるのをごまかされた"),
    "care_msg": (0.8, "暑さ寒さを気づかってくれた"),
}
CALL_UNKNOWN = 1.2                    # 電話に出る時間帯をまだ覚えていないうちの, 不在着信の重さの倍率 (覚える前は重く出る)
# あなたの癖 (habit)
HABIT_SLOTS = ((0, 5, "夜中"), (5, 10, "朝"), (10, 16, "昼"), (16, 19, "夕方"), (19, 24, "夜"))
HABIT_MIN = 4.0                       # 枠の記録がこれより少ないうちは, その枠では判断しない (全体の記録で. それも少なければ, いままでと同じ)
HABIT_FULL = 8.0                      # 慣れ = 記録の数 / (これ × 性格の覚えやすさ)
HABIT_DECAY = 0.97                    # 1 件ごとに, それまでの記録を薄める
HABIT_HALF = 30 * 86400               # 日がたつと薄れる (半分になるまで)
HABIT_SLOW_CAP = 720.0                # 返すまでの分は, ここまでで数える
EASE = 0.6                            # ふだんどおりのとき, 重さから引く割合 (× 慣れ. 依存度が高いと半分)
EASE_DEP = 0.3                        # これより依存度 (attach.factor) が高いと, 分かっていても不安
ODD = 0.3                             # ふだんと違うとき, 重さに足す割合 (× 慣れ)
ODD_MIN = 20.0                        # これより短い待ち (分) は, ふだんと違うとは言わない
ODD_KEEP = 3 * 86400                  # 「いつもと違う」と気づいてから, これを過ぎたら聞かない
ASK_GAP = 3 * 86400                   # 「何かあった？」と聞く間隔
ASK_AFF = 40                          # これより好感度が低いと, 気づいても聞いてこない
# 返信の速さを, あなたのふだんの速さに寄せる (engine.reply_delay)
MATCH = {"tsundere": 0.6, "sadist": 0.6, "fushigi": 0.0, "tenshin": 0.0}    # 性格の係数 (張り合う人は大きく, 気にしない人は 0). ほかは MATCH_BASE
MATCH_BASE = 0.25
MATCH_CAP = 30 * 60                   # 寄せる幅 (秒) の上限
MATCH_DEP = 0.6                       # 依存度 (attach.factor) がここまで上がると係数が 0 (合わせられず, すぐ返す). 0 以下では弱めない
TEASE_KINDS = ("tease", "re_lol")
TEASE_SHARE, TEASE_FAM, TEASE_BONUS = 0.3, 0.5, 4.0     # からかいが返しの 3 割以上で, 慣れていれば, からかいの点に足す


def slot(t):
    """時刻 → 枠 (w = 平日 / h = 土日・祝日, 0〜4 = 夜中・朝・昼・夕方・夜)."""
    d = datetime.fromtimestamp(t)
    hol = d.weekday() >= 5 or d.date() in market.holidays(d.year)
    i = next(i for i, (a, b, _) in enumerate(HABIT_SLOTS) if a <= d.hour < b)
    return ("h" if hol else "w") + str(i)


def slot_label(key):
    return ("休日" if key[0] == "h" else "平日") + "の" + HABIT_SLOTS[int(key[1])][2]


# 性格ごとの読み方: (bias -1 低く見積もる 〜 +1 高く見積もる, 確かさの上がりやすさ)
READING = {
    "hikutsu": (-0.8, 0.8), "uchiki": (-0.5, 0.8), "byoujaku": (-0.3, 0.9), "mukuchi": (-0.2, 1.0), "amaenbo": (-0.2, 0.7),
    "teinei": (-0.1, 1.0), "seijitsu": (0.0, 1.1), "cool": (0.0, 1.1), "jimuteki": (0.0, 1.2), "rikejo": (0.0, 1.2),
    "shikkari": (0.0, 1.1), "yareyare": (0.0, 1.0), "fushigi": (0.0, 0.7), "tsundere": (0.0, 0.55), "ottori": (0.1, 1.0),
    "boyish": (0.1, 1.0), "otokomae": (0.1, 1.1), "aneki": (0.2, 1.1), "osananajimi": (0.2, 1.2), "itazura": (0.2, 1.0),
    "genki": (0.3, 1.0), "tenshin": (0.3, 0.9), "hitonatsukko": (0.3, 1.0), "rakuten": (0.4, 1.0), "ojousama": (0.5, 1.1),
    "kedakai": (0.5, 1.1), "sadist": (0.6, 1.1),
}


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(v)))


class Regard:
    def __init__(self, app):
        self.app = app
        self.rng = random.Random()      # 揺らぎは自前の乱数で (全体の乱数の順を変えない: 種を決めた既存のテストがずれないように)

    # ------------------------------------------------------------------ 値
    def reading(self, char):
        """(読み違えの向き, 確かさの上がりやすさ). 性格の traits に書いてあればそちら."""
        tr = self.app.traits(char)
        b, s = READING.get(char.get("persona_id") or "", (0.0, 1.0))
        return max(-1.0, min(1.0, float(tr.get("regard_bias", b)))), max(0.3, min(1.3, float(tr.get("regard_sure", s))))

    def sure_cap(self, char):
        return min(0.95, SURE_MAX * self.reading(char)[1])

    def baseline(self, char, st, now=None):
        """初めの値: 今の関係と最近のやりとり (相手から見えていたもの) から. 揺らぎはキャラごとに決まった分だけ."""
        app = self.app
        now = now or time.time()
        B = app.bonds
        cid = char["id"]
        stage = B.stage(cid)
        bias, _ = self.reading(char)
        rnd = random.Random("regard:%s" % cid)
        freq, gap = B.freq(st, now), B.gap_days(st, now)
        led = (st.get("attach") or {}).get("ledger") or {}
        v = 45 + 2.2 * (freq - 4) - 2.0 * max(0.0, min(10.0, gap - 3)) + {"visit": 6, "live": 12}.get(stage, 0) \
            + 2.0 * min(4.0, float(led.get("me", 0))) + 0.2 * (st["params"].get("trust", 50) - 50) \
            - 5 * len(st.get("jealous") or {}) - (4 if st.get("ap_ignored") else 0) + 8 * bias + rnd.uniform(-5, 5)
        sure = 0.25 + 0.03 * min(10, freq) + {"visit": 0.1, "live": 0.2}.get(stage, 0)
        return {"v": round(_clamp(v), 1), "sure": round(_clamp(sure, 0.1, self.sure_cap(char)), 3)}

    def rec(self, char, st):
        r = st.get("regard")
        if not r or "v" not in r or "sure" not in r:
            r = dict(self.baseline(char, st), day={}, since=time.time())
            st["regard"] = r
            trace = getattr(self.app, "trace", None)
            if trace:
                trace.add("regard", "見立ての初めの値を決めた", char.get("id"), v=r["v"], sure=r["sure"])
        return r

    def get(self, char, st):
        return float(self.rec(char, st)["v"])

    # ------------------------------------------------------------------ 印
    def sign(self, char, st, kind, now=None, k=1.0):
        """相手から見えた あなたの振る舞い. 動いた分を返す. k: 強さの倍率."""
        d0 = SIGNS[kind][0] * float(k)
        if not d0:
            return 0.0
        now = now or time.time()
        r = self.rec(char, st)
        bias, _ = self.reading(char)
        d = d0 * ((1 + 0.4 * bias) if d0 > 0 else (1 - 0.4 * bias))       # 読み違え
        d *= (1.7 - r["sure"]) * self.rng.uniform(0.6, 1.25)                 # 確かでないほど大きく揺れる
        day = datetime.fromtimestamp(now).strftime("%Y%m%d")
        used = r.setdefault("day", {})
        if used.get("d") != day:
            used.clear()
            used["d"] = day
        sg = "+" if d > 0 else "-"
        room = DAY_CAP[sg] - used.get(sg, 0.0)
        old = r["v"]
        if room > 0:
            r["v"] = round(_clamp(old + max(-room, min(room, d))), 2)
            used[sg] = round(used.get(sg, 0.0) + abs(r["v"] - old), 2)
        # 確かさ: 見立てと同じ向きの印が重なると固まり, 逆向きの印で揺らぐ (揺らぐほうが速い)
        agree = (d0 > 0) == (old >= 50)
        r["sure"] = round(_clamp(r["sure"] + (0.015 if agree else -0.03) * min(3.0, abs(d0)), 0.05, self.sure_cap(char)), 3)
        trace = getattr(self.app, "trace", None)
        if trace and (abs(r["v"] - old) >= 0.05):
            trace.add("regard", "見立てが動いた: %s" % SIGNS[kind][1], char.get("id"), now, kind=kind, v=r["v"],
                      d=round(r["v"] - old, 2), sure=r["sure"])
        return r["v"] - old

    def daily(self, char, st, t):
        """日付が替わったとき: 会った日 / 何日も音沙汰がない. 音沙汰がないと, 確かさも少しずつ薄れる."""
        B = self.app.bonds
        if B.stage(char["id"]) == "known":
            return
        r = self.rec(char, st)
        gap = B.gap_days(st, t)
        if t - float(st.get("last_met") or 0) < 86400:
            self.sign(char, st, "met_day", t)
        elif gap >= 3 and B.stage(char["id"]) != "live":
            self.sign(char, st, "no_contact", t, k=min(2.0, gap / 5.0))
            r["sure"] = round(max(0.05, r["sure"] - 0.01), 3)

    # ------------------------------------------------------------------ あなたの癖
    def habit(self, char, st):
        r = self.rec(char, st)
        h = r.get("habit")
        if not isinstance(h, dict):
            h = r["habit"] = {}
        for k in ("reply", "all", "tease", "start", "call"):
            if not isinstance(h.get(k), dict):
                h[k] = {}
        return h

    def learn(self, char):
        """癖の覚えやすさ (小さいほど早く覚える. 0.6〜1.5): マメな人は早く, 返事の遅れを気にしない人 (traits.absence が低い) は遅い.
        性格の traits に habit_learn があればそちら."""
        from . import react
        tr = self.app.traits(char)
        if "habit_learn" in tr:
            return max(0.4, min(2.0, float(tr["habit_learn"])))
        m = _clamp((react.mame(self.app, char) - 0.45) / 0.3, 0.0, 1.0)
        a = _clamp((1.0 - float(tr.get("absence", 1))) / 0.4, 0.0, 1.0)
        return 1.0 - 0.4 * m + 0.5 * a

    @staticmethod
    def _faded(b, now):
        """枠の記録を, いまの時刻まで薄めた値 (数, 返した数, 返すまでの分). 書き換えない."""
        n, r = float(b.get("n", 0)), float(b.get("r", 0))
        t = float(b.get("t") or 0)
        if t and now > t:
            f = 0.5 ** ((now - t) / HABIT_HALF)
            n, r = n * f, r * f
        return n, r, float(b.get("slow", 0))

    def known(self, char, st, t_msg, now):
        """その時刻の枠について覚えていること: (数, 返す割合, 返すまでの分 (分からなければ None), 慣れ 0〜1, どの記録か).
        枠の記録が少なければ全体の記録で. それも少なければ None (まだ覚えていない)."""
        h = self.habit(char, st)
        key = slot(t_msg)
        for name, b in ((key, h["reply"].get(key)), ("all", h["all"])):
            if not b:
                continue
            n, r, slow = self._faded(b, now)
            if n >= HABIT_MIN:
                return n, r / n, (slow if r >= 2 and slow > 0 else None), min(1.0, n / (HABIT_FULL * self.learn(char))), name
        return None

    def ease(self, char, st, t_msg, now, waited=None, mark=True):
        """時刻 t_msg に来たメッセージへの, あなたの返し方の受け取り方の倍率 (重さに掛ける. 0.4〜1.3).
        waited: 返ってくるまでの分. None = 返ってこなかった (now までの経過で見る).
        ふだんどおり (その枠ではあまり返さない人 / ふだんの遅さの 1.5 倍まで) → 1 より小さい (慣れているほど. 依存度が高いと半分).
        ふだんと違う (よく返す枠なのに返ってこない / ふだんの 3 倍より遅い) → 1 より大きい. mark: 「いつもと違う」と気づいたことを覚える."""
        k = self.known(char, st, t_msg, now)
        if not k:
            return 1.0
        _, share, slow, fam, name = k
        el = float(waited) if waited is not None else max(0.0, (now - t_msg) / 60.0)
        if waited is None:
            usual = share < 0.4 or (slow is not None and el <= 1.5 * slow)
            odd = share >= 0.8 and el >= ODD_MIN and (slow is None or el > 3 * slow)
        else:
            usual = slow is not None and el <= 1.5 * slow
            odd = slow is not None and el > 3 * slow and el >= ODD_MIN
        if usual:
            dep = self.app.attach.factor(char, st, "dependence") > EASE_DEP
            f = 1 - EASE * fam * (0.5 if dep else 1.0)
        elif odd:
            f = 1 + ODD * fam
            if mark:
                self.habit(char, st)["odd"] = now
        else:
            return 1.0
        trace = getattr(self.app, "trace", None)
        if trace and mark:
            trace.add("regard", "あなたの癖: %s" % ("ふだんどおり (軽く受け取る)" if usual else "ふだんと違う (気にする)"), char.get("id"), now,
                      slot=name, share=round(share, 2), slow=slow, waited=None if waited is None else round(el, 1), fam=round(fam, 2),
                      ease=round(f, 2))
        return f

    def match_coef(self, char, st):
        """返信の速さを寄せる係数 (0〜1). 性格の traits に reply_match があればそちら. 依存度が高いほど 0 に近づく."""
        tr = self.app.traits(char)
        c = float(tr.get("reply_match", MATCH.get(char.get("persona_id") or "", MATCH_BASE)))
        dep = self.app.attach.factor(char, st, "dependence")
        return _clamp(c * (1.0 - _clamp(dep / MATCH_DEP, 0.0, 1.0)), 0.0, 1.0)

    def match_shift(self, char, st, delay, now):
        """相手の返信の待ち (秒) を, あなたのふだんの返す速さ (全体の記録) に寄せる分 (秒. ±MATCH_CAP).
        まだ分からない (記録 HABIT_MIN 件未満・返した数 2 件未満) なら 0. 慣れが浅いうちは弱く. 乱数は使わない."""
        b = self.habit(char, st)["all"]
        if not b:
            return 0.0
        n, r, slow = self._faded(b, now)
        if n < HABIT_MIN or r < 2 or slow <= 0:
            return 0.0
        fam = min(1.0, n / (HABIT_FULL * self.learn(char)))
        c = self.match_coef(char, st) * fam
        if c <= 0:
            return 0.0
        return max(-MATCH_CAP, min(MATCH_CAP, c * (slow * 60.0 - float(delay))))

    def note_reply(self, char, st, t_msg, now, waited=None, late=False):
        """相手から来たメッセージ 1 件を覚える. waited (分) = 返した / None = 返さなかった.
        late: 時間切れで「返さなかった」と数えたあとに返した (数は増やさず, 返した数と遅さだけ直す)."""
        h = self.habit(char, st)
        for b in (h["reply"].setdefault(slot(t_msg), {}), h["all"]):
            n, r, slow = self._faded(b, now)
            if late:
                if n < 0.5:              # 数えていないメッセージ (覚えはじめる前のもの)
                    continue
            else:
                n, r = n * HABIT_DECAY + 1, r * HABIT_DECAY
            if waited is not None:
                r = min(n, r + 1)
                w = min(HABIT_SLOW_CAP, max(0.0, float(waited)))
                slow = w if slow <= 0 else slow + max(0.25, 1.0 / max(1.0, r)) * (w - slow)
            b.update(n=round(n, 3), r=round(r, 3), slow=round(slow, 1), t=now)

    def replied(self, char, st, t_msg, now):
        """相手からのメッセージに返した (速さは相手から見える). 癖を覚えていれば, ふだんどおりの遅さは「返事が来た」と同じに受け取り,
        ふだんよりずっと遅いと, 返ってきたうれしさが薄い. 印を入れて, 癖に覚える."""
        waited = max(0.0, now - float(t_msg))
        kind = "reply_fast" if waited < 600 else "reply" if waited < 3600 else "reply_slow"
        ez = self.ease(char, st, t_msg, now, waited=waited / 60.0)
        k = 1.0
        if ez < 1 and kind == "reply_slow":
            k = 1 + (SIGNS["reply"][0] / SIGNS["reply_slow"][0] - 1) * (1 - ez) / EASE
        elif ez > 1 and kind != "reply_fast":
            k = max(0.0, 1 - (ez - 1) / ODD)
        self.sign(char, st, kind, now, k=k)
        self.note_reply(char, st, t_msg, now, waited=waited / 60.0)

    # 電話に出る時間帯 (A23 段 2): habit["call"] = {枠: {n かけた数, r 出た数, t}, "all": {…}}. 返信の癖と同じ薄め方
    def note_call(self, char, st, t_ring, answered):
        """かけた電話に, あなたが出た / 出なかった を覚える."""
        h = self.habit(char, st)["call"]
        for key in (slot(t_ring), "all"):
            b = h.setdefault(key, {})
            n, r, _ = self._faded(b, t_ring)
            n, r = n * HABIT_DECAY + 1, r * HABIT_DECAY + (1 if answered else 0)
            b.update(n=round(n, 3), r=round(min(n, r), 3), t=t_ring)

    def call_known(self, char, st, t):
        """その時刻の枠で, あなたが電話に出る割合を覚えているか: (数, 出る割合, 慣れ 0〜1) / None (まだ覚えていない)."""
        h = self.habit(char, st)["call"]
        for key in (slot(t), "all"):
            b = h.get(key)
            if not b:
                continue
            n, r, _ = self._faded(b, t)
            if n >= HABIT_MIN:
                return n, r / n, min(1.0, n / (HABIT_FULL * self.learn(char)))
        return None

    def call_ease(self, char, st, t_ring, now):
        """不在着信の受け取り方の倍率: ふだん出ない時間帯なら軽く (慣れているほど), ふだん出るのに出ないと重く. 覚える前は少し重い."""
        k = self.call_known(char, st, t_ring)
        if not k:
            return CALL_UNKNOWN
        _, share, fam = k
        if share < 0.4:
            dep = self.app.attach.factor(char, st, "dependence") > EASE_DEP
            return 1 - EASE * fam * (0.5 if dep else 1.0)
        if share >= 0.8:
            return 1 + ODD * fam
        return 1.0

    def note_kind(self, char, st, kind):
        """あなたの返しの種類 (からかいの多さ)."""
        t = self.habit(char, st)["tease"]
        t["n"] = round(float(t.get("n", 0)) * HABIT_DECAY + 1, 3)
        t["k"] = round(float(t.get("k", 0)) * HABIT_DECAY + (1 if kind in TEASE_KINDS else 0), 3)

    def teaser(self, char, st):
        """「よくからかう人」と分かっているか (からかいが通じやすい)."""
        t = self.habit(char, st)["tease"]
        n = float(t.get("n", 0))
        return n >= HABIT_MIN and float(t.get("k", 0)) / n >= TEASE_SHARE and min(1.0, n / (HABIT_FULL * self.learn(char))) >= TEASE_FAM

    def note_start(self, char, st, now):
        """あなたから連絡を始めた時刻の枠 (いつ連絡してくる人か)."""
        s = self.habit(char, st)["start"]
        for k in list(s):
            s[k] = round(float(s[k]) * HABIT_DECAY, 3)
            if s[k] < 0.05:
                del s[k]
        key = slot(now)
        s[key] = round(float(s.get(key, 0)) + 1, 3)

    def ask_changed(self, char, st, now):
        """いま「何かあった？」と聞くか: 少し前に「いつもと違う」と気づいていて, 前に聞いてから間があいているとき. 言い争いのあとは聞かない."""
        h = self.habit(char, st)
        odd = h.get("odd")
        if not odd:
            return False
        if now - float(odd) > ODD_KEEP:
            h.pop("odd", None)
            return False
        if now - float(h.get("asked") or 0) < ASK_GAP or self.app.quarrel.active(st, now) \
                or st["params"].get("affection", 50) < ASK_AFF:
            return False
        h["asked"] = now
        h.pop("odd", None)
        return True

    # ------------------------------------------------------------------ 効き方
    def hold(self, char, st):
        """0〜1: 好きなのに, 思われていないと感じている度合い. そもそも好きでなければ気にしない."""
        aff = st["params"].get("affection", 50)
        if aff < 45:
            return 0.0
        return _clamp((aff - self.get(char, st) - 8) / 35.0, 0.0, 1.0)

    def lean(self, char, st):
        """0〜1: 思われていると感じている度合い. 自分の気持ちに届いていないと感じている (hold) 間は 0."""
        if self.hold(char, st) > 0:
            return 0.0
        return _clamp((self.get(char, st) - 55) / 35.0, 0.0, 1.0)

    def invite_factor(self, char, st):
        """誘ってくる多さへの倍率 (0.4〜1.25): 思われていないと感じると控え, 思われていると感じると踏み出しやすい."""
        return (1 - 0.6 * self.hold(char, st)) * (1 + 0.25 * self.lean(char, st))

    def contact_factor(self, char, st):
        """離れているときの, 自分からの連絡の多さへの倍率 (0.65〜1.5): 思われていないと感じると,
        依存度が高ければ不安で増え, そうでなければ控える."""
        h = self.hold(char, st)
        if h <= 0:
            return 1 + 0.1 * self.lean(char, st)
        dep = self.app.attach.factor(char, st, "dependence")
        return 1 + 0.5 * h * dep if dep > 0.2 else 1 - 0.35 * h

    def ready_shift(self, char, st):
        """段階の提案を受ける気持ち (bonds.readiness) に足す分 (±12 まで. 確かなほど効く)."""
        r = self.rec(char, st)
        return round(12 * (r["v"] - 50) / 50.0 * (0.5 + 0.5 * r["sure"]), 1)

    def probe(self, char, st, now):
        """いま探りを入れるか (「最近忙しい？」). 間隔をあけ, 言い争いのあとはしない."""
        h = self.hold(char, st)
        r = self.rec(char, st)
        if h < 0.3 or now - float(r.get("probe_t") or 0) < PROBE_GAP or self.app.quarrel.active(st, now):
            return False
        if random.random() >= 0.7 * h:
            return False
        r["probe_t"] = now
        return True

    def debug(self, char, st):
        r = self.rec(char, st)
        out = {"思われている度": r["v"], "確かさ": r["sure"], "控え": round(self.hold(char, st), 2), "踏み出し": round(self.lean(char, st), 2)}
        now = time.time()
        for key, b in sorted(self.habit(char, st)["reply"].items()):
            n, rr, slow = self._faded(b, now)
            if n >= 1:
                out["癖: " + slot_label(key)] = "%.1f 件・返す %d%%・%d 分" % (n, round(100 * rr / n), round(slow))
        return out
