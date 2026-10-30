"""反応・セリフのキー (性格プリセットでセリフを差し替えるときの目印).

コマンドの反応は "<コマンドid>.<キー>", ミニゲームのセリフは "mg.<ゲームid>.<場面>.<キー>",
キャラからの働きかけは "ap.<働きかけid>.<場面>" (場面 = call / accept / later / ignore / busy).
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


AP_SCENES = (("call", "話しかける"), ("accept", "応じた"), ("later", "あとで"), ("ignore", "返事なし"),
             ("busy", "返事なし (作業中)"))


def approach_text(a, scene):
    """働きかけの場面ごとの元のセリフ (無い場面は空)."""
    if scene == "call":
        return a.get("text", "")
    if scene == "busy":
        return (a.get("ignore") or {}).get("busy_text", "")
    return (a.get(scene) or {}).get("text", "")


def all_keys(actions, minigames, approaches=()):
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
    for a in approaches or ():
        for sc, label in AP_SCENES:
            t = approach_text(a, sc)
            if t:     # セリフが無い場面 (応じたらコマンドに切り替わるだけ, など) は差し替えない
                out["ap.%s.%s" % (a["id"], sc)] = {"scene": "働きかけ「%s」/ %s" % (a.get("label", a["id"]), label),
                                                    "when": a.get("when", ""), "text": t}
    from .chat import LINES as CHAT_LINES, SCENE_LABEL as CHAT_SCENES     # メッセージアプリの返信 (種類 x 状況)
    for k, t in CHAT_LINES.items():
        out[k] = {"scene": "メッセージの返信 / %s" % CHAT_SCENES[k.split(".", 1)[1]], "when": "", "text": t}
    from .msgreply import LINES as MR_LINES, SCENE_LABEL as MR_SCENES     # メッセージへの返事 (選んだ返事 x 受け取り方)
    for k, t in MR_LINES.items():
        out[k] = {"scene": "メッセージの返事 / %s" % MR_SCENES[k], "when": "", "text": t}
    from .nori import LINES as NORI_LINES, SCENE_LABEL as NORI_SCENES     # メッセージのやりとりのノリが下がって切り上げる
    for k, t in NORI_LINES.items():
        out[k] = {"scene": "メッセージの返信 / %s" % NORI_SCENES[k.split(".", 1)[1]], "when": "", "text": t}
    from .posing import LINES as PO_LINES, SCENE_LABEL as PO_SCENES     # 相手からのポーズ・見せて・持ちかけ・感想への返し
    for k, t in PO_LINES.items():
        out[k] = {"scene": "ポーズ・見せて / %s" % PO_SCENES[k], "when": "", "text": t}
    from .home import LINES as HOME_LINES, SCENE_LABEL as HOME_SCENES     # 家の様子への反応 (招いた相手・同居相手)
    for k, t in HOME_LINES.items():
        out[k] = {"scene": "家の様子 / %s" % HOME_SCENES[k], "when": "", "text": t}
    from .places import LINES as DROP_LINES, SCENE_LABEL as DROP_SCENES     # 約束なしに家を訪ねたとき
    for k, t in DROP_LINES.items():
        out[k] = {"scene": "訪問 / %s" % DROP_SCENES[k].split(" / ", 1)[1], "when": "", "text": t}
    from .street import LINES as ENC_LINES     # 出先でのばったり (声をかけられる・立ち話・断られる)
    for k, t in ENC_LINES.items():
        out[k] = {"scene": "出先でのばったり / %s" % {"enc.call.first": "知らない人が声をかけてくる", "enc.call.again": "顔なじみが声をかけてくる",
                                                   "enc.call.known": "知り合いが声をかけてくる", "enc.chat": "立ち話",
                                                   "enc.decline": "急いでいると断られた",
                                                   "enc.join.invite": "立ち話のあと, 一緒に過ごそうと誘ってくる",
                                                   "enc.join.yes": "一緒に過ごそうと誘ったら, 応じた",
                                                   "enc.join.no": "一緒に過ごそうと誘ったら, 断られた"}[k], "when": "", "text": t}
    return out
