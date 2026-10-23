"""出先でのばったり (外出中の偶然の出会いの中身).

- 誰に会うか: 人にはそれぞれ「よく行く場所と時間帯」(顔なじみの理由) がある. 同じ場所・同じ時間帯に通えば, 同じ人にまた会いやすい.
  仕事中に会うのは同僚だけ. 初めて見る顔 (このワールドにまだ現れていない定義の人, いなければ新しく作った人) もいる.
- 段階的に知り合う: まだ知らない → 見かけたことがある → 会釈する仲 → 立ち話する仲 → 知り合い (ここで登録するかを尋ねる).
  何度か会ううちに進むかどうかは, こちらの反応・相手の性格 (慎重さ)・偶然しだいで, 進まないこともある.
- 相手から声をかけられたら, こちらも反応を選ぶ (応じる / 会釈だけ / 急いでいると断る). 気づかずに時間が過ぎたら,
  無視ではなく, 無難に会釈して流したことになる. 見かけただけなら (声をかける / 会釈 / 通り過ぎる), 気づかなければ通り過ぎる.
  相手から声をかけられたときは, 名前を呼ばれれば気づくのと同じく知らせる (画面の知らせ・控えめな音・タブの題名).
  見かけただけのときは控えめ (こちらが気づくかどうか).
記録は data/worlds/<id>/people.json (登録していない人) と, 登録キャラのログ.
"""
import hashlib
import json
import random
import time
import uuid
from datetime import datetime

from . import store
from .places import PLACES

STAGES = ["まだ知らない", "見かけたことがある", "会釈する仲", "立ち話する仲", "知り合い"]
CALL_P = [0.08, 0.2, 0.45, 0.6, 0.6]          # 段階ごとの, 相手から声をかけてくる起きやすさ
TIMEOUT = 150                                 # 返事を選ばずにこれだけ過ぎたら, 無難な対応に落ち着く (秒)
NEW_FACE_W = 1.0
OPTIONS = {"call": [("chat", "応じて立ち話する"), ("nod", "軽く会釈する"), ("decline", "急いでいると断る")],
           "sight": [("talk", "声をかける"), ("nod", "会釈する"), ("pass", "そのまま通り過ぎる")]}
HAUNT_PLACES = ["park", "shopping_street", "riverside", "station", "cafe", "mall"]
HAUNT_PHASES = ["morning", "noon", "evening", "night"]
# 共通のセリフ (性格プリセットに無ければ). {call} は知り合いのときだけ
LINES = {"enc.call.first": "あの……すみません、これ、落としませんでしたか？",
         "enc.call.again": "あ……よく、ここで会いますね。",
         "enc.call.known": "あれ、{call}？ こんなところで会うなんて、偶然ですね。",
         "enc.chat": "ふふ、ちょっとだけお話ししちゃいましたね。……この辺、よく来るんですか？",
         "enc.decline": "あ、ごめんなさい。お急ぎでしたね。",
         "enc.join.invite": "あの、{call}。よかったら、このまま少し一緒にいませんか？",
         "enc.join.yes": "いいですよ。じゃあ、少しだけ一緒に。",
         "enc.join.no": "ごめんなさい、このあと用事があって……また今度。"}
JOIN_WAIT = 600         # 立ち話のあと, 一緒に過ごすか決めるまで (秒)


def haunts_of(c):
    """その人がよく行く場所と時間帯 (名前と外見から決まる. ワールドが違っても同じ人は同じ習慣)."""
    seed = int(hashlib.md5(("%s|%s" % (c.get("name", ""), c.get("pos", ""))).encode("utf-8")).hexdigest()[:8], 16)
    rng = random.Random(seed)
    out = [[rng.choice(HAUNT_PLACES), rng.choice(HAUNT_PHASES)] for _ in range(2)]
    if rng.random() < 0.2:
        out.append(["office", None])      # 同じ職場
    return out


class Street:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ 記録
    def people(self):
        return store.load(store.wpath("people.json"), {}) or {}

    def save_people(self, ppl):
        store.save(store.wpath("people.json"), ppl)

    def rec(self):
        return self.app.presence.rec()

    def pending(self):
        return self.rec().get("street_pending")

    # ------------------------------------------------------------------ 誰に会うか
    @staticmethod
    def _weight(haunts, place, phase, work):
        if work:
            return 3.0 if any(h[0] == "office" for h in haunts) else 0.0
        if [place, phase] in haunts:
            return 6.0
        if any(h[0] == place for h in haunts):
            return 2.0
        return 0.3

    def happen(self, cur, now=None):
        """外出中の出会い. cur: {kind, place, with}. 返事待ちのばったりがあるうちは, 次は起きない."""
        app = self.app
        now = now or time.time()
        if self.pending():
            return None
        from .outdoor import PLACES
        phase = app.phase_at(datetime.fromtimestamp(now)).get("id", "noon")
        place, work, with_cid = cur["place"], cur["kind"] == "work", cur.get("with")
        live = app.bonds.living()
        pool = []
        for cid, c in app.chars.items():
            if cid in (with_cid, live):
                continue
            w = self._weight(haunts_of(c), place, phase, work)
            if w:
                pool.append((w, "char", cid))
        ppl = self.people()
        for pid, pr in ppl.items():
            if pr.get("cid") or (pr.get("src") or {}).get("id") in app.chars:
                continue                    # このワールドに現れた人は, キャラとして上で数える
            w = self._weight(pr.get("haunts") or haunts_of(pr["char"]), place, phase, work)
            if w:
                pool.append((w, "person", pid))
        coworkers = sum(1 for pr in ppl.values() if pr.get("coworker"))
        new_w = (0.8 if coworkers < 6 else 0.0) if work else NEW_FACE_W
        if new_w:
            pool.append((new_w, "new", None))
        if not pool:
            return None
        _, kind, who = random.choices(pool, [x[0] for x in pool])[0]
        if kind == "new":
            who = self._new_person(ppl, place, phase, work, now)
            kind = "person"
        where = (PLACES.get(place) or PLACES["town"])["label"]
        return self._meet(kind, who, where, with_cid, now, place)

    def _new_person(self, ppl, place, phase, work, now):
        enc = self.app.encounters
        seen = {(pr["char"].get("name"), pr["char"].get("pos")) for pr in ppl.values()}
        cands = [(wid, c) for wid, c in enc.candidates() if (c.get("name"), c.get("pos")) not in seen]
        if cands:
            _, c = random.choice(cands)
            src = {"type": "def", "id": c["id"]}       # すでにある定義の人 (このワールドでは初対面)
            c = {k: v for k, v in json.loads(json.dumps(c)).items() if k not in ("prompt_history", "met", "id")}
        else:
            c, src = enc.generate(), {"type": "new"}
        pid = "p" + uuid.uuid4().hex[:8]
        hs = haunts_of(c)
        if not work and [place, phase] not in hs:
            hs.append([place, phase])        # ここで会ったのは, ここに来る習慣があるから
        ppl[pid] = {"char": c, "stage": 0, "meets": 0, "last": 0, "haunts": hs, "coworker": work or any(h[0] == "office" for h in hs),
                    "src": src, "first": now}
        self.save_people(ppl)
        return pid

    def _meet(self, kind, who, where, with_cid, now, place=None):
        app = self.app
        if kind == "char":
            c = app.chars[who]
            stage_i = 4
            p_call = 0.7 if app.bonds.stage(who) != "known" else 0.4
            name = c.get("name", "")
        else:
            ppl = self.people()
            pr = ppl[who]
            c, stage_i = pr["char"], int(pr.get("stage", 0))
            pr["meets"], pr["last"] = pr.get("meets", 0) + 1, now
            self.save_people(ppl)
            p_call = CALL_P[min(stage_i, 4)] * (0.3 if now < pr.get("cool_until", 0) else 1.0)
            name = c.get("name", "") if stage_i >= 3 else ("見覚えのある人" if stage_i >= 1 else "知らない人")
        p_call *= float((self.app.personas.get(c.get("persona_id") or "") or {}).get("traits", {}).get("approach", 1))
        typ = "call" if random.random() < min(0.9, p_call) else "sight"
        text = ""
        if typ == "call":
            key = "enc.call.known" if kind == "char" else "enc.call.again" if stage_i >= 2 else "enc.call.first"
            text = self._line(c, key, where)
        pend = {"kind": kind, "who": who, "type": typ, "t": now, "until": now + TIMEOUT, "where": where, "with": with_cid,
                "name": name, "text": text, "stage": stage_i, "place": place}
        self.rec()["street_pending"] = pend
        app.presence.save()
        msg = ("%sで、%sに声をかけられた" % (where, name)) if typ == "call" else ("%sで、%sを見かけた" % (where, name))
        app.outdoor.note(msg, now)
        return {"kind": typ, "name": name, "where": where, "text": "（%s）" % msg}

    def _line(self, c, key, where):
        app = self.app
        t = app.persona_text(c, key) or LINES[key]
        fp, _, call = app.pronouns(c)
        return t.replace("{fp}", fp).replace("{call}", call).replace("{name}", c.get("name", "")).replace("{location}", where)

    # ------------------------------------------------------------------ 反応
    def live(self, now=None):
        """返事を選ばないまま時間が過ぎていたら, 無難な対応に落ち着かせる."""
        now = now or time.time()
        pend = self.pending()
        if pend and now >= pend["until"]:
            return self.resolve("nod" if pend["type"] == "call" else "pass", auto=True, now=now)
        return None

    def answer(self, choice):
        pend = self.pending()
        if not pend:
            raise ValueError("いまは誰とも会っていません")
        if choice not in [o[0] for o in OPTIONS[pend["type"]]]:
            raise ValueError("選べない反応です: %s" % choice)
        return self.resolve(choice)

    def resolve(self, choice, auto=False, now=None):
        app = self.app
        now = now or time.time()
        pend = self.rec().pop("street_pending", None)
        app.presence.save()
        if not pend:
            return None
        talk = choice in ("chat", "talk")
        name, where = pend["name"], pend["where"]
        if pend["kind"] == "char":
            out = self._resolve_char(pend, choice, talk, auto, now)
        else:
            out = self._resolve_person(pend, choice, talk, auto, now)
        app.outdoor.note(out["text"].split("\n")[0].strip("（）"), now)
        out.update(choice=choice, auto=auto, name=name, where=where)
        return out

    def _resolve_person(self, pend, choice, talk, auto, now):
        app = self.app
        ppl = self.people()
        pr = ppl.get(pend["who"])
        if not pr:
            return {"text": "（その人は、もういなかった）"}
        c = pr["char"]
        stage = int(pr.get("stage", 0))
        caution = float(((app.personas.get(c.get("persona_id") or "") or {}).get("traits") or {}).get("caution", 0))
        f = max(0.3, 1 + caution / 40.0)
        noticed = not (auto and pend["type"] == "sight")
        if noticed:
            stage = max(stage, 1)          # 見かけた (声をかけられた) ことは覚えている
        line = ""
        if talk:
            p_adv = (0.6 if pend["type"] == "call" else 0.45) * f
            line = self._line(c, "enc.chat", pend["where"])
        elif choice == "nod":
            p_adv = (0.2 if auto else 0.35) * f if stage < 2 else 0.0      # 会釈だけでは, 会釈する仲より先には進まない
        else:
            p_adv = 0.0
            if choice == "decline":
                pr["cool_until"] = now + 3 * 86400
                line = self._line(c, "enc.decline", pend["where"])
        adv = stage < 4 and random.random() < p_adv * (0.9 + 0.2 * app.life.skill_soft("groom"))     # 身だしなみで, 少しだけ
        if adv:
            stage += 1
        pr["stage"] = stage
        self.save_people(ppl)
        what = {"chat": "少し立ち話をした", "talk": "声をかけて、少し話した", "nod": "会釈して流した" if auto else "軽く会釈した",
                "decline": "急いでいると断った", "pass": "気づかずに通り過ぎた" if auto else "そのまま通り過ぎた"}[choice]
        label = c.get("name", "") if stage >= 3 else ("見覚えのある人" if stage >= 1 else "知らない人")
        text = "（%s%s）" % (what, "。%sとは「%s」になった" % (label, STAGES[stage]) if adv else "")
        if line:
            text += "\n" + line
        asked = False
        if stage >= 4 and not pr.get("cid") and not app.encounters.pending() and pr.get("asked_meets", -9) + 3 <= pr.get("meets", 0):
            # 知り合いになった: 連絡先を交換して登録するか尋ねる (断っても, また何度か会えば)
            pr["asked_meets"] = pr.get("meets", 0)
            self.save_people(ppl)
            app.encounters.ask_register(c, pend["where"], pend.get("with"), pr.get("src") or {"type": "new"}, pid=pend["who"], now=now)
            asked = True
        return {"text": text, "stage": stage, "advanced": adv, "asked": asked}

    def _resolve_char(self, pend, choice, talk, auto, now):
        app = self.app
        cid = pend["who"]
        if cid not in app.chars:
            return {"text": "（その人は、もういなかった）"}
        char = app.char(cid)
        exchanged = introduced = False
        with app.lock:
            app.tick(cid)
            st = app.state(cid)
            eff, line = {}, ""
            if talk:
                eff = {"mood": 3, "loneliness": -6, "affection": 1}
                line = self._line(char, "enc.chat", pend["where"])
            elif choice == "nod":
                eff = {"mood": 1}
            elif choice == "decline":
                eff = {"mood": -3}
                line = self._line(char, "enc.decline", pend["where"])
                app.life.add_reason(st, "player", "bad", "%sに、急いでいると流された" % app.pronouns(char)[2], now, told=False,
                                    action="_street")
            deltas = {}
            if eff:
                eff, _ = app.bonds.realize(char, st, eff, "_encounter", now)
                deltas = app.apply_effects(st, app.trait_effects(char, eff))
            if talk:
                app.bonds.touch(st, now)
                # 知り合いとは, 話の流れで連絡先を交換することも (あなたの話のうまさ・相手の機嫌と好感度・性格しだい)
                if app.bonds.stage(cid) == "known" and random.random() < app.bonds.exchange_chance(char, st):
                    app.bonds.set_stage(cid, "contact", now)
                    exchanged = True
                w = pend.get("with")
                if w in app.chars:
                    for a, b in ((cid, w), (w, cid)):
                        if not app.relation(a, b)["knows"]:
                            app.change_affinity(a, b, 0)
                            introduced = True
            what = {"chat": "少し立ち話をした", "talk": "声をかけて、少し話した", "nod": "会釈して流した" if auto else "軽く会釈した",
                    "decline": "急いでいると断った", "pass": "気づかずに通り過ぎた" if auto else "そのまま通り過ぎた"}[choice]
            text = "（%sで%sに会った。%s%s%s）" % (pend["where"], char.get("name", ""), what, "。連絡先を交換した" if exchanged else "",
                                             "。一緒にいた人を紹介した" if introduced else "")
            if line:
                text += "\n" + line
            join = self._join_chance(char, st, pend, talk, auto, now)
            if join and join["offer"]:
                text += "\n" + join["line"]
            if choice != "pass" or not auto:
                app.encounters._entry(cid, now, "ばったり", "✨", text, deltas)
            app.save_state(cid)
        return {"text": text, "exchanged": exchanged, "introduced": introduced, "join": join}

    # ------------------------------------------------------------------ そのまま一緒に過ごす (出先での合流)
    def _join_chance(self, char, st, pend, talk, auto, now):
        """立ち話をした連絡先の相手とは, そのまま一緒に過ごす話になることがある. 相手から誘われる (仲・寂しさ・性格しだい)
        か, こちらから誘える (受けるかは相手しだい). 一人で出かけているときだけ. 決めるまでの記録 street_join を返す (無ければ None)."""
        app = self.app
        cid = char["id"]
        p = app.presence.rec()
        if not talk or auto or pend.get("with") or p.get("mode") != "out" or app.bonds.stage(cid) not in ("contact", "visit") \
                or app.bonds.with_rec():
            return None
        pr = st["params"]
        po = (0.15 + (pr.get("affection", 50) - 50) / 100.0 + (pr.get("loneliness", 50) - 50) / 200.0) \
            * float(app.traits(char).get("approach", 1))
        offer = pr.get("affection", 0) >= 40 and random.random() < max(0.0, min(0.6, po))
        j = {"cid": cid, "name": char.get("name", ""), "place": pend.get("place") or "town", "where": pend["where"], "t": now,
             "until": now + JOIN_WAIT, "offer": offer}
        if offer:
            j["line"] = self._line(char, "enc.join.invite", pend["where"])
        p["street_join"] = j
        app.presence.save()
        return dict(j)

    def join_view(self, now=None):
        now = now or time.time()
        j = self.rec().get("street_join")
        if not j or now >= j["until"] or self.rec().get("mode") != "out":
            return None
        return {"cid": j["cid"], "name": j["name"], "where": j["where"], "offer": j["offer"], "line": j.get("line", "")}

    def join(self, yes, now=None):
        """一緒に過ごすか決める. 相手から誘われていれば yes で合流 (no なら別れる).
        誘われていなければ, yes はこちらから誘う (断られることも). 結果 {joined, text} を返す."""
        app = self.app
        now = now or time.time()
        j = self.rec().pop("street_join", None)
        app.presence.save()
        if not j or now >= j["until"] or j["cid"] not in app.chars or self.rec().get("mode") != "out":
            raise ValueError("いまは誰とも一緒にいません")
        cid = j["cid"]
        char = app.char(cid)
        if not yes:
            text = "（%sとは、そこで別れた）" % char.get("name", "")
            if j["offer"]:          # 誘ったのに断られた: 少しだけ残念 (性格しだい)
                with app.lock:
                    st = app.state(cid)
                    app.apply_effects(st, app.trait_effects(char, {"mood": -1}))
                    app.save_state(cid)
            app.outdoor.note(text.strip("（）"), now)
            return {"joined": False, "text": text}
        with app.lock:
            st = app.state(cid)
            pr = st["params"]
            line = ""
            if not j["offer"]:      # こちらから誘う: 受けるかは仲・機嫌・慎重さしだい (補正なし)
                pj = 0.3 + (pr.get("affection", 50) - 50) / 80.0 + (pr.get("mood", 50) - 50) / 120.0 \
                    + (0.15 if app.bonds.stage(cid) == "visit" else 0.0) - float(app.traits(char).get("caution", 0)) / 40.0
                ok = random.random() < max(0.05, min(0.9, pj))
                line = self._line(char, "enc.join.yes" if ok else "enc.join.no", j["where"])
                if not ok:
                    text = "（%sを誘ったが、断られた）\n%s" % (char.get("name", ""), line)
                    app.encounters._entry(cid, now, "誘ってみた", "🚶", text, {})
                    app.outdoor.note("%sを誘ったが、断られた" % char.get("name", ""), now)
                    return {"joined": False, "text": text}
        return self._do_join(char, j, line, now)

    def _do_join(self, char, j, line, now):
        """出先で合流: 一人の外出はそこまで (過ごした時間の結果は残す). 相手と同じ行き先で, 外で会っている (meet) ことにする."""
        app = self.app
        cid = char["id"]
        ll = app.presence.back(now)
        res = app.solo.finish(ll) if ll else None
        with app.lock:
            st = app.state(cid)
            pl = j["place"] if j["place"] in PLACES else "town"
            st["override"] = {"activity": "together", "label": "%sで一緒に過ごしている" % PLACES[pl]["label"],
                              "location": PLACES[pl]["label"], "place": pl, "minutes": 90, "until": now + 90 * 60,
                              "outing": True, "outfit": "@outing", "from_action": "_join",
                              "pos": "outdoors, walking together, smile", "neg": "", "effects": {}}
            app.bonds.start(cid, "meet", now)
            eff, _ = app.bonds.realize(char, st, {"loneliness": -10, "mood": 3, "affection": 1}, "_join", now)
            app.bonds.touch(st, now)
            st["last_interaction"] = now
            deltas = app.apply_effects(st, app.trait_effects(char, eff))
            text = "（%sで、%sとそのまま一緒に過ごすことにした）" % (PLACES[pl]["label"], char.get("name", ""))
            if line:
                text += "\n" + line
            e = app.encounters._entry(cid, now, "一緒に過ごす", "🚶", text, deltas)
            app.save_state(cid)
        app.outdoor.note("%sと一緒に過ごすことにした" % char.get("name", ""), now)
        return {"joined": True, "text": text, "solo": res, "entry": e["id"] if isinstance(e, dict) else e}

    def view(self, now=None):
        pend = self.pending()
        if not pend:
            return None
        return {"type": pend["type"], "name": pend["name"], "where": pend["where"], "text": pend.get("text", ""), "t": pend["t"],
                "options": [{"id": i, "label": l} for i, l in OPTIONS[pend["type"]]]}
