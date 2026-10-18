"""性格プリセット (defaults/personas/*.json または指定ファイル) の検査.

    python tools/check_persona.py [ファイル ...]

- 全キーがそろっているか / 余計なキーがないか
- 置換文字 {..} は元のセリフにあるもの + 共通のもの ({call} {name} {player} {location} {activity_label} {time}) だけか
- 元がナレーション（（…））/ 📱メッセージなら, 同じ書式か
- 空のセリフ・長すぎるセリフがないか
"""
import glob
import io
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from core.keys import all_keys  # noqa: E402

COMMON = {"call", "name", "player", "location", "activity_label", "time", "fp", "fp_st"}
REQUIRED_FIELDS = ("id", "name", "desc", "persona", "player_call", "lines")


def check(path, keys):
    errs, warns = [], []
    try:
        p = json.load(io.open(path, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return ["JSON として読めません: %s" % e], []
    for f in REQUIRED_FIELDS:
        if not p.get(f):
            errs.append("項目 %s がありません" % f)
    lines = p.get("lines") or {}
    missing = [k for k in keys if k not in lines]
    extra = [k for k in lines if k not in keys]
    if missing:
        errs.append("足りないキー %d 個: %s" % (len(missing), ", ".join(missing[:15]) + (" ..." if len(missing) > 15 else "")))
    if extra:
        errs.append("存在しないキー %d 個: %s" % (len(extra), ", ".join(extra[:15])))
    for k, texts in lines.items():
        if k not in keys:
            continue
        if isinstance(texts, str):
            texts = [texts]
        if not texts:
            errs.append("%s: セリフが空" % k)
            continue
        orig = keys[k]["text"]
        allowed = COMMON | set(re.findall(r"\{(\w+)\}", orig))
        for t in texts:
            if not t.strip():
                errs.append("%s: 空のセリフ" % k)
            bad = set(re.findall(r"\{(\w+)\}", t)) - allowed
            if bad:
                errs.append("%s: 使えない置換文字 %s 「%s」" % (k, ",".join("{%s}" % b for b in bad), t))
            if orig.startswith("（") != t.startswith("（"):
                errs.append("%s: ナレーション（（…））かどうかが元と違う「%s」" % (k, t))
            if orig.startswith("📱") != t.startswith("📱"):
                errs.append("%s: 📱メッセージかどうかが元と違う「%s」" % (k, t))
            if len(t) > 90:
                warns.append("%s: 長め (%d 字)" % (k, len(t)))
    return errs, warns


def main():
    load = lambda name: json.load(io.open(os.path.join(BASE, "defaults", name), encoding="utf-8"))  # noqa: E731
    keys = all_keys(load("actions.json"), load("minigames.json"), load("approaches.json"))
    files = sys.argv[1:] or sorted(glob.glob(os.path.join(BASE, "defaults", "personas", "*.json")))
    bad = 0
    for f in files:
        errs, warns = check(f, keys)
        n = len((json.load(io.open(f, encoding="utf-8")).get("lines") or {})) if not errs or "JSON" not in errs[0] else 0
        print("%s: %s (%d キー, 警告 %d)" % (os.path.basename(f), "NG" if errs else "OK", n, len(warns)))
        for e in errs[:40]:
            print("  ✗", e)
        for w in warns[:5]:
            print("  △", w)
        bad += bool(errs)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
