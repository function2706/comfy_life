"""相手の家にいるとき (bonds の with.mode == "visit"): お客の立場でできることと, 頼まれごとの手伝い.

- できること: 同居しているときのコマンドから, お客の立場でできるものだけ (GUEST_NG を外す).
  台所・お風呂を使う・起こす・寝かしつけるなど家主のすることはしない. 看病は相手が具合の悪いときだけ (コマンドの条件のまま).
  一緒に寝る (添い寝) は泊まっているときだけ (お泊り: 未).
- 頼まれごとの約束で着いた: 相手の家に来ている状態になる (すぐには始めない). 「🤝 ○○を始める」で取りかかる.
- 手伝っている最中 (with.helping): あなたは相手の家にいるまま (仕事扱いにしない). 相手の様子は「○○を手伝ってもらっている」.
  コマンドは手を動かしながらできること (HELPING_OK) だけ. 「ひと休みする」(手伝いの終わりが少し延びる) と「切り上げる」.
  決めた時間が過ぎれば終わる (お礼は earn.favor_done). 終わっても相手の家にいて, 「そろそろ帰るね」で帰る.
- 画面を閉じていた間に終わりの時刻が過ぎた: ひと通り済ませたことにする (終わりの時刻で).
"""
import re
import time

GUEST_NG = {"cook", "tea", "snack", "water", "bath", "tuck_in", "wake", "clean", "sleep_together"}
HELPING_OK = {"talk", "talk_topic", "praise", "look", "peek_face", "watch_quietly", "full_body"}
REST_MIN = 15             # ひと休み 1 回で延びる分
REST_MAX = 2              # 1 回の手伝いで, ひと休みできる回数
STAY_AFTER_H = 1.0        # 手伝いが終わってから, 相手の家にいられる時間


class Visit:
    def __init__(self, app):
        self.app = app

    def rec(self, cid=None):
        """相手の家に来ているときの with (cid を渡せば, その人の家のときだけ)."""
        w = self.app.bonds.with_rec()
        if not w or w.get("mode") != "visit" or (cid and w.get("cid") != cid):
            return None
        return w

    def helping(self, cid=None):
        w = self.rec(cid)
        return (w or {}).get("helping")

    def host_scene(self, char, base, t):
        """来ている間の相手の場面: ほかに過ごし方 (一緒にゲームなど) が無ければ, 家で一緒に過ごしている
        (予定では出かける時刻でも, あなたが来ているあいだは家にいる)."""
        w = self.rec(char.get("id"))
        if not w or not (w.get("t", 0) - 60 <= t < w.get("until", 0)):       # (時刻を日時にすると丸まるので, 少し余裕)
            return base
        return dict(base, activity="host", label="家で一緒に過ごしている", location="自宅", away=False, busy=False, asleep=False,
                    outing=False, pos="indoors, at home, relaxed", neg="")

    # ------------------------------------------------------------------ できること
    def allows(self, a, cid):
        """相手の家にいるとき, そのコマンドができるか (理由の文 / None = できる)."""
        w = self.rec(cid)
        if not w:
            return None
        if a.get("category") in ("system", "あなたの予定", "連絡", "お金"):
            return None
        if w.get("helping"):
            if a["id"] not in HELPING_OK:
                return "手伝いの最中です（話しかけるくらいなら、手を動かしながらできます）"
            return None
        if a["id"] in GUEST_NG:
            return "%sの家では、お客なのでしません" % self.app.chars[cid].get("name", "")
        return None

    def extend(self, w, until):
        w["until"] = max(float(w.get("until", 0)), until)
        self.app.bonds.save()

    # ------------------------------------------------------------------ 頼まれごと
    def favor_arrive(self, cid, f, now):
        """頼まれごとの約束で相手の家に着いた: 相手の家に来ている状態にする (手伝いは「始める」で)."""
        app = self.app
        app.bonds.start(cid, "visit", now)
        w = app.bonds.with_rec()
        w["favor"] = f["id"]
        x = app.appoint.find(f.get("appoint")) if f.get("appoint") else None
        if x:
            x["athome"] = True          # 相手の家で手伝う形 (以前の「仕事中」の不具合のお詫びの対象ではない)
            app.appoint.save()
        self.extend(w, now + (float(f.get("h", 1)) + STAY_AFTER_H + 0.5) * 3600)
        app.presence.touch(now)
        app.solo.note("visit", "%sの家に%sの手伝いに来た" % (app.chars[cid].get("name", ""), f["label"]), now)

    def favor_pending(self, cid):
        """来ている家で頼まれていて, まだ始めていない手伝い."""
        w = self.rec(cid)
        if not w or w.get("helping") or not w.get("favor"):
            return None
        return self.app.earn.favor(w["favor"])

    def start(self, cid, now=None):
        """「○○を始める」: 手伝いに取りかかる."""
        app = self.app
        now = now or time.time()
        cid = cid or (self.rec() or {}).get("cid")
        with app.lock:
            f = self.favor_pending(cid)
            if not f:
                raise ValueError("いまは手伝うことがありません")
            if app.body.level() >= 3:
                raise ValueError("寝込むほどつらくて、手伝えそうにない")
            w = self.rec(cid)
            h = float(f.get("h", 1))
            w["helping"] = {"fid": f["id"], "t0": now, "until": now + h * 3600, "rest": 0}
            self.extend(w, now + (h + STAY_AFTER_H) * 3600)
            char = app.chars[cid]
            e = app.favor_scene(f, "（%sと一緒に%sに取りかかった。%g時間ほどかかりそうだ）" % (char.get("name", ""), f["label"], h),
                                now, start=True)
            return {"entry": e, "job": (e or {}).get("job")}

    def rest(self, cid, now=None):
        """ひと休み: 手伝いの終わりが少し延びる (働いた時間には入れない)."""
        app = self.app
        now = now or time.time()
        cid = cid or (self.rec() or {}).get("cid")
        with app.lock:
            hp = self.helping(cid)
            if not hp:
                raise ValueError("いまは手伝っていません")
            if hp["rest"] >= REST_MAX:
                raise ValueError("さっき休んだばかりです（あとひと息）")
            hp["rest"] += 1
            hp["until"] += REST_MIN * 60
            hp["t0"] += REST_MIN * 60
            w = self.rec(cid)
            self.extend(w, hp["until"] + STAY_AFTER_H * 3600)
            st = app.state(cid)
            ov = st.get("override") or {}
            if ov.get("activity") == "favor":
                ov["until"] = hp["until"]
            app.save_state(cid)
            char = app.chars[cid]
            e = app.note_entry(char, st, now, "_favor_rest", "ひと休み", "☕",
                               "（%sとひと休みした。%d分ほど）" % (char.get("name", ""), REST_MIN))
            return {"entry": e}

    def stop(self, cid, now=None):
        """切り上げる: そこまでの分で終える (決めた時間の 6 割に届かなければ「途中で帰った」扱い. 家にはまだいる)."""
        app = self.app
        now = now or time.time()
        cid = cid or (self.rec() or {}).get("cid")
        with app.lock:
            if not self.helping(cid):
                raise ValueError("いまは手伝っていません")
            return self._finish(cid, now)

    def _finish(self, cid, t):
        """手伝いを終える (t: 終えた時刻). お礼は earn.favor_done. 相手の家にはまだいる."""
        app = self.app
        w = self.rec(cid)
        hp = w.pop("helping")
        w.pop("favor", None)
        f = app.earn.favor(hp["fid"])
        app.bonds.save()
        if not f:
            return {"entry": None}
        h = max(0.0, (t - hp["t0"]) / 3600.0)
        pay, text = app.earn.favor_done(f, h, t, stay=True)
        if f in app.earn.favors():                       # 途中で切り上げた分も, 頼まれごとの一覧からは外す (続きは頼まれ直したら)
            app.earn.favors().remove(f)
        if not pay and "切り上げ" in text:
            app.chat.add(cid, "sys", "（%s）" % text, kind="favor", t=t)
        app.life.save_player()
        e = app.favor_scene(f, "（%s）" % text, t, start=False)
        self.extend(w, t + STAY_AFTER_H * 3600)
        return {"entry": e, "job": (e or {}).get("job"), "text": text, "pay": pay}

    def on_leave(self, now=None):
        """相手の家から帰る (bonds.end の前): 手伝いの最中ならそこで切り上げ, 始めていなければ手伝わずに帰ったことにする."""
        app = self.app
        now = now or time.time()
        w = self.rec()
        if not w:
            return None
        hp = w.get("helping")
        if hp:
            return self._finish(w["cid"], min(now, hp["until"]))
        f = self.favor_pending(w["cid"])
        w.pop("favor", None)
        if not f:
            return None
        app.earn.favor_done(f, 0.0, now)                 # 6 割に届かない: 信頼・機嫌 −1
        if f in app.earn.favors():
            app.earn.favors().remove(f)
        app.life.save_player()
        text = "%sの%sを手伝わずに帰ってきてしまった" % (app.chars[w["cid"]].get("name", ""), re.sub("の手伝い$", "", f["label"]))
        app.chat.add(w["cid"], "sys", "（%s）" % text, kind="favor", t=now)
        return {"text": text}

    def busy_ids(self):
        """相手の家で待っている / 手伝っている頼まれごとの id."""
        w = self.rec() or {}
        return {w.get("favor"), (w.get("helping") or {}).get("fid")} - {None}

    def live(self, cid, now):
        """時間が来た手伝いを終える (tick のたび. 画面を閉じていた間に過ぎていれば, 終わりの時刻で)."""
        hp = self.helping(cid)
        if hp and now >= hp["until"]:
            return self._finish(cid, hp["until"])
        return None

    # ------------------------------------------------------------------ 画面
    def view(self, cid, now=None):
        w = self.rec(cid)
        if not w:
            return None
        now = now or time.time()
        out = {"name": self.app.chars[cid].get("name", "")}
        f = self.favor_pending(cid)
        if f:
            out["favor"] = {"label": f["label"], "h": f.get("h", 1)}
        hp = w.get("helping")
        if hp:
            f = self.app.earn.favor(hp["fid"]) or {}
            out["helping"] = {"label": f.get("label", "手伝い"), "until": hp["until"], "remain": max(0, int(hp["until"] - now)),
                              "rest_left": REST_MAX - hp["rest"]}
        return out
