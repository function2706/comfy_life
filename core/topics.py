"""話題のたくわえ: あなたが実際にしたこと・知ったことが話題になり, 会って / メッセージで相手に振れる.

- 話題の元 (ランダムではない): 一人で出かけた先・誰かと出かけた先 (思い出話)・読んだ本・観た映画・仕事・噂.
  文で持つ (「水族館に行った話」). 系統 (TAGS) は裏だけで, 画面には出さない. 古いほど鮮度が落ち, 3 週間で消える.
- 相手が乗るか: 性格の既定の好き (items.PERSONA_LIKES とキャラの likes) + キャラごとの隠れた好み (性格とは別. キャラごとに固定) +
  その時の機嫌・ノリ・疲れ + 同じ系統が続いた飽き + 揺らぎ. 同じ話をもう一度すると「前も聞いた」. 噂は相手がもう知っていることも.
  その人と一緒に行った先の話は思い出話 (知っている前提で, 乗りやすい).
- 結果: hit (盛り上がる) / ok / bored (つまらなそう) / known (知ってる) / again (前も聞いた). 盛り上がれば, その系統が
  「好きなもの」の覚えに残る (bonds.learn). 外したことは残さない (あなたが覚えておく).
- 以前のセーブ: はじめて使うときに, 一人の時間の記録と相手との記録から直近 2 週間の体験を話題として拾う (一度だけ).
  隠れた好みも, はじめて使うときに決める.
"""
import math
import random
import time
import uuid

from . import nori as nori_mod

TAGS = {"books": "本", "movies": "映画", "food": "食べ物", "sweets": "甘いもの", "animals": "動物", "nature": "自然", "sea": "海",
        "amusement": "遊園地", "shopping": "買い物", "fashion": "服", "games": "ゲーム", "work": "仕事", "money": "お金",
        "gossip": "噂話", "sports": "運動", "cooking": "料理", "stars": "星"}
# 行き先 → 系統
PLACE_TAGS = {"park": ["nature"], "riverside": ["nature"], "shopping_street": ["shopping", "food"], "station": ["shopping"],
              "town": ["shopping"], "cafe": ["sweets"], "supermarket": ["cooking"], "convenience": ["food"], "drugstore": ["shopping"],
              "bookstore": ["books"], "electronics": ["games"], "mall": ["shopping", "fashion"], "aquarium": ["animals", "sea"],
              "amusement": ["amusement"], "beach": ["sea", "nature"], "mountain": ["nature", "sports"], "hill": ["stars", "nature"],
              "teishoku": ["food"], "ramen": ["food"], "fastfood": ["food"], "family": ["food"], "restaurant": ["food"]}
# 品物の好みの印 (items) → 話題の系統
LIKE_MAP = {"food": ["food", "cooking"], "tea": ["sweets"], "sweets": ["sweets"], "practical": ["work", "money"], "books": ["books"],
            "flowers": ["nature"], "cute": ["animals"], "accessories": ["fashion"], "fashion": ["fashion", "shopping"], "games": ["games"]}
BOOKS = [("ある推理小説", ["books"]), ("恋愛小説", ["books"]), ("犬が主人公の小説", ["books", "animals"]), ("料理のエッセイ", ["books", "cooking"]),
         ("海辺の町の小説", ["books", "sea"]), ("山登りの紀行文", ["books", "nature"]), ("星にまつわる短編集", ["books", "stars"]),
         ("お仕事小説", ["books", "work"]), ("服飾の歴史の本", ["books", "fashion"])]
MOVIES = [("アクション映画", ["movies"]), ("恋愛映画", ["movies"]), ("動物のドキュメンタリー", ["movies", "animals"]),
          ("アニメ映画", ["movies", "games"]), ("ホラー映画", ["movies"]), ("グルメ映画", ["movies", "food"]),
          ("海の生き物の記録映画", ["movies", "sea", "animals"]), ("宇宙の映画", ["movies", "stars"]), ("スポーツ映画", ["movies", "sports"])]
WORK = ["仕事で忙しかった話", "職場であったちょっとした話", "仕事でうまくいった話", "仕事で失敗した話"]
KEEP_DAYS = 21          # これより古い話題は消える
FRESH_DAYS = 14         # 鮮度が落ちきるまで
RESULTS = ("hit", "ok", "bored", "known", "again")
EFFECT = {"hit": {"mood": 4, "boredom": -8, "loneliness": -4, "affection": 1}, "ok": {"boredom": -3, "loneliness": -2},
          "bored": {"mood": -1, "boredom": 3}, "known": {"boredom": -1}, "again": {"mood": -1, "boredom": 2}}
NORI = {"hit": 10, "ok": -2, "bored": -12, "known": -4, "again": -8}
# メッセージで振ったときの共通の返し (性格プリセットに talk_topic.<結果> があれば, それを 📱 で包む)
PHONE_LINES = {"hit": "📱『えっ、それでそれで？ もっと聞かせてください！』", "ok": "📱『へえ、そうなんですね』",
               "bored": "📱『……そうなんですね』", "known": "📱『あ、それ知ってます』", "again": "📱『……それ、前も聞きましたよ？』"}


class Topics:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ たくわえ
    def ps(self):
        ps = self.app.life.player_state()
        ps.setdefault("topics", [])
        if not ps.get("topics_v1"):
            ps["topics_v1"] = True
            self._retro(ps)
        return ps

    def all(self, now=None):
        now = now or time.time()
        ps = self.ps()
        ps["topics"] = [x for x in ps["topics"] if now - x["t"] < KEEP_DAYS * 86400]
        return ps["topics"]

    def add(self, src, text, tags, t=None, with_=None, ref=None, save=True):
        """話題を足す. 同じ文の話題が 1 日以内にあれば足さない (鮮度だけ新しく). 足した (か更新した) 話題を返す."""
        t = t or time.time()
        tops = self.all(t)
        for x in tops:
            if x["text"] == text:            # 同じ先にまた行った: 一つの話題のまま新しくなる (新しい話なので, まだ誰にも話していない)
                if t - x["t"] >= 86400:
                    x["told"] = {}
                x["t"] = max(x["t"], t)
                for c in with_ or []:
                    if c not in x.setdefault("with", []):
                        x["with"].append(c)
                return x
        x = {"id": uuid.uuid4().hex[:8], "t": t, "src": src, "text": text, "tags": list(tags), "told": {}}
        if with_:
            x["with"] = list(with_)
        if ref:
            x["ref"] = ref
        tops.append(x)
        del tops[:-60]
        if save:
            self.app.life.save_player()
        trace = getattr(self.app, "trace", None)
        if trace:
            trace.add("topic", "話題が増えた", None, t, src=src, text=text, tags=tags, with_=with_)
        return x

    def view(self, cid=None, now=None):
        """画面に出す話題 (新しい順. 系統は出さない). 誰に話したか (told_to)・誰と一緒だったか (with)."""
        now = now or time.time()
        out = []
        for x in sorted(self.all(now), key=lambda x: -x["t"])[:20]:
            out.append({"id": x["id"], "text": x["text"], "t": x["t"], "told_to": sorted(x.get("told", {})),
                        "with": list(x.get("with") or [])})
        return out

    # ------------------------------------------------------------------ 話題の元
    def from_solo(self, note_kind, kind, place, h, now):
        """一人の時間の結果から (出かけた先・読んだ本・観た映画・走った)."""
        if h < 0.25:
            return None
        if kind == "read_done":
            return None
        if place and place in PLACE_TAGS and note_kind in ("out", "walk", "shopping", "cafe", "jog"):
            label = self.app.places.label(place)
            if kind == "jog":
                return self.add("solo", "%sを走った話" % label, ["sports"] + PLACE_TAGS[place][:1], now)
            return self.add("solo", "%sに行った話" % label, PLACE_TAGS[place], now)
        return None

    def from_act(self, char, a, r, opts, now):
        """誰かと出かけた・映画を観た (思い出話になる)."""
        if (r or {}).get("override"):
            return None
        ov = a.get("override") or {}
        if a.get("id") == "movie":
            title, tags = random.choice(MOVIES)
            return self.add("with", "%sと%sを観た話" % (char.get("name", ""), title), tags, now, with_=[char["id"]])
        if ov.get("outing"):
            place = (opts or {}).get("place") if (opts or {}).get("place") in (a.get("places") or []) else ov.get("place")
            if place in PLACE_TAGS:
                return self.add("with", "%sと%sに行った話" % (char.get("name", ""), self.app.places.label(place)),
                                PLACE_TAGS[place], now, with_=[char["id"]])
        return None

    def from_work(self, h, now):
        if h >= 2 and random.random() < 0.35:
            return self.add("work", random.choice(WORK), ["work"], now)
        return None

    def from_rumor(self, text, now):
        return self.add("rumor", "噂で聞いた話（%s）" % text[:24].rstrip("、。"), ["gossip", "money"], now)

    def read_book(self, now):
        """小説を 1 冊読み終える (持ち物の小説を使う). (文, 話題) を返す. 小説が無ければ ValueError."""
        items = self.app.items
        if items.count("novel") <= 0:
            raise ValueError("読む本がない（小説は本屋や駅前などで買えます）")
        items.add("novel", -1)
        title, tags = random.choice(BOOKS)
        return "%sを読み終えた" % title, self.add("book", "%sを読んだ話" % title, tags, now)

    def watch_movie(self, now):
        title, tags = random.choice(MOVIES)
        return "家で%sを観た" % title, self.add("movie", "%sを観た話" % title, tags, now)

    # ------------------------------------------------------------------ 好み
    def tastes(self, char, st):
        """キャラごとの話題の好み (系統 → -1〜1). 性格の既定の好き・苦手 + キャラごとに決まった隠れた好み."""
        tv = st.get("tastes")
        if tv:
            return tv
        lk, dk = self.app.items.likes(char)
        tv = {}
        for tg in lk:
            for k in LIKE_MAP.get(tg, []):
                tv[k] = tv.get(k, 0) + 0.6
        for tg in dk:
            for k in LIKE_MAP.get(tg, []):
                tv[k] = tv.get(k, 0) - 0.6
        rnd = random.Random("tastes:%s" % char.get("id"))
        keys = sorted(TAGS)
        for k in rnd.sample(keys, 2):
            tv[k] = tv.get(k, 0) + rnd.uniform(0.4, 0.8)
        for k in rnd.sample(keys, rnd.choice((1, 2))):
            tv[k] = tv.get(k, 0) - rnd.uniform(0.4, 0.8)
        tv = {k: round(max(-1.0, min(1.0, v)), 2) for k, v in tv.items() if abs(v) >= 0.05}
        st["tastes"] = tv
        return tv

    # ------------------------------------------------------------------ 振る
    def judge(self, char, st, x, now):
        """相手がこの話題に乗るか. (結果, 判定の値) を返す. 記録 (話したこと・飽き) はまだ残さない."""
        cid = char["id"]
        if cid in x.get("told", {}):
            if random.random() < 0.8:
                return "again", {}
        if x["src"] == "rumor" and random.Random("%s:%s" % (x["id"], cid)).random() < 0.35:
            return "known", {}
        p = st["params"]
        tv = self.tastes(char, st)
        taste = sum(tv.get(k, 0.0) for k in x["tags"]) / math.sqrt(max(1, len(x["tags"])))
        age = (now - x["t"]) / 86400.0
        fresh = max(0.0, 1 - age / FRESH_DAYS)
        recent = [h for h in st.get("topic_tags") or [] if now - h["t"] < 3 * 86400 and h["tag"] in x["tags"]]
        lv = nori_mod.level(st, now)
        shared = cid in (x.get("with") or [])
        score = 26 * taste + 0.2 * (p.get("mood", 50) - 50) + (15 * (lv - 0.5) if lv is not None else 0) + 8 * fresh \
            - 9 * len(recent) - (8 if p.get("energy", 60) < 25 else 0) + (10 if shared else 0) + random.uniform(-15, 15)
        res = "hit" if score >= 14 else "ok" if score >= -6 else "bored"
        if res != "ok" and random.random() < 0.1:      # 好きな話でも今日はそれほど / 苦手な話でも今日は聞いてくれる (確定させない)
            res = "ok"
        return res, {"score": round(score, 1), "taste": round(taste, 2), "fresh": round(fresh, 2), "recent": len(recent),
                     "nori": lv, "shared": shared}

    def told(self, char, st, x, res, now):
        """話した記録・飽き・覚え・ノリ."""
        cid = char["id"]
        x.setdefault("told", {})[cid] = now
        hist = [h for h in st.get("topic_tags") or [] if now - h["t"] < 7 * 86400]
        hist += [{"tag": k, "t": now} for k in x["tags"]]
        st["topic_tags"] = hist[-30:]
        if res == "hit":
            tv = self.tastes(char, st)
            best = max(x["tags"], key=lambda k: tv.get(k, 0.0))
            if tv.get(best, 0.0) > 0:
                self.app.bonds.learn(st, "like", TAGS[best], now)
        if nori_mod.active(st, now):
            nori_mod.bump(self.app, st, now, NORI[res], "話題: " + res)
        self.app.life.save_player()

    def find(self, tid):
        x = next((x for x in self.all() if x["id"] == tid), None)
        if not x:
            raise KeyError("話題が見つかりません（古くなって忘れたのかもしれません）")
        return x

    def tell(self, tid, cid=None):
        """会って話題を振る (コマンド talk_topic. 反応の条件 topic_res)."""
        x = self.find(tid)
        char = self.app.char(cid)
        st = self.app.state(char["id"])
        now = time.time()
        res, vals = self.judge(char, st, x, now)
        r = self.app.act("talk_topic", char["id"], opts={"ctx": {"topic_res": res}, "extra": {"topic": x["text"]},
                                                          "effects": EFFECT[res]})
        e = r.get("entry") or {}
        if not e.get("override"):
            with self.app.lock:
                st = self.app.state(char["id"])
                self.told(char, st, x, res, now)
                e["text"] = "（%sをした）\n%s" % (x["text"], e.get("text", ""))      # 何の話をしたか
                self.app.save_state(char["id"])
                self.app.save_log(char["id"])
        trace = getattr(self.app, "trace", None)
        if trace:
            trace.add("topic", "話題を振った (会って)", char["id"], now, topic=x["text"], res=res, **vals)
        r["topic_res"] = res
        return r

    def send(self, tid, cid):
        """メッセージで話題を振る (返事は時間差. chat.reply の kind="topic")."""
        x = self.find(tid)
        return self.app.chat.send(cid, "topic", extra={"topic": x["id"], "topic_text": x["text"]})

    def phone_reply(self, char, st, meta, now):
        """メッセージで振った話題への返事: (場面の鍵, 効果, 置き換え)."""
        try:
            x = self.find(meta.get("topic"))
        except KeyError:
            return "topic_ok", {}, {"topic": meta.get("topic_text", "")}
        res, vals = self.judge(char, st, x, now)
        self.told(char, st, x, res, now)
        trace = getattr(self.app, "trace", None)
        if trace:
            trace.add("topic", "話題を振った (メッセージ)", char["id"], now, topic=x["text"], res=res, **vals)
        return "topic_" + res, dict(EFFECT[res]), {"topic": x["text"]}

    def phone_line(self, char, res, extra):
        t = self.app.persona_text(char, "talk_topic." + res)
        t = "📱『%s』" % t if t else PHONE_LINES[res]
        fp, _, call = self.app.pronouns(char)
        for k, v in dict(extra, fp=fp, call=call, name=char.get("name", "")).items():
            t = t.replace("{%s}" % k, str(v))
        return t

    # ------------------------------------------------------------------ 以前のセーブ
    def _retro(self, ps):
        """はじめて使うとき: 一人の時間の記録と, 相手との記録から, 直近 2 週間の体験を話題として拾う (一度だけ)."""
        now = time.time()
        t0 = now - 14 * 86400
        n = 0
        try:
            for e in self.app.solo.mylog():
                if e.get("t", 0) < t0 or e.get("void"):
                    continue
                place = e.get("place")
                if place in PLACE_TAGS and e.get("kind") in ("out", "walk", "shopping", "cafe", "jog"):
                    label = self.app.places.label(place)
                    text = "%sを走った話" % label if e.get("kind") == "jog" else "%sに行った話" % label
                    self._retro_add(ps, "solo", text, PLACE_TAGS[place], e["t"])
                    n += 1
                elif e.get("kind") == "work" and float(e.get("hours") or 0) >= 2 and random.random() < 0.35:
                    self._retro_add(ps, "work", random.choice(WORK), ["work"], e["t"])
                    n += 1
            acts = {a["id"]: a for a in self.app.actions}
            for cid, char in self.app.chars.items():
                for e in self.app.log(cid):
                    if e.get("t", 0) < t0:
                        continue
                    a = acts.get(e.get("action"))
                    if not a or e.get("override"):
                        continue
                    ov = a.get("override") or {}
                    place = e.get("place") or ov.get("place")
                    if ov.get("outing") and place in PLACE_TAGS:
                        self._retro_add(ps, "with", "%sと%sに行った話" % (char.get("name", ""), self.app.places.label(place)),
                                        PLACE_TAGS[place], e["t"], with_=[cid])
                        n += 1
        except Exception:  # noqa: BLE001 - 拾えなくても話題機能は使える
            pass
        trace = getattr(self.app, "trace", None)
        if trace:
            trace.add("retro", "話題を以前の記録から拾った", None, now, n=n)

    def _retro_add(self, ps, src, text, tags, t, with_=None):
        for x in ps["topics"]:
            if x["text"] == text:
                x["t"] = max(x["t"], t)
                return
        x = {"id": uuid.uuid4().hex[:8], "t": t, "src": src, "text": text, "tags": list(tags), "told": {}}
        if with_:
            x["with"] = list(with_)
        ps["topics"].append(x)
