# -*- coding: utf-8 -*-
"""性格セリフの検査: 現実の会話ではまず見ない, 型どおりの言い回し (アニメ・マンガ的な口癖・決め台詞・擬音) を性格ごとに数える.
頻度の問題 (語尾の傾向・「……」の多さ・話し言葉の自然などもり) は数えない. 数えるのは:
- メッセージ (📱) の中のどもり (打つ文字はどもらない)
- 口に出す擬音・幼児語 (ぷいっ・ふにゃ・んく・ぷはっ・じーっ・けほっ・むー・ふふん・へへん・お手々 など. ナレーション （） の中は数えない)
- お約束の決め台詞 (ツンデレ定型・悪役の捨て台詞・「〜だと……！？」・キザな「ふっ、」・お嬢様言葉 など)
- 感情や体を機械の言葉で言う (処理速度・上昇中・完了・記録しておく・生理反応 など)
- 話し言葉の文末の「♪」

    python tools/check_stock_phrases.py [--show 型の名前] [--persona id]
"""
import argparse
import glob
import io
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PATTERNS = {
    "📱どもり": (r"(^|[『…、。！？ ])([ぁ-んァ-ン])、\2", "chat"),
    "擬音": (r"ぷいっ|ふにゃ|んく[、。]|ぷはっ|ぷはー|こく、こく|ごくごく|じーっ[。！]|けほっ|ぽっぽ|にかっ|(^|[『…、。 ])む[ぅー][。！、…』]|"
             r"(^|[『…、。 ])むっ[。、]|(^|[『…、。 ])ぶー[。！、…』]|ふふん|へへん|(^|[『…、。 ])ふんっ|(^|[『…、。 ])ふ、ふん|お手々|うわーん|えーん|あわわ|"
             r"(^|[『…、。 ])ひゃっ", "speech"),
    "決め台詞": (r"なんだからね|勘違いしないでよね|べ、別に|覚えてなさい|覚えてなよ|覚えておきなさい|首を洗って|百年早い|十年早い|光栄に思いなさい|おしおき|"
               r"だと……[！!]?[？?]|(^|[『…、。 ])ふっ、|褒めても何も出ない|ぶっとばす|のくせに生意気|ですわ|ですの[。！？』]|よくてよ|ごきげんよう|くださいまし|"
               r"からかうのは.{0,4}役目|そういうのは、反則", "speech"),
    "機械の言葉": (r"処理速度|上昇中|低下中|補給、完了|完了。$|記録しておく|報告は以上|事実の報告|生理反応|室温のせい|体温調節だから|受理する|入力。|出力して|"
                 r"稼働を|再現性あり", "speech"),
    "話し言葉の♪": (r"♪", "speech_only"),
}
NARR = re.compile(r"（[^）]*）|\([^)]*\)")


def lines_of(d):
    for k, v in (d.get("lines") or {}).items():
        for t in (v if isinstance(v, list) else [v]):
            yield k, t


def hits(t, name):
    pat, where = PATTERNS[name]
    chat = t.startswith("📱")
    if where == "chat" and not chat:
        return False
    if where == "speech_only" and chat:
        return False
    body = NARR.sub("", t)
    return bool(re.search(pat, body))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show")
    ap.add_argument("--persona")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    total = {n: 0 for n in PATTERNS}
    print("%-13s %5s " % ("性格", "行") + " ".join("%-8s" % n for n in PATTERNS))
    for f in sorted(glob.glob(os.path.join(ROOT, "defaults", "personas", "*.json"))):
        pid = os.path.basename(f)[:-5]
        if a.persona and pid != a.persona:
            continue
        d = json.load(io.open(f, encoding="utf-8"))
        L = list(lines_of(d))
        c = {n: [(k, t) for k, t in L if hits(t, n)] for n in PATTERNS}
        for n in PATTERNS:
            total[n] += len(c[n])
        print("%-13s %5d " % (pid, len(L)) + " ".join("%-8d" % len(c[n]) for n in PATTERNS))
        if a.show:
            for k, t in c.get(a.show, []):
                print("    %s | %s" % (k, t))
    print("%-13s %5s " % ("合計", "") + " ".join("%-8d" % total[n] for n in PATTERNS))


if __name__ == "__main__":
    main()
