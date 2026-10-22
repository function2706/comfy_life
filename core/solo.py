"""一人の時間 (誰とも一緒にいないとき / 同居していても「ちょっと一人になる」とき).

休む・家事・研鑽・外出は「始めて, 戻るまで」. 過ごした時間で結果が決まる.
- 休む / 家事 / 研鑽: 在席状態は「作業中」(busy) と同じ扱い (家にいる)
- 外出:             行き先 (core/places.py の表) を選ぶ. 行き先しだいですることが決まる (公園・河川敷ならぶらぶら歩く,
                    カフェならお茶, 店なら買い物, 水族館などは見て回る, 相手の家なら訪ねる). 在席状態は「外出中」(out).
                    出かけている間 (画面を開いている間だけ) に偶然の出会いが起こりうる (補正はしない)
                    以前の「一人で散歩・一人で買い物・カフェで過ごす」(walk / shopping / cafe) は, 外出 + 行き先に読み替える
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
from . import places as places_mod

KINDS = {
    "rest": {"label": "休む", "icon": "🛋", "mode": "busy", "doing": "休憩中", "go": "go_busy"},
    "chores": {"label": "家事をする", "icon": "🧹", "mode": "busy", "doing": "片付け中", "go": "go_busy"},
    "practice": {"label": "研鑽する", "icon": "📚", "mode": "busy", "doing": "研鑽中", "go": "go_busy"},
    "out": {"label": "外出", "icon": "🚶", "mode": "out", "doing": "外出中", "go": "go_out"},
}
# 以前の一人の外出 (行き先しだいの「外出」に吸収した). 戻ったときの結果の種類としては使う
LEGACY = {
    "walk": {"label": "一人で散歩", "icon": "🚶", "mode": "out", "doing": "散歩中", "go": "go_out"},
    "shopping": {"label": "一人で買い物", "icon": "🛍", "mode": "out", "doing": "買い物中", "go": "go_out"},
    "cafe": {"label": "カフェで過ごす", "icon": "☕", "mode": "out", "doing": "カフェで過ごし中", "go": "go_out"},
}
ALL_KINDS = dict(KINDS, **LEGACY)
# 外出は「何をしに出るか」で選ぶ (目的のない「出かける」は置かない). 同居相手がそばにいれば「ちょっと出かけてくる」と告げてから
# 告げる相手がいなくてもできる, あなたの予定 (そばに誰かいれば go_* として告げる)
PLAIN = {
    "busy": {"label": "作業する", "icon": "🖥", "mode": "busy", "go": "go_busy", "text": "作業を始めた"},
    "work": {"label": "仕事に行く", "icon": "💼", "mode": "work", "go": "go_work", "text": "仕事に出かけた"},
    "sleep": {"label": "寝る", "icon": "🌙", "mode": "sleep", "go": "go_sleep", "text": "寝ることにした"},
    "leave": {"label": "席を外す", "icon": "👋", "mode": "left", "go": "go_leave", "text": "席を外した"},
}
START_TEXT = {"rest": "ひと休みすることにした", "chores": "家事を始めた", "practice": "{skill}の練習を始めた",
              "walk": "一人で散歩に出た", "shopping": "一人で買い物に出た", "cafe": "一人でカフェに出かけた",
              "out": "{place}へ出かけた"}
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
    def near(self, cid=None):
        """告げる相手: いまそばにいる人 (家にいる同居相手 / 会っている / 来ている) のうち,「誰かと」で選んでいる相手.
        いなければ None (一人)."""
        return self.app.target(cid)

    def _plain_ok(self, go, cid):
        """告げる相手がいなくても, その予定の条件 (時刻・あなたの体力・在席) を満たすか."""
        app = self.app
        try:
            a = app.action(go)
        except KeyError:
            return False
        if not cid:                   # 告げる相手がいない: あなた一人の条件 (時刻・在席・体力)
            return cond.check(a.get("when", ""), app.you_context())
        char, st = app.char(cid), app.state(cid)
        return cond.check(a.get("when", ""), app.context(char, st, datetime.now()))

    def _place(self, kind, place):
        if kind != "out":
            return None
        if place not in self.app.places.out_choices():
            raise ValueError("行き先を選んでください")
        o = places_mod.open_state(place, datetime.now())
        if not o["open"]:
            raise ValueError("%sは閉まっています（%s）" % (self.app.places.label(place), o["note"]))
        return place

    def start(self, kind, skill=None, place=None, cid=None):
        """cid: 告げる相手 (そばにいる人の中から. 無ければ「誰かと」で選んでいる相手)."""
        app = self.app
        if kind in PLAIN:
            return self.start_plain(kind, place, cid)
        if kind == "kakeibo":
            return self.kakeibo()
        if kind in LEGACY:              # 以前の「散歩・買い物・カフェ」: 外出 + 行き先
            place = place or places_mod.LEGACY_DO[kind]
            kind = "out"
        if kind == "out" and places_mod.is_home(place):      # 相手の家を訪ねる
            self._place(kind, place)
            return app.drop_in(places_mod.home_of(place))
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
        cid = self.near(cid)
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
        self.note(kind, START_TEXT[kind].replace("{skill}", SKILL_LABEL.get(skill or "", ""))
                  .replace("{place}", app.places.label(place) if place else ""), now)
        return {"started": kind, "label": k["doing"], "act": res}

    def kakeibo(self, now=None):
        """家事の「家計簿をつける」(15 分ほど. その場で済む): 前につけたときから今までの出入りを書き込む (日を空けるほど, うろ覚え)."""
        app = self.app
        now = now or time.time()
        p = app.presence.rec()
        if p.get("mode") not in ("none", "busy") or app.outdoor.current(now) or                 ((app.bonds.with_rec() or {}).get("mode") in ("meet", "visit")):
            raise ValueError("家計簿は家でつけます")
        r = app.kakeibo.write(now)
        app.life.tire(1)
        self.note("kakeibo", r["text"], now, id="k%d" % int(now * 1000), icon="📒", name="家計簿")
        return {"started": None, "label": "家計簿", "done": r["text"], "kakeibo": r}

    def start_plain(self, kind, place=None, cid=None):
        """作業する・出かける・仕事に行く・寝る・席を外す. そばに誰かいれば告げて, いなければ一人で."""
        app = self.app
        k = PLAIN[kind]
        if kind == "busy" and not app.bonds.living():
            raise ValueError("一人暮らしでは「作業する」はありません（同居している相手に、作業中と伝えるためのものです）")
        place = self._place(kind, place)
        cid = self.near(cid)
        if kind == "leave" and not cid:
            raise ValueError("一人のときは「席を外す」はありません（そばにいる相手に告げて離れるためのものです。一人なら画面を閉じれば、オフライン時の過ごし方どおりに過ごします）")
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
        return self.result(sl["kind"], max(0.0, float(ll.get("h", 0))), ll.get("back", time.time()), sl.get("skill"), ll.get("place"),
                           ate=bool(sl.get("ate")))

    def result(self, kind, h, now, skill=None, place=None, ate=False):
        """一人の時間を h 時間過ごした結果 (画面を開いての一人の時間と, オフラインの行動パターンの両方で使う)."""
        app, L = self.app, self.app.life
        jit = random.uniform(0.6, 1.2)          # 同じ時間でも, はかどる日とそうでない日がある
        note_kind = kind
        if kind == "out":                       # 外出: 行き先しだいで, したことが決まる
            place = place if place in places_mod.PLACES else "town"
            kind = places_mod.solo_kind(place)
        elif kind in LEGACY:
            place = place or places_mod.LEGACY_DO[kind]
        where = places_mod.PLACES.get(place, {}).get("label", "") if place else ""
        out = {"kind": kind, "hours": round(h, 2), "place": place}
        if kind == "rest":
            text = "%s休んだ。少し体が軽くなった" % _dur(h)       # 回復は時間経過 (life.tick_world) で済んでいる
        elif kind == "chores":
            L.tire(4 * h)
            soap = app.items.use_kind("detergent")              # 洗剤があるとはかどる
            how = app.home.chores(h, soap, jit)                 # 家が片付く (たまっているものほど)
            text = "%s家事をした。%s（%s）" % (_dur(h), "部屋がすっきりした" if soap else "洗剤が切れていて、思うようにははかどらなかった", how)
            text += app.home.notice_chores(h, soap, now, jit)      # 同居相手が気づくかどうかは偶然
        elif kind == "practice":
            sk = skill or "talk"
            L.tire(3 * h)
            from .items import PRACTICE_BOOK
            book = app.items.count(PRACTICE_BOOK[sk]) > 0           # その分野の本・教材があると伸びやすい (減らない)
            gain = L.train(sk, min(3.0, 1.2 * h) * jit * (1.5 if book else 1.0)) if h >= 0.25 else 0
            out["skill"] = {sk: gain}
            text = "%s%s%s。%sが%s" % (_dur(h), "本を見ながら" if book else "", PRACTICE_TEXT[sk], SKILL_LABEL[sk],
                                       "少し伸びた" if gain >= 0.1 else "伸びた気はあまりしない")
        elif kind == "walk":
            L.tire(2 * h)
            text = "%s%s一人でぶらぶらした" % (_dur(h), where + "を" if where else "")
        elif kind == "eat":                     # 食べに行った: そこで食べていなければ, 帰る前に何か食べる
            L.tire(1 * h)
            if ate:
                text = "%s%sで食事をした" % (_dur(h), where)
            else:
                menu = [m for m in app.body.menu(place, now) if m["price"] <= L.player_state()["money"]]
                if menu:
                    r = app.body.eat_at(min(menu, key=lambda m: m["price"])["id"], place, now, log=False)
                    text = "%s%sで%s" % (_dur(h), where, r["text"])
                    out["money"] = -r["price"]
                else:
                    text = "%s%sに行ったが、何も食べなかった" % (_dur(h), where)
        elif kind == "see":
            L.tire(2 * h)
            ps = L.player_state()
            fee = min(int(ps["money"]), int(places_mod.PLACES[place].get("fee", 0)))
            if fee > 0:
                ps["money"] -= fee
                L.ledger(now, -fee, "fun", "%sの入場料" % where)
                L.save_player()
            out["money"] = -fee
            text = "%s一人で%sを見て回った（%s円）" % (_dur(h), where, format(fee, ",")) if fee else "%s一人で%sを見て回った" % (_dur(h), where)
        elif kind == "cafe":
            ps = L.player_state()
            spend = min(int(ps["money"]), int(random.randint(5, 12) * 100 * (1 + min(h, 3) * 0.3)))
            if spend > 0:
                ps["money"] -= spend
                L.ledger(now, -spend, "eatout", "カフェ")
                L.save_player()
            bought, missed = app.items.shop(place or "cafe", h, now)       # 買うものリストの品がカフェにあれば
            out["money"] = -spend - sum(b["price"] for b in bought)
            out["bought"] = bought
            text = "%s一人でカフェで過ごした（%s円）。少し気分が落ち着いた" % (_dur(h), format(spend, ","))
            if bought or missed:
                text += "。" + app.items.describe(bought, missed)
        else:   # shopping
            L.tire(2 * h)
            # 買うものリストの品が, この店にあれば買う (品切れ・値段の上下・お金しだい. 衝動買いも少し)
            bought, missed = app.items.shop(place or "shopping_street", h, now)
            out["money"] = -sum(b["price"] for b in bought)
            out["bought"] = bought
            text = "%s%s一人で買い物をした。%s" % (_dur(h), where + "で" if where else "",
                                                app.items.describe(bought, missed) or "買うものリストの品は見つからず、何も買わなかった")
        out["text"] = "（%s）" % text
        self.note(note_kind, text, now, hours=round(h, 2), place=place)
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
            if kid == "busy" and not self.app.bonds.living():
                continue              # 一人暮らしでは「作業する」はいらない (同居相手に遠慮してもらうためのもの)
            if kid == "leave" and not near:
                continue              # 「席を外す」はそばにいる相手に「またね」と告げて離れるためのもの. 一人なら画面を閉じればよい
            try:
                go = self.app.action(k["go"])
            except KeyError:
                continue
            plain.append({"id": kid, "icon": k["icon"], "label": go.get("name", k["label"]) if near else k["label"],
                          "ok": self._plain_ok(k["go"], near)})
        return {"current": dict(cur, **{k: ALL_KINDS.get(cur["kind"], KINDS["out"])[k] for k in ("label", "icon", "doing")}) if cur else None,
                "near": {"cid": near, "name": self.app.chars[near].get("name", "")} if near else None, "plain": plain,
                "kinds": [{"id": k, "label": v["label"], "icon": v["icon"], "mode": v["mode"]} for k, v in KINDS.items()],
                "skills": SKILL_LABEL, "diary_today": any(d["day"] == date.today().isoformat() for d in self.diary_list())}


def _dur(h):
    m = int(round(h * 60))
    if m < 60:
        return "%d分ほど" % max(1, m)
    return "%d時間%s" % (m // 60, "%d分" % (m % 60) if m % 60 else "") + "ほど"
