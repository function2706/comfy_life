# -*- coding: utf-8 -*-
"""一度きり: 人違い (A20) のセリフを全性格に足す. chat.apology_wrong / apologize.apology_wrong / chat.thanks_wrong / thank.thanks_wrong."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "defaults", "personas")

# (謝ったのが、ほかの人とのことだった, お礼を言ったのが、ほかの人がしてくれたことだった)
LINES = {
    "amaenbo": ("え……それ、{fp}じゃないよ？ 誰と間違えてるの……？", "それ、{fp}じゃないよ……。誰にしてもらったの？"),
    "aneki": ("それ、{fp}じゃないわよ。誰かと間違えてない？", "それをしたのは{fp}じゃないわね。誰にしてもらったの？"),
    "boyish": ("それ、{fp}じゃなくない？ 誰の話してんの", "それ、{fp}じゃないよ。誰かと勘違いしてない？"),
    "byoujaku": ("それ……{fp}じゃないよ。誰かと、間違えてない……？", "それ、{fp}じゃないの……。ほかの人に、してもらったんだね"),
    "cool": ("……それ、{fp}じゃない。誰の話？", "……それ、{fp}じゃない"),
    "fushigi": ("それは{fp}の覚えにない話だよ。別の誰かとのことじゃない？", "それをしたのは、{fp}じゃない誰かだね"),
    "genki": ("え、それ{fp}じゃないよ！ 誰と間違えてるの？", "え、それ{fp}じゃないよ？ ほかの誰かでしょ"),
    "hikutsu": ("え……それ、{fp}じゃない、です……。ほかの人と、間違えてませんか……", "それ……{fp}じゃ、ないです……。{fp}、そんなことできてないので……"),
    "hitonatsukko": ("あれ、それ{fp}じゃないよ？ 誰かと間違えてない？", "それ、{fp}じゃないって。誰にしてもらったの？"),
    "itazura": ("それ、{fp}じゃないよね？ ふーん、誰とのことかな", "それ{fp}じゃないけど？ 誰にしてもらったのか、あとで聞かせてね"),
    "jimuteki": ("それは{fp}との件ではないわね。相手を取り違えているわ", "それをしたのは{fp}ではないわ。相手を確かめて"),
    "kedakai": ("それは{fp}とのことではないわね。どなたと取り違えているのかしら", "それは{fp}ではないわ。お礼を言う相手を間違えているわよ"),
    "mukuchi": ("……それ、{fp}じゃない", "……{fp}は、してない"),
    "ojousama": ("まぁ、それは{fp}とのことじゃないわ。どなたと間違えているの？", "それをしたのは{fp}じゃないわ。どなたにしてもらったのかしら"),
    "osananajimi": ("それ、{fp}じゃないでしょ。誰と間違えてんの", "それ、{fp}じゃないって。誰にしてもらったのよ"),
    "otokomae": ("それは{fp}じゃない。誰と取り違えてる？", "それをしたのは{fp}じゃないな。礼なら本人に言ってやれ"),
    "ottori": ("あら、それは{fp}じゃないわよぉ。誰かと間違えてない？", "それをしてくれたのは、{fp}じゃないわねぇ"),
    "rakuten": ("え、それ{fp}じゃないよ。誰かと間違えてない？", "それ、{fp}じゃないって。誰かほかの人じゃない？"),
    "rikejo": ("その件に、{fp}は関わっていない。ほかの人の記憶と混ざってる", "それをしたのは{fp}じゃない。相手を取り違えてるね"),
    "sadist": ("それ、{fp}じゃないわよ。誰と間違えたのか、ちゃんと言いなさい", "{fp}じゃない誰かにしてもらったのね。へえ、そう"),
    "seijitsu": ("え、それは{fp}じゃないですよ。誰かと間違えていませんか", "それ、{fp}じゃないです。ほかの人にしてもらったんですね"),
    "shikkari": ("それは{fp}じゃないぞ。誰と間違えてるんだ", "それをしたのは{fp}じゃない。礼を言う相手が違うぞ"),
    "teinei": ("それ、{fp}ではないですよね。どなたかと間違えていませんか", "それは{fp}ではないです。どなたかにしていただいたんですね"),
    "tenshin": ("え、それ{fp}じゃないよ？ 誰とのこと？", "それ、{fp}じゃないよ。誰がしてくれたの？"),
    "tsundere": ("は？ それ{fp}じゃないんだけど。誰と間違えてるのよ", "それ、{fp}じゃないわよ。……誰にしてもらったの"),
    "uchiki": ("え……それ、{fp}じゃ、ないです……。どなたかと……", "それ……{fp}じゃないです……"),
    "yareyare": ("それ、{fp}じゃないですよ。誰と間違えてるんですか", "それは{fp}じゃないですね。お礼はその人に言ってあげてください"),
}


def insert_after(raw, anchor, key, text):
    """anchor のキーの値 (リスト) のすぐあとに, key: [text] を差し込む (手で整えた形を崩さないよう, 文字列のまま)."""
    nl = "\r\n" if "\r\n" in raw else "\n"
    i = raw.index(nl + '  "%s": [' % anchor)
    j = raw.index(nl + "  ]", i) + len(nl) + 3
    add = "," + nl + "  %s: [" % json.dumps(key, ensure_ascii=False) + nl + "   %s" % json.dumps(text, ensure_ascii=False) + nl + "  ]"
    return raw[:j] + add + raw[j:]


def main():
    n = 0
    for f in sorted(os.listdir(D)):
        if not f.endswith(".json"):
            continue
        pid = f[:-5]
        path = os.path.join(D, f)
        raw = open(path, encoding="utf-8", newline="").read()
        if '"chat.apology_wrong"' in raw:
            continue
        ap, th = LINES[pid]
        raw = insert_after(raw, "chat.apology_unminded", "chat.apology_wrong", "📱『%s』" % ap)
        raw = insert_after(raw, "chat.thanks_what", "chat.thanks_wrong", "📱『%s』" % th)
        raw = insert_after(raw, "apologize.apology_unminded", "apologize.apology_wrong", ap)
        raw = insert_after(raw, "thank.thanks_what", "thank.thanks_wrong", th)
        d = json.loads(raw)
        assert all(k in json.dumps(d, ensure_ascii=False) for k in ("chat.apology_wrong", "thank.thanks_wrong"))
        open(path, "w", encoding="utf-8", newline="").write(raw)
        n += 4
    print("足した行:", n)


if __name__ == "__main__":
    main()
