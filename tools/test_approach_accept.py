"""F19: 相手から誘ったことに「いいよ」と応じたら, 断られない (一時データ).
働きかけ (approaches.json) の accept.action をすべて回し, その行動の断る反応 (override. taken を除く) の条件を
成り立たせても, 応じたときには選ばれないこと (ふつうに選ぶときは選ばれる). あわせて, 散歩・ゲームの誘いは
相手の体力が無いときには出ないこと, 体力が無いのに誘いが残っていて応じても散歩に行くことを確かめる.

    python tools/test_approach_accept.py
"""
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import cond, engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)


def satisfy(when, ctx):
    """条件式を成り立たせる値を ctx に入れる (単純な比較だけ)."""
    for c in [x.strip() for x in (when or "").split(",") if x.strip()]:
        m = re.match(r"^(\w+)\s*(>=|<=|!=|>|<|=)\s*(.+)$", c)
        k, op, v = m.groups()
        try:
            n = float(v)
            ctx[k] = {">=": n, "<=": n, ">": n + 1, "<": n - 1, "=": n, "!=": n + 1}[op]
        except ValueError:
            alts = v.split("|")
            if op == "=":
                ctx[k] = True if alts[0] == "true" else False if alts[0] == "false" else alts[0]
            else:
                ctx[k] = "_other_"
    assert cond.check(when, ctx), (when, {k: ctx.get(k) for k in re.findall(r"(\w+)\s*[<>=!]", when)})


def main():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("誘い")
        cid = app.settings["active_character"]
        char, st = app.chars[cid], app.state(cid)
        n = 0
        for ap in app.approaches:
            aid = (ap.get("accept") or {}).get("action")
            if not aid:
                continue
            a = app.action(aid)
            for r in a.get("reactions") or []:
                if not (r.get("override") and not r.get("taken")):
                    continue
                ctx = app.context(char, st, datetime.now())
                satisfy(r.get("when", ""), ctx)
                for _ in range(30):
                    got = app.pick_reaction(a, ctx, invited=True)
                    assert got is not r and not (got.get("override") and not got.get("taken")), \
                        (ap["id"], aid, r.get("when"), "誘いに応じたのに断る反応", got.get("when"))
                assert any(app.pick_reaction(a, ctx) is r or app.pick_reaction(a, ctx).get("override") for _ in range(60)), \
                    (ap["id"], aid, r.get("when"), "ふつうに選ぶときに断る反応が出ない (条件の組み立てを見直す)")
                n += 1
        assert n >= 5, n
        print("働きかけ × 断る反応 %d 通り: 応じたら断らない: OK" % n)

        # 体力が無いと, 散歩・ゲームには誘ってこない
        for aid in ("walk_invite", "play"):
            ap = app.presence.find(aid)
            ctx = app.context(char, st, datetime.now())
            satisfy(ap["when"], ctx)
            ctx["energy"] = 10
            assert not cond.check(ap["when"], ctx), (aid, "体力が無いのに誘う")
        print("体力 10 では散歩・ゲームに誘わない: OK")

        # 誘いが出たあとで体力が落ちても, 応じたら散歩に行く (actで)
        st["params"]["energy"] = 10
        st["params"]["mood"] = 80
        st["override"] = None
        app.save_state(cid)
        app.bonds.set_stage(cid, "visit")
        app.bonds.start(cid, "guest")          # あなたの家に来ている (そばにいる)
        app.force_approach("walk_invite", cid)
        res = app.answer_approach("accept", cid)
        e = res.get("entry") or {}
        assert not e.get("override"), ("応じたのに断られた", e.get("text"))
        print("体力が落ちてから応じても断られない: OK (%s)" % (e.get("text") or "")[:30])
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
