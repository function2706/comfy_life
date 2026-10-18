"""ファイル入出力とデータディレクトリの初期化.

data/ の構成:
- 全体共通: settings.json (ComfyUI・LLM・表示) / personas/ / workflow.json / images/ (画像と索引) / worlds.json
- ワールドごと (data/worlds/<id>/): characters/ state/ log/ player.json relations.json local.json と定義類
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
WORLD_ITEMS = ("characters", "state", "log", "player.json", "relations.json") + DEF_FILES
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
        meta = {"current": wid, "worlds": [{"id": wid, "name": "最初のワールド", "created": time.time()}]}
        save(dpath("worlds.json"), meta)
    if meta.get("current") not in [w["id"] for w in meta["worlds"]]:
        meta["current"] = meta["worlds"][0]["id"]
        save(dpath("worlds.json"), meta)
    WORLD = meta["current"]
    init_world(WORLD)


def init_world(wid, copy_from=None, chars=None):
    """ワールドのフォルダを用意する. 定義類とキャラは copy_from のワールド (無ければ defaults/) から複製.
    chars を渡せば, キャラはそれ (キャラ定義のリスト) にする."""
    wdir = dpath("worlds", wid)
    src = dpath("worlds", copy_from) if copy_from else DEFAULTS
    for d in ("characters", "state", "log"):
        os.makedirs(os.path.join(wdir, d), exist_ok=True)
    for name in DEF_FILES:
        if not os.path.exists(os.path.join(wdir, name)):
            f = os.path.join(src, name)
            shutil.copyfile(f if os.path.exists(f) else os.path.join(DEFAULTS, name), os.path.join(wdir, name))
    if copy_from and not os.path.exists(os.path.join(wdir, "local.json")):
        loc = {k: v for k, v in (load(os.path.join(src, "local.json"), {}) or {}).items() if k.startswith("seen_")}
        save(os.path.join(wdir, "local.json"), loc)
    if chars:
        for c in chars:
            save(os.path.join(wdir, "characters", c["id"] + ".json"), c)
    if not glob.glob(os.path.join(wdir, "characters", "*.json")):
        for f in glob.glob(os.path.join(src, "characters", "*.json")):
            shutil.copy(f, os.path.join(wdir, "characters"))


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


def load_characters():
    chars = {}
    for f in sorted(glob.glob(wpath("characters", "*.json"))):
        c = load(f)
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
    save(wpath("characters", c["id"] + ".json"), c)


def delete_character(cid):
    p = wpath("characters", cid + ".json")
    if os.path.exists(p):
        os.remove(p)
