"""手伝いまわりの重みの一覧 (検査用. 一時データ). 性格・仲の近さ・懐具合・献身度・依存度を振って, 見込みを表にする.

1. 相手を手伝ったとき, お礼がお金になる見込み (earn.money_chance) と, お金でないお礼の形の割合
2. その場の強欲度 (askhelp.greed): 性格 + 懐具合 − 近さ − 献身度
3. 手伝いを頼んで受けてくれる見込み (askhelp.accept_chance)
4. 手伝ってもらったあとの出方: お金を求める / 今度おごって / 何も求めない (askhelp.outcome_chances)
5. あなたからお礼のお金を渡して, 受け取る見込み (askhelp.offer_chance)

    python tools/check_help_weights.py [性格 ...]
"""
import collections
import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from core.earn import Earn  # noqa: E402

PERSONAS = sys.argv[1:] or ["osananajimi", "amaenbo", "genki", "teinei", "aneki", "jimuteki", "seijitsu", "hikutsu", "kedakai",
                            "ojousama", "sadist", "itazura", "yareyare", "cool"]
RELS = [("浅い", "contact", 52, 50), ("ふつう", "contact", 65, 60), ("家に行ける仲", "visit", 72, 68), ("親密", "visit", 88, 82)]
MONEY = [("金欠", 3000), ("ふつう", 30000), ("余裕", 120000)]


def main():
    random.seed(1)
    tmp = tempfile.mkdtemp(prefix="kurashi_w_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)
        H = app.askhelp

        def setup(pid, rel, money=30000, dv=50, dep=50):
            char["persona_id"] = pid
            _, stage, aff, tr = rel
            app.bonds.set_stage(cid, stage)
            st["params"].update(affection=aff, trust=tr, mood=55)
            app.life.her_money(st)["a"] = money
            st["attach"] = dict(st.get("attach") or {}, devotion=dv, dependence=dep)

        print("== 1. 相手を手伝ったとき: お金になる見込み (献身・依存 ふつう) / 律儀さ")
        print("%-12s %5s  " % ("性格", "律儀") + "  ".join("%-8s" % r[0] for r in RELS))
        for pid in PERSONAS:
            setup(pid, RELS[0])
            rp = float(app.traits(char).get("repay", 1))
            row = []
            for rel in RELS:
                setup(pid, rel)
                row.append(Earn.money_chance(app.earn.closeness(cid, st), rp, 0, 0))
            print("%-12s %5.1f  " % (pid, rp) + "  ".join("%7.0f%%" % (v * 100) for v in row))
        print("\n   献身度・依存度の効き (丁寧・家に行ける仲): お金の見込み / お金でないお礼の形")
        for dv, dep in ((50, 50), (85, 50), (15, 50), (50, 85), (85, 85)):
            setup("teinei", RELS[2], dv=dv, dep=dep)
            fv, fd = app.attach.factor(char, st, "devotion"), app.attach.factor(char, st, "dependence")
            pm = Earn.money_chance(app.earn.closeness(cid, st), 1.1, fv, fd)
            c = collections.Counter(app.earn.thanks_form(fv, fd)[0] for _ in range(2000))
            print("   献身 %2d 依存 %2d : お金 %3.0f%% | %s" % (dv, dep, pm * 100,
                                                       " ".join("%s %2.0f%%" % (k, c[k] / 20.0) for k in ("treat", "cook", "sweets", "words", "later", "together"))))

        print("\n== 2. その場の強欲度 (献身 ふつう) / 性格の強欲度")
        print("%-12s %5s  " % ("性格", "強欲") + "  ".join("%-14s" % ("%s・%s" % (r[0], m[0])) for r in (RELS[0], RELS[2], RELS[3]) for m in MONEY))
        for pid in PERSONAS:
            setup(pid, RELS[0])
            g0 = float(app.traits(char).get("greed", 0.2))
            row = []
            for rel in (RELS[0], RELS[2], RELS[3]):
                for _, mo in MONEY:
                    setup(pid, rel, money=mo)
                    row.append(H.greed(char, st))
            print("%-12s %5.2f  " % (pid, g0) + "  ".join("%13.2f " % v for v in row))

        print("\n== 3. 手伝いを頼んで受けてくれる見込み (懐 ふつう)")
        print("%-12s %5s  " % ("性格", "世話") + "  ".join("%-8s" % r[0] for r in RELS))
        for pid in PERSONAS:
            setup(pid, RELS[0])
            cr = float(app.traits(char).get("carer", 0.3))
            row = []
            for rel in RELS:
                setup(pid, rel)
                row.append(H.accept_chance(char, st))
            print("%-12s %5.2f  " % (pid, cr) + "  ".join("%7.0f%%" % (v * 100) for v in row))

        print("\n== 4. 手伝ってもらったあとの出方: お金 / おごって / なし (懐 ふつう・金欠)")
        for pid in PERSONAS:
            cells = []
            for rel in (RELS[0], RELS[2], RELS[3]):
                for mn, mo in (MONEY[1], MONEY[0]):
                    setup(pid, rel, money=mo)
                    pm, pt = H.outcome_chances(char, st)
                    cells.append("%s%s %2.0f/%2.0f/%2.0f" % (rel[0][:2], mn[:1], pm * 100, pt * 100, (1 - pm - pt) * 100))
            print("%-12s " % pid + "  ".join(cells))

        print("\n== 5. あなたからお礼のお金を渡して, 受け取る見込み (懐 ふつう)")
        print("%-12s %5s  " % ("性格", "抵抗") + "  ".join("%-8s" % r[0] for r in RELS))
        for pid in PERSONAS:
            setup(pid, RELS[0])
            mt = float(app.traits(char).get("money", 0))
            row = []
            for rel in RELS:
                setup(pid, rel)
                row.append(H.offer_chance(char, st))
            print("%-12s %5.0f  " % (pid, mt) + "  ".join("%7.0f%%" % (v * 100) for v in row))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
