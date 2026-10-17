"""ファイル入出力とデータディレクトリの初期化."""
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


def load_personas():
    """性格プリセット. defaults/personas の上に data/personas (ユーザー編集分) を重ねる."""
    out = {}
    for d in (os.path.join(DEFAULTS, "personas"), dpath("personas")):
        for f in sorted(glob.glob(os.path.join(d, "*.json"))):
            p = load(f)
            if p and p.get("id"):
                p["_custom"] = d != os.path.join(DEFAULTS, "personas")
                out[p["id"]] = p
    return out


def save_persona(p):
    p = {k: v for k, v in p.items() if not k.startswith("_")}
    save(dpath("personas", p["id"] + ".json"), p)


def save_character(c):
    save(dpath("characters", c["id"] + ".json"), c)


def delete_character(cid):
    p = dpath("characters", cid + ".json")
    if os.path.exists(p):
        os.remove(p)
