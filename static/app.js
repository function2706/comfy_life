'use strict';
/* くらし — フロントエンド (依存なし) */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  let value;
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style') el.style.cssText = v;
    else if (k === 'value') value = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'checked' || k === 'disabled') el[k] = !!v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  if (value !== undefined) el.value = value;
  return el;
}

async function api(path, body) {
  const opt = body === undefined ? {} :
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({ error: 'HTTP ' + r.status }));
  // 失敗判定は HTTP ステータスだけで行う. ジョブ情報などは正常応答でも error 項目を持つため,
  // j.error で判定すると「失敗したジョブ」が取得失敗扱いになり, 生成待ちのまま固まる.
  if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
  return j;
}

function toast(msg, kind = '') {
  const t = h('div', { class: 'toast ' + kind }, msg);
  $('#toasts').append(t);
  setTimeout(() => t.remove(), kind === 'err' ? 7000 : 3200);
}

const clone = (o) => JSON.parse(JSON.stringify(o));
const DOW = '日月火水木金土';
const pad = (n) => String(n).padStart(2, '0');
const imgUrl = (rel) => '/images/' + rel.split('/').map(encodeURIComponent).join('/');
function fmtTime(t) {
  const d = new Date(t * 1000), now = new Date();
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (d.toDateString() === now.toDateString()) return hm;
  return `${d.getMonth() + 1}/${d.getDate()}(${DOW[d.getDay()]}) ${hm}`;
}

/* ---------------------------------------------------------------- state */
const S = {
  boot: null,       // settings, params, actions, world, characters, character
  view: null,       // /api/state
  current: null,    // 表示中のログエントリ
  jobs: new Map(),  // jid -> job view
  busy: false,
  typing: null,
  lastDeltas: {},
  showHidden: false,
};
const pname = (id) => (S.boot.params.find((p) => p.id === id) || {}).name || id;

/* ---------------------------------------------------------------- boot */
async function loadBoot() {
  S.boot = await api('/api/boot');
  const sel = $('#char-select');
  sel.replaceChildren(...S.boot.characters.map((c) => h('option', { value: c.id }, c.name)));
  sel.value = S.boot.character.id;
  $('#nameplate').textContent = S.boot.character.name;
}

async function refresh() {
  try {
    S.view = await api('/api/state');
  } catch (e) {
    toast('状態の取得に失敗: ' + e.message, 'err');
    return;
  }
  for (const j of S.view.jobs) if (!S.jobs.has(j.id)) trackJob(j.id);
  renderWho();
  renderCommands();
  renderDress();
  renderGames();
  renderStatus();
  renderLog();
  if (!S.current && S.view.log.length) showEntry(S.view.log[S.view.log.length - 1], false);
  if (!S.view.log.length && !S.current) showGreeting();
}

function showGreeting() {
  setDialogue(`（${S.boot.character.name}との暮らしが始まった。右のコマンドから話しかけてみよう）`, false);
}

/* ---------------------------------------------------------------- clock */
function tickClock() {
  const d = new Date();
  $('#clock-hm').textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  $('#clock-s').textContent = ':' + pad(d.getSeconds());
  $('#clock-date').textContent = `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} (${DOW[d.getDay()]})`;
  if (S.view && S.view.override_until) {
    const rest = Math.max(0, Math.round(S.view.override_until - Date.now() / 1000));
    const el = $('#ov-rest');
    if (el) el.textContent = rest > 0 ? `あと${Math.ceil(rest / 60)}分` : '';
    if (rest === 0) refresh();
  }
  updateGenBadge();
}

/* ---------------------------------------------------------------- who / scene */
function moodFace(p) {
  if (S.view.scene.asleep) return '😴';
  if (S.view.scene.away) return '🚶';
  if ((p.health ?? 100) < 50) return '🤒';
  if ((p.shyness ?? 0) >= 60) return '😳';
  if ((p.heart ?? 0) >= 60) return '🥰';
  const m = p.mood ?? 50;
  if (m >= 75) return '😊';
  if (m >= 50) return '🙂';
  if (m >= 35) return '😐';
  if (m >= 15) return '😣';
  return '😢';
}

function renderWho() {
  const v = S.view;
  $('#phase-chip').textContent = v.phase.label || '—';
  const sc = v.scene;
  const where = sc.location ? `📍${sc.location}` : '';
  $('#scene-chip').textContent = `${where}　${sc.label || ''}`.trim();
  $('#who-name').textContent = v.name;
  $('#who-scene').replaceChildren(...[
    `${sc.label}${sc.location ? '（' + sc.location + '）' : ''}`,
    sc.source === 'override' ? h('span', { class: 'muted', id: 'ov-rest', style: 'margin-left:6px' }) : null,
  ].filter(Boolean));
  const face = $('#who-face');
  const lastImg = [...v.log].reverse().find((e) => e.image);
  if (lastImg) { face.style.backgroundImage = `url("${imgUrl(lastImg.image)}")`; face.textContent = ''; face.title = moodFace(v.params); }
  else { face.style.backgroundImage = ''; face.textContent = moodFace(v.params); }
  $('#who-tags').replaceChildren(
    h('span', { class: 'tag', style: 'background:#2b2540;color:#d9d0ff' }, moodFace(v.params)),
    v.dress && v.dress.wearing ? h('span', { class: 'tag dress' }, '👗' + v.dress.wearing) : '',
    ...v.tags.map((t) => h('span', { class: 'tag' }, t.label)),
  );
}

/* ---------------------------------------------------------------- commands */
function renderCommands() {
  const box = $('#tab-commands');
  const av = S.view.available;
  const cats = new Map();
  let hidden = 0;
  for (const a of S.boot.actions) {
    if (a.category === 'system' || !av[a.id]) continue;
    if (!av[a.id].ok && !S.showHidden) { hidden++; continue; }
    if (!cats.has(a.category)) cats.set(a.category, []);
    cats.get(a.category).push(a);
  }
  const out = [];
  for (const [cat, list] of cats) {
    out.push(h('div', { class: 'cat' },
      h('div', { class: 'cat-title' }, cat || 'その他'),
      h('div', { class: 'cmds' }, list.map((a) => {
        const st = av[a.id];
        const tip = [a.when ? '条件: ' + a.when : '', a.effects && Object.keys(a.effects).length ?
          '効果: ' + Object.entries(a.effects).map(([k, v]) => `${pname(k)}${v > 0 ? '+' : ''}${v}`).join(' ') : '',
          st.cooldown ? `連続実行で効果減 (あと${Math.ceil(st.cooldown / 60)}分)` : ''].filter(Boolean).join('\n');
        return h('button', { class: 'cmd', disabled: !st.ok || S.busy, title: tip, onclick: () => doAct(a.id) },
          h('span', { class: 'ic' }, a.icon || '•'), h('span', {}, a.name),
          st.cooldown ? h('span', { class: 'cd' }, '♻') : null);
      }))));
  }
  if (!out.length) out.push(h('p', { class: 'muted' }, '今できることはなさそうだ…'));
  out.push(h('button', { class: 'cmds-hidden-toggle', onclick: () => { S.showHidden = !S.showHidden; renderCommands(); } },
    S.showHidden ? '▲ 今できないコマンドを隠す' : `▼ 今できないコマンドも表示 (${hidden})`));
  box.replaceChildren(...out);
}

/* ---------------------------------------------------------------- dress tab */
function renderDress() {
  const d = S.view.dress;
  const items = S.boot.character.wardrobe || [];
  const card = (id, icon, name, ok, tip) => h('button', {
    class: 'outfit' + (d.current === id ? ' on' : ''), disabled: !d.can || !ok || S.busy,
    title: tip || '', onclick: () => doAct('_dress', id),
  }, h('span', { class: 'ic' }, icon), h('span', {}, name));
  $('#tab-dress').replaceChildren(
    h('div', { class: 'dress-now' },
      h('div', {}, h('b', {}, 'いまの服 '), d.wearing || 'おまかせ（スケジュール通り）'),
      h('div', {}, h('code', {}, d.outfit || '—')),
      d.fixed ? h('div', { class: 'muted small' }, '※ 今の場面は服装固定（就寝中など）なので、着せ替えは場面が変わってから反映されます') : '',
      !d.can ? h('div', { class: 'muted small' }, `今は着替えられません（${d.why}）`) : ''),
    h('div', { class: 'outfits' },
      card('', '🔄', 'おまかせ', true, 'スケジュール通りの服に戻す'),
      items.map((o) => card(o.id, o.icon || '👕', o.name || o.id, d.items[o.id], o.when ? '条件: ' + o.when : o.pos))),
    items.length ? '' : h('p', { class: 'muted small' }, '服が登録されていません。設定 → 着せ替え から追加できます。'),
    h('p', { class: 'hint', style: 'margin-top:12px' }, S.boot.character.dress_reset_on_sleep !== false
      ? '着せ替えた服は、寝るとスケジュール通りの服に戻ります。' : '着せ替えた服は「おまかせ」を選ぶまで続きます。'),
  );
}

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

async function gameAct(path, body) {
  if (S.busy) return;
  S.busy = true;
  renderGames();
  try {
    const r = await api(path, body);
    S.gameHint = r.hint || null;
    S.gameResult = r.ended === 'win' ? '🎉 あなたの勝ち！' : r.ended === 'lose' ? '😵 あなたの負け…' : r.refused ? '断られてしまった…' : null;
    if (r.entry) handleActResult(r);
  } catch (e) {
    toast(e.message, 'err');
  } finally {
    S.busy = false;
    await refresh();
  }
}

async function doAct(aid, outfit) {
  if (S.busy) return;
  S.busy = true;
  renderCommands();
  try {
    const r = outfit === undefined ? await api('/api/act', { action: aid }) : await api('/api/dress', { outfit });
    handleActResult(r);
  } catch (e) {
    toast(e.message, 'err');
  } finally {
    S.busy = false;
    await refresh();
  }
}

function handleActResult(r) {
  if (r.llm_error) toast('LLM 失敗のため定型文を使用: ' + r.llm_error, 'err');
  S.lastDeltas = r.entry.deltas || {};
  showEntry(r.entry, true);
  if (r.job) trackJob(r.job);
}

/* ---------------------------------------------------------------- stage */
function setImage(rel) {
  const img = $('#stage-img');
  $('#stage-empty').hidden = !!rel || !!img.dataset.rel;
  if (!rel || img.dataset.rel === rel) return;
  const pre = new Image();
  pre.onload = () => {
    img.classList.remove('show');
    setTimeout(() => {
      img.src = pre.src;
      img.dataset.rel = rel;
      img.classList.add('show');
      $('#stage-bg').style.backgroundImage = `url("${pre.src}")`;
      $('#stage-empty').hidden = true;
    }, img.src ? 180 : 0);
  };
  pre.src = imgUrl(rel);
}

function setDialogue(text, animate, name) {
  const dlg = $('#dialogue');
  const narr = text.startsWith('（') || text.startsWith('(');
  dlg.classList.toggle('narr', narr);
  dlg.classList.toggle('phone', text.startsWith('📱'));
  $('#nameplate').textContent = narr ? 'ナレーション' : (name || S.boot.character.name);
  const el = $('#dtext');
  if (S.typing) { clearInterval(S.typing); S.typing = null; }
  if (!animate) { el.textContent = text; return; }
  let i = 0;
  const chars = [...text];
  el.replaceChildren('', h('span', { class: 'caret' }));
  S.typing = setInterval(() => {
    i++;
    el.firstChild.textContent = chars.slice(0, i).join('');
    if (i >= chars.length) { clearInterval(S.typing); S.typing = null; el.textContent = text; }
  }, 28);
  S.typingText = text;
}

function showEntry(e, animate) {
  S.current = e;
  setDialogue(e.text || `（${e.action_name}）`, animate);
  $('#dtime').textContent = `${fmtTime(e.t)}・${e.icon || ''}${e.action_name}${e.text_src === 'llm' ? '・LLM' : ''}`
    + (e.reused ? `・既存${e.same_prompt || ''}枚から表示${e.job ? '（新規生成中）' : e.busy_skip ? '（生成中のため新規生成なし）' : ''}` : '');
  $('#deltas').replaceChildren(...Object.entries(e.deltas || {}).map(([k, v]) => {
    const p = S.boot.params.find((x) => x.id === k) || {};
    const cls = p.neutral ? '' : ((v > 0) !== !!p.invert ? 'up' : 'down');
    return h('span', { class: 'delta ' + cls }, `${pname(k)} ${v > 0 ? '+' : ''}${v}`);
  }));
  if (e.image) setImage(e.image);
  else if (!$('#stage-img').dataset.rel) $('#stage-empty').hidden = false;
  $$('.log-item').forEach((x) => x.classList.toggle('cur', x.dataset.id === e.id));
  if (!$('#prompt-drawer').hidden) fillPromptDrawer(e);
}

/* ---------------------------------------------------------------- jobs */
function trackJob(jid) {
  S.jobs.set(jid, { id: jid, status: 'queued' });
  updateGenBadge();
  if (!S.jobTimer) S.jobTimer = setInterval(pollJobs, 1000);
}

async function pollJobs() {
  if (S.polling) return;   // 応答が遅いときに問い合わせを重ねない
  S.polling = true;
  try { await pollJobsOnce(); } finally { S.polling = false; }
}

async function pollJobsOnce() {
  for (const [jid] of S.jobs) {
    let j;
    try {
      j = await api('/api/job?id=' + jid);
      S.pollError = null;
    } catch (e) {
      S.pollError = e.message;   // サーバ応答なしをバッジに出す
      continue;
    }
    S.jobs.set(jid, j);
    if (j.status === 'done') {
      S.jobs.delete(jid);
      if (S.current && S.current.id === j.entry) { S.current.image = j.image; setImage(j.image); }
      else if (!S.current || S.current.t <= (S.view.log.find((x) => x.id === j.entry) || {}).t) setImage(j.image);
      refresh();
    } else if (['error', 'unknown', 'cancelled'].includes(j.status)) {
      S.jobs.delete(jid);
      if (j.status !== 'cancelled' && j.error) { S.lastError = j.error; toast('画像生成エラー: ' + j.error, 'err'); }
      refresh();
    }
  }
  if (!S.jobs.size) { clearInterval(S.jobTimer); S.jobTimer = null; }
  updateGenBadge();
}

const secs = (s) => (s >= 60 ? `${Math.floor(s / 60)}分${Math.round(s % 60)}秒` : `${Math.round(s)}秒`);

function jobText(j) {
  if (j.status === 'queued') return j.stage_label ? `${j.stage_label}（${j.ahead ? `先に${j.ahead}件・` : ''}${secs(j.waited || 0)}）` : '受付中…';
  const pos = j.stage === 'comfy_queued' && j.queue_pos ? ` ${j.queue_pos}番目` : '';
  return `${j.stage_label || '処理中'}${pos} ${secs(j.stage_elapsed || 0)}`;
}

function updateGenBadge() {
  const b = $('#gen-badge');
  b.onclick = () => openJobs();
  const jobs = [...S.jobs.values()];
  if (S.pollError && jobs.length) {
    b.className = 'gen-badge err';
    b.replaceChildren('⚠ サーバ応答なし');
    b.title = S.pollError;
    return;
  }
  if (!jobs.length) {
    b.className = S.lastError ? 'gen-badge err' : 'gen-badge idle';
    b.replaceChildren(S.lastError ? '⚠ 生成失敗（詳細）' : '🖼 生成ジョブ');
    b.title = S.lastError || 'クリックで生成ジョブの詳細';
    return;
  }
  b.className = 'gen-badge'; b.title = 'クリックで詳細';
  const run = jobs.find((j) => j.status === 'running') || jobs[0];
  b.replaceChildren(h('span', { class: 'spin' }), jobText(run) + (jobs.length > 1 ? `（全${jobs.length}件）` : ''));
}

/* ---------------------------------------------------------------- jobs panel */
const JOB_ST = { queued: '待ち', running: '処理中', done: '完了', error: '失敗', cancelled: '取消', unknown: '不明' };

async function openJobs() {
  S.lastError = null;
  $('#jobs-panel').hidden = false;
  $('#prompt-drawer').hidden = true;
  await renderJobs();
  clearInterval(S.jpTimer);
  S.jpTimer = setInterval(() => { if ($('#jobs-panel').hidden) clearInterval(S.jpTimer); else renderJobs(); }, 1500);
}

async function renderJobs() {
  let r;
  try { r = await api('/api/jobs'); } catch (e) {
    $('#jp-worker').textContent = 'サーバに接続できません: ' + e.message;
    return;
  }
  const w = r.worker;
  $('#jp-worker').textContent = `ワーカー: ${w.alive ? (w.current ? `処理中「${w.current_action || ''}」${secs(w.busy_for)}` : '待機中') : '停止'}`
    + `${w.restarts ? `（再起動${w.restarts}回）` : ''}・待ち ${r.queue_len}件・ComfyUI ${r.comfy_url}${r.use_proxy ? '（プロキシ経由）' : ''}`;
  const open = new Set($$('#jp-body details[open]').map((d) => d.dataset.id));
  const body = $('#jp-body');
  if (!r.jobs.length) { body.replaceChildren(h('p', { class: 'muted' }, 'まだジョブはありません')); return; }
  body.replaceChildren(...r.jobs.map((j) => {
    const active = j.status === 'queued' || j.status === 'running';
    return h('div', { class: 'job' },
      h('div', { class: 'job-head' },
        h('span', { class: 'job-st ' + j.status }, JOB_ST[j.status] || j.status),
        h('b', {}, j.action || '（手動）'),
        h('span', { class: 'muted' }, fmtTime(j.created)),
        active ? h('span', {}, jobText(j)) : h('span', { class: 'muted' }, `所要 ${secs(j.status === 'queued' ? j.waited : j.elapsed)}`),
        j.prompt_id ? h('code', { class: 'muted small', title: 'ComfyUI の prompt_id' }, j.prompt_id.slice(0, 8)) : null,
        h('div', { class: 'spacer' }),
        active ? h('button', { class: 'btn ghost danger', onclick: async () => {
          await api('/api/job/cancel', { id: j.id }); renderJobs();
        } }, '取消') : null),
      j.error ? h('div', { class: 'job-err' }, j.error) : null,
      h('details', { 'data-id': j.id, open: open.has(j.id) || (active && r.jobs[0].id === j.id) },
        h('summary', { class: 'muted small' }, `経過ログ（${(j.events || []).length}）${j.last_event ? '：' + j.last_event : ''}`),
        h('ul', { class: 'job-ev' }, (j.events || []).map((ev) => h('li', { class: ev.level },
          h('time', {}, new Date(ev.t * 1000).toLocaleTimeString()), ev.msg)))));
  }));
}

/* ---------------------------------------------------------------- status tab */
function level(p, v) {
  if (p.neutral) return 'var(--sky)';
  const n = (v - (p.min ?? 0)) / ((p.max ?? 100) - (p.min ?? 0));
  const g = p.invert ? 1 - n : n;
  return g >= 0.6 ? 'var(--good)' : g >= 0.3 ? 'var(--mid)' : 'var(--bad)';
}

function renderStatus() {
  const v = S.view;
  const groups = [['physical', 'からだ'], ['mental', 'こころ']];
  const others = S.boot.params.filter((p) => !['physical', 'mental'].includes(p.group));
  const rows = (list) => list.map((p) => {
    const val = v.params[p.id] ?? 0;
    const pct = ((val - (p.min ?? 0)) / ((p.max ?? 100) - (p.min ?? 0))) * 100;
    const d = S.lastDeltas[p.id];
    return h('div', { class: 'prow' + (d ? ' flash' : ''), title: p.id },
      h('span', {}, p.name),
      h('div', { class: 'bar' }, h('i', { style: `width:${pct}%;background:${level(p, val)}` })),
      h('span', { class: 'pval' }, d ? `${d > 0 ? '+' : ''}${d}` : Math.round(val)));
  });
  const sc = v.scene;
  const flags = [sc.asleep && '睡眠中', sc.away && '外出中', sc.busy && '手が離せない'].filter(Boolean).join('・');
  $('#tab-status').replaceChildren(
    h('div', { class: 'scene-box' },
      h('div', {}, h('b', {}, '時間帯 '), v.phase.label),
      h('div', {}, h('b', {}, 'いま '), `${sc.label}（${sc.location || '—'}）`, flags ? `　${flags}` : ''),
      h('div', {}, h('b', {}, '最後のふれあい '), v.absent < 1 ? `${Math.round(v.absent * 60)}分前` : `${v.absent.toFixed(1)}時間前`)),
    ...groups.map(([g, label]) => h('div', { class: 'pgroup' }, h('h4', {}, label), rows(S.boot.params.filter((p) => p.group === g)))),
    others.length ? h('div', { class: 'pgroup' }, h('h4', {}, 'その他'), rows(others)) : '',
  );
  setTimeout(() => { S.lastDeltas = {}; }, 4000);
}

/* ---------------------------------------------------------------- log tab */
function logItem(e) {
  const th = h('div', { class: 'log-thumb' });
  if (e.image) th.style.backgroundImage = `url("${imgUrl(e.image)}")`;
  else th.textContent = e.job ? '⏳' : e.error ? '⚠' : (e.icon || '•');
  return h('div', { class: 'log-item' + (S.current && S.current.id === e.id ? ' cur' : ''), 'data-id': e.id,
    onclick: () => showEntry(e, false) },
    th,
    h('div', { class: 'log-main' },
      h('div', { class: 'log-head' }, h('span', {}, fmtTime(e.t)), h('span', {}, `${e.icon || ''}${e.action_name}`),
        h('span', {}, e.scene || '')),
      h('div', { class: 'log-text' }, e.text || '—')));
}

function renderLog() {
  const v = S.view;
  const items = [...v.log].reverse().map(logItem);
  const box = $('#tab-log');
  box.replaceChildren(...items);
  if (v.log_total > v.log.length) {
    let offset = v.log.length;
    const more = h('div', { class: 'center' }, h('button', { class: 'btn ghost', onclick: async () => {
      const r = await api(`/api/log?offset=${offset}&limit=60`);
      offset += r.items.length;
      more.before(...r.items.map(logItem));
      if (offset >= r.total) more.remove();
    } }, 'さらに古い記録'));
    box.append(more);
  }
}

/* ---------------------------------------------------------------- prompt drawer */
function fillPromptDrawer(e) {
  S.pdEntry = e;
  $('#pd-src').textContent = e ? `${fmtTime(e.t)} ${e.action_name}` : '今の状態';
  $('#pd-pos').value = e ? e.pos : '';
  $('#pd-neg').value = e ? e.neg : '';
  $('#pd-seed').value = '';
  $('#pd-regen').disabled = !e;
  renderParts(e ? e.parts : []);
}
function renderParts(parts) {
  $('#pd-parts').replaceChildren(...(parts || []).map((p) => h('div', { class: 'part' },
    h('span', { class: 'src' }, p.src),
    h('span', {}, p.pos, p.neg ? h('div', { class: 'neg' }, '− ' + p.neg) : null))));
}
async function genFromDrawer(useEntry) {
  const seed = $('#pd-seed').value;
  try {
    const r = await api('/api/generate', {
      entry: useEntry && S.pdEntry ? S.pdEntry.id : null,
      pos: $('#pd-pos').value, neg: $('#pd-neg').value, seed: seed === '' ? null : Number(seed),
    });
    trackJob(r.job);
    if (!useEntry) { showEntry(r.entry, false); }
    await refresh();
  } catch (e) { toast(e.message, 'err'); }
}

/* ---------------------------------------------------------------- gallery */
async function openGallery() {
  const dlg = $('#gallery-dlg');
  const box = $('#gallery');
  box.replaceChildren();
  let offset = 0;
  const load = async () => {
    const r = await api(`/api/log?images=1&offset=${offset}&limit=40`);
    offset += r.items.length;
    $('#gal-count').textContent = `${r.total} 件の記録`;
    for (const e of r.items) {
      for (const im of [...(e.images || [])].reverse()) {
        const it = h('div', { class: 'gal-item', style: `background-image:url("${imgUrl(im.path)}")`,
          onclick: () => openLightbox(e, im) }, h('span', {}, `${fmtTime(im.t || e.t)} ${e.icon || ''}${e.action_name}`));
        box.append(it);
      }
    }
    $('#gal-more').hidden = offset >= r.total;
  };
  $('#gal-more').onclick = load;
  dlg.showModal();
  await load();
}
function openLightbox(e, im) {
  $('#lb-img').src = imgUrl(im.path);
  $('#lb-open').href = imgUrl(im.path);
  $('#lb-text').textContent = e.text || e.action_name;
  $('#lb-meta').textContent = `${fmtTime(im.t || e.t)}・${e.action_name}・${e.scene || ''}・seed ${im.seed}`;
  $('#lb-prompt').textContent = `${im.pos}\n\nNegative: ${im.neg}`;
  $('#lb-stage').onclick = () => {
    showEntry(Object.assign({}, e, { image: im.path }), false);
    setImage(im.path);
    $('#lightbox').close(); $('#gallery-dlg').close();
  };
  $('#lightbox').showModal();
}

/* ================================================================= settings */
const SEC = {};
let SE = {}; // 編集中のワーキングコピー

function openSettings(sec) {
  SE = {
    settings: clone(S.boot.settings), char: clone(S.boot.character), actions: clone(S.boot.actions),
    params: clone(S.boot.params), world: clone(S.boot.world), selAction: SE.selAction || 0,
  };
  $('#settings-dlg').showModal();
  showSection(sec || SE.sec || 'char');
}
function showSection(sec) {
  SE.sec = sec;
  $$('#snav button').forEach((b) => b.classList.toggle('on', b.dataset.sec === sec));
  const body = $('#sbody');
  body.replaceChildren(...[SEC[sec]()].flat().filter((x) => x != null && x !== false));
  body.scrollTop = 0;
}
async function reloadAll(sec) {
  await loadBoot();
  SE.settings = clone(S.boot.settings); SE.char = clone(S.boot.character);
  SE.actions = clone(S.boot.actions); SE.params = clone(S.boot.params); SE.world = clone(S.boot.world);
  if (sec) showSection(sec);
  await refresh();
}

/* ---- form helpers */
function inp(obj, key, o = {}) {
  const type = o.type || 'text';
  let el;
  if (type === 'textarea') el = h('textarea', { rows: o.rows || 2, placeholder: o.ph || '' });
  else if (type === 'checkbox') el = h('input', { type: 'checkbox' });
  else if (type === 'select') el = h('select', {}, o.options.map((x) => Array.isArray(x) ? h('option', { value: x[0] }, x[1]) : h('option', { value: x }, x)));
  else el = h('input', { type, placeholder: o.ph || '', step: o.step || null, list: o.list || null });
  const v = obj[key];
  if (type === 'checkbox') el.checked = !!v;
  else el.value = o.fmt ? o.fmt(v) : (v ?? '');
  el.addEventListener(type === 'checkbox' || type === 'select' ? 'change' : 'input', () => {
    let x = type === 'checkbox' ? el.checked : el.value;
    if (type === 'number') x = x === '' ? null : Number(x);
    if (o.parse) {
      try { x = o.parse(x); el.classList.remove('bad'); el.title = ''; }
      catch (err) { el.classList.add('bad'); el.title = '書式エラー: ' + (err.message || ''); return; }
    }
    obj[key] = x;
    if (o.onchange) o.onchange(x);
  });
  return el;
}
const fld = (label, el, hint, cls) => h('label', { class: 'fld ' + (cls || '') }, h('span', { class: 'fl' }, label), el, hint ? h('small', { class: 'hint' }, hint) : null);
const chk = (obj, key, label, onchange) => h('label', { class: 'check' }, inp(obj, key, { type: 'checkbox', onchange }), label);

const fmtEff = (o) => Object.entries(o || {}).map(([k, v]) => `${k}:${v > 0 ? '+' : ''}${v}`).join(', ');
function parseEff(s) {
  const o = {};
  for (const part of String(s).split(/[,、\n]/)) {
    const t = part.trim();
    if (!t) continue;
    const m = t.match(/^([A-Za-z_]\w*)\s*[:=]\s*([+-]?\d+(?:\.\d+)?)$/);
    if (!m) throw new Error(t);
    o[m[1]] = Number(m[2]);
  }
  return o;
}
const fmtRules = (arr, key) => (arr || []).map((r) => `${r.when} => ${r[key]}`).join('\n');
function parseRules(s, key) {
  return String(s).split('\n').map((l) => l.trim()).filter(Boolean).map((l) => {
    const i = l.lastIndexOf('=>');
    if (i < 0) throw new Error(l);
    const n = Number(l.slice(i + 2));
    if (Number.isNaN(n)) throw new Error(l);
    return { when: l.slice(0, i).trim(), [key]: n };
  });
}
function paramKeysHint() {
  return h('div', { class: 'keys' },
    h('div', {}, 'パラメータ id: ', SE.params.map((p, i) => [i ? '、' : '', h('code', {}, p.id), `(${p.name})`])),
    h('div', {}, '条件キー: ', ['activity', 'location', 'phase', 'free', 'away', 'asleep', 'busy', 'hour', 'time', 'weekday', 'day', 'weekend', 'absent', 'repeat', 'outfit']
      .map((k, i) => [i ? ' ' : '', h('code', {}, k)])),
    h('div', {}, '条件の書き方: ', h('code', {}, 'free=true, mood>=50, phase=night|midnight'), '（カンマで AND、| で OR、time は 07:30 形式）'),
    h('div', {}, '効果の書き方: ', h('code', {}, 'mood:+5, stress:-10'), '（1時間あたりの値はスケジュール・一時シーン）'));
}
function saveBar(title, onsave, extra) {
  return h('div', { class: 'sbar' }, h('h3', {}, title), h('div', { class: 'spacer' }), extra || null,
    h('button', { class: 'btn primary', onclick: async (ev) => {
      ev.target.disabled = true;
      try { await onsave(); toast('保存しました', 'ok'); } catch (e) { toast(e.message, 'err'); }
      ev.target.disabled = false;
    } }, '保存'));
}
function moveIn(arr, i, d) { const j = i + d; if (j < 0 || j >= arr.length) return; [arr[i], arr[j]] = [arr[j], arr[i]]; }
function downloadJson(name, obj) {
  const a = h('a', { href: URL.createObjectURL(new Blob([JSON.stringify(obj, null, 1)], { type: 'application/json' })), download: name });
  a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function pickJson() {
  return new Promise((res, rej) => {
    const f = h('input', { type: 'file', accept: '.json,application/json' });
    f.onchange = async () => { try { res(JSON.parse(await f.files[0].text())); } catch (e) { rej(e); } };
    f.click();
  });
}

/* ---- 主人公 */
SEC.char = () => {
  const c = SE.char, st = SE.settings;
  const hist = h('div', { class: 'hist' });
  const posEl = inp(c, 'pos', { type: 'textarea', rows: 5, ph: '1girl, solo, long hair, ...' });
  const negEl = inp(c, 'neg', { type: 'textarea', rows: 3 });
  for (const it of c.prompt_history || []) {
    hist.append(h('div', { class: 'hist-item' },
      h('div', {}, h('div', { class: 'muted' }, new Date(it.t * 1000).toLocaleString()),
        h('code', {}, it.pos), it.neg ? h('code', { class: 'neg' }, '\n− ' + it.neg) : null),
      h('div', {}, h('button', { class: 'btn', onclick: () => {
        c.pos = it.pos; c.neg = it.neg; posEl.value = it.pos; negEl.value = it.neg;
        toast('入力欄に復元しました（保存で確定）');
      } }, '復元'))));
  }
  return [
    saveBar('主人公', async () => {
      await api('/api/settings', { settings: { player_name: st.player_name } });
      await api('/api/character/save', { data: c });
      await reloadAll('char');
    }, h('div', { class: 'row' },
      h('select', { onchange: async (ev) => { await api('/api/character/select', { id: ev.target.value }); S.current = null; await reloadAll('char'); } },
        S.boot.characters.map((x) => h('option', { value: x.id, selected: x.id === c.id }, x.name))),
      h('button', { class: 'btn', onclick: async () => {
        const name = prompt('新しいキャラの名前（スケジュールは現在のキャラから複製）');
        if (!name) return;
        await api('/api/character/new', { name }); S.current = null; await reloadAll('char');
      } }, '＋新規'),
      h('button', { class: 'btn danger', onclick: async () => {
        if (!confirm(`「${c.name}」を削除しますか？（ログと画像は残ります）`)) return;
        try { await api('/api/character/delete', { id: c.id }); S.current = null; await reloadAll('char'); } catch (e) { toast(e.message, 'err'); }
      } }, '削除'))),
    h('p', { class: 'lead' }, '一緒に暮らす相手の設定です。外見の SD プロンプトは保存のたびに履歴へ残り、いつでも復元できます。'),
    h('div', { class: 'grid3' },
      fld('名前', inp(c, 'name')),
      fld('あなたの呼ばれ方', inp(c, 'player_call'), '{player} = あなたの名前'),
      fld('あなたの名前', inp(st, 'player_name'))),
    h('div', { class: 'sect' }, '外見プロンプト'),
    fld('Positive（外見・固有の特徴）', posEl),
    fld('Negative', negEl),
    fld('普段の服装（スケジュールで未指定のとき）', inp(c, 'outfit_default')),
    h('div', { class: 'sect' }, '性格・口調（LLM 使用時に参照）'),
    inp(c, 'persona', { type: 'textarea', rows: 3 }),
    h('div', { class: 'sect' }, `プロンプト履歴（${(c.prompt_history || []).length}）`),
    hist,
  ];
};

/* ---- スケジュール */
function sceneFields(e, opts = {}) {
  return h('div', { class: 'grid4' },
    opts.days ? fld('曜日', inp(e, 'days', { type: 'select', options: [['all', '毎日'], ['weekday', '平日'], ['weekend', '土日'], ['mon', '月'], ['tue', '火'], ['wed', '水'], ['thu', '木'], ['fri', '金'], ['sat', '土'], ['sun', '日']] })) : null,
    opts.days ? fld('開始', inp(e, 'from', { ph: '07:00' })) : null,
    opts.days ? fld('終了', inp(e, 'to', { ph: '08:00' })) : null,
    opts.minutes ? fld('継続（分）', inp(e, 'minutes', { type: 'number' })) : null,
    fld('表示名', inp(e, 'label', { ph: '朝ごはん' })),
    fld('activity id', inp(e, 'activity', { ph: 'breakfast' }), null),
    fld('場所', inp(e, 'location', { ph: 'ダイニング' })),
    h('div', { class: 'fld' }, h('span', { class: 'fl' }, '状態'),
      h('div', { class: 'row' }, chk(e, 'away', '外出'), chk(e, 'asleep', '睡眠'), chk(e, 'busy', '手が離せない'),
        h('label', { class: 'check', title: '着せ替えより、この場面の服装を優先する（未指定なら睡眠中のみ固定）' },
          h('input', { type: 'checkbox', checked: e.fixed_outfit ?? !!e.asleep, onchange: (ev) => { e.fixed_outfit = ev.target.checked; } }), '服装固定'))),
    fld('服装（空欄=継続）', inp(e, 'outfit'), null, 'span2'),
    fld('毎時の効果', inp(e, 'effects', { fmt: fmtEff, parse: parseEff, ph: 'satiety:+60' }), null, 'span2'),
    fld('Positive（場面）', inp(e, 'pos', { type: 'textarea', rows: 2 }), null, 'span2'),
    fld('Negative', inp(e, 'neg', { type: 'textarea', rows: 2 }), null, 'span2'),
  );
}
SEC.schedule = () => {
  const c = SE.char;
  c.schedule = c.schedule || [];
  c.default_activity = c.default_activity || {};
  const list = h('div');
  const draw = () => {
    list.replaceChildren(...c.schedule.map((e, i) => h('div', { class: 'card' },
      h('div', { class: 'card-head' }, h('b', {}, `${i + 1}. ${e.from || '?'}〜${e.to || '?'}  ${e.label || ''}`),
        h('span', { class: 'muted small' }, { all: '毎日', weekday: '平日', weekend: '土日' }[e.days] || e.days),
        h('div', { class: 'spacer' }),
        h('button', { class: 'btn ghost', title: '上へ', onclick: () => { moveIn(c.schedule, i, -1); draw(); } }, '↑'),
        h('button', { class: 'btn ghost', title: '下へ', onclick: () => { moveIn(c.schedule, i, 1); draw(); } }, '↓'),
        h('button', { class: 'btn ghost danger', onclick: () => { c.schedule.splice(i, 1); draw(); } }, '削除')),
      sceneFields(e, { days: true }))));
  };
  draw();
  return [
    saveBar(`${c.name}の生活スケジュール`, async () => { await api('/api/character/save', { data: c }); await reloadAll(); }),
    h('p', { class: 'lead' }, '実際の時刻に合わせて、上から順に最初に一致した予定が「いまの場面」になります。どれにも一致しなければ「普段」が使われます。日をまたぐ予定（22:00〜02:00 など）も書けます。毎時の効果は滞在 1 時間あたりのパラメータ変化です。'),
    paramKeysHint(),
    h('div', { class: 'sect' }, '普段（予定のない時間）'),
    h('div', { class: 'card' }, sceneFields(c.default_activity)),
    h('div', { class: 'sect' }, '予定'),
    list,
    h('button', { class: 'btn', onclick: () => { c.schedule.push({ days: 'all', from: '10:00', to: '11:00', activity: 'new', label: '新しい予定', location: '', pos: '', neg: '', effects: {} }); draw(); } }, '＋予定を追加'),
  ];
};

/* ---- 着せ替え */
SEC.wardrobe = () => {
  const c = SE.char;
  c.wardrobe = c.wardrobe || [];
  c.dress_reset_on_sleep = c.dress_reset_on_sleep !== false;
  const list = h('div');
  const draw = () => {
    list.replaceChildren(...c.wardrobe.map((o, i) => h('div', { class: 'card' },
      h('div', { class: 'card-head' }, h('b', {}, `${o.icon || '👕'} ${o.name || o.id}`), h('code', { class: 'muted small' }, o.id),
        h('div', { class: 'spacer' }),
        h('button', { class: 'btn ghost', onclick: () => { moveIn(c.wardrobe, i, -1); draw(); } }, '↑'),
        h('button', { class: 'btn ghost', onclick: () => { moveIn(c.wardrobe, i, 1); draw(); } }, '↓'),
        h('button', { class: 'btn ghost', onclick: () => { const n = clone(o); n.id += '_copy'; n.name += '（複製）'; c.wardrobe.splice(i + 1, 0, n); draw(); } }, '複製'),
        h('button', { class: 'btn ghost danger', onclick: () => { c.wardrobe.splice(i, 1); draw(); } }, '削除')),
      h('div', { class: 'grid4' },
        fld('id', inp(o, 'id'), '反応の条件 outfit=… で使う'), fld('名前', inp(o, 'name')), fld('アイコン', inp(o, 'icon')),
        fld('着られる条件', inp(o, 'when', { ph: 'affection>=40' })),
        fld('Positive（服装）', inp(o, 'pos', { type: 'textarea', rows: 2 }), null, 'span2'),
        fld('Negative', inp(o, 'neg', { type: 'textarea', rows: 2 }), null, 'span2')))));
  };
  draw();
  return [
    saveBar(`${c.name}の着せ替え`, async () => { await api('/api/character/save', { data: c }); await reloadAll(); }),
    h('p', { class: 'lead' }, 'サイドの「着せ替え」タブから選べる服です。選ぶとコマンド「着せ替え」（_dress）の反応が返り、断られなければ服装プロンプトが差し替わります。スケジュールで「服装固定」にした場面（就寝中など）では固定の服が優先されます。反応は 設定 → コマンド →「着せ替え」で、条件に outfit=maid のように着替え先を書いて作れます（outfit= で「おまかせ」）。'),
    h('div', { class: 'row', style: 'margin-bottom:10px' }, chk(c, 'dress_reset_on_sleep', '寝たらスケジュール通りの服に戻す')),
    list,
    h('button', { class: 'btn', onclick: () => { c.wardrobe.push({ id: 'outfit' + Date.now().toString(36), name: '新しい服', icon: '👕', when: '', pos: '', neg: '' }); draw(); } }, '＋服を追加'),
  ];
};

/* ---- ミニゲーム */
SEC.minigames = () => {
  const ta = h('textarea', { rows: 30, style: 'min-height:55vh', value: JSON.stringify(S.boot.minigames || [], null, 1) });
  const res = h('div', { class: 'result', hidden: true });
  ta.addEventListener('input', () => {
    try { JSON.parse(ta.value); ta.classList.remove('bad'); res.hidden = true; }
    catch (e) { ta.classList.add('bad'); res.hidden = false; res.className = 'result err'; res.textContent = 'JSON の書式エラー: ' + e.message; }
  });
  return [
    saveBar('ミニゲーム', async () => {
      await api('/api/minigames', { minigames: JSON.parse(ta.value) });
      await reloadAll();
    }, h('button', { class: 'btn', onclick: () => downloadJson('minigames.json', JSON.parse(ta.value)) }, 'ファイルに保存')),
    h('p', { class: 'lead' }, '遊べるミニゲームの定義です（JSON で直接編集）。kind は yakyuken（野球拳）か acchimuite（あっち向いてホイ）で、同じ kind で中身の違うゲームをいくつでも作れます。'),
    h('div', { class: 'keys' },
      h('div', {}, h('code', {}, 'require'), ' 遊べる条件（満たさないとボタンが押せない） / ', h('code', {}, 'when'), ' 誘いに乗る条件（満たさないと lines.refuse で断られる）'),
      h('div', {}, h('code', {}, 'stages'), ' 野球拳の段階。mode: add = 今の服に追記 / replace = 置き換え、remove = 外見プロンプトから外すタグ。', h('code', {}, 'giveup'), ' は降参時の服装'),
      h('div', {}, h('code', {}, 'lines'), ' 場面ごとのセリフ（反応と同じ書式: text / when / priority / pos / neg）。',
        '野球拳: refuse start hint draw round_win round_lose win lose quit interrupted、あっち向いてホイ: start hint draw rps_me rps_her point_me dodge_me point_her dodge_her win lose quit interrupted'),
      h('div', {}, h('code', {}, 'effects'), ' 場面ごとのパラメータ変化。セリフの置換: ', ['{her_hand}', '{my_hand}', '{hint_hand}', '{stage}', '{dir}', '{her_dir}'].map((k) => [h('code', {}, k), ' '])),
      h('div', {}, '条件で使える追加キー: ', ['game_stage', 'game_round', 'lives', 'my_point', 'her_point'].map((k) => [h('code', {}, k), ' ']))),
    h('div', { style: 'margin-top:10px' }, ta),
    res,
  ];
};

/* ---- コマンド */
SEC.actions = () => {
  const acts = SE.actions;
  const listBox = h('div', { class: 'ed-list' });
  const edBox = h('div');
  const drawList = () => {
    let cat = null;
    const els = [];
    acts.forEach((a, i) => {
      if (a.category !== cat) { cat = a.category; els.push(h('div', { class: 'catlbl' }, cat || 'その他')); }
      els.push(h('button', { class: i === SE.selAction ? 'on' : '', onclick: () => { SE.selAction = i; drawList(); drawEd(); } },
        h('span', {}, a.icon || '•'), h('span', {}, a.name || a.id), h('small', {}, (a.reactions || []).length + '反応')));
    });
    listBox.replaceChildren(...els);
  };
  const drawEd = () => {
    const a = acts[SE.selAction];
    if (!a) { edBox.replaceChildren(h('p', { class: 'muted' }, 'コマンドを選択してください')); return; }
    a.reactions = a.reactions || [];
    const reBox = h('div');
    const drawRe = () => {
      reBox.replaceChildren(...a.reactions.map((r, i) => h('div', { class: 'card' },
        h('div', { class: 'card-head' }, h('b', {}, `反応 ${i + 1}`),
          h('span', { class: 'muted small' }, r.when ? '条件: ' + r.when : '（いつでも）'),
          h('div', { class: 'spacer' }),
          h('button', { class: 'btn ghost', onclick: () => { moveIn(a.reactions, i, -1); drawRe(); } }, '↑'),
          h('button', { class: 'btn ghost', onclick: () => { moveIn(a.reactions, i, 1); drawRe(); } }, '↓'),
          h('button', { class: 'btn ghost', onclick: () => { a.reactions.splice(i + 1, 0, clone(r)); drawRe(); } }, '複製'),
          h('button', { class: 'btn ghost danger', onclick: () => { a.reactions.splice(i, 1); drawRe(); } }, '削除')),
        h('div', { class: 'grid4' },
          fld('セリフ / ナレーション', inp(r, 'text', { type: 'textarea', rows: 2 }), '（…）で始めるとナレーション。{call} {name} {player} {location} {activity_label} {time} が使えます', 'spanall'),
          fld('条件', inp(r, 'when', { ph: 'mood>=50' }), null, 'span2'),
          fld('優先度', inp(r, 'priority', { type: 'number' }), '一致した中で最大のものだけ候補'),
          h('div', { class: 'fld' }, h('span', { class: 'fl' }, '効果の扱い'), chk(r, 'override', '行動の効果・シーン切替を置き換える')),
          fld('追加の効果', inp(r, 'effects', { fmt: fmtEff, parse: parseEff, ph: 'affection:-2' }), null, 'span2'),
          fld('Positive（反応）', inp(r, 'pos', { type: 'textarea', rows: 2 }), null, 'span2'),
          fld('Negative（反応）', inp(r, 'neg', { type: 'textarea', rows: 2 }), null, 'spanall')))));
    };
    drawRe();
    const ovBox = h('div');
    const drawOv = () => {
      ovBox.replaceChildren(a.override ? h('div', { class: 'card' }, sceneFields(a.override, { minutes: true })) : '');
    };
    drawOv();
    const hasOv = { v: !!a.override };
    edBox.replaceChildren(
      h('div', { class: 'grid4' },
        fld('id', inp(a, 'id', { onchange: drawList })),
        fld('名前', inp(a, 'name', { onchange: drawList })),
        fld('アイコン', inp(a, 'icon', { onchange: drawList })),
        fld('カテゴリ', inp(a, 'category', { list: 'cat-list', onchange: drawList }), 'system = 非表示（_return は「おかえり」用）'),
        fld('実行できる条件', inp(a, 'when', { ph: 'free=true' }), null, 'span2'),
        fld('クールダウン（分）', inp(a, 'cooldown', { type: 'number' }), 'この間の連続実行は repeat が増え効果減'),
        fld('連続時の効果倍率', inp(a, 'repeat_scale', { type: 'number', step: '0.1', ph: '0.5' })),
        fld('効果', inp(a, 'effects', { fmt: fmtEff, parse: parseEff, ph: 'mood:+5, loneliness:-10' }), null, 'spanall'),
        fld('Positive（行動）', inp(a, 'pos', { type: 'textarea', rows: 2 }), null, 'span2'),
        fld('Negative（行動）', inp(a, 'neg', { type: 'textarea', rows: 2 }), null, 'span2'),
        h('div', { class: 'row spanall' },
          chk(a, 'replace_scene', '場面プロンプトを使わない（服装は残す）'),
          chk(a, 'no_llm', 'LLM を使わない'),
          h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: a.generate !== false, onchange: (ev) => { a.generate = ev.target.checked; } }), '自動で画像生成'),
          h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: hasOv.v, onchange: (ev) => {
            if (ev.target.checked) a.override = a.override || { activity: a.id, label: a.name + '中', location: '', minutes: 30, pos: '', neg: '', outfit: '', effects: {} };
            else delete a.override;
            drawOv();
          } }), '実行後、一時シーンに切り替える'))),
      ovBox,
      h('div', { class: 'sect' }, `反応（${a.reactions.length}）`),
      h('p', { class: 'hint' }, '条件に合う反応のうち優先度が最大のものから、条件の細かいものほど選ばれやすい重みでランダムに 1 つ選ばれます。'),
      reBox,
      h('button', { class: 'btn', onclick: () => { a.reactions.push({ text: '', when: '', pos: '', neg: '' }); drawRe(); } }, '＋反応を追加'),
    );
  };
  drawList();
  drawEd();
  const cats = [...new Set(acts.map((a) => a.category).filter(Boolean))];
  return [
    saveBar('コマンド', async () => { await api('/api/actions', { actions: acts }); await reloadAll(); }, h('div', { class: 'row' },
      h('button', { class: 'btn', onclick: () => { const a = acts[SE.selAction]; const n = { id: 'cmd' + Date.now().toString(36), name: '新しいコマンド', icon: '✦', category: a ? a.category : 'その他', when: 'free=true', cooldown: 10, effects: {}, pos: '', neg: '', reactions: [{ text: '', when: '', pos: '', neg: '' }] }; acts.splice(SE.selAction + 1, 0, n); SE.selAction++; drawList(); drawEd(); } }, '＋追加'),
      h('button', { class: 'btn', onclick: () => { const a = acts[SE.selAction]; if (!a) return; const n = clone(a); n.id += '_copy'; n.name += '（複製）'; acts.splice(SE.selAction + 1, 0, n); SE.selAction++; drawList(); drawEd(); } }, '複製'),
      h('button', { class: 'btn', onclick: () => { moveIn(acts, SE.selAction, -1); SE.selAction = Math.max(0, SE.selAction - 1); drawList(); } }, '↑'),
      h('button', { class: 'btn', onclick: () => { moveIn(acts, SE.selAction, 1); SE.selAction = Math.min(acts.length - 1, SE.selAction + 1); drawList(); } }, '↓'),
      h('button', { class: 'btn danger', onclick: () => { const a = acts[SE.selAction]; if (!a || !confirm(`「${a.name}」を削除しますか？`)) return; acts.splice(SE.selAction, 1); SE.selAction = Math.max(0, SE.selAction - 1); drawList(); drawEd(); } }, '削除'))),
    h('p', { class: 'lead' }, 'キャラへの行動と、その反応を編集します。行動・反応のどちらにも Positive / Negative プロンプトを指定でき、画像生成時に共通 → 主人公 → 服装 → 場面 → 時間帯 → 状態 → 行動 → 反応 の順で合成されます。'),
    paramKeysHint(),
    h('datalist', { id: 'cat-list' }, [...cats, 'system'].map((c) => h('option', { value: c }))),
    h('div', { class: 'ed', style: 'margin-top:14px' }, listBox, edBox),
  ];
};

/* ---- パラメータ */
SEC.params = () => {
  const ps = SE.params;
  const box = h('div');
  const draw = () => {
    box.replaceChildren(...ps.map((p, i) => {
      p.tags = p.tags || [];
      const tagBox = h('div', { class: 'mini-table' });
      const drawTags = () => tagBox.replaceChildren(
        h('div', { class: 'mini-row muted small' }, h('span', {}, '条件'), h('span', {}, '表示名'), h('span', {}, 'Positive'), h('span', {}, 'Negative'), h('span', {})),
        ...p.tags.map((t, j) => h('div', { class: 'mini-row' },
          inp(t, 'when'), inp(t, 'label'), inp(t, 'pos'), inp(t, 'neg'),
          h('button', { class: 'btn ghost danger', onclick: () => { p.tags.splice(j, 1); drawTags(); } }, '✕'))),
        h('div', {}, h('button', { class: 'btn ghost', onclick: () => { p.tags.push({ when: `${p.id}>=70`, label: '', pos: '', neg: '' }); drawTags(); } }, '＋状態タグ')));
      drawTags();
      const driftBox = h('div');
      const drawDrift = () => driftBox.replaceChildren(p.drift ? h('div', { class: 'grid3' },
        fld('目標値', inp(p.drift, 'target', { type: 'number' })),
        fld('戻る速さ（/時）', inp(p.drift, 'rate', { type: 'number', step: '0.01' }), '0.1 = 1時間で差の1割'),
        fld('目標の補正（条件 => 加算）', inp(p.drift, 'mods', { type: 'textarea', rows: 3, fmt: (v) => fmtRules(v, 'add'), parse: (s) => parseRules(s, 'add') }), 'satiety<25 => -15')) : '');
      drawDrift();
      return h('div', { class: 'card' },
        h('div', { class: 'card-head' }, h('b', {}, `${p.name}`), h('code', { class: 'muted small' }, p.id), h('div', { class: 'spacer' }),
          h('button', { class: 'btn ghost', onclick: () => { moveIn(ps, i, -1); draw(); } }, '↑'),
          h('button', { class: 'btn ghost', onclick: () => { moveIn(ps, i, 1); draw(); } }, '↓'),
          h('button', { class: 'btn ghost danger', onclick: () => { if (confirm(`「${p.name}」を削除しますか？`)) { ps.splice(i, 1); draw(); } } }, '削除')),
        h('div', { class: 'grid4' },
          fld('id', inp(p, 'id')), fld('名前', inp(p, 'name')),
          fld('分類', inp(p, 'group', { type: 'select', options: [['physical', 'からだ'], ['mental', 'こころ'], ['other', 'その他']] })),
          h('div', { class: 'fld' }, h('span', { class: 'fl' }, '表示'), h('div', { class: 'row' }, chk(p, 'invert', '高いほど悪い'), chk(p, 'neutral', '中立'))),
          fld('最小', inp(p, 'min', { type: 'number' })), fld('最大', inp(p, 'max', { type: 'number' })),
          fld('初期値', inp(p, 'init', { type: 'number' })), fld('基本変化（/時）', inp(p, 'rate', { type: 'number', step: '0.1' })),
          fld('変化の上書き（条件 => /時、最初に一致）', inp(p, 'rate_rules', { type: 'textarea', rows: 2, fmt: (v) => fmtRules(v, 'rate'), parse: (s) => parseRules(s, 'rate') }), 'asleep=true => 0', 'span2'),
          h('div', { class: 'fld span2' }, h('span', { class: 'fl' }, '自然回帰'),
            h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: !!p.drift, onchange: (ev) => {
              if (ev.target.checked) p.drift = p.drift || { target: p.init ?? 50, rate: 0.1, mods: [] }; else delete p.drift;
              drawDrift();
            } }), '目標値へ徐々に戻る（機嫌・照れなど）'))),
        driftBox,
        h('div', { class: 'sect' }, '状態タグ（条件を満たすとプロンプトに追加）'),
        tagBox);
    }));
  };
  draw();
  return [
    saveBar('パラメータ', async () => { await api('/api/params', { params: ps }); await reloadAll(); }, h('button', { class: 'btn', onclick: () => {
      ps.push({ id: 'p' + Date.now().toString(36), name: '新しいパラメータ', group: 'mental', min: 0, max: 100, init: 50, rate: 0, tags: [] });
      draw();
    } }, '＋追加')),
    h('p', { class: 'lead' }, 'リアル時間 5 分ごとに「基本変化 + 場面の毎時効果 + 自然回帰」で変化します。アプリを閉じている間も、次に開いたときにまとめて追いつき計算されます（最大 14 日）。'),
    paramKeysHint(),
    box,
  ];
};

/* ---- ComfyUI */
SEC.comfy = () => {
  const st = SE.settings, c = st.comfy;
  const res = h('div', { class: 'result', hidden: true });
  const dl = (id, items) => h('datalist', { id }, (items || []).map((x) => h('option', { value: x })));
  const lists = h('div', {}, dl('ck-list', SE.comfyInfo && SE.comfyInfo.checkpoints), dl('sm-list', SE.comfyInfo && SE.comfyInfo.samplers), dl('sc-list', SE.comfyInfo && SE.comfyInfo.schedulers));
  const wfRes = h('div', { class: 'result', hidden: !S.boot.has_workflow }, S.boot.has_workflow ? 'カスタムワークフロー登録済み' : '');
  const customBox = h('div');
  const drawMode = () => {
    customBox.hidden = c.workflow_mode !== 'custom';
  };
  customBox.append(
    h('p', { class: 'hint' }, 'ComfyUI で「Export (API)」した JSON を登録します。入力値に次のプレースホルダを書いておくと置換されます（文字列の一部でも可）: ',
      S.boot.placeholders.map((p, i) => [i ? ' ' : '', h('code', {}, p)])),
    h('div', { class: 'row' },
      h('button', { class: 'btn', onclick: async () => {
        try {
          const wf = await pickJson();
          const r = await api('/api/workflow', { workflow: wf });
          S.boot.has_workflow = true;
          wfRes.hidden = false; wfRes.className = 'result ' + (r.placeholders.includes('%POSITIVE%') ? 'ok' : 'err');
          wfRes.textContent = '登録しました。検出: ' + (r.placeholders.join(' ') || 'なし') + (r.placeholders.includes('%POSITIVE%') ? '' : '\n⚠ %POSITIVE% がありません。プロンプトが反映されません');
        } catch (e) { wfRes.hidden = false; wfRes.className = 'result err'; wfRes.textContent = e.message; }
      } }, 'JSON を読み込む'),
      h('button', { class: 'btn ghost', onclick: async () => { const r = await api('/api/workflow'); if (r.workflow) downloadJson('workflow_api.json', r.workflow); else toast('未登録です'); } }, '登録中の JSON を保存')),
    wfRes);
  drawMode();
  st.images = st.images || { mode: 'reuse', max_per_prompt: 8 };
  if (st.images.busy_reuse === undefined) st.images.busy_reuse = true;
  return [
    saveBar('画像生成 (ComfyUI)', async () => { await api('/api/settings', { settings: { comfy: c, auto_generate: st.auto_generate, images: st.images } }); await reloadAll(); }),
    h('p', { class: 'lead' }, 'ComfyUI の HTTP API に接続します。リモートの PC で動かす場合は ComfyUI を --listen 付きで起動してください。'),
    h('div', { class: 'grid4' },
      fld('ホスト / アドレス', inp(c, 'host', { ph: '127.0.0.1' }), null, 'span2'),
      fld('ポート', inp(c, 'port', { type: 'number' })),
      h('div', { class: 'fld' }, h('span', { class: 'fl' }, '　'), chk(c, 'use_https', 'HTTPS'))),
    h('div', { class: 'row', style: 'margin:10px 0' },
      h('button', { class: 'btn', onclick: async () => {
        res.hidden = false; res.className = 'result'; res.textContent = '接続中…';
        try {
          const r = await api('/api/comfy/info', { comfy: c });
          SE.comfyInfo = r;
          res.className = 'result ok';
          res.textContent = `接続OK: ${r.url}  ${(r.devices || []).join(', ')}\nチェックポイント ${(r.checkpoints || []).length} 件 / サンプラー ${(r.samplers || []).length} 件` + (r.warning ? '\n⚠ ' + r.warning : '');
          lists.replaceChildren(dl('ck-list', r.checkpoints), dl('sm-list', r.samplers), dl('sc-list', r.schedulers));
          if (!c.ckpt && r.checkpoints && r.checkpoints.length) { c.ckpt = r.checkpoints[0]; $('#ck-input').value = c.ckpt; }
        } catch (e) { res.className = 'result err'; res.textContent = e.message; }
      } }, '接続テスト'),
      chk(st, 'auto_generate', 'コマンド実行時に画像を表示する')),
    res, lists,
    h('div', { class: 'sect' }, '画像の出し方'),
    h('div', { class: 'grid3' },
      fld('同じプロンプトの画像があるとき', inp(st.images, 'mode', { type: 'select', options: [
        ['reuse', '既存の画像からランダムにすぐ表示'], ['always', '毎回新しく生成する']] }), null, 'span2'),
      fld('1プロンプトあたりの上限枚数', inp(st.images, 'max_per_prompt', { type: 'number' }),
        '「すぐ表示」のとき、この枚数に達するまでは裏で新規生成も行う（1 = 1枚あれば以降は生成しない）'),
      h('div', { class: 'fld spanall' }, chk(st.images, 'busy_reuse', '生成中にコマンドを実行したら、既存の画像があればそれを表示して新規生成しない（なければ待ち行列に追加）'))),
    h('p', { class: 'hint' }, '同じプロンプト = 合成後の Positive と Negative が完全に一致するもの（キャラをまたいでも共有）。表示中の画像は 🎲 で同じプロンプトの別の画像に、⟳ で新規生成に切り替えられます。'),
    h('div', { class: 'sect' }, 'ワークフロー'),
    h('div', { class: 'row' },
      ...[['builtin', '内蔵 txt2img'], ['custom', 'カスタム (API 形式 JSON)']].map(([v, l]) => h('label', { class: 'check' },
        h('input', { type: 'radio', name: 'wfmode', checked: c.workflow_mode === v, onchange: () => { c.workflow_mode = v; drawMode(); } }), l))),
    h('div', { class: 'grid4', style: 'margin-top:10px' },
      fld('チェックポイント', Object.assign(inp(c, 'ckpt', { list: 'ck-list', ph: '接続テストで候補が出ます' }), { id: 'ck-input' }), null, 'span2'),
      fld('幅', inp(c, 'width', { type: 'number', step: '8' })), fld('高さ', inp(c, 'height', { type: 'number', step: '8' })),
      fld('Steps', inp(c, 'steps', { type: 'number' })), fld('CFG', inp(c, 'cfg', { type: 'number', step: '0.5' })),
      fld('Sampler', inp(c, 'sampler', { list: 'sm-list' })), fld('Scheduler', inp(c, 'scheduler', { list: 'sc-list' })),
      fld('CLIP skip', inp(c, 'clip_skip', { type: 'number' }), '1 = なし（内蔵のみ）'),
      fld('生成のタイムアウト（秒）', inp(c, 'timeout_sec', { type: 'number' }), 'ComfyUI で実行が始まってから'),
      fld('キュー待ちの上限（秒）', inp(c, 'queue_timeout_sec', { type: 'number' }), 'ComfyUI が他の生成で混んでいるとき'),
      h('div', { class: 'fld' }, h('span', { class: 'fl' }, '通信'), chk(c, 'use_proxy', 'システムのプロキシを使う'))),
    h('p', { class: 'hint' }, 'カスタム時も 幅/高さ/Steps/CFG/チェックポイント などはプレースホルダ経由で使われます。'),
    customBox,
  ];
};

/* ---- 共通プロンプト・時間帯 */
SEC.prompt = () => {
  const pr = SE.settings.prompt, w = SE.world;
  w.phases = w.phases || [];
  const box = h('div', { class: 'mini-table' });
  const draw = () => box.replaceChildren(
    h('div', { class: 'mini-row muted small', style: 'grid-template-columns:.7fr .7fr .6fr .6fr 2fr 1.2fr auto' }, h('span', {}, 'id'), h('span', {}, '表示名'), h('span', {}, '開始'), h('span', {}, '終了'), h('span', {}, 'Positive'), h('span', {}, 'Negative'), h('span', {})),
    ...w.phases.map((p, i) => h('div', { class: 'mini-row', style: 'grid-template-columns:.7fr .7fr .6fr .6fr 2fr 1.2fr auto' },
      inp(p, 'id'), inp(p, 'label'), inp(p, 'from'), inp(p, 'to'), inp(p, 'pos'), inp(p, 'neg'),
      h('button', { class: 'btn ghost danger', onclick: () => { w.phases.splice(i, 1); draw(); } }, '✕'))),
    h('div', {}, h('button', { class: 'btn ghost', onclick: () => { w.phases.push({ id: 'new', label: '', from: '00:00', to: '01:00', pos: '', neg: '' }); draw(); } }, '＋時間帯')));
  draw();
  return [
    saveBar('共通プロンプト・時間帯', async () => {
      await api('/api/settings', { settings: { prompt: pr } });
      await api('/api/world', { world: w });
      await reloadAll();
    }),
    h('p', { class: 'lead' }, 'すべての画像に付く品質タグと、時刻による光の演出です。'),
    fld('共通 Positive（先頭）', inp(pr, 'prefix_pos', { type: 'textarea', rows: 2 })),
    fld('共通 Negative', inp(pr, 'prefix_neg', { type: 'textarea', rows: 3 })),
    h('div', { class: 'sect' }, '時間帯（条件キー phase の値）'),
    box,
    h('div', { class: 'sect' }, 'その他'),
    h('div', { class: 'grid3' }, fld('「おかえり」を出す不在時間（時間）', inp(w, 'absent_greet_hours', { type: 'number', step: '0.5' }))),
  ];
};

/* ---- LLM */
SEC.llm = () => {
  const l = SE.settings.llm;
  const res = h('div', { class: 'result', hidden: true });
  return [
    saveBar('セリフ生成 (LLM)', async () => { await api('/api/settings', { settings: { llm: l } }); await reloadAll(); }),
    h('p', { class: 'lead' }, '有効にすると、選ばれた定型セリフを「方向性の参考」としてローカル LLM にセリフを作らせます。失敗した場合は定型セリフのまま進みます。ナレーション（（…））の反応と「LLM を使わない」コマンドは定型のままです。'),
    h('div', { class: 'grid4' },
      h('div', { class: 'fld' }, h('span', { class: 'fl' }, '　'), chk(l, 'enabled', 'LLM を使う')),
      fld('種類', inp(l, 'kind', { type: 'select', options: [['ollama', 'Ollama'], ['openai', 'OpenAI 互換 (LM Studio / llama.cpp 等)']] })),
      fld('URL', inp(l, 'url', { ph: 'http://127.0.0.1:11434' }), 'OpenAI 互換は /v1 の手前まで', 'span2'),
      fld('モデル名', inp(l, 'model')), fld('API キー（必要な場合）', inp(l, 'api_key', { type: 'password' })),
      fld('temperature', inp(l, 'temperature', { type: 'number', step: '0.1' })), fld('タイムアウト（秒）', inp(l, 'timeout_sec', { type: 'number' })),
      h('div', { class: 'fld' }, h('span', { class: 'fl' }, '通信'), chk(l, 'use_proxy', 'システムのプロキシを使う'))),
    fld('システムプロンプト', inp(l, 'system', { type: 'textarea', rows: 5 }), '{name} {player} {call} {persona} が置換されます'),
    h('div', { class: 'row', style: 'margin-top:10px' }, h('button', { class: 'btn', onclick: async () => {
      res.hidden = false; res.className = 'result'; res.textContent = '問い合わせ中…';
      try { const r = await api('/api/llm/test', { llm: l }); res.className = 'result ok'; res.textContent = '応答: ' + r.text; }
      catch (e) { res.className = 'result err'; res.textContent = e.message; }
    } }, '接続テスト')),
    res,
  ];
};

/* ---- データ */
SEC.data = () => {
  const v = S.view;
  const vals = {};
  const sliders = S.boot.params.map((p) => {
    const out = h('span', { class: 'pval' }, Math.round(v.params[p.id] ?? 0));
    const r = h('input', { type: 'range', min: p.min ?? 0, max: p.max ?? 100, step: 1, value: v.params[p.id] ?? 0,
      oninput: (ev) => { vals[p.id] = Number(ev.target.value); out.textContent = ev.target.value; } });
    return h('div', { class: 'slider-row' }, h('span', {}, p.name), r, out);
  });
  return [
    h('div', { class: 'sbar' }, h('h3', {}, 'データ')),
    h('p', { class: 'lead' }, 'デバッグや調整用です。データは kurashi/data/ に JSON と画像で保存されています。'),
    h('div', { class: 'sect' }, `${v.name}の現在値を直接変更`),
    ...sliders,
    h('div', { class: 'row', style: 'margin-top:10px' },
      h('button', { class: 'btn primary', onclick: async () => { await api('/api/state/set', { values: vals }); toast('反映しました', 'ok'); await refresh(); } }, '反映'),
      h('button', { class: 'btn', onclick: async () => { await api('/api/state/clear_override', {}); toast('一時シーンを解除しました', 'ok'); await refresh(); } }, '一時シーンを解除（予定に戻す）'),
      h('button', { class: 'btn danger', onclick: async () => {
        if (!confirm('パラメータを初期値に戻しますか？（ログと画像は残ります）')) return;
        await api('/api/state/reset', {}); toast('初期化しました', 'ok'); await refresh(); showSection('data');
      } }, 'パラメータ初期化')),
    h('div', { class: 'sect' }, 'エクスポート / インポート'),
    h('div', { class: 'row' },
      h('button', { class: 'btn', onclick: () => downloadJson('actions.json', S.boot.actions) }, 'コマンドを保存'),
      h('button', { class: 'btn', onclick: () => downloadJson('params.json', S.boot.params) }, 'パラメータを保存'),
      h('button', { class: 'btn', onclick: () => downloadJson(`character_${S.boot.character.id}.json`, S.boot.character) }, '主人公を保存')),
    h('div', { class: 'row', style: 'margin-top:8px' },
      h('button', { class: 'btn', onclick: async () => { try { const j = await pickJson(); if (!Array.isArray(j)) throw new Error('配列ではありません'); await api('/api/actions', { actions: j }); await reloadAll(); toast('コマンドを読み込みました', 'ok'); } catch (e) { toast(e.message, 'err'); } } }, 'コマンドを読込'),
      h('button', { class: 'btn', onclick: async () => { try { const j = await pickJson(); if (!Array.isArray(j)) throw new Error('配列ではありません'); await api('/api/params', { params: j }); await reloadAll(); toast('パラメータを読み込みました', 'ok'); } catch (e) { toast(e.message, 'err'); } } }, 'パラメータを読込'),
      h('button', { class: 'btn', onclick: async () => { try { const j = await pickJson(); if (!j.id) throw new Error('id がありません'); await api('/api/character/save', { data: j }); await api('/api/character/select', { id: j.id }); S.current = null; await reloadAll(); toast('主人公を読み込みました', 'ok'); } catch (e) { toast(e.message, 'err'); } } }, '主人公を読込')),
  ];
};

/* ================================================================= events */
function bind() {
  $$('#tabs button').forEach((b) => b.addEventListener('click', () => {
    $$('#tabs button').forEach((x) => x.classList.toggle('on', x === b));
    for (const t of ['commands', 'dress', 'games', 'status', 'log']) $('#tab-' + t).hidden = t !== b.dataset.tab;
  }));
  $('#dialogue').addEventListener('click', () => {
    if (S.typing) { clearInterval(S.typing); S.typing = null; $('#dtext').textContent = S.typingText; }
  });
  $('#char-select').addEventListener('change', async (ev) => {
    await api('/api/character/select', { id: ev.target.value });
    S.current = null;
    const img = $('#stage-img'); img.removeAttribute('src'); delete img.dataset.rel; img.classList.remove('show');
    $('#stage-bg').style.backgroundImage = '';
    await loadBoot(); await refresh();
    try { const r = await api('/api/visit', {}); if (r.result) handleActResult(r.result); } catch (e) { /* noop */ }
  });
  $('#btn-settings').addEventListener('click', () => openSettings());
  $('#btn-gallery').addEventListener('click', openGallery);
  $$('#snav button').forEach((b) => b.addEventListener('click', () => showSection(b.dataset.sec)));
  $$('[data-close]').forEach((b) => b.addEventListener('click', () => b.closest('dialog').close()));
  $('#settings-dlg').addEventListener('close', () => refresh());
  $('#btn-prompt').addEventListener('click', () => {
    const d = $('#prompt-drawer');
    d.hidden = !d.hidden;
    if (!d.hidden) fillPromptDrawer(S.current);
  });
  $('#pd-close').addEventListener('click', () => { $('#prompt-drawer').hidden = true; });
  $('#jp-close').addEventListener('click', () => { $('#jobs-panel').hidden = true; });
  $('#jp-cancel-all').addEventListener('click', async () => {
    const r = await api('/api/job/cancel', { all: true });
    toast(`${r.cancelled}件を取り消しました`);
    renderJobs();
  });
  $('#jp-test').addEventListener('click', async () => {
    try {
      const r = await api('/api/comfy/info', {});
      toast(`接続OK: ${r.url}（チェックポイント ${(r.checkpoints || []).length}件）${r.warning ? ' ⚠ ' + r.warning : ''}`, 'ok');
    } catch (e) { toast(e.message, 'err'); }
  });
  $('#pd-load').addEventListener('click', async () => {
    const r = await api('/api/prompt');
    $('#pd-pos').value = r.pos; $('#pd-neg').value = r.neg; renderParts(r.parts);
    $('#pd-src').textContent = '今の状態から組み立て';
  });
  $('#pd-regen').addEventListener('click', () => genFromDrawer(true));
  $('#pd-new').addEventListener('click', () => genFromDrawer(false));
  $('#btn-regen').addEventListener('click', async () => {
    if (!S.current || !S.current.pos) return toast('再生成できる記録がありません');
    try { const r = await api('/api/generate', { entry: S.current.id }); trackJob(r.job); } catch (e) { toast(e.message, 'err'); }
  });
  $('#btn-reroll').addEventListener('click', async () => {
    if (!S.current || !S.current.pos) return toast('表示中の記録がありません');
    try {
      const r = await api('/api/reroll', { entry: S.current.id });
      showEntry(r.entry, false);
      setImage(r.entry.image);
      await refresh();
    } catch (e) { toast(e.message, 'err'); }
  });
  $('#btn-snap').addEventListener('click', async () => {
    try { const r = await api('/api/generate', {}); showEntry(r.entry, false); trackJob(r.job); await refresh(); } catch (e) { toast(e.message, 'err'); }
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
}

async function init() {
  bind();
  try { await loadBoot(); } catch (e) { toast('サーバに接続できません: ' + e.message, 'err'); return; }
  await refresh();
  try { const r = await api('/api/visit', {}); if (r.result) handleActResult(r.result); } catch (e) { toast(e.message, 'err'); }
  tickClock();
  setInterval(tickClock, 1000);
  setInterval(refresh, 30000);
}
init();
