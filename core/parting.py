"""別れぎわ (解散して家に帰る・相手の家から帰る・送っていく): 相手が応じるか.

以前は押せば必ず別れていて, 「もう帰るんですか？」と言わせても何も変わらなかった. 現実的に:
- もっと一緒にいたいか (want): 機嫌・好感度・寂しさ・依存度・会ってからの長さ (来たばかりなら「もう？」)・疲れ・時間帯
- いたくても, それを口に出すか (voice): 自分から来る度合い (approach)・遠慮 (modesty)・仲・依存度.
  献身的なほど, あなたに合わせて飲み込む (言い出したのはあなたなので, 断りにくい)
  - 口に出せば引き止める: その場は別れない (反応 part=hold. コマンドは効かない)
  - 飲み込めば応じる: 名残惜しそう (part=reluctant. 機嫌が少し下がる)
- 引き止められたあと, 30 分のうちにもう一度言えば, それでも帰る (part=insist. 寂しがる)
- いたいと思っていなければ, ふつうに応じる (part=ok)
反応の条件 part (ok / reluctant / hold / insist). 画面のボタンは, 引き止められている間は確かめてから (available の confirm).
"""
import random
from datetime import datetime

PART_ACTIONS = ("go_home", "leave_visit", "see_off")
FIXED = None          # テスト用: 決めた part にする (別れが主題でないテストは "ok" にして, 必ず応じる)
HOLD_SEC = 1800
CONFIRM = {"go_home": "%sはもう少し一緒にいたそうでした。それでも解散して帰りますか？",
           "leave_visit": "%sはもう少しいてほしそうでした。それでも帰りますか？",
           "see_off": "%sはもう少しいたそうでした。それでも送っていきますか？"}


class Parting:
    def __init__(self, app):
        self.app = app

    def pending(self, char, st, aid, now):
        """引き止められていて, まだその返事をしていない (同じ会っている間の, 30 分のうち)."""
        h = st.get("part_hold") or {}
        return h.get("aid") == aid and now - float(h.get("t", 0)) < HOLD_SEC and h.get("since") == self.since(char["id"], st)

    def confirm(self, char, st, aid, now):
        return CONFIRM[aid] % char.get("name", "相手") if self.pending(char, st, aid, now) else None

    def since(self, cid, st):
        """会った (相手の家に来た・招いた・一緒に出かけた) 時刻. わからなければ None."""
        w = self.app.bonds.with_rec() or {}
        if w.get("cid") == cid and w.get("mode") in ("meet", "visit", "guest"):
            return w.get("t")
        return (st.get("override") or {}).get("start")

    def elapsed(self, cid, st, now):
        """会ってからの長さ (秒). わからなければ None."""
        s = self.since(cid, st)
        return now - float(s) if s else None

    def want(self, char, st, aid, now):
        """もっと一緒にいたい見込み (0〜1)."""
        app = self.app
        cid = char["id"]
        p = st["params"]
        if p.get("energy", 60) < 20 or p.get("mood", 50) < 30:
            return 0.0                     # くたくた / 機嫌が悪い: 早く帰りたい
        w = 0.2 + (p.get("mood", 50) - 50) / 120.0 + (p.get("affection", 50) - 50) / 150.0 \
            + p.get("loneliness", 0) / 250.0 + 0.2 * app.attach.factor(char, st, "dependence")
        el = self.elapsed(cid, st, now)
        if el is not None:
            w += 0.25 if el < 40 * 60 else 0.1 if el < 90 * 60 else -0.15 if el > 4 * 3600 else 0.0
        if p.get("energy", 60) < 35:
            w -= 0.3
        h = datetime.fromtimestamp(now).hour
        stage = app.bonds.stage(cid)
        if (h >= 22 or h < 5) and stage != "live":
            w -= 0.15
        if aid == "go_home" and stage == "live":
            w -= 0.2                       # 同居: 帰っても一緒 (その場所に, もう少しいたいかだけ)
        return max(0.0, min(0.9, w))

    def voice(self, char, st):
        """いたくても口に出す見込み (0〜1). 献身的なほど飲み込む."""
        app = self.app
        cid = char["id"]
        tr = app.traits(char)
        close = {"live": 0.2, "visit": 0.1}.get(app.bonds.stage(cid), 0.0)
        v = 0.35 + 0.3 * (float(tr.get("approach", 1.0)) - 1.0) - 0.02 * float(tr.get("modesty", 0)) + close \
            + 0.15 * app.attach.factor(char, st, "dependence") - 0.2 * app.attach.factor(char, st, "devotion") \
            + (st["params"].get("affection", 50) - 60) / 200.0
        return max(0.05, min(0.9, v))

    def decide(self, char, st, aid, now):
        """反応の条件 part を決める (ok / reluctant / hold / insist)."""
        if FIXED:
            return FIXED
        if self.pending(char, st, aid, now):
            part, w, v = "insist", None, None
        else:
            w = self.want(char, st, aid, now)
            v = self.voice(char, st)
            part = "ok" if random.random() >= w else "hold" if random.random() < v else "reluctant"
        self.app.trace.add("parting", "別れぎわ: %s" % part, char["id"], now, aid=aid,
                           want=None if w is None else round(w, 2), voice=None if v is None else round(v, 2))
        return part

    def settle(self, char, st, aid, part, now):
        """反応を出したあと: 引き止めなら覚えておき, 別れたら忘れる."""
        if part == "hold":
            st["part_hold"] = {"aid": aid, "t": now, "since": self.since(char["id"], st)}
        else:
            st.pop("part_hold", None)
