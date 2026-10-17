"""ミニゲーム (野球拳 / あっち向いてホイ).

ゲームの状態はキャラの state["game"] に持つ. 1 手ごとにログ記録 (セリフ・効果・画像) を作る.
セリフ・効果・プロンプト・段階は data/minigames.json で編集できる.
"""
import random
import time
from datetime import datetime

from . import cond

BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}
HANDS = ("rock", "scissors", "paper")
DIRS = ("up", "down", "left", "right")


def judge(me, her):
    """1 = あなたの勝ち, -1 = 相手の勝ち, 0 = あいこ."""
    if me == her:
        return 0
    return 1 if BEATS[me] == her else -1


class Games:
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ config
    def get(self, gid):
        for g in self.app.minigames:
            if g.get("id") == gid:
                return g
        raise KeyError("ミニゲームが見つかりません: %s" % gid)

    def _hand_name(self, g, h):
        return (g.get("hands") or {}).get(h, {}).get("name", h)

    def _dir_name(self, g, d):
        return (g.get("dirs") or {}).get(d, {}).get("name", d)

    # ------------------------------------------------------------------ helpers
    def _ctx(self, char, st, dt, game):
        ctx = self.app.context(char, st, dt)
        ctx.update({"game": game["id"], "game_stage": game.get("stage", 0), "game_round": game.get("round", 0),
                    "lives": game.get("lives", 0), "my_point": game.get("me", 0), "her_point": game.get("her", 0)})
        return ctx

    def _line(self, g, event, ctx):
        lines = (g.get("lines") or {}).get(event) or []
        return self.app.pick_reaction({"reactions": lines}, ctx) if lines else {"text": ""}

    def _fmt(self, text, char, scene, dt, extra):
        text = self.app.format_text(text, char, scene, dt)
        for k, v in extra.items():
            text = text.replace("{%s}" % k, str(v))
        return text

    def _decide_next(self, g, game):
        """相手の次の手を先に決め, ときどき予告 (本当とは限らない) を用意する."""
        w = {h: 1.0 for h in HANDS}
        if game.get("last_her"):
            w[game["last_her"]] = 0.7          # 同じ手は続けにくい (人間っぽさ)
        nxt = random.choices(HANDS, [w[h] for h in HANDS])[0]
        game["next"] = nxt
        game["hint"] = None
        if random.random() < float(g.get("hint_rate", 0.3)):
            honest = random.random() < float(g.get("hint_honesty", 0.6))
            game["hint"] = nxt if honest else random.choice([h for h in HANDS if h != nxt])

    def stage_outfit(self, g, char, st, stage, giveup=False):
        """野球拳の段階に応じた服装 (段階 1..n を順に適用)."""
        base = self.app.scene_at(char, dict(st, game=None), datetime.now())   # 着せ替え込みの今の服
        pos, neg, remove = base["outfit"], base["outfit_neg"], []
        steps = list((g.get("stages") or [])[1:stage + 1])
        if giveup and g.get("giveup"):
            steps.append(g["giveup"])
        label = (g.get("stages") or [{}])[0].get("label", "") if stage == 0 else ""
        for s in steps:
            if s.get("mode") == "replace":
                pos, neg = s.get("pos", ""), s.get("neg", "")
            else:
                pos = ", ".join(x for x in (pos, s.get("pos", "")) if x)
                neg = ", ".join(x for x in (neg, s.get("neg", "")) if x)
            remove += [t.strip() for t in (s.get("remove") or "").split(",") if t.strip()]
            label = s.get("label", "")
        return {"pos": pos, "neg": neg, "remove": remove, "label": label}

    # ------------------------------------------------------------------ record
    def _record(self, cid, char, st, g, event_line, extra, act_pos, effects_key, round_label):
        """1 手分のログ記録を作り, 効果を適用し, 画像を出す."""
        now = time.time()
        dt = datetime.fromtimestamp(now)
        deltas = self.app.apply_effects(st, (g.get("effects") or {}).get(effects_key) or {}) if effects_key else {}
        scene = self.app.scene_at(char, st, dt)
        text = self._fmt(event_line.get("text", ""), char, scene, dt, extra)
        pseudo = {"id": "_game_" + g["id"], "name": "%s%s" % (g.get("name", ""), round_label),
                  "icon": g.get("icon", "🎲"), "pos": ", ".join(x for x in (g.get("pos", ""), act_pos) if x),
                  "neg": g.get("neg", "")}
        pos, neg, parts = self.app.build_prompt(char, st, dt, pseudo, event_line)
        st["last_interaction"] = now
        entry = self.app._new_entry(cid, now, pseudo, text, deltas, scene, dt, pos, neg, parts)
        job = None
        if self.app.settings.get("auto_generate"):
            job = self.app._present_image(cid, entry)
        return entry, job

    def _finish(self, st):
        st["game"] = None

    # ------------------------------------------------------------------ API
    def view(self, char, st, ctx):
        games = []
        for g in self.app.minigames:
            desc = (g.get("desc") or "").replace("{name}", char.get("name", "")).replace("{target}", str(g.get("target", 3)))
            games.append({"id": g["id"], "name": g.get("name", g["id"]), "icon": g.get("icon", "🎲"), "desc": desc,
                          "ok": cond.check(g.get("require", ""), ctx), "require": g.get("require", "")})
        cur = st.get("game")
        out = None
        if cur:
            g = self.get(cur["id"])
            out = {"id": cur["id"], "name": g.get("name"), "kind": g.get("kind"), "round": cur.get("round", 0),
                   "phase": cur.get("phase", "rps"),
                   "hands": {h: {"name": self._hand_name(g, h), "icon": (g.get("hands") or {}).get(h, {}).get("icon", "")} for h in HANDS},
                   "dirs": {d: {"name": self._dir_name(g, d), "icon": (g.get("dirs") or {}).get(d, {}).get("icon", "")} for d in DIRS}}
            if g.get("kind") == "yakyuken":
                out.update(stage=cur.get("stage", 0), stages=len(g.get("stages") or []),
                           stage_label=(cur.get("outfit") or {}).get("label", ""),
                           lives=cur.get("lives", 0), lives_max=int(g.get("lives", 3)))
            else:
                out.update(me=cur.get("me", 0), her=cur.get("her", 0), target=int(g.get("target", 3)))
        return {"list": games, "current": out}

    def start(self, gid, cid=None):
        app = self.app
        with app.lock:
            char = app.char(cid)
            cid = char["id"]
            app.tick(cid)
            st = app.state(cid)
            g = self.get(gid)
            dt = datetime.now()
            ctx = app.context(char, st, dt)
            if not cond.check(g.get("require", ""), ctx):
                raise ValueError("今は「%s」で遊べません（%s）" % (g.get("name"), g.get("require")))
            game = {"id": gid, "round": 0, "phase": "rps", "started": time.time(), "stage": 0,
                    "lives": int(g.get("lives", 3)), "me": 0, "her": 0}
            gctx = self._ctx(char, st, dt, game)
            if not cond.check(g.get("when", ""), ctx):
                line = self._line(g, "refuse", gctx) if (g.get("lines") or {}).get("refuse") else \
                    {"text": "今はちょっと……", "pos": ""}
                entry, job = self._record(cid, char, st, g, line, {}, "", None, "")
                app.save_state(cid)
                app.save_log(cid)
                return {"entry": entry, "job": job, "refused": True}
            if g.get("kind") == "yakyuken":
                game["outfit"] = self.stage_outfit(g, char, st, 0)
            self._decide_next(g, game)
            st["game"] = game
            line = self._line(g, "start", gctx)
            entry, job = self._record(cid, char, st, g, line, {}, "", "start", "")
            app.save_state(cid)
            app.save_log(cid)
            return {"entry": entry, "job": job, "hint": self._hint_text(char, st, g, game)}

    def _hint_text(self, char, st, g, game):
        if not game.get("hint"):
            return None
        line = self._line(g, "hint", self._ctx(char, st, datetime.now(), game))
        scene = self.app.scene_at(char, st, datetime.now())
        return self._fmt(line.get("text", ""), char, scene, datetime.now(), {"hint_hand": self._hand_name(g, game["hint"])})

    def move(self, cid=None, hand=None, direction=None):
        app = self.app
        with app.lock:
            char = app.char(cid)
            cid = char["id"]
            app.tick(cid)
            st = app.state(cid)
            game = st.get("game")
            if not game:
                raise ValueError("ゲーム中ではありません")
            g = self.get(game["id"])
            dt = datetime.now()
            if not cond.check(g.get("require", ""), app.context(char, st, dt)):
                line = self._line(g, "interrupted", self._ctx(char, st, dt, game))
                self._finish(st)
                entry, job = self._record(cid, char, st, g, line, {}, "", "quit", "")
                app.save_state(cid)
                app.save_log(cid)
                return {"entry": entry, "job": job, "ended": "interrupted"}
            if g.get("kind") == "yakyuken":
                r = self._move_yakyuken(cid, char, st, g, game, hand)
            else:
                r = self._move_acchimuite(cid, char, st, g, game, hand, direction)
            if st.get("game"):
                r["hint"] = self._hint_text(char, st, g, st["game"])
            app.save_state(cid)
            app.save_log(cid)
            return r

    def quit(self, cid=None):
        app = self.app
        with app.lock:
            char = app.char(cid)
            cid = char["id"]
            st = app.state(cid)
            game = st.get("game")
            if not game:
                return {"entry": None, "job": None}
            g = self.get(game["id"])
            line = self._line(g, "quit", self._ctx(char, st, datetime.now(), game))
            self._finish(st)
            entry, job = self._record(cid, char, st, g, line, {}, "", "quit", "")
            app.save_state(cid)
            app.save_log(cid)
            return {"entry": entry, "job": job, "ended": "quit"}

    # ------------------------------------------------------------------ 野球拳
    def _move_yakyuken(self, cid, char, st, g, game, hand):
        if hand not in HANDS:
            raise ValueError("グー・チョキ・パーから選んでください")
        her = game["next"]
        game["round"] += 1
        game["last_her"] = her
        res = judge(hand, her)
        hands = (g.get("hands") or {})
        act_pos = hands.get(her, {}).get("pos", "")
        extra = {"her_hand": self._hand_name(g, her), "my_hand": self._hand_name(g, hand)}
        label = "（%d回戦）" % game["round"]
        n_stages = len(g.get("stages") or [])
        ended = None
        if res == 0:
            event, eff = "draw", "draw"
        elif res > 0:
            if game["stage"] + 1 >= n_stages:      # もう脱げない → 降参
                game["outfit"] = self.stage_outfit(g, char, st, game["stage"], giveup=True)
                event, eff, ended = "win", "win", "win"
                act_pos = ""
            else:
                game["stage"] += 1
                game["outfit"] = self.stage_outfit(g, char, st, game["stage"])
                event, eff = "round_win", "round_win"
        else:
            game["lives"] -= 1
            if game["lives"] <= 0:
                event, eff, ended = "lose", "lose", "lose"
            else:
                event, eff = "round_lose", "round_lose"
        extra["stage"] = (game.get("outfit") or {}).get("label", "")
        line = self._line(g, event, self._ctx(char, st, datetime.now(), game))
        entry, job = self._record(cid, char, st, g, line, extra, act_pos, eff, label)
        entry["game"] = {"me": hand, "her": her, "result": res}
        if ended:
            self._finish(st)
        else:
            self._decide_next(g, game)
        return {"entry": entry, "job": job, "ended": ended, "result": res, "her": her}

    # ------------------------------------------------------------------ あっち向いてホイ
    def _move_acchimuite(self, cid, char, st, g, game, hand, direction):
        dirs = g.get("dirs") or {}
        target = int(g.get("target", 3))
        game.setdefault("round", 0)
        ended, res, her = None, None, None
        if game.get("phase", "rps") == "rps":
            if hand not in HANDS:
                raise ValueError("グー・チョキ・パーから選んでください")
            her = game["next"]
            game["last_her"] = her
            res = judge(hand, her)
            extra = {"her_hand": self._hand_name(g, her), "my_hand": self._hand_name(g, hand)}
            act_pos = (g.get("hands") or {}).get(her, {}).get("pos", "")
            if res == 0:
                event = "draw"
                self._decide_next(g, game)
            elif res > 0:
                event, game["phase"] = "rps_me", "me_point"
            else:
                event, game["phase"] = "rps_her", "her_point"
                game["her_dir"] = random.choice(DIRS)
            eff = None
        else:
            if direction not in DIRS:
                raise ValueError("上下左右から選んでください")
            game["round"] += 1
            extra = {"dir": self._dir_name(g, direction)}
            if game["phase"] == "me_point":
                look = random.choice(DIRS)
                hit = look == direction
                act_pos = "%s, %s" % (dirs.get(look, {}).get("look", ""), "surprised" if hit else "smile")
                event, eff = ("point_me", "point_me") if hit else ("dodge_me", None)
                if hit:
                    game["me"] += 1
            else:
                pd = game.pop("her_dir", random.choice(DIRS))
                hit = pd == direction
                act_pos = dirs.get(pd, {}).get("point", "")
                extra["her_dir"] = self._dir_name(g, pd)
                event, eff = ("point_her", "point_her") if hit else ("dodge_her", None)
                if hit:
                    game["her"] += 1
            game["phase"] = "rps"
            if game["me"] >= target:
                event, eff, ended = "win", "win", "win"
            elif game["her"] >= target:
                event, eff, ended = "lose", "lose", "lose"
            else:
                self._decide_next(g, game)
        line = self._line(g, event, self._ctx(char, st, datetime.now(), game))
        label = "（%d-%d）" % (game.get("me", 0), game.get("her", 0))
        entry, job = self._record(cid, char, st, g, line, extra, act_pos, eff, label)
        entry["game"] = {"me": hand, "her": her, "result": res, "dir": direction}
        if ended:
            self._finish(st)
        return {"entry": entry, "job": job, "ended": ended, "result": res, "her": her,
                "phase": (st.get("game") or {}).get("phase")}
