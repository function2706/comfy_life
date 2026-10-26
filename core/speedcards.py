"""スピード (二人で同時に出していくトランプ): 規則とキャラの動き.

- あなたは赤 (♥♦), キャラは黒 (♠♣) の 26 枚ずつ. 手元に 4 枚の場札を表で並べ, 残りは自分の山. 真ん中に台札が 2 つ.
- 場札を, 台札の一番上と 1 つ違い (A と K もつながる) なら, どちらの台札にも出せる. 出したら自分の山から場札を補う.
- どちらも出せなくなったら「スピード！」: お互いの山 (無ければ場札) から 1 枚ずつ台札に出して, また始める.
- 先に手札 (場札と山) を出し切ったほうの勝ち.
- 同時に動く: キャラは時刻の予定 (ai_next) で動く. 画面は少しずつ問い合わせ (tick), あなたの手もその時刻で当てる (advance).
  キャラの速さ (delay) は体力・眠気・機嫌で変わり, ときどき出せる札を見落とす (いつも最速ではない).
"""
import random

RED, BLACK = (1, 2), (0, 3)


def rank(c):
    return c % 13 + 1


def name(c):
    return "A23456789TJQK"[c % 13] + "SHDC"[c // 13]


def fits(c, top):
    d = abs(rank(c) - rank(top))
    return d == 1 or d == 12


def new(rng=random):
    mine = [s * 13 + r for s in RED for r in range(13)]
    hers = [s * 13 + r for s in BLACK for r in range(13)]
    rng.shuffle(mine)
    rng.shuffle(hers)
    st = {"p": {"field": [mine.pop() for _ in range(4)], "stock": mine},
          "a": {"field": [hers.pop() for _ in range(4)], "stock": hers}, "center": [], "log": [], "speeds": 0}
    st["center"] = [st["p"]["stock"].pop(), st["a"]["stock"].pop()]
    return st


def playable(st, who):
    """出せる手 [(場札の位置, 台札の位置)]."""
    return [(i, j) for i, c in enumerate(st[who]["field"]) if c is not None
            for j, top in enumerate(st["center"]) if fits(c, top)]


def play(st, who, i, j):
    side = st[who]
    c = side["field"][i]
    if c is None or not fits(c, st["center"][j]):
        raise ValueError("その札はそこに出せません（1 つ違いの数だけ）")
    st["center"][j] = c
    side["field"][i] = side["stock"].pop() if side["stock"] else None


def left(st, who):
    return len(st[who]["stock"]) + sum(1 for c in st[who]["field"] if c is not None)


def speed(st):
    """どちらも出せない: お互いの山 (無ければ場札) から 1 枚ずつ台札へ."""
    for j, who in enumerate(("p", "a")):
        side = st[who]
        if side["stock"]:
            st["center"][j] = side["stock"].pop()
        else:
            k = next((i for i, c in enumerate(side["field"]) if c is not None), None)
            if k is not None:
                st["center"][j] = side["field"][k]
                side["field"][k] = None
    st["speeds"] += 1


def delay(quick, rng=random):
    """キャラが次の札を出すまでの秒. quick: 0〜1 (体力・眠気・機嫌)."""
    return (0.7 + 1.9 * (1 - quick)) * rng.uniform(0.8, 1.3)


def quickness(params):
    p = params
    q = 0.35 + p.get("energy", 70) / 250.0 + (100 - p.get("sleepiness", 0)) / 300.0 + (p.get("mood", 50) - 50) / 300.0
    return max(0.05, min(1.0, q))


def advance(st, now, quick, rng=random, miss=0.12):
    """キャラの予定の時刻 (ai_next) が来ていれば動かす. どちらも出せなければ「スピード！」. 起きたこと [str] を返す."""
    out = []
    for _ in range(40):
        if st.get("over") or st["ai_next"] > now:
            break
        t = st["ai_next"]
        mine = playable(st, "a")
        if mine and rng.random() >= miss:
            i, j = rng.choice(mine)
            play(st, "a", i, j)
            out.append("play")
            if not left(st, "a"):
                st["over"] = "lose"
                break
            st["ai_next"] = t + delay(quick, rng)
        elif not mine and not playable(st, "p"):
            speed(st)
            out.append("speed")
            st["ai_next"] = t + 1.0 + delay(quick, rng)
        else:
            st["ai_next"] = t + 0.4 * rng.uniform(0.8, 1.4) + (0.6 if mine else 0)    # 見落とした・出せる札が無いので様子を見る
    return out


def view(st):
    return {"center": [name(c) for c in st["center"]],
            "mine": [name(c) if c is not None else None for c in st["p"]["field"]], "my_stock": len(st["p"]["stock"]),
            "hers": [name(c) if c is not None else None for c in st["a"]["field"]], "her_stock": len(st["a"]["stock"]),
            "left": {"p": left(st, "p"), "a": left(st, "a")}, "speeds": st["speeds"], "over": st.get("over"),
            "stuck": not playable(st, "p")}
