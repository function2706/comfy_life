"""現実的な深まり方の確認: 揺らぎ・鈍り・繰り返しの逆効果, ご無沙汰で冷める, 提案は断られうる, 贈り物は性格と仲しだい,
偶然の出会いに偏りがない (一時データ, 画像生成なし).

    python tools/test_realism.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)     # 時刻を昼に固定 (流す時刻に左右されないように)



def main():
    random.seed(21)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        B, E = app.bonds, app.encounters
        char, st = app.char("hina"), app.state("hina")
        now = time.time()

        def reset_day():
            st.pop("gain_day", None)

        # ---- 1. 揺らぎと鈍り: 同じ +5 でも毎回違い, その日のうちに上がるほど小さくなる
        app.set_params({"mood": 70})
        gains = [B.realize(char, st, {"affection": 5}, None, now)[0]["affection"] for _ in range(12)]
        assert len(set(round(g, 3) for g in gains)) > 6, "毎回同じ量にならない"
        assert sum(gains[:3]) / 3 > sum(gains[-3:]) / 3 * 1.5, gains
        assert sum(gains) < 12 * 5 * 0.6, sum(gains)
        reset_day()
        app.set_params({"mood": 20})
        low = sum(B.realize(char, st, {"affection": 5}, None, now)[0]["affection"] for _ in range(40)) / 40
        reset_day()
        app.set_params({"mood": 70})
        high = sum(B.realize(char, st, {"affection": 5}, None, now)[0]["affection"] for _ in range(40)) / 40
        assert low < high, "機嫌が悪いと効きにくい"
        print("jitter / saturation: OK", [round(g, 2) for g in gains[:5]])

        # ---- 2. 同じことの繰り返しは, うんざりされて逆効果になることがある
        reset_day()
        notes, negs = 0, 0
        for _ in range(12):
            eff, note = B.realize(char, st, {"affection": 4, "trust": 2}, "talk", now)
            notes += bool(note)
            negs += eff["affection"] < 0
        assert notes >= 2 and negs == notes, (notes, negs)
        reset_day()
        first = [B.realize(char, st, {"affection": 4}, "praise", now)[1] for _ in range(2)]
        assert first == [None, None], "1〜2 回目でうんざりはされない"
        # コマンド経由でも記録され, 文章に添えられる
        reset_day()
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": 9e12}
        app.set_params({"mood": 70, "sleepiness": 0, "energy": 80})
        texts = []
        for _ in range(10):
            st["cooldowns"] = {}
            texts.append(app.act("talk")["entry"]["text"])
        assert any("うんざり" in t for t in texts), texts
        assert B.freq(st, time.time()) == 1 and st["last_touch"] > now - 60, "交流した日が記録される"
        print("repetition backfire: OK", notes, "/ 12")

        # ---- 3. ご無沙汰で冷める (同居は除く). 長く会わないと家に行ける仲も遠のく
        mio = app.new_character("みお")
        app.select_character("hina")
        sm = app.state(mio["id"])
        B.set_stage(mio["id"], "visit")
        app.set_params({"affection": 70, "trust": 70}, mio["id"])
        sm["last_touch"] = time.time() - 10 * 86400
        sm["last_tick"] = time.time() - 5 * 86400
        app.tick(mio["id"])
        assert 25 <= sm["params"]["affection"] < 70 - 1.5 and sm["params"]["trust"] < 70, sm["params"]
        assert B.stage(mio["id"]) == "visit"
        sm["last_touch"] = time.time() - 40 * 86400
        sm["last_tick"] = time.time() - 86400
        app.tick(mio["id"])
        assert B.stage(mio["id"]) == "contact", "しばらく会わないと, 家に行ける仲から遠のく"
        assert any("距離" in r["tell"] for r in sm.get("reasons") or [])
        st["last_touch"] = time.time() - 30 * 86400        # 同居相手は冷めない (在席の仕組みで別に扱う)
        a0 = st["params"]["affection"]
        st["last_tick"] = time.time() - 86400
        app.tick("hina")
        assert st["params"]["affection"] >= a0 - 0.01
        print("cooling: OK", round(sm["params"]["affection"], 1))

        # ---- 4. 段階の提案: 数値を満たしても, 最近の交流が少なく久しぶりなら断られる
        app.set_params({"affection": 70, "trust": 70, "mood": 70}, mio["id"])
        sm["override"] = {"activity": "relax", "label": "くつろぎ", "location": "みおの部屋", "until": 9e12}
        sm["touch_days"], sm["last_touch"] = [], time.time() - 20 * 86400
        assert max(B.readiness(app.char(mio["id"]), sm, time.time()) for _ in range(50)) < 50
        app.select_character(mio["id"])
        app.act("ask_visit", mio["id"])
        assert B.stage(mio["id"]) == "contact", "しきい値を超えても, 断られうる"
        days = [B._day(time.time() - i * 86400) for i in range(10)]
        sm["touch_days"], sm["last_touch"] = days, time.time()
        app.set_params({"affection": 85, "trust": 85}, mio["id"])
        assert min(B.readiness(app.char(mio["id"]), sm, time.time()) for _ in range(50)) > 50
        sm["cooldowns"] = {}
        app.act("ask_visit", mio["id"])
        assert B.stage(mio["id"]) == "visit", "よく会っていて気持ちが整っていれば受けてくれる"
        print("readiness: OK")

        # ---- 5. 贈り物・お金: 性格と仲の深さ・頻度しだい
        mc = app.char(mio["id"])
        B.start(mio["id"], "visit")          # みおの家に遊びに来ている
        mc["persona_id"] = "kedakai"
        app.life.player_state()["money"] = 200000
        app.set_params({"affection": 45, "trust": 45, "mood": 60}, mio["id"])
        m0 = app.life.player_state()["money"]
        e = app.act("expensive_gift", mio["id"])["entry"]
        assert "受け取れない" in e["text"] and app.life.player_state()["money"] == m0, ("気高い人・浅い仲には重い", e["text"])
        sm["cooldowns"] = {}
        e = app.act("allowance", mio["id"])["entry"]
        assert app.life.player_state()["money"] == m0 and e["deltas"].get("trust", 0) < 0, e
        # 甘えたがりで深い仲なら喜ぶ
        mc["persona_id"] = "amaenbo"
        B.set_stage(mio["id"], "visit")
        app.set_params({"affection": 90, "trust": 90, "mood": 70}, mio["id"])
        sm["gifts"], sm["cooldowns"] = [], {}
        assert min(B.gift_feel(mc, sm, time.time(), money=True) for _ in range(50)) > 45
        app.act("expensive_gift", mio["id"])
        assert app.life.player_state()["money"] < m0
        # 贈り物が続くと, ありがたみが薄れる
        f0 = sum(B.gift_feel(mc, sm, time.time()) for _ in range(50)) / 50
        sm["gifts"] = [time.time() - 3600 * i for i in range(4)]
        f4 = sum(B.gift_feel(mc, sm, time.time()) for _ in range(50)) / 50
        assert f4 < f0 - 40, (f0, f4)
        # 性格の gift 倍率: 気高い人は物では動きにくい
        reset = lambda: sm.pop("gain_day", None)  # noqa: E731
        mc["persona_id"] = "kedakai"
        reset()
        k = sum(B.realize(mc, sm, {"affection": 5}, None, time.time(), gift="item")[0]["affection"] for _ in range(30))
        mc["persona_id"] = "amaenbo"
        reset()
        a = sum(B.realize(mc, sm, {"affection": 5}, None, time.time(), gift="item")[0]["affection"] for _ in range(30))
        assert k < a, (k, a)
        print("gifts: OK")

        # ---- 6. 偶然の出会いに偏りはない: 会う相手がいなければ何も起きない (知らない人に振り替えない)
        app.world["encounters"] = {"stranger_share": 0}
        for c in [c for c in app.chars if c != "hina"]:
            app.delete_character(c)
        assert all(E.happen("out") is None for _ in range(20)), "知っている人がいなくても, 知らない人に会わせはしない"
        app.world["encounters"] = {"stranger_share": 1}
        E.happen("out")
        assert E.pending()
        mio2 = app.new_character("みお")
        app.select_character("hina")
        assert all(E.happen("out") is None for _ in range(20)), "返事待ちのときに, 代わりに知っている人へ会わせはしない"
        assert mio2["id"] in app.chars
        print("encounter bias: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
