"""オフラインモードの確認: 画面を閉じている間は予定 (勤務時間) どおりに過ごし, 開いたときにまとめを一度だけ見せる.
仕事のうまくいかない・早退・残業, 職場での出会い (無難な対応), 届くメッセージと返事の遅れ (一時データ, 画像生成なし).

    python tools/test_offline.py
"""
import collections
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, store  # noqa: E402


def ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").timestamp()


def main():
    random.seed(23)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("オフライン")
        O, L = app.offline, app.life
        mon8, mon20 = ts("2026-10-12 08:00"), ts("2026-10-12 20:00")       # 月曜

        # ---- 1. 予定: 既定は平日 9〜18 時が仕事. 以前の勤務時間の設定も読み替える
        seg = O.segments(mon8, mon20)
        assert seg == [(ts("2026-10-12 09:00"), ts("2026-10-12 18:00"))], seg
        assert O.segments(ts("2026-10-17 08:00"), ts("2026-10-17 20:00")) == [], "土曜は休み"
        app.save_settings({"offline": {"work": {"sat": {"on": True, "from": "10:00", "to": "15:00"}}}})
        assert O.segments(ts("2026-10-17 08:00"), ts("2026-10-17 20:00")) == [(ts("2026-10-17 10:00"), ts("2026-10-17 15:00"))]
        assert O.segments(mon8, mon20), "以前の設定 (勤務時間) は行動パターンの「仕事」に読み替える. ほかの曜日は既定のまま"
        app.save_settings({"offline": {"work": {"sat": {"on": False}}}})
        assert O.simulate(mon8, mon8 + 600) is None, "短い離席は対象外"

        # ---- 2. 勤務: 給料・体力・仕事スキル. 体力しだいで早退が増え, うまくいかない日も
        def run(stamina, n=40):
            notes = collections.Counter()
            for _ in range(n):
                L.player_state()["stamina"] = stamina
                L.player_state()["work_log"] = {}
                L.player_state()["last_tick"] = mon8
                rep = O.simulate(mon8, mon20)
                w = rep["works"][0]
                for x in w["notes"]:
                    notes[x] += 1
            return notes, rep
        tired, rep = run(10)
        fresh, rep2 = run(100)
        assert tired["体調がすぐれず、早退した"] > fresh["体調がすぐれず、早退した"] + 5, (tired, fresh)
        assert fresh["残業になった"] > 0 and fresh["仕事がうまくいかず、叱られた"] > 0, fresh
        w = rep2["works"][0]
        assert w["pay"] > 0 and w["hours"] > 3 and rep2["stamina"][1] < 100, rep2
        print("work:", dict(tired), "/", dict(fresh))

        # ---- 3. 職場の出会いは, 気づけないので無難な対応 (返事待ちは残らない)
        app.world["outdoor"] = {"rate_work": 1e6}
        L.player_state()["work_log"] = {}
        rep = O.simulate(mon8, mon20)
        assert rep["meets"] and not app.street.pending(), rep["meets"]
        assert any(("会釈して流した" in m) or ("通り過ぎた" in m) for m in rep["meets"]), rep["meets"]
        app.world["outdoor"] = {}

        # ---- 4. 離れているキャラからメッセージ. 返事の遅れの受け止め方は性格しだい
        cid = app.settings["active_character"]
        st = app.state(cid)
        char = app.char(cid)
        app.world.setdefault("presence", {})["approach_apart_rate_per_hour"] = 1000

        def msg(pid):
            char["persona_id"] = pid
            st.pop("approach", None)
            st["ap_last"] = {}
            app.set_params({"loneliness": 90, "affection": 80, "mood": 60, "trust": 40}, cid)
            r = O.simulate(mon8, mon20)
            return r["messages"]
        m1 = msg("amaenbo")
        m2 = msg("cool")
        per = lambda m: m["mood"] / min(8.0, 0.6 * (mon20 - m["t"]) / 3600.0)  # noqa: E731  (返事を待たせた時間あたり)
        assert m1 and m2 and per(m1[0]) < per(m2[0]) < 0, (m1, m2)
        assert st.get("approach") and st["approach"]["until"] == mon20 + 1800, "開いてから少しのあいだ返事ができる"
        assert mon8 <= m1[0]["t"] <= mon20
        app.world["presence"]["approach_apart_rate_per_hour"] = 0.25
        print("messages: OK", m1[0]["mood"], m2[0]["mood"])

        # ---- 5. 開いたとき: まとめを一度だけ見せて, 普段に戻る
        st.pop("approach", None)
        p = app.presence.rec()
        p["beat"] = time.time() - 3 * 86400
        L.player_state()["last_tick"] = time.time() - 3 * 86400
        v = app.state_view(beat=True, idle=0)
        assert v["gap"] and v["gap"].get("report") and v["offline_report"], v["gap"]
        assert app.state_view(beat=True, idle=0)["offline_report"], "読むまでは出ている"
        app.offline.ack()
        assert app.state_view(beat=True, idle=0)["offline_report"] is None and v["gap"]
        # 外出中 (仕事) に閉じた: その時点で帰り, あとは予定どおり
        app.presence.declare("work", time.time() - 4 * 3600)
        p["beat"] = time.time() - 3 * 3600
        g = app.outdoor.check_gap()
        assert g and p["mode"] == "none" and app.offline.report(), g
        # オフラインモードを切れば, 家で静かに過ごしていただけ
        app.offline.ack()
        app.save_settings({"offline": {"enabled": False}})
        p["beat"] = time.time() - 5 * 3600
        g = app.outdoor.check_gap()
        assert g is None and app.offline.report() is None
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
