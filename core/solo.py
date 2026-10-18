"""一人の時間 (誰とも一緒にいないとき / 同居していても「ちょっと一人になる」とき).

休む・家事・研鑽・散歩・買い物は「始めて, 戻るまで」. 過ごした時間で結果が決まる.
- 休む / 家事 / 研鑽: 在席状態は「作業中」(busy) と同じ扱い (家にいる)
- 散歩 / 買い物:     在席状態は「外出中」(out) と同じ扱い. 出かけている間 (画面を開いている間だけ) に偶然の出会いが起こりうる (補正はしない)
- 日記:              その場で書く. その日のログ (全キャラ + 一人の時間) から. LLM が有効なら LLM, 無ければ定型

一緒にいる相手がいれば, 既存の「ちょっと作業するね」「ちょっと出かけてくる」として声をかけ, 相手が反応する.
離れているなら, あなたの行動だけが記録される.
作業する・出かける・仕事に行く・寝る・席を外す (PLAIN) も同じ: そばに誰かいれば「〜してくるね」と告げ,
誰もいなければ告げる相手なしで, あなたの予定としてそうする. 一人の時間の記録と日記は data/worlds/<id>/mylog.json / diary.json.
"""
import random
import time
from datetime import date, datetime

from . import cond, llm, store

KINDS = {
    "rest": {"label": "休む", "icon": "🛋", "mode": "busy", "doing": "休憩中", "go": "go_busy"},
    "chores": {"label": "家事をする", "icon": "🧹", "mode": "busy", "doing": "家事中", "go": "go_busy"},
    "practice": {"label": "研鑽する", "icon": "📚", "mode": "busy", "doing": "研鑽中", "go": "go_busy"},
    "walk": {"label": "一人で散歩", "icon": "🚶", "mode": "out", "doing": "散歩中", "go": "go_out"},
    "shopping": {"label": "一人で買い物", "icon": "🛍", "mode": "out", "doing": "買い物中", "go": "go_out"},
}
# 告げる相手がいなくてもできる, あなたの予定 (そばに誰かいれば go_* として告げる)
PLAIN = {
    "busy": {"label": "作業する", "icon": "🖥", "mode": "busy", "go": "go_busy", "text": "作業を始めた"},
    "out": {"label": "出かける", "icon": "🚪", "mode": "out", "go": "go_out", "text": "出かけた"},
    "work": {"label": "仕事に行く", "icon": "💼", "mode": "work", "go": "go_work", "text": "仕事に出かけた"},
    "sleep": {"label": "寝る", "icon": "🌙", "mode": "sleep", "go": "go_sleep", "text": "寝ることにした"},
    "leave": {"label": "席を外す", "icon": "👋", "mode": "left", "go": "go_leave", "text": "席を外した"},
}
START_TEXT = {"rest": "ひと休みすることにした", "chores": "家事を始めた", "practice": "{skill}の練習を始めた",
              "walk": "一人で散歩に出た", "shopping": "一人で買い物に出た"}
OWN_ACTIONS = ("_back", "work", "_return")
SKILL_LABEL = {"talk": "会話", "touch": "スキンシップ", "cook": "料理", "work": "仕事"}
PRACTICE_TEXT = {"talk": "話し方の本を読んだ", "touch": "マッサージのやり方を調べた", "cook": "料理の練習をした",
                 "work": "仕事の勉強をした"}


class Solo:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 記録
    def mylog(self):
        return store.load(store.wpath("mylog.json"), []) or []

    def note(self, kind, text, now=None, **extra):
        log = self.mylog()
        e = {"t": now or time.time(), "kind": kind, "text": text}
        e.update(extra)
        log.append(e)
        store.save(store.wpath("mylog.json"), log[-500:])
        return e

    def current(self):
        p = self.app.presence.rec()
        return p.get("solo") if p.get("mode") in ("busy", "out") else None

    # ------------------------------------------------------------------ 始める
    def near(self):
        """いまそばにいる人 (同居して家にいる / 会っている). 選んでいるキャラを優先. いなければ None."""
        app = self.app
        cur = app.settings.get("active_character")
        cids = ([cur] if cur in app.chars else []) + [c for c in app.chars if c != cur]
        return next((c for c in cids if app.bonds.together(c)), None)

    def _plain_ok(self, go, cid):
        """告げる相手がいなくても, その予定の条件 (時刻・あなたの体力・在席) を満たすか."""
        app = self.app
        try:
            a = app.action(go)
        except KeyError:
            return False
        cid = cid or app.settings.get("active_character")
        char, st = app.char(cid), app.state(cid)
        ctx = app.context(char, st, datetime.now())
        if not app.bonds.together(cid):
            ctx["outing"] = False     # 相手の外出は関係ない (あなたの予定)
        return cond.check(a.get("when", ""), ctx)

    def _place(self, kind, place):
        from .outdoor import CHOICES
        ch = CHOICES.get(kind)
        if not ch:
            return None
        if place not in ch:
            raise ValueError("行き先を選んでください")
        return place

    def start(self, kind, skill=None, place=None):
        app = self.app
        if kind in PLAIN:
            return self.start_plain(kind, place)
        k = KINDS.get(kind)
        if not k:
            raise ValueError("一人でできることではありません: %s" % kind)
        if kind == "practice" and skill not in SKILL_LABEL:
            raise ValueError("何を練習するか選んでください")
        place = self._place(kind, place)
        p = app.presence.rec()
        if p.get("mode") not in ("none",) and app.presence.at(time.time()) not in ("here", "idle"):
            raise ValueError("いまは始められません（%s）" % app.presence.view(time.time())["label"])
        now = time.time()
        res = None
        cid = self.near()
        if cid:
            # 一緒にいる相手には声をかけていく (既存の「ちょっと作業するね」「ちょっと出かけてくる」と同じ)
            try:
                res = app.act(k["go"], cid)
            except ValueError:
                res = None
        if not res:
            app.presence.declare(k["mode"], now)
        p = app.presence.rec()
        p["solo"] = {"kind": kind, "skill": skill, "t": now}
        if place:
            p["place"] = place
        app.presence.save()
        self.note(kind, START_TEXT[kind].replace("{skill}", SKILL_LABEL.get(skill or "", "")), now)
        return {"started": kind, "label": k["doing"], "act": res}

    def start_plain(self, kind, place=None):
        """作業する・出かける・仕事に行く・寝る・席を外す. そばに誰かいれば告げて, いなければ一人で."""
        app = self.app
        k = PLAIN[kind]
        place = self._place(kind, place)
        cid = self.near()
        if cid:
            r = app.act(k["go"], cid)
            if place and app.presence.rec().get("mode") == "out":
                app.presence.rec()["place"] = place
                app.presence.save()
            return {"started": kind, "label": k["label"], "act": r}
        if not self._plain_ok(k["go"], None):
            raise ValueError("いまは「%s」できません（%s）" % (k["label"], app.action(k["go"]).get("when", "")))
        now = time.time()
        app.presence.declare(k["mode"], now)
        if place:
            app.presence.rec()["place"] = place
            app.presence.save()
        self.note(kind, k["text"], now)
        return {"started": kind, "label": k["label"], "act": None}

    # ------------------------------------------------------------------ 戻ったとき (come_back から)
    def finish(self, ll):
        """ll: presence.back() の結果. 一人の時間だったら結果を返す (なければ None)."""
        sl = ll.get("solo")
        if not sl:
            return None
        app, L = self.app, self.app.life
        kind, h = sl["kind"], max(0.0, float(ll.get("h", 0)))
        now = ll.get("back", time.time())
        jit = random.uniform(0.6, 1.2)          # 同じ時間でも, はかどる日とそうでない日がある
        out = {"kind": kind, "hours": round(h, 2)}
        if kind == "rest":
            text = "%s休んだ。少し体が軽くなった" % _dur(h)       # 回復は時間経過 (life.tick_world) で済んでいる
        elif kind == "chores":
            L.tire(4 * h)
            text = "%s家事をした。部屋がすっきりした" % _dur(h)
            live = app.bonds.living()
            if live and h >= 0.25 and random.random() < 0.6:     # 同居相手が気づくかどうかは偶然
                st = app.state(live)
                char = app.char(live)
                d = app.apply_effects(st, {"mood": round(min(4.0, 1.5 * h) * jit, 1), "stress": -round(min(5.0, 2 * h), 1)})
                L.add_reason(st, "player", "good", "%sが家事をしてくれた" % app.pronouns(char)[2], now, told=True,
                             delta=d.get("mood", 0), action="_chores")
                app.save_state(live)
                text += "。%sが気づいてくれたようだ" % char.get("name", "")
        elif kind == "practice":
            sk = sl.get("skill") or "talk"
            L.tire(3 * h)
            gain = L.train(sk, min(3.0, 1.2 * h) * jit) if h >= 0.25 else 0
            out["skill"] = {sk: gain}
            text = "%s%s。%sが%s" % (_dur(h), PRACTICE_TEXT[sk], SKILL_LABEL[sk], "少し伸びた" if gain >= 0.3 else
                                     "伸びた気はあまりしない")
        elif kind == "walk":
            L.tire(2 * h)
            text = "%s一人で散歩した" % _dur(h)
        else:   # shopping
            L.tire(2 * h)
            ps = L.player_state()
            spend = min(int(ps["money"]), int(random.randint(5, 40) * 100 * (0.5 + min(h, 3))))
            if spend > 0:
                ps["money"] -= spend
                L.save_player()
            out["money"] = -spend
            text = "%s一人で買い物をした（%s円）" % (_dur(h), format(spend, ","))
        out["text"] = "（%s）" % text
        self.note(kind, text, now, hours=round(h, 2))
        return out

    # ------------------------------------------------------------------ 日記
    def diary_list(self):
        return store.load(store.wpath("diary.json"), []) or []

    def write_diary(self, day=None):
        """その日の出来事から日記を書く. LLM が有効なら LLM, 無ければ定型でまとめる."""
        app = self.app
        day = day or date.today().isoformat()
        items = []
        for cid, char in app.chars.items():
            for e in app.log(cid):
                # 離れている相手のログに残る「あなたの行動だけ」の記録 (（戻ってきた）など) は, 一緒に過ごしたうちに入れない
                if e.get("text", "").startswith("（") and (e.get("action") in OWN_ACTIONS or e.get("action", "").startswith("go_")):
                    continue
                if datetime.fromtimestamp(e["t"]).date().isoformat() == day and e.get("text"):
                    items.append((e["t"], char.get("name", ""), e.get("action_name", ""), e["text"]))
        mine = [(e["t"], "", e["kind"], e["text"]) for e in self.mylog()
                if datetime.fromtimestamp(e["t"]).date().isoformat() == day and e.get("kind") != "diary"]
        items = sorted(items + mine)
        player = app.settings.get("player_name") or "あなた"
        text, src = None, "template"
        cfg = app.settings.get("llm") or {}
        if cfg.get("enabled") and items:
            lines = "\n".join("- %s %s%s: %s" % (datetime.fromtimestamp(t).strftime("%H:%M"), n + "／" if n else "", a, x)
                              for t, n, a, x in items[-40:])
            try:
                text = llm.chat(cfg, "あなたは%s。一日の終わりに、短い日記を一人称で書く。いいことも、うまくいかなかったことも、そのまま書く。" % player,
                                "%s の出来事:\n%s\n\n200字ほどの日記だけを返して。" % (day, lines))
                src = "llm" if text else "template"
            except Exception:  # noqa: BLE001 - LLM が使えなければ定型で
                text = None
        if not text:
            text = self._template(items)
        d = {"day": day, "t": time.time(), "text": text, "src": src}
        lst = [x for x in self.diary_list() if x["day"] != day] + [d]
        store.save(store.wpath("diary.json"), sorted(lst, key=lambda x: x["day"])[-365:])
        self.note("diary", "日記をつけた", d["t"])
        return d

    @staticmethod
    def _template(items):
        if not items:
            return "今日は特に何もなかった。静かな一日だった。"
        names = []
        for _, n, _, _ in items:
            if n and n not in names:
                names.append(n)
        mine = [x for _, n, _, x in items if not n]
        parts = []
        if names:
            parts.append("今日は%sと過ごした（記録 %d 件）。" % ("、".join(names), sum(1 for i in items if i[1])))
        else:
            parts.append("今日は一人で過ごした。")
        for t, n, a, x in [i for i in items if i[1]][-3:]:
            parts.append("%s %sの「%s」: %s" % (datetime.fromtimestamp(t).strftime("%H:%M"), n, a, x.replace("\n", " ")[:60]))
        if mine:
            parts.append("一人の時間: " + "／".join(m.replace("\n", " ")[:30] for m in mine[-4:]))
        return "\n".join(parts)

    def view(self):
        cur = self.current()
        near = self.near()
        plain = []
        for kid, k in PLAIN.items():
            try:
                go = self.app.action(k["go"])
            except KeyError:
                continue
            plain.append({"id": kid, "icon": k["icon"], "label": go.get("name", k["label"]) if near else k["label"],
                          "ok": self._plain_ok(k["go"], near)})
        return {"current": dict(cur, **{k: KINDS[cur["kind"]][k] for k in ("label", "icon", "doing")}) if cur else None,
                "near": {"cid": near, "name": self.app.chars[near].get("name", "")} if near else None, "plain": plain,
                "kinds": [{"id": k, "label": v["label"], "icon": v["icon"], "mode": v["mode"]} for k, v in KINDS.items()],
                "skills": SKILL_LABEL, "diary_today": any(d["day"] == date.today().isoformat() for d in self.diary_list())}


def _dur(h):
    m = int(round(h * 60))
    if m < 60:
        return "%d分ほど" % max(1, m)
    return "%d時間%s" % (m // 60, "%d分" % (m % 60) if m % 60 else "") + "ほど"
