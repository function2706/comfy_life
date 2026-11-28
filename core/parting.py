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

相手からの切り上げ (A41・S34): 会っている間に, 相手から早めに帰ると言い出す (疲れ・体調・明日が早い・急な連絡・気分).
- 会うたびに一度だけ, 起きるかと時刻 (会ってから 45〜150 分) を決める (cut_chance. ふつう 1 割未満. 疲れ・体調・機嫌・ストレス・
  明日が早いで上がり, 仲がいいほど・最近切り上げたばかりほど下がる). 理由は言い出すときの相手の状態から (cut_why).
- 働きかけ leave_<理由> (defaults/approaches.json. 決めた時刻にだけ出る forced) で言う: 「うん, 帰ろう」= 別れる (解散 / 送っていく /
  あなたが帰る), 「もう少しだけいない？」= 引き止める (cut_hold: 理由の重さと仲で, 応じる / それでも帰る).
- あなたが「ひと休みする」を選んだ直後 (1 時間) は言い出さない (少しあとに延ばす). 返事がなければ, 一度だけ言い直す.
- 相手から言い出したあとの別れは, 引き止められない (decide が ok).
"""
import random
import time
from datetime import datetime, timedelta

PART_ACTIONS = ("go_home", "leave_visit", "see_off")
FIXED = None          # テスト用: 決めた part にする (別れが主題でないテストは "ok" にして, 必ず応じる)
HOLD_SEC = 1800
CONFIRM = {"go_home": "%sはもう少し一緒にいたそうでした。それでも解散して帰りますか？",
           "leave_visit": "%sはもう少しいてほしそうでした。それでも帰りますか？",
           "see_off": "%sはもう少しいたそうでした。それでも送っていきますか？"}
CUT_FIXED = None      # テスト用: 切り上げの起きやすさを決めた値に
CUT_SPAN = 30 * 86400
CUT_LEAVE = {"guest": "see_off", "visit": "leave_visit"}        # 相手から帰ると言われて「うん」: 会っている形ごとの別れ (外なら go_home)
CUT_STAY = {"call": 0.1, "sick": 0.15, "early": 0.4, "tired": 0.4, "mood": 0.3}     # 引き止めに応じる見込みのもと (理由の重さ)
LINES = {
    "leave.stay": "……じゃあ、もう少しだけ。",
    "leave.go": "ごめんなさい、やっぱり今日は帰ります。また今度、ゆっくり。",
}
SCENE = {"leave.stay": "相手から早めに帰ると言い出して, 引き止められて, 応じた",
         "leave.go": "相手から早めに帰ると言い出して, 引き止められたが, それでも帰る"}


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
        if now - float(st.get("part_her", 0)) < 3600:
            return "ok"                  # 相手から帰ると言い出した (切り上げ): 引き止めない
        if aid == "go_home" and self.app.bonds.stay_back(char["id"], now):
            return "ok"                  # 泊まる約束: 「帰る」は二人でその家へ戻るだけで, 別れではない
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

    # ------------------------------------------------------------------ 相手からの切り上げ (A41・S34)
    def cut_recent(self, st, now):
        return len([t for t in st.get("cuts") or [] if 0 <= now - t < CUT_SPAN])

    def early_tomorrow(self, char, now):
        """明日の朝が早い (7 時半に, もう出かけている・手が離せない予定)."""
        d = (datetime.fromtimestamp(now) + timedelta(days=1)).replace(hour=7, minute=30, second=0, microsecond=0)
        sc = self.app.scheduled_scene(char, d)
        return bool(sc.get("away") or sc.get("busy"))

    def cut_chance(self, char, st, now):
        """この会っている間に, 相手から切り上げる見込み (ふつう 1 割未満)."""
        if CUT_FIXED is not None:
            return CUT_FIXED
        p = st["params"]
        c = 0.03 + (0.08 if p.get("energy", 60) < 35 else 0.0) + (0.1 if p.get("health", 90) < 50 else 0.0) \
            + (0.05 if p.get("mood", 50) < 40 else 0.0) + (0.03 if p.get("stress", 0) > 65 else 0.0)
        if datetime.fromtimestamp(now).hour >= 17 and self.early_tomorrow(char, now):
            c += 0.03
        c *= max(0.4, min(1.0, 1.25 - p.get("affection", 50) / 100.0)) * 0.5 ** self.cut_recent(st, now)
        return c

    def cut_why(self, char, st, now):
        """言い出すときの理由 (その時の相手の状態から): tired / sick / early / mood / call."""
        p = st["params"]
        w = {"call": 1.0}
        if p.get("energy", 60) < 40:
            w["tired"] = 3.0
        if p.get("health", 90) < 50:
            w["sick"] = 3.0
        if p.get("mood", 50) < 40 or p.get("stress", 0) > 65:
            w["mood"] = 2.0
        if datetime.fromtimestamp(now).hour >= 17 and self.early_tomorrow(char, now):
            w["early"] = 2.0
        return random.choices(list(w), list(w.values()))[0]

    def cut_live(self, char, st, now):
        """会っている間 (state_view のたび): 会うたびに一度, 切り上げるかを決め, その時刻になれば言い出す. 言い出したら記録を返す."""
        app = self.app
        cid = char["id"]
        if app.bonds.mode(cid) not in ("meet", "visit", "guest") or app.bonds.stage(cid) == "live" or app.stay.staying(cid):
            return None
        since = self.since(cid, st)
        if not since:
            return None
        c = st.get("cut") or {}
        if c.get("since") != since:
            pr = self.cut_chance(char, st, now)
            c = {"since": since}
            if random.random() < pr:
                c["at"] = float(since) + random.uniform(45, 150) * 60
            st["cut"] = c
            app.trace.add("parting", "切り上げの見込み", cid, now, chance=round(pr, 3), at=c.get("at"))
            app.save_state(cid)
            return None
        if not c.get("at") or now < c["at"] or st.get("approach") or st.get("game") or app.phonetalk.rec():
            return None
        rests = (st.get("override") or {}).get("rests") or []
        if any(0 <= now - float(r) < 3600 for r in rests):
            c["at"] = now + 30 * 60               # ひと休みした直後: 少しあとに延ばす
            app.save_state(cid)
            return None
        why = c.get("why") or self.cut_why(char, st, now)
        d = datetime.fromtimestamp(now)
        e = app.presence.fire(char, st, now, app.context(char, st, d, app.scene_at(char, st, d)), force="leave_" + why)
        c.update(why=why, n=int(c.get("n", 0)) + 1)
        c.pop("at")
        st["part_her"] = now
        if c["n"] == 1:
            st["cuts"] = [t for t in st.get("cuts") or [] if 0 <= now - t < CUT_SPAN] + [now]
            app.appoint.her_note(st, now)
        app.trace.add("parting", "相手から切り上げを言い出した: %s" % why, cid, now, n=c["n"])
        app.save_state(cid)
        return e

    def cut_ignored(self, st, now):
        """言い出したのに返事がなかった: 10 分ほどして, 一度だけ言い直す."""
        c = st.get("cut") or {}
        if c.get("why") and int(c.get("n", 0)) < 2:
            c["at"] = now + 10 * 60

    def cut_line(self, char, key):
        app = self.app
        t = app.persona_text(char, key) or LINES[key]
        return t

    def cut_hold(self, char, st, a, now, use_action):
        """切り上げを引き止めた: 理由の重さ・仲・寄りかかりで, 応じる (もう少しいる) / それでも帰る. (記録, 代わりにするコマンド)."""
        app = self.app
        cid = char["id"]
        p = st["params"]
        why = (st.get("cut") or {}).get("why") or a["id"].replace("leave_", "")
        pr = CUT_STAY.get(why, 0.3) + (p.get("affection", 50) - 50) / 150.0 + 0.15 * app.attach.factor(char, st, "dependence")
        stay = random.random() < max(0.03, min(0.8, pr))
        st["approach"] = None
        app.presence.touch(now)
        st["last_interaction"] = now
        st["ap_quiet_until"] = now + 30 * 60
        app.trace.add("parting", "切り上げを引き止めた: %s" % ("応じた" if stay else "それでも帰る"), cid, now, why=why, chance=round(pr, 2))
        if stay:
            st.pop("part_her", None)
            deltas = app.apply_effects(st, app.trait_effects(char, {"mood": -1, "stress": 2} if why in ("tired", "sick", "mood") else {"mood": -1}))
            e = app.presence._entry(char, st, now, a, "stay", self.cut_line(char, "leave.stay"), deltas, None, gen=False)
            app.save_state(cid)
            return e, None
        e = app.presence._entry(char, st, now, a, "go", self.cut_line(char, "leave.go"), {}, None, gen=False)
        app.save_state(cid)
        return e, ((a.get("accept") or {}).get("action") if use_action else None)

    def cut_action(self, cid):
        """相手から帰ると言われて別れるときのコマンド (会っている形しだい)."""
        return CUT_LEAVE.get(self.app.bonds.mode(cid), "go_home")
