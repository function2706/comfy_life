"""判断の記録 (core/trace.py) と, 不具合を報告するときの書き出し (core/debugdump.py・tools/debug_decode.py).

- 記録が残る (メッセージの返信の予定・届けた/既読だけ・働きかけ・謝罪・閉じていた間・約束の状態). 上限・古いものは捨てる.
- ディスク上の記録に平文 (mood などのキー名・日本語) が出ない. server.log にも判断の中身を書かない.
- 書き出し: 要点 (バージョン・ワールド・あなた・相手の状態) → 詳細. 符号化 → 復号の往復, 途中で切れた・化けたブロックの検出.
- 古いセーブ (記録が無い・項目が欠けている) でも書き出せる.

    python tools/test_debug_dump.py
"""
import io
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from core import engine, store, trace as TR  # noqa: E402
from core.debugdump import decode_block, encode_block  # noqa: E402


def main():
    random.seed(8)
    tmp = tempfile.mkdtemp(prefix="kurashi_test_")
    store.DATA = tmp
    try:
        app = engine.App()
        app.save_settings({"auto_generate": False})
        app.create_world("書き出し")
        cid = app.settings["active_character"]
        app.bonds.set_stage(cid, "contact")
        st = app.state(cid)
        now = time.time()

        # ---- 1. 記録が残る: メッセージ → 返信の予定 → 届ける. 謝罪の判定. 約束の状態
        app.presence.declare("none", now)
        app.chat.send(cid, "greet_morning")
        assert st.get("msg_pending"), "返信の予定が決まっていない"
        st["msg_pending"]["due"] = now - 60
        app.deliver_due(now + 1)
        app.manners.apology(app.chars[cid], st, now)
        app.appoint.propose(cid, now + 2 * 86400, "park", "walk", now)
        app.offline.simulate(now - 6 * 3600, now - 60)
        recs = app.trace.read()
        cats = {r["c"] for r in recs}
        for c in ("msg", "deliver", "manners", "appoint", "offline"):
            assert c in cats, (c, cats)
        print("記録が残る: OK |", len(recs), "件", sorted(cats))

        # ---- 2. ディスク上は読めない形 (平文のキー名・日本語が出ない). server.log にも書かない
        raw = open(app.trace.path(), encoding="ascii").read()
        for w in ("mood", "affection", "msg_pending", "reply", "offline"):
            assert w not in raw, w
        assert TR.dec(raw.splitlines()[0])["c"]
        slog = store.dpath("server.log")
        assert not os.path.exists(slog) or "返信の予定" not in open(slog, encoding="utf-8", errors="replace").read()
        print("読めない形で保存: OK |", raw.splitlines()[0][:40], "…")

        # ---- 3. 上限・古いものは捨てる
        T = app.trace
        mx, keep = TR.MAX_LINES, TR.KEEP_DAYS
        TR.MAX_LINES = 50
        try:
            T.add("test", "古い", t=now - (keep + 1) * 86400)
            for i in range(80):
                T.add("test", "n%d" % i, t=now)
            T.trim(now)
            rs = T.read()
            assert len(rs) == 50 and rs[-1]["m"] == "n79" and not any(r["m"] == "古い" for r in rs), len(rs)
        finally:
            TR.MAX_LINES = mx
        print("上限・古いものを捨てる: OK")

        # ---- 4. 書き出し: 要点 → 詳細. 必要な欄がそろう
        app.offline.simulate(now - 3 * 3600, now - 30)
        text = app.debugdump.build(hours=48, cid=cid, now=now)
        for k in ("version:", "world:", "now:", "range:", "== あなた ==", "params=", "msg_pending=", "approach=", "apology_last=",
                  "contacts_24h=", "reasons(機嫌の理由)=", "appoints=", "earn.favors=", "=== 詳細 ===", "--- 判断の記録", "--- トーク:",
                  "--- ログ:", "--- 一人の時間", "--- 日記", "--- server.log"):
            assert k in text, k
        assert text.index("== あなた ==") < text.index("=== 詳細 ===")
        assert "pos" not in [ln.split("=")[0] for ln in text.splitlines()]
        brief = app.debugdump.build(hours=48, cid=cid, brief=True, now=now)
        assert "params=" in brief and "=== 詳細 ===" not in brief
        print("書き出しの欄: OK |", text.count("\n") + 1, "行 / 要点だけ", brief.count("\n") + 1, "行")

        # ---- 5. 符号化 → 復号の往復. 画面に渡すのはブロックだけ. 切れた・化けたブロックを見つける
        r = app.debugdump.dump(hours=48, cid=cid, now=now)
        blk = r["block"]
        assert blk.startswith("-----BEGIN KURASHI-DUMP v1") and blk.rstrip().endswith("-----END KURASHI-DUMP-----")
        assert "params" not in blk and "mood" not in blk and max(len(x) for x in blk.splitlines()[1:-1]) <= 76
        back, probs = decode_block("こんにちは、これです\n" + blk + "\nよろしく")
        assert back == text and not probs, probs
        cut = "\n".join(blk.splitlines()[:len(blk.splitlines()) // 2])
        part, probs = decode_block(cut)
        assert probs and any("切れ" in p for p in probs) and part.startswith("=== KURASHI"), probs
        lines = blk.splitlines()
        lines[2] = ("A" if lines[2][0] != "A" else "B") + lines[2][1:]
        _, probs = decode_block("\n".join(lines))
        assert any("チェックサム" in p for p in probs), probs
        # 道具でも
        f = os.path.join(tmp, "pasted.txt")
        io.open(f, "w", encoding="utf-8").write(blk)
        out = subprocess.run([sys.executable, "-X", "utf8", os.path.join(HERE, "debug_decode.py"), f], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert out.returncode == 0 and "params=" in out.stdout.decode("utf-8"), out.stderr.decode("utf-8", "replace")
        print("符号化と復号: OK | ブロック", len(blk), "文字 / 切れ・化けを検出")

        # ---- 6. 古いセーブ: 記録が無い・項目が欠けていても書き出せる
        os.remove(app.trace.path())
        for k in ("contacts", "reasons", "apology_last", "favors", "msg_pending", "approach"):
            st.pop(k, None)
        app.appoint.all().append({"id": "old", "cid": cid, "t": now - 3600, "place": "park"})
        text = app.debugdump.build(hours=24, now=now)
        assert "params=" in text and "--- 判断の記録 (0) ---" in text
        assert encode_block("")
        print("古いセーブ: OK")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
