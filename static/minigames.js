'use strict';
/* くらし — ミニゲームの画面 (遊べる一覧・野球拳・あっち向いてホイ・麻雀・盤面ゲーム・ヨット・トランプ・花札).
   本体のゲームタブ (static/app.js) と単独版 (static/minigame_lab.html, tools/minigame_lab.py) の両方が使う. 同じ操作感を保つため, ここを一つだけにする.

   使う側が用意するもの (グローバル):
     h(tag, attrs, ...kids) / $(sel) / toast(msg, kind) と, 状態の入れ物 S.
       S.view.games = {list, current} (サーバの games.view), S.view.name (相手の名前), S.busy, S.gameHint / S.gameResult (出さないなら null).
     画面の要素 #tab-games.
     gameAct(path, body): 操作を送る (POST /api/game/start {game} / /api/game/move {...} / /api/game/quit) → 描き直す.
   renderGames() で描く. */

/* ---------------------------------------------------------------- games tab */
function renderGames() {
  const gv = S.view.games;
  const box = $('#tab-games');
  const cur = gv.current;
  if (!cur) {
    box.replaceChildren(
      S.gameResult ? h('div', { class: 'hint-bubble' }, S.gameResult) : '',
      ...gv.list.map((g) => h('div', { class: 'game-card' },
        h('h4', {}, g.icon, g.name),
        h('p', {}, g.desc),
        h('button', { class: 'btn primary', disabled: !g.ok || S.busy, title: g.ok ? '' : '条件: ' + g.require,
          onclick: () => gameAct('/api/game/start', { game: g.id }) }, g.ok ? 'あそぶ' : '今は遊べません'))),
      gv.list.length ? '' : h('p', { class: 'muted' }, 'ミニゲームがありません（設定 → ミニゲーム）'));
    return;
  }
  if (cur.kind === 'mahjong') { box.replaceChildren(renderMahjong(cur)); return; }
  if (['connect4', 'hex', 'reversi'].includes(cur.kind)) { box.replaceChildren(renderBoard(cur)); return; }
  if (cur.kind === 'yacht') { box.replaceChildren(renderYacht(cur)); return; }
  if (cur.cards) { box.replaceChildren(renderCardGame(cur)); return; }
  const name = S.view.name;
  let score;
  if (cur.kind === 'yakyuken') {
    score = h('div', { class: 'score' },
      h('div', {}, h('div', { class: 'sc-who' }, 'あなたのライフ'),
        h('div', { class: 'val' }, '❤️'.repeat(Math.max(0, cur.lives)) + '🤍'.repeat(Math.max(0, cur.lives_max - cur.lives)))),
      h('div', { class: 'vs' }, `${cur.round}回戦`),
      h('div', {}, h('div', { class: 'sc-who' }, name), h('div', { style: 'font-size:13px' }, cur.stage_label || ''),
        h('div', { class: 'stage-dots' }, Array.from({ length: cur.stages }, (_, i) => h('i', { class: i <= cur.stage ? 'on' : '' })))));
  } else {
    score = h('div', { class: 'score' },
      h('div', {}, h('div', { class: 'sc-who' }, 'あなた'), h('div', { class: 'val' }, cur.me)),
      h('div', { class: 'vs' }, `先取 ${cur.target}`),
      h('div', {}, h('div', { class: 'sc-who' }, name), h('div', { class: 'val' }, cur.her)));
  }
  let q, btns;
  if (cur.phase === 'rps') {
    q = 'じゃん けん……';
    btns = h('div', { class: 'big-btns' }, Object.entries(cur.hands).map(([k, v]) =>
      h('button', { class: 'big-btn', disabled: S.busy, onclick: () => gameAct('/api/game/move', { hand: k }) }, v.icon, h('span', {}, v.name))));
  } else {
    q = cur.phase === 'me_point' ? 'あっち向いて……どこを指す？' : `${name}が指さしてくる！ どっちを向く？`;
    btns = h('div', { class: 'big-btns dirs' }, Object.entries(cur.dirs).map(([k, v]) =>
      h('button', { class: 'big-btn', disabled: S.busy, onclick: () => gameAct('/api/game/move', { dir: k }) }, v.icon, h('span', {}, v.name))));
  }
  box.replaceChildren(h('div', { class: 'board' },
    h('div', { class: 'board-head' }, h('b', {}, cur.name), h('div', { class: 'spacer' }),
      h('button', { class: 'btn ghost', disabled: S.busy, onclick: () => gameAct('/api/game/quit', {}) }, 'やめる')),
    score,
    S.gameHint ? h('div', { class: 'hint-bubble' }, '💭 ' + S.gameHint) : '',
    h('div', { class: 'prompt-q' }, q),
    btns));
}

/* ---- 脱衣の進み具合 (野球拳・麻雀共通) */
function stripScore(cur, mid) {
  return h('div', { class: 'score' },
    h('div', {}, h('div', { class: 'sc-who' }, 'あなたのライフ'),
      h('div', { class: 'val' }, '❤️'.repeat(Math.max(0, cur.lives)) + '🤍'.repeat(Math.max(0, cur.lives_max - cur.lives)))),
    h('div', { class: 'vs' }, mid),
    h('div', {}, h('div', { class: 'sc-who' }, S.view.name), h('div', { style: 'font-size:13px' }, cur.stage_label || ''),
      h('div', { class: 'stage-dots' }, Array.from({ length: cur.stages }, (_, i) => h('i', { class: i <= cur.stage ? 'on' : '' })))));
}

function boardHead(cur, extra) {
  const over = (cur.mj && cur.mj.over) || (cur.board && cur.board.over);
  return h('div', { class: 'board-head' }, h('b', {}, cur.name), extra || '', h('div', { class: 'spacer' }),
    h('button', { class: 'btn ghost', disabled: S.busy, onclick: () => gameAct('/api/game/quit', {}) }, over ? '閉じる' : 'やめる'));
}

/* ---- 麻雀 */
const MJ_NUM = '一二三四五六七八九';
const MJ_HONOR = '東南西北白發中';
// 筒子・索子は柄で見分ける: 筒子は丸 (●) の並び, 索子は竹 (棒) の並び. 本物の牌と同じく, 数は並びの数そのもの.
// 3×3 のどこに置くか (0 が左上, 8 が右下). 角には小さく数字も添える (ひと目で数が読めるように)
const MJ_PIPS = { 1: [4], 2: [1, 7], 3: [0, 4, 8], 4: [0, 2, 6, 8], 5: [0, 2, 4, 6, 8], 6: [0, 2, 3, 5, 6, 8],
  7: [0, 1, 2, 3, 5, 6, 8], 8: [0, 1, 2, 3, 5, 6, 7, 8], 9: [0, 1, 2, 3, 4, 5, 6, 7, 8] };
const MJ_RED = { 1: [4], 5: [4], 7: [0, 1, 2], 9: [3, 4, 5] };          // 赤い粒 (本物の牌の配色にならう)
// 牌・札の絵 (static/img/. 麻雀牌は FluffyStuff/riichi-mahjong-tiles (CC0), 花札は Wikimedia Commons の一式 (CC BY-SA 4.0)).
// 絵が読み込めたら絵を出し (has-img), 読み込めなければ下の柄・文字の表示のまま
const MJ_IMG = ['Man', 'Pin', 'Sou'];
const MJ_HONOR_IMG = ['Ton', 'Nan', 'Shaa', 'Pei', 'Haku', 'Hatsu', 'Chun'];
function withImg(el, src) {
  const img = h('img', { class: 'face', alt: '', draggable: 'false', src });
  img.addEventListener('load', () => el.classList.add('has-img'));
  img.addEventListener('error', () => img.remove());
  el.append(img);
  return el;
}
function tileEl(t, o = {}) {
  const cls0 = `tile${o.small ? ' small' : ''}${o.hl ? ' hl' : ''}${o.dim ? ' dim' : ''}${o.drawn ? ' drawn' : ''}`;
  const attrs = (cls) => ({ class: `${cls0} ${cls}`, disabled: o.disabled, onclick: o.onclick, title: o.title || '' });
  const tag = o.onclick ? 'button' : 'div';
  if (t >= 27) return withImg(h(tag, attrs('z' + (t - 26)), h('span', { class: 't-top' }, MJ_HONOR[t - 27])), `/static/img/mahjong/${MJ_HONOR_IMG[t - 27]}.svg`);
  const n = t % 9 + 1, s = Math.floor(t / 9);
  const src = `/static/img/mahjong/${MJ_IMG[s]}${n}.svg`;
  if (s === 0) return withImg(h(tag, attrs('m'), h('span', { class: 't-top' }, MJ_NUM[n - 1]), h('span', { class: 't-bot' }, '萬')), src);
  const kind = s === 1 ? 'p' : 's';
  const pos = MJ_PIPS[n], red = MJ_RED[n] || [];
  return withImg(h(tag, attrs(kind), h('span', { class: 't-num' }, String(n)),
    h('span', { class: `t-pips n${n}` }, Array.from({ length: 9 }, (_, i) => h('i', { class: pos.includes(i) ? (red.includes(i) ? 'on red' : 'on') : '' }))),
    h('span', { class: 'sr' }, `${n}${kind === 'p' ? '筒' : '索'}`)), src);
}
const tileBack = (small) => h('div', { class: 'tile back' + (small ? ' small' : '') });     // 裏は今の色のまま (絵の裏は赤が強いので)

function renderMahjong(cur) {
  const m = cur.mj, me = S.view.name;
  const turn = m.phase === 'p_turn' && !S.busy;
  const riichiMode = S.mjRiichi && turn && m.riichi_tiles.length;
  const discard = (t) => {
    const riichi = riichiMode;
    S.mjRiichi = false;
    gameAct('/api/game/move', { act: riichi ? 'riichi' : 'discard', tile: t });
  };
  const handTile = (t, drawn) => {
    const okRiichi = m.riichi_tiles.includes(t);
    const locked = m.riichi.p && !drawn;   // リーチ後はツモ切りのみ
    return tileEl(t, { drawn, onclick: () => discard(t), disabled: !turn || locked || (riichiMode && !okRiichi),
      hl: riichiMode && okRiichi, title: drawn ? 'ツモ牌' : '' });
  };
  const river = (who) => h('div', { class: 'river' }, (m.river[who] || []).map((t, i) =>
    tileEl(t, { small: true, hl: m.last && m.last.who === who && i === m.river[who].length - 1 })));
  let controls;
  if (m.phase === 'hand_end') {
    const r = m.result;
    const who = r.winner === 'p' ? 'あなた' : r.winner === 'a' ? me : null;
    controls = h('div', { class: 'mj-result' },
      h('div', { class: 'mj-res-head' }, who ? `${who}の${r.how}！` : '流局',
        r.han ? h('span', { class: 'han' }, r.yakuman ? '役満' : `${r.han}翻`) : ''),
      r.yaku && r.yaku.length ? h('div', { class: 'yaku' }, r.yaku.map(([n, v]) => h('span', {}, `${n} ${v >= 13 ? '' : v}`))) : '',
      h('div', { class: 'sc-who', style: 'margin:8px 0 4px' }, `${me}の手牌`),
      h('div', { class: 'hand small-hand' }, (m.her_hand || []).map((t) => tileEl(t, { small: true, hl: t === r.win_tile && r.winner === 'a' }))),
      h('div', { class: 'row', style: 'margin-top:10px;justify-content:center' },
        m.over ? h('button', { class: 'btn primary', disabled: S.busy, onclick: () => gameAct('/api/game/move', { act: 'next' }) },
          m.over === 'win' ? '🎉 勝利！ 閉じる' : '😵 敗北… 閉じる')
          : h('button', { class: 'btn primary', disabled: S.busy, onclick: () => gameAct('/api/game/move', { act: 'next' }) }, '次の局へ')));
  } else if (m.phase === 'p_ron') {
    controls = h('div', { class: 'row', style: 'justify-content:center' },
      h('span', { class: 'prompt-q' }, `${me}の捨て牌でロンできます`),
      h('button', { class: 'btn primary', disabled: S.busy, onclick: () => gameAct('/api/game/move', { act: 'ron' }) }, 'ロン！'),
      h('button', { class: 'btn', disabled: S.busy, onclick: () => gameAct('/api/game/move', { act: 'skip' }) }, '見送り'));
  } else {
    controls = h('div', { class: 'row', style: 'justify-content:center' },
      m.can_tsumo ? h('button', { class: 'btn primary', disabled: S.busy, onclick: () => gameAct('/api/game/move', { act: 'tsumo' }) }, 'ツモ！') : '',
      !m.riichi.p && m.riichi_tiles.length ? h('button', { class: 'btn' + (riichiMode ? ' primary' : ''), disabled: !turn,
        onclick: () => { S.mjRiichi = !S.mjRiichi; renderGames(); } }, riichiMode ? 'リーチ：切る牌を選ぶ（取消）' : 'リーチ') : '',
      h('span', { class: 'muted small' }, m.riichi.p ? 'リーチ中（和了れる牌が来たらツモ）' : turn ? '切る牌を選んでください' : '…'));
  }
  return h('div', { class: 'board mj' },
    boardHead(cur, h('span', { class: 'muted small' }, `第${m.hand_no}局・親：${m.dealer === 'p' ? 'あなた' : me}`)),
    stripScore(cur, `残り${m.wall}枚`),
    h('div', { class: 'mj-row' }, h('span', { class: 'sc-who' }, me), m.riichi.a ? h('span', { class: 'riichi-badge' }, 'リーチ') : '',
      h('div', { class: 'hand backs' }, Array.from({ length: m.her_count }, () => tileBack(true)))),
    river('a'),
    h('div', { class: 'mj-center' }, h('span', { class: 'sc-who' }, 'ドラ表示'), (m.dora || []).map((t) => tileEl(t, { small: true }))),
    river('p'),
    h('div', { class: 'mj-row' }, h('span', { class: 'sc-who' }, 'あなた'), m.riichi.p ? h('span', { class: 'riichi-badge' }, 'リーチ') : ''),
    h('div', { class: 'hand' }, m.hand.map((t) => handTile(t, false)), m.drawn != null ? h('span', { class: 'gap' }) : '',
      m.drawn != null ? handTile(m.drawn, true) : ''),
    S.gameHint ? h('div', { class: 'hint-bubble', style: 'margin-top:10px' }, '💭 ' + S.gameHint) : '',
    h('div', { style: 'margin-top:10px' }, controls));
}

/* ---- 盤面ゲーム */
function renderBoard(cur) {
  const b = cur.board, name = S.view.name;
  const can = !S.busy && !b.over;
  const move = (body) => gameAct('/api/game/move', body);
  let grid, legend;
  if (cur.kind === 'connect4') {
    legend = h('div', { class: 'legend' }, h('i', { class: 'disc me' }), 'あなた　', h('i', { class: 'disc her' }), name,
      h('span', { style: 'margin-left:auto' }, '▼ の列に上から落とす'));
    const full = (c) => b.cells[(b.h - 1) * b.w + c] !== 0;
    const fresh = S.c4Seen !== JSON.stringify(b.last);   // 新しく置かれたコマだけ落下アニメーション
    S.c4Seen = JSON.stringify(b.last);
    // 投入口: マウスを乗せた列の上に, これから落とすコマを浮かべる
    const slots = Array.from({ length: b.w }, (_, c) => h('button', {
      class: 'c4-slot', disabled: !can || full(c), title: `${c + 1}列目に落とす`, onclick: () => move({ col: c }),
    }, h('i', { class: 'disc me ghost' }), h('span', {}, '▼')));
    const cells = [];
    for (let r = b.h - 1; r >= 0; r--) {
      for (let c = 0; c < b.w; c++) {
        const i = r * b.w + c, v = b.cells[i];
        const order = b.last.indexOf(i);
        const drop = fresh && order >= 0;
        cells.push(h('button', { class: 'c4-cell', disabled: !can || full(c), onclick: () => move({ col: c }),
          onmouseenter: () => slots[c].classList.add('hover'), onmouseleave: () => slots[c].classList.remove('hover') },
        v ? h('i', {
          class: `disc ${v === 1 ? 'me' : 'her'}${order >= 0 ? ' last' : ''}${(b.line || []).includes(i) ? ' win' : ''}${drop ? ' drop' : ''}`,
          style: drop ? `--fall:${b.h - r};animation-delay:${order * 0.45}s` : null,
        }) : ''));
      }
    }
    grid = h('div', {}, h('div', { class: 'c4-slots', style: `grid-template-columns:repeat(${b.w},1fr)` }, slots),
      h('div', { class: 'c4', style: `grid-template-columns:repeat(${b.w},1fr)` }, cells));
  } else if (cur.kind === 'reversi') {
    legend = h('div', { class: 'legend' }, h('i', { class: 'disc black' }), `あなた ${b.me}　`, h('i', { class: 'disc white' }), `${name} ${b.her}`);
    grid = h('div', { class: 'rv' }, b.cells.map((v, i) => {
      const legal = b.legal.includes(i);
      return h('button', { class: 'rv-cell' + (legal && can ? ' legal' : ''), disabled: !can || !legal, onclick: () => move({ cell: i }) },
        v ? h('i', { class: `disc ${v === 1 ? 'black' : 'white'}${b.last.includes(i) ? ' last' : ''}` }) : '');
    }));
  } else {
    legend = h('div', { class: 'legend' }, h('i', { class: 'disc me' }), 'あなた（上下をつなぐ）　', h('i', { class: 'disc blue' }), `${name}（左右）`);
    grid = hexSvg(b, can, (i) => move({ cell: i }));
  }
  const res = b.over ? h('div', { class: 'hint-bubble', style: 'text-align:center' },
    { win: '🎉 あなたの勝ち！', lose: '😵 あなたの負け…', draw: '🤝 引き分け' }[b.over]) : '';
  return h('div', { class: 'board' }, boardHead(cur), legend, res,
    S.gameHint && !b.over ? h('div', { class: 'hint-bubble' }, '💭 ' + S.gameHint) : '', grid);
}

/* ---- ヨット */
const PIPS = { 1: [4], 2: [0, 8], 3: [0, 4, 8], 4: [0, 2, 6, 8], 5: [0, 2, 4, 6, 8], 6: [0, 2, 3, 5, 6, 8] };
function dieEl(v, o = {}) {
  return h(o.onclick ? 'button' : 'div', {
    class: `die${o.small ? ' small' : ''}${o.held ? ' held' : ''}${v ? '' : ' blank'}${o.roll ? ' roll' : ''}`,
    onclick: o.onclick, disabled: o.disabled, title: o.title || '',
  }, v ? Array.from({ length: 9 }, (_, i) => h('i', { class: PIPS[v].includes(i) ? 'pip' : '' })) : h('span', {}, '?'));
}

function renderYacht(cur) {
  const y = cur.yacht, name = S.view.name;
  const key = JSON.stringify([y.dice, y.rolls_left, y.round]);
  if (S.ytKey !== key) {   // 出目が変わったらキープを引き継ぎ, 新しいターンなら解除
    S.ytHold = y.dice ? (y.hold || [false, false, false, false, false]).slice() : [false, false, false, false, false];
    S.ytAnimUntil = S.ytKey ? Date.now() + 400 : 0;   // 振った直後だけ転がす
    S.ytKey = key;
  }
  const rolling = Date.now() < (S.ytAnimUntil || 0);
  const myTurn = !S.busy && !y.over;
  const dice = (y.dice || [0, 0, 0, 0, 0]).map((v, i) => dieEl(v, {
    held: S.ytHold[i], roll: v && rolling && !S.ytHold[i],
    disabled: !myTurn || !y.dice || y.rolls_left === 0,
    title: y.dice ? (S.ytHold[i] ? 'キープ中（クリックで解除）' : 'クリックでキープ') : '',
    onclick: () => { S.ytHold[i] = !S.ytHold[i]; renderGames(); },
  }));
  const her = y.her ? h('div', { class: 'yt-her' },
    h('div', { class: 'sc-who' }, `${name}の番`),
    h('div', { class: 'yt-steps' }, y.her.steps.map((s, k) => h('div', { class: 'yt-step' },
      h('span', { class: 'muted small' }, `${k + 1}投目`), s.dice.map((v, i) => dieEl(v, { small: true, held: k > 0 && s.hold[i] }))))),
    h('div', {}, `→ ${y.her.name} に `, h('b', {}, `${y.her.score}点`))) : '';
  const t = y.totals;
  const row = (c) => {
    const mine = y.sheet.p[c], hers = y.sheet.a[c];
    const pv = y.preview[c];
    const cell = mine !== undefined ? h('td', { class: 'done' }, mine)
      : pv !== undefined ? h('td', {}, h('button', { class: 'yt-pick' + (pv ? ' good' : ''), disabled: !myTurn,
        onclick: () => gameAct('/api/game/move', { act: 'score', cat: c }) }, pv))
        : h('td', { class: 'muted' }, '');
    return h('tr', {}, h('th', {}, y.names[c]), cell, h('td', { class: hers !== undefined ? 'done' : '' }, hers ?? ''));
  };
  const upper = y.cats.slice(0, 6), lower = y.cats.slice(6);
  const table = h('table', { class: 'yt-sheet' },
    h('thead', {}, h('tr', {}, h('th', {}, '役'), h('th', {}, 'あなた'), h('th', {}, name))),
    h('tbody', {}, upper.map(row),
      h('tr', { class: 'sub' }, h('th', {}, `小計（${y.bonus_line}で+${y.bonus}）`),
        h('td', {}, `${t.p.upper}${t.p.bonus ? ' +' + t.p.bonus : ''}`), h('td', {}, `${t.a.upper}${t.a.bonus ? ' +' + t.a.bonus : ''}`)),
      lower.map(row),
      h('tr', { class: 'total' }, h('th', {}, '合計'), h('td', {}, t.p.total), h('td', {}, t.a.total))));
  const res = y.over ? h('div', { class: 'hint-bubble', style: 'text-align:center' },
    { win: '🎉 あなたの勝ち！', lose: '😵 あなたの負け…', draw: '🤝 引き分け' }[y.over] + `（${t.p.total} 対 ${t.a.total}）`) : '';
  return h('div', { class: 'board' },
    boardHead(Object.assign({}, cur, { board: { over: y.over } }), h('span', { class: 'muted small' }, `${Math.min(y.round, 12)} / 12 ラウンド`)),
    res, her,
    S.gameHint && !y.over ? h('div', { class: 'hint-bubble' }, '💭 ' + S.gameHint) : '',
    y.over ? '' : h('div', { class: 'yt-dice' }, dice),
    y.over ? '' : h('div', { class: 'row', style: 'justify-content:center;margin:8px 0 12px' },
      h('button', { class: 'btn primary', disabled: !myTurn || y.rolls_left === 0,
        onclick: () => gameAct('/api/game/move', { act: 'roll', hold: S.ytHold }) },
      y.dice ? `振り直す（あと${y.rolls_left}回）` : 'サイコロを振る'),
      h('span', { class: 'muted small' }, y.dice ? (y.rolls_left ? '残すサイコロをクリック → 振り直す、または役を選ぶ' : '役を選んでください') : '')),
    table);
}

/* ---- トランプ・花札 */
const SUIT_SYM = { S: '♠', H: '♥', D: '♦', C: '♣' };
function pcardEl(c, o = {}) {
  if (!c || c === '??' || o.back) return h('div', { class: 'pcard back' + (o.small ? ' small' : ''), onclick: o.onclick });
  const joker = c === 'XJ';
  const r = c[0] === 'T' ? '10' : c[0], s = c[1];
  return h(o.onclick ? 'button' : 'div', {
    class: `pcard${joker ? ' joker' : ''}${'HD'.includes(s) && !joker ? ' red' : ''}${o.small ? ' small' : ''}${o.sel ? ' sel' : ''}${o.hl ? ' hl' : ''}${o.dim ? ' dim' : ''}${o.peek ? ' her-shown' : ''}`,
    onclick: o.onclick, disabled: o.disabled, title: o.title || '',
  }, joker ? [h('span', { class: 'pc-r' }, '🃏'), h('span', { class: 'pc-s' }, 'JOKER')]
    : [h('span', { class: 'pc-r' }, r), h('span', { class: 'pc-s' }, SUIT_SYM[s])]);
}

const HF_MONTH = ['松', '梅', '桜', '藤', '菖蒲', '牡丹', '萩', '芒', '菊', '紅葉', '柳', '桐'];
const HF_EMOJI = ['🌲', '🌺', '🌸', '🍇', '💠', '🌹', '🌿', '🌾', '🌼', '🍁', '☔', '🍃'];
// [種類, 名前, 絵] (サーバ側 hanafuda.CARDS と同じ並び)
const HF_CARDS = [
  ['h', '鶴', '🦢'], ['t', '赤短', '📜'], ['k', ''], ['k', ''], ['n', '鶯', '🐦'], ['t', '赤短', '📜'], ['k', ''], ['k', ''],
  ['h', '幕', '🎪'], ['t', '赤短', '📜'], ['k', ''], ['k', ''], ['n', '不如帰', '🐦'], ['t', '短冊', '📜'], ['k', ''], ['k', ''],
  ['n', '八橋', '🌉'], ['t', '短冊', '📜'], ['k', ''], ['k', ''], ['n', '蝶', '🦋'], ['t', '青短', '📘'], ['k', ''], ['k', ''],
  ['n', '猪', '🐗'], ['t', '短冊', '📜'], ['k', ''], ['k', ''], ['h', '月', '🌕'], ['n', '雁', '🦆'], ['k', ''], ['k', ''],
  ['n', '盃', '🍶'], ['t', '青短', '📘'], ['k', ''], ['k', ''], ['n', '鹿', '🦌'], ['t', '青短', '📘'], ['k', ''], ['k', ''],
  ['h', '小野道風', '☂️'], ['n', '燕', '🐦'], ['t', '短冊', '📜'], ['k', ''], ['h', '鳳凰', '🦚'], ['k', ''], ['k', ''], ['k', ''],
];
const HF_KIND = { h: '光', n: 'タネ', t: '短冊', k: 'カス' };
function hfEl(id, o = {}) {
  if (o.back) return withImg(h('div', { class: 'hcard back' + (o.small ? ' small' : '') }), '/static/img/hanafuda/back.svg');
  const m = Math.floor(id / 4), [k, name, pic] = HF_CARDS[id];
  const red = name === '赤短', blue = name === '青短';
  return withImg(h(o.onclick ? 'button' : 'div', {
    class: `hcard k-${k}${red ? ' aka' : ''}${blue ? ' ao' : ''}${o.small ? ' small' : ''}${o.hl ? ' hl' : ''}${o.dim ? ' dim' : ''}`,
    onclick: o.onclick, disabled: o.disabled, title: `${HF_MONTH[m]}（${m + 1}月）${name ? 'に' + name : 'のカス'}・${HF_KIND[k]}`,
  }, h('span', { class: 'hc-m' }, HF_MONTH[m]), h('span', { class: 'hc-pic' }, pic || HF_EMOJI[m]),
  h('span', { class: 'hc-n' }, name || 'カス')), `/static/img/hanafuda/hf${String(id).padStart(2, '0')}.svg`);
}

function raceScore(cur, mid, unit) {
  return h('div', { class: 'score' },
    h('div', {}, h('div', { class: 'sc-who' }, 'あなた'), h('div', { class: 'val' }, `${cur.me}${unit || ''}`)),
    h('div', { class: 'vs' }, mid),
    h('div', {}, h('div', { class: 'sc-who' }, S.view.name), h('div', { class: 'val' }, `${cur.her}${unit || ''}`)));
}

function renderCardGame(cur) {
  const c = cur.cards, name = S.view.name;
  const act = (body) => gameAct('/api/game/move', body);
  const busy = S.busy;
  const nextBtn = () => h('div', { class: 'row', style: 'justify-content:center;margin-top:10px' },
    h('button', { class: 'btn primary', disabled: busy, onclick: () => act({ act: 'next' }) },
      c.over ? ({ win: '🎉 勝利！ 閉じる', lose: '😵 敗北… 閉じる', draw: '🤝 引き分け 閉じる' }[c.over] || '閉じる') : '次の勝負へ'));
  const head = boardHead(Object.assign({}, cur, { board: { over: c.over } }),
    h('span', { class: 'muted small' }, c.round ? `第${c.round}${cur.kind === 'koikoi' ? '局' : '回戦'}` : ''));
  const score = cur.strip ? stripScore(cur, '')
    : cur.kind === 'koikoi' ? raceScore(cur, `${c.round}/${c.rounds} 局`, '文')
      : cur.kind === 'blackjack' ? raceScore(cur, `先に${cur.target}勝`, '勝')
        : cur.kind === 'concentration' ? raceScore({ me: c.me, her: c.her }, '', '組') : '';
  const hint = S.gameHint ? h('div', { class: 'hint-bubble' }, '💭 ' + S.gameHint) : '';
  let body;

  if (cur.kind === 'poker') {
    S.pkSel = S.pkSel || [];
    if (c.phase !== 'exchange') S.pkSel = [];
    const r = c.result;
    body = [
      h('div', { class: 'sc-who' }, `${name}の手札${c.her_ex != null && !r ? `（${c.her_ex}枚交換）` : ''}`),
      h('div', { class: 'cardrow' }, c.her_hand ? c.her_hand.map((x) => pcardEl(x)) : Array.from({ length: c.her_count }, () => pcardEl(null))),
      r ? h('div', { class: 'card-res' }, r.fold ? `${name}が降りた！（${name}: ${r.her}）` :
        `あなた: ${r.my} ／ ${name}: ${r.her} → ${r.winner === 'p' ? 'あなたの勝ち' : r.winner === 'a' ? `${name}の勝ち` : '引き分け'}${r.steps === 2 ? '（倍）' : ''}`) : '',
      h('div', { class: 'sc-who', style: 'margin-top:8px' }, `あなたの手札：${c.my_name}`),
      h('div', { class: 'cardrow room' }, c.hand.map((x, i) => pcardEl(x, {
        sel: S.pkSel.includes(i),
        onclick: c.phase === 'exchange' && !busy ? () => { S.pkSel = S.pkSel.includes(i) ? S.pkSel.filter((j) => j !== i) : [...S.pkSel, i]; renderGames(); } : null,
        title: c.phase === 'exchange' ? 'クリックで交換する札に選ぶ' : '',
      }))),
      c.phase === 'exchange' ? h('div', { class: 'row', style: 'justify-content:center;margin-top:8px' },
        h('span', { class: 'muted small' }, '交換する札を選んで（選ばなければそのまま）'),
        h('button', { class: 'btn primary', disabled: busy, onclick: () => { const d = S.pkSel; S.pkSel = []; act({ act: 'exchange', discard: d }); } },
          S.pkSel.length ? `${S.pkSel.length}枚交換する` : 'このまま')) : '',
      c.phase === 'bet' ? h('div', { class: 'row', style: 'justify-content:center;margin-top:8px' },
        h('button', { class: 'btn primary', disabled: busy, onclick: () => act({ act: 'call' }) }, '勝負！'),
        h('button', { class: 'btn', disabled: busy, onclick: () => act({ act: 'raise' }), title: `受けて立たれたら2段階。${name}が降りることも` }, '倍プッシュ')) : '',
      c.phase === 'round_end' ? nextBtn() : '',
    ];
  } else if (cur.kind === 'blackjack') {
    const r = c.result;
    body = [
      h('div', { class: 'sc-who' }, `ディーラー（${name}）：${c.dealer_value}${c.phase === 'round_end' ? '' : ' + ?'}`),
      h('div', { class: 'cardrow' }, c.dealer.map((x) => pcardEl(x))),
      r ? h('div', { class: 'card-res' }, `${r.why} → ${r.winner === 'p' ? 'あなたの勝ち' : r.winner === 'a' ? 'ディーラーの勝ち' : '引き分け'}${r.steps === 2 ? '（倍）' : ''}`) : '',
      h('div', { class: 'sc-who', style: 'margin-top:8px' }, `あなた：${c.value}${c.value > 21 ? '（バースト）' : ''}`),
      h('div', { class: 'cardrow' }, c.hand.map((x) => pcardEl(x))),
      c.phase === 'play' ? h('div', { class: 'row', style: 'justify-content:center;margin-top:8px' },
        h('button', { class: 'btn primary', disabled: busy, onclick: () => act({ act: 'hit' }) }, 'ヒット'),
        h('button', { class: 'btn', disabled: busy, onclick: () => act({ act: 'stand' }) }, 'スタンド'),
        c.can_double ? h('button', { class: 'btn', disabled: busy, onclick: () => act({ act: 'double' }), title: '1枚だけ引いて勝負。勝ち負けが倍' }, 'ダブル') : '') : '',
      c.phase === 'round_end' ? nextBtn() : '',
    ];
  } else if (cur.kind === 'koikoi') {
    const choosing = c.choosing != null;
    const capRow = (who) => {
      const caps = c.caps[who], groups = { h: [], n: [], t: [], k: [] };
      caps.forEach((id) => groups[HF_CARDS[id][0]].push(id));
      return h('div', { class: 'caps' }, ['h', 'n', 't', 'k'].map((k) => groups[k].length ? h('div', { class: 'cap-g' },
        h('span', { class: 'cap-l' }, `${HF_KIND[k]}${groups[k].length}`), h('div', { class: 'cap-cards' }, groups[k].map((id) => hfEl(id, { small: true })))) : ''),
      c.yaku[who].length ? h('div', { class: 'yaku' }, c.yaku[who].map(([n, p]) => h('span', {}, `${n} ${p}文`))) : '');
    };
    const r = c.result;
    body = [
      h('div', { class: 'mj-row' }, h('span', { class: 'sc-who' }, `${name}${c.dealer === 'a' ? '（親）' : ''}`),
        c.koi.a ? h('span', { class: 'riichi-badge' }, `こいこい×${c.koi.a}`) : '',
        h('div', { class: 'cardrow tight' }, Array.from({ length: c.her_count }, () => hfEl(0, { back: true, small: true })))),
      capRow('a'),
      h('div', { class: 'field' }, h('div', { class: 'sc-who' }, `場（山 ${c.deck}枚）`),
        h('div', { class: 'cardrow wrap' }, c.field.map((id) => hfEl(id, choosing ? {
          hl: c.targets.includes(id), dim: !c.targets.includes(id),
          onclick: c.targets.includes(id) && !busy ? () => act({ act: 'target', target: id }) : null,
        } : {})))),
      choosing ? h('div', { class: 'row', style: 'justify-content:center' },
        h('span', { class: 'prompt-q' }, c.phase === 'p_choose_draw' ? '山から引いた札：' : '出す札：'), hfEl(c.choosing, { small: true }),
        h('span', { class: 'prompt-q' }, 'どちらを取る？（光っている札をクリック）'),
        c.phase === 'p_choose_hand' ? h('button', { class: 'btn ghost', onclick: () => act({ act: 'cancel' }) }, 'やめる') : '') : '',
      capRow('p'),
      h('div', { class: 'mj-row' }, h('span', { class: 'sc-who' }, `あなた${c.dealer === 'p' ? '（親）' : ''}`),
        c.koi.p ? h('span', { class: 'riichi-badge' }, `こいこい×${c.koi.p}`) : ''),
      h('div', { class: 'cardrow wrap' }, c.hand.map((id) => {
        const m = c.field.some((f) => Math.floor(f / 4) === Math.floor(id / 4));
        return hfEl(id, { hl: c.phase === 'p_play' && m, onclick: c.phase === 'p_play' && !busy ? () => act({ act: 'play', card: id }) : null,
          disabled: c.phase !== 'p_play' || busy });
      })),
      c.phase === 'p_koi' ? h('div', { class: 'koi-box' },
        h('div', {}, `役ができました！ いま ${c.points.p}文`),
        h('div', { class: 'row', style: 'justify-content:center' },
          h('button', { class: 'btn primary', disabled: busy, onclick: () => act({ act: 'stop' }) }, 'あがり'),
          h('button', { class: 'btn', disabled: busy, onclick: () => act({ act: 'koi' }), title: '続けて点を伸ばす。ただし相手にあがられると倍取られる' }, 'こいこい'))) : '',
      r ? h('div', { class: 'card-res' }, r.winner ? `${r.winner === 'p' ? 'あなた' : name}のあがり：${r.yaku.map(([n, p]) => `${n}${p}`).join('・')} ＝ ${r.points}文${r.mult > 1 ? ` ×${r.mult} → ${r.total}文` : ''}` : '流れ（どちらも役なし）') : '',
      c.phase === 'round_end' ? nextBtn() : '',
      c.log.length ? h('details', { class: 'kk-log' }, h('summary', { class: 'muted small' }, `直前の流れ：${c.log[c.log.length - 1]}`),
        h('ul', {}, c.log.map((l) => h('li', {}, l)))) : '',
    ];
  } else if (cur.kind === 'concentration') {
    const can = c.phase === 'p_turn' && !busy;
    // キャラがめくった札は, あなたが次の 1 枚をめくるまで位置ごと見せておく (覚えるための情報)
    const herShown = {};
    if (c.phase === 'p_turn' && !c.up.length) c.her_steps.forEach((s) => { herShown[s.a] = s.ca; herShown[s.b] = s.cb; });
    body = [
      c.her_steps.length && c.phase === 'p_turn' ? h('div', { class: 'card-res' }, `${name}の番：`,
        c.her_steps.map((s) => h('span', { class: 'cc-step' }, pcardEl(s.ca, { small: true }), pcardEl(s.cb, { small: true }), s.match ? '○' : '×'))) : '',
      h('div', { class: 'cc-grid', style: `grid-template-columns:repeat(${c.cols},1fr)` }, c.faces.map((f, i) => {
        const owner = c.taken[i];
        if (owner) return h('div', { class: 'cc-slot ' + (owner === 'p' ? 'mine' : 'hers') }, pcardEl(f, { small: true, dim: true }));
        if (f) return pcardEl(f, { hl: c.up.includes(i) });
        if (herShown[i]) return pcardEl(herShown[i], { peek: true, onclick: can ? () => act({ act: 'flip', idx: i }) : null, title: `${name}がめくった札（クリックでめくる）` });
        return pcardEl(null, { onclick: can ? () => act({ act: 'flip', idx: i }) : null });
      })),
      c.phase === 'p_miss' ? h('div', { class: 'row', style: 'justify-content:center;margin-top:8px' },
        h('span', { class: 'muted small' }, 'はずれ…'), h('button', { class: 'btn primary', disabled: busy, onclick: () => act({ act: 'ok' }) }, `ふせて${name}の番へ`)) : '',
      c.phase === 'round_end' ? nextBtn() : '',
    ];
  } else if (cur.kind === 'oldmaid') {
    const can = c.phase === 'p_draw' && !busy;
    body = [
      h('div', { class: 'sc-who' }, `${name}の手札（${c.her_count}枚）— ${c.peek == null ? '指をかける札を選ぶ' : 'もう一度押すと引く／他の札に変える'}`),
      h('div', { class: 'cardrow fan room' }, c.her_hand ? c.her_hand.map((x) => pcardEl(x)) :
        Array.from({ length: c.her_count }, (_, i) => h('div', { class: 'pcard back' + (c.peek === i ? ' peek' : ''),
          onclick: can ? () => act({ act: c.peek === i ? 'draw' : 'peek', idx: i }) : null }))),
      c.log.length ? h('div', { class: 'card-res' }, c.log.map((l) => h('div', {}, l))) : '',
      h('div', { class: 'sc-who', style: 'margin-top:8px' }, `あなたの手札（${c.hand.length}枚）`),
      h('div', { class: 'cardrow wrap' }, c.hand.map((x) => pcardEl(x))),
      c.phase === 'round_end' ? nextBtn() : '',
    ];
  }
  return h('div', { class: 'board' }, head, score, hint, body);
}

function hexSvg(b, can, onclick) {
  const n = b.n, R = 13, W = Math.sqrt(3) * R;
  const cx = (r, c) => W * (c + r / 2) + W, cy = (r) => 1.5 * R * r + R * 1.6;
  const NS = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };
  const width = W * (n + (n - 1) / 2) + W * 2, height = 1.5 * R * (n - 1) + R * 3.2;
  const svg = el('svg', { viewBox: `0 0 ${width} ${height}`, class: 'hex' });
  const corner = (r, c, dx, dy) => [cx(r, c) + dx, cy(r) + dy];
  const edge = (p1, p2, color) => svg.append(el('line', { x1: p1[0], y1: p1[1], x2: p2[0], y2: p2[1], stroke: color, 'stroke-width': 4, 'stroke-linecap': 'round' }));
  edge(corner(0, 0, -W / 2, -R * 1.2), corner(0, n - 1, W / 2, -R * 1.2), 'var(--bad)');
  edge(corner(n - 1, 0, -W / 2, R * 1.2), corner(n - 1, n - 1, W / 2, R * 1.2), 'var(--bad)');
  edge(corner(0, 0, -W * 0.8, -R * 0.4), corner(n - 1, 0, -W * 0.8, R * 0.4), 'var(--sky)');
  edge(corner(0, n - 1, W * 0.8, -R * 0.4), corner(n - 1, n - 1, W * 0.8, R * 0.4), 'var(--sky)');
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      const i = r * n + c, v = b.cells[i];
      const pts = Array.from({ length: 6 }, (_, k) => {
        const a = Math.PI / 180 * (60 * k - 90);
        return `${cx(r, c) + (R - 0.8) * Math.cos(a)},${cy(r) + (R - 0.8) * Math.sin(a)}`;
      }).join(' ');
      const poly = el('polygon', { points: pts, class: `hx ${v === 1 ? 'me' : v === 2 ? 'her' : ''}${b.last.includes(i) ? ' last' : ''}${!v && can ? ' open' : ''}` });
      if (!v && can) poly.addEventListener('click', () => onclick(i));
      svg.append(poly);
    }
  }
  return svg;
}
