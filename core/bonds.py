"""あなたと各キャラの間柄 (data/worlds/<id>/player.json の bonds / with).

段階 (stage):
- known:   知り合い. 顔は知っているが連絡先は知らない (連絡も誘いもできない. 偶然会えば連絡先を交換する)
- contact: 連絡先を知っている. メッセージ・電話・お出かけに誘える (外で会う)
- visit:   家に遊びに行ける (「今度、家に行ってもいい？」を受けてもらった)
- live:    一緒に暮らしている (一人だけ. 「一緒に住まない？」を受けてもらった)

いまどこで誰といるか (with):
- None:                      自分の家 (同居している相手が家にいればその人と一緒. あなたが外出・仕事中か,
                             相手が自分の予定で出かけているあいだは, 同居していても離れている)
- {"cid", "mode": "meet"}:   外で会っている (お出かけの一時シーンが終われば別れる)
- {"cid", "mode": "visit"}:  相手の家に遊びに来ている (until まで)
- {"cid", "mode": "guest"}:  相手をあなたの家に招いている (until まで. 来たときの家の様子に反応する: core/home.py).
                             同居相手が家にいれば, その人もそばにいる (そばにいるのが二人になる)

いまそばにいる人たち (company): 上の形で一緒にいる人全員. 画面の「誰かと」の相手はこの中から選ぶ.
そばにいる効果 (寂しさが紛れる) がかかるのは, あなたとその人の二人きりのときだけ (engine._step).

一緒にいない相手には, 体に触れる・家の中のことなどはできず, 連絡・誘う・あなたの予定だけ (apart).
本命は各キャラが自分の視点で持つ: あなたと仲が深いキャラは, あなたがほかの人とも深い仲だと知ると嫉妬する.

現実的であること (このアプリの公理): 回数をこなせば仲が深まる, とはしない.
- 好感度・信頼が上がる量は毎回揺らぎ, その日のうちに上がるほど鈍る. 機嫌が悪いと効きにくい
- 同じことを一日に何度も繰り返すと, うんざりされて逆効果になることがある
- しばらく交流がないと, 好感度・信頼は少しずつ冷め, 家に行ける仲も「連絡先」に戻る
- 段階の提案 (家に行っていい？/ 一緒に住む？) は, 数値・最近の交流・性格・その日の気分で決まり, 断られうる
- 贈り物・お金は, 性格と仲の深さ・頻度しだいで, 喜ばれないことも, 重いと思われることもある
- 知り合いと偶然会っても, 連絡先を交換するとは限らない (あなたの話のうまさ・相手の機嫌と好感度・性格しだい)
"""
import datetime as _dt
import math
import random
import time

from . import store

STAGES = ("known", "contact", "visit", "live")
STAGE_LABEL = {"known": "知り合い", "contact": "連絡先", "visit": "家に行ける仲", "live": "同居"}
# 一緒にいないときでもできるコマンドの分類 (個別には action の "apart": true / false で指定)
APART_CATEGORIES = ("連絡", "会う", "あなたの予定")
# 離れている相手のときの「あなたの予定」などの記録 (相手は見送りも出迎えもしない)
APART_TEXT = {"work": "仕事から帰ってきた。今日の稼ぎは {amount}円", "_back": "戻ってきた", "go_work": "仕事に出かけた",
              "go_out": "ちょっと出かけた", "go_sleep": "寝ることにした", "go_leave": "ひと休みすることにした",
              "go_busy": "作業を始めた", "_return": "家に戻った"}
DEFAULTS = {"gain_cap_affection": 6, "gain_cap_trust": 5, "cool_after_days": 3, "cool_per_day": 0.5, "cool_floor": 25,
            "drift_apart_days": 30, "visit_hours": 3, "meet_min_affection": 35, "deep_affection": 60, "jealousy_per_day": 0.6,
            "renotice_days": 7, "selfie_rate": 1.0}


class Bonds:
    def __init__(self, app):
        self.app = app

    def cfg(self):
        c = dict(DEFAULTS)
        c.update(self.app.world.get("bonds") or {})
        return c

    # ------------------------------------------------------------------ 記録
    def rec(self):
        ps = self.app.life.player_state()
        if "bonds" not in ps:
            # 以前からのワールドは, 選んでいたキャラと暮らしている. 新しく作ったワールドは誰とも暮らしていない
            meta = next((w for w in store.load_worlds().get("worlds") or [] if w["id"] == store.WORLD), {})
            cur = self.app.settings.get("active_character")
            if meta.get("alone"):       # 作ったときにくじで決めた間柄 (無ければ, 全員「連絡先」)
                ps["bonds"] = {cid: {"stage": s, "t": time.time()} for cid, s in (meta.get("start_bonds") or {}).items()}
            else:
                ps["bonds"] = {cur: {"stage": "live", "t": time.time()}} if cur else {}
            ps.setdefault("with", None)
            self.app.life.save_player()
        ps.setdefault("with", None)
        return ps

    def save(self):
        self.app.life.save_player()

    def stage(self, cid):
        return ((self.rec()["bonds"].get(cid) or {}).get("stage")) or "contact"

    def set_stage(self, cid, stage, now=None):
        ps = self.rec()
        if stage == "live":
            other = self.living()
            if other and other != cid:
                raise ValueError("一緒に暮らせるのは一人だけです（先に今の同居を解消してください）")
        prev = ps["bonds"].get(cid) or {}
        hist = dict(prev.get("hist") or {})          # 段階が変わった日 (記念日. core/anniv.py)
        if stage in ("contact", "visit", "live") and prev.get("stage") != stage:
            hist[stage] = now or time.time()
        ps["bonds"][cid] = {"stage": stage, "t": now or time.time(), "hist": hist}
        self.save()

    def living(self):
        for cid, b in self.rec()["bonds"].items():
            if b.get("stage") == "live" and cid in self.app.chars:
                return cid
        return None

    def with_rec(self):
        w = self.rec().get("with")
        if w and w.get("cid") not in self.app.chars:
            return None
        return w

    def mode(self, cid, t=None):
        """cid と一緒にいる形: home (同居して家にいる) / meet / visit / guest (招いている) / None (離れている).
        同居相手は, あなたも相手も家にいるときだけ home (あなたが外出・仕事中, 相手が自分の予定で出かけている間は離れている).
        t: その時刻での形 (時間経過のまとめ計算用. 間柄と with はいまのまま)."""
        w = self.with_rec()
        if w and w["cid"] == cid:
            return w["mode"]
        if w and w["mode"] != "guest":         # 外で会っている・相手の家にいる: 同居相手は家
            return None
        if self.living() == cid and self.home_together(cid, t):
            return "home"
        return None

    def home_together(self, cid, t=None):
        """同居相手とあなたが, どちらも家にいるか (時刻 t)."""
        app = self.app
        t = t or time.time()
        if app.presence.at(t) in ("out", "work"):
            return False
        char = app.chars.get(cid)
        if not char:
            return False
        return not app.scene_at(char, app.state(cid), _dt.datetime.fromtimestamp(t))["away"]

    def together(self, cid, t=None):
        return self.mode(cid, t) is not None

    def company(self, t=None):
        """いまそばにいる人たち (外で会っている人・招いた人・家にいる同居相手). 会っている人, 同居相手の順."""
        w = self.with_rec()
        out = [w["cid"]] if w and self.mode(w["cid"], t) else []
        live = self.living()
        if live and live not in out and self.mode(live, t):
            out.append(live)
        return out

    def alone_with(self, cid, t=None):
        """あなたと cid の二人きりか."""
        return self.company(t) == [cid]

    # ------------------------------------------------------------------ 会う・別れる
    def start(self, cid, mode, now=None):
        now = now or time.time()
        w = {"cid": cid, "mode": mode, "t": now}
        if mode in ("visit", "guest"):
            w["until"] = now + float(self.cfg()["visit_hours"]) * 3600
        self.rec()["with"] = w
        self.save()

    def end(self):
        w = self.rec().get("with") or {}
        if w.get("mode") == "guest":
            self.app.home.guest_left()          # 来客のあとは少し散らかる
            if w.get("cid") in self.app.chars:  # 帰った: 「あなたの家に遊びに来ている」を終える
                st = self.app.state(w["cid"])
                if (st.get("override") or {}).get("activity") == "guest":
                    st["override"] = None
                    self.app.save_state(w["cid"])
        if self.rec().get("with"):
            self.rec()["with"] = None
            self.save()

    def sync(self, cid, st, now):
        """外で会っていてお出かけの一時シーンが終わった / 遊びに来ていて時間が過ぎた → 別れる."""
        w = self.with_rec()
        if not w or w["cid"] != cid:
            return False
        ov = st.get("override")
        if w["mode"] == "meet" and not (ov and ov.get("until", 0) > now and ov.get("outing")):
            self.end()
            return True
        if w["mode"] in ("visit", "guest") and now >= w.get("until", 0):
            self.end()
            return True
        return False

    def apply(self, a, cid, now):
        """コマンドの bond 指定を反映 (反応が断り = override のときは呼ばない)."""
        b = a.get("bond")
        if b == "to_visit" and self.stage(cid) == "contact":
            self.set_stage(cid, "visit", now)
        elif b == "to_live":
            self.set_stage(cid, "live", now)
            self.end()
        elif b == "end_live" and self.stage(cid) == "live":
            self.set_stage(cid, "visit", now)
            self.end()
        elif b == "visit_start":
            self.start(cid, "visit", now)
        elif b == "guest_start":
            self.start(cid, "guest", now)
        elif b == "visit_end":
            self.end()

    # ------------------------------------------------------------------ 条件・表示
    def deep(self, cid):
        """あなたと深い仲か (家に行ける以上, または好感度が高い)."""
        if self.stage(cid) in ("visit", "live"):
            return True
        st = self.app.state(cid)
        return st["params"].get("affection", 0) >= float(self.cfg()["deep_affection"])

    def rivals(self, cid):
        return [o for o in self.app.chars if o != cid and self.deep(o)]

    def ctx(self, cid, st, t=None):
        m = self.mode(cid, t)
        known = st.get("jealous") or {}
        rv = self.rivals(cid)
        live = self.living()
        now = time.time()
        char = self.app.chars.get(cid) or {"id": cid}
        return {"stage": self.stage(cid), "apart": m is None, "with_mode": m or "none", "company": len(self.company(t)),
                "living_other": bool(live and live != cid), "rivals": len(rv),
                "rivals_known": sum(1 for o in rv if o in known),
                # 現実的な深まり方: 最近の交流日数 / ご無沙汰の日数 / 提案を受ける気持ち / 贈り物・お金の受け止め方
                "met_14d": self.freq(st, now), "gap_d": round(self.gap_days(st, now), 2),
                # 連絡しすぎ: 24 時間の連絡 (種類ごとの重み. 会話の返事は数えず, 追いメッセージは重め) が,
                # 性格 (approach)・間柄・相手からの連絡の多さ・相手の状況で決まる許容を超えた
                "contacts_24h": round(self._contacts(st, now), 1),
                "too_often": self._contacts(st, now) > self.tolerance(char, cid, st, now),
                "ready": self.readiness(char, st, now), "gift_feel": self.gift_feel(char, st, now),
                "money_feel": self.gift_feel(char, st, now, money=True)}

    def allowed_apart(self, a, cid=None):
        if cid and self.stage(cid) == "known":     # 連絡先を知らない: 連絡も誘いもできない
            if a.get("category") in ("連絡", "会う") or (a.get("override") or {}).get("outing"):
                return False
        if "apart" in a:
            return bool(a["apart"])
        return a.get("category") in APART_CATEGORIES or bool((a.get("override") or {}).get("outing") and a.get("home_only"))

    def view(self, cid):
        m = self.mode(cid)
        w = self.with_rec()
        label = {"home": "家で一緒", "meet": "外で会っている", "visit": "%sの家に来ている" % self.app.chars[cid].get("name", ""),
                 "guest": "あなたの家に来ている", None: "離れている"}[m]
        if m is None and self.living() == cid:
            label = "一緒に暮らしている（いまは離れている）"
        return {"stage": self.stage(cid), "stage_label": STAGE_LABEL[self.stage(cid)], "mode": m, "label": label,
                "living": self.living(), "until": (w or {}).get("until") if m in ("visit", "guest") else None}

    def list_view(self):
        return {cid: {"stage": self.stage(cid), "mode": self.mode(cid)} for cid in self.app.chars}

    # ------------------------------------------------------------------ 嫉妬
    def jealousy(self, char):
        """嫉妬の強さ: 性格 × 依存度 (依存しているほど強い)."""
        st = self.app.state(char["id"])
        return float(self.app.traits(char).get("jealousy", 1)) * (1 + 0.5 * self.app.attach.factor(char, st, "dependence"))

    # ------------------------------------------------------------------ 現実的な深まり方
    @staticmethod
    def _day(t):
        return _dt.date.fromtimestamp(t).isoformat()

    def touch(self, st, now):
        """あなたと交流した (会った・話した・連絡した) 日を記録する."""
        st["last_touch"] = now
        days = st.setdefault("touch_days", [])
        d = self._day(now)
        if d not in days:
            days.append(d)
            del days[:-30]

    def met(self, st, now, contact=False):
        """会った (contact=False) / スマホで連絡した (contact=True) 日時を覚える (関係性の「最後に会った・連絡した」)."""
        st["last_contact" if contact else "last_met"] = now

    @staticmethod
    def learn(st, kind, text, now):
        """あなたが知ったこと (like = 好きなもの / dislike = 苦手なもの / heard = 聞いた話). 同じことは一つに."""
        if not text:
            return
        known = st.setdefault("known", [])
        for k in known:
            if k["kind"] == kind and k["text"] == text:
                k["t"] = now
                return
        known.append({"kind": kind, "text": text, "t": now})
        del known[:-30]

    def remember(self, char, st, now):
        """本人から聞いた出来事 (機嫌の理由のうち, 話してもらったもの) を「聞いた話」として覚える."""
        call = self.app.pronouns(char)[2]
        for r in st.get("reasons") or []:
            if r.get("kind") == "event" and r.get("told") and r.get("tell") and not r.get("_heard"):
                r["_heard"] = True
                self.learn(st, "heard", r["tell"].replace("{call}", call), r.get("t", now))

    def freq(self, st, now, days=14):
        """最近 days 日のうち, 交流した日数."""
        since = self._day(now - days * 86400)
        return sum(1 for d in st.get("touch_days") or [] if d > since)

    def gap_days(self, st, now):
        return max(0.0, now - st.get("last_touch", st.get("created", now))) / 86400.0

    def trait(self, char, k, default=0.0):
        return float(self.app.traits(char).get(k, default))

    def realize(self, char, st, eff, key, now, gift=None):
        """交流で動く好感度・信頼を, 現実的にする. (直した効果, 添えるナレーション or None) を返す.
        key: 繰り返しを数える目印 (コマンド id など. None なら数えない).
        gift: "item" / "money" なら性格の贈り物の感じ方 (gift 倍率) をかける."""
        c = self.cfg()
        gd = st.get("gain_day") or {}
        if gd.get("d") != self._day(now):
            gd = {"d": self._day(now), "affection": 0.0, "trust": 0.0, "acts": {}}
        st["gain_day"] = gd
        n = gd["acts"].get(key, 0) if key else 0
        if key:
            gd["acts"][key] = n + 1
        eff = dict(eff)
        pos = [k for k in ("affection", "trust") if float(eff.get(k, 0)) > 0]
        note = None
        # 同じことの繰り返し: 3 回目あたりから, うんざりされることがある
        if pos and n >= 2 and random.random() < min(0.5, 0.12 * (n - 1)):
            for k in pos:
                eff[k] = -0.4 * float(eff[k])
            eff["mood"] = float(eff.get("mood", 0)) - 2
            return eff, "（{name}は、同じことの繰り返しに少しうんざりしているようだ）"
        mood_f = 0.5 if st["params"].get("mood", 50) < 35 else 1.0
        gift_f = self.trait(char, "gift", 1.0) if gift else 1.0
        for k in pos:
            used = gd.get(k, 0.0)
            v = float(eff[k]) * random.uniform(0.5, 1.25) * mood_f * gift_f / (1 + used / float(c["gain_cap_" + k]))
            gd[k] = used + v
            eff[k] = v
        return eff, note

    # ---- 連絡しすぎ. st["contacts"] は あなたから送った連絡 [{t, w}] (以前の記録は時刻だけ: 1 回と数える)
    CONTACT_W = {"greet_morning": 0.5, "greet_night": 0.5, "stamp": 0.5, "_phone": 1.5}     # 種類ごとの重み (ほかは 1)
    FOLLOWUP_W = 1.5         # 返事がないのに続けて送った (追いメッセージ) ときの倍率
    HER_BONUS_MAX = 4        # 相手からよく来るときに増える, 我慢できる回数の上限

    @staticmethod
    def contact_t(x):
        return x["t"] if isinstance(x, dict) else float(x)

    @staticmethod
    def contact_w(x):
        return float(x.get("w", 1.0)) if isinstance(x, dict) else 1.0

    @classmethod
    def _contacts(cls, st, now):
        """直近 24 時間の連絡の多さ (重みの合計)."""
        return sum(cls.contact_w(x) for x in st.get("contacts") or [] if now - cls.contact_t(x) < 86400)

    def contact_weight(self, char, st, kind, now, phone=False):
        """これから送る連絡の重み: 挨拶・スタンプは軽く, 電話は重め. 相手から返事 (・メッセージ) が来たあとの 1 通は会話なので
        数えない (0). 返事がないのに続けて送る (返事待ちの間・既読のまま 6 時間のうち) と重め (追いメッセージ)."""
        w = self.CONTACT_W["_phone" if phone else kind] if (phone or kind in self.CONTACT_W) else 1.0
        items = [it for it in self.app.chat.load(char["id"])["items"] if it.get("who") in ("me", "her")]
        mine = [self.contact_t(x) for x in st.get("contacts") or []]
        last_me = max(mine) if mine else 0
        last_her = max([it["t"] for it in items if it["who"] == "her"] or [0])
        if not phone and (st.get("approach") or last_her > last_me):
            return 0.0                                   # 相手が話しかけてきた・返事をくれたあとの返事
        if st.get("msg_pending") or (last_me and last_me > last_her and now - last_me < 6 * 3600):
            w *= self.FOLLOWUP_W                         # 返事がないのに続けて送る
        return w

    def history_weights(self, items):
        """トークの記録から, あなたが送った連絡を時刻順に組み直す: [(時刻, 重み, 種類)] (以前の記録の置き換え・判定し直し用).
        あなたの発言 (謝るは除く) と, あなたがかけた電話 (📞). 重みの決まりは contact_weight と同じ (相手の発言のあとの 1 通は会話で 0,
        相手の返事がないまま 6 時間のうちに続けて送ると追いメッセージで重め)."""
        out, last_me, last_her = [], 0.0, 0.0
        for it in sorted(items, key=lambda x: x["t"]):
            who, kind = it.get("who"), it.get("kind")
            if who == "her":
                last_her = it["t"]
                continue
            phone = who == "sys" and kind == "call" and str(it.get("text", "")).startswith("📞")
            if not (who == "me" and kind != "apology") and not phone:
                continue
            w = self.CONTACT_W["_phone" if phone else kind] if (phone or kind in self.CONTACT_W) else 1.0
            if not phone and last_her > last_me:
                w = 0.0
            elif last_me and last_me > last_her and it["t"] - last_me < 6 * 3600:
                w *= self.FOLLOWUP_W
            out.append((it["t"], w, "_phone" if phone else kind))
            last_me = it["t"]
        return out

    def tolerance(self, char, cid, st=None, now=None):
        """我慢できる連絡の多さ: 性格 (甘えたがりほど平気)・間柄・相手からの連絡の多さ (上限あり)・相手の状況
        (仕事中・手が離せないと減り, 機嫌がいい・寂しいと少し増える)・その日の揺らぎ."""
        base = 2 + 2 * float(self.app.traits(char).get("approach", 1)) \
            + {"known": 0, "contact": 0, "visit": 2, "live": 4}.get(self.stage(cid), 0)
        if st is None:
            return base
        now = now or time.time()
        her = sum(1 for it in self.app.chat.load(cid)["items"] if it.get("who") == "her" and 0 <= now - it["t"] < 86400)
        base += min(self.HER_BONUS_MAX, her)
        p = st["params"]
        scene = self.app.scene_at(char, st, _dt.datetime.fromtimestamp(now))
        if scene.get("busy"):
            base *= 0.6
        base += (1.0 if p.get("mood", 50) >= 65 else 0.0) + (1.0 if p.get("loneliness", 0) >= 60 else 0.0)
        fd = self.app.attach.factor(char, st, "dependence")      # 依存しているほど, 連絡が多くても平気 (低くても少し減るだけ)
        base = max(1.0, base + (2.5 * fd if fd > 0 else 0.8 * fd))
        day = _dt.datetime.fromtimestamp(now).strftime("%Y%m%d")
        jitter = random.Random("%s:%s" % (cid, day)).uniform(-0.75, 0.75)      # その日の揺らぎ (一日のうちは同じ)
        return base + jitter

    def readiness(self, char, st, now):
        """段階の提案を受ける気持ち (目安 0〜100). 数値だけでなく, 最近の交流・ご無沙汰・性格・その日の気分で揺れる."""
        p = st["params"]
        return round(50 + (p.get("affection", 40) - 60) + 0.8 * (p.get("trust", 40) - 50) + 4 * (self.freq(st, now) - 4)
                     - 5 * max(0.0, self.gap_days(st, now) - 3) + self.trait(char, "caution") + random.uniform(-20, 20), 1)

    def exchange_chance(self, char, st):
        """知り合いと偶然会って話したとき, 連絡先を交換する確率 (0.05〜0.85).
        あなたの会話スキル・相手の機嫌と好感度・性格 (慎重さ) しだい. 何度会っても必ず交換する, とはしない."""
        p = st["params"]
        score = 0.6 * (p.get("mood", 50) - 50) + 0.3 * (p.get("affection", 40) - 40) \
            + 0.4 * (self.app.life.skill("talk") - 30) + 1.5 * self.trait(char, "caution")
        return round(max(0.05, min(0.85, 0.4 + score / 100.0)), 3)

    def gift_feel(self, char, st, now, money=False):
        """贈り物・お金を素直に喜べるか (目安 0〜100). 仲の浅さ・最近の贈り物の多さ・機嫌・性格しだい."""
        p = st["params"]
        recent = sum(1 for t in st.get("gifts") or [] if now - t < 7 * 86400)
        f = 50 + 0.8 * (p.get("affection", 40) - 50) + 0.5 * (p.get("trust", 40) - 50) - 15 * recent \
            + 0.3 * (p.get("mood", 50) - 50) + random.uniform(-20, 20)
        if money:
            f += self.trait(char, "money") - (15 if self.stage(char["id"]) in ("known", "contact") else 0)
        return round(f, 1)

    def cool_down(self, char, st, t, h):
        """しばらく交流がないと, 好感度・信頼が少しずつ冷める. 長く会わないと家に行ける仲も遠のく (同居は除く)."""
        cid = char["id"]
        stage = self.stage(cid)
        if stage == "live" or "last_touch" not in st:
            return
        c = self.cfg()
        gap = (t - st["last_touch"]) / 86400.0
        if gap < float(c["cool_after_days"]):
            return
        r = float(c["cool_per_day"]) * h / 24.0
        floor = float(c["cool_floor"])
        p = st["params"]
        if p.get("affection", 0) > floor:
            p["affection"] = max(floor, p["affection"] - r)
        if p.get("trust", 0) > floor:
            p["trust"] = max(floor, p["trust"] - r * 0.6)
        if stage == "visit" and gap >= float(c["drift_apart_days"]):
            self.set_stage(cid, "contact", t)
            self.app.life.add_reason(st, "player", "bad", "%sとしばらく会っていなくて、少し距離ができた" % self.app.pronouns(char)[2],
                                     t, told=False, action="_drift")

    def step(self, char, st, t, h):
        """時間経過: ご無沙汰で冷める. あなたと深い仲のキャラが, あなたとほかの人との深い仲に気づくかどうか."""
        cid = char["id"]
        self.cool_down(char, st, t, h)
        if len(self.app.chars) < 2 or not self.deep(cid):
            return
        c = self.cfg()
        j = self.jealousy(char)
        known = st.setdefault("jealous", {})
        for o in self.rivals(cid):
            if t - known.get(o, -1e18) < float(c["renotice_days"]) * 86400:
                continue
            rate = float(c["jealousy_per_day"]) / 24.0 * j
            rate *= 3 if self.stage(cid) == "live" else 1          # 一緒に暮らしていると気づきやすい
            rate *= 2 if self.stage(o) == "live" else 1
            rate *= 1.5 if self.app.relation(cid, o)["knows"] else 1
            if random.random() >= 1 - math.exp(-rate * h):
                continue
            self.notice(char, st, o, t, again=o in known)

    def notice(self, char, st, other, t, again=False):
        cid = char["id"]
        j = self.jealousy(char)
        k = j * (1.5 if self.stage(cid) == "live" else 1) * (0.5 if again else 1)
        eff = {"mood": -8 * k, "trust": -6 * k, "affection": -3 * k}
        deltas = self.app.apply_effects(st, self.app.trait_effects(char, eff))
        st.setdefault("jealous", {})[other] = t
        name = self.app.chars[other].get("name", other)
        call = self.app.pronouns(char)[2]
        tell = "%sが%sと親しくしている" % (call, name) + ("のが、まだ続いている" if again else "")
        self.app.life.add_reason(st, "player", "bad", tell, t, told=False, delta=deltas.get("mood", 0), action="_jealous")
        r = self.app.relation(cid, other)
        self.app.change_affinity(cid, other, -10 * j if r["knows"] else -5 * j)
        return deltas

    # ------------------------------------------------------------------ 自撮り
    def selfie_chance(self, ctx):
        """メッセージに自撮りが添えられる確率. 機嫌・好感度・ドキドキが高い (テンションが上がっている) ときほど."""
        f = 0.04 + max(0.0, ctx.get("mood", 50) - 50) / 250.0 + max(0.0, ctx.get("affection", 50) - 40) / 400.0 \
            + max(0.0, ctx.get("heart", 0) - 30) / 500.0 - max(0.0, ctx.get("stress", 0) - 50) / 300.0
        return max(0.0, min(0.35, f * float(self.cfg()["selfie_rate"])))
