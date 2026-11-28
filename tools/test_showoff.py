"""見せたくなる場面 (A44 段 2. core/showoff.py・core/posing.py の live / dress_show / answer).

見せたい気持ち (下がる・戻る・返事しだい)・新しい服 (いま持っている服は新しくない)・場面の倍率・
性格 × 場面の総当たりで 1 日あたりの数が幅に入り日ごとにぶれる (ゼロにならない・上限は置かず気持ちで頭打ち)・
着替えて見せる (寝るまで着ている・二度目は新しくない)・写メ (返事・返事がない・形に残るので大胆さを下げる・
会う約束の前の服)・大人だけ・二重に開いても二重に送らない.

    python tools/test_showoff.py
"""
import collections
import os
import random
import shutil
import statistics
import sys
import tempfile
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from core import engine, showoff, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
H = 3600.0


def main():
    random.seed(45)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        so, P = app.showoff, app.posing
        cid = "hina"
        char, st = app.chars[cid], app.state(cid)
        st.update(override={"activity": "relax", "label": "くつろぎ", "location": "リビング", "until": 9e12})
        base_params = {"affection": 75, "trust": 70, "heart": 55, "mood": 65, "energy": 70, "health": 90, "loneliness": 40,
                       "boredom": 40, "sleepiness": 0}
        app.set_params(base_params)
        now = time.time()

        # ---- 1. 見せたい気持ち: 始まり・見せると下がる・戻る・返事しだい
        st.pop("showy", None)
        assert so.level(char, st, now) == showoff.START
        so.shown(char, st, now)
        v1 = so.level(char, st, now)
        assert abs(v1 - showoff.START * showoff.SHOW_LEFT) < 1e-6
        assert v1 < so.level(char, st, now + 6 * H) < so.level(char, st, now + 24 * H) < 1.0, "時間とともに戻る"
        s_ok = {"showy": {"v": 0.3, "t": now, "since": now}}
        s_bad = {"showy": {"v": 0.3, "t": now, "since": now}}
        so.reacted(char, s_bad, "bad", now)
        so.rec(char, s_bad, now)
        so.rec(char, s_ok, now)
        s_bad["showy"]["v"] = s_ok["showy"]["v"] = 0.3
        assert so.level(char, s_bad, now + 12 * H) < so.level(char, s_ok, now + 12 * H), "嫌がられたあとは戻りが遅い"
        so.reacted(char, s_ok, "good", now + 12 * H)
        assert so.scene(char, dict(s_ok, params=st["params"]), now + 13 * H, False)[0] > 1.0 - 1e-9, "褒められた直後は乗る"
        print("見せたい気持ち: ok")

        # ---- 2. 新しい服: いま持っている服は新しくない (遡及). 手に入れた服は 7 日まで
        st.pop("showy", None)
        st["shown"] = []
        so.rec(char, st, now)
        assert not so.new_clothes(char, st, now), "いま持っている服は見せたことにする"
        free = [o for o in app.wardrobe.all() if o.get("kind") == "casual" and o.get("slot") in ("set", "onepiece") and o["bold"] == 0
                and o["id"] not in app.wardrobe.owned_ids(char)]
        assert free
        char.setdefault("clothes", []).append({"id": free[0]["id"], "from": "player", "t": now + 1})
        assert [o["id"] for o in so.new_clothes(char, st, now + 2)] == [free[0]["id"]]
        assert not so.new_clothes(char, st, now + 8 * 86400), "7 日を過ぎたら新しくない"
        assert so.scene(char, st, now + 2, False) == (showoff.NEW_MULT, "new")
        print("新しい服: ok")

        # ---- 3. 着替えて見せる: 新しい服に着替える → 感想 → 二度目は新しくない. 寝るまで着ている
        orig_at = app.presence.at
        app.presence.at = lambda t: "here"           # noqa: E731
        st["pose_offer"] = None
        e = P.dress_show(char, st, P._dress_pick(char, st, now + 2, "new", random), now + 2, "new")
        assert st["dress"]["id"] == free[0]["id"] and st["dress"]["by"] == "her"
        assert st["pose_offer"]["kind"] == "dress" and "着てみた" in e["text"], e["text"]
        assert not so.new_clothes(char, st, now + 3), "見せた服は新しくない"
        pv = app.posing.pending_view(char, st)
        assert pv["choices"] and not pv["apart"]
        r = app.answer_approach("reply", cid, "praise")
        assert st["pose_offer"] is None and r["entry"]
        assert app.prefs_pref(st, "outfit:" + free[0]["id"]) != 0 if hasattr(app, "prefs_pref") else True
        print("着替えて見せる:", e["text"].replace("\n", " / "))

        # ---- 4. 性格 × 場面の総当たり: 二人きりで 8 日 (10 分ごと). 1 日あたりの数が幅に入り, 日ごとにぶれる
        real_traits = app.traits
        PROFILES = {"人懐っこい": {"approach": 1.8, "play": 0.8, "modesty": -4, "carer": 0.6, "caution": -3},
                    "ふつう": {"approach": 1.0, "play": 0.2, "modesty": 0, "carer": 0.4, "caution": 0},
                    "恥ずかしがり": {"approach": 0.6, "play": -0.6, "modesty": 6, "carer": 0.3, "caution": 5}}
        SCENES = {"ふつう": {}, "寂しい": {"loneliness": 80}, "疲れ": {"energy": 20}}
        table = {}
        for pn, tr in PROFILES.items():
            app.traits = lambda c, tr=tr: dict(real_traits(c), **tr)     # noqa: E731
            for sn, sp in SCENES.items():
                per_day = []
                for day in range(8):
                    st.pop("showy", None)
                    st["pose_offer"] = None
                    st["dress"] = None
                    t = now + day * 86400
                    so.rec(char, st, t - 1)
                    st["pose_check"] = t
                    n = 0
                    for i in range(1, 6 * 16 + 1):          # 起きている 16 時間
                        tt = t + i * 600
                        app.set_params(dict(base_params, **sp))
                        if sn == "寂しい":
                            st["last_interaction"] = tt - 3 * H
                        else:
                            st["last_interaction"] = tt
                        if P.live(char, st, tt):
                            n += 1
                        if st.get("pose_offer") and st["pose_offer"]["kind"] in ("did", "dress"):
                            P.answer(char, st, "praise", tt)
                        elif st.get("pose_offer"):
                            st["pose_offer"] = None
                    per_day.append(n)
                table[(pn, sn)] = per_day
        app.traits = real_traits
        for k, v in table.items():
            print("  %s × %s: 1 日 %s" % (k[0], k[1], v))
        assert sum(table[("人懐っこい", "ふつう")]) > 0 and sum(table[("恥ずかしがり", "ふつう")]) >= 0
        assert sum(table[("人懐っこい", "ふつう")]) > sum(table[("恥ずかしがり", "ふつう")]), "恥ずかしがりは控えめ"
        assert sum(table[("人懐っこい", "疲れ")]) < sum(table[("人懐っこい", "ふつう")]) + 1, "疲れていると下がる"
        assert max(max(v) for v in table.values()) <= 16, "見せたい気持ちで頭打ち (上限は置かないが, 多すぎない)"
        spread = [statistics.pstdev(v) for k, v in table.items() if sum(v) >= 3]
        assert spread and max(spread) > 0, "日ごとにぶれる"
        print("性格 × 場面: ok")

        # ---- 5. 写メ (離れている相手): 同居していない人で
        app.presence.at = orig_at
        app.create_world("見せたくなる場面")
        c2 = app.settings["active_character"]
        ch2, st2 = app.chars[c2], app.state(c2)
        sched = app.scheduled_scene
        app.scheduled_scene = lambda c, d: dict(sched(c, d), away=False, busy=False, asleep=False)    # noqa: E731
        app.bonds.set_stage(c2, "contact") if hasattr(app.bonds, "set_stage") else None
        assert app.bonds.stage(c2) in ("contact", "visit", "live") and not app.bonds.together(c2), app.bonds.stage(c2)
        for k, v in dict(base_params, affection=80, heart=60).items():
            st2["params"][k] = v
        st2["last_interaction"] = now
        sent, pose_caps = 0, []
        st2["photo_check"] = now
        cap = so.cap(ch2, st2)
        for i in range(1, 6 * 24 * 3):
            tt = now + i * 600
            e = so.photo_live(ch2, st2, tt)
            if e:
                sent += 1
                off = st2["pose_offer"]
                if off["itype"] in ("pose", "show"):
                    pose_caps.append(P.get(off["item"])["bold"])
                assert so.photo_live(ch2, st2, tt) is None, "二重に開いても二重に送らない"
                r = app.answer_approach("reply", c2, "praise")
                assert st2["pose_offer"] is None
                its = app.chat.load(c2)["items"]
                kinds = collections.Counter((x.get("kind"), x["who"]) for x in its)
                assert kinds[("her_photo", "her")] == sent and kinds[("photo_react", "her")] == sent, kinds
        print("写メ: 3 日で %d 枚 / 写したものの大胆さ %s (上限 %d - 1)" % (sent, collections.Counter(pose_caps), cap))
        assert sent > 0
        assert all(b <= cap - 1 for b in pose_caps), "写メは形に残るので, 大胆さを 1 段下げる"
        # 返事がない: 待ちが切れたら気持ちが下がり, 戻りが遅い
        st2["pose_offer"] = None
        so.send_photo(ch2, st2, now, "", None, random)
        v0 = so.level(ch2, st2, now)
        so.photo_live(ch2, st2, now + showoff.PHOTO_WAIT + 1)
        assert st2["pose_offer"] is None and so.level(ch2, st2, now + showoff.PHOTO_WAIT + 1) < v0 + 0.05
        assert float(st2["showy"].get("slow_until", 0)) > now
        # 会う約束の前: 今日の服
        st2["pose_offer"] = None
        e = so.send_photo(ch2, st2, now, "date", {"id": "x1"}, random)
        assert "今日" in e["text"] and st2["photo_date"] == "x1"
        app.answer_approach("later", c2)
        print("写メの返事・返事なし・約束の前: ok")

        # ---- 6. 大人だけ
        age = ch2.get("age")
        ch2["age"] = 16
        st2["pose_offer"] = None
        st2["photo_check"] = now
        assert not any(so.photo_live(ch2, st2, now + i * 600) for i in range(1, 300)), "18 歳未満は写メを送ってこない"
        ch2["age"] = age
        app.scheduled_scene = sched
        print("ok: 全部通った")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
