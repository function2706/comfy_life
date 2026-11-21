"""「いつ・どこで・何を・誰と」の読み出し (DESIGN 6 章の統一モデル. 移行手順 2〜3).

あなたの「いま何を・どこで・誰と」は player.json の presence 1 つに持つ (Activity の記録):
  mode (= do)・since (= t0)・place・solo / job / task / travel / arrived / left・with (誰と. 以前は player.json 直下).
心拍の beat / input / last_left は「画面の前にいるか」の値で, 同じ記録に置くが Activity の一部ではない.

外で誰かと会っている間の居場所は, 二人で共有するお出かけの記録 (相手の override.place / trips) を with からたどる
(あなたの place には写さない. キャラ側を Activity にするのは移行手順 4).

「外にいるか」「家で手が空いているか」「誰かと出ているか」は, ここだけで決める (outdoor.current・bonds.mode・
App.out_with・内職 / 家計簿 / 店 / 約束の「家にいるか」はここを読む).
"""
import time
from datetime import datetime

from . import places as places_mod

HOME_ME = places_mod.HOME_ME

# あなたの「何を」の語彙. state: いまの状態の言い方 (在席の表示), plan: 予定・行動パターンの言い方, away: 家を空けるか.
# presence.MODE_LABEL と offline.DO_LABEL はここから作る (文言は以前のまま)
DO = {
    "here": {"state": "そばにいる"},
    "idle": {"state": "そばでのんびり"},
    "none": {"state": "家にいる"},
    "busy": {"state": "作業中"},
    "out": {"state": "外出中", "plan": "外出", "away": True},
    "work": {"state": "仕事中", "plan": "仕事", "away": True},
    "sleep": {"state": "就寝中", "plan": "寝る"},
    "left": {"state": "離れている"},
    "gone": {"state": "いない"},
    "rest": {"plan": "休む"},
    "home": {"plan": "家で静かに過ごす"},
    "chores": {"plan": "家事"},
    "kakeibo": {"plan": "家事（家計簿をつける）"},
    "practice": {"plan": "研鑽"},
    "meal": {"plan": "食事"},
    "parttime": {"plan": "アルバイト", "away": True},
    "jog": {"plan": "ジョギング", "away": True},
    "read": {"plan": "本を読む"},
    "movie": {"plan": "映画を観る"},
    "exam": {"plan": "試験", "away": True},
}
STATE_ORDER = ("here", "idle", "busy", "out", "work", "sleep", "left", "gone")
PLAN_ORDER = ("sleep", "rest", "home", "work", "out", "chores", "kakeibo", "practice", "meal", "parttime", "jog", "read", "movie")
MODE_LABEL = {k: DO[k]["state"] for k in STATE_ORDER}
PLAN_LABEL = {k: DO[k]["plan"] for k in PLAN_ORDER}
AWAY_PLAN = tuple(k for k, v in DO.items() if v.get("away") and "plan" in v)     # 家を空ける予定
FREE_AT_HOME = ("none", "busy")          # 家にいて, 手が空いている (作業中は声をかければ手が空く) 在席


class Activity:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ あなた
    def outdoor(self, now=None):
        """いまの外出 {kind: out/work/outing, place, with, moving?, inside?, dest?, how?} (家の外にいなければ None).
        相手の家にいる (with.mode = visit) のは外出ではない (外出の画面・偶然の出会いの対象外)."""
        app = self.app
        p = app.presence.rec()
        tr = p.get("travel")
        if tr and p.get("mode") in ("out", "work"):        # 移動中: 通っていく道 (電車・バスなら駅前, 歩くなら街) の人の多さ
            return {"kind": "out", "place": "station" if tr.get("how") == "transit" else "town", "with": None, "moving": True,
                    "inside": tr.get("how") in ("car", "taxi"),        # 車・タクシーの中では, 偶然の出会いは無い
                    "dest": tr["to"] if tr.get("dir") == "go" else HOME_ME, "how": tr.get("how")}
        if p.get("mode") == "out":
            pl = p.get("place") or "town"
            if places_mod.is_home(pl):              # 相手の家の前 (約束の訪問で待っている・玄関先)
                return {"kind": "out", "place": pl, "with": None}
            return {"kind": "out", "place": pl if pl in places_mod.PLACES else "town", "with": None}
        if p.get("mode") == "work":
            return {"kind": "work", "place": "office", "with": None}
        cid, ov = self.outing(now)
        if cid:
            trip = app.outing_trip(app.state(cid), now)
            if trip:                # 一緒に移動中: まだ行き先にはいない (通っていく道. 一人の移動と同じ)
                return {"kind": "outing", "place": "station" if trip.get("legs") or trip.get("how") == "transit" else "town",
                        "with": cid, "moving": True, "inside": trip.get("how") in ("car", "taxi"), "how": trip.get("how"),
                        "dest": trip["to"] if trip["dir"] == "go" else HOME_ME}
            return {"kind": "outing", "place": self.outing_place(ov), "with": cid}
        return None

    @staticmethod
    def outing_place(ov):
        """二人のお出かけの記録 (相手の override) の行き先 id."""
        return ov.get("place") if ov.get("place") in places_mod.PLACES else places_mod.from_location(ov.get("location"))

    def outing(self, now=None):
        """いま一緒にお出かけしている相手 (cid) と, その上書き (二人で共有するお出かけの記録). 無ければ (None, None)."""
        app = self.app
        now = now or time.time()
        for cid in app.bonds.company():
            ov = app.state(cid).get("override") or {}
            if ov.get("outing") and ov.get("until", 0) > now:
                return cid, ov
        return None, None

    def player(self, now=None):
        """いまのあなたの Activity.
        {who, do (presence の mode), t0, place (行き先 id. 家は home. 相手の家は home:<cid>), with ([cid]), how (meet/visit/guest/home),
         kind (out/work/outing. 家の外でなければ None), moving, out (outdoor() の値)}"""
        app = self.app
        now = now or time.time()
        p = app.presence.rec()
        w = app.bonds.with_rec()
        out = self.outdoor(now)
        act = {"who": "player", "do": p.get("mode", "none"), "t0": p.get("since"), "place": HOME_ME, "with": [],
               "how": None, "kind": None, "moving": False, "out": out}
        if out:
            act.update(place=out.get("dest") if out.get("moving") else out["place"], kind=out["kind"], moving=bool(out.get("moving")))
            if out.get("with"):
                act["with"] = [out["with"]]
                act["how"] = w["mode"] if w and w["cid"] == out["with"] else "live"      # 外で会った人 / 同居相手と出かけた
        elif w and w["mode"] in ("meet", "visit"):
            # 外で会っている (お出かけの記録が切れた直後. sync で別れる) / 相手の家にいる
            act["place"] = "home:" + w["cid"] if w["mode"] == "visit" else \
                self.outing_place(app.state(w["cid"]).get("override") or {}) or "town"
            act["with"], act["how"] = [w["cid"]], w["mode"]
        if not act["with"] and not act["kind"]:
            for cid in app.bonds.company():           # 家に招いた人・家にいる同居相手
                act["with"].append(cid)
            if act["with"]:
                act["how"] = "guest" if w and w["mode"] == "guest" else "home"
        return act

    def at_home(self, now=None):
        """あなたが家にいるか (外出・仕事・移動中・外で会っている・相手の家にいる, のどれでもない). 寝ている・離れているも家."""
        a = self.player(now)
        return a["kind"] is None and a["place"] == HOME_ME

    def home_free(self, now=None):
        """家にいて, 手が空いているか (内職・家計簿・家での約束を迎える など. 作業中は手を止められる)."""
        return self.app.presence.rec().get("mode") in FREE_AT_HOME and self.at_home(now)

    def out_with(self, now=None):
        """外で誰かと会っている・一緒にお出かけしている・相手の家にいるなら, その相手 (cid). 無ければ None.
        (家に来てもらっている・同居相手と家にいるのは含めない)"""
        now = now or time.time()
        w = self.app.bonds.with_rec()
        if w and w.get("mode") in ("meet", "visit"):
            return w["cid"]
        return self.outing(now)[0]

    # ------------------------------------------------------------------ あなたの予定 (閉じている間)
    def planned(self, t):
        """家の画面を閉じている間の時刻 t の, 予定・行動パターンの「いまの枠」(Activity の形: {do, place, src}). 無ければ None.
        閉じてから間もない (まとめの対象にならない短さ) うちは None (家にいるまま)."""
        app = self.app
        off = app.offline
        beat = app.presence.rec().get("beat", 0)
        if not beat or t <= beat or not off.will_run(beat, t):
            return None
        if app.planner.active():
            for s, e, kind, x in app.planner.slots(t, t + 60):
                if not (s <= t < e):
                    continue
                if kind == "appoint":
                    return {"who": "player", "do": "out" if x.get("place") != HOME_ME else "home", "place": x.get("place"),
                            "src": "promise", "t0": s, "t1": e}
                if kind == "exam":
                    return {"who": "player", "do": "exam", "place": None, "src": "schedule", "t0": s, "t1": e}
                if kind == "plan":
                    return self._block(x, s, e, "plan")
                break
        if not off.cfg().get("enabled"):
            return None
        return next((self._block(bb, s, e, "routine") for s, e, bb in off.blocks(t, t + 60) if s <= t < e), None)

    @staticmethod
    def _block(b, s, e, src):
        a = {"who": "player", "do": b.get("do"), "place": b.get("place"), "how": b.get("how"), "src": src, "t0": s, "t1": e}
        if b.get("do") == "meal":
            a["place"] = HOME_ME if b.get("how") == "cook" else b.get("place")
        return a

    @staticmethod
    def leaves_home(a):
        """予定の Activity が家を空けるものか (仕事・アルバイト・外出・ジョギング・試験・外での約束・外食 / 買って食べる)."""
        if not a:
            return False
        if a.get("src") == "promise":
            return a.get("place") != HOME_ME
        return bool((DO.get(a.get("do")) or {}).get("away")) or (a.get("do") == "meal" and a.get("how") in ("out", "buy"))

    # ------------------------------------------------------------------ 相手
    def char(self, cid, t=None):
        """相手の Activity (本人の予定どおり. あなたから見えるかとは別).
        {who, do (with: あなたと一緒 / sleep / out: 本人の予定で出かけている / busy / home), place, with, src, label}.
        place: あなたと一緒なら, あなたと同じ所. 本人の予定の外出は行き先 id が分からない (予定の場所は自由記述) ので None."""
        app = self.app
        t = t or time.time()
        char = app.chars.get(cid)
        if not char:
            return None
        st = app.state(cid)
        sc = app.scene_at(char, st, datetime.fromtimestamp(t))
        mode = app.bonds.mode(cid, t)
        act = {"who": cid, "do": "home", "place": "home:" + cid, "with": [], "src": sc.get("source") or "schedule",
               "label": sc.get("label", ""), "location": sc.get("location", "")}
        if mode:
            me = self.player(t)
            act.update(do="with", place=me["place"], src="with", with_me=True)
            act["with"] = ["player"] + [c for c in me["with"] if c != cid]
        elif sc["asleep"]:
            act["do"] = "sleep"
        elif sc["away"]:
            ov = st.get("override") or {}
            act.update(do="out", place=self.outing_place(ov) if ov.get("outing") and ov.get("until", 0) > t else None)
        elif sc["busy"]:
            act["do"] = "busy"
        return act
