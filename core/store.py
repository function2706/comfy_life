"""ファイル入出力とデータディレクトリの初期化.

data/ の構成:
- 全体共通: settings.json (ComfyUI・LLM・表示) / personas/ / workflow.json / images/ (画像と索引) / worlds.json
            characters/ (キャラクターの定義. どのワールドで編集しても全ワールドに反映)
- ワールドごと (data/worlds/<id>/): cast.json (このワールドに現れている定義の id) / state/ log/ (各キャラの個体)
            player.json relations.json local.json people.json と定義類
"""
import copy
import glob
import hashlib
import json
import os
import shutil
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULTS = os.path.join(BASE, "defaults")
DATA = os.environ.get("KURASHI_DATA") or os.path.join(BASE, "data")
WORLD = None          # いま開いているワールドの id
DEF_FILES = ("params.json", "actions.json", "world.json", "minigames.json", "events.json", "approaches.json")
# ワールドごとに持つもの (data 直下にあった旧形式からの移行対象)
WORLD_ITEMS = ("state", "log", "player.json", "relations.json") + DEF_FILES
# settings のうちワールドごとに持つ項目 (local.json へ)
WORLD_SETTING_KEYS = ("active_character",)


def dpath(*p):
    return os.path.join(DATA, *p)


def wpath(*p):
    """いま開いているワールドのデータ."""
    return os.path.join(DATA, "worlds", WORLD, *p)


def _world_setting_key(k):
    return k in WORLD_SETTING_KEYS or k.startswith("seen_")


def load(p, default=None):
    try:
        with open(p, encoding="utf-8-sig") as f:   # メモ帳で保存した BOM 付きも読めるように
            return json.load(f)
    except FileNotFoundError:
        return default


def save(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    # Windows ではウイルス対策ソフトなどが直前のファイルを一瞬つかんでいて置き換えに失敗することがある
    for i in range(10):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if i == 9:
                raise
            time.sleep(0.05 * (i + 1))


def obj_hash(o):
    """設定項目の指紋 (キー順に依存しない)."""
    return hashlib.md5(json.dumps(o, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def bootstrap():
    """data/ を用意する. 旧形式 (data 直下にキャラ・状態・ログ) なら最初のワールドへ移す."""
    global WORLD
    os.makedirs(dpath("images"), exist_ok=True)
    meta = load(dpath("worlds.json"))
    if not meta or not meta.get("worlds"):
        wid = "w1"
        wdir = dpath("worlds", wid)
        os.makedirs(wdir, exist_ok=True)
        for name in WORLD_ITEMS:
            if os.path.exists(dpath(name)) and not os.path.exists(os.path.join(wdir, name)):
                shutil.move(dpath(name), os.path.join(wdir, name))
        s = load(dpath("settings.json"))
        if s:
            local = {k: s.pop(k) for k in list(s) if _world_setting_key(k)}
            if local:
                save(os.path.join(wdir, "local.json"), local)
                save(dpath("settings.json"), s)
        # 旧形式の data/characters はそのまま全体の定義になり, 最初のワールドにはその全員が現れる
        ids = [os.path.splitext(os.path.basename(f))[0] for f in sorted(glob.glob(dpath("characters", "*.json")))]
        if ids:
            save(os.path.join(wdir, "cast.json"), ids)
        meta = {"current": wid, "worlds": [{"id": wid, "name": "最初のワールド", "created": time.time()}]}
        save(dpath("worlds.json"), meta)
    migrate_characters(meta)
    if meta.get("current") not in [w["id"] for w in meta["worlds"]]:
        meta["current"] = meta["worlds"][0]["id"]
        save(dpath("worlds.json"), meta)
    WORLD = meta["current"]
    init_world(WORLD)


def init_world(wid, copy_from=None, cast=None):
    """ワールドのフォルダを用意する. 定義類は copy_from のワールド (無ければ defaults/) から複製.
    顔ぶれ (cast.json) は cast を渡せばそれ, copy_from ならその顔ぶれ, どちらも無ければ既定のキャラ."""
    wdir = dpath("worlds", wid)
    src = dpath("worlds", copy_from) if copy_from else DEFAULTS
    for d in ("state", "log"):
        os.makedirs(os.path.join(wdir, d), exist_ok=True)
    for name in DEF_FILES:
        if not os.path.exists(os.path.join(wdir, name)):
            f = os.path.join(src, name)
            shutil.copyfile(f if os.path.exists(f) else os.path.join(DEFAULTS, name), os.path.join(wdir, name))
    if copy_from and not os.path.exists(os.path.join(wdir, "local.json")):
        loc = {k: v for k, v in (load(os.path.join(src, "local.json"), {}) or {}).items() if k.startswith("seen_")}
        save(os.path.join(wdir, "local.json"), loc)
    if cast is not None:
        save(os.path.join(wdir, "cast.json"), list(cast))
    elif not os.path.exists(os.path.join(wdir, "cast.json")):
        if copy_from:
            save(os.path.join(wdir, "cast.json"), load(os.path.join(src, "cast.json"), []) or [])
        else:
            save(os.path.join(wdir, "cast.json"), ensure_default_characters())


def ensure_default_characters():
    """既定のキャラの定義を全体の定義に入れる (まだ無ければ). その id のリストを返す."""
    ids = []
    for f in sorted(glob.glob(os.path.join(DEFAULTS, "characters", "*.json"))):
        c = load(f)
        if c and c.get("id"):
            if not os.path.exists(dpath("characters", c["id"] + ".json")):
                save(dpath("characters", c["id"] + ".json"), c)
            ids.append(c["id"])
    return ids


def _same_def(a, b):
    strip = lambda c: {k: v for k, v in c.items() if k not in ("prompt_history", "met")}  # noqa: E731
    return obj_hash(strip(a)) == obj_hash(strip(b))


def migrate_characters(meta):
    """以前の形式 (ワールドごとに characters/ を持つ, 登録だけの registry/characters/) を, 全体の定義 + 顔ぶれへ移す.
    同じ id で中身が違うものは, 別のキャラとして新しい id を振り, そのワールドの記録の参照も付け替える."""
    import uuid
    for w in meta.get("worlds") or []:
        wdir = dpath("worlds", w["id"])
        cdir = os.path.join(wdir, "characters")
        if not os.path.isdir(cdir):
            continue
        cast = load(os.path.join(wdir, "cast.json"), []) or []
        rename = {}
        for f in sorted(glob.glob(os.path.join(cdir, "*.json"))):
            c = load(f)
            if not c or not c.get("id"):
                continue
            cid = c["id"]
            g = load(dpath("characters", cid + ".json"))
            if g is not None and not _same_def(g, c):
                new = "c" + uuid.uuid4().hex[:8]
                rename[cid] = new
                c["id"] = cid = new
            if g is None or cid != (g or {}).get("id"):
                save(dpath("characters", cid + ".json"), c)
            if cid not in cast:
                cast.append(cid)
        save(os.path.join(wdir, "cast.json"), cast)
        if rename:
            _rename_refs(w["id"], rename, meta)
        os.replace(cdir, cdir + ".migrated")       # 念のため残す (使わない)
    rdir = dpath("registry", "characters")
    if os.path.isdir(rdir):
        for f in sorted(glob.glob(os.path.join(rdir, "*.json"))):
            c = load(f)
            if not c or not c.get("id"):
                continue
            g = load(dpath("characters", c["id"] + ".json"))
            if g is not None and not _same_def(g, c):
                c["id"] = "c" + uuid.uuid4().hex[:8]
            if g is None or not _same_def(g, c):
                save(dpath("characters", c["id"] + ".json"), c)
        os.replace(rdir, rdir + ".migrated")
    save(dpath("worlds.json"), meta)


def _rename_refs(wid, ren, meta):
    """そのワールドの記録の中のキャラ id を付け替える (状態・ログ・関係・間柄・選択中・出会い)."""
    wdir = dpath("worlds", wid)
    for sub in ("state", "log"):
        for old, new in ren.items():
            p = os.path.join(wdir, sub, old + ".json")
            if os.path.exists(p):
                os.replace(p, os.path.join(wdir, sub, new + ".json"))
    r = lambda x: ren.get(x, x)  # noqa: E731
    rel = load(os.path.join(wdir, "relations.json"))
    if rel:
        save(os.path.join(wdir, "relations.json"), {r(a): {r(b): v for b, v in m.items()} for a, m in rel.items()})
    loc = load(os.path.join(wdir, "local.json"))
    if loc and loc.get("active_character") in ren:
        loc["active_character"] = ren[loc["active_character"]]
        save(os.path.join(wdir, "local.json"), loc)
    ps = load(os.path.join(wdir, "player.json"))
    if ps:
        ps["bonds"] = {r(k): v for k, v in (ps.get("bonds") or {}).items()}
        for k in ("with", "encounter"):
            if isinstance(ps.get(k), dict) and ps[k].get("cid") in ren:
                ps[k]["cid"] = ren[ps[k]["cid"]]
            if isinstance(ps.get(k), dict) and ps[k].get("with") in ren:
                ps[k]["with"] = ren[ps[k]["with"]]
        save(os.path.join(wdir, "player.json"), ps)
    ppl = load(os.path.join(wdir, "people.json"))
    if ppl:
        for pr in ppl.values():
            if pr.get("cid") in ren:
                pr["cid"] = ren[pr["cid"]]
        save(os.path.join(wdir, "people.json"), ppl)
    for w in meta.get("worlds") or []:
        if w["id"] == wid and w.get("start_bonds"):
            w["start_bonds"] = {r(k): v for k, v in w["start_bonds"].items()}


def load_worlds():
    return load(dpath("worlds.json"), {"current": WORLD, "worlds": []})


def save_worlds(meta):
    save(dpath("worlds.json"), meta)


def load_settings():
    s = deep_merge(load(os.path.join(DEFAULTS, "settings.json"), {}), load(dpath("settings.json"), {}))
    for k in list(s):
        if _world_setting_key(k):
            del s[k]
    s.update(load(wpath("local.json"), {}) or {})
    return s


def save_settings(s):
    """全体共通の設定は data/settings.json, ワールドごとの項目は local.json へ分けて保存."""
    save(dpath("settings.json"), {k: v for k, v in s.items() if not _world_setting_key(k)})
    save(wpath("local.json"), {k: v for k, v in s.items() if _world_setting_key(k)})


def all_characters():
    """全体の定義 (どのワールドに現れているかを問わない)."""
    out = {}
    for f in sorted(glob.glob(dpath("characters", "*.json"))):
        c = load(f)
        if c and c.get("id"):
            out[c["id"]] = c
    return out


def load_cast(wid=None):
    return list(load(dpath("worlds", wid or WORLD, "cast.json"), []) or [])


def save_cast(ids, wid=None):
    save(dpath("worlds", wid or WORLD, "cast.json"), list(dict.fromkeys(ids)))


def worlds_with(cid):
    """その定義が現れているワールドの id."""
    return [w["id"] for w in load_worlds().get("worlds") or [] if cid in load_cast(w["id"])]


def load_characters():
    """いまのワールドに現れているキャラ (全体の定義のうち, 顔ぶれにあるもの)."""
    chars = {}
    for cid in load_cast():
        c = load(dpath("characters", cid + ".json"))
        if c and c.get("id"):
            chars[c["id"]] = c
    return chars


def load_personas():
    """性格プリセット. defaults/personas の上に data/personas (ユーザー編集分) を重ねる."""
    out = {}
    for d in (os.path.join(DEFAULTS, "personas"), dpath("personas")):
        for f in sorted(glob.glob(os.path.join(d, "*.json"))):
            p = load(f)
            if p and p.get("id"):
                p["_custom"] = d != os.path.join(DEFAULTS, "personas")
                if p["_custom"] and "traits" not in p and p["id"] in out:
                    p["traits"] = out[p["id"]].get("traits")     # 傾向は編集前の既定を引き継ぐ
                out[p["id"]] = p
    return out


def save_persona(p):
    p = {k: v for k, v in p.items() if not k.startswith("_")}
    save(dpath("personas", p["id"] + ".json"), p)


def save_character(c):
    """定義を保存する (全ワールドに反映)."""
    save(dpath("characters", c["id"] + ".json"), c)


def delete_character(cid):
    """定義を消す. どこかのワールドに現れているなら消さない (呼ぶ側で確かめる)."""
    p = dpath("characters", cid + ".json")
    if os.path.exists(p):
        os.remove(p)
