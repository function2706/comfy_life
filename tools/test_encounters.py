"""偶然の出会いと, 知り合った人の登録の確認 (一時データ, 画像生成なし).

    python tools/test_encounters.py
"""
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)     # 時刻を昼に固定 (流す時刻に左右されないように)



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

        # ---- 3. 新しいワールドの顔ぶれ: 登録済みの全員 (どのワールドで・手動でもくじでも) から, くじで連絡先/知り合い/まだ知らない
        man = app.new_character("ゆかり")                 # 手動で作った人も対象
        app.select_character("hina")
        pool = sorted(c["name"] for _, c in E.registered(include_defaults=True))
        assert pool == sorted(["ひな", res["registered"]["name"], "ゆかり"]), pool
        app.world["encounters"] = {"start_contact": 1, "start_known": 0}
        app.create_world("全員連絡先")
        assert sorted(c["name"] for c in app.chars.values()) == pool, "全員そろう"
        assert all(app.bonds.stage(c) == "contact" for c in app.chars), app.bonds.rec()
        assert all(app.log(c) == [] and app.state(c)["params"]["affection"] == 40 for c in app.chars), "状態・ログは一から"
        assert not any(app.relations.get(c) for c in app.chars), "関係も一から"
        app.switch_world(w1)
        app.world["encounters"] = {"start_contact": 0, "start_known": 1}
        app.create_world("知り合い")
        st_ = [app.bonds.stage(c) for c in app.chars]
        assert len(st_) == 3 and st_.count("contact") == 1 and st_.count("known") == 2, "最低一人は連絡先を知っている"
        kid = next(c for c in app.chars if app.bonds.stage(c) == "known")
        app.select_character(kid)
        av = app.state_view(kid)["available"]
        assert not av["message"]["ok"] and not av["call"]["ok"] and not av["cafe"]["ok"], "知り合いには連絡も誘いもできない"
        r = app.encounters.bump(kid, "out", None, "街", time.time())
        assert r["exchanged"] and app.bonds.stage(kid) == "contact" and "連絡先を交換" in r["text"]
        assert app.state_view(kid)["available"]["message"]["ok"]
        print("new world cast: OK")

        # ---- 4. まだ知らない人は「知らない人」の候補になる (ほかのワールドで登録済みの人)
        app.switch_world(w1)
        app.world["encounters"] = {"start_contact": 0, "start_known": 0}
        app.create_world("B")
        assert len(app.chars) == 1
        cands = sorted(c["name"] for _, c in app.encounters.candidates())
        assert len(cands) == 2 and next(iter(app.chars.values()))["name"] not in cands, cands
        r = app.encounters.happen("work", stranger=True)
        assert r["kind"] == "stranger" and r["name"] in cands and r["where"] == "職場"
        assert app.state_view()["encounter"]["from_world"]
        app.answer_encounter(False)
        assert len(app.chars) == 1 and app.encounters.pending() is None, "断れば登録しない"
        r = app.encounters.happen("work", stranger=True)
        reg = app.answer_encounter(True)["registered"]
        assert len(store.worlds_with(reg["id"])) >= 2, "同じ定義が, このワールドにも現れた (状態・ログはワールドごと)"
        assert len(app.encounters.candidates()) == 1, "このワールドにいる人は候補にしない"
        print("stranger from other world: OK")

        # ---- 5. 出会いは外出中に (心拍のたび). 帰ったときには判定しない
        from core import outdoor as outdoor_mod
        O = app.outdoor
        app.world["encounters"] = {"stranger_share": 0}
        app.presence.declare("work", time.time() - 3 * 3600)
        assert "encounter" not in app.come_back()
        app.solo.start("walk", place="park")
        assert O.current()["place"] == "park" and O.view()["current"]["label"] == "公園"
        app.world["outdoor"] = {"rate_out": 0}
        app.presence.rec()["enc_check"] = time.time() - 600
        assert O.live() is None, "起きやすさ 0 なら会わない"
        app.world["outdoor"] = {"rate_out": 1e6}
        app.presence.rec()["enc_check"] = time.time() - 600
        r = O.live()
        assert r and r["kind"] in ("call", "sight") and O.view()["current"]["log"] and app.street.pending(), r
        app.street.resolve("pass")
        app.presence.back()
        assert O.live() is None, "家にいれば会わない"
        # 起きやすさ: 行き先の人の多さ (時間帯) x 天気. 仕事・誰かとのお出かけは低め
        app.world["outdoor"] = {}
        noon = datetime.now().replace(hour=13)
        cur = lambda k, pl: {"kind": k, "place": pl, "with": None}  # noqa: E731
        real_w = outdoor_mod.weather
        outdoor_mod.weather = lambda dt: dict(real_w(dt), outdoor=1.0, indoor=1.0)
        sunny = O.rate(cur("out", "shopping_street"), noon)
        assert sunny > O.rate(cur("out", "riverside"), noon) and sunny > O.rate(cur("outing", "shopping_street"), noon)
        outdoor_mod.weather = lambda dt: dict(real_w(dt), outdoor=0.35, indoor=0.85)
        assert O.rate(cur("out", "shopping_street"), noon) < sunny * 0.5, "雨の屋外は人が少ない"
        assert O.rate(cur("out", "station"), noon) > O.rate(cur("out", "park"), noon), "雨でも屋内は減りにくい"
        outdoor_mod.weather = real_w
        assert outdoor_mod.PLACES["riverside"]["crowd"]["night"] < outdoor_mod.PLACES["shopping_street"]["crowd"]["noon"]
        w = O.view()["weather"]
        assert w["label"] in ("晴れ", "くもり", "雨", "雪") and outdoor_mod.weather(noon) == outdoor_mod.weather(noon), "同じ日は同じ天気"

        # ---- 6. 画面を閉じたら (心拍が途絶えたら), 外出はその時点で終わり, 家で静かに過ごしていた
        app.save_settings({"offline": {"enabled": False}})     # 予定どおりに過ごす分は test_offline で見る
        app.solo.start("walk", place="park")                 # 開き直しただけ (心拍が続いている) なら, 外出は続く
        app.state_view(beat=True, idle=0)
        assert app.visit() is None and app.presence.rec()["mode"] == "out"
        app.presence.back()
        p = app.presence.rec()
        app.presence.declare("work", time.time() - 3 * 3600)
        p["beat"] = time.time() - 2 * 3600                 # 1 時間働いたところで閉じた
        n0 = len(app.log(app.settings["active_character"]))
        m0 = app.life.player_state()["money"]
        g = O.check_gap()
        assert g and "家で静かに" in g["text"] and p["mode"] == "none", g
        assert 0 < app.life.player_state()["money"] - m0 < 3 * 1200 * 1.5, "給料は最後の心拍まで"
        assert len(app.log(app.settings["active_character"])) == n0, "「おかえり」は出さない"
        assert O.check_gap() is None
        app.switch_world(w1)                               # 同居相手とのお出かけも, そのまま解散
        st = app.state("hina")
        st["override"] = {"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": 9e12}
        app.set_params({"energy": 80, "sleepiness": 0, "mood": 70, "affection": 60, "health": 90})
        app.act("cafe")
        assert O.current()["kind"] == "outing" and O.current()["place"] == "cafe"
        assert "encounter" not in app.act("go_home")
        st["cooldowns"] = {}
        app.act("cafe")
        app.presence.rec()["beat"] = time.time() - 3600
        assert "解散" in O.check_gap()["text"] and not st.get("override") and O.current() is None
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
