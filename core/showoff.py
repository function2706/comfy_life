"""見せたくなる場面 (A44 段 2): 相手が見せたい気持ちになった場面で, そばにいれば見せる・着替えて見せる, 離れていれば写メを送る.

- 見せたい気持ち (状態の showy.v. 0〜1. 見せない値): 見せるたびに下がり (× SHOW_LEFT), 時間とともに戻る (半日ほどで半分.
  戻りの速さは人ごと・日ごとに揺らぐ). 返事しだいで: 褒められた → 数時間乗ってくる / 嫌がられた・返事がなかった → 下がり, 数日は戻りが遅い.
  回数の上限・決まった間隔は置かない (この値と確率だけで量が決まり, 日によってぶれる. 11/28 ユーザー).
- 場面 (割合への倍率. scene): 新しい服をまだ見せていない (手に入れて NEW_DAYS 日まで) × NEW_MULT / 目を引きたい (寂しいのに構われていない・
  しばらく会っていない) × ATTN_MULT / 褒められた直後 × PRAISED_MULT. 疲れ・体調不良・機嫌が悪いと下がる.
- 出口: そばで見せる (core/posing.py の live. ポーズ・見せて・着替えて見せる) と, 離れていて送る写メ (photo_live).
  写メは形に残るので, 大胆さの上限をそばより 1 段下げ, 慎重 (traits の caution) が高いほど控える.
- 遡及: 見せたい気持ちは START から. いま持っている服は「もう見せた」扱い (showy.since より前に手に入れた服は新しい服にしない).
"""
import math
import random
import time
from datetime import datetime

from . import prefs as prefs_mod

START = 0.6
HALF_H = 12.0              # 見せたい気持ちが半分戻るまで (時間)
SHOW_LEFT = 0.7            # 見せたあとに残る割合
AFTER = {"good": 1.0, "neutral": 0.9, "bad": 0.5, "ignored": 0.6}      # 返事しだいで, さらに掛ける
SLOW_DAYS = {"bad": 3, "ignored": 2}       # 戻りが遅い日数
SLOW_SPEED = 0.4
PRAISED_H = 4
PRAISED_MULT = 1.3
NEW_DAYS = 7
NEW_MULT = 2.5
ATTN_MULT = 1.7
LOW_MULT = 0.3             # 疲れ・体調不良・機嫌が悪い
NEW_KINDS = ("casual", "formal", "lounge", "swim", "costume")     # 着替えて見せる新しい服 (一式・ワンピース. 部品だけの服・パジャマ・仕事着は見せない)
SHOW_KINDS = ("swim", "costume")           # 新しくなくても, 着替えて見せることのある服
PHOTO_RATE = 0.06          # 離れていて写メを送る (1 時間あたり. その気と見せたい気持ちと場面を掛ける)
PHOTO_WAIT = 3 * 3600      # 写メへの返事を待つ
DATE_H = 3                 # 会う約束の何時間前から「今日これで行くけど」
DATE_MULT = 4.0


class Showoff:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 見せたい気持ち
    def rec(self, char, st, now):
        r = st.get("showy")
        if not r:
            r = st["showy"] = {"v": START, "t": now, "since": now}
            return r
        h = max(0.0, now - float(r.get("t", now))) / 3600.0
        if h:
            day = datetime.fromtimestamp(now).date().isoformat()
            speed = random.Random("showy|%s|%s" % (char.get("id"), day)).uniform(0.7, 1.4)
            if now < float(r.get("slow_until", 0)):
                speed *= SLOW_SPEED
            r["v"] = round(1.0 - (1.0 - float(r.get("v", START))) * 0.5 ** (h * speed / HALF_H), 4)
            r["t"] = now
        return r

    def level(self, char, st, now):
        return float(self.rec(char, st, now)["v"])

    def shown(self, char, st, now, key=None):
        """見せた (そば・写メ・着替え). 新しい服なら「もう見せた」に."""
        r = self.rec(char, st, now)
        r["v"] = round(float(r["v"]) * SHOW_LEFT, 4)
        r["last"] = now
        if key:
            sh = st.setdefault("shown", [])
            if key not in sh:
                sh.append(key)
                del sh[:-60]

    def reacted(self, char, st, how, now):
        """見せたものへの返事 (good / neutral / bad / ignored)."""
        r = self.rec(char, st, now)
        r["v"] = round(float(r["v"]) * AFTER.get(how, 1.0), 4)
        if how == "good":
            r["praised"] = now
        if how in SLOW_DAYS:
            r["slow_until"] = max(float(r.get("slow_until", 0)), now + SLOW_DAYS[how] * 86400)

    # ------------------------------------------------------------------ 場面
    def cap(self, char, st):
        """自分から見せる大胆さの上限 (着る服の上限 + ドキドキ 50 以上で 1. core/posing.py の pick と同じ)."""
        return self.app.wardrobe.comfort(char, st) + (1 if st["params"].get("heart", 0) >= 50 else 0)

    def new_clothes(self, char, st, now, cap=None):
        """手に入れてまだ見せていない服 (一式・ワンピース. NEW_DAYS 日まで. 着られる大胆さまで)."""
        r = self.rec(char, st, now)
        cap = self.cap(char, st) if cap is None else cap
        sh = set(st.get("shown") or [])
        return [o for o in self.app.wardrobe.owned(char)
                if o.get("kind") in NEW_KINDS and o.get("slot") in ("set", "onepiece") and float(o.get("owned_t") or 0) > float(r.get("since", now))
                and now - float(o.get("owned_t") or 0) < NEW_DAYS * 86400 and o["key"] not in sh and o["id"] not in sh and o["bold"] <= cap]

    def attention(self, char, st, now, apart):
        """目を引きたい: 寂しいのに構われていない (そばで作業中・しばらくやりとりがない) / 離れていて, しばらく会っていない."""
        p = st["params"]
        if p.get("loneliness", 0) < 60:
            return False
        if apart:
            return now - float(st.get("last_interaction") or now) > 2 * 86400
        return self.app.presence.at(now) == "busy" or now - float(st.get("last_interaction") or now) > 2 * 3600

    def scene(self, char, st, now, apart):
        """(倍率, 理由). 理由: new (新しい服) / attention (目を引きたい) / ""."""
        p = st["params"]
        r = self.rec(char, st, now)
        m, why = 1.0, ""
        if self.new_clothes(char, st, now):
            m, why = NEW_MULT, "new"
        elif self.attention(char, st, now, apart):
            m, why = ATTN_MULT, "attention"
        if now - float(r.get("praised", 0)) < PRAISED_H * 3600:
            m *= PRAISED_MULT
        if p.get("energy", 50) < 30 or p.get("health", 100) < 50 or p.get("mood", 50) < 35 or self.app.quarrel.active(st, now):
            m *= LOW_MULT
        return m, why

    def base(self, char, st):
        """好みが無くても, 人懐っこい・おどけが平気な人は, 仲が深ければ自分から見せることがある (その気 eagerness の下限)."""
        tr = self.app.traits(char)
        if st["params"].get("affection", 0) < 50:
            return 0.0
        return 0.05 * float(tr.get("approach", 1) or 1) + 0.08 * max(0.0, float(tr.get("play", 0) or 0))

    # ------------------------------------------------------------------ 離れていて写メ
    def date_soon(self, cid, now):
        """今日, もうすぐ会う約束 (DATE_H 時間以内. あなたと会う約束)."""
        for x in self.app.appoint.all():
            if x.get("cid") == cid and x.get("status") in ("set", "waiting") and 0 < float(x.get("t", 0)) - now <= DATE_H * 3600:
                return x
        return None

    def photo_live(self, char, st, now, rng=random):
        """離れている相手が, 見せたい気持ちになって写メを送ってくる. 返事待ちが切れたら, 返事がなかったことに."""
        app = self.app
        cid = char["id"]
        off = st.get("pose_offer")
        if off and off.get("kind") == "photo" and now >= off["until"]:
            st["pose_offer"] = None
            self.reacted(char, st, "ignored", now)
            return None
        if off or st.get("approach") or not app.posing.adult_ok(char):
            return None
        if app.bonds.stage(cid) not in ("contact", "visit", "live") or app.bonds.together(cid):
            return None
        last = st.get("photo_check") or now
        st["photo_check"] = now
        dt_h = min(max(now - last, 0), 600) / 3600.0
        if not dt_h:
            return None
        dt = datetime.fromtimestamp(now)
        sc = app.scheduled_scene(char, dt)
        if sc.get("asleep"):
            return None
        mult, why = self.scene(char, st, now, apart=True)
        date = self.date_soon(cid, now)
        if date and st.get("photo_date") != date["id"]:
            mult *= DATE_MULT
            why = "date"
        caution = float(app.traits(char).get("caution", 0) or 0)
        rate = PHOTO_RATE * (app.posing.eagerness(char, st) + self.base(char, st)) * self.level(char, st, now) * mult \
            * max(0.3, 1 - caution / 15.0) * (0.4 if sc.get("busy") or sc.get("away") else 1.0)
        if rng.random() >= 1 - math.exp(-rate * dt_h):
            return None
        return self.send_photo(char, st, now, why, date, rng)

    def send_photo(self, char, st, now, why, date=None, rng=random):
        """写メを送る (画像つきのメッセージ. 返事は感想と同じ選び方で, トークの「↩ 返す」から)."""
        app = self.app
        cid = char["id"]
        item, itype, key = None, None, None
        if why == "new":
            news = self.new_clothes(char, st, now, cap=max(0, self.cap(char, st) - 1))
            if news:
                item = rng.choice(news)
                st["dress"] = {"id": item["key"], "t": now, "by": "her"}      # 着てみた (寝るまで. engine の着替えと同じ)
                itype, key = "outfit", "photo.new"
        if not item and why == "date":
            itype, key = "wear", "photo.date"
            st["photo_date"] = date["id"]
        if not item and not itype:
            o = app.posing.pick(char, st, rng, cap_drop=1)
            if not o:
                return None
            item, itype, key = o, o["type"], "photo." + o["type"]
        name = (item or {}).get("name", "")
        text = app.persona_text(char, key) or app.posing.line(key)
        if why == "attention":
            pre = app.persona_text(char, "photo.attention") or app.posing.line("photo.attention")
            text = pre.rstrip("』") + " " + text.lstrip("📱『") if pre.endswith("』") and text.startswith("📱『") else pre + " " + text
        text = text.replace("{item}", name)
        dt = datetime.fromtimestamp(now)
        scene = app.scene_at(char, st, dt)
        text = app.format_text(text, char, scene, dt)
        pos = "selfie, holding smartphone, looking at viewer" + ((", " + item["pos"]) if itype in ("pose", "show") and item.get("pos") else ", full body")
        act = {"id": "_photo", "name": "写メ", "icon": "📷", "pos": pos, "neg": (item or {}).get("neg", "") if itype in ("pose", "show") else ""}
        ppos, pneg, parts = app.build_prompt(char, st, dt, act)
        e = app._new_entry(cid, now, act, text + "\n（📷 写真が添えられていた）", {}, scene, dt, ppos, pneg, parts)
        e["selfie"] = True
        if app.settings.get("auto_generate"):
            e["job"] = app._present_image(cid, e)
        app.chat.add(cid, "her", text + "\n（📷 写真が添えられていた）", kind="her_photo", t=now, selfie=True, entry=e["id"])
        app.picked_up_phone(char, st, now)
        ik = (item or {}).get("key") or (item or {}).get("id") or ""
        st["pose_offer"] = {"kind": "photo", "itype": itype, "item": ik, "name": name, "t": now, "until": now + PHOTO_WAIT, "entry": e["id"]}
        self.shown(char, st, now, ik if itype == "outfit" else None)
        app.trace.add("showoff", "写メ: %s %s" % (itype, name), cid, now, why=why)
        app.save_log(cid)
        return e

    def pref_key(self, off):
        """返事で覚える好みの鍵."""
        if off.get("itype") in ("pose", "show"):
            return "%s:%s" % (off["itype"], off["item"])
        if off.get("itype") == "outfit" and off.get("item"):
            return "outfit:" + off["item"]
        return None

    def learn(self, st, off, amount, now=None):
        k = self.pref_key(off)
        if k:
            prefs_mod.learn(st, k, amount, now or time.time())
