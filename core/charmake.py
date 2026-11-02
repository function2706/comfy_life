# -*- coding: utf-8 -*-
"""キャラメイキング (設定 → あなた): 質問に答えて, あなた (操作者) の値を現実のあなたに近づける.
- 決める値: スキル 9 つ (会話・スキンシップ・料理・仕事・家事・気配り・身だしなみ・やりくり・文章) / 貯金 (所持金) /
  運動の習慣 (body.exercise) / 車の免許.
- 質問はリスト (QUESTIONS) から, 決める値ごとに 1 つずつ (聞き方は何通りかからくじ) 選んで, 順番も混ぜて出す.
- 答えは選択肢 (いちばん近いもの). 反映すると, スキルは鈍りの目安 (skill_peak) も同じ値にそろえる.
  貯金は所持金をその額にする (借金・人から借りたお金はそのまま. 返すかは自分で).
- 心の中 (不満・我慢など) は聞かない (プレイヤー側の心理値は作らない).
"""
import random
import time

SK = [10, 22, 35, 50, 65]          # スキルの選択肢 → 値 (下から順に)

# 決める値: (表示名, 選択肢の値)
TARGETS = {
    "talk": ("会話", SK), "touch": ("スキンシップ", SK), "cook": ("料理", SK), "work": ("仕事", SK), "house": ("家事", SK),
    "care": ("気配り", SK), "groom": ("身だしなみ", SK), "budget": ("やりくり", SK), "write": ("文章", SK),
    "money": ("貯金", [10000, 50000, 150000, 400000, 1000000]),
    "exercise": ("運動", [20, 35, 50, 65, 80]),
    "drive": ("車の免許", [False, True]),
}

# (id, 決める値, 質問, 選択肢 (値の小さい順))
QUESTIONS = [
    ("talk1", "talk", "初対面の人と二人きりになったら？",
     ["何を話せばいいかわからず黙ってしまう", "聞かれたことには答えられる", "当たりさわりのない話ならできる", "自分から話題を振れる", "気づくと相手が楽しそうに話している"]),
    ("talk2", "talk", "飲み会や集まりでのあなたは？",
     ["隅で静かにしている", "近くの人と少し話す", "ふつうに輪に入れる", "場を回すことが多い", "いつも中心にいる"]),
    ("talk3", "talk", "電話で知らないお店に問い合わせるのは？",
     ["できれば避けたい", "メモを用意すればできる", "特に苦ではない", "むしろ得意", "雑談まで弾む"]),
    ("touch1", "touch", "友だちや身近な人に触れることは？",
     ["ほとんどない", "握手くらい", "肩をたたくくらいは自然に", "ハグもわりと平気", "スキンシップは多いほう"]),
    ("touch2", "touch", "マッサージや髪を触るような、人に触れる手つきは？",
     ["まったく自信がない", "やり方がよくわからない", "人並み", "上手と言われたことがある", "よく頼まれる"]),
    ("cook1", "cook", "ふだんの食事は？",
     ["ほぼ外食か買ったもの", "たまにインスタントを作る", "簡単なものは自炊する", "毎日のように自炊する", "人にふるまえるくらい作る"]),
    ("cook2", "cook", "冷蔵庫の余りもので一品作れる？",
     ["無理", "炒めるくらいなら", "レシピを見ればなんとか", "だいたい作れる", "得意"]),
    ("work1", "work", "仕事（勉強）の段取りは？",
     ["いつもぎりぎり", "言われたことはこなせる", "人並みにこなせる", "頼られることが多い", "まわりをまとめる側"]),
    ("work2", "work", "職場や学校での評価は？",
     ["叱られることが多い", "可もなく不可もなく", "まじめと言われる", "仕事ができると言われる", "替えがきかないと言われる"]),
    ("house1", "house", "部屋の片付け・洗濯などの家事は？",
     ["ほとんどやらない", "たまったらやる", "ひと通りやっている", "まめにやるほう", "家事は得意"]),
    ("house2", "house", "急に人が部屋に来ることになったら？",
     ["見せられる状態ではない", "大急ぎで片付ければなんとか", "少し片付ければ大丈夫", "いつでも呼べる", "むしろ来てほしい"]),
    ("care1", "care", "人の体調や機嫌の変化に気づく？",
     ["言われるまで気づかない", "たまに気づく", "人並みに気づく", "よく気づくほう", "先回りして動ける"]),
    ("care2", "care", "具合の悪い人の世話をするのは？",
     ["どうしていいかわからない", "言われればできる", "ひと通りできる", "慣れている", "看病は得意"]),
    ("groom1", "groom", "身だしなみや服装は？",
     ["気にしない", "最低限は整える", "人並みに気をつかう", "おしゃれなほう", "服や髪にこだわりがある"]),
    ("groom2", "groom", "朝の支度にかける手間は？",
     ["起きてすぐ出られる", "顔を洗って寝ぐせを直すくらい", "ふつうに整える", "けっこう時間をかける", "納得いくまで整える"]),
    ("budget1", "budget", "お金の管理は？",
     ["あるだけ使ってしまう", "なんとなく気にしている", "だいたい把握している", "家計簿をつけている", "予算を決めてきっちり管理"]),
    ("budget2", "budget", "買い物のときは？",
     ["欲しいものはすぐ買う", "値段は少し見る", "安いほうを選ぶ", "比べてから買う", "底値まで把握している"]),
    ("write1", "write", "文章を書くのは？",
     ["苦手", "短いメッセージなら", "人並み", "わりと得意", "文章で褒められることが多い"]),
    ("write2", "write", "長めのメールや報告書を書くことになったら？",
     ["何から書けばいいかわからない", "時間をかければ書ける", "ふつうに書ける", "わかりやすいと言われる", "頼まれて代わりに書くこともある"]),
    ("money1", "money", "いまの貯金はどれくらい？（いちばん近いもの）",
     ["ほとんどない（1万円くらい）", "5万円くらい", "15万円くらい", "40万円くらい", "100万円くらい"]),
    ("money2", "money", "急に5万円の出費があったら？",
     ["払えない", "かなり苦しい", "痛いけど払える", "特に困らない", "気にならない"]),
    ("ex1", "exercise", "ふだんの運動は？",
     ["ほとんど動かない", "通勤・通学で歩くくらい", "ときどき散歩や軽い運動", "週に何度か運動する", "毎日のように運動する"]),
    ("ex2", "exercise", "駅の階段を一気に上ると？",
     ["息が切れてつらい", "少し息が上がる", "ふつう", "平気", "まだまだ余裕"]),
    ("drive1", "drive", "車の運転免許は？", ["持っていない", "持っている"]),
]


class CharMake:
    def __init__(self, app):
        self.app = app

    def questions(self, rng=random):
        """決める値ごとに 1 つずつ (聞き方はくじ), 順番も混ぜて."""
        by = {}
        for q in QUESTIONS:
            by.setdefault(q[1], []).append(q)
        pick = [rng.choice(v) for v in by.values()]
        rng.shuffle(pick)
        return [{"id": qid, "target": t, "label": TARGETS[t][0], "q": text, "options": opts} for qid, t, text, opts in pick]

    def current(self):
        """いまの値 (答えの初期位置の目安)."""
        ps = self.app.life.player_state()
        out = {k: float(ps["skills"].get(k, 10)) for k in TARGETS if TARGETS[k][1] is SK}
        out.update(money=int(ps["money"]), exercise=float(self.app.body.rec().get("exercise", 50)), drive=self.app.quals.has("drive"))
        return out

    def apply(self, answers):
        """answers {質問 id: 選んだ番号} を反映して, 変わったもの [{label, old, new}] を返す."""
        app, L = self.app, self.app.life
        ps = L.player_state()
        qs = {q[0]: q for q in QUESTIONS}
        got = {}
        for qid, i in (answers or {}).items():
            if qid not in qs:
                raise ValueError("知らない質問です: %s" % qid)
            t = qs[qid][1]
            vals = TARGETS[t][1]
            i = int(i)
            if not 0 <= i < len(vals):
                raise ValueError("選択肢の番号が違います: %s" % qid)
            got[t] = vals[i]
        cur, out = self.current(), []
        for t, v in got.items():
            if TARGETS[t][1] is SK:
                ps["skills"][t] = float(v)
                ps.setdefault("skill_peak", {})[t] = float(v)
            elif t == "money":
                ps["money"] = int(v)
            elif t == "exercise":
                app.body.rec()["exercise"] = float(v)
            elif t == "drive":
                have = app.quals.rec()["have"]
                if v:
                    have.setdefault("drive", time.time())
                else:
                    have.pop("drive", None)
            out.append({"target": t, "label": TARGETS[t][0], "old": cur[t], "new": v})
        L.save_player()
        app.trace.add("charmake", "キャラメイキングを反映", None, time.time(), changes=out)
        return {"changes": out}
