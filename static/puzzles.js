'use strict';
/* くらし — 内職のパズルの画面 (盤の描画・操作・ドラッグ・数独のメモ・拡大など).
   本体の内職 (static/app.js) と単独版 (static/puzzle_lab.html, tools/puzzle_lab.py) の両方が使う. 同じ操作感を保つため, ここを一つだけにする.

   使う側が用意するもの (グローバル):
     h(tag, attrs, ...kids) / $(sel) / api(path, body) / toast(msg, kind) / yen(n) と, 状態の入れ物 S (S.task を使う).
     画面の要素 #task-body (盤と操作) と #task-sub (見出し).
     finishTask(gaveUp): できあがったとき・やめたときに呼ばれる (結果は renderTask(結果の要素) で盤と一緒に出せる).
     closeTask(): 「やめる」で呼ばれる.
   サーバの API: POST /api/task/move {token, move} → {view, wrong?, short?, solved} (答え合わせはサーバ).
   beginTask(tk) で始める. tk = {token, view, name, level_name, base, par, desc, elapsed}. */

function beginTask(tk) {
  S.task = { tk, view: tk.view, flags: new Set(), xs: new Set(), memo: {}, sel: null, t0: Date.now() - (tk.elapsed || 0) * 1000, done: false, alt: false, busy: false };
  if (tk.view.kind === 'slither') slInit(S.task);
  S.task.timer = setInterval(taskStats, 500);
  S.task.key = (ev) => {
    const T = S.task;
    if (T && !T.done && T.view.kind === 'slither' && (ev.ctrlKey || ev.metaKey)) {      // Ctrl+Z / Ctrl+Y (Ctrl+Shift+Z)
      const k = ev.key.toLowerCase();
      if (k === 'z' && !ev.shiftKey) { ev.preventDefault(); slUndo(T); }
      else if (k === 'y' || (k === 'z' && ev.shiftKey)) { ev.preventDefault(); slRedo(T); }
      return;
    }
    if (!T || T.done || T.view.kind !== 'sudoku') return;
    const mv = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] }[ev.key];
    if (mv) {                                  // 矢印キーでマスを移動 (端では反対側へ)
      ev.preventDefault();
      const [r, c] = T.sel || [4, 4];
      T.sel = [(r + mv[0] + 9) % 9, (c + mv[1] + 9) % 9];
      T.flash = null;
      renderTask();
      return;
    }
    if (ev.key === 'm' || ev.key === 'M') { T.memoMode = !T.memoMode; renderTask(); return; }
    if (!T.sel) return;
    if (/^[1-9]$/.test(ev.key)) { ev.preventDefault(); sudokuInput(+ev.key); }
    if (ev.key === 'Backspace' || ev.key === 'Delete') { delete T.memo[T.sel[0] * 9 + T.sel[1]]; renderTask(); }
  };
  document.addEventListener('keydown', S.task.key);
  renderTask();
}

const fmtSec = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
function taskStats() {
  const T = S.task;
  const el = document.querySelector('.pz-stats');
  if (!T || !el) return;
  const v = T.view;
  const sec = (Date.now() - T.t0) / 1000;
  let rest = '';
  if (v.kind === 'mines') rest = `残り地雷 ${v.n - T.flags.size}`;
  else if (v.kind === 'sudoku') rest = `残り ${v.cur.filter((x) => !x).length} マス`;
  else if (v.kind === 'picross') rest = `塗った ${v.filled.length} / ${v.rows.flat().reduce((a, b) => a + b, 0)} マス`;
  else if (v.kind === 'slither') rest = `線 ${(T.sl ? T.sl.st : v.st).filter((x) => x === 1).length} 本${T.sl && T.sl.trials.length ? `　✎ 仮置き中${T.sl.trials.length > 1 ? `（${T.sl.trials.length} 段目）` : ''}` : ''}`;
  else rest = `${v.moves} 手`;
  el.textContent = `⏱ ${fmtSec(sec)}（目安 ${fmtSec(T.tk.par)}）　ミス ${v.miss}　${rest}`;
}

// マインスイーパの一括開け: 数字マスをダブルクリック・ダブルタップ・左右同時クリック
function chordable(el, go) {
  let last = 0;
  el.addEventListener('dblclick', (ev) => { ev.preventDefault(); go(); });
  el.addEventListener('pointerdown', (ev) => {
    if (ev.buttons === 3) { ev.preventDefault(); go(); return; }        // 左右同時
    if (ev.pointerType === 'touch') { const t = Date.now(); if (t - last < 350) { last = 0; go(); } else last = t; }
  });
  el.addEventListener('contextmenu', (ev) => ev.preventDefault());
}
async function chord(r, c) {
  const T = S.task;
  if (!T || T.done || T.busy) return;
  const flags = [...T.flags].map((k) => k.split(',').map(Number));
  T.busy = true;
  try {
    const res = await api('/api/task/move', { token: T.tk.token, move: { r, c, chord: true, flags } });
    T.view = res.view;
    T.flash = null;
    if (res.short) { T.glow = `${r},${c}`; setTimeout(() => { if (S.task === T) { T.glow = null; renderTask(); } }, 400); }
    renderTask();
    if (res.solved) await finishTask(false);
  } catch (e) { toast(e.message, 'err'); }
  finally { T.busy = false; }
}
// ピクロス: タップで塗る / 塗ったマスはもう一度で消す / ×. ドラッグで同じ行・列をまとめて (最初のマスで決まる:
// 空きから始めれば塗る, 塗ったマスから始めれば消す, ×のマスから始めれば×を消す). 長押し・右クリック・「×印」モードは×.
// 一手ごとの答え合わせはしない (普通のピクロスと同じ). 塗る・消すはサーバへ指を離してから送る
function picrossDrag(grid) {
  const T = S.task;
  const cellAt = (ev) => { const el = document.elementFromPoint(ev.clientX, ev.clientY); return el && el.closest && el.closest('.pc'); };
  const rc = (el) => [+el.dataset.r, +el.dataset.c];
  const state = (el) => (el.classList.contains('fill') ? 'fill' : T.xs.has(rc(el).join(',')) ? 'x' : 'empty');
  let d = null;
  // D: いまのドラッグ. 指を離したとき (end) は d を先に空にするので, そこからは渡したものを使う
  const mark = (el, D = d) => {
    if (D.seen.has(el)) return;
    D.seen.add(el);
    const s = state(el);
    if (D.mode === 'fill' && s === 'empty') { el.classList.add('pending'); D.fill.push([...rc(el), 'fill']); }
    else if (D.mode === 'erase' && s === 'fill') { el.classList.remove('fill'); el.classList.add('pending-erase'); D.fill.push([...rc(el), 'erase']); }
    else if (D.mode === 'x' && s === 'empty') { T.xs.add(rc(el).join(',')); el.textContent = '×'; }
    else if (D.mode === 'unx' && s === 'x') { T.xs.delete(rc(el).join(',')); el.textContent = ''; }
  };
  grid.addEventListener('pointerdown', (ev) => {
    const el = cellAt(ev);
    if (!el || T.done) return;
    ev.preventDefault();
    const s = state(el);
    const xmode = ev.button === 2 || T.alt;
    d = { el, r0: rc(el), axis: null, seen: new Set(), fill: [], moved: false, long: false,
      mode: s === 'x' ? (xmode ? 'unx' : null) : s === 'fill' ? (xmode ? null : 'erase') : xmode ? 'x' : 'fill' };
    if (ev.pointerType === 'touch' && !xmode) {            // 長押し: そのマスに×
      d.timer = setTimeout(() => { if (d && !d.moved) { d.long = true; d.mode = s === 'x' ? 'unx' : 'x'; mark(el); } }, 450);
    }
    try { grid.setPointerCapture(ev.pointerId); } catch (e) { /* 取れなくても動く */ }
  });
  grid.addEventListener('pointermove', (ev) => {
    const el = cellAt(ev);
    if (el) {                                   // 今の行・列の強調 (ヒントとマス)
      const [r, c] = rc(el);
      if (!T.hover || T.hover[0] !== r || T.hover[1] !== c) {
        T.hover = [r, c];
        grid.querySelectorAll('.cur, .hl').forEach((x) => x.classList.remove('cur', 'hl'));
        grid.querySelectorAll('.pc').forEach((x) => { if (+x.dataset.r === r || +x.dataset.c === c) x.classList.add('hl'); });
        const rows = grid.querySelectorAll('.pz-clue.row'), cols = grid.querySelectorAll('.pz-clue.col');
        if (rows[r]) rows[r].classList.add('cur');
        if (cols[c]) cols[c].classList.add('cur');
      }
    }
    if (!d || !el || !d.mode) return;
    const [r, c] = rc(el);
    if (r === d.r0[0] && c === d.r0[1]) return;
    if (!d.moved) { d.moved = true; clearTimeout(d.timer); mark(d.el); }
    d.axis = d.axis || (r === d.r0[0] ? 'row' : c === d.r0[1] ? 'col' : null);
    if (!d.axis) return;
    const [a, b] = d.axis === 'row' ? [d.r0[1], c] : [d.r0[0], r];       // 始めのマスから今のマスまで, 同じ行・列だけ
    for (let i = Math.min(a, b); i <= Math.max(a, b); i++) {
      const sel = d.axis === 'row' ? `.pc[data-r="${d.r0[0]}"][data-c="${i}"]` : `.pc[data-r="${i}"][data-c="${d.r0[1]}"]`;
      const t = grid.querySelector(sel);
      if (t) mark(t);
    }
  });
  const end = async () => {
    if (!d) return;
    const dd = d;
    d = null;
    clearTimeout(dd.timer);
    if (!dd.moved && !dd.long && dd.mode) mark(dd.el, dd);          // タップ
    if (!dd.mode && !dd.moved) { T.xs.delete(dd.r0.join(',')); }      // ×のマスをタップ: ×を外す
    for (const [r, c, op] of dd.fill) {
      if (T.done) break;
      await taskMove({ r, c, op });
    }
    if (!T.done) renderTask();
  };
  grid.addEventListener('pointerup', end);
  grid.addEventListener('pointercancel', end);
  grid.addEventListener('contextmenu', (ev) => ev.preventDefault());
  grid.addEventListener('pointerleave', () => { if (!d) { T.hover = null; grid.querySelectorAll('.cur, .hl').forEach((x) => x.classList.remove('cur', 'hl')); } });
}
// タップ / クリックと, 長押し / 右クリック (旗・×印) を分ける
function pressable(el, tap, alt) {
  let timer = null, fired = false;
  el.addEventListener('pointerdown', (ev) => {
    if (ev.button === 2) return;
    fired = false;
    timer = setTimeout(() => { fired = true; timer = null; alt(); }, 450);
  });
  const cancel = () => { if (timer) { clearTimeout(timer); timer = null; } };
  el.addEventListener('pointerup', (ev) => { if (ev.button === 2) return; const was = !!timer; cancel(); if (was && !fired) tap(); });
  el.addEventListener('pointerleave', cancel);
  el.addEventListener('contextmenu', (ev) => { ev.preventDefault(); if (!fired) alt(); fired = false; });
}

// 数独: 入力 (メモの切り替え, または答え). 正しく入ったら, 同じ行・列・ブロックのメモからその数字を消す
async function sudokuInput(d) {
  const T = S.task;
  if (!T || !T.sel) return;
  const [r, c] = T.sel, i = r * 9 + c;
  if (T.view.cur[i]) return;
  if (T.memoMode) {
    const m = T.memo[i] = T.memo[i] || [];
    const k = m.indexOf(d);
    if (k >= 0) m.splice(k, 1); else m.push(d);
    renderTask();
    return;
  }
  await taskMove({ r, c, v: d });
  if (T.view.cur[i] === d) {
    delete T.memo[i];
    if (!autoMemo()) { renderTask(); return; }       // 同じ行・列・ブロックのメモからその数字を消すのは, 選んだときだけ
    for (const [j, m] of Object.entries(T.memo)) {
      const jr = Math.floor(j / 9), jc = j % 9;
      if (jr === r || jc === c || (Math.floor(jr / 3) === Math.floor(r / 3) && Math.floor(jc / 3) === Math.floor(c / 3))) {
        const k = m.indexOf(d);
        if (k >= 0) m.splice(k, 1);
      }
    }
    renderTask();
  }
}
// 数独: 正しい数字が入ったら, 同じ行・列・ブロックのメモからその数字を自動で消すか (このブラウザで覚える. 既定は消さない)
function autoMemo() { try { return localStorage.getItem('kurashi.sudokuAutoMemo') === '1'; } catch (e) { return false; } }
function setAutoMemo(on) { try { localStorage.setItem('kurashi.sudokuAutoMemo', on ? '1' : '0'); } catch (e) { /* 覚えられなくても動く */ } }
async function taskMove(mv) {
  const T = S.task;
  if (!T || T.done || T.busy) return;
  T.busy = true;
  try {
    const r = await api('/api/task/move', { token: T.tk.token, move: mv });
    T.view = r.view;
    T.flash = r.wrong ? `${mv.r},${mv.c}` : null;
    if (T.view.kind !== 'picross') renderTask();
    if (r.solved) await finishTask(false);
  } catch (e) { toast(e.message, 'err'); }
  finally { T.busy = false; }
}

// ---- スリザーリンク: 点と点の間に線を引いて一つの輪を作る.
// なぞって線 (最初の辺に線があれば消しながら), クリック・タップで × (もう一度で消す. 線をクリックすると消す).
// 元に戻す / やり直す, 仮置き (そこから先の線と×を別の見た目にして, 確定して抜けるか, 消して抜けるか. 仮置きの中でさらに仮置きできる), つながっていない線の色分け.
// 履歴は通常の手 (sl.base) と仮置きの段ごと (sl.trials[i]) に別々の {hist, redo} を持ち, 元に戻す・やり直すは今の段の中だけをたどる.
//   消して抜ける: その段の線と×を入る前に戻し, その段の履歴は捨てる (一つ上の履歴は入る前のまま. やり直しの残りも).
//   確定して抜ける: その段でした変わり分をまとめて一つの手として一つ上の履歴に積む (元に戻すで仮置きごと取り消せる).
// 辺の番号はサーバ (core/slither.py) と同じ: 横の辺 r * w + c, 縦の辺 H + r * (w + 1) + c (H = (h + 1) * w).
const SL_PAL = ['#9c6ade', '#d24b8f', '#3fa6c9', '#4caf6f', '#c9a227', '#e0784a'];      // つながっていない線 (実線. 仮置きは点線)
function slColor() { try { return localStorage.getItem('kurashi.slitherColor') !== '0'; } catch (e) { return true; } }
function setSlColor(on) { try { localStorage.setItem('kurashi.slitherColor', on ? '1' : '0'); } catch (e) { /* 覚えられなくても動く */ } }
const SL_TRIAL_PAL = ['#e0a23a', '#2f9fd0', '#3fae6a', '#c4577f', '#8a6fd1'];      // 仮置きの段ごとの色 (段の上限もこの数)
function slInit(T) { T.sl = slState(T.view.st, T.view); }
// ---- 盤の状態と履歴 (画面にもサーバにも触れない. tools/test_slither_history.py が確かめる)
function slState(st, v) {      // v: 盤の大きさ {h, w} (あれば線のかたまりの色も覚える)
  return { st: st.slice(), base: { hist: [], redo: [] }, trials: [], v: v ? { h: v.h, w: v.w } : null, colors: v ? slColorsFor(v, st, new Map(), null) : new Map() };
}
function slLevel(sl) { return sl.trials.length ? sl.trials[sl.trials.length - 1] : sl.base; }
function slSetSt(sl, e, val, changes) {
  const from = sl.st[e];
  if (from === val) return;
  if (!changes.has(e)) changes.set(e, from);
  for (const tr of sl.trials) if (!tr.orig.has(e)) tr.orig.set(e, from);      // 段ごとに, 入ったときの値
  sl.st[e] = val;
}
// ひとまとまりの操作 (なぞり 1 回・クリック 1 回) を今の段の履歴に積む. 変わった辺 [{e, from, to}] (無ければ null).
// startV: なぞり始めた点 [r, c] (線のかたまりがつながったとき, その点の線の色にそろえる)
function slRecord(sl, changes, startV) {
  const list = [...changes].filter(([e, from]) => sl.st[e] !== from).map(([e, from]) => ({ e, from, to: sl.st[e] }));
  if (!list.length) return null;
  slRecolor(sl, list, sl.colors, startV);
  const lv = slLevel(sl);
  lv.hist.push(list);
  lv.redo = [];
  return list;
}
function slRecolor(sl, list, before, startV) {      // 一手の前後の色を覚える (元に戻す・やり直すで戻す)
  list.colBefore = before;
  if (sl.v) sl.colors = slColorsFor(sl.v, sl.st, before, startV);
  list.colAfter = sl.colors;
}
function slUndoSt(sl) {      // 戻した辺 [[e, 値]] (戻すものが無ければ null)
  const lv = slLevel(sl), a = lv.hist.pop();
  if (!a) return null;
  for (const x of a) sl.st[x.e] = x.from;
  if (a.colBefore) sl.colors = a.colBefore;
  lv.redo.push(a);
  return a.map((x) => [x.e, x.from]);
}
function slRedoSt(sl) {
  const lv = slLevel(sl), a = lv.redo.pop();
  if (!a) return null;
  for (const x of a) sl.st[x.e] = x.to;
  if (a.colAfter) sl.colors = a.colAfter;
  lv.hist.push(a);
  return a.map((x) => [x.e, x.to]);
}
function slTrialBegin(sl) {
  if (sl.trials.length >= SL_TRIAL_PAL.length) return false;
  sl.trials.push({ orig: new Map(), hist: [], redo: [], colors: sl.colors });
  return true;
}
function slTrialEndSt(sl, keep) {      // 変わった辺 [[e, 値]] (サーバに送る)
  const tr = sl.trials.pop();
  if (!tr) return [];
  if (keep) {
    const list = [...tr.orig].filter(([e, o]) => sl.st[e] !== o).map(([e, o]) => ({ e, from: o, to: sl.st[e] }));
    if (list.length) { list.colBefore = tr.colors; list.colAfter = sl.colors; const lv = slLevel(sl); lv.hist.push(list); lv.redo = []; }
    return [];
  }
  const out = [];
  for (const [e, o] of tr.orig) if (sl.st[e] !== o) { sl.st[e] = o; out.push([e, o]); }
  sl.colors = tr.colors;
  return out;
}
function slTrialDepth(sl, e) {      // その辺を変えた, いちばん深い仮置きの段 (1 から. 変えていなければ 0)
  for (let i = sl.trials.length - 1; i >= 0; i--) {
    const o = sl.trials[i].orig;
    if (o.has(e) && o.get(e) !== sl.st[e]) return i + 1;
  }
  return 0;
}
function slEnds(v, e) {      // 辺 → 両端の点 [r, c]
  const H = (v.h + 1) * v.w;
  if (e < H) { const r = Math.floor(e / v.w), c = e % v.w; return [[r, c], [r, c + 1]]; }
  const k = e - H, r = Math.floor(k / (v.w + 1)), c = k % (v.w + 1);
  return [[r, c], [r + 1, c]];
}
function slEdgeBetween(v, a, b) {      // 隣り合う 2 点の間の辺 (隣でなければ null)
  const [r1, c1] = a, [r2, c2] = b;
  if (r1 === r2 && Math.abs(c1 - c2) === 1) return r1 * v.w + Math.min(c1, c2);
  if (c1 === c2 && Math.abs(r1 - r2) === 1) return (v.h + 1) * v.w + Math.min(r1, r2) * (v.w + 1) + c1;
  return null;
}
// 線のかたまりの色 (つながっていない線の色分け). 色はかたまりごとに覚えておき (辺 → 色番号の Map. 0 = 墨, 1.. = SL_PAL),
// 描くたびに付け直さない:
//   - どの色も持たない新しいかたまり → まだ使っていない色 (最初のかたまりは墨)
//   - いくつかの色のかたまりがつながった → つないだ元の色にそろえる (元 = なぞり始めた点に来ていた線の色.
//     無ければ (離れた所から引いた線が 2 つをつないだなど) 辺の多いほうの色)
//   - 一つの色のかたまりが分かれた → その色の辺がいちばん多いほうが色を残し, ほかは新しい色
// 色の割り当ては履歴の一手ごとに前後を持つので, 元に戻す・やり直す・仮置きの取り消しで色も戻る.
function slColorsFor(v, st, prev, startV) {
  const nv = (v.h + 1) * (v.w + 1), par = Array.from({ length: nv }, (_, i) => i);
  const find = (x) => { while (par[x] !== x) { par[x] = par[par[x]]; x = par[x]; } return x; };
  const id = ([r, c]) => r * (v.w + 1) + c;
  st.forEach((s, e) => { if (s === 1) { const [a, b] = slEnds(v, e); par[find(id(a))] = find(id(b)); } });
  const comps = new Map();      // 根 → 辺
  st.forEach((s, e) => { if (s === 1) { const k = find(id(slEnds(v, e)[0])); if (!comps.has(k)) comps.set(k, []); comps.get(k).push(e); } });
  const start = startV ? id(startV) : null;
  // かたまりごとの望む色と, その色の辺の数
  const want = [];
  for (const edges of comps.values()) {
    const cnt = new Map();
    let origin = null;
    for (const e of edges) {
      if (!prev.has(e)) continue;
      const c = prev.get(e);
      cnt.set(c, (cnt.get(c) || 0) + 1);
      if (start !== null && slEnds(v, e).some((p) => id(p) === start)) origin = c;
    }
    let c = null;
    if (cnt.size === 1) c = [...cnt.keys()][0];
    else if (cnt.size > 1) c = origin !== null && cnt.has(origin) ? origin : [...cnt].sort((a, b) => b[1] - a[1] || a[0] - b[0])[0][0];
    want.push({ edges, c, n: c === null ? 0 : cnt.get(c) });
  }
  // 同じ色を望むかたまりが二つ以上 (分かれた): その色の辺の多いほう (同じなら大きいほう) が残す
  const keep = new Map();
  for (const w of want) {
    if (w.c === null) continue;
    const k = keep.get(w.c);
    if (!k || w.n > k.n || (w.n === k.n && w.edges.length > k.edges.length)) keep.set(w.c, w);
  }
  const used = new Map();
  for (const [c] of keep) used.set(c, 1);
  const K = SL_PAL.length + 1;
  const fresh = () => {      // まだ使っていない色 (全部使っていれば, 使っている数の少ない色)
    let best = 0;
    for (let c = 0; c < K; c++) {
      if (!used.has(c)) { best = c; break; }
      if (used.get(c) < used.get(best)) best = c;
    }
    used.set(best, (used.get(best) || 0) + 1);
    return best;
  };
  const out = new Map();
  for (const w of want) {
    const c = w.c !== null && keep.get(w.c) === w ? w.c : fresh();
    for (const e of w.edges) out.set(e, c);
  }
  return out;
}
function slColorOf(colors, e) { const c = colors.get(e); return c ? SL_PAL[(c - 1) % SL_PAL.length] : null; }
function slBoard(T, v, cs, result) {
  const pad = Math.max(10, cs * 0.4), W = v.w * cs + pad * 2, Hh = v.h * cs + pad * 2;
  const NS = 'http://www.w3.org/2000/svg';
  const mk = (tag, a) => { const el = document.createElementNS(NS, tag); for (const k in a) el.setAttribute(k, a[k]); return el; };
  const svg = mk('svg', { class: 'pz-slither-svg', width: W, height: Hh, viewBox: `0 0 ${W} ${Hh}` });
  const X = (c) => pad + c * cs, Y = (r) => pad + r * cs;
  const st = () => (result ? v.st : T.sl.st);
  v.clues.forEach((cl, i) => {
    if (cl === null || cl === undefined) return;
    const t = mk('text', { x: X(i % v.w + 0.5), y: Y(Math.floor(i / v.w) + 0.5), class: 'sl-clue', 'font-size': cs * 0.5 });
    t.textContent = String(cl);
    svg.append(t);
  });
  const layer = mk('g', {});
  svg.append(layer);
  for (let r = 0; r <= v.h; r++) for (let c = 0; c <= v.w; c++) svg.append(mk('circle', { cx: X(c), cy: Y(r), r: Math.max(2, cs * 0.06), class: 'sl-dot' }));
  let d = null;      // なぞっている途中 (下の pointerdown から)
  const draw = () => {
    layer.replaceChildren();
    const s = st(), cols = !result && slColor() ? slColorsFor(v, s, T.sl.colors, d && d.moved ? d.start : null) : null;      // なぞっている間も, 引き終えたときと同じ色
    const col = (e) => (cols ? slColorOf(cols, e) : null);
    s.forEach((x, e) => {
      if (!x) return;
      const [[r1, c1], [r2, c2]] = slEnds(v, e);
      const depth = result ? 0 : slTrialDepth(T.sl, e), trial = depth > 0;
      if (x === 1) {
        const ln = mk('line', { x1: X(c1), y1: Y(r1), x2: X(c2), y2: Y(r2), class: 'sl-line' + (trial ? ' trial' : ''), 'stroke-width': Math.max(3, cs * 0.12) });
        const cc = trial ? SL_TRIAL_PAL[depth - 1] : col(e);
        if (cc) ln.style.stroke = cc;
        layer.append(ln);
      } else {
        const mx = (X(c1) + X(c2)) / 2, my = (Y(r1) + Y(r2)) / 2, d = cs * 0.1;
        for (const [a, b, c, dd] of [[-d, -d, d, d], [-d, d, d, -d]]) {
          const xl = mk('line', { x1: mx + a, y1: my + b, x2: mx + c, y2: my + dd, class: 'sl-x' + (trial ? ' trial' : ''), 'stroke-width': Math.max(1.5, cs * 0.05) });
          if (trial) xl.style.stroke = SL_TRIAL_PAL[depth - 1];
          layer.append(xl);
        }
      }
    });
  };
  draw();
  if (result) return svg;
  // 押した位置 → 盤の座標 (マス単位)
  const pos = (ev) => { const b = svg.getBoundingClientRect(); return [((ev.clientY - b.top) * (Hh / b.height) - pad) / cs, ((ev.clientX - b.left) * (W / b.width) - pad) / cs]; };
  const nearV = ([y, x], lim) => { const r = Math.round(y), c = Math.round(x); return r >= 0 && r <= v.h && c >= 0 && c <= v.w && Math.hypot(y - r, x - c) <= lim ? [r, c] : null; };
  const nearE = ([y, x]) => {     // いちばん近い辺 (辺の近くを押したときだけ)
    const cands = [];
    const rh = Math.round(y), ch = Math.floor(x);
    if (rh >= 0 && rh <= v.h && ch >= 0 && ch < v.w) cands.push([Math.abs(y - rh), rh * v.w + ch]);
    const rv = Math.floor(y), cv = Math.round(x);
    if (rv >= 0 && rv < v.h && cv >= 0 && cv <= v.w) cands.push([Math.abs(x - cv), (v.h + 1) * v.w + rv * (v.w + 1) + cv]);
    cands.sort((a, b) => a[0] - b[0]);
    return cands.length && cands[0][0] <= 0.35 ? cands[0][1] : null;
  };
  svg.addEventListener('pointerdown', (ev) => {
    if (T.done) return;
    ev.preventDefault();
    const p = pos(ev);
    d = { p, last: nearV(p, 0.45), moved: false, mode: null, changes: new Map() };
    d.start = d.last;
    try { svg.setPointerCapture(ev.pointerId); } catch (e) { /* 取れなくても動く */ }
  });
  svg.addEventListener('pointermove', (ev) => {
    if (!d || !d.last) return;
    const v2 = nearV(pos(ev), 0.38);
    if (!v2 || (v2[0] === d.last[0] && v2[1] === d.last[1])) return;
    // まっすぐ離れた点へ飛んだときは, 間の辺を順に
    const steps = [];
    let [r, c] = d.last;
    if (v2[0] === r || v2[1] === c) {
      while (r !== v2[0] || c !== v2[1]) {
        const nr = r + Math.sign(v2[0] - r), nc = c + Math.sign(v2[1] - c);
        steps.push(slEdgeBetween(v, [r, c], [nr, nc]));
        r = nr; c = nc;
      }
    }
    if (!steps.length) return;
    d.moved = true;
    for (const e of steps) {
      if (d.mode === null) d.mode = T.sl.st[e] === 1 ? 0 : 1;      // 最初の辺に線があれば, 消しながらなぞる
      if (d.mode === 0 && T.sl.st[e] !== 1) continue;
      slSet(T, e, d.mode, d.changes);
    }
    d.last = v2;
    draw();
  });
  const end = () => {
    if (!d) return;
    const dd = d;
    d = null;
    if (!dd.moved) {                        // クリック・タップ: × を付ける / 消す (線なら消す)
      const e = nearE(dd.p);
      if (e === null) return;
      const s = T.sl.st[e];
      slSet(T, e, s === 0 ? -1 : 0, dd.changes);
      draw();
    }
    slCommit(T, dd.changes, dd.moved ? dd.start : null);
  };
  svg.addEventListener('pointerup', end);
  svg.addEventListener('pointercancel', end);
  svg.addEventListener('contextmenu', (ev) => ev.preventDefault());
  T.slDraw = draw;
  return svg;
}
function slSet(T, e, val, changes) { slSetSt(T.sl, e, val, changes); }
async function slCommit(T, changes, startV) {
  const list = slRecord(T.sl, changes, startV);
  if (list) await slSend(T, list.map((x) => [x.e, x.to]));
}
async function slSend(T, edges) {
  try {
    const r = await api('/api/task/move', { token: T.tk.token, move: { edges } });
    T.view = Object.assign(r.view, { st: T.sl.st });     // 画面の側の状態が正 (サーバはそれを写したもの)
    taskStats();
    if (T.slDraw) T.slDraw();
    slTools(T);
    if (r.solved) await finishTask(false);
  } catch (e) { toast(e.message, 'err'); }
}
function slUndo(T) { const edges = slUndoSt(T.sl); if (edges) slSend(T, edges); }
function slRedo(T) { const edges = slRedoSt(T.sl); if (edges) slSend(T, edges); }
function slTrialEnd(T, keep) {
  if (!T.sl.trials.length) return;
  slSend(T, slTrialEndSt(T.sl, keep));      // 確定は送るものが無くても, 見た目と並びを直す
}
// 操作の並び (元に戻す・やり直す・仮置き・色分け). 描き直さずに入れ替えられるように
function slTools(T) {
  const box = document.querySelector('.sl-tools');
  if (!box || T.done) return;
  const sl = T.sl, lv = slLevel(sl), n = sl.trials.length;
  const begin = () => { if (slTrialBegin(sl)) { slTools(T); taskStats(); } };
  box.replaceChildren(
    h('button', { class: 'btn small', disabled: !lv.hist.length, title: n ? 'Ctrl+Z（この仮置きの中だけ）' : 'Ctrl+Z', onclick: () => slUndo(T) }, '↶ 元に戻す'),
    h('button', { class: 'btn small', disabled: !lv.redo.length, title: n ? 'Ctrl+Y（この仮置きの中だけ）' : 'Ctrl+Y', onclick: () => slRedo(T) }, '↷ やり直す'),
    ...(n
      ? [h('button', { class: 'btn small primary', title: 'この仮置きでした線と×を残す（まとめて一つの手になり、元に戻すで取り消せる）', onclick: () => slTrialEnd(T, true) }, '✔ 仮置きを確定して抜ける'),
        h('button', { class: 'btn small', title: 'この仮置きでした線と×を消して、入る前に戻す', onclick: () => slTrialEnd(T, false) }, '✖ 仮置きを消して抜ける'),
        h('button', { class: 'btn small', disabled: n >= SL_TRIAL_PAL.length, title: `仮置きの中で、さらに試しに引いてみる（${SL_TRIAL_PAL.length} 段まで。段ごとに色が変わる）`, onclick: begin }, '✎ さらに仮置き')]
      : [h('button', { class: 'btn small', title: '確定できない分かれ道で、試しに引いてみる（ここから先の線と×が別の色になる）', onclick: begin }, '✎ 仮置き')]),
    h('label', { class: 'small muted', title: 'ひと続きの輪の本体とつながっていない線のかたまりを、別の色で出す' },
      h('input', { type: 'checkbox', checked: slColor(), onchange: (ev) => { setSlColor(ev.target.checked); if (T.slDraw) T.slDraw(); } }), ' つながっていない線を色分け'));
}

function renderTask(result) {
  const T = S.task;
  if (!T) return;
  const v = T.view;
  $('#task-sub').textContent = `${T.tk.name}（${T.tk.level_name}）・解けたら ${yen(T.tk.base)}前後`;
  const n = v.kind === 'mines' || v.kind === 'slither' ? v.w : v.kind === 'sudoku' ? 9 : v.n;
  const extra = v.kind === 'picross' ? 1 : 0;
  // 盤に収まるマスの大きさ. 押しにくいほど小さい (30px 未満) ときは「拡大」で大きくして, 盤を縦横にずらして遊べる
  const room = ($('#task-body').clientWidth || Math.min(560, window.innerWidth * 0.96)) - 40;      // 作業画面の中の実際の幅
  const fit = Math.max(18, Math.min(v.kind === 'slide' ? 64 : v.kind === 'slither' ? 48 : 34, room / (n + extra * 2.2 + (v.kind === 'slither' ? 0.8 : 0))));     // 測れない (表示の途中など) ときも小さくしすぎない
  const small = fit < 30;
  const cell = small && T.zoom ? '38px' : `${Math.floor(fit)}px`;
  let grid = h('div', { class: `pz-grid pz-${v.kind}`, style: `--cell:${cell}` });
  const key = (r, c) => `${r},${c}`;
  if (v.kind === 'mines') {
    grid.style.gridTemplateColumns = `repeat(${v.w}, var(--cell))`;
    for (let r = 0; r < v.h; r++) for (let c = 0; c < v.w; c++) {
      const x = v.grid[r][c], flag = T.flags.has(key(r, c));
      const glow = T.glow && x === null && !flag && Math.abs(+T.glow.split(',')[0] - r) <= 1 && Math.abs(+T.glow.split(',')[1] - c) <= 1;
      const el = h('button', { class: 'pz-c' + (x === null ? ' closed' : ' open') + (x === '*' ? ' boom' : '') + (x > 0 ? ' n' + x : '') + (glow ? ' glow' : '') },
        x === '*' ? '💥' : x === 'm' ? '💣' : x > 0 ? String(x) : x === null && flag ? '🚩' : '');
      if (!result && x === null) pressable(el, () => (T.alt ? toggle(T.flags, key(r, c)) : !flag && taskMove({ r, c })), () => toggle(T.flags, key(r, c)));
      if (!result && x > 0) chordable(el, () => chord(r, c));
      grid.append(el);
    }
  } else if (v.kind === 'sudoku') {
    grid.style.gridTemplateColumns = 'repeat(9, var(--cell))';
    const sr = T.sel ? T.sel[0] : -1, sc = T.sel ? T.sel[1] : -1;
    const sv = T.sel ? v.cur[sr * 9 + sc] : 0;            // 選んだマスの数字 (同じ数字を強調)
    for (let i = 0; i < 81; i++) {
      const r = Math.floor(i / 9), c = i % 9, given = v.given[i], val = v.cur[i];
      const sel = r === sr && c === sc;
      const peer = T.sel && !sel && (r === sr || c === sc || (Math.floor(r / 3) === Math.floor(sr / 3) && Math.floor(c / 3) === Math.floor(sc / 3)));
      const memo = !val && T.memo[i] && T.memo[i].length
        ? h('div', { class: 'memo' }, [1, 2, 3, 4, 5, 6, 7, 8, 9].map((d) => h('span', {}, T.memo[i].includes(d) ? String(d) : ''))) : '';
      const el = h('button', { class: 'pz-c sd' + (given ? ' given' : '') + (sel ? ' sel' : '') + (peer ? ' peer' : '')
        + (sv && val === sv ? ' same' : '') + (T.flash === key(r, c) ? ' wrong' : '')
        + (c % 3 === 2 && c < 8 ? ' br' : '') + (r % 3 === 2 && r < 8 ? ' bb' : '') }, val ? String(val) : memo);
      if (!result) el.onclick = () => { T.sel = [r, c]; T.flash = null; renderTask(); };
      grid.append(el);
    }
  } else if (v.kind === 'picross') {
    grid.style.gridTemplateColumns = `max-content repeat(${v.n}, var(--cell))`;
    const filled = new Set(v.filled.map(([r, c]) => key(r, c))), wrong = new Set(v.x.map(([r, c]) => key(r, c)));
    // 塗り方がヒントどおりになった行・列は済み (答えと合っているとは限らない. 一手ごとの答え合わせはしない)
    const runs = (cells) => { const o = []; let k = 0; cells.forEach((x) => { if (x) k++; else if (k) { o.push(k); k = 0; } }); if (k) o.push(k); return o.join(','); };
    const same = (cl, cells) => runs(cells) === cl.filter((x) => x).join(',');
    const rowDone = (r) => same(v.rows[r], [...Array(v.n)].map((_, c) => filled.has(key(r, c))));
    const colDone = (c) => same(v.cols[c], [...Array(v.n)].map((_, r) => filled.has(key(r, c))));
    const [hr, hc] = T.hover || [-1, -1];
    grid.append(h('div', {}));
    v.cols.forEach((cl, c) => grid.append(h('div', { class: 'pz-clue col' + (colDone(c) ? ' done' : '') + (c === hc ? ' cur' : '') },
      cl.map((x) => h('span', {}, String(x))))));
    for (let r = 0; r < v.n; r++) {
      grid.append(h('div', { class: 'pz-clue row' + (rowDone(r) ? ' done' : '') + (r === hr ? ' cur' : '') }, v.rows[r].join(' ')));
      for (let c = 0; c < v.n; c++) {
        const k = key(r, c), f = filled.has(k), w = wrong.has(k), x = T.xs.has(k);
        grid.append(h('button', { class: 'pz-c pc' + (f ? ' fill' : '') + (w ? ' wrong' : '') + (r === hr || c === hc ? ' hl' : '')
          + (c % 5 === 4 && c < v.n - 1 ? ' br' : '') + (r % 5 === 4 && r < v.n - 1 ? ' bb' : ''), 'data-r': r, 'data-c': c },
        w ? '✕' : x && !f ? '×' : ''));
      }
    }
    if (!result) picrossDrag(grid);
  } else if (v.kind === 'slither') {
    grid = h('div', { class: 'pz-slither' }, slBoard(T, v, parseFloat(cell), result));
  } else {
    grid.style.gridTemplateColumns = `repeat(${v.n}, var(--cell))`;
    v.board.forEach((x, i) => {
      const el = h('button', { class: 'pz-c tile' + (x ? '' : ' blank') + (x === i + 1 ? ' home' : '') }, x ? String(x) : '');
      if (!result && x) el.onclick = () => taskMove({ r: Math.floor(i / v.n), c: i % v.n });
      grid.append(el);
    });
  }
  const tools = [];
  if (!result && small) {
    tools.push(h('button', { class: 'btn small' + (T.zoom ? ' primary' : ''), onclick: () => { T.zoom = !T.zoom; renderTask(); } },
      T.zoom ? '🔍 全体を表示' : '🔍 拡大（盤をずらして遊ぶ）'));
  }
  if (!result && v.kind === 'slither') tools.push(h('div', { class: 'row sl-tools', style: 'gap:6px;flex-wrap:wrap' }));
  if (!result && (v.kind === 'mines' || v.kind === 'picross')) {
    tools.push(h('button', { class: 'btn small' + (T.alt ? ' primary' : ''), onclick: () => { T.alt = !T.alt; renderTask(); } },
      v.kind === 'mines' ? '🚩 旗を立てる' : '× 印を付ける'));
  }
  if (!result && v.kind === 'sudoku') {
    const used = (d) => v.cur.filter((x) => x === d).length;        // 9 個そろった数字は使い切り
    tools.push(h('div', { class: 'pz-pad' }, [1, 2, 3, 4, 5, 6, 7, 8, 9].map((d) => h('button', { class: 'btn' + (used(d) >= 9 ? ' done' : ''),
      disabled: !T.sel || used(d) >= 9, title: `${d}（あと ${9 - used(d)} 個）`, onclick: () => sudokuInput(d) }, String(d), h('small', {}, String(9 - used(d)))))));
    tools.push(h('div', { class: 'row', style: 'gap:6px' },
      h('button', { class: 'btn small' + (T.memoMode ? ' primary' : ''), onclick: () => { T.memoMode = !T.memoMode; renderTask(); } }, '✏ メモ'),
      h('button', { class: 'btn small', disabled: !T.sel, onclick: () => { if (T.sel) { delete T.memo[T.sel[0] * 9 + T.sel[1]]; renderTask(); } } }, 'メモを消す'),
      h('label', { class: 'small muted', title: '正しい数字が入ったとき、同じ行・列・ブロックのメモからその数字を消す' },
        h('input', { type: 'checkbox', checked: autoMemo(), onchange: (ev) => setAutoMemo(ev.target.checked) }), ' メモを自動で消す'),
      h('span', { class: 'muted small' }, T.memoMode ? 'メモ: 数字を押すと候補を書く・消す（M キーで切り替え）' : '矢印キーでマスを移動、1〜9 で入力')));
  }
  $('#task-body').replaceChildren(
    result || h('div', { class: 'pz-stats muted' }),
    h('div', { class: 'pz-wrap' + (small && T.zoom ? ' zoom' : '') }, grid),
    ...tools,
    result ? '' : h('div', { class: 'row' }, h('span', { class: 'muted small', style: 'flex:1' }, T.tk.desc),
      h('button', { class: 'btn small ghost', onclick: () => closeTask() }, 'やめる')));
  taskStats();
  if (!result && v.kind === 'slither') slTools(T);
  function toggle(set, k) { if (set.has(k)) set.delete(k); else set.add(k); renderTask(); }
}
