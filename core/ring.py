"""相手からかかってくる電話 (A23 段 2). 出れば, 段 1 の電話の対話 (core/phonetalk.py) が by="her" で始まる.

かかってくる流れ (via):
- sudden : 急に. 離れている相手の働きかけの抽せん (presence.live → fire) が「話そう」(msg_chat) に当たったとき,
           メッセージの代わりに電話にすることがある (want_call). 理由は「話そう」の理由 (退屈・疲れ・いいこと・寂しい・探り・何かあった).
- asked  : メッセージから.「電話していい？」(st.call_ask) → トークで「いいよ」と返すと, 少しして鳴る. 断る・放っておくと鳴らない.
- back   : 段 1 の「またかけるね」(st.call_back) のかけ直し. 30〜150 分あと, 相手の手が空いていれば.
- req    : 頼みごと. 急な誘い (appoint._maybe_now)・看病 (appoint.care_call)・頼まれごと (appoint.favor_offer) を, メッセージではなく
           電話で切り出す (offer). 約束の記録はいままでどおり (phone: True の印). 出れば最初のひとことが頼みごとで, 受ける / あとで返事する /
           断る から選ぶ (phonetalk の req の切れ目). 出なければ, いままでどおりメッセージで届く.
鳴っている間 (RING_SEC) に出なければ不在着信 (missed). 「出ない」を押すと拒否 (declined: 見ていたのが伝わるので重い).
寝ると告げている間は出られない (asleep: 軽い).
割り込み (catch. A23 段 3): ほかの人と通話中でも鳴る (rec の catch = いまの通話の相手). 出ない・鳴り終わる → 話し中 (busy: 軽い) /
少し出て, かけ直すと伝える (back: 軽く. st["call_promise"]. PROMISE_H のうちにあなたからかければ済み, かけなければ心当たりに.
いまの相手は少し待たされ, 詮索しがちなら「誰から？」) / いまの電話を切って出る (switch: いまの相手は phonetalk の why=switch).
不在着信の重さは, あなたが電話に出る時間帯を相手が覚えているか (regard.call_ease) で揺れる: ふだん出ない時間なら軽く, ふだん出るのに
出ないと重い. 覚える前は少し重い. 覚えた枠に合わせて, ふだん出る時間にかけてくる (want_call).
頻度: 働きかけの抽せんと同じ枠 (メッセージの代わり) で, そのうえ着信どうしは GAP_H あけ, 1 日 DAY_MAX まで (かけ直し・頼みごとは別).
閉じている間 (offline): 閉じていた間のまとめ (offline.simulate) の中で, かけ直しと, まれな急な着信を決める. そのときあなたが
寝ていた・仕事中なら不在着信, ほかは短く無難に出たことに (やりとりはせず, 効き目は弱め).
記録: presence.rec()["ring"] = {id, cid, name, t, until, via, why, req, req_kind, req_text, sys_t}.
"""
import random
import time
import uuid
from datetime import datetime

RING_SEC = (20.0, 40.0)          # 鳴っている秒
GAP_H = 2.0                      # 着信どうしの間 (時間)
DAY_MAX = 2                      # 1 日にかけてくる上限 (かけ直し・頼みごとは別)
BACK_DELAY = (30, 150)           # かけ直しまでの分
BACK_KEEP = 12 * 3600            # これを過ぎたら, かけ直さない
ASK_WAIT = 20 * 60               # 「電話していい？」の返事を待つ秒
ASK_RING = (8.0, 30.0)           # 「いいよ」から鳴るまでの秒
WANT_BASE = 0.14                 # 「話そう」がメッセージでなく電話になる割合のもと
WHY_W = {"lonely": 1.5, "happy": 1.4, "tired": 1.2, "bored": 0.8, "unsure": 1.0, "changed": 1.3}
REQ_P = {"care": 0.55, "now": 0.35, "favor": 0.2}       # 頼みごとを電話で切り出す割合のもと (急ぐものほど)
MISS_W = {"missed": 1.0, "declined": 1.6, "busy": 0.35, "asleep": 0.5, "offline": 0.6}
OFFLINE_RATE = 0.02              # 閉じている間の, 急な着信 (1 時間あたり. × 連絡したさ × 性格)
OFFLINE_EFF = {"loneliness": -3, "boredom": -2, "mood": 0.5}
HOW_LABEL = {"missed": "出なかった", "declined": "出なかった（切った）", "busy": "話し中だった", "asleep": "寝ていて出られなかった",
             "offline": "出られなかった"}
REQ_RETURNS = [("yes", "受ける", "🙆"), ("later", "あとで返事する", "⏳"), ("no", "断る", "🙅")]
ANSWERS = [("yes", "出る"), ("no", "出ない")]
CATCH_ANSWERS = [("back", "少し出て、かけ直すと伝える"), ("switch", "今の電話を切って出る"), ("no", "出ない")]
PROMISE_H = 3.0                  # 「あとでかけ直す」と伝えてから, あなたからかけるまでの猶予 (時間)


class Ring:
    def __init__(self, app):
        self.app = app

    def rec(self):
        return self.app.presence.rec().get("ring")

    # ------------------------------------------------------------------ かけられるか
    def _free(self, char, st, now):
        sc = self.app.scene_at(char, st, datetime.fromtimestamp(now))
        return not (sc.get("asleep") or sc.get("busy"))

    def why_not(self, char, st, now, strict=True):
        """いまかけてこない理由 (かけてくるなら None). strict: 間隔・1 日の上限も見る (かけ直し・頼みごとは見ない)."""
        app = self.app
        cid = char["id"]
        if self.rec():
            return "ほかの着信が鳴っている"
        c = app.phonetalk.rec()
        if c and c.get("cid") == cid:
            return "いま話している"
        if app.bonds.together(cid) or app.bonds.stage(cid) == "known":
            return "そばにいる / 連絡先を知らない"
        if not self._free(char, st, now):
            return "相手が寝ている・手が離せない"
        if app.phase_at(datetime.fromtimestamp(now)).get("id") in ("midnight", "dawn") and not app.phonetalk.close_rel(char, st):
            return "夜中"
        if strict:
            log = [t for t in st.get("ring_log") or [] if now - t < 86400]
            if log and now - max(log) < GAP_H * 3600:
                return "少し前にかけた"
            if len(log) >= DAY_MAX:
                return "今日はもう何度かかけた"
        return None

    def want_call(self, char, st, why, now):
        """「話そう」をメッセージでなく電話にするか (急に / 電話していい？ / しない)."""
        app = self.app
        if self.why_not(char, st, now):
            return None
        close = app.phonetalk.close_rel(char, st)
        p = WANT_BASE * WHY_W.get(why, 1.0) * (1.6 if close else 0.8) * float(app.traits(char).get("approach", 1.0))
        k = app.regard.call_known(char, st, now)
        if k:                                      # あなたが電話に出る時間を覚えていれば, ふだん出る時間にかける
            p *= 0.3 + 0.9 * k[1]
        if random.random() >= min(0.6, p):
            return None
        # いきなりかけるか, 先に聞くか: 近い仲・寂しい・何かあったと思ったときほど, いきなり
        direct = 0.25 + (0.35 if close else 0) + (0.2 if why in ("lonely", "changed") else 0)
        return "sudden" if random.random() < direct else "asked"

    # ------------------------------------------------------------------ 鳴らす
    def start(self, char, st, now, via, why=None, req=None, req_kind=None, req_text=None):
        """鳴らす. 鳴らせなかった (あなたが画面を閉じている / 寝ている / 話し中) ときは, その場で不在着信などにして None."""
        app = self.app
        pres = app.presence.at(now)
        st.setdefault("ring_log", [])
        st["ring_log"] = [t for t in st["ring_log"] if now - t < 86400] + [now]
        r = {"id": uuid.uuid4().hex[:8], "cid": char["id"], "name": char.get("name", ""), "t": now,
             "until": now + random.uniform(*RING_SEC), "via": via, "why": why, "req": req, "req_kind": req_kind, "req_text": req_text}
        app.trace.add("call", "電話をかけてきた (%s)" % via, char["id"], now, why=why, req=req_kind, presence=pres)
        app.picked_up_phone(char, st, now)
        if pres == "gone":                         # 家の画面を閉じている (スマホで進めている間): 閉じている間と同じ決め方
            bl = app.offline.blocks(now - 1, now + 1)        # 閉じている間の行動パターン (いま何をしていることになっているか)
            self._closed(char, st, r, now, bl[-1][2].get("do") if bl else None)
            return None
        if pres == "sleep":
            self._missed(char, st, r, now, "asleep")
            return None
        c = app.phonetalk.rec()
        if c:                                      # ほかの人と話している: 割り込みで鳴る (出なければ話し中)
            r["catch"] = c.get("cid")
        app.presence.rec()["ring"] = r
        app.presence.save()
        app.save_state(char["id"])
        return r

    def tick(self, now=None):
        """鳴っている電話を now まで進める (鳴り終わっていれば不在着信)."""
        now = now or time.time()
        r = self.rec()
        if not r:
            return None
        app = self.app
        if r["cid"] not in app.chars:
            app.presence.rec().pop("ring", None)
            app.presence.save()
            return None
        if now < r["until"]:
            return None
        app.presence.rec().pop("ring", None)
        char, st = app.char(r["cid"]), app.state(r["cid"])
        self._missed(char, st, r, r["until"], "busy" if self._catching(r) else "missed")
        app.presence.save()
        return r

    def _catching(self, r):
        """割り込みの着信か (いまも, その通話が続いている)."""
        c = self.app.phonetalk.rec()
        return bool(r.get("catch")) and bool(c) and c.get("cid") == r["catch"]

    # ------------------------------------------------------------------ 出る / 出ない
    def answer(self, yes, now=None, how=None):
        """出る (yes) / 出ない. 割り込みの着信は how: back (少し出て, かけ直すと伝える) / switch (いまの電話を切って出る) / no."""
        now = now or time.time()
        app = self.app
        self.tick(now)
        r = self.rec()
        if not r:
            raise ValueError("いまは電話が鳴っていません")
        catching = self._catching(r)
        how = how or ("yes" if yes else "no")
        if how not in [k for k, _ in (CATCH_ANSWERS if catching else ANSWERS)]:
            raise ValueError("出る・出ない を選んでください" if not catching else "ほかの人と話している途中です（出ない・かけ直すと伝える・今の電話を切って出る から）")
        app.presence.rec().pop("ring", None)
        char, st = app.char(r["cid"]), app.state(r["cid"])
        if how == "no":
            self._missed(char, st, r, now, "busy" if catching else "declined")
            app.presence.save()
            return {"declined": True}
        if how == "back":
            return self._promise(char, st, r, now)
        if how == "switch":
            app.phonetalk.switch(now)
        app.facetalk.interrupt(now, "phone")            # 会って話している途中なら, 話は終わる (core/facetalk.py)
        if app.phonetalk.rec():
            app.presence.save()
            raise ValueError(app.call_block())
        app.presence.rec()["beat"] = app.presence.rec()["input"] = now
        app.regard.note_call(char, st, r["t"], True)
        app.regard.sign(char, st, "call_answered", now)
        app.bonds.met(st, now, contact=True)
        key = "phone.ring_req" if r.get("req") else "phone.ring_" + (r.get("via") if r.get("via") in ("back", "asked") else r.get("why") or "bored")
        from .phonetalk import LINES
        said = app.phonetalk.line(char, key if key in LINES else "phone.ring_bored")
        app.chat.add(r["cid"], "sys", "📞 電話がかかってきた", kind="call", t=now)
        sys_t = app.chat.load(r["cid"])["items"][-1]["t"]
        c = app.phonetalk.begin(char, st, said, True, now, by="her", sys_t=sys_t)
        c["via"], c["why"] = r.get("via"), r.get("why")
        if r.get("req"):                           # 頼みごと: 最初のひとことのあとに切り出す
            app.phonetalk.req_beat(char, st, c, r, now + 0.5)
        st.pop("call_back", None)
        st.pop("call_promise", None)
        app.trace.add("call", "かかってきた電話に出た", r["cid"], now, via=r.get("via"), why=r.get("why"), req=r.get("req_kind"))
        app.save_state(r["cid"])
        app.presence.save()
        return {"call": app.phonetalk.view(now)}

    def _missed(self, char, st, r, t, how):
        """出なかった: 不在着信 (トークに残る). 重さは出なかった形と, あなたの出る時間帯の癖で揺れる. 頼みごとはメッセージで届く."""
        app = self.app
        cid = char["id"]
        ease = app.regard.call_ease(char, st, r["t"], t) if how in ("missed", "offline") else 1.0
        w = MISS_W[how] * ease * max(0.4, float(app.traits(char).get("absence", 1.0))) \
            * (1 + 0.4 * max(0.0, app.attach.factor(char, st, "dependence"))) * random.uniform(0.7, 1.3)
        if r.get("via") == "asked" and how in ("missed", "declined"):
            w *= 1.3                                # いいよと言ったのに
        d = round(min(8.0, 2.5 * w), 1)
        app.apply_effects(st, {"mood": -d}, t)
        if how != "busy":
            app.regard.note_call(char, st, r["t"], False)
        app.regard.sign(char, st, "call_missed", t, k=min(1.6, w))
        if d >= 2.5 and how in ("missed", "declined"):
            app.life.add_reason(st, "player", "bad", "電話したのに、{call}が出てくれなかった" if how == "missed"
                                else "電話を、{call}に切られた", t, told=False, delta=-d, action="_ring_missed")
        app.chat.add(cid, "sys", "📞 不在着信（%s）" % HOW_LABEL[how], kind="missed_call", t=t)
        st.pop("call_back", None)
        if r.get("req"):                            # 頼みごと: いままでどおりメッセージで (トークから答えられる)
            app.appoint.post_offer(r["req"], t + 30)
        elif how in ("missed", "declined") and random.random() < 0.55 + (0.2 if app.phonetalk.close_rel(char, st) else 0):
            key = "phone.ring_declined_msg" if how == "declined" else "phone.ring_missed_msg"
            app.chat.add(cid, "her", app.phonetalk.line(char, key), kind="call_missed_msg", t=t + random.uniform(40, 240))
        app.trace.add("call", "不在着信 (%s)" % how, cid, t, via=r.get("via"), why=r.get("why"), req=r.get("req_kind"),
                      ease=round(ease, 2), mood=-d)
        app.save_state(cid)

    def _promise(self, char, st, r, now):
        """割り込みの着信に少し出て, あとでかけ直すと伝えた. いまの通話の相手は少し待たされる."""
        app = self.app
        cid = char["id"]
        w = random.uniform(0.6, 1.2) * (1.3 if r.get("why") in ("lonely", "tired") or r.get("req") else 1.0)
        app.apply_effects(st, {"mood": -round(0.8 * w, 1)}, now)
        st["call_promise"] = {"t": now, "until": now + PROMISE_H * 3600}
        st.pop("call_back", None)
        app.regard.note_call(char, st, r["t"], True)
        app.chat.add(cid, "sys", "📞 電話がかかってきた（話し中だったので、あとでかけ直すと伝えた）", kind="missed_call", t=now)
        if r.get("req"):                            # 頼みごとは, メッセージで (トークから答えられる)
            app.appoint.post_offer(r["req"], now + 30)
        app.phonetalk.catch_wait(cid, now)
        app.trace.add("call", "割り込みの着信: かけ直すと伝えた", cid, now, via=r.get("via"), why=r.get("why"))
        app.save_state(cid)
        app.presence.save()
        return {"promised": True, "call": app.phonetalk.view(now)}

    def promise_check(self, char, st, now):
        """「あとでかけ直す」と伝えたのに, かけないまま猶予を過ぎた: 軽く機嫌を下げ, 心当たりに."""
        pr = st.get("call_promise")
        if not pr or now < pr.get("until", 0):
            return False
        app = self.app
        st.pop("call_promise", None)
        w = random.uniform(0.7, 1.3) * max(0.5, float(app.traits(char).get("absence", 1.0))) \
            * (1 + 0.3 * max(0.0, app.attach.factor(char, st, "dependence")))
        d = round(min(5.0, 2.5 * w), 1)
        app.apply_effects(st, {"mood": -d}, pr["until"])
        app.life.add_reason(st, "player", "bad", "かけ直すと言ったのに、{call}からかかってこなかった", pr["until"], told=False,
                            delta=-d, action="_call_promise")
        app.regard.sign(char, st, "call_missed", pr["until"], k=0.8)
        app.trace.add("call", "かけ直すと言ったのに, かけなかった", char["id"], now, mood=-d)
        return True

    def _closed(self, char, st, r, t, doing):
        """家の画面を閉じている間の着信: 寝ていた・仕事中 → 出ない / それ以外 → 短く無難に出たことに (やりとりはせず, 弱め)."""
        app = self.app
        if doing in ("sleep", "work"):
            self._missed(char, st, r, t, "offline" if doing == "work" else "asleep")
            return "missed"
        cid = char["id"]
        eff = dict(OFFLINE_EFF)
        if r.get("why") in ("lonely", "tired"):
            eff["loneliness"] = -5
        app.apply_effects(st, eff, t)
        app.regard.note_call(char, st, r["t"], True)
        st.pop("call_back", None)
        app.chat.add(cid, "sys", "📞 電話がかかってきて、少しだけ話した（%d分ほど。閉じていたあいだ・自動）" % random.randint(2, 6),
                     kind="call", t=t)
        if r.get("req"):
            app.appoint.post_offer(r["req"], t + 60)
        app.trace.add("call", "閉じている間の着信に, 短く出た", cid, t, via=r.get("via"), why=r.get("why"))
        app.save_state(cid)
        return "auto"

    # ------------------------------------------------------------------ 電話していい？
    def ask(self, char, st, why, now):
        """「電話していい？」を送る (メッセージから)."""
        app = self.app
        st["call_ask"] = {"t": now, "until": now + ASK_WAIT, "why": why}
        st.setdefault("ring_log", [])
        app.chat.add(char["id"], "her", app.phonetalk.line(char, "phone.ring_ask"), kind="call_ask", t=now)
        app.picked_up_phone(char, st, now)
        app.trace.add("call", "電話していい？と聞いてきた", char["id"], now, why=why)
        app.save_state(char["id"])

    def ask_answer(self, cid, yes, now=None):
        now = now or time.time()
        app = self.app
        char, st = app.char(cid), app.state(cid)
        a = st.get("call_ask")
        if not a or a.get("ok") or now >= a["until"]:
            raise ValueError("いまは電話していいか聞かれていません")
        if yes:
            a["ok"] = True
            a["ring_at"] = now + random.uniform(*ASK_RING)
            app.chat.add(cid, "me", "（📞 いいよ、と返した）", kind="call_ask_ok", t=now)
        else:
            st.pop("call_ask", None)
            app.chat.add(cid, "me", "（📞 いまはちょっと、と返した）", kind="call_ask_no", t=now)
            w = random.uniform(0.6, 1.2) * (1.3 if a.get("why") in ("lonely", "tired") else 1.0)
            app.apply_effects(st, {"mood": -round(1.5 * w, 1)}, now)
            app.chat.add(cid, "her", app.phonetalk.line(char, "phone.ring_ask_no"), kind="call_ask_no", t=now + random.uniform(20, 90))
        app.chat.mark_read_by_her(cid, now)
        app.save_state(cid)
        return {"ok": True}

    def ask_view(self, st, now):
        a = st.get("call_ask")
        if not a or a.get("ok") or now >= a.get("until", 0):
            return None
        return {"t": a["t"], "until": a["until"]}

    # ------------------------------------------------------------------ 画面を開いている間 (state_view の心拍)
    def live(self, char, st, now):
        """電話していい？ の期限・いいよのあとの着信・またかけるね のかけ直し・かけ直すと伝えた約束の期限."""
        app = self.app
        self.promise_check(char, st, now)
        a = st.get("call_ask")
        if a:
            if a.get("ok") and now >= a.get("ring_at", 0):
                st.pop("call_ask", None)
                if not self.why_not(char, st, now, strict=False):
                    return self.start(char, st, now, "asked", why=a.get("why"))
                return None
            if not a.get("ok") and now >= a["until"]:
                st.pop("call_ask", None)            # 返事がないまま: 電話はしない (軽く気にする)
                app.apply_effects(st, {"mood": -round(random.uniform(0.5, 1.5), 1)}, now)
                app.trace.add("call", "電話していい？に返事がなかった", char["id"], now)
                return None
        cb = st.get("call_back")
        if cb:
            if now - cb.get("t", now) > BACK_KEEP:
                st.pop("call_back", None)
                return None
            if "due" not in cb:
                cb["due"] = cb.get("t", now) + random.uniform(*BACK_DELAY) * 60
            if now >= cb["due"] and not self.why_not(char, st, now, strict=False):
                st.pop("call_back", None)
                return self.start(char, st, now, "back")
        return None

    # ------------------------------------------------------------------ 頼みごとを電話で
    def offer(self, char, st, x, kind, text, now):
        """頼みごと (約束の誘い・看病・頼まれごと) を電話で切り出すか. 鳴らしたら True (メッセージは出さない)."""
        app = self.app
        if x.get("ask") or app.presence.at(now) not in ("here", "idle", "busy", "out", "work"):
            return False
        if self.why_not(char, st, now, strict=False):
            return False
        p = REQ_P.get(kind, 0.2) * (1.3 if app.phonetalk.close_rel(char, st) else 1.0) * float(app.traits(char).get("approach", 1.0))
        if random.random() >= min(0.8, p):
            return False
        x["phone"] = True
        x["offer_text"] = text
        spoken = (text or "").replace("📱", "").strip()
        if spoken.startswith("『") and "』" in spoken:
            spoken = spoken[1:spoken.index("』")]
        self.start(char, st, now, "req", req=x["id"], req_kind=kind, req_text=spoken)      # 出られなければ, その場でメッセージに (_missed)
        return True

    # ------------------------------------------------------------------ 閉じている間
    def offline(self, t0, t1, timeline):
        """閉じていた間 (offline.simulate): かけ直しと, まれな急な着信. あなたのしていたこと (timeline) で, 出ない / 短く出る."""
        app = self.app
        out = []
        h = (t1 - t0) / 3600.0
        if h <= 0:
            return out
        for cid, char in app.chars.items():
            if app.bonds.together(cid) or app.bonds.stage(cid) == "known":
                continue
            st = app.state(cid)
            when, via = None, None
            cb = st.get("call_back")
            if cb and cb.get("t", 0) < t1 and t1 - cb.get("t", 0) <= BACK_KEEP + h * 3600:
                t = max(t0, cb.get("due") or cb.get("t", t0) + random.uniform(*BACK_DELAY) * 60)
                when, via = self._free_at(char, st, t, t1), "back"
                if when is None:
                    st.pop("call_back", None)
            if when is None and h >= 0.5:
                ctx = app.context(char, st, datetime.fromtimestamp(t1))
                rate = OFFLINE_RATE * app.presence.eagerness_apart(ctx) * float(app.traits(char).get("approach", 1.0)) \
                    * (1.5 if app.phonetalk.close_rel(char, st) else 0.6)
                if random.random() < 1 - pow(2.718281828, -rate * min(h, 12)):
                    when, via = self._free_at(char, st, t0 + random.random() * (t1 - t0), t1), "sudden"
            if when is None or self.why_not(char, st, when, strict=via != "back") not in (None, "ほかの着信が鳴っている"):
                continue
            from . import msgreply
            why = msgreply.pick_why(char, st) if via == "sudden" else None
            st["ring_log"] = [x for x in st.get("ring_log") or [] if t1 - x < 86400] + [when]
            r = {"id": uuid.uuid4().hex[:8], "cid": cid, "t": when, "via": via, "why": why}
            doing = self._doing(timeline, when)
            res = self._closed(char, st, r, when, doing)
            out.append({"cid": cid, "name": char.get("name", ""), "t": when, "via": via, "res": res,
                        "label": HOW_LABEL["asleep" if doing == "sleep" else "offline"] if res == "missed" else "少しだけ話した（自動）"})
        return out

    def _free_at(self, char, st, t, t1):
        """t から t1 までで, 相手の手が空いている最初の時刻 (無ければ None)."""
        while t < t1:
            if self._free(char, st, t) and not (1 <= datetime.fromtimestamp(t).hour < 7):
                return t
            t += 20 * 60
        return None

    @staticmethod
    def _doing(timeline, t):
        for x in timeline or []:
            if x["t"] <= t < x.get("end", x["t"]):
                return x.get("do")
        return None

    # ------------------------------------------------------------------ 画面
    def view(self, now=None):
        now = now or time.time()
        self.tick(now)
        r = self.rec()
        if not r:
            return None
        catching = self._catching(r)
        return {"id": r["id"], "cid": r["cid"], "name": r.get("name", ""), "left": max(0, int(r["until"] - now)),
                "face": self.app.chat.face(r["cid"]),
                "catch": (self.app.chars.get(r["catch"]) or {}).get("name", "") if catching else None,
                "opts": [{"id": k, "label": l} for k, l in (CATCH_ANSWERS if catching else ANSWERS)]}
