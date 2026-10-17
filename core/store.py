"""ファイル入出力とデータディレクトリの初期化."""
import copy
import glob
import json
import os
import shutil

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULTS = os.path.join(BASE, "defaults")
DATA = os.environ.get("KURASHI_DATA") or os.path.join(BASE, "data")


def dpath(*p):
    return os.path.join(DATA, *p)


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
    os.replace(tmp, p)


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def bootstrap():
    """data/ が無ければ defaults/ から複製する."""
    for d in ("characters", "state", "log", "images"):
        os.makedirs(dpath(d), exist_ok=True)
    for name in ("params.json", "actions.json", "world.json", "minigames.json"):
        if not os.path.exists(dpath(name)):
            shutil.copyfile(os.path.join(DEFAULTS, name), dpath(name))
    if not glob.glob(dpath("characters", "*.json")):
        for f in glob.glob(os.path.join(DEFAULTS, "characters", "*.json")):
            shutil.copy(f, dpath("characters"))


def load_settings():
    return deep_merge(load(os.path.join(DEFAULTS, "settings.json"), {}),
                      load(dpath("settings.json"), {}))


def load_characters():
    chars = {}
    for f in sorted(glob.glob(dpath("characters", "*.json"))):
        c = load(f)
        if c and c.get("id"):
            chars[c["id"]] = c
    return chars


def save_character(c):
    save(dpath("characters", c["id"] + ".json"), c)


def delete_character(cid):
    p = dpath("characters", cid + ".json")
    if os.path.exists(p):
        os.remove(p)
