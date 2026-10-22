"""スリザーリンクの元に戻す・やり直す・仮置き (static/puzzles.js の slState / slSetSt / slRecord / slUndoSt / slRedoSt /
slTrialBegin / slTrialEndSt / slTrialDepth) の確認. 画面の側の JS なので, ヘッドレスのブラウザ (Edge か Chrome) で動かす.
- 通常の手と仮置きの手の履歴が混ざらない (仮置きの中の元に戻すは, 仮置きに入ったところで止まる. 通常のやり直しの残りも触らない)
- 消して抜ける: 線と×は入る前に戻り, 通常の履歴 (やり直しの残りも) は入る前のまま
- 確定して抜ける: まとめて一つの手として通常の履歴に積まれ, 元に戻すで仮置きごと取り消せる (やり直しの残りは消える)
- 仮置きの中の仮置き (段ごとに別の履歴. 段の上限)
- 線のかたまりの色 (slColorsFor): 増えても既存の色は変わらない, つながったら元の色, 分かれたら片方だけ新しい色, 元に戻すで色も戻る

    python tools/test_slither_history.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "msedge", "google-chrome", "chromium", "chromium-browser", "chrome",
]

CHECKS = r"""
function eq(a, b, msg) { const j = (o) => JSON.stringify(o, (k, val) => (val instanceof Map ? [...val] : val)), x = j(a), y = j(b); if (x !== y) throw new Error(msg + ': ' + x + ' != ' + y); }
function act(sl, pairs, start) { const ch = new Map(); for (const [e, v] of pairs) slSetSt(sl, e, v, ch); return slRecord(sl, ch, start); }
function run() {
  // 通常の手 2 つ, 1 つ戻してやり直しの残りを作る
  let sl = slState([0, 0, 0, 0, 0, 0]);
  act(sl, [[0, 1]]); act(sl, [[1, 1], [2, 1]]);
  eq(slUndoSt(sl), [[1, 0], [2, 0]], '通常の元に戻す');
  eq(sl.st, [1, 0, 0, 0, 0, 0], '戻した盤');
  // 仮置き: 元に戻すは仮置きの手だけ. 入ったところで止まり, 通常の履歴は触らない
  slTrialBegin(sl);
  eq(slUndoSt(sl), null, '仮置きに入った直後は戻すものが無い');
  eq(slRedoSt(sl), null, '仮置きに入った直後は通常のやり直しを使わない');
  act(sl, [[3, 1]]); act(sl, [[4, -1]]);
  eq(slTrialDepth(sl, 3), 1, '仮置きの線'); eq(slTrialDepth(sl, 0), 0, '通常の線');
  eq(slUndoSt(sl), [[4, 0]], '仮置きの元に戻す'); eq(slUndoSt(sl), [[3, 0]], '仮置きの元に戻す 2');
  eq(slUndoSt(sl), null, '仮置きの前までは戻らない');
  eq(sl.st, [1, 0, 0, 0, 0, 0], '通常の手はそのまま');
  eq(slRedoSt(sl), [[3, 1]], '仮置きのやり直し');
  // 消して抜ける: 盤は入る前, 通常の履歴とやり直しの残りも入る前のまま
  eq(slTrialEndSt(sl, false), [[3, 0]], '消して抜けた辺');
  eq(sl.st, [1, 0, 0, 0, 0, 0], '消して抜けた盤');
  eq(sl.base.hist.length, 1, '消して抜けても通常の履歴は増えない');
  eq(slRedoSt(sl), [[1, 1], [2, 1]], '通常のやり直しの残りが使える');
  eq(slUndoSt(sl), [[1, 0], [2, 0]], 'また戻す');

  // 確定して抜ける: まとめて一つの手. 通常のやり直しの残りは消える. 元に戻すで仮置きごと取り消せる
  slTrialBegin(sl);
  act(sl, [[3, 1]]); act(sl, [[4, -1], [0, 0]]); act(sl, [[3, 0]]);      // 3 は引いて消したので変わり分に入らない
  eq(slTrialEndSt(sl, true), [], '確定は送るものが無い');
  eq(sl.st, [0, 0, 0, 0, -1, 0], '確定した盤');
  eq(sl.base.hist.length, 2, '確定は通常の履歴に一つ');
  eq(sl.base.redo.length, 0, '確定で通常のやり直しの残りは消える');
  eq(slTrialDepth(sl, 4), 0, '確定したら仮置きの色ではない');
  eq(slUndoSt(sl).sort(), [[0, 1], [4, 0]], '元に戻すで仮置きごと取り消す');
  eq(sl.st, [1, 0, 0, 0, 0, 0], '取り消した盤');
  eq(slRedoSt(sl).sort(), [[0, 0], [4, -1]], 'やり直すで確定した仮置きをまた');
  eq(slUndoSt(sl).length, 2, '');
  // 仮置きで何もせずに確定しても履歴は増えない
  slTrialBegin(sl); slTrialEndSt(sl, true);
  eq(sl.base.hist.length, 1, '空の確定');

  // 仮置きの中の仮置き: 段ごとに履歴が別. 内側の確定は外側の一手. 外側を消して抜けると内側で確定した分も消える
  sl = slState([0, 0, 0, 0, 0, 0]);
  act(sl, [[0, 1]]);
  slTrialBegin(sl); act(sl, [[1, 1]]);
  slTrialBegin(sl); act(sl, [[2, 1]]); act(sl, [[1, -1]]);
  eq(sl.trials.length, 2, '2 段目');
  eq(slTrialDepth(sl, 2), 2, '2 段目の線'); eq(slTrialDepth(sl, 1), 2, '2 段目で変えた 1 段目の線');
  eq(slUndoSt(sl), [[1, 1]], '2 段目の元に戻す'); eq(slTrialDepth(sl, 1), 1, '戻したら 1 段目の線');
  eq(slUndoSt(sl), [[2, 0]], ''); eq(slUndoSt(sl), null, '2 段目に入る前までは戻らない');
  slRedoSt(sl);
  eq(slTrialEndSt(sl, false), [[2, 0]], '2 段目を消して抜ける');
  eq(sl.trials[0].hist.length, 1, '1 段目の履歴はそのまま');
  slTrialBegin(sl); act(sl, [[2, 1]]); act(sl, [[3, -1]]);
  slTrialEndSt(sl, true);
  eq(sl.trials[0].hist.length, 2, '2 段目の確定は 1 段目の一手');
  eq(slTrialDepth(sl, 2), 1, '確定した 2 段目の線は 1 段目の色');
  eq(slUndoSt(sl).sort(), [[2, 0], [3, 0]], '1 段目の元に戻すで 2 段目ごと取り消す');
  slRedoSt(sl);
  eq(slTrialEndSt(sl, false).sort(), [[1, 0], [2, 0], [3, 0]], '1 段目を消して抜けると 2 段目で確定した分も消える');
  eq(sl.st, [1, 0, 0, 0, 0, 0], '入る前の盤');
  eq(sl.base.hist.length, 1, '通常の履歴はそのまま');
  // 段の上限
  let n = 0;
  while (slTrialBegin(sl)) n++;
  eq(n, SL_TRIAL_PAL.length, '段の上限');
  eq(slTrialEndSt(slState([0]), true), [], '仮置きでないときに抜けても何もしない');
  colors();
  return 'OK';
}
// 線のかたまりの色: 増えても既存の色は変わらない / つながったら元 (なぞり始め) の色にそろう / 分かれたら片方だけ新しい色 /
// 元に戻す・やり直す・仮置きの取り消しで色も戻る. 盤 3×3: 横の辺 r*3+c (0..11), 縦の辺 12 + r*4 + c
function colors() {
  const v = { h: 3, w: 3 }, z = () => Array(24).fill(0);
  const col = (sl, e) => sl.colors.get(e);
  let sl = slState(z(), v);
  act(sl, [[0, 1]], [0, 0]);                      // A: (0,0)-(0,1)
  eq(col(sl, 0), 0, '最初のかたまりは墨');
  act(sl, [[8, 1]], [2, 2]);                      // B: (2,2)-(2,3)
  act(sl, [[4, 1]], [1, 1]);                      // C: (1,1)-(1,2)
  eq([col(sl, 0), col(sl, 8), col(sl, 4)], [0, 1, 2], 'かたまりが増えても既存の色は変わらない');
  act(sl, [[11, 1]], [3, 2]);                     // D: (3,2)-(3,3) 別のかたまり
  eq([col(sl, 0), col(sl, 8), col(sl, 4), col(sl, 11)], [0, 1, 2, 3], 'さらに増えても');
  // C の端 (1,1) から上へなぞって A とつなぐ → C の色にそろう
  act(sl, [[13, 1]], [1, 1]);
  eq([col(sl, 0), col(sl, 13), col(sl, 4), col(sl, 8)], [2, 2, 2, 1], 'つないだ元の色にそろう');
  eq(slUndoSt(sl), [[13, 0]], '');
  eq([col(sl, 0), col(sl, 4)], [0, 2], '元に戻すと色も戻る');
  slRedoSt(sl);
  eq([col(sl, 0), col(sl, 4)], [2, 2], 'やり直すとまた');
  slUndoSt(sl);
  // A の端 (0,1) から下へなぞって C とつなぐ → A の色
  act(sl, [[13, 1]], [0, 1]);
  eq([col(sl, 0), col(sl, 4)], [0, 0], '逆からつなげば A の色');
  slUndoSt(sl);
  // なぞり始めに線が無い (クリックなど) → 辺の多いほうの色: A を 2 本にしてからつなぐ
  act(sl, [[1, 1]], [0, 1]);                      // A: (0,0)-(0,2)
  act(sl, [[13, 1]], null);
  eq([col(sl, 1), col(sl, 4)], [0, 0], '元が分からなければ大きいほうの色');
  // 分かれる: 間の辺を消すと, 大きいほう (A 側 3 本) が色を残し, C (1 本) は使っていない色
  act(sl, [[13, 0]], null);
  eq(col(sl, 0), 0, '分かれても大きいほうは元の色');
  const c4 = col(sl, 4);
  eq([1, 3, 0].includes(c4), false, '分かれた小さいほうは使っていない色');
  eq([col(sl, 8), col(sl, 11)], [1, 3], 'ほかのかたまりの色は変わらない');
  // 仮置き: つないでから消して抜けると色も戻る. 確定して抜けたあと元に戻すと色も戻る
  const before = sl.colors;
  slTrialBegin(sl);
  act(sl, [[23, 1]], [2, 3]);                     // B と D をつなぐ縦の辺 (2,3)-(3,3)
  eq(col(sl, 11), 1, '仮置きでつないだら B の色');
  slTrialEndSt(sl, false);
  eq(sl.colors, before, '消して抜けたら色も入る前');
  slTrialBegin(sl);
  act(sl, [[23, 1]], [3, 3]);
  eq(col(sl, 8), 3, 'D の端から → D の色');
  slTrialEndSt(sl, true);
  eq(col(sl, 8), 3, '確定しても色はそのまま');
  slUndoSt(sl);
  eq([col(sl, 8), col(sl, 11)], [1, 3], '確定した仮置きを元に戻すと色も戻る');
  // 盤の大きさを知らないとき (古い呼び方) は色を覚えないだけ
  eq(slState([0, 0]).colors.size, 0, '');
}
"""


def find_browser():
    for b in BROWSERS:
        p = b if os.path.isabs(b) else shutil.which(b)
        if p and os.path.exists(p):
            return p
    return None


def main():
    br = find_browser()
    if not br:
        print("slither history: SKIP (Edge / Chrome が見つからない)")
        return
    tmp = tempfile.mkdtemp(prefix="kurashi_slh_")
    js = open(os.path.join(ROOT, "static", "puzzles.js"), encoding="utf-8").read()
    page = os.path.join(tmp, "t.html")
    with open(page, "w", encoding="utf-8") as f:
        f.write('<!doctype html><meta charset="utf-8"><body><pre id="out">NOT RUN</pre><script>\n' + js + "\n" + CHECKS +
                "\ntry { document.getElementById('out').textContent = 'RESULT:' + run(); }"
                " catch (e) { document.getElementById('out').textContent = 'RESULT:FAIL ' + e.message; }\n</script>")
    url = "file:///" + page.replace("\\", "/")
    out = subprocess.run([br, "--headless", "--disable-gpu", "--no-first-run", "--user-data-dir=" + os.path.join(tmp, "prof"),
                          "--virtual-time-budget=3000", "--dump-dom", url],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120).stdout.decode("utf-8", "replace")
    shutil.rmtree(tmp, ignore_errors=True)
    i = out.find("RESULT:")
    res = out[i + 7:out.find("</pre>", i)] if i >= 0 else "(結果なし) " + out[:300]
    assert res == "OK", res
    print("slither history: OK")


if __name__ == "__main__":
    main()
    sys.exit(0)
