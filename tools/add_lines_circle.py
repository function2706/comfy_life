"""性格別のセリフ (A34 段 1): 誘った時間に, 知り合いと会う予定がある (chat.appoint_plan. {who} は 友達 / 職場の人 / 上司 / 家族).

    python tools/add_lines_circle.py        # defaults/personas/*.json に足す (もうあれば何もしない)
"""
import glob
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = "chat.appoint_plan"
LINES = {
    "amaenbo": "📱『その時間は{who}と会う約束してるの……ごめんね、{call}。別の日じゃだめ？』",
    "aneki": "📱『その時間は{who}と先に約束しちゃってるのよ。悪いわね、また今度』",
    "boyish": "📱『あー、その時間は{who}と約束あるんだ。ごめん！』",
    "byoujaku": "📱『その時間は{who}と会うことになってて……ごめんね』",
    "cool": "📱『その時間は{who}と約束がある。ごめん』",
    "fushigi": "📱『その時間は、{who}と会うことになってるの。ごめんね』",
    "genki": "📱『その時間、{who}と約束しちゃってるんだ……ごめんね！』",
    "hikutsu": "📱『すみません……その時間は{who}と約束があって……』",
    "hitonatsukko": "📱『ごめん！ その時間は{who}と約束あるんだー』",
    "itazura": "📱『その時間は{who}と先約なの。ごめんね〜』",
    "jimuteki": "📱『その時間は{who}との予定が先に入っている。別の日程なら調整する』",
    "kedakai": "📱『その時間は{who}との先約があるの。別の日になさい』",
    "mukuchi": "📱『……その時間、{who}と約束。ごめん』",
    "ojousama": "📱『その時間は{who}とお約束があるの……ごめんなさい』",
    "osananajimi": "📱『その時間は{who}と約束あんの。ごめんね』",
    "otokomae": "📱『その時間は{who}と約束があるんだ。すまない』",
    "ottori": "📱『その時間は{who}と約束しているのよぉ。ごめんなさいね』",
    "rakuten": "📱『その時間は{who}と約束しちゃってるんだ。ごめん』",
    "rikejo": "📱『その時間は{who}と約束がある。ごめん、別の日なら』",
    "sadist": "📱『その時間は{who}と先約があるの。残念だったわね』",
    "seijitsu": "📱『その時間は{who}と約束があって……すみません』",
    "shikkari": "📱『その時間は{who}と約束がある。すまない』",
    "teinei": "📱『その時間は{who}と約束があって……ごめんなさい』",
    "tenshin": "📱『その時間は{who}と約束しちゃってるの。ごめんね』",
    "tsundere": "📱『その時間は{who}と約束あるのよ。……ごめん』",
    "uchiki": "📱『あの……その時間は{who}と約束があって……ごめんなさい……』",
    "yareyare": "📱『その時間は{who}と約束しちゃってて。ごめんなさい』",
}


def main():
    d = os.path.join(ROOT, "defaults", "personas")
    files = sorted(glob.glob(os.path.join(d, "*.json")))
    assert len(files) == len(LINES) == 27, (len(files), len(LINES))
    n = 0
    for f in files:
        src = io.open(f, encoding="utf-8", newline="").read()
        p = json.loads(src)
        if KEY in p["lines"]:
            continue
        tail = "\n }\n}"                      # "lines" が最後の塊: 文字として差し込む (ファイルの書式を保つ)
        at = src.rindex(tail)
        assert list(p)[-1] == "lines", f
        out = src[:at] + ',\n  %s: [\n   %s\n  ]' % (json.dumps(KEY), json.dumps(LINES[p["id"]], ensure_ascii=False)) + src[at:]
        q = json.loads(out)
        assert q["lines"][KEY] == [LINES[p["id"]]] and len(q["lines"]) == len(p["lines"]) + 1
        io.open(f, "w", encoding="utf-8", newline="").write(out)
        n += 1
    print("ok", n, "性格")


if __name__ == "__main__":
    main()
