ID = "20261128_back_to_work"
DESC = "11/28 14:33 に画面が途切れて職場から帰った扱いを、職場にいたままに戻す"
UNTIL = 1795874400
T = 1795844002.4177353


def apply(ctx):
    for w in ctx.worlds():
        path = ctx.store.dpath("worlds", w, "player.json")
        ps = ctx.store.load(path, None) or {}
        p = ps.get("presence") or {}
        ll = p.get("last_left") or {}
        if p.get("mode") != "none" or p.get("pos") != "home:me" or ll.get("mode") != "gone" or abs(ll.get("t", 0) - T) > 2:
            continue
        for k in ("solo", "place", "job", "task", "travel", "left", "work_contacts", "with"):
            p.pop(k, None)
        p.update({"mode": "work", "since": 1795830423.1973794, "pos": "office", "arrived": T})
        ctx.store.save(path, ps)
        return "職場にいる形に戻した（14:33 から）"
    return None
