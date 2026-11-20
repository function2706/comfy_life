"""ピクロスの？印と元に戻す・やり直す (static/puzzles.js の pcStartMode / pcNext / pcRecord / pcUndoSt / pcRedoSt / pcApply / pcSetMark) の確認.
画面の側の JS なので, ヘッドレスのブラウザ (Edge か Chrome) で動かす. サーバ (taskMove) と描き直し (renderTask) は差し替える.
- 状態 (空き・塗り・×・？) × 押した手 (塗る・×・？) の総当たり: なぞりの手と, 行の途中の各状態のマスがどうなるか
- 一つのなぞり = 一つの手. 元に戻すで前の状態へ, やり直すで後の状態へ (印も塗りも. 塗りはサーバの盤と一致する)
- 変わらなかったなぞりは履歴に積まない. 新しい手でやり直しの残りは消える. 履歴の上限. 終わった・一時停止・なぞり中は戻さない
- なぞり・戻す・やり直すを乱数で 300 回混ぜても, 画面の印とサーバの塗りがずれない. 戻し切ると最初の盤

    python tools/test_picross_history.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_slither_history import run_browser  # noqa: E402  時間切れで止まらない起動 (子プロセスごと終わらせる)
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "msedge", "google-chrome", "chromium", "chromium-browser", "chrome",
]

CHECKS = r"""
function eq(a, b, msg) { const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) throw new Error(msg + ': ' + x + ' != ' + y); }
// サーバの代わり: 塗ったマスの集まり. op をそのまま当てる (core/puzzles.py の picross_move と同じく fill / erase は状態を決める)
let SERVER = new Set();
var S = {};
taskMove = async (mv) => {
  const k = mv.r + ',' + mv.c;
  if (mv.op === 'fill') SERVER.add(k); else SERVER.delete(k);
  S.task.view = { kind: 'picross', filled: [...SERVER].map((x) => x.split(',').map(Number)) };
};
renderTask = () => {};
function newT() { SERVER = new Set(); S.task = { view: { kind: 'picross', filled: [] }, xs: new Set(), qs: new Set(), pc: pcHist(), done: false, paused: false, dragging: false, busy: false }; return S.task; }
function st(T, k) { return pcCellState(T, k, T.view.filled.some(([r, c]) => r + ',' + c === k)); }
function srv(k) { return SERVER.has(k); }
function put(T, k, s) {          // 盤に直接状態を置く (サーバにも)
  pcSetMark(T, k, s);
  const [r, c] = k.split(',').map(Number);
  T.view.filled = T.view.filled.filter(([a, b]) => a !== r || b !== c);
  SERVER.delete(k);
  if (s === 'fill') { T.view.filled.push([r, c]); SERVER.add(k); }
}
// なぞり (picrossDrag の mark / end と同じ順): 最初のマスで手を決め, 並んだマスに当てて, 一つの手として積み, 塗り・消しを送る
async function drag(T, keys, pm) {
  const mode = pcStartMode(st(T, keys[0]), pm), changes = [], ops = [];
  for (const k of keys) {
    const s = st(T, k), to = mode && pcNext(mode, s);
    if (!to) continue;
    changes.push([k, s, to]);
    pcSetMark(T, k, to);
    const [r, c] = k.split(',').map(Number);
    if (to === 'fill') ops.push([r, c, 'fill']); else if (s === 'fill') ops.push([r, c, 'erase']);
  }
  if (!mode && keys.length === 1 && T.xs.has(keys[0])) { changes.push([keys[0], 'x', 'empty']); T.xs.delete(keys[0]); }
  pcRecord(T.pc, changes);
  await pcSend(T, ops);
}
async function settle(T) { await T.chain; }
const STATES = ['empty', 'fill', 'x', 'q'], PENS = ['fill', 'x', 'q'];
async function run() {
  // ---- 総当たり: 最初のマス × 押した手 → なぞりの手
  const want = { empty: { fill: 'fill', x: 'x', q: 'q' }, fill: { fill: 'erase', x: null, q: null }, x: { fill: null, x: 'unx', q: null }, q: { fill: 'fill', x: 'x', q: 'unq' } };
  for (const s of STATES) for (const pm of PENS) eq(pcStartMode(s, pm), want[s][pm], `始めの手 ${s}/${pm}`);
  // 手 × 途中のマスの状態 → 後の状態 (同じ手を二度当てても変わらない)
  const next = { fill: { empty: 'fill', q: 'fill' }, erase: { fill: 'empty' }, x: { empty: 'x', q: 'x' }, unx: { x: 'empty' }, q: { empty: 'q' }, unq: { q: 'empty' } };
  for (const m of Object.keys(next)) for (const s of STATES) {
    eq(pcNext(m, s), next[m][s] || null, `${m} を ${s} に`);
    const t = pcNext(m, s);
    if (t) eq(pcNext(m, t), null, `${m} を二度当てても変わらない (${s})`);
  }
  // ---- 総当たり: 5 マスの行 (最初のマスの状態 × 途中に全状態) を各手でなぞる → 元に戻すで全部元, やり直すで全部後. 画面とサーバが一致
  for (const s0 of STATES) for (const pm of PENS) {
    const T = newT(), keys = ['0,0', '0,1', '0,2', '0,3', '0,4'], init = [s0, ...STATES];
    keys.forEach((k, i) => put(T, k, init[i]));
    await drag(T, keys, pm); await settle(T);
    const after = keys.map((k) => st(T, k));
    keys.forEach((k) => eq(srv(k), st(T, k) === 'fill', `サーバと一致 ${s0}/${pm} ${k}`));
    const changed = after.some((x, i) => x !== init[i]);
    eq(T.pc.hist.length, changed ? 1 : 0, `変わったときだけ積む ${s0}/${pm}`);
    if (!changed) continue;
    pcUndo(T); await settle(T);
    eq(keys.map((k) => st(T, k)), init, `元に戻す ${s0}/${pm}`);
    keys.forEach((k, i) => eq(srv(k), init[i] === 'fill', `戻したサーバ ${s0}/${pm} ${k}`));
    pcRedo(T); await settle(T);
    eq(keys.map((k) => st(T, k)), after, `やり直す ${s0}/${pm}`);
    keys.forEach((k, i) => eq(srv(k), after[i] === 'fill', `やり直したサーバ ${s0}/${pm} ${k}`));
  }
  // ---- ？の上書き: 塗る・×で消え, 印は一つだけ
  let T = newT();
  await drag(T, ['1,1'], 'q'); eq(st(T, '1,1'), 'q', '？を付ける');
  await drag(T, ['1,1'], 'x'); eq([T.xs.has('1,1'), T.qs.has('1,1')], [true, false], '×で？は消える');
  pcUndo(T); await settle(T); eq(st(T, '1,1'), 'q', '戻すと？');
  await drag(T, ['1,1'], 'fill'); await settle(T); eq([st(T, '1,1'), T.qs.has('1,1'), srv('1,1')], ['fill', false, true], '塗ると？は消える');
  eq(T.pc.redo.length, 0, '新しい手でやり直しの残りは消える');
  pcUndo(T); await settle(T); eq([st(T, '1,1'), srv('1,1')], ['q', false], '塗りを戻すと？に戻り, サーバも消える');
  await drag(T, ['1,1'], 'q'); eq(st(T, '1,1'), 'empty', '？のマスを？の手で: 消す');
  // ×のマスを塗る手でタップ: ×を外す (一つの手)
  T = newT(); put(T, '2,2', 'x');
  await drag(T, ['2,2'], 'fill'); eq(st(T, '2,2'), 'empty', '×をタップで外す');
  pcUndo(T); eq(st(T, '2,2'), 'x', '外した×を戻す');
  // 何も変わらないなぞりは積まない
  T = newT(); put(T, '0,0', 'fill');
  await drag(T, ['0,0', '0,1'], 'x'); eq(T.pc.hist.length, 0, '塗りから×でなぞっても何もしない');
  eq(pcUndoSt(T.pc), null, '戻すものが無い'); eq(pcRedoSt(T.pc), null, 'やり直すものが無い');
  // 履歴の上限
  T = newT();
  for (let i = 0; i < PC_HIST_MAX + 20; i++) pcRecord(T.pc, [['0,0', i % 2 ? 'x' : 'empty', i % 2 ? 'empty' : 'x']]);
  eq(T.pc.hist.length, PC_HIST_MAX, '履歴の上限');
  // 終わった・一時停止・なぞり中は元に戻さない
  T = newT(); await drag(T, ['0,0'], 'x');
  for (const f of ['done', 'paused', 'dragging']) { T[f] = true; pcUndo(T); eq(st(T, '0,0'), 'x', f + ' のときは戻さない'); T[f] = false; }
  // ---- 乱数で 300 回: なぞり・戻す・やり直すを混ぜても, 画面とサーバがずれず, 戻し切ると最初の盤
  let seed = 7;
  const rnd = (n) => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
  T = newT();
  const all = [];
  for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) all.push(r + ',' + c);
  for (let i = 0; i < 300; i++) {
    const a = rnd(10);
    if (a < 6) {
      const r = rnd(4), c0 = rnd(4), c1 = rnd(4), col = rnd(2), keys = [];
      for (let c = Math.min(c0, c1); c <= Math.max(c0, c1); c++) keys.push(col ? c + ',' + r : r + ',' + c);
      await drag(T, rnd(2) ? keys : [keys[0]], PENS[rnd(3)]);
    } else if (a < 8) pcUndo(T); else pcRedo(T);
    await settle(T);
    all.forEach((k) => eq(srv(k), st(T, k) === 'fill', `乱数 ${i} 回目 ${k}`));
    all.forEach((k) => eq(T.xs.has(k) && T.qs.has(k), false, `印は一つだけ ${i} ${k}`));
  }
  while (T.pc.hist.length) { pcUndo(T); await settle(T); }
  all.forEach((k) => eq(st(T, k), 'empty', '戻し切ると最初の盤 ' + k));
  eq(SERVER.size, 0, '戻し切るとサーバも空');
  return 'OK';
}
"""


def find_browsers():
    out = []
    for b in BROWSERS:
        p = b if os.path.isabs(b) else shutil.which(b)
        if p and os.path.exists(p) and p not in out:
            out.append(p)
    return out


def main():
    brs = find_browsers()
    if not brs:
        print("picross history: SKIP (Edge / Chrome が見つからない)")
        return
    tmp = tempfile.mkdtemp(prefix="kurashi_pch_")
    js = open(os.path.join(ROOT, "static", "puzzles.js"), encoding="utf-8").read()
    page = os.path.join(tmp, "t.html")
    with open(page, "w", encoding="utf-8") as f:
        f.write('<!doctype html><meta charset="utf-8"><body><pre id="out">NOT RUN</pre><script>\n' + js + "\n" + CHECKS +
                "\nrun().then((r) => { document.getElementById('out').textContent = 'RESULT:' + r; },"
                " (e) => { document.getElementById('out').textContent = 'RESULT:FAIL ' + e.message; });\n</script>")
    url = "file:///" + page.replace("\\", "/")
    out = ""
    for k, br in enumerate(brs):
        out = run_browser([br, "--headless", "--disable-gpu", "--no-first-run", "--user-data-dir=" + os.path.join(tmp, "prof%d" % k),
                              "--virtual-time-budget=20000", "--dump-dom", url], timeout=180)
        if "RESULT:" in out and "NOT RUN" not in out:
            break
    shutil.rmtree(tmp, ignore_errors=True)
    i = out.find("RESULT:")
    res = out[i + 7:out.find("</pre>", i)] if i >= 0 else "(結果なし) " + out[:300]
    assert res == "OK", res
    print("picross history: OK")


if __name__ == "__main__":
    main()
    sys.exit(0)
