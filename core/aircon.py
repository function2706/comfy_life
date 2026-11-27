"""同居のエアコン争い (S58. A42 段 2 の 2). 冷暖房の使い方は家に 1 つ (core/home.py の ac_mode / set_ac).

- 好み: その人の好みの室温 (season.pref_room. 暑がりは低め・寒がりは高め) から 1℃ を超えてずれると, 暑い / 寒い (season.ac_fuss).
- 同居相手とあなたが家で起きているとき, 1 時間に一度だけ見て, 合わない度合いしだいで (一日に一度まで):
  言ってくる (性格の approach) / 自分で変える (管理傾向 moneytalk.manage) / 黙って我慢する (言わないまま機嫌が少し下がる).
  変えても過ごしやすくならない (春・秋で冷暖房が動かない) ときは何もしない.
- 言ってきたら: 合わせる (相手の使い方に. 喜ぶ) / 電気代を理由に断る (相手の使い方の方が高いときだけ. 納得するかは会話スキル) /
  このままがいいと言い返す (渋々か, 言い争いに. core/quarrel.py).
- あなたが「家の様子」で使い方を変えたとき, 同居相手がそばにいれば気づく: 過ごしにくくなった (相手が変えたのを戻したなら強く) /
  過ごしやすくなった (ありがとう). 二重に開いた画面で同じ使い方を押しても, 変わらなければ何も起きない.
あなたの暑い・寒いの値は作らない (あなたが払うのは電気代だけ). 遡及なし (性格の暑がり / 寒がりから, これから起きる).
"""
import random
import time
from datetime import datetime

from . import season as season_mod

CHECK_SEC = 3600            # 見る間隔
STALE_SEC = 6 * 3600        # 言ってきたまま答えずにいたら, うやむやに
NOTE_SEC = 1800             # あなたが変えたときの反応の間隔 (押し直しで何度も言わない)
CHOICES = {"match": "合わせる", "bill": "電気代が気になると断る", "push": "このままがいいと言い返す"}
LINES = {
    "ac.ask_hot": "……ちょっと暑くないですか？ {ac}もいいですか？",
    "ac.ask_cold": "……ちょっと寒くないですか？ {ac}もいいですか？",
    "ac.self_hot": "暑かったので、{ac}おきました",
    "ac.self_cold": "寒かったので、{ac}おきました",
    "ac.match": "ありがとうございます。……これで落ち着きます",
    "ac.bill_ok": "……電気代、そうですよね。もうちょっと我慢してみます",
    "ac.bill_meh": "……それはそうですけど。{feel}ものは{feel}んですよ",
    "ac.push_unhappy": "……わかりました。我慢します",
    "ac.push_fight": "{fp}が{feel}って言ってるのに、どうしてそうなるんですか",
    "ac.undo": "あれ、戻しました？ {fp}、さっき変えたんですけど……",
    "ac.notice_hot": "……なんだか暑くなってきましたね",
    "ac.notice_cold": "……なんだか寒くなってきましたね",
    "ac.thanks": "あ、ちょうどよくなりました。ありがとうございます",
}
SCENE_LABEL = {"ask_hot": "部屋が暑くて, 冷暖房を変えていいか聞く ({ac} に「冷房をもう少し強くして」など)",
               "ask_cold": "部屋が寒くて, 冷暖房を変えていいか聞く ({ac} に「暖房をつけて」など)",
               "self_hot": "部屋が暑くて, 自分で冷暖房を変えておいた ({ac})", "self_cold": "部屋が寒くて, 自分で冷暖房を変えておいた ({ac})",
               "match": "冷暖房を合わせてもらって, ほっとする", "bill_ok": "電気代を理由に断られて, 納得する",
               "bill_meh": "電気代を理由に断られたが, 微妙 ({feel} に 暑い / 寒い)", "push_unhappy": "このままがいいと言い返されて, 渋々我慢する",
               "push_fight": "このままがいいと言い返されて, 言い争いに ({feel} に 暑い / 寒い)",
               "undo": "自分で変えた冷暖房を, あなたに戻された", "notice_hot": "あなたが冷暖房を変えて, 部屋が暑くなった",
               "notice_cold": "あなたが冷暖房を変えて, 部屋が寒くなった", "thanks": "あなたが冷暖房を変えて, 過ごしやすくなった"}


def phrase(t, cur, want):
    """「冷房をもう少し強くして」など (cur から want へ変える言い方)."""
    kind = "冷房" if season_mod.warm_half(t) else "暖房"
    o = season_mod.AC_ORDER
    if o.index(want) > o.index(cur):
        return kind + ("をつけて" if cur == "off" else "をもう少し強くして")
    return kind + ("を切って" if want == "off" else "を少し弱くして")


class Aircon:
    def __init__(self, app):
        self.app = app

    def line(self, char, key, extra=None):
        app = self.app
        t = app.persona_text(char, "ac." + key) or LINES["ac." + key]
        fp, _, call = app.pronouns(char)
        for k, v in dict(extra or {}, fp=fp, call=call, name=char.get("name", "")).items():
            t = t.replace("{%s}" % k, str(v))
        return t

    def _entry(self, char, st, t, key, text, deltas):
        app = self.app
        dt = datetime.fromtimestamp(t)
        scene = app.scene_at(char, st, dt)
        act = {"id": "_aircon", "name": "冷暖房", "icon": "❄", "pos": "", "neg": ""}
        pos, neg, parts = app.build_prompt(char, st, dt, act)
        e = app._new_entry(char["id"], t, act, text, deltas, scene, dt, pos, neg, parts)
        e["aircon"] = key
        app.save_log(char["id"])
        return e

    def _apply(self, char, st, eff, now, tag):
        app = self.app
        if any(v > 0 for v in eff.values()):
            eff, _ = app.bonds.realize(char, st, eff, "_aircon_" + tag, now)
        return app.apply_effects(st, app.trait_effects(char, eff))

    def awake_home(self, cid, now):
        """同居相手とあなたが家にいて, どちらも起きている."""
        app = self.app
        if app.bonds.living() != cid or app.bonds.mode(cid, now) != "home":
            return False
        if app.presence.at(now) not in ("here", "idle", "busy"):
            return False
        return not app.scene_at(app.chars[cid], app.state(cid), datetime.fromtimestamp(now))["asleep"]

    def want(self, char, t):
        """(合わない度合い, 変えたい使い方). 変えても過ごしやすくならなければ使い方は None."""
        app = self.app
        tc = season_mod.temp(datetime.fromtimestamp(t))
        cur = app.home.ac_mode()
        f = season_mod.ac_fuss(app, char, tc, cur)
        w = season_mod.ac_best(app, char, tc)
        if w == cur or abs(season_mod.ac_fuss(app, char, tc, w)) > abs(f) - 0.2:
            return f, None
        return f, w

    # ------------------------------------------------------------------ 毎時
    def tick(self, char, st, now):
        app = self.app
        cid = char["id"]
        at = st.get("ac_talk")
        if at and now - at["t"] > STALE_SEC:          # 答えないまま: うやむや (言わないまま少しむっとする)
            st.pop("ac_talk", None)
            self._apply(char, st, {"mood": -1}, now, "stale")
        if at or now - float(st.get("ac_check", 0)) < CHECK_SEC or not self.awake_home(cid, now):
            return
        st["ac_check"] = now
        day = datetime.fromtimestamp(now).date().isoformat()
        if st.get("ac_day") == day:
            return
        f, w = self.want(char, now)
        if not w or abs(f) < 0.3:
            return
        p = min(0.5, 0.25 * abs(f))
        app.trace.add("aircon", "部屋が合わない", cid, now, fuss=f, want=w, mode=app.home.ac_mode(), p=round(p, 2))
        if random.random() >= p:
            return
        st["ac_day"] = day
        hot = f > 0
        cur = app.home.ac_mode()
        tc = season_mod.temp(datetime.fromtimestamp(now))
        ws = {"say": 1.0 * float(app.traits(char).get("approach", 1)), "self": 1.2 * app.moneytalk.manage(char, st), "endure": 0.8}
        how = random.choices(list(ws), weights=list(ws.values()))[0]
        app.trace.add("aircon", "出方", cid, now, how=how, w={k: round(v, 2) for k, v in ws.items()})
        ac = phrase(tc, cur, w)
        if how == "say":
            st["ac_talk"] = {"t": now, "want": w, "from": cur, "hot": hot}
            self._entry(char, st, now, "ask_" + ("hot" if hot else "cold"), self.line(char, "ask_" + ("hot" if hot else "cold"), {"ac": ac}), {})
        elif how == "self":
            app.home.set_mode(w)
            st["ac_self"] = {"t": now, "mode": w, "from": cur}
            self._entry(char, st, now, "self_" + ("hot" if hot else "cold"), self.line(char, "self_" + ("hot" if hot else "cold"), {"ac": ac}), {})
        else:
            d = self._apply(char, st, {"mood": -1}, now, "endure")
            app.life.add_reason(st, "player", "bad", "部屋が%sのを我慢した" % ("暑い" if hot else "寒い"), now, told=False,
                                delta=d.get("mood", 0), action="_aircon")
        app.save_state(cid)

    # ------------------------------------------------------------------ 言ってきたことへの出方
    def pending(self):
        app = self.app
        cid = app.bonds.living()
        if not cid:
            return None
        at = app.state(cid).get("ac_talk")
        if not at or not app.bonds.together(cid):
            return None
        char = app.chars[cid]
        costly = season_mod.AC_ORDER.index(at["want"]) > season_mod.AC_ORDER.index(app.home.ac_mode())
        return {"cid": cid, "name": char.get("name", ""),
                "text": "（%sが、部屋が%sと言っている。冷暖房を「%s」にしたいらしい）" % (
                    char.get("name", ""), "暑い" if at["hot"] else "寒い", season_mod.AC_LABEL[at["want"]]),
                "choices": [{"id": k, "label": v} for k, v in CHOICES.items() if k != "bill" or costly]}

    def respond(self, choice, now=None):
        app = self.app
        now = now or time.time()
        pv = self.pending()
        if not pv or choice not in [c["id"] for c in pv["choices"]]:
            raise ValueError("いまは何もありません")
        char = app.char(pv["cid"])
        st = app.state(char["id"])
        at = st.pop("ac_talk")
        feel = "暑い" if at["hot"] else "寒い"
        if choice == "match":
            app.home.set_mode(at["want"])
            key, eff = "match", {"mood": 2}
        elif choice == "bill":
            ok = random.random() < 0.3 + 0.5 * app.life.skill_soft("talk")
            key, eff = ("bill_ok", {"mood": -0.5}) if ok else ("bill_meh", {"mood": -1.5})
        else:
            fight = random.random() < min(0.8, 0.45 * float(app.traits(char).get("grudge", 1)))
            key, eff = ("push_fight", {"mood": -3}) if fight else ("push_unhappy", {"mood": -2})
            if fight:
                app.quarrel.start(char, st, now, "冷暖房", her_fault=False)
        d = self._apply(char, st, eff, now, choice)
        said = {"match": "（冷暖房を「%s」にした）" % season_mod.AC_LABEL[at["want"]], "bill": "（電気代が気になると断った）",
                "push": "（このままがいいと言い返した）"}[choice]
        e = self._entry(char, st, now, key, said + "\n" + self.line(char, key, {"feel": feel}), d)
        app.trace.add("aircon", "言ってきたことへの出方", char["id"], now, choice=choice, key=key)
        app.save_state(char["id"])
        return {"entry": e, "key": key}

    # ------------------------------------------------------------------ あなたが変えたとき
    def changed(self, old, new, now=None):
        """あなたが使い方を old → new にした. 同居相手が起きてそばにいれば気づく (記録した場面を返す)."""
        app = self.app
        now = now or time.time()
        cid = app.bonds.living()
        if old == new or not cid or not self.awake_home(cid, now):
            return None
        char, st = app.chars[cid], app.state(cid)
        tc = season_mod.temp(datetime.fromtimestamp(now))
        fo, fn = season_mod.ac_fuss(app, char, tc, old), season_mod.ac_fuss(app, char, tc, new)
        if st.get("ac_talk") and abs(fn) < abs(fo):        # 言ってきたことを, 答える前に家の様子から叶えた
            st.pop("ac_talk", None)
        if now - float(st.get("ac_note", 0)) < NOTE_SEC:
            app.save_state(cid)
            return None
        mine = st.get("ac_self") or {}
        undo = mine.get("mode") == old and now - float(mine.get("t", 0)) < 6 * 3600
        key, eff, p = None, {}, 0.0
        if abs(fn) >= 0.3 and abs(fn) > abs(fo) + 0.2:
            key = "undo" if undo else "notice_" + ("hot" if fn > 0 else "cold")
            eff, p = ({"mood": -2}, 0.8) if undo else ({"mood": -1}, 0.4)
        elif abs(fo) >= 0.3 and abs(fn) < abs(fo) - 0.2:
            key, eff, p = "thanks", {"mood": 1}, 0.5
        app.trace.add("aircon", "あなたが変えた", cid, now, old=old, new=new, fo=fo, fn=fn, key=key, p=p)
        if not key or random.random() >= p:
            app.save_state(cid)
            return None
        st["ac_note"] = now
        if undo:
            st.pop("ac_self", None)
        d = self._apply(char, st, eff, now, key)
        e = self._entry(char, st, now, key, self.line(char, key), d)
        app.save_state(cid)
        return e
