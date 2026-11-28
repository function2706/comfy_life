"""テレビ (A58 段 2. S61): 時間帯の番組表と連続ドラマ.

- 番組は時刻で決まる (program). 平日と週末で表が違う: 朝と夜のニュース・昼の情報番組・料理番組・夕方の動物番組・夜のバラエティ・
  ドラマ・週末のスポーツ中継. 深夜 (1〜5 時) は通販番組ばかり (種類なし). 番組名はこのアプリだけのもの.
- 連続ドラマ: 木曜 21 時. 10 話 + 休みの週 1 つで 11 週ごとに次の作品 (SERIALS を順に). 話数は日付だけで決まる (保存しない).
  観た回は あなた = player.json の tv.serial {title, seen}, 相手 = 状態の tv.serial {title, seen, with} (一緒に観た回は with にも).
  前の回を見逃していると話が少し分からない (あなた: 文で添える / 相手: 「先週の見逃しちゃって」).
  一緒に続けて観ていると「来週どうなるんだろう」(習慣. その時間に一緒にいれば「そろそろ始まりますよ」と誘ってくることも).
- 一人で観る (一人の時間の tv): 観ていた間の番組を数え, 20 分以上観た番組は話題 (topics) に. 連続ドラマは 30 分以上で観た回に.
- 一緒に観る (行動 tv. 30〜60 分ほど): いまの番組の種類と, 相手の好み (tastes の tv:<種類>) で反応が変わる (その日の揺らぎで確定しない).
  観た番組は二人の話題に. あなたから誘った種類は, 相手が「この人はこれが好き」と覚える (prefs の tv:<種類>).
- 相手も自分の暮らしの中で観ている (char_saw: 家にいて起きていた夜の番組を, 好みしだいで. キャラ・日付で決まる).
  観た番組は, 離れているときのメッセージの話題になる (働きかけ msg_tv. 条件の値 tv_seen).
- 好み: tastes に tv:<種類> を, 初めて使うときに一度だけ足す (印 tastes_fam の "tv". 決め方は core/ambience.py の tastes と同じ).
"""
import random
from datetime import datetime, timedelta

KINDS = {"news": "ニュース", "info": "情報番組", "variety": "バラエティ", "drama": "ドラマ", "sports": "スポーツ中継",
         "cooking": "料理番組", "animals": "動物番組"}
# 種類 → 話題の系統 (core/topics.py の TAGS)
TAGS = {"news": ["gossip"], "info": ["shopping"], "variety": ["gossip"], "drama": ["romance"], "sports": ["sports"],
        "cooking": ["cooking", "food"], "animals": ["animals"]}
# 性格の好きな品物の印 → 番組の好み (苦手な印なら逆向き)
TV_LIKE = {"books": {"tv:news": 0.3, "tv:drama": 0.3}, "practical": {"tv:news": 0.4, "tv:info": 0.3}, "cute": {"tv:animals": 0.5},
           "food": {"tv:cooking": 0.4}, "sweets": {"tv:cooking": 0.3, "tv:variety": 0.2}, "games": {"tv:variety": 0.4, "tv:sports": 0.2},
           "flowers": {"tv:drama": 0.3, "tv:animals": 0.2}, "fashion": {"tv:info": 0.3, "tv:drama": 0.2}, "tea": {"tv:drama": 0.2},
           "accessories": {"tv:drama": 0.3}}
SERIALS = ["春を待つ部屋", "灯台の見える町で", "となりの席の約束", "夜明けの研究室", "坂の上の写真館"]
SERIAL_DAY = 3                          # 木曜
SERIAL_EPS = 10
EPOCH = datetime(2026, 1, 1).date()     # 木曜. ここから 11 週ごとに作品が替わる
# (始まり, 終わり, 種類, 番組名). 終わりは 24 を超えてよい (深夜)
WEEKDAY = [(5, 8, "news", "モーニング・デスク"), (8, 11, "info", "あさのまど"), (11, 12, "cooking", "きょうのおかず"),
           (12, 13, "news", "おひるのニュース"), (13, 17, "info", "午後のひろば"), (17, 19, "news", "夕方ニュース いまどき"),
           (19, 20, "animals", "いきもの散歩"), (20, 21, "variety", "わらってナイト"), (21, 22, None, None),
           (22, 23, "news", "ナイト・デスク"), (23, 25, "variety", "深夜のどっちもアリ")]
WEEKEND = [(6, 9, "news", "週末モーニング"), (9, 11, "animals", "いきもの散歩 週末版"), (11, 12, "cooking", "週末のおかず"),
           (12, 13, "news", "おひるのニュース"), (13, 17, "sports", "週末スポーツ中継"), (17, 19, "variety", "夕方の寄り道"),
           (19, 21, "variety", "わらいの殿堂"), (21, 23, "drama", "ドラマ・ステージ"), (23, 25, "variety", "深夜のどっちもアリ")]
NIGHT21 = {0: ("variety", "どっちもアリ選手権"), 1: ("drama", "ドラマ・ステージ"), 2: ("variety", "クイズ・ひらめき堂"),
           4: ("drama", "ドラマ・ステージ")}
SOLO_MIN, SERIAL_MIN = 20, 30           # 話題になる・連続ドラマを観た回にする, 観ていた分数
SEEN_H = 20                             # 相手が観た番組をメッセージの話題にするのは, 終わってからこの時間まで


def serial_of(d):
    """その日 (date) の連続ドラマ: (作品名, 話数) か, 休みの週 / 放送の日でなければ None."""
    if d.weekday() != SERIAL_DAY:
        return None
    weeks = (d - EPOCH).days // 7
    idx = weeks % (SERIAL_EPS + 1)
    if idx >= SERIAL_EPS:
        return None
    return SERIALS[(weeks // (SERIAL_EPS + 1)) % len(SERIALS)], idx + 1


def program(dt):
    """時刻 dt の番組 {key, kind, title, start, end, serial?, ep?}. 深夜の通販番組なら kind は None."""
    h = dt.hour + (24 if dt.hour < 1 else 0)
    base = dt.date() - timedelta(days=1) if dt.hour < 1 else dt.date()      # 24 時台は前の日の表
    table = WEEKEND if base.weekday() >= 5 else WEEKDAY
    for s, e, kind, title in table:
        if s <= h < e:
            out = {"kind": kind, "title": title, "start": datetime.combine(base, datetime.min.time()) + timedelta(hours=s),
                   "end": datetime.combine(base, datetime.min.time()) + timedelta(hours=e)}
            if s == 21 and table is WEEKDAY:
                sr = serial_of(base)
                if sr:
                    out.update(kind="drama", title=sr[0], serial=sr[0], ep=sr[1])
                else:
                    out["kind"], out["title"] = NIGHT21.get(base.weekday(), ("variety", "木曜の特番"))
            out["key"] = "%s:%02d" % (base.isoformat(), s)
            return out
    return {"kind": None, "title": "通販番組", "key": "%s:late" % base.isoformat(), "start": dt.replace(minute=0, second=0, microsecond=0),
            "end": dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)}


def programs_between(t0, t1):
    """t0〜t1 (時刻) に観ていた番組と, それぞれ観ていた分数 [(番組, 分)]."""
    out = []
    t = datetime.fromtimestamp(t0)
    end = datetime.fromtimestamp(t1)
    while t < end:
        p = program(t)
        stop = min(end, p["end"]) if p["end"] > t else min(end, t + timedelta(hours=1))
        m = (stop - t).total_seconds() / 60.0
        if out and out[-1][0]["key"] == p["key"]:
            out[-1] = (p, out[-1][1] + m)
        else:
            out.append((p, m))
        t = stop
    return out


def label(p):
    return "『%s』第%d話" % (p["title"], p["ep"]) if p.get("serial") else "『%s』" % p["title"]


class TV:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 好み
    def tastes(self, char, st):
        """相手の好みに番組の種類 (tv:<種類>) を一度だけ足して返す (いまある系統は変えない)."""
        tv = self.app.ambience.tastes(char, st)
        if "tv" in (st.get("tastes_fam") or []):
            return tv
        lk, dk = self.app.items.likes(char)
        add = {}
        for sign, tags in ((1, lk), (-1, dk)):
            for tg in tags:
                for k, v in TV_LIKE.get(tg, {}).items():
                    add[k] = add.get(k, 0) + sign * v
        rnd = random.Random("tastes_tv:%s" % char.get("id"))
        ks = ["tv:" + k for k in KINDS]
        for k in rnd.sample(ks, 2):
            add[k] = add.get(k, 0) + rnd.uniform(0.4, 0.8)
        k = rnd.choice(ks)
        add[k] = add.get(k, 0) - rnd.uniform(0.4, 0.8)
        for k, v in add.items():
            if k not in tv and abs(v) >= 0.05:
                tv[k] = round(max(-1.0, min(1.0, v)), 2)
        st["tastes"] = tv
        st["tastes_fam"] = list(st.get("tastes_fam") or []) + ["tv"]
        return tv

    def taste(self, char, st, kind):
        return float(self.tastes(char, st).get("tv:%s" % kind, 0.0)) if kind else 0.0

    # ------------------------------------------------------------------ 連続ドラマの記録
    @staticmethod
    def _serial(rec, title):
        s = rec.get("serial") or {}
        if s.get("title") != title:              # 次の作品: 前の作品の記録は消す
            s = {"title": title, "seen": [], "with": []}
            rec["serial"] = s
        return s

    def follows(self, char, st, title):
        """相手がその作品を (自分で) 追っているか: 好みしだい. キャラと作品で決まる."""
        p = 0.25 + 0.5 * self.taste(char, st, "drama")
        return random.Random("tvf:%s:%s" % (char.get("id"), title)).random() < p

    def char_saw_ep(self, char, st, title, ep, ref):
        """相手がその回を観たか (一緒に観た・自分で観た)."""
        s = (st.get("tv") or {}).get("serial") or {}
        if s.get("title") == title and ep in (s.get("seen") or []):
            return True
        if not self.follows(char, st, title):
            return False
        d = self.air_date(title, ep, ref)
        return d is not None and self._home_at(char, st, datetime.combine(d, datetime.min.time()) + timedelta(hours=21, minutes=20)) \
            and random.Random("tvw:%s:%s:%d" % (char.get("id"), title, ep)).random() < 0.8

    @staticmethod
    def air_date(title, ep, ref):
        """その作品のその回が放送された (される) 日 (ref の日に近い周回で). 無ければ None."""
        c = ((ref - EPOCH).days // 7) // (SERIAL_EPS + 1)
        for cc in (c, c - 1):
            if cc >= 0 and SERIALS[cc % len(SERIALS)] == title:
                return EPOCH + timedelta(days=7 * (cc * (SERIAL_EPS + 1) + ep - 1))
        return None

    def _home_at(self, char, st, dt):
        sc = self.app.scene_at(char, st, dt)
        return not sc["away"] and not sc["asleep"]

    def char_saw(self, char, st, now):
        """相手が自分の暮らしの中で, 前の晩 (19〜23 時) に観た番組 (好きな種類のもの. 家にいて起きていた). 無ければ None."""
        d = datetime.fromtimestamp(now)
        base = (d - timedelta(days=1)).date() if d.hour < 23 else d.date()
        rnd = random.Random("tvsaw:%s:%s" % (char.get("id"), base.isoformat()))
        cands = []
        for hr in (19, 20, 21, 22):
            p = program(datetime.combine(base, datetime.min.time()) + timedelta(hours=hr, minutes=20))
            tv = self.taste(char, st, p["kind"])
            if p["kind"] and tv >= 0.3:
                cands.append((p, tv))
        rnd.shuffle(cands)
        for p, tv in cands:
            if rnd.random() < 0.35 + 0.4 * tv and self._home_at(char, st, p["start"] + timedelta(minutes=20)):
                if now - p["end"].timestamp() < SEEN_H * 3600 and now > p["end"].timestamp():
                    return p
        return None

    # ------------------------------------------------------------------ 一人で観る
    def watch_solo(self, t0, t1):
        """一人の時間「テレビを観る」を終えた: 観た番組の文. 話題と連続ドラマの回を記録する."""
        app = self.app
        ps = app.life.player_state()
        rec = ps.setdefault("tv", {})
        got = [(p, m) for p, m in programs_between(t0, t1) if m >= 5]
        if not got:
            return "テレビをつけたが、すぐに消した"
        names = "・".join(label(p) if p["kind"] else "通販番組" for p, _ in got[:3])
        text = "テレビを観た（%s）" % names
        n = 0
        for p, m in got:
            if p.get("serial") and m >= SERIAL_MIN:
                s = self._serial(rec, p["serial"])
                missed = p["ep"] > 1 and (p["ep"] - 1) not in s["seen"] and bool(s["seen"])     # 初めて観る作品は「見逃した」にしない
                if p["ep"] not in s["seen"]:
                    s["seen"].append(p["ep"])
                if missed:
                    text += "。先週の回を見逃していて、話が少し分からなかった"
            if p["kind"] and m >= SOLO_MIN and n < 2 and rec.get("last_topic") != p["key"]:
                app.topics.add("tv", "%sを観た話" % label(p), list(TAGS[p["kind"]]), t1)
                rec["last_topic"] = p["key"]
                n += 1
        app.life.save_player()
        return text

    # ------------------------------------------------------------------ 一緒に観る
    def together(self, char, st, opts, ctx, now):
        """行動「テレビを観る」の前: いまの番組と受け止めを反応の条件 (tv_kind / tv_feel / tv_serial) に."""
        p = program(datetime.fromtimestamp(now))
        ctx["tv_kind"] = p["kind"] or "none"
        x = self.taste(char, st, p["kind"]) + random.gauss(0, 0.3)
        ctx["tv_feel"] = "like" if x >= 0.35 else "dislike" if x <= -0.35 else "ok"
        ctx["tv_serial"] = ""
        if p.get("serial"):
            ep = p["ep"]
            saw = ep > 1 and self.char_saw_ep(char, st, p["serial"], ep - 1, p["start"].date())
            if ep > 1 and not saw:
                ctx["tv_serial"] = "missed"
            elif saw and ep < SERIAL_EPS:
                ctx["tv_serial"] = "next"
        opts["tv"] = {k: p[k] for k in ("key", "kind", "title") if k in p}
        if p.get("serial"):
            opts["tv"].update(serial=p["serial"], ep=p["ep"])
        opts.setdefault("extra", {}).update(show=label(p) if p["kind"] else "通販番組", kind=KINDS.get(p["kind"], "番組"))

    def after_together(self, char, st, opts, now):
        """一緒に観た (断られなかった): 観た回の記録と, 二人の話題 (topics.from_act から). 話題の (文, 系統) を返す."""
        app = self.app
        p = opts.get("tv") or {}
        if p.get("serial"):
            s = self._serial(st.setdefault("tv", {}), p["serial"])
            for k in ("seen", "with"):
                if p["ep"] not in s[k]:
                    s[k].append(p["ep"])
            ps = app.life.player_state()
            mine = self._serial(ps.setdefault("tv", {}), p["serial"])
            if p["ep"] not in mine["seen"]:
                mine["seen"].append(p["ep"])
        if not p.get("kind"):
            return None
        return "%sと%sを観た話" % (char.get("name", ""), label(p)), list(TAGS[p["kind"]])

    def serial_on(self, char, st, now):
        """条件の値 tv_serial_on: いま連続ドラマの時間 (始まる 10 分前から 20 分過ぎまで) で, 相手が前の 2 回のうちどちらかを一緒に観た."""
        d = datetime.fromtimestamp(now)
        p = program(d + timedelta(minutes=10))
        if not p.get("serial") or d > p["start"] + timedelta(minutes=20) or p["ep"] < 2:
            return 0
        s = (st.get("tv") or {}).get("serial") or {}
        if s.get("title") != p["serial"]:
            return 0
        return int(any(e in (s.get("with") or []) for e in (p["ep"] - 1, p["ep"] - 2)))

    # ------------------------------------------------------------------ 離れているときの話題
    def seen_ctx(self, char, st, now):
        """条件の値 tv_seen: 相手が前の晩に観た番組があり, まだあなたに話していない (観た番組は 15 分ごとに見直す)."""
        ck = (char.get("id"), int(now // 900))
        cache = self.__dict__.setdefault("_seen", {})
        if ck not in cache:
            if len(cache) > 200:
                cache.clear()
            cache[ck] = self.char_saw(char, st, now)
        p = cache[ck]
        return int(bool(p) and (st.get("tv") or {}).get("told") != p["key"])

    def serial_label(self, now):
        p = program(datetime.fromtimestamp(now) + timedelta(minutes=10))
        return label(p) if p.get("serial") else "ドラマ"

    def pick_seen(self, char, st, now):
        """働きかけ msg_tv で話す番組 (話したことを残す). 番組名の文を返す."""
        p = self.char_saw(char, st, now)
        if not p:
            return "昨日のテレビ"
        st.setdefault("tv", {})["told"] = p["key"]
        return label(p)

    def view(self, now):
        p = program(datetime.fromtimestamp(now))
        return {"now": label(p) if p["kind"] else "通販番組", "kind": KINDS.get(p["kind"], "")}
