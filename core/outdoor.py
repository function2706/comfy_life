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
from . import store

# 行き先の表 (core/places.py) を, 以前の名前でも引けるように
PLACES = places_mod.PLACES
LOCATION_PLACE = places_mod.LOCATION_PLACE
# 一人の外出で選べる行き先. 以前の「散歩・買い物・カフェ」(walk / shopping / cafe) の選択肢も, 読み替えのために残す
CHOICES = {"out": list(places_mod.OUT_PLACES),
           "walk": [k for k in places_mod.OUT_PLACES if places_mod.main_do(k) == "walk"],
           "shopping": [k for k in places_mod.OUT_PLACES if "shop" in PLACES[k]["does"]],
           "cafe": ["cafe"]}
WEATHER = {"sunny": ("晴れ", "☀", 1.0, 1.0), "cloudy": ("くもり", "☁", 0.9, 1.0), "rain": ("雨", "☔", 0.35, 0.85),
           "snow": ("雪", "❄", 0.3, 0.8)}      # (名前, 印, 屋外の人の多さ, 屋内の人の多さ)
SEASON_WEATHER = {"spring": (("sunny", 0.5), ("cloudy", 0.3), ("rain", 0.2)),
                  "summer": (("sunny", 0.55), ("cloudy", 0.2), ("rain", 0.25)),
                  "autumn": (("sunny", 0.5), ("cloudy", 0.3), ("rain", 0.2)),
                  "winter": (("sunny", 0.45), ("cloudy", 0.35), ("rain", 0.1), ("snow", 0.1))}
SEASONS = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
           6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}
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
        """いまの外出 {kind: out/work/outing, place, with} (外出していなければ None)."""
        app = self.app
        p = app.presence.rec()
        if p.get("mode") == "out":
            pl = p.get("place") or "town"
            return {"kind": "out", "place": pl if pl in PLACES else "town", "with": None}
        if p.get("mode") == "work":
            return {"kind": "work", "place": "office", "with": None}
        now = now or time.time()
        for cid in app.chars:
            if not app.bonds.together(cid):
                continue
            ov = app.state(cid).get("override") or {}
            if ov.get("outing") and ov.get("until", 0) > now:
                pl = ov.get("place") if ov.get("place") in PLACES else places_mod.from_location(ov.get("location"))
                return {"kind": "outing", "place": pl, "with": cid}
        return None

    def rate(self, cur, dt):
        """1時間あたりの出会いの起きやすさ."""
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
        ch = dict(CHOICES, out=self.app.places.out_choices())
        out = {"weather": weather(dt), "places": pv["places"], "groups": pv["groups"], "does": pv["does"],
               "choices": ch, "routine_choices": list(places_mod.OUT_PLACES), "current": None}
        if cur:
            pl = PLACES.get(cur["place"]) or PLACES["town"]
            out["current"] = dict(cur, label=pl["label"], icon=pl["icon"],
                                  log=(self.app.presence.rec().get("street_log") or [])[-6:])
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
        if not cur or cur["kind"] == "work":
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

    def check_gap(self, now=None):
        """心拍が途絶えていたら, 最後の心拍の時点で外出を終える (家に帰って静かに過ごしていた). 終えたら説明を返す."""
        app = self.app
        now = now or time.time()
        p = app.presence.rec()
        beat = p.get("beat", 0)
        if not beat or now - beat <= app.presence._gone_sec():
            return None
        msgs = []
        # 誰かとのお出かけ: そのまま解散して, それぞれ家へ
        for cid in list(app.chars):
            st = app.state(cid)
            ov = st.get("override") or {}
            if ov.get("outing") and ov.get("until", 0) > beat:
                st["override"] = None
                app.bonds.sync(cid, st, now)
                app.save_state(cid)
                msgs.append("%sとのお出かけは、そのまま解散して家に帰った" % app.chars[cid].get("name", ""))
        mode = p.get("mode")
        if mode in ("out", "work"):
            res = app.come_back(at=beat, quiet=True)
            msgs.append(res.get("text") or "")
        # オフラインモード: 閉じていた間は, 予定 (勤務時間) に沿って過ごした
        rep = app.offline.simulate(beat, now)
        if not msgs and not rep:
            return None
        if rep:
            return {"text": "（" + "。".join(m for m in msgs if m) + ("。" if any(msgs) else "") + "画面を閉じていたあいだのことは、まとめを見てください）",
                    "report": True}
        text = "（画面を閉じていたあいだ、%s。家で静かに過ごしていた）" % "。".join(m for m in msgs if m)
        app.solo.note("home", text.strip("（）"), beat)
        return {"text": text}
