"""外出 (一人の外出, 誰かとのお出かけ, 仕事) と, 天気. 行き先の表は core/places.py (ここは読み替えて使うだけ).

- 外出は画面を開いている間だけ続く. 心拍が途絶えたら, 最後の心拍の時点で外出は終わり, 家に帰って静かに過ごしていた扱い
  (誰にも会わない. 仕事の給料も最後の心拍まで). 開き直しても「おかえり」の場面にはしない.
- 偶然の出会いは, 外出中に心拍のたび判定する. 起きやすさ (1時間あたり) は 行動 x 行き先の人の多さ (時間帯ごと) x 天気.
  出会わせる補正はない.
- 天気はリアルの日付から疑似的に決める (朝・昼・夜で変わることがある). 屋外の行き先ほど, 雨や雪で人が減る.
"""
import hashlib
import math
import random
import time
from datetime import datetime

from . import places as places_mod
from . import season as season_mod
from . import store
from .stay import STAY_MORNING

# 行き先の表 (core/places.py) を, 以前の名前でも引けるように
PLACES = places_mod.PLACES
LOCATION_PLACE = places_mod.LOCATION_PLACE
# 一人の外出で選べる行き先. 以前の「散歩・買い物・カフェ」(walk / shopping / cafe) の選択肢も, 読み替えのために残す
CHOICES = {"out": list(places_mod.OUT_PLACES),
           "walk": [k for k in places_mod.OUT_PLACES if places_mod.main_do(k) == "walk"],
           "shopping": [k for k in places_mod.OUT_PLACES if "shop" in PLACES[k]["does"]],
           "cafe": places_mod.branches("cafe")}
WEATHER = {"sunny": ("晴れ", "☀", 1.0, 1.0), "cloudy": ("くもり", "☁", 0.9, 1.0), "rain": ("雨", "☔", 0.35, 0.85),
           "snow": ("雪", "❄", 0.3, 0.8)}      # (名前, 印, 屋外の人の多さ, 屋内の人の多さ)
SEASON_WEATHER = {"spring": (("sunny", 0.5), ("cloudy", 0.3), ("rain", 0.2)),
                  "summer": (("sunny", 0.55), ("cloudy", 0.2), ("rain", 0.25)),
                  "autumn": (("sunny", 0.5), ("cloudy", 0.3), ("rain", 0.2)),
                  "winter": (("sunny", 0.45), ("cloudy", 0.35), ("rain", 0.1), ("snow", 0.1))}
SEASONS = season_mod.SEASONS        # 季節の表は core/season.py に 1 つ (S38)
ARRIVE_GRACE = 10 * 60    # 移動中に閉じて, 着いてからこれだけの間に開けば, そのまま行き先にいる
DEFAULTS = {"rate_out": 0.6, "rate_outing": 0.25, "rate_work": 0.3}     # 1時間あたり (人の多さ 1.0・晴れのとき)


def weather(dt):
    """その日・その時間帯 (0〜11時 / 12〜17時 / 18〜23時) の天気. リアルの日付から決まる (毎回同じ)."""
    slot = 0 if dt.hour < 12 else 1 if dt.hour < 18 else 2
    seed = int(hashlib.md5(("%s/%d" % (dt.date().isoformat(), slot)).encode()).hexdigest()[:8], 16)
    day = int(hashlib.md5(dt.date().isoformat().encode()).hexdigest()[:8], 16)
    rng = random.Random(day if (seed % 3) else seed)        # たいていは一日同じ. ときどき時間帯で変わる
    table = SEASON_WEATHER[SEASONS[dt.month]]
    r, acc = rng.random(), 0.0
    wid = table[-1][0]
    for w, p in table:
        acc += p
        if r < acc:
            wid = w
            break
    if wid == "snow" and season_mod.base_temp(dt) > season_mod.SNOW_MAX:
        wid = "rain"                                        # 暖かい日の雪は雨 (S38)
    name, icon, out_m, in_m = WEATHER[wid]
    return {"id": wid, "label": name, "icon": icon, "outdoor": out_m, "indoor": in_m}


class Outdoor:
    def __init__(self, app):
        self.app = app

    def cfg(self):
        c = dict(DEFAULTS)
        c.update(self.app.world.get("outdoor") or {})
        return c

    # ------------------------------------------------------------------ いまどこにいるか
    def current(self, now=None):
        """いまの外出 {kind: out/work/outing, place, with} (外出していなければ None). 決めるのは core/activity.py."""
        return self.app.activity.outdoor(now)

    def rate(self, cur, dt):
        """1時間あたりの出会いの起きやすさ."""
        if places_mod.is_home(cur["place"]) or cur.get("inside"):
            return 0.0                              # 家・車の中では偶然の出会いは起きない
        pl = PLACES.get(cur["place"]) or PLACES["town"]
        ph = self.app.phase_at(dt).get("id", "noon")
        w = weather(dt)
        return float(self.cfg()["rate_" + cur["kind"]]) * float(pl["crowd"].get(ph, 0.5)) \
            * float(w["outdoor"] if pl["outdoor"] else w["indoor"])

    def view(self, now=None):
        now = now or time.time()
        dt = datetime.fromtimestamp(now)
        cur = self.current(now)
        pv = self.app.places.view(now)
        from .solo import JOG_PLACES
        ch = dict(CHOICES, out=self.app.places.out_choices(), jog=list(JOG_PLACES))
        out = {"weather": dict(weather(dt), **season_mod.view(dt)), "places": pv["places"], "groups": pv["groups"], "does": pv["does"],
               "choices": ch, "routine_choices": list(places_mod.ROUTINE_OUT), "near": pv.get("near", {}), "current": None}
        out["season"] = season_mod.season(dt)      # 服の棚の「いまの季節」(S37)
        out["with_home"] = {k: self.app.places.with_why(k) for k in ch["out"] if self.app.places.with_why(k)}     # 一緒にいる人の家 (F18)
        if cur:
            pl = self.app.places.get(cur["place"]) or PLACES["town"]
            out["current"] = dict(cur, label=pl["label"], icon=pl["icon"],
                                  log=(self.app.presence.rec().get("street_log") or [])[-6:])
            if cur.get("moving"):
                out["current"].update(label="%sへ移動中" % self.app.places.label(cur["dest"]) if cur["dest"] != places_mod.HOME_ME else "家へ移動中",
                                      icon={"transit": "🚃", "bike": "🚲", "car": "🚗", "taxi": "🚕"}.get(cur.get("how"), "🚶"))
        # 行き先ごとの行き方の目安 (いまいる場所から)
        pair = bool(self.app.outing_now(now)[0])              # 相手と一緒: 自転車は出さない (二人では乗れない. F13)
        out["routes"] = self.app.geo.choices_view(sorted(set(ch["out"]) | set(places_mod.OUT_PLACES) | {places_mod.HOME_ME}), now, pair)   # 家へ: 帰る行き方
        out["travel"] = self.app.geo.view(now)
        out["vehicles"] = self.app.geo.vehicles_view(now)
        out["here"] = self.app.geo.where(now)
        cid, ov = self.app.outing_now(now)                    # 相手と一緒に出かけている: 地図で行き先を押すと「一緒に行く」
        if cid:
            st = self.app.state(cid)
            trip = self.app.outing_trip(st, now)
            char = self.app.chars[cid]
            # 一緒に行けるところ (その場所の移動のコマンドがあり, いまの条件を満たす. 中古車屋・教習所などは一緒には行かない)
            spots = [p for p in sorted(set(ch["out"]) | set(places_mod.OUT_PLACES)) if self.app._move_action(p, char, st)]
            out["with_outing"] = {"cid": cid, "name": char.get("name", ""), "place": ov.get("place"), "spots": spots,
                                  "moving": bool(trip), "to": trip["to"] if trip and trip["dir"] == "go" else None}
        else:
            out["out_with"] = self.app.out_with(now)          # 相手の家にいる途中など: 一人では出かけられない
        out["map"] = self.app.geo.map_view(sorted(set(ch["out"]) | set(places_mod.OUT_PLACES)), now)
        out["net"] = self.app.geo.transit.map_view()          # 路線と駅・停留所 (地図に描く. 押すと時刻表)
        return out

    # ------------------------------------------------------------------ 心拍のたびに
    def live(self, now=None):
        """外出中なら, 前の判定からの時間ぶん, 偶然の出会いを判定する. 起きたら結果を返す."""
        app = self.app
        now = now or time.time()
        p = app.presence.rec()
        cur = self.current(now)
        last = p.get("enc_check") or now
        p["enc_check"] = now
        if not cur:
            return None
        h = min(max(now - last, 0), 600) / 3600.0
        if not h or random.random() >= 1 - math.exp(-self.rate(cur, datetime.fromtimestamp(now)) * h):
            return None
        return app.encounters.happen_at(cur, now)

    def closing(self, now=None):
        """いる行き先が閉まったら出される. 一人の外出なら, それまでの結果を出して街へ (外出は続く).
        誰かとのお出かけなら, そこで切り上げて帰る. 何か起きたらテキストを返す."""
        app = self.app
        now = now or time.time()
        cur = self.current(now)
        if not cur or cur["kind"] == "work" or cur.get("moving"):
            return None
        pl = cur["place"]
        o = places_mod.open_state(pl, datetime.fromtimestamp(now))
        if o["open"]:
            return None
        name = PLACES.get(pl, {}).get("label", pl)
        if cur["kind"] == "out":
            ll = app.presence.back(now)
            res = app.solo.finish(ll) if ll else None
            app.presence.declare("out", now)
            p = app.presence.rec()
            p["solo"] = {"kind": "out", "skill": None, "t": now}
            p["place"] = "town"
            app.presence.save()
            text = "（%sが閉まる時間になったので、出て街を歩くことにした）" % name
            self.note(text.strip("（）"), now)
            app.solo.note("out", text.strip("（）"), now)
            return {"text": text, "solo": res}
        cid = cur["with"]
        char, st = app.char(cid), app.state(cid)
        with app.lock:
            st["override"] = None
            text = "（%sが閉まる時間になったので、%sとはそこで切り上げて帰った）" % (name, char.get("name", ""))
            app.note_entry(char, st, now, "_closing", "閉店", "🔒", text)
            app.bonds.sync(cid, st, now)
            app.save_state(cid)
        self.note(text.strip("（）"), now)
        return {"text": text}

    def note(self, text, now=None):
        p = self.app.presence.rec()
        lg = p.setdefault("street_log", [])
        lg.append({"t": now or time.time(), "text": text})
        del lg[:-20]

    def _with_leave(self, w, beat):
        """閉じたまま一緒にいた相手と別れる時刻: いる時間の終わり (泊まりなら朝 stay.morning) か, それより前に
        閉じている間の予定で家を空ける (仕事・外出など) 最初の時刻 (泊まりなら朝 5 時から見る)."""
        app = self.app
        until = float(w.get("until", beat))
        t = beat
        if w.get("stay"):
            until = max(until, app.stay.morning(float(w["stay"].get("t", beat))))
            t = max(beat, until - (STAY_MORNING - 5) * 3600)
        t = math.ceil(t / 900.0) * 900
        while t < until:
            if app.offline.away_closed(t):
                return t
            t += 900
        return until

    def check_gap(self, now=None):
        """心拍が途絶えていたら, 最後の心拍の時点で外出を終える (家に帰って静かに過ごしていた). 終えたら説明を返す.
        移動中に閉じたなら, 移動は続く (core/geo.py): 着いて ARRIVE_GRACE 以内に開けば, そのまま行き先にいる (帰る途中なら家に着く).
        それより遅ければ, 着いてすぐ家に引き返したことにして, 家に着いてから閉じていた間の過ごし方を始める."""
        app = self.app
        now = now or time.time()
        p = app.presence.rec()
        beat = p.get("beat", 0)
        if not beat or now - beat <= app.presence._gone_sec():
            return None
        tr = p.get("travel")
        if tr and p.get("mode") in ("out", "work") and now < tr["arr"] + ARRIVE_GRACE:
            return None                                # まだ移動中 / 着いたばかり: 着いたことは geo.tick で
        # 短い離席 (オフラインモードの min_minutes 未満): 出先・職場・移動中なら, 閉じていてもそのまま (移動は geo.tick で着く).
        # 以前は 5 分途切れただけで, 仕事を終えて家に帰ったことになっていた. 相手とのお出かけ中は下で解散する (今までどおり)
        if p.get("mode") in ("out", "work") and now - beat < float(app.offline.cfg().get("min_minutes", 30)) * 60 \
                and not any((app.state(c).get("override") or {}).get("outing") for c in app.chars):
            return None
        if tr and tr.get("doing"):                     # 移動中に読んでいた・観ていた: 着くまで (閉じていても) 続けていた
            app.geo.finish_doing(tr, tr["arr"])
        msgs = []
        start = None
        # 誰かとのお出かけ: そのまま解散して, それぞれ家へ (帰り道は閉じた時刻から. 以前は開いた時刻に帰り道を組み, 運賃もそのときに払っていた).
        # 泊まる約束をして家から出てきていたなら, 一緒にその家へ戻る (そのあとは下の「一緒にいる」で)
        for cid in list(app.chars):
            st = app.state(cid)
            ov = st.get("override") or {}
            if ov.get("outing") and ov.get("until", 0) > beat:
                st["override"] = None
                w = app.bonds.with_rec()
                if w and w.get("cid") == cid and w.get("mode") == "meet":
                    back = app.bonds.stay_back(cid, beat)
                    if back:
                        app.bonds.start(cid, back, beat)
                    else:
                        loc = w.get("place") or ov.get("place") or "town"
                        app.bonds.end(go_home=False)
                        if p.get("mode") not in ("out", "work") and not places_mod.is_home(loc):
                            start = loc
                        msgs.append("%sとのお出かけは、そのまま解散して家に帰った" % app.chars[cid].get("name", ""))
                else:
                    app.bonds.sync(cid, st, now)
                    msgs.append("%sとのお出かけは、そのまま解散して家に帰った" % app.chars[cid].get("name", ""))
                app.save_state(cid)
        mode = p.get("mode")
        home_at = beat
        lead = None
        # 相手の家にいる / 家に招いている (泊まっている) まま閉じた: 閉じていても一緒にいて, 別れる時刻 (泊まりなら朝. それより前に
        # 出かける予定 (仕事など) があればその時刻) に別れたことにする. 相手の家からなら, そこから次の予定へ向かう.
        # 以前は閉じた時刻から家で過ごしたことにしたうえで, 開いた時刻にあらためて相手の家から帰っていた (運賃もそのとき)
        w = app.bonds.with_rec()
        if mode not in ("out", "work") and w and w.get("mode") in ("visit", "guest") and w.get("cid") in app.chars                 and app.offline.will_run(beat, now):
            leave = self._with_leave(w, beat)
            if leave > now:
                return None                            # まだ一緒にいる時間 (泊まっていて, 朝より前に開いた など)
            cid = w["cid"]
            name = app.chars[cid].get("name", "")
            stay = bool(w.get("stay"))
            if w["mode"] == "visit":
                text = "%sの家に%s" % (name, "泊まった" if stay else "いた")
                start = "home:" + cid
            else:
                text = "%sが家に%s" % (name, "泊まっていった" if stay else "来ていた")
            app.bonds.end(go_home=False)
            app.bonds.sync(cid, app.state(cid), now)
            app.save_state(cid)
            lead, home_at = (beat, text), leave
        # 出先・向かう途中で閉じた: 行動パターン・予定で過ごすなら, 家に寄らずにその場所から次の場所へ (なにも無ければ家へ).
        # 向かう途中なら, 着いて, ふだんどおりの長さ (買い物なら店のふだんの長さ, ほかは 45 分ほど) を過ごしてから
        place = tr["to"] if tr and tr.get("dir") == "go" else (None if tr else p.get("pos"))
        if mode in ("out", "work") and place and not places_mod.is_home(place):
            if tr:
                t_out = tr["arr"] + 60 * (app.solo.shop_typical(place) if places_mod.solo_kind(place) == "shopping" else 45)
                t_out = min(now, t_out)
                if t_out < tr["arr"] + 60:
                    t_out = min(now, tr["arr"] + 60)
            else:
                t_out = beat
            if app.offline.will_run(t_out, now):
                if tr:
                    p["arrived"] = tr["arr"]
                    p["pos"] = tr["to"]
                    p.pop("travel", None)
                sl = p.get("solo") or {}
                if sl.get("kind") == "out" and places_mod.solo_kind(place) == "shopping" and not sl.get("shop_done"):
                    t_in = sl.get("shop_from") or p.get("arrived", t_out)        # 買い足しの途中なら, 買い足すと決めてから
                    sl["shop_done"] = app.solo.merge_prev(sl, app.solo._shop_now(place, max(0.0, t_out - t_in) / 3600.0, t_out))   # 店で過ごして買い物を済ませた
                res = app.come_back(at=t_out, quiet=True)
                msgs.append(res.get("text") or "")
                start, home_at, mode = place, t_out, None
        if mode in ("out", "work"):
            # 出先にいた: 最後の心拍で出先を出て, 家まで移動した (着くまでは閉じていた間の過ごし方に入らない)
            t_out = beat
            if tr and tr.get("dir") == "go":           # 向かう途中で閉じた: 移動は続いて着き, 着いてすぐ家へ引き返した
                t_out = tr["arr"]
                p["arrived"] = p["left"] = t_out
                p["pos"] = tr["to"]
                p.pop("travel", None)
                home_at = min(now, app.geo.home_eta(t_out))
            elif tr:                                   # 帰る途中で閉じた: そのまま家に着いた
                t_out = home_at = tr["arr"]
                p.pop("travel", None)
            else:
                home_at = min(now, app.geo.home_eta(beat))
                p["left"] = beat
            if not (tr and tr.get("dir") != "go") and app.geo.home_eta(t_out) > now:
                # 家に着く前に開いた: まだ帰り道の途中 (着いたら geo.tick で戻る). 以前は開いた時刻に家に着いたことにしていた
                frm = p.get("pos")
                trv = app.geo.depart(places_mod.HOME_ME, None, t_out, frm=frm, direction="home")
                if trv and trv["arr"] > now:
                    label = app.places.label(frm)
                    app.solo.note("out", "%sを出て家へ向かった" % label, t_out)
                    return {"text": "（画面を閉じていたあいだ、%sに%sを出て、いま家へ向かっている。あと%d分ほど）"
                            % (datetime.fromtimestamp(t_out).strftime("%H:%M"), label, max(1, round((trv["arr"] - now) / 60)))}
                if trv:
                    home_at = trv["arr"]
                    p.pop("travel", None)
            res = app.come_back(at=t_out, quiet=True)
            msgs.append((res.get("text") or "") + ("。家に着いたのは%s" % datetime.fromtimestamp(home_at).strftime("%H:%M")
                                                   if home_at - t_out >= 300 or t_out != beat else ""))
        p["pos"] = places_mod.HOME_ME
        # オフラインモード: 閉じていた間は, 予定 (勤務時間) に沿って過ごした
        rep = app.offline.simulate(home_at, now, start=start, lead=lead)
        if not msgs and not rep:
            return None
        if rep:
            return {"text": "（" + "。".join(m for m in msgs if m) + ("。" if any(msgs) else "") + "画面を閉じていたあいだのことは、まとめを見てください）",
                    "report": True}
        text = "（画面を閉じていたあいだ、%s。家で静かに過ごしていた）" % "。".join(m for m in msgs if m)
        app.solo.note("home", text.strip("（）"), beat)
        return {"text": text}
