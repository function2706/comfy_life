ID = "20261128_bike_home"
DESC = "経路の不具合でモール前に置かれた自転車を家に戻す"
UNTIL = 1796137200


def apply(ctx):
    n = 0
    for w in ctx.worlds():
        p = ctx.store.dpath("worlds", w, "geo.json")
        g = ctx.store.load(p, None)
        v = (g or {}).get("veh") or {}
        if v.get("bicycle") == "st:mall":
            v["bicycle"] = "home:me"
            ctx.store.save(p, g)
            n += 1
    return "家に戻した（%d 件）" % n if n else None
