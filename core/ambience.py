"""部屋の設定 (A58 段 1. S61): 冷暖房・音楽・お香 / アロマ. 家に続く設定と, そばにいる相手の反応の土台.

- 設定: あなたの家に 1 つずつ. 冷暖房は今までどおり home.json の aircon (室温と電気代の式は core/season.py・core/home.py に残す),
  音楽と香りは home.json の ambience ({music: {v, t, by}, scent: {v, how, t, end, by}, prompt}).
- 反応の土台 (Reactor. 冷暖房 S58 の作りを移したもの): 1 回見る間隔 (CHECK_SEC) ごとに, その場の相手 (起きている同居相手と,
  あなたの家に来ている相手) にとっての合わなさを見て, 一日に一度まで: 言ってくる (性格の approach) / 自分で変える (管理傾向.
  来ている相手は変えない) / 黙って我慢する (言わないまま機嫌が少し下がる). 言ってきたら 合わせる / 断る / 言い返す.
  答えないまま STALE_SEC たつと, うやむや. あなたが変えたら気づく (同じ値の二度押しは何も起きない. 続けて押しても NOTE_SEC は言わない).
  設定ごとに差し替えるのは decide (合わなさと, 言い方の鍵) / answer (答えの効き) / react (あなたが変えたときの気づき) / 選択肢.
- 音楽 (パッシブ): かけている間もほかのコマンドはできる. あなたが出かける (外出・仕事・相手の家・外で会う) と止まる.
  映画を観ている間は鳴らない (観終えると戻る. 止めた記録は持たない). お金はかけない. 夜中に流していると, 寝ている同居相手は眠りが浅くなる.
- お香 / アロマ: 消耗品 (core/items.py の incense / aroma_oil). 焚くと一定の時間で終わる (お香 30〜40 分・アロマ 3〜4 時間).
- 効き: その場にいる相手に, 時間に応じて少しずつ (好きなら機嫌 +・ストレス −, 苦手なら機嫌 −. その時の揺らぎで確定しない).
  数えた時刻 (状態の amb_t) から先だけ数える (閉じていた間に終わっても二重にしない). あなたの心理の値は作らない.
- 好み: 相手の tastes に music:<id> / scent:<id> / smoke (お香の煙) を, 初めて使うときに一度だけ足す
  (性格の既定 AMB_LIKE + キャラの id で決まる隠れた好み. いまある系統は変えない). 相手は, あなたがかけた曲・焚いた香りを
  「この人はこれが好き」と覚え (core/prefs.py), 自分からかける・焚くときの選び方に掛ける.
"""
import math
import random
import time
from datetime import datetime

from . import prefs as prefs_mod

MUSIC = [("pop", "ポップ"), ("rock", "ロック"), ("jazz", "ジャズ"), ("classical", "クラシック"), ("lofi", "ローファイ・環境音"),
         ("anison", "アニソン"), ("hiphop", "ヒップホップ"), ("kayo", "歌謡曲")]
SCENTS = [("lavender", "ラベンダー"), ("sandalwood", "白檀"), ("citrus", "柑橘"), ("rose", "ローズ"), ("forest", "森の香り")]
MUSIC_LABEL = dict(MUSIC)
SCENT_LABEL = dict(SCENTS)
# 焚き方: (名前, 品物, 続く分 (最短, 最長))
HOW = {"incense": ("お香", "incense", (30, 40)), "aroma": ("アロマ", "aroma_oil", (180, 240))}
# 性格の好きな品物の印 (items.PERSONA_LIKES) → 好み. 苦手な印なら逆向き
AMB_LIKE = {"books": {"music:jazz": 0.3, "music:classical": 0.4}, "tea": {"music:jazz": 0.3, "music:lofi": 0.3, "scent:sandalwood": 0.3},
            "cute": {"music:pop": 0.4, "music:anison": 0.3}, "games": {"music:anison": 0.4, "music:rock": 0.3},
            "flowers": {"scent:rose": 0.5, "scent:lavender": 0.3}, "sweets": {"music:pop": 0.3, "scent:citrus": 0.3},
            "food": {"music:kayo": 0.3}, "practical": {"music:lofi": 0.2, "smoke": -0.3},
            "fashion": {"music:hiphop": 0.4, "music:pop": 0.2}, "accessories": {"scent:rose": 0.3, "music:jazz": 0.2}}
SMOKE_PERSONA = {"byoujaku": -0.6}          # 体の弱い人は煙が苦手
PROMPT = {"music": "music, speaker, relaxed", "incense": "incense, thin smoke", "aroma": "aroma diffuser, mist"}

CHECK_SEC = 3600            # 見る間隔
STALE_SEC = 6 * 3600        # 言ってきたまま答えずにいたら, うやむやに
NOTE_SEC = 1800             # あなたが変えたときの反応の間隔 (押し直しで何度も言わない)
EFF_CAP_H = 2.0             # 一度に数える効きの上限 (時間)


class Reactor:
    """続く設定への, その場の相手の反応 (冷暖房・音楽・香りで共通). 差し替える所は下の「設定ごと」."""
    P = "ac"                    # 状態の鍵の頭 (ac_talk / ac_check / ac_day / ac_self / ac_note)
    LP = "ac."                  # セリフの鍵の頭
    ACT = {"id": "_aircon", "name": "冷暖房", "icon": "❄"}
    MARK = "aircon"             # 記録した場面の印 (e[MARK] = 場面)
    LINES = {}
    CHECK = CHECK_SEC
    TOPIC = "冷暖房"            # 言い争いの種
    CHOICES = {"match": "合わせる", "push": "このままがいいと言い返す"}

    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 設定ごと (差し替える)
    def current(self):
        raise NotImplementedError

    def put(self, v, cid):
        """相手が変える / 合わせてもらう."""
        raise NotImplementedError

    def decide(self, char, st, now):
        """変えたいか. None か {f: 合わなさ (0〜1), w: 変えたい値, p: 出る確率, say: 言い方の鍵, self: 自分で変えたときの鍵 (無ければ変えない),
        endure: 我慢の理由の文 (無ければ我慢はしない), talk: 言ってきたことに残す値, extra: セリフの差し込み}."""
        raise NotImplementedError

    def ask_text(self, char, talk):
        raise NotImplementedError

    def choices(self, talk):
        return dict(self.CHOICES)

    def answer(self, char, st, talk, choice, now):
        """(場面の鍵, 効き, 添える文, セリフの差し込み)."""
        raise NotImplementedError

    def granted(self, char, st, talk, old, new, now):
        """言ってきたことを, 答える前に家の様子から叶えたか."""
        return new == talk.get("want")

    def react(self, char, st, old, new, undo, now):
        """あなたが old → new にした: (場面の鍵, 効き, 確率, 差し込み) か None."""
        return None

    # ------------------------------------------------------------------ 共通
    def line(self, char, key, extra=None):
        app = self.app
        t = app.persona_text(char, self.LP + key) or self.LINES[self.LP + key]
        fp, _, call = app.pronouns(char)
        for k, v in dict(extra or {}, fp=fp, call=call, name=char.get("name", "")).items():
            t = t.replace("{%s}" % k, str(v))
        return t

    def _entry(self, char, st, t, key, text, deltas):
        app = self.app
        dt = datetime.fromtimestamp(t)
        scene = app.scene_at(char, st, dt)
        act = dict(self.ACT, pos="", neg="")
        pos, neg, parts = app.build_prompt(char, st, dt, act)
        e = app._new_entry(char["id"], t, act, text, deltas, scene, dt, pos, neg, parts)
        e[self.MARK] = key if self.MARK == "aircon" else self.LP + key
        app.save_log(char["id"])
        return e

    def _apply(self, char, st, eff, now, tag):
        app = self.app
        if any(v > 0 for v in eff.values()):
            eff, _ = app.bonds.realize(char, st, eff, "_%s_%s" % (self.MARK, tag), now)
        return app.apply_effects(st, app.trait_effects(char, eff))

    def cands(self):
        """反応しうる相手: 同居相手と, あなたの家に来ている相手."""
        app = self.app
        out = []
        live = app.bonds.living()
        if live:
            out.append(live)
        w = app.bonds.with_rec()
        if w and w.get("mode") == "guest" and w["cid"] not in out:
            out.append(w["cid"])
        return out

    def guest(self, cid, now=None):
        return self.app.bonds.mode(cid, now) == "guest"

    def awake_home(self, cid, now):
        """相手があなたの家にいて (同居して家で一緒 / 来ている), あなたもいて, どちらも起きている."""
        app = self.app
        if cid not in app.chars or app.bonds.mode(cid, now) not in ("home", "guest"):
            return False
        if app.bonds.mode(cid, now) == "home" and app.bonds.living() != cid:
            return False
        if app.presence.at(now) not in ("here", "idle", "busy"):
            return False
        return not app.scene_at(app.chars[cid], app.state(cid), datetime.fromtimestamp(now))["asleep"]

    # ------------------------------------------------------------------ 毎時
    def tick(self, char, st, now):
        app, P = self.app, self.P
        cid = char["id"]
        at = st.get(P + "_talk")
        if at and now - at["t"] > STALE_SEC:          # 答えないまま: うやむや (言わないまま少しむっとする)
            st.pop(P + "_talk", None)
            if at.get("sour", True):
                self._apply(char, st, {"mood": -1}, now, "stale")
        if at or now - float(st.get(P + "_check", 0)) < self.CHECK or not self.awake_home(cid, now):
            return
        st[P + "_check"] = now
        day = datetime.fromtimestamp(now).date().isoformat()
        if st.get(P + "_day") == day:
            return
        d = self.decide(char, st, now)
        if not d:
            return
        app.trace.add(self.MARK, "合わない / したい", cid, now, f=round(d["f"], 2), want=d["w"], cur=self.current(), p=round(d["p"], 2))
        if random.random() >= d["p"]:
            return
        st[P + "_day"] = day
        cur = self.current()
        guest = self.guest(cid, now)
        ws = {"say": 1.0 * float(app.traits(char).get("approach", 1)) if d.get("say") else 0.0,
              "self": 0.0 if guest or not d.get("self") else 1.2 * app.moneytalk.manage(char, st),
              "endure": 0.8 if d.get("endure") else 0.0}
        if sum(ws.values()) <= 0:
            return
        how = random.choices(list(ws), weights=list(ws.values()))[0]
        app.trace.add(self.MARK, "出方", cid, now, how=how, w={k: round(v, 2) for k, v in ws.items()})
        ex = d.get("extra") or {}
        if how == "say":
            st[P + "_talk"] = dict({"t": now, "want": d["w"], "from": cur}, **(d.get("talk") or {}))
            self._entry(char, st, now, d["say"], self.line(char, d["say"], ex), {})
        elif how == "self":
            self.put(d["w"], cid)
            st[P + "_self"] = {"t": now, "mode": d["w"], "from": cur}
            self.seen(char, st, now)
            self._entry(char, st, now, d["self"], self.line(char, d["self"], ex), {})
        else:
            dd = self._apply(char, st, {"mood": -1}, now, "endure")
            app.life.add_reason(st, "player", "bad", d["endure"], now, told=False, delta=dd.get("mood", 0), action=self.ACT["id"])
        app.save_state(cid)

    # ------------------------------------------------------------------ 言ってきたことへの出方
    def pending(self):
        app = self.app
        for cid in self.cands():
            at = app.state(cid).get(self.P + "_talk")
            if not at or not app.bonds.together(cid):
                continue
            char = app.chars[cid]
            return {"cid": cid, "name": char.get("name", ""), "kind": self.P, "icon": self.ACT["icon"],
                    "text": self.ask_text(char, at), "choices": [{"id": k, "label": v} for k, v in self.choices(at).items()]}
        return None

    def respond(self, choice, now=None):
        app = self.app
        now = now or time.time()
        pv = self.pending()
        if not pv or choice not in [c["id"] for c in pv["choices"]]:
            raise ValueError("いまは何もありません")
        char = app.char(pv["cid"])
        st = app.state(char["id"])
        at = st.pop(self.P + "_talk")
        key, eff, said, ex = self.answer(char, st, at, choice, now)
        d = self._apply(char, st, eff, now, choice)
        e = self._entry(char, st, now, key, said + "\n" + self.line(char, key, ex), d)
        app.trace.add(self.MARK, "言ってきたことへの出方", char["id"], now, choice=choice, key=key)
        app.save_state(char["id"])
        return {"entry": e, "key": key}

    def fight(self, char, st, now, base=0.45):
        """言い返されて言い争いになるか (なれば言い争いを始める)."""
        if random.random() < min(0.8, base * float(self.app.traits(char).get("grudge", 1))):
            self.app.quarrel.start(char, st, now, self.TOPIC, her_fault=False)
            return True
        return False

    # ------------------------------------------------------------------ あなたが変えたとき
    def changed(self, old, new, now=None):
        """あなたが old → new にした. その場の相手が起きていれば気づく (いちばん先に記録した場面を返す)."""
        app = self.app
        now = now or time.time()
        if old == new:
            return None
        first = None
        for cid in self.cands():
            if not self.awake_home(cid, now):
                continue
            char, st = app.chars[cid], app.state(cid)
            at = st.get(self.P + "_talk")
            if at and self.granted(char, st, at, old, new, now):
                st.pop(self.P + "_talk", None)
            self.seen(char, st, now)
            if now - float(st.get(self.P + "_note", 0)) < NOTE_SEC:
                app.save_state(cid)
                continue
            mine = st.get(self.P + "_self") or {}
            undo = mine.get("mode") == old and now - float(mine.get("t", 0)) < 6 * 3600
            r = self.react(char, st, old, new, undo, now)
            app.trace.add(self.MARK, "あなたが変えた", cid, now, old=old, new=new, r=r and r[:3])
            if not r or random.random() >= r[2]:
                app.save_state(cid)
                continue
            key, eff, _, ex = r
            st[self.P + "_note"] = now
            if undo:
                st.pop(self.P + "_self", None)
            d = self._apply(char, st, eff, now, key)
            e = self._entry(char, st, now, key, self.line(char, key, ex), d)
            app.save_state(cid)
            first = first or e
        return first

    def seen(self, char, st, now):
        """あなたが変えたのを見た (気づきを二重にしない. 音楽・香りで使う)."""
        return None


# ====================================================================== 音楽
class Music(Reactor):
    P = "mu"
    LP = "mu."
    ACT = {"id": "_music", "name": "音楽", "icon": "🎵"}
    MARK = "ambience"
    TOPIC = "音楽"
    LINES = {
        "mu.ask_change": "……この曲、ちょっと変えてもいいですか？",
        "mu.ask_play": "{genre}、かけてもいいですか？",
        "mu.self": "{genre}、かけておきますね",
        "mu.match": "ありがとうございます",
        "mu.push": "……わかりました",
        "mu.like": "あ、{genre}。これ、好きなんです",
        "mu.notice": "……この曲、あんまり得意じゃないかもしれません",
        "mu.theirs": "{genre}、家にいるときはよく流してるんです",
    }
    SCENE_LABEL = {"ask_change": "流れている音楽が好みでなく, 変えていいか聞く", "ask_play": "自分の好きな音楽 ({genre}) をかけていいか聞く",
                   "self": "自分の好きな音楽 ({genre}) をかけた (同居)", "match": "音楽のことを聞いてもらえた",
                   "push": "音楽のことを断られて, 渋々", "like": "あなたがかけた音楽 ({genre}) が好きで, 乗る",
                   "notice": "あなたがかけた音楽が, あまり得意でない", "theirs": "相手の家に行くと, 相手の好きな音楽 ({genre}) が流れていた"}

    def __init__(self, app, amb):
        super().__init__(app)
        self.amb = amb

    def current(self):
        m = self.amb.music()
        return m["v"] if m else "off"

    def put(self, v, cid):
        self.amb.set_music(v, by=cid)

    @staticmethod
    def label(v):
        return MUSIC_LABEL.get(v, "音楽")

    def decide(self, char, st, now):
        amb = self.amb
        if amb.watching(now):
            return None
        cur = self.current()
        if cur != "off":
            tv = amb.taste(char, st, "music:" + cur)
            if tv > -0.3:
                return None
            alt = amb.fav(char, st, "music", now, exclude=cur)
            w = alt or "off"
            return {"f": -tv, "w": w, "p": min(0.5, 0.45 * -tv), "say": "ask_change", "self": "self" if alt else None,
                    "endure": "流れている音楽が好みでないのを我慢した", "extra": {"genre": self.label(w)}}
        hr = datetime.fromtimestamp(now).hour
        if hr < 7 or hr >= 23:
            return None
        fav = amb.fav(char, st, "music", now)
        if not fav:
            return None
        tv = amb.taste(char, st, "music:" + fav)
        return {"f": tv, "w": fav, "p": min(0.3, 0.15 * tv * prefs_mod.factor(self.app, char, st, "music:" + fav, now)),
                "say": "ask_play", "self": "self", "endure": None, "talk": {"play": True, "sour": False},
                "extra": {"genre": self.label(fav)}}

    def ask_text(self, char, talk):
        n = char.get("name", "")
        if talk.get("play"):
            return "（%sが、%sをかけたいらしい）" % (n, self.label(talk["want"]))
        if talk["want"] == "off":
            return "（%sは、流れている音楽が好みではないらしい。止めてほしそうだ）" % n
        return "（%sは、流れている音楽が好みではないらしい。%sに変えたいようだ）" % (n, self.label(talk["want"]))

    def choices(self, talk):
        if talk.get("play"):
            return {"match": "かけていいよ", "push": "いまはやめておいてもらう"}
        return {"match": "止める" if talk["want"] == "off" else "%sに変える" % self.label(talk["want"]), "push": "このままがいいと言う"}

    def answer(self, char, st, talk, choice, now):
        if choice == "match":
            self.amb.set_music(talk["want"], by=char["id"])
            self.seen(char, st, now)
            said = "（音楽を止めた）" if talk["want"] == "off" else "（%sにした）" % self.label(talk["want"])
            return "match", {"mood": 1.5}, said, {}
        said = "（いまはやめておいてと言った）" if talk.get("play") else "（このままがいいと言った）"
        return "push", {"mood": -1 if talk.get("play") else -1.5}, said, {}

    def granted(self, char, st, talk, old, new, now):
        return new == talk.get("want") or (not talk.get("play") and new != talk.get("from"))

    def react(self, char, st, old, new, undo, now):
        if new == "off":
            return None
        x = self.amb.taste(char, st, "music:" + new) + random.gauss(0, 0.25)
        ex = {"genre": self.label(new)}
        if x >= 0.4:
            return "like", {"mood": 1}, 0.5, ex
        if x <= -0.4:
            return "notice", {"mood": -2 if undo else -1}, 0.8 if undo else 0.5, ex
        return None

    def seen(self, char, st, now):
        m = self.amb.music()
        if m:
            st["mu_seen"] = m["t"]


# ====================================================================== 香り
class Scent(Reactor):
    P = "sc"
    LP = "sc."
    ACT = {"id": "_scent", "name": "香り", "icon": "🕯"}
    MARK = "ambience"
    TOPIC = "香り"
    CHECK = 900                 # お香は 30 分ほどで終わるので, 15 分ごとに見る
    LINES = {
        "sc.good": "……いい匂いですね。{scent}ですか？",
        "sc.smoky": "……ちょっと煙たいかもしれません",
        "sc.bad": "……この匂い、ちょっと苦手かもしれません",
        "sc.ask": "……窓、少し開けてもいいですか？ 匂いが気になって",
        "sc.match": "ありがとうございます。助かります",
        "sc.push": "……わかりました",
        "sc.self": "{scent}、焚いておきました",
    }
    SCENE_LABEL = {"good": "部屋の香り ({scent}) に気づいて, いい匂い", "smoky": "お香の煙に気づいて, 煙たい",
                   "bad": "部屋の香りが苦手", "ask": "部屋の香りが苦手で, 止めていいか聞く", "match": "香りを止めてもらえた",
                   "push": "香りを止めるのを断られて, 渋々", "self": "自分で香り ({scent}) を焚いた (同居)"}

    def __init__(self, app, amb):
        super().__init__(app)
        self.amb = amb

    def current(self):
        s = self.amb.scent()
        return s["v"] if s else "off"

    def put(self, v, cid):
        if v == "off":
            self.amb.stop_scent()
        else:
            how = "aroma" if self.app.items.count("aroma_oil") > 0 else "incense"
            self.amb.light(v, how, by=cid)

    def decide(self, char, st, now):
        amb = self.amb
        s = amb.scent(now)
        if s:
            tv = amb.feel(char, st, s)
            if tv > -0.3:
                return None
            return {"f": -tv, "w": "off", "p": min(0.6, 0.5 * -tv), "say": "ask", "self": None,
                    "endure": "部屋の匂いが苦手なのを我慢した", "extra": {}}
        if self.guest(char["id"], now) or not (self.app.items.count("aroma_oil") or self.app.items.count("incense")):
            return None
        hr = datetime.fromtimestamp(now).hour
        if hr < 8:
            return None
        fav = amb.fav(char, st, "scent", now)
        if not fav:
            return None
        how = "aroma" if self.app.items.count("aroma_oil") > 0 else "incense"
        tv = amb.feel(char, st, {"v": fav, "how": how})
        if tv < 0.3:
            return None
        return {"f": tv, "w": fav, "p": min(0.15, 0.08 * tv * prefs_mod.factor(self.app, char, st, "scent:" + fav, now)),
                "say": None, "self": "self", "endure": None, "extra": {"scent": SCENT_LABEL[fav]}}

    def ask_text(self, char, talk):
        return "（%sは、部屋の匂いが気になるらしい。止めてほしそうだ）" % char.get("name", "")

    def choices(self, talk):
        return {"match": "止めて窓を開ける", "push": "このままがいいと言う"}

    def seen(self, char, st, now):
        s = self.amb.scent(now)
        if s:
            st["sc_seen"] = s["t"]

    def answer(self, char, st, talk, choice, now):
        if choice == "match":
            self.amb.stop_scent()
            return "match", {"mood": 1.5}, "（香りを止めて、窓を開けた）", {}
        return "push", {"mood": -1.5}, "（このままがいいと言った）", {}


class Ambience:
    """部屋の設定の記録 (home.json の ambience) と, 音楽・香りの効き."""

    def __init__(self, app):
        self.app = app
        self.musicr = Music(app, self)
        self.scentr = Scent(app, self)

    # ------------------------------------------------------------------ 記録
    def rec(self):
        return self.app.home.rec().setdefault("ambience", {})

    def save(self):
        self.app.home.save()

    def away(self, now):
        """あなたが家にいない (出かけた・仕事・相手の家・外で会っている)."""
        app = self.app
        if app.presence.at(now) in ("out", "work"):
            return True
        w = app.bonds.with_rec()
        return bool(w and w.get("mode") in ("visit", "meet"))

    def music(self, now=None):
        """いまかけている音楽 ({v, t, by}) か None. あなたが出かけていれば, ここで止める."""
        r = self.rec()
        m = r.get("music")
        if m and self.away(now or time.time()):
            r.pop("music", None)
            self.save()
            return None
        return m

    def watching(self, now=None):
        """映画を観ている (一人で・一緒に): 音楽は鳴らない."""
        app = self.app
        now = now or time.time()
        sl = app.presence.rec().get("solo") or {}
        if app.presence.at(now) == "busy" and sl.get("kind") in ("movie", "tv"):
            return True
        for cid in app.chars:
            ov = (app.states.get(cid) or {}).get("override") or {}
            if ov.get("activity") in ("movie", "tv") and float(ov.get("until", 0)) > now:
                return True
        return False

    def playing(self, now=None):
        m = self.music(now)
        return m["v"] if m and not self.watching(now) else None

    def set_music(self, v, by="me", now=None):
        now = now or time.time()
        r = self.rec()
        if v in (None, "", "off"):
            if r.pop("music", None) is not None:
                self.save()
            return
        if v not in MUSIC_LABEL:
            raise ValueError("音楽のジャンルが分かりません")
        if (r.get("music") or {}).get("v") == v:          # 同じ曲のまま (二重に開いた画面からの同じ操作): かけ直さない
            return
        r["music"] = {"v": v, "t": now, "by": by}
        self.save()

    def scent(self, now=None):
        """いま焚いている香り ({v, how, t, end, by}) か None (終わっていれば None. 記録は次に焚くまで残す)."""
        s = self.rec().get("scent")
        if s and float(s.get("end", 0)) > (now or time.time()):
            return s
        return None

    def light(self, v, how, by="me", now=None):
        now = now or time.time()
        if v not in SCENT_LABEL or how not in HOW:
            raise ValueError("香りが分かりません")
        if self.scent(now):
            raise ValueError("いまは%sを焚いています" % HOW[self.rec()["scent"]["how"]][0])
        name, iid, (lo, hi) = HOW[how]
        if self.app.items.count(iid) <= 0:
            raise ValueError("%sがない（雑貨はドラッグストア・モール・商店街で買えます）" % name)
        self.app.items.add(iid, -1)
        self.rec()["scent"] = {"v": v, "how": how, "t": now, "end": now + random.uniform(lo, hi) * 60, "by": by}
        self.save()

    def stop_scent(self, now=None):
        now = now or time.time()
        s = self.scent(now)
        if s:
            s["end"] = now
            self.save()

    def prompt_on(self):
        return self.rec().get("prompt", True) is not False

    # ------------------------------------------------------------------ あなたの操作
    def you_music(self, v, now=None):
        now = now or time.time()
        if self.away(now):
            raise ValueError("家にいるときだけかけられます")
        old = self.musicr.current()
        self.set_music(v, "me", now)
        new = self.musicr.current()
        if new != "off" and new != old:
            for cid in self.musicr.cands():
                if self.musicr.awake_home(cid, now):        # あなたがかけた曲: 相手は「この人はこれが好き」と覚える
                    prefs_mod.learn(self.app.state(cid), "music:" + new, 1.0, now)
        e = self.musicr.changed(old, new, now)
        return dict({"ok": True, "ambience": self.view(now)}, **({"entry": e} if e else {}))

    def you_scent(self, v, how=None, now=None):
        now = now or time.time()
        old = self.scentr.current()
        if v in (None, "", "off"):
            self.stop_scent(now)
        else:
            self.light(v, how or "incense", "me", now)
            for cid in self.scentr.cands():
                if self.scentr.awake_home(cid, now):
                    prefs_mod.learn(self.app.state(cid), "scent:" + v, 1.0, now)
        new = self.scentr.current()
        at = None
        if new == "off" and old != "off":                    # 苦手と言ってきた香りを, 答える前に止めた
            for cid in self.scentr.cands():
                st = self.app.state(cid)
                if st.pop("sc_talk", None):
                    self.app.save_state(cid)
        e = None
        if new != "off":
            for cid in self.scentr.cands():
                if self.scentr.awake_home(cid, now):
                    at = self.notice_scent(self.app.chars[cid], self.app.state(cid), now, p=0.6)
                    e = e or at
        return dict({"ok": True, "ambience": self.view(now)}, **({"entry": e} if e else {}))

    def set_prompt(self, on):
        self.rec()["prompt"] = bool(on)
        self.save()
        return {"ok": True, "ambience": self.view()}

    def on_leave(self, now=None):
        """あなたが出かけた (presence.declare): 音楽を止める."""
        if self.rec().pop("music", None) is not None:
            self.save()

    # ------------------------------------------------------------------ 好み
    def tastes(self, char, st):
        """相手の好み (topics.tastes) に, 音楽・香り・煙の系統を一度だけ足して返す (遡及: いまある系統は変えない)."""
        tv = self.app.topics.tastes(char, st)
        if "amb" in (st.get("tastes_fam") or []):
            return tv
        lk, dk = self.app.items.likes(char)
        add = {}
        for sign, tags in ((1, lk), (-1, dk)):
            for tg in tags:
                for k, v in AMB_LIKE.get(tg, {}).items():
                    add[k] = add.get(k, 0) + sign * v
        add["smoke"] = add.get("smoke", 0) + SMOKE_PERSONA.get(char.get("persona_id") or "", 0)
        rnd = random.Random("tastes_amb:%s" % char.get("id"))
        mk = ["music:" + i for i, _ in MUSIC]
        sk = ["scent:" + i for i, _ in SCENTS]
        for k in rnd.sample(mk, 2):
            add[k] = add.get(k, 0) + rnd.uniform(0.4, 0.8)
        for k in rnd.sample(mk, rnd.choice((1, 2))):
            add[k] = add.get(k, 0) - rnd.uniform(0.4, 0.8)
        k = rnd.choice(sk)
        add[k] = add.get(k, 0) + rnd.uniform(0.3, 0.7)
        k = rnd.choice(sk)
        add[k] = add.get(k, 0) - rnd.uniform(0.3, 0.7)
        add["smoke"] += rnd.uniform(-0.6, 0.4)
        for k, v in add.items():
            if k not in tv and abs(v) >= 0.05:
                tv[k] = round(max(-1.0, min(1.0, v)), 2)
        st["tastes"] = tv
        st["tastes_fam"] = list(st.get("tastes_fam") or []) + ["amb"]
        return tv

    def taste(self, char, st, key):
        return float(self.tastes(char, st).get(key, 0.0))

    def feel(self, char, st, s):
        """香りの受け止め (香り + お香なら煙)."""
        tv = self.taste(char, st, "scent:" + s["v"])
        if s.get("how") == "incense":
            tv += self.taste(char, st, "smoke")
        return max(-1.0, min(1.0, tv))

    def fav(self, char, st, fam, now, exclude=None):
        """相手が自分から選ぶ曲 / 香り (好きなもの. あなたの好みと覚えたものも少し掛ける). 無ければ None."""
        ids = [i for i, _ in (MUSIC if fam == "music" else SCENTS) if i != exclude]
        cand = [(i, self.taste(char, st, "%s:%s" % (fam, i))) for i in ids]
        cand = [(i, v) for i, v in cand if v >= 0.3]
        if not cand:
            return None
        w = [math.exp(1.5 * v) * prefs_mod.factor(self.app, char, st, "%s:%s" % (fam, i), now) for i, v in cand]
        return random.choices([i for i, _ in cand], w)[0]

    # ------------------------------------------------------------------ 刻み
    def tick(self, char, st, now):
        """その場の相手への効きと反応 (engine.tick から, 毎回)."""
        app = self.app
        cid = char["id"]
        if app.bonds.mode(cid, now) == "visit":
            self.at_theirs(char, st, now)
        here = self.musicr.awake_home(cid, now)
        marks = st.setdefault("amb_t", {})
        live_asleep = app.bonds.living() == cid and app.bonds.home_together(cid, now) and not here and \
            app.scene_at(char, st, datetime.fromtimestamp(now))["asleep"]
        since = float(((app.bonds.with_rec() or {}).get("t") if self.musicr.guest(cid, now) else 0) or 0)
        g = self.playing(now)
        m = self.rec().get("music") or {}
        if g and (here or live_asleep):
            h = min(EFF_CAP_H, max(0.0, now - max(float(marks.get("music", 0)), float(m.get("t", 0)), since)) / 3600.0)
            if h >= 0.05:
                if here:
                    self._feel(char, st, self.taste(char, st, "music:" + g), h, now, "music")
                    if st.get("mu_seen") != m.get("t"):
                        self.notice_music(char, st, now)
                else:
                    self._night(char, st, h, now)
                marks["music"] = now
        else:
            marks["music"] = now
        s = self.rec().get("scent")
        if s and here:
            end = min(now, float(s.get("end", 0)))
            h = min(EFF_CAP_H, max(0.0, end - max(float(marks.get("scent", 0)), float(s["t"]), since)) / 3600.0)
            if h >= 0.05:
                bed = 21 <= datetime.fromtimestamp(now).hour or datetime.fromtimestamp(now).hour < 2
                self._feel(char, st, self.feel(char, st, s), h, now, "scent", bed)
            marks["scent"] = max(float(marks.get("scent", 0)), end)
            if self.scent(now) and st.get("sc_seen") != s["t"]:
                self.notice_scent(char, st, now)
        elif not here:
            marks["scent"] = now
        if here:
            self.musicr.tick(char, st, now)
            self.scentr.tick(char, st, now)

    def _feel(self, char, st, tv, h, now, kind, bed=False):
        x = tv + random.gauss(0, 0.3)                    # その時の揺らぎ (好きでも今日はそれほど / 苦手でも気にならない日)
        if x >= 0.3:
            eff = {"mood": round(1.0 * h, 2), "stress": -round(1.0 * h, 2)} if kind == "music" else {"stress": -round(1.5 * h, 2)}
            if bed:
                eff["sleepiness"] = round(1.5 * h, 2)        # 寝る前の好きな香り: 寝つきやすい
        elif x <= -0.3:
            eff = {"mood": -round(1.0 * h, 2)}
        else:
            return
        eff, _ = self.app.bonds.realize(char, st, eff, None, now)
        self.app.apply_effects(st, self.app.trait_effects(char, eff))
        self.app.trace.add("ambience", "効き", char["id"], now, kind=kind, tv=round(tv, 2), x=round(x, 2), h=round(h, 2))

    def _night(self, char, st, h, now):
        """夜中に音楽をかけたまま: 寝ている同居相手の眠りが浅くなる."""
        self.app.apply_effects(st, {"energy": -round(2.0 * h, 2), "mood": -round(0.3 * h, 2)})
        day = datetime.fromtimestamp(now - 6 * 3600).date().isoformat()
        if st.get("mu_night") != day:
            st["mu_night"] = day
            self.app.life.add_reason(st, "player", "bad", "夜中に音楽が鳴っていて、よく眠れなかった", now, told=False, action="_music")

    def notice_music(self, char, st, now):
        """来たとき・そばにいるときに, 流れている音楽に気づく (その曲の間に一度)."""
        m = self.rec().get("music") or {}
        st["mu_seen"] = m.get("t")
        r = self.musicr.react(char, st, "off", m.get("v", "off"), False, now)
        if not r or random.random() >= r[2]:
            return None
        key, eff, _, ex = r
        d = self.musicr._apply(char, st, eff, now, key)
        return self.musicr._entry(char, st, now, key, self.musicr.line(char, key, ex), d)

    def notice_scent(self, char, st, now, p=0.5):
        """部屋の香りに気づく (その香りの間に一度). 記録した場面か None."""
        s = self.scent(now)
        if not s:
            return None
        st["sc_seen"] = s["t"]
        if random.random() >= p:
            return None
        smoke = self.taste(char, st, "smoke") if s["how"] == "incense" else 0.0
        sv = self.taste(char, st, "scent:" + s["v"]) + random.gauss(0, 0.2)
        if smoke <= -0.3 and smoke < sv:
            key, eff = "smoky", {"mood": -1}
        elif sv + smoke <= -0.3:
            key, eff = "bad", {"mood": -1}
        elif sv + smoke >= 0.3:
            key, eff = "good", {"mood": 1}
        else:
            return None
        d = self.scentr._apply(char, st, eff, now, key)
        e = self.scentr._entry(char, st, now, key, self.scentr.line(char, key, {"scent": SCENT_LABEL[s["v"]]}), d)
        self.app.save_state(char["id"])
        return e

    def at_theirs(self, char, st, now):
        """相手の家に上がった: 相手の好きな音楽が流れていることがある (その訪問で一度. 流れていれば好みが少し分かる)."""
        w = self.app.bonds.with_rec() or {}
        if st.get("mu_visit") == w.get("t"):
            return None
        st["mu_visit"] = w.get("t")
        fav = self.fav(char, st, "music", now)
        if not fav or random.random() >= 0.35:
            return None
        self.app.bonds.learn(st, "like", MUSIC_LABEL[fav], now)
        e = self.musicr._entry(char, st, now, "theirs", self.musicr.line(char, "theirs", {"genre": MUSIC_LABEL[fav]}), {})
        e["text"] = "（%sが流れている）\n" % MUSIC_LABEL[fav] + e["text"]
        self.app.save_state(char["id"])
        return e

    # ------------------------------------------------------------------ 絵
    def prompt_part(self, char, st, dt):
        """あなたの家にいる相手の絵に足す雰囲気 (設定で外せる)."""
        if not self.prompt_on() or self.app.bonds.mode(char["id"]) not in ("home", "guest"):
            return None
        t = dt.timestamp()
        tags, src = [], []
        if self.playing(t):
            tags.append(PROMPT["music"])
            src.append("音楽")
        s = self.scent(t)
        if s:
            tags.append(PROMPT[s["how"]])
            src.append(HOW[s["how"]][0])
        return {"src": "部屋: " + "・".join(src), "pos": ", ".join(tags), "neg": ""} if tags else None

    # ------------------------------------------------------------------ 表示
    def pending(self):
        return self.musicr.pending() or self.scentr.pending()

    def respond(self, kind, choice):
        r = {"mu": self.musicr, "sc": self.scentr}.get(kind)
        if not r:
            raise ValueError("いまは何もありません")
        return r.respond(choice)

    def view(self, now=None):
        now = now or time.time()
        m = self.music(now)
        s = self.scent(now)
        return {"music": {"on": m["v"] if m else "", "label": MUSIC_LABEL.get(m["v"], "") if m else "",
                          "by": (m or {}).get("by", ""), "paused": bool(m and self.watching(now)), "away": self.away(now),
                          "genres": [{"id": i, "label": lb} for i, lb in MUSIC]},
                "scent": {"on": s["v"] if s else "", "label": SCENT_LABEL.get(s["v"], "") if s else "",
                          "how": (s or {}).get("how", ""), "left": int(max(0, float(s["end"]) - now) // 60) if s else 0,
                          "scents": [{"id": i, "label": lb} for i, lb in SCENTS],
                          "hows": [{"id": k, "label": v[0], "have": self.app.items.count(v[1])} for k, v in HOW.items()]},
                "prompt": self.prompt_on()}
