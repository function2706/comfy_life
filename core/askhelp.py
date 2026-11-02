"""あなたから相手に手伝いを頼む (頼まれごとの逆向き): 約束の欄で「あなたの家」+「○○を手伝ってもらう」.

- 頼む: こちらからの誘いと同じく時間差で返事 (appoint.reply → reply). 受けるかは, 仲 (好感度・信頼・間柄)・世話焼き (carer)・
  献身度・心の開きやすさ (caution) と, 強欲度 (見返りが見込めない浅い仲だと乗り気でない). その時間に予定があれば別の日時か断り.
- 当日: 相手があなたの家に来る (with.mode = guest, with.help). 「🤝 手伝ってもらう」で始める. 最中は「○○を手伝ってくれている」.
  ひと休み・切り上げ (visit と同じ). 終わったら (時間が来れば. 画面を閉じていた間なら終わりの時刻で) 相手の出方を決める.
- 強欲度 (greed_eff): 性格の traits.greed (静的) + 懐具合 (金欠なら上がる・余裕があれば少し下がる) − 仲の近さ − 献身度. 0〜1.
  終わったあとの出方: お金を求める (強欲 × 浅い仲) / 「今度おごってよ」(貸し st.iou) / 何も求めない.
  お金を求められたら, 払う / 断る. 断ると機嫌・信頼が下がる (強欲なほど). 求められていなくても, あなたからお礼を渡せる
  (受け取るかは強欲度・近さ・お金への抵抗 traits.money. 近い仲で受け取らないのは「水くさい」).
- 貸し (st.iou): あなたがおごる (お金のかかることをあなたが払う) か贈り物で返せる. 5 日たつと一度言ってくる.
  14 日たっても返さなければ, うやむやになって機嫌・信頼が下がる (強欲なほど).
- 律儀さ (repay) は「相手が手伝ってもらったときに返すか」なので, ここでは使わない (律儀な人ほど自分が手伝ったときは求めない, ではなく
  求めるかは強欲度だけで決める).
"""
import random
import re
import time

from . import places as places_mod

KINDS = {"clean": ("大掃除", 3.0), "furniture": ("家具の組み立て", 2.0), "pc": ("パソコンの設定", 1.5), "carry": ("荷物の片付け", 1.5)}
REST_MIN, REST_MAX = 15, 2
STAY_AFTER_H = 1.0
IOU_REMIND_D, IOU_LAPSE_D = 5, 14
LINES = {
    "help.arrive": "来ましたよ、{call}。{what}、さっそく始めましょうか",
    "help.done_none": "これくらい、いいですよ。お礼なんて気にしないでください",
    "help.done_treat": "結構がんばりましたよね。……今度、何かおごってくださいね",
    "help.done_money": "あの……手伝った分、{amount}円くらいもらえたりしますか？",
    "help.paid": "ありがとうございます。じゃあ、遠慮なく",
    "help.refused": "……そうですか。まあ、いいですけど",
    "help.offer_yes": "え、いいんですか？ ……じゃあ、ありがたく",
    "help.offer_no": "いいですって。そういうの、水くさいですよ",
    "help.iou_paid": "これで、この前の手伝いの分はチャラですね",
}
SCENE_LABEL = {
    "help.arrive": "あなたが頼んだ手伝いに来た ({what})", "help.done_none": "手伝い終えて, 何も求めない",
    "help.done_treat": "手伝い終えて, 今度おごってと言う (貸し)", "help.done_money": "手伝い終えて, お金を求める ({amount})",
    "help.paid": "求めたお金を払ってもらった", "help.refused": "求めたお金を断られた",
    "help.offer_yes": "あなたからのお礼のお金を受け取る", "help.offer_no": "あなたからのお礼のお金を断る (水くさい)",
    "help.iou_paid": "おごってもらって, 手伝いの貸しが返った",
}


class AskHelp:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 値
    def greed(self, char, st, now=None):
        """その場の強欲度 (0〜1): 性格 + 懐具合 − 近さ − 献身度."""
        app = self.app
        g = float(app.traits(char).get("greed", 0.2))
        money = float(app.life.her_money(st).get("a", 0))
        g += 0.3 if money < 5000 else 0.15 if money < 15000 else (-0.1 if money > 80000 else 0.0)
        g -= 0.4 * app.earn.closeness(char["id"], st)
        g -= 0.25 * max(0.0, app.attach.factor(char, st, "devotion"))
        return max(0.0, min(1.0, g))

    def accept_chance(self, char, st):
        """頼まれて受ける見込み."""
        app = self.app
        p = st["params"]
        tr = app.traits(char)
        close = app.earn.closeness(char["id"], st)
        c = 0.15 + (p.get("affection", 50) - 50) / 100.0 + (p.get("trust", 50) - 50) / 160.0 + 0.3 * float(tr.get("carer", 0.3)) \
            + 0.15 * max(0.0, app.attach.factor(char, st, "devotion")) + float(tr.get("caution", 0)) / 50.0 \
            + (0.1 if app.bonds.stage(char["id"]) == "visit" else 0.0) - 0.25 * self.greed(char, st) * (1 - close) \
            + (p.get("mood", 50) - 50) / 150.0
        return max(0.03, min(0.9, c))

    def outcome_chances(self, char, st):
        """終わったあとの出方の見込み: (お金を求める, 今度おごって). 残りは何も求めない.
        お金はその場の強欲度 (浅い仲・金欠ほど). 「今度おごって」は強欲というより気安さでも言うので, 性格の強欲度を一部残す
        (近い仲でも気安い性格なら言う). おごっての見込みは, お金を求めなかったときのうちの割合."""
        g = self.greed(char, st)
        g0 = float(self.app.traits(char).get("greed", 0.2))
        close = self.app.earn.closeness(char["id"], st)
        pm = min(0.7, g * g * (1 - close) * 1.3)
        pt = min(0.6, (0.6 * g + 0.4 * g0) * (1 - 0.3 * close)) * (1 - pm)
        return pm, pt

    # ------------------------------------------------------------------ 頼む (約束の欄)
    def dos(self, cid):
        """約束の欄の「あなたの家」に出す, 手伝ってもらうこと."""
        if self.app.bonds.stage(cid) not in ("contact", "visit"):
            return []
        return [{"id": "_help:" + k, "name": "%sを手伝ってもらう" % v[0], "icon": "🤝"} for k, v in KINDS.items()]

    def propose(self, cid, t, kind, now=None):
        app = self.app
        now = now or time.time()
        char = app.char(cid)
        cid = char["id"]
        if kind not in KINDS:
            raise ValueError("その手伝いは頼めません")
        if app.bonds.stage(cid) not in ("contact", "visit"):
            raise ValueError("%sには、手伝いは頼めません" % char.get("name", ""))
        t = float(t)
        if t < now + 30 * 60 or t > now + 14 * 86400:
            raise ValueError("約束は 30 分後から 2 週間先までです")
        for x in app.appoint.open_with(cid):
            if abs(x["t"] - t) < 3 * 3600:
                raise ValueError("その時間の近くに、もう約束（か返事待ち）があります")
        label, h = KINDS[kind]
        x = {"id": "h" + str(int(now * 1000))[-9:] + str(random.randrange(10)), "cid": cid, "t": t, "place": places_mod.HOME_ME,
             "do": "_help:" + kind, "by": "me", "status": "asked", "made": now, "help": kind, "label": label, "h": h}
        app.appoint.all().append(x)
        app.appoint.save()
        from .appoint import fmt_when
        app.appoint._send(x, now, "（%s、%sを手伝ってほしいと頼んだ）" % (fmt_when(t, now), label))
        return x

    def reply(self, char, st, x, now, extra):
        """頼みへの返事 (時間差). (セリフの場面, 効果, 置き換え)."""
        app = self.app
        from datetime import datetime
        from .appoint import COUNTER_MAX, fmt_when
        extra = dict(extra, what=x.get("label", ""))
        busy = app.scheduled_scene(char, datetime.fromtimestamp(x["t"]))
        if busy["away"] or busy["busy"] or busy["asleep"]:
            alt = app.appoint._alt_time(char, x, now) if int(x.get("rounds", 0)) < COUNTER_MAX else None
            if alt and random.random() < 0.5 + 0.3 * float(app.traits(char).get("carer", 0.3)):
                x.update(t=alt, status="offered", made=now, by="her", rounds=int(x.get("rounds", 0)) + 1)
                app.appoint.save()
                return "help_counter", {}, dict(extra, when=fmt_when(alt, now))
            x["status"] = "declined"
            app.appoint.save()
            return "help_busy", {}, extra
        if random.random() < self.accept_chance(char, st):
            x["status"] = "set"
            x["plan"] = app.appoint._plan(char, st, x)
            app.appoint.save()
            app.manners.favor(st, "appoint", now)
            return "help_yes", {"mood": 1}, extra
        x["status"] = "declined"
        app.appoint.save()
        return "help_no", {}, extra

    # ------------------------------------------------------------------ 当日
    def rec(self, cid=None):
        w = self.app.bonds.with_rec()
        if not w or w.get("mode") != "guest" or not w.get("help") or (cid and w.get("cid") != cid):
            return None
        return w

    def arrive(self, x, now):
        """約束の時刻に, 相手があなたの家に来た."""
        app = self.app
        cid = x["cid"]
        char, st = app.chars[cid], app.state(cid)
        app.bonds.start(cid, "guest", now)
        w = app.bonds.with_rec()
        w["help"] = {"kind": x["help"], "label": x.get("label", ""), "h": float(x.get("h", 1))}
        w["until"] = max(float(w.get("until", 0)), now + (float(x.get("h", 1)) + STAY_AFTER_H + 0.5) * 3600)
        app.bonds.save()
        st["override"] = {"activity": "guest", "label": "手伝いに来てくれた", "location": "あなたの家", "until": w["until"],
                          "pos": "indoors, visiting, casual clothes", "neg": ""}
        app.presence.touch(now)
        app.solo.note("home", "%sが%sを手伝いに来てくれた" % (char.get("name", ""), x.get("label", "")), now)
        return app.note_entry(char, st, now, "_help_arrive", "手伝いに来てくれた", "🤝", self.line(char, "help.arrive", {"what": x.get("label", "")}))

    def auto(self, x, now):
        """閉じていた間の約束: 来てもらって, ひと通り手伝ってもらった (お金の話はその場で答えられないので, 貸しの形に)."""
        app = self.app
        cid = x["cid"]
        char, st = app.chars[cid], app.state(cid)
        h = float(x.get("h", 1))
        app.life.tire(4 * h)
        if x["help"] == "clean":
            app.home.clean(40, now=now)
        app.apply_effects(st, {"energy": -5 * h})
        app.attach.give(char, st, "her", 3, "手伝ってくれた")
        app.manners.favor(st, "help", now)
        pm, pt = self.outcome_chances(char, st)
        if random.random() < pm + pt:
            st["iou"] = {"t": now, "what": x.get("label", ""), "reminded": False}
            how = "今度何かおごってと言われた"
        else:
            how = "お礼はいいよと言われた"
        app.save_state(cid)
        return "%sに%sを手伝ってもらった。%s" % (char.get("name", ""), x.get("label", ""), how)

    def start(self, cid, now=None):
        app = self.app
        now = now or time.time()
        cid = cid or (self.rec() or {}).get("cid")
        with app.lock:
            w = self.rec(cid)
            if not w or w["help"].get("run") or w["help"].get("done"):
                raise ValueError("いまは手伝ってもらうことがありません")
            hp = w["help"]
            hp["run"] = {"t0": now, "until": now + hp["h"] * 3600, "rest": 0}
            w["until"] = max(float(w["until"]), now + (hp["h"] + STAY_AFTER_H) * 3600)
            app.bonds.save()
            char, st = app.chars[cid], app.state(cid)
            st["override"] = {"activity": "help_you", "label": "%sを手伝ってくれている" % re.sub("の手伝い$", "", hp["label"]),
                              "location": "あなたの家", "until": hp["run"]["until"],
                              "pos": app.FAVOR_POS.get(hp["kind"], "helping each other, indoors"), "neg": ""}
            e = app.note_entry(char, st, now, "_help_start", "手伝ってもらう", "🤝",
                               "（%sと一緒に%sに取りかかった。%g時間ほどかかりそうだ）" % (char.get("name", ""), hp["label"], hp["h"]))
            app.save_state(cid)
            return {"entry": e}

    def rest(self, cid, now=None):
        app = self.app
        now = now or time.time()
        cid = cid or (self.rec() or {}).get("cid")
        with app.lock:
            w = self.rec(cid)
            run = ((w or {}).get("help") or {}).get("run")
            if not run:
                raise ValueError("いまは手伝ってもらっていません")
            if run["rest"] >= REST_MAX:
                raise ValueError("さっき休んだばかりです（あとひと息）")
            run["rest"] += 1
            run["until"] += REST_MIN * 60
            run["t0"] += REST_MIN * 60
            w["until"] = max(float(w["until"]), run["until"] + STAY_AFTER_H * 3600)
            app.bonds.save()
            char, st = app.chars[cid], app.state(cid)
            if (st.get("override") or {}).get("activity") == "help_you":
                st["override"]["until"] = run["until"]
            app.save_state(cid)
            return {"entry": app.note_entry(char, st, now, "_help_rest", "ひと休み", "☕", "（%sとひと休みした。%d分ほど）" % (char.get("name", ""), REST_MIN))}

    def stop(self, cid, now=None):
        app = self.app
        now = now or time.time()
        cid = cid or (self.rec() or {}).get("cid")
        with app.lock:
            w = self.rec(cid)
            if not ((w or {}).get("help") or {}).get("run"):
                raise ValueError("いまは手伝ってもらっていません")
            return self._finish(cid, now)

    def live(self, cid, now):
        w = self.rec(cid)
        run = ((w or {}).get("help") or {}).get("run")
        if run and now >= run["until"]:
            return self._finish(cid, run["until"])
        return None

    def on_leave(self, now=None):
        """帰る (bonds.end の前): 最中ならそこで切り上げる."""
        now = now or time.time()
        w = self.rec()
        if w and w["help"].get("run"):
            return self._finish(w["cid"], min(now, w["help"]["run"]["until"]))
        return None

    def _finish(self, cid, t):
        """手伝いが終わった: 家のこと・疲れ・仲, そして相手の出方."""
        app = self.app
        w = self.rec(cid)
        hp = w["help"]
        run = hp.pop("run")
        h = max(0.0, (t - run["t0"]) / 3600.0)
        ratio = min(1.0, h / max(0.25, hp["h"]))
        char, st = app.chars[cid], app.state(cid)
        if (st.get("override") or {}).get("activity") == "help_you":
            st["override"] = dict(st["override"], activity="guest", label="あなたの家に来ている", until=w["until"])
        app.life.tire(8 * hp["h"] * ratio * 0.5)                  # あなたも一緒に手を動かした
        if hp["kind"] == "clean" and ratio >= 0.6:
            app.home.clean(40 * ratio, now=t)
        app.apply_effects(st, {"energy": -5 * h})
        hp["done"] = {"t": t, "h": round(h, 2), "full": ratio >= 0.6}
        what = re.sub("の手伝い$", "", hp["label"])
        if ratio < 0.6:                                           # あなたが早めに切り上げた: 見返りの話にはならない
            app.bonds.save()
            app.save_state(cid)
            e = app.note_entry(char, st, t, "_help_done", "手伝ってもらった", "🤝", "（%sを、途中で切り上げてもらった）" % what)
            return {"entry": e, "outcome": "short"}
        app.attach.give(char, st, "her", 3, "手伝ってくれた")
        app.manners.favor(st, "help", t)
        pm, pt = self.outcome_chances(char, st)
        r = random.random()
        if r < pm:
            amt = max(500, int(800 * hp["h"] * random.uniform(0.8, 1.3) / 500) * 500)
            hp["ask_money"] = amt
            key, extra, out = "help.done_money", {"amount": format(amt, ",")}, "money"
        elif r < pm + pt:
            st["iou"] = {"t": t, "what": hp["label"], "reminded": False}
            key, extra, out = "help.done_treat", {}, "treat"
        else:
            key, extra, out = "help.done_none", {}, "none"
        app.bonds.save()
        e = app.note_entry(char, st, t, "_help_done", "手伝ってもらった", "🤝",
                           "（%sが終わった）\n%s" % (what, self.line(char, key, extra)))
        app.save_state(cid)
        app.trace.add("askhelp", "手伝い終わり: %s" % out, cid, t, greed=round(self.greed(char, st), 2), pm=round(pm, 2), pt=round(pt, 2))
        return {"entry": e, "outcome": out}

    # ------------------------------------------------------------------ お金
    def pay(self, cid, yes, now=None):
        """求められたお金を払う / 断る."""
        app = self.app
        now = now or time.time()
        cid = cid or (self.rec() or {}).get("cid")
        with app.lock:
            w = self.rec(cid)
            amt = ((w or {}).get("help") or {}).get("ask_money")
            if not amt:
                raise ValueError("いまはお金の話はありません")
            char, st = app.chars[cid], app.state(cid)
            g = self.greed(char, st)
            if yes:
                if app.life.player_state().get("money", 0) < amt:
                    raise ValueError("お金が足りません")
                self._give_money(char, st, amt, now)
                d = app.apply_effects(st, app.trait_effects(char, {"mood": 2}))
                key = "help.paid"
            else:
                d = app.apply_effects(st, app.trait_effects(char, {"mood": -(2 + 2 * g), "trust": -(1 + g)}))
                app.life.add_reason(st, "player", "bad", "手伝ったのに、お礼を断られた", now, told=True, delta=d.get("mood", 0), action="_help")
                key = "help.refused"
            w["help"].pop("ask_money")
            w["help"]["settled"] = True
            app.bonds.save()
            e = app.note_entry(char, st, now, "_help_pay", "お礼", "💴", self.line(char, key, {}), d)
            app.save_state(cid)
            return {"entry": e}

    def offer_chance(self, char, st):
        """あなたからお礼のお金を渡したとき, 受け取る見込み."""
        close = self.app.earn.closeness(char["id"], st)
        c = 0.25 + 0.8 * self.greed(char, st) - 0.6 * close + float(self.app.traits(char).get("money", 0)) / 40.0
        return max(0.05, min(0.95, c))

    def offer(self, cid, now=None):
        """求められていないけれど, お礼にお金を渡す (手伝いの時間 × 1,000 円)."""
        app = self.app
        now = now or time.time()
        cid = cid or (self.rec() or {}).get("cid")
        with app.lock:
            w = self.rec(cid)
            hp = (w or {}).get("help") or {}
            if not hp.get("done") or hp.get("ask_money") or hp.get("settled") or not hp["done"].get("full"):
                raise ValueError("いまはお礼を渡す場面ではありません")
            char, st = app.chars[cid], app.state(cid)
            amt = max(1000, int(hp["h"] * 1000 / 500) * 500)
            if app.life.player_state().get("money", 0) < amt:
                raise ValueError("お金が足りません")
            hp["settled"] = True
            if random.random() < self.offer_chance(char, st):
                self._give_money(char, st, amt, now)
                d = app.apply_effects(st, app.trait_effects(char, {"mood": 1}))
                key = "help.offer_yes"
                st.pop("iou", None)                       # 渡したお礼で, 貸しも済み
            else:
                d = app.apply_effects(st, app.trait_effects(char, {"mood": 1}))     # 受け取らないが, 気持ちはうれしい
                key = "help.offer_no"
            app.bonds.save()
            e = app.note_entry(char, st, now, "_help_offer", "お礼を渡す", "💴", self.line(char, key, {}), d)
            app.save_state(cid)
            return {"entry": e, "amount": amt, "taken": key == "help.offer_yes"}

    def _give_money(self, char, st, amt, now):
        app = self.app
        app.life.player_state()["money"] -= amt
        app.life.her_money(st)["a"] = app.life.her_money(st).get("a", 0) + amt
        app.life.ledger(now, -amt, "social", "%sへ手伝いのお礼" % char.get("name", ""))
        app.life.save_player()

    # ------------------------------------------------------------------ 貸し
    def tick(self, char, st, now):
        """貸し (今度おごって) の催促と, うやむや."""
        app = self.app
        iou = st.get("iou")
        if not iou:
            return False
        age = (now - iou["t"]) / 86400.0
        if age >= IOU_LAPSE_D:
            st.pop("iou")
            g = self.greed(char, st)
            d = app.apply_effects(st, app.trait_effects(char, {"mood": -(2 + 2 * g), "trust": -(1 + 2 * g)}))
            app.life.add_reason(st, "player", "bad", "手伝ったお礼のおごりが、うやむやになった", now, told=False, delta=d.get("mood", 0),
                                action="_help")
            return True
        if age >= IOU_REMIND_D and not iou.get("reminded"):
            iou["reminded"] = True
            app.chat.add(char["id"], "her", app.chat.line(char, "help_iou_remind", {"what": iou.get("what", "")}), kind="help_iou", t=now)
            app.picked_up_phone(char, st, now)
            return True
        return False

    def iou_paid(self, char, st, now):
        """おごった / 贈り物をした: 貸しが返った. 言ってくるひとこと (無ければ None)."""
        if not st.get("iou"):
            return None
        st.pop("iou")
        self.app.apply_effects(st, self.app.trait_effects(char, {"mood": 2}))
        return self.line(char, "help.iou_paid", {})

    def allows(self, a, cid):
        """手伝ってもらっている最中は, 手を動かしながらできること (話す・見る) だけ (相手の家での手伝いと同じ)."""
        from .visit import HELPING_OK
        w = self.rec(cid)
        if not w or not w["help"].get("run") or a.get("category") in ("system", "あなたの予定", "連絡", "お金"):
            return None
        return None if a["id"] in HELPING_OK else "手伝ってもらっている最中です（話しかけるくらいなら、手を動かしながらできます）"

    # ------------------------------------------------------------------ 画面
    def view(self, cid, now=None):
        w = self.rec(cid)
        if not w:
            return None
        now = now or time.time()
        hp = w["help"]
        run = hp.get("run")
        return {"label": hp["label"], "h": hp["h"], "ready": not run and not hp.get("done"),
                "running": {"remain": max(0, int(run["until"] - now)), "rest_left": REST_MAX - run["rest"]} if run else None,
                "ask_money": hp.get("ask_money"), "can_offer": bool(hp.get("done") and hp["done"].get("full") and not hp.get("ask_money")
                                                                    and not hp.get("settled")),
                "offer_amount": max(1000, int(hp["h"] * 1000 / 500) * 500)}

    def line(self, char, key, extra):
        app = self.app
        t = app.persona_text(char, key) or LINES[key]
        fp, _, call = app.pronouns(char)
        for k, v in dict(extra, fp=fp, call=call).items():
            t = t.replace("{%s}" % k, str(v))
        return t
