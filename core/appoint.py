"""約束 (アポ): 同居していない相手とは, 約束してから会う.

- こちらから: トークの「📅 約束する」で, 日時・行き先 (core/places.py の表)・何をするか (お出かけのコマンド. 相手の家なら訪ねる,
  あなたの家なら招く) を決めて誘う. 返事はいつものメッセージの時間差で届く (msg_pending の kind "appoint").
  受けるかは仲・機嫌・慎重さ・その時間の相手の予定 (予定があれば断られる)・「会おうよ」に応じていたか (date_promise) しだい.
- 相手から: 離れている連絡先の相手が, ときどきメッセージで誘ってくる (仲・寂しさ・その日の機嫌・ストレス・体調・性格しだい.
  出会わせる方向の補正はなし). 行き先は, その人の好み (好きなもの)・一緒に行って楽しかった所・まだ行ったことのない所で,
  少しだけ選ばれやすさが傾く (性格で決め打ちしない. どの人でも幅広い行き先から). トークで 受ける / 断る / 「別の日時なら」と返す.
  別の案には, 相手がその時間の予定・仲・機嫌・性格しだいで 受ける / 断る / さらに別の案を返す (やりとりは COUNTER_MAX 回まで).
  丸一日返事をしなければ, 流れる (少し寂しがる).
- 約束の場所へは, 自分で出向く: ふつうの外出 (一人の「外出」で行き先を約束の場所に) で行く. 約束の場所にいる状態で約束の時刻を
  迎えると会える (早く着けば, その場で待つ. 待っている間も外出中で, 偶然の出会いなども普段どおり. 別の用事で同じ場所に来ていても会える).
  相手の家での約束は, 相手の家へ出向く (約束の前後なら, 約束なしの訪問ではなく玄関先で待つ). あなたの家に招く約束は, 家にいればよい.
  移動に時間はかからない (ほかの外出と同じく, 出かけたらすぐ着く). 外出は画面を開いている間だけなので, 閉じれば家に帰る (= いない).
- 相手の側は, 約束したときに決まっている (見えない):
  すっぽかし (仲が浅いほど・時間にルーズな性格ほど) / 遅刻 (性格の punctual しだい) / 体調不良のキャンセル (3 時間前ごろ, 健康しだい).
  来なければ, その場所で待ちぼうけ (30 分待って来なければあきらめる. あとで謝りのメッセージが来ることも). 遅れて来れば, それまで待つ.
- あなたが約束の時刻に約束の場所にいなければ遅刻: 遅れて着けば少し機嫌を損ね, 45 分たってもいなければ (画面を閉じていても)
  すっぽかしたことになる (相手は傷つく). 画面を開いたまま放置していても, 行動パターンでは出向かない (手動で).
- 会ったら, 約束したお出かけのコマンドを実行する (条件は約束したときに済んでいる). 新しい交流は bonds.realize を通る (act の中).
記録は player.json の appoints ([{id, cid, t, place, do, by, status, plan, made, ...}]).
status: asked (返事待ち) / offered (相手からの誘い) / set (約束した) / waiting (着いて待っている) / met / stood_up (相手が来なかった) /
        missed (あなたが行かなかった) / declined / cancelled.
"""
import random
import time
import uuid
from datetime import datetime, timedelta

from . import cond
from . import places as places_mod

EARLY = 15 * 60          # 約束の時刻のこれだけ前から「もうすぐ」として知らせる
GRACE = 45 * 60          # 約束の時刻からこれだけ過ぎても約束の場所にいなければ, すっぽかしたことに
LATE_ME = 10 * 60        # これより遅れて着くと, 相手は少し機嫌を損ねる
GIVE_UP = 30 * 60        # 相手が来ないとき, これだけ待ったらあきらめる
NEAR = 3 * 3600          # 約束のこれだけ前からは, 相手の家へ出かけると「約束の訪問」(玄関先で待つ)
COUNTER_MAX = 3          # 誘いへの「別の日時なら」のやりとりの回数の上限 (あなたと相手の案を合わせて)
# 好きなもの (items の好みの印) → 行きたくなる行き先 (気持ち傾くだけ)
LIKE_PLACES = {"books": ("bookstore",), "sweets": ("cafe", "mall"), "tea": ("cafe",), "flowers": ("park", "hill"),
               "games": ("electronics", "amusement"), "food": ("teishoku", "ramen", "restaurant", "shopping_street"),
               "cute": ("aquarium", "mall"), "fashion": ("mall",), "accessories": ("mall",), "practical": ("supermarket", "mall")}
OPEN = ("asked", "offered", "set", "waiting")
STATUS_LABEL = {"asked": "返事待ち", "offered": "誘われている", "set": "約束した", "waiting": "待っている", "met": "会えた",
                "stood_up": "来なかった", "missed": "行かなかった", "declined": "断られた", "cancelled": "キャンセル",
                "refused": "断った", "lapsed": "流れた"}
HOME_DO = {"visit": "visit_home", "guest": "invite_home"}


def fmt_when(t, now=None):
    d = datetime.fromtimestamp(t)
    n = datetime.fromtimestamp(now or time.time())
    days = (d.date() - n.date()).days
    day = {0: "今日", 1: "明日", 2: "あさって"}.get(days) or "%d/%d（%s）" % (d.month, d.day, "月火水木金土日"[d.weekday()])
    return "%s %d:%02d" % (day, d.hour, d.minute)


def phase_ok(app, a, dt):
    """コマンドの条件のうち, 時間帯 (phase) だけを見る (ほかの条件は会うときの状態しだいなので, 約束では見ない)."""
    parts = [p.strip() for p in (a.get("when") or "").split(",") if p.strip().startswith("phase")]
    return cond.check(", ".join(parts), {"phase": app.phase_at(dt).get("id", "")}) if parts else True


class Appoint:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 記録
    def all(self):
        ps = self.app.life.player_state()
        return ps.setdefault("appoints", [])

    def save(self):
        lst = self.all()
        now = time.time()
        lst[:] = [x for x in lst if x["status"] in OPEN or now - x["t"] < 30 * 86400][-60:]
        self.app.life.save_player()

    def get(self, aid):
        x = next((x for x in self.all() if x["id"] == aid), None)
        if not x:
            raise KeyError("約束が見つかりません: %s" % aid)
        return x

    def open_with(self, cid):
        return [x for x in self.all() if x["cid"] == cid and x["status"] in OPEN]

    # ------------------------------------------------------------------ 何ができるか
    def needs(self, a, cid):
        """離れている相手と, このコマンドで会うのに約束がいるか (お出かけ・訪問・招く. 同居相手は いらない)."""
        if self.app.bonds.stage(cid) == "live":
            return False
        return bool((a.get("override") or {}).get("outing")) or a.get("bond") in ("visit_start", "guest_start")

    def dos_at(self, cid, pid):
        """その行き先で, その相手と約束できること (コマンド)."""
        app = self.app
        if pid == places_mod.HOME_ME:
            return [app.action("invite_home")] if app.bonds.stage(cid) == "visit" else []
        if places_mod.is_home(pid):
            return [app.action("visit_home")] if places_mod.home_of(pid) == cid and app.bonds.stage(cid) == "visit" else []
        out = []
        for a in app.actions:
            ov = a.get("override") or {}
            if not ov.get("outing") or a.get("category") == "system":
                continue
            if pid in (a.get("places") or [ov.get("place")]):
                out.append(a)
        return out

    def choices(self, cid):
        """約束の行き先と, そこですること (画面の選択肢)."""
        app = self.app
        out = []
        for pid, p in app.places.table().items():
            dos = self.dos_at(cid, pid)
            if dos:
                out.append({"place": pid, "label": p["label"], "icon": p["icon"], "group": p["group"],
                            "hours": places_mod.hours_label(pid),
                            "dos": [{"id": a["id"], "name": a.get("name", a["id"]), "icon": a.get("icon", "")} for a in dos]})
        return out

    # ------------------------------------------------------------------ こちらから誘う
    def propose(self, cid, t, place, do, now=None):
        app = self.app
        now = now or time.time()
        char = app.char(cid)
        cid = char["id"]
        stage = app.bonds.stage(cid)
        if stage == "known":
            raise ValueError("%sの連絡先を知りません" % char.get("name", ""))
        if stage == "live":
            raise ValueError("一緒に暮らしているので、約束しなくても出かけられます")
        t = float(t)
        if t < now + 30 * 60 or t > now + 14 * 86400:
            raise ValueError("約束は 30 分後から 2 週間先までです")
        if not any(a["id"] == do for a in self.dos_at(cid, place)):
            raise ValueError("その行き先では、それはできません")
        a = app.action(do)
        if not phase_ok(app, a, datetime.fromtimestamp(t)):
            raise ValueError("「%s」はその時間帯にはできません（%s）" % (a.get("name", do), a.get("when", "")))
        o = places_mod.open_state(place, datetime.fromtimestamp(t))
        if not o["open"]:
            raise ValueError("その時間、%sは閉まっています（%s・%s）" % (app.places.label(place), o["note"], o["hours"]))
        for x in self.open_with(cid):
            if abs(x["t"] - t) < 3 * 3600:
                raise ValueError("その時間の近くに、もう約束（か返事待ち）があります")
        x = {"id": uuid.uuid4().hex[:8], "cid": cid, "t": t, "place": place, "do": do, "by": "me", "status": "asked", "made": now}
        self.all().append(x)
        self.save()
        self._send(x, now, "（%s、%sで「%s」に誘った）" % (fmt_when(t, now), app.places.label(place), a.get("name", do)))
        return dict(x, label=STATUS_LABEL[x["status"]])

    def reply(self, char, st, pend, now, ctx):
        """誘いへの返事 (時間差で届いたとき). (セリフの場面, 効果, 置き換え) を返す."""
        app = self.app
        try:
            x = self.get(pend.get("appoint"))
        except KeyError:
            return "appoint_no", {}, {"when": "", "place": ""}
        extra = {"when": fmt_when(x["t"], now), "place": app.places.label(x["place"])}
        if x["status"] != "asked":
            return "appoint_no", {}, extra
        p = st["params"]
        busy = app.scheduled_scene(char, datetime.fromtimestamp(x["t"]))
        if (busy["away"] or busy["busy"] or busy["asleep"]) and not places_mod.is_home(x["place"]) and random.random() < 0.8:
            alt = self._alt_time(char, x, now) if x.get("counter") and int(x.get("rounds", 0)) < COUNTER_MAX else None
            if alt and random.random() < 0.3 + (p.get("affection", 50) - 50) / 100.0 + (p.get("mood", 50) - 50) / 200.0:
                return self._counter_back(x, alt, now, extra)        # その時間は無理だけど, この時間なら
            x["status"] = "declined"
            self.save()
            return "appoint_busy", {}, extra
        promised = st.get("date_promise", 0) > now or bool(x.get("counter"))        # 自分から誘った話の続き
        pa = 0.35 + (p.get("affection", 50) - 50) / 80.0 + (p.get("mood", 50) - 50) / 150.0 \
            - float(app.traits(char).get("caution", 0)) / 50.0 + (0.1 if app.bonds.stage(char["id"]) == "visit" else 0.0) \
            + (0.3 if promised else 0.0) - (0.3 if ctx.get("too_often") else 0.0)
        if places_mod.is_home(x["place"]) and app.bonds.stage(char["id"]) != "visit":
            pa = 0
        if random.random() < max(0.03, min(0.95, pa)):
            x["status"] = "set"
            x["plan"] = self._plan(char, st)
            st.pop("date_promise", None)
            self.save()
            return "appoint_yes", {"heart": 2, "mood": 2}, extra
        if x.get("counter") and int(x.get("rounds", 0)) < COUNTER_MAX and random.random() < 0.35:
            alt = self._alt_time(char, x, now)
            if alt:
                return self._counter_back(x, alt, now, extra)
        x["status"] = "declined"
        self.save()
        return "appoint_no", {}, extra

    def _counter_back(self, x, t, now, extra):
        """相手が, さらに別の日時を返してくる (あなたが受ける / 断る / また返す)."""
        x.update(t=t, status="offered", made=now, rounds=int(x.get("rounds", 0)) + 1)
        self.save()
        extra = dict(extra, when=fmt_when(t, now))
        return "appoint_counter", {}, extra

    def _plan(self, char, st):
        """相手の側の, 当日のこと (約束したときに決まる. 画面には出さない). 体調不良のキャンセルは当日の健康で決める."""
        p = st["params"]
        punctual = float(self.app.traits(char).get("punctual", 0.75))
        noshow = random.random() < 0.02 + (1 - punctual) * 0.08 + max(0.0, 45 - p.get("affection", 50)) / 300.0
        late = 0
        if not noshow and random.random() > punctual:
            late = int(random.uniform(5, 40) * (1.5 - punctual))
        return {"noshow": noshow, "late": late, "cancel_checked": False}

    # ------------------------------------------------------------------ 相手から誘われる
    def answer(self, aid, yes, now=None):
        app = self.app
        now = now or time.time()
        x = self.get(aid)
        if x["status"] != "offered":
            raise ValueError("いまは誘われていません")
        char = app.char(x["cid"])
        with app.lock:
            st = app.state(x["cid"])
            if yes:
                x["status"] = "set"
                x["plan"] = self._plan(char, st)
                eff, _ = app.bonds.realize(char, st, {"mood": 3, "heart": 2, "affection": 0.5}, "_appoint", now)
                app.bonds.touch(st, now)
                app.chat.add(x["cid"], "me", "（%s、%sの約束をした）" % (fmt_when(x["t"], now), app.places.label(x["place"])),
                             kind="appoint", t=now)
            else:
                x["status"] = "refused"
                eff = {"mood": -2}
                app.chat.add(x["cid"], "me", "（誘いを断った）", kind="appoint", t=now)
            app.apply_effects(st, app.trait_effects(char, eff))
            app.chat.mark_read_by_her(x["cid"], now)
            app.save_state(x["cid"])
        self.save()
        return {"ok": True, "status": x["status"]}

    def _maybe_invite(self, cid, now, h):
        """離れている連絡先の相手が, ときどき誘ってくる (仲・寂しさ・性格しだい. 仲が浅いうちは誘わない)."""
        app = self.app
        if app.bonds.stage(cid) not in ("contact", "visit") or app.bonds.together(cid) or self.open_with(cid):
            return None
        char, st = app.chars[cid], app.state(cid)
        p = st["params"]
        if p.get("affection", 0) < 45:
            return None
        rate = 0.02 * max(0.1, (p.get("affection", 50) - 35) / 30.0 + (p.get("loneliness", 30) - 40) / 80.0) \
            * float(app.traits(char).get("approach", 1)) * self.mood_factor(p)
        if random.random() >= rate * h:
            return None
        dt0 = datetime.fromtimestamp(now)
        for _ in range(8):
            day = (dt0 + timedelta(days=random.randint(1, 5))).replace(hour=random.choice((11, 13, 15, 18)), minute=0,
                                                                       second=0, microsecond=0)
            sc = app.scheduled_scene(char, day)
            if sc["away"] or sc["busy"] or sc["asleep"]:
                continue
            opts = [(pid, a) for pid in places_mod.OUT_PLACES for a in self.dos_at(cid, pid)
                    if phase_ok(app, a, day) and places_mod.open_state(pid, day)["open"]]
            if not opts:
                continue
            pid, a = self.pick(char, st, opts)
            x = {"id": uuid.uuid4().hex[:8], "cid": cid, "t": day.timestamp(), "place": pid, "do": a["id"], "by": "her",
                 "status": "offered", "made": now}
            self.all().append(x)
            self.save()
            text = app.chat.line(char, "appoint_invite", {"when": fmt_when(x["t"], now), "place": app.places.label(pid)})
            app.chat.add(cid, "her", text + "（%s）" % a.get("name", ""), kind="appoint_invite", t=now, appoint=x["id"])
            app.picked_up_phone(char, st, now)
            app.save_state(cid)
            return x
        return None

    @staticmethod
    def mood_factor(p):
        """その日の気分での, 誘う気持ちの強さ (落ち込んでいる・ストレスが高い・体調が悪い日は誘いにくい. 機嫌がいい日は誘いやすい)."""
        f = 1.0 + (p.get("mood", 50) - 50) / 60.0
        if p.get("stress", 0) > 65:
            f *= 0.6
        if p.get("health", 90) < 50:
            f *= 0.35
        return max(0.1, min(1.5, f))

    def place_weight(self, char, st, pid):
        """行き先の選ばれやすさ (気持ち傾くだけ. 0.8〜1.5): 好きなものに合う所・一緒に行って楽しかった所・まだ行ったことのない所."""
        lk, dk = self.app.items.likes(char)
        w = 1.0
        if any(pid in LIKE_PLACES.get(t, ()) for t in lk):
            w += 0.25
        if any(pid in LIKE_PLACES.get(t, ()) for t in dk):
            w -= 0.2
        fun = (st.get("place_fun") or {}).get(pid)
        if fun is None:
            w += 0.1                                  # 行ったことのない所への興味
        else:
            w += max(-0.15, min(0.2, fun / 25.0))     # 一緒に行って楽しかった (つまらなかった)
        return max(0.8, min(1.5, w))

    def pick(self, char, st, opts):
        """誘う行き先とすること. 好みで少しだけ傾けて, あとは偶然."""
        return random.choices(opts, [self.place_weight(char, st, pid) for pid, _ in opts])[0]

    def remember(self, cid, place, mood_delta):
        """一緒に行った行き先の楽しさを覚える (次に誘うときに, 少しだけ選ばれやすく)."""
        st = self.app.state(cid)
        pf = st.setdefault("place_fun", {})
        pf[place] = round(0.6 * float(pf.get(place, 0.0)) + 0.4 * float(mood_delta) * 3, 2)

    # ------------------------------------------------------------------ 誘いに「別の日時なら」
    def counter(self, aid, t, place=None, do=None, now=None):
        """相手からの誘い (offered) に, 別の日時 (・行き先) を返す. 返事は時間差 (msg_pending の kind appoint)."""
        app = self.app
        now = now or time.time()
        x = self.get(aid)
        if x["status"] != "offered":
            raise ValueError("いまは誘われていません")
        if int(x.get("rounds", 0)) >= COUNTER_MAX:
            raise ValueError("もう何度もやりとりしているので、受けるか断るかにしましょう")
        place = place or x["place"]
        do = do or x["do"]
        t = float(t)
        if t < now + 30 * 60 or t > now + 14 * 86400:
            raise ValueError("約束は 30 分後から 2 週間先までです")
        if not any(a["id"] == do for a in self.dos_at(x["cid"], place)):
            raise ValueError("その行き先では、それはできません")
        a = app.action(do)
        if not phase_ok(app, a, datetime.fromtimestamp(t)):
            raise ValueError("「%s」はその時間帯にはできません（%s）" % (a.get("name", do), a.get("when", "")))
        o = places_mod.open_state(place, datetime.fromtimestamp(t))
        if not o["open"]:
            raise ValueError("その時間、%sは閉まっています（%s・%s）" % (app.places.label(place), o["note"], o["hours"]))
        x.update(t=t, place=place, do=do, status="asked", made=now, rounds=int(x.get("rounds", 0)) + 1, counter=True)
        self.save()
        self._send(x, now, "（別の日時なら、と返した: %s、%sで「%s」）" % (fmt_when(t, now), app.places.label(place), a.get("name", do)))
        return dict(x, label=STATUS_LABEL[x["status"]])

    def _send(self, x, now, text):
        """約束の誘い・別の案を送る (トークに要約. 返事はいつものメッセージの時間差・すぐの返信)."""
        app = self.app
        cid = x["cid"]
        char = app.chars[cid]
        with app.lock:
            st = app.state(cid)
            scene = app.scene_at(char, st, datetime.fromtimestamp(now))
            ctx = app.context(char, st, datetime.fromtimestamp(now), scene)
            app._phoned(st, now)
            app.chat.add(cid, "me", text, kind="appoint", t=now)
            pend = st.get("msg_pending")
            if pend:            # 返信は, いちばん新しいメッセージに対して
                pend.update(kind="appoint", appoint=x["id"], count=pend.get("count", 1) + 1, reply=True)
            else:
                p = st["params"]
                delay = random.uniform(3, 40) * 60 * (2 if p.get("mood", 50) < 35 else 1)
                quick = app._still_on_phone(char, st, now, scene, ctx)
                if quick:
                    delay = random.uniform(10, 90)
                st["msg_pending"] = {"aid": "message", "t": now, "due": now + delay, "reply": True, "count": 1, "kind": "appoint",
                                     "appoint": x["id"], "quick": quick}
            app.presence.drop(st)
            app.save_state(cid)

    def _alt_time(self, char, x, now):
        """相手が返す別の案: あなたの案の近く (前後の日・時間) で, 相手の予定が空いていて, 行き先が開いている時間. 無ければ None."""
        app = self.app
        base = datetime.fromtimestamp(x["t"])
        a = app.action(x["do"])
        for _ in range(12):
            d = (base + timedelta(days=random.choice((0, 0, 1, -1, 2)))).replace(
                hour=random.choice((10, 11, 13, 14, 15, 16, 17, 18, 19)), minute=0, second=0, microsecond=0)
            if d.timestamp() < now + 3600 or abs(d.timestamp() - x["t"]) < 3600:
                continue
            sc = app.scheduled_scene(char, d)
            if sc["away"] or sc["busy"] or sc["asleep"]:
                continue
            if phase_ok(app, a, d) and places_mod.open_state(x["place"], d)["open"]:
                return d.timestamp()
        return None

    # ------------------------------------------------------------------ 当日
    def due_at(self, place, now=None):
        """その行き先での, 近いうちの約束 (相手の家へ出かけるときに, 約束なしの訪問と区別する)."""
        now = now or time.time()
        return next((x for x in self.all() if x["status"] in ("set", "waiting") and x["place"] == place
                     and x["t"] - NEAR <= now <= x["t"] + GRACE), None)

    def here(self, place, now=None):
        """あなたがいま, その約束の場所にいるか (外出の行き先 / あなたの家なら家にいる)."""
        app = self.app
        p = app.presence.rec()
        mode = p.get("mode")
        w = app.bonds.with_rec()
        if place == places_mod.HOME_ME:
            return mode in ("none", "busy") and not (w and w["mode"] in ("meet", "visit")) and not app.outdoor.current(now)
        return mode == "out" and (p.get("place") or "town") == place and not w

    def go(self, aid, now=None):
        """約束の場所へ出かける (ふつうの外出. 行き先を約束の場所に). あなたの家に招く約束なら, 家にいればよい."""
        app = self.app
        now = now or time.time()
        x = self.get(aid)
        if x["status"] not in ("set", "waiting"):
            raise ValueError("この約束はもう%s" % STATUS_LABEL.get(x["status"], x["status"]))
        if self.here(x["place"], now):
            return {"status": "here", "text": "（もう%sにいる。%sの約束の時刻を待つ）" % (app.places.label(x["place"]), fmt_when(x["t"], now))}
        if x["place"] == places_mod.HOME_ME:
            raise ValueError("あなたの家に来てもらう約束です（%sに家にいれば会えます）" % fmt_when(x["t"], now))
        pres = app.presence.rec()
        if pres.get("mode") == "out":          # 一人で出かけていたなら, そこから向かう (結果は残す)
            ll = app.presence.back(now)
            if ll:
                app.solo.finish(ll)
        r = app.solo.start("out", place=x["place"])
        return dict(r, status="going", text="（%sへ出かけた。約束は%s）" % (app.places.label(x["place"]), fmt_when(x["t"], now)))

    def arrive_home_of(self, place, now=None):
        """相手の家へ出かけた (約束の訪問): 約束なしの訪問ではなく, 玄関先で約束の時刻を待つ (外出中)."""
        app = self.app
        now = now or time.time()
        app.presence.declare("out", now)
        pr = app.presence.rec()
        pr["solo"] = {"kind": "out", "skill": None, "t": now, "appoint": True}
        pr["place"] = place
        app.presence.save()
        x = self.due_at(place, now)
        text = "%sの家の前に着いた（約束は%s）" % (app.places.label(place).replace("の家", ""), fmt_when(x["t"], now) if x else "")
        app.solo.note("out", text, now)
        return {"started": "out", "label": "%sへ" % app.places.label(place), "act": None, "done": "（%s）" % text}

    def _tick(self, x, now, out):
        """約束の時刻の前後: あなたが約束の場所にいるか・相手が来るか (遅刻・すっぽかし) を進める. 変わったら True."""
        app = self.app
        char = app.chars[x["cid"]]
        plan = x.setdefault("plan", {})
        at = self.here(x["place"], now)
        if now < x["t"] - NEAR:
            return False
        if at:
            x.setdefault("arrived", now)          # 着いた時刻 (早く着いていれば, 約束の時刻より前)
        elif now < x["t"]:
            x.pop("arrived", None)                # 時刻の前に離れた: 着いていないことに
        if now < x["t"]:
            return False
        arrived = x.get("arrived")
        if plan.get("noshow"):
            if at and now >= max(x["t"], arrived) + GIVE_UP:       # 待ったが来なかった
                x["status"] = "stood_up"
                x["sorry_at"] = now + random.uniform(30, 180) * 60
                text = "%sで待っていたが、%sは来なかった" % (app.places.label(x["place"]), char.get("name", ""))
                app.outdoor.note(text, now)
                app.solo.note("out", text, now)
                out.append(text)
                return True
            if not arrived and now > x["t"] + GRACE:
                x["status"] = "missed"            # 二人とも来なかった (相手は気にしない)
                return True
            return False
        come = x["t"] + plan.get("late", 0) * 60
        if at and now >= come:
            r = self._meet(x, now, arrived - x["t"] > LATE_ME)
            out.append((r.get("entry") or {}).get("text", "").split("\n")[0] or "%sと会えた" % char.get("name", ""))
            return True
        if at and x["status"] == "set":
            x["status"] = "waiting"               # 着いた. 相手はまだ
            out.append("%sに着いた。%sはまだ来ていない" % (app.places.label(x["place"]), char.get("name", "")))
            return True
        if not at and x["status"] == "waiting":
            x["status"] = "set"                   # 待つのをやめて離れた
        if now > x["t"] + GRACE:                  # 約束の時刻を過ぎても, その場所にいなかった
            x["status"] = "missed"
            st = app.state(x["cid"])
            with app.lock:
                d = app.apply_effects(st, app.trait_effects(char, {"mood": -8, "trust": -4, "affection": -2}))
                app.life.add_reason(st, "player", "bad", "%sが約束をすっぽかした" % app.pronouns(char)[2], now,
                                    told=True, delta=d.get("mood", 0), action="_appoint")
                app.chat.add(x["cid"], "her", app.chat.line(char, "appoint_missed", {}), kind="appoint_missed", t=x["t"] + GRACE)
                app.save_state(x["cid"])
            out.append("%sとの約束（%s）に行かなかった" % (char.get("name", ""), fmt_when(x["t"], now)))
            return True
        return False

    def _meet(self, x, now, me_late=False):
        app = self.app
        cid = x["cid"]
        char = app.char(cid)
        if app.presence.rec().get("mode") == "out":
            ll = app.presence.back(now)
            if ll:
                app.solo.finish(ll)
        late = (x.get("plan") or {}).get("late", 0) if x.get("status") == "waiting" else 0
        x["status"] = "met"
        self.save()
        opts = {"appointment": x["id"]}
        if x["place"] in places_mod.PLACES:
            opts["place"] = x["place"]
        r = app.act(x["do"], cid, opts=opts)
        if r.get("entry") and x["place"] in places_mod.PLACES:
            self.remember(cid, x["place"], (r["entry"].get("deltas") or {}).get("mood", 0))
        notes = []
        if late:
            notes.append("（%sは%d分ほど遅れて来た）" % (char.get("name", ""), late))
        if me_late:             # あなたが遅れて行った: 少し機嫌を損ねる (性格しだい)
            with app.lock:
                st = app.state(cid)
                d = app.apply_effects(st, app.trait_effects(char, {"mood": -3}))
                app.life.add_reason(st, "player", "bad", "%sが約束に遅れてきた" % app.pronouns(char)[2], now, told=False,
                                    delta=d.get("mood", 0), action="_appoint")
                app.save_state(cid)
            notes.append("（約束の時間に遅れてしまった）")
        if notes and r.get("entry"):
            r["entry"]["text"] = "\n".join(notes) + "\n" + r["entry"]["text"]
            app.save_log(cid)
        return dict(r, status="met")

    def live(self, now=None):
        """画面を開いている間 (state_view のたび). 期限・キャンセル・遅れて来た相手・相手からの誘い・すっぽかしを進める.
        何か起きたら [テキスト] を返す."""
        app = self.app
        now = now or time.time()
        out = []
        changed = False
        for x in list(self.all()):
            if x["status"] not in OPEN and not (x["status"] == "stood_up" and x.get("sorry_at")):
                continue
            cid = x["cid"]
            if cid not in app.chars:
                x["status"] = "cancelled"
                changed = True
                continue
            char = app.chars[cid]
            st = app.state(cid)
            if x["status"] in ("asked", "offered") and (now - x["made"] > 24 * 3600 or now > x["t"]):
                if x["status"] == "offered":          # 誘ったのに返事がなかった
                    app.apply_effects(st, app.trait_effects(char, {"mood": -3, "loneliness": 4}))
                    app.save_state(cid)
                x["status"] = "lapsed"
                changed = True
            elif x["status"] == "set":
                plan = x.setdefault("plan", {})
                if not plan.get("cancel_checked") and now >= x["t"] - 3 * 3600:
                    plan["cancel_checked"] = True
                    changed = True
                    sick = st["params"].get("health", 90) < 45
                    if random.random() < (0.6 if sick else 0.03):
                        x["status"] = "cancelled"
                        app.chat.add(cid, "her", app.chat.line(char, "appoint_cancel", {}), kind="appoint_cancel", t=now)
                        app.picked_up_phone(char, st, now)
                        app.save_state(cid)
                        out.append("%sから、約束のキャンセルの連絡が来た" % char.get("name", ""))
                        continue
                changed = self._tick(x, now, out) or changed
            elif x["status"] == "waiting":
                changed = self._tick(x, now, out) or changed
            elif x["status"] == "stood_up" and now >= x.get("sorry_at", 9e18):
                x.pop("sorry_at", None)
                changed = True
                if random.random() < 0.3 + st["params"].get("trust", 40) / 150.0:      # 謝ってくるかは, 人しだい
                    app.chat.add(cid, "her", app.chat.line(char, "appoint_sorry", {}), kind="appoint_sorry", t=now)
                    app.save_state(cid)
        last = app.presence.rec().get("appoint_check") or now
        app.presence.rec()["appoint_check"] = now
        h = min(max(now - last, 0), 600) / 3600.0
        if h:
            for cid in list(app.chars):
                if self._maybe_invite(cid, now, h):
                    out.append("%sから誘いのメッセージが来た" % app.chars[cid].get("name", ""))
        if changed:
            self.save()
        return out

    # ------------------------------------------------------------------ 表示
    def view(self, now=None):
        app = self.app
        now = now or time.time()
        out = []
        for x in sorted(self.all(), key=lambda x: x["t"]):
            if x["status"] not in OPEN or x["cid"] not in app.chars:
                continue
            due = x["status"] in ("set", "waiting") and x["t"] - EARLY <= now <= x["t"] + GRACE
            out.append({"here": x["status"] in ("set", "waiting") and self.here(x["place"], now),
                        "home_me": x["place"] == places_mod.HOME_ME, "remain": int(x["t"] - now), "id": x["id"], "cid": x["cid"], "name": app.chars[x["cid"]].get("name", ""), "t": x["t"],
                        "when": fmt_when(x["t"], now), "place": x["place"], "place_label": app.places.label(x["place"]),
                        "do": x["do"], "do_label": app.action(x["do"]).get("name", x["do"]), "by": x["by"], "status": x["status"],
                        "status_label": STATUS_LABEL[x["status"]], "due": due})
        return out
