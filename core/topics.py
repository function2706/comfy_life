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
        "gossip": "噂話", "sports": "運動", "cooking": "料理", "stars": "星",
        "mystery": "推理もの", "romance": "恋愛もの", "action": "アクションもの", "horror": "ホラー", "anime": "アニメ"}
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
# ジャンルを選んで読む・観る (A3): (id, 画面の名前, 題名の候補, 系統). 系統の 2 つめがジャンル (相手の好みはここで見る)
BOOK_GENRES = [
    ("mystery", "推理小説", ["ある推理小説", "古い洋館が舞台の推理小説"], ["books", "mystery"]),
    ("romance", "恋愛小説", ["恋愛小説", "すれ違い続ける二人の恋愛小説"], ["books", "romance"]),
    ("horror", "ホラー小説", ["怖い話の短編集", "山奥の村のホラー小説"], ["books", "horror"]),
    ("animals", "動物の小説", ["犬が主人公の小説", "猫と暮らす人の小説"], ["books", "animals"]),
    ("cooking", "料理のエッセイ", ["料理のエッセイ", "台所のエッセイ"], ["books", "cooking"]),
    ("sea", "海の小説", ["海辺の町の小説"], ["books", "sea"]),
    ("nature", "紀行文", ["山登りの紀行文", "歩く旅の紀行文"], ["books", "nature"]),
    ("stars", "星の短編集", ["星にまつわる短編集"], ["books", "stars"]),
    ("work", "お仕事小説", ["お仕事小説"], ["books", "work"]),
    ("fashion", "服の本", ["服飾の歴史の本"], ["books", "fashion"]),
]
MOVIE_GENRES = [
    ("action", "アクション", ["アクション映画"], ["movies", "action"]),
    ("romance", "恋愛", ["恋愛映画"], ["movies", "romance"]),
    ("mystery", "サスペンス", ["サスペンス映画"], ["movies", "mystery"]),
    ("horror", "ホラー", ["ホラー映画"], ["movies", "horror"]),
    ("anime", "アニメ", ["アニメ映画"], ["movies", "anime"]),
    ("animals", "動物のドキュメンタリー", ["動物のドキュメンタリー", "海の生き物の記録映画"], ["movies", "animals"]),
    ("food", "グルメ", ["グルメ映画"], ["movies", "food"]),
    ("stars", "宇宙", ["宇宙の映画"], ["movies", "stars"]),
    ("sports", "スポーツ", ["スポーツ映画"], ["movies", "sports"]),
]
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

    def reading(self):
        """読みかけの本 / 観かけの映画 ({title, tags, h, t} か None)."""
        ps = self.app.life.player_state()
        return ps.get("reading"), ps.get("watching")

    @staticmethod
    def pick_genre(genres, gid):
        """ジャンルから題名を 1 つ (選んでいなければ, どれかから). (題名, 系統)."""
        g = next((x for x in genres if x[0] == gid), None) or random.choice(genres)
        return random.choice(g[2]), list(g[3])

    def genres_view(self):
        return {"books": [{"id": g[0], "label": g[1]} for g in BOOK_GENRES],
                "movies": [{"id": g[0], "label": g[1]} for g in MOVIE_GENRES]}

    def read(self, h, now, need=1.5, genre=None):
        """本を読む: 読みかけがあれば続きから (日を空けたぶん少し読み返す), 無ければ持ち物の小説を 1 冊開く.
        読んだ時間の合計が need に届けば読み終えて話題に. 文を返す. 読む本が無ければ ValueError."""
        ps = self.app.life.player_state()
        b = ps.get("reading")
        back = 0.0
        if not b:
            if self.app.items.count("novel") <= 0:
                raise ValueError("読む本がない（小説は本屋や駅前などで買えます）")
            self.app.items.add("novel", -1)
            title, tags = self.pick_genre(BOOK_GENRES, genre)
            b = ps["reading"] = {"title": title, "tags": tags, "h": 0.0, "t": now}
            head = "%sを読み始めた" % title
        else:
            back = min(0.5, 0.25 * max(0.0, (now - b["t"]) / 86400.0 - 1) / 7.0)      # 日を空けたぶん, 少し読み返す
            head = "%sの続きを読んだ" % b["title"] + ("（少し前を読み返した）" if back >= 0.1 else "")
        b["h"] = round(b["h"] + max(0.0, h - back), 2)
        b["t"] = now
        if b["h"] >= need:
            ps.pop("reading", None)
            self.add("book", "%sを読んだ話" % b["title"], b["tags"], now)
            return "%sを一気に読み終えた" % b["title"] if head.endswith("読み始めた") else "%s。読み終えた" % head
        self.app.life.save_player()
        return "%s（あと%d分ほど）" % (head, max(5, int(round((need - b["h"]) * 60 / 5.0)) * 5))

    def watch(self, h, now, need=2.0, forget_days=3, genre=None):
        """家で映画を観る (配信): 観かけがあれば続きから. 何日も空けたら忘れて, 別の映画を最初から. 文を返す."""
        ps = self.app.life.player_state()
        m = ps.get("watching")
        if m and now - m["t"] > forget_days * 86400:
            m = None                                    # 観かけは忘れた
        if not m:
            title, tags = self.pick_genre(MOVIE_GENRES, genre)
            m = ps["watching"] = {"title": title, "tags": tags, "h": 0.0, "t": now}
            head = "家で%sを観始めた" % title
        else:
            head = "%sの続きを観た" % m["title"]
        m["h"] = round(m["h"] + h, 2)
        m["t"] = now
        if m["h"] >= need:
            ps.pop("watching", None)
            self.add("movie", "%sを観た話" % m["title"], m["tags"], now)
            return "家で%sを観た" % m["title"] if head.endswith("観始めた") else "%s。観終えた" % head
        self.app.life.save_player()
        return "%s（あと%d分ほど）" % (head, max(5, int(round((need - m["h"]) * 60 / 5.0)) * 5))

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

    REVEAL = {"like": "{genre}、けっこう好きなんです。", "dislike": "{genre}は、あんまり得意じゃないかも。"}

    def reveal(self, char, st, x, res, now):
        """読んだ本・観た映画の話から, そのジャンルが好き・苦手かを相手が口にすることがある (仲・機嫌・性格しだい).
        聞いたことは「知っていること」に残る. 口にした一言 (文) を返す. 言わなければ None."""
        if x.get("src") not in ("book", "movie") or res in ("again", "known"):
            return None
        g = next((k for k in x.get("tags") or [] if k not in ("books", "movies")), None)
        tv = self.tastes(char, st).get(g, 0.0) if g else 0.0
        if not g or abs(tv) < 0.3:
            return None
        p = st["params"]
        close = self.app.bonds.stage(char["id"]) in ("visit", "live")
        open_ = float(self.app.traits(char).get("approach", 1.0))          # 話したがりほど, 自分のことを言う
        pr = 0.2 + (0.2 if close else 0) + (p.get("trust", 50) - 50) / 200.0 + (p.get("mood", 50) - 50) / 250.0 + 0.15 * (open_ - 1)
        if random.random() >= max(0.05, min(0.8, pr)):
            return None
        kind = "like" if tv > 0 else "dislike"
        self.app.bonds.learn(st, kind, TAGS[g], now)
        t = self.app.persona_text(char, "topic.genre_" + kind) or self.REVEAL[kind]
        return t.replace("{genre}", TAGS[g])

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
                rv = self.reveal(char, st, x, res, now)
                e["text"] = "（%sをした）\n%s" % (x["text"], e.get("text", "")) + ("\n「%s」" % rv if rv else "")     # 何の話をしたか
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
        rv = self.reveal(char, st, x, res, now)
        trace = getattr(self.app, "trace", None)
        if trace:
            trace.add("topic", "話題を振った (メッセージ)", char["id"], now, topic=x["text"], res=res, reveal=rv, **vals)
        return "topic_" + res, dict(EFFECT[res]), {"topic": x["text"], "reveal": rv or ""}

    def phone_line(self, char, res, extra):
        t = self.app.persona_text(char, "talk_topic." + res)
        t = "📱『%s』" % t if t else PHONE_LINES[res]
        if extra.get("reveal"):                      # ジャンルの好き・苦手を口にした
            t = t[:-1] + " " + extra["reveal"] + "』" if t.endswith("』") else t + " " + extra["reveal"]
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
