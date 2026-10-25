"""性格プリセットのセリフの口調の精査 (機械で調べるだけ. 直さない).

    python tools/check_tone.py                     # 全性格. 内訳を出し, 一覧を data/tone_report.tsv に
    python tools/check_tone.py --out x.tsv teinei  # 性格を絞る・出力先を変える

性格ごとの決まり (RULES と, 既存の行の大多数から決める) と照らして, 外れている行を 性格・場面 (キー)・行・理由 で出す.
- 一人称の直書き: {fp} を使わず「私・わたし・あたし・ボク・わたくし」などを書いている (私服・私物などは除く).
- 呼び方: その性格の呼び方 (player_call) と違う呼び方を直書きしている (あなた・キミ・あんた・君).
- 丁寧さ: その性格の大多数 (丁寧語 / タメ口) と逆の行. 決まり (RULES の register) があればそちら.
- 使わない語尾: 例 男前は「〜わ」「〜わね」「〜かしら」「〜のよ」を使わない. 敬語を使わない性格の「です・ます」.
- お嬢様言葉: お嬢様で, 丁寧語なのに「〜わ」「〜の」「〜かしら」「〜てよ」「〜ませんこと」などが一つも無い.
- 丁寧語の性格のタメ口は, 「だよ・だね・じゃん・だろ・〜だ」のようにはっきりしたものだけ数える (短い感嘆・独り言は数えない).
- 「〜でしょう」「〜ましょう」と決まり文句 (いただきます・おじゃまします など) は丁寧語に数えない (タメ口の女性言葉でも使う).
- 共通のまま: 共通のセリフ (性格が無いときの言い方) とほぼ同じ行で, 共通の口調 (多くは丁寧語) がその性格の口調と違う (浮いている).
  共通のセリフがもともとその性格に合う口調なら, 同じでも拾わない.
ナレーション (（…）だけの行) は口調の対象にしない. 結果はあくまで候補で, 誤検出を含む (人が読んで決める).
"""
import argparse
import difflib
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from core.keys import all_keys  # noqa: E402

POLITE = re.compile(r"(です|ます|でした|ました|ません|ください|ございま)")
# 丁寧語に数えない決まり文句 (タメ口の人も言う). 「〜でしょう」「〜ましょう」はタメ口の女性言葉でも使うので丁寧語に数えない
SET_PHRASES = re.compile(r"(いただきます|ごちそうさまでした?|おじゃまします|お邪魔します|おかえりなさいませ|お待ちしてます|"
                         r"よろしくお願いします|ありがとうございま[すし]た?|おはようございます|すみません|おじゃま|お邪魔|"
                         r"待ってました|残念でした|参りました|んですって|ですって)")
CASUAL = re.compile(r"(だよ|だね|だろ|じゃん|だった|だから|だって|かな[。！？…」!?]|よね|てる[。！？…」!?よね]|ちゃう|ちゃった|なの[。！？…」!?]|"
                    r"のよ|わよ|わね|だ[。！!？?…」]|だ$|ね[。！!？?…」]|よ[。！!？?…」]|ない[。！!？?…」]|るの[。！？…」!?])")
FIRST_PERSON = re.compile(r"(わたくし|わたし|あたし|ボク|僕|俺|私)(?!服|物|立|生活|設|鉄|的)")
CALLS = {"あなた": r"あなた", "キミ": r"キミ|君(?!た|の名|子)", "あんた": r"あんた"}
FEMININE = re.compile(r"(わ[。！!？?…」]|わね|かしら|のよ|わよ)")
OJOU = re.compile(r"(わ[。！!？?…」、,♪〜～]|わ$|くて[？?]|わね|わよ|ですの|ますの|ませんの|ましたの|でしたの|ませんこと|ますこと|かしら|てよ|"
                  r"くださいまし|くださいませ|ですわ|ますわ|あそばせ|ですもの|ますもの|の[！!？?…。]|の$|なさい)")
# 丁寧語の性格で「浮いている」とみなすタメ口 (ゆるい独り言・感嘆はタメ口に数えない)
STRONG_CASUAL = re.compile(r"(だよ|だね|だろ|じゃん|だった[。！？…」!?]|だから[。！？…」!?]|だ[。！!？?」]|だ$)")
# 説明から決まる性格ごとの決まり (register: polite / casual. 無ければ大多数から決める)
RULES = {
    "aneki": {"register": "casual"}, "jimuteki": {"register": "casual"}, "kedakai": {"register": "casual"},
    "otokomae": {"register": "casual", "no_feminine": True}, "ojousama": {"register": "polite", "ojou": True},
    "teinei": {"register": "polite"}, "hikutsu": {"register": "polite"}, "uchiki": {"register": "polite"},
    "osananajimi": {"register": "casual"}, "boyish": {"register": "casual"}, "genki": {"register": "casual"},
    "amaenbo": {"register": "casual"}, "hitonatsukko": {"register": "casual"}, "itazura": {"register": "casual"},
    "tenshin": {"register": "casual"}, "tsundere": {"register": "casual"}, "sadist": {"register": "casual"},
    "cool": {"register": "casual"}, "mukuchi": {"register": "casual"},
}


def body(t):
    """口調を見る部分 (📱『…』の中. ナレーション （…） は外す)."""
    t = re.sub(r"^📱『|』$", "", t)
    return re.sub(r"（[^）]*）", "", t).strip()


def register_of(t):
    b = SET_PHRASES.sub("", body(t))
    if not b:
        return None
    if POLITE.search(b):
        return "polite"
    if CASUAL.search(b):
        return "casual"
    return None


def call_word(p):
    c = (p.get("player_call") or "").replace("{player}", "").strip()
    return c


def check(path, keys):
    p = json.load(open(path, encoding="utf-8"))
    pid = p["id"]
    rule = RULES.get(pid, {})
    lines = [(k, t) for k, v in (p.get("lines") or {}).items() for t in (v if isinstance(v, list) else [v])]
    regs = Counter(r for _, t in lines for r in [register_of(t)] if r)
    total = sum(regs.values()) or 1
    reg = rule.get("register") or ("polite" if regs["polite"] / total >= 0.7 else "casual" if regs["casual"] / total >= 0.7 else None)
    own_call = call_word(p)
    out = []
    for k, t in lines:
        b = body(t)
        if not b:
            continue
        why = []
        if FIRST_PERSON.search(b.replace("{fp}", "").replace("{fp_st}", "")):
            why.append("一人称の直書き")
        for name, pat in CALLS.items():
            if name != own_call and re.search(pat, b):
                why.append("呼び方の直書き（%s）" % name)
        r = register_of(t)
        if reg == "polite" and r == "casual" and not STRONG_CASUAL.search(body(t)):
            r = None                       # 丁寧語の人の短い感嘆・独り言 (「かわいい……！」) は浮いていない
        if reg and r and r != reg:
            why.append("丁寧さ（%sの性格に%s）" % ("丁寧語" if reg == "polite" else "タメ口", "タメ口" if r == "casual" else "丁寧語"))
        if rule.get("no_feminine") and FEMININE.search(b):
            why.append("使わない語尾（女性的な「わ・かしら・のよ」）")
        if rule.get("ojou") and r == "polite" and not OJOU.search(b) and len(b) > 8:
            why.append("お嬢様言葉が無い")
        if pid != "teinei" and k in keys:
            orig = keys[k]["text"]
            # 共通のセリフとほぼ同じで, しかも共通の口調 (丁寧語など) がこの性格の口調と違う = 浮いている
            # (語尾だけ性格に合わせて直してある行は, 似ていても拾わない)
            if orig and reg and r and r == register_of(orig) != reg \
                    and difflib.SequenceMatcher(None, body(orig), b).ratio() >= 0.85:
                why = [w for w in why if not w.startswith("丁寧さ")] + ["共通のまま"]
        for w in why:
            out.append((pid, k, t, w))
    return pid, reg, regs, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--out", default=os.path.join(BASE, "data", "tone_report.tsv"))      # data/ は git に入れない
    a = ap.parse_args()
    actions = json.load(open(os.path.join(BASE, "defaults", "actions.json"), encoding="utf-8"))
    minigames = json.load(open(os.path.join(BASE, "defaults", "minigames.json"), encoding="utf-8"))
    approaches = json.load(open(os.path.join(BASE, "defaults", "approaches.json"), encoding="utf-8"))
    keys = all_keys(actions, minigames, approaches)
    rows, per, reasons, scanned = [], Counter(), Counter(), 0
    for f in sorted(glob.glob(os.path.join(BASE, "defaults", "personas", "*.json"))):
        if a.ids and os.path.splitext(os.path.basename(f))[0] not in a.ids:
            continue
        pid, reg, regs, out = check(f, keys)
        scanned += sum(len(v) if isinstance(v, list) else 1 for v in json.load(open(f, encoding="utf-8"))["lines"].values())
        rows += out
        per[pid] = len(out)
        for _, _, _, w in out:
            reasons[re.sub(r"（.*", "", w)] += 1
        print("%-13s 口調 %-6s (丁寧語 %4d / タメ口 %4d)  引っかかり %4d" % (pid, reg or "まちまち", regs["polite"], regs["casual"], len(out)))
    by_reason = defaultdict(Counter)
    for pid, _, _, w in rows:
        by_reason[re.sub(r"（.*", "", w)][pid] += 1
    print("\n読んだ行 %d / 引っかかり %d 件 (行の重複を含む)" % (scanned, len(rows)))
    for w, n in reasons.most_common():
        print("  %-24s %4d  %s" % (w, n, " ".join("%s:%d" % x for x in by_reason[w].most_common(6))))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as fo:
        fo.write("性格\t場面\t理由\t行\n")
        for pid, k, t, w in rows:
            fo.write("%s\t%s\t%s\t%s\n" % (pid, k, w, t.replace("\t", " ").replace("\n", " ")))
    print("\n一覧: %s" % a.out)


if __name__ == "__main__":
    main()
