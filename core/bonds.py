"""あなたと各キャラの間柄 (data/worlds/<id>/player.json の bonds / with).

段階 (stage):
- contact: 連絡先を知っている. メッセージ・電話・お出かけに誘える (外で会う)
- visit:   家に遊びに行ける (「今度、家に行ってもいい？」を受けてもらった)
- live:    一緒に暮らしている (一人だけ. 「一緒に住まない？」を受けてもらった)

いまどこで誰といるか (with):
- None:                      自分の家 (同居している相手がいればその人と一緒)
- {"cid", "mode": "meet"}:   外で会っている (お出かけの一時シーンが終われば別れる)
- {"cid", "mode": "visit"}:  相手の家に遊びに来ている (until まで)

一緒にいない相手には, 体に触れる・家の中のことなどはできず, 連絡・誘う・あなたの予定だけ (apart).
本命は各キャラが自分の視点で持つ: あなたと仲が深いキャラは, あなたがほかの人とも深い仲だと知ると嫉妬する.
"""
import math
import random
import time

from . import store

STAGES = ("contact", "visit", "live")
STAGE_LABEL = {"contact": "連絡先", "visit": "家に行ける仲", "live": "同居"}
# 一緒にいないときでもできるコマンドの分類 (個別には action の "apart": true / false で指定)
APART_CATEGORIES = ("連絡", "会う", "あなたの予定")
# 離れている相手のときの「あなたの予定」などの記録 (相手は見送りも出迎えもしない)
APART_TEXT = {"work": "仕事から帰ってきた。今日の稼ぎは {amount}円", "_back": "戻ってきた", "go_work": "仕事に出かけた",
              "go_out": "ちょっと出かけた", "go_sleep": "寝ることにした", "go_leave": "ひと休みすることにした",
              "go_busy": "作業を始めた", "_return": "家に戻った"}
DEFAULTS = {"visit_hours": 3, "meet_min_affection": 35, "deep_affection": 60, "jealousy_per_day": 0.6,
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
            ps["bonds"] = {} if meta.get("alone") or not cur else {cur: {"stage": "live", "t": time.time()}}
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
        ps["bonds"][cid] = {"stage": stage, "t": now or time.time()}
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

    def mode(self, cid):
        """cid と一緒にいる形: home (同居して家にいる) / meet / visit / None (離れている)."""
        w = self.with_rec()
        if w:
            return w["mode"] if w["cid"] == cid else None
        return "home" if self.living() == cid else None

    def together(self, cid):
        return self.mode(cid) is not None

    # ------------------------------------------------------------------ 会う・別れる
    def start(self, cid, mode, now=None):
        now = now or time.time()
        w = {"cid": cid, "mode": mode, "t": now}
        if mode == "visit":
            w["until"] = now + float(self.cfg()["visit_hours"]) * 3600
        self.rec()["with"] = w
        self.save()

    def end(self):
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
        if w["mode"] == "visit" and now >= w.get("until", 0):
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
        elif b == "visit_end":
            self.end()

    # ------------------------------------------------------------------ 条件・表示
    def deep(self, cid):
        """あなたと深い仲か (家に行ける以上, または好感度が高い)."""
        if self.stage(cid) != "contact":
            return True
        st = self.app.state(cid)
        return st["params"].get("affection", 0) >= float(self.cfg()["deep_affection"])

    def rivals(self, cid):
        return [o for o in self.app.chars if o != cid and self.deep(o)]

    def ctx(self, cid, st):
        m = self.mode(cid)
        known = st.get("jealous") or {}
        rv = self.rivals(cid)
        live = self.living()
        return {"stage": self.stage(cid), "apart": m is None, "with_mode": m or "none",
                "living_other": bool(live and live != cid), "rivals": len(rv),
                "rivals_known": sum(1 for o in rv if o in known)}

    def allowed_apart(self, a):
        if "apart" in a:
            return bool(a["apart"])
        return a.get("category") in APART_CATEGORIES or bool((a.get("override") or {}).get("outing") and a.get("home_only"))

    def view(self, cid):
        m = self.mode(cid)
        w = self.with_rec()
        label = {"home": "一緒に暮らしている", "meet": "外で会っている", "visit": "%sの家に来ている" % self.app.chars[cid].get("name", ""),
                 None: "離れている"}[m]
        if m is None and w:
            label += "（%sと一緒）" % self.app.chars[w["cid"]].get("name", "")
        return {"stage": self.stage(cid), "stage_label": STAGE_LABEL[self.stage(cid)], "mode": m, "label": label,
                "living": self.living(), "until": (w or {}).get("until") if m == "visit" else None}

    def list_view(self):
        return {cid: {"stage": self.stage(cid), "mode": self.mode(cid)} for cid in self.app.chars}

    # ------------------------------------------------------------------ 嫉妬
    def jealousy(self, char):
        return float(self.app.traits(char).get("jealousy", 1))

    def step(self, char, st, t, h):
        """あなたと深い仲のキャラが, あなたとほかの人との深い仲に気づくかどうか (時間経過で)."""
        cid = char["id"]
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
