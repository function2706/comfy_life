"""かな → ローマ字の打ち方 (タイピングの内職). 一つのかなに複数の打ち方を受け付ける.

- shi/si・tsu/tu・chi/ti・fu/hu・ji/zi・じゃ ja/zya/jya・しゃ sha/sya・ちゃ cha/tya/cya など (TABLE).
- 「ん」: nn・xn. 次が母音・や行・な行・「ん」でなく, 末尾でもなければ n 一つでもよい.
- 小さい字は単独でも打てる (xa/la・xya/lya・xtu/ltu/xtsu/ltsu など). 「きゃ」は kya のほか kixya とも打てる.
- 「っ」: xtu/ltu/xtsu/ltsu, または次のかなの子音を重ねる (っか kka・っち cchi/tti).
- 「ー」は -. 数字・記号はそのまま (全角は半角にして) 打つ. 空白は打たない (読みからは除く).
判定 (accepts / complete) は, 打った文字列が読みのどれかの打ち方の頭 (またはまるごと) になっているか.
画面の側 (static/puzzles.js の typing 部分) にも同じ表と同じ判定がある (表を変えたら両方).
"""
import unicodedata

TABLE = {
    "あ": ["a"], "い": ["i", "yi"], "う": ["u", "wu", "whu"], "え": ["e"], "お": ["o"],
    "か": ["ka", "ca"], "き": ["ki"], "く": ["ku", "cu", "qu"], "け": ["ke"], "こ": ["ko", "co"],
    "さ": ["sa"], "し": ["shi", "si", "ci"], "す": ["su"], "せ": ["se", "ce"], "そ": ["so"],
    "た": ["ta"], "ち": ["chi", "ti"], "つ": ["tsu", "tu"], "て": ["te"], "と": ["to"],
    "な": ["na"], "に": ["ni"], "ぬ": ["nu"], "ね": ["ne"], "の": ["no"],
    "は": ["ha"], "ひ": ["hi"], "ふ": ["fu", "hu"], "へ": ["he"], "ほ": ["ho"],
    "ま": ["ma"], "み": ["mi"], "む": ["mu"], "め": ["me"], "も": ["mo"],
    "や": ["ya"], "ゆ": ["yu"], "よ": ["yo"],
    "ら": ["ra"], "り": ["ri"], "る": ["ru"], "れ": ["re"], "ろ": ["ro"],
    "わ": ["wa"], "を": ["wo"],
    "が": ["ga"], "ぎ": ["gi"], "ぐ": ["gu"], "げ": ["ge"], "ご": ["go"],
    "ざ": ["za"], "じ": ["ji", "zi"], "ず": ["zu"], "ぜ": ["ze"], "ぞ": ["zo"],
    "だ": ["da"], "ぢ": ["di"], "づ": ["du"], "で": ["de"], "ど": ["do"],
    "ば": ["ba"], "び": ["bi"], "ぶ": ["bu"], "べ": ["be"], "ぼ": ["bo"],
    "ぱ": ["pa"], "ぴ": ["pi"], "ぷ": ["pu"], "ぺ": ["pe"], "ぽ": ["po"],
    "ゔ": ["vu"],
    "ぁ": ["xa", "la"], "ぃ": ["xi", "li"], "ぅ": ["xu", "lu"], "ぇ": ["xe", "le"], "ぉ": ["xo", "lo"],
    "ゃ": ["xya", "lya"], "ゅ": ["xyu", "lyu"], "ょ": ["xyo", "lyo"], "ゎ": ["xwa", "lwa"],
    "っ": ["xtu", "ltu", "xtsu", "ltsu"],
    "きゃ": ["kya"], "きゅ": ["kyu"], "きょ": ["kyo"], "きぇ": ["kye"],
    "しゃ": ["sha", "sya"], "しゅ": ["shu", "syu"], "しょ": ["sho", "syo"], "しぇ": ["she", "sye"],
    "ちゃ": ["cha", "tya", "cya"], "ちゅ": ["chu", "tyu", "cyu"], "ちょ": ["cho", "tyo", "cyo"], "ちぇ": ["che", "tye", "cye"],
    "にゃ": ["nya"], "にゅ": ["nyu"], "にょ": ["nyo"], "にぇ": ["nye"],
    "ひゃ": ["hya"], "ひゅ": ["hyu"], "ひょ": ["hyo"],
    "みゃ": ["mya"], "みゅ": ["myu"], "みょ": ["myo"],
    "りゃ": ["rya"], "りゅ": ["ryu"], "りょ": ["ryo"],
    "ぎゃ": ["gya"], "ぎゅ": ["gyu"], "ぎょ": ["gyo"],
    "じゃ": ["ja", "zya", "jya"], "じゅ": ["ju", "zyu", "jyu"], "じょ": ["jo", "zyo", "jyo"], "じぇ": ["je", "zye", "jye"],
    "ぢゃ": ["dya"], "ぢゅ": ["dyu"], "ぢょ": ["dyo"],
    "びゃ": ["bya"], "びゅ": ["byu"], "びょ": ["byo"],
    "ぴゃ": ["pya"], "ぴゅ": ["pyu"], "ぴょ": ["pyo"],
    "ふぁ": ["fa"], "ふぃ": ["fi"], "ふぇ": ["fe"], "ふぉ": ["fo"],
    "てぃ": ["thi"], "でぃ": ["dhi"], "でゅ": ["dhu"], "とぅ": ["twu"], "どぅ": ["dwu"],
    "うぃ": ["wi"], "うぇ": ["we"], "いぇ": ["ye"], "ゔぁ": ["va"], "ゔぃ": ["vi"], "ゔぇ": ["ve"], "ゔぉ": ["vo"],
    "ー": ["-"], "、": [","], "。": ["."], "・": ["/"], "「": ["["], "」": ["]"], "〜": ["~"],
}
VOWELS = "aiueo"


def normalize(yomi):
    """読みを打つ文字の並びに: カタカナはひらがな, 全角の英数記号は半角, 英字は小文字, 空白は除く."""
    out = []
    for ch in yomi or "":
        if ch in (" ", "　"):
            continue
        if ch in TABLE:
            out.append(ch)
            continue
        if "ァ" <= ch <= "ヶ":
            ch = chr(ord(ch) - 0x60)
        elif ch not in TABLE:
            ch = unicodedata.normalize("NFKC", ch).lower()
        out.append(ch)
    return "".join(out)


def options(kana, i):
    """読みの i 文字目からの打ち方 [(ローマ字, 進むかなの数)]."""
    ch = kana[i]
    out = []
    two = kana[i:i + 2]
    if len(two) == 2 and two in TABLE:
        out += [(r, 2) for r in TABLE[two]]
    if ch == "ん":
        nxt = options(kana, i + 1) if i + 1 < len(kana) else []
        if nxt and not any(r[0] in VOWELS + "yn" for r, _ in nxt):
            out.append(("n", 1))
        return out + [("nn", 1), ("xn", 1)]
    if ch == "っ":
        if i + 1 < len(kana) and kana[i + 1] != "っ":       # 子音を重ねる (見本は次のかなのいちばん素直な打ち方の頭)
            heads = []
            for r, _ in options(kana, i + 1):
                if r[0] not in VOWELS + "n" and r[0].isalpha() and r[0] not in heads:
                    heads.append(r[0])
            out += [(c, 1) for c in heads]
        return out + [(r, 1) for r in TABLE["っ"]]
    if ch in TABLE:
        return out + [(r, 1) for r in TABLE[ch]]
    return [(ch, 1)]                    # 数字・記号などはそのまま


def _match(kana, typed, full):
    n, m = len(kana), len(typed)
    memo = {}

    def go(i, j):
        if j == m:
            return i == n if full else True
        if i == n:
            return False
        key = (i, j)
        if key in memo:
            return memo[key]
        ok = False
        for r, k in options(kana, i):
            seg = typed[j:j + len(r)]
            if j + len(r) <= m:
                if seg == r and go(i + k, j + len(r)):
                    ok = True
                    break
            elif r.startswith(seg) and not full:      # 打ちかけ (このかなの途中まで)
                ok = True
                break
        memo[key] = ok
        return ok
    return go(0, 0)


def accepts(kana, typed):
    """typed が読みのどれかの打ち方の頭になっているか."""
    return _match(kana, typed, False)


def complete(kana, typed):
    """typed が読みをまるごと打ち終えているか."""
    return _match(kana, typed, True)


def replay(kana, keys):
    """押したキーの並びを順に当てる: (受け付けた文字列, 打ち間違いの数). 受け付けないキーは間違いとして数え, 入れない."""
    typed, miss = "", 0
    for k in keys:
        k = k.lower()
        if accepts(kana, typed + k):
            typed += k
        else:
            miss += 1
    return typed, miss


def guide(kana, typed=""):
    """見本の打ち方 (打った分に続けて, いちばん素直な打ち方). 打った分が合っていなければ None."""
    n = len(kana)

    def go(i, j):
        if i == n:
            return "" if j >= len(typed) else None
        for r, k in options(kana, i):
            if j < len(typed):
                seg = typed[j:j + len(r)]
                if not (r.startswith(seg) if j + len(r) > len(typed) else seg == r):
                    continue
            rest = go(i + k, j + len(r))
            if rest is not None:
                return r + rest
        return None
    return go(0, 0)


def typeable(yomi):
    """読みが打てるか (表に無い字が混ざっていないか)."""
    kana = normalize(yomi)
    for ch in kana:
        if ch in TABLE or ch == "ん":
            continue
        if not (ch.isascii() and ch.isprintable()):
            return False
    return bool(kana) and guide(kana) is not None
