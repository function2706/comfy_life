"""既定の服 (defaults/outfits.json) の「売っている店」を, 服屋の種類ごとに振り分け直す (服屋の多様化).

    python tools/add_clothes_shops.py

何度流しても同じ結果になる (各服の places を規則から作り直す). 規則を変えたらここを直して流し直す.
- mall: 流行りの服をひととおり. 着物・振袖と, 衣装の店に回した衣装・制服は置かない (サンタ・魔女・ゴスロリは季節物・売り場として残す)
- shopping_street: 普段の服 (以前の商店街の品から, 地雷系と「きれいめ・モードだけ」の服, 衣装寄りの制服を外す)
- boutique: きれいめ・モード (よそ行き・ドレス・オフィス, 部品・アウター)
- used_clothes: 古着 (ストリート・ナチュラル・カジュアルの普段の服. 値段は 6 割. core/places.py の KIND_PRICE)
- sports_shop: スポーツ (sporty の印・水着・ジャージ・アウトドアのアウター)
- costume_shop: 衣装 (コスプレ・制服)
- kimono_shop: 和装 (浴衣・着物・振袖・甚平)
"""
import io
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(BASE, "defaults", "outfits.json")

TO_COSTUME = {"teacher", "attendant", "waitress", "barista", "chef", "doctor", "kigurumi"}
MALL_COSTUME = {"santa", "witch", "gothic"}
KIMONO = {"yukata", "kimono", "furisode", "jinbei"}
KIMONO_ONLY = {"kimono", "furisode"}
SPORTS = {"jersey", "mountain_parka", "down_jacket", "p_backpack", "p_socks", "p_rain_boots"}
ORDER = ["mall", "shopping_street", "boutique", "used_clothes", "sports_shop", "costume_shop", "kimono_shop"]


def shops(o, old):
    i, k, sl, tg = o["id"], o["kind"], o.get("slot"), set(o.get("tags") or [])
    out = set()
    if i not in KIMONO_ONLY and not (k == "costume" and i not in MALL_COSTUME) and i not in TO_COSTUME:
        out.add("mall")
    if "shopping_street" in old and i not in TO_COSTUME and "jirai" not in tg \
            and not (tg & {"mode", "elegant"} and not tg & {"casual", "natural", "sporty"}):
        out.add("shopping_street")
    if (k == "formal" and i not in KIMONO | {"wedding"}) or i == "office" or \
            (k in ("part", "outer", "casual") and sl != "lingerie" and tg & {"elegant", "mode"}):
        out.add("boutique")
    if k in ("part", "outer", "casual") and sl not in ("legwear", "lingerie") and tg & {"street", "natural", "casual"}:
        out.add("used_clothes")
    if "sporty" in tg or k == "swim" or i in SPORTS:
        out.add("sports_shop")
    if k == "costume" or i in TO_COSTUME:
        out.add("costume_shop")
    if i in KIMONO:
        out.add("kimono_shop")
    return [p for p in ORDER if p in out]


def main():
    items = json.load(io.open(PATH, encoding="utf-8"))
    for o in items:
        o["places"] = shops(o, o.get("places") or ["mall"])
    with io.open(PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("[\n" + ",\n".join(" " + json.dumps(o, ensure_ascii=False) for o in items) + "\n]\n")
    cnt = {p: sum(p in o["places"] for o in items) for p in ORDER}
    print(cnt)


if __name__ == "__main__":
    main()
