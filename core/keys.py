"""反応・セリフのキー (性格プリセットでセリフを差し替えるときの目印).

コマンドの反応は "<コマンドid>.<キー>", ミニゲームのセリフは "mg.<ゲームid>.<場面>.<キー>".
キーは各項目の "key" か, 無ければ条件式から作る (同じものが並んだら _2, _3 を付ける).
"""


def cond_slug(when):
    """条件式からキーを作る (例: "free=true, mood<35" → "free_true__mood_lt_35")."""
    s = (when or "").replace(" ", "")
    if not s:
        return "default"
    for a, b in ((">=", "_ge_"), ("<=", "_le_"), ("!=", "_ne_"), (">", "_gt_"), ("<", "_lt_"), ("=", "_"),
                 ("|", "_or_"), ("&&", "__"), (",", "__")):
        s = s.replace(a, b)
    return s.lower()


def line_keys(items):
    keys, seen = [], {}
    for it in items:
        k = it.get("key") or cond_slug(it.get("when", ""))
        seen[k] = seen.get(k, 0) + 1
        keys.append(k if seen[k] == 1 else "%s_%d" % (k, seen[k]))
    return keys


def all_keys(actions, minigames):
    """全キーと, その元のセリフ・条件・場面 (セリフ集づくりの参考用)."""
    out = {}
    for a in actions:
        rs = a.get("reactions") or []
        for k, r in zip(line_keys(rs), rs):
            out["%s.%s" % (a["id"], k)] = {"scene": "コマンド「%s」" % a.get("name", a["id"]),
                                           "when": r.get("when", ""), "text": r.get("text", "")}
    for g in minigames:
        for ev, lines in (g.get("lines") or {}).items():
            for k, r in zip(line_keys(lines), lines):
                out["mg.%s.%s.%s" % (g["id"], ev, k)] = {"scene": "%s / %s" % (g.get("name", g["id"]), ev),
                                                          "when": r.get("when", ""), "text": r.get("text", "")}
    return out
