"""セリフ中の一人称・二人称を置換用の目印に変える (一度だけ実行する移行用スクリプト).

    python tools/convert_pronouns.py [--dry-run]

- 一人称 (私 / わたし / あたし / ボク / わたくし) → {fp}
  内気の言いよどみ「わ、私」→ {fp_st} (固定していないときはプリセットの言いよどみ形になる)
  「私的」「私服」のような熟語は変えない
- 相手を直接呼ぶ「あなた」「あんた」→ {call} (ナレーション（（…））は変えない)
- 性格プリセットには first_person (と first_person_stutter) を書き込む

対象: defaults/personas/*.json, defaults/actions.json, defaults/minigames.json
"""
import glob
import io
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(BASE, "defaults")

FIRST_PERSON = {
    "teinei": "私", "osananajimi": "あたし", "aneki": "私", "ottori": "わたし", "ojousama": "わたくし",
    "kedakai": "私", "tsundere": "私", "cool": "私", "mukuchi": "私", "jimuteki": "私", "otokomae": "私",
    "genki": "わたし", "tenshin": "わたし", "uchiki": "私", "boyish": "ボク", "amaenbo": "わたし",
}
STUTTER = {"uchiki": "わ、私"}
NOT_PRONOUN = r"(?!的|服|物|立|用|事|語|有|欲|設|宅|室|信|生活|鉄)"
FP_RE = re.compile(r"(?:わたくし|わたし|あたし|ボク|私)" + NOT_PRONOUN)
SP_RE = re.compile(r"あなた|あんた")


def convert(text, stutter=None):
    n_fp = n_sp = 0
    if stutter and stutter in text:
        n_fp += text.count(stutter)
        text = text.replace(stutter, "{fp_st}")
    text, k = FP_RE.subn("{fp}", text)
    n_fp += k
    if not text.startswith("（"):
        text, k = SP_RE.subn("{call}", text)
        n_sp += k
    return text, n_fp, n_sp


def main():
    dry = "--dry-run" in sys.argv
    total = {}
    for f in sorted(glob.glob(os.path.join(D, "personas", "*.json"))):
        p = json.load(io.open(f, encoding="utf-8"))
        nf = ns = 0
        for k, v in p["lines"].items():
            out = []
            for t in v:
                t2, a, b = convert(t, STUTTER.get(p["id"]))
                nf, ns = nf + a, ns + b
                out.append(t2)
            p["lines"][k] = out
        # first_person を player_call の直後に入れる
        q = {}
        for k, v in p.items():
            if k == "lines":
                continue
            q[k] = v
            if k == "player_call":
                q["first_person"] = FIRST_PERSON.get(p["id"], "私")
                if p["id"] in STUTTER:
                    q["first_person_stutter"] = STUTTER[p["id"]]
        q.setdefault("first_person", FIRST_PERSON.get(p["id"], "私"))
        q["lines"] = p["lines"]
        total[p["id"]] = (nf, ns)
        if not dry:
            io.open(f, "w", encoding="utf-8", newline="\n").write(json.dumps(q, ensure_ascii=False, indent=1) + "\n")
    for name in ("actions.json", "minigames.json"):
        f = os.path.join(D, name)
        d = json.load(io.open(f, encoding="utf-8"))
        nf = ns = 0
        for a in d:
            groups = [a.get("reactions") or []] if name == "actions.json" else list((a.get("lines") or {}).values())
            for g in groups:
                for r in g:
                    r["text"], x, y = convert(r.get("text", ""))
                    nf, ns = nf + x, ns + y
        total["(共通) " + name] = (nf, ns)
        if not dry:
            io.open(f, "w", encoding="utf-8", newline="\n").write(json.dumps(d, ensure_ascii=False, indent=1) + "\n")
    for k, (a, b) in total.items():
        print("%-26s 一人称 %3d / 二人称 %3d" % (k, a, b))
    print("(dry-run)" if dry else "変換しました")


if __name__ == "__main__":
    main()
