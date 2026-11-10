"""あなたの在席状態と, キャラからの働きかけ.

在席状態 (data/player.json の presence):
- here  : 画面を開いていて, 最近なにか操作した (そばで構っている)
- idle  : 画面は開いているが, しばらく何もしていない (そばにはいる)
- busy  : 「作業するね」と告げて, 家で作業中
- out / work / sleep / left : 出かけた / 仕事に行った / 寝た / 「またね」とそばを離れた (告げてから)
- gone  : 何も言わずに画面を閉じた (心拍が途絶えた)

画面は 30 秒ごとに /api/state を呼ぶ (心拍). 途絶えて gone_minutes 経つと gone とみなす.

働きかけ (data/approaches.json): あなたがそばにいる (here / idle / busy) ときに, キャラの状態しだいで
キャラのほうから話しかけてくる. 一緒に暮らしていない相手 (apart) からは, "apart": true の働きかけだけが
メッセージとして届く (画像なし. 頻度は寂しさ・好感度・機嫌しだいで控えめ). 「応じる」「あとで」と答えるか, 放っておくと approach_wait_minutes で
「返事がなかった」になり, キャラの状態 (寂しさなど) に応じてパラメータが動く.
"""
import math
import random
import time
from datetime import datetime

from . import cond
from . import msgreply
from . import nori
from . import react

DECLARED = ("busy", "out", "work", "sleep", "left")
AWAY_MODES = ("out", "work", "sleep", "left")
AWAY_SEND = 0.35        # 相手が仕事中・出かけているときの, 送ってくる見込みの倍率 (休憩・移動の合間)
MODE_LABEL = {"here": "そばにいる", "idle": "そばでのんびり", "busy": "作業中", "out": "外出中", "work": "仕事中",
              "sleep": "就寝中", "left": "離れている", "gone": "いない"}


def hour_factor(dt):
    """離れている相手がメッセージを送ってくる時刻の現実味: 起きていても, 夜中や早朝にはまず送らない."""
    h = dt.hour + dt.minute / 60.0
    if 1 <= h < 6:
        return 0.03
    if 6 <= h < 7.5 or 0 <= h < 1:
        return 0.3
    if h >= 23:
        return 0.6
    return 1.0


class Presence:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 設定
    def cfg(self):
        return self.app.world.get("presence") or {}

    def _gone_sec(self):
        return float(self.cfg().get("gone_minutes", 5)) * 60

    def _idle_sec(self):
        return float(self.cfg().get("idle_minutes", 10)) * 60

    def rec(self):
        ps = self.app.life.player_state()
        p = ps.setdefault("presence", {})
        p.setdefault("mode", "none")
        return p

    def save(self):
        self.app.life.save_player()

    # ------------------------------------------------------------------ 心拍・状態
    def beat(self, now=None, idle_sec=None):
        """画面からの心拍. 途絶えていた (= 黙って閉じていた) なら, そのことを覚えておく."""
        now = now or time.time()
        p = self.rec()
        prev = p.get("beat", 0)
        if prev and now - prev > self._gone_sec() and p["mode"] == "none":
            p["last_left"] = {"t": prev, "said": False, "mode": "gone", "back": now, "h": round((now - prev) / 3600, 2)}
        p["beat"] = now
        if idle_sec is not None:
            p["input"] = now - float(idle_sec)
        self.save()

    def touch(self, now=None):
        """あなたが何か操作した (スマホ用の入り口からの操作は数えない: 家の画面の前にはいない)."""
        if self.app.from_phone() or self.app.remote.active:     # 閉じている間の進行の中 (自動の返事) も
            return
        p = self.rec()
        p["input"] = now or time.time()

    def at(self, t):
        """時刻 t のあなたの在席状態 (過ぎた時間のまとめ計算にも使う)."""
        p = self.rec()
        m = p["mode"] if t >= p.get("since", 0) else "none"
        if m in AWAY_MODES:
            return m
        if t > p.get("beat", 0) + self._gone_sec():
            return "gone"
        if m == "busy":
            return "busy"
        return "idle" if t - p.get("input", 0) > self._idle_sec() else "here"

    def ctx(self, t):
        p = self.rec()
        ll = p.get("last_left") or {}
        recent = bool(ll) and t - ll.get("back", 0) < 900       # 戻ってきて 15 分は「どう離れていたか」を条件で使える
        return {"presence": self.at(t),
                "said": bool(ll.get("said")) if recent else True,
                "left_mode": ll.get("mode", "none") if recent else "none",
                "left_h": ll.get("h", 0) if recent else 0}

    def declare(self, mode, now=None):
        now = now or time.time()
        p = self.rec()
        p["mode"], p["since"] = mode, now
        p["input"] = now
        p.pop("solo", None)          # 一人の時間の中身は, solo.start がこのあと入れる
        p.pop("place", None)         # 外出の行き先も (solo.start で)
        p.pop("work_contacts", None)
        p.pop("job", None)           # アルバイト・副業・頼まれごと (earn) のときは, このあと入れる
        p.pop("task", None)
        p.pop("travel", None)        # 移動 (core/geo.py) も. 出かけるなら, このあと geo.depart で
        p.pop("arrived", None)
        p.pop("left", None)
        p["street_log"], p["enc_check"] = [], now
        self.save()

    def back(self, now=None):
        """告げて離れていたところから戻る. (離れていた様子) を返す. 離れていなければ None."""
        now = now or time.time()
        p = self.rec()
        if p["mode"] == "none":
            return None
        ll = {"t": p.get("since", now), "said": True, "mode": p["mode"], "back": now,
              "h": round((now - p.get("since", now)) / 3600, 2), "solo": p.pop("solo", None), "place": p.get("place"),
              "job": p.pop("job", None), "task": p.pop("task", None)}
        # 移動があった (core/geo.py): その場所にいたのは, 着いてから出るまで (行き帰りの移動の時間は入れない)
        tr = p.pop("travel", None)
        arr = p.pop("arrived", None)
        left = p.pop("left", None)
        if tr and tr.get("dir") == "go" and now < tr["arr"]:
            arr = now                                  # 着く前に戻った
        if arr is not None:
            ll["arr"], ll["left"] = arr, min(now, left or now)
            ll["h_at"] = round(max(0.0, ll["left"] - arr) / 3600, 3)
        p["last_left"] = ll
        p["mode"] = "none"
        p["input"] = p["beat"] = now
        self.save()
        return ll

    def effects(self, t):
        """在席状態による, キャラのパラメータ変化 (1時間あたり)."""
        return (self.cfg().get("effects") or {}).get(self.at(t)) or {}

    def view(self, now):
        p = self.rec()
        m = self.at(now)
        out = {"mode": p["mode"], "state": m, "label": MODE_LABEL.get(m, m), "since": p.get("since")}
        sl = p.get("solo") if p["mode"] in ("busy", "out") else None
        if sl:      # 一人の時間 (休む・家事・研鑽・外出)
            from .solo import ALL_KINDS
            k = ALL_KINDS.get(sl["kind"]) or {}
            doing = k.get("doing", "")
            if p["mode"] == "out" and p.get("place"):
                doing = "%s（%s）" % (doing, self.app.places.label(p["place"]))
            out["solo"] = {"kind": sl["kind"], "skill": sl.get("skill"), "label": doing, "icon": k.get("icon", "")}
            if sl.get("shop_done"):
                out["shop"] = sl["shop_done"]                 # 店での買い物が済んだ (知らせる)
            elif sl.get("shop_need") and not p.get("travel"):           # 店に着いてから, 品を選ぶ
                out["shop_wait"] = max(0, int(p.get("arrived", sl["t"]) + sl["shop_need"] * 60 - now))
            out["label"] = doing or out["label"]
        lw = p.get("last_words")
        if lw and float(lw.get("t", 0)) >= float(p.get("since") or 0) - 5:
            out["last_words"] = lw      # 離れる直前の, 相手との最後のやりとり (解散して家へ など)
        tv = self.app.geo.view(now)
        if tv:                      # 移動中 (core/geo.py)
            out["travel"] = tv
            out["label"] = "%sへ移動中（%s・あと%d分）" % (tv["label"], tv["how_label"], max(1, round(tv["remain"] / 60)))
        if p["mode"] == "work" and not (tv and tv["dir"] == "go"):
            pay, h, raw = self.app.life.work_pay(p.get("arrived", p.get("since", now)), p.get("left", now))
            out["work"] = {"hours": round(h, 2), "raw": round(raw, 2), "pay": pay}
        return out

    # ------------------------------------------------------------------ 働きかけ
    def find(self, aid):
        return next((x for x in self.app.approaches if x.get("id") == aid), None)

    def live(self, char, st, now):
        """画面を開いている間 (state_view のたび) に呼ぶ. 期限切れの処理と, 新しい働きかけ. 作った記録を返す."""
        if react.ignore_tick(self.app, char, st, now):     # 返さないまま既読で放っておくほど, 少しずつ重くなる
            self.app.save_state(char["id"])
        ap = st.get("approach")
        remote = self.app.remote.active         # 家の画面を閉じている間の進行 (core/remote.py. 設定でオンのとき)
        if ap and now >= ap.get("until", 0):
            a0 = self.find(ap["id"]) or {}
            pol = remote and a0.get("apart") and self.app.planner.rec()["auto"].get("reply")
            if pol:                             # 予定の「自動の応答」: 待ち時間が切れたときに, 弱い自動の返事 (閉じていた間のまとめと同じ)
                ids = [o["id"] for o in msgreply.options(a0["id"], ap.get("why"))]
                re_ = self._reply(char, st, a0, pol if pol in ids else ids[0], now, auto=True)
                self.app.save_log(char["id"])
                return re_
            return self._expire(char, st, now)
        last = st.get("ap_check") or now
        st["ap_check"] = now
        T = self.app.trace
        if ap or now < st.get("ap_quiet_until", 0):
            if T.every("apskip:" + char["id"], 1800, now):
                T.add("approach", "抽せんしない (%s)" % ("返事待ちの働きかけがある" if ap else "少し前に離れていった (quiet)"), char["id"], now,
                      approach=(ap or {}).get("id"), quiet_until=st.get("ap_quiet_until"))
            return None
        dt_h = min(max(now - last, 0), 600) / 3600.0
        if not dt_h:
            return None
        pres = self.at(now)
        if st.get("game"):
            return None
        d = datetime.fromtimestamp(now)
        scene = self.app.scene_at(char, st, d)
        ctx = self.app.context(char, st, d, scene)
        apart = bool(ctx.get("apart"))
        # あなたが寝る・離れると告げていても, 離れている相手のメッセージは届く (読むのは戻ってから. 以前はこの間は来なかった)
        # 家の画面を閉じている間 (gone) も, 設定でオンなら, 離れている相手のメッセージは届く (スマホで読む. core/remote.py)
        if pres not in ("here", "idle", "busy", "out", "work") + (("sleep", "left") if apart else ()) \
                + (("gone",) if apart and remote else ()):
            return None
        away_f = 1.0
        if not ctx["free"]:
            # 相手が仕事中・出かけている: 休憩や移動の合間に, ときどきスマホを見て送ってくる (以前は一切来なかった).
            # 寝ている・入浴などで手が離せないときは来ない
            if not (apart and scene.get("away") and not scene.get("asleep") and not scene.get("busy")):
                return None
            away_f = AWAY_SEND
        if apart and ctx.get("stage") == "known":    # 連絡先を知らない相手からは来ない
            return None
        if apart:                    # 離れている相手からは, メッセージが届く (外出中・仕事中でも)
            rate = float(self.cfg().get("approach_apart_rate_per_hour", 0.25)) * self.eagerness_apart(ctx) * hour_factor(d) * away_f
        elif pres in ("out", "work"):
            return None
        else:
            rate = float(self.cfg().get("approach_rate_per_hour", 0.8)) * self.eagerness(ctx)
        rate *= float(self.app.traits(char).get("approach", 1))
        hit = 1 - math.exp(-rate * dt_h)
        if random.random() >= hit:
            if T.every("apmiss:" + char["id"], 1800, now):
                T.add("approach", "抽せん: 外れ (30 分に一度だけ残す)", char["id"], now, rate_h=rate, p=hit, apart=ctx.get("apart"),
                      presence=pres, mood=ctx.get("mood"), loneliness=ctx.get("loneliness"), affection=ctx.get("affection"))
            return None
        pend = st.get("msg_pending")
        if ctx.get("apart") and pend:
            # あなたのメッセージに返していないうちは, 別の話を送ってこない. 話したくてスマホを手に取ったので, いま読んで返す
            # (返さないと決めていても, 話したい気持ちのほうが勝つ. 返事の中身は読んだときの状況しだい)
            was = pend.get("reply")
            pend["due"] = min(pend.get("due", now), now)
            pend["reply"], pend["unread"] = True, False
            T.add("approach", "抽せん: 当たったが, 返事待ちのメッセージがあるので送らず, いま読んで返す", char["id"], now, rate_h=rate, p=hit,
                  reply_before=was)
            return None
        T.add("approach", "抽せん: 当たり", char["id"], now, rate_h=rate, p=hit, apart=ctx.get("apart"), presence=pres,
              mood=ctx.get("mood"), loneliness=ctx.get("loneliness"), affection=ctx.get("affection"))
        return self.fire(char, st, now, ctx)

    def eagerness(self, ctx):
        """キャラが自分から話しかけたくなる度合い. 寂しさ・退屈・好感度しだい.
        作業中と告げていれば遠慮する (ただし, とても寂しければ来る). いま構っている最中なら来にくい."""
        f = (0.3 + ctx.get("loneliness", 30) / 100.0 + ctx.get("boredom", 30) / 150.0 + (ctx.get("affection", 50) - 50) / 200.0) \
            * (1 + 0.4 * (ctx.get("dependence", 50) - 50) / 50.0) * (0.2 if ctx.get("fight") else 1.0)       # 依存しているほど構いに来る (言い争いのあとは来ない)
        if ctx.get("presence") == "busy":
            f *= 0.7 if ctx.get("loneliness", 0) >= 75 else 0.25
        elif ctx.get("outing"):
            f *= 2.0                 # お出かけ中 (デート): 一緒に歩いていて, 見つけたこと・疲れた・次はどこ, と話すきっかけが多い
        elif ctx.get("presence") == "here" and ctx.get("absent", 1) < 5 / 60.0:
            f *= 0.3
        return max(0.05, min(2.0, f))

    def eagerness_apart(self, ctx):
        """離れている相手がメッセージを送りたくなる度合い (1.6.0 で掛け算に).
        あなたへの興味 (好感度) × 送る理由の強さ (寂しさ・退屈・機嫌) × 依存度. 好感度 30 以下なら 0 (自分からは送ってこない.
        お金の催促・約束の取りやめなど用事のあるものは別に届く). 寂しさ・退屈は, 興味のある相手に送る理由を強めるだけ.
        以前は寂しさと好感度の足し算で下限もあったので, 嫌っている相手からも, 寂しいと毎日のように届いていた."""
        aff = ctx.get("affection", 50)
        interest = max(0.0, min(1.25, (aff - 30) / 40.0)) ** 1.4
        drive = 0.6 + ctx.get("loneliness", 30) / 120.0 + ctx.get("boredom", 30) / 250.0 + (ctx.get("mood", 50) - 50) / 200.0
        f = interest * max(0.2, drive) * (1 + 0.6 * (ctx.get("dependence", 50) - 50) / 50.0) \
            * (0.2 if ctx.get("fight") else 1.0)       # 依存しているほど送ってくる (言い争いのあとは来ない)
        return max(0.0, min(1.5, f))

    def fire(self, char, st, now, ctx, force=None):
        cands = []
        apart = bool(ctx.get("apart"))
        for a in self.app.approaches:
            if force and a["id"] != force:
                continue
            if not force:
                if bool(a.get("apart")) != apart:      # 離れているときはメッセージだけ, 一緒のときはメッセージ以外
                    continue
                if now - (st.get("ap_last") or {}).get(a["id"], 0) < float(a.get("cooldown_h", 3)) * 3600:
                    continue
                if apart and now < st.get("ap_ignored_until", 0) and not (a["id"] == "msg_miss" and ctx.get("loneliness", 0) >= 75):
                    continue          # あなたのメッセージを既読のまま返さなかったばかり: 気軽な話は送ってこない (とても寂しければ別)
                if not cond.check(a.get("when", ""), ctx):
                    continue
                if a.get("pick_place") and not self._next_places(char, st, a, ctx):
                    continue
            cands.append(a)
        if not cands:
            self.app.trace.add("approach", "候補なし (条件・間隔)", char["id"], now, apart=apart, force=force)
            return None
        a = random.choices(cands, [float(x.get("weight", 1)) for x in cands])[0]
        self.app.trace.add("approach", "働きかけ: %s" % a["id"], char["id"], now, cands=[x["id"] for x in cands], force=force)
        st.setdefault("ap_last", {})[a["id"]] = now
        wait = float(a.get("wait_minutes", self.cfg().get("approach_wait_minutes", 15))) * 60
        st["approach"] = {"id": a["id"], "t": now, "until": now + wait, "presence": ctx.get("presence")}
        text0 = a.get("text", "")
        if a.get("pick_place"):          # お出かけ中「次, あそこ行かない？」: 行き先はその人の好みで (応じれば, そこへ移る)
            nxt = self._next_places(char, st, a, ctx)
            if nxt:
                act = random.choices(nxt, [w for _, w in nxt])[0][0]
                st["approach"]["act"] = act["id"]
                st["approach"]["place_label"] = (act.get("override") or {}).get("location") or act.get("name", "")
                text0 = text0.replace("{place}", st["approach"]["place_label"])
        why = msgreply.pick_why(char, st) if a["id"] in msgreply.WHY_AIDS else None      # 「話そう」の理由: 誘いの文に出す
        if why:
            st["approach"]["why"] = why
            self.app.trace.add("approach", "話そうの理由: %s" % why, char["id"], now, boredom=st["params"].get("boredom"),
                               energy=st["params"].get("energy"), mood=st["params"].get("mood"), loneliness=st["params"].get("loneliness"))
        e = self._entry(char, st, now, a, "call_" + why if why else "call", msgreply.WHY_TEXT[why] if why else text0, {}, a,
                        gen=a.get("generate", True) and not a.get("apart"))
        if a.get("apart"):              # 離れている相手からのメッセージ: トークにも (送ったあと, しばらくスマホを見ている)
            self.app.chat.add(char["id"], "her", e["text"], kind="approach", t=now, ap=a["id"], why=why)    # 何の話か (返し方の合う・外す)
            told = self.app.knowsched.from_message(char, st, now)      # 今日のことが添えられることがある
            if told:
                self.app.chat.add(char["id"], "sys", told, kind="sched", t=now + 0.0005)
            rum = self.app.rumors.from_message(char, st, now)          # 会社や店の噂が添えられることも
            if rum:
                self.app.chat.add(char["id"], "sys", rum, kind="rumor", t=now + 0.0007)
            nori.start(self.app, char, st, now, boost=15 if a["id"] == "msg_chat" else 8, why="相手から送ってきた: " + a["id"])
            self.app.picked_up_phone(char, st, now)
        st["approach"]["entry"] = e["id"]
        return e

    def _next_places(self, char, st, a, ctx):
        """次に誘える行き先 [(コマンド, 重み)]: いまいる場所以外で, いま行けるところ (時間帯・好み)."""
        app = self.app
        here = (st.get("override") or {}).get("place")
        out = []
        for aid in a.get("pick_place") or []:
            try:
                act = app.action(aid)
            except KeyError:
                continue
            ov = act.get("override") or {}
            if ov.get("place") == here or not cond.check(act.get("when", ""), ctx):
                continue
            from . import places as places_mod
            pl = ov.get("place")
            if pl in places_mod.PLACES and not places_mod.open_state(pl, datetime.now())["open"]:     # 閉まっている所には誘わない
                continue
            try:
                w = max(0.05, float(app.appoint.place_weight(char, st, ov.get("place"))))      # その人の行き先の好み (約束と同じ)
            except (KeyError, TypeError, ValueError):
                w = 1.0
            out.append((act, w))
        return out

    def _entry(self, char, st, now, a, ev, text, deltas, prompt_src, gen=True):
        """働きかけの記録を作る (セリフは性格プリセットの ap.<id>.<場面> があればそちら)."""
        app = self.app
        d = datetime.fromtimestamp(now)
        text = app.persona_text(char, "ap.%s.%s" % (a["id"], ev)) or text
        text = text.replace("{place}", (st.get("approach") or {}).get("place_label", ""))     # 「次, あそこ」の行き先 (性格のセリフにも)
        scene = app.scene_at(char, st, d)
        text = app.format_text(text, char, scene, d)
        act = {"id": "_ap_" + a["id"], "name": a.get("label", a["id"]), "icon": a.get("icon", "💬"),
               "pos": (prompt_src or {}).get("pos", ""), "neg": (prompt_src or {}).get("neg", "")}
        pos, neg, parts = app.build_prompt(char, st, d, act if prompt_src else None)
        e = app._new_entry(char["id"], now, act, text, deltas, scene, d, pos, neg, parts)
        e["approach"] = a["id"]
        if gen and prompt_src and app.settings.get("auto_generate"):
            e["job"] = app._present_image(char["id"], e)
        st["last_auto"] = {"id": e["id"], "t": now}
        app.save_log(char["id"])
        return e

    def _expire(self, char, st, now):
        """返事がないまま時間切れ. 作業中・不在なら軽く, 寂しいときほど重く受け止める."""
        ap = st.pop("approach")
        a = self.find(ap["id"]) or {"id": ap["id"]}
        ig = a.get("ignore") or {}
        pres = self.at(now)
        lon = st["params"].get("loneliness", 50)
        read = False
        if a.get("apart"):
            # メッセージ: 既読のまま放っておかれると重く, 開いていない (未読) なら軽い. 急ぎの内容ほど重い. 気にしない性格もいる
            read = self.app.chat.load(char["id"])["seen_t"] >= ap.get("t", 0)
            mult = 0.6 * float(self.app.traits(char).get("absence", 1)) * (1.4 if read else 0.7) * float(a.get("urgency", 1.0)) \
                * (1 + 0.5 * self.app.attach.factor(char, st, "dependence"))
            self.app.attach.move(char, st, "dependence", -0.3, "送ったメッセージに返事が来なかった", now)
        else:
            mult = (0.4 if ap.get("presence") == "busy" or pres == "busy"
                    else 0.6 if pres in ("gone",) + AWAY_MODES else 1.0)
        mult *= 0.5 + lon / 100.0
        eff = {k: float(v) * mult for k, v in (ig.get("effects") or {"mood": -3, "loneliness": 5}).items()}
        deltas = self.app.apply_effects(st, self.app.trait_effects(char, eff))
        self.app.trace.add("approach", "時間切れ (返事がなかった): %s" % ap["id"], char["id"], now, read=read, mult=mult, loneliness=lon,
                           presence=pres, deltas=deltas)
        busy = ap.get("presence") == "busy"
        text = (ig.get("busy_text") if busy else None) or ig.get("text") or "（返事がないので、{name}はそっと離れていった）"
        st["ap_quiet_until"] = now + float(self.cfg().get("approach_quiet_minutes", 20)) * 60
        call = self.app.pronouns(char)[2]
        if deltas.get("mood", 0) <= -2 and (lon >= 75 or (lon >= 50 and not busy)):
            tell = ("{call}に既読のまま放っておかれた" if a.get("apart") and read else
                    "{call}にメッセージを送ったのに、返事がなかった" if a.get("apart") else
                    "{call}が作業に夢中で、構ってもらえなかった" if busy else "{call}に話しかけたのに、返事がなかった")
            self.app.life.add_reason(st, "player", "bad", tell.replace("{call}", call), now, told=False,
                                     delta=deltas.get("mood", 0), action="_ap_" + a["id"])
        e = self._entry(char, st, now, a, "busy" if busy and ig.get("busy_text") else "ignore", text, deltas, None, gen=False)
        if a.get("apart"):        # 待ち時間が過ぎたあとも既読のままなら, 少しずつ重くなる (core/react.py ignore_tick. 返せば一部戻る)
            st["ap_ignored"] = {"t": now, "t_msg": float(ap.get("t", now)), "aid": a["id"], "read": read, "applied": 0.0,
                                "urgency": float(a.get("urgency", 1.0))}
        if a.get("apart") and read:
            self.app.chat.add(char["id"], "sys", "既読のまま返事をしなかった", kind="ignored", t=now)
        self.app.save_state(char["id"])
        return e

    def answer(self, char, st, ans, now=None, use_action=True, choice=None):
        """働きかけに答える. ans = accept / later (メッセージは reply + choice も). (記録, 代わりに実行するコマンド id) を返す."""
        now = now or time.time()
        ap = st.get("approach")
        if not ap:
            raise ValueError("いまは話しかけられていません")
        a = self.find(ap["id"]) or {"id": ap["id"]}
        if a.get("apart") and ans in ("accept", "reply"):
            return self._reply(char, st, a, choice, now), None
        if a.get("talk") and ans == "reply":          # 対面で話しかけられた: 返し方を選んで返す (メッセージと同じ判定)
            return self._reply_face(char, st, a, choice, now), None
        out = a.get(ans) or {}
        st["approach"] = None
        self.touch(now)
        st["last_interaction"] = now
        if ans == "later":
            # しばらくしたら, また同じことで来るかもしれない
            st.setdefault("ap_last", {})[a["id"]] = now - float(a.get("cooldown_h", 3)) * 3600 + 30 * 60
            st["ap_quiet_until"] = now + 30 * 60
        else:
            st["ap_quiet_until"] = now + float(self.cfg().get("approach_quiet_minutes", 20)) * 60
        run = (ap.get("act") if ans == "accept" else None) or out.get("action")     # 「次, あそこ」は誘われた行き先のコマンド
        if ans == "accept" and run and use_action:
            return None, run
        mult = self.app.life.skill_mult(out["skill"]) if out.get("skill") else 1.0
        eff = {k: (float(v) * mult if float(v) * (1 if not (self.app.param_def(k) or {}).get("invert") else -1) > 0 else float(v))
               for k, v in (out.get("effects") or {}).items()}
        if ans == "accept":     # 応じても, 確実に仲が深まるわけではない (揺らぎ・鈍り・繰り返し)
            eff, _ = self.app.bonds.realize(char, st, eff, "_ap_" + a["id"], now)
            self.app.bonds.touch(st, now)
        deltas = self.app.apply_effects(st, self.app.trait_effects(char, eff))
        if out.get("skill"):
            self.app.life.train(out["skill"], 1.0)
        if ans == "accept" and out.get("care"):          # 看病してくれる (あなたの体調が治りやすい)
            self.app.body.cared(char, now)
            self.app.attach.give(char, st, "her", 3, "看病してくれた")
            self.app.manners.favor(st, "care", now)      # 看病してくれた (お礼の心当たり)
        if out.get("reason_good") and deltas.get("mood", 0) > 0:
            self.app.life.add_reason(st, "player", "good", out["reason_good"].replace("{call}", self.app.pronouns(char)[2]),
                                     now, told=True, delta=deltas.get("mood", 0), action="_ap_" + a["id"])
        e = self._entry(char, st, now, a, ans, out.get("text") or "", deltas, out if (out.get("pos") or out.get("neg")) else None,
                        gen=bool(out.get("pos") or out.get("neg")) and not a.get("apart"))
        if a.get("apart") and ans in ("accept", "later"):      # メッセージへの返事: トークにも
            self.app.chat.add(char["id"], "me", "（返信した）" if ans == "accept" else "（あとで返すと送った）", kind="approach", t=now)
            self.app.chat.mark_read_by_her(char["id"], now)
            if out.get("text"):
                self.app.chat.add(char["id"], "her", e["text"], kind="approach", t=now + 0.001)
                self.app.picked_up_phone(char, st, now)
        self.app.save_state(char["id"])
        return e, None

    def _reply(self, char, st, a, choice, now, auto=False):
        """メッセージに選んだ返事をする. 相手の返しは, ふつうのメッセージと同じく時間差で届く (engine.reply_delay:
        まだスマホを見ていればすぐ, 置いていれば数分〜. 寝ている・手が離せないなら, そのあと). 以前は返信した瞬間に返ってきていた.
        届いたとき (engine._chat_reply → reply_land) に, 受け取り方 (good / neutral / bad) と返しが決まる.
        auto: 画面を閉じていた間の自動の返事 (その場で済ませる)."""
        ap = st.get("approach") or {}
        why = ap.get("why")
        opts = [o["id"] for o in msgreply.options(a["id"], why)]
        kind = choice if choice in opts or choice in react.AP_KINDS else opts[0]       # 「返す」の種類 (1.6.0) / 以前の 4 択
        st["approach"] = None
        self.touch(now)
        st["last_interaction"] = now
        st["ap_quiet_until"] = now + float(self.cfg().get("approach_quiet_minutes", 20)) * 60
        chat = self.app.chat
        if kind in react.AP_KINDS:
            chat.add(char["id"], "me", react.said(kind), kind=kind, t=now)
        else:
            chat.add(char["id"], "me", "（%s%s）" % (msgreply.said(a["id"], kind, why), "・自動" if auto else ""), kind="approach", t=now)
        if auto or st.get("msg_pending"):        # 自動の返事 / 別の返事待ちがある (重ねない): その場で
            return self.reply_land(char, st, a["id"], kind, now, auto=auto, why=why)
        app = self.app
        d = datetime.fromtimestamp(now)
        scene = app.scene_at(char, st, d)
        delay, quick, _ = app.reply_delay(char, st, now, scene, app.context(char, st, d, scene))
        st["msg_pending"] = {"aid": "_ap_reply", "t": now, "due": now + delay, "reply": True, "count": 1, "kind": "ap_reply",
                             "quick": quick, "meta": {"ap": a["id"], "choice": kind, "why": why, "waited": now - float(ap.get("t", now))}}
        app.trace.add("msg", "働きかけに返事: 返しの予定を決めた", char["id"], now, ap=a["id"], choice=kind, due_min=delay / 60.0,
                      quick=quick, waited_min=(now - float(ap.get("t", now))) / 60.0)
        e = self._entry(char, st, now, a, "sent", "（📱 %sに返信した）" % char.get("name", ""), {}, None, gen=False)
        e["sent"] = True
        app.save_log(char["id"])
        app.save_state(char["id"])
        return e

    def _reply_face(self, char, st, a, choice, now):
        """そばで話しかけられて, 返し方を選んで返した (1.6.0. 以前は「いいよ / あとでね」の 2 択).
        何の話か (働きかけの talk: 話の向き) と返し方の合い方で, 受け取り方 (good / neutral / bad) が決まる (core/react.py).
        よく効けば「応じた」ときの効き目. 相手の返しは, メッセージの返しと同じセリフを対面の言い方で."""
        app = self.app
        tone = a.get("talk") or "plain"
        kind = choice if choice in [c["id"] for c in react.face_choices(tone)] else "re_more"
        st["approach"] = None
        self.touch(now)
        st["last_interaction"] = now
        st["ap_quiet_until"] = now + float(self.cfg().get("approach_quiet_minutes", 20)) * 60
        res, score = react.judge(app, char, st, tone, kind)
        app.trace.add("approach", "そばで話しかけられて返した: %s → %s" % (kind, res), char["id"], now, ap=a["id"], tone=tone,
                      score=round(score, 1))
        out = a.get("accept") or {}
        mult = app.life.skill_mult("talk")
        if res == "good":
            eff = {k: (float(v) * mult if float(v) * (1 if not (app.param_def(k) or {}).get("invert") else -1) > 0 else float(v))
                   for k, v in (out.get("effects") or {}).items()}
        else:
            eff = dict(msgreply.EFFECT[res])
        eff, _ = app.bonds.realize(char, st, eff, "_ap_" + a["id"], now)
        app.bonds.touch(st, now)
        deltas = app.apply_effects(st, app.trait_effects(char, eff))
        app.life.train("talk", 1.0)
        call = app.pronouns(char)[2]
        if res == "good" and out.get("reason_good") and deltas.get("mood", 0) > 0:
            app.life.add_reason(st, "player", "good", out["reason_good"].replace("{call}", call), now, told=True,
                                delta=deltas.get("mood", 0), action="_ap_" + a["id"])
        if res == "bad":
            app.life.add_reason(st, "player", "bad", react.BAD_TELL[kind].replace("{call}", call), now, told=True,
                                delta=deltas.get("mood", 0), action="_react")
        nori.after_choice(app, char, st, now, res)
        key = "chat.react_%s_%s" % (kind[3:], res)
        line = react.face_line(app.persona_text(char, key) or react.LINES[key])
        e = self._entry(char, st, now, a, "reply", line, deltas, None, gen=False)     # ほかの対面のコマンドと同じく, 相手のセリフだけ
        e["said"] = react.said(kind)
        e["reply"] = {"kind": kind, "result": res}
        app.save_state(char["id"])
        return e

    def reply_land(self, char, st, aid, kind, now, auto=False, why=None, re_t=None, quote=None):
        """働きかけへのあなたの返事を, 相手が読んだ: 受け取り方 (good / neutral / bad) で効き目と返しが変わり, ときどきもう一言."""
        a = self.find(aid) or {"id": aid}
        out = a.get("accept") or {}
        mult = self.app.life.skill_mult("talk")
        if kind in react.AP_KINDS:       # 「返す」の種類: 何の話か (働きかけ・理由) と返し方の合い方で (core/react.py)
            res, _ = react.judge(self.app, char, st, react.ap_tone(a["id"], why), kind)
            cat = react.CAT[kind]
        else:
            res = msgreply.judge(char, st, a["id"], kind, mult, noise=25 if auto else 15, why=why)     # 自動の返事は, 相手の様子を読み違えやすい
            cat = kind
        self.app.attach.move(char, st, "dependence", 0.4, "送ったメッセージに返事が来た", now)
        if res == "good":
            eff = {k: (float(v) * mult if float(v) * (1 if not (self.app.param_def(k) or {}).get("invert") else -1) > 0 else float(v))
                   for k, v in (out.get("effects") or {}).items()}
        else:
            eff = dict(msgreply.EFFECT[res])
        if auto:                                     # 自動の返事 (画面を閉じていた間): 効き目を弱く
            eff = {k: v * 0.5 for k, v in eff.items()}
        eff, _ = self.app.bonds.realize(char, st, eff, "_ap_" + a["id"], now)        # 揺らぎ・鈍り・繰り返し
        self.app.bonds.touch(st, now)
        deltas = self.app.apply_effects(st, self.app.trait_effects(char, eff))
        self.app.life.train("talk", 1.0)
        call = self.app.pronouns(char)[2]
        if res == "good" and out.get("reason_good") and deltas.get("mood", 0) > 0:
            self.app.life.add_reason(st, "player", "good", out["reason_good"].replace("{call}", call), now, told=True,
                                     delta=deltas.get("mood", 0), action="_ap_" + a["id"])
        if res == "bad":
            self.app.life.add_reason(st, "player", "bad", (react.BAD_TELL.get(kind) or msgreply.BAD_TELL[cat]).replace("{call}", call), now, told=True,
                                     delta=deltas.get("mood", 0), action="_ap_" + a["id"])
        key = "msgr.%s.%s" % (a["id"] if a["id"] in msgreply.AP_REPLY else cat, res)
        text = self.app.persona_text(char, key) or msgreply.LINES[key]
        if res == "bad" and why in msgreply.WHY_BAD:          # よくなかった: 理由をにじませる (次から読めるように)
            text = self.app.persona_text(char, "msgr.why.%s.bad" % why) or msgreply.WHY_BAD[why]
        e = self._entry(char, st, now, a, "reply", text, deltas, None, gen=False)
        e["reply"] = {"kind": kind, "result": res}
        chat = self.app.chat
        chat.mark_read_by_her(char["id"], now)
        chat.add(char["id"], "her", e["text"], kind="approach", t=now + 0.001, re=chat.ref(char["id"], re_t or now,
                 random.random() < react.quote_chance(self.app, char, st) if quote is None else quote))
        closing = nori.after_choice(self.app, char, st, now, res)
        lv = nori.level(st, now)
        if closing:                                            # ノリが下がりきった: 相手から切り上げる
            ck, ctext = nori.close(self.app, char, st, now)
            chat.add(char["id"], "her", ctext, kind=ck, t=now + 0.002)
            e["closed"] = ck
        elif random.random() < msgreply.MORE_RATE[res] * (1.0 if lv is None else 0.5 + lv):   # 会話している感じ: もう一言 (乗っているほど)
            more = self.app.persona_text(char, "msgr.more." + res) or msgreply.LINES["msgr.more." + res]
            d = datetime.fromtimestamp(now)
            more = self.app.format_text(more, char, self.app.scene_at(char, st, d), d)
            chat.add(char["id"], "her", more, kind="approach", t=now + 0.002)
            e["more"] = more
        if not closing:
            self.app.picked_up_phone(char, st, now)
        self.app.save_log(char["id"])
        self.app.save_state(char["id"])
        return e

    def drop(self, st):
        """あなたが別のことで構ったら, 待っていた働きかけはそれで済んだことにする."""
        if st.get("approach"):
            st["approach"] = None
            st["ap_quiet_until"] = time.time() + float(self.cfg().get("approach_quiet_minutes", 20)) * 60

    def pending_view(self, char, st):
        ap = st.get("approach")
        if not ap:
            return None
        a = self.find(ap["id"]) or {}
        return {"id": ap["id"], "entry": ap.get("entry"), "until": ap["until"], "label": a.get("label", ""), "act": ap.get("act"),
                "icon": a.get("icon", "💬"), "apart": bool(a.get("apart")),
                "accept": (a.get("accept") or {}).get("label") or "うん", "later": (a.get("later") or {}).get("label") or "あとでね",
                "choices": msgreply.options(ap["id"], ap.get("why")) if a.get("apart")
                else react.face_choices(a["talk"]) if a.get("talk") else None}       # そばで話しかけられた: 返し方を選ぶ

