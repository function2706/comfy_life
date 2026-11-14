"""生活の型 (core/lifetype.py) の確認 (一時データ, 画像生成なし).
- 型 × 性格 × 種の総当たり: 予定に重なりが無い・睡眠が毎晩 6〜9 時間・仕事の日数・勤め先の営業時間の中・起きてから出かけるまでの間
- 同じ life から同じ予定. 人が増えると型が分かれる. 性格の文の職の言葉が先・学生は若い人だけ
- 定義の移行: 既定のキャラはそのまま / 写し・少し古い写し・空は作り直す / 手で直した予定は残る / schedule_old / バックアップ /
  二度目は何もしない / 途中で止めてやり直しても同じ
- ワールド: 作り直した人の知っている予定・覚えた日ごとのずれだけ消える / 二度は走らない / ほかのワールドは開いたときに
- 生活リズム (core/rhythm.py): 昼に寝る人 (夜勤) で落ちない・寝坊・寝そびれ・朝の残業 / ひなの基本の時刻は前のまま
- 新しく作る人・設定で足す人・予定を手で書き換えた人 / 出先でのばったり / 聞ける予定 / あいさつの時刻

    python tools/test_lifetype.py
"""
import copy
import glob
import json
import os
import random
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import engine, knowsched, lifetype, places, rhythm, store  # noqa: E402

WORK = rhythm.WORK_ACTS + ("class",)
MON = datetime(2026, 11, 16)          # 月曜


def scene_rows(sched, d, m):
    """その曜日 (0=月) の m 分に当てはまる行."""
    dt = MON + timedelta(days=d, minutes=m)
    return [e for e in sched if engine.day_match(e.get("days"), dt) and engine.in_range(m, e["from"], e["to"])]


def check_schedule(char, tag):
    life, sched = char["life"], char["schedule"]
    tid = life["type"]
    grid = []                         # 7 日 × 288 コマ
    for d in range(7):
        for m in range(0, 1440, 5):
            rows = scene_rows(sched, d, m)
            assert len(rows) <= 1, "%s: 予定が重なっている %s %d:%02d %s" % (tag, lifetype.DAYS[d], m // 60, m % 60, [r["label"] for r in rows])
            grid.append(rows[0] if rows else None)
    for e in sched:
        assert lifetype._mins(e["from"]) < lifetype._mins(e["to"]), (tag, e)
        assert not e.get("cont") or e["from"] == "00:00", (tag, e)
    # 睡眠: 一週間をひと回りして, 続いた枠が 7 つ, どれも 6〜9 時間
    n = len(grid)
    asleep = [bool(g and g.get("asleep")) for g in grid]
    start = next(i for i in range(n) if asleep[i] and not asleep[i - 1])
    runs, i = [], 0
    while i < n:
        j = (start + i) % n
        if asleep[j]:
            k = 0
            while asleep[(j + k) % n]:
                k += 1
            runs.append(k * 5)
            i += k
        else:
            i += 1
    assert len(runs) == 7, "%s: 睡眠の枠が 7 つでない %s" % (tag, runs)
    assert all(360 <= r <= 540 for r in runs), "%s: 睡眠が 6〜9 時間でない %s" % (tag, [r / 60.0 for r in runs])
    # 仕事: 日数と, 勤め先の営業時間
    off = {lifetype.DAYS.index(x) for x in life.get("off") or []}
    for d in range(7):
        day = grid[d * 288:(d + 1) * 288]
        starts = [i for i in range(288) if day[i] and day[i].get("activity") in WORK and not day[i].get("cont")
                  and (i == 0 or not (day[i - 1] and day[i - 1].get("activity") in WORK + ("lunch",)))]
        if tid in ("office", "shift", "service", "freelance", "night"):
            assert bool(starts) == (d not in off), "%s: %s の仕事の有無が休みの日と合わない" % (tag, lifetype.DAYS[d])
        for i in range(288):
            g = day[i]
            if g and g.get("workplace"):
                o, c, closed = lifetype.shop_hours(g["workplace"])
                assert d not in closed, "%s: 定休日に働いている %s" % (tag, g["label"])
                assert tid == "night" or o <= i * 5 < c, "%s: 営業時間の外で働いている %s %d" % (tag, g["label"], i * 5)
        # 起きてから家を出るまでに, 少なくとも 1 時間
        wake = next((i for i in range(1, 288) if day[i - 1] and day[i - 1].get("asleep") and not (day[i] and day[i].get("asleep"))), None)
        if wake is not None:
            out = next((i for i in range(wake, 288) if day[i] and day[i].get("away")), None)
            assert out is None or (out - wake) * 5 >= 60, "%s: %s 起きてすぐ出かけている (%d 分)" % (tag, lifetype.DAYS[d], (out - wake) * 5)
    assert any(e.get("asleep") for e in sched)
    return grid


def test_build():
    personas = store.load_personas()
    assert len(personas) >= 27 and all("chrono" in (p.get("traits") or {}) for p in personas.values() if not p.get("_custom")), \
        "性格の傾向に chrono (朝型・夜型) がある"
    n = 0
    for tid in lifetype.TYPES:
        for pid, p in sorted(personas.items()):
            for k in range(20):
                c = {"id": "%s_%s_%d" % (tid, pid, k), "name": "x", "age": 20 + k % 3, "persona": "", "persona_id": pid,
                     "outfit_outing": "coat, skirt"}
                c["life"] = lifetype.decide(c, p.get("traits"), type_id=tid)
                c["schedule"] = lifetype.build(c)
                check_schedule(c, c["id"])
                again = dict(c, life=lifetype.decide(c, p.get("traits"), type_id=tid))
                assert again["life"] == c["life"] and lifetype.build(again) == c["schedule"], "同じ人・同じ種なら同じ予定"
                n += 1
    print("build: %d 通り (型 %d × 性格 %d × 種 20) OK" % (n, len(lifetype.TYPES), len(personas)))
    # 朝型・夜型で寝起きがずれる (同じ型で比べる)
    early = lifetype.assign({"id": "e1", "age": 25, "persona": ""}, {"chrono": -0.6}, type_id="freelance")
    late = lifetype.assign({"id": "e1", "age": 25, "persona": ""}, {"chrono": 0.6}, type_id="freelance")
    assert late["life"]["chrono"] - early["life"]["chrono"] == 70, (early["life"], late["life"])
    w = lambda c: min(lifetype._mins(e["to"]) for e in c["schedule"] if e.get("asleep"))  # noqa: E731
    assert w(late) > w(early), "夜型は起きるのが遅い"
    # 20 人: 型が 4 種類以上に分かれ, 平日の 14 時に全員が仕事中にはならない
    ppl = [lifetype.assign({"id": "p%d" % i, "age": 19 + i % 14, "persona": ""}, {"chrono": 0}) for i in range(20)]
    kinds = {c["life"]["type"] for c in ppl}
    assert len(kinds) >= 4, kinds
    busy = [bool(r and (r[0].get("away") or r[0].get("busy") or r[0].get("asleep"))) for r in (scene_rows(c["schedule"], 2, 840) for c in ppl)]
    assert 0 < sum(busy) < 20, busy
    assert all(c["life"]["src"] == "lottery" for c in ppl)
    # 性格の文に職の言葉があれば, その型. 学生のくじは若い人だけ
    c = lifetype.assign({"id": "t1", "age": 30, "persona": "大学生。明るい"}, {})
    assert c["life"]["type"] == "student" and c["life"]["src"] == "text", c["life"]
    assert lifetype.assign({"id": "t2", "age": 28, "persona": "看護の仕事をしている"}, {})["life"]["type"] == "night"
    assert not any(lifetype.decide({"id": "o%d" % i, "age": 30, "persona": ""})["type"] == "student" for i in range(300))
    assert any(lifetype.decide({"id": "o%d" % i, "age": 20, "persona": ""})["type"] == "student" for i in range(300))
    print("types: %s / text / age OK" % sorted(kinds))


def old_data(tmp):
    """更新前のデータを作る: 生活の型の無い定義 (ひな・ひなの写し・少し古い写し・空・手書き) と, 2 つのワールドの記録."""
    store.DATA = tmp
    app = engine.App()
    app.save_settings({"auto_generate": False})
    w1 = store.WORLD
    hina = store.all_characters()["hina"]
    base = {k: v for k, v in hina.items() if k not in ("id", "name", "life", "persona")}
    older = copy.deepcopy(hina["schedule"])
    for e in older:
        e.pop("workplace", None)                 # 少し前の版の既定 (勤め先が無い・一つだけ時刻が違う)
    older[2]["to"] = "07:10"
    custom = [{"days": "all", "from": "01:00", "to": "09:00", "activity": "sleep", "label": "就寝中", "asleep": True},
              {"days": "mon,wed,fri", "from": "13:00", "to": "19:00", "activity": "work", "label": "塾で仕事中", "location": "塾", "away": True}]
    defs = {"c_copy": dict(base, schedule=copy.deepcopy(hina["schedule"]), persona="のんびりしている", age=27),
            "c_older": dict(base, schedule=older, persona="会社員。きっちりしている", age=29),
            "c_empty": dict(base, schedule=[], persona="", age=31),
            "c_custom": dict(base, schedule=custom, persona="", age=33)}
    for cid, c in defs.items():
        c.update(id=cid, name=cid)
        store.save(store.dpath("characters", cid + ".json"), c)
    h = dict(hina)
    h.pop("life")
    store.save(store.dpath("characters", "hina.json"), h)
    app.create_world("二つ目", switch=False)
    w2 = [w["id"] for w in store.load_worlds()["worlds"] if w["id"] != w1][0]
    t = time.time()
    for wid in (w1, w2):
        store.save(store.dpath("worlds", wid, "cast.json"), ["hina"] + sorted(defs))
        ps = store.load(store.dpath("worlds", wid, "player.json")) or {"money": 30000, "last_tick": t}
        ps.pop("life_v", None)
        store.save(store.dpath("worlds", wid, "player.json"), ps)
        store.save(store.dpath("worlds", wid, "mylog.json"), [{"t": t - 86400, "kind": "home", "text": "前からの記録"}])
        for cid in ["hina"] + sorted(defs):
            p = store.dpath("worlds", wid, "state", cid + ".json")
            st = store.load(p) or {"params": {}, "last_tick": t, "last_interaction": t, "override": None, "cooldowns": {}, "created": t}
            st["known"] = [{"kind": "schedule", "text": "土曜の午前は本屋でバイトらしい", "t": t, "key": "k", "via": "talk"},
                           {"kind": "like", "text": "甘いものが好き", "t": t}]
            st["sched_told"] = {"d": "2026-11-01"}
            st["rhythm"] = {"2026-11-13": {"wake": 30, "bed": 0, "all_night": False, "ot": 0}}
            st["rhythm_since"] = "2026-10-01"
            store.save(p, st)
    return w1, w2, hina, defs


def test_migrate():
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    try:
        w1, w2, hina, defs = old_data(tmp)
        meta = store.load_worlds()
        assert any("生活の型" in x for x in store.pending_migrations(meta)), "生活の型の無い定義があれば, 移行が要る"
        store._backed_up.clear()
        before = set(os.listdir(store.backup_dir())) if os.path.isdir(store.backup_dir()) else set()
        app = engine.App()                      # 更新後の起動
        after = set(os.listdir(store.backup_dir()))
        assert len(after - before) == 1, "移行の前にバックアップができる"
        bk = os.path.join(store.backup_dir(), (after - before).pop())
        assert "life" not in store.load(os.path.join(bk, "characters", "c_copy.json")), "バックアップは移行の前の中身"
        assert not any("生活の型" in x for x in store.pending_migrations(store.load_worlds()))
        chars = store.all_characters()
        # 定義
        h = chars["hina"]
        assert h["schedule"] == hina["schedule"] and h["life"]["type"] == "student" and h["life"]["src"] == "given", h["life"]
        assert "schedule_old" not in h
        for cid in ("c_copy", "c_older", "c_empty"):
            c = chars[cid]
            assert c["schedule_old"] == defs[cid]["schedule"], cid
            assert c["schedule"] != defs[cid]["schedule"] and c["life"]["src"] in ("lottery", "text") and c["life"]["seed"] == cid, c["life"]
            check_schedule(c, cid)
        assert chars["c_older"]["life"]["type"] == "office" and chars["c_older"]["life"]["src"] == "text", "性格の文が会社員"
        cu = chars["c_custom"]
        assert cu["schedule"] == defs["c_custom"]["schedule"] and "schedule_old" not in cu, "手で書き換えた予定は作り直さない"
        assert cu["life"]["src"] == "custom" and cu["life"]["type"] in lifetype.TYPES, cu["life"]
        print("migrate defs: OK", {k: (v["life"]["type"], v["life"]["src"]) for k, v in sorted(chars.items())})
        # 二度目は何もしない. 途中で止まった (life が付く前に落ちた) 定義をやり直しても同じ
        snap = {f: open(f, encoding="utf-8").read() for f in glob.glob(store.dpath("characters", "*.json"))}
        assert lifetype.migrate_defs() == []
        c = dict(chars["c_copy"])
        c["schedule"] = c.pop("schedule_old")
        c.pop("life")
        store.save(store.dpath("characters", "c_copy.json"), c)
        assert lifetype.migrate_defs() == ["c_copy"]
        assert {f: open(f, encoding="utf-8").read() for f in glob.glob(store.dpath("characters", "*.json"))} == snap, "やり直しても同じ結果"
        # ワールド (いま開いているほう)
        assert app.life.player_state().get("life_v") == lifetype.V
        for cid in ("c_copy", "c_older", "c_empty"):
            st = app.state(cid)
            assert [k["kind"] for k in st["known"]] == ["like"] and "sched_told" not in st and not st.get("rhythm"), (cid, st.get("known"))
            assert st.get("rhythm_since") == "2026-10-01"
        for cid in ("hina", "c_custom"):
            st = app.state(cid)
            assert len(st["known"]) == 2 and st.get("sched_told") and st.get("rhythm"), "予定を変えていない人の記録は消さない (%s)" % cid
        notes = [e for e in app.solo.mylog() if "暮らしぶり" in e.get("text", "")]
        assert len(notes) == 1, notes
        # もう一方のワールドは, まだそのまま. 開いたときに同じ処理
        st2 = store.load(store.dpath("worlds", w2, "state", "c_copy.json"))
        assert len(st2["known"]) == 2
        other = w2 if store.WORLD == w1 else w1
        app.switch_world(other)
        assert [k["kind"] for k in app.state("c_copy")["known"]] == ["like"] and len(app.state("hina")["known"]) == 2
        assert len([e for e in app.solo.mylog() if "暮らしぶり" in e.get("text", "")]) == 1
        # 二度は走らない: 新しく聞いた予定は, 開き直しても残る
        e = knowsched.notable(app.chars["c_copy"])[0]
        assert app.knowsched.learn("c_copy", e, "talk")
        app.save_state("c_copy")
        assert lifetype.world_step(app) is None
        app.switch_world(w1 if other == w2 else w2)
        app.switch_world(other)
        assert any(k["kind"] == "schedule" for k in app.state("c_copy")["known"])
        assert len([e for e in app.solo.mylog() if "暮らしぶり" in e.get("text", "")]) == 1
        app2 = engine.App()
        assert any(k["kind"] == "schedule" for k in app2.state("c_copy")["known"]), "起動し直しても消えない"
        # 新しく作ったワールドには, 移行の印が初めから付く (暮らしぶりの知らせも出ない)
        app2.create_world("三つ目")
        assert app2.life.player_state().get("life_v") == lifetype.V and not app2.solo.mylog()
        print("migrate worlds: OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp + "_backup", ignore_errors=True)


def test_runtime():
    random.seed(5)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        hina = app.chars["hina"]
        # ひなの基本の時刻は, 前の決め方のまま (日ごとのずれの出方が変わらない)
        dm = engine.day_match
        assert rhythm.sleep_times(hina, date(2026, 11, 16), dm) == (390, 1440)       # 月
        assert rhythm.sleep_times(hina, date(2026, 11, 21), dm) == (480, 1440)       # 土
        assert [rhythm.free_morning(hina, date(2026, 11, 16 + i), dm) for i in (0, 5, 6)] == [False, False, True]
        assert rhythm.work_end(hina, date(2026, 11, 21), dm) == 840
        # 夜勤の人: 昼に寝る
        nc = {"id": "c_night", "name": "よる", "age": 26, "persona": "", "persona_id": "teinei", "pos": "1girl", "neg": "",
              "outfit_default": "", "outfit_outing": "coat", "clothes": [], "prompt_history": []}
        nc["life"] = dict(lifetype.decide(nc, {"chrono": 0}, type_id="night"), off=["tue", "wed"], chrono=0)
        nc["schedule"] = lifetype.build(nc)
        nc["default_activity"] = lifetype.default_activity()
        app.save_character(nc)
        app.place_character("c_night", "contact")
        nc = app.chars["c_night"]
        check_schedule(nc, "c_night")
        sat = date(2026, 11, 21)                      # 金曜の晩から働いて, 土曜の昼に寝る
        wake, bed = rhythm.sleep_times(nc, sat, dm)
        assert (wake, bed) == (930, 480) and rhythm.same_day((wake, bed)), (wake, bed)
        assert rhythm.work_end(nc, sat, dm) == 360, "夜勤の終わりは朝"
        st = app.state("c_night")
        st["rhythm_since"] = "2026-01-01"
        base = lambda h, m: app._base_scene(nc, datetime(2026, 11, 21, h, m))       # noqa: E731
        now = lambda h, m: app.scheduled_scene(nc, datetime(2026, 11, 21, h, m))    # noqa: E731
        assert base(6, 10)["label"] == "帰宅中" and base(8, 30)["asleep"] and not base(15, 40)["asleep"]
        st["rhythm"] = {sat.isoformat(): {"wake": 40, "bed": 60, "all_night": False, "ot": 60},
                        (sat - timedelta(days=1)).isoformat(): {"wake": 0, "bed": 0, "all_night": False, "ot": 0}}
        assert "残業" in now(6, 10)["label"] and now(6, 10)["away"], "残業が朝に付く"
        assert not now(8, 30)["asleep"] and now(8, 30)["label"] == "まだ起きている", now(8, 30)
        assert now(9, 10)["asleep"]
        assert now(15, 50)["asleep"], "昼すぎの寝坊"
        assert not now(16, 20)["asleep"]
        st["rhythm"][sat.isoformat()] = {"wake": -30, "bed": -45, "all_night": False, "ot": 0}
        assert now(7, 30)["asleep"] and not now(15, 10)["asleep"], "早寝・早起き"
        st["rhythm"][sat.isoformat()] = {"wake": 0, "bed": 0, "all_night": True, "ot": 0}
        assert not now(12, 0)["asleep"] and now(12, 0)["label"] == "寝ないで起きている"
        st["rhythm"] = {}
        for i in range(14 * 96):                      # 2 週間を 15 分ごとに: どの時刻でも落ちない
            app.scheduled_scene(nc, datetime(2026, 11, 16) + timedelta(minutes=15 * i))
        for cid in ("hina", "c_night"):
            for i in range(21):
                rhythm.decide(app, app.chars[cid], app.state(cid), date(2026, 11, 16) + timedelta(days=i), dm)
        print("rhythm (night shift): OK")
        # 0 時すぎに寝る人の早寝は, 日付の前へ出る
        fc = lifetype.assign({"id": "c_free", "name": "ふり", "age": 28, "persona": "", "persona_id": "teinei", "pos": "1girl", "neg": "",
                              "outfit_default": "", "clothes": [], "prompt_history": []}, {"chrono": 0.5}, type_id="freelance")
        app.save_character(fc)
        app.place_character("c_free", "contact")
        fc = app.chars["c_free"]
        w2, b2 = rhythm.sleep_times(fc, sat, dm)
        assert rhythm.same_day((w2, b2)) and b2 < 180, (w2, b2)
        fs = app.state("c_free")
        fs["rhythm_since"] = "2026-01-01"
        fs["rhythm"] = {sat.isoformat(): {"wake": 0, "bed": -60, "all_night": False, "ot": 0},
                        (sat - timedelta(days=1)).isoformat(): {"wake": 0, "bed": 0, "all_night": False, "ot": 0}}
        fri = datetime(2026, 11, 20, 23, 59)
        assert not app._base_scene(fc, fri)["asleep"]
        assert app.scheduled_scene(fc, fri)["asleep"] == (b2 - 60 < 0), "0 時すぎに寝る人の早寝"
        # 聞ける予定: 日をまたいだ後半の行は数えない
        assert any(e.get("cont") for e in nc["schedule"]) and not any(e.get("cont") for e in knowsched.notable(nc))
        assert any("夜勤" in e["label"] for e in knowsched.notable(nc))
        # あいさつ: 夜勤の人は, 夕方の「おはよう」・朝の「おやすみ」が変ではない. ひなには変
        assert app.manners.greet_fits(nc, "greet_morning", datetime(2026, 11, 21, 16, 30))
        assert app.manners.greet_fits(nc, "greet_night", datetime(2026, 11, 21, 7, 0))
        assert not app.manners.greet_fits(hina, "greet_morning", datetime(2026, 11, 21, 16, 30))
        assert not app.manners.greet_fits(hina, "greet_night", datetime(2026, 11, 21, 9, 0))
        # 出先でのばったり: 寝ている・仕事中の人には会わない
        t = lambda h, m: datetime(2026, 11, 21, h, m).timestamp()        # noqa: E731
        st["rhythm"] = {(sat + timedelta(days=i)).isoformat(): {"wake": 0, "bed": 0, "all_night": False, "ot": 0} for i in (-1, 0, 1)}
        assert not app.street.around("c_night", t(10, 0)) and not app.street.around("c_night", t(23, 0))
        assert app.street.around("c_night", t(17, 0))
        print("known / greet / street: OK")
        # 新しく作る人
        seen = set()
        for _ in range(40):
            g = app.encounters.generate()
            assert g["life"]["src"] in ("lottery", "text") and g["schedule"] and g["default_activity"], g.get("life")
            seen.add(g["life"]["type"])
        assert len(seen) >= 4, seen
        nw = app.new_character("あたらしい")
        assert nw["life"]["type"] in lifetype.TYPES and nw["schedule"] and nw["life"]["seed"] == nw["id"]
        check_schedule(nw, "new")
        cp = app.new_character("うつし", copy_from="hina")
        assert cp["schedule"] == hina["schedule"] and cp["life"]["src"] == "custom" and cp["life"]["type"] == "student", cp["life"]
        # 古い画面からの保存 (life を持たない) でも, 型は消えない. 予定を手で書き換えたら, 作り直さない人になる
        edit = {k: v for k, v in copy.deepcopy(nw).items() if k not in ("life", "_stage")}
        app.save_character(edit)
        assert store.all_characters()[nw["id"]]["life"] == nw["life"]
        edit = {k: v for k, v in copy.deepcopy(nw).items() if k != "_stage"}
        edit["schedule"] = edit["schedule"][:-1]
        app.save_character(edit)
        assert store.all_characters()[nw["id"]]["life"]["src"] == "custom"
        print("generate / new / edit: OK", sorted(seen))
        # 登録を尋ねている途中の人 (以前の形: 予定の写しを持ち, 生活の型が無い) も作り直す
        g = app.encounters.generate()
        g.pop("life")
        g["schedule"] = copy.deepcopy(hina["schedule"])
        ps = app.life.player_state()
        ps["encounter"] = {"t": time.time(), "kind": "out", "where": "街", "with": None, "char": g, "src": {"type": "new"}, "persona_name": ""}
        ps.pop("life_v")
        assert lifetype.world_step(app) is not None
        e = app.encounters.pending()["char"]
        assert e["life"]["type"] in lifetype.TYPES and e["schedule"] != hina["schedule"]
        r = app.encounters.answer(True)
        assert store.all_characters()[r["registered"]["id"]]["life"] == e["life"]
        print("pending encounter: OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp + "_backup", ignore_errors=True)


def main():
    assert lifetype.FIXED is None
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        test_build()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    test_migrate()
    test_runtime()
    print("ALL OK")


if __name__ == "__main__":
    main()
