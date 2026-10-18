"""偶然の出会いと, 知り合った人の登録の確認 (一時データ, 画像生成なし).

    python tools/test_encounters.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402


def main():
    random.seed(11)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        w1 = store.WORLD
        E = app.encounters

        # ---- 1. ほかのワールドに候補がいなければ, 新しい人を作って知り合う → 登録するか尋ねる
        assert not E.candidates()
        r = E.happen("out", stranger=True)
        assert r["kind"] == "stranger" and E.pending(), r
        v = app.state_view()["encounter"]
        assert v["name"] == r["name"] and v["where"] == "街" and not v["from_world"], v
        c = E.pending()["char"]
        assert c["pos"].startswith("1girl") and c["schedule"] and c.get("persona_id"), c
        assert E.happen("out", stranger=True) is None, "返事待ちの人がいる間は新しい人とは知り合わない. 同居相手には偶然会わない"
        res = app.answer_encounter(True)
        nid = res["registered"]["id"]
        assert nid in app.chars and app.bonds.stage(nid) == "contact"
        assert app.chars[nid]["met"]["src"]["type"] == "new"
        assert "知り合って" in app.log(nid)[-1]["text"]
        assert app.state_view()["encounter"] is None
        print("stranger (new) -> register: OK", res)

        # ---- 2. 登録済みのキャラに偶然会う. 一緒にいた人とは互いに知り合う
        assert not app.relation("hina", nid)["knows"]
        r = E.happen("outing", with_cid="hina", where="カフェ", stranger=False)
        assert r["kind"] == "bump" and r["cid"] == nid and r["introduced"], r
        assert app.relation("hina", nid)["knows"] and app.relation(nid, "hina")["knows"]
        assert "カフェ" in app.log(nid)[-1]["text"]
        print("bump: OK", r["text"])

        # ---- 3. 別のワールドでは, ワールド1で登録した人が「知らない人」の候補になる
        app.create_world("B")
        cands = [c["name"] for _, c in app.encounters.candidates()]
        assert cands == [app.encounters.candidates()[0][1]["name"]] and res["registered"]["name"] in cands, cands
        r = app.encounters.happen("work", stranger=True)
        assert r["kind"] == "stranger" and r["name"] == res["registered"]["name"] and r["where"] == "職場"
        assert app.state_view()["encounter"]["from_world"]
        app.answer_encounter(False)
        assert len(app.chars) == 1 and app.encounters.pending() is None, "断れば登録しない"
        r = app.encounters.happen("work", stranger=True)
        reg = app.answer_encounter(True)["registered"]
        assert app.chars[reg["id"]]["met"]["src"] == {"type": "world", "world": w1}
        assert not app.encounters.candidates(), "このワールドにいる人は候補にしない"
        print("stranger from other world: OK")

        # ---- 4. 仕事帰り・一人で出かけた帰り・お出かけの帰りに起きる
        app.world["encounters"] = {"rate_work": 50, "rate_out": 50, "rate_outing": 50, "max_chance": 1, "stranger_share": 0}
        app.presence.declare("work", time.time() - 3 * 3600)
        r = app.come_back()
        assert r.get("encounter") and r["encounter"]["kind"] == "bump", r.get("encounter")
        app.presence.declare("out", time.time() - 3600)
        assert app.come_back().get("encounter")
        app.world["encounters"]["rate_work"] = 0
        app.presence.declare("work", time.time() - 3 * 3600)
        assert app.come_back().get("encounter") is None
        # お出かけ (同居相手と) の帰り
        app.switch_world(w1)
        app.world["encounters"] = {"rate_outing": 50, "max_chance": 1, "stranger_share": 1}
        st = app.state("hina")
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": 9e12}
        app.set_params({"energy": 80, "sleepiness": 0, "mood": 70, "affection": 60, "health": 90})
        app.act("cafe")
        st["override"]["until"] -= 30 * 60          # 30 分たった
        r = app.act("go_home")
        assert r.get("encounter") and r["encounter"]["kind"] == "stranger", r.get("encounter")
        assert app.state_view()["encounter"]["with"] == "ひな"
        reg = app.answer_encounter(True)["registered"]
        assert app.relation("hina", reg["id"])["knows"], "一緒にいた人とは知り合い"
        # 返事をしないまま日がたつと消える
        app.encounters.happen("out", stranger=True)
        app.life.player_state()["encounter"]["t"] -= 100 * 3600
        assert app.encounters.pending() is None
        print("hooks: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
