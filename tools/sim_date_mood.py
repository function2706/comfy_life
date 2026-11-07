"""開発者向け: デートの機嫌・照れの動きを見る (11/07 の報告と同じ流れ: 水族館 → カフェ → 移動、知り合いの仲).
コマンドを報告と同じくらいの間隔で押し, 機嫌・照れ・ドキドキの動きと, 絵の頬の赤さ (blush) を出す. 何度か流して平均も.

    python tools/sim_date_mood.py [回数] [old]      # old: 鈍り・慣れ・頬の赤さの合わせ (1.5.0) を外した, 以前の動き
"""
import os
import random
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)

# (分, コマンド) 報告の流れ (13:00 水族館 〜 15:35)
FLOW = [(1.5, "talk"), (2, "praise"), (2.5, "peek_face"), (3, "full_body"), (5.5, "stare"), (6.5, "tease"),
        (9, "hold_hands"), (53, "hold_hands"), (67, "talk"), (68, "full_body"), (68.5, "ask_mood"), (69, "headpat"),
        (80, "praise"), (92, "talk"), (102, "full_body"), (109, "peek_face"), (109.5, "talk"), (110, "hold_hands"),
        (111, "gift"), (112, "photo"), (136, "talk"), (140, "thank"), (143, "tease"), (155, "ask_mood"), (155.2, "comfort")]


def run(seed):
    random.seed(seed)
    tmp = tempfile.mkdtemp(prefix="kurashi_sim_")
    store.DATA = tmp
    real = time.time
    off = [0.0]
    time.time = lambda: real() + off[0]
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("機嫌")
        cid = app.settings["active_character"]
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)
        app.bonds.set_stage(cid, "contact")
        app.bonds.start(cid, "meet")
        st = app.state(cid)
        st["override"] = {"outing": True, "place": "aquarium", "location": "水族館", "until": time.time() + 4 * 3600, "from_action": "aquarium"}
        app.set_params({"mood": 61, "shyness": 5, "heart": 0, "affection": 41, "trust": 43, "energy": 80, "stress": 19, "loneliness": 20,
                        "boredom": 30}, cid)
        st["last_tick"] = time.time()
        rows, blush = [], 0
        t0 = time.time()
        for m, aid in FLOW:
            off[0] += max(0.0, t0 + m * 60 - time.time())
            st["cooldowns"] = {}
            try:
                r = app.act(aid, cid, opts={"pick": "x"} if aid == "thank" else {"gift_item": None} if aid == "gift" else {})
            except ValueError:
                continue
            e = (r or {}).get("entry") or {}
            p = st["params"]
            tg = [t.strip() for t in (e.get("pos") or "").split(",")]
            b = "full" if "full-face blush" in tg else "blush" if "blush" in tg else "light" if "light blush" in tg else ""
            blush += 1 if b else 0
            rows.append((m, aid, round(p["mood"], 1), round(p["shyness"], 1), round(p["heart"], 1), b))
        return rows, blush
    finally:
        time.time = real
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    if "old" in sys.argv:
        engine.App.SATURATE, engine.App.HABITUATE = {}, {}
        engine.App.BLUSH_MIN = engine.App.BLUSH_MID = engine.App.BLUSH_FULL = 0.0
    fin = []
    for i in range(n):
        rows, blush = run(i)
        if i == 0:
            for r in rows:
                print("%6.1f分 %-11s 機嫌 %5.1f  照れ %5.1f  ドキドキ %5.1f  %s" % r)
        fin.append((rows[-1][2], max(r[3] for r in rows), rows[-1][3], blush, len(rows)))
    print("---- %d 回: 終わりの機嫌 %.1f / 照れの最高 %.1f / 終わりの照れ %.1f / 頬の赤い絵 %.1f / %d 枚" % (
        n, sum(f[0] for f in fin) / n, sum(f[1] for f in fin) / n, sum(f[2] for f in fin) / n, sum(f[3] for f in fin) / n, fin[0][4]))


if __name__ == "__main__":
    main()
