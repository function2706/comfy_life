# -*- coding: utf-8 -*-
"""S37: 既定の服の一覧 (defaults/outfits.json) に, 部品・アウター・一式を足す (一度だけ. 同じ id があれば足さない).

参考: loose_coupling_wc の sfw/costumes.yaml (tailor の部品・costumes のセット)・sfw/boots_setup.yaml (行き先ごとのコーデ)・
nsfw/footwear.yaml (衣装に合う靴). 使い方: python tools/add_outfits_s37.py
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "defaults", "outfits.json")
MS = ["mall", "shopping_street"]
BLUE = ["blue", "light_blue", "navy", "black", "white", "grey"]
NEUTRAL = ["black", "white", "grey", "navy", "beige", "brown", "khaki"]


def part(id_, name, icon, slot, pos, tags, price, bold=0, seasons=(), match=(), colors=(), outing=True, places=MS):
    return {"id": id_, "name": name, "icon": icon, "kind": "part", "slot": slot, "bold": bold, "outing_ok": outing,
            "seasons": list(seasons), "price": price, "places": list(places), "when": "", "pos": pos, "neg": "",
            "colors": list(colors), "match": list(match), "tags": list(tags)}


def whole(id_, name, icon, kind, pos, price, bold=0, seasons=(), tags=(), outing=False, places=("mall",), slot=None):
    o = {"id": id_, "name": name, "icon": icon, "kind": kind, "bold": bold, "outing_ok": outing, "seasons": list(seasons),
         "price": price, "places": list(places), "when": "", "pos": pos, "neg": ""}
    if slot:
        o["slot"] = slot
    if tags:
        o["tags"] = list(tags)
    return o


C = "{color} "
NEW = [
    # ---- ハット (頭につけるもの)
    part("p_cabbie", "キャスケット", "🧢", "hat", C + "cabbie hat", ["casual", "girly"], 3000, match=["casquette"]),
    part("p_fedora", "中折れ帽", "🎩", "hat", C + "fedora", ["mode", "elegant"], 4500),
    part("p_boater", "カンカン帽", "👒", "hat", C + "boater hat", ["elegant", "natural"], 3500, seasons=["summer"],
         colors=["beige", "white", "black", "navy"]),
    part("p_hairband", "カチューシャ", "🎀", "hat", C + "hairband", ["girly", "jirai"], 1500),
    part("p_flat_cap", "ハンチング", "🧢", "hat", C + "flat cap", ["casual", "mode"], 3000, seasons=["autumn", "winter", "spring"]),
    part("p_earmuffs", "イヤーマフ", "🎧", "hat", C + "earmuffs", ["girly", "casual"], 2500, seasons=["winter"]),
    part("p_visor", "サンバイザー", "🧢", "hat", C + "visor cap", ["sporty"], 2000, seasons=["spring", "summer"]),
    part("p_bandana", "バンダナ", "🧣", "hat", C + "bandana", ["street", "casual"], 1200),
    # ---- トップス
    part("p_tank", "タンクトップ", "🎽", "top", C + "tank top", ["casual", "sporty"], 1500, seasons=["summer"]),
    part("p_polo", "ポロシャツ", "👕", "top", C + "polo shirt", ["casual", "sporty"], 3500, seasons=["spring", "summer", "autumn"]),
    part("p_sweatshirt", "トレーナー", "👕", "top", C + "sweatshirt", ["casual", "street", "sporty"], 4000,
         seasons=["autumn", "winter", "spring"]),
    part("p_striped", "ボーダーT", "👕", "top", C + "striped shirt", ["casual", "natural"], 2500),
    part("p_flannel", "チェックシャツ", "👔", "top", C + "plaid flannel shirt", ["casual", "street"], 4000,
         seasons=["autumn", "winter", "spring"], match=["flannel shirt", "plaid shirt"]),
    part("p_frill_blouse", "フリルブラウス", "👚", "top", C + "frilled blouse", ["girly", "jirai"], 4500, match=["frilled shirt"]),
    part("p_lace_blouse", "レースブラウス", "👚", "top", C + "lace blouse", ["girly", "jirai", "elegant"], 5000),
    part("p_graphic_t", "グラフィックT", "👕", "top", C + "graphic t-shirt", ["street"], 2500, match=["band t-shirt"]),
    part("p_big_shirt", "ビッグシャツ", "👔", "top", C + "oversized shirt", ["casual", "street", "mode"], 4000,
         match=["loose shirt"]),
    part("p_v_knit", "Vネックニット", "🧶", "top", C + "v-neck sweater", ["elegant", "natural"], 4500,
         seasons=["autumn", "winter", "spring"]),
    part("p_off_knit", "オフショルニット", "🧶", "top", C + "off-shoulder sweater, bare shoulders", ["girly", "mode"], 5000,
         bold=1, seasons=["autumn", "winter"]),
    part("p_tube_top", "チューブトップ", "🎽", "top", C + "tube top, bare shoulders", ["street", "mode"], 2500, bold=1,
         seasons=["summer"], match=["strapless shirt"]),
    part("p_halter", "ホルターネック", "🎽", "top", C + "halter top, bare shoulders", ["mode", "girly"], 3500, bold=1,
         seasons=["summer"]),
    part("p_aloha", "アロハシャツ", "🌺", "top", C + "hawaiian shirt", ["casual"], 4000, seasons=["summer"]),
    part("p_tunic", "チュニック", "👚", "top", C + "tunic", ["natural", "casual"], 4000),
    # ---- ワンピース
    part("p_shirt_dress", "シャツワンピース", "👗", "onepiece", C + "shirt dress", ["elegant", "casual", "skirt", "long"], 7000),
    part("p_pinafore", "ジャンパースカート", "👗", "onepiece", C + "pinafore dress", ["girly", "natural", "skirt"], 6000,
         match=["jumper skirt"]),
    part("p_slip_dress", "キャミワンピース", "👗", "onepiece", C + "slip dress, bare shoulders", ["girly", "mode", "skirt"], 5500,
         bold=1, seasons=["summer"]),
    part("p_pencil_dress", "タイトワンピース", "👗", "onepiece", C + "pencil dress", ["mode", "elegant", "skirt"], 7000),
    part("p_wrap_dress", "ラップワンピース", "👗", "onepiece", C + "wrap dress", ["elegant", "mode", "skirt"], 7500),
    part("p_long_dress", "ロングワンピース", "👗", "onepiece", C + "long dress", ["natural", "elegant", "skirt", "long"], 7000,
         match=["maxi dress", "midi dress"]),
    # ---- ボトムス
    part("p_cargo", "カーゴパンツ", "👖", "bottom", C + "cargo pants", ["street", "casual", "pants", "long"], 5000,
         colors=NEUTRAL),
    part("p_slacks", "スラックス", "👖", "bottom", C + "tailored pants", ["elegant", "mode", "pants", "long"], 6000,
         match=["slacks", "trousers", "straight pants"]),
    part("p_skinny", "スキニーパンツ", "👖", "bottom", C + "skinny jeans", ["casual", "mode", "pants", "long"], 5000,
         match=["skinny pants", "tight pants"], colors=BLUE),
    part("p_denim_shorts", "デニムショート", "🩳", "bottom", C + "denim shorts", ["casual", "street", "pants", "mini"], 3500,
         bold=1, seasons=["spring", "summer"], colors=["blue", "light_blue", "navy", "black", "white"]),
    part("p_bike_shorts", "バイカーショーツ", "🩳", "bottom", C + "bike shorts", ["sporty", "street", "pants", "mini"], 2500,
         bold=1, seasons=["spring", "summer", "autumn"]),
    part("p_plaid_mini", "チェックのミニスカート", "👗", "bottom", C + "plaid miniskirt", ["jirai", "street", "girly", "skirt", "mini"],
         4000, bold=1, match=["plaid mini skirt", "plaid skirt"]),
    part("p_sweatpants", "スウェットパンツ", "👖", "bottom", C + "sweatpants", ["casual", "sporty", "pants", "long"], 3000,
         outing=False, match=["jogger pants"]),
    part("p_overalls", "サロペット", "👖", "bottom", C + "overalls", ["casual", "natural", "pants", "long"], 6000),
    part("p_baggy", "バギーパンツ", "👖", "bottom", C + "baggy pants", ["street", "pants", "long"], 5000, match=["baggy jeans"]),
    part("p_flare_pants", "フレアパンツ", "👖", "bottom", C + "flared pants", ["mode", "girly", "pants", "long"], 5000,
         match=["bell-bottoms"]),
    part("p_tiered", "ティアードスカート", "👗", "bottom", C + "layered skirt", ["natural", "girly", "skirt", "long"], 5000,
         match=["tiered skirt"]),
    # ---- ソックス・タイツ
    part("p_loose_socks", "ルーズソックス", "🧦", "legwear", C + "loose socks", ["street", "girly"], 1000, colors=["white"]),
    part("p_fishnet", "網タイツ", "🦵", "legwear", C + "fishnet pantyhose", ["mode", "jirai"], 1500, bold=1, colors=["black"]),
    part("p_leg_warmers", "レッグウォーマー", "🧦", "legwear", C + "leg warmers", ["natural", "girly"], 1500,
         seasons=["autumn", "winter"]),
    part("p_striped_hh", "しましまニーハイ", "🧦", "legwear", C + "striped thighhighs", ["jirai", "girly"], 1500, bold=1),
    # ---- 靴
    part("p_platform_boots", "厚底ブーツ", "👢", "shoes", C + "platform boots", ["jirai", "street", "boots"], 9000,
         colors=["black", "white", "brown", "pink"]),
    part("p_flats", "バレエシューズ", "🥿", "shoes", C + "flats", ["girly", "natural", "elegant"], 5000, match=["flat shoes"]),
    part("p_combat_boots", "ワークブーツ", "🥾", "shoes", C + "combat boots", ["street", "casual", "boots"], 10000,
         colors=["black", "brown", "khaki", "beige"]),
    part("p_chunky_sneakers", "ダッドスニーカー", "👟", "shoes", C + "chunky sneakers", ["street", "sporty", "sneakers"], 9000),
    part("p_thigh_boots", "サイハイブーツ", "👢", "shoes", C + "thigh boots", ["mode", "boots"], 14000, bold=1,
         seasons=["autumn", "winter"], colors=["black", "brown", "white", "grey"]),
    part("p_platform_shoes", "厚底シューズ", "👞", "shoes", C + "platform shoes", ["jirai", "girly"], 7000,
         match=["platform mary janes"], colors=["black", "white", "pink", "brown"]),
    part("p_flip_flops", "ビーチサンダル", "🩴", "shoes", C + "flip-flops", ["casual"], 1500, seasons=["summer"]),
    part("p_rain_boots", "レインブーツ", "🥾", "shoes", C + "rain boots", ["casual", "boots"], 5000),
    # ---- アクセサリー (色の無いものは {color} を付けない)
    part("p_necklace", "ネックレス", "📿", "acc", "necklace", ["elegant", "natural"], 6000, match=["pendant"]),
    part("p_earrings", "イヤリング", "💎", "acc", "earrings", ["elegant", "girly", "mode"], 4000),
    part("p_glasses", "メガネ", "👓", "acc", "glasses", ["elegant", "natural"], 8000),
    part("p_sunglasses", "サングラス", "🕶", "acc", "sunglasses", ["mode", "street"], 5000, seasons=["spring", "summer"]),
    part("p_shoulder_bag", "ショルダーバッグ", "👜", "acc", C + "shoulder bag", ["casual", "elegant"], 6000),
    part("p_watch", "腕時計", "⌚", "acc", "wristwatch", ["elegant", "casual"], 12000, match=["watch"]),
    part("p_bracelet", "ブレスレット", "📿", "acc", "bracelet", ["girly", "elegant"], 3000),
    part("p_hair_clip", "ヘアクリップ", "🎀", "acc", C + "hair clip", ["girly", "jirai", "casual"], 800, match=["hairclip"]),
    part("p_scrunchie", "シュシュ", "🎀", "acc", C + "hair scrunchie", ["girly", "casual"], 800, match=["scrunchie"]),
    part("p_gloves", "手袋", "🧤", "acc", C + "knit gloves", ["elegant", "casual"], 2500, seasons=["winter"],
         match=["mittens"]),
    part("p_backpack", "リュック", "🎒", "acc", C + "backpack", ["casual", "sporty", "street"], 6000),
    part("p_hairpin", "ヘアピン", "📍", "acc", C + "hairpin", ["girly", "natural", "casual"], 600, match=["hair pin"]),
    # ---- ランジェリー (上に何も着ていないときだけ描かれる. 文の照合には入らない)
    part("p_sports_bra", "スポーツブラ", "🎽", "lingerie", C + "sports bra, {color} boyshorts", ["sporty", "casual"], 2500, bold=2,
         outing=False, places=MS),
    part("p_cotton_lingerie", "コットンの下着", "🩲", "lingerie", C + "cotton bra, {color} panties", ["natural", "casual"], 2000, bold=3,
         outing=False, places=MS),
    part("p_bralette", "ブラレット", "🎀", "lingerie", C + "lace bralette, {color} panties", ["girly", "natural"], 3500, bold=3,
         outing=False, places=MS),
    part("p_frill_lingerie", "フリルの下着", "🎀", "lingerie", C + "frilled bra, {color} frilled panties", ["girly", "jirai"], 4000,
         bold=3, outing=False),
    part("p_lace_lingerie", "レースの下着", "🎀", "lingerie", C + "lace bra, {color} lace panties", ["elegant", "mode"], 5000, bold=3,
         outing=False),
    part("p_strapless_bra", "ストラップレスブラ", "🎀", "lingerie", C + "strapless bra, {color} panties", ["mode", "elegant"], 4500,
         bold=3, outing=False),
    part("p_chemise", "シュミーズ", "🕯", "lingerie", C + "chemise, lace trim", ["elegant", "girly"], 5000, bold=2, outing=False),
    part("p_garter_set", "ガーターベルトの下着", "🎀", "lingerie", C + "lace bra, {color} panties, {color} garter belt",
         ["mode", "elegant"], 6000, bold=3, outing=False),
    # ---- アウター (色は文に書く. いまのアウターと同じ形)
    whole("leather_jacket", "レザージャケット", "🧥", "outer", "black leather jacket, open jacket", 18000,
          seasons=["spring", "autumn"], tags=["street", "mode"], outing=True, places=MS),
    whole("long_coat", "ロングコート", "🧥", "outer", "grey long coat, open coat", 16000, seasons=["autumn", "winter"],
          tags=["elegant", "mode"], outing=True, places=MS),
    whole("cropped_jacket", "ショート丈ジャケット", "🧥", "outer", "black cropped jacket", 9000, seasons=["spring", "autumn"],
          tags=["street", "mode"], outing=True, places=MS),
    whole("blazer", "テーラードジャケット", "🧥", "outer", "navy blazer, open jacket", 12000, seasons=["spring", "autumn"],
          tags=["elegant", "mode"], outing=True, places=MS),
    whole("bomber", "MA-1", "🧥", "outer", "khaki bomber jacket", 10000, seasons=["autumn", "winter"],
          tags=["street", "casual"], outing=True, places=MS),
    whole("fur_coat", "ファーコート", "🧥", "outer", "white fur coat", 20000, seasons=["winter"], tags=["elegant", "girly"],
          outing=True, places=["mall"]),
    whole("poncho", "ポンチョ", "🧥", "outer", "beige knit poncho", 7000, seasons=["autumn", "winter"], tags=["natural", "girly"],
          outing=True, places=MS),
    whole("letterman", "スタジャン", "🧥", "outer", "navy letterman jacket, open jacket", 12000, seasons=["autumn", "winter", "spring"],
          tags=["street", "sporty", "casual"], outing=True, places=MS),
    # ---- 一式: 部屋着
    whole("fleece_lounge", "もこもこルームウェア", "🧸", "lounge", "fluffy fleece loungewear, hooded jacket, long pants", 5000,
          seasons=["autumn", "winter"], tags=["girly", "casual", "pants", "long"], places=MS),
    whole("cool_lounge", "夏の部屋着", "🧸", "lounge", "tank top, dolphin shorts, loungewear, bare legs", 3000, bold=1,
          seasons=["summer"], tags=["casual", "pants", "mini"], places=MS),
    whole("jersey", "ジャージ", "🏃", "lounge", "track suit, track jacket, track pants", 5000, tags=["sporty", "pants", "long"],
          places=MS),
    whole("jinbei", "甚平", "🎐", "lounge", "jinbei, short sleeves, shorts", 4500, seasons=["summer"], places=MS),
    # ---- 一式: パジャマ
    whole("kigurumi", "着ぐるみパジャマ", "🐻", "pajamas", "animal onesie, animal hood, hood up", 5000, places=MS),
    whole("babydoll", "ベビードール", "🕯", "pajamas", "babydoll, lace trim, bare shoulders", 6000, bold=2),
    # ---- 一式: 水着
    whole("swim_skirt", "水着スカート", "👙", "swim", "swimsuit, swimsuit skirt, frills", 6000, bold=1, seasons=["summer"]),
    whole("frill_bikini", "フリルビキニ", "👙", "swim", "frilled bikini, navel, bare shoulders", 6500, bold=2, seasons=["summer"]),
    whole("rash_guard", "ラッシュガード", "🏄", "swim", "rash guard, long sleeves, swim shorts", 5000, seasons=["summer"]),
    # ---- 一式: よそ行き
    whole("cocktail", "パーティードレス", "🥂", "formal", "cocktail dress, off-shoulder, high heels, earrings", 12000, bold=1,
          tags=["elegant", "mode", "heels"], outing=True),
    whole("furisode", "振袖", "👘", "formal", "furisode, obi, kanzashi, hair up", 30000, seasons=["winter", "spring"], outing=True),
    # ---- 一式: 衣装 (靴は footwear.yaml の合わせ方)
    whole("miko", "巫女", "⛩", "costume", "miko, white kimono, red hakama, hair ribbon", 8000),
    whole("magical", "魔法少女", "🪄", "costume", "magical girl, frilled dress, layered skirt, brooch, elbow gloves, knee boots", 9000, bold=1),
    whole("gothic", "ゴスロリ", "🖤", "costume", "gothic lolita, black frilled dress, lace headband, platform boots", 9000),
    whole("vampire", "ヴァンパイア", "🦇", "costume", "vampire, cosplay, black gown, cape, fangs, boots", 9000),
    whole("angel", "天使", "😇", "costume", "angel, cosplay, white dress, yellow halo, white feather wings, sandals", 9000),
    whole("princess", "お姫様", "👑", "costume", "princess, tiara, gown, puffy sleeves, elbow gloves, high heels", 10000),
    # ---- 一式: 衣装 (latex 系. nsfw/latex.yaml の組み方: ブラ + ミニスカート / ショーツ + ロンググローブ + ブーツ)
    whole("latex_bondage", "ラテックスのボンデージ", "⛓", "costume",
          "black latex bra, black latex miniskirt, black latex elbow gloves, black latex thigh boots, shiny clothes", 12000, bold=3),
    whole("latex_red", "赤いラテックス", "💋", "costume",
          "red latex strapless bra, red latex panties, red latex elbow gloves, red latex knee boots, garter belt, shiny clothes", 12000, bold=3),
    whole("latex_bodysuit", "ラバースーツ", "🖤", "costume", "black latex bodysuit, shiny clothes, high heels", 14000, bold=2),
    whole("catsuit", "キャットスーツ", "🐈", "costume", "black latex catsuit, cat ears, cat tail, shiny clothes, high heels", 13000, bold=2),
    whole("latex_nurse", "ラテックスナース", "💉", "costume",
          "nurse, white latex dress, nurse cap, white latex gloves, white thighhighs, shiny clothes", 12000, bold=2),
    whole("latex_bunny", "ラテックスのバニー", "🐰", "costume",
          "playboy bunny, black latex leotard, rabbit ears, fishnet pantyhose, high heels, shiny clothes", 12000, bold=3),
]


def main():
    items = json.load(open(PATH, encoding="utf-8"))
    have = {o["id"] for o in items}
    add = [o for o in NEW if o["id"] not in have]
    ids = [o["id"] for o in NEW]
    assert len(ids) == len(set(ids)), "id が重複"
    # 部品 (色無し以外) の後ろ, アウターの後ろ... と並べると読みづらいので, 区分ごとに既存の同じ区分の最後へ差し込む
    def group(o):
        if o.get("kind") == "part":
            return "part:" + o["slot"]
        return "kind:" + o["kind"]
    for o in add:
        g = group(o)
        idx = max((i for i, x in enumerate(items) if group(x) == g), default=len(items) - 1)
        items.insert(idx + 1, o)
    with open(PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("[\n" + ",\n".join(" " + json.dumps(o, ensure_ascii=False) for o in items) + "\n]\n")
    print("added", len(add), "total", len(items))


if __name__ == "__main__":
    main()
