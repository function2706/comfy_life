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
  S.task.timer = setInterval(taskStats, 500);
  S.task.key = (ev) => {
    const T = S.task;
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

function renderTask(result) {
  const T = S.task;
  if (!T) return;
  const v = T.view;
  $('#task-sub').textContent = `${T.tk.name}（${T.tk.level_name}）・解けたら ${yen(T.tk.base)}前後`;
  const n = v.kind === 'mines' ? v.w : v.kind === 'sudoku' ? 9 : v.n;
  const extra = v.kind === 'picross' ? 1 : 0;
  // 盤に収まるマスの大きさ. 押しにくいほど小さい (30px 未満) ときは「拡大」で大きくして, 盤を縦横にずらして遊べる
  const room = ($('#task-body').clientWidth || Math.min(560, window.innerWidth * 0.96)) - 40;      // 作業画面の中の実際の幅
  const fit = Math.max(18, Math.min(v.kind === 'slide' ? 64 : 34, room / (n + extra * 2.2)));     // 測れない (表示の途中など) ときも小さくしすぎない
  const small = fit < 30;
  const cell = small && T.zoom ? '38px' : `${Math.floor(fit)}px`;
  const grid = h('div', { class: `pz-grid pz-${v.kind}`, style: `--cell:${cell}` });
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
      h('span', { class: 'muted small' }, T.memoMode ? 'メモ: 数字を押すと候補を書く・消す（M キーで切り替え）' : '矢印キーでマスを移動、1〜9 で入力')));
  }
  $('#task-body').replaceChildren(
    result || h('div', { class: 'pz-stats muted' }),
    h('div', { class: 'pz-wrap' + (small && T.zoom ? ' zoom' : '') }, grid),
    ...tools,
    result ? '' : h('div', { class: 'row' }, h('span', { class: 'muted small', style: 'flex:1' }, T.tk.desc),
      h('button', { class: 'btn small ghost', onclick: () => closeTask() }, 'やめる')));
  taskStats();
  function toggle(set, k) { if (set.has(k)) set.delete(k); else set.add(k); renderTask(); }
}
