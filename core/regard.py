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

初めの値は, はじめて使うとき (以前のセーブなら更新後の最初) に, 今の関係と最近のやりとりから一度だけ決める (baseline).
公理: 確定させない (揺らぎ・一日の上限). 見立ては相手の頭の中のもので, 当たっているとは限らない.
"""
import random
import time
from datetime import datetime

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
}
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
        return {"思われている度": r["v"], "確かさ": r["sure"], "控え": round(self.hold(char, st), 2), "踏み出し": round(self.lean(char, st), 2)}
