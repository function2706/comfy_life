"""偶然の出会い (出かけているとき・仕事中・誰かとお出かけ中).

- このワールドに登録済みのキャラには「偶然会う」: そのキャラのログに残り, 少しうれしい.
  誰かと一緒にいたなら, その二人は互いを知る (紹介した).
- 登録していない人と知り合うこともある. 候補は「このワールドにまだ現れていないキャラの定義」, いなければ新しく作る.
  知り合ったら, 登録する (連絡先を交換する) かどうかをあなたに尋ねる. ランダムなキャラが登録されるのはここだけ.
  定義は全体に 1 つなので, ほかのワールドでも (そこに現れていなければ) 出会いの候補になる.
"""
import copy
import glob
import json
import math
import os
import random
import time
import uuid

from . import store

DEFAULTS = {"start_contact": 0.4, "start_known": 0.35, "rate_work": 0.05, "rate_out": 0.2, "rate_outing": 0.1, "stranger_share": 0.5, "max_chance": 0.6,
            "pending_hours": 72}
WHERE = {"work": "職場", "out": "街", "outing": None}

NAMES = ["あかり", "さくら", "ゆい", "みさき", "ことね", "りん", "なつき", "しおり", "かえで", "まゆ", "あおい", "ちひろ",
         "ほのか", "すず", "れいな", "いろは", "つむぎ", "ひより", "かのん", "めい"]
HAIR_COLOR = ["black hair", "dark brown hair", "light brown hair", "blonde hair", "silver hair", "pink hair",
              "light blue hair", "red hair", "ash grey hair"]
HAIR_STYLE = ["long hair", "short hair", "bob cut", "medium hair, ponytail", "long hair, twintails", "long hair, braid",
              "medium hair, hair bun", "long hair, low ponytail", "short hair, hair clip"]
EYES = ["brown eyes", "blue eyes", "green eyes", "purple eyes", "amber eyes", "grey eyes", "red eyes"]
EXTRA = ["", "", "", "glasses", "hair ribbon", "hairband", "beauty mark", "freckles", "ahoge", "earrings"]
OUTFIT = ["casual clothes, hoodie, jeans", "casual clothes, blouse, flared skirt", "t-shirt, denim shorts",
          "sweater, pleated skirt", "shirt, cardigan, long skirt", "casual clothes, oversized sweater, leggings"]
OUTING = ["coat, scarf, skirt, shoulder bag", "jacket, blouse, long skirt, handbag", "one-piece dress, cardigan, sandals",
          "denim jacket, t-shirt, skirt, sneakers"]


class Encounters:
    def __init__(self, app):
        self.app = app

    def cfg(self):
        c = dict(DEFAULTS)
        c.update(self.app.world.get("encounters") or {})
        return c

    def pending(self):
        ps = self.app.life.player_state()
        p = ps.get("encounter")
        if p and time.time() - p.get("t", 0) > float(self.cfg()["pending_hours"]) * 3600:
            ps["encounter"] = None
            self.app.life.save_player()
            return None
        return p

    # ------------------------------------------------------------------ 起きるかどうか
    def roll(self, kind, hours, with_cid=None, where=None, now=None):
        """kind: work / out / outing. hours: 出かけていた時間. 起きたら結果 {kind, name, ...} を返す."""
        c = self.cfg()
        rate = float(c.get("rate_" + kind, 0))
        chance = min(float(c["max_chance"]), 1 - math.exp(-rate * max(0.0, hours)))
        if random.random() >= chance:
            return None
        return self.happen(kind, with_cid, where, now)

    def happen_at(self, cur, now=None):
        """外出中 (outdoor.live) に起きた出会い. 中身 (誰に会うか・声をかけられるか) は street.py. cur: {kind, place, with}."""
        return self.app.street.happen(cur, now)

    def ask_register(self, c, where, with_cid, src, pid=None, now=None):
        """知り合いになった人を, 登録する (連絡先を交換する) か尋ねる."""
        c = {k: v for k, v in json.loads(json.dumps(c)).items() if k not in ("id", "prompt_history")}
        p = (self.app.personas.get(c.get("persona_id") or "") or {})
        self.app.life.player_state()["encounter"] = {"t": now or time.time(), "kind": "street", "where": where, "with": with_cid,
                                                     "char": c, "src": src, "persona_name": p.get("name", ""), "pid": pid}
        self.app.life.save_player()

    def happen(self, kind, with_cid=None, where=None, now=None, stranger=None):
        now = now or time.time()
        where = where or WHERE.get(kind) or "出かけた先"
        live = self.app.bonds.living()       # 一緒に暮らしている人には「偶然」会わない
        known = [cid for cid in self.app.chars if cid not in (with_cid, live)]
        # 偶然は偶然: 知らない人に会いやすくする補正も, 誰かに必ず会わせる代わりもない (会わないまま終わってよい)
        if stranger is None:
            stranger = random.random() < float(self.cfg()["stranger_share"])
        if stranger:
            return None if self.pending() else self.meet_stranger(kind, with_cid, where, now)
        return self.bump(random.choice(known), kind, with_cid, where, now) if known else None

    # ------------------------------------------------------------------ 登録済みのキャラに偶然会う
    def bump(self, cid, kind, with_cid, where, now):
        app = self.app
        char = app.char(cid)
        with app.lock:
            app.tick(cid)
            st = app.state(cid)
            eff, _ = app.bonds.realize(char, st, {"mood": 3, "loneliness": -6, "affection": 1}, "_encounter", now)
            app.bonds.touch(st, now)
            deltas = app.apply_effects(st, app.trait_effects(char, eff))
            wname = app.chars[with_cid].get("name", "") if with_cid else ""
            text = "（%sで、偶然%sに会った%s）" % (where, char.get("name", ""), "。%sと一緒だったので紹介した" % wname if with_cid else "")
            exchanged = app.bonds.stage(cid) == "known"
            if exchanged:          # 知り合いだった人とは, ここで連絡先を交換する
                app.bonds.set_stage(cid, "contact", now)
                text = text[:-1] + "。連絡先を交換した）"
            introduced = False
            if with_cid:
                for a, b in ((cid, with_cid), (with_cid, cid)):
                    if not app.relation(a, b)["knows"]:
                        app.change_affinity(a, b, 0)
                        introduced = True
            e = self._entry(cid, now, "偶然会った", "✨", text, deltas)
            app.save_state(cid)
        return {"kind": "bump", "cid": cid, "name": char.get("name", ""), "where": where, "entry": e["id"],
                "introduced": introduced, "exchanged": exchanged, "text": text}

    def _entry(self, cid, now, name, icon, text, deltas):
        app = self.app
        char, st = app.char(cid), app.state(cid)
        from datetime import datetime
        dt = datetime.fromtimestamp(now)
        scene = app.scene_at(char, st, dt)
        act = {"id": "_encounter", "name": name, "icon": icon, "pos": "looking at viewer, surprised, smile, outdoors", "neg": ""}
        pos, neg, parts = app.build_prompt(char, st, dt, act)
        e = app._new_entry(cid, now, act, text, deltas, scene, dt, pos, neg, parts)
        app.save_log(cid)
        return e

    # ------------------------------------------------------------------ 登録していない人と知り合う
    def registered(self, skip_world=None, include_defaults=False):
        """キャラの定義全員 [(None, 定義)] (どのワールドで作ったか・手動かくじかを問わない)."""
        store.ensure_default_characters() if include_defaults else None
        return [(None, c) for c in store.all_characters().values()]

    def start_cast(self):
        """新しいワールドの顔ぶれ. 定義の全員について, くじで「連絡先を知っている」「知り合い」「まだ知らない」.
        まだ知らない人は, そのワールドでは偶然の出会いで知り合える. 最低一人は連絡先を知っている.
        (顔ぶれの id のリスト, {id: 間柄}) を返す. 状態・ログ・関係は新しいワールドで一から."""
        c = self.cfg()
        pc, pk = float(c["start_contact"]), float(c["start_known"])
        store.ensure_default_characters()
        pool = list(store.all_characters())
        cast, start = [], {}
        for cid in pool:
            r = random.random()
            stage = "contact" if r < pc else "known" if r < pc + pk else None
            if stage:
                cast.append(cid)
                start[cid] = stage
        if not any(s == "contact" for s in start.values()):
            if cast:
                start[random.choice(cast)] = "contact"
            else:
                if not pool:
                    g = self.generate()
                    g["id"] = "c" + uuid.uuid4().hex[:8]
                    store.save_character(g)
                    pool = [g["id"]]
                cid = random.choice(pool)
                cast.append(cid)
                start[cid] = "contact"
        return cast, start

    def candidates(self):
        """このワールドにはまだ現れていない定義 [(None, 定義)]."""
        return [(None, c) for cid, c in store.all_characters().items() if cid not in self.app.chars]

    def generate(self):
        """新しい人を作る (名前・外見・性格をくじで)."""
        app = self.app
        used = {c.get("name") for c in app.chars.values()}
        name = random.choice([n for n in NAMES if n not in used] or NAMES)
        ps = [p for p in app.personas.values() if not p.get("_custom")] or list(app.personas.values())
        p = random.choice(ps) if ps else {}
        look = ", ".join(x for x in ["1girl, solo", random.choice(HAIR_COLOR), random.choice(HAIR_STYLE), random.choice(EYES),
                                     random.choice(EXTRA)] if x)
        tmpl = app.char() if app.chars else {}
        return {"name": name, "player_call": "", "first_person": "", "persona_id": p.get("id", ""),
                "persona": p.get("persona", ""), "pos": look, "neg": "", "outfit_default": random.choice(OUTFIT),
                "outfit_outing": random.choice(OUTING), "wardrobe": copy.deepcopy(tmpl.get("wardrobe") or []),
                "schedule": copy.deepcopy(tmpl.get("schedule") or []),
                "default_activity": copy.deepcopy(tmpl.get("default_activity") or {}), "prompt_history": []}

    def meet_stranger(self, kind, with_cid, where, now):
        cands = self.candidates()
        if cands:
            _, c = random.choice(cands)
            src = {"type": "def", "id": c["id"]}          # すでにある定義の人 (このワールドでは初対面)
            c = {k: v for k, v in c.items() if k != "prompt_history"}
        else:
            c, src = self.generate(), {"type": "new"}
        c.pop("id", None)
        p = (self.app.personas.get(c.get("persona_id") or "") or {})
        enc = {"t": now, "kind": kind, "where": where, "with": with_cid, "char": c, "src": src,
               "persona_name": p.get("name", "")}
        ps = self.app.life.player_state()
        ps["encounter"] = enc
        self.app.life.save_player()
        return {"kind": "stranger", "name": c.get("name", ""), "where": where,
                "text": "（%sで、%sという人と知り合った）" % (where, c.get("name", ""))}

    def answer(self, yes):
        """知り合った人を登録する (連絡先を交換する) / しない."""
        app = self.app
        with app.lock:
            enc = self.pending()
            if not enc:
                raise ValueError("いまは知り合った人がいません")
            ps = app.life.player_state()
            ps["encounter"] = None
            app.life.save_player()
            if not yes:
                return {"registered": None}
            src = enc.get("src") or {}
            if src.get("type") == "def" and src.get("id") in store.all_characters():
                c = app.place_character(src["id"], "contact")      # すでにある定義: このワールドに現れる
            else:
                c = json.loads(json.dumps(enc["char"]))           # 新しく作った人: 定義を作って現れる
                c["id"] = "c" + uuid.uuid4().hex[:8]
                c["met"] = {"t": enc["t"], "where": enc["where"], "src": src}
                app.save_character(c)
                app.place_character(c["id"], "contact")
            if enc.get("pid"):           # 出先で段階的に知り合った人: 以後はキャラとして会う
                ppl = app.street.people()
                if enc["pid"] in ppl:
                    ppl[enc["pid"]]["cid"] = c["id"]
                    app.street.save_people(ppl)
            if enc.get("with") in app.chars:
                for a, b in ((c["id"], enc["with"]), (enc["with"], c["id"])):
                    app.change_affinity(a, b, 0)
            e = self._entry(c["id"], time.time(), "知り合った", "🤝",
                            "（%sで知り合って、連絡先を交換した）" % enc["where"], {})
            if app.settings.get("auto_generate"):
                e["job"] = app._present_image(c["id"], e)
                app.save_log(c["id"])
            return {"registered": {"id": c["id"], "name": c.get("name", "")}}

    def view(self):
        p = self.pending()
        if not p:
            return None
        c = p["char"]
        return {"name": c.get("name", ""), "where": p["where"], "persona": p.get("persona_name", ""),
                "from_world": (p.get("src") or {}).get("type") in ("world", "def"), "t": p["t"],
                "with": self.app.chars.get(p.get("with") or "", {}).get("name")}
