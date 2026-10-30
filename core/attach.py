"""あなたとの関わり方の傾き: 献身度・依存度・誠実さ (相手ごと. 0〜100. 画面には出さない).

- 献身度 (devotion): 相手 (あなた) と自分のどちらを優先するか. 高いほど予定を空ける・払う・頼みごとは控えめ.
  低いほど自分の都合で約束を動かし, 払わせ, よく頼む・せがむ.
- 依存度 (dependence): どれだけ普段からあなたを求めるか. 高いほどよく連絡してきて, 連絡が多くても平気, 放っておかれると堪え,
  嫉妬しやすく, 寂しくなりやすい. 低いほど一人で平気.
- 誠実さ (sincerity): 見せる好意と本心が同じか (表と裏). いまは記録して動かすだけ (演技・違和感は後の段階).

ヒモ・束縛・自己中・飼い殺し・パパ活のような「型」は, この組み合わせと, 今ある状態 (相手の懐具合・寂しさ・嫉妬) から生まれる例にすぎない.
性格プリセットは初めの値と動きやすさを決めるだけで, やりとりで動く. 初めの値は, はじめて使うとき (以前のセーブなら起動後の最初) に
性格の傾向と今の関係 (好感度・信頼・間柄) から決める.

動き方 (公理: 確定させない. 一日に動く幅に上限・揺らぎ):
- 献身度: お互いさまなら上がる. 一方的に尽くさせ続けると下がる. ただし依存度が高いと逆に上がることも (共依存).
  どちらがどれだけ尽くしたかは give() で裏の帳簿に (日ごとに薄れる).
- 依存度: あなたといて寂しさが紛れる・送ったメッセージにいつも返ってくると上がる. 長く会わなくても平気で過ごせた・
  ほかに深い仲の人がいる・傷つけられることが続くと下がる.
- 誠実さ: 信頼と時間で少しずつ上がり, 裏切られたと感じる (嫉妬) と下がる.
"""
import random
import time
from datetime import datetime

KEYS = ("devotion", "dependence", "sincerity")
LABEL = {"devotion": "献身度", "dependence": "依存度", "sincerity": "誠実さ"}
DAY_CAP = {"devotion": 4.0, "dependence": 4.0, "sincerity": 2.0}     # 一日に動く幅の上限 (それぞれ上げ・下げ)
LEDGER_FADE = 0.85      # 尽くした帳簿は一日ごとにこれだけ残る


def _clamp(v):
    return max(0.0, min(100.0, float(v)))


class Attach:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 値
    def baseline(self, char, st):
        """初めの値: 性格の傾向と今の関係から. 揺らぎはキャラごとに決まった分だけ (起動し直しても同じ)."""
        tr = self.app.traits(char)
        p = st["params"]
        stage = self.app.bonds.stage(char["id"])
        rnd = random.Random("attach:%s" % char["id"])
        aff, trust = p.get("affection", 50), p.get("trust", 50)
        dep = 40 + 25 * (float(tr.get("approach", 1)) - 1) + 20 * (float(tr.get("absence", 1)) - 1) \
            + 12 * (float((tr.get("rate") or {}).get("loneliness", 1)) - 1) + 0.2 * (aff - 50) \
            + {"visit": 3, "live": 8}.get(stage, 0) + rnd.uniform(-6, 6)
        dev = 45 + 30 * (float(tr.get("carer", 0.3)) - 0.3) + 0.25 * (trust - 50) + 0.15 * (aff - 50) + rnd.uniform(-6, 6)
        sin = 75 + 0.1 * (trust - 50) + rnd.uniform(-5, 5)
        return {"devotion": round(_clamp(dev), 1), "dependence": round(_clamp(dep), 1), "sincerity": round(_clamp(sin), 1)}

    def speed(self, char, key):
        """動きやすさ (性格しだい): 依存度は寂しがり・話しかけてくる人ほど, 献身度は世話焼きほど動きやすい. 誠実さはゆっくり."""
        tr = self.app.traits(char)
        if key == "dependence":
            return max(0.6, min(1.6, (float(tr.get("approach", 1)) + float(tr.get("absence", 1))) / 2.0))
        if key == "devotion":
            return max(0.7, min(1.4, 0.8 + float(tr.get("carer", 0.3))))
        return 0.6 / max(0.8, float(tr.get("grudge", 1)))

    def rec(self, char, st):
        r = st.get("attach")
        if not r or any(k not in r for k in KEYS):
            base = self.baseline(char, st)
            r = dict(base, **(r or {}))
            r.setdefault("ledger", {"her": 0.0, "me": 0.0})
            r.setdefault("day", {})
            r.setdefault("since", time.time())
            st["attach"] = r
            trace = getattr(self.app, "trace", None)
            if trace:
                trace.add("attach", "初めの値を決めた", char.get("id"), **{k: r[k] for k in KEYS})
        return r

    def get(self, char, st, key):
        return float(self.rec(char, st)[key])

    def factor(self, char, st, key):
        """-1 (とても低い) 〜 +1 (とても高い). 50 で 0."""
        return (self.get(char, st, key) - 50.0) / 50.0

    def move(self, char, st, key, d, why, now=None):
        """値を動かす (性格の動きやすさ × 揺らぎ. 一日に動く幅は上限まで). 動いた分を返す."""
        if not d:
            return 0.0
        now = now or time.time()
        r = self.rec(char, st)
        day = datetime.fromtimestamp(now).strftime("%Y%m%d")
        used = r.setdefault("day", {})
        if used.get("d") != day:
            used.clear()
            used["d"] = day
        k = "%s%s" % (key, "+" if d > 0 else "-")
        room = DAY_CAP[key] - abs(used.get(k, 0.0))
        if room <= 0:
            return 0.0
        dd = float(d) * self.speed(char, key) * random.uniform(0.6, 1.2)
        dd = max(-room, min(room, dd))
        old = r[key]
        r[key] = round(_clamp(old + dd), 2)
        used[k] = round(used.get(k, 0.0) + abs(r[key] - old), 2)
        trace = getattr(self.app, "trace", None)
        if trace and abs(r[key] - old) >= 0.05:
            trace.add("attach", "%sが動いた" % LABEL[key], char.get("id"), now, key=key, v=r[key], d=round(r[key] - old, 2), why=why)
        return r[key] - old

    # ------------------------------------------------------------------ 尽くした帳簿
    def give(self, char, st, who, pts, why, now=None):
        """どちらがどれだけ尽くしたか. who: "her" (相手が尽くした) / "me" (あなたが尽くした). pts の目安: おごる 2, 贈り物 2, 手伝い 3."""
        r = self.rec(char, st)
        led = r.setdefault("ledger", {"her": 0.0, "me": 0.0})
        led[who] = round(led.get(who, 0.0) + float(pts), 2)
        trace = getattr(self.app, "trace", None)
        if trace:
            trace.add("attach", "尽くした (%s)" % ("相手" if who == "her" else "あなた"), char.get("id"), now, pts=pts, why=why,
                      her=led["her"], me=led["me"])

    # ------------------------------------------------------------------ 日ごとの動き
    def daily(self, char, st, t):
        """日付が替わったとき (相手の毎日). 帳簿の差し引き・会った時間・ご無沙汰・ほかの深い仲・傷つけられた回数で動かす."""
        app = self.app
        r = self.rec(char, st)
        cid = char["id"]
        p = st["params"]
        led = r.setdefault("ledger", {"her": 0.0, "me": 0.0})
        her, me = led.get("her", 0.0), led.get("me", 0.0)
        dep = r["dependence"]
        if her + me >= 1.0:
            if me >= her * 0.7:                                  # お互いさま (かあなたの方が尽くしている)
                self.move(char, st, "devotion", min(2.5, 0.4 + 0.15 * min(me, her * 1.5)), "お互いさまだった", t)
            elif her - me >= 4:                                  # 一方的に尽くさせている
                if dep >= 65 and random.random() < 0.5:
                    self.move(char, st, "devotion", 1.0, "一方的でも離れられず, もっと尽くそうとする (共依存)", t)
                else:
                    self.move(char, st, "devotion", -min(3.0, 0.3 * (her - me)), "尽くしてばかりだった", t)
        led["her"], led["me"] = round(her * LEDGER_FADE, 2), round(me * LEDGER_FADE, 2)
        # 依存度: 会えた・紛れた / 長く会わなくても平気 / ほかの深い仲 / 傷つけられることが続いた
        gap = app.bonds.gap_days(st, t)
        if gap < 1 and p.get("loneliness", 50) < 45:
            self.move(char, st, "dependence", 0.8, "一緒にいて寂しさが紛れた", t)
        elif gap >= 3 and p.get("mood", 50) >= 45 and p.get("loneliness", 50) < 60:
            self.move(char, st, "dependence", -0.6, "長く会わなくても平気で過ごせた", t)
        others = [o for o in app.chars if o != cid and app.relation(cid, o)["knows"] and app.relation(cid, o)["affinity"] >= 70]
        if others:
            self.move(char, st, "dependence", -0.3 * len(others), "ほかに親しい相手がいる", t)
        day0 = t - 86400
        hurt = sum(1 for x in st.get("reasons") or [] if x.get("kind") == "player" and x.get("mood") == "bad" and x.get("t", 0) >= day0)
        if hurt >= 2:
            self.move(char, st, "dependence", -0.8 * (hurt - 1), "傷つけられることが続いた", t)
        # 誠実さ: 信頼と時間でゆっくり
        if gap < 2 and p.get("trust", 50) >= 55:
            self.move(char, st, "sincerity", 0.3 + (p["trust"] - 55) / 100.0, "信頼して本音を見せるようになる", t)

    def view(self, char, st):
        r = self.rec(char, st)
        return {k: r[k] for k in KEYS}
