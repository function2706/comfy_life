"""株の噂: 知り合いから聞ける, 会社や店の話.

- 話のついで (立ち話・会話のコマンドのあと) に, ときどき「◯◯の新商品が好評らしい」のような話が聞ける.
  人づて (相手が知っている人の勤め先の話) やメッセージにも添えられることがある.
- 会話 (と気配り) のスキルが高いほど, 聞ける頻度が上がり, 話の確かさ (実際の値動きと合う割合) が上がる. ただし確定にはしない (上限 85%).
  その会社・業種の店で働いている人の話 (相手の予定の勤め先) は, 少し確か.
- 噂は「これから起きること」の先触れ: 聞いた時点で, その銘柄にこれからの出来事 (本当の向き) を一つ決め, 0.5〜3 日後の取引時間に
  公開のニュースとして表に出て値段が動く (公開のニュースの当たりやすさは誰にも同じ. 噂を聞いていない人にも同じように起きる).
- 聞いた話は, 関係性 (知っていること kind = stock), トーク (メッセージのとき), 株のニュースの欄に出所つきで残る.
新しいセリフの場面は作らない (ナレーション).
"""
import random
import time
from datetime import datetime, timedelta

from . import market as market_mod

# 行き先 (勤め先) → 銘柄の業種
PLACE_SECTOR = {"supermarket": "supermarket", "convenience": "convenience", "drugstore": "drugstore", "bookstore": "bookstore",
                "electronics": "electronics", "family": "eat", "teishoku": "eat", "ramen": "eat", "fastfood": "eat", "restaurant": "eat",
                "mall": "mall", "cafe": "cafe", "amusement": "amusement", "aquarium": "aquarium"}
SAY = {1: ["{name}の新商品が好評らしい", "{name}の店、最近すごく混んでるらしい", "{name}が近くに新しい店を出すって聞いた",
           "{name}、今度大きな取引が決まりそうなんだって"],
       -1: ["{name}の店、最近お客さんが減ってるらしい", "{name}、また値上げするって話があるらしい", "{name}の新商品、評判がいまいちらしい",
            "{name}、人が足りなくて店を閉める日が増えるらしい"]}
INSIDE = {1: ["働いている{place}の本部から、新しい企画が来てるらしい", "働いている{place}で、売り上げが前の年よりずっといいらしい"],
          -1: ["働いている{place}で、売り上げが落ちてるって店長がこぼしてたらしい", "働いている{place}で、近くの店を閉めるって話が出てるらしい"]}


class Rumors:
    def __init__(self, app):
        self.app = app

    @property
    def M(self):
        return self.app.market

    def accuracy(self, inside=False, secondhand=False):
        """話の確かさ: 会話と気配りのスキルで上がる. 働いている人の話は少し確か, 人づては少し落ちる. 上限 85%."""
        L = self.app.life
        a = 0.5 + 0.2 * L.skill_soft("talk") + 0.1 * L.skill_soft("care") + (0.08 if inside else 0) - (0.05 if secondhand else 0)
        return max(0.4, min(0.85, a))

    def rate(self):
        """1 回の会話で噂を聞ける見込み (会話・気配りのスキルで上がる)."""
        L = self.app.life
        return 0.02 + 0.07 * L.skill_soft("talk") + 0.03 * L.skill_soft("care")

    def insider(self, char):
        """その人の勤め先 (予定の workplace) の業種の銘柄 or None."""
        for e in char.get("schedule") or []:
            sec = PLACE_SECTOR.get(e.get("workplace") or "")
            if sec:
                a = next((x for x in self.M.assets() if x.get("sector") == sec), None)
                if a:
                    return a, e["workplace"]
        return None

    def hear(self, char, via, now=None, about=None):
        """char から噂を聞く (via: talk / secondhand / message). about: 人づてのとき, 話に出てくる人.
        聞けたら (噂の記録) を返す."""
        app = self.app
        now = now or time.time()
        src = about or char
        ins = self.insider(src)
        pick = [a for a in self.M.assets() if a.get("sector") not in ("index",)]
        if not pick:
            return None
        if ins and random.random() < 0.6:
            a, place = ins
            inside = True
        else:
            a, place, inside = random.choice(pick), None, False
        real = random.choice((1, -1))
        acc = self.accuracy(inside, via == "secondhand")
        said = real if random.random() < acc else -real
        name = a.get("name", a["id"])
        if inside:
            what = random.choice(INSIDE[said]).replace("{place}", "%s（%s）" % (app.places.label(place), name))
        else:
            what = random.choice(SAY[said]).replace("{name}", name)
        # これから起きること: 0.5〜3 日後の取引時間に, 公開のニュースとして表に出る (本当の向きは real)
        at = market_mod.next_open(datetime.fromtimestamp(now + random.uniform(0.5, 3.0) * 86400)).timestamp()
        m = self.M.m()
        m.setdefault("pending", []).append({"asset": a["id"], "real": real, "at": at})
        r = {"t": now, "asset": a["id"], "dir": said, "text": what, "src": src["id"], "src_name": src.get("name", ""),
             "via": via, "teller": char["id"], "inside": inside}
        m.setdefault("rumors", []).append(r)
        del m["rumors"][:-20]
        app.topics.from_rumor(what, now)          # 聞いた噂は, ほかの人への話題にもなる
        st = app.state(src["id"] if via != "secondhand" else char["id"])
        known = st.setdefault("known", [])
        known.append({"kind": "stock", "text": what, "t": now, "via": via,
                      **({"about": src.get("name", "")} if via == "secondhand" else {})})
        del known[:-30]
        return r

    def from_talk(self, char, st, now=None):
        """話のついでに, 会社や店の噂を聞くことがある (一日に一人一度まで). ナレーション or None."""
        now = now or time.time()
        day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        if (st.get("rumor_day") == day) or random.random() >= self.rate():
            return None
        st["rumor_day"] = day
        app = self.app
        about = None
        others = [b for b, rel in (app.relations.get(char["id"]) or {}).items() if rel.get("knows") and b in app.chars
                  and self.insider(app.chars[b])]
        if others and random.random() < 0.3:          # 人づて: 知っている人の勤め先の話
            about = app.chars[random.choice(others)]
        r = self.hear(char, "secondhand" if about else "talk", now, about)
        if not r:
            return None
        if not about:
            app.save_state(char["id"])
        app.life.save_player()
        if about:
            return "（%sから、%sの話を聞いた。%s）" % (char.get("name", ""), about.get("name", ""), r["text"])
        return "（話のついでに、%sから聞いた。%s）" % (char.get("name", ""), r["text"])

    def from_message(self, char, st, now=None):
        """離れている相手のメッセージに, 噂が添えられることがある (まれ). トークの一行 or None."""
        now = now or time.time()
        day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        if st.get("rumor_day") == day or random.random() >= self.rate() * 0.5:
            return None
        st["rumor_day"] = day
        r = self.hear(char, "message", now)
        if r:
            self.app.save_state(char["id"])
            self.app.life.save_player()
        return "（そういえば、%s）" % r["text"] if r else None

    def view(self, now=None):
        m = self.M.m()
        names = {a["id"]: a.get("name", a["id"]) for a in self.M.assets()}
        return [dict(r, name=names.get(r["asset"], r["asset"])) for r in reversed((m.get("rumors") or [])[-8:])]
