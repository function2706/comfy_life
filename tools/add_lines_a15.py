# -*- coding: utf-8 -*-
"""性格別セリフを足す (残件 A15 の段 2〜3: あなたの返し方がいつもと違ったあとの「何かあった？」). 一度きりの取り込み用 (もう一度流しても同じ結果).

    python tools/add_lines_a15.py      # ap.msg_chat.call_changed・msgr.why.changed.bad
"""
import glob
import io
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 性格 id: (何かあった？, それを流されたときの返し)
L = {
    "amaenbo": ("{call}、なにかあった？ いつもならお返事くれるころなのに、こなかったから", "……なんにもないの？ ならいいんだけど……"),
    "aneki": ("{call}、何かあったの？ いつもと返事の調子が違うから、気になって", "……そう。何もないならいいのよ。無理はしないでね"),
    "boyish": ("{call}、なんかあった？ いつもと返事の感じが違うからさ", "……そっか。なんもないならいいんだ"),
    "byoujaku": ("{call}、何かあった？ いつもと様子が違うから、具合でも悪いのかなって", "……そっか。何もないなら、よかった"),
    "cool": ("{call}。何かあった？ いつもと違う", "……そう。気のせいならいい"),
    "fushigi": ("{call}、何かあった？ いつもの時間に、いつもの返事がこなかったから", "……ふうん。じゃあ、たまたまだったんだね"),
    "genki": ("{call}、なんかあった？ いつもと違うから、めずらしいなって！", "……そっか！ なんにもないなら、よかった"),
    "hikutsu": ("{call}、何かありましたか……？ いつもと違うので、{fp}が何かしてしまったのかと", "……そうですか。すみません、{fp}の気にしすぎでした"),
    "hitonatsukko": ("{call}、何かあった？ いつもとちょっと違うから、心配になっちゃって", "……そっか。何もないなら、安心した"),
    "itazura": ("{call}、何かあった？ 返事がいつもと違うから、ちょっと気になった", "……そっか。何もないって言うなら、信じとく"),
    "jimuteki": ("{call}、何かあったのかしら。返信がいつもの様子と違うから、確認しておきたくて", "……そう。変わりないのなら、いいわ。念のため聞いただけ"),
    "kedakai": ("{call}。何かあったの？ いつもと様子が違うようだけれど", "……そう。何もないと言うのなら、それ以上は聞かないわ"),
    "mukuchi": ("……{call}。何か、あった？ いつもと違う", "……そう。……なら、いい"),
    "ojousama": ("{call}、何かあったの？ いつもとご様子が違うから、どうなさったのかと思って", "……そう。何もないのなら、よかったわ"),
    "osananajimi": ("{call}、なんかあった？ いつもと返事が違うから、らしくないなって", "……ふうん。まあ、言いたくなったら言いなよ"),
    "otokomae": ("{call}、何かあったのか？ いつもと様子が違うようだが", "……そうか。話したくなったら、いつでも聞く"),
    "ottori": ("{call}、何かあったのかしら？ いつもと少し違うみたいだから", "……そう。なら、{fp}の思い過ごしね"),
    "rakuten": ("{call}、なんかあった？ いつもと違うから、どうしたのかなーって", "……そっか。なんもないなら、まあいいや"),
    "rikejo": ("{call}、何かあった？ 返信のパターンがいつもと違うから、気になって", "……そっか。じゃあ、たまたまのばらつきだね"),
    "sadist": ("{call}、何かあったの？ いつもと違うじゃない。言ってごらんなさい", "……そう。言わないのなら、それでいいわ"),
    "seijitsu": ("{call}、何かありましたか？ いつもとご様子が違うので、心配になって", "……そうですか。何もないのでしたら、安心しました"),
    "shikkari": ("{call}、何かあった？ いつもと様子が違うから、どうしたのかと思って", "……そうか。思い違いならいいんだ"),
    "teinei": ("{call}、何かありましたか？ いつもと少し様子が違う気がして", "……そうですか。何もないなら、よかったです"),
    "tenshin": ("{call}、なにかあったの？ いつもとちがうから、どうしたのかなって", "……そっか。なんにもないんだね"),
    "tsundere": ("{call}、何かあったの？ ……いつもと違うから、聞いてみただけ", "……そう。なら、聞かなかったことにして"),
    "uchiki": ("あの……{call}、何か、ありましたか……？ いつもと、少し違う気がして……", "……そう、ですか……。何もないなら、よかったです……"),
    "yareyare": ("{call}、何かあったんですか？ いつもと返事の感じが違うんで", "……そうですか。何もないなら、別にいいんですけど"),
}


def main():
    files = sorted(glob.glob(os.path.join(BASE, "defaults", "personas", "*.json")))
    assert len(files) == len(L) == 27, (len(files), len(L))
    done = 0
    for f in files:
        src = io.open(f, encoding="utf-8", newline="").read()
        p = json.loads(src)
        a, b = L[p["id"]]
        add = [("ap.msg_chat.call_changed", u"📱『%s』" % a), ("msgr.why.changed.bad", u"📱『%s』" % b)]
        add = [(k, v) for k, v in add if k not in p["lines"]]
        if not add:
            continue
        tail = "\n }\n}"                      # the "lines" block is the last one: insert as text (keeps the file's formatting)
        at = src.rindex(tail)
        assert list(p)[-1] == "lines", f
        ins = "".join(',\n  %s: [\n   %s\n  ]' % (json.dumps(k), json.dumps(v, ensure_ascii=False)) for k, v in add)
        out = src[:at] + ins + src[at:]
        q = json.loads(out)
        assert all(q["lines"][k] == [v] for k, v in add) and len(q["lines"]) == len(p["lines"]) + len(add)
        io.open(f, "w", encoding="utf-8", newline="").write(out)
        done += len(add)
    print("ok", len(files), "files,", done, "lines")


if __name__ == "__main__":
    main()
