"""画像の見せ方 (S2): トークの自撮りのサムネイル (A18. core/chat.py の with_photos) と, ギャラリーの人ごとの絞り込み (A19).

- 自撮りが添えられた返事に, 同じ時刻の記録 (ログ) の画像が付く. 作っている途中は pending, できたら画像
- 再起動で消えたジョブは「生成中」にしない. 画像も途中のジョブも無ければ何も付けない (文字の「自撮りが添えられていた」だけ)
- 以前の返事 (selfie の印が無く, 文字だけ) にも, 記録に画像があれば付く (遡及). 電話での返事 (📞) にも
- 自撮りでない返事には付けない. 別の時刻の記録の画像を取り違えない
- ギャラリー: 画像のある人だけ選べる (枚数. ファイルが消えた画像は数えない). 時系列・シチュエーション別とも人で絞れる

    python tools/test_chat_photo.py
"""
import os
import random
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from core import engine, store  # noqa: E402
from testclock import fix_noon  # noqa: E402

fix_noon(engine)
MARK = "（📷 自撮りが添えられていた）"


def put_image(app, e, name):
    """記録に画像を 1 枚付ける (ファイルも置く)."""
    rel = "test/%s.png" % name
    full = store.dpath("images", "test", name + ".png")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
    im = {"path": rel, "seed": 7, "pos": e.get("pos", "") or "selfie", "neg": e.get("neg", ""), "t": e["t"]}
    e.setdefault("images", []).append(im)
    e["image"] = rel
    return im


def main():
    random.seed(3)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("画像")
        cid = app.settings["active_character"]
        char, st = app.char(cid), app.state(cid)

        real_reply = app.chat.reply
        def reply_as(key):
            app.chat.reply = lambda *a, **k: (key, {}, {})
        def say(kind, now):
            app._chat_reply(char, st, {"kind": kind, "t": now - 30, "kind_t": now - 30, "reply": True}, now)
            return [x for x in app.chat.thread(cid)["items"] if x["who"] == "her"][-1]

        # ---- 1. 自撮りを送ってくれた返事: 画像も途中のジョブも無ければ, 文字だけ (photo なし)
        now = time.time()
        reply_as("selfie_yes")
        it = say("ask_selfie", now)
        assert it.get("selfie") and MARK in it["text"] and "photo" not in it, it
        e = [x for x in app.log(cid) if x.get("selfie")][-1]
        assert abs(e["t"] - it["t"]) < 0.01
        print("画像なし: OK")

        # ---- 2. 作っている途中 → できたら画像. 再起動で消えたジョブは「生成中」にしない
        e["job"] = "j_test"
        app.jobs["j_test"] = {"id": "j_test", "status": "queued", "created": now}
        it = [x for x in app.chat.thread(cid)["items"] if x["who"] == "her"][-1]
        assert it["photo"]["pending"] and it["photo"]["im"] is None, it
        app.jobs["j_test"]["status"] = "running"
        assert [x for x in app.chat.thread(cid)["items"] if x["who"] == "her"][-1]["photo"]["pending"]
        app.jobs["j_test"]["status"] = "done"
        e.pop("job")
        im = put_image(app, e, "a")
        p = [x for x in app.chat.thread(cid)["items"] if x["who"] == "her"][-1]["photo"]
        assert not p["pending"] and p["im"]["path"] == im["path"] and p["entry"]["id"] == e["id"], p
        e["job"] = "j_gone"                       # サーバを立て直してジョブが消えた
        p = [x for x in app.chat.thread(cid)["items"] if x["who"] == "her"][-1]["photo"]
        assert not p["pending"] and p["im"], p
        e.pop("job")
        print("生成中 → 差し替え: OK")

        # ---- 3. 自撮りでない返事には付けない. 近い時刻でも別の記録の画像を取り違えない
        reply_as("selfie_no")          # (自撮りが付かない返事)
        it2 = say("smalltalk", now + 60)
        assert "photo" not in it2 and not it2.get("selfie"), it2
        e2 = app.log(cid)[-1]
        put_image(app, e2, "b")                   # 自撮りでない記録に画像があっても
        assert "photo" not in [x for x in app.chat.thread(cid)["items"] if x["who"] == "her"][-1]
        print("自撮りでない返事: OK")

        # ---- 4. 遡及: 以前の返事 (selfie の印が無い. 文字だけ) にも, 記録に画像があれば付く. 記録に画像が無ければ付かない
        old_t = now - 86400
        app.chat.add(cid, "her", "📱『どうぞ』" + "\n" + MARK, kind="selfie_yes", t=old_t)
        old_e = {"id": "old1", "t": old_t, "action": "_chat", "action_name": "返信", "icon": "📱", "text": "📱『どうぞ』\n" + MARK,
                 "scene": "", "pos": "selfie", "neg": "", "images": [], "image": None}
        app.log(cid).insert(0, old_e)
        th = app.chat.thread(cid)["items"]
        o = next(x for x in th if abs(x["t"] - old_t) < 0.01)
        assert "photo" not in o, o
        put_image(app, old_e, "old")
        o = next(x for x in app.chat.thread(cid)["items"] if abs(x["t"] - old_t) < 0.01)
        assert o["photo"]["im"]["path"] == "test/old.png", o
        # 既存の画像を出しただけ (images は空で image だけ) の記録も
        ru_t = now - 7200
        app.chat.add(cid, "her", "📱『はい』\n" + MARK, kind="smalltalk_ok", t=ru_t, selfie=True)
        app.log(cid).insert(0, {"id": "ru1", "t": ru_t, "action": "_chat", "action_name": "返信", "text": "x", "selfie": True,
                                "pos": "selfie", "neg": "", "images": [], "image": "test/a.png", "seed": 9, "reused": True})
        o = next(x for x in app.chat.thread(cid)["items"] if abs(x["t"] - ru_t) < 0.01)
        assert o["photo"]["im"]["path"] == "test/a.png" and o["photo"]["im"]["seed"] == 9, o
        print("遡及: OK")

        # ---- 5. 電話での返事 (📞 に置き換わる) にも
        reply_as("selfie_yes")
        it5 = say("ask_selfie", now + 120)
        d = app.chat.load(cid)
        for x in d["items"]:
            if abs(x["t"] - it5["t"]) < 0.01:
                x["text"] = x["text"].replace("📱", "📞", 1)
        app.chat.save(cid, d)
        put_image(app, [x for x in app.log(cid) if x.get("selfie")][-1], "call")
        o = next(x for x in app.chat.thread(cid)["items"] if abs(x["t"] - it5["t"]) < 0.01)
        assert o["text"].startswith("📞") and o["photo"]["im"]["path"] == "test/call.png", o
        app.chat.reply = real_reply
        print("電話の返事: OK")

        # ---- 6. ギャラリー: 画像のある人だけ・枚数 (ファイルが消えた画像は数えない)
        app.new_character("ふたりめ", stage="contact")
        others = [c for c in app.chars if c != cid]
        assert others
        ppl = {p["id"]: p["count"] for p in app.gallery_people()["people"]}
        n_me = sum(len(x.get("images") or []) for x in app.log(cid))
        assert ppl.get(cid) == n_me and all(c not in ppl for c in others), (ppl, n_me)
        os.remove(store.dpath("images", "test", "b.png"))
        assert app.gallery_people()["people"][0]["count"] == n_me - 1
        # 時系列・シチュエーション別とも, 人で絞れる
        if others:
            o2 = others[0]
            oe = {"id": "oth1", "t": now - 50, "action": "talk", "action_name": "話す", "text": "x", "scene": "", "pos": "other", "neg": "",
                  "images": [], "image": None}
            app.log(o2).append(oe)
            put_image(app, oe, "other")
            ppl = {p["id"]: p["count"] for p in app.gallery_people()["people"]}
            assert ppl.get(o2) == 1, ppl
            got = app.log_page(o2, 0, 40, True)
            assert got["total"] == 1 and got["items"][0]["id"] == "oth1", got
            assert all(x["who"] == cid for x in app.log_page(cid, 0, 40, True)["items"])
            assert len({x["who"] for x in app.log_page(None, 0, 40, True)["items"]}) == 2
            al = app.album(o2)["groups"]
            assert len(al) == 1 and al[0]["cover"] == "test/other.png", al
            assert all(g["cover"] != "test/other.png" for g in app.album(cid)["groups"])
            assert app.album(o2, al[0]["key"])["items"][0]["path"] == "test/other.png"
        print("ギャラリーの人ごと: OK", app.gallery_people()["people"])
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
