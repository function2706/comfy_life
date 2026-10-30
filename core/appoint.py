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
- 頼まれごと (core/earn.py の favors) も約束に乗せる (favor: 頼まれごとの id, do は "_favor", 行き先は相手の家. 家に行ける仲の前
  (連絡先) でも, 頼まれごとの約束なら相手の家で約束できる例外). 引っ越しは相手が日時を決めてくる (fixed: 受けるか断るかだけ),
  大掃除・家具の組み立てなどは 相手が案を出す / こちらに都合を聞く (ask: 日時を返すまで受けられない) のどちらか. 植木の水やりは,
  相手の留守中 (t〜until) に自分で家へ行く (会わない. 期間内に行かなければ枯れてがっかり). 当日は自分で出向き, 会えたら手伝いに
  取りかかる (f["h"] 時間ほど. 戻ると earn.favor_done). すっぽかしは普段の約束より重い (当てにしていた). 返事を丸一日放っておくと
  流れる (ほかの人に頼んで済んでしまう). 相手の都合で日がずれる・取りやめになることも, まれにある.
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
FAVOR_DO = "_favor"
FAVOR_RESCHED = 0.04     # 約束の 3 時間前ごろに, 相手の都合で日がずれる・取りやめになる確率 (頼まれごと)


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
        for x in lst:                     # 状態が変わったら判断の記録に (どの道筋で変わっても)
            if x.get("_tr") != x.get("status"):
                self.app.trace.add("favor" if x.get("favor") else "appoint", "%s → %s" % (x.get("_tr") or "新規", x.get("status")),
                                   x.get("cid"), now, id=x.get("id"), at=x.get("t"), place=x.get("place"), do=x.get("label") or x.get("do"),
                                   by=x.get("by"), fixed=x.get("fixed"), ask=x.get("ask"), rounds=x.get("rounds"))
                x["_tr"] = x.get("status")
        lst[:] = [x for x in lst if x["status"] in OPEN or now - x["t"] < 30 * 86400][-60:]
        self.app.life.save_player()

    def get(self, aid):
        x = next((x for x in self.all() if x["id"] == aid), None)
        if not x:
            raise KeyError("約束が見つかりません: %s" % aid)
        return x

    def open_with(self, cid):
        return [x for x in self.all() if x["cid"] == cid and x["status"] in OPEN]

    def find(self, aid):
        return next((x for x in self.all() if x["id"] == aid), None) if aid else None

    def when_of(self, x, now=None):
        if x.get("plants"):
            return "%s〜%s" % (fmt_when(x["t"], now).split(" ")[0], fmt_when(x["until"], now).split(" ")[0])
        return fmt_when(x["t"], now)

    def favor_homes(self):
        """頼まれごとの約束がある相手の家 (家に行ける仲の前でも, 行き先の表に加える)."""
        return {places_mod.home_of(x["place"]) for x in self.all() if x.get("favor") and x["status"] in OPEN}

    def favor_status(self, x, now=None):
        if not x:
            return ""
        if x["status"] == "offered":
            return "都合を聞かれている" if x.get("ask") else ("日時が決まっている（受けるか断るか）" if x.get("fixed") else "日時の案が来ている")
        if x["status"] == "asked":
            return "返事待ち"
        if x.get("plants"):
            return "留守中に水やりに行く"
        return "%sに約束" % fmt_when(x["t"], now)

    # ------------------------------------------------------------------ 頼まれごと
    def favor_offer(self, f, now, legacy=False):
        """頼まれごとが来た: 種類ごとに日時の決め方を変えて, 約束 (offered) にする. 離れていればメッセージで, そばにいれば対面で頼まれる.
        legacy: 以前から頼まれていたもの (日時を決める前の形) を, 都合を聞かれている形にする (頼まれ直すのではない)."""
        app = self.app
        cid = f["cid"]
        char = app.chars[cid]
        st = app.state(cid)
        kind = f.get("kind") or "clean"
        x = {"id": uuid.uuid4().hex[:8], "cid": cid, "place": "home:" + cid, "do": FAVOR_DO, "by": "her", "status": "offered",
             "made": now, "favor": f["id"], "fkind": kind, "label": f["label"]}
        line, extra = "favor_ask_offer", {"what": f["label"]}
        if kind == "plants":
            start = self._free_time(char, now, days=(1, 3), hours=(9,)) or now + 86400
            x.update(t=start, until=start + random.randint(2, 4) * 86400, plants=True, fixed=True, rounds=COUNTER_MAX)
            line = "favor_ask_plants"
            extra.update({"from": fmt_when(x["t"], now).split(" ")[0], "to": fmt_when(x["until"], now).split(" ")[0]})
        elif kind == "move":
            t = self._free_time(char, now, days=(2, 6), hours=(9, 10)) or now + 3 * 86400
            x.update(t=t, fixed=True, rounds=COUNTER_MAX)
            line = "favor_ask_move"
        elif legacy or random.random() < 0.4:       # いつなら空いているか, こちらに聞いてくる
            x.update(t=now + 2 * 86400, ask=True)
            line = "favor_ask_when"
        else:
            x["t"] = self._free_time(char, now, days=(1, 5), hours=(10, 13, 15)) or now + 2 * 86400
        extra["when"] = self.when_of(x, now)
        f["appoint"] = x["id"]
        f["until"] = max(f.get("until", 0), (x.get("until") or x["t"]) + 86400)
        self.all().append(x)
        self.save()
        if legacy:
            app.chat.add(cid, "sys", "（頼まれていた%sは、日時を決めて答えられるようになった。約束の欄から）" % f["label"], kind="favor", t=now)
            return x
        text = app.chat.line(char, line, extra)
        if app.bonds.together(cid):                  # そばにいる: 対面で頼まれる (記録にも残す)
            app.her_says(cid, text.replace("📱『", "「").replace("』", "」"), "頼まれごと", "🤝", now)
        app.chat.add(cid, "her", text, kind="favor_ask", t=now, appoint=x["id"])
        app.picked_up_phone(char, st, now)
        app.save_state(cid)
        return x

    def _free_time(self, char, now, days=(1, 5), hours=(10, 13, 15)):
        """相手の予定が空いている日時 (頼まれごとの案)."""
        dt0 = datetime.fromtimestamp(now)
        for _ in range(12):
            d = (dt0 + timedelta(days=random.randint(*days))).replace(hour=random.choice(hours), minute=0, second=0, microsecond=0)
            sc = self.app.scheduled_scene(char, d)
            if not (sc["away"] or sc["busy"] or sc["asleep"]):
                return d.timestamp()
        return None

    def _favor_plan(self):
        """頼まれごとの当日の相手の側: 頼んだ側なので, すっぽかしも遅刻もまずない (日がずれる・取りやめは前日ごろに決まる)."""
        return {"noshow": False, "late": 0, "cancel_checked": False}

    def water_plants(self, place, now=None):
        """植木の水やり: 相手の留守中の期間に, 相手の家へ行った (会わない. 鍵を預かっている). 終わればお礼はあとで."""
        app = self.app
        now = now or time.time()
        x = next((x for x in self.all() if x.get("plants") and x["place"] == place and x["status"] == "set"
                  and x["t"] - 3600 <= now <= x["until"]), None)
        if not x:
            return None
        f = app.earn.favor(x.get("favor"))
        x["status"] = "met"
        self.save()
        if not f:
            return "（%sの植木に水をやった）" % app.places.label(place)
        _, text = app.earn.favor_done(f, f["h"], now)
        app.life.save_player()
        return "（%s）" % text

    # ------------------------------------------------------------------ 何ができるか
    def needs(self, a, cid):
        """離れている相手と, このコマンドで会うのに約束がいるか (お出かけ・訪問・招く. 同居相手は いらない)."""
        if self.app.bonds.stage(cid) == "live":
            return False
        return bool((a.get("override") or {}).get("outing")) or a.get("bond") in ("visit_start", "guest_start")

    def dos_at(self, cid, pid):
        """その行き先で, その相手と約束できること (コマンド). 頼まれごとの約束 (FAVOR_DO) はここには出さない (相手から頼まれるもの)."""
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
        if x.get("favor"):                    # 頼まれごとの日時: 頼んだ側なので, 予定が空いていればまず受ける
            extra["what"] = x.get("label", "")
            busy = app.scheduled_scene(char, datetime.fromtimestamp(x["t"]))
            if busy["away"] or busy["busy"] or busy["asleep"]:
                alt = self._alt_time(char, x, now) if int(x.get("rounds", 0)) < COUNTER_MAX else None
                if alt:
                    x.update(t=alt, status="offered", made=now, rounds=int(x.get("rounds", 0)) + 1, ask=False)
                    self.save()
                    return "favor_counter", {}, dict(extra, when=fmt_when(alt, now))
                x["status"] = "declined"
                self.save()
                return "favor_busy", {}, extra
            x["status"] = "set"
            x["plan"] = self._favor_plan()
            self.save()
            return "favor_yes", {"mood": 2, "trust": 1}, extra
        busy = app.scheduled_scene(char, datetime.fromtimestamp(x["t"]))
        if (busy["away"] or busy["busy"] or busy["asleep"]) and not places_mod.is_home(x["place"]) and random.random() < 0.8:
            alt = self._alt_time(char, x, now) if int(x.get("rounds", 0)) < COUNTER_MAX else None
            fv = app.attach.factor(char, st, "devotion")
            if fv > 0 and random.random() < 0.4 * fv:          # 献身的なら, 自分の予定のほうを動かして合わせてくれることも
                x["status"] = "set"
                x["plan"] = self._plan(char, st)
                x["rearranged"] = True
                st.pop("date_promise", None)
                self.save()
                app.attach.give(char, st, "her", 2, "予定を動かして合わせてくれた")
                return "appoint_rearranged", {"heart": 2, "mood": 1}, extra
            if alt and random.random() < self.counter_chance(char, p, busy=True):
                return self._counter_back(char, st, x, alt, now, extra)        # その時間は無理だけど, この時間なら
            x["status"] = "declined"
            self.save()
            return "appoint_busy", {}, extra
        promised = st.get("date_promise", 0) > now or bool(x.get("counter"))        # 自分から誘った話の続き
        pa = 0.35 + (p.get("affection", 50) - 50) / 80.0 + (p.get("mood", 50) - 50) / 150.0 \
            - float(app.traits(char).get("caution", 0)) / 50.0 + (0.1 if app.bonds.stage(char["id"]) == "visit" else 0.0) \
            + (0.3 if promised else 0.0) - (0.3 if ctx.get("too_often") else 0.0) \
            + 0.2 * app.attach.factor(char, st, "devotion")
        if places_mod.is_home(x["place"]) and app.bonds.stage(char["id"]) != "visit":
            pa = 0
        if random.random() < max(0.03, min(0.95, pa)):
            x["status"] = "set"
            x["plan"] = self._plan(char, st)
            st.pop("date_promise", None)
            self.save()
            return "appoint_yes", {"heart": 2, "mood": 2}, extra
        if int(x.get("rounds", 0)) < COUNTER_MAX and not places_mod.is_home(x["place"]) \
                and random.random() < self.counter_chance(char, p, busy=False):
            alt = self._alt_time(char, x, now)
            if alt:
                return self._counter_back(char, st, x, alt, now, extra)      # その日は気が乗らないけど, こっちなら
        x["status"] = "declined"
        self.save()
        return "appoint_no", {}, extra

    def counter_chance(self, char, p, busy):
        """断るときに, 別の日時 (・行き先) を返してくれるか. 予定が合わないだけなら返しやすく, 気が乗らないだけなら返しにくい.
        仲・機嫌・性格 (話しかけてくる多さ・慎重さ) しだい. 必ずではない."""
        tr = self.app.traits(char)
        f = (0.3 if busy else 0.12) + (p.get("affection", 50) - 50) / (100.0 if busy else 150.0) \
            + 0.1 * self.app.attach.factor(char, self.app.state(char["id"]), "devotion") \
            + (p.get("mood", 50) - 50) / (200.0 if busy else 250.0) + 0.15 * (float(tr.get("approach", 1)) - 1) \
            - float(tr.get("caution", 0)) / 60.0
        return max(0.02, min(0.7, f))

    def _counter_back(self, char, st, x, t, now, extra):
        """相手が別の日時を返してくる (ときどき行き先も. あなたが受ける / 断る / また返す)."""
        app = self.app
        d = datetime.fromtimestamp(t)
        if random.random() < 0.3:              # 行き先も変える (その人の好みで, 気持ち傾くだけ)
            opts = [(pid, a) for pid in places_mod.OUT_PLACES for a in self.dos_at(x["cid"], pid)
                    if phase_ok(app, a, d) and places_mod.open_state(pid, d)["open"]]
            if opts:
                pid, a = self.pick(char, st, opts)
                x.update(place=pid, do=a["id"])
        x.update(t=t, status="offered", made=now, rounds=int(x.get("rounds", 0)) + 1)
        self.save()
        extra = dict(extra, when=fmt_when(t, now), place=app.places.label(x["place"]))
        return "appoint_counter", {}, extra

    def _plan(self, char, st):
        """相手の側の, 当日のこと (約束したときに決まる. 画面には出さない). 体調不良のキャンセルは当日の健康で決める."""
        p = st["params"]
        low = max(0.0, -self.app.attach.factor(char, st, "devotion"))      # 自分優先なほど, すっぽかし・遅刻しやすい
        punctual = float(self.app.traits(char).get("punctual", 0.75)) - 0.15 * low
        noshow = random.random() < 0.02 + (1 - punctual) * 0.08 + max(0.0, 45 - p.get("affection", 50)) / 300.0 + 0.06 * low
        late = 0
        if not noshow and random.random() > punctual:
            late = int(random.uniform(5, 40) * (1.5 - punctual))
        move = not noshow and random.random() < 0.3 * low           # 自分の都合で, 日を動かしたいと言ってくる
        return {"noshow": noshow, "late": late, "cancel_checked": False, "move": move}

    # ------------------------------------------------------------------ 相手から誘われる
    def answer(self, aid, yes, now=None):
        app = self.app
        now = now or time.time()
        x = self.get(aid)
        if x["status"] != "offered":
            raise ValueError("いまは誘われていません")
        char = app.char(x["cid"])
        if yes and x.get("ask"):
            raise ValueError("いつなら行けるか、日時を返してください（「別の日時なら」から）")
        with app.lock:
            st = app.state(x["cid"])
            if x.get("favor"):               # 頼まれごと: 引き受ける / 断る (引き受ければ必ず喜ばれる, ではない. 効果は realize を通る)
                if yes:
                    x["status"] = "set"
                    x["plan"] = self._favor_plan()
                    eff, _ = app.bonds.realize(char, st, {"mood": 2, "trust": 1}, "_favor_yes", now)
                    app.chat.add(x["cid"], "me", "（%sを引き受けた: %s）" % (x.get("label", ""), self.when_of(x, now)), kind="appoint", t=now)
                else:
                    x["status"] = "refused"
                    eff = {"mood": -1}
                    app.chat.add(x["cid"], "me", "（%sは断った）" % x.get("label", ""), kind="appoint", t=now)
                    f = app.earn.favor(x["favor"])
                    if f:
                        app.earn.favors().remove(f)
                app.apply_effects(st, app.trait_effects(char, eff))
                app.chat.mark_read_by_her(x["cid"], now)
                app.save_state(x["cid"])
                self.save()
                return {"ok": True, "status": x["status"]}
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
        if x.get("fixed"):
            raise ValueError("その日しか無理だそうです（受けるか断るかで答えましょう）")
        if int(x.get("rounds", 0)) >= COUNTER_MAX:
            raise ValueError("もう何度もやりとりしているので、受けるか断るかにしましょう")
        if x.get("favor"):
            t = float(t)
            if t < now + 30 * 60 or t > now + 14 * 86400:
                raise ValueError("約束は 30 分後から 2 週間先までです")
            x.update(t=t, status="asked", made=now, rounds=int(x.get("rounds", 0)) + 1, counter=True, ask=False)
            self.save()
            self._send(x, now, "（%sは、%sなら行ける、と返した）" % (x.get("label", ""), fmt_when(t, now)))
            return dict(x, label=STATUS_LABEL[x["status"]])
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
            app._phoned(st, now, char, "appoint")
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
        a = app.action(x["do"]) if x["do"] != FAVOR_DO else {}
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
            fav = bool(x.get("favor"))            # 頼まれごと: 当てにしていたので, 普段の約束より重い
            with app.lock:
                d = app.apply_effects(st, app.trait_effects(char, {"mood": -12, "trust": -8, "affection": -3} if fav
                                                            else {"mood": -8, "trust": -4, "affection": -2}))
                app.life.add_reason(st, "player", "bad", ("当てにしていたのに、%sが%sに来なかった" % (app.pronouns(char)[2], x.get("label", ""))
                                                          if fav else "%sが約束をすっぽかした" % app.pronouns(char)[2]), now,
                                    told=True, delta=d.get("mood", 0), action="_appoint")
                app.chat.add(x["cid"], "her", app.chat.line(char, "favor_missed" if fav else "appoint_missed", {"what": x.get("label", "")}),
                             kind="favor_missed" if fav else "appoint_missed", t=x["t"] + GRACE)
                app.save_state(x["cid"])
                self._favor_drop(x)
            out.append("%sとの約束（%s）に行かなかった" % (char.get("name", ""), fmt_when(x["t"], now)))
            return True
        return False

    def _meet(self, x, now, me_late=False, extra_opts=None):
        app = self.app
        cid = x["cid"]
        char = app.char(cid)
        if app.presence.rec().get("mode") == "out":
            ll = app.presence.back(now)
            if ll:
                app.solo.finish(ll)
        late = (x.get("plan") or {}).get("late", 0) if x.get("status") == "waiting" else 0
        x["status"] = "met"
        app.attach.give(char, app.state(cid), "me", 1, "約束を守って会えた")
        self.save()
        if x.get("favor"):
            return self._favor_meet(x, now, me_late, extra_opts or {})
        opts = dict({"appointment": x["id"]}, **(extra_opts or {}))
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

    def _favor_drop(self, x):
        f = self.app.earn.favor(x.get("favor"))
        if f:
            self.app.earn.favors().remove(f)
            self.app.life.save_player()

    def _favor_meet(self, x, now, me_late, opts):
        """頼まれごとの約束で会えた: 手伝いに取りかかる (戻ると earn.favor_done). 閉じていた間 (auto_weak) なら, その場でひと通り済ませる."""
        app = self.app
        cid = x["cid"]
        char = app.chars[cid]
        f = app.earn.favor(x.get("favor"))
        if not f:
            return {"status": "met", "entry": None, "text": "%sの家に行ったが、頼まれごとはもう済んでいた" % char.get("name", "")}
        if me_late:
            with app.lock:
                st = app.state(cid)
                d = app.apply_effects(st, app.trait_effects(char, {"mood": -3}))
                app.life.add_reason(st, "player", "bad", "%sが%sに遅れてきた" % (app.pronouns(char)[2], f["label"]), now, told=False,
                                    delta=d.get("mood", 0), action="_appoint")
                app.save_state(cid)
        if opts.get("auto_weak"):
            _, text = app.earn.favor_done(f, f["h"], now + f["h"] * 3600)
            app.life.save_player()
            return {"status": "met", "entry": {"text": text}}
        r = app._go_task("favor", f, "%sの家で%sに取りかかった（%s時間ほど）%s" % (char.get("name", ""), f["label"], f["h"],
                                                                         "。約束に遅れてしまった" if me_late else ""))
        return dict(r, status="met", entry={"text": r.get("label", "")})

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
            if x.get("plants") and x["status"] == "set":
                if now > x["until"]:                  # 留守のあいだに水やりに行かなかった: 枯れてがっかり
                    x["status"] = "missed"
                    with app.lock:
                        d = app.apply_effects(st, app.trait_effects(char, {"mood": -4, "trust": -3, "affection": -1}))
                        app.life.add_reason(st, "player", "bad", "頼んでいた植木が枯れていた", now, told=True, delta=d.get("mood", 0),
                                            action="_appoint")
                        app.chat.add(cid, "her", app.chat.line(char, "favor_plants_dead", {}), kind="favor_plants_dead", t=now)
                        app.save_state(cid)
                    self._favor_drop(x)
                    out.append("%sの植木の水やりに行かないまま、留守が終わった" % char.get("name", ""))
                    changed = True
                continue
            if x["status"] in ("asked", "offered") and (now - x["made"] > 24 * 3600 or now > x["t"]):
                if x["status"] == "offered" and x.get("favor"):     # 頼まれごとの返事を放っておいた: ほかの人に頼んで済んでしまう
                    app.apply_effects(st, app.trait_effects(char, {"trust": -1}))
                    app.chat.add(cid, "her", app.chat.line(char, "favor_lapsed", {"what": x.get("label", "")}), kind="favor_lapsed", t=now)
                    app.save_state(cid)
                    self._favor_drop(x)
                elif x["status"] == "offered":          # 誘ったのに返事がなかった
                    app.apply_effects(st, app.trait_effects(char, {"mood": -3, "loneliness": 4}))
                    app.save_state(cid)
                elif x.get("favor"):
                    self._favor_drop(x)
                x["status"] = "lapsed"
                changed = True
            elif x["status"] == "set":
                plan = x.setdefault("plan", {})
                if x.get("favor") and not plan.get("cancel_checked") and now >= x["t"] - 3 * 3600:
                    plan["cancel_checked"] = True
                    changed = True
                    if random.random() < FAVOR_RESCHED and not x.get("fixed"):       # 相手の都合で, 日がずれる / 取りやめになる
                        alt = self._alt_time(char, x, now) if random.random() < 0.6 else None
                        if alt:
                            x.update(t=alt, status="offered", made=now, ask=False)
                            app.chat.add(cid, "her", app.chat.line(char, "favor_resched", {"what": x.get("label", ""), "when": fmt_when(alt, now)}),
                                         kind="favor_resched", t=now, appoint=x["id"])
                            out.append("%sから、%sの日をずらしたいと連絡が来た" % (char.get("name", ""), x.get("label", "")))
                        else:
                            x["status"] = "cancelled"
                            app.chat.add(cid, "her", app.chat.line(char, "favor_cancel", {"what": x.get("label", "")}), kind="favor_cancel", t=now)
                            self._favor_drop(x)
                            out.append("%sから、%sは取りやめになったと連絡が来た" % (char.get("name", ""), x.get("label", "")))
                        app.picked_up_phone(char, st, now)
                        app.save_state(cid)
                        continue
                if plan.get("move") and not x.get("favor") and now >= x["t"] - 20 * 3600:
                    plan["move"] = False                   # 自分優先: 前の日ごろに, 自分の都合で日を動かしたいと言ってくる
                    changed = True
                    alt = self._alt_time(char, x, now)
                    if alt and int(x.get("rounds", 0)) < COUNTER_MAX:
                        x.update(t=alt, status="offered", made=now, by="her", rounds=int(x.get("rounds", 0)) + 1)
                        app.chat.add(cid, "her", app.chat.line(char, "appoint_move_mine", {"when": fmt_when(alt, now)}),
                                     kind="appoint_move_mine", t=now, appoint=x["id"])
                        app.picked_up_phone(char, st, now)
                        app.save_state(cid)
                        app.trace.add("appoint", "自分の都合で日を動かしたいと言ってきた", cid, now, appoint=x["id"], new_t=alt)
                        out.append("%sから、約束の日を変えたいと連絡が来た" % char.get("name", ""))
                        continue
                if not plan.get("cancel_checked") and now >= x["t"] - 3 * 3600:
                    plan["cancel_checked"] = True
                    changed = True
                    sick = st["params"].get("health", 90) < 45
                    if random.random() < (0.6 if sick else 0.03 * (1 - app.attach.factor(char, st, "devotion"))):     # 自分優先なら, 仮病も
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
            out.append(self.row(x, now))
        return out

    def row(self, x, now=None):
        """画面に出す一件 (トークの約束の欄・ホーム・カレンダーで共通). 以前のセーブの欠けた項目は既定で."""
        app = self.app
        now = now or time.time()
        st = x.get("status", "lapsed")
        due = st in ("set", "waiting") and x["t"] - EARLY <= now <= x["t"] + GRACE
        return {"here": st in ("set", "waiting") and self.here(x["place"], now),
                "home_me": x["place"] == places_mod.HOME_ME, "remain": int(x["t"] - now), "id": x["id"], "cid": x["cid"],
                "name": app.chars[x["cid"]].get("name", "") if x["cid"] in app.chars else "", "t": x["t"],
                "when": fmt_when(x["t"], now), "place": x["place"], "place_label": app.places.label(x["place"]),
                "do": x.get("do"), "do_label": x.get("label") if x.get("favor") else app.action(x.get("do")).get("name", x.get("do")),
                "by": x.get("by", "me"), "status": st,
                "status_label": self.favor_status(x, now) if x.get("favor") else STATUS_LABEL.get(st, st), "due": due,
                "favor": bool(x.get("favor")), "fixed": bool(x.get("fixed")), "ask": bool(x.get("ask")),
                "plants": bool(x.get("plants")), "until": x.get("until"),
                "when_label": self.when_of(x, now)}
