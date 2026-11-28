"""同居のエアコン争い (S58. A42 段 2 の 2). 冷暖房の使い方は家に 1 つ (core/home.py の ac_mode / set_ac).
反応の作り (見る間隔・出方・答え・気づき) は部屋の設定の土台 core/ambience.py の Reactor (S61). ここは冷暖房の差し替え分だけ.
同居相手のほか, あなたの家に来ている相手も言ってくる / 我慢する (来ている相手は自分では変えない. S61).

- 好み: その人の好みの室温 (season.pref_room. 暑がりは低め・寒がりは高め) から 1℃ を超えてずれると, 暑い / 寒い (season.ac_fuss).
- 同居相手とあなたが家で起きているとき, 1 時間に一度だけ見て, 合わない度合いしだいで (一日に一度まで):
  言ってくる (性格の approach) / 自分で変える (管理傾向 moneytalk.manage) / 黙って我慢する (言わないまま機嫌が少し下がる).
  変えても過ごしやすくならない (春・秋で冷暖房が動かない) ときは何もしない.
- 言ってきたら: 合わせる (相手の使い方に. 喜ぶ) / 電気代を理由に断る (相手の使い方の方が高いときだけ. 納得するかは会話スキル) /
  このままがいいと言い返す (渋々か, 言い争いに. core/quarrel.py).
- あなたが「家の様子」で使い方を変えたとき, 同居相手がそばにいれば気づく: 過ごしにくくなった (相手が変えたのを戻したなら強く) /
  過ごしやすくなった (ありがとう). 二重に開いた画面で同じ使い方を押しても, 変わらなければ何も起きない.
あなたの暑い・寒いの値は作らない (あなたが払うのは電気代だけ). 遡及なし (性格の暑がり / 寒がりから, これから起きる).
"""
import random
from datetime import datetime

from . import ambience as amb_mod
from . import season as season_mod

CHOICES = {"match": "合わせる", "bill": "電気代が気になると断る", "push": "このままがいいと言い返す"}
LINES = {
    "ac.ask_hot": "……ちょっと暑くないですか？ {ac}もいいですか？",
    "ac.ask_cold": "……ちょっと寒くないですか？ {ac}もいいですか？",
    "ac.self_hot": "暑かったので、{ac}おきました",
    "ac.self_cold": "寒かったので、{ac}おきました",
    "ac.match": "ありがとうございます。……これで落ち着きます",
    "ac.bill_ok": "……電気代、そうですよね。もうちょっと我慢してみます",
    "ac.bill_meh": "……それはそうですけど。{feel}ものは{feel}んですよ",
    "ac.push_unhappy": "……わかりました。我慢します",
    "ac.push_fight": "{fp}が{feel}って言ってるのに、どうしてそうなるんですか",
    "ac.undo": "あれ、戻しました？ {fp}、さっき変えたんですけど……",
    "ac.notice_hot": "……なんだか暑くなってきましたね",
    "ac.notice_cold": "……なんだか寒くなってきましたね",
    "ac.thanks": "あ、ちょうどよくなりました。ありがとうございます",
}
SCENE_LABEL = {"ask_hot": "部屋が暑くて, 冷暖房を変えていいか聞く ({ac} に「冷房をもう少し強くして」など)",
               "ask_cold": "部屋が寒くて, 冷暖房を変えていいか聞く ({ac} に「暖房をつけて」など)",
               "self_hot": "部屋が暑くて, 自分で冷暖房を変えておいた ({ac})", "self_cold": "部屋が寒くて, 自分で冷暖房を変えておいた ({ac})",
               "match": "冷暖房を合わせてもらって, ほっとする", "bill_ok": "電気代を理由に断られて, 納得する",
               "bill_meh": "電気代を理由に断られたが, 微妙 ({feel} に 暑い / 寒い)", "push_unhappy": "このままがいいと言い返されて, 渋々我慢する",
               "push_fight": "このままがいいと言い返されて, 言い争いに ({feel} に 暑い / 寒い)",
               "undo": "自分で変えた冷暖房を, あなたに戻された", "notice_hot": "あなたが冷暖房を変えて, 部屋が暑くなった",
               "notice_cold": "あなたが冷暖房を変えて, 部屋が寒くなった", "thanks": "あなたが冷暖房を変えて, 過ごしやすくなった"}


def phrase(t, cur, want):
    """「冷房をもう少し強くして」など (cur から want へ変える言い方)."""
    kind = "冷房" if season_mod.warm_half(t) else "暖房"
    o = season_mod.AC_ORDER
    if o.index(want) > o.index(cur):
        return kind + ("をつけて" if cur == "off" else "をもう少し強くして")
    return kind + ("を切って" if want == "off" else "を少し弱くして")


class Aircon(amb_mod.Reactor):
    LINES = LINES
    CHOICES = CHOICES

    def current(self):
        return self.app.home.ac_mode()

    def put(self, v, cid):
        self.app.home.set_mode(v)

    def want(self, char, t):
        """(合わない度合い, 変えたい使い方). 変えても過ごしやすくならなければ使い方は None."""
        app = self.app
        tc = season_mod.temp(datetime.fromtimestamp(t))
        cur = app.home.ac_mode()
        f = season_mod.ac_fuss(app, char, tc, cur)
        w = season_mod.ac_best(app, char, tc)
        if w == cur or abs(season_mod.ac_fuss(app, char, tc, w)) > abs(f) - 0.2:
            return f, None
        return f, w

    def decide(self, char, st, now):
        f, w = self.want(char, now)
        if not w or abs(f) < 0.3:
            return None
        side = "hot" if f > 0 else "cold"
        ac = phrase(season_mod.temp(datetime.fromtimestamp(now)), self.current(), w)
        return {"f": abs(f), "w": w, "p": min(0.5, 0.25 * abs(f)), "say": "ask_" + side, "self": "self_" + side,
                "endure": "部屋が%sのを我慢した" % ("暑い" if f > 0 else "寒い"), "talk": {"hot": f > 0}, "extra": {"ac": ac}}

    def ask_text(self, char, at):
        return "（%sが、部屋が%sと言っている。冷暖房を「%s」にしたいらしい）" % (
            char.get("name", ""), "暑い" if at["hot"] else "寒い", season_mod.AC_LABEL[at["want"]])

    def choices(self, at):
        costly = season_mod.AC_ORDER.index(at["want"]) > season_mod.AC_ORDER.index(self.app.home.ac_mode())
        return {k: v for k, v in CHOICES.items() if k != "bill" or costly}

    def answer(self, char, st, at, choice, now):
        app = self.app
        feel = "暑い" if at["hot"] else "寒い"
        if choice == "match":
            app.home.set_mode(at["want"])
            key, eff = "match", {"mood": 2}
        elif choice == "bill":
            ok = random.random() < 0.3 + 0.5 * app.life.skill_soft("talk")
            key, eff = ("bill_ok", {"mood": -0.5}) if ok else ("bill_meh", {"mood": -1.5})
        else:
            fight = self.fight(char, st, now)
            key, eff = ("push_fight", {"mood": -3}) if fight else ("push_unhappy", {"mood": -2})
        said = {"match": "（冷暖房を「%s」にした）" % season_mod.AC_LABEL[at["want"]], "bill": "（電気代が気になると断った）",
                "push": "（このままがいいと言い返した）"}[choice]
        return key, eff, said, {"feel": feel}

    def granted(self, char, st, at, old, new, now):
        tc = season_mod.temp(datetime.fromtimestamp(now))
        return abs(season_mod.ac_fuss(self.app, char, tc, new)) < abs(season_mod.ac_fuss(self.app, char, tc, old))

    def react(self, char, st, old, new, undo, now):
        tc = season_mod.temp(datetime.fromtimestamp(now))
        fo, fn = season_mod.ac_fuss(self.app, char, tc, old), season_mod.ac_fuss(self.app, char, tc, new)
        if abs(fn) >= 0.3 and abs(fn) > abs(fo) + 0.2:
            if undo:
                return "undo", {"mood": -2}, 0.8, {}
            return "notice_" + ("hot" if fn > 0 else "cold"), {"mood": -1}, 0.4, {}
        if abs(fo) >= 0.3 and abs(fn) < abs(fo) - 0.2:
            return "thanks", {"mood": 1}, 0.5, {}
        return None
