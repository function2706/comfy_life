"""一人の時間 (誰とも一緒にいないとき / 同居していても「ちょっと一人になる」とき).

休む・家事・研鑽・外出は「始めて, 戻るまで」. 過ごした時間で結果が決まる.
- 休む / 家事 / 研鑽: 在席状態は「作業中」(busy) と同じ扱い (家にいる)
- 外出:             行き先 (core/places.py の表) を選ぶ. 行き先しだいですることが決まる (公園・河川敷ならぶらぶら歩く,
                    カフェならお茶, 店なら買い物, 水族館などは見て回る, 相手の家なら訪ねる). 在席状態は「外出中」(out).
                    店では, しばらくいると (品を選び終えたら) その場で買い物が済み, 済んだことが分かる (shop_tick).
                    済む前に店を出れば「まだ買い物の途中だった」. 済んだあともその場にいてよい. 行動パターンの買い物は今どおりまとめて
                    出かけている間 (画面を開いている間だけ) に偶然の出会いが起こりうる (補正はしない)
                    以前の「一人で散歩・一人で買い物・カフェで過ごす」(walk / shopping / cafe) は, 外出 + 行き先に読み替える
- 日記:              その場で書く. その日のログ (全キャラ + 一人の時間) から. LLM が有効なら LLM, 無ければ定型

一緒にいる相手がいれば, 既存の「ちょっと作業するね」「ちょっと出かけてくる」として声をかけ, 相手が反応する.
離れているなら, あなたの行動だけが記録される.
作業する・出かける・仕事に行く・寝る・席を外す (PLAIN) も同じ: そばに誰かいれば「〜してくるね」と告げ,
誰もいなければ告げる相手なしで, あなたの予定としてそうする. 一人の時間の記録と日記は data/worlds/<id>/mylog.json / diary.json.
"""
import math
import random
import re
import time
from datetime import date, datetime, timedelta

from . import cond, llm, store
from . import geo as geo_mod
from . import places as places_mod
from .home import PART_LABEL

KINDS = {
    "rest": {"label": "休む", "icon": "🛋", "mode": "busy", "doing": "休憩中", "go": "go_busy"},
    "chores": {"label": "家事をする", "icon": "🧹", "mode": "busy", "doing": "片付け中", "go": "go_busy"},
    "practice": {"label": "研鑽する", "icon": "📚", "mode": "busy", "doing": "研鑽中", "go": "go_busy"},
    "out": {"label": "外出", "icon": "🚶", "mode": "out", "doing": "外出中", "go": "go_out"},
    "jog": {"label": "ジョギング", "icon": "🏃", "mode": "out", "doing": "ジョギング中", "go": "go_out"},
    "read": {"label": "本を読む", "icon": "📖", "mode": "busy", "doing": "読書中", "go": "go_busy"},
    "movie": {"label": "映画を観る", "icon": "🎬", "mode": "busy", "doing": "映画を観ている", "go": "go_busy"},
}
# 店で買い物を済ませる時間 (分): 店ごとの, 見て回るふだんの長さ (中央値)・揺れ (長いほうに裾がある. 本屋・モールは長居しがち)・
# リストの品 1 つあたり (その店に売っているものだけ). コンビニに 15 分いることはまず無く, モールは 30 分ほどいることが多い
SHOP_BASE = {"convenience": (3, 0.3, 0.5), "station": (3, 0.3, 0.5), "drugstore": (7, 0.35, 0.8), "bookstore": (10, 0.5, 0.8),
             "supermarket": (10, 0.3, 0.9), "shopping_street": (15, 0.4, 1.0), "electronics": (20, 0.45, 1.0), "mall": (25, 0.45, 1.0),
             "car_dealer": (45, 0.35, 1.0)}
READ_H, MOVIE_H = 1.5, 2.0      # 読み終える・観終わるのにかかる時間 (合計. 途中でやめても続きから. core/topics.py)
JOG_PLACES = ("park", "riverside", "town")       # 走れる行き先
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
              "out": "{place}へ出かけた", "jog": "{place}へ走りに出た", "read": "本を読み始めた", "movie": "家で映画を観始めた"}
OWN_ACTIONS = ("_back", "work", "_return")
SKILL_LABEL = {"talk": "会話", "touch": "スキンシップ", "cook": "料理", "work": "仕事",
               "house": "家事", "care": "気配り", "groom": "身だしなみ", "budget": "やりくり", "write": "文章"}
PRACTICE_TEXT = {"talk": "話し方の本を読んだ", "touch": "マッサージのやり方を調べた", "cook": "料理の練習をした",
                 "work": "仕事の勉強をした",
                 "house": "家事の段取りを考えた", "care": "人の気持ちについての本を読んだ", "groom": "身だしなみを整える練習をした",
                 "budget": "家計の組み立て方を調べた", "write": "文章を書く練習をした"}


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
        if kind == "jog":
            if place not in JOG_PLACES:
                raise ValueError("どこを走るか選んでください")
            return place
        if kind != "out":
            return None
        if place not in self.app.places.out_choices():
            raise ValueError("行き先を選んでください")
        o = places_mod.open_state(place, datetime.now())
        if not o["open"]:
            raise ValueError("%sは閉まっています（%s）" % (self.app.places.label(place), o["note"]))
        return place

    def start(self, kind, skill=None, place=None, cid=None, how=None, frm=None):
        """cid: 告げる相手 (そばにいる人の中から. 無ければ「誰かと」で選んでいる相手).
        how: 行き方 (walk / transit. 無ければおまかせ). frm: 出るところ (出先から移るとき. 無ければいまいる場所)."""
        app = self.app
        frm = frm or app.geo.where()
        why = app.blocked("solo")
        if why:
            raise ValueError(why)
        if kind in ("out", "jog", "work") or kind in LEGACY:      # 家を出る (内職を一時停止したままなら, 先に終える)
            if app.stay_home():
                raise ValueError(app.stay_home())
        if kind in PLAIN:
            return self.start_plain(kind, place, cid, how=how)
        if kind == "kakeibo":
            return self.kakeibo()
        if kind == "read" and app.items.count("novel") <= 0 and not app.life.player_state().get("reading"):
            raise ValueError("読む本がない（小説は本屋や駅前などで買えます）")
        if kind in LEGACY:              # 以前の「散歩・買い物・カフェ」: 外出 + 行き先
            place = place or places_mod.LEGACY_DO[kind]
            kind = "out"
        if kind == "out" and places_mod.is_home(place):      # 相手の家を訪ねる
            self._place(kind, place)
            if frm != place:                                  # まず相手の家まで移動する (着いたら arrive_then)
                now = time.time()
                app.presence.declare("out", now)
                pr = app.presence.rec()
                pr["solo"] = {"kind": "out", "skill": None, "t": now}
                pr["place"] = place
                tr = app.geo.depart(place, how, now, then="visit", frm=frm)
                if tr:
                    text = "%sへ向かった（%sで%d分ほど）" % (app.places.label(place), geo_mod.HOW_LABEL[tr["how"]],
                                                     max(1, round((tr["arr"] - now) / 60)))
                    self.note("out", text, now)
                    return {"started": "out", "label": "%sへ移動中" % app.places.label(place), "act": None, "done": "（%s）" % text}
                return self.arrive_then("visit", place, now)          # 移動がいらなかった (すぐ着いた)
            return self._at_home_of(place)
        return self._start(kind, skill, place, cid, how, frm)

    def arrive_then(self, then, place, t):
        """移動して着いたときにすること (core/geo.py の tick から). 相手の家なら, 着いてから訪ねる."""
        if then == "visit":
            p = self.app.presence.rec()
            p["mode"] = "none"                 # 玄関先に着いた (訪ねる処理は家を出るところから)
            p.pop("solo", None)
            return self._at_home_of(place, t)
        return None

    def _at_home_of(self, place, now=None):
        """相手の家に着いた: 植木の水やり / 約束の訪問 (玄関先で待つ) / 約束なしの訪問."""
        app = self.app
        if True:
            done = app.appoint.water_plants(place, now)       # 留守中の植木の水やり (会わない. 鍵を預かっている)
            if done:
                now = now or time.time()
                app.presence.declare("out", now)
                pr = app.presence.rec()
                pr["solo"] = {"kind": "out", "skill": None, "t": now}
                pr["place"] = place
                app.presence.save()
                app.solo.note("out", done.strip("（）"), now)
                return {"started": "out", "label": "%sへ" % app.places.label(place), "act": None, "done": done}
            if app.appoint.due_at(place, now):                # 約束の訪問: 玄関先で約束の時刻を待つ
                return app.appoint.arrive_home_of(place, now)
            return app.drop_in(places_mod.home_of(place), now)

    def _start(self, kind, skill, place, cid, how, frm):
        app = self.app
        k = KINDS.get(kind)
        if not k:
            raise ValueError("一人でできることではありません: %s" % kind)
        if kind == "practice" and str(skill or "").startswith("qual:"):
            from .quals import QUALS
            if skill[5:] not in QUALS or app.quals.has(skill[5:]):
                raise ValueError("その資格の勉強はできません")
            if QUALS[skill[5:]].get("place"):
                raise ValueError("%sは家では勉強できません（%sに通う）" % (QUALS[skill[5:]]["label"], app.places.label(QUALS[skill[5:]]["place"])))
        elif kind == "practice" and skill not in SKILL_LABEL:
            raise ValueError("何を練習するか選んでください")
        if kind == "chores" and skill and skill not in PART_LABEL:
            raise ValueError("何を片付けるか選んでください")
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
            if not places_mod.is_home(place) and places_mod.solo_kind(place) == "shopping":    # 店: 品を選び終えるまでの時間
                p["solo"]["shop_need"] = round(self.shop_minutes(place, now), 1)
        app.presence.save()
        tr = app.geo.depart(place, "run" if kind == "jog" else how, now, frm=frm) if place else None
        if k["mode"] == "out":
            app.life.train("groom", 0.15)           # 出かける前に整える
        self.note(kind, ("資格の勉強を始めた" if str(skill or "").startswith("qual:") else START_TEXT[kind]).replace("{skill}", SKILL_LABEL.get(skill or "", ""))
                  .replace("{place}", app.places.label(place) if place else ""), now)
        if tr:
            mins = max(1, round((tr["arr"] - now) / 60))
            return {"started": kind, "label": "%sへ移動中" % app.places.label(place), "act": res, "travel": app.geo.view(now),
                    "done": None if res else "（%sへ向かった。%sで%d分ほど%s）" % (
                        app.places.label(place), geo_mod.HOW_LABEL[tr["how"]], mins, "・%s円" % format(tr["fare"], ",") if tr["fare"] else "")}
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

    # ------------------------------------------------------------------ 店での買い物 (画面を開いている外出)
    def _shop_items_here(self, place):
        from .items import CATALOG
        return sum(1 for i in self.app.items.ps()["shop_list"] if place in (CATALOG.get(i) or {}).get("places", []))

    def shop_minutes(self, place, now=None):
        """店に着いてから買い物を済ませるまでの時間 (分): 店ごとの見て回る長さ (ふだんの長さのまわりに揺れる. 長居することも) +
        その店に売っているリストの品の数 + レジ (混む時間は長め). 売っていない品は数えない."""
        med, sigma, per = SHOP_BASE.get(place, (6, 0.35, 0.8))
        crowd = 1.0
        pl = places_mod.PLACES.get(place)
        if pl:
            crowd = float(pl["crowd"].get(self.app.phase_at(datetime.fromtimestamp(now or time.time())).get("id", "noon"), 1.0))
        return min(random.lognormvariate(math.log(med), sigma), 3 * med) + per * random.uniform(0.8, 1.2) * min(self._shop_items_here(place), 15)             + random.uniform(0.5, 2.0) * max(0.5, crowd)

    def shop_typical(self, place):
        """その店でのふだんの買い物の長さ (分. 揺れなし): 閉じていた間に「切り上げた」かを見る目安."""
        med, _, per = SHOP_BASE.get(place, (6, 0.35, 0.8))
        return med + per * min(self._shop_items_here(place), 15) + 1.2

    def shop_tick(self, now=None):
        """店に出かけていて, 品を選び終える時間がたったら, その場で買い物を済ませる (心拍のたび). 済んだら結果を返す."""
        app = self.app
        now = now or time.time()
        p = app.presence.rec()
        sl = p.get("solo") or {}
        place = p.get("place")
        if p.get("mode") != "out" or sl.get("kind") != "out" or sl.get("shop_done") \
                or places_mod.is_home(place or "") or places_mod.solo_kind(place) != "shopping" or p.get("travel"):
            return None
        need = sl.setdefault("shop_need", round(self.shop_minutes(place, now), 1))
        t_at = p.get("arrived", sl.get("t", now))          # 店に着いてから
        if now - t_at < need * 60:
            return None
        res = self._shop_now(place, (now - t_at) / 3600.0, now)
        sl["shop_done"] = res
        app.presence.save()
        self.note("shopping", "%sで買い物を終えた。%s" % (res["label"], res["text"]), now, place=place)
        return res

    def _shop_now(self, place, h, now):
        """店で買い物を済ませる. 買うものがなかったとき (リストが空・この店に売っていない・全部品切れ) も, そうと分かる結果に."""
        from .items import CATALOG
        app = self.app
        want = dict(app.items.ps()["shop_list"])
        here = [i for i in want if place in (CATALOG.get(i) or {}).get("places", [])]
        bought, missed = app.items.shop(place, h, now)
        listed = [b for b in bought if not b.get("impulse")]
        nothing = None
        if not listed:
            if not want:
                nothing = "買うものリストは空だった"
            elif not here:
                nothing = "リストの品（%s）は、この店には売っていなかった" % "、".join(CATALOG[i]["name"] for i in want if i in CATALOG)
            else:
                nothing = "リストの品は、品切れやお金が足りなくて買えなかった"
        text = app.items.describe(bought, missed)
        if nothing:
            text = "この店で買うものはなかった（%s）" % nothing + ("。" + text if text else "")
        elsewhere = [CATALOG[i]["name"] for i in want if i in CATALOG and i not in here] if listed or here else []
        return {"t": now, "place": place, "label": app.places.label(place), "bought": bought, "missed": missed,
                "total": sum(b["price"] for b in bought), "nothing": nothing, "text": text, "seen": False,
                "elsewhere": elsewhere}

    def shop_ack(self):
        """買い物を終えた知らせを読んだ (閉じる)."""
        sl = self.app.presence.rec().get("solo") or {}
        if sl.get("shop_done"):
            sl["shop_done"]["seen"] = True
            self.app.presence.save()
        return {"ok": True}

    def move(self, place, now=None, how=None):
        """出かけている先から, ほかの行き先へ (いまの外出の結果を出して, そのまま出かける. 場所どうしの距離の移動)."""
        app = self.app
        now = now or time.time()
        p = app.presence.rec()
        if p.get("mode") != "out":
            raise ValueError("いまは出かけていません")
        if app.stay_home():
            raise ValueError(app.stay_home())
        self._place("out", place)
        frm = app.geo.where(now)
        if p.get("travel"):                    # 向かう途中・帰る途中で行き先を変える: いまの地点から
            frm = app.geo.cut(now)
        ll = app.presence.back(now)
        res = self.finish(ll) if ll else None
        r = self.start("out", place=place, how=how, frm=frm)
        r["solo"] = res
        return r

    def start_plain(self, kind, place=None, cid=None, how=None, dest=None):
        """作業する・出かける・仕事に行く・寝る・席を外す. そばに誰かいれば告げて, いなければ一人で.
        仕事は職場 (dest: アルバイト先など) まで通う (core/geo.py)."""
        app = self.app
        k = PLAIN[kind]
        frm = app.geo.where()
        if kind == "busy" and not app.bonds.living():
            raise ValueError("一人暮らしでは「作業する」はありません（同居している相手に、作業中と伝えるためのものです）")
        place = self._place(kind, place)
        if kind == "work" and app.body.level() >= 3:
            raise ValueError("寝込むほどつらくて、仕事に行けそうにない（休むか、病院へ）")
        cid = self.near(cid)
        if kind == "leave" and not cid:
            raise ValueError("一人のときは「席を外す」はありません（そばにいる相手に告げて離れるためのものです。一人なら画面を閉じれば、オフライン時の過ごし方どおりに過ごします）")
        if cid:
            r = app.act(k["go"], cid)
            if place and app.presence.rec().get("mode") == "out":
                app.presence.rec()["place"] = place
                app.presence.save()
            if kind == "work" and app.presence.rec().get("mode") == "work":
                app.geo.depart(dest or "office", how, frm=frm)
            return {"started": kind, "label": k["label"], "act": r}
        if not self._plain_ok(k["go"], None):
            raise ValueError("いまは「%s」できません（%s）" % (k["label"], app.action(k["go"]).get("when", "")))
        now = time.time()
        app.presence.declare(k["mode"], now)
        if place:
            app.presence.rec()["place"] = place
            app.presence.save()
        tr = app.geo.depart(dest or "office", how, now, frm=frm) if kind == "work" else None
        self.note(kind, k["text"], now)
        if tr:
            return {"started": kind, "label": k["label"], "act": None, "travel": app.geo.view(now),
                    "done": "（%sへ向かった。%sで%d分ほど）" % ("職場" if not dest else app.places.label(dest), geo_mod.HOW_LABEL[tr["how"]],
                                                       max(1, round((tr["arr"] - now) / 60)))}
        return {"started": kind, "label": k["label"], "act": None}

    # ------------------------------------------------------------------ 戻ったとき (come_back から)
    def finish(self, ll):
        """ll: presence.back() の結果. 一人の時間だったら結果を返す (なければ None)."""
        sl = ll.get("solo")
        if not sl or sl.get("parted"):          # 別れて家へ帰ってきただけ (core/bonds.py)
            return None
        h = max(0.0, float(ll.get("h_at", ll.get("h", 0))))     # その場所にいた時間 (移動の時間は入れない)
        shop = sl.get("shop_done")
        if not shop and sl.get("shop_need") and h * 60 >= sl["shop_need"]:
            # 品を選び終える時間は店にいた (心拍の間に済んでいた / 画面を閉じた時点で済んでいた): そこで買い物は済んでいる
            shop = self._shop_now(ll.get("place"), h, ll.get("back", time.time()))
        return self.result(sl["kind"], h, ll.get("back", time.time()), sl.get("skill"), ll.get("place"),
                           ate=bool(sl.get("ate")), shop=shop or "pending")

    def result(self, kind, h, now, skill=None, place=None, ate=False, shop=None):
        """shop: 店での買い物の済み具合 (画面を開いての外出から). None = その場で買う (行動パターン) / "pending" = 済む前に店を出た /
        辞書 = 店にいる間に済んだ結果 (shop_tick)."""
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
        elif kind == "read":                    # 小説を読む (読みかけは続きから. 読み終えると話題に. 開いた本は使う)
            try:
                text = "%s%s" % (_dur(h), app.topics.read(h, now, READ_H))
            except ValueError as e:
                text = str(e)
        elif kind == "movie":                   # 家で映画を観る (配信. 観かけは続きから. 観終えると話題に)
            text = "%s%s" % (_dur(h), app.topics.watch(h, now, MOVIE_H))
        elif kind == "chores":
            L.tire(4 * h)
            soap = app.items.use_kind("detergent")              # 洗剤があるとはかどる
            part = skill if skill in PART_LABEL else None        # 一つだけ (洗い物・洗濯など) なら, そこだけ
            how = app.home.chores(h, soap, jit * (0.85 + 0.35 * L.skill_soft("house")), part, now)   # 家が片付く (家事スキルで少しはかどる)
            app.chores.did_mine(part, h, now)              # 同居の分担: あなたの担当を片付けた / 相手の担当を代わりにやった
            L.train("house", min(2.0, 0.8 * h)) if h >= 0.25 else 0
            text = "%s家事をした。%s（%s）" % (_dur(h), "部屋がすっきりした" if soap else "洗剤が切れていて、思うようにははかどらなかった", how)
            text += app.home.notice_chores(h, soap, now, jit)      # 同居相手が気づくかどうかは偶然
        elif kind == "practice" and str(skill or "").startswith("qual:"):      # 資格の勉強
            L.tire(3 * h)
            text, gain = app.quals.study(skill[5:], h * jit)
            out["skill"] = gain
            text = "%s%s" % (_dur(h), text)
        elif kind == "practice":
            sk = skill or "talk"
            L.tire(3 * h)
            from .items import PRACTICE_BOOK
            book = app.items.count(PRACTICE_BOOK[sk]) > 0           # その分野の本・教材があると伸びやすい (減らない)
            gain = L.train(sk, min(3.0, 1.2 * h) * jit * (1.5 if book else 1.0)) if h >= 0.25 else 0
            out["skill"] = {sk: gain}
            text = "%s%s%s。%sが%s" % (_dur(h), "本を見ながら" if book else "", PRACTICE_TEXT[sk], SKILL_LABEL[sk],
                                       "少し伸びた" if gain >= 0.1 else "伸びた気はあまりしない")
        elif kind == "jog":
            L.tire(min(40.0, 8 * h))                 # 走るのは疲れる (体は動かした: body.step)
            text = "%s%sを走った。%s" % (_dur(h), where, "息が上がったけれど、すっきりした" if h < 1.5 else "走りすぎて、へとへとだ")
            text += self._wet(place, h, now)
        elif kind == "walk":
            ef = places_mod.effort(place)            # 山道・砂浜は, 同じ時間でも疲れる (運動にもなる: body.step)
            L.tire(2 * h * ef)
            text = "%s%s一人で%s" % (_dur(h), where + "を" if where else "",
                                   "歩いた。足が重い" if ef >= 1.8 and h >= 1 else "ぶらぶらした")
            text += self._wet(place, h, now)
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
        elif kind == "learn":                   # 教習所: 入校していれば教習を受ける (免許の勉強時間)
            if app.quals.enrolled("drive"):
                L.tire(3 * h)
                text, gain = app.quals.study("drive", h * jit)
                out["skill"] = gain
                text = "%s%sで教習を受けた（%s）" % (_dur(h), where, text.split("（", 1)[-1].rstrip("）"))
            elif app.quals.has("drive"):
                text = "%s%sに寄った（もう免許は持っている）" % (_dur(h), where)
            else:
                text = "%s%sで入校の案内を聞いた（入校は資格の欄から申し込む）" % (_dur(h), where)
        elif kind == "clinic":                  # 病院で診てもらう
            r = app.body.clinic(now)
            out["money"] = r["money"]
            text = "%s%s" % (_dur(h), r["text"])
        elif kind == "see":
            L.tire(2 * h * places_mod.effort(place))      # 遊園地は歩き回って並ぶ
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
            ps["stamina"] = min(app.body.stamina_cap(), float(ps.get("stamina", 100)) + 3 * min(h, 3))    # 座って一息: 休むのと同じくらい戻る
            text = "%s一人でカフェで過ごした（%s円）。座って一息ついて、少し疲れがとれた" % (_dur(h), format(spend, ","))
            if bought or missed:
                text += "。" + app.items.describe(bought, missed)
        elif shop == "pending":     # 品を選び終える前に店を出た
            L.tire(2 * h)
            out["money"] = 0
            out["bought"] = []
            out["shop_pending"] = True
            text = "%s%sにいたが、まだ買い物の途中だった（何も買わずに出た）" % (_dur(h), where)
        elif isinstance(shop, dict):    # 店にいる間に買い物が済んでいた
            L.tire(2 * h)
            out["money"] = -shop["total"]
            out["bought"] = shop["bought"]
            text = "%s%s一人で買い物をした。%s" % (_dur(h), where + "で" if where else "", shop["text"])
        else:   # shopping (行動パターン: その場で買う)
            L.tire(2 * h)
            # 買うものリストの品が, この店にあれば買う (品切れ・値段の上下・お金しだい. 衝動買いも少し)
            bought, missed = app.items.shop(place or "shopping_street", h, now)
            out["money"] = -sum(b["price"] for b in bought)
            out["bought"] = bought
            text = "%s%s一人で買い物をした。%s" % (_dur(h), where + "で" if where else "",
                                                app.items.describe(bought, missed) or "買うものリストの品は見つからず、何も買わなかった")
        out["text"] = "（%s）" % text
        self.note(note_kind, text, now, hours=round(h, 2), place=place)
        try:
            app.topics.from_solo(note_kind, kind, place, h, now)     # 出かけた先・走った先は話題になる
        except Exception:  # noqa: BLE001 - 話題が残せなくても一人の時間は済んでいる
            pass
        return out

    def _wet(self, place, h, now):
        """雨・雪の日に外 (屋外の行き先) で過ごした: 体が冷えて, その日は体調を崩しやすい (body.risk). 添える一文."""
        from .outdoor import weather
        pl = places_mod.PLACES.get(place or "") or {}
        w = weather(datetime.fromtimestamp(now - h * 1800))
        if not pl.get("outdoor") or w["id"] not in ("rain", "snow") or h < 0.25:
            return ""
        self.app.body.add_wet(h)
        self.app.life.tire(1 * h)
        return "。%sに濡れて、体が冷えた" % w["label"]

    # ------------------------------------------------------------------ 日記
    def diary_list(self):
        return store.load(store.wpath("diary.json"), []) or []

    # 始めたときの一行 (「料理の練習を始めた」「仕事に出かけた」など). 結果の一行が別に残るので, 日記には出さない
    _START = re.compile("^(%s)$" % "|".join(
        [re.escape(x).replace(re.escape("{skill}"), ".+?").replace(re.escape("{place}"), ".+?") for x in START_TEXT.values()]
        + [re.escape(k["text"]) for k in PLAIN.values()]))
    SKIP_KINDS = ("diary", "offline", "plan")

    def day_mine(self, day):
        """その日の一人の時間の記録 [(時刻, 一行)] (日記のもと). 始めたときの一行・同じ一行の重複 (結果と「戻る」) ・
        仕事に置き換えた記録は除き, 閉じていた間のまとめは行動ごとに, それぞれの日へ振り分ける."""
        from .offline import parse_summary
        out = []
        d0 = datetime.strptime(day, "%Y-%m-%d")
        d1 = d0 + timedelta(days=1)
        for e in self.mylog():
            if e.get("kind") == "offline":       # 戻った日の記録だが, 中身はそれぞれの日の出来事
                voids = e.get("void_parts") or []
                for p in parse_summary(e):
                    if d0.timestamp() <= p["s"] < d1.timestamp() and not any(a <= p["s"] < b for a, b in voids):
                        out.append((p["s"], p["text"]))
                continue
            if e.get("kind") in self.SKIP_KINDS or e.get("void") or not (d0.timestamp() <= e["t"] < d1.timestamp()):
                continue
            text = (e.get("text") or "").strip()
            if not text or self._START.match(text):
                continue
            out.append((e["t"], text))
        out.sort()
        res = []
        for t, x in out:                         # 同じ出来事の重複 (一方がもう一方の書き出し) は, 長いほうを一つだけ
            k = x.strip("（）")
            hit = next((i for i, (_, y) in enumerate(res) if y.strip("（）").startswith(k) or k.startswith(y.strip("（）"))), None)
            if hit is None:
                res.append((t, x))
            elif len(k) > len(res[hit][1].strip("（）")):
                res[hit] = (res[hit][0], x)
        return res

    def write_diary(self, day=None, regen=False):
        """その日の出来事から日記を書く. LLM が有効なら LLM, 無ければ定型でまとめる.
        regen: 以前の日記を書き直す (定型だけ. 書いた時刻はそのまま, 「日記をつけた」は残さない)."""
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
        mine = [(t, "", "", x) for t, x in self.day_mine(day)]
        items = sorted(items + mine)
        player = app.settings.get("player_name") or "あなた"
        text, src = None, "template"
        cfg = app.settings.get("llm") or {}
        if cfg.get("enabled") and items and not regen:
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
        old = next((x for x in self.diary_list() if x["day"] == day), None)
        d = {"day": day, "t": old["t"] if regen and old else time.time(), "text": text, "src": src}
        lst = [x for x in self.diary_list() if x["day"] != day] + [d]
        store.save(store.wpath("diary.json"), sorted(lst, key=lambda x: x["day"])[-365:])
        if not regen:
            self.note("diary", "日記をつけた", d["t"])
        return d

    def rewrite_diaries(self, force=False):
        """日記の組み立てを直したので, 以前の日記 (定型で書いたもの) を一度だけ書き直す. LLM で書いた日記はそのまま (同じ文にはならない).
        一人の時間の記録は新しい 500 件しか残らないので, その日の記録がまるごと残っている日だけ (足りない日は書き直さない).
        force: 取りこぼしの仕事を払った (払った日も書き直す). 書き直した日の一覧を返す."""
        ps = self.app.life.player_state()
        if ps.get("diary_fix_v1") and not force:
            return []
        ps["diary_fix_v1"] = time.time()
        self.app.life.save_player()
        log = self.mylog()
        oldest = None if len(log) < 500 else datetime.fromtimestamp(min(e["t"] for e in log)).date().isoformat()
        done = []
        for d in list(self.diary_list()):
            if d.get("src") != "template" or (oldest and d["day"] <= oldest):
                continue
            self.write_diary(d["day"], regen=True)
            done.append(d["day"])
        return done

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
            # 多ければ, 仕事・稼ぎの一行は残して, あとは新しいほうから (6 件まで. 順番は時刻のまま)
            keep = set(i for i, m in enumerate(mine) if m.startswith("仕事") or "円）" in m[:40] and "仕事" in m)
            for i in range(len(mine) - 1, -1, -1):
                if len(keep) >= 6:
                    break
                keep.add(i)
            parts.append("一人の時間: " + "／".join(Solo._short(m) for i, m in enumerate(mine) if i in keep))
        return "\n".join(parts)

    @staticmethod
    def _short(m, limit=48):
        """日記の一行を短く. 文の途中では切らない (最初の文まで. それでも長ければ, 読点で切って「…」)."""
        m = m.replace("\n", " ").strip("（）")
        if len(m) <= limit:
            return m
        depth, end = 0, len(m)
        for i, ch in enumerate(m):              # 括弧の中の「。」では切らない
            depth += 1 if ch == "（" else -1 if ch == "）" else 0
            if ch == "。" and depth <= 0:
                end = i
                break
        first = m[:end]
        if len(first) <= limit:
            return first
        cut = first[:limit]
        i = cut.rfind("、")
        cut = cut[:i] if i >= limit // 2 else cut
        return cut + "…" + ("）" if cut.count("（") > cut.count("）") else "")

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
