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
  移動には時間がかかる (core/geo.py. 約束の時刻は着く時刻. row の leave に何時に出れば間に合うか). 外出は画面を開いている間だけなので, 閉じれば家に帰る (= いない).
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
- 決まった約束 (set) は, こちらから 変えたい (change) / 取りやめる (cancel) と伝えられる. 返事は時間差. 応じるか・受け取り方は,
  相手のその時間の予定・伝えた時期 (直前ほど重い)・何回目か・誰が誘ったか・性格 (時間にきっちりか)・仲と機嫌と献身・
  お互いさま (相手が最近ずらした・来なかった)・変え方の中身 (好きな所へ・早く会える) しだい (change_score). すんなり応じて
  何も変わらないことも. 取りやめは断れないが, 受け取り方は同じように変わる (すっぽかすより前もって伝えたほうが軽い).
"""
import random
import time
import uuid
from datetime import datetime, timedelta

from . import cond
from . import places as places_mod
from . import prefs as prefs_mod
from . import season as season_mod

EARLY = 15 * 60          # 約束の時刻のこれだけ前から「もうすぐ」として知らせる
GRACE = 45 * 60          # 約束の時刻からこれだけ過ぎても約束の場所にいなければ, すっぽかしたことに
LATE_ME = 10 * 60        # これより遅れて着くと, 相手は少し機嫌を損ねる
GIVE_UP = 30 * 60        # 相手が来ないとき, これだけ待ったらあきらめる
NEAR = 3 * 3600          # 約束のこれだけ前からは, 相手の家へ出かけると「約束の訪問」(玄関先で待つ)
COUNTER_MAX = 3          # 誘いへの「別の日時なら」のやりとりの回数の上限 (あなたと相手の案を合わせて)
# 好きなもの (items の好みの印) → 行きたくなる行き先 (気持ち傾くだけ)
LIKE_PLACES = {"books": ("bookstore",), "sweets": ("cafe", "mall"), "tea": ("cafe",), "flowers": ("park", "hill"),
               "games": ("electronics", "amusement"), "food": ("teishoku", "ramen", "restaurant", "shopping_street"),
               "cute": ("aquarium", "mall"), "fashion": ("mall", "boutique", "used_clothes"), "accessories": ("mall", "boutique"), "practical": ("supermarket", "mall")}
LIKE_PLACES = {k: tuple(places_mod.with_branches(v)) for k, v in LIKE_PLACES.items()}     # 2 店目以降も (A10)
OPEN = ("asked", "offered", "set", "waiting")
STATUS_LABEL = {"asked": "返事待ち", "offered": "誘われている", "set": "約束した", "waiting": "待っている", "met": "会えた",
                "stood_up": "来なかった", "missed": "行かなかった", "declined": "断られた", "cancelled": "キャンセル",
                "refused": "断った", "lapsed": "流れた"}
HOME_DO = {"visit": "visit_home", "guest": "invite_home"}
FAVOR_DO = "_favor"
FAVOR_RESCHED = 0.04     # 約束の 3 時間前ごろに, 相手の都合で日がずれる・取りやめになる確率 (頼まれごと)
MOVE_SPAN = 21 * 86400   # あなたが約束を動かした・取りやめた回数を数える期間 (続くと受け取り方が悪くなる)
APPT_KINDS = ("appoint", "appoint_change", "appoint_cancel_me")      # 約束の返事待ち (msg_pending の kind)
ALT_HOURS = (10, 11, 13, 14, 15, 16, 17, 18, 19)           # 相手が返す別の案の時刻
ALT_HOURS_WIDE = (9, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 21)
RELIFE_SPAN = 120        # 予定を作り直したあとの点検: 約束の時刻からこれだけ (分) のあいだ, ふさがっていれば都合がつかない
RELIFE_SOON = 3 * 3600   # 約束までこれを切っていれば, 打診はすぐ送る
RELIFE_NEAR = 3600       # 約束までこれを切っていれば, 打診しない (そのまま来る)
# スマホで「今から家に行っていい？」(残件 A25): 返事が来たら, あなたは相手の家へ向かう (着いたら訪問). 約束の形 (ask_now) に乗せる
NOW_PREP = 10            # 着く見込みに足す, 出るまでの分
NOW_STALE = 90 * 60      # 聞いてからこれより遅れて読んだら, もう「今から」ではない (断る)
NOW_ASK_SPAN = 6 * 3600  # この間に断られた回数を数える (続けて聞くと, しつこい)
NOW_LATE_ME = 20 * 60    # 着く見込みからこれより遅れると, 少し機嫌を損ねる (見込みなので, ふつうの約束より緩く)
NOW_MISSED = {"mood": -5, "trust": -2, "affection": -1}     # いいと言われたのに来なかった (約束のすっぽかし −8/−4/−2 より軽い)
# 遅れると伝える (メッセージ・電話の「遅れる」): 伝えた分だけ相手は待つ. 伝えた見込みのうちに着けば, 黙って遅れるより軽い
LATE_MINS = (10, 20, 30, 45, 60)
LATE_WAIT = 20 * 60      # 伝えた見込みから, さらにこれだけは待つ (それでも来なければすっぽかし. 黙っているときの GRACE より短くはしない)
LATE_KEPT = 10 * 60      # 伝えた見込みからこれ以内に着けば, 「伝えたとおり」
LATE_SPAN = 30 * 86400   # 遅れると伝えた回数を数える期間 (続くと受け取りが悪くなる)
# 約束の相手のブレ (A41・S34). 確率は低く, 同じ人が続けて起こしにくく (直近 HER_SPAN の回数で半分ずつ)
HER_SPAN = 30 * 86400    # 相手が遅れた・取りやめた・変えた・切り上げた回数を数える期間
CHG_P = 0.05             # 誰でもまれに, 約束を変えたい (時刻・場所・すること) と言ってくる
DROP_BASE = 0.012        # 直前の取りやめ (体調以外) のもと
DROP_WHYS = ("work", "urgent", "family", "mood", "weather")
HER_LATE_KEY = {"traffic": "appoint_her_late_traffic", "oversleep": "appoint_her_late_oversleep"}     # 無ければ appoint_her_late (支度)
TELL_PHONE = 0.2         # 遅れる・取りやめの連絡を電話でする割合のもと (× 自分から来る度合い. 仲が近いと 1.3 倍)


def fmt_when(t, now=None):
    d = datetime.fromtimestamp(t)
    n = datetime.fromtimestamp(now or time.time())
    days = (d.date() - n.date()).days
    day = {0: "今日", 1: "明日", 2: "あさって"}.get(days) or "%d/%d（%s）" % (d.month, d.day, "月火水木金土日"[d.weekday()])
    return "%s %d:%02d" % (day, d.hour, d.minute)


HOME_INVITE = 0.2            # 家に行ける仲で, 誘いが家になる割合の基本 (慣れで HOME_INVITE_FAM × 慣れ 増える)
HOME_INVITE_FAM = 0.3
PLACE_PREF = 0.03           # あなたがよく誘う所 (覚えた好み 1 あたり. A44 段 1)
TIGHT_INVITE = 0.6          # 所持金が苦しいときの, 誘いの起きやすさの倍率 (core/purse.py)
TIGHT_PAID = 0.3            # 同じく, お金のかかる行き先・することの選ばれやすさの倍率
NOW_RATE = 0.012             # 急な誘いの起きやすさ (1 時間あたり. 退屈・寂しさ・機嫌 × 性格 approach)
NOW_LEAD = (40, 45, 50, 60)  # 急な誘いの待ち合わせまで (分)
NOW_HOME = 0.35              # 急な誘いが家になる割合の基本


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
            start = self._free_time(char, now, days=(1, 3), hours=(9,)) or self._day_time(now, 1, 9)
            x.update(t=start, until=start + random.randint(2, 4) * 86400, plants=True, fixed=True, rounds=COUNTER_MAX)
            line = "favor_ask_plants"
            extra.update({"from": fmt_when(x["t"], now).split(" ")[0], "to": fmt_when(x["until"], now).split(" ")[0]})
        elif kind == "move":
            t = self._free_time(char, now, days=(2, 6), hours=(9, 10, 13)) or self._day_time(now, 3, 10)
            x.update(t=t, fixed=True, rounds=COUNTER_MAX)
            line = "favor_ask_move"
        elif legacy or random.random() < 0.4:       # いつなら空いているか, こちらに聞いてくる
            x.update(t=self._day_time(now, 2, 10), ask=True)
            line = "favor_ask_when"
        else:
            x["t"] = self._free_time(char, now, days=(1, 5), hours=(10, 13, 15)) or self._day_time(now, 2, 13)
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
        elif self._by_phone(char, st, x, "favor", "favor_ask", text, now):      # 電話で頼まれる (A23 段 2. core/ring.py)
            app.save_state(cid)
            return x
        app.chat.add(cid, "her", text, kind="favor_ask", t=now, appoint=x["id"])
        app.picked_up_phone(char, st, now)
        app.save_state(cid)
        return x

    def _free_time(self, char, now, days=(1, 5), hours=(10, 13, 15)):
        """相手の予定が空いている日時 (頼まれごとの案). 候補の日 × 時刻をすべて (順は散らして) 見る.
        (以前はくじを 12 回引くだけで, 平日の朝に働いている人だと見つからず, 頼まれた時刻ちょうどの数日後 (夜中にも) になっていた)"""
        dt0 = datetime.fromtimestamp(now)
        cands = [(dd, hh) for dd in range(days[0], days[1] + 1) for hh in hours]
        random.shuffle(cands)
        for dd, hh in cands:
            d = (dt0 + timedelta(days=dd)).replace(hour=hh, minute=0, second=0, microsecond=0)
            sc = self.app.scheduled_scene(char, d)
            if not (sc["away"] or sc["busy"] or sc["asleep"]):
                return d.timestamp()
        return None

    @staticmethod
    def _day_time(now, days, hour):
        """days 日後の hour 時ちょうど (空いている時刻が見つからなかったときの案. 夜中にしない)."""
        return (datetime.fromtimestamp(now) + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0).timestamp()

    NIGHT_END = 6            # 頼まれごとの約束がこれより前の時刻なら, 夜中 (以前の作りで付いてしまったもの)

    def fix_night_favors(self, now=None):
        """以前の作りで夜中 (0〜6 時) になった頼まれごとの約束 (まだ済んでいないもの) を, 同じ日の 10 時に読み替える (起動したとき.
        読み替えたものは 10 時になるので, 二度は当たらない). 10 時がもう過ぎていれば触らない. 読み替えた数を返す."""
        app = self.app
        now = now or time.time()
        n = 0
        for x in self.all():
            if not x.get("favor") or x.get("by") != "her" or x["status"] not in OPEN or x.get("plants"):
                continue
            d = datetime.fromtimestamp(x["t"])
            if d.hour >= self.NIGHT_END:
                continue
            # 以前の作りの代わりの時刻 (頼まれた時刻のちょうど 2 日後・3 日後) だけ. あなたが返した日時 (夜中を選んだもの) は動かさない
            days = (x["t"] - float(x.get("made") or 0)) / 86400.0
            if not (abs(days - round(days)) < 1e-6 and round(days) in (2, 3)):
                continue
            t = d.replace(hour=10, minute=0, second=0, microsecond=0).timestamp()
            if t < now + 30 * 60:
                continue
            x["t"] = t
            f = app.earn.favor(x["favor"])
            if f:
                f["until"] = max(f.get("until", 0), t + 86400)
            if x["cid"] in app.chars:
                app.chat.add(x["cid"], "sys", "（%sの時刻は、%sからのことだった）" % (x.get("label") or "頼まれごと", self.when_of(x, now)),
                             kind="favor", t=now)
            n += 1
        if n:
            self.save()
        return n

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
            if pid == places_mod.HOME_ME:
                dos = list(dos) + app.askhelp.dos(cid)            # 手伝いを頼む (core/askhelp.py)
            if dos:
                out.append({"place": pid, "label": p["label"], "icon": p["icon"], "group": p["group"],
                            "hours": places_mod.hours_label(pid),
                            "dos": [{"id": a["id"], "name": a.get("name", a["id"]), "icon": a.get("icon", "")} for a in dos]})
        return out

    # ------------------------------------------------------------------ こちらから誘う
    def propose(self, cid, t, place, do, now=None):
        app = self.app
        now = now or time.time()
        if str(do).startswith("_help:"):                         # 手伝いを頼む (core/askhelp.py)
            x = app.askhelp.propose(cid, t, do.split(":", 1)[1], now)
            return dict(x, label=STATUS_LABEL[x["status"]])
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
        if place == "restaurant":                 # 予約: 曜日・時間・何日前かで, いっぱいのことがある
            from .anniv import reserve_full
            full = reserve_full(t, now)
            app.trace.add("appoint", "レストランの予約", cid, now, at=t, full=full)
            if full:
                raise ValueError("%sは、その日時の予約が取れなかった（いっぱいだった）" % app.places.label(place))
        x = {"id": uuid.uuid4().hex[:8], "cid": cid, "t": t, "place": place, "do": do, "by": "me", "status": "asked", "made": now}
        self.all().append(x)
        self.save()
        if place in places_mod.PLACES:       # あなたから誘った行き先 = あなたの好み (A44 段 1. 家は数えない)
            prefs_mod.learn(app.state(cid), "place:" + place, 1.0, now)
            app.save_state(cid)
        self._send(x, now, "（%s、%sで「%s」に誘った）" % (fmt_when(t, now), app.places.label(place), a.get("name", do)))
        return dict(x, label=STATUS_LABEL[x["status"]])

    # ------------------------------------------------------------------ 今から家に行っていい？ (A25)
    def now_eta(self, cid, now):
        """いまいる場所から相手の家に着く見込みの時刻 (出るまでの分を足す. 揺らぎなし)."""
        app = self.app
        try:
            m = app.geo.leg(app.geo.where(now), "home:" + cid, None, now, rand=False)["min"]
        except ValueError:
            m = 30
        return now + (m + NOW_PREP) * 60

    def now_why(self, cid, now=None):
        """スマホで「今から家に行っていい？」と聞けないなら, その理由 (聞けるなら None)."""
        app = self.app
        now = now or time.time()
        stage = app.bonds.stage(cid)
        if stage == "live":
            return "一緒に暮らしています"
        if stage != "visit":
            return "家に行ける仲になってから"
        if app.bonds.together(cid):
            return "いまそばにいます"
        for x in self.open_with(cid):
            if x.get("ask_now") and x["status"] in ("asked", "set", "waiting"):
                return "返事を待っています" if x["status"] == "asked" else "もう行くことになっています"
            if abs(x["t"] - now) < 3 * 3600:
                return "近くに約束（か返事待ち）があります"
        return None

    def ask_now(self, cid, now=None):
        """スマホで「今から家に行っていい？」と聞く. 返事はいつものメッセージの時間差 (すぐのことも). 受けてもらえたら,
        相手の家へ向かえば (トークの「出かける」) 着いたときに訪問になる. 聞いた時点では約束の形 (asked) で, t は着く見込み."""
        app = self.app
        now = now or time.time()
        char = app.char(cid)
        cid = char["id"]
        why = self.now_why(cid, now)
        if why:
            raise ValueError(why)
        x = {"id": uuid.uuid4().hex[:8], "cid": cid, "t": self.now_eta(cid, now), "place": "home:" + cid, "do": HOME_DO["visit"],
             "by": "me", "status": "asked", "made": now, "now": True, "ask_now": True}
        self.all().append(x)
        self.save()
        self._send(x, now, "（今から%sの家に行ってもいいか聞いた）" % char.get("name", ""))
        app.trace.add("appoint", "今から家に行っていいか聞いた", cid, now, appoint=x["id"])
        return dict(x, label=STATUS_LABEL[x["status"]])

    def _now_reply(self, char, st, x, now, extra):
        """「今から家に行っていい？」への返事. 読んだときの相手の都合 (留守・寝ていた・手が離せない・体調)・時間帯・機嫌・仲・
        心の開きやすさ・家に上がる慣れ・続けて断った回数で決める. 回数を重ねれば通る作りにはしない (続けて聞くほど通りにくい).
        断る理由は, 相手の知りうるもの (出先・忙しい・もう遅い・体調・部屋が散らかっている など. セリフで)."""
        app = self.app
        cid = char["id"]
        p = st["params"]
        dt = datetime.fromtimestamp(now)
        scene = app.scene_at(char, st, dt)
        ph = app.phase_at(dt).get("id")
        asks = [t for t in st.get("now_refused") or [] if now - t < NOW_ASK_SPAN]
        key, eff = None, {}
        if now - x["made"] > NOW_STALE:
            key = "visit_now_stale"                      # 読むのが遅れた: もう「今から」ではない
        elif scene["away"] or scene.get("outing"):
            key = "visit_now_out"
        elif scene["asleep"] or ph in ("midnight", "dawn"):
            key = "visit_now_late"
        elif p.get("health", 90) < 50 or app.care.ill(st, now):
            key = "visit_now_unwell"
        elif scene["busy"] and random.random() < 0.7:
            key = "visit_now_busy"
        else:
            pa = 0.45 + (p.get("affection", 50) - 50) / 100.0 + (p.get("trust", 50) - 50) / 150.0 \
                + (p.get("mood", 50) - 50) / 120.0 + float(app.traits(char).get("caution", 0)) / 40.0 \
                + app.athome.drop_bonus(cid, st, now) - (0.25 if ph == "night" else 0.0) - (0.2 if scene["busy"] else 0.0) \
                - 0.15 * len(asks)
            app.trace.add("appoint", "今から家に: 受ける見込み", cid, now, p=round(pa, 2), refused=len(asks))
            if random.random() < max(0.05, min(0.9, pa)):
                key = "visit_now_yes"
            else:
                key = "visit_now_no"
                if asks:
                    eff = {"mood": -1}                   # 続けて聞かれた (しつこい)
        if key == "visit_now_yes":
            x["status"] = "set"
            x["t"] = self.now_eta(cid, now)              # 読んだ時点の, あなたのいる所から
            x["plan"] = {"noshow": False, "late": 0, "cancel_checked": True, "move": False, "go": 0}
            self._favor_set(st, x, now)
            eff = {"heart": 1, "mood": 1}
        else:
            x["status"] = "declined"
            if key != "visit_now_stale":
                st["now_refused"] = asks + [now]
        self.save()
        return key, eff, dict(extra, when=datetime.fromtimestamp(x["t"]).strftime("%H:%M"))

    def wait_scene(self, char, base, t):
        """「今から家においで」と言ったあと, 着くまでは家にいる (予定では出かける時刻でも)."""
        cid = char.get("id")
        for x in self.all():
            if x["cid"] == cid and x.get("ask_now") and x["status"] in ("set", "waiting") and x.get("made", 0) <= t <= self.grace(x):
                if base.get("away") or base.get("outing"):
                    return dict(base, activity="relax", label="家にいる", location="自宅", away=False, outing=False,
                                pos="indoors, at home", neg="")
                return base
        return base

    def reply(self, char, st, pend, now, ctx):
        """誘いへの返事 (時間差で届いたとき). (セリフの場面, 効果, 置き換え) を返す."""
        app = self.app
        try:
            x = self.get(pend.get("appoint"))
        except KeyError:
            return "appoint_no", {}, {"when": "", "place": ""}
        extra = {"when": fmt_when(x["t"], now), "place": app.places.label(x["place"])}
        if x.get("ask_now") and x["status"] != "asked":         # 今から家に (A25): もう流れていた
            return "visit_now_stale", {}, extra
        if x["status"] != "asked":
            return "appoint_no", {}, extra
        p = st["params"]
        if x.get("help"):                     # あなたが頼んだ手伝い (core/askhelp.py)
            return app.askhelp.reply(char, st, x, now, extra)
        if x.get("ask_now"):                  # 今から家に行っていい？ (A25)
            return self._now_reply(char, st, x, now, extra)
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
        plan = app.circle.plan_over(char, st, x["t"], x["t"] + 2 * 3600)      # 知り合いと会う予定 (core/circle.py)
        if plan:
            extra["who"] = app.circle.who_word(char, st, plan)
        if ((busy["away"] or busy["busy"] or busy["asleep"]) and not places_mod.is_home(x["place"]) and random.random() < 0.8 or plan):
            # 知り合いと先に約束していれば, たまたま受けることはない (献身的なら, その予定をずらして合わせてくれることがある)
            alt = self._alt_time(char, x, now) if int(x.get("rounds", 0)) < COUNTER_MAX else None
            fv = app.attach.factor(char, st, "devotion")
            if fv > 0 and random.random() < 0.4 * fv:          # 献身的なら, 自分の予定のほうを動かして合わせてくれることも
                x["status"] = "set"
                x["plan"] = self._plan(char, st, x)
                x["rearranged"] = True
                if plan:
                    app.circle.drop(char, st, plan, "あなたとの約束に合わせた")
                st.pop("date_promise", None)
                self.save()
                app.attach.give(char, st, "her", 2, "予定を動かして合わせてくれた")
                self._favor_set(st, x, now)                 # 約束を受けてくれた (お礼の心当たり)
                return "appoint_rearranged", {"heart": 2, "mood": 1}, extra
            if alt and random.random() < self.counter_chance(char, p, busy=True):
                return self._counter_back(char, st, x, alt, now, extra)        # その時間は無理だけど, この時間なら
            x["status"] = "declined"
            self.save()
            if plan:                                   # 名前を言って断った: あなたがその人を知る (core/circle.py)
                app.circle.learn(char, st, plan["pid"], "decline", now)
            return ("appoint_plan" if plan else "appoint_busy"), {}, extra
        promised = st.get("date_promise", 0) > now or bool(x.get("counter"))        # 自分から誘った話の続き
        pa = 0.35 + (p.get("affection", 50) - 50) / 80.0 + (p.get("mood", 50) - 50) / 150.0 \
            - float(app.traits(char).get("caution", 0)) / 50.0 + (0.1 if app.bonds.stage(char["id"]) == "visit" else 0.0) \
            + (0.3 if promised else 0.0) - (0.3 if ctx.get("too_often") else 0.0) \
            + 0.2 * app.attach.factor(char, st, "devotion") + app.waves.accept_shift(char, st)       # 生活の波 (忙しい・人付き合い … core/waves.py)
        if places_mod.is_home(x["place"]) and app.bonds.stage(char["id"]) != "visit":
            pa = 0
        xdt = datetime.fromtimestamp(x["t"])
        of = self.out_factor(char, x["place"], xdt)          # 屋外の行き先: その日の暑さ・寒さ・天気 (S38)
        pa *= of
        if random.random() < max(0.03, min(0.95, pa)):
            x["status"] = "set"
            x["plan"] = self._plan(char, st, x)
            if plan:                                   # 予定より, あなたとの約束を選んだ (友達との予定はやめる)
                app.circle.drop(char, st, plan, "あなたとの約束を選んだ")
            st.pop("date_promise", None)
            self.save()
            self._favor_set(st, x, now)
            return "appoint_yes", {"heart": 2, "mood": 2}, extra
        if int(x.get("rounds", 0)) < COUNTER_MAX and not places_mod.is_home(x["place"]) \
                and random.random() < self.counter_chance(char, p, busy=False):
            alt = self._alt_time(char, x, now)
            if alt:
                return self._counter_back(char, st, x, alt, now, extra)      # その日は気が乗らないけど, こっちなら
        x["status"] = "declined"
        self.save()
        why = season_mod.out_why(app, char, xdt) if of < 0.85 and x["place"] != places_mod.HOME_ME else None     # 家の室温では「外は」と言わない
        if why:
            return "appoint_no_" + why, {}, extra        # 暑い / 寒いから, その日の外はやめておく (S38)
        return app.waves.decline_key(char, st, x["t"]) or "appoint_no", {}, extra       # 忙しい・友達と約束 (時期と, その日の予定. core/waves.py)

    def _favor_set(self, st, x, now):
        """約束が決まった: お礼の心当たり. 約束してくれた / もとが相手からの誘いなら, 会おうと言ってくれた
        (あなたが別の日時を返して決まっても. 以前はそこを見ておらず, 「会おうと言ってくれた」へのお礼に「何のお礼？」と返っていた)."""
        self.app.manners.favor(st, "appoint", now)
        if x.get("by") == "her":
            self.app.manners.favor(st, "invite", now)
        if x.pop("moving", None):                      # こちらが変えたいと言って, 相手が出し返した時間で決まった: 変えてくれた
            self.app.manners.favor(st, "change", now)

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
                pid, a = self.pick(char, st, opts, d)
                x.update(place=pid, do=a["id"])
        x.update(t=t, status="offered", made=now, rounds=int(x.get("rounds", 0)) + 1)
        self.save()
        extra = dict(extra, when=fmt_when(t, now), place=app.places.label(x["place"]))
        return "appoint_counter", {}, extra

    def _plan(self, char, st, x=None):
        """相手の側の, 当日のこと (約束したときに決まる. 画面には出さない). 体調不良のキャンセルは当日の健康で決める.
        相手も自分の家から約束の場所へ移動する (core/geo.py): 電車・バスなら遅延, 車なら渋滞で遅れることがある. go: 移動の分."""
        p = st["params"]
        low = max(0.0, -self.app.attach.factor(char, st, "devotion"))      # 自分優先なほど, すっぽかし・遅刻しやすい
        punctual = float(self.app.traits(char).get("punctual", 0.75)) - 0.15 * low
        noshow = random.random() < 0.02 + (1 - punctual) * 0.08 + max(0.0, 45 - p.get("affection", 50)) / 300.0 + 0.06 * low
        late = 0
        why = None                                 # 遅れの理由 (A41): slow 支度 / oversleep 寝坊 / traffic 電車・道の遅れ
        if not noshow and random.random() > punctual:
            late = int(random.uniform(5, 40) * (1.5 - punctual))
            hour = datetime.fromtimestamp(x["t"]).hour if x and x.get("t") else 14
            night = float(self.app.traits(char).get("chrono", 0))
            why = "oversleep" if hour <= 11 and random.random() < 0.15 + 0.5 * max(0.0, night) else "slow"
        recent = self.her_recent(st)
        move = not noshow and random.random() < 0.3 * low           # 自分の都合で, 日を動かしたいと言ってくる
        chg = not noshow and not move and random.random() < CHG_P * 0.5 ** recent       # 誰でもまれに, 時刻・場所・することを変えたい
        go = 0
        her_side = bool(x and x.get("place") and (not places_mod.is_home(x["place"]) or x["place"] == places_mod.HOME_ME))
        if her_side:                                                                       # 相手の家なら移動なし
            try:
                lg = self.app.geo.leg("home:" + char["id"], x["place"], None, x["t"])
                go = int(lg["min"])
                if not noshow and lg.get("note") and lg["how"] in ("transit", "car", "taxi", "bike"):
                    late += int(random.uniform(5, 20))         # 途中の遅れ (遅延・渋滞・パンク)
                    why = why or "traffic"
            except ValueError:
                go = 0
        early = 0                                  # 早く着いて待っている (時間にきっちりなほど・寄りかかるほど)
        if her_side and not noshow and not late:
            pe = 0.08 + 0.5 * (punctual - 0.75) + 0.08 * max(0.0, self.app.attach.factor(char, st, "dependence"))
            if random.random() < max(0.02, min(0.35, pe)):
                early = random.randint(5, 20)
        out = {"noshow": noshow, "late": late, "cancel_checked": False, "move": move, "go": go}
        if why and late:
            out["late_why"] = why
        if early:
            out["early"] = early
        if chg and x and x.get("t") and x.get("made") is not None:
            room = x["t"] - 2 * 3600 - max(float(x.get("made") or 0), time.time())
            if room > 3600:                        # 言ってくる時期: 数日前〜2 時間前のどこか
                out["chg_at"] = x["t"] - 2 * 3600 - random.uniform(0, min(room, 3 * 86400))
        return out

    # ------------------------------------------------------------------ 相手の側のブレ (A41・S34)
    def her_recent(self, st, now=None):
        """相手が最近 (HER_SPAN) 遅れた・取りやめた・変えた・切り上げた回数 (続けて起こしにくくする)."""
        now = now or time.time()
        return len([t for t in st.get("her_moves") or [] if 0 <= now - t < HER_SPAN])

    def her_note(self, st, now):
        """相手の側のブレを 1 回数える (お互いさまの her_moved とは別に, 起こしやすさだけに使う)."""
        st["her_moves"] = [t for t in st.get("her_moves") or [] if 0 <= now - t < HER_SPAN] + [now]

    def _tell(self, char, st, x, key, extra, now, kind=None, phone=True):
        """相手からの連絡 (遅れる・取りやめ・変えたい・着いた): 電話にすることもある (出なければメッセージで届く. core/ring.py)."""
        app = self.app
        text = app.chat.line(char, key, extra)
        p = TELL_PHONE * float(app.traits(char).get("approach", 1.0)) * (1.3 if app.phonetalk.close_rel(char, st) else 1.0)
        if not (phone and random.random() < p and app.ring.tell(char, st, x, text, kind or key, now)):
            app.chat.add(x["cid"], "her", text, kind=kind or key, t=now, appoint=x["id"])
        app.picked_up_phone(char, st, now)
        app.save_state(x["cid"])
        return text

    def drop_chance(self, char, st, x, now):
        """直前の取りやめ (体調以外) の起きやすさと, 理由ごとの重み. 体調 (健康 45 未満) は別に 6 割.
        仕事・急用・家のことは誰にでもまれに, 気分 (機嫌が悪い・ストレス)・天気 (屋外の行き先で, 猛暑・真冬・雨)・相手の交友関係の
        予定と重なった (circle) が足される. 自分優先なほど起きやすく, 仲がいいほど起きにくく, 最近起こしていれば半分ずつ."""
        app = self.app
        p = st["params"]
        low = max(0.0, -app.attach.factor(char, st, "devotion"))
        w = {"work": 1.0, "urgent": 1.0, "family": 0.7}
        mood = (0.04 if p.get("mood", 50) < 35 else 0.0) + (0.03 if p.get("stress", 0) > 70 else 0.0)
        wx = 0.0
        pl = app.places.get(x["place"]) or {}
        if pl.get("outdoor"):
            wx = 0.06 * max(0.0, 0.9 - season_mod.out_factor(app, char, datetime.fromtimestamp(x["t"]))) / 0.55
        circle = 0.08 if app.circle.plan_over(char, st, x["t"], x["t"] + 2 * 3600) else 0.0
        pr = (DROP_BASE + 0.03 * low + mood + wx + circle) * max(0.4, min(1.0, 1.3 - p.get("affection", 50) / 100.0)) \
            * 0.5 ** self.her_recent(st, now)
        w["mood"] = 20 * mood
        w["weather"] = 20 * wx
        w["urgent"] += 20 * circle                # 友達・家族との予定と重なった: 急な用事として言う
        return pr, w

    def _drop_plan(self, x, char, st, now):
        """約束の 3 時間前ごろ: 直前の取りやめになるかを決め, 連絡の時刻と形を plan["drop"] に置く (見えない).
        連絡の形: メッセージ (電話のことも) / 連絡なしで来ない (すっぽかし: 自分優先・気分のときほど).
        気分のときは, 正直に言うか別の理由にするか (仲・機嫌しだい. 嘘を見抜く仕組みは作らない)."""
        app = self.app
        if x.get("care") or x.get("plants") or x.get("ask_now"):
            return None
        plan = x.setdefault("plan", {})
        if plan.get("noshow"):
            return None
        p = st["params"]
        if p.get("health", 90) < 45 and random.random() < 0.6:
            why = "sick"
        else:
            pr, w = self.drop_chance(char, st, x, now)
            if random.random() >= pr:
                app.trace.add("appoint", "直前の取りやめ: なし", x["cid"], now, appoint=x["id"], chance=round(pr, 3))
                return None
            why = random.choices(list(w), list(w.values()))[0]
        low = max(0.0, -app.attach.factor(char, st, "devotion"))
        silent = why != "sick" and random.random() < 0.05 + 0.15 * low + (0.15 if why == "mood" else 0.0)
        say = why
        if why == "mood" and random.random() >= 0.25 + 0.3 * (p.get("affection", 50) - 50) / 50.0:
            say = random.choice(("urgent", "family"))               # 気分が乗らないとは言わず, 別の理由にする
        last = x["t"] - (3600 if why == "mood" else 20 * 60)
        at = now if why == "sick" else random.uniform(now, max(now, last))
        plan["drop"] = {"why": why, "say": say, "at": at, "silent": silent}
        app.trace.add("appoint", "直前の取りやめになる", x["cid"], now, appoint=x["id"], why=why, say=say, silent=silent,
                      at=datetime.fromtimestamp(at).strftime("%H:%M"))
        return plan["drop"]

    def _drop_send(self, x, char, st, dr, now, out):
        """直前の取りやめを伝える (連絡なしなら, すっぽかしになるだけ). 代わりの日を出してくることも. 伝えたら True."""
        app = self.app
        cid = x["cid"]
        plan = x.setdefault("plan", {})
        self.her_note(st, now)
        if dr.get("silent"):
            plan["noshow"] = True                  # 連絡なしで来ない (今のすっぽかしと同じ流れ. あとで謝ることも)
            app.save_state(cid)
            return False
        say = dr.get("say") or dr.get("why")
        key = "appoint_cancel" if say == "sick" else "appoint_drop_" + say
        self.her_moved(cid, now)
        p = st["params"]
        alt_p = 0.35 + 0.3 * app.attach.factor(char, st, "devotion") + (p.get("affection", 50) - 50) / 150.0 \
            - (0.2 if dr["why"] == "mood" else 0.0)
        alt = self._alt_time(char, x, now) if dr["why"] != "sick" and int(x.get("rounds", 0)) < COUNTER_MAX \
            and random.random() < alt_p else None
        x["status"] = "cancelled"
        x["cancel_by"] = "her"
        x["drop_why"] = dr["why"]
        self._tell(char, st, x, key, {"place": app.places.label(x["place"])}, now)
        if alt:                                    # 代わりの日を出す: 誘いとして受ける / 断る / 別の日時を返す
            x.update(t=alt, status="offered", made=now, by="her", rounds=int(x.get("rounds", 0)) + 1, plan={})
            x.pop("arrived", None)
            app.chat.add(cid, "her", app.chat.line(char, "appoint_drop_alt", {"when": fmt_when(alt, now)}), kind="appoint_drop_alt",
                         t=now + 0.002, appoint=x["id"])
            app.save_state(cid)
        out.append("%sから、約束のキャンセルの連絡が来た" % char.get("name", ""))
        return True

    def _her_change(self, x, char, st, now, out):
        """相手から, 決まった約束を変えたいと言ってくる (A41): 時刻をずらす / 場所を変える (天気・店の都合) / することを変える.
        誘いとして返事を待つ (受ける / 断る / 別の日時を返す). 断られたら, そのまま来る・渋々来る・やめる (answer). 言ったら True."""
        app = self.app
        cid = x["cid"]
        if x.get("help") or x.get("care") or x.get("fixed") or x.get("plants") or x.get("now") or x["do"] == FAVOR_DO \
                or int(x.get("rounds", 0)) >= COUNTER_MAX:
            return False
        dt = datetime.fromtimestamp(x["t"])
        act = app.action(x["do"])
        pl = app.places.get(x["place"]) or {}
        opts = []
        here_do = [a for a in self.dos_at(cid, x["place"]) if a["id"] != x["do"] and phase_ok(app, a, dt)]
        if pl.get("outdoor") and season_mod.out_factor(app, char, dt) < 0.75:
            opts.append(("place_weather", 4.0))
        shift = next((x["t"] + d for d in (3600, -3600) if x["t"] + d > now + 2 * 3600
                      and self._alt_ok(char, x, act, datetime.fromtimestamp(x["t"] + d), now)), None)
        if shift:
            opts.append(("time", 1.0))
        if not places_mod.is_home(x["place"]):
            opts.append(("place", 0.7))
        if here_do:
            opts.append(("do", 0.6))
        if not opts:
            return False
        kind = random.choices([k for k, _ in opts], [w for _, w in opts])[0]
        new = {"t": x["t"], "place": x["place"], "do": x["do"]}
        why = "weather" if kind == "place_weather" else random.choice(("work", "urgent")) if kind == "time" else "mood"
        if kind == "time":
            new["t"] = shift
        elif kind == "do":
            new["do"] = random.choice(here_do)["id"]
        else:
            cands = []
            for c in self.choices(cid):
                if c["place"] == x["place"] or places_mod.is_home(c["place"]) or not places_mod.open_state(c["place"], dt)["open"]:
                    continue
                if kind == "place_weather" and (app.places.get(c["place"]) or {}).get("outdoor"):
                    continue
                for a in self.dos_at(cid, c["place"]):
                    if phase_ok(app, a, dt):
                        cands.append((c["place"], a))
            if not cands:
                return False
            pid, a = self.pick(char, st, cands, dt)
            new.update(place=pid, do=a["id"])
        x["her_chg"] = {"old": {"t": x["t"], "place": x["place"], "do": x["do"]}, "kind": kind, "why": why}
        x.update(new, status="offered", made=now, by="her", rounds=int(x.get("rounds", 0)) + 1, ask=False)
        x.pop("arrived", None)
        self.her_note(st, now)
        self.her_moved(cid, now)
        key = "appoint_chg_" + kind
        self._tell(char, st, x, key, {"when": fmt_when(new["t"], now), "place": app.places.label(new["place"]),
                                       "what": app.action(new["do"]).get("name", "")}, now)
        app.trace.add("appoint", "約束を変えたいと言ってきた", cid, now, appoint=x["id"], kind=kind, why=why, new=new)
        out.append("%sから、約束を変えたいと連絡が来た" % char.get("name", ""))
        return True

    def _her_change_no(self, char, st, x, now):
        """相手からの変えたいを断った: そのまま来る (keep) / 渋々来る (grudge. 機嫌が少し下がる) / やめる (drop).
        やむを得ない理由 (仕事・急用で時刻を・自分の都合で日を) ほど, もとのままでは来られずにやめやすい. 献身的なほど合わせる."""
        app = self.app
        ch = x.pop("her_chg")
        dev = app.attach.factor(char, st, "devotion")
        if ch["kind"] in ("time", "day"):
            w = {"keep": 0.25, "grudge": 0.3, "drop": 0.45}
        elif ch["kind"] == "place_weather":
            w = {"keep": 0.45, "grudge": 0.45, "drop": 0.1}
        else:
            w = {"keep": 0.6, "grudge": 0.3, "drop": 0.1}
        w["keep"] *= 1 + 0.5 * max(0.0, dev)
        w["drop"] *= 1 + max(0.0, -dev)
        res = random.choices(list(w), list(w.values()))[0]
        x.update(ch["old"])
        extra = {"when": fmt_when(x["t"], now), "place": app.places.label(x["place"])}
        if res == "drop":
            x["status"] = "cancelled"
            x["cancel_by"] = "her"
            eff = {}
        else:
            x["status"] = "set"
            x["plan"] = {k: v for k, v in self._plan(char, st, x).items() if k != "chg_at"}
            x["plan"]["move"] = False
            eff = {"mood": -2} if res == "grudge" else {}
        app.chat.add(x["cid"], "her", app.chat.line(char, "appoint_chg_" + res, extra), kind="appoint_chg_" + res, t=now + 0.002,
                     appoint=x["id"])
        app.trace.add("appoint", "変えたいを断られて: %s" % res, x["cid"], now, appoint=x["id"], kind=ch["kind"], w=w)
        return res, eff

    def heading(self, cid, now=None):
        """相手がいま約束の場所へ向かっているところなら, その約束 (相手の様子に「向かっている」と出す)."""
        now = now or time.time()
        for x in self.all():
            if x["cid"] != cid or x["status"] not in ("set", "waiting"):
                continue
            pl = x.get("plan") or {}
            if pl.get("noshow") or not pl.get("go"):
                continue
            come = self.her_eta(x)[0]
            if come - pl["go"] * 60 <= now < come:
                return x
        return None

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
                    app.regard.sign(char, st, "favor_yes", now)
                    app.chat.add(x["cid"], "me", "（%sを引き受けた: %s）" % (x.get("label", ""), self.when_of(x, now)), kind="appoint", t=now)
                else:
                    x["status"] = "refused"
                    eff = {"mood": -1}
                    app.regard.sign(char, st, "favor_no", now)
                    app.chat.add(x["cid"], "me", "（%sは断った）" % x.get("label", ""), kind="appoint", t=now)
                    f = app.earn.favor(x["favor"])
                    if f:
                        app.earn.favors().remove(f)
                app.apply_effects(st, app.trait_effects(char, eff))
                app.chat.mark_read_by_her(x["cid"], now)
                app.save_state(x["cid"])
                self.save()
                return {"ok": True, "status": x["status"]}
            if x.get("care"):                # 看病に呼ばれた: 相手は家で寝ているので, すっぽかしも遅刻もない
                if yes:
                    x["status"] = "set"
                    x["plan"] = {}
                    eff, _ = app.bonds.realize(char, st, {"mood": 3, "trust": 1}, "_care_yes", now)
                    app.regard.sign(char, st, "care_yes", now)
                    app.chat.add(x["cid"], "me", "（看病に行くと返した）", kind="appoint", t=now)
                else:
                    x["status"] = "refused"
                    pm = app.presence.rec().get("mode")
                    eff = {"mood": -1} if pm in ("work", "out") else {"mood": -3, "trust": -1}       # 仕事・外出中なら仕方ない
                    app.regard.sign(char, st, "care_no_busy" if pm in ("work", "out") else "care_no", now)
                    app.chat.add(x["cid"], "me", "（看病には行けないと返した）", kind="appoint", t=now)
                app.apply_effects(st, app.trait_effects(char, eff))
                app.chat.mark_read_by_her(x["cid"], now)
                app.save_state(x["cid"])
                self.save()
                return {"ok": True, "status": x["status"]}
            if yes:
                x["status"] = "set"
                x.pop("her_chg", None)
                x["plan"] = self._plan(char, st, x)
                eff, _ = app.bonds.realize(char, st, {"mood": 3, "heart": 2, "affection": 0.5}, "_appoint", now)
                app.regard.sign(char, st, "invite_yes", now)
                app.bonds.touch(st, now)
                app.chat.add(x["cid"], "me", "（%s、%sの約束をした）" % (fmt_when(x["t"], now), app.places.label(x["place"])),
                             kind="appoint", t=now)
                # お礼の心当たり: 相手が出し返した日時・相手からの誘いに応じて決まった約束も, 相手が約束してくれたこと
                # (以前は記録しておらず, 直後に「約束してくれた」とお礼を言うと「え、何が？」と返っていた)
                self._favor_set(st, x, now)
            elif x.get("her_chg"):            # 相手からの変えたい (A41) を断った: もとの約束に戻して, そのまま来る・渋々来る・やめる
                app.chat.add(x["cid"], "me", "（変えるのは断った）", kind="appoint", t=now)
                _, eff = self._her_change_no(char, st, x, now)
            else:
                x["status"] = "refused"
                eff = {"mood": -2}
                app.regard.sign(char, st, "invite_no", now)
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
            * float(app.traits(char).get("approach", 1)) * self.mood_factor(p) \
            * app.regard.invite_factor(char, st) * app.circle.invite_f(char, st)             * (TIGHT_INVITE if app.purse.tight(char, st) else 1.0) \
            * app.waves.invite_factor(char, st)      # 思われていないと感じる (core/regard.py)・所持金が苦しいと, 誘いを控える・生活の波と慣れ (core/waves.py)
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
            homes = [(pid, a) for pid, a in self._home_opts(cid) if phase_ok(app, a, day)]
            fam = app.athome.fam(cid, st, now)[0]
            if homes and (not opts or random.random() < HOME_INVITE + HOME_INVITE_FAM * fam):
                pid, a = self._pick_home(cid, st, homes, now)
            elif opts:
                pid, a = self.pick(char, st, opts, day)
            else:
                continue
            x = {"id": uuid.uuid4().hex[:8], "cid": cid, "t": day.timestamp(), "place": pid, "do": a["id"], "by": "her",
                 "status": "offered", "made": now}
            self.all().append(x)
            self.save()
            text = app.chat.line(char, self.invite_key(pid), {"when": fmt_when(x["t"], now), "place": app.places.label(pid)})
            app.chat.add(cid, "her", text + "（%s）" % self.invite_label(pid, a), kind="appoint_invite", t=now, appoint=x["id"])
            app.picked_up_phone(char, st, now)
            app.save_state(cid)
            return x
        return None

    def _home_opts(self, cid):
        """家に行ける仲なら, 家での約束も誘える (相手の家に呼ぶ / あなたの家に行きたい)."""
        if self.app.bonds.stage(cid) != "visit":
            return []
        return [("home:" + cid, self.app.action("visit_home")), (places_mod.HOME_ME, self.app.action("invite_home"))]

    def _pick_home(self, cid, st, homes, now):
        """相手の家に呼ぶか, あなたの家に行きたいか: 慣れているほど自分の家に呼びやすい. あとは性格 (人懐っこい人ほど行きたがる)."""
        fam = self.app.athome.fam(cid, st, now)[0]
        go = float(self.app.traits(self.app.chars[cid]).get("approach", 1))
        w = {places_mod.HOME_ME: 0.5 * go}
        return random.choices(homes, [w.get(pid, 0.4 + 0.6 * fam) for pid, _ in homes])[0]

    @staticmethod
    def invite_key(pid, now=False):
        k = "appoint_invite_now" if now else "appoint_invite"
        if pid == places_mod.HOME_ME:
            return k + "_yourhome"
        if places_mod.is_home(pid):
            return k + "_myhome"
        return k

    def invite_label(self, pid, a):
        """誘いのメッセージのあとに添える, すること (家なら場所)."""
        if places_mod.is_home(pid):
            return self.app.places.label(pid)
        return a.get("name", "")

    def _by_phone(self, char, st, x, kind, chat_kind, text, now):
        """頼みごと (急な誘い・看病・頼まれごと) を電話で切り出すなら鳴らして True (メッセージは, 出なかったときに post_offer で)."""
        x["offer_kind"] = chat_kind
        if not self.app.ring.offer(char, st, x, kind, text, now):
            x.pop("offer_kind", None)
            return False
        self.save()
        return True

    def post_offer(self, aid, t, now=None):
        """電話で切り出すつもりだった頼みごとを, メッセージで届ける (出なかった / あとで返事する). まだ答えていなければ."""
        x = next((y for y in self.all() if y.get("id") == aid), None)
        if not x or x.get("status") != "offered" or not x.get("offer_text"):
            return None
        self.app.chat.later(x["cid"], "her", x.pop("offer_text"), t, t if now is None else now,
                            kind=x.pop("offer_kind", "appoint_invite"), appoint=x["id"])
        self.save()
        return x

    def care_call(self, char, st, now, want):
        """看病に来てほしい (core/care.py): 急な誘いと同じ形の約束. 待ち合わせは 30〜45 分先 (買い物して来られるくらい)."""
        app = self.app
        cid = char["id"]
        t = now + random.choice((30, 40, 45)) * 60
        x = {"id": uuid.uuid4().hex[:8], "cid": cid, "t": t, "place": "home:" + cid, "do": "visit_home", "by": "her",
             "status": "offered", "made": now, "now": True, "care": True, "want": list(want)}
        self.all().append(x)
        self.save()
        key = "care_call_want" if want else "care_call"
        text = app.chat.line(char, key, {"items": app.care.want_text(want)})
        if not self._by_phone(char, st, x, "care", "appoint_invite", text + "（看病・%sの家・%s）" % (char.get("name", ""), fmt_when(t, now)), now):
            app.chat.add(cid, "her", text + "（看病・%sの家・%s）" % (char.get("name", ""), fmt_when(t, now)), kind="appoint_invite",
                         t=now, appoint=x["id"])
        app.picked_up_phone(char, st, now)
        app.save_state(cid)
        app.trace.add("care", "看病に来てほしいと連絡してきた", cid, now, appoint=x["id"], want=want)
        return x

    def _maybe_now(self, cid, now, h):
        """いまから会わない？ (急な誘い): 相手がいま手すきで, 退屈・寂しい・機嫌がいいと. 待ち合わせは少し先 (NOW_LEAD 分).
        家に行ける仲なら, 家に呼ぶ / 近くにいるから寄っていい？ も (慣れているほど家になりやすい).
        返事は約束の答えと同じ. 返事がないまま時間が過ぎても, 急な誘いなので気にするのは少しだけ."""
        app = self.app
        if app.bonds.stage(cid) not in ("contact", "visit") or app.bonds.together(cid) or self.open_with(cid):
            return None
        char, st = app.chars[cid], app.state(cid)
        p = st["params"]
        if p.get("affection", 0) < 50:
            return None
        want = max(0.0, (p.get("boredom", 30) - 40) / 40.0) + max(0.0, (p.get("loneliness", 30) - 40) / 50.0) \
            + max(0.0, (p.get("mood", 50) - 55) / 60.0)
        rate = NOW_RATE * want * float(app.traits(char).get("approach", 1)) * self.mood_factor(p) * app.regard.invite_factor(char, st) * app.circle.invite_f(char, st)             * (TIGHT_INVITE if app.purse.tight(char, st) else 1.0) * app.waves.invite_factor(char, st)
        if not rate or random.random() >= rate * h:
            return None
        dt = datetime.fromtimestamp(now)
        if app.phase_at(dt).get("id") in ("midnight", "dawn"):
            return None
        sc = app.scene_at(char, st, dt)
        if sc["away"] or sc["busy"] or sc["asleep"] or sc.get("source") == "override":
            return None
        t = now + random.choice(NOW_LEAD) * 60
        day = datetime.fromtimestamp(t)
        later = app.scheduled_scene(char, day + timedelta(hours=1))        # 会ってからも少しは手すき
        if later["away"] or later["busy"] or later["asleep"]:
            return None
        opts = [(pid, a) for pid in places_mod.OUT_PLACES for a in self.dos_at(cid, pid)
                if phase_ok(app, a, day) and places_mod.open_state(pid, day)["open"]]
        homes = [(pid, a) for pid, a in self._home_opts(cid) if phase_ok(app, a, day)]
        fam = app.athome.fam(cid, st, now)[0]
        if homes and (not opts or random.random() < NOW_HOME + HOME_INVITE_FAM * fam):
            pid, a = self._pick_home(cid, st, homes, now)
        elif opts:
            pid, a = self.pick(char, st, opts, datetime.fromtimestamp(t))
        else:
            return None
        x = {"id": uuid.uuid4().hex[:8], "cid": cid, "t": t, "place": pid, "do": a["id"], "by": "her",
             "status": "offered", "made": now, "now": True}
        self.all().append(x)
        self.save()
        text = app.chat.line(char, self.invite_key(pid, now=True), {"when": fmt_when(t, now), "place": app.places.label(pid)})
        full = text + "（%s・%s）" % (self.invite_label(pid, a), fmt_when(t, now))
        if not self._by_phone(char, st, x, "now", "appoint_invite", full, now):          # 急ぐので, 電話で来ることも (A23 段 2)
            app.chat.add(cid, "her", full, kind="appoint_invite", t=now, appoint=x["id"])
        app.picked_up_phone(char, st, now)
        app.save_state(cid)
        app.trace.add("appoint", "急に誘ってきた", cid, now, appoint=x["id"], place=pid)
        return x

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
        """行き先の選ばれやすさ (気持ち傾くだけ. 0.8〜1.8): 好きなものに合う所・一緒に行って楽しかった所・まだ行ったことのない所・
        あなたがよく誘う所 (覚えた好み place:<id>. 世話焼きほど汲み, 機嫌が悪いと汲まない. A44 段 1)."""
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
        w += PLACE_PREF * max(0.0, prefs_mod.pref(st, "place:%s" % pid)) * prefs_mod.receptive(self.app, char, st)
        return max(0.8, min(1.8, w))

    def pick(self, char, st, opts, dt=None):
        """誘う行き先とすること. 好みで少しだけ傾けて, あとは偶然. 所持金が苦しいときは, お金のかかることを避ける.
        dt があれば, その時の暑さ・寒さ・天気で屋外の行き先を傾ける (S38)."""
        tight = self.app.purse.tight(char, st)
        return random.choices(opts, [self.place_weight(char, st, pid) * (TIGHT_PAID if tight and self.paid(a) else 1.0)
                                     * (self.out_factor(char, pid, dt) if dt else 1.0) for pid, a in opts])[0]

    def out_factor(self, char, pid, dt):
        """屋外の行き先への, その時の気持ち (暑さ・寒さ・雨と, 外好きか. 屋内の行き先・相手の家は 1. S38). あなたの家は室温 (S39).
        行き先の季節の向き不向き (海は夏・星は冬・公園は春秋. S39) も掛ける."""
        if pid == places_mod.HOME_ME:            # あなたの家: その時の室温 (冷暖房しだい. S39)
            return season_mod.home_ask(self.app, char, dt, self.app.home.ac_mode())
        pl = self.app.places.get(pid) or {}
        return season_mod.out_factor(self.app, char, dt) * season_mod.place_ask(pid, dt) if pl.get("outdoor") else 1.0

    @staticmethod
    def paid(a):
        return bool(a.get("cost") or a.get("meal_out"))

    def remember(self, cid, place, mood_delta):
        """一緒に行った行き先の楽しさを覚える (次に誘うときに, 少しだけ選ばれやすく)."""
        st = self.app.state(cid)
        pf = st.setdefault("place_fun", {})
        if place not in pf:              # 一緒に初めて行った所: 新鮮さが戻ることがある (core/waves.py)
            self.app.waves.novel(self.app.chars[cid], st, "place", why=place)
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
        if x.get("favor") or x.get("help"):
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

    # ------------------------------------------------------------------ 決まった約束を, こちらから変える・取りやめる
    def change(self, aid, t, place=None, do=None, now=None):
        """約束した (set) 約束の日時 (・行き先・すること) を変えたいと伝える. 返事は時間差 (msg_pending の kind appoint_change).
        返事が来るまでは, もとの約束のまま. 応じるかと, 応じたときの受け取り方は change_reply."""
        app = self.app
        now = now or time.time()
        x = self.get(aid)
        self._can_touch(x, now)
        if x.get("change"):
            raise ValueError("変えたいと伝えた返事を待っています")
        if x.get("now") or x.get("care") or x.get("fixed") or x.get("plants"):
            raise ValueError("この約束は日時を動かせません（取りやめるかどうかだけ）")
        t = float(t)
        if t < now + 30 * 60 or t > now + 14 * 86400:
            raise ValueError("約束は 30 分後から 2 週間先までです")
        if x.get("favor") or x.get("help"):            # 頼まれごと・頼んだ手伝い: 場所は決まっている. 日時だけ
            place, do = x["place"], x["do"]
        else:
            place = place or x["place"]
            do = do or x["do"]
            if not any(a["id"] == do for a in self.dos_at(x["cid"], place)):
                raise ValueError("その行き先では、それはできません")
            a = app.action(do)
            if not phase_ok(app, a, datetime.fromtimestamp(t)):
                raise ValueError("「%s」はその時間帯にはできません（%s）" % (a.get("name", do), a.get("when", "")))
            o = places_mod.open_state(place, datetime.fromtimestamp(t))
            if not o["open"]:
                raise ValueError("その時間、%sは閉まっています（%s・%s）" % (app.places.label(place), o["note"], o["hours"]))
        if abs(t - x["t"]) < 60 and place == x["place"] and do == x["do"]:
            raise ValueError("いまの約束と同じです")
        for y in self.open_with(x["cid"]):
            if y["id"] != x["id"] and abs(y["t"] - t) < 3 * 3600:
                raise ValueError("その時間の近くに、もう約束（か返事待ち）があります")
        if place == "restaurant" and (place != x["place"] or abs(t - x["t"]) >= 60):
            from .anniv import reserve_full
            if reserve_full(t, now):
                raise ValueError("%sは、その日時の予約が取れなかった（いっぱいだった）" % app.places.label(place))
        x["change"] = {"t": t, "place": place, "do": do, "made": now}
        self.save()
        what = x.get("label") if x.get("favor") or x.get("help") else "%sで「%s」" % (app.places.label(place), app.action(do).get("name", do))
        self._send(x, now, "（%sの約束を、%s、%sに変えられないか聞いた）" % (fmt_when(x["t"], now), fmt_when(t, now), what),
                   kind="appoint_change")
        return self.row(x, now)

    def cancel(self, aid, now=None):
        """約束した約束を取りやめると伝える. 取りやめは伝えた時点で決まる (相手は断れない). 受け取り方は, 読んでから (時間差の返事)."""
        app = self.app
        now = now or time.time()
        x = self.get(aid)
        self._can_touch(x, now)
        x.pop("change", None)
        x["status"] = "cancelled"
        x["cancel_by"] = "me"
        x["cancel_at"] = now
        self._my_move(x["cid"], now)
        if x.get("favor"):
            self._favor_drop(x)
        self.save()
        self._send(x, now, "（%sの約束を、取りやめたいと伝えた）" % self.when_of(x, now), kind="appoint_cancel_me")
        return self.row(x, now)

    def _can_touch(self, x, now):
        if x["status"] == "waiting":
            raise ValueError("もう約束の場所で待っています")
        if x["status"] != "set":
            raise ValueError("この約束はもう%s" % STATUS_LABEL.get(x["status"], x["status"]))
        if now > x["t"]:
            raise ValueError("約束の時刻を過ぎています")
        if self.app.bonds.together(x["cid"]):
            raise ValueError("いまはそばにいるので、直接話しましょう")

    def _my_move(self, cid, now):
        """あなたが約束を動かした・取りやめた時刻 (続くと, 受け取り方が悪くなる)."""
        st = self.app.state(cid)
        st["my_moves"] = [t for t in st.get("my_moves") or [] if now - t < MOVE_SPAN] + [now]

    def her_moved(self, cid, now):
        """相手が約束を動かした・取りやめた・来なかった (お互いさま: しばらくは, こちらの変更にすんなり応じやすい)."""
        self.app.state(cid)["her_moved"] = now

    def change_score(self, char, st, x, ref, new=None, cancel=False):
        """変更・取りやめの受け取りにくさ (0 前後ならすんなり. 大きいほど悪く取られる) と, いちばん効いた理由 (late / again / "").
        伝えた時期・何回目か・誰が誘ったか・性格 (時間にきっちりか)・仲と機嫌と献身・お互いさま・変え方の中身 (好きな所へ・早く会える)."""
        app = self.app
        p = st["params"]
        h = (x["t"] - ref) / 3600.0
        notice = 0.0 if h >= 72 else 0.1 if h >= 24 else 0.3 if h >= 6 else 0.55
        recent = [t for t in st.get("my_moves") or [] if ref - t < MOVE_SPAN and abs(t - ref) > 1]
        again = 0.25 * int(x.get("changes", 0)) + 0.12 * len(recent)
        who = 0.15 if x.get("by") == "her" and not x.get("favor") else 0.1 if x.get("favor") else 0.0
        punct = (float(app.traits(char).get("punctual", 0.75)) - 0.75) * 0.8
        rel = (p.get("affection", 50) - 50) / 120.0 + (p.get("mood", 50) - 50) / 200.0 + 0.15 * app.attach.factor(char, st, "devotion")
        mutual = 0.25 if ref - float(st.get("her_moved", 0)) < 30 * 86400 else 0.0
        content = 0.0
        if new:
            if new["place"] != x["place"]:
                content += 0.4 * (self.place_weight(char, st, new["place"]) - self.place_weight(char, st, x["place"]))
            if new["t"] < x["t"] and p.get("loneliness", 30) > 55:
                content += 0.1                           # 早く会える
        s = notice + again + who + punct - rel - mutual - content + random.uniform(-0.15, 0.15) + (0.25 if cancel else 0.0)
        why = "late" if notice >= 0.3 and notice >= again else "again" if again >= 0.25 else ""
        return s, why, content

    def change_reply(self, char, st, pend, now):
        """変えたい・取りやめたいへの返事 (時間差で届いたとき). (セリフの場面, 効果, 置き換え) を返す."""
        app = self.app
        x = self.find(pend.get("appoint"))
        if pend.get("kind") == "appoint_cancel_me":
            return self._cancel_reply(char, st, x, now)
        ch = (x or {}).pop("change", None)
        if not x or not ch or x["status"] != "set" or now > x["t"]:
            if x:
                self.save()
            return "appoint_change_gone", {}, {"when": "", "place": "", "what": ""}
        new = {"t": ch["t"], "place": ch["place"], "do": ch["do"]}
        extra = {"when": fmt_when(new["t"], now), "place": app.places.label(new["place"]), "what": x.get("label", ""),
                 "was": fmt_when(x["t"], now)}
        self._my_move(x["cid"], ch["made"])
        busy = app.scheduled_scene(char, datetime.fromtimestamp(new["t"]))
        if busy["away"] or busy["busy"] or busy["asleep"]:                                         # その時間は相手に予定がある: 別の時間を返すか, もとのままがいいと言う
            alt = self._alt_time(char, dict(x, **new), now) if int(x.get("rounds", 0)) < COUNTER_MAX else None
            if alt and random.random() < 0.75:
                x.update(new, t=alt, status="offered", made=now, rounds=int(x.get("rounds", 0)) + 1, moving=True, ask=False)
                x["changes"] = int(x.get("changes", 0)) + 1
                self.save()
                return "appoint_change_counter", {}, dict(extra, when=fmt_when(alt, now))
            self.save()
            return "appoint_change_keep_busy", {}, dict(extra, when=extra["was"])
        s, why, content = self.change_score(char, st, x, ch["made"], new=new)
        app.trace.add("appoint", "約束を変えたいと言われた", x["cid"], now, appoint=x["id"], score=round(s, 2), why=why)
        if s >= 0.65 and random.random() < 0.5:
            if x.get("favor"):                           # 頼まれごと: それならほかの人に頼む (取りやめ)
                x["status"] = "cancelled"
                x["cancel_by"] = "her"
                self._favor_drop(x)
                self.save()
                return "appoint_change_others", {"mood": -1, "trust": -1}, extra
            self.save()
            return "appoint_change_keep_want", {"mood": -1}, dict(extra, when=extra["was"])
        old_t = x["t"]
        x.update(new)
        x["changes"] = int(x.get("changes", 0)) + 1
        x.pop("arrived", None)
        if x.get("favor"):
            x["plan"] = self._favor_plan()
        elif not x.get("help"):
            x["plan"] = {k: v for k, v in self._plan(char, st, x).items() if k != "chg_at"}     # 当日の相手の側は, 決め直し
            x["plan"]["move"] = False                                   # (こちらが動かしたあとに動かし返さない)
        else:
            x.setdefault("plan", {})["cancel_checked"] = False
        self.save()
        app.trace.add("appoint", "約束を変えた", x["cid"], now, appoint=x["id"], old_t=old_t, new_t=x["t"])
        app.manners.favor(st, "change", now)            # お礼の心当たり: 渋々でも応じてくれた (もとのまま・取りやめは残さない)
        if s < 0.15:
            return ("appoint_change_glad", {"mood": 1}, extra) if content > 0.08 else ("appoint_change_fine", {}, extra)
        if s < 0.4:
            return "appoint_change_sad", {"mood": -2}, extra
        return "appoint_change_sour" + ("_" + why if why else ""), {"mood": -3, "affection": -1}, extra

    def _cancel_reply(self, char, st, x, now):
        app = self.app
        extra = {"when": fmt_when(x["t"], now) if x else "", "place": app.places.label(x["place"]) if x else "", "what": (x or {}).get("label", "")}
        if not x:
            return "appoint_cancel_fine", {}, extra
        s, why, _ = self.change_score(char, st, x, x.get("cancel_at", now), cancel=True)
        app.trace.add("appoint", "約束を取りやめると言われた", x["cid"], now, appoint=x["id"], score=round(s, 2), why=why)
        tier = "fine" if s < 0.2 else "sad" if s < 0.45 else "sour" if s < 0.85 else "hurt"
        eff = {"fine": {}, "sad": {"mood": -3, "loneliness": 3}, "sour": {"mood": -4, "affection": -1.5, "trust": -1},
               "hurt": {"mood": -6, "affection": -3, "trust": -2}}[tier]
        if x.get("favor"):
            return "appoint_cancel_favor" + ("" if tier in ("fine", "sad") else "_sour"), dict(eff, trust=eff.get("trust", 0) - 1), extra
        if tier == "sour" and why:
            return "appoint_cancel_sour_" + why, eff, extra
        return "appoint_cancel_" + tier, eff, extra

    def _send(self, x, now, text, kind="appoint"):
        """約束の誘い・別の案・変更・取りやめを送る (トークに要約. 返事はいつものメッセージの時間差・すぐの返信).
        別の約束の返事を待っているところなら, そちらの返事も消さない (appoint_first. 返事は二つ届く)."""
        app = self.app
        cid = x["cid"]
        char = app.chars[cid]
        with app.lock:
            st = app.state(cid)
            scene = app.scene_at(char, st, datetime.fromtimestamp(now))
            ctx = app.context(char, st, datetime.fromtimestamp(now), scene)
            app._phoned(st, now, char, "appoint")
            app.chat.add(cid, "me", text, kind=kind, t=now)
            pend = st.get("msg_pending")
            if pend:            # 返信は, いちばん新しいメッセージに対して
                if pend.get("kind") in APPT_KINDS and pend.get("appoint") != x["id"] and not pend.get("appoint_first"):
                    pend["appoint_first"] = {"kind": pend["kind"], "appoint": pend.get("appoint"), "t": pend.get("kind_t") or pend["t"]}
                pend.update(kind=kind, appoint=x["id"], count=pend.get("count", 1) + 1, reply=True, kind_t=now)
            else:
                delay, quick, _ = app.reply_delay(char, st, now, scene, ctx)
                st["msg_pending"] = {"aid": "message", "t": now, "due": now + delay, "reply": True, "count": 1, "kind": kind,
                                     "appoint": x["id"], "quick": quick}
            app.presence.drop(st)
            app.save_state(cid)

    def _alt_time(self, char, x, now):
        """相手が返す別の案: あなたの案の近く (前後の日・時間) で, 相手の予定が空いていて, 行き先が開いている時間. 無ければ None."""
        app = self.app
        base = datetime.fromtimestamp(x["t"])
        a = app.action(x["do"]) if x["do"] != FAVOR_DO and not x.get("help") else {}
        # 夜勤・シフト・土日が仕事の人は昼の空きが少ないので, 朝と夜の時刻も候補に入れる
        hours = ALT_HOURS_WIDE if (char.get("life") or {}).get("type") in ("night", "shift", "service") else ALT_HOURS
        for _ in range(12):
            d = (base + timedelta(days=random.choice((0, 0, 1, -1, 2)))).replace(
                hour=random.choice(hours), minute=0, second=0, microsecond=0)
            if self._alt_ok(char, x, a, d, now):
                return d.timestamp()
        return None

    def _alt_ok(self, char, x, a, d, now):
        if d.timestamp() < now + 3600 or abs(d.timestamp() - x["t"]) < 3600:
            return False
        sc = self.app.scheduled_scene(char, d)
        if sc["away"] or sc["busy"] or sc["asleep"]:
            return False
        return phase_ok(self.app, a, d) and places_mod.open_state(x["place"], d)["open"]

    def _alt_scan(self, char, x, now):
        """別の案がくじで見つからないとき: もとの日から近い順に先 7 日を, 時刻を順に探す. 無ければ None."""
        base = datetime.fromtimestamp(x["t"])
        a = self.app.action(x["do"]) if x["do"] != FAVOR_DO and not x.get("help") else {}
        for off in (0, 1, -1, 2, -2, 3, 4, 5, 6, 7):
            for hour in ALT_HOURS_WIDE:
                d = (base + timedelta(days=off)).replace(hour=hour, minute=0, second=0, microsecond=0)
                if self._alt_ok(char, x, a, d, now):
                    return d.timestamp()
        return None

    # ------------------------------------------------------------------ 生活の型の割り当て (予定の作り直し) のあと
    def clash(self, char, t):
        """その約束の時刻から 2 時間のあいだ, 相手の基本の予定 (日ごとのずれは見ない) がふさがっているか."""
        for m in range(0, RELIFE_SPAN + 1, 15):
            sc = self.app._base_scene(char, datetime.fromtimestamp(t + m * 60))
            if sc["away"] or sc["busy"] or sc["asleep"]:
                return True
        return False

    def relife_mark(self, cids, now=None):
        """予定を作り直した人との, これから先の約束を点検する (core/lifetype.py world_step から一度だけ).
        新しい予定で都合がつかない約束に印 (relife: 打診を送る時刻) を付ける. 送るのは live (相手が起きていて手が空いているとき).
        - 決まっている約束 (set / waiting)・誘われて返事待ち (offered): 相手から別の日時を打診してくる.
        - こちらの誘いの返事待ち (asked): 何もしない (返事は返すときの予定で決まる).
        - 頼まれごと: 日時の決まっているもの (fixed. 留守の水やり・引っ越し)・都合を聞かれているもの (ask) は触らない.
        - 看病に呼ばれた・あなたが頼んだ手伝い・急な誘い: 触らない.
        - 約束まで 1 時間を切っている: 打診しない (そのまま来る). 3 時間を切っている: すぐ送る.
        ほかは, 人ごとに 5〜90 分ずらす (全員から一斉には来ない). 印を付けた数を返す."""
        app = self.app
        now = now or time.time()
        todo = []
        for x in self.all():
            if x["cid"] not in cids or x["cid"] not in app.chars or x["status"] not in ("set", "waiting", "offered"):
                continue
            if x.get("fixed") or x.get("plants") or x.get("care") or x.get("help") or x.get("ask") or x.get("now"):
                continue
            if x["t"] - now < RELIFE_NEAR or not self.clash(app.chars[x["cid"]], x["t"]):
                continue
            todo.append(x)
        people = sorted({x["cid"] for x in todo})
        random.shuffle(people)
        width = 85.0 / max(1, len(people))
        due = {cid: now + (5 + width * i + random.uniform(0, width * 0.8)) * 60 for i, cid in enumerate(people)}
        for x in todo:
            x["relife"] = now if x["t"] - now < RELIFE_SOON else due[x["cid"]]
        if todo:
            self.save()
        return len(todo)

    def _relife_send(self, x, char, st, now, out):
        """作り直した予定で都合がつかなくなった約束: 相手から別の日時を打診してくる (いまの「自分の都合で日を動かしたい」と同じ流れ.
        受ける / 断る / 別の日時は, いつもの返事). やりとりの回数 (rounds) は増やさない. 相手が動かした事実 (her_moved) は残す.
        空きがどこにも無ければ, 相手からの取りやめ (あなたへの悪影響はなし)."""
        app = self.app
        cid = x["cid"]
        x.pop("relife", None)
        alt = self._alt_time(char, x, now) or self._alt_scan(char, x, now)
        self.her_moved(cid, now)
        fav = bool(x.get("favor"))
        if alt:
            x.update(t=alt, status="offered", made=now, by="her")
            x.pop("arrived", None)
            if fav:
                app.chat.add(cid, "her", app.chat.line(char, "favor_resched", {"what": x.get("label", ""), "when": fmt_when(alt, now)}),
                             kind="favor_resched", t=now, appoint=x["id"])
                out.append("%sから、%sの日をずらしたいと連絡が来た" % (char.get("name", ""), x.get("label", "")))
            else:
                app.chat.add(cid, "her", app.chat.line(char, "appoint_move_mine", {"when": fmt_when(alt, now)}),
                             kind="appoint_move_mine", t=now, appoint=x["id"])
                out.append("%sから、約束の日を変えたいと連絡が来た" % char.get("name", ""))
            app.trace.add("appoint", "暮らし方が変わって都合がつかず, 日を動かしたいと言ってきた", cid, now, appoint=x["id"], new_t=alt)
        else:
            x["status"] = "cancelled"
            if fav:
                app.chat.add(cid, "her", app.chat.line(char, "favor_cancel", {"what": x.get("label", "")}), kind="favor_cancel", t=now)
                self._favor_drop(x)
                out.append("%sから、%sは取りやめになったと連絡が来た" % (char.get("name", ""), x.get("label", "")))
            else:
                app.chat.add(cid, "sys", "（%sから、都合がつかなくなったので約束を取りやめたいと連絡が来た）" % char.get("name", ""),
                             kind="appoint_cancel", t=now)
                out.append("%sから、約束の取りやめの連絡が来た" % char.get("name", ""))
            app.trace.add("appoint", "暮らし方が変わって都合がつかず, 空きも無いので取りやめた", cid, now, appoint=x["id"])
        app.picked_up_phone(char, st, now)
        app.save_state(cid)

    # ------------------------------------------------------------------ 遅れると伝える
    def grace(self, x):
        """この時刻を過ぎても約束の場所にいなければ, すっぽかし. 遅れると伝えていれば, その分 (+ LATE_WAIT) まで待ってくれる."""
        n = x.get("late_note") or {}
        return x["t"] + max(GRACE, int(n.get("min", 0)) * 60 + LATE_WAIT if n else GRACE)

    def late_target(self, cid, now=None):
        """遅れると伝えられる約束 (まだ着いていない決まった約束で, 3 時間前〜待ってくれる時刻まで). 無ければ None."""
        now = now or time.time()
        hit = [x for x in self.all() if x["cid"] == cid and x["status"] == "set" and not x.get("plants")
               and x["t"] - NEAR <= now <= self.grace(x) and not self.here(x["place"], now)]
        return min(hit, key=lambda x: x["t"]) if hit else None

    def late_why(self, cid, now=None):
        if self.app.bonds.together(cid):
            return "いまはそばにいます"
        return "" if self.late_target(cid, now) else "遅れそうな約束がありません（約束の 3 時間前から伝えられます）"

    def tell_late(self, cid, mins, now=None, how="msg"):
        """遅れると伝えた (メッセージは送った時点・電話はつながった時点で決まる). 伝え直しもできる (見込みは新しい方)."""
        now = now or time.time()
        mins = int(mins)
        if mins not in LATE_MINS:
            raise ValueError("遅れる時間が違います")
        x = self.late_target(cid, now)
        if not x:
            raise ValueError(self.late_why(cid, now) or "遅れそうな約束がありません")
        old = x.get("late_note") or {}
        x["late_note"] = {"min": int((now - x["t"]) / 60 + mins) if now > x["t"] else mins, "at": now, "how": how,
                          "n": int(old.get("n", 0)) + 1, "by": max(x["t"], now) + mins * 60}
        st = self.app.state(cid)
        st["late_told"] = [t for t in st.get("late_told") or [] if now - t < LATE_SPAN] + [now]
        self.save()
        self.app.trace.add("appoint", "遅れると伝えた", cid, now, appoint=x["id"], mins=mins, how=how, again=old.get("n", 0))
        return x

    def late_reply(self, char, st, meta, now):
        """遅れると伝えたことへの返事 (メッセージは読んだとき・電話はその場). (セリフの場面, 効果, 置き換え) を返す.
        受け取り方: 伝えた時期 (時刻を過ぎてからほど悪い)・遅れの長さ・性格 (時間にきっちりか)・何度目か・仲と機嫌と献身.
        相手も遅れそうなら「こっちも」, まだ出ていなければ「じゃあゆっくり行く」と自分の出方をずらすことも."""
        app = self.app
        x = self.find(meta.get("appoint"))
        mins = int(meta.get("late") or 0)
        extra = {"min": str(mins), "what": (x or {}).get("label", "")}
        if not x or x["status"] not in ("set", "waiting"):
            return "appoint_late_gone", {}, extra
        p = st["params"]
        sent = float(meta.get("sent") or (x.get("late_note") or {}).get("at") or now)
        before = (x["t"] - sent) / 60.0
        notice = 0.0 if before >= 60 else 0.1 if before >= 15 else 0.25 if before >= 0 else 0.4 + min(0.3, -before / 100.0)
        amount = min(0.5, mins / 120.0)
        punct = (float(app.traits(char).get("punctual", 0.75)) - 0.75) * 0.8
        again = 0.2 * max(0, len([t for t in st.get("late_told") or [] if 0 < sent - t < LATE_SPAN]))
        again += 0.25 * max(0, int((x.get("late_note") or {}).get("n", 1)) - 1)      # 同じ約束で伝え直した
        rel = (p.get("affection", 50) - 50) / 120.0 + (p.get("mood", 50) - 50) / 200.0 + 0.15 * app.attach.factor(char, st, "devotion")
        s = notice + amount + punct + again - rel + random.uniform(-0.15, 0.15)
        plan = x.setdefault("plan", {})
        her = int(plan.get("late", 0))
        app.trace.add("appoint", "遅れると言われた", x["cid"], now, appoint=x["id"], score=round(s, 2), her_late=her, mins=mins)
        if plan.get("noshow"):                   # もともと来ないつもりだった: 返事は当たり障りなく
            return "appoint_late_fine", {}, extra
        if her and her >= mins - 5:              # 相手も遅れそうだった: お互いさま
            plan["told"] = True                  # 自分も遅れると, ここで伝えた (あとから改めて連絡しない)
            self.save()
            return "appoint_late_also", {}, extra
        go = int(plan.get("go", 0))
        if x["status"] == "set" and now < x["t"] - go * 60 - 600 and s < 0.45 and random.random() < 0.6:
            plan["late"] = max(her, int(mins * random.uniform(0.6, 1.0)))       # まだ出ていない: 合わせてゆっくり来る
            self.save()
            return "appoint_late_adjust", {}, extra
        if s < 0.2:
            return "appoint_late_fine", {}, extra
        if s < 0.5:
            return "appoint_late_sad", {"mood": -1}, extra
        return "appoint_late_sour", {"mood": -2}, extra

    # ------------------------------------------------------------------ 相手が遅れる (相手からの連絡・「今どこ？」)
    @staticmethod
    def _her_side(x):
        """相手が約束の場所へ出向くか (相手の家での約束は, 相手は家にいる)."""
        return not x.get("plants") and not (places_mod.is_home(x["place"]) and x["place"] != places_mod.HOME_ME)

    @staticmethod
    def her_eta(x):
        """相手の当日の動き: (着く時刻, 家を出る時刻). 見えない値 (plan) から."""
        plan = x.get("plan") or {}
        come = x["t"] + (int(plan.get("late", 0)) - int(plan.get("early", 0))) * 60      # 早く着く (A41) は前へ
        return come, come - int(plan.get("go", 0)) * 60

    @staticmethod
    def _guess(mins):
        """相手が言う「◯分くらい」: 5 分きざみで, 少し甘く見積もる (言ったより遅れることもある)."""
        return max(5, int(round(mins * random.uniform(0.7, 1.0) / 5.0)) * 5)

    def _her_late_tell(self, x, char, st, now):
        """相手が遅れる (10 分以上) とき, 連絡してくるか (一度だけ決める). 時間にきっちりな性格ほど・献身的なほど・仲がいいほど連絡してくる.
        連絡の時期は理由で変わる (A41): 支度 slow は本来出る時刻のころ / 電車・道の遅れ traffic は向かう途中で / 寝坊 oversleep は
        起きてから (遅く. 出る時刻を過ぎてから). 電話のこともある (出なければメッセージ). 連絡したら, その知らせの文を返す."""
        plan = x.setdefault("plan", {})
        if "told" in plan or plan.get("noshow") or int(plan.get("late", 0)) < 10 or not self._her_side(x)                 or x.get("ask_now") or x["status"] not in ("set", "waiting") or self.app.bonds.together(x["cid"]):
            return None
        go = int(plan.get("go", 0))
        why = plan.get("late_why") or "slow"
        jit = plan.setdefault("tell_jit", random.randint(0, 10)) * 60
        come, leave = self.her_eta(x)
        if why == "traffic":                      # 乗ってから・走り出してから遅れに気づく
            send = leave + max(5 * 60, go * 60 * 0.4) + jit
        elif why == "oversleep":                  # 起きたときには, もう出る時刻を過ぎている
            send = leave - 5 * 60 + jit
        else:
            send = x["t"] - max(go, 10) * 60 - jit
        send = max(float(x.get("made", 0)), min(send, come - 5 * 60))
        if now < send:
            return None
        punct = float(self.app.traits(char).get("punctual", 0.75))
        p = st["params"]
        ch = -0.2 + 1.1 * punct + 0.2 * self.app.attach.factor(char, st, "devotion") + (p.get("affection", 50) - 50) / 250.0
        plan["told"] = random.random() < min(0.95, max(0.05, ch))
        self.app.trace.add("appoint", "遅れる相手が連絡するか", x["cid"], now, appoint=x["id"], late=plan.get("late"), chance=round(ch, 2),
                           told=plan["told"], why=why)
        if not plan["told"]:
            self.save()                           # 黙って遅れる (決めたことを残す)
            return None
        mins = self._guess(int(plan["late"]))
        plan["told_min"] = mins
        self.save()
        self._tell(char, st, x, HER_LATE_KEY.get(why, "appoint_her_late"), {"min": str(mins), "place": self.app.places.label(x["place"])},
                   min(now, send), kind="appoint_her_late", phone=now - send < 120)      # 閉じていた間の分は, その時刻のメッセージで
        return "%sから、%d分くらい遅れそうと連絡が来た" % (char.get("name", ""), mins)

    def _her_notes(self, x, char, st, now):
        """相手の側の短い知らせ (A41): 早く着いて「着いちゃった」/ 遅れていて, 着く直前に「もうすぐ着く」. どちらも一度だけ, ときどき."""
        plan = x.get("plan") or {}
        if x["status"] not in ("set", "waiting") or plan.get("noshow") or not self._her_side(x) or x.get("ask_now")                 or self.app.bonds.together(x["cid"]):
            return None
        come, _ = self.her_eta(x)
        app = self.app
        punct = float(app.traits(char).get("punctual", 0.75))
        if plan.get("early") and "early_sent" not in plan and come <= now < x["t"]:
            plan["early_sent"] = not self.here(x["place"], now) and random.random() < 0.3 + 0.4 * punct
            self.save()
            if plan["early_sent"]:
                app.chat.add(x["cid"], "her", app.chat.line(char, "appoint_her_early", {"place": app.places.label(x["place"])}),
                             kind="appoint_her_early", t=now, appoint=x["id"])
                app.picked_up_phone(char, st, now)
                app.save_state(x["cid"])
                return "%sから、もう着いたと連絡が来た" % char.get("name", "")
        if plan.get("told") and int(plan.get("late", 0)) >= 15 and "near_sent" not in plan and come - 6 * 60 <= now < come:
            plan["near_sent"] = random.random() < 0.2 + 0.4 * punct
            self.save()
            if plan["near_sent"]:
                app.chat.add(x["cid"], "her", app.chat.line(char, "appoint_her_near", {"place": app.places.label(x["place"])}),
                             kind="appoint_her_near", t=now, appoint=x["id"])
                app.picked_up_phone(char, st, now)
                app.save_state(x["cid"])
                return "%sから、もうすぐ着くと連絡が来た" % char.get("name", "")
        return None

    WHERE_BEFORE = 30 * 60      # 約束のこれだけ前から「今どこ？」を聞ける

    def where_target(self, cid, now=None):
        """「今どこ？」を聞ける約束 (相手が出向いてくる決まった約束で, 30 分前〜待ってくれる時刻まで). 無ければ None."""
        now = now or time.time()
        hit = [x for x in self.all() if x["cid"] == cid and x["status"] in ("set", "waiting") and self._her_side(x)
               and not x.get("ask_now") and x["t"] - self.WHERE_BEFORE <= now <= self.grace(x)]
        return min(hit, key=lambda x: x["t"]) if hit else None

    def where_why(self, cid, now=None):
        if self.app.bonds.together(cid):
            return "いまはそばにいます"
        return "" if self.where_target(cid, now) else "待ち合わせの前後に聞けます（約束の 30 分前から）"

    def where_reply(self, char, st, meta, now):
        """「今どこ？」への返事 (読んだときの相手の様子で). (セリフの場面, 効果, 置き換え).
        向かっている (時間どおり / 遅れて) / まだ出ていない (間に合う / 遅れる) / もう着いている / 来るつもりがなかった (行けないと言う)."""
        app = self.app
        x = self.find(meta.get("appoint"))
        if not x or x["status"] not in ("set", "waiting"):
            return "appoint_where_gone", {}, {}
        plan = x.setdefault("plan", {})
        extra = {"place": app.places.label(x["place"]), "min": "5"}
        x["where_n"] = int(x.get("where_n", 0)) + 1
        self.save()
        if plan.get("noshow"):                   # 来るつもりがなかった (忘れていた・気が向かない): 聞かれて, 行けないと言う
            x["status"] = "cancelled"
            self.her_moved(x["cid"], now)
            self.save()
            app.chat.add(x["cid"], "sys", "📅 約束はなくなった（%sは来られない）" % char.get("name", ""), kind="promise", t=now + 0.001)
            app.trace.add("appoint", "今どこ？で, 来ないと分かった", x["cid"], now, appoint=x["id"])
            return "appoint_where_cant", {}, extra
        come, leave = self.her_eta(x)
        late = come - x["t"] >= 5 * 60
        if late:
            plan["told"] = True                  # ここで遅れると伝わった (あとから改めて連絡しない)
            self.save()
        if now >= come:
            return "appoint_where_here", {}, extra
        if x["where_n"] >= 3 and not late:       # 遅れてもいないのに, 何度も聞かれる
            return "appoint_where_much", {"mood": -2}, extra
        extra["min"] = str(self._guess((come - now) / 60.0) if now >= leave else self._guess((come - x["t"]) / 60.0))
        if now >= leave:
            return ("appoint_where_coming_late" if late else "appoint_where_coming"), {}, extra
        return ("appoint_where_notyet" if late else "appoint_where_soon"), {}, extra

    def _late_cost(self, x, arrived):
        """遅れて着いたときの機嫌の下がりと理由: 伝えた見込みのうちなら軽い. (効果, 理由の文, 見立ての倍率)."""
        n = x.get("late_note")
        if n and arrived <= float(n.get("by", 0)) + LATE_KEPT:
            return {"mood": -1}, "%sが約束に遅れてきた（連絡はあった）", 0.75
        if n:
            return {"mood": -3}, "%sが、伝えてきたよりさらに遅れてきた", 0.5
        return {"mood": -3}, "%sが約束に遅れてきた", 0.5

    # ------------------------------------------------------------------ 当日
    def due_at(self, place, now=None):
        """その行き先での, 近いうちの約束 (相手の家へ出かけるときに, 約束なしの訪問と区別する)."""
        now = now or time.time()
        return next((x for x in self.all() if x["status"] in ("set", "waiting") and x["place"] == place
                     and x["t"] - NEAR <= now <= self.grace(x)), None)

    def here(self, place, now=None):
        """あなたがいま, その約束の場所にいるか (外出の行き先 / あなたの家なら家にいる)."""
        app = self.app
        p = app.presence.rec()
        mode = p.get("mode")
        w = app.bonds.with_rec()
        if place == places_mod.HOME_ME:
            return app.activity.home_free(now)
        return mode == "out" and (p.get("place") or "town") == place and not w and not p.get("travel")     # 移動中はまだ着いていない

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
        if app.stay_home():
            raise ValueError(app.stay_home())
        pres = app.presence.rec()
        frm = app.geo.where(now)
        if pres.get("mode") == "out":          # 一人で出かけていたなら, そこから向かう (結果は残す)
            if pres.get("travel"):             # 移動の途中なら, いまの地点から
                frm = app.geo.cut(now)
            ll = app.presence.back(now)
            if ll:
                app.solo.finish(ll)
        r = app.solo.start("out", place=x["place"], frm=frm)
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
        if at and x.get("ask_now") and x["status"] in ("set", "waiting"):     # 今から家に (A25): 着いたら, すぐ迎えてくれる
            x.setdefault("arrived", now)
            r = self._meet(x, now, now - x["t"] > NOW_LATE_ME)
            out.append(self.meet_text(r) or "%sの家に着いた" % char.get("name", ""))
            return True
        if at and "arrived" not in x:
            x["arrived"] = now                    # 着いた時刻 (早く着いていれば, 約束の時刻より前)
            if now < x["t"]:                      # 早く着いた: 時刻になれば会える (それまで画面は変わらないので, 待つことを知らせる)
                out.append("%sに着いた。約束の%sまで、ここで待つ（時間になれば%sと会える）" % (
                    app.places.label(x["place"]), datetime.fromtimestamp(x["t"]).strftime("%H:%M"), char.get("name", "")))
                return True
        elif not at and now < x["t"]:
            x.pop("arrived", None)                # 時刻の前に離れた: 着いていないことに
        if at and now < x["t"] and not plan.get("noshow") and int(plan.get("early", 0)) and now >= self.her_eta(x)[0]:
            r = self._meet(x, now, False)        # 二人とも早く着いた: 時刻を待たずに会える (A41)
            out.append(self.meet_text(r) or "%sと会えた" % char.get("name", ""))
            return True
        if now < x["t"]:
            return False
        arrived = x.get("arrived")
        if plan.get("noshow"):
            if at and now >= max(x["t"], arrived) + GIVE_UP:       # 待ったが来なかった
                x["status"] = "stood_up"
                self.her_moved(x["cid"], now)
                x["sorry_at"] = now + random.uniform(30, 180) * 60
                text = "%sで待っていたが、%sは来なかった" % (app.places.label(x["place"]), char.get("name", ""))
                app.outdoor.note(text, now)
                app.solo.note("out", text, now)
                out.append(text)
                return True
            if not arrived and now > self.grace(x):
                x["status"] = "missed"            # 二人とも来なかった (相手は気にしない)
                return True
            return False
        come = x["t"] + plan.get("late", 0) * 60
        if at and now >= come:
            r = self._meet(x, now, arrived - x["t"] > LATE_ME)
            out.append(self.meet_text(r) or "%sと会えた" % char.get("name", ""))
            return True
        if at and x["status"] == "set":
            x["status"] = "waiting"               # 着いた. 相手はまだ
            out.append("%sに着いた。%sはまだ来ていない" % (app.places.label(x["place"]), char.get("name", "")))
            return True
        if not at and x["status"] == "waiting":
            x["status"] = "set"                   # 待つのをやめて離れた
        if now > self.grace(x):                  # 約束の時刻を過ぎても, その場所にいなかった
            x["status"] = "missed"
            st = app.state(x["cid"])
            fav = bool(x.get("favor"))            # 頼まれごと: 当てにしていたので, 普段の約束より重い
            nw = bool(x.get("ask_now"))           # 今から家に (A25): いいと言ったのに来なかった. 約束のすっぽかしより軽い
            with app.lock:
                d = app.apply_effects(st, app.trait_effects(char, {"mood": -12, "trust": -8, "affection": -3} if fav
                                                            else NOW_MISSED if nw else {"mood": -8, "trust": -4, "affection": -2}))
                app.life.add_reason(st, "player", "bad", ("当てにしていたのに、%sが%sに来なかった" % (app.pronouns(char)[2], x.get("label", ""))
                                                          if fav else "来ると言っていたのに、%sが来なかった" % app.pronouns(char)[2] if nw
                                                          else "%sが遅れると言っていたのに、来なかった" % app.pronouns(char)[2] if x.get("late_note")
                                                          else "%sが約束をすっぽかした" % app.pronouns(char)[2]), now,
                                    told=True, delta=d.get("mood", 0), action="_appoint")
                app.regard.sign(char, st, "missed_favor" if fav else "missed", now, k=0.6 if nw else 1.0)
                mk = "favor_missed" if fav else "visit_now_missed" if nw else "appoint_missed"
                app.chat.add(x["cid"], "her", app.chat.line(char, mk, {"what": x.get("label", "")}), kind=mk, t=self.grace(x))
                app.save_state(x["cid"])
                self._favor_drop(x)
            out.append("%sとの約束（%s）に行かなかった" % (char.get("name", ""), fmt_when(x["t"], now)))
            return True
        return False

    @staticmethod
    def meet_text(r):
        """会えたときの知らせ (画面のトースト): 前置きの注 (「（〇〇は 16 分ほど遅れて来た）」など) と, 相手の最初のひとこと.
        以前は最初の行だけで, 注が付くと相手のひとことが見えなかった."""
        lines = [ln for ln in ((r.get("entry") or {}).get("text") or "").split("\n") if ln.strip()]
        notes = [ln for ln in lines if ln.startswith("（") and ln.endswith("）")]
        said = next((ln for ln in lines if ln not in notes), "")
        return " ".join(notes + ([said] if said else []))

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
        app.regard.sign(char, app.state(cid), "kept", now, k=self._late_cost(x, x.get("arrived") or now)[2] if me_late else 1.0)
        self.save()
        if x.get("favor"):
            return self._favor_meet(x, now, me_late, extra_opts or {})
        if x.get("help"):                         # あなたが頼んだ手伝いに来てくれた (core/askhelp.py)
            if (extra_opts or {}).get("auto_weak"):
                return {"status": "met", "entry": {"text": app.askhelp.auto(x, now)}}
            return {"status": "met", "entry": app.askhelp.arrive(x, now)}
        if x.get("care"):                         # 看病に呼ばれて来た (core/care.py)
            if (extra_opts or {}).get("auto_weak"):
                return {"status": "met", "entry": {"text": "%sの看病に行った" % char.get("name", "")}}
            return {"status": "met", "entry": app.care.arrive(cid, x, now)}
        opts = dict({"appointment": x["id"]}, **(extra_opts or {}))
        if x["place"] in places_mod.PLACES:
            opts["place"] = x["place"]
        r = app.act(x["do"], cid, opts=opts)
        if r.get("entry") and x["place"] in places_mod.PLACES:
            self.remember(cid, x["place"], (r["entry"].get("deltas") or {}).get("mood", 0))
        notes = []
        if late:
            notes.append("（%sは%d分ほど遅れて来た%s）" % (char.get("name", ""), late, "。遅れると連絡はあった" if (x.get("plan") or {}).get("told") else ""))
        if me_late:             # あなたが遅れて行った: 少し機嫌を損ねる (性格しだい. 遅れると伝えて, そのうちに着けば軽い)
            eff, why, _ = self._late_cost(x, x.get("arrived") or now)
            with app.lock:
                st = app.state(cid)
                d = app.apply_effects(st, app.trait_effects(char, eff))
                app.life.add_reason(st, "player", "bad", why % app.pronouns(char)[2], now, told=False,
                                    delta=d.get("mood", 0), action="_appoint")
                app.save_state(cid)
            notes.append("（約束の時間に遅れてしまった%s）" % ("。遅れると伝えてあった" if x.get("late_note") else ""))
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
        """頼まれごとの約束で会えた: 相手の家に来ている状態になる (手伝いは相手の家の画面から始める. core/visit.py).
        閉じていた間 (auto_weak) なら, その場でひと通り済ませる."""
        app = self.app
        cid = x["cid"]
        char = app.chars[cid]
        f = app.earn.favor(x.get("favor"))
        if not f:
            return {"status": "met", "entry": None, "text": "%sの家に行ったが、頼まれごとはもう済んでいた" % char.get("name", "")}
        if me_late:
            eff, why, _ = self._late_cost(x, x.get("arrived") or now)
            with app.lock:
                st = app.state(cid)
                d = app.apply_effects(st, app.trait_effects(char, eff))
                app.life.add_reason(st, "player", "bad", why.replace("約束に", f["label"] + "に") % app.pronouns(char)[2], now, told=False,
                                    delta=d.get("mood", 0), action="_appoint")
                app.save_state(cid)
        if opts.get("auto_weak"):
            _, text = app.earn.favor_done(f, f["h"], now + f["h"] * 3600)
            app.life.save_player()
            return {"status": "met", "entry": {"text": text}}
        # 相手の家に来ている状態になる. 手伝いは, 相手の家の画面の「始める」で (core/visit.py)
        app.athome.favor_arrive(cid, f, now)
        st = app.state(cid)
        e = app.note_entry(char, st, now, "_favor_arrive", "家に着いた", "🏠",
                           "（%sの家に着いた。%sを頼まれている%s）" % (char.get("name", ""), f["label"],
                                                          "。約束に遅れてしまった" if me_late else ""))
        return {"status": "met", "entry": e}

    def live(self, now=None, contact_only=False):
        """画面を開いている間 (state_view のたび). 期限・キャンセル・遅れて来た相手・相手からの誘い・すっぽかしを進める.
        何か起きたら [テキスト] を返す.
        contact_only: 家の画面を閉じている間の進行 (core/remote.py) から. 相手からの連絡 (誘い・急な誘い・日を変えたい・取りやめ・
        すっぽかしのあとの謝り・看病の呼び出し) だけを進める. あなたの側に関わる判定 (着いた・会えた・遅刻・すっぽかし・
        返事の期限切れ・水やり) は進めない: 今までどおり, 家の画面を開いたとき (閉じていた間のまとめと, ここ)."""
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
                if now > x["until"] and not contact_only:                  # 留守のあいだに水やりに行かなかった: 枯れてがっかり
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
            if x.get("relife"):                       # 暮らし方が変わって, 都合がつかなくなった約束 (relife_mark)
                if x["status"] not in ("set", "offered") or now >= x["t"] - RELIFE_NEAR:
                    x.pop("relife", None)             # 着いて待っている・もう直前: 打診しない (そのまま来る)
                    changed = True
                elif now >= x["relife"]:
                    sc = app.scene_at(char, st, datetime.fromtimestamp(now))
                    if x["t"] - now < RELIFE_SOON or not (sc["asleep"] or sc["away"] or sc["busy"]):
                        self._relife_send(x, char, st, now, out)      # 送るのは, 相手が起きていて手が空いているとき
                        changed = True
                        continue
            told = self._her_late_tell(x, char, st, now) or self._her_notes(x, char, st, now)   # 相手からの連絡なので, 閉じていても
            if told:
                out.append(told)
                changed = True
            # 今から家に (A25) の返事待ちは, 着く見込みの時刻ではなく, 聞いてからの長さで流れる (返事は遅れて届くことがある)
            if x["status"] in ("asked", "offered") and (now - x["made"] > 24 * 3600 or (now > x["t"] and not x.get("ask_now"))
                                                        or (x.get("ask_now") and now - x["made"] > NOW_STALE + 3600)):
                if contact_only:
                    continue
                if x["status"] == "offered" and x.get("favor"):     # 頼まれごとの返事を放っておいた: ほかの人に頼んで済んでしまう
                    app.apply_effects(st, app.trait_effects(char, {"trust": -1}))
                    app.chat.add(cid, "her", app.chat.line(char, "favor_lapsed", {"what": x.get("label", "")}), kind="favor_lapsed", t=now)
                    app.save_state(cid)
                    self._favor_drop(x)
                elif x["status"] == "offered":          # 誘ったのに返事がなかった (急な誘いなら, 少しだけ)
                    app.apply_effects(st, app.trait_effects(char, {"mood": -2, "loneliness": 3} if x.get("care") else
                                                            {"mood": -1, "loneliness": 2} if x.get("now") else {"mood": -3, "loneliness": 4}))
                    app.save_state(cid)
                elif x.get("favor"):
                    self._favor_drop(x)
                x["status"] = "lapsed"
                changed = True
            elif x["status"] == "set":
                if contact_only and now >= x["t"] - EARLY:
                    continue                               # もう約束の時刻のまわり: 開いたときの判定に任せる
                plan = x.setdefault("plan", {})
                if x.get("favor") and not plan.get("cancel_checked") and now >= x["t"] - 3 * 3600:
                    plan["cancel_checked"] = True
                    changed = True
                    if random.random() < FAVOR_RESCHED and not x.get("fixed"):       # 相手の都合で, 日がずれる / 取りやめになる
                        alt = self._alt_time(char, x, now) if random.random() < 0.6 else None
                        if alt:
                            x.update(t=alt, status="offered", made=now, ask=False)
                            self.her_moved(cid, now)
                            app.chat.add(cid, "her", app.chat.line(char, "favor_resched", {"what": x.get("label", ""), "when": fmt_when(alt, now)}),
                                         kind="favor_resched", t=now, appoint=x["id"])
                            out.append("%sから、%sの日をずらしたいと連絡が来た" % (char.get("name", ""), x.get("label", "")))
                        else:
                            x["status"] = "cancelled"
                            self.her_moved(cid, now)
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
                        x["her_chg"] = {"old": {"t": x["t"], "place": x["place"], "do": x["do"]}, "kind": "day", "why": "own"}
                        x.update(t=alt, status="offered", made=now, by="her", rounds=int(x.get("rounds", 0)) + 1)
                        self.her_moved(cid, now)
                        self.her_note(st, now)
                        app.chat.add(cid, "her", app.chat.line(char, "appoint_move_mine", {"when": fmt_when(alt, now)}),
                                     kind="appoint_move_mine", t=now, appoint=x["id"])
                        app.picked_up_phone(char, st, now)
                        app.save_state(cid)
                        app.trace.add("appoint", "自分の都合で日を動かしたいと言ってきた", cid, now, appoint=x["id"], new_t=alt)
                        out.append("%sから、約束の日を変えたいと連絡が来た" % char.get("name", ""))
                        continue
                if plan.get("chg_at") and not x.get("favor") and now >= plan["chg_at"]:
                    plan.pop("chg_at")                     # 誰でもまれに: 時刻・場所・することを変えたいと言ってくる (A41)
                    changed = True
                    if not app.bonds.together(cid) and self._her_change(x, char, st, now, out):
                        continue
                if not plan.get("cancel_checked") and now >= x["t"] - 3 * 3600:
                    plan["cancel_checked"] = True          # 直前の取りやめ (体調・急用・仕事・家のこと・気分・天気. A41) を決める
                    changed = True
                    self._drop_plan(x, char, st, now)
                dr = plan.get("drop")
                if dr and now >= dr["at"] and not app.bonds.together(cid):
                    plan.pop("drop")
                    changed = True
                    if self._drop_send(x, char, st, dr, now, out):
                        continue
                if not contact_only:
                    changed = self._tick(x, now, out) or changed
            elif x["status"] == "waiting":
                if not contact_only:
                    changed = self._tick(x, now, out) or changed
            elif x["status"] == "stood_up" and now >= x.get("sorry_at", 9e18):
                x.pop("sorry_at", None)
                changed = True
                if random.random() < 0.3 + st["params"].get("trust", 40) / 150.0:      # 謝ってくるかは, 人しだい
                    app.chat.add(cid, "her", app.chat.line(char, "appoint_sorry", {}), kind="appoint_sorry", t=now)
                    st["appoint_sorry"] = now              # 許すかどうか (言い争いのあとの謝罪と同じく, 答えを待つ)
                    app.save_state(cid)
        last = app.presence.rec().get("appoint_check") or now
        app.presence.rec()["appoint_check"] = now
        h = min(max(now - last, 0), 600) / 3600.0
        if h:
            for cid in list(app.chars):
                if self._maybe_invite(cid, now, h):
                    out.append("%sから誘いのメッセージが来た" % app.chars[cid].get("name", ""))
                elif self._maybe_now(cid, now, h):
                    out.append("%sから「これから会わない？」とメッセージが来た" % app.chars[cid].get("name", ""))
        for cid in list(app.chars):
            if app.care.live_call(cid, now):          # 風邪で寝込んで, 看病に呼ぶ
                out.append("%sから、具合が悪いとメッセージが来た" % app.chars[cid].get("name", ""))
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
        due = st in ("set", "waiting") and x["t"] - EARLY <= now <= self.grace(x)
        return {"here": st in ("set", "waiting") and self.here(x["place"], now),
                "home_me": x["place"] == places_mod.HOME_ME, "remain": int(x["t"] - now), "id": x["id"], "cid": x["cid"],
                "name": app.chars[x["cid"]].get("name", "") if x["cid"] in app.chars else "", "t": x["t"],
                "when": fmt_when(x["t"], now), "place": x["place"], "place_label": app.places.label(x["place"]),
                "do": x.get("do"), "do_label": (x.get("label") if x.get("favor") else "%sを手伝ってもらう" % x.get("label", "") if x.get("help")
                                                else app.action(x.get("do")).get("name", x.get("do"))),
                "by": x.get("by", "me"), "status": st,
                "status_label": "変えたいと伝えた（返事待ち）" if x.get("change") else self.favor_status(x, now) if x.get("favor")
                else STATUS_LABEL.get(st, st), "due": due,
                # こちらから 変えたい / 取りやめる (決まった約束. 着いて待っているとき・時刻を過ぎたら, できない)
                "changing": bool(x.get("change")), "can_cancel": st == "set" and now < x["t"],
                "can_change": st == "set" and now < x["t"] and not x.get("change")
                and not (x.get("now") or x.get("care") or x.get("fixed") or x.get("plants")),
                "favor": bool(x.get("favor")), "fixed": bool(x.get("fixed")), "ask": bool(x.get("ask")),
                "plants": bool(x.get("plants")), "until": x.get("until"),
                "when_label": self.when_of(x, now), "leave": self.leave_by(x, now) if st in ("set", "waiting") else None}

    def leave_by(self, x, now=None):
        """何時に出れば間に合うか (いまいる場所から. 電車・バスなら待ちも見込む). あなたの家なら None."""
        if x["place"] == places_mod.HOME_ME:
            return None
        app = self.app
        try:
            o = app.geo.options(app.geo.where(now), x["place"], x["t"] - 3600)
        except Exception:  # noqa: BLE001 - 目安なので
            return None
        how = o["best"]
        if how == "transit":                      # 電車・バス: 時刻表で, 間に合ういちばん遅い出発 (5 分の余裕)
            hit = app.geo.latest_departure(app.geo.where(now), x["place"], x["t"] - 300)
            if hit:
                t = hit[0]
                return {"t": t, "label": datetime.fromtimestamp(t).strftime("%H:%M"), "min": int(round((x["t"] - t) / 60)), "how": how}
        m = (o["transit"] or {}).get("min", 0) + 5 if how == "transit" else o["walk"]["min"]
        if not m:
            return None
        t = x["t"] - m * 60
        return {"t": t, "label": datetime.fromtimestamp(t).strftime("%H:%M"), "min": int(m), "how": how}
