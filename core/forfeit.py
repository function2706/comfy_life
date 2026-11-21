"""罰ゲームと勝負の形 (残件 A12 / S14).

ゲームは「種類 (data/minigames.json の定義) × 罰ゲーム × 勝負の形」で始める. 脱衣麻雀は「麻雀 + 脱衣 + 脱ぎきるまで」.
定義に stages があるゲーム (野球拳・脱衣麻雀・脱衣ポーカー) は, 何も選ばずに始めると, 以前と同じ「脱衣 + 脱ぎきるまで」(既定の組み合わせ).

勝負の単位 (1 勝負): 局のあるゲーム (野球拳の 1 回のじゃんけん・麻雀の 1 局・ポーカー / ブラックジャック / こいこいの 1 局) は 1 局,
ほかのゲーム (盤面・ヨット・数当て・スピード・神経衰弱・ババ抜き・ダウト・あっち向いてホイ) は 1 ゲーム.
1 勝負ごとに forfeit.unit(勝った方, 重み) を呼ぶ. 重み (steps) は麻雀の翻 (役満 99)・ブラックジャックのナチュラル (2).

勝負の形 (FORMS):
  one     一発勝負: 1 回で決まる (引き分けはやり直し). 罰は負けた方に. 脱衣なら全部
  n       n 回勝負: n 回やる (引き分けも 1 回). 負けるたびに罰. 脱衣は, n 回負けると必ず全部になるよう,
          そのときの服の枚数 ÷ 残りの回数 (切り上げ) を脱ぐ. 勝ち負けは勝った数 (こいこいは点の合計)
  first   先に n 勝: 重みの合計が先に n に届いた方の勝ち. 罰は最後に負けた方へ (脱衣だけは負けるたびに, n 回で全部になる割合で)
  points  持ち点制: 二人とも n 点から. 負けると重みの分だけ減り, 尽きた方の負け. 脱衣は減った点の割合だけ脱ぐ
  strip   脱ぎきるまで (脱衣を選んだときだけ): 負けるたびに重みの枚数を脱ぎ, 脱ぎきった方の負け (以前の脱衣ゲーム)
どの形でも, 脱ぎきった方はその場で負け (役満など).

罰ゲーム (PENALTIES): 双方向. あなたが負ければ, あなたが払う・脱ぐ・家事をする・券を渡す.
  privacy: public (人前でも可) / private (二人きりの家の中だけ). 組み合わせのどれかが private なら, そのゲームは private
  (games.place_why). 4 人麻雀 (A29) は public の罰だけを選べるようにする.
  w: 重さ (受けるかの判定で, 重いほど渋る). お金は額で重くなる.
  その場で済むもの (お金・着せ替え・スキンシップ・写真・質問・禁止・呼び方) と, あとで果たすもの (家事 (家にいなければ)・デート・
  おごり・相手が払えなかったお金・券). あとで果たすものは st["forfeit"]["owed"] に積み, 果たされたかを追う (tick):
    家事: 二人で家にいるときに果たす. デート: 決めた行き先へ一緒に出かければ果たす. おごり: 次に二人で払うものを負けた方が払う
    (life.plan_payment). お金: 払えるようになったら払う. 7 日 (デートとおごりは 14 日) で期限.
    あなたが果たさなかった: 約束やぶりと同じ (機嫌・信頼が下がる. 根に持つ性格ほど). 3 日前に一度メッセージで言ってくる.
    相手が果たさなかった: うやむやになる (記録だけ. あなたの側の不満の値は作らない).
  券 (何でも言うことを一つ聞く): 勝った方が持つ. あなたが使うときは, 頼む中身ごとに相手がまた受けるかを判定する
  (断られたら券は手元に残る). 相手が持っている券は, そばにいるときに相手が使ってくる (中身は相手が決める).

受けるか (judge): 始める前に, 組み合わせの重さを関係 (好感度・信頼・間柄)・性格 (慎重さ・恥ずかしがり)・機嫌で判定する.
同じ日に何度も持ちかけるほど渋る (断られるたびに少し機嫌が下がる). 回数を重ねれば必ず受ける道は作らない.
何も選ばずに始める既定の組み合わせは, 以前どおり定義の when (脱衣ゲームの好感度) だけで決める.
負けたあと罰を渋る・ごまかすこともある (律儀でない性格ほど. 脱衣は試合の流れの中なので渋らない).

遡及: いまのセーブに罰の記録は無い. 途中の脱衣ゲーム (st["game"] に bout が無い) は, 開いたときに既定の組み合わせ
(脱衣 + 脱ぎきるまで) として続く. 以前の成績の記録は持っていない (ゲームの記録はログにあるまま).
"""
import math
import random
import time

DAY = 86400.0

PENALTIES = (
    {"id": "strip", "label": "脱衣", "icon": "👚", "privacy": "private", "w": 0.9, "adult": True},
    {"id": "chores", "label": "家事・手伝い", "icon": "🧹", "privacy": "public", "w": 0.3},
    {"id": "date", "label": "デートの約束", "icon": "🎡", "privacy": "public", "w": 0.35},
    {"id": "money", "label": "お金", "icon": "💴", "privacy": "public", "w": 0.4},
    {"id": "pose", "label": "着せ替え・ポーズ", "icon": "📸", "privacy": "private", "w": 0.5, "adult": True},
    {"id": "ticket", "label": "何でも言うことを一つ聞く券", "icon": "🎫", "privacy": "public", "w": 0.6},
    {"id": "skinship", "label": "スキンシップ", "icon": "🤗", "privacy": "private", "w": 0.45},
    {"id": "callname", "label": "呼び方を一日変える", "icon": "🏷️", "privacy": "public", "w": 0.3},
    {"id": "honest", "label": "質問に正直に答える", "icon": "💬", "privacy": "public", "w": 0.5},
    {"id": "photo", "label": "罰ゲームの写真（変顔）", "icon": "🤪", "privacy": "public", "w": 0.4},
    {"id": "ban", "label": "一日○○禁止", "icon": "🚫", "privacy": "public", "w": 0.35},
)
PEN = {p["id"]: p for p in PENALTIES}
FORMS = {"one": "一発勝負", "n": "%d 回勝負", "first": "先に %d 勝", "points": "持ち点 %d", "strip": "脱ぎきるまで"}
N_RANGE = {"n": (2, 9), "first": (2, 9), "points": (2, 20)}
MONEY = (500, 1000, 3000, 5000, 10000)
DATE_PLACES = ("cafe", "eat_out", "aquarium", "amusement", "beach", "picnic", "stargazing", "date")
BANS = {"phone": "スマホ", "snack": "おやつ"}
CALLS = ("名前で呼び捨て", "{player}さま", "先輩", "ご主人さま", "{player}くん", "{player}ちゃん")
SKIN = {"hug": ("ハグ", "hugging, embrace, close-up, blush"), "lap": ("膝枕", "lap pillow, lying on lap, smile, blush"),
        "aan": ("あーん", "feeding, holding spoon, say ah, blush"), "pat": ("頭をなでる", "headpat, hand on head, blush, smile")}
PHOTO_POS = ("making a funny face, silly face, puffed cheeks, tongue out", "funny face, cross-eyed, pulling cheeks",
             "cosplay, cat ears, embarrassed, blush, peace sign")
TICKET_REQ = {     # 券であなたが頼めること: (名前, 重さ, 効き目, 絵)
    "lap": ("膝枕して", 0.45, {"heart": 6, "shyness": 8}, "lap pillow, lying on lap, looking down at viewer, smile"),
    "cook": ("手料理を作って", 0.25, {"heart": 3, "energy": -6}, "cooking, kitchen, apron, smile"),
    "massage": ("肩をもんで", 0.2, {"heart": 2, "energy": -3}, "massaging shoulders, from behind, smile"),
    "dress": ("好きな服で一日過ごして", 0.5, {"shyness": 10, "heart": 3}, "posing, showing outfit, blush"),
    "secret": ("本音をひとつ聞かせて", 0.45, {"shyness": 6, "trust": 1}, "embarrassed, looking away, blush"),
    "date": ("一日付き合って（デート）", 0.35, {"heart": 3}, ""),
}
HER_TICKET = {     # 相手があなたに使う券の中身: (名前, あなたが払うもの)
    "massage": ("肩をもんで", {"tire": 6}), "treat": ("今度おごって", {"treat": True}),
    "lap": ("膝枕して", {"tire": 2}), "errand": ("買い物に付き合って", {"tire": 8}),
}
OWE_DAYS = {"chores": 7, "money": 7, "date": 14, "treat": 14}
REMIND_BEFORE = 3 * DAY
TICKET_HER_P = 0.12      # そばにいる 1 時間あたり, 持っている券を使ってくる見込み

LINES = {
    "ff.accept": "いいよ。負けたら、ちゃんと{pen}だからね",
    "ff.refuse": "{pen}つきは……ちょっと、やめとく。ふつうに遊ぼうよ",
    "ff.pay": "……負けは負けだもんね。約束どおり、{pen}",
    "ff.renege": "えっと……{pen}は、また今度ってことで。ね？",
    "ff.collect": "{fp}の勝ち。じゃあ、約束どおり{pen}ね",
    "ff.lapse": "罰ゲームの{pen}、結局うやむやにしたでしょ。……覚えてるからね",
    "ff.remind": "📱 そういえば、罰ゲームの{pen}、まだだよね",
    "ff.ticket_yes": "券を出されたら、しょうがないな。……{what}、だね",
    "ff.ticket_no": "{what}は……ごめん、券があっても、それはなし。ほかのにして",
    "ff.ticket_her": "はい、これ。罰ゲームの券。……{what}",
    "ff.honest_high": "正直に言うとね、{call}といる時間、けっこう好きだよ",
    "ff.honest_mid": "正直に？ ……{call}のこと、まだよく分からないところもある。嫌いじゃないけど",
    "ff.honest_low": "正直に言うと……最近、{call}が何を考えてるのか、ちょっと分からない",
}
SCENE_LABEL = {
    "ff.accept": "罰ゲームつきの勝負を受ける ({pen} に罰の名前)",
    "ff.refuse": "罰ゲームつきの勝負を断る (重すぎる. {pen} に罰の名前)",
    "ff.pay": "負けて, 罰ゲームを受ける ({pen} に罰の中身)",
    "ff.renege": "負けたのに, 罰ゲームを渋る・ごまかす ({pen})",
    "ff.collect": "勝って, あなたに罰ゲームをさせる ({pen})",
    "ff.lapse": "あなたが罰ゲームの約束 (家事・デート・おごり・お金) を果たさず, 期限が過ぎた ({pen})",
    "ff.remind": "罰ゲームの約束がまだだと, メッセージで言ってくる (📱 で始める. {pen})",
    "ff.ticket_yes": "あなたが「何でも言うことを聞く券」を使い, 受ける ({what} に頼んだこと)",
    "ff.ticket_no": "あなたが券を使ったが, その中身は断る ({what})",
    "ff.ticket_her": "相手が持っている券を, あなたに使う ({what} に頼むこと)",
    "ff.honest_high": "罰ゲームで本音を言う (あなたを高く思っている)",
    "ff.honest_mid": "罰ゲームで本音を言う (まだ測りかねている)",
    "ff.honest_low": "罰ゲームで本音を言う (あなたをあまり良く思っていない)",
}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def privacy_of(pens):
    return "private" if any(PEN.get(p, {}).get("privacy") == "private" for p in pens or ()) else "public"


class Forfeit:
    def __init__(self, app):
        self.app = app
        self.always = False         # 必ず受ける (ミニゲームの単独版・テスト用)

    # ================================================================== 記録
    def rec(self, st):
        r = st.get("forfeit")
        if not isinstance(r, dict):
            r = st["forfeit"] = {}
        r.setdefault("owed", [])
        r.setdefault("tickets", {"mine": 0, "hers": 0})
        r.setdefault("day", [])
        r.setdefault("asks", [])
        return r

    def line(self, char, key, extra=None):
        app = self.app
        t = app.persona_text(char, key) or LINES[key]
        fp, _, call = app.pronouns(char)
        for k, v in dict(extra or {}, fp=fp, call=call).items():
            t = t.replace("{%s}" % k, str(v))
        return t

    # ================================================================== 組み合わせ
    @staticmethod
    def preset(g):
        """定義ごとの既定の組み合わせ (何も選ばずに始めたとき). 以前の遊び方と同じ."""
        from .games import STRIP_KINDS
        kind = g.get("kind")
        if kind in STRIP_KINDS or g.get("stages"):
            return {"pens": ["strip"], "form": "strip", "n": 0, "opt": {}}
        if kind in ("koikoi", "poker", "blackjack"):
            if g.get("match") == "points":
                return {"pens": [], "form": "n", "n": int(g.get("rounds", 3)), "opt": {}, "pts": True}
            return {"pens": [], "form": "first", "n": int(g.get("target", 3)), "opt": {}}
        return {"pens": [], "form": "one", "n": 1, "opt": {}}

    def normalize(self, g, char, req):
        """画面から選んだ組み合わせを確かめる. req が空なら既定."""
        if not req:
            return self.preset(g)
        pens = []
        for p in req.get("pens") or []:
            if p not in PEN:
                raise ValueError("罰ゲームが違います: %s" % p)
            if p not in pens:
                pens.append(p)
        from .posing import adult
        if any(PEN[p].get("adult") for p in pens) and not adult(char):
            raise ValueError("その罰ゲームは選べません")
        form = req.get("form") or "one"
        if form not in FORMS:
            raise ValueError("勝負の形が違います: %s" % form)
        if form == "strip" and "strip" not in pens:
            raise ValueError("「脱ぎきるまで」は、罰に脱衣を選んだときだけです")
        n = 1
        if form in N_RANGE:
            lo, hi = N_RANGE[form]
            try:
                n = int(req.get("n") or 0)
            except (TypeError, ValueError):
                n = 0
            if not lo <= n <= hi:
                raise ValueError("%sの数は %d〜%d です" % (FORMS[form].replace("%d", "n").replace(" ", ""), lo, hi))
        elif form == "strip":
            n = 0
        o = req.get("opt") or {}
        opt = {}
        if "money" in pens:
            m = o.get("money", 1000)
            if m == "treat":
                opt["money"] = "treat"
            else:
                try:
                    m = int(m)
                except (TypeError, ValueError):
                    m = 0
                if m not in MONEY:
                    raise ValueError("お金の額は %s 円から選んでください" % "・".join(format(x, ",") for x in MONEY))
                opt["money"] = m
        if "date" in pens:
            d = o.get("date") or ""
            if d and d not in DATE_PLACES:
                raise ValueError("デートの行き先が違います")
            opt["date"] = d
        if "callname" in pens:
            c = (str(o.get("call") or "")).strip()[:12]
            opt["call"] = c or CALLS[1]
        if "ban" in pens:
            b = o.get("ban") or "phone"
            if b not in BANS:
                raise ValueError("禁止するものが違います")
            opt["ban"] = b
        pts = form == "n" and g.get("kind") == "koikoi"
        return {"pens": pens, "form": form, "n": n, "opt": opt, "pts": pts}

    def label(self, b):
        f = FORMS[b["form"]]
        return f % b["n"] if "%d" in f else f

    def pen_label(self, p, opt, who="her"):
        if p == "money":
            m = opt.get("money")
            return "おごり（次の支払い）" if m == "treat" else "%s円" % format(int(m or 0), ",")
        if p == "date":
            d = opt.get("date")
            return "デートの約束%s" % ("（%s）" % self._place_name(d) if d else "")
        if p == "ban":
            return "一日%s禁止" % BANS.get(opt.get("ban"), "スマホ")
        if p == "callname" and who == "her":
            return "一日「%s」と呼ぶ" % self._call_text(opt.get("call"))
        return PEN[p]["label"]

    def _call_text(self, c):
        player = self.app.player_name() or "あなた"
        c = c or CALLS[1]
        if c == "名前で呼び捨て":
            return player
        return c.replace("{player}", player)

    def _place_name(self, aid):
        try:
            return self.app.action(aid).get("name", aid)
        except Exception:
            return aid

    def weight(self, b, char, st):
        """組み合わせの重さ (0〜1.6). 罰の重さの合計 (重いもの 1 つ + 残りの半分)・お金の額・一発勝負."""
        ws = []
        for p in b["pens"]:
            w = PEN[p]["w"]
            if p == "money":
                m = b["opt"].get("money")
                money = float(self.app.life.her_money(st).get("a", 0))
                w = 0.3 if m == "treat" else 0.2 + min(0.6, float(m) / max(5000.0, money * 0.5))
            if PEN[p]["privacy"] == "private":
                w += float(self.app.traits(char).get("modesty", 0)) / 40.0     # 恥ずかしがるほど重い
            ws.append(max(0.05, w))
        if not ws:
            return 0.0
        ws.sort(reverse=True)
        w = ws[0] + 0.5 * sum(ws[1:])
        if b["form"] == "one" and "strip" in b["pens"]:
            w += 0.15                                     # 一回で全部
        return min(1.6, w)

    def readiness(self, char, st, now=None):
        """乗り気の度合い (0〜1.2): 好感度・信頼・機嫌・間柄・慎重さ・その日に何度持ちかけられたか."""
        app = self.app
        now = now or time.time()
        p = st["params"]
        r = 0.5 + (p.get("affection", 50) - 50) / 100.0 + (p.get("trust", 50) - 50) / 200.0 + (p.get("mood", 50) - 50) / 200.0 \
            + {"visit": 0.1, "live": 0.2}.get(app.bonds.stage(char["id"]), 0.0) - float(app.traits(char).get("caution", 0)) / 50.0
        asks = sum(1 for t in self.rec(st)["asks"] if now - t < DAY)
        return _clamp(r - 0.15 * asks, 0.0, 1.2)

    def accept_chance(self, char, st, b, now=None):
        w = self.weight(b, char, st)
        if w <= 0:
            return 1.0
        return _clamp(self.readiness(char, st, now) + 0.45 - 0.6 * w, 0.02, 0.97)

    def judge(self, char, st, b, preset, now=None):
        """始める前に受けるか. (受ける, セリフ). 罰なしは必ず受ける.
        既定の組み合わせ (脱衣ゲームをそのまま始める) は, 以前どおり定義の when (好感度など) だけで決める (編集できる条件のまま)."""
        now = now or time.time()
        if not b["pens"] or preset:
            return True, None
        c = self.accept_chance(char, st, b, now)
        pen = "・".join(self.pen_label(p, b["opt"]) for p in b["pens"])
        if self.always or random.random() < c:
            return True, self.line(char, "ff.accept", {"pen": pen})
        r = self.rec(st)
        r["asks"] = [t for t in r["asks"] if now - t < DAY] + [now]
        self.app.apply_effects(st, self.app.trait_effects(char, {"mood": -1}))
        return False, self.line(char, "ff.refuse", {"pen": pen})

    # ================================================================== 勝負の進み
    def bout(self, g, game):
        """途中のゲームの勝負の記録 (以前の版で始めたものは既定の組み合わせ)."""
        b = game.get("bout")
        if not b:
            b = game["bout"] = dict(self.preset(g))
        b.setdefault("me", 0)
        b.setdefault("her", 0)
        b.setdefault("units", 0)
        b.setdefault("lost", {"me": 0, "her": 0})
        b.setdefault("pts", False)
        b.setdefault("score", {"me": 0, "her": 0})
        if b["form"] == "points":
            b.setdefault("hp", {"me": b["n"], "her": b["n"]})
        return b

    def strips(self, g, game):
        return "strip" in self.bout(g, game)["pens"]

    def _pieces(self, b, side, rem, steps, total):
        """負けた side が脱ぐ枚数."""
        if rem <= 0:
            return 0
        f = b["form"]
        if f == "strip":
            k = steps
        elif f == "one":
            k = rem
        else:       # n / first / points: 負けた割合だけ. n 回 (持ち点が尽きる) で全部, それより前に脱ぎきることはない
            lost = b["n"] - max(0, b["hp"][side]) if f == "points" else b["lost"][side] + steps
            target = total if lost >= b["n"] else min(total - 1, int(math.floor(total * lost / float(b["n"]) + 0.5)))
            k = target - (total - rem)
        return max(0, min(rem, k))

    def unit(self, cid, char, st, g, game, winner, steps=1, pts=None):
        """1 勝負の決着. winner = "p" (あなた) / "a" (相手) / None (引き分け). 試合の決着 ("win" / "lose" / "draw" / None) を返す.
        脱衣は game["stage"] (相手の脱いだ枚数) と game["lives"] (あなたの残り) を進める. 負けるたびの罰 (n 回勝負) もここで払う."""
        games = self.app.games
        b = self.bout(g, game)
        b["units"] += 1
        steps = max(1, int(steps or 1))
        side = {"p": "her", "a": "me"}.get(winner)          # 負けた方
        if winner == "p":
            b["me"] += steps
        elif winner == "a":
            b["her"] += steps
        if pts is not None and winner in ("p", "a"):
            b["score"]["me" if winner == "p" else "her"] += pts
        if b["form"] == "points" and side:
            b["hp"][side] = b["hp"][side] - steps
        bare = None
        if side and "strip" in b["pens"]:
            if side == "her":
                total = len(g.get("stages") or games.default_stages())
                rem = total - game.get("stage", 0)
                k = self._pieces(b, "her", rem, steps, total)
                if k and games._strip(g, char, st, game, k):
                    bare = "her"
            else:
                total = int(game.get("lives_max") or g.get("lives", 3))
                rem = int(game.get("lives", 0))
                k = self._pieces(b, "me", rem, steps, total)
                game["lives"] = rem - k
                if game["lives"] <= 0:
                    game["lives"], bare = 0, "me"
        if side:
            b["lost"][side] += steps
        f, n = b["form"], b["n"]
        ended = None
        if bare:
            ended = "win" if bare == "her" else "lose"
        elif f == "one":
            ended = {"p": "win", "a": "lose"}.get(winner)
        elif f == "first":
            ended = "win" if b["me"] >= n else "lose" if b["her"] >= n else None
        elif f == "points":
            ended = "lose" if b["hp"]["me"] <= 0 else "win" if b["hp"]["her"] <= 0 else None
        elif f == "n" and b["units"] >= n:
            a, c = (b["score"]["me"], b["score"]["her"]) if b.get("pts") else (b["me"], b["her"])
            ended = "win" if a > c else "lose" if a < c else "draw"
        now = time.time()
        if side and f == "n":                          # 負けるたびに罰
            for p in b["pens"]:
                if p != "strip":
                    self.pay(cid, char, st, g, side, p, b["opt"], now)
        elif ended in ("win", "lose") and f != "n":
            for p in b["pens"]:
                if p != "strip":
                    self.pay(cid, char, st, g, "her" if ended == "win" else "me", p, b["opt"], now)
        return ended

    # ================================================================== 罰を払う
    def _renege_chance(self, char, st, p, b_opt):
        tr = self.app.traits(char)
        c = 0.04 + 0.3 * (1 - float(tr.get("repay", 0.6))) - (st["params"].get("trust", 50) - 50) / 400.0
        if p == "money":
            c += 0.15 * float(tr.get("greed", 0.2))
        if p in ("ticket", "strip"):
            return 0.0
        return _clamp(c, 0.0, 0.5)

    def pay(self, cid, char, st, g, who, p, opt, now):
        """who (her = 相手 / me = あなた) が罰 p を払う. 記録 (ログ) を作る."""
        app = self.app
        name = char.get("name", "")
        label = self.pen_label(p, opt, who)
        if who == "her" and random.random() < self._renege_chance(char, st, p, opt):
            app.note_entry(char, st, now, "_forfeit", "罰ゲーム", "🙈", self.line(char, "ff.renege", {"pen": label}))
            app.trace.add("forfeit", "罰を渋った: %s" % p, cid, now)
            return "renege"
        say = self.line(char, "ff.pay" if who == "her" else "ff.collect", {"pen": label})
        fn = getattr(self, "_pay_" + p)
        fn(cid, char, st, g, who, opt, now, say, name)
        app.trace.add("forfeit", "罰: %s が %s" % (who, p), cid, now)
        return "paid"

    def _note(self, char, st, now, text, deltas=None, icon="🎯"):
        return self.app.note_entry(char, st, now, "_forfeit", "罰ゲーム", icon, text, deltas)

    def _image(self, cid, char, st, g, now, text, pos, eff=None):
        """絵のある罰 (着せ替え・スキンシップ・写真): ゲームの記録と同じ作り方."""
        app = self.app
        deltas = {}
        if eff:
            eff, _ = app.bonds.realize(char, st, eff, None, now)
            deltas = app.apply_effects(st, app.trait_effects(char, eff))
        e, _ = app.games._record(cid, char, st, g, {"text": text}, {}, pos, None, "（罰ゲーム）")
        e["deltas"] = deltas
        return e

    def _owe(self, st, who, p, opt, now, **extra):
        r = self.rec(st)
        days = OWE_DAYS.get("treat" if p == "money" and opt.get("money") == "treat" else p, 7)
        x = {"id": "%x" % int(now * 1000), "who": who, "pen": p, "t": now, "due": now + days * DAY,
             "opt": dict(opt), "reminded": False}
        x.update(extra)
        r["owed"].append(x)
        del r["owed"][:-20]
        return x

    def _pay_chores(self, cid, char, st, g, who, opt, now, say, name):
        app = self.app
        sp = (app.games.spot(cid, now) or {}).get("spot")
        if who == "her" and sp == "home":
            app.home.clean(30, now=now)
            d = app.apply_effects(st, {"energy": -6})
            self._note(char, st, now, "%s\n（罰ゲームで、%sが部屋を片付けてくれた）" % (say, name), d, "🧹")
        elif who == "me" and sp in ("home", "her_home"):
            app.life.tire(6)
            if sp == "home":
                app.home.clean(30, now=now)
            d = app.apply_effects(st, app.trait_effects(char, {"mood": 3}))
            self._note(char, st, now, "%s\n（罰ゲームで、%sの片付けをした）" % (say, "部屋" if sp == "home" else name + "の部屋"), d, "🧹")
        else:
            self._owe(st, who, "chores", opt, now)
            self._note(char, st, now, "%s\n（家事は、今度二人で家にいるときに）" % say, None, "🧹")

    def _pay_date(self, cid, char, st, g, who, opt, now, say, name):
        place = opt.get("date") if who == "her" else ""
        if not place:
            place = random.choice(DATE_PLACES)      # 勝った相手が決める (あなたが勝って決めていなければ, 相手のおまかせ)
        self._owe(st, who, "date", opt, now, place=place)
        self._note(char, st, now, "%s\n（%s約束: %s。14 日のうちに）" % (
            say, "%sが付き合う" % name if who == "her" else "あなたが連れていく", self._place_name(place)), None, "🎡")

    def _pay_money(self, cid, char, st, g, who, opt, now, say, name):
        app = self.app
        m = opt.get("money")
        if m == "treat":
            self._owe(st, who, "money", opt, now)
            self._note(char, st, now, "%s\n（次に二人で払うものは、%sが払う）" % (say, name if who == "her" else "あなた"), None, "💴")
            return
        m = int(m)
        if self._give(char, st, who, m, now):
            self._note(char, st, now, "%s\n（%s円を%s）" % (say, format(m, ","), "受け取った" if who == "her" else "渡した"), None, "💴")
        else:
            self._owe(st, who, "money", opt, now)
            self._note(char, st, now, "%s\n（いま手元に無いので、%s円はあとで）" % (say, format(m, ",")), None, "💴")

    def _give(self, char, st, who, m, now):
        """罰のお金を動かす. 払えなければ False."""
        life = self.app.life
        ps, hm = life.player_state(), life.her_money(st)
        if who == "her":
            if hm.get("a", 0) < m:
                return False
            hm["a"] -= m
            ps["money"] = ps.get("money", 0) + m
            life.ledger(now, m, "social", "%sから罰ゲームのお金" % char.get("name", ""))
        else:
            if ps.get("money", 0) < m:
                return False
            ps["money"] -= m
            hm["a"] = hm.get("a", 0) + m
            life.ledger(now, -m, "social", "%sへ罰ゲームのお金" % char.get("name", ""))
        life.save_player()
        return True

    def _pay_pose(self, cid, char, st, g, who, opt, now, say, name):
        app = self.app
        if who == "her":
            cands = [o for o in app.posing.all("pose") if int(o.get("bold") or 0) <= 1 and o.get("pos")]
            o = random.choice(cands) if cands else {"name": "ポーズ", "pos": "posing, peace sign, blush"}
            self._image(cid, char, st, g, now, "%s\n（罰ゲームで、%sが「%s」をした）" % (say, name, o.get("name", "")),
                        "%s, embarrassed, blush" % o["pos"], {"shyness": 10, "heart": 3})
        else:
            d = app.apply_effects(st, app.trait_effects(char, {"mood": 4}))
            self._note(char, st, now, "%s\n（罰ゲームで、言われたとおりのポーズをとった）" % say, d, "📸")

    def _pay_ticket(self, cid, char, st, g, who, opt, now, say, name):
        t = self.rec(st)["tickets"]
        k = "mine" if who == "her" else "hers"
        t[k] = min(9, int(t.get(k, 0)) + 1)
        self._note(char, st, now, "%s\n（%s）" % (
            say, "%sの「何でも言うことを聞く券」をもらった" % name if who == "her" else "%sに「何でも言うことを聞く券」を渡した" % name), None, "🎫")

    def _pay_skinship(self, cid, char, st, g, who, opt, now, say, name):
        k = random.choice(list(SKIN))
        lbl, pos = SKIN[k]
        text = "（罰ゲームで、%s）" % ("%sが%sをしてくれた" % (name, lbl) if who == "her" else "あなたが%sに%sをした" % (name, lbl))
        self._image(cid, char, st, g, now, "%s\n%s" % (say, text), pos, {"heart": 6, "shyness": 8})

    def _pay_callname(self, cid, char, st, g, who, opt, now, say, name):
        r = self.rec(st)
        r["day"] = [x for x in r["day"] if not (x["what"] == "call" and x["who"] == who)]
        if who == "her":
            c = self._call_text(opt.get("call"))
            r["day"].append({"who": "her", "what": "call", "name": c, "until": now + DAY})
            self._note(char, st, now, "%s\n（明日のこの時間まで、%sはあなたを「%s」と呼ぶ）" % (say, name, c), None, "🏷️")
        else:
            c = random.choice(("%sさま" % name, "%sちゃん" % name, "%sさん" % name))
            r["day"].append({"who": "me", "what": "call", "name": c, "until": now + DAY})
            d = self.app.apply_effects(st, self.app.trait_effects(char, {"mood": 3}))
            self._note(char, st, now, "%s\n（明日のこの時間まで、%sのことを「%s」と呼ぶことになった）" % (say, name, c), d, "🏷️")

    def _pay_honest(self, cid, char, st, g, who, opt, now, say, name):
        app = self.app
        if who == "me":
            d = app.apply_effects(st, app.trait_effects(char, {"trust": 1, "mood": 2}))
            self._note(char, st, now, "%s\n（罰ゲームで、聞かれたことに正直に答えた）" % say, d, "💬")
            return
        cands = app.knowsched.unknown(char, st)
        if cands and random.random() < 0.5:
            text = app.knowsched.learn(cid, random.choice(cands), "forfeit", now)
            if text:
                self._note(char, st, now, "%s\n（罰ゲームで聞いた: %s）" % (say, text), None, "💬")
                return
        v = app.regard.rec(char, st).get("v", 50)
        key = "ff.honest_high" if v >= 62 else "ff.honest_low" if v < 40 else "ff.honest_mid"
        d = app.apply_effects(st, {"shyness": 6})
        self._note(char, st, now, "%s\n%s" % (say, self.line(char, key)), d, "💬")

    def _pay_photo(self, cid, char, st, g, who, opt, now, say, name):
        app = self.app
        if who == "her":
            self._image(cid, char, st, g, now, "%s\n（罰ゲームの写真を撮った）" % say, random.choice(PHOTO_POS), {"shyness": 8, "mood": 1})
        else:
            d = app.apply_effects(st, app.trait_effects(char, {"mood": 5}))
            self._note(char, st, now, "%s\n（%sに、変顔の写真を撮られた）" % (say, name), d, "🤪")

    def _pay_ban(self, cid, char, st, g, who, opt, now, say, name):
        r = self.rec(st)
        what = opt.get("ban") or "phone"
        r["day"] = [x for x in r["day"] if not (x["what"] == what and x["who"] == who)]
        r["day"].append({"who": who, "what": what, "until": now + DAY})
        self._note(char, st, now, "%s\n（明日のこの時間まで、%sは%s禁止）" % (say, name if who == "her" else "あなた", BANS[what]), None, "🚫")

    # ================================================================== 一日の取り決め
    def day(self, st, who, what, now=None):
        now = now or time.time()
        r = st.get("forfeit") or {}
        return next((x for x in r.get("day") or [] if x["who"] == who and x["what"] == what and x["until"] > now), None)

    def call_override(self, char):
        """罰ゲームで変えた, あなたの呼び方 (無ければ None)."""
        st = self.app.states.get(char.get("id")) if hasattr(self.app, "states") else None
        if st is None:
            try:
                st = self.app.state(char["id"])
            except Exception:
                return None
        x = self.day(st, "her", "call")
        return x["name"] if x else None

    def phone_ban_until(self, st, now=None):
        x = self.day(st, "her", "phone", now)
        return x["until"] if x else None

    def allows(self, a, cid, now=None):
        """罰ゲームの禁止でできないこと (理由. できれば None)."""
        app = self.app
        now = now or time.time()
        st = app.state(cid)
        if a.get("category") == "連絡":
            for c2 in app.chars:
                x = self.day(app.state(c2), "me", "phone", now)
                if x:
                    return "罰ゲームで、%sまでスマホ禁止です" % time.strftime("%m/%d %H:%M", time.localtime(x["until"]))
        if a.get("id") == "snack":          # おやつ (一緒に食べる): どちらかが禁止なら
            if self.day(st, "her", "snack", now):
                return "%sは罰ゲームでおやつ禁止です（明日まで）" % app.chars[cid].get("name", "")
            if self.day(st, "me", "snack", now):
                return "あなたは罰ゲームでおやつ禁止です（明日まで）"
        return None

    # ================================================================== おごり
    def treat_policy(self, char, st):
        """次の支払いを誰がするか (罰のおごり). "me" / "her" / None."""
        for x in self.rec(st)["owed"]:
            if x["pen"] == "money" and x["opt"].get("money") == "treat":
                return x["who"]
        return None

    def treat_paid(self, char, st, payer, now):
        """二人で払った: 罰のおごりが果たされた. ひとこと (無ければ None)."""
        r = self.rec(st)
        x = next((x for x in r["owed"] if x["pen"] == "money" and x["opt"].get("money") == "treat" and x["who"] == payer), None)
        if not x:
            return None
        r["owed"].remove(x)
        return "（罰ゲームのおごりを、%s）" % ("果たした" if payer == "me" else "%sが果たした" % char.get("name", ""))

    # ================================================================== 券
    def use_ticket(self, cid, req, now=None):
        """あなたが持っている券を使う. 受けるかは中身しだい (断られたら券は残る)."""
        app = self.app
        now = now or time.time()
        with app.lock:
            char = app.char(cid)
            cid = char["id"]
            app.tick(cid)
            st = app.state(cid)
            t = self.rec(st)["tickets"]
            if int(t.get("mine", 0)) <= 0:
                raise ValueError("%sの券を持っていません" % char.get("name", ""))
            if req not in TICKET_REQ:
                raise ValueError("頼むことを選んでください")
            if not app.bonds.together(cid):
                raise ValueError("%sはそばにいません（会っているときに使えます）" % char.get("name", ""))
            name, w, eff, pos = TICKET_REQ[req]
            if req in ("lap", "dress") and not (app.games.spot(cid, now) or {}).get("private"):
                raise ValueError("「%s」は、二人きりの家で頼めます" % name)
            c = _clamp(self.readiness(char, st, now) + 0.55 - 0.6 * w, 0.05, 0.97)      # 券があるぶん, ふだんより受けやすい
            if random.random() >= c:
                e = self._note(char, st, now, self.line(char, "ff.ticket_no", {"what": name}), None, "🎫")
                app.save_state(cid)
                app.save_log(cid)
                return {"entry": e, "accepted": False}
            t["mine"] = int(t["mine"]) - 1
            say = self.line(char, "ff.ticket_yes", {"what": name})
            if req == "date":
                self._owe(st, "her", "date", {}, now, place=random.choice(DATE_PLACES))
                e = self._note(char, st, now, "%s\n（券で、デートの約束をした。14 日のうちに）" % say, None, "🎫")
            elif req == "secret":
                v = app.regard.rec(char, st).get("v", 50)
                key = "ff.honest_high" if v >= 62 else "ff.honest_low" if v < 40 else "ff.honest_mid"
                d = app.apply_effects(st, app.trait_effects(char, eff))
                e = self._note(char, st, now, "%s\n%s" % (say, self.line(char, key)), d, "🎫")
            else:
                e = self._image(cid, char, st, {"id": "ticket", "name": "券", "icon": "🎫"}, now, say, pos, eff)
            app.save_state(cid)
            app.save_log(cid)
            return {"entry": e, "accepted": True}

    def _her_ticket(self, char, st, now):
        """相手が持っている券を, あなたに使ってくる."""
        app = self.app
        t = self.rec(st)["tickets"]
        k = random.choice(list(HER_TICKET))
        name, cost = HER_TICKET[k]
        t["hers"] = int(t["hers"]) - 1
        say = self.line(char, "ff.ticket_her", {"what": name})
        if cost.get("treat"):
            self._owe(st, "me", "money", {"money": "treat"}, now)
            note = "（券を使われた: 次に二人で払うものは、あなたが払う）"
        else:
            app.life.tire(cost.get("tire", 0))
            note = "（券を使われて、%s）" % {"massage": "肩をもんだ", "lap": "膝枕をした", "errand": "付き合った"}[k]
        d = app.apply_effects(st, app.trait_effects(char, {"mood": 4, "heart": 2}))
        self._note(char, st, now, "%s\n%s" % (say, note), d, "🎫")
        app.trace.add("forfeit", "相手が券を使った: %s" % k, char["id"], now)

    # ================================================================== 時間の流れ
    def tick(self, char, st, now):
        """約束になった罰の行方 (果たした・催促・期限) と, 相手の券. 何か変わったら True."""
        app = self.app
        r = st.get("forfeit")
        if not r:
            return False
        cid = char["id"]
        changed = False
        r["day"] = [x for x in r.get("day") or [] if x["until"] > now]
        together = app.bonds.together(cid, now)
        sp = (app.games.spot(cid, now) or {}).get("spot") if together else None
        ov = st.get("override") or {}
        for x in list(r.get("owed") or []):
            p, who = x["pen"], x["who"]
            done = False
            if p == "chores" and sp in ("home", "her_home") and not st.get("game"):
                if who == "her" and sp == "home":
                    app.home.clean(30, now=now)
                    app.apply_effects(st, {"energy": -6})
                    self._note(char, st, now, "（罰ゲームの約束どおり、%sが部屋を片付けてくれた）" % char.get("name", ""), None, "🧹")
                    done = True
                elif who == "me":
                    app.life.tire(6)
                    if sp == "home":
                        app.home.clean(30, now=now)
                    self._note(char, st, now, "（罰ゲームの約束どおり、片付けをした）", app.apply_effects(st, {"mood": 2}), "🧹")
                    done = True
            elif p == "date" and together and ov.get("outing") and ov.get("activity") == x.get("place"):
                done = True
                d = app.apply_effects(st, app.trait_effects(char, {"mood": 3}))
                self._note(char, st, now, "（罰ゲームで約束したデート: %sに来た）" % self._place_name(x["place"]), d, "🎡")
            elif p == "money" and x["opt"].get("money") != "treat" and now - x.get("tried", 0) > DAY / 4:
                x["tried"] = now
                if self._give(char, st, who, int(x["opt"]["money"]), now):
                    done = True
                    self._note(char, st, now, "（罰ゲームの%s円を%s）" % (format(int(x["opt"]["money"]), ","),
                                                                  "受け取った" if who == "her" else "渡した"), None, "💴")
            if done:
                r["owed"].remove(x)
                changed = True
                continue
            label = self.pen_label(p, x["opt"], who)
            if now >= x["due"]:
                r["owed"].remove(x)
                changed = True
                if who == "me":       # 約束やぶりと同じ
                    gr = float(app.traits(char).get("grudge", 1.0))
                    d = app.apply_effects(st, app.trait_effects(char, {"mood": -4 * gr, "trust": -3 * gr}))
                    app.life.add_reason(st, "player", "bad", "罰ゲームの約束を、うやむやにされた", now, told=False,
                                        delta=d.get("mood", 0), action="_forfeit")
                    if together:
                        self._note(char, st, now, self.line(char, "ff.lapse", {"pen": label}), d, "😤")
                    else:
                        r.setdefault("grumble", []).append(label)
                else:
                    app.solo.note("forfeit", "（%sの罰ゲームの%sは、うやむやになった）" % (char.get("name", ""), label), now)
            elif who == "me" and not x["reminded"] and now >= x["due"] - REMIND_BEFORE and not together:
                x["reminded"] = True
                changed = True
                app.chat.add(cid, "her", self.line(char, "ff.remind", {"pen": label}), kind="forfeit_remind", t=now)
                app.picked_up_phone(char, st, now)
        if together and r.get("grumble"):
            label = r.pop("grumble")[0]
            self._note(char, st, now, self.line(char, "ff.lapse", {"pen": label}), None, "😤")
            changed = True
        if together and int(r["tickets"].get("hers", 0)) > 0 and not st.get("game"):
            last = r.get("tick_t") or now
            h = min(2.0, max(0.0, (now - last) / 3600.0))
            if h > 0 and random.random() < 1 - (1 - TICKET_HER_P) ** h:
                self._her_ticket(char, st, now)
                changed = True
        r["tick_t"] = now
        return changed

    # ================================================================== 画面
    def options(self, char, st, cid):
        """始めるときに選べるもの."""
        from .posing import adult
        ok_adult = adult(char)
        return {"pens": [{"id": p["id"], "label": p["label"], "icon": p["icon"], "privacy": p["privacy"]}
                         for p in PENALTIES if ok_adult or not p.get("adult")],
                "forms": [{"id": k, "label": v.replace("%d ", "n ").replace(" %d", " n").replace("%d", "n"),
                           "range": list(N_RANGE.get(k, (0, 0)))} for k, v in FORMS.items()],
                "money": list(MONEY), "dates": [{"id": d, "name": self._place_name(d)} for d in DATE_PLACES],
                "calls": [c.replace("{player}", self.app.player_name() or "あなた") for c in CALLS], "bans": BANS}

    def bout_view(self, g, game):
        b = self.bout(g, game)
        out = {"form": b["form"], "n": b["n"], "label": self.label(b), "me": b["me"], "her": b["her"], "units": b["units"],
               "pens": [{"id": p, "label": self.pen_label(p, b["opt"]), "icon": PEN[p]["icon"]} for p in b["pens"]],
               "between": bool(game.get("between"))}
        if b["form"] == "points":
            out["hp"] = dict(b["hp"])
        if b.get("pts"):
            out["score"] = dict(b["score"])
        return out

    def view(self, char, st, now=None):
        now = now or time.time()
        r = st.get("forfeit") or {}
        owed = [{"who": x["who"], "label": self.pen_label(x["pen"], x["opt"], x["who"]) +
                 ("（%s）" % self._place_name(x["place"]) if x.get("place") and not x["opt"].get("date") else ""),
                 "days": max(0, int((x["due"] - now) // DAY))} for x in r.get("owed") or []]
        day = [{"who": x["who"], "label": ("「%s」と呼ぶ" % x["name"]) if x["what"] == "call" else "%s禁止" % BANS.get(x["what"], ""),
                "until": time.strftime("%m/%d %H:%M", time.localtime(x["until"]))} for x in r.get("day") or [] if x["until"] > now]
        t = r.get("tickets") or {}
        return {"owed": owed, "day": day, "tickets": int(t.get("mine", 0)), "her_tickets": int(t.get("hers", 0)),
                "requests": [{"id": k, "name": v[0]} for k, v in TICKET_REQ.items()]}
