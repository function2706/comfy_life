"""疑似生活シミュレーション本体.

- リアル時刻でパラメータを進める (5 分刻みで追いつき計算)
- スケジュール / 行動による一時シーン (override) から現在の場面を決める
- 行動 → 反応選択 → 効果適用 → プロンプト合成 → ComfyUI ジョブ
"""
import glob
import hashlib
import json
import math
import os
import queue
import random
import re
import shutil
import threading
import time
import traceback
import uuid
from datetime import datetime

from . import bonds as bonds_mod
from . import encounters as encounters_mod
from . import solo as solo_mod
from . import outdoor as outdoor_mod
from . import street as street_mod
from . import offline as offline_mod
from . import items as items_mod
from . import chat as chat_mod
from . import home as home_mod
from . import places as places_mod
from . import appoint as appoint_mod
from . import kakeibo as kakeibo_mod
from . import body as body_mod
from . import presence as presence_mod
from . import knowsched as knowsched_mod
from . import market as market_mod
from . import earn as earn_mod
from . import rumor as rumor_mod
from . import wardrobe as wardrobe_mod
from . import posing as posing_mod
from . import planner as planner_mod
from . import manners as manners_mod
from . import calview as calview_mod
from . import trace as trace_mod
from . import debugdump as debugdump_mod
from . import comfy, cond, games, life, llm, puzzles, store, transfer
from . import keys as keys_mod
from .keys import line_keys

STEP_SEC = 300
MAX_CATCHUP_SEC = 14 * 24 * 3600
DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_JA = "月火水木金土日"
FLOORED = ("affection", "trust")          # 時間の経過だけでは cool_floor より下がらないパラメータ
LOG_KEEP_IN_VIEW = 60
SEASONS = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
           6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}
# あなた一人の行動 (コマンド) → 一人の時間の記録の種類
MY_ACTION_KIND = {"work": "work", "_back": "back", "_return": "back", "go_work": "work", "go_out": "out", "go_sleep": "sleep",
                  "go_leave": "leave", "go_busy": "busy"}
# 話しているうちに, 相手の予定をぽろっと聞くことがあるコマンド (knowsched.from_talk)
SCHED_TALK = ("talk", "greet", "ask_mood", "call", "walk", "cafe", "eat_out", "date", "tea", "picnic")
CARE_ACTIONS = ("look", "peek_face", "watch_quietly", "ask_mood", "comfort", "leave_alone")     # 気配りが伸びるコマンド
# 一人の時間の記録 (mylog) の種類 → ログに並べるときの名前と印
MY_KIND_LABEL = {"rest": "休む", "chores": "家事", "practice": "研鑽", "out": "外出", "walk": "散歩", "shopping": "買い物", "cafe": "カフェ",
                 "see": "見て回る", "visit": "訪ねる", "home": "家で", "money": "お金", "diary": "日記", "kakeibo": "家計簿", "meal": "食事", "health": "体調", "busy": "作業", "work": "仕事",
                 "sleep": "寝る", "leave": "席を外す", "back": "戻る", "side_job": "内職", "invest": "株", "offline": "閉じていた間"}
MY_KIND_ICON = {"rest": "🛋", "chores": "🧹", "practice": "📚", "out": "🚶", "walk": "🚶", "shopping": "🛍", "cafe": "☕", "see": "👀",
                "visit": "🚪", "home": "🏠", "money": "💴", "diary": "📓", "kakeibo": "📒", "meal": "🍚", "health": "🤒", "busy": "🖥", "work": "💼", "sleep": "🌙", "leave": "👋",
                "back": "🏠", "side_job": "🧵", "invest": "📈", "offline": "🌙"}
PERSONA_ORDER = ["teinei", "osananajimi", "aneki", "ottori", "ojousama", "kedakai", "tsundere", "sadist", "itazura", "cool", "mukuchi", "jimuteki",
                 "rikejo", "otokomae", "genki", "tenshin", "fushigi", "hitonatsukko", "uchiki", "hikutsu", "byoujaku", "boyish", "amaenbo"]


def hm(s):
    s = str(s).strip()
    if ":" in s:
        h, m = s.split(":", 1)
        return int(h) * 60 + int(m)
    return int(float(s) * 60)


def in_range(mins, frm, to):
    a, b = hm(frm), hm(to)
    if a == b:
        return True
    if a < b:
        return a <= mins < b
    return mins >= a or mins < b


# 予定に睡眠が一つも無いキャラの, 既定の睡眠 (作ったばかりのキャラが一日中起きていることにならないように)
DEFAULT_SLEEP = ("01:00", "07:00")
DEFAULT_SLEEP_SCENE = {"activity": "sleep", "label": "就寝中", "location": "寝室", "asleep": True, "outfit": "pajamas",
                       "pos": "sleeping, lying on bed, closed eyes, bedroom, blanket", "neg": "", "effects": {"energy": 12, "sleepiness": -12}}


def day_match(spec, dt):
    spec = (spec or "all").strip().lower()
    wd = dt.weekday()
    if spec in ("all", "", "*"):
        return True
    if spec == "weekday":
        return wd < 5
    if spec == "weekend":
        return wd >= 5
    return DAY_KEYS[wd] in [x.strip() for x in spec.split(",")]


def split_tags(s):
    """カンマ区切り (括弧内は分割しない) でタグに分ける."""
    out, buf, depth = [], "", 0
    for ch in (s or "").replace("\n", ","):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append(buf)
            buf = ""
        else:
            buf += ch
    out.append(buf)
    return [t.strip() for t in out if t.strip()]


def join_tags(chunks):
    seen, out = set(), []
    for c in chunks:
        for t in split_tags(c):
            k = t.lower()
            if k not in seen:
                seen.add(k)
                out.append(t)
    return ", ".join(out)


class App:
    def __init__(self):
        store.bootstrap()
        self.lock = threading.RLock()
        self.trace = trace_mod.Trace(self)       # 判断の記録 (不具合を報告するときの書き出しのもと. 読めない形で保存)
        self.states, self.logs, self.jobs = {}, {}, {}
        self.jobq = queue.Queue()
        self._icon_tried = set()
        self.logq = queue.Queue()
        threading.Thread(target=self._log_writer, daemon=True, name="log-writer").start()
        prev_hook = threading.excepthook

        def hook(args):              # 裏のスレッドで捕まえきれなかった例外: 時刻つきでログと判断の記録に (書き出しのエラーの欄)
            tb = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)).rstrip()
            self.logq.put("%s [ERROR] スレッド %s: %s\n%s" % (datetime.now().strftime("%m-%d %H:%M:%S"),
                                                            getattr(args.thread, "name", "?"), args.exc_value, tb))
            self.trace.error("スレッド %s" % getattr(args.thread, "name", "?"), "%s: %s" % (args.exc_type.__name__, args.exc_value), tb=tb)
            prev_hook(args)
        threading.excepthook = hook
        self.reload()
        self.games = games.Games(self)
        self.life = life.Life(self)
        self.bonds = bonds_mod.Bonds(self)
        self.encounters = encounters_mod.Encounters(self)
        self.solo = solo_mod.Solo(self)
        self.outdoor = outdoor_mod.Outdoor(self)
        self.knowsched = knowsched_mod.KnowSched(self)
        self.market = market_mod.Market(self)
        self.earn = earn_mod.Earn(self)
        self.rumors = rumor_mod.Rumors(self)
        self.street = street_mod.Street(self)
        self.offline = offline_mod.Offline(self)
        self.items = items_mod.Items(self)
        self.chat = chat_mod.Chat(self)
        self.home = home_mod.Home(self)
        self.places = places_mod.Places(self)
        self.appoint = appoint_mod.Appoint(self)
        self.kakeibo = kakeibo_mod.Kakeibo(self)
        self.body = body_mod.Body(self)
        self.presence = presence_mod.Presence(self)
        self.planner = planner_mod.Planner(self)
        self.manners = manners_mod.Manners(self)
        self.calview = calview_mod.CalView(self)
        self.debugdump = debugdump_mod.DebugDump(self)
        self.tasks = {}          # 内職の作業 (token -> {t0, kind, cid, puzzle}). ワールドの tasks.json にも書く (再起動しても続きから)
        self._tasks_w = None
        self._load_index()
        rt = self.manners.rejudge_thanks()          # 謝ったあとのお礼が以前の判定で「何が？」と返っていたら, 本来の効き目を当て直す
        rc = self.manners.retro_contacts()          # 連絡しすぎの数え方を以前の記録にも遡って効かせる
        self.earn.migrate_favors()             # 以前から頼まれていたものも, 日時のすり合わせで答えられるように
        paid = self.offline.retro_missed_work()        # 以前の取りこぼし (予定を組んでいない日の仕事) を一度だけ払う
        if rt or rc or paid:
            self.trace.add("retro", "起動時の当て直し", thanks=rt, contacts=rc, missed_work=paid)
        self.solo.rewrite_diaries(force=bool(paid))   # 日記の組み立てを直したので, 書き直せる日を一度だけ書き直す (払った日も)
        self._ensure_worker()

    # ------------------------------------------------------------------ config
    def reload(self):
        self.settings = store.load_settings()
        self.params = store.load(store.wpath("params.json"), [])
        self.actions = store.load(store.wpath("actions.json"), [])
        if not hasattr(self, "wardrobe"):
            self.wardrobe = wardrobe_mod.Wardrobe(self)
        self.wardrobe.load()                   # 服の一覧 (全体で 1 つ)
        if not hasattr(self, "posing"):
            self.posing = posing_mod.Posing(self)
        self.posing.load()                     # ポーズ・見せての一覧 (全体で 1 つ)
        self.wardrobe.migrate()                # 以前のキャラごとの wardrobe を一覧へ (済んでいれば何もしない)
        # 既定に増えた項目 (economy など) も使えるよう, 既定の上に data を重ねる
        self.world = store.deep_merge(store.load(os.path.join(store.DEFAULTS, "world.json"), {}),
                                      store.load(store.wpath("world.json"), {}))
        self.chars = store.load_characters()
        self.minigames = store.load(store.wpath("minigames.json"), [])
        self.events = store.load(store.wpath("events.json"), [])
        self.approaches = store.load(store.wpath("approaches.json"), [])
        self.personas = store.load_personas()
        self.relations = store.load(store.wpath("relations.json"), {}) or {}
        if self.settings.get("active_character") not in self.chars and self.chars:
            self.settings["active_character"] = next(iter(self.chars))
        self._migrate()

    def _migrate(self):
        """既存の data/ に, 後から増えた既定項目を補う (ユーザーの編集内容は上書きしない)."""
        self._migrate_living_cost()
        self._migrate_my_entries()
        self._migrate_assets()
        self._sync_defaults("actions", self.actions, "actions.json")
        self._sync_defaults("minigames", self.minigames, "minigames.json")
        self._sync_defaults("events", self.events, "events.json")
        self._sync_defaults("approaches", self.approaches, "approaches.json")
        for c in self.chars.values():
            if "outfit_outing" not in c or "clothes" not in c:
                store.backup("キャラの定義に後から増えた項目を補う")      # 定義を書き換える前に (一回の起動で一度だけ)
            if "outfit_outing" not in c:          # お出かけ着
                c["outfit_outing"] = c.get("outfit_default", "")
                store.save_character(c)
            # 以前は性格を選ぶと呼び方をキャラにコピーしていた. プリセットと同じなら「プリセットに従う」(空欄) に戻す
            p = self.personas.get(c.get("persona_id") or "")
            if p and c.get("player_call") and c["player_call"] == p.get("player_call"):
                c["player_call"] = ""
                store.save_character(c)
            if "age" not in c:                    # 年齢 (既定のキャラだけ既定から. ほかは設定で入れるまで空)
                d = store.load(os.path.join(store.DEFAULTS, "characters", c["id"] + ".json")) or {}
                if d.get("age"):
                    c["age"] = d["age"]
                    store.save_character(c)
            if "clothes" not in c:                # 持っている服 (以前の形式は wardrobe.migrate で移してある)
                d = store.load(os.path.join(store.DEFAULTS, "characters", c["id"] + ".json")) or {}
                c["clothes"] = d.get("clothes") or [{"id": i, "from": "default"} for i in wardrobe_mod.STARTER]
                store.save_character(c)

    def _migrate_assets(self):
        """銘柄を店の種類ぶん増やした: 以前の既定の 4 銘柄のまま保存しているワールドに, 新しい既定の銘柄を足す
        (持っている株・値段・ニュースはそのまま. 銘柄を自分で書き換えたワールドは触らない)."""
        f = store.wpath("world.json")
        w = store.load(f, None)
        mine = ((w or {}).get("economy") or {}).get("assets")
        if not mine:
            return
        default = (store.load(os.path.join(store.DEFAULTS, "world.json"), {}) or {}).get("economy", {}).get("assets") or []
        old = {"idx", "food", "tech", "game"}
        ids = {a.get("id") for a in mine}
        if not ids <= old or not [a for a in default if a["id"] not in ids]:
            return
        store.backup("株の銘柄を店の種類ぶん増やす")
        by = {a["id"]: a for a in default}
        w["economy"]["assets"] = [dict(by.get(a["id"], {}), **{k: v for k, v in a.items() if k not in ("drift",)}) for a in mine] \
            + [a for a in default if a["id"] not in ids]
        store.save(f, w)
        self.world = store.deep_merge(store.load(os.path.join(store.DEFAULTS, "world.json"), {}), w)

    def _migrate_my_entries(self):
        """以前の「選んでいるキャラ」のログに書かれていた, あなた一人の行動の記録 (離れている相手のログの「（仕事から帰ってきた。…）」
        など) を, あなたの記録 (mylog) へ移す. 外で会っていた相手と別れたところ (「〇〇と別れて、…」) は, その人との記録として残す.
        一度だけ (player.json の migrated.my_entries). 移す前に自動バックアップ."""
        pf = store.wpath("player.json")
        ps = store.load(pf, None)
        if ps is None or (ps.get("migrated") or {}).get("my_entries"):
            return
        mine_ids = set(bonds_mod.APART_TEXT) | {a["id"] for a in self.actions if a.get("category") == "あなたの予定"}
        moved = []
        for cid in self.chars:
            f = store.wpath("log", cid + ".json")
            log = store.load(f, None)
            if not log:
                continue
            keep = []
            for e in log:
                t = e.get("text") or ""
                if e.get("action") in mine_ids and t.startswith("（") and t.endswith("）") and "と別れて" not in t \
                        and not e.get("deltas") and not e.get("images"):
                    moved.append(e)
                else:
                    keep.append(e)
            if len(keep) != len(log):
                store.backup("あなた一人の行動の記録を, キャラのログからあなたの記録へ移す")     # 一回の起動で一度だけ
                store.save(f, keep)
                self.logs.pop(cid, None)
        if moved:
            mylog = store.load(store.wpath("mylog.json"), []) or []
            for e in moved:
                mylog.append({"t": e["t"], "kind": MY_ACTION_KIND.get(e.get("action"), "home"), "text": e["text"].strip("（）"),
                              "id": "m" + e["id"], "icon": e.get("icon") or "🧍", "name": e.get("action_name") or "",
                              **({"money": {"p": e["money"]["p"]}} if (e.get("money") or {}).get("p") else {}),
                              **({"skill": e["skill"]} if e.get("skill") else {}), "migrated": True})
            mylog.sort(key=lambda x: x["t"])
            store.save(store.wpath("mylog.json"), mylog[-500:])
        ps.setdefault("migrated", {})["my_entries"] = len(moved)
        store.save(pf, ps)
        if getattr(self, "life", None) is not None and self.life.player is not None:
            self.life.player.setdefault("migrated", {})["my_entries"] = len(moved)

    def _migrate_living_cost(self):
        """食事 (自炊・外食・買って食べる) を足したので, 以前の既定の生活費 (食費込みの 3,000 円) を食費抜きの既定に直す.
        自分で変えていた額はそのまま. 一度だけ (economy.living_cost_no_food)."""
        f = store.wpath("world.json")
        w = store.load(f, {}) or {}
        eco = w.get("economy") or {}
        if eco.get("living_cost_no_food"):
            return
        new = (store.load(os.path.join(store.DEFAULTS, "world.json"), {}) or {}).get("economy", {}).get("living_cost_per_day", 1200)
        if int(eco.get("living_cost_per_day", 3000)) == 3000:
            store.backup("生活費から食費を外す (食事を足したため)")
            eco["living_cost_per_day"] = new
        eco["living_cost_no_food"] = True
        w["economy"] = eco
        store.save(f, w)
        self.world = store.deep_merge(store.load(os.path.join(store.DEFAULTS, "world.json"), {}), w)

    def _sync_defaults(self, kind, items, fname):
        """data/ の項目を既定に追従させる.
        - 過去の既定と完全に同じ (=未編集) 項目は最新の既定に更新する. 手を加えたものは触らない
        - 新しく増えた既定項目を, 既定での並び位置に近いところへ追加する (ユーザーが消したものは戻さない)"""
        defaults = store.load(os.path.join(store.DEFAULTS, fname), [])
        hist = (store.load(os.path.join(store.DEFAULTS, "default_history.json"), {}) or {}).get(kind, {})
        dmap = {d["id"]: d for d in defaults}
        updated = []
        for i, it in enumerate(items):
            d = dmap.get(it.get("id"))
            if d is None:
                continue
            h = store.obj_hash(it)
            if h != store.obj_hash(d) and h in hist.get(it["id"], []):
                items[i] = json.loads(json.dumps(d))
                updated.append(it["id"])
        have = [it.get("id") for it in items]
        key = "seen_" + kind
        seen = set(self.settings.get(key) or []) or set(have)
        added = []
        for pos, d in enumerate(defaults):
            if d["id"] in have or d["id"] in seen:
                continue
            prev = next((defaults[j]["id"] for j in range(pos - 1, -1, -1) if defaults[j]["id"] in have), None)
            at = have.index(prev) + 1 if prev else len(items)
            items.insert(at, json.loads(json.dumps(d)))
            have.insert(at, d["id"])
            added.append(d["id"])
        if updated or added:
            store.save(store.wpath(fname), items)
            self.logq.put("%s [INFO] 既定の%sを反映: 更新 %d 件 %s / 追加 %d 件 %s" % (
                datetime.now().strftime("%m-%d %H:%M:%S"), kind, len(updated), ",".join(updated),
                len(added), ",".join(added)))
        all_ids = sorted(seen | set(dmap))
        if all_ids != sorted(self.settings.get(key) or []):
            self.settings[key] = all_ids
            store.save_settings(self.settings)

    def char(self, cid=None):
        cid = cid or self.settings.get("active_character")
        c = self.chars.get(cid)
        if not c:
            raise KeyError("キャラクターが見つかりません: %s" % cid)
        return c

    def target(self, cid=None):
        """「誰かと」の相手: いまそばにいる人 (bonds.company) の中から. cid がそばにいればそれ, いなければ最後に選んだ相手,
        それもいなければそばにいる最初の人. 誰もそばにいなければ None (一人)."""
        comp = self.bonds.company()
        if cid in comp:
            return cid
        cur = self.settings.get("active_character")
        return cur if cur in comp else (comp[0] if comp else None)

    def set_target(self, cid):
        """「誰かと」の相手を選ぶ (そばにいる人だけ). 選んだ相手はワールドごとに覚える (local.json の active_character)."""
        if cid not in self.bonds.company():
            raise ValueError("%sはいまそばにいません" % (self.chars.get(cid) or {}).get("name", cid))
        return self.save_settings({"active_character": cid})

    # 同時にはできないこと: いましていること (内職・一人の時間・ミニゲーム) と, 始めようとしていること
    BLOCK_KINDS = ("solo", "side_job", "social", "game", "cook")

    def doing_now(self):
        """いましていること (同時にほかのことを始められない): {kind, label} か None.
        内職の途中 / 休む・家事・研鑽の途中 (家で) / 誰かとミニゲームの途中."""
        if self.task_active():
            return {"kind": "task", "label": "内職"}
        p = self.presence.rec()
        sl = p.get("solo") or {}
        if p.get("mode") == "busy" and sl.get("kind") in solo_mod.KINDS:
            return {"kind": sl["kind"], "label": solo_mod.KINDS[sl["kind"]]["doing"].replace("中", "")}
        for c in self.chars:
            if (self.states.get(c) or {}).get("game"):
                return {"kind": "game", "label": "%sとのミニゲーム" % self.chars[c].get("name", "")}
        return None

    def blocked(self, what):
        """what (solo = 一人の行動 / side_job = 内職 / social = 誰かとすること / game = ミニゲーム / cook = 自炊) を
        いま始められない理由 (押す前に画面に出す). 始められるなら None."""
        d = self.doing_now()
        if not d:
            return None
        if what == "cook" and d["kind"] == "rest":
            return None                         # 休んでいる途中に作って食べるのはかまわない
        if what == "game" and d["kind"] == "game":
            return None                         # 続き
        if d["kind"] == "task":
            return "内職の途中です（先に内職を終えてから）"
        if d["kind"] == "game":
            return "%sの途中です（先に終えてから）" % d["label"]
        return "%sの途中です（先に「%sを終える」で終えてから）" % (d["label"], d["label"])

    def blocked_view(self):
        return {w: self.blocked(w) for w in self.BLOCK_KINDS}

    def you_context(self, dt=None):
        """あなた一人の条件式の値 (誰とも関係しない予定・一人の行動の条件用): 時刻・在席・お金・体力・あなたの情報."""
        dt = dt or datetime.now()
        ctx = {"phase": self.phase_at(dt).get("id", ""), "hour": dt.hour, "time": dt.hour * 60 + dt.minute,
               "weekday": dt.weekday(), "day": DAY_KEYS[dt.weekday()], "weekend": dt.weekday() >= 5,
               "month": dt.month, "season": SEASONS[dt.month], "outing": False, "overriding": False,
               "away": False, "asleep": False, "busy": False, "free": True, "apart": True, "company": len(self.bonds.company())}
        ctx.update(self.life.money_ctx(None))
        ctx.update(self.presence.ctx(dt.timestamp()))
        ctx.update(self.player_ctx())
        ctx["roll"] = random.randint(0, 99)
        return ctx

    def my_entry(self, kind, name, icon, text, now=None, money=None, skill=None):
        """あなた一人の記録 (誰もそばにいないときの行動の結果). 一人の時間の記録 (mylog) に残し, 画面に出す形で返す."""
        now = now or time.time()
        if text.startswith("（") and text.endswith("）"):
            text = text[1:-1]           # 外側の括弧だけ (「…（7,200円）」の閉じ括弧は残す)
        e = self.solo.note(kind, text, now, id=uuid.uuid4().hex[:12], icon=icon, name=name,
                           **({"money": money} if money else {}), **({"skill": skill} if skill else {}))
        return {"entry": self._my_view(e), "job": None, "llm_error": None}

    @staticmethod
    def _my_view(e):
        """一人の時間の記録を, ログの 1 件の形に (あなたの 1 本の時系列に並べる)."""
        return {"id": e.get("id") or "m%d" % int(e["t"] * 1000), "t": e["t"], "who": None, "who_name": "",
                "action": "_my_" + e.get("kind", ""), "action_name": e.get("name") or MY_KIND_LABEL.get(e.get("kind"), "一人の時間"),
                "icon": e.get("icon") or MY_KIND_ICON.get(e.get("kind"), "🧍"), "text": "（%s）" % e.get("text", ""),
                "deltas": {}, "money": e.get("money") or {}, "skill": e.get("skill") or {}, "image": None, "images": [], "mine": True}

    def action(self, aid):
        for a in self.actions:
            if a.get("id") == aid:
                return a
        raise KeyError("行動が見つかりません: %s" % aid)

    def param_def(self, pid):
        for p in self.params:
            if p["id"] == pid:
                return p
        return None

    # ------------------------------------------------------------------ state / log
    def state(self, cid):
        st = self.states.get(cid)
        if st is None:
            st = store.load(store.wpath("state", cid + ".json"))
            if st is None:
                t = time.time()
                st = {"params": {}, "last_tick": t, "last_interaction": t, "override": None,
                      "cooldowns": {}, "created": t}
            self.states[cid] = st
        for p in self.params:
            st["params"].setdefault(p["id"], float(p.get("init", 50)))
        return st

    def save_state(self, cid):
        store.save(store.wpath("state", cid + ".json"), self.states[cid])

    def log(self, cid):
        if cid not in self.logs:
            self.logs[cid] = store.load(store.wpath("log", cid + ".json"), [])
        return self.logs[cid]

    def save_log(self, cid):
        store.save(store.wpath("log", cid + ".json"), self.logs[cid])

    def find_entry(self, cid, eid):
        for e in reversed(self.log(cid)):
            if e["id"] == eid:
                return e
        return None

    # ------------------------------------------------------------------ scene / context
    def _norm_scene(self, e, char, src):
        asleep = bool(e.get("asleep"))
        return {"activity": e.get("activity") or "relax", "label": e.get("label") or "",
                "location": e.get("location") or "", "outfit": e.get("outfit") or "", "outfit_neg": "",
                "pos": e.get("pos", ""), "neg": e.get("neg", ""), "effects": e.get("effects") or {},
                "away": bool(e.get("away")), "asleep": asleep, "busy": bool(e.get("busy")),
                # 服装固定 (着せ替えより優先). 未指定なら睡眠中の場面だけ固定
                "fixed_outfit": bool(e.get("fixed_outfit", asleep)),
                "outing": bool(e.get("outing")),   # 外出 (散歩・お出かけ). 部屋着のままにはしない
                "dress": None, "source": src}

    def wardrobe_item(self, char, oid):
        """その人が持っている服 (服の一覧 + その人用の上書き)."""
        return self.wardrobe.item(char, oid) if oid else None

    def _apply_dress(self, char, st, s, dt=None):
        """着せ替え中なら, 服装固定でない場面の服装を差し替える (ミニゲームの服装が最優先).
        頼まれていなければ, 予定どおりの服 (普段着・お出かけ着) のところは本人が選んだ服のことがある (wardrobe.self_pick)."""
        go = (st.get("game") or {}).get("outfit")
        if go:
            s["outfit"], s["outfit_neg"], s["dress"] = go.get("pos", ""), go.get("neg", ""), go.get("label") or None
            s["remove_tags"] = go.get("remove") or []
            return s
        o = self.wardrobe_item(char, (st.get("dress") or {}).get("id"))
        if o and s["outing"] and not o.get("outing_ok"):
            o = None          # 部屋着・パジャマなどは外に着ていかない (お出かけ着のまま)
        if not o and dt is not None and s.get("plain_outfit") and not s["fixed_outfit"] and not s["asleep"]:
            o = self.wardrobe.self_pick(char, st, dt, outing=s["outing"])
            s["self_picked"] = bool(o)
        if o and not s["fixed_outfit"]:
            s["outfit"], s["outfit_neg"], s["dress"] = o.get("pos", ""), o.get("neg", ""), o.get("name", o["id"])
        return s

    def scheduled_scene(self, char, dt):
        mins = dt.hour * 60 + dt.minute
        sched = char.get("schedule") or []
        for e in sched:
            if day_match(e.get("days"), dt) and in_range(mins, e.get("from", "00:00"), e.get("to", "24:00")):
                s = self._norm_scene(e, char, "schedule")
                break
        else:
            if not any(e.get("asleep") for e in sched) and in_range(mins, *DEFAULT_SLEEP):
                # 予定に睡眠が一つも無い: 誰でも夜は寝ている (一日中起きていることにしない)
                s = self._norm_scene(DEFAULT_SLEEP_SCENE, char, "default_sleep")
            else:
                s = self._norm_scene(char.get("default_activity") or {}, char, "default")
        s["plain_outfit"] = not s["outfit"]       # 予定に服の指定が無い (普段着): 本人が選ぶことがある
        s["outfit"] = s["outfit"] or char.get("outfit_default", "")
        return s

    def scene_at(self, char, st, dt):
        base = self.scheduled_scene(char, dt)
        ov = st.get("override")
        if ov and ov.get("until", 0) > dt.timestamp():
            s = self._norm_scene(ov, char, "override")
            s["plain_outfit"] = s["outfit"] == "@outing" or (not s["outfit"] and (s["outing"] or base.get("plain_outfit")))
            if s["outfit"] == "@outing" or (s["outing"] and not s["outfit"]):
                s["outfit"] = char.get("outfit_outing") or char.get("outfit_default", "")
            s["outfit"] = s["outfit"] or base["outfit"]
            s["until"] = ov["until"]
            return self._apply_dress(char, st, s, dt)
        return self._apply_dress(char, st, base, dt)

    def phase_at(self, dt):
        mins = dt.hour * 60 + dt.minute
        for p in self.world.get("phases") or []:
            if in_range(mins, p.get("from", "00:00"), p.get("to", "24:00")):
                return p
        return {"id": "day", "label": "", "pos": "", "neg": ""}

    def context(self, char, st, dt, scene=None, view=True):
        """条件式の値. view=True ならあなたから見た値 (離れている相手は away=True = そばにいない).
        view=False なら本人の状態のまま (本人のパラメータの動き・出来事に使う. 離れていても自分の予定どおりに過ごしている)."""
        scene = scene or self.scene_at(char, st, dt)
        ctx = {k: round(v, 3) for k, v in st["params"].items()}
        ctx.update({
            "activity": scene["activity"], "location": scene["location"],
            "away": scene["away"], "asleep": scene["asleep"], "busy": scene["busy"],
            "free": not (scene["away"] or scene["asleep"] or scene["busy"]),
            "phase": self.phase_at(dt).get("id", ""), "hour": dt.hour, "time": dt.hour * 60 + dt.minute,
            "weekday": dt.weekday(), "day": DAY_KEYS[dt.weekday()], "weekend": dt.weekday() >= 5,
            "absent": round((dt.timestamp() - st.get("last_interaction", dt.timestamp())) / 3600.0, 2),
            "repeat": 0, "outfit": (st.get("dress") or {}).get("id", ""),
            "outing": scene.get("outing", False),
            # 行動による一時的な過ごし方 (ゲーム・映画・散歩など) の最中か. 寝ているのは除く
            "overriding": scene.get("source") == "override" and not scene["asleep"],
            "month": dt.month, "season": SEASONS[dt.month],
        })
        ctx.update(self.life.money_ctx(st))                    # my_money / her_money / invest_value / profit
        ctx.update(self.life.mood_ctx(st, dt.timestamp()))     # cause / knows / reason / untold / request / away_events
        ctx.update(self.presence.ctx(dt.timestamp()))          # presence / said / left_mode / left_h
        ctx.update(self.bonds.ctx(char["id"], st, dt.timestamp()))   # stage / apart / with_mode / company / living_other / rivals
        if ctx["apart"] and view:
            ctx["away"] = True      # あなたから見れば, そばにいない (free は相手自身の予定のまま = 誘えるか)
        ctx["roll"] = random.randint(0, 99)
        ctx.update(self.player_ctx())                          # player_gender / player_age / player_has_job / player_likes
        ctx["player_sick"] = self.body.level()                 # あなたの体調 (0〜3. そばにいれば顔色で分かる)
        ctx["player_hungry"] = self.body.rec()["satiety"] < 30                    # 反応を確率で分けたいとき用 (例: sk_cook<30, roll<50)
        return ctx

    # ------------------------------------------------------------------ time
    def _clamp(self, p, v):
        return max(float(p.get("min", 0)), min(float(p.get("max", 100)), v))

    def _step(self, char, st, dt, h):
        scene = self.scene_at(char, st, dt)
        if scene["asleep"] and st.get("dress") and char.get("dress_reset_on_sleep", True):
            st["dress"] = None   # 寝たら翌日はスケジュール通りの服に戻る
        ctx = self.context(char, st, dt, scene, view=False)     # 本人の過ごし方で動く (あなたから見えるかとは別)
        vals = st["params"]
        floor = float(self.bonds.cfg()["cool_floor"])
        t = dt.timestamp()
        pres = self.presence.effects(t) if not scene["away"] and self.bonds.together(char["id"], t) else {}
        if pres and not self.bonds.alone_with(char["id"], t):
            # そばにいる効果 (寂しさが紛れる) は, あなたとその人の二人きりのときだけ. ほかの人もいる中では, あなたへの寂しさは紛れない
            pres = {k: v for k, v in pres.items() if not (k == "loneliness" and float(v) < 0)}
        tr = self.traits(char)
        t_rate, t_drift, t_speed = tr.get("rate") or {}, tr.get("drift") or {}, tr.get("drift_speed") or {}
        if pres and self.presence.at(dt.timestamp()) == "gone":     # 黙っていなくなった: 性格しだいで堪える
            pres = {k: float(v) * float(tr.get("absence", 1)) for k, v in pres.items()}
        for p in self.params:
            pid = p["id"]
            v = vals.get(pid, float(p.get("init", 50)))
            rate = float(p.get("rate", 0))
            for r in p.get("rate_rules") or []:
                if cond.check(r.get("when", ""), ctx):
                    rate = float(r.get("rate", 0))
                    break
            rate *= float(t_rate.get(pid, 1))
            d = rate * h + float(scene["effects"].get(pid, 0)) * h + float(pres.get(pid, 0)) * h
            dr = p.get("drift")
            if dr:
                target = float(dr.get("target", v)) + float(t_drift.get(pid, 0)) + sum(
                    float(m.get("add", 0)) for m in dr.get("mods") or [] if cond.check(m.get("when", ""), ctx))
                d += (target - v) * min(1.0, float(dr.get("rate", 0)) * float(t_speed.get(pid, 1)) * h)
            if d < 0 and pid in FLOORED:
                # 時間だけで冷める分 (寂しさが続く など) は, ご無沙汰で冷めるのと同じ下限に近づくほど鈍り, そこで止まる.
                # 下がりきるのは, はっきりした出来事 (嫉妬・ひどいことをされた など) があったときだけ
                room = v - floor
                d = 0.0 if room <= 0 else max(-room, d * min(1.0, room / 15.0))
            vals[pid] = self._clamp(p, v + d)

    def tick(self, cid, now=None):
        char, st = self.char(cid), self.state(cid)
        now = now or time.time()
        t = st.get("last_tick") or now
        if now - t > MAX_CATCHUP_SEC:
            t = now - MAX_CATCHUP_SEC
        changed = False
        self.life.tick_world(now)
        self.home.tick(now)                    # 家は暮らしているうちに少しずつ散らかる
        while t + STEP_SEC <= now:
            self._step(char, st, datetime.fromtimestamp(t + STEP_SEC / 2), STEP_SEC / 3600.0)
            self.life.step(char, st, t, t + STEP_SEC, STEP_SEC / 3600.0)   # お金の出入り・キャラ側の出来事
            self.bonds.step(char, st, t + STEP_SEC, STEP_SEC / 3600.0)     # ほかの人との仲に気づく (嫉妬)
            self.wardrobe.step(char, st, t + STEP_SEC, STEP_SEC / 3600.0)  # ときどき自分で服を買う
            t += STEP_SEC
            changed = True
        st["last_tick"] = t
        ov = st.get("override")
        if ov and ov.get("until", 0) <= now:
            st["override"] = None
            changed = True
        self.bonds.sync(cid, st, now)         # 外で会っていたお出かけが終わった / 遊びに来ていた時間が過ぎた
        if changed:
            self.save_state(cid)

    # ------------------------------------------------------------------ prompt
    def active_tags(self, ctx):
        out = []
        for p in self.params:
            for tg in p.get("tags") or []:
                if cond.check(tg.get("when", ""), ctx):
                    out.append({"param": p["id"], "label": tg.get("label") or p.get("name", p["id"]),
                                "pos": tg.get("pos", ""), "neg": tg.get("neg", "")})
        return out

    def build_prompt(self, char, st, dt, act=None, reaction=None):
        scene = self.scene_at(char, st, dt)
        ctx = self.context(char, st, dt, scene)
        phase = self.phase_at(dt)
        pr = self.settings.get("prompt") or {}
        parts = [{"src": "共通", "pos": pr.get("prefix_pos", ""), "neg": pr.get("prefix_neg", "")},
                 {"src": "キャラクター", "pos": char.get("pos", ""), "neg": char.get("neg", "")},
                 {"src": "服装" + (": " + scene["dress"] if scene["dress"] else ""),
                  "pos": scene["outfit"], "neg": scene["outfit_neg"]}]
        looks = (self.player_profile().get("looks") or "").strip()
        if act and act.get("with_player") and looks:
            parts.append({"src": "あなた", "pos": looks, "neg": ""})
        if not (act and act.get("replace_scene")):
            parts.append({"src": "場面: " + scene["label"], "pos": scene["pos"], "neg": scene["neg"]})
        parts.append({"src": "時間帯: " + phase.get("label", ""), "pos": phase.get("pos", ""), "neg": phase.get("neg", "")})
        for tg in self.active_tags(ctx):
            parts.append({"src": "状態: " + tg["label"], "pos": tg["pos"], "neg": tg["neg"]})
        if act:
            parts.append({"src": "行動: " + act.get("name", ""), "pos": act.get("pos", ""), "neg": act.get("neg", "")})
        if reaction and (reaction.get("pos") or reaction.get("neg")):
            parts.append({"src": "反応", "pos": reaction.get("pos", ""), "neg": reaction.get("neg", "")})
        parts = [p for p in parts if p["pos"] or p["neg"]]
        pos = join_tags(p["pos"] for p in parts)
        rm = {t.lower() for t in scene.get("remove_tags") or []}
        if rm:   # ミニゲームの段階で外したもの (例: hair ribbon) を外見プロンプトからも除く
            pos = ", ".join(t for t in split_tags(pos) if t.lower() not in rm)
            parts.append({"src": "除外", "pos": "", "neg": "（除外）" + ", ".join(sorted(rm))})
        return pos, join_tags(p["neg"] for p in parts if p["src"] != "除外"), parts

    # ------------------------------------------------------------------ text
    def pronouns(self, char):
        """(一人称, 言いよどみの一人称, 呼び方). キャラクターで固定していればそれ, 無ければ性格プリセットに従う."""
        p = self.personas.get(char.get("persona_id") or "") or {}
        player = self.player_name()
        fixed_fp = (char.get("first_person") or "").strip()
        fp = fixed_fp or p.get("first_person") or "私"
        fp_st = fixed_fp or p.get("first_person_stutter") or fp
        call = (char.get("player_call") or "").strip() or p.get("player_call") or "{player}"
        return fp, fp_st, call.replace("{player}", player)

    # ------------------------------------------------------------------ あなた (プレイヤー)
    def player_profile(self):
        """あなたの情報 (全ワールド共通). キャラクターはこれを見て反応する."""
        p = dict(self.settings.get("player") or {})
        p["name"] = (p.get("name") or self.settings.get("player_name") or "").strip()
        return p

    def player_name(self):
        return self.player_profile()["name"] or "あなた"

    @staticmethod
    def _items(s):
        return [x.strip() for x in str(s or "").replace("、", ",").split(",") if x.strip()]

    def player_ctx(self):
        p = self.player_profile()
        age = p.get("age")
        return {"player_gender": p.get("gender") or "none", "player_age": float(age) if str(age or "").strip() else 0,
                "player_has_job": bool((p.get("job") or "").strip()),
                "player_likes": len(self._items(p.get("likes"))), "player_dislikes": len(self._items(p.get("dislikes")))}

    def player_text(self):
        """LLM に渡す, あなたの紹介."""
        p = self.player_profile()
        g = {"male": "男性", "female": "女性", "other": "その他"}.get(p.get("gender") or "", "")
        bits = [x for x in (g, ("%s歳" % p["age"]) if str(p.get("age") or "").strip() else "",
                            ("職業: " + p["job"]) if p.get("job") else "",
                            ("人柄: " + p["personality"]) if p.get("personality") else "",
                            ("好きなもの: " + p["likes"]) if p.get("likes") else "",
                            ("苦手なもの: " + p["dislikes"]) if p.get("dislikes") else "",
                            p.get("note") or "") if x]
        return "、".join(bits)

    def format_text(self, text, char, scene, dt):
        player = self.player_name()
        prof = self.player_profile()
        likes, dislikes = self._items(prof.get("likes")), self._items(prof.get("dislikes"))
        text = text.replace("{player_job}", prof.get("job") or "お仕事") \
            .replace("{player_like}", random.choice(likes) if likes else "好きなもの") \
            .replace("{player_dislike}", random.choice(dislikes) if dislikes else "苦手なもの")
        fp, fp_st, call = self.pronouns(char)
        for k, v in (("{fp_st}", fp_st), ("{fp}", fp), ("{call}", call), ("{player}", player), ("{name}", char.get("name", "")),
                     ("{location}", scene["location"]), ("{activity_label}", scene["label"]),
                     ("{time}", dt.strftime("%H:%M"))):
            text = text.replace(k, v)
        return text

    def _llm_text(self, char, st, dt, act, template, scene):
        cfg = self.settings.get("llm") or {}
        player = self.player_name()
        fp, _, call = self.pronouns(char)
        ctx = self.context(char, st, dt, scene)
        lines = []
        for p in self.params:
            lines.append("%s %d/%d" % (p.get("name", p["id"]), round(st["params"][p["id"]]), p.get("max", 100)))
        tags = "、".join(t["label"] for t in self.active_tags(ctx)) or "特になし"
        recent = "\n".join("- %s → %s" % (e.get("action_name", ""), e.get("text", ""))
                           for e in self.log(char["id"])[-4:])
        system = (cfg.get("system") or "").replace("{name}", char.get("name", "")).replace("{call}", call) \
            .replace("{player}", player).replace("{persona}", char.get("persona", "")).replace("{fp}", fp)
        system += "\n一人称は必ず「%s」、%sのことは必ず「%s」と呼ぶ。" % (fp, player, call)
        if self.player_text():
            system += "\n%sについて知っていること: %s。これを踏まえて話す（好きなものの話題に乗る、苦手なものは避ける など）。" % (
                player, self.player_text())
        bv = self.bonds.view(char["id"])
        system += "\n%sとの間柄: %s（いまは%s）。" % (player, bv["stage_label"], bv["label"])
        known = self.relations_text(char)
        if known:
            system += "\n知っている人: %s。それ以外の登場人物は知らない。" % known
        user = ("現在 %s（%s曜 %s）\n%sの状況: %s（%s）\nパラメータ: %s\n目立つ状態: %s\n直近のやりとり:\n%s\n\n"
                "%sの行動: %s\n参考セリフ（この方向性で）: %s\n\n%sとしてのセリフだけを返して。"
                % (dt.strftime("%H:%M"), DAY_JA[dt.weekday()], self.phase_at(dt).get("label", ""),
                   char.get("name", ""), scene["label"], scene["location"], "、".join(lines), tags,
                   recent or "（なし）", player, act.get("name", ""), template, char.get("name", "")))
        return llm.chat(cfg, system, user)

    # ------------------------------------------------------------------ actions
    def persona_text(self, char, key):
        """キャラクターの性格プリセットにそのキーのセリフがあれば 1 つ選んで返す."""
        if not key:
            return None
        p = self.personas.get(char.get("persona_id") or "")
        texts = (p or {}).get("lines", {}).get(key)
        if isinstance(texts, str):
            return texts
        return random.choice(texts) if texts else None

    def traits(self, char):
        """性格プリセットの傾向 (パラメータの動きやすさ・話しかけてくる多さなど)."""
        return (self.personas.get(char.get("persona_id") or "") or {}).get("traits") or {}

    def trait_effects(self, char, eff):
        """性格による効き目の違い: うれしい方向は gain, つらい方向は hurt の倍率をかける."""
        tr = self.traits(char)
        gain, hurt = tr.get("gain") or {}, tr.get("hurt") or {}
        if not (gain or hurt):
            return dict(eff)
        out = {}
        for k, v in eff.items():
            pd = self.param_def(k) or {}
            good = (float(v) > 0) != bool(pd.get("invert"))
            out[k] = float(v) * float((gain if good else hurt).get(k, 1))
        return out

    def pick_reaction(self, act, ctx):
        cands = [r for r in act.get("reactions") or [] if cond.check(r.get("when", ""), ctx)]
        if not cands:
            return {"text": ""}
        top = max(int(r.get("priority", 0)) for r in cands)
        cands = [r for r in cands if int(r.get("priority", 0)) == top]
        return random.choices(cands, [1 + cond.count(r.get("when", "")) for r in cands])[0]

    def apply_effects(self, st, effects):
        deltas = {}
        for pid, dv in effects.items():
            p = self.param_def(pid)
            if not p:
                continue
            old = st["params"][pid]
            st["params"][pid] = self._clamp(p, old + float(dv))
            d = round(st["params"][pid] - old, 1)
            if d:
                deltas[pid] = d
        return deltas

    def available(self, char, st, dt):
        ctx = self.context(char, st, dt)
        now = dt.timestamp()
        out = {}
        for a in self.actions:
            if a.get("category") == "system":
                continue
            cd = float(a.get("cooldown", 0)) * 60
            last = max(st["cooldowns"].get(a["id"], [0]) or [0])
            ovp = a.get("override") or {}
            shut = bool(ovp.get("outing")) and not any(places_mod.open_state(p, dt)["open"]      # 行き先がどこも閉まっている
                                                       for p in (a.get("places") or [ovp.get("place") or places_mod.from_location(ovp.get("location"))]))
            out[a["id"]] = {"ok": cond.check(self._when(a, ctx), ctx) and not (a.get("home_only") and ctx["outing"]) and not shut
                            and (not ctx["apart"] or (self.bonds.allowed_apart(a, char["id"]) and not self.appoint.needs(a, char["id"]))),
                            "closed": shut,
                            "cooldown": max(0, int(last + cd - now)) if cd else 0}
        return out

    def act(self, aid, cid=None, dress=None, opts=None):
        """行動を実行する. aid="_dress" のときは dress に着替え先の id ("" でおまかせ) を渡す.
        opts: 呼び出し側で済ませたお金の動きなど {"money": {p, a}, "extra": 置換文字, "ctx": 条件に足す値}."""
        opts = opts or {}
        with self.lock:
            char = self.char(cid)
            cid = char["id"]
            self.tick(cid)
            st, a = self.state(cid), self.action(aid)
            called = False
            uses = items_mod.USES.get(aid)          # 家での行動が使う持ち物 (料理=食材 など)
            gift_item = opts.get("gift_item")       # 持ち物からのプレゼント
            if uses or gift_item:
                a = dict(a, cost=0)                 # 品物はもう買ってある (その場では払わない)
            now = time.time()
            dt = datetime.fromtimestamp(now)
            if a.get("category") != "system":       # 画面から操作した = そばにいる
                pr = self.presence.rec()
                if not opts.get("deliver"):        # 時間差で届いた返信は, あなたの操作ではない
                    pr["beat"] = pr["input"] = now
            scene = self.scene_at(char, st, dt)
            ctx = self.context(char, st, dt, scene)
            appt = opts.get("appointment")          # 約束して会えた (条件は約束したときに済んでいる)
            when = "asleep=false, away=false" if gift_item else "" if appt else self._when(a, ctx)     # 持ち物を渡すなら, 所持金の条件はいらない
            if not appt and ctx["apart"] and not opts.get("deliver") and self.appoint.needs(a, cid):
                raise ValueError("%sとは、約束してから会いましょう（トークの「📅 約束する」から）" % char.get("name", ""))
            # 閉じていた間の約束をあとからまとめて進めるとき (auto_weak) は, いまの時刻ではなく約束の時刻の話なので見ない
            replay = opts.get("auto_weak") and opts.get("appointment")
            if not replay and not cond.check(when, ctx):
                raise ValueError("今は「%s」できません（%s）" % (a.get("name", aid), when))
            ovp = (a.get("override") or {})
            if ovp.get("outing") and not replay:      # お出かけの行き先が閉まっていたら行けない (約束でも, 着いた時刻で)
                pl = opts.get("place") if opts.get("place") in (a.get("places") or []) else ovp.get("place")
                pl = pl if pl in places_mod.PLACES else places_mod.from_location(ovp.get("location"))
                o = places_mod.open_state(pl, dt)
                if not o["open"]:
                    raise ValueError("%sは閉まっています（%s）" % (places_mod.PLACES[pl]["label"], o["note"]))
            if a.get("home_only") and ctx["outing"]:
                raise ValueError("お出かけ中は「%s」できません" % a.get("name", aid))
            apart = ctx["apart"]
            if apart and a.get("category") == "連絡" and not opts.get("deliver") and opts.get("msg_kind") != "apology":
                self._phoned(st, now, char, opts.get("msg_kind"), phone=bool(a.get("phone")))      # スマホで連絡した (謝るメッセージは数えない)
            if apart and a.get("reply_later", aid == "message") and not opts.get("deliver"):
                # 離れている相手へのメッセージは, 送るだけ. 返信は相手の状況しだいで, しばらくしてから (来ないことも)
                return self._send_later(char, st, a, now, dt, scene, ctx, opts.get("msg_kind"))
            if apart and a.get("phone") and not opts.get("deliver"):
                # 電話: 寝ている・手が離せない・気分しだいで出ない. あとで折り返しが来ることも
                missed = self._call_missed(char, st, a, now, dt, scene, ctx)
                if missed:
                    return missed
                called = True
                st["peek_until"] = now + 600        # 電話のあいだ, 相手がいまどこで何をしているかは少しわかる
                if st.pop("call_ok_until", 0) > now:     # 「今いい？」と聞いてからかけた: いきなりより少しだけ感じがいい
                    fx = dict(opts.get("effects") or {})
                    fx["mood"] = float(fx.get("mood", 0)) + 1.5
                    opts = dict(opts, effects=fx)
            if apart and not appt and a.get("category") != "system" and not self.bonds.allowed_apart(a, cid):
                if self.bonds.stage(cid) == "known":
                    raise ValueError("%sの連絡先を知りません（偶然会えたら交換できます）" % char.get("name", ""))
                raise ValueError("いまは%sと一緒にいません（連絡するか、会いに行きましょう）" % char.get("name", ""))
            if a.get("category") != "system" and not opts.get("deliver") and not opts.get("approach") \
                    and not (apart and a.get("category") in ("連絡", "会う")) and not opts.get("appointment"):
                why = self.blocked("social")
                if why:
                    raise ValueError(why)
            ctx.update(opts.get("ctx") or {})
            outfit = None
            if dress is not None:
                if dress:
                    outfit = self.wardrobe_item(char, dress)
                    if not outfit:
                        raise KeyError("服が見つかりません: %s" % dress)
                    if not cond.check(outfit.get("when", ""), ctx):
                        raise ValueError("今は「%s」に着替えられません（%s）" % (outfit.get("name", dress), outfit.get("when", "")))
                ctx["outfit"] = dress   # 反応の条件では「着替え先」を outfit として参照できる
                # 大胆な服: 着てくれるか (照れながら・渋々・ノリノリ・断る・しつこくて怒る). 反応の条件 dress_feel / dress_bold
                ctx["dress_feel"] = self.wardrobe.accept(char, st, outfit, now, others=len(self.bonds.company(now)) > 1) \
                    if outfit else "ok"
                ctx["dress_bold"] = int((outfit or {}).get("bold") or 0)
            pose = None
            if aid in ("_pose", "_show"):             # ポーズを取って / ○○を見せて (大人だけ. 受け入れは着せ替えと同じ考え方)
                pose = self.posing.get(opts.get("pose") or "")
                if not pose or pose["type"] != aid[1:]:
                    raise KeyError("ポーズ・見せるものが見つかりません: %s" % opts.get("pose"))
                ok, why = self.posing.can(char, st, now)
                if not ok:
                    raise ValueError(why)
                outside = self.posing.outside(cid)
                if outside and not pose["outside_ok"]:
                    raise ValueError("「%s」は外では頼めません" % pose["name"])
                ctx["pose"] = pose["id"]
                ctx["pose_feel"] = self.wardrobe.accept(char, st, pose, now, outside=outside,
                                                        others=len(self.bonds.company(now)) > 1, asks_key="pose_asks")
                ctx["pose_bold"] = pose["bold"]
                opts.setdefault("extra", {})["item"] = pose["name"]
                self.posing.learn(st, "%s:%s" % (pose["type"], pose["id"]), 1.0)     # 頼んだもの = あなたの好み
            if dress:
                self.posing.learn(st, "outfit:" + dress, 1.0)
            cd = float(a.get("cooldown", 0)) * 60
            hist = [x for x in st["cooldowns"].get(aid, []) if now - x < cd] if cd else []
            ctx["repeat"] = len(hist)
            # ---- お金: 誰が払うか・払えるかを先に決める (反応の条件 payer で使える)
            extra = self.life.mood_text(st, now)          # {ev_text} {bad_text} {away_text} {req_text} {amount}
            extra.update(opts.get("extra") or {})
            plan, req = None, st.get("request")
            if a.get("meal_out") and not apart:     # 一緒に外食: 費用は行き先のメニュー (二人分)
                a = dict(a, cost=self.body.pair_cost(opts.get("place") if opts.get("place") in (a.get("places") or []) else
                                                     (a.get("override") or {}).get("place")))
            if a.get("cost"):
                plan = self.life.plan_payment(char, st, int(a["cost"]), "me" if a.get("payer") == "me" else None)
                ctx["payer"] = plan["payer"]
                extra["cost"] = format(int(a["cost"]), ",")
            ans = a.get("request_answer")
            if ans:
                if not req:
                    raise ValueError("今はお願いされていません")
                ctx["req_kind"] = req["kind"]
                if ans == "yes" and req["kind"] in ("money", "gift") and self.life.player_state()["money"] < req["amount"]:
                    raise ValueError("お金が足りません（%s円必要）" % format(req["amount"], ","))
            tr = a.get("transfer")
            if tr and tr.get("from") == "p" and self.life.player_state()["money"] < int(tr.get("amount", 0)):
                raise ValueError("お金が足りません（%s円必要）" % format(int(tr["amount"]), ","))
            self._apol = None
            if a.get("mood_action") == "apologize":       # その場で謝る: 許し方はメッセージと同じ判定 (反応の条件 apology)
                self._apol = self.manners.apology(char, st, now, face=True)
                ctx["apology"] = self._apol["out"]
            r = self.pick_reaction(a, ctx)
            invite = apart and (a.get("override") or {}).get("outing")
            promised = st.get("date_promise", 0) > now          # メッセージで「会おう」に応じてくれていた
            if invite and not appt and not promised and ctx.get("affection", 0) < float(self.bonds.cfg()["meet_min_affection"]) and not r.get("override"):
                r = {"text": "📱『ごめんなさい、その日はちょっと……』", "override": True, "key": "_invite_no"}
            mine = (a.get("category") == "あなたの予定" or aid in bonds_mod.APART_TEXT) and not a.get("request_answer")
            # 同居していない相手と外で会っている / 相手の家にいるときに出かける・離れる = 別れて行く
            parting = mine and not apart and self.bonds.mode(cid) in ("meet", "visit", "guest")                 and a.get("presence_set") in ("work", "out", "left", "sleep")
            if apart and mine and not parting:
                # その場にいない相手にかかわらない, あなた一人の行動 (仕事から帰った・出かけた など): あなたの記録にだけ残す
                # (以前は「選んでいるキャラ」のログに書いていた名残. キャラのログには, その人がその場にいて関わった出来事だけ)
                what = a.get("apart_text") or bonds_mod.APART_TEXT.get(aid) or a.get("name", aid)
                for k, v in extra.items():
                    what = what.replace("{%s}" % k, str(v))
                if a.get("presence_set"):
                    self.presence.declare(a["presence_set"], now)
                return self.my_entry(MY_ACTION_KIND.get(aid, "home"), a.get("name", aid), a.get("icon", "🧍"), what, now,
                                     money=opts.get("money"), skill={k: v for k, v in (opts.get("skill") or {}).items() if v} or None)
            narrate = parting
            if narrate:     # 外で会っていた相手と別れて行く: 別れるところまでは, その人との記録
                what = a.get("apart_text") or bonds_mod.APART_TEXT.get(aid) or a.get("name", aid)
                r = {"text": "（%s%s）" % ("{name}と別れて、" if parting else "", what)}
            scale = float(a.get("repeat_scale", 0.5)) ** len(hist)
            sk = a.get("skill")
            sk_mult = self.life.skill_mult(sk) if sk else 1.0
            if a.get("category") not in ("system", "あなたの予定"):
                sk_mult *= self.life.stamina_mult()        # 疲れていると, 構っても効きが悪い
            eff = {}
            if not r.get("override"):
                for k, v in (a.get("effects") or {}).items():
                    v = float(v) * scale
                    pd = self.param_def(k) or {}
                    if (v < 0) == bool(pd.get("invert")) or pd.get("neutral"):
                        v *= sk_mult          # あなたのスキルで, うれしい方向の効き目が変わる
                    eff[k] = eff.get(k, 0) + v
            for k, v in (r.get("effects") or {}).items():
                eff[k] = eff.get(k, 0) + float(v)
            if narrate:
                eff = {}
            for k, v in (opts.get("effects") or {}).items():
                eff[k] = eff.get(k, 0) + float(v)
            real_note = None
            item_note = None
            if uses and (not r.get("override") or r.get("taken")) and not narrate:     # 焦がしても食材は使う
                if not self.items.use_kind(uses):    # 持ち物が無い: ありあわせで, 効き目が落ちる
                    f = 0.7 if uses == "detergent" else 0.5
                    eff = {k: (v * f if v > 0 else v) for k, v in eff.items()}
                    item_note = items_mod.MISSING.get(aid)
            if gift_item and (not r.get("override") or r.get("taken")):
                self.items.add(gift_item, -1)        # 受け取ってもらえた (はっきり断られたら手元に残る)
                if gift_item.startswith("outfit:"):  # 服: その人の持っている服になる (着るかは本人しだい)
                    self.wardrobe.give_to(char, gift_item.split(":", 1)[1], "player", now)
            social = a.get("category") not in ("system", "あなたの予定") or a.get("request_answer") or aid in ("_pose", "_show")
            if social and not narrate:
                # 現実的に: 好感度・信頼の上がり方は揺らぎ, 鈍り, 繰り返せばうんざりされる. 交流した日も記録する
                if opts.get("auto_weak"):          # 自動で過ごした (画面を閉じていた間の約束など): 良い影響が出にくい
                    eff = {k: (float(v) * 0.4 if float(v) * (-1 if (self.param_def(k) or {}).get("invert") else 1) > 0 else float(v))
                           for k, v in eff.items()}
                eff, real_note = self.bonds.realize(char, st, eff, aid, now, gift=a.get("gift"))
                self.bonds.touch(st, now)
                if a.get("gift"):
                    st.setdefault("gifts", []).append(now)
                    st["gifts"] = [x for x in st["gifts"] if now - x < 30 * 86400]
            deltas = self.apply_effects(st, self.trait_effects(char, eff))
            if a.get("meal_out") and not r.get("override") and not narrate:
                pl = opts.get("place") if opts.get("place") in (a.get("places") or []) else (a.get("override") or {}).get("place")
                meal_note = self.body.eat_with(pl, char, now)          # あなたも食べる (払いは上の費用で済んでいる)
            else:
                meal_note = None
            dress_note = None
            if a.get("override") and not r.get("override"):
                ov = dict(a["override"])
                ov["until"] = now + float(ov.get("minutes", 30)) * 60
                ov["from_action"] = aid
                if ov.get("outing"):        # お出かけの行き先 (表の id). 選べるものは places から
                    pl = opts.get("place") if opts.get("place") in (a.get("places") or []) else ov.get("place")
                    pl = pl if pl in places_mod.PLACES else places_mod.from_location(ov.get("location"))
                    ov["place"] = pl
                    ov["location"] = places_mod.PLACES[pl]["label"]
                st["override"] = ov
                worn = self.wardrobe_item(char, (st.get("dress") or {}).get("id"))
                if ov.get("outing") and worn and worn["outing_ok"] and worn["bold"] > 0 and self.wardrobe.accept(
                        char, st, worn, now, outside=True, others=1, record=False) in ("refuse", "angry"):
                    st["dress"] = None            # 外では, 大胆な服は性格と場所しだいで嫌がる
                    dress_note = "（{name}は「%s」のまま出かけるのは嫌だと、着替えてから出かけた）" % worn["name"]
            if a.get("end_override") and not r.get("override"):
                st["override"] = None     # 「家に帰る」「切り上げる」: 一時的な過ごし方を終えて予定に戻る
            if dress is not None and not r.get("override"):
                st["dress"] = {"id": dress, "t": now} if dress else None
            home_note = None
            at_home = self.bonds.mode(cid) in ("home", "guest")
            if at_home and a.get("home_dirty") and (not r.get("override") or r.get("taken")):
                self.home.add(**a["home_dirty"])          # 料理をすれば洗い物が出る (焦がしても)
            if not r.get("override"):
                self.bonds.apply(a, cid, now)
                heff = {}
                if a.get("bond") == "guest_start":         # 家に招いた: 来た相手が家の様子に反応する (性格しだい)
                    home_note, heff = self.home.on_guest(char, st, now)
                    st["override"] = {"activity": "guest", "label": "あなたの家に遊びに来ている", "location": "あなたの家",
                                      "until": (self.bonds.with_rec() or {}).get("until", now + 3 * 3600), "from_action": aid,
                                      "pos": "indoors, apartment, living room", "neg": ""}
                elif a.get("bond") == "visit_start":       # 相手の家に来た: 暮らしぶりが見える
                    home_note = places_mod.home_glimpse(self, char, st)
                elif social and not narrate and self.bonds.mode(cid) == "home":
                    home_note, heff = self.home.live_check(char, st, now)     # 同居相手は日々の家の様子に反応する
                if at_home and a.get("home_clean"):
                    self.home.clean(float(a["home_clean"]) * random.uniform(0.7, 1.2))
                if heff:
                    for k, v in self.apply_effects(st, self.trait_effects(char, heff)).items():
                        deltas[k] = round(deltas.get(k, 0) + v, 2)
                if invite:
                    self.bonds.start(cid, "meet", now)      # 誘いに乗ってくれた: 外で会う
                    st.pop("date_promise", None)
            self.bonds.sync(cid, st, now)                   # 「家に帰る」で別れる など
            money = self._act_money(char, st, a, r, plan, req, extra)
            for k, v in (opts.get("money") or {}).items():
                money[k] = money.get(k, 0) + v
            self._act_reasons(char, st, a, r, deltas, now)
            if (not apart or called) and a.get("category") not in ("system", "あなたの予定") and not narrate:
                if not apart:
                    self.manners.favor(st, "met", now)          # 会ってくれた (お礼の心当たり)
                self.manners.saw_down(st, now)                  # 具合の悪さ・落ち込みに気づく (「大丈夫？」の心当たり)
            if plan and plan.get("payer") == "her":
                self.manners.favor(st, "treat", now)
            skill_up = {sk: self.life.train(sk, 1.2 * scale)} if sk else {}
            if aid in CARE_ACTIONS and not r.get("override"):         # 様子を見る・気持ちを聞く: 気配り
                skill_up["care"] = self.life.train("care", 0.8 * scale)
            if aid == "clean" and not r.get("override"):               # 一緒に掃除: 家事
                skill_up["house"] = self.life.train("house", 0.8 * scale)
            skill_up.update(opts.get("skill") or {})
            if a.get("presence_set"):
                self.presence.declare(a["presence_set"], now)
                if parting:
                    self.bonds.end()
            elif a.get("category") != "system" and not opts.get("deliver"):
                self.presence.touch(now)
                if self.presence.rec()["mode"] == "busy" and not (apart and a.get("category") == "連絡") \
                        and not self.task_active():       # スマホなら続けられる
                    # 作業中・一人の時間の途中でも, 話しかけられて応じたら, そこでおしまい (一人の時間の結果は残す)
                    ll = self.presence.back(now)
                    if ll:
                        self.solo.finish(ll)
                self.presence.drop(st)
            if cd:
                st["cooldowns"][aid] = hist + [now]
            st["last_interaction"] = now
            if a.get("category") != "system" or aid in ("_req_yes", "_req_no", "_dress", "_back", "work", "_return"):
                if not narrate and not opts.get("deliver"):
                    self.bonds.met(st, now, contact=apart)       # 関係性: 最後に会った / 連絡した
            scene2 = self.scene_at(char, st, dt)
            rs = a.get("reactions") or []
            pkey = "%s.%s" % (aid, line_keys(rs)[rs.index(r)]) if r in rs else None
            text = self.persona_text(char, pkey) or r.get("text", "")
            if "{away_text}" in text or "{ev_text}" in text or "{bad_text}" in text:
                # 話して聞かせた出来事は「理由を知っている」扱いにする
                said = " ".join(extra.get(k, "") for k in ("away_text", "ev_text", "bad_text") if "{%s}" % k in text)
                for x in self.life.reasons(st, now):
                    if x["kind"] == "event" and x["tell"] and x["tell"] in said:
                        x["told"] = True
            for k, v in extra.items():                     # 先に差し込む (中の {call} なども下で置換される)
                text = text.replace("{%s}" % k, str(v))
            text = self.format_text(text, char, scene, dt)
            gen_ok = a.get("generate", True)
            selfie = False
            if not self.bonds.together(cid):
                # 離れている相手の画像は出さない. ただしメッセージには, テンションしだいで自撮りが添えられる
                selfie = bool(a.get("selfie")) and not r.get("override") and random.random() < self.bonds.selfie_chance(ctx)
                gen_ok = selfie
            pa = dict(a, pos=a.get("selfie_pos") or "selfie, holding smartphone, looking at viewer, upper body") if selfie else a
            if pose and not r.get("override"):        # 受けてくれたら, そのポーズ・部位で
                pa = dict(pa, pos=pose["pos"], neg=pose["neg"])
            pos, neg, parts = self.build_prompt(char, st, dt, pa, r)
            self.save_state(cid)

        text_src, llm_error = "template", None
        cfg = self.settings.get("llm") or {}
        if cfg.get("enabled") and text and not text.startswith("（") and not a.get("no_llm"):
            try:
                t2 = self._llm_text(char, st, dt, a, text, scene2)
                if t2:
                    text, text_src = t2, "llm"
            except Exception as e:  # noqa: BLE001 - LLM 失敗時は定型文で続行
                llm_error = str(e)

        if selfie:
            text += "\n（📷 自撮りが添えられていた）"
        if real_note:
            text += "\n" + self.format_text(real_note, char, scene, dt)
        if item_note:
            text += "\n" + self.format_text(item_note, char, scene, dt)
        if aid in SCHED_TALK and not r.get("override") and not narrate:
            sched_note = self.knowsched.from_talk(char, st, now)      # 話のついでに, 予定を聞くことがある
            if sched_note:
                text += "\n" + sched_note
            rumor_note = self.rumors.from_talk(char, st, now)        # 会社や店の噂 (会話・気配りのスキルで頻度と確かさ)
            if rumor_note:
                text += "\n" + rumor_note
        if home_note:
            text += "\n" + self.format_text(home_note, char, scene, dt)
        if dress_note:
            text += "\n" + self.format_text(dress_note, char, scene, dt)
        if meal_note:
            text += "\n" + meal_note
        with self.lock:
            entry = self._new_entry(cid, now, a, text, deltas, scene2, dt, pos, neg, parts)
            entry["text_src"] = text_src
            if selfie:
                entry["selfie"] = True
            if money:
                entry["money"] = money
            if any(skill_up.values()):
                entry["skill"] = {k: v for k, v in skill_up.items() if v}
            job = None
            if self.settings.get("auto_generate") and gen_ok:
                job = self._present_image(cid, entry)
            self.save_log(cid)
        if called:          # 電話で話した: トークにも並べる
            self.chat.add(cid, "sys", "📞 電話で話した", kind="call", t=now)
            self.chat.add(cid, "her", text, kind="call", t=now + 0.001)
        return {"entry": entry, "job": job, "llm_error": llm_error}

    def give_item(self, iid, cid=None):
        """持ち物からプレゼントする. 好き・苦手と値段で反応が変わる (高価なものは「重い」と断られることも)."""
        it = items_mod.CATALOG.get(iid)
        if not it or not it["giftable"]:
            raise ValueError("プレゼントにできない品物です")
        if self.items.count(iid) <= 0:
            raise ValueError("%sを持っていません" % it["name"])
        char = self.char(cid)
        aid = "expensive_gift" if it["price"] >= 10000 else "gift"
        feel = self.items.feel(char, iid)
        if it.get("outfit"):           # 服: 持っていれば要らない. 大胆すぎると受け取れない (反応の条件 gift_outfit)
            if it["outfit"] in self.wardrobe.owned_ids(char):
                raise ValueError("%sは「%s」をもう持っています" % (char.get("name", ""), it["name"]))
            feel["gift_outfit"] = self.wardrobe.gift_feel(char, self.state(char["id"]), it["outfit"], time.time())
        r = self.act(aid, char["id"], opts={"gift_item": iid, "ctx": feel, "extra": {"item": it["name"]}})
        if feel["liked"] or feel["disliked"]:           # 渡してみて分かった, 好きなもの・苦手なもの (関係性)
            lk, dk = self.items.likes(char)
            tags = [t for t in it["tags"] if t in (lk if feel["liked"] else dk)]
            with self.lock:
                st = self.state(char["id"])
                for t in tags:
                    self.bonds.learn(st, "like" if feel["liked"] else "dislike", items_mod.TAG_LABEL.get(t, t), time.time())
                self.save_state(char["id"])
        return r

    def _when(self, a, ctx):
        """コマンドの条件. 離れている相手には apart_when があればそれ (例: メッセージは相手が寝ていても送れる)."""
        if ctx.get("apart") and "apart_when" in a:
            return a.get("apart_when") or ""
        return a.get("when", "")

    def _phoned(self, st, now, char=None, kind=None, phone=False):
        """スマホで連絡した記録: 相手ごとの頻度 (種類ごとの重み. bonds.contact_weight) と, 仕事中の連絡 (多いと仕事に響く)."""
        w = self.bonds.contact_weight(char, st, kind, now, phone) if char else 1.0
        st["contacts"] = [x for x in st.get("contacts") or [] if now - self.bonds.contact_t(x) < 86400] + [{"t": now, "w": round(w, 2)}]
        p = self.presence.rec()
        if p.get("mode") == "work":
            p["work_contacts"] = p.get("work_contacts", 0) + 1

    def _call_missed(self, char, st, a, now, dt, scene, ctx):
        """離れている相手への電話に出るか. 出なければ記録を返す (折り返しはメッセージで届くことも). 出るなら None."""
        p = st["params"]
        callback = None
        if scene["asleep"]:
            callback = (random.uniform(30, 90) * 60) if random.random() < 0.5 else None   # 起きてから気づくことも
        elif scene["busy"]:
            callback = (random.uniform(20, 90) * 60) if random.random() < 0.7 else None
        else:
            pr = 0.9 * (0.6 if p.get("mood", 50) < 30 else 1) * (0.5 if ctx.get("too_often") else 1) \
                * (0.7 if p.get("affection", 50) < 35 else 1) * (1.15 if st.get("call_ok_until", 0) > now else 1)
            if random.random() < min(0.95, pr):
                self.trace.add("msg", "電話に出た", char["id"], now, pr=pr, mood=p.get("mood"), affection=p.get("affection"),
                               too_often=ctx.get("too_often"))
                return None
            callback = (random.uniform(10, 60) * 60) if random.random() < 0.3 else None
        cid = char["id"]
        self.trace.add("msg", "電話に出なかった", cid, now, asleep=scene["asleep"], busy=scene["busy"], callback_min=(callback or 0) / 60.0,
                       mood=p.get("mood"), affection=p.get("affection"), too_often=ctx.get("too_often"))
        self.bonds.met(st, now, contact=True)
        if callback and not st.get("msg_pending"):
            st["msg_pending"] = {"aid": "message", "t": now, "due": now + callback, "reply": True, "count": 1, "callback": True}
        cd = float(a.get("cooldown", 0)) * 60
        if cd:
            st["cooldowns"][a["id"]] = [x for x in st["cooldowns"].get(a["id"], []) if now - x < cd] + [now]
        pos, neg, parts = self.build_prompt(char, st, dt, a)
        e = self._new_entry(cid, now, a, "（📞 %sに電話をかけたが、出なかった）" % char.get("name", ""), {}, scene, dt, pos, neg, parts)
        self.chat.add(cid, "sys", "📞 電話をかけたが、出なかった", kind="call", t=now)
        e["missed"] = True
        self.save_state(cid)
        self.save_log(cid)
        return {"entry": e, "job": None, "llm_error": None, "missed": True}

    def _send_later(self, char, st, a, now, dt, scene, ctx, kind=None):
        """離れている相手にメッセージを送る. 返信の予定 (いつ・来るか) を決めて, 送った記録だけを残す.
        kind: メッセージの種類 (chat.KINDS. 無ければ, ただの「メッセージを送る」)."""
        cid = char["id"]
        p = st["params"]
        pend = st.get("msg_pending")
        self.bonds.met(st, now, contact=True)
        if st.get("approach"):
            self.presence.drop(st)              # 届いていたメッセージには, これが返事になる
        self.chat.add(cid, "me", chat_mod.KINDS[kind][2] if kind else "（メッセージを送った）", kind=kind, t=now)
        meta = self.manners.on_send(char, st, kind, now) if kind else {}     # 送った時刻・続け方 (あいさつ・スタンプ など)
        if pend:
            pend["count"] = pend.get("count", 1) + 1
            if kind == "nudge":                        # 返事を待っている間の催促: 返信はもとのメッセージに. 急ぎの話なら多少許される
                pend["nudge"] = "ok" if self.manners.nudge_urgent(char, st, pend, now) else "bad"
            elif kind:
                if pend.get("kind") == "apology" and kind != "apology" and not pend.get("apology_first"):
                    # 謝罪の返事を待っている間に別のメッセージ: 謝罪を上書きしない (返事は謝罪への分と, 新しい方への分の 2 つ)
                    pend["apology_first"] = {"t": pend.get("kind_t") or pend["t"], "meta": pend.get("meta") or {}}
                pend["kind"] = kind                    # 返信は, いちばん新しいメッセージに対して
                pend["meta"] = meta
                pend["kind_t"] = now
        else:
            delay = random.uniform(3, 40) * 60
            if p.get("mood", 50) < 35:
                delay *= 2
            if p.get("affection", 50) < 40:
                delay *= 2
            pr = 0.9 * (0.6 if p.get("mood", 50) < 30 else 1) * (0.7 if p.get("affection", 50) < 35 else 1) \
                * (0.7 if p.get("stress", 0) > 70 else 1)                 * (0.6 if ctx.get("too_often") and not (kind == "thanks" and self.manners.thanks_grace(st, now)) else 1)
            quick = self._still_on_phone(char, st, now, scene, ctx)
            if quick:
                delay = random.uniform(10, 90)
            st["msg_pending"] = {"aid": a["id"], "t": now, "due": now + delay, "reply": random.random() < pr, "count": 1,
                                 "kind": kind, "quick": quick, "meta": meta}
            self.trace.add("msg", "送った: 返信の予定を決めた", cid, now, kind=kind, due_min=delay / 60.0, pr=pr,
                           reply=st["msg_pending"]["reply"], quick=quick, too_often=ctx.get("too_often"),
                           contacts=ctx.get("contacts_24h"), mood=p.get("mood"), affection=p.get("affection"), stress=p.get("stress"),
                           scene=scene.get("label"), asleep=scene.get("asleep"), busy=scene.get("busy"), meta=meta)
        if pend:
            self.trace.add("msg", "送った: 返事待ちに重ねた", cid, now, kind=kind, count=pend.get("count"), due_in_min=(pend.get("due", now) - now) / 60.0,
                           reply=pend.get("reply"), nudge=pend.get("nudge"), apology_first=bool(pend.get("apology_first")),
                           too_often=ctx.get("too_often"), contacts=ctx.get("contacts_24h"))
        cd = float(a.get("cooldown", 0)) * 60
        if cd:
            st["cooldowns"][a["id"]] = [x for x in st["cooldowns"].get(a["id"], []) if now - x < cd] + [now]
        text = "（📱 %sに%s）" % (char.get("name", ""), "「%s」と送った" % chat_mod.KINDS[kind][0] if kind else "メッセージを送った")
        pos, neg, parts = self.build_prompt(char, st, dt, a)
        e = self._new_entry(cid, now, a, text, {}, scene, dt, pos, neg, parts)
        e["sent"] = True
        self.save_state(cid)
        self.save_log(cid)
        return {"entry": e, "job": None, "llm_error": None, "sent": True}

    def picked_up_phone(self, char, st, now):
        """相手があなたにメッセージを送った・返した直後は, しばらくスマホを見ている (すぐの返信の手がかり).
        どれくらい見ているかは揺らぎと性格 (話しかけてくる多さ) しだい."""
        st["phone_until"] = now + random.uniform(2, 10) * 60 * min(1.5, max(0.5, float(self.traits(char).get("approach", 1))))

    def _still_on_phone(self, char, st, now, scene, ctx):
        """相手がまだスマホを見ている間に送ったら, すぐ返ってくることがある. 必ずではない (機嫌・好感度・続いた回数・
        手が離せない・送りすぎ・性格しだい). すぐ返すと決まれば True."""
        if now >= st.get("phone_until", 0) or scene["asleep"] or scene["busy"]:
            st["phone_turns"] = 0
            return False
        p = st["params"]
        pq = 0.75 * (0.5 if p.get("mood", 50) < 35 else 1) * (0.6 if p.get("affection", 50) < 40 else 1) \
            * (0.5 if ctx.get("too_often") else 1) * (0.8 ** st.get("phone_turns", 0)) \
            * min(1.3, max(0.5, float(self.traits(char).get("approach", 1))))
        if random.random() < pq:
            st["phone_turns"] = st.get("phone_turns", 0) + 1
            return True
        st["phone_until"] = 0                  # スマホを置いた: ここからは時間差
        st["phone_turns"] = 0
        return False

    def _nudge_seen(self, char, st, pend, now):
        """返事を待っている間に届いた「返事まだ？」を読んだ (ほぼ逆効果. 急ぎの話なら多少許される)."""
        key, eff = self.manners.nudge_effect(char, st, pend, now)
        eff, _ = self.bonds.realize(char, st, eff, "_chat_nudge", now)
        self.apply_effects(st, self.trait_effects(char, eff))
        if pend.get("reply"):
            self.chat.add(char["id"], "her", self.chat.line(char, key, {}), kind=key, t=now - 0.001)

    def _chat_reply(self, char, st, pend, now):
        """メッセージの種類と状況で返信を決めて届ける (効果・既読・トーク・ログ)."""
        cid = char["id"]
        dt = datetime.fromtimestamp(now)
        kind = pend["kind"]
        with self.lock:
            first = pend.get("apology_first")
            if first and kind != "apology":     # 先に送った謝罪に返してから, 新しい方に返す
                self._chat_reply(char, st, {"kind": "apology", "t": first["t"], "meta": first["meta"]}, now - 1)
            ctx = self.context(char, st, dt)
            if kind == "appoint":               # 約束の誘いへの返事
                key, eff, extra = self.appoint.reply(char, st, pend, now, ctx)
            else:
                ctx["_meta"] = pend.get("meta") or {}
                ctx["_sent"] = pend.get("kind_t") or pend.get("t")
                ctx["_after_apology"] = bool(first)       # 謝罪と同じ返事待ちのうちに送ったお礼
                key, eff, extra = self.chat.reply(char, st, kind, now, ctx)
            raw_eff = dict(eff)
            eff, _ = self.bonds.realize(char, st, eff, "_chat_" + kind, now)
            self.trace.add("reply", "返信の中身: %s" % key, cid, now, kind=kind, eff=raw_eff, realized=eff, too_often=ctx.get("too_often"),
                           contacts=ctx.get("contacts_24h"), tolerance=self.bonds.tolerance(char, cid, st, now),
                           mood=st["params"].get("mood"), affection=st["params"].get("affection"), trust=st["params"].get("trust"))
            self.bonds.touch(st, now)
            self.bonds.met(st, now, contact=True)
            st["last_interaction"] = now
            deltas = self.apply_effects(st, self.trait_effects(char, eff))
            text = self.chat.line(char, key, extra)
            selfie = key == "selfie_yes" or (
                key not in ("too_often", "late_night", "tease_hurt", "flirt_cold", "apology_confused", "selfie_no", "selfie_pester")
                and random.random() < self.bonds.selfie_chance(ctx) * (1.5 if kind == "photo" else 1.0))
            self.chat.add(cid, "her", text + ("\n（📷 自撮りが添えられていた）" if selfie else ""), kind=key, t=now, selfie=selfie)
            if selfie:
                self.manners.favor(st, "selfie", now)       # 自撮りを送ってくれた (お礼の心当たり)
            self.manners.saw_down(st, now)
            if key not in ("too_often", "late_night"):
                self.picked_up_phone(char, st, now)
            if key == "invite_yes":
                self.chat.add(cid, "sys", "📅 会おうという話になった（半日のうちに約束すれば、応じてもらいやすい）", kind="promise", t=now + 0.001)
            if key == "favor_yes":
                self.chat.add(cid, "sys", "📅 約束した: %s %sの家で%s" % (extra["when"], char.get("name", ""), extra.get("what", "")),
                              kind="promise", t=now + 0.001)
            if key == "appoint_yes":
                self.chat.add(cid, "sys", "📅 約束した: %s %s" % (extra["when"], extra["place"]), kind="promise", t=now + 0.001)
            scene = self.scene_at(char, st, dt)
            act = {"id": "_chat", "name": "返信", "icon": "📱",
                   "pos": "selfie, holding smartphone, looking at viewer, upper body, smile" if selfie else "", "neg": ""}
            pos, neg, parts = self.build_prompt(char, st, dt, act)
            e = self._new_entry(cid, now, act, text + ("\n（📷 自撮りが添えられていた）" if selfie else ""), deltas, scene, dt, pos, neg, parts)
            e["reply"] = True
            if selfie:
                e["selfie"] = True
                if self.settings.get("auto_generate"):
                    e["job"] = self._present_image(cid, e)
            self.save_state(cid)
            self.save_log(cid)
        return {"cid": cid, "name": char.get("name", ""), "text": text, "late": now - pend["t"] > 3600}

    def her_says(self, cid, text, name, icon, now=None):
        """そばにいる相手が話しかけてきた一言を記録に残す (頼まれごとを対面で頼まれた など)."""
        now = now or time.time()
        char = self.chars[cid]
        st = self.state(cid)
        dt = datetime.fromtimestamp(now)
        scene = self.scene_at(char, st, dt)
        act = {"id": "_say", "name": name, "icon": icon, "pos": "talking, looking at viewer", "neg": ""}
        pos, neg, parts = self.build_prompt(char, st, dt, act)
        e = self._new_entry(cid, now, act, text, {}, scene, dt, pos, neg, parts)
        self.save_log(cid)
        return e

    def _contacts_view(self):
        """スマホの連絡先 (連絡先を知っていて, いまそばにいない人. 出かけている同居相手も)."""
        return [{"id": cid, "name": c.get("name", ""), "stage": self.bonds.stage(cid)} for cid, c in self.chars.items()
                if self.bonds.stage(cid) != "known" and not self.bonds.together(cid)]

    # ------------------------------------------------------------------ あなたの 1 本の時系列・関係性
    def timeline(self, who=None, offset=0, limit=60, images_only=False):
        """あなたの 1 本の時系列: 誰かとの記録 (各キャラのログ) と一人の時間の記録 (mylog) を時刻順に. 新しい順の
        (items, total). who: キャラの id ならその人との記録だけ, "me" なら一人の時間だけ, None なら全部."""
        items = []
        if who in (None, "", "me") and not images_only:
            items += [self._my_view(e) for e in self.solo.mylog()]
        if who != "me":
            for c in ([who] if who in self.chars else list(self.chars) if not who else []):
                name = self.chars[c].get("name", "")
                for e in self.log(c):
                    if images_only and not e.get("images"):
                        continue
                    x = dict(e, who=c, who_name=name)
                    x.pop("parts", None)
                    items.append(x)
        items.sort(key=lambda x: -x["t"])
        return items[offset:offset + limit], len(items)

    def log_entry(self, eid, cid=None):
        """記録を id で探す (誰との記録か分からなければ全員から). (cid, 記録) か (None, None)."""
        for c in ([cid] if cid in self.chars else []) + [c for c in self.chars if c != cid]:
            e = self.find_entry(c, eid)
            if e:
                return c, e
        return None, None

    def people_view(self, now=None):
        """関係性: このワールドで知っている人全員. 間柄・最後に会った日 / 連絡した日・あなたが知っていること
        (好きなもの・聞いた話)・貸し借り・取り決め. 様子 (params) は見た目の印象用 (そばにいない人は画面で「？」)."""
        now = now or time.time()
        ps = self.life.player_state()
        out = []
        for cid, c in self.chars.items():
            st = self.state(cid)
            b = self.bonds.view(cid)
            self.bonds.remember(c, st, now)
            out.append({"id": cid, "name": c.get("name", ""), "stage": b["stage"], "stage_label": b["stage_label"],
                        "mode": b["mode"], "label": b["label"], "face": self.chat.face(cid),
                        "last_met": st.get("last_met") or (st.get("last_touch") if b["stage"] == "live" else None),
                        "last_contact": st.get("last_contact"), "last_touch": st.get("last_touch"),
                        "known": list(reversed([k for k in st.get("known") or [] if k.get("kind") != "schedule"]))[:12],
                        "sched": list(reversed(self.knowsched.view(c, st, now))),
                        "owed": int((ps.get("loans") or {}).get(cid, 0)),
                        "living_policy": c.get("living_policy") or "split" if b["stage"] == "live" else None,
                        "pay_policy": c.get("pay_policy") or "auto",
                        "params": {k: round(v, 1) for k, v in st["params"].items()},
                        "pending_msg": bool(st.get("msg_pending"))})
        rank = {"live": 0, "visit": 1, "contact": 2, "known": 3}
        out.sort(key=lambda x: (not x["mode"], rank.get(x["stage"], 9), -(x["last_touch"] or 0)))
        return out

    def deliver_due(self, now=None):
        """時間差の返信: 期限が来て, 相手が寝ていない・手が離せないなら返信が届く (来ないと決まっていれば読むだけ).
        届いた返信 [{cid, name, text}] を返す."""
        now = now or time.time()
        out = []
        for cid in list(self.chars):
            st = self.state(cid)
            pend = st.get("msg_pending")
            if not pend or now < pend.get("due", 0):
                continue
            if now - pend["t"] > 24 * 3600:          # 一日たっても返ってこなければ, もう来ない
                st.pop("msg_pending", None)
                self.save_state(cid)
                self.trace.add("deliver", "一日たったので返事は来ないことに", cid, now, kind=pend.get("kind"), sent=pend["t"])
                continue
            char = self.chars[cid]
            self.tick(cid, now)
            scene = self.scene_at(char, st, datetime.fromtimestamp(now))
            if scene["asleep"] or scene["busy"]:       # 寝ている・入浴中・仕事中など: 落ち着いてから
                pend["due"] = now + random.uniform(15, 40) * 60
                self.save_state(cid)
                if self.trace.every("defer:" + cid, 1800, now):
                    self.trace.add("deliver", "延期 (寝ている・手が離せない)", cid, now, scene=scene.get("label"), new_due=pend["due"])
                continue
            st.pop("msg_pending", None)
            self.trace.add("deliver", "読んだ" + ("・返信する" if pend.get("reply") else "・返事はしない (既読だけ)"), cid, now,
                           kind=pend.get("kind"), sent=pend["t"], late_min=(now - pend["t"]) / 60.0, nudge=pend.get("nudge"))
            self.chat.mark_read_by_her(cid, now)       # 既読
            if pend.get("nudge"):
                self._nudge_seen(char, st, pend, now)
            if not pend.get("reply"):
                self.save_state(cid)                   # 読んだが, 返事はしなかった (既読だけ)
                continue
            if pend.get("kind"):
                out.append(self._chat_reply(char, st, pend, now))
                continue
            try:
                r = self.act(pend["aid"], cid, opts={"deliver": True, "ctx": {"callback": bool(pend.get("callback"))}})
            except (ValueError, KeyError):
                self.save_state(cid)
                continue
            e = r["entry"]
            e["action_name"], e["icon"], e["reply"] = ("折り返し" if pend.get("callback") else "返信"), "📱", True
            self.save_log(cid)
            self.chat.add(cid, "her", e["text"], kind="callback" if pend.get("callback") else "reply", t=now)
            self.picked_up_phone(char, self.state(cid), now)
            self.save_state(cid)
            out.append({"cid": cid, "name": char.get("name", ""), "text": e["text"], "late": now - pend["t"] > 3600})
        return out

    def _act_money(self, char, st, a, r, plan, req, extra):
        """行動に伴うお金の出入り. 断られた (override) ときは動かさない. 動いた額 {p, a} を返す."""
        money = {}

        def add(m):
            for k, v in m.items():
                money[k] = money.get(k, 0) + v

        if r.get("override"):
            if a.get("request_answer"):
                st["request"] = None
            return money
        L = self.life
        name = char.get("name", "")
        if plan:        # 費用 (お出かけ・料理の材料・プレゼントなど): 家計簿では, 誰かと使ったお金は交際費, 食べ物は食費
            cat = a.get("ledger") or ("food" if a.get("category") == "お世話" else "social")
            add(L.move(st, plan["p"], plan["a"], cat=cat, note="%s（%s）" % (a.get("name", ""), name)))
        if a.get("earn"):
            for who, rng in a["earn"].items():
                amt = life._amount(rng)
                add(L.move(st, dp=amt, cat="income", note=a.get("name", "")) if who == "p" else L.move(st, da=amt))
                extra["amount"] = format(amt, ",")
        tr = a.get("transfer")
        if tr:
            amt = int(tr.get("amount", 0))
            if tr.get("from") == "a":
                amt = min(amt, max(L.her_money(st)["a"], 0))
            if amt:
                add(L.move(st, dp=-amt, da=amt, cat="social", note="%sに%s" % (name, a.get("name", ""))) if tr.get("from") == "p"
                    else L.move(st, dp=amt, da=-amt, cat="borrow", note="%sから" % name))
            extra["amount"] = format(amt, ",")
        ans = a.get("request_answer")
        if ans and req:
            amt = int(req.get("amount", 0))
            if ans == "yes":
                if req["kind"] == "money":
                    add(L.move(st, dp=-amt, da=amt, cat="social", note="%sに貸した" % name))
                elif req["kind"] == "gift":
                    add(L.move(st, dp=-amt, cat="social", note="%sに買ってあげた" % name))
                elif req["kind"] == "treat":
                    add(L.move(st, da=-min(amt, max(L.her_money(st)["a"], 0))))
            st["request"] = None
        return money

    def _act_reasons(self, char, st, a, r, deltas, now):
        """機嫌の理由: 聞いた (ask) / 相談にのった (comfort) / 謝った (apologize) を反映し,
        それ以外の行動で機嫌が大きく動いたら, あなたの行動を理由として記録する."""
        L = self.life
        rr = r.get("reason")
        if rr and rr.get("tell"):          # 反応に理由が書いてあれば, それを記録する (例: 黙っていなくなった)
            L.add_reason(st, "player", rr.get("mood", "bad"), rr["tell"].replace("{call}", self.pronouns(char)[2]), now,
                         told=True, delta=deltas.get("mood", 0), action=a.get("id"))
            return
        ma = a.get("mood_action")
        if ma:
            if r.get("override"):           # はぐらかされた・逆効果: 理由は分からないまま
                return
            if ma == "ask":
                untold = [x for x in L.reasons(st, now) if not x["told"]]
                L.mark_told(untold[0] if untold else L.dominant(st, now))
            elif ma == "comfort":
                bad = L.dominant(st, now, "bad")
                if bad and bad["kind"] == "event":
                    L.mark_told(bad)
                    L.resolve(st, "bad", now, kind="event")       # 相談で和らぐのは出来事の理由だけ (あなたのせいの分は残る)
            elif ma == "apologize":     # 許し方 (すぐ / 半分 / 態度で / 受け付けない / 今さら) は manners. 消えるのは あなたのせいの理由だけ
                v = getattr(self, "_apol", None) or self.manners.apology(char, st, now, face=True)
                self._apol = None
                self.manners.apply_apology(char, st, v, now)
            return
        if a.get("request_answer") or a.get("category") == "system":
            return
        L.note_player_reason(char, st, a, deltas, now, self.pronouns(char)[2])

    # ------------------------------------------------------------------ image reuse
    @staticmethod
    def prompt_key(pos, neg):
        """同一プロンプト判定のキー (generatw と同じく pos+neg の MD5)."""
        return hashlib.md5((pos + neg).encode("utf-8")).hexdigest()

    def _load_index(self):
        """プロンプト → 生成済み画像の索引 (全ワールド共通). 無ければ全ワールドのログから作り直す."""
        idx = store.load(store.dpath("images", "index.json"))
        if idx is None:
            idx = {}
            for f in glob.glob(store.dpath("worlds", "*", "log", "*.json")):
                for e in store.load(f, []):
                    for im in e.get("images") or []:
                        idx.setdefault(self.prompt_key(im.get("pos", ""), im.get("neg", "")), []).append(
                            {"path": im["path"], "seed": im.get("seed"), "t": im.get("t")})
            store.save(store.dpath("images", "index.json"), idx)
        self.img_index = idx

    def existing_images(self, pos, neg):
        """同じプロンプトで生成済みの画像 (ファイルが残っているもの)."""
        items = self.img_index.get(self.prompt_key(pos, neg)) or []
        return [im for im in items if os.path.exists(store.dpath("images", *im["path"].split("/")))]

    def _present_image(self, cid, entry):
        """設定に従い, 既存画像をすぐ表示するか / 新規生成するかを決める. 生成したらジョブ id を返す."""
        self.make_icon(cid)      # まだ顔のアイコンがない人 (以前からいる人も) は, 画像を出すついでに一度だけ
        ic = self.settings.get("images") or {}
        mode = ic.get("mode", "reuse")
        # 生成中 (実行中 or 待ちあり) なら, 既存画像があればそれで済ませて待たせない
        busy = ic.get("busy_reuse", True) and self.generating()
        have = self.existing_images(entry["pos"], entry["neg"]) if (mode == "reuse" or busy) else []
        entry["same_prompt"] = len(have)
        if have:
            im = random.choice(have)
            entry["image"], entry["seed"], entry["reused"] = im["path"], im.get("seed"), True
            if busy:
                entry["busy_skip"] = True
                return None   # 生成中なので新規生成はしない
        limit = int(ic.get("max_per_prompt", 8))
        if mode == "reuse" and have and len(have) >= limit:
            return None   # 上限に達しているので生成しない
        job = self.enqueue(cid, entry["id"], entry["pos"], entry["neg"])
        entry["job"] = job
        return job

    # 顔だけのアイコン: トーク・関係性・そばにいる人の欄に出す顔. 一度だけ作って定義に固定する (char["icon"]).
    # キャラの外見 (定義の pos/neg) + 顔だけのタグ. 共通プロンプト・場面・服・表情は入れない (足すタグに画質のタグも含める).
    # 足すタグは設定の images.icon_pos / icon_neg で変えられる
    ICON_POS = "portrait,looking at viewer,simple background,1girl,solo,masterpiece,best quality,amazing quality"
    ICON_NEG = "full body,wide shot,multiple views,worst quality,bad quality,(monochrome),3d,(shiny skin:1.2),worst detail,text,logo,cropped,deformed,blurry,sketch,censor"

    def icon_prompt(self, char):
        ic = self.settings.get("images") or {}
        pos = join_tags([char.get("pos", ""), ic.get("icon_pos") or self.ICON_POS])
        neg = join_tags([char.get("neg", ""), ic.get("icon_neg") or self.ICON_NEG])
        return pos, neg

    def icon_job(self, cid):
        """作っている途中のアイコンのジョブ (無ければ None)."""
        return next((j["id"] for j in self.jobs.values()
                     if j.get("kind") == "icon" and j["cid"] == cid and j["status"] in ("queued", "running")), None)

    def make_icon(self, cid, force=False):
        """顔だけのアイコンを作る. force でなければ, すでにある・作っている途中・画像の自動表示が切れているときは作らない.
        設定の「作り直す」(force) は自動表示の設定によらず作る. ジョブ id を返す."""
        c = self.chars.get(cid) or store.all_characters().get(cid)
        if not c:
            raise KeyError("キャラの定義が見つかりません: %s" % cid)
        cur = self.icon_job(cid)
        if cur:
            return cur
        if not force:
            if not self.settings.get("auto_generate") or self.has_icon(c) or cid in self._icon_tried:
                return None
        self._icon_tried.add(cid)       # 失敗しても, 一回の起動では作り直しを繰り返さない (作り直すは設定から)
        pos, neg = self.icon_prompt(c)
        return self.enqueue(cid, None, pos, neg, kind="icon")

    def make_person_icon(self, pid, force=False):
        """出先で会った, まだ登録していない人 (people.json) の顔のアイコンを一度だけ作る. できたらその人の記録に固定し,
        知り合いになって登録したら, キャラの定義に引き継ぐ (作り直さない). 登録済みならキャラのアイコン."""
        pr = self.street.people().get(pid)
        if not pr:
            raise KeyError("その人が見つかりません: %s" % pid)
        if pr.get("cid"):
            return self.make_icon(pr["cid"], force)
        cur = next((j["id"] for j in self.jobs.values() if j.get("kind") == "icon_person" and j["entry"] == pid
                    and j["status"] in ("queued", "running")), None)
        if cur:
            return cur
        if not force:
            if not self.settings.get("auto_generate") or self.has_icon(pr) or ("p:" + pid) in self._icon_tried:
                return None
        self._icon_tried.add("p:" + pid)
        pos, neg = self.icon_prompt(pr["char"])
        return self.enqueue("_people", pid, pos, neg, kind="icon_person")

    def _set_person_icon(self, j, rel):
        """できた, 登録していない人のアイコンを people.json (作ったときのワールド) に固定する."""
        with self.lock:
            f = store.dpath("worlds", j["wid"], "people.json")
            ppl = store.load(f, {}) or {}
            if j["entry"] in ppl:
                ppl[j["entry"]]["icon"] = rel
                store.save(f, ppl)

    @staticmethod
    def has_icon(c):
        p = c.get("icon")
        return bool(p) and os.path.exists(store.dpath("images", *p.split("/")))

    def _set_icon(self, j, rel):
        """できたアイコンを定義に固定する (全ワールド共通)."""
        with self.lock:
            c = store.all_characters().get(j["cid"])
            if not c:
                return
            c["icon"], c["icon_seed"] = rel, j["seed"]
            store.save_character(c)
            if j["cid"] in self.chars:
                self.chars[j["cid"]]["icon"], self.chars[j["cid"]]["icon_seed"] = rel, j["seed"]

    def make_sample(self, oid):
        """服の一覧の, 服装のサンプル画像を作る (サンプルのキャラに着せる. できたら一覧に保存). ジョブ id を返す."""
        o = self.wardrobe.get(oid)
        if not o:
            raise KeyError("服が見つかりません: %s" % oid)
        cur = next((j["id"] for j in self.jobs.values() if j.get("kind") == "sample" and j["entry"] == oid
                    and j["status"] in ("queued", "running")), None)
        if cur:
            return cur
        pos, neg = self.wardrobe.sample_prompt(o)
        return self.enqueue("_outfits", oid, pos, neg, kind="sample")

    def generating(self):
        """生成ジョブが実行中か待ち行列にあるか."""
        return any(j["status"] in ("queued", "running") for j in self.jobs.values())

    def reroll(self, entry_id, cid=None):
        """同じプロンプトの既存画像から別の 1 枚を選び直す."""
        with self.lock:
            cid, e = self.log_entry(entry_id, cid)
            if not e:
                raise KeyError("記録が見つかりません")
            char = self.chars[cid]
            have = self.existing_images(e["pos"], e["neg"])
            if not have:
                raise ValueError("このプロンプトの画像はまだありません")
            others = [im for im in have if im["path"] != e.get("image")] or have
            im = random.choice(others)
            e["image"], e["seed"], e["reused"] = im["path"], im.get("seed"), True
            e["same_prompt"] = len(have)
            self.save_log(char["id"])
            return {"entry": e}

    def drop_in(self, cid, now=None):
        """外出の行き先として, 約束なしに相手 (家に行ける仲) の家を訪ねる. 在宅か (本人の予定)・出てくるか・迎えてくれるか
        (仲・機嫌・性格・時間帯・手が離せないか) しだい. 迎えてくれたら相手の家で過ごす (visit). 留守・断られたら, そのまま外にいる."""
        now = now or time.time()
        with self.lock:
            char = self.char(cid)
            cid = char["id"]
            if self.bonds.stage(cid) != "visit":
                raise ValueError("%sの家は知りません（家に行ける仲になってから）" % char.get("name", ""))
            p = self.presence.rec()
            if p.get("mode") not in ("none",) and self.presence.at(now) not in ("here", "idle"):
                raise ValueError("いまは出かけられません（%s）" % self.presence.view(now)["label"])
            self.tick(cid, now)
            st = self.state(cid)
            dt = datetime.fromtimestamp(now)
            scene = self.scene_at(char, st, dt)
            ctx = self.context(char, st, dt, scene, view=False)        # 本人がいまどうしているか
            name = char.get("name", "")
            p = st["params"]
            key, eff = None, {}
            if scene["away"] or ctx["outing"]:
                text = "（%sの家を訪ねたが、留守のようだった）" % name
            elif scene["asleep"]:
                text = "（%sの家のインターホンを鳴らしたが、出てこなかった。寝ているのかもしれない）" % name
            elif scene["busy"] and random.random() < 0.6:
                text = "（%sの家のインターホンを鳴らしたが、出てこなかった）" % name
            else:
                ph = ctx.get("phase")
                pw = 0.35 + (p.get("affection", 50) - 50) / 100.0 + (p.get("trust", 50) - 50) / 150.0 \
                    + (p.get("mood", 50) - 50) / 150.0 - float(self.traits(char).get("caution", 0)) / 40.0 \
                    - (0.3 if ph in ("night", "midnight", "dawn") else 0.0) - (0.2 if scene["busy"] else 0.0)
                if random.random() < max(0.05, min(0.9, pw)):
                    key, eff = "drop.yes", {"loneliness": -8, "mood": 2, "affection": 1}
                else:
                    key, eff = "drop.no", {"mood": -2, "trust": -1}
                text = self.persona_text(char, key) or places_mod.LINES[key]
            if key:
                eff, _ = self.bonds.realize(char, st, eff, "_drop_in", now)
                self.bonds.touch(st, now)
                st["last_interaction"] = now
            deltas = self.apply_effects(st, self.trait_effects(char, eff)) if eff else {}
            if key == "drop.no":
                self.life.add_reason(st, "player", "bad", "%sが約束もなしに家に来た" % self.pronouns(char)[2], now, told=True,
                                     delta=deltas.get("mood", 0), action="_drop_in")
            e = self.note_entry(char, st, now, "_drop_in", "家を訪ねた", "🚪", text, deltas)
            self.save_state(cid)
            if key == "drop.yes":               # 迎えてくれた: 相手の家で過ごす (暮らしぶりが見える)
                e["text"] += "\n" + places_mod.home_glimpse(self, char, st)
                self.save_log(cid)
                self.bonds.start(cid, "visit", now)
                self.presence.touch(now)
                self.solo.note("visit", "%sの家を訪ねた" % name, now)
                return {"started": "visit", "label": "%sの家" % name, "act": {"entry": e, "job": None, "llm_error": None}}
            # 留守・出てこない・断られた: そのまま外にいる (近くをぶらぶら. 戻ると外出の結果)
            self.presence.declare("out", now)
            pr = self.presence.rec()
            pr["solo"] = {"kind": "out", "skill": None, "t": now}
            pr["place"] = "town"
            self.presence.save()
            self.solo.note("out", text.strip("（）"), now)
            return {"started": "out", "label": "外出中", "act": {"entry": e, "job": None, "llm_error": None}, "text": text}

    def note_entry(self, char, st, now, aid, name, icon, text, deltas=None):
        """画像を作らない記録 (お金のこと・家のことなど, そばで言われたひとこと). 記録を返す."""
        dt = datetime.fromtimestamp(now)
        scene = self.scene_at(char, st, dt)
        act = {"id": aid, "name": name, "icon": icon, "pos": "", "neg": ""}
        pos, neg, parts = self.build_prompt(char, st, dt, act)
        e = self._new_entry(char["id"], now, act, self.format_text(text, char, scene, dt), deltas or {}, scene, dt, pos, neg, parts)
        self.save_log(char["id"])
        return e

    def _new_entry(self, cid, now, a, text, deltas, scene, dt, pos, neg, parts):
        e = {"id": uuid.uuid4().hex[:12], "t": now, "action": a.get("id"), "action_name": a.get("name", ""),
             "icon": a.get("icon", ""), "text": text, "deltas": deltas, "scene": scene["label"],
             "location": scene["location"], "phase": self.phase_at(dt).get("label", ""),
             "pos": pos, "neg": neg, "parts": parts, "images": [], "image": None, "seed": None}
        if not self.bonds.together(cid):
            e["apart"] = True           # 離れていたときの記録 (相手がそのとき何をしていたかは, ログにも出さない)
        self.log(cid).append(e)
        return e

    def visit(self, cid=None):
        """開いたときの「おかえり」. 告げて離れていたなら, その戻り (仕事なら稼ぎも). 黙って閉じていたら一定時間で."""
        with self.lock:
            p = self.presence.rec()
            if p["mode"] in ("out", "work"):
                # 外出・仕事は画面を開いているあいだ続く. 開き直しただけ (心拍が途絶えていない) なら続き.
                # 閉じていたなら, もう outdoor.check_gap で家に帰っている
                return None
            if p["mode"] in presence_mod.AWAY_MODES or (p["mode"] == "busy" and self.presence.at(time.time() - 1) == "gone"):
                declared = True
            else:
                declared = False
        if declared:
            return self.come_back()
        live = self.bonds.living()
        if not live or self.bonds.mode(live) != "home":     # 「おかえり」は家にいる同居相手だけ
            return None
        char = self.chars[live]
        with self.lock:
            self.tick(live)
            st = self.state(live)
            absent = (time.time() - st.get("last_interaction", time.time())) / 3600.0
        pc = self.presence.ctx(time.time())
        silent = pc["left_mode"] == "gone" and not pc["said"]
        if absent < float(self.world.get("absent_greet_hours", 3)) and not (silent and absent >= 1):
            return None
        try:
            self.action("_return")
        except KeyError:
            return None
        return self.act("_return", char["id"], opts={"effects": self.silent_penalty(char, absent) if silent else {}})

    def silent_penalty(self, char, hours):
        """何も言わずにいなくなったぶんの機嫌・信頼の目減り (空けた時間・寂しさ・性格しだい)."""
        st = self.state(char["id"])
        k = float(self.traits(char).get("absence", 1)) * (0.4 + st["params"].get("loneliness", 30) / 100.0)
        eff = {"mood": -min(10.0, 2 + hours * 0.4) * k}
        if hours >= 3:
            eff["trust"] = -min(4.0, hours * 0.1) * k
        if hours >= 24:
            eff["affection"] = -min(3.0, hours / 24.0) * k
        return {key: round(v, 1) for key, v in eff.items()}

    # ------------------------------------------------------------------ generation
    def snapshot(self, cid=None, pos=None, neg=None, seed=None, entry_id=None):
        """手動生成. entry_id 指定ならその記録で再生成, 無ければ現在の様子を新規記録."""
        with self.lock:
            if entry_id:
                cid, e = self.log_entry(entry_id, cid)
                if not e:
                    raise KeyError("記録が見つかりません")
            else:
                cid = self.target(cid)
                if not cid:
                    raise ValueError("いまはそばに誰もいません（画像は、そばにいる人の様子だけを撮ります）")
                char = self.chars[cid]
                self.tick(cid)
                st = self.state(cid)
                now = time.time()
                dt = datetime.fromtimestamp(now)
                p2, n2, parts = self.build_prompt(char, st, dt)
                e = self._new_entry(cid, now, {"id": "_snapshot", "name": "スナップ", "icon": "📷"}, "",
                                    {}, self.scene_at(char, st, dt), dt, p2, n2, parts)
            if pos is not None:
                e["pos"] = pos
            if neg is not None:
                e["neg"] = neg
            job = self.enqueue(cid, e["id"], e["pos"], e["neg"], seed)
            e["job"] = job
            self.save_log(cid)
            return {"entry": e, "job": job}

    STAGE_LABEL = {"queued": "前のジョブ待ち", "prepare": "準備中", "submit": "ComfyUI へ送信中",
                   "comfy_queued": "ComfyUI のキュー待ち", "comfy_running": "ComfyUI で生成中",
                   "download": "画像を取得中", "done": "完了", "error": "失敗", "cancelled": "取り消し"}

    def jlog(self, j, msg, level="info"):
        """ジョブの経過を記録 (ジョブ内 / コンソール / data/server.log)."""
        now = time.time()
        j.setdefault("events", []).append({"t": now, "msg": msg, "level": level})
        del j["events"][:-40]
        line = "%s [%s] job %s (%s): %s" % (datetime.fromtimestamp(now).strftime("%m-%d %H:%M:%S"),
                                            level.upper(), j["id"][:6], j.get("action", ""), msg)
        self.logq.put(line)

    def _log_writer(self):
        # コンソールへの出力は別スレッドで行う (Windows のコンソールで範囲選択中は
        # 書き込みがブロックされるため, 生成ワーカーが道連れで止まらないように)
        while True:
            line = self.logq.get()
            try:
                with open(store.dpath("server.log"), "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass
            try:
                print(line, flush=True)
            except Exception:  # noqa: BLE001
                pass

    def _set_stage(self, j, stage, msg=None, level="info", **extra):
        j["stage"], j["stage_at"] = stage, time.time()
        if stage in ("done", "error", "cancelled"):
            j["finished"] = j["stage_at"]
        j.update({k: v for k, v in extra.items() if k != "quiet"})
        if msg and not extra.get("quiet"):
            self.jlog(j, msg, level)

    def enqueue(self, cid, eid, pos, neg, seed=None, kind="entry"):
        """生成ジョブを積む. kind: entry = ログ項目の画像 / icon = 顔だけのアイコン (できたら定義に固定)."""
        jid = uuid.uuid4().hex
        if seed in (None, "", -1):
            seed = random.randint(0, 2 ** 32 - 1)
        e = (self.find_entry(cid, eid) if eid and kind == "entry" else None) or {}
        j = {"id": jid, "kind": kind, "status": "queued", "stage": "queued", "cid": cid, "entry": eid, "wid": store.WORLD,
             "action": {"icon": "顔アイコン", "icon_person": "顔アイコン", "sample": "服のサンプル"}.get(kind) or e.get("action_name", ""), "pos": pos, "neg": neg, "seed": int(seed),
             "created": time.time(), "error": None, "image": None, "prompt_id": None, "queue_pos": None,
             "cancel": False, "events": []}
        self.jobs[jid] = j
        self.jlog(j, "受付 (アプリ内の待ち %d 件)" % (self.jobq.qsize()))
        self._ensure_worker()
        self.jobq.put(jid)
        # 古い完了済みジョブを掃除
        done = [x for x in self.jobs.values() if x["status"] in ("done", "error", "cancelled")]
        for x in sorted(done, key=lambda x: x["created"])[:-100]:
            self.jobs.pop(x["id"], None)
        return jid

    def _ensure_worker(self):
        t = getattr(self, "_worker_thread", None)
        if t is None or not t.is_alive():
            if t is not None:
                self.logq.put("%s [ERROR] 生成ワーカーが停止していたため再起動" % datetime.now().strftime("%m-%d %H:%M:%S"))
            self.worker = {"current": None, "since": time.time(), "restarts": getattr(self, "worker", {}).get("restarts", -1) + 1}
            self._worker_thread = threading.Thread(target=self._worker, daemon=True, name="gen-worker")
            self._worker_thread.start()

    def job_view(self, jid, detail=False):
        j = self.jobs.get(jid)
        if not j:
            return {"id": jid, "status": "unknown", "error": "サーバにこのジョブがありません（サーバ再起動など）"}
        now = j.get("finished") or time.time()
        ahead = sum(1 for x in self.jobs.values() if x["status"] == "queued" and x["created"] < j["created"])
        keys = ("id", "kind", "status", "stage", "cid", "entry", "action", "seed", "error", "image", "created",
                "prompt_id", "queue_pos")
        out = {k: j.get(k) for k in keys}
        out["stage_label"] = self.STAGE_LABEL.get(j.get("stage"), j.get("stage"))
        out["ahead"] = ahead
        out["elapsed"] = round(now - j.get("started", j["created"]), 1)
        out["waited"] = round(now - j["created"], 1)
        out["stage_elapsed"] = round(now - j.get("stage_at", j["created"]), 1)
        ev = j.get("events") or []
        out["last_event"] = ev[-1]["msg"] if ev else ""
        if detail:
            out["events"] = ev
        return out

    def jobs_view(self):
        t = getattr(self, "_worker_thread", None)
        w = dict(getattr(self, "worker", {}))
        w["alive"] = bool(t and t.is_alive())
        cur = self.jobs.get(w.get("current") or "")
        w["current_action"] = cur.get("action") if cur else None
        w["busy_for"] = round(time.time() - w.get("since", time.time()), 1)
        jobs = sorted(self.jobs.values(), key=lambda x: x["created"], reverse=True)[:30]
        c = self.settings.get("comfy") or {}
        return {"worker": w, "comfy_url": comfy.base_url(c), "use_proxy": bool(c.get("use_proxy")),
                "queue_len": self.jobq.qsize(), "jobs": [self.job_view(x["id"], detail=True) for x in jobs]}

    def cancel_job(self, jid=None, all_pending=False):
        n = 0
        for j in list(self.jobs.values()):
            if (all_pending or j["id"] == jid) and j["status"] in ("queued", "running"):
                j["cancel"] = True
                if j["status"] == "queued":
                    j["status"] = "cancelled"
                    self._set_stage(j, "cancelled", "取り消し（実行前）")
                    self._clear_entry_job(j, None)
                else:
                    self.jlog(j, "取り消し要求")
                n += 1
        return {"cancelled": n}

    def _job_entry(self, j, fn):
        """ジョブの元になったログ項目を fn(e) で書き換えて保存する.
        生成中にワールドを切り替えていたら, 元のワールドのログファイルを直接直す."""
        with self.lock:
            if j.get("wid", store.WORLD) == store.WORLD:
                e = self.find_entry(j["cid"], j["entry"])
                if e and fn(e) is not False:
                    self.save_log(j["cid"])
                return
            f = store.dpath("worlds", j["wid"], "log", j["cid"] + ".json")
            log = store.load(f, [])
            e = next((x for x in reversed(log) if x.get("id") == j["entry"]), None)
            if e and fn(e) is not False:
                store.save(f, log)

    def _clear_entry_job(self, j, error):
        if j.get("kind") in ("icon", "sample", "icon_person"):
            return
        def fn(e):
            if e.get("job") != j["id"]:
                return False
            e.pop("job", None)
            if error:
                e["error"] = error
        self._job_entry(j, fn)

    def _worker(self):
        while True:
            jid = self.jobq.get()
            j = self.jobs.get(jid)
            if not j or j["status"] != "queued":
                continue
            self.worker.update(current=jid, since=time.time())
            j["status"], j["started"] = "running", time.time()
            self._set_stage(j, "prepare", "処理開始（待ち %.1f 秒）" % (j["started"] - j["created"]))
            try:
                c = dict(self.settings.get("comfy") or {})
                if j.get("kind") == "icon":
                    # 顔のアイコンは丸く切り抜いて出すので, 縦長だと頭や顎が見切れる. 同じくらいの画素数の正方形で作る
                    side = int(round((int(c.get("width", 832)) * int(c.get("height", 1216))) ** 0.5 / 64.0)) * 64
                    c["width"] = c["height"] = side
                custom = None
                if c.get("workflow_mode") == "custom":
                    custom = store.load(store.dpath("workflow.json"))
                    if not custom:
                        raise RuntimeError("カスタムワークフローが未登録です")
                data, ext = comfy.generate(
                    c, j["pos"], j["neg"], j["seed"], custom,
                    report=lambda stage, msg, **kw: self._set_stage(j, stage, msg, **kw),
                    cancelled=lambda: j["cancel"])
                rel = "%s/%s_%s.%s" % (j["cid"], datetime.now().strftime("%Y%m%d_%H%M%S"), jid[:6], ext)
                full = store.dpath("images", *rel.split("/"))
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "wb") as f:
                    f.write(data)
                with self.lock:
                    self.img_index.setdefault(self.prompt_key(j["pos"], j["neg"]), []).append(
                        {"path": rel, "seed": j["seed"], "t": time.time()})
                    store.save(store.dpath("images", "index.json"), self.img_index)
                if j.get("kind") in ("icon", "sample", "icon_person"):
                    if j["kind"] == "icon":
                        self._set_icon(j, rel)
                    elif j["kind"] == "icon_person":
                        self._set_person_icon(j, rel)
                    else:
                        with self.lock:
                            self.wardrobe.set_sample(j["entry"], rel)
                    j["image"], j["status"] = rel, "done"
                    self._set_stage(j, "done", "完了 %s（%.1f 秒）" % (rel, time.time() - j["started"]))
                    continue

                def put(e):
                    e["image"], e["seed"], e["reused"] = rel, j["seed"], False
                    e.pop("error", None)
                    e.setdefault("images", []).append({"path": rel, "seed": j["seed"], "pos": j["pos"],
                                                       "neg": j["neg"], "t": time.time()})
                    e.pop("job", None)
                self._job_entry(j, put)
                j["image"], j["status"] = rel, "done"
                self._set_stage(j, "done", "完了 %s（%.1f 秒）" % (rel, time.time() - j["started"]))
            except comfy.Cancelled:
                j["status"] = "cancelled"
                self._set_stage(j, "cancelled", "取り消し（ComfyUI 側も中断を要求）")
                self._clear_entry_job(j, None)
            except Exception as ex:  # noqa: BLE001 - どんな失敗でもワーカーは止めない
                j["error"], j["status"] = str(ex), "error"
                self._set_stage(j, "error", "失敗: %s" % ex, level="error")
                self.trace.error("生成ワーカー job %s" % j.get("id", "")[:8], "%s: %s" % (type(ex).__name__, ex),
                                 tb=traceback.format_exc().rstrip(), cid=None, stage=j.get("stage"))
                self._clear_entry_job(j, str(ex))
            finally:
                self.worker.update(current=None, since=time.time())

    # ------------------------------------------------------------------ views
    def state_view(self, cid=None, beat=False, idle=None):
        """画面の 1 回の更新. あなたが中心: あなたの在席・一人の時間・お金・持ち物・スマホ, いまそばにいる人たち (company),
        「誰かと」の相手 (target. cid がそばにいればその人) の様子 (with), あなたの 1 本の時系列のログ.
        誰もそばにいなければ target / with は None."""
        replies = self.deliver_due()
        # 画面を閉じていた (心拍が途絶えた) なら, 外出はその時点で終わっていた: 家で静かに過ごしていた
        # (約束の場所にいたかどうかは, 家に帰ったあとで見る)
        gap = self.outdoor.check_gap() if beat else None
        appoint_events = self.appoint.live()            # 約束 (着いた・会えた・遅刻・すっぽかし・キャンセル・相手からの誘い)
        if beat:
            appoint_events += self.planner.live()       # 予定の時刻になった (画面を開いている間は知らせるだけで, 何もしない)
        with self.lock:
            now = time.time()
            for oid in self.bonds.company() or ([self.settings.get("active_character")] if self.settings.get("active_character") in self.chars else []):
                self.tick(oid, now)         # 先に, 心拍が途絶えていた間を「いない」として進める
            if beat:
                self.presence.beat(time.time(), idle)
            closed = self.outdoor.closing() if beat else None       # いる行き先が閉まったら出される
            street_auto = self.street.live()                 # 声をかけられたまま返事をしなかった: 無難な対応に
            street = self.outdoor.live() if beat else None     # 外出中の偶然の出会い (心拍のたびに)
            shop_done = self.solo.shop_tick() if beat else None  # 店にいて品を選び終えた: その場で買い物が済む
            workplace = self.knowsched.at_workplace() if beat else []   # 行き先で, 知り合いが店員として働いていた
            now = time.time()
            company = self.bonds.company(now)
            if beat:
                # そばにいる人は話しかけてくる. 離れている連絡先の人も, それぞれ自分の予定どおりに過ごしていて,
                # ときどきメッセージを送ってくる (「誰かと」で選んでいる相手に限らない)
                for oid in list(self.chars):
                    if oid not in company and self.bonds.stage(oid) == "known":
                        continue
                    self.tick(oid, now)
                    ost = self.state(oid)
                    if self.presence.live(self.chars[oid], ost, now):
                        self.save_state(oid)
                    if oid in company and self.posing.live(self.chars[oid], ost, now):
                        self.save_state(oid)
            company = self.bonds.company(now)
            tid = self.target(cid)
            dt = datetime.fromtimestamp(now)
            phase = self.phase_at(dt)
            log, log_total = self.timeline(limit=LOG_KEEP_IN_VIEW)
            pending = [self.job_view(j["id"]) for j in self.jobs.values()
                       if j.get("wid") == store.WORLD and j["status"] in ("queued", "running")]
            autos = [self.state(c).get("last_auto") for c in company if self.state(c).get("last_auto")]
            out = {
                "now": now, "phase": {"id": phase.get("id"), "label": phase.get("label", "")},
                "company": [self._company_item(c) for c in company], "target": tid,
                "with": self.person_view(tid, dt) if tid else None,
                "you": dict(self.life.player_view(), care=round(self.life.skill_soft("care"), 2)), "earn": self.earn.view(now), "kakeibo": self.kakeibo.view(now), "meal": self.body.view(now),
                "log": log, "log_total": log_total, "jobs": pending,
                "solo": self.solo.view(), "home": self.home.view(), "replies": replies, "outdoor": self.outdoor.view(), "gap": gap,
                "street": street, "items": self.items.view(), "shop_done": shop_done, "workplace": workplace,
                "appoints": self.appoint.view(), "appoint_events": appoint_events, "closed": closed, "plan": self.planner.view(now),
                "side_job": self.task_ready(now), "task_active": self.task_active(), "blocked": self.blocked_view(),
                "street_pending": self.street.view(), "street_join": self.street.join_view(), "street_auto": street_auto,
                "offline_report": self.offline.report(),
                "chat_unread": self.chat.unread_total(), "contacts": self._contacts_view(),
                "bonds": self.bonds.list_view(), "encounter": self.encounters.view(), "people": self.people_view(now),
                "presence": self.presence.view(now),
                "approaches": [x for x in (self._approach_item(c) for c in self.chars) if x],
                "auto": max(autos, key=lambda x: x["t"]) if autos else None,
            }
            return out

    def _company_item(self, cid):
        b = self.bonds.view(cid)
        return {"id": cid, "name": self.chars[cid].get("name", ""), "mode": b["mode"], "label": b["label"],
                "stage": b["stage"], "stage_label": b["stage_label"], "face": self.chat.face(cid)}

    def _approach_item(self, cid):
        """話しかけられている・メッセージが来て返事を待たれている (誰から)."""
        v = self.presence.pending_view(self.chars[cid], self.state(cid)) or self.posing.pending_view(self.chars[cid], self.state(cid))
        if v:
            v.update(cid=cid, name=self.chars[cid].get("name", ""))
        return v

    def person_view(self, cid=None, dt=None):
        """「誰かと」の相手の様子 (そばにいるので見える): 場面・状態・できること・着せ替え・ゲーム・お金のやりとり."""
        char = self.char(cid)
        cid = char["id"]
        st = self.state(cid)
        dt = dt or datetime.now()
        now = dt.timestamp()
        scene = self.scene_at(char, st, dt)
        ctx = self.context(char, st, dt, scene)
        return {"character": cid, "name": char.get("name", ""),
                "params": {k: round(v, 1) for k, v in st["params"].items()},
                "scene": {k: scene[k] for k in ("activity", "label", "location", "away", "asleep", "busy", "source")},
                "override_until": scene.get("until"),
                "tags": [{"param": t["param"], "label": t["label"]} for t in self.active_tags(ctx)],
                "available": self.available(char, st, dt), "absent": ctx["absent"],
                "dress": self._dress_view(char, st, scene, ctx), "wardrobe": self.wardrobe.owned(char),
                "posing": self.posing.view(char, st, now),
                "dress_reset_on_sleep": char.get("dress_reset_on_sleep", True),
                "games": self.games.view(char, st, ctx), "life": self.life.partner_view(char, st),
                "pending_msg": bool(st.get("msg_pending")), "bond": self.bonds.view(cid), "face": self.chat.face(cid),
                "approach": self.presence.pending_view(char, st),
                "peek": st.get("peek_until", 0) > now}

    def _dress_view(self, char, st, scene, ctx):
        try:
            da = self.action("_dress")
            can, why = cond.check(da.get("when", ""), ctx), da.get("when", "")
        except KeyError:
            can, why = False, "着せ替え用のコマンド (_dress) がありません"
        return {"current": (st.get("dress") or {}).get("id", ""), "wearing": scene["dress"], "self": bool(scene.get("self_picked")),
                "outfit": scene["outfit"], "fixed": scene["fixed_outfit"], "can": can, "why": why,
                "items": {o["id"]: cond.check(o.get("when", ""), ctx) for o in self.wardrobe.owned(char)}}

    # ------------------------------------------------------------------ 在席・働きかけ・仕事・投資
    def come_back(self, cid=None, at=None, quiet=False):
        """告げて離れていたところから戻る. 仕事なら, 働いた時間ぶんの稼ぎを受け取る.
        at: 戻った時刻 (心拍が途絶えていたときは最後の心拍). quiet: 誰の反応もなく, 結果だけ (画面を閉じていたとき).
        偶然の出会いは外出中に起きるので (outdoor.live), 戻ったときには判定しない."""
        with self.lock:
            wc = self.presence.rec().pop("work_contacts", 0)
            ll = self.presence.back(at)
            if not ll:
                raise ValueError("いまは離れていません")
            near = None if quiet else self.solo.near(cid)       # 戻った先にいる人 (家にいる同居相手・来ている人)
            if ll["mode"] != "work":
                solo = self.solo.finish(ll)          # 一人の時間 (休む・家事・研鑽・散歩・買い物) の結果
                if quiet:
                    return {"text": ((solo or {}).get("text") or "").strip("（）") or "出かけ先から帰った", "solo": solo}
                if not near:                         # 誰もいない: 出迎えはない. 一人の時間の結果だけ
                    r = self.my_entry("back", "戻る", "🏠", (solo or {}).get("text") or "（戻ってきた）")
                    r["solo"] = solo
                    return r
                r = self.act("_back", near)
                r["solo"] = solo
                return r
            if ll.get("job") == "parttime":
                return self._back_parttime(ll, near, quiet, wc)
            if ll.get("job") in ("gig", "favor"):
                return self._back_task(ll, near, quiet)
            pay, h, raw = self.life.work_pay(ll["t"], ll["back"], record=True)
            work_note = ""
            if wc > 2:       # 仕事中にしょっちゅうスマホを見ていた: 効率が落ちて, 評価にも響く
                pay = int(pay * max(0.6, 1 - 0.05 * (wc - 2)) / 10) * 10
                work_note = "仕事中の連絡が多く、はかどらなかった" + ("（注意された）" if wc >= 5 else "")
            mv = self.life.move(None, dp=pay, cat="income", note="給料") if pay else {}
            gain = self.life.train("work", 0.5 * h) if h >= 0.25 else 0
            self.life.tire(float(self.world.get("economy", {}).get("stamina_per_work_hour", 9)) * h)
            if quiet or not near:
                text = "仕事を終えて帰った（%s円）%s" % (format(pay, ","), "。" + work_note if work_note else "")
                if quiet:
                    return {"text": text, "pay": pay}
                r = self.my_entry("work", "仕事から帰った", "💼", text, money=mv, skill={"work": gain} if gain else None)
                if work_note:
                    r["work_note"] = work_note
                return r
        r = self.act("work", near, opts={"money": mv, "extra": {"amount": format(pay, ",")},
                                               "ctx": {"work_h": round(raw, 2), "paid_h": round(h, 2), "pay": pay},
                                               "skill": {"work": gain}})
        if work_note:
            r["work_note"] = work_note
        return r

    def _back_parttime(self, ll, near, quiet, wc):
        """アルバイトから戻った: シフトと重なった分だけ. (誰かいれば「仕事から帰る」の反応)."""
        pt = self.earn.pt() or {}
        pay, h, gain = self.earn.pt_pay(ll["t"], ll["back"])
        note = ""
        if wc > 2:
            pay = int(pay * max(0.6, 1 - 0.05 * (wc - 2)) / 10) * 10
            note = "。バイト中の連絡が多く、注意された"
        mv = self.life.move(None, dp=pay, cat="income", note="バイト代") if pay else {}
        label = self.earn.job(pt["job"])["label"] if pt.get("job") else "アルバイト"
        text = ("%sのバイトを終えた（%s円）%s" % (label, format(pay, ","), note)) if h \
            else "バイト先に着いてすぐ、引き返してきた" if float(ll.get("h", 0)) < 0.25 \
            else "%sのバイトに行ったが、シフトの時間ではなかった" % self.places.label(ll.get("place") or "")
        if quiet:
            return {"text": text, "pay": pay}
        if not near:
            return self.my_entry("work", "バイトから帰った", "🧑‍💼", text, money=mv, skill={k: v for k, v in gain.items() if v} or None)
        return self.act("work", near, opts={"money": mv, "extra": {"amount": format(pay, ",")},
                                             "ctx": {"work_h": round(ll.get("h", 0), 2), "paid_h": round(h, 2), "pay": pay},
                                             "skill": gain})

    def _back_task(self, ll, near, quiet):
        """副業・頼まれごとから戻った (結果はあなたの記録. 誰かいれば「おかえり」)."""
        h = float(ll.get("h", 0))
        task = ll.get("task") or {}
        if ll["job"] == "gig":
            pay, text, gain = self.earn.gig_done(task, h, ll["back"])
            icon, name = "💡", "副業"
        else:
            pay, text = self.earn.favor_done(task, h, ll["back"])
            gain, icon, name = {}, "🤝", "頼まれごと"
        self.life.save_player()
        if quiet:
            return {"text": text, "pay": pay}
        r = self.my_entry("work", name, icon, text, money={"p": pay} if pay else None, skill={k: v for k, v in gain.items() if v} or None)
        if near:
            r["back"] = self.act("_back", near)
        return r

    def _go_task(self, job, task, text):
        now = time.time()
        if self.body.level() >= 3:
            raise ValueError("寝込むほどつらくて、出かけられそうにない（休むか、病院へ）")
        for oid in list(self.bonds.company()):        # そばにいる人には告げて (外で会っていたなら, そこで別れる)
            if self.bonds.mode(oid) not in ("home", "guest"):
                self.bonds.end()
                break
        self.presence.declare("work", now)
        p = self.presence.rec()
        p["job"], p["task"] = job, task
        self.presence.save()
        self.solo.note("work", text, now)
        self.life.save_player()
        return {"started": job, "label": text}

    def go_parttime(self, cid=None):
        """シフトの時間 (前後 30 分から) に, バイトに行く. 行き先はバイト先の店."""
        with self.lock:
            pt = self.earn.pt()
            if not pt:
                raise ValueError("アルバイトをしていません（求人から応募できます）")
            if not self.earn.shift_now():
                raise ValueError("いまはシフトの時間ではありません（%s）" % self.earn.shift_text(pt["shifts"]))
            if self.solo.near(cid):          # そばに誰かいれば「仕事に行ってくる」と告げて
                r = self.solo.start_plain("work", cid=cid)
            else:                            # 一人なら, シフトの時間に合わせて (夜のシフトも)
                if self.body.level() >= 3:
                    raise ValueError("寝込むほどつらくて、バイトに行けそうにない（休むか、病院へ）")
                if self.presence.rec().get("mode") != "none":
                    raise ValueError("いまは出かけられません（先に戻ってください）")
                now = time.time()
                self.presence.declare("work", now)
                self.solo.note("work", "バイトに出かけた", now)
                r = {"started": "work", "label": "バイトに行く", "act": None}
            p = self.presence.rec()
            p["job"] = "parttime"
            p["place"] = self.earn.job(pt["job"])["place"]
            self.presence.save()
            return r

    def earn_api(self, op, b):
        """稼ぎ方の操作 (アルバイトの応募・辞める)."""
        with self.lock:
            if op == "apply":
                r = self.earn.apply(b.get("job"), b.get("shifts"))
            elif op == "quit":
                r = self.earn.quit()
            elif op == "flea":
                x = self.earn.flea_list(b.get("item"), b.get("price") or 0)
                r = {"text": "%sを %s円で出品した" % (x["name"], format(x["price"], ","))}
            elif op == "flea_cancel":
                x = self.earn.flea_cancel(b.get("id"))
                r = {"text": "%sの出品を取り下げた" % x["name"]}
            elif op == "lotto":
                tk = self.earn.lotto_buy(b.get("n") or 1)
                r = {"text": "宝くじを%d枚買った" % tk["n"]}
            elif op == "gig":
                o = self.earn.gig_take(b.get("id"))
                r = self._go_task("gig", o, "%s（%s）に取りかかった" % (o["label"], o["client"]))
            elif op == "favor":
                f, said = self.earn.favor_answer(b.get("id"), bool(b.get("yes")))
                if said:
                    self.life.save_player()
                    r = {"text": said}
                else:
                    r = self._go_task("favor", f, "%sの%sに行った" % (self.chars[f["cid"]].get("name", ""), f["label"]))
            else:
                raise KeyError(op)
            return dict(r, earn=self.earn.view())

    def answer_encounter(self, yes):
        r = self.encounters.answer(yes)
        return r

    def answer_approach(self, ans, cid=None, choice=None):
        with self.lock:
            char = self.char(cid)
            st = self.state(char["id"])
            if not st.get("approach") and st.get("pose_offer"):      # 相手から見せてくれた・持ちかけてきた
                e = self.posing.answer(char, st, choice or ans, time.time())
                self.save_state(char["id"])
                return {"entry": e, "job": (e or {}).get("job")}
            ap = st.get("approach") or {}
            spec = (self.presence.find(ap.get("id")) or {}).get(ans) or {}
            aid = spec.get("action")
            if aid:           # 応じたら, そのコマンドをする (できない状況なら, ふつうに応じたことにする)
                try:
                    a = self.action(aid)
                    now = time.time()
                    ctx = self.context(char, st, datetime.fromtimestamp(now))
                    if not cond.check(a.get("when", ""), ctx) or (a.get("home_only") and ctx["outing"]):
                        aid = None
                except KeyError:
                    aid = None
            p = self.presence.rec()
            if ans == "accept" and p.get("mode") == "busy" and (p.get("solo") or {}).get("kind") in solo_mod.KINDS                     and not (self.presence.find(ap.get("id")) or {}).get("apart"):
                ll = self.presence.back()          # そばで話しかけられて応じた: 一人の時間はそこまで (結果は残す)
                if ll:
                    self.solo.finish(ll)
            e, run = self.presence.answer(char, st, ans, use_action=bool(aid), choice=choice)
        if run:
            return self.act(run, char["id"], opts={"approach": True})
        return {"entry": e, "job": e.get("job") if e else None}

    def force_approach(self, aid, cid=None):
        with self.lock:
            char = self.char(cid)
            st = self.state(char["id"])
            if st.get("approach"):
                st["approach"] = None
            now = time.time()
            d = datetime.fromtimestamp(now)
            e = self.presence.fire(char, st, now, self.context(char, st, d), force=aid)
            if not e:
                raise KeyError("働きかけが見つかりません: %s" % aid)
            self.save_state(char["id"])
            return {"entry": e, "job": e.get("job")}

    def repay(self, to, amount, cid=None):
        """借金・借りたお金を返す."""
        with self.lock:
            r = self.life.repay(to, amount)
        return dict(r, ok=True)

    def trade(self, asset, qty, cid=None):
        with self.lock:
            mv, amt, profit, reserved = self.life.trade(asset, qty)
        name = next((a.get("name", asset) for a in self.life.assets() if a["id"] == asset), asset)
        near = self.target(cid)
        if reserved:            # 取引時間外: 次の取引開始に売買する注文 (予約) を出しただけ
            mk = self.market.view()
            text = "取引時間外なので、%sを%s株%s注文を出した。次の取引開始は %s" % (
                name, format(abs(int(qty)), ","), "買う" if int(qty) > 0 else "売る", mk["next"])
            return self.my_entry("invest", "株の注文", "📈", text)
        if not near:            # 一人で: あなたの記録だけ
            text = "%sを%s株、%s円で%s" % (name, format(abs(int(qty)), ","), format(amt, ","), "買った" if int(qty) > 0 else "売った")
            if int(qty) < 0 and profit:
                text += "（%s%s円）" % ("+" if profit > 0 else "−", format(abs(profit), ","))
            return self.my_entry("invest", "株を買う" if int(qty) > 0 else "株を売る", "📈", text, money=mv)
        return self.act("invest_buy" if int(qty) > 0 else "invest_sell", near, opts={
            "money": mv, "ctx": {"profit": profit},
            "extra": {"amount": format(amt, ","), "profit": format(abs(profit), ","), "asset": name, "qty": format(abs(int(qty)), ",")}})

    def market_order(self, asset, side, qty, limit=None, days=None):
        """指値の注文 (limit 円以下で買う / 以上で売る. days 日のあいだ)."""
        with self.lock:
            o = self.market.order(asset, side, qty, limit, days)
            return {"order": o, "market": self.market.view()}

    def market_cancel(self, oid):
        with self.lock:
            self.market.cancel(oid)
            return {"market": self.market.view()}

    def market_plan(self, asset, amount=None, day=None, drop=None):
        """積立 (毎月 day 日に amount 円分). drop: 積立の id をやめる."""
        with self.lock:
            if drop:
                self.market.drop_plan(drop)
            else:
                self.market.set_plan(asset, amount, day)
            return {"market": self.market.view()}

    def task_start(self, kind, level="easy", cid=None):
        """内職 (パズル) を始める. 連続ではできない (コマンド side_job のクールダウン). 盤面はサーバで作る."""
        with self.lock:
            now = time.time()
            why = self.task_ready(now)
            if why:
                raise ValueError(why["reason"])
            if self.task_active():
                raise ValueError("やりかけの内職があります（続きから）")
        pz = puzzles.new(kind, level, extra=self.world.get("typing_extra"))      # 盤面づくり (スリザーリンクの難は数秒) の間は, ほかの操作を止めない
        with self.lock:
            if self.task_active():
                raise ValueError("やりかけの内職があります（続きから）")
            now = time.time()
            token = uuid.uuid4().hex[:10]
            tasks = self._task_store()
            tasks[token] = {"t0": now, "kind": kind, "puzzle": pz}
            self._task_save()
            self.presence.declare("busy", now)
            return self._task_info(token)

    def _task_store(self):
        """内職の作業 (このワールドの分). 再起動のあとは tasks.json から読む. 1 日たったものは捨てる."""
        if self._tasks_w != store.WORLD:
            now = time.time()
            self.tasks = {k: v for k, v in (store.load(store.wpath("tasks.json"), {}) or {}).items() if now - v.get("t0", 0) < 86400}
            self._tasks_w = store.WORLD
        return self.tasks

    def _task_save(self):
        store.save(store.wpath("tasks.json"), self._task_store())

    def task_active(self):
        """やりかけの内職 (いちばん新しいもの) の token. 無ければ None."""
        ts = self._task_store()
        return max(ts, key=lambda k: ts[k]["t0"]) if ts else None

    def _task_info(self, token):
        t = self._task_store()[token]
        pz = t["puzzle"]
        kind, level = pz["kind"], pz["level"]
        base = puzzles.base_pay(kind, level, self.world.get("economy", {}).get("side_job_rate_per_min"))
        mult = puzzles.skill_mult(kind, self.life.skill_mult)
        paused = puzzles.paused(t)       # 一時停止中は盤面を返さない (覗いて考えられないように)
        return {"token": token, "view": None if paused else puzzles.view(pz), "paused": paused, "skill": round(self.life.skill("work"), 1),
                "base": int(round(float(base) * mult / 10.0)) * 10, "par": puzzles.PAR[kind][level],
                "name": puzzles.KINDS[kind], "level_name": puzzles.LEVEL_LABEL[level], "desc": puzzles.DESC[kind],
                "elapsed": round(puzzles.elapsed(t), 1)}

    def task_pause(self, token, on=True):
        """内職の一時停止 (離席用) / 再開. 止めている間は経過時間に数えず, 盤面も返さない."""
        with self.lock:
            t = self._task_store().get(token)
            if not t:
                raise ValueError("作業が見つかりません（やり直してください）")
            (puzzles.pause if on else puzzles.unpause)(t)
            self._task_save()
            return self._task_info(token)

    def task_resume(self, token=None):
        """やりかけの内職の続き (盤面と経過時間)."""
        with self.lock:
            token = token or self.task_active()
            if not token or token not in self._task_store():
                raise ValueError("やりかけの内職はありません")
            self.presence.declare("busy", time.time())
            return self._task_info(token)

    def side_job_last(self):
        """最後に内職を終えた時刻 (あなたの記録. 以前はキャラの状態に残していたので, そちらも見る)."""
        ps = self.life.player_state()
        old = [max(self.state(c)["cooldowns"].get("side_job", [0]) or [0]) for c in self.chars]
        return max([float(ps.get("side_job_t", 0))] + old)

    def task_ready(self, now=None):
        """内職を始められないなら理由 {reason, wait (休憩の残り秒)}. 始められるなら None. 画面にも先に出す.
        内職はあなたのこと (誰がそばにいるかは関係ない. 家にいるかどうかと, 休憩・体力)."""
        now = now or time.time()
        if self.task_active():
            return None                      # やりかけがあれば, 続きから
        why = self.blocked("side_job")
        if why:
            return {"reason": why, "wait": 0}
        a = self.action("side_job")
        w = self.bonds.with_rec()
        if self.presence.rec().get("mode") not in ("none", "busy") or self.outdoor.current(now) or (w and w["mode"] in ("meet", "visit")):
            return {"reason": "いまは家にいないので内職できません", "wait": 0}
        if not cond.check(a.get("when", ""), self.you_context(datetime.fromtimestamp(now))):
            return {"reason": "今は内職できません", "wait": 0}
        cd = float(a.get("cooldown", 0)) * 60
        last = self.side_job_last()
        if cd and now - last < cd:
            return {"reason": "まだ疲れが残っています（あと%d分）" % math.ceil((last + cd - now) / 60), "wait": int(last + cd - now)}
        need = float(self.world.get("economy", {}).get("stamina_per_side_job", 10))
        if self.life.stamina() < need:
            return {"reason": "疲れていて作業できません（体力 %d / %d 必要）" % (self.life.stamina(), need), "wait": 0}
        return None

    def task_move(self, token, mv):
        """内職の一手. 答え合わせはここでする (ミス・できあがり)."""
        with self.lock:
            t = self._task_store().get(token)
            if not t:
                raise ValueError("作業が見つかりません（やり直してください）")
            if puzzles.paused(t):
                raise ValueError("一時停止中です（再開してから）")
            r = puzzles.task_move(t, mv)
            self._task_save()
            return dict(r, view=puzzles.view(t["puzzle"]), sec=round(puzzles.elapsed(t), 1))

    def task_finish(self, token, cid=None):
        """内職を終える (できあがっていても, 途中でやめても). 稼ぎ・体力・仕事スキル・キャラの反応."""
        with self.lock:
            t = self._task_store().get(token)
            if not t:
                raise ValueError("作業が見つかりません（やり直してください）")
            self.tasks.pop(token, None)
            self._task_save()
            pz = t["puzzle"]
            sec = puzzles.elapsed(t)              # 一時停止していた間は数えない
            e = self.world.get("economy", {})
            pay = puzzles.pay(pz, sec, puzzles.skill_mult(pz["kind"], self.life.skill_mult), e.get("side_job_rate_per_min"))
            mv = self.life.move(None, dp=pay, cat="income", note="内職") if pay else {}
            self.life.player_state()["side_job_t"] = time.time()
            solved = puzzles.solved(pz)
            gain = self.life.train("work", puzzles.TRAIN[pz["level"]] * (1.0 if solved else 0.3 * puzzles.progress(pz)))
            k2 = puzzles.SKILL_MIX.get(pz["kind"])          # タイピングは文章のスキルも少し伸びる
            gain2 = self.life.train(k2, 0.5 * puzzles.TRAIN[pz["level"]] * (1.0 if solved else 0.3 * puzzles.progress(pz))) if k2 else 0
            self.life.tire(float(e.get("stamina_per_side_job", 10)))
            p = self.presence.rec()
            if p["mode"] == "busy":
                p["mode"] = "none"
        fast = puzzles.fast(pz, sec)
        near = self.target(cid)
        task = {"solved": solved, "fast": fast, "miss": pz["miss"], "sec": round(sec), "pay": pay, "kind": pz["kind"],
                "level": pz["level"], "view": puzzles.view(pz, reveal=not solved)}
        if not near:                # 一人で: 黙々と. あなたの記録だけ
            r = self.my_entry("side_job", "内職", "🧵", "%sの内職を%s。%s円になった" % (
                puzzles.KINDS[pz["kind"]], "仕上げた" if solved else "途中でやめた", format(pay, ",")),
                money=mv, skill={k: v for k, v in (("work", gain), (k2, gain2)) if k and v} or None)
            r["task"] = task
            return r
        r = self.act("side_job", near, opts={
            "money": mv, "extra": {"amount": format(pay, ","), "ng": pz["miss"], "puzzle": puzzles.KINDS[pz["kind"]]},
            "ctx": {"task_solved": solved, "task_fast": fast, "task_miss": pz["miss"], "task_level": pz["level"], "pay": pay},
            "skill": {k: v for k, v in (("work", gain), (k2, gain2)) if k and v}})
        r["task"] = task
        return r

    def prompt_preview(self, cid=None):
        with self.lock:
            cid = self.target(cid)
            if not cid:
                raise ValueError("いまはそばに誰もいません")
            char = self.chars[cid]
            self.tick(char["id"])
            pos, neg, parts = self.build_prompt(char, self.state(char["id"]), datetime.now())
            return {"pos": pos, "neg": neg, "parts": parts}

    def boot_view(self):
        return {"settings": self.settings, "params": self.params, "worlds": self.worlds_view(), "relations": self.relations,
                "others": self.others_list(), "defs": self.defs_list(), "catalog": items_mod.Items.catalog(), "outfits": self.wardrobe.catalog_view(), "poses": self.posing.catalog_view(), "puzzles": puzzles.catalog(), "persona_likes": items_mod.PERSONA_LIKES,
                "routine": {"days": self.offline.cfg()["days"], "labels": offline_mod.DO_LABEL, "meal_how": offline_mod.MEAL_HOW, "meal_places": offline_mod.MEAL_PLACES}, "actions": self.actions, "world": self.world,
                "characters": [{"id": c["id"], "name": c.get("name", "")} for c in self.chars.values()],
                "character": self.char(), "placeholders": list(comfy.PLACEHOLDERS),
                "has_workflow": os.path.exists(store.dpath("workflow.json")), "minigames": self.minigames,
                "events": self.events, "approaches": self.approaches,
                "personas": [{k: p.get(k) for k in ("id", "name", "desc", "persona", "player_call", "first_person", "traits", "_custom")}
                             for p in sorted(self.personas.values(), key=lambda p: (
                                 PERSONA_ORDER.index(p["id"]) if p["id"] in PERSONA_ORDER else 99, p.get("name", "")))]}

    # ------------------------------------------------------------------ personas
    def persona_full(self, pid):
        p = self.personas.get(pid)
        if not p:
            raise KeyError("性格プリセットが見つかりません: %s" % pid)
        return {"persona": p, "keys": keys_mod.all_keys(self.actions, self.minigames, self.approaches)}

    def save_persona(self, p):
        with self.lock:
            if not p.get("id") or not re.match(r"^[A-Za-z0-9_-]+$", p["id"]):
                raise ValueError("id は英数字・_・- で指定してください")
            lines = p.get("lines") or {}
            if not isinstance(lines, dict):
                raise ValueError("lines の形式が違います")
            p["lines"] = {k: [t for t in (v if isinstance(v, list) else [v]) if str(t).strip()]
                          for k, v in lines.items()}
            p["lines"] = {k: v for k, v in p["lines"].items() if v}
            store.save_persona(p)
            self.personas = store.load_personas()
            return self.personas[p["id"]]

    def reset_persona(self, pid):
        with self.lock:
            f = store.dpath("personas", pid + ".json")
            if os.path.exists(f):
                os.remove(f)
            self.personas = store.load_personas()
            return {"exists": pid in self.personas}

    # ------------------------------------------------------------------ editing
    def save_settings(self, obj):
        with self.lock:
            obj = dict(obj)
            if "active_character" in obj and obj["active_character"] not in self.chars:
                obj.pop("active_character")
            self.settings = store.deep_merge(self.settings, obj)
            # あなたの名前は player.name に一本化 (古い player_name も同じ値にそろえておく)
            if "player_name" in obj and "player" not in obj:
                self.settings.setdefault("player", {})["name"] = obj["player_name"]
            self.settings["player_name"] = (self.settings.get("player") or {}).get("name") or self.settings.get("player_name", "")
            store.save_settings(self.settings)
            return self.settings

    def select_character(self, cid):
        self.char(cid)
        return self.save_settings({"active_character": cid})

    def save_character(self, c):
        with self.lock:
            if not c.get("id"):
                raise ValueError("id がありません")
            old = self.chars.get(c["id"]) or store.all_characters().get(c["id"])
            hist = list((old or {}).get("prompt_history") or [])
            if old and not hist:
                hist.insert(0, {"t": time.time() - 1, "pos": old.get("pos", ""), "neg": old.get("neg", "")})
            if not old or not hist or hist[0].get("pos") != c.get("pos") or hist[0].get("neg") != c.get("neg"):
                hist.insert(0, {"t": time.time(), "pos": c.get("pos", ""), "neg": c.get("neg", "")})
            c["prompt_history"] = hist[:200]
            for k in ("icon", "icon_seed"):      # 設定を開いている間にできた顔のアイコンを, 古い画面の保存で消さない
                if k not in c and (old or {}).get(k):
                    c[k] = old[k]
            if c["id"] in self.chars or c["id"] in store.load_cast():     # このワールドに現れている人だけ手元に
                self.chars[c["id"]] = c
            store.save_character(c)              # 定義は全体 (全ワールドに反映)
            return c

    NEW_STAGES = ("contact", "known", "absent", "random")

    def new_character(self, name, copy_from=None, stage="contact", pos=None, persona_id=None):
        """設定からキャラを追加する. stage: このワールドでのあなたとの間柄.
        contact = 連絡先を知っている / known = 知り合い / absent = このワールドには現れない (偶然の出会いを待つ) /
        random = くじ (新しいワールドを作るときと同じ割合). 同居はいきなりは選べない (仲を深めて提案する).
        どれを選んでも登録キャラになり, ほかのワールドでは出会いの候補・新しいワールドの顔ぶれの候補になる."""
        if stage not in self.NEW_STAGES:
            raise ValueError("間柄の指定が違います: %s" % stage)
        with self.lock:
            src = self.char(copy_from) if copy_from else self.char()
            cid = "c" + uuid.uuid4().hex[:8]
            p = self.personas.get(persona_id or "") or {}
            c = {"id": cid, "name": name or "新しいキャラ", "player_call": "", "first_person": "",
                 "persona_id": p.get("id", ""), "persona": p.get("persona", ""),
                 "pos": (pos or "").strip() or "1girl, solo", "neg": "", "outfit_default": src.get("outfit_default", ""),
                 "schedule": src.get("schedule", []), "default_activity": src.get("default_activity", {}),
                 "clothes": [{"id": i, "from": "default"} for i in wardrobe_mod.STARTER], "age": 20,
                 "prompt_history": [], "origin": {"type": "manual", "t": time.time(), "world": store.WORLD}}
            if stage == "random":
                ec = self.encounters.cfg()
                r = random.random()
                pc, pk = float(ec["start_contact"]), float(ec["start_known"])
                stage = "contact" if r < pc else "known" if r < pc + pk else "absent"
            self.save_character(c)                 # 定義は全体に (ほかのワールドでも出会い・顔ぶれの候補)
            if stage == "absent":
                return dict(c, _stage="absent")
            self.place_character(cid, stage)
            return dict(c, _stage=stage)

    # ---- キャラの定義は全体で 1 つ. ワールドには, そのうち現れている人 (顔ぶれ) の個体 (状態・ログ・間柄・関係) がある
    def defs_list(self):
        """キャラクターの定義全員 (全ワールド共通. どのワールドから見ても同じ). このワールドにいるか・どこに現れているか・どこから来たか."""
        worlds = store.load_worlds().get("worlds") or []
        wname = {w["id"]: w["name"] for w in worlds}
        casts = {w["id"]: store.load_cast(w["id"]) for w in worlds}
        defaults = set(store.default_character_ids()) if hasattr(store, "default_character_ids") else {"hina"}
        out = []
        for cid, c in store.all_characters().items():
            out.append({"id": cid, "name": c.get("name", ""), "persona_id": c.get("persona_id", ""), "pos": c.get("pos", ""),
                        "here": cid in self.chars, "stage": self.bonds.stage(cid) if cid in self.chars else None,
                        "worlds": [wname[w] for w, ids in casts.items() if cid in ids], "origin": self._origin(c, cid, wname, defaults)})
        out.sort(key=lambda x: (not x["here"], x["name"]))
        return out

    @staticmethod
    def _origin(c, cid, wname, defaults):
        """その定義がどこから来たか (なぞのキャラの出どころを確かめられるように)."""
        fmt = lambda t: datetime.fromtimestamp(t).strftime("%Y/%m/%d %H:%M") if t else "日時不明"  # noqa: E731
        met = c.get("met")
        if met:
            w = wname.get(met.get("world") or "", "")
            return "出会って登録（%s・%s%s）" % (fmt(met.get("t")), met.get("where") or "", "・" + w if w else "")
        org = c.get("origin") or {}
        if org.get("type") == "manual":
            w = wname.get(org.get("world") or "", "")
            return "設定で追加（%s%s）" % (fmt(org.get("t")), "・" + w if w else "")
        if cid in defaults:
            return "既定のキャラ"
        return "以前のデータから（いつ・どこで作ったかの記録なし）"

    def others_list(self):
        """このワールドにはまだ現れていない定義 (追加で「現れない」・くじで現れなかった人・ほかのワールドで作った人)."""
        here = set(self.chars)
        out = []
        for cid, c in store.all_characters().items():
            if cid not in here:
                out.append(dict(c, _worlds=[w["name"] for w in store.load_worlds().get("worlds") or []
                                            if cid in store.load_cast(w["id"])]))
        return out

    def place_character(self, cid, stage):
        """定義を, このワールドに出す (知り合い / 連絡先). 同居はいきなりは選べない."""
        if stage not in ("known", "contact"):
            raise ValueError("間柄の指定が違います: %s" % stage)
        with self.lock:
            c = store.all_characters().get(cid)
            if not c:
                raise KeyError("キャラの定義が見つかりません: %s" % cid)
            store.save_cast(store.load_cast() + [cid])
            self.chars[cid] = c
            self.bonds.set_stage(cid, stage)
            self.make_icon(cid)        # 顔のアイコン (まだ無ければ. 自動表示が切れていれば作らない)
            return dict(c, _stage=stage)

    def save_definition(self, c):
        """このワールドにいない定義を編集する (名前・性格・外見など. 全ワールドに反映)."""
        old = store.all_characters().get(c.get("id"))
        if not old:
            raise KeyError("キャラの定義が見つかりません: %s" % c.get("id"))
        old.update({k: v for k, v in c.items() if not k.startswith("_")})
        p2 = self.personas.get(old.get("persona_id") or "") or {}
        if "persona_id" in c and p2 and not c.get("persona"):
            old["persona"] = p2.get("persona", "")
        store.save_character(old)
        return old

    def delete_character(self, cid):
        """定義の抹消 (全ワールドに波及). どこかのワールドに現れている (知り合い・同居など) キャラは消せない. 変更はできる."""
        with self.lock:
            ws = store.worlds_with(cid)
            if ws:
                names = [w["name"] for w in store.load_worlds()["worlds"] if w["id"] in ws]
                raise ValueError("「%s」に現れているので削除できません（定義の変更はできます）" % "」「".join(names))
            if cid not in store.all_characters():
                raise KeyError("キャラの定義が見つかりません: %s" % cid)
            store.delete_character(cid)
            return {"ok": True}

    # ------------------------------------------------------------------ worlds
    def worlds_view(self):
        meta = store.load_worlds()
        return {"current": store.WORLD, "worlds": meta.get("worlds") or []}

    def create_world(self, name, copy_from=None, switch=True):
        """新しいワールド. copy_from を指定すればそのワールドの定義類とキャラ設定を複製 (状態・ログ・お金は引き継がない)."""
        with self.lock:
            meta = store.load_worlds()
            if copy_from and copy_from not in [w["id"] for w in meta["worlds"]]:
                raise KeyError("ワールドが見つかりません: %s" % copy_from)
            wid = "w" + uuid.uuid4().hex[:8]
            start = None
            if copy_from:
                store.init_world(wid, copy_from)
            else:
                # キャラの定義 (どのワールドで作ったかを問わない) から, くじで連絡先を知っている人・知り合いを決める
                cast, start = self.encounters.start_cast()
                store.init_world(wid, cast=cast)
            if copy_from:
                rel = store.load(store.dpath("worlds", copy_from, "relations.json"))
                if rel:
                    store.save(store.dpath("worlds", wid, "relations.json"), rel)
            # 新しいワールドでは, あなたは最初だれとも暮らしていない (登録したキャラとは連絡先を知っている仲)
            meta["worlds"].append({"id": wid, "name": (name or "").strip() or "新しいワールド", "created": time.time(), "alone": True})
            if start is not None:
                meta["worlds"][-1]["start_bonds"] = start
            store.save_worlds(meta)
            if switch:
                self.switch_world(wid)
            for cid in store.load_cast(wid):
                self.make_icon(cid)        # 最初から顔ぶれにいる人の顔のアイコン (まだ無ければ. 自動表示が切れていれば作らない)
            return {"id": wid, "worlds": self.worlds_view()}

    def export_world(self, wid=None, images=False):
        """セーブの書き出し (core/transfer.py). (ファイル名, zip) を返す."""
        with self.lock:
            fname, data, _ = transfer.export_world(wid or store.WORLD, images)
            return fname, data

    def import_world(self, data, name=None):
        """セーブの読み込み: いつも新しいワールドとして足す (切り替えはしない)."""
        with self.lock:
            r = transfer.import_world(data, name)
            self._load_index()                 # 足した画像を, 同じプロンプトの再利用に入れる
            r["worlds"] = self.worlds_view()
            return r

    def switch_world(self, wid):
        with self.lock:
            meta = store.load_worlds()
            if wid not in [w["id"] for w in meta["worlds"]]:
                raise KeyError("ワールドが見つかりません: %s" % wid)
            if wid == store.WORLD:
                return self.worlds_view()
            store.WORLD = wid
            store.init_world(wid)
            meta["current"] = wid
            store.save_worlds(meta)
            # ワールドごとの記憶を捨てて読み直す (生成中のジョブは元のワールドのログへ書き戻す)
            self.states, self.logs, self.tasks = {}, {}, {}
            self._tasks_w = None
            self.life.player = None
            self.reload()
            self.manners.rejudge_thanks()
            self.manners.retro_contacts()
            return self.worlds_view()

    def rename_world(self, wid, name):
        with self.lock:
            meta = store.load_worlds()
            for w in meta["worlds"]:
                if w["id"] == wid:
                    w["name"] = (name or "").strip() or w["name"]
                    store.save_worlds(meta)
                    return self.worlds_view()
            raise KeyError("ワールドが見つかりません: %s" % wid)

    def delete_world(self, wid):
        """ワールドを消す (キャラ設定・状態・ログ・お金). 画像は全体共通なので残す."""
        with self.lock:
            meta = store.load_worlds()
            ids = [w["id"] for w in meta["worlds"]]
            if wid not in ids:
                raise KeyError("ワールドが見つかりません: %s" % wid)
            if len(ids) <= 1:
                raise ValueError("最後のワールドは削除できません")
            if wid == store.WORLD:
                self.switch_world(next(i for i in ids if i != wid))
                meta = store.load_worlds()
            meta["worlds"] = [w for w in meta["worlds"] if w["id"] != wid]
            store.save_worlds(meta)
            shutil.rmtree(store.dpath("worlds", wid), ignore_errors=True)
            return self.worlds_view()

    # ------------------------------------------------------------------ relations (同じワールドのキャラ同士)
    def relation(self, a, b):
        """a から見た b. knows: 知っているか / kind: 関係 (自由記述) / affinity: 好感度 (0〜100)."""
        r = (self.relations.get(a) or {}).get(b) or {}
        return {"knows": bool(r.get("knows")), "kind": r.get("kind", ""), "affinity": float(r.get("affinity", 50))}

    def save_relations(self, cid, rels):
        """cid から見た他キャラとの関係をまとめて保存. rels: {b: {knows, kind, affinity}}."""
        with self.lock:
            self.char(cid)
            out = {}
            for b, r in (rels or {}).items():
                if b == cid or b not in self.chars:
                    continue
                out[b] = {"knows": bool(r.get("knows")), "kind": str(r.get("kind") or "").strip(),
                          "affinity": max(0.0, min(100.0, float(r.get("affinity", 50))))}
            self.relations[cid] = out
            store.save(store.wpath("relations.json"), self.relations)
            return self.relations

    def change_affinity(self, a, b, delta):
        """出来事などで a→b の好感度を動かす (知り合いになる)."""
        with self.lock:
            r = self.relation(a, b)
            r["knows"] = True
            r["affinity"] = max(0.0, min(100.0, r["affinity"] + delta))
            self.relations.setdefault(a, {})[b] = r
            store.save(store.wpath("relations.json"), self.relations)
            return r

    def relations_text(self, char):
        """LLM へ渡す「このキャラが知っている人」."""
        out = []
        for b, r in sorted((self.relations.get(char["id"]) or {}).items()):
            if not r.get("knows") or b not in self.chars:
                continue
            a = float(r.get("affinity", 50))
            feel = "大好き" if a >= 80 else "好意的" if a >= 60 else "普通" if a >= 40 else "苦手" if a >= 20 else "嫌い"
            out.append("%s（%s、%s）" % (self.chars[b].get("name", b), r.get("kind") or "知り合い", feel))
        return "、".join(out)

    def _check_conds(self, items, label):
        for it in items:
            try:
                cond.parse(it.get("when", ""))
            except ValueError as e:
                raise ValueError("%s: %s" % (label, e))

    def save_actions(self, actions):
        with self.lock:
            ids = [a.get("id") for a in actions]
            if any(not i for i in ids) or len(set(ids)) != len(ids):
                raise ValueError("行動 id が空か重複しています")
            for a in actions:
                self._check_conds([a] + list(a.get("reactions") or []), "行動「%s」" % a.get("name", a["id"]))
            self.actions = actions
            store.save(store.wpath("actions.json"), actions)
            return actions

    def save_params(self, params):
        with self.lock:
            ids = [p.get("id") for p in params]
            if any(not i for i in ids) or len(set(ids)) != len(ids):
                raise ValueError("パラメータ id が空か重複しています")
            for p in params:
                lab = "パラメータ「%s」" % p.get("name", p["id"])
                self._check_conds(p.get("rate_rules") or [], lab)
                self._check_conds(p.get("tags") or [], lab)
                self._check_conds((p.get("drift") or {}).get("mods") or [], lab)
            self.params = params
            store.save(store.wpath("params.json"), params)
            for cid in list(self.states):
                self.state(cid)
                self.save_state(cid)
            return params

    def save_world(self, world):
        with self.lock:
            self.world = world
            store.save(store.wpath("world.json"), world)
            return world

    def force_event(self, eid, cid=None):
        """テスト用: 出来事をいま起こす (条件・クールダウンは無視)."""
        with self.lock:
            char = self.char(cid)
            self.tick(char["id"])
            st = self.state(char["id"])
            rec = self.life.happen(char, st, time.time(), self.context(char, st, datetime.now()), force=eid)
            if not rec:
                raise KeyError("出来事が見つかりません: %s" % eid)
            self.save_state(char["id"])
            return rec

    def save_events(self, items):
        with self.lock:
            if not isinstance(items, list):
                raise ValueError("出来事は配列で指定してください")
            ids = [e.get("id") for e in items]
            if any(not i for i in ids) or len(set(ids)) != len(ids):
                raise ValueError("出来事の id が空か重複しています")
            self._check_conds(items, "出来事")
            self.events = items
            store.save(store.wpath("events.json"), items)
            return items

    def save_approaches(self, items):
        with self.lock:
            if not isinstance(items, list):
                raise ValueError("働きかけは配列で指定してください")
            ids = [e.get("id") for e in items]
            if any(not i for i in ids) or len(set(ids)) != len(ids):
                raise ValueError("働きかけの id が空か重複しています")
            self._check_conds(items, "働きかけ")
            self.approaches = items
            store.save(store.wpath("approaches.json"), items)
            return items

    def save_minigames(self, items):
        with self.lock:
            if not isinstance(items, list):
                raise ValueError("ミニゲーム定義は配列で指定してください")
            ids = [g.get("id") for g in items]
            if any(not i for i in ids) or len(set(ids)) != len(ids):
                raise ValueError("ミニゲームの id が空か重複しています")
            for g in items:
                if g.get("kind") not in games.KINDS:
                    raise ValueError("「%s」の kind は %s のどれかです" % (g.get("name", g["id"]), " / ".join(games.KINDS)))
                for k in ("require", "when"):
                    cond.parse(g.get(k, ""))
                for ev, lines in (g.get("lines") or {}).items():
                    self._check_conds(lines, "「%s」の %s" % (g.get("name", g["id"]), ev))
                if g["kind"] in games.STRIP_KINDS and not g.get("stages"):
                    raise ValueError("「%s」の stages が空です" % g.get("name", g["id"]))
            self.minigames = items
            store.save(store.wpath("minigames.json"), items)
            for st in self.states.values():   # 消えたゲームの進行中状態は破棄
                if st.get("game") and st["game"].get("id") not in ids:
                    st["game"] = None
            return items

    def save_workflow(self, wf):
        found = comfy.validate_workflow(wf)
        store.save(store.dpath("workflow.json"), wf)
        return found

    def set_params(self, values, cid=None):
        with self.lock:
            char = self.char(cid)
            st = self.state(char["id"])
            for k, v in values.items():
                p = self.param_def(k)
                if p:
                    st["params"][k] = self._clamp(p, float(v))
            self.save_state(char["id"])

    def reset_state(self, cid=None):
        with self.lock:
            char = self.char(cid)
            self.states.pop(char["id"], None)
            p = store.wpath("state", char["id"] + ".json")
            if os.path.exists(p):
                os.remove(p)
            self.state(char["id"])
            self.save_state(char["id"])

    def clear_override(self, cid=None):
        with self.lock:
            char = self.char(cid)
            self.state(char["id"])["override"] = None
            self.save_state(char["id"])

    def album(self, cid=None, key=None):
        """アルバム: シチュエーション (= 合成後のプロンプト) ごとのまとまり. key を指定すればその中の画像."""
        groups = {}
        for e in (e for c in ([cid] if cid in self.chars else list(self.chars)) for e in self.log(c)):   # 全員分 (cid で絞れる)
            for im in e.get("images") or []:
                if not os.path.exists(store.dpath("images", *im["path"].split("/"))):
                    continue
                k = self.prompt_key(im.get("pos", ""), im.get("neg", ""))
                if key and k != key:
                    continue
                g = groups.setdefault(k, {"key": k, "items": []})
                g["items"].append({"path": im["path"], "seed": im.get("seed"), "t": im.get("t") or e["t"], "pos": im.get("pos", ""),
                                   "neg": im.get("neg", ""), "entry": {k2: e.get(k2) for k2 in ("id", "t", "text", "action_name", "icon", "scene")}})
        if key:
            g = groups.get(key) or {"key": key, "items": []}
            g["items"].sort(key=lambda x: -x["t"])
            return g
        out = []
        for g in groups.values():
            last = max(g["items"], key=lambda x: x["t"])
            labels = {}
            for it in g["items"]:
                lb = "%s%s・%s" % (it["entry"].get("icon") or "", it["entry"].get("action_name") or "", it["entry"].get("scene") or "")
                labels[lb] = labels.get(lb, 0) + 1
            out.append({"key": g["key"], "count": len(g["items"]), "t": last["t"], "cover": last["path"],
                        "label": max(labels, key=labels.get), "pos": last["pos"]})
        out.sort(key=lambda x: -x["t"])
        return {"groups": out}

    def delete_image(self, path):
        """気に入らない画像を消す: ファイル・索引・全キャラのログから取り除く."""
        with self.lock:
            full = store.dpath("images", *[p for p in path.split("/") if p and p != ".."])
            if not full.startswith(store.dpath("images")) or not path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                raise ValueError("消せない画像です")
            if os.path.exists(full):
                os.remove(full)
            for k in list(self.img_index):
                self.img_index[k] = [im for im in self.img_index[k] if im["path"] != path]
                if not self.img_index[k]:
                    del self.img_index[k]
            store.save(store.dpath("images", "index.json"), self.img_index)
            # 画像は全ワールド共通なので, 他のワールドのログからも外す
            for f in glob.glob(store.dpath("worlds", "*", "log", "*.json")):
                cid = os.path.splitext(os.path.basename(f))[0]
                here = os.path.normcase(os.path.dirname(f)) == os.path.normcase(store.wpath("log"))
                log = self.log(cid) if here else store.load(f, [])
                changed = False
                for e in log:
                    if any(im["path"] == path for im in e.get("images") or []):
                        e["images"] = [im for im in e["images"] if im["path"] != path]
                        changed = True
                    if e.get("image") == path:
                        e["image"] = e["images"][-1]["path"] if e.get("images") else None
                        changed = True
                if changed:
                    self.save_log(cid) if here else store.save(f, log)
            return {"ok": True}

    def log_page(self, who=None, offset=0, limit=60, images_only=False):
        """あなたの時系列のページ (who で人を絞る. "me" は一人の時間だけ)."""
        items, total = self.timeline(who, offset, limit, images_only)
        return {"total": total, "items": items}
