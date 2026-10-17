"""ミニゲーム.

kind ごとの遊び方:
  yakyuken   野球拳 (脱衣)          acchimuite  あっち向いてホイ
  mahjong    二人打ち簡易麻雀 (脱衣)  connect4 / hex / reversi  盤面の二人対戦

ゲームの状態はキャラの state["game"] に持つ. 要所ごとにログ記録 (セリフ・効果・画像) を作る.
セリフ・効果・プロンプト・段階は data/minigames.json で編集できる.
"""
import random
import time
from datetime import datetime

from . import boardgames as BG
from . import cond
from . import mahjong as MJ
from . import yacht as YT

BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}
HANDS = ("rock", "scissors", "paper")
DIRS = ("up", "down", "left", "right")
KINDS = ("yakyuken", "acchimuite", "mahjong", "connect4", "hex", "reversi", "yacht")
STRIP_KINDS = ("yakyuken", "mahjong")
BOARD_KINDS = ("connect4", "hex", "reversi")


def judge(me, her):
    """1 = あなたの勝ち, -1 = 相手の勝ち, 0 = あいこ."""
    if me == her:
        return 0
    return 1 if BEATS[me] == her else -1


class Games:
    def __init__(self, app):
        self.app = app

    # ================================================================== 共通
    def get(self, gid):
        for g in self.app.minigames:
            if g.get("id") == gid:
                return g
        raise KeyError("ミニゲームが見つかりません: %s" % gid)

    def _hand_name(self, g, h):
        return (g.get("hands") or {}).get(h, {}).get("name", h)

    def _dir_name(self, g, d):
        return (g.get("dirs") or {}).get(d, {}).get("name", d)

    def _ctx(self, char, st, dt, game, **extra):
        ctx = self.app.context(char, st, dt)
        ctx.update({"game": game["id"], "game_stage": game.get("stage", 0), "game_round": game.get("round", 0),
                    "lives": game.get("lives", 0), "my_point": game.get("me", 0), "her_point": game.get("her", 0)})
        ctx.update(extra)
        return ctx

    def _line(self, g, event, ctx):
        lines = (g.get("lines") or {}).get(event) or []
        return self.app.pick_reaction({"reactions": lines}, ctx) if lines else {"text": ""}

    def _fmt(self, text, char, scene, dt, extra):
        text = self.app.format_text(text, char, scene, dt)
        for k, v in extra.items():
            text = text.replace("{%s}" % k, str(v))
        return text

    def _skill(self, g, st):
        """AI の強さと凡ミス率. 眠いと甘くなり, 不機嫌でも集中を欠く."""
        p = st["params"]
        skill = float(g.get("skill", 0.7))
        err = float(g.get("err", 0.05)) + max(0.0, p.get("sleepiness", 0) - 50) / 250.0
        if p.get("mood", 50) < 30:
            err += 0.1
        return skill, min(err, 0.8)

    def _record(self, cid, char, st, g, line, extra, act_pos, effects_key, label, image=True):
        """要所のログ記録を作り, 効果を適用し, 画像を出す."""
        now = time.time()
        dt = datetime.fromtimestamp(now)
        deltas = self.app.apply_effects(st, (g.get("effects") or {}).get(effects_key) or {}) if effects_key else {}
        scene = self.app.scene_at(char, st, dt)
        text = self._fmt(line.get("text", ""), char, scene, dt, extra)
        pseudo = {"id": "_game_" + g["id"], "name": "%s%s" % (g.get("name", ""), label),
                  "icon": g.get("icon", "🎲"), "pos": ", ".join(x for x in (g.get("pos", ""), act_pos) if x),
                  "neg": g.get("neg", "")}
        pos, neg, parts = self.app.build_prompt(char, st, dt, pseudo, line)
        st["last_interaction"] = now
        entry = self.app._new_entry(cid, now, pseudo, text, deltas, scene, dt, pos, neg, parts)
        job = None
        if image and self.app.settings.get("auto_generate"):
            job = self.app._present_image(cid, entry)
        return entry, job

    def _say(self, char, st, g, event, game, **extra):
        """記録を残さない一言 (吹き出し用)."""
        lines = (g.get("lines") or {}).get(event)
        if not lines:
            return None
        dt = datetime.now()
        line = self._line(g, event, self._ctx(char, st, dt, game, **extra))
        return self._fmt(line.get("text", ""), char, self.app.scene_at(char, st, dt), dt,
                         {k: v for k, v in extra.items() if isinstance(v, (str, int, float))}) or None

    def _save(self, cid):
        self.app.save_state(cid)
        self.app.save_log(cid)

    # ---------------------------------------------------------- 脱衣の段階
    def stage_outfit(self, g, char, st, stage, giveup=False):
        """段階に応じた服装 (段階 1..n を順に適用)."""
        base = self.app.scene_at(char, dict(st, game=None), datetime.now())   # 着せ替え込みの今の服
        pos, neg, remove = base["outfit"], base["outfit_neg"], []
        stages = g.get("stages") or [{}]
        steps = list(stages[1:stage + 1])
        if giveup and g.get("giveup"):
            steps.append(g["giveup"])
        label = stages[0].get("label", "")
        for s in steps:
            if s.get("mode") == "replace":
                pos, neg = s.get("pos", ""), s.get("neg", "")
            else:
                pos = ", ".join(x for x in (pos, s.get("pos", "")) if x)
                neg = ", ".join(x for x in (neg, s.get("neg", "")) if x)
            remove += [t.strip() for t in (s.get("remove") or "").split(",") if t.strip()]
            label = s.get("label", "")
        return {"pos": pos, "neg": neg, "remove": remove, "label": label}

    def _strip(self, g, char, st, game, steps):
        """キャラが steps 段階脱ぐ. 脱ぎきったら降参して True."""
        n = len(g.get("stages") or [])
        if game["stage"] + steps >= n:
            game["stage"] = n - 1
            game["outfit"] = self.stage_outfit(g, char, st, game["stage"], giveup=True)
            return True
        game["stage"] += steps
        game["outfit"] = self.stage_outfit(g, char, st, game["stage"])
        return False

    # ================================================================== API
    def view(self, char, st, ctx):
        games = []
        for g in self.app.minigames:
            desc = (g.get("desc") or "").replace("{name}", char.get("name", "")).replace(
                "{target}", str(g.get("target", 3)))
            games.append({"id": g["id"], "name": g.get("name", g["id"]), "icon": g.get("icon", "🎲"), "desc": desc,
                          "kind": g.get("kind"), "ok": cond.check(g.get("require", ""), ctx),
                          "require": g.get("require", "")})
        cur = st.get("game")
        out = None
        if cur:
            try:
                g = self.get(cur["id"])
            except KeyError:
                st["game"] = None
                return {"list": games, "current": None}
            kind = g.get("kind")
            out = {"id": cur["id"], "name": g.get("name"), "kind": kind, "round": cur.get("round", 0),
                   "phase": cur.get("phase", "rps")}
            if kind in ("yakyuken", "acchimuite"):
                out["hands"] = {h: {"name": self._hand_name(g, h), "icon": (g.get("hands") or {}).get(h, {}).get("icon", "")}
                                for h in HANDS}
                out["dirs"] = {d: {"name": self._dir_name(g, d), "icon": (g.get("dirs") or {}).get(d, {}).get("icon", "")}
                               for d in DIRS}
            if kind in STRIP_KINDS:
                out.update(stage=cur.get("stage", 0), stages=len(g.get("stages") or []),
                           stage_label=(cur.get("outfit") or {}).get("label", ""),
                           lives=cur.get("lives", 0), lives_max=int(g.get("lives", 3)))
            if kind == "acchimuite":
                out.update(me=cur.get("me", 0), her=cur.get("her", 0), target=int(g.get("target", 3)))
            if kind == "mahjong":
                out["mj"] = self._mj_view(cur)
            if kind in BOARD_KINDS:
                out["board"] = self._board_view(g, cur)
            if kind == "yacht":
                out["yacht"] = self._yacht_view(cur)
        return {"list": games, "current": out}

    def start(self, gid, cid=None):
        app = self.app
        with app.lock:
            char = app.char(cid)
            cid = char["id"]
            app.tick(cid)
            st = app.state(cid)
            g = self.get(gid)
            kind = g.get("kind")
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
                self._save(cid)
                return {"entry": entry, "job": job, "refused": True}
            if kind in STRIP_KINDS:
                game["outfit"] = self.stage_outfit(g, char, st, 0)
            if kind in ("yakyuken", "acchimuite"):
                self._decide_next(g, game)
            st["game"] = game
            line = self._line(g, "start", gctx)
            entry, job = self._record(cid, char, st, g, line, {}, "", "start", "")
            hint = None
            if kind == "mahjong":
                game["phase"] = "mj"
                hint = self._mj_new_hand(cid, char, st, g, game, first=True)
            elif kind in BOARD_KINDS:
                hint = self._board_start(char, st, g, game)
            elif kind == "yacht":
                hint = self._yacht_start(char, st, g, game)
            else:
                hint = self._hint_text(char, st, g, game)
            self._save(cid)
            return {"entry": entry, "job": job, "hint": hint}

    def move(self, cid=None, payload=None):
        payload = payload or {}
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
            kind = g.get("kind")
            dt = datetime.now()
            over = game.get("over")
            if not over and not cond.check(g.get("require", ""), app.context(char, st, dt)):
                line = self._line(g, "interrupted", self._ctx(char, st, dt, game))
                st["game"] = None
                entry, job = self._record(cid, char, st, g, line, {}, "", "quit", "")
                self._save(cid)
                return {"entry": entry, "job": job, "ended": "interrupted"}
            if kind == "yakyuken":
                r = self._move_yakyuken(cid, char, st, g, game, payload.get("hand"))
                if st.get("game"):
                    r["hint"] = self._hint_text(char, st, g, st["game"])
            elif kind == "acchimuite":
                r = self._move_acchimuite(cid, char, st, g, game, payload.get("hand"), payload.get("dir"))
                if st.get("game"):
                    r["hint"] = self._hint_text(char, st, g, st["game"])
            elif kind == "mahjong":
                r = self._move_mahjong(cid, char, st, g, game, payload)
            elif kind in BOARD_KINDS:
                r = self._move_board(cid, char, st, g, game, payload)
            elif kind == "yacht":
                r = self._move_yacht(cid, char, st, g, game, payload)
            else:
                raise ValueError("未対応のゲームです: %s" % kind)
            self._save(cid)
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
            st["game"] = None
            if game.get("over"):          # 決着後の「終わる」は記録を残さない
                self._save(cid)
                return {"entry": None, "job": None, "ended": "closed"}
            g = self.get(game["id"])
            line = self._line(g, "quit", self._ctx(char, st, datetime.now(), game))
            entry, job = self._record(cid, char, st, g, line, {}, "", "quit", "")
            self._save(cid)
            return {"entry": entry, "job": job, "ended": "quit"}

    # ================================================================== じゃんけん系
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

    def _hint_text(self, char, st, g, game):
        if not game.get("hint"):
            return None
        return self._say(char, st, g, "hint", game, hint_hand=self._hand_name(g, game["hint"]))

    def _move_yakyuken(self, cid, char, st, g, game, hand):
        if hand not in HANDS:
            raise ValueError("グー・チョキ・パーから選んでください")
        her = game["next"]
        game["round"] += 1
        game["last_her"] = her
        res = judge(hand, her)
        act_pos = (g.get("hands") or {}).get(her, {}).get("pos", "")
        extra = {"her_hand": self._hand_name(g, her), "my_hand": self._hand_name(g, hand)}
        ended = None
        if res == 0:
            event = eff = "draw"
        elif res > 0:
            if self._strip(g, char, st, game, 1):
                event = eff = ended = "win"
                act_pos = ""
            else:
                event = eff = "round_win"
        else:
            game["lives"] -= 1
            if game["lives"] <= 0:
                event = eff = ended = "lose"
            else:
                event = eff = "round_lose"
        extra["stage"] = (game.get("outfit") or {}).get("label", "")
        line = self._line(g, event, self._ctx(char, st, datetime.now(), game))
        entry, job = self._record(cid, char, st, g, line, extra, act_pos, eff, "（%d回戦）" % game["round"])
        entry["game"] = {"me": hand, "her": her, "result": res}
        if ended:
            st["game"] = None
        else:
            self._decide_next(g, game)
        return {"entry": entry, "job": job, "ended": ended, "result": res, "her": her}

    def _move_acchimuite(self, cid, char, st, g, game, hand, direction):
        dirs = g.get("dirs") or {}
        target = int(g.get("target", 3))
        ended, res, her, eff = None, None, None, None
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
                event = eff = ended = "win"
            elif game["her"] >= target:
                event = eff = ended = "lose"
            else:
                self._decide_next(g, game)
        line = self._line(g, event, self._ctx(char, st, datetime.now(), game))
        label = "（%d-%d）" % (game.get("me", 0), game.get("her", 0))
        entry, job = self._record(cid, char, st, g, line, extra, act_pos, eff, label)
        entry["game"] = {"me": hand, "her": her, "result": res, "dir": direction}
        if ended:
            st["game"] = None
        return {"entry": entry, "job": job, "ended": ended, "result": res, "her": her,
                "phase": (st.get("game") or {}).get("phase")}

    # ================================================================== 麻雀
    # 状態 game["mj"]: wall / dora / ura / hands{p,a} / drawn{p,a} / river{p,a} / riichi{p,a}
    #                  dealer / hand_no / phase (p_turn | p_ron | hand_end) / last / result
    def _mj_view(self, game):
        m = game.get("mj") or {}
        hand = list(m.get("hands", {}).get("p", []))
        drawn = m.get("drawn", {}).get("p")
        if drawn is not None and drawn in hand:
            hand.remove(drawn)
        hand.sort()
        res = m.get("result")
        out = {"phase": m.get("phase"), "hand": hand, "drawn": drawn, "hand_no": m.get("hand_no", 1),
               "dealer": m.get("dealer"), "dora": m.get("dora", []), "wall": len(m.get("wall", [])),
               "river": m.get("river", {}), "riichi": m.get("riichi", {}),
               "her_count": len(m.get("hands", {}).get("a", [])), "last": m.get("last"),
               "can_tsumo": bool(m.get("can_tsumo")), "riichi_tiles": m.get("riichi_tiles", []),
               "can_ron": m.get("phase") == "p_ron", "result": res, "over": game.get("over")}
        if res:
            out["her_hand"] = sorted(m.get("hands", {}).get("a", []))
        return out

    def _mj_visible(self, m, who):
        vis = MJ.to_counts(m["hands"][who])
        for t in m["river"]["p"] + m["river"]["a"] + m["dora"]:
            vis[t] += 1
        return vis

    def _mj_furiten(self, m, who):
        hand13 = list(m["hands"][who])
        return bool(set(MJ.waits(hand13)) & set(m["river"][who]))

    def _mj_eval(self, m, who, win, tsumo):
        seat = 27 if m["dealer"] == who else 28   # 親 = 東, 子 = 南
        tiles = list(m["hands"][who]) + ([] if tsumo else [win])
        if not MJ.is_agari(MJ.to_counts(tiles)):
            return None
        return MJ.evaluate(sorted(tiles), win, tsumo, m["riichi"][who], seat, 27, m["dora"], m["ura"])

    def _mj_new_hand(self, cid, char, st, g, game, first=False):
        m = game.get("mj") or {"hand_no": 0, "dealer": "a"}
        wall = [t for t in range(34) for _ in range(4)]
        random.shuffle(wall)
        dead, live = wall[:14], wall[14:]
        live = live[:26 + int(g.get("live_wall", 70))]
        m.update({"hand_no": m.get("hand_no", 0) + 1, "dealer": "p" if m.get("dealer") == "a" else "a",
                  "wall": live[26:], "dora": [dead[4]], "ura": [dead[5]],
                  "hands": {"p": sorted(live[:13]), "a": sorted(live[13:26])},
                  "drawn": {"p": None, "a": None}, "river": {"p": [], "a": []},
                  "riichi": {"p": False, "a": False}, "phase": "p_turn", "last": None, "result": None,
                  "can_tsumo": False, "riichi_tiles": []})
        game["mj"] = m
        if m["dealer"] == "a":
            return self._mj_draw_and_ai(cid, char, st, g, game)
        return self._mj_player_draw(cid, char, st, g, game)

    def _mj_ryuukyoku(self, cid, char, st, g, game):
        m = game["mj"]
        m["phase"] = "hand_end"
        m["result"] = {"winner": None, "how": "流局", "yaku": [], "han": 0}
        line = self._line(g, "ryuukyoku", self._ctx(char, st, datetime.now(), game))
        entry, job = self._record(cid, char, st, g, line, {}, "", "ryuukyoku", "（第%d局 流局）" % m["hand_no"])
        game["_entry"], game["_job"] = entry, job
        return None

    def _mj_end(self, cid, char, st, g, game, who, how, res, win):
        m = game["mj"]
        m["phase"] = "hand_end"
        steps = MJ.stage_steps(res, g.get("han_steps") or [[1, 1], [5, 2], [8, 3]])
        yaku_text = "・".join("%s" % n for n, _ in res["yaku"])
        m["result"] = {"winner": who, "how": how, "yaku": res["yaku"], "han": res["han"],
                       "yakuman": res["yakuman"], "win_tile": win, "steps": steps}
        extra = {"yaku": yaku_text, "han": "役満" if res["yakuman"] else "%d翻" % res["han"],
                 "stage": ""}
        ended = None
        if who == "p":
            gave_up = self._strip(g, char, st, game, 99 if res["yakuman"] else steps)
            event = eff = "hand_win"
            if gave_up:
                event = eff = ended = "win"
        else:
            game["lives"] -= (99 if res["yakuman"] else steps)
            event = eff = "hand_lose"
            if game["lives"] <= 0:
                game["lives"] = 0
                event = eff = ended = "lose"
        extra["stage"] = (game.get("outfit") or {}).get("label", "")
        if ended:
            game["over"] = ended
        ctx = self._ctx(char, st, datetime.now(), game, han=res["han"], yakuman=res["yakuman"],
                        tsumo=(how == "ツモ"))
        line = self._line(g, event, ctx)
        label = "（第%d局 %sの%s）" % (m["hand_no"], "あなた" if who == "p" else char.get("name", ""), how)
        entry, job = self._record(cid, char, st, g, line, extra, "", eff, label)
        game["_entry"], game["_job"] = entry, job
        return None

    def _mj_player_draw(self, cid, char, st, g, game):
        m = game["mj"]
        if not m["wall"]:
            return self._mj_ryuukyoku(cid, char, st, g, game)
        t = m["wall"].pop(0)
        m["hands"]["p"].append(t)
        m["drawn"]["p"] = t
        res = self._mj_eval(m, "p", t, True) if MJ.is_agari(MJ.to_counts(m["hands"]["p"])) else None
        m["can_tsumo"] = bool(res)
        m["riichi_tiles"] = [] if m["riichi"]["p"] else MJ.riichi_discards(m["hands"]["p"])
        m["phase"] = "p_turn"
        if m["riichi"]["p"] and not res:     # リーチ後は和了れない牌を自動でツモ切り
            return self._mj_player_discard(cid, char, st, g, game, t, auto=True)
        return None

    def _mj_player_discard(self, cid, char, st, g, game, t, riichi=False, auto=False):
        m = game["mj"]
        if t not in m["hands"]["p"]:
            raise ValueError("その牌は手牌にありません")
        if m["riichi"]["p"] and t != m["drawn"]["p"]:
            raise ValueError("リーチ後はツモ切りしかできません")
        hint = None
        if riichi:
            if t not in m["riichi_tiles"]:
                raise ValueError("その牌を切ってもテンパイになりません")
            m["riichi"]["p"] = True
            line = self._line(g, "my_riichi", self._ctx(char, st, datetime.now(), game))
            entry, job = self._record(cid, char, st, g, line, {}, "", "my_riichi", "（リーチ）")
            game["_entry"], game["_job"] = entry, job
        m["hands"]["p"].remove(t)
        m["hands"]["p"].sort()
        m["drawn"]["p"] = None
        m["river"]["p"].append(t)
        m["last"] = {"who": "p", "t": t}
        m["can_tsumo"], m["riichi_tiles"] = False, []
        # キャラのロン
        res = self._mj_eval(m, "a", t, False)
        if res and not self._mj_furiten(m, "a"):
            m["hands"]["a"].append(t)
            return self._mj_end(cid, char, st, g, game, "a", "ロン", res, t)
        return self._mj_draw_and_ai(cid, char, st, g, game) or hint

    def _mj_draw_and_ai(self, cid, char, st, g, game):
        m = game["mj"]
        if not m["wall"]:
            return self._mj_ryuukyoku(cid, char, st, g, game)
        t = m["wall"].pop(0)
        m["hands"]["a"].append(t)
        m["drawn"]["a"] = t
        res = self._mj_eval(m, "a", t, True) if MJ.is_agari(MJ.to_counts(m["hands"]["a"])) else None
        if res:
            return self._mj_end(cid, char, st, g, game, "a", "ツモ", res, t)
        skill, err = self._skill(g, st)
        if m["riichi"]["a"]:
            d = t
        else:
            d = MJ.choose_discard(m["hands"]["a"], self._mj_visible(m, "a"), m["riichi"]["p"],
                                  m["river"]["p"], err)
        hint = None
        m["hands"]["a"].remove(d)
        if not m["riichi"]["a"]:
            tenpai = MJ.shanten(MJ.to_counts(m["hands"]["a"])) == 0
            if tenpai and random.random() < float(g.get("riichi_rate", 0.75)) + (0.15 if st["params"].get("mood", 50) >= 70 else 0):
                m["riichi"]["a"] = True
                line = self._line(g, "her_riichi", self._ctx(char, st, datetime.now(), game))
                entry, job = self._record(cid, char, st, g, line, {}, "", "her_riichi", "（リーチ）")
                game["_entry"], game["_job"] = entry, job
            elif random.random() < float(g.get("hint_rate", 0.15)):
                honest = random.random() < float(g.get("hint_honesty", 0.6))
                hint = self._say(char, st, g, "hint", game, tenpai=(tenpai if honest else not tenpai))
        m["hands"]["a"].sort()
        m["drawn"]["a"] = None
        m["river"]["a"].append(d)
        m["last"] = {"who": "a", "t": d}
        # あなたのロン判定
        res = self._mj_eval(m, "p", d, False)
        if res and not self._mj_furiten(m, "p"):
            m["phase"] = "p_ron"
            m["ron_res"] = res
            return hint
        return self._mj_player_draw(cid, char, st, g, game) or hint

    def _move_mahjong(self, cid, char, st, g, game, payload):
        m = game["mj"]
        act = payload.get("act")
        game.pop("_entry", None)
        game.pop("_job", None)
        hint = None
        if act == "next":
            if m["phase"] != "hand_end":
                raise ValueError("まだ局の途中です")
            if game.get("over"):
                st["game"] = None
                return {"entry": None, "job": None, "ended": "closed"}
            hint = self._mj_new_hand(cid, char, st, g, game)
        elif act == "tsumo":
            if m["phase"] != "p_turn" or not m.get("can_tsumo"):
                raise ValueError("ツモ和了できません")
            t = m["drawn"]["p"]
            self._mj_end(cid, char, st, g, game, "p", "ツモ", self._mj_eval(m, "p", t, True), t)
        elif act == "ron":
            if m["phase"] != "p_ron":
                raise ValueError("ロンできません")
            t = m["last"]["t"]
            res = m.pop("ron_res")
            m["hands"]["p"].append(t)
            self._mj_end(cid, char, st, g, game, "p", "ロン", res, t)
        elif act == "skip":
            if m["phase"] != "p_ron":
                raise ValueError("見送る牌がありません")
            m.pop("ron_res", None)
            hint = self._mj_player_draw(cid, char, st, g, game)
        elif act in ("discard", "riichi"):
            if m["phase"] != "p_turn":
                raise ValueError("今は打牌できません")
            t = int(payload.get("tile"))
            hint = self._mj_player_discard(cid, char, st, g, game, t, riichi=(act == "riichi"))
        else:
            raise ValueError("不明な操作です: %s" % act)
        ended = game.get("over") if (st.get("game") is game and m.get("phase") == "hand_end") else None
        return {"entry": game.pop("_entry", None), "job": game.pop("_job", None), "hint": hint,
                "ended": ended}

    # ================================================================== 盤面ゲーム
    def _board_start(self, char, st, g, game):
        kind = g.get("kind")
        if kind == "connect4":
            game["board"] = BG.c4_new()
        elif kind == "hex":
            game["n"] = int(g.get("size", 7))
            game["board"] = BG.hex_new(game["n"])
        else:
            game["board"] = BG.rv_new()
        game["phase"] = "board"
        game["last"] = []
        game["moves"] = 0
        first = g.get("first", "me")
        if first == "her" or (first == "random" and random.random() < 0.5):
            self._board_ai(g, st, game)
        return None

    def _board_view(self, g, game):
        kind = g.get("kind")
        b = game.get("board") or []
        out = {"cells": b, "last": game.get("last", []), "line": game.get("line"), "over": game.get("over")}
        if kind == "connect4":
            out.update(w=BG.C4_W, h=BG.C4_H)
        elif kind == "hex":
            out.update(n=game.get("n", 7))
        else:
            out.update(legal=[] if game.get("over") else BG.rv_moves(b, BG.ME),
                       me=b.count(BG.ME), her=b.count(BG.HER))
        return out

    def _board_ai(self, g, st, game):
        kind, b = g.get("kind"), game["board"]
        skill, err = self._skill(g, st)
        if kind == "connect4":
            i = BG.c4_play(b, BG.c4_ai(b, skill, err), BG.HER)
            # 直前のあなたの一手も残し, 画面で「あなた → キャラ」の順に落とす
            game["last"] = [x for x in game.get("last", []) if b[x] == BG.ME][-1:] + [i]
        elif kind == "hex":
            i = BG.hex_ai(b, game["n"], skill, err)
            b[i] = BG.HER
            game["last"] = [i]
        else:
            i = BG.rv_ai(b, skill, err)
            if i is None:
                return False
            fl = BG.rv_play(b, i, BG.HER)
            game["last"] = [i] + fl
        game["moves"] += 1
        return True

    def _board_result(self, g, game):
        """None = 続行, 'win' / 'lose' / 'draw'."""
        kind, b = g.get("kind"), game["board"]
        if kind == "connect4":
            w, line = BG.c4_winner(b)
            game["line"] = line
            return None if w is None else {0: "draw", BG.ME: "win", BG.HER: "lose"}[w]
        if kind == "hex":
            w = BG.hex_winner(b, game["n"])
            return None if w is None else ("win" if w == BG.ME else "lose")
        if BG.rv_moves(b, BG.ME) or BG.rv_moves(b, BG.HER):
            return None
        d = b.count(BG.ME) - b.count(BG.HER)
        return "win" if d > 0 else "lose" if d < 0 else "draw"

    def _board_advantage(self, g, game):
        kind, b = g.get("kind"), game["board"]
        if kind == "connect4":
            return BG.c4_advantage(b)
        if kind == "hex":
            return BG.hex_advantage(b, game["n"]) * 10
        return BG.rv_advantage(b)

    def _move_board(self, cid, char, st, g, game, payload):
        kind, b = g.get("kind"), game["board"]
        if game.get("over"):
            raise ValueError("この対局は終わっています")
        if kind == "connect4":
            col = int(payload.get("col", -1))
            if col not in BG.c4_moves(b):
                raise ValueError("その列には置けません")
            mine = [BG.c4_play(b, col, BG.ME)]
        elif kind == "hex":
            i = int(payload.get("cell", -1))
            if not (0 <= i < len(b)) or b[i]:
                raise ValueError("そこには置けません")
            b[i] = BG.ME
            mine = [i]
        else:
            i = int(payload.get("cell", -1))
            if i not in BG.rv_moves(b, BG.ME):
                raise ValueError("そこには置けません")
            mine = [i] + BG.rv_play(b, i, BG.ME)
        game["moves"] += 1
        game["last"] = mine
        result = self._board_result(g, game)
        passed = False
        if result is None:
            self._board_ai(g, st, game)
            result = self._board_result(g, game)
            # リバーシ: あなたが打てないあいだはキャラが続けて打つ
            while result is None and kind == "reversi" and not BG.rv_moves(b, BG.ME):
                passed = True
                if not self._board_ai(g, st, game):
                    break
                result = self._board_result(g, game)
        hint = None
        if result:
            game["over"] = result
            ctx = self._ctx(char, st, datetime.now(), game)
            line = self._line(g, result, ctx)
            extra = {}
            if kind == "reversi":
                extra = {"me": b.count(BG.ME), "her": b.count(BG.HER)}
            entry, job = self._record(cid, char, st, g, line, extra, "", result,
                                      "（%s）" % {"win": "あなたの勝ち", "lose": "あなたの負け", "draw": "引き分け"}[result])
            return {"entry": entry, "job": job, "ended": result}
        every = int(g.get("comment_every", 4))
        if passed:
            hint = self._say(char, st, g, "pass", game)
        elif every and game["moves"] % every < 2 and random.random() < 0.7:
            hint = self._say(char, st, g, "mid", game, advantage=self._board_advantage(g, game))
        return {"entry": None, "job": None, "hint": hint, "ended": None}

    # ================================================================== ヨット
    # 状態 game["yt"]: dice / hold / rolls_left / round / sheet{p,a} / her (直前のキャラの番の経過)
    def _yacht_start(self, char, st, g, game):
        game["phase"] = "yacht"
        game["yt"] = {"dice": None, "hold": [False] * 5, "rolls_left": 3, "round": 1,
                      "sheet": {"p": {}, "a": {}}, "her": None}
        first = g.get("first", "me")
        if first == "her" or (first == "random" and random.random() < 0.5):
            return self._yacht_her_turn(char, st, g, game)
        return None

    def _yacht_view(self, game):
        y = game.get("yt") or {}
        sheet = y.get("sheet", {"p": {}, "a": {}})
        preview = {}
        if y.get("dice"):
            preview = {c: YT.score(c, y["dice"]) for c in YT.CATS if c not in sheet["p"]}
        return {"dice": y.get("dice"), "hold": y.get("hold"), "rolls_left": y.get("rolls_left", 0),
                "round": y.get("round", 1), "sheet": sheet, "preview": preview,
                "totals": {k: YT.totals(v) for k, v in sheet.items()}, "her": y.get("her"),
                "cats": YT.CATS, "names": YT.NAMES, "over": game.get("over"),
                "bonus_line": YT.BONUS_LINE, "bonus": YT.BONUS}

    def _yacht_her_turn(self, char, st, g, game):
        y = game["yt"]
        skill, err = self._skill(g, st)
        steps, dice, cat = YT.ai_turn(y["sheet"]["a"], skill, err)
        sc = YT.score(cat, dice)
        y["sheet"]["a"][cat] = sc
        y["her"] = {"steps": steps, "cat": cat, "name": YT.NAMES[cat], "score": sc}
        if cat == "yacht" and sc:
            return self._say(char, st, g, "her_yacht", game)
        return None

    def _move_yacht(self, cid, char, st, g, game, payload):
        y = game["yt"]
        if game.get("over"):
            raise ValueError("この対局は終わっています")
        act = payload.get("act")
        hint = None
        if act == "roll":
            if y["rolls_left"] <= 0:
                raise ValueError("もう振れません。役を選んでください")
            hold = [bool(x) for x in (payload.get("hold") or [False] * 5)][:5]
            if not y["dice"]:
                hold = [False] * 5
            y["dice"] = YT.roll(y["dice"], hold)
            y["hold"] = hold
            y["rolls_left"] -= 1
            if YT.score("yacht", y["dice"]):
                hint = self._say(char, st, g, "my_yacht", game)
            return {"entry": None, "job": None, "hint": hint, "ended": None}
        if act != "score":
            raise ValueError("不明な操作です: %s" % act)
        cat = payload.get("cat")
        if not y["dice"]:
            raise ValueError("まずサイコロを振ってください")
        if cat not in YT.CATS or cat in y["sheet"]["p"]:
            raise ValueError("その役には入れられません")
        y["sheet"]["p"][cat] = YT.score(cat, y["dice"])
        y["dice"], y["hold"], y["rolls_left"] = None, [False] * 5, 3
        if len(y["sheet"]["a"]) < len(YT.CATS):
            hint = self._yacht_her_turn(char, st, g, game)
        if len(y["sheet"]["p"]) >= len(YT.CATS) and len(y["sheet"]["a"]) >= len(YT.CATS):
            me, her = YT.totals(y["sheet"]["p"])["total"], YT.totals(y["sheet"]["a"])["total"]
            result = "win" if me > her else "lose" if me < her else "draw"
            game["over"] = result
            line = self._line(g, result, self._ctx(char, st, datetime.now(), game))
            entry, job = self._record(cid, char, st, g, line, {"me": me, "her": her}, "", result,
                                      "（%d対%d）" % (me, her))
            return {"entry": entry, "job": job, "ended": result, "hint": hint}
        y["round"] = len(y["sheet"]["p"]) + 1
        if not hint and y["round"] % int(g.get("comment_every", 3)) == 0:
            diff = YT.totals(y["sheet"]["p"])["total"] - YT.totals(y["sheet"]["a"])["total"]
            hint = self._say(char, st, g, "mid", game, advantage=diff)
        return {"entry": None, "job": None, "hint": hint, "ended": None}
