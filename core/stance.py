"""相手の言い分に, 肯定・否定で返す (A21). 「そうだね / いいね」(re_yes) と「そうかな / それはちょっと」(re_no).

- 言い分 (stance): 相手が口にした, 向きのある話. {"sign": +1 好き・よいと思う / -1 苦手・よくないと思う, "w": 思い入れ 0〜1,
  "tag": 話題の系統 (あれば), "src": taste (好き・苦手・意見) / advice (相談への答え)}.
  出るのは: 好き・苦手を口にした (hima.reveal_*)・好みについての意見 (hima.opinion_*)・あなたの相談への答え (consult_good / consult_off).
  メッセージ (トークの 1 件に stance を残す. 「返す」に並ぶ), 電話・対面の会話 (切れ目に stance. 返し方に並ぶ).
  誘い (約束) は「受ける / 断る」が別にあるので, ここには入れない. 言い分の無い話には, 肯定・否定は並べない.
- 合う・外す (fit. react.FIT と同じ目盛り):
  肯定: 思い入れが強いほど合う. ただし合わせてばかり (肯定が 3 日のうちに続く) だと, 調子を合わせているだけに聞こえる
  (正直さを好む性格ほど早く). 必ず効く返しにしない.
  否定: 思い入れが強いほど外れる (好きなものを否定されるのは, 苦手なものを「そうかな」と言われるより重い). 正直さを好む性格
  (candor > 0) には, 率直に言ってくれることが合い, 否定に弱い性格 (traits.hurt の mood > 1) には刺さる. 仲が深いほど受け止められる.
  思い入れの薄い軽い話でノリが高いときは, 掛け合いとして通じる.
- よく効いた否定は, 信頼が少し上がる (正直に言ってくれた). よくなかった否定・合わせすぎは, 機嫌の理由 (謝れる心当たり) になる.
- 記録: st["stance"] = {"run": 続けて肯定した数, "t": 最後に返した時刻}. 新しい欄だけ (遡及しない).
"""
import time

YES, NO = "re_yes", "re_no"
KINDS = (YES, NO)
RUN_SPAN = 3 * 86400         # これより間が空いたら, 続けて肯定した数を数え直す
RUN_FREE = 2                 # ここまでは続けて肯定しても気にされない
# 正直に言われるのを好む (+) ↔ 合わせてほしい (-). 性格の traits に candor があれば, そちら
CANDOR = {"jimuteki": 0.8, "rikejo": 0.8, "cool": 0.7, "otokomae": 0.7, "aneki": 0.5, "osananajimi": 0.5, "boyish": 0.5,
          "shikkari": 0.4, "seijitsu": 0.4, "yareyare": 0.3, "sadist": 0.3, "mukuchi": 0.3, "fushigi": 0.2, "rakuten": 0.2,
          "itazura": 0.1, "teinei": 0.0, "genki": 0.0, "tenshin": -0.1, "ottori": -0.1, "hitonatsukko": -0.2, "tsundere": -0.3,
          "kedakai": -0.5, "ojousama": -0.5, "byoujaku": -0.5, "amaenbo": -0.6, "uchiki": -0.6, "hikutsu": -0.7}
ADVICE = {"sign": 1, "w": 0.5, "src": "advice"}
TELL = {YES: "{call}が、調子を合わせてばかりいる", NO: "{call}に、言ったことを否定された"}


def make(sign, w, tag=None, src="taste"):
    return {"sign": 1 if sign > 0 else -1, "w": round(max(0.0, min(1.0, float(w))), 2), "tag": tag, "src": src}


def of_taste(tag, v):
    """好み (topics.tastes の値 -1〜1) を口にしたときの言い分."""
    return make(1 if v > 0 else -1, abs(v), tag)


def candor(app, char):
    tr = app.traits(char)
    if "candor" in tr:
        return max(-1.0, min(1.0, float(tr["candor"])))
    return CANDOR.get(char.get("persona_id") or "", 0.0)


def soft(app, char):
    """否定に弱いか (0 = ふつう〜). つらい方向の効き目 (traits.hurt の mood) から."""
    h = (app.traits(char).get("hurt") or {}).get("mood", 1.0)
    return max(0.0, float(h) - 1.0)


def run(st, now):
    rec = st.get("stance") or {}
    if now - float(rec.get("t") or 0) > RUN_SPAN:
        return 0
    return int(rec.get("run") or 0)


def fit(app, char, st, sv, kind, now=None, lv=None):
    """言い分 sv への返し kind の合い方 (react.FIT と同じ目盛り). 肯定・否定でなければ 0."""
    if not sv or kind not in KINDS:
        return 0.0
    now = now or time.time()
    w = max(0.0, min(1.0, float(sv.get("w") or 0)))
    c = candor(app, char)
    if kind == YES:
        f = 3 + 8 * w
        n = run(st, now)
        if n >= RUN_FREE:
            f -= (n - RUN_FREE + 1) * (3 + 4 * max(0.0, c))
        return f
    p = st["params"]
    f = (-2 - 12 * w) if sv.get("sign", 1) > 0 else (-1 - 6 * w)
    f += 14 * c - 8 * soft(app, char) + 0.25 * (p.get("affection", 45) - 55)
    if w < 0.5 and lv is not None and lv >= 0.6:          # 軽い話で乗っている: 掛け合いとして通じる
        f += 6
    return f


def note(app, char, st, kind, res, now):
    """返したあとの記録 (続けて肯定した数) と, 効き目の足し (よく効いた否定は信頼が少し上がる)."""
    if kind not in KINDS:
        return {}
    rec = st.setdefault("stance", {})
    rec["run"] = (run(st, now) + 1) if kind == YES else 0
    rec["t"] = now
    return {"trust": 1.0} if kind == NO and res == "good" else {}


def tell(kind):
    return TELL.get(kind)
