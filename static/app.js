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
  const ws = $('#world-select');
  ws.replaceChildren(...S.boot.worlds.worlds.map((w) => h('option', { value: w.id }, '🌐 ' + w.name)));
  ws.value = S.boot.worlds.current;
  ws.hidden = S.boot.worlds.worlds.length < 2;
  $('#nameplate').textContent = S.boot.character.name;
}

// ワールドを切り替えたら, キャラ・ログ・お金・在席がすべて別になるので画面ごと読み直す
async function switchWorld(id) {
  await api('/api/world/switch', { id });
  location.reload();
}

async function refresh() {
  try {
    S.view = await api('/api/state?beat=1&idle=' + idleSec());
  } catch (e) {
    toast('状態の取得に失敗: ' + e.message, 'err');
    return;
  }
  for (const j of S.view.jobs) if (!S.jobs.has(j.id)) trackJob(j.id);
  if (S.view.gap) toast(S.view.gap.text, 'ok');
  if (S.view.street_auto) toast(S.view.street_auto.text.split('\n')[0], 'ok');
  for (const m of S.view.replies || []) toast(`📱 ${m.name}から返信: ${m.text.replace(/\n.*/s, '').slice(0, 60)}`, 'ok');
  renderWho();
  renderAway();
  renderApproach();
  renderRequest();
  renderEncounter();
  renderStreet();
  renderOffline();
  const cb = $('#chat-badge');
  cb.hidden = !S.view.chat_unread;
  cb.textContent = S.view.chat_unread > 99 ? '99+' : String(S.view.chat_unread || '');
  if (S.chatDlg && S.chatDlg.open) drawChat();
  renderCommands();
  renderDress();
  renderGames();
  renderStatus();
  renderMoney();
  renderItems();
  renderLog();
  if (!S.current && S.view.log.length) showEntry(S.view.log[S.view.log.length - 1], false);
  if (!S.view.log.length && !S.current) showGreeting();
  showAutoEntry();
}

function showGreeting() {
  const n = S.boot.character.name;
  const b = S.view.bond;
  // 離れている相手は, 間柄 (段階) に合わせて言う
  const apart = {
    known: `（${n}とは顔見知り。連絡先は知らないので、出先で偶然会えたら話せるかもしれない）`,
    contact: `（${n}とは連絡先を知っている仲。メッセージを送ったり、お出かけに誘ったりしてみよう）`,
    visit: `（${n}とは家を行き来する仲。メッセージを送ったり、家に遊びに行ったりしてみよう）`,
  };
  setDialogue(b && !b.mode
    ? apart[b.stage] || apart.contact
    : `（${n}との暮らしが始まった。右のコマンドから話しかけてみよう）`, false);
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
  if (S.view && S.view.approach) {
    const rest = Math.max(0, Math.round(S.view.approach.until - Date.now() / 1000));
    const el = $('#ap-rest');
    if (el) el.textContent = `（あと${Math.ceil(rest / 60)}分）`;
    if (rest === 0 && !S.apRefresh) { S.apRefresh = true; refresh().finally(() => { S.apRefresh = false; }); }
  }
}

/* ---------------------------------------------------------------- who / scene */
// 離れている相手 (同居して家にいる / 会っている 以外) の様子は, 既定では見えない (設定 → 表示 で見られる)
const veiled = () => !!(S.view && S.view.bond && !S.view.bond.mode && !S.ui.showApart);
function moodFace(p) {
  if (veiled()) return '❔';
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

const BOND_IC = { known: '👤', contact: '📱', visit: '🔑', live: '🏠' };
function renderWho() {
  const v = S.view;
  const sel = $('#char-select');
  const rank = (b) => (b && b.mode ? 0 : 1) * 10 + ({ live: 0, visit: 1, contact: 2, known: 3 }[b && b.stage] ?? 4);
  for (const o of [...sel.options].sort((x, y) => rank((v.bonds || {})[x.value]) - rank((v.bonds || {})[y.value]))) {
    const b = (v.bonds || {})[o.value];   // キャラ切替に, あなたとの間柄を添える (一緒にいる人から順に)
    const c = S.boot.characters.find((x) => x.id === o.value);
    if (b && c) o.textContent = `${BOND_IC[b.stage] || ''} ${c.name}${b.mode && b.mode !== 'home' ? '（一緒）' : ''}`;
    sel.append(o);
  }
  sel.value = v.character;
  $('#phase-chip').textContent = v.phase.label || '—';
  const wx = (v.outdoor || {}).weather;
  $('#weather-chip').textContent = wx ? `${wx.icon} ${wx.label}` : '';
  // 誰と暮らしているか・いまそばに誰がいるか (いなければ, そうはっきり書く)
  const nm = (id) => (S.boot.characters.find((x) => x.id === id) || {}).name || '';
  const liv = v.bond && v.bond.living;
  const near = Object.entries(v.bonds || {}).filter(([, b]) => b.mode).map(([id]) => nm(id));
  const hc = $('#home-chip');
  const hm = v.home || {};
  hc.textContent = `🏠 ${liv ? nm(liv) + 'と同居' : '一人暮らし'}・${near.length ? 'そばに' + near.join('、') : 'いまは一人'}${hm.label ? '・' + hm.label : ''}`;
  hc.title = `${liv ? nm(liv) + 'と暮らしている' : '誰とも暮らしていない（一人暮らし）'}。${near.length ? 'いまそばにいるのは ' + near.join('、') : 'いまそばには誰もいない'}。家は「${hm.label || '—'}」（クリックで家の様子）`;
  hc.dataset.level = String(hm.level ?? '');
  if (S.homeDlg && S.homeDlg.open) drawHome();
  const hide = veiled();
  const sc = v.scene;
  const where = sc.location ? `📍${sc.location}` : '';
  const peek = hide && v.peek;     // 電話で話したので, いまどこで何をしているかだけは分かる
  $('#scene-chip').textContent = hide && !peek ? `📱 ${v.name}とは離れている` : `${peek ? '📞 ' : ''}${where}　${sc.label || ''}`.trim();
  $('#who-name').textContent = v.name;
  $('#who-scene').replaceChildren(...(hide && !peek ? ['離れていて、いまの様子はわからない'] : peek ? [`電話で聞いた: ${sc.label}${sc.location ? '（' + sc.location + '）' : ''}`] : [
    `${sc.label}${sc.location ? '（' + sc.location + '）' : ''}`,
    sc.source === 'override' ? h('span', { class: 'muted', id: 'ov-rest', style: 'margin-left:6px' }) : null,
  ]).filter(Boolean));
  const face = $('#who-face');
  const lastImg = [...v.log].reverse().find((e) => e.image);
  if (lastImg) { face.style.backgroundImage = `url("${imgUrl(lastImg.image)}")`; face.textContent = ''; face.title = moodFace(v.params); }
  else { face.style.backgroundImage = ''; face.textContent = moodFace(v.params); }
  $('#who-tags').replaceChildren(
    h('span', { class: 'tag', style: 'background:#2b2540;color:#d9d0ff' }, moodFace(v.params)),
    v.bond ? h('span', { class: 'tag bond' + (v.bond.mode ? '' : ' apart'), title: 'あなたとの間柄・いまどこで会っているか' },
      `${BOND_IC[v.bond.stage] || ''}${v.bond.stage_label}・${v.bond.label}`) : '',
    v.pending_msg ? h('span', { class: 'tag', title: '送ったメッセージへの返信は、相手の状況しだい（来ないことも）' }, '📱 返信待ち') : '',
    !hide && v.dress && v.dress.wearing ? h('span', { class: 'tag dress' }, '👗' + v.dress.wearing) : '',
    !hide && v.life && v.life.hint ? h('span', { class: 'tag hint', title: '「何かあった？」で聞いてみよう' },
      v.life.hint_mood === 'good' ? '✨うれしそう' : '💭何かあったみたい') : '',
    ...(hide ? [] : v.tags.map((t) => h('span', { class: 'tag' }, t.label))),
  );
}

/* ---------------------------------------------------------------- commands */
// 「何を、誰と（あるいは一人で）するか」: 上に「一人で」、下に「〇〇と」（相手はここで選ぶ）
const isSoloAction = (a) => a.category === 'あなたの予定' || a.id === 'side_job';
const isPlainGo = (a) => a.category === 'あなたの予定' && /^go_/.test(a.id);   // 一人で欄では, 告げる相手の有無で出し分ける
function cmdButton(a) {
  const st = S.view.available[a.id];
  const tip = [a.when ? '条件: ' + a.when : '', S.ui.deltas !== false && a.effects && Object.keys(a.effects).length ?
    '効果: ' + Object.entries(a.effects).map(([k, v]) => `${pname(k)}${v > 0 ? '+' : ''}${v}`).join(' ') : '',
    st.cooldown ? `連続実行で効果減 (あと${Math.ceil(st.cooldown / 60)}分)` : ''].filter(Boolean).join('\n');
  return h('button', { class: 'cmd', disabled: !st.ok || S.busy, title: tip, onclick: () => (a.id === 'side_job' ? openTask() : a.id === 'message' && S.view.bond && !S.view.bond.mode ? openChat(S.view.character) : ['gift', 'expensive_gift'].includes(a.id) ? giftPicker(a.id) : (!a.confirm || confirm(a.confirm)) && doAct(a.id)) },
    h('span', { class: 'ic' }, a.icon || '•'), h('span', {}, a.name),
    st.cooldown ? h('span', { class: 'cd' }, '♻') : null);
}

function renderSolo(soloActs) {
  const v = S.view, so = v.solo || {};
  const free = (v.presence || {}).mode === 'none';
  const btn = (icon, label, onclick, tip) => h('button', { class: 'cmd', disabled: !free || S.busy, title: tip || '', onclick },
    h('span', { class: 'ic' }, icon), h('span', {}, label));
  const kinds = (so.kinds || []).map((k) => k.id === 'practice'
    ? btn(k.icon, k.label, () => { S.practiceOpen = !S.practiceOpen; renderCommands(); }, '会話・スキンシップ・料理・仕事のどれかを練習する（戻るまで）')
    : (OD_CHOICES()[k.id] && OD_CHOICES()[k.id].length === 1 ? btn(k.icon, k.label, () => soloStart(k.id, null, OD_CHOICES()[k.id][0]),
      '出かける。画面を開いているあいだだけ（閉じたら家に帰る）。偶然の出会いはその間に')
    : OD_CHOICES()[k.id] ? btn(k.icon, k.label, () => { S.placeFor = S.placeFor === k.id ? null : k.id; renderCommands(); },
      '行き先を選んで出かける。画面を開いているあいだだけ（閉じたら家に帰る）。偶然の出会いはその間に')
      : btn(k.icon, k.label, () => soloStart(k.id), '家で、戻るまで')));
  // 誰かと一緒にいるときは畳んでおく (開け閉めは覚える)
  const open = S.soloOpen ?? !(v.bond && v.bond.mode);
  const head = h('div', { class: 'with-head', style: 'cursor:pointer', title: '開く／畳む',
    onclick: () => { S.soloOpen = !open; renderCommands(); } }, `${open ? '▾' : '▸'} 🧍 一人で`,
    so.current ? h('span', { class: 'muted small', style: 'margin-left:8px' }, `${so.current.icon} ${so.current.doing}`) : null);
  // 家での一人の時間・作業の最中は, ここに「終わる」を出す (畳んでいても見えるように見出しのすぐ下)
  const pres = v.presence || {};
  const busyNow = pres.mode === 'busy' ? h('div', { class: 'solo-now' },
    h('span', {}, pres.solo ? `${pres.solo.icon} ${pres.solo.label}…` : '🖥 作業中…'),
    h('span', { class: 'muted small' }, '終えると、過ごした時間で結果が出ます'),
    h('button', { class: 'btn primary small', disabled: S.busy, onclick: comeBack }, pres.solo ? `${pres.solo.label.replace(/中$/, '')}を終える` : '作業を終える')) : null;
  if (!open) return h('div', { class: 'cat solo' }, head, busyNow);
  return h('div', { class: 'cat solo' },
    head,
    busyNow,
    h('div', { class: 'cmds' }, ...kinds,
      h('button', { class: 'cmd', disabled: S.busy, title: '今日の出来事から日記をつける（読み返しもここから）', onclick: openDiary },
        h('span', { class: 'ic' }, '📓'), h('span', {}, so.diary_today ? '日記（今日の分あり）' : '日記をつける')),
      // 作業する・出かける・仕事・寝る・席を外す: そばに誰かいれば「〜してくるね」と告げる形、いなければ一人で
      ...(so.plain || []).map((p) => h('button', { class: 'cmd', disabled: !free || !p.ok || S.busy,
        title: so.near ? `${so.near.name}に告げてから` : '告げる相手はいない（一人で）', onclick: () => (OD_CHOICES()[p.id] ? (S.placeFor = S.placeFor === p.id ? null : p.id, renderCommands()) : soloStart(p.id)) },
        h('span', { class: 'ic' }, p.icon), h('span', {}, p.label))),
      ...soloActs.filter((a) => !isPlainGo(a)).map(cmdButton)),
    S.placeFor && free ? h('div', { class: 'cmds', style: 'margin-top:6px' },
      h('div', { class: 'muted small', style: 'grid-column:1/-1' }, '行き先（人の多さは時間帯と天気しだい）'),
      OD_CHOICES()[S.placeFor].map((pl) => { const P = (S.view.outdoor.places || {})[pl] || {}; return btn(P.icon || '📍', P.label || pl, () => { const k = S.placeFor; S.placeFor = null; soloStart(k, null, pl); }); })) : null,
    S.practiceOpen && free ? h('div', { class: 'cmds', style: 'margin-top:6px' },
      Object.entries(so.skills || {}).map(([id, label]) => btn('📚', `${label}の練習`, () => { S.practiceOpen = false; soloStart('practice', id); }))) : null);
}

const OD_CHOICES = () => (S.view && S.view.outdoor && S.view.outdoor.choices) || {};
async function soloStart(kind, skill, place) {
  if (S.busy) return;
  S.busy = true;
  try {
    const r = await api('/api/solo/start', { kind, skill, place });
    if (r.act) handleActResult(r.act); else toast(`${r.label}…`, 'ok');
  } catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await refresh(); }
}

// 自宅の様子: 散らかり・洗い物・洗濯物・ゴミ. 招く前に確かめて片付けられるように
function openHome() {
  if (!S.homeDlg) {
    S.homeDlg = h('dialog', { class: 'modal home-dlg' });
    document.body.append(S.homeDlg);
  }
  drawHome();
  if (!S.homeDlg.open) S.homeDlg.showModal();
}
function drawHome() {
  const v = S.view || {};
  const hm = v.home || { parts: [] };
  const free = (v.presence || {}).mode === 'none';
  const soap = ((v.items || {}).items || []).find((x) => x.id === 'detergent');
  const bar = (val) => h('div', { class: 'home-bar' }, h('div', { class: 'home-fill lv' + Math.min(4, Math.floor(val / 20)), style: `width:${Math.max(2, Math.min(100, val))}%` }));
  const guest = Object.entries(v.bonds || {}).find(([, b]) => b.mode === 'guest');
  S.homeDlg.replaceChildren(h('div', { style: 'padding:16px' },
    h('div', { class: 'row' }, h('h3', { style: 'margin:0' }, '🏠 家の様子'), h('div', { class: 'spacer' }),
      h('button', { class: 'btn ghost small', onclick: () => S.homeDlg.close() }, '✕')),
    h('div', { class: 'home-sum lv' + (hm.level ?? 0) }, hm.label || '—',
      h('span', { class: 'muted small' }, `　散らかり具合 ${Math.round(hm.score || 0)} / 100（0 がいちばんきれい）`)),
    bar(hm.score || 0),
    h('div', { class: 'home-parts' }, hm.parts.map((p) => h('div', { class: 'home-part' },
      h('div', { class: 'row' }, h('b', {}, p.label), h('div', { class: 'spacer' }), h('span', { class: 'small' }, p.word)),
      bar(p.value)))),
    hm.hint ? h('p', { class: 'small', style: 'margin:8px 0 0' }, `⚠ ${hm.hint}`) : '',
    h('p', { class: 'hint' }, '暮らしているうちに少しずつ散らかり（料理のあとは洗い物、来客のあとは少し散らかる）、家事や「一緒に掃除」で片付きます。洗剤があるとはかどります。',
      h('br'), '家に招いた相手は、来たときの家の様子を見ます。片付いていれば好印象を持ってもらえることもありますが、気づかないことも。散らかっていると、気にするか、気にしないか、片付けを手伝い出すかは性格しだいです。同居している相手も、日々の家の様子に気づきます。'),
    guest ? h('p', { class: 'small' }, `いま${(S.boot.characters.find((x) => x.id === guest[0]) || {}).name || ''}が家に来ています。`) : '',
    h('div', { class: 'row' },
      h('button', { class: 'btn primary', disabled: !free || S.busy, title: free ? '家事をする（一人の時間）' : 'いまは始められません',
        onclick: () => { S.homeDlg.close(); soloStart('chores'); } }, '🧹 家事をする'),
      h('span', { class: 'muted small' }, soap ? `洗剤 ${soap.count} 個` : '洗剤なし（買い物で買えます）'))));
}

async function openDiary() {
  const dlg = h('dialog', { class: 'modal', style: 'width:min(640px,94vw);height:auto;max-height:86vh;overflow:auto' });
  const close = () => { dlg.close(); dlg.remove(); };
  const draw = async () => {
    const r = await api('/api/diary');
    dlg.replaceChildren(h('div', { style: 'padding:16px' },
      h('h3', {}, '📓 日記'),
      h('div', { class: 'row', style: 'justify-content:flex-end' },
        h('button', { class: 'btn primary', onclick: async (ev) => {
          ev.target.disabled = true;
          try { await api('/api/diary/write', {}); await draw(); } catch (e) { toast(e.message, 'err'); ev.target.disabled = false; }
        } }, (S.view.solo || {}).diary_today ? '今日の日記を書き直す' : '今日の日記をつける'),
        h('button', { class: 'btn', onclick: close }, '閉じる')),
      r.diary.length ? [...r.diary].reverse().map((d) => h('div', { class: 'diary-day' },
        h('div', { class: 'muted small' }, `${d.day}${d.src === 'llm' ? '（LLM）' : ''}`),
        h('div', { style: 'white-space:pre-wrap' }, d.text))) : h('p', { class: 'muted' }, 'まだ日記はありません。')));
  };
  document.body.append(dlg);
  dlg.showModal();
  await draw();
  refresh();
}

function renderCommands() {
  const box = $('#tab-commands');
  const av = S.view.available;
  const cats = new Map();
  const soloActs = [];
  let hidden = 0;
  for (const a of S.boot.actions) {
    if (a.category === 'system' || !av[a.id]) continue;
    if (!av[a.id].ok && !S.showHidden) { hidden++; continue; }
    if (isSoloAction(a)) { soloActs.push(a); continue; }
    if (!cats.has(a.category)) cats.set(a.category, []);
    cats.get(a.category).push(a);
  }
  const out = [renderSolo(soloActs)];
  const b = S.view.bond || {};
  out.push(h('div', { class: 'with-head' }, '👥 ', $('#char-select'), h('span', {}, ' と'),
    h('span', { class: 'muted small', style: 'margin-left:8px' }, (b.label || '') + (S.view.pending_msg ? '・📱返信待ち' : ''))));
  for (const [cat, list] of cats) {
    out.push(h('div', { class: 'cat' },
      h('div', { class: 'cat-title' }, cat || 'その他'),
      h('div', { class: 'cmds' }, list.map(cmdButton))));
  }
  if (!cats.size) out.push(h('p', { class: 'muted' }, b.stage === 'known' ? '連絡先を知らないので、いまはできることがない。偶然会えたら……' : '今できることはなさそうだ…'));
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
function tileEl(t, o = {}) {
  let top, bot, cls;
  if (t >= 27) { top = MJ_HONOR[t - 27]; bot = ''; cls = 'z' + (t - 26); }
  else { const n = t % 9 + 1, s = Math.floor(t / 9); top = s === 0 ? MJ_NUM[n - 1] : String(n); bot = '萬筒索'[s]; cls = 'mps'[s]; }
  return h(o.onclick ? 'button' : 'div', {
    class: `tile ${cls}${o.small ? ' small' : ''}${o.hl ? ' hl' : ''}${o.dim ? ' dim' : ''}${o.drawn ? ' drawn' : ''}`,
    disabled: o.disabled, onclick: o.onclick, title: o.title || '',
  }, h('span', { class: 't-top' }, top), bot ? h('span', { class: 't-bot' }, bot) : '');
}
const tileBack = (small) => h('div', { class: 'tile back' + (small ? ' small' : '') });

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
  if (o.back) return h('div', { class: 'hcard back' + (o.small ? ' small' : '') });
  const m = Math.floor(id / 4), [k, name, pic] = HF_CARDS[id];
  const red = name === '赤短', blue = name === '青短';
  return h(o.onclick ? 'button' : 'div', {
    class: `hcard k-${k}${red ? ' aka' : ''}${blue ? ' ao' : ''}${o.small ? ' small' : ''}${o.hl ? ' hl' : ''}${o.dim ? ' dim' : ''}`,
    onclick: o.onclick, disabled: o.disabled, title: `${HF_MONTH[m]}（${m + 1}月）${name ? 'に' + name : 'のカス'}・${HF_KIND[k]}`,
  }, h('span', { class: 'hc-m' }, HF_MONTH[m]), h('span', { class: 'hc-pic' }, pic || HF_EMOJI[m]),
  h('span', { class: 'hc-n' }, name || 'カス'));
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
  if (r.encounter) toast(r.encounter.text, 'ok');
  if (r.solo) toast(r.solo.text, 'ok');
  if (r.work_note) toast(r.work_note, 'err');
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

/* ---- 会話欄の表示設定 (ブラウザごとに保存) */
const UI_KEY = 'kurashi.ui';
const UI_DEFAULT = { pos: 'bottom', alpha: 0.82, font: 17, compact: false, autoHide: 0, deltas: true, stats: 'exact', showApart: false, callSound: true };
S.ui = (() => {
  try { return Object.assign({}, UI_DEFAULT, JSON.parse(localStorage.getItem(UI_KEY) || '{}')); } catch (e) { return Object.assign({}, UI_DEFAULT); }
})();
function saveUi() {
  try { localStorage.setItem(UI_KEY, JSON.stringify(S.ui)); } catch (e) { /* 保存できなくても表示はできる */ }
  applyUi();
  if (S.view) { renderStatus(); renderCommands(); }
}
function applyUi() {
  const st = $('#stage');
  st.classList.toggle('dlg-top', S.ui.pos === 'top');
  st.classList.toggle('dlg-below', S.ui.pos === 'below');
  st.classList.toggle('dlg-compact', !!S.ui.compact);
  st.style.setProperty('--dlg-alpha', S.ui.alpha);
  st.style.setProperty('--dlg-font', S.ui.font + 'px');
  fitDialogueSpace();
}
function fitDialogueSpace() {   // 「画像の下に分ける」とき, 会話欄の高さぶん画像を縮める
  $('#stage').style.setProperty('--dlg-space', ($('#dialogue').offsetHeight + 20) + 'px');
}
function setDlgHidden(v) {
  S.dlgHidden = v;
  $('#stage').classList.toggle('dlg-hidden', v);
  $('#btn-dlg').classList.toggle('off', v);
  clearTimeout(S.dlgTimer);
}
function scheduleAutoHide(ms) {
  clearTimeout(S.dlgTimer);
  if (S.ui.autoHide > 0) S.dlgTimer = setTimeout(() => setDlgHidden(true), ms + S.ui.autoHide * 1000);
}

function setDialogue(text, animate, name) {
  const dlg = $('#dialogue');
  setDlgHidden(false);                 // 新しいセリフが来たら出す
  scheduleAutoHide(animate ? [...text].length * 28 : 0);
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
  $('#deltas').replaceChildren(...Object.entries(S.ui.deltas === false ? {} : (e.deltas || {})).map(([k, v]) => {
    const p = S.boot.params.find((x) => x.id === k) || {};
    const cls = p.neutral ? '' : ((v > 0) !== !!p.invert ? 'up' : 'down');
    return h('span', { class: 'delta ' + cls }, `${pname(k)} ${v > 0 ? '+' : ''}${v}`);
  }), ...Object.entries(e.money || {}).map(([k, v]) => h('span', { class: 'delta money ' + (v > 0 ? 'up' : 'down') },
    `${k === 'p' ? 'あなた' : S.boot.character.name} ${v > 0 ? '+' : ''}${yen(v)}`)),
  ...Object.entries(e.skill || {}).map(([k, v]) => h('span', { class: 'delta skill up' }, `${SKILL_NAME[k] || k}スキル +${v}`)));
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

const yen = (n) => `${Math.round(n).toLocaleString()}円`;

const SKILL_NAME = { talk: '会話', touch: 'スキンシップ', cook: '料理', work: '仕事' };
function sparkline(vals, title) {
  const w = 300, hgt = 36, mn = Math.min(...vals), mx = Math.max(...vals), span = mx - mn || 1;
  const pts = vals.map((v, i) => `${(i / (vals.length - 1)) * w},${hgt - ((v - mn) / span) * (hgt - 4) - 2}`).join(' ');
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${w} ${hgt}`);
  svg.setAttribute('class', 'spark');
  const pl = document.createElementNS(NS, 'polyline');
  pl.setAttribute('points', pts);
  pl.setAttribute('fill', 'none');
  pl.setAttribute('stroke', vals[vals.length - 1] >= vals[0] ? 'var(--good)' : 'var(--bad)');
  pl.setAttribute('stroke-width', '2');
  svg.append(pl);
  return h('div', { class: 'spark-wrap', title: title || '' }, svg);
}

/* ---- キャラからのお願い */
function renderRequest() {
  const box = $('#request-box');
  const req = S.view.life && S.view.life.request;
  if (!req) { box.hidden = true; return; }
  const name = S.view.name;
  const label = { money: `お金を貸してほしいみたい（${yen(req.amount)}）`, gift: `買ってほしいものがあるみたい（${yen(req.amount)}）`,
    treat: 'ごちそうしたいみたい', present: 'プレゼントを用意してくれたみたい' }[req.kind] || req.label;
  box.hidden = false;
  box.replaceChildren(
    h('div', { class: 'req-text' }, h('b', {}, `💬 ${name}：`), label, req.text ? h('div', { class: 'muted small' }, `（${req.text}）`) : ''),
    h('div', { class: 'row' },
      h('button', { class: 'btn primary', disabled: S.busy, onclick: () => doAct('_req_yes') },
        req.kind === 'present' ? '受け取る' : req.kind === 'treat' ? 'ごちそうになる' : 'いいよ'),
      req.kind !== 'present' ? h('button', { class: 'btn', disabled: S.busy, onclick: () => doAct('_req_no') }, 'ごめんね') : ''));
}

/* ---- 偶然知り合った人: 登録する (連絡先を交換する) か */
function renderEncounter() {
  const box = $('#encounter-box');
  const en = S.view.encounter;
  if (!en) { box.hidden = true; return; }
  const answer = async (yes) => {
    try {
      const r = await api('/api/encounter', { yes });
      if (r.registered) { toast(`${r.registered.name}を登録しました（キャラ切替から連絡できます）`, 'ok'); await loadBoot(); }
    } catch (e) { toast(e.message, 'err'); }
    await refresh();
  };
  box.hidden = false;
  box.replaceChildren(
    h('div', { class: 'req-text' }, h('b', {}, `🤝 ${en.where}で${en.name}と知り合った`),
      h('div', { class: 'muted small' }, [en.persona ? `${en.persona}な感じの人` : '', en.with ? `${en.with}と一緒のとき` : '',
        '連絡先を交換して、このワールドに登録しますか？'].filter(Boolean).join('。'))),
    h('div', { class: 'row' },
      h('button', { class: 'btn primary', onclick: () => answer(true) }, '登録する'),
      h('button', { class: 'btn', onclick: () => answer(false) }, 'やめておく')));
}

/* ---- スマホ: 外出中・仕事中・一人の時間でも, そばにいない相手にメッセージ・電話できる.
   メッセージの返信は相手の状況しだいで遅れる/来ない. 電話は出ないことも (あとで折り返しが来ることも) */
function phonePanel() {
  const cs = S.view.contacts || [];
  if (!cs.length) return '';
  const open = !!S.phoneOpen;
  const send = async (cid, action) => {
    if (S.busy) return;
    S.busy = true;
    try {
      const r = await api('/api/act', { action, character: cid });
      toast(r.entry.text.replace(/\n.*/s, ''), r.missed ? 'err' : 'ok');
    } catch (e) { toast(e.message, 'err'); }
    finally { S.busy = false; await refresh(); }
  };
  return h('div', { class: 'phone-panel' },
    h('button', { class: 'btn small', onclick: () => { S.phoneOpen = !open; renderAway(); } }, open ? '📱 スマホをしまう' : '📱 スマホを見る'),
    open ? h('div', { class: 'phone-list' }, cs.map((c) => h('div', { class: 'row' },
      h('span', { style: 'flex:1' }, `${BOND_IC[c.stage] || ''} ${c.name}`),
      h('button', { class: 'btn small', disabled: S.busy, onclick: () => openChat(c.id) }, '📱 メッセージ'),
      h('button', { class: 'btn small', disabled: S.busy, onclick: () => send(c.id, 'call') }, '📞 電話')))) : '');
}

/* ---- 持ち物: 持っている品物・買うものリスト・品物の一覧 (どの店で売っているか) */
const PLACE_LABEL = (id) => ((S.view.outdoor || {}).places || {})[id] ? `${S.view.outdoor.places[id].icon}${S.view.outdoor.places[id].label}` : id;
function renderItems() {
  const box = $('#tab-items');
  const iv = S.view.items || { items: [], shop_list: [] };
  const cat = (S.boot.catalog || {}).items || [];
  const want = Object.fromEntries(iv.shop_list.map((x) => [x.id, x.want]));
  const setWant = async (id, qty) => { try { await api('/api/items/list', { id, qty }); await refresh(); } catch (e) { toast(e.message, 'err'); } };
  const canGive = !!(S.view.bond && S.view.bond.mode && (S.view.available.gift || {}).ok);   // いま目の前にいて, 受け取れる状態か
  box.replaceChildren(
    h('div', { class: 'pgroup' }, h('h4', {}, '🎒 持ち物'),
      iv.items.length ? iv.items.map((it) => h('div', { class: 'row item-row' },
        h('span', { style: 'flex:1' }, `${it.icon} ${it.name} ×${it.count}`),
        it.giftable && canGive ? h('button', { class: 'btn small', disabled: S.busy, title: `${S.view.name}に渡す`,
          onclick: () => giveItem(it.id, S.view.character) }, `🎁 ${S.view.name}に渡す`) : ''))
        : h('p', { class: 'muted small' }, 'なにも持っていない。買うものリストに入れておくと、買い物のときに買ってくる。'),
      h('p', { class: 'hint' }, '料理は食材、お茶はお茶っ葉・コーヒー豆、おやつはお菓子を使います（無ければありあわせで効き目が落ちる）。家事は洗剤があるとはかどり、研鑽はその分野の本があると伸びやすくなります（本は減りません）。')),
    h('div', { class: 'pgroup' }, h('h4', {}, '📝 買うものリスト'),
      h('p', { class: 'hint' }, '買い物（とカフェ）に出たとき、その店で売っていれば買ってきます。品切れや値段の上下があり、お金が足りなければ買えません。リストにない物をつい買うこともあります。'),
      cat.map((it) => h('div', { class: 'row item-row' },
        h('span', { style: 'flex:1;min-width:10em' }, `${it.icon} ${it.name}`, h('span', { class: 'muted small' }, ` ${yen(it.price)}前後・${it.places.map(PLACE_LABEL).join(' ')}`),
          iv.in_debt && !it.essential ? h('span', { class: 'muted small down' }, '（借金のあいだは買わない）') : ''),
        h('button', { class: 'btn small', disabled: !want[it.id], onclick: () => setWant(it.id, (want[it.id] || 0) - 1) }, '−'),
        h('span', { style: 'min-width:2em;text-align:center' }, String(want[it.id] || 0)),
        h('button', { class: 'btn small', onclick: () => setWant(it.id, (want[it.id] || 0) + 1) }, '＋')))));
}
async function giveItem(item, cid) {
  if (S.busy) return;
  S.busy = true;
  try { handleActResult(await api('/api/gift', { item, character: cid })); } catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await refresh(); }
}
function giftPicker(aid) {
  const gifts = ((S.view.items || {}).items || []).filter((x) => x.giftable && (aid === 'expensive_gift' ? x.price >= 10000 : x.price < 10000));
  if (!gifts.length) { toast('持ち物に渡せるものがない（持ち物タブの「買うものリスト」に入れておくと、買い物のときに買ってくる）', 'err'); return; }
  const dlg = h('dialog', { class: 'modal', style: 'width:min(480px,94vw);height:auto;overflow:auto' });
  const close = () => { dlg.close(); dlg.remove(); };
  dlg.append(h('div', { style: 'padding:16px' }, h('h3', {}, `${S.view.name}に渡すもの`),
    gifts.map((it) => h('div', { class: 'row item-row' }, h('span', { style: 'flex:1' }, `${it.icon} ${it.name} ×${it.count}`),
      h('button', { class: 'btn small primary', onclick: () => { close(); giveItem(it.id, S.view.character); } }, '渡す'))),
    h('div', { class: 'row', style: 'justify-content:flex-end;margin-top:10px' }, h('button', { class: 'btn', onclick: close }, 'やめる'))));
  document.body.append(dlg);
  dlg.showModal();
}

/* ---- メッセージアプリ: トーク一覧 → トーク画面. 自分は右 (要約), 相手は左 (本文). 送受信の時刻・日付の区切り・既読・返信待ち */
function openChat(cid) {
  if (!S.chatDlg) {
    S.chatDlg = h('dialog', { class: 'modal chat-dlg' });
    S.chatDlg.addEventListener('close', () => { S.chatCid = null; });
    document.body.append(S.chatDlg);
  }
  S.chatCid = cid || null;
  if (!S.chatDlg.open) S.chatDlg.showModal();
  drawChat();
}
const chatText = (t) => String(t || '').replace(/^📱『/, '').replace(/』(\n|$)/, '$1');
const hhmm = (t) => new Date(t * 1000).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
const dayLabel = (t) => new Date(t * 1000).toLocaleDateString('ja-JP', { month: 'long', day: 'numeric', weekday: 'short' });
function avatar(face, name, cls) {
  const a = h('div', { class: 'chat-ava ' + (cls || '') });
  if (face) a.style.backgroundImage = `url("${imgUrl(face)}")`; else a.textContent = (name || '?').slice(0, 1);
  return a;
}
async function drawChat() {
  const dlg = S.chatDlg;
  let list, th = null;
  try {
    list = (await api('/api/chats')).chats;
    if (S.chatCid) {
      th = await api('/api/chat?id=' + encodeURIComponent(S.chatCid));
      if (th.items.some((x) => x.who === 'her' && x.t > th.seen_t)) { await api('/api/chat/seen', { id: S.chatCid }); list = (await api('/api/chats')).chats; }
    }
  } catch (e) { toast(e.message, 'err'); return; }
  const total = list.reduce((n, c) => n + (c.unread || 0), 0);        // 読んだら, すぐ未読の数に反映
  $('#chat-badge').hidden = !total;
  $('#chat-badge').textContent = String(total || '');
  const keepScroll = dlg.querySelector('.chat-body');
  const atBottom = !keepScroll || keepScroll.scrollTop + keepScroll.clientHeight >= keepScroll.scrollHeight - 30;
  const listEl = h('div', { class: 'chat-list' },
    h('div', { class: 'chat-head' }, h('b', {}, '💬 メッセージ'), h('div', { class: 'spacer' }),
      h('button', { class: 'btn ghost small chat-close', onclick: () => dlg.close() }, '✕')),
    list.length ? list.map((c) => h('div', { class: 'chat-row' + (c.id === S.chatCid ? ' on' : ''), onclick: () => { S.chatCid = c.id; drawChat(); } },
      avatar(c.face, c.name),
      h('div', { class: 'chat-row-main' },
        h('div', { class: 'chat-row-top' }, h('b', {}, c.name), h('span', { class: 'muted small' }, c.last ? hhmm(c.last.t) : '')),
        h('div', { class: 'chat-row-last muted small' }, c.waiting ? '返信待ち…' : c.last ? chatText(c.last.text).split('\n')[0] : 'まだやりとりはありません')),
      c.unread ? h('span', { class: 'chat-unread' }, String(c.unread)) : ''))
      : h('p', { class: 'muted small', style: 'padding:12px' }, '連絡先を知っている人がいません。'));
  let threadEl = h('div', { class: 'chat-thread empty' }, h('p', { class: 'muted' }, '左のトークを選んでください'));
  if (th) {
    let lastDay = '';
    const body = [];
    const lastMine = [...th.items].reverse().find((x) => x.who === 'me');
    for (const it of th.items) {
      const d = dayLabel(it.t);
      if (d !== lastDay) { body.push(h('div', { class: 'chat-day' }, d)); lastDay = d; }
      if (it.who === 'sys') { body.push(h('div', { class: 'chat-sys' }, `${it.text}　${hhmm(it.t)}`)); continue; }
      const mine = it.who === 'me';
      body.push(h('div', { class: 'chat-msg ' + (mine ? 'me' : 'her') },
        mine ? '' : avatar(th.face, th.name, 'small'),
        h('div', { class: 'chat-bubble' + (mine ? ' summary' : '') }, chatText(it.text)),
        h('div', { class: 'chat-meta' }, mine && it.read_t ? h('div', {}, '既読') : '', h('div', {}, hhmm(it.t)))));
    }
    if (th.waiting) body.push(h('div', { class: 'chat-sys muted' }, '返信待ち…（相手の状況しだい。来ないことも）'));
    const can = !th.together;
    threadEl = h('div', { class: 'chat-thread' },
      h('div', { class: 'chat-head' },
        h('button', { class: 'btn ghost small chat-back', onclick: () => { S.chatCid = null; drawChat(); } }, '‹'),
        avatar(th.face, th.name, 'small'), h('b', {}, th.name),
        h('span', { class: 'muted small', style: 'margin-left:8px' }, th.together ? 'そばにいる' : th.promise ? `📅 会う約束（${hhmm(th.promise)}まで）` : ''),
        h('div', { class: 'spacer' }), h('button', { class: 'btn ghost small chat-close', onclick: () => dlg.close() }, '✕')),
      h('div', { class: 'chat-body' }, body.length ? body : h('p', { class: 'muted small', style: 'text-align:center' }, 'まだやりとりはありません')),
      h('div', { class: 'chat-send' },
        can ? th.kinds.map((k) => h('button', { class: 'chat-kind', disabled: S.busy, onclick: () => sendChat(th.id, k.id) }, `${k.icon} ${k.label}`))
          : h('p', { class: 'muted small' }, 'いまはそばにいるので、直接話しましょう。')));
    void lastMine;
  }
  dlg.classList.toggle('thread-open', !!th);
  dlg.replaceChildren(h('div', { class: 'chat-wrap' }, listEl, threadEl));
  const nb = dlg.querySelector('.chat-body');
  if (nb && (atBottom || S.chatJump)) nb.scrollTop = nb.scrollHeight;
  S.chatJump = false;
  clearTimeout(S.chatPoll);       // 返信待ちの間は, 相手がまだスマホを見ていればすぐ返ってくるので, こまめに見る
  if (th && th.waiting) S.chatPoll = setTimeout(() => { if (dlg.open && S.chatCid === th.id) drawChat(); }, 8000);
}
async function sendChat(cid, kind) {
  if (S.busy) return;
  S.busy = true;
  try { await api('/api/chat/send', { id: cid, kind }); S.chatJump = true; } catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await drawChat(); refresh(); }
}

/* ---- オフラインの間のまとめ: 開いたときに一度だけ. 読んだら普段に戻る. 届いたメッセージにはここから返事できる */
function renderOffline() {
  const rep = S.view.offline_report;
  if (!rep || S.offlineShown === rep.to) return;
  S.offlineShown = rep.to;
  const t = (x, f) => new Date(x * 1000).toLocaleString('ja-JP', f || { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  const hm = (x) => t(x, { hour: '2-digit', minute: '2-digit' });
  const dlg = h('dialog', { class: 'modal', style: 'width:min(640px,94vw);height:auto;max-height:86vh;overflow:auto' });
  const close = async () => { dlg.close(); dlg.remove(); try { await api('/api/offline/ack', {}); } catch (e) { /* noop */ } await refresh(); };
  dlg.append(h('div', { style: 'padding:16px' },
    h('h3', {}, '🌙 画面を閉じていたあいだ'),
    h('p', { class: 'muted small' }, `${t(rep.from)} 〜 ${t(rep.to)}`),
    h('div', { class: 'pgroup' }, h('h4', {}, 'どう過ごしたか'),
      (rep.timeline || []).length ? rep.timeline.map((x) => h('div', { class: 'small' + (x.skipped ? ' muted' : '') },
        `${t(x.t)}〜${hm(x.end)}　${x.label}：${x.text}`, (x.meets || []).length ? h('div', { class: 'muted' }, '　' + x.meets.join(' / ')) : ''))
        : h('div', { class: 'muted small' }, '家で静かに過ごした')),
    h('div', { class: 'small' }, `お金 ${rep.pay >= 0 ? '+' : ''}${yen(rep.pay)}・体力 ${Math.round(rep.stamina[0])} → ${Math.round(rep.stamina[1])}`),
    rep.meets.length ? h('div', { class: 'pgroup' }, h('h4', {}, '出会い'), rep.meets.map((m) => h('div', { class: 'small' }, m))) : '',
    h('div', { class: 'pgroup' }, h('h4', {}, '届いたメッセージ'),
      rep.messages.length ? rep.messages.map((m) => h('div', { class: 'row', style: 'align-items:flex-start' },
        h('div', { style: 'flex:1' }, h('b', {}, m.name), h('span', { class: 'muted small' }, ` ${t(m.t)}`), h('div', {}, m.text),
          m.mood < 0 ? h('div', { class: 'muted small' }, '（返事がなくて、少し気にしているかも）') : ''),
        h('button', { class: 'btn small', onclick: async (ev) => {
          ev.target.disabled = true;
          try { const r = await api('/api/approach', { answer: 'accept', character: m.cid }); toast(`${m.name}に返事をした`, 'ok'); if (r && r.entry) S.lastDeltas = r.entry.deltas || {}; }
          catch (e) { toast(e.message, 'err'); ev.target.disabled = false; }
        } }, '返事をする'))) : h('div', { class: 'muted small' }, 'なし')),
    h('div', { class: 'row', style: 'justify-content:flex-end;margin-top:12px' }, h('button', { class: 'btn primary', onclick: close }, '閉じる'))));
  document.body.append(dlg);
  dlg.showModal();
}

/* ---- 出先でのばったり: 声をかけられた / 見かけた. 選ばないまま時間が過ぎたら, 無難な対応に落ち着く.
   声をかけられたときは知らせる (画面の知らせ・控えめな音・タブの題名). 見かけただけなら控えめ (タブの題名に小さな印) */
function streetCard() {
  const sp = S.view.street_pending;
  if (!sp) return null;
  return h('div', { class: 'street-card' + (sp.type === 'call' ? ' calling' : '') },
    h('div', {}, sp.type === 'call' ? `💬 ${sp.where}で、${sp.name}に声をかけられた` : `👀 ${sp.where}で、${sp.name}を見かけた`),
    sp.text ? h('div', { class: 'muted' }, `「${sp.text}」`) : '',
    h('div', { class: 'row' }, sp.options.map((o) => h('button', { class: 'btn small', disabled: S.busy, onclick: () => answerStreet(o.id) }, o.label))));
}
function renderStreet() {
  const box = $('#street-box');
  const away = !$('#away-overlay').hidden;
  const card = away ? null : streetCard();
  box.hidden = !card;
  if (card) box.replaceChildren(card);
  const sp = S.view.street_pending;
  if (sp && sp.type === 'call' && S.lastCallT !== sp.t) {
    // 声をかけられた: 名前を呼ばれれば気づくのと同じく, はっきり知らせる (見かけただけのときは控えめのまま)
    S.lastCallT = sp.t;
    toast(`💬 ${sp.where}で、${sp.name}に声をかけられた`, 'ok');
    if (S.ui.callSound !== false) chime();
  }
  document.title = sp && document.hidden ? (sp.type === 'call' ? '💬 声をかけられた - くらし' : '・くらし') : 'くらし';
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) document.title = 'くらし'; });
// 声をかけられたときの, 控えめな 2 音
function chime() {
  try {
    const ac = S.audio || (S.audio = new (window.AudioContext || window.webkitAudioContext)());
    [[660, 0], [880, 0.16]].forEach(([f, d]) => {
      const o = ac.createOscillator(), g = ac.createGain();
      o.type = 'sine'; o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, ac.currentTime + d);
      g.gain.exponentialRampToValueAtTime(0.12, ac.currentTime + d + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + d + 0.35);
      o.connect(g).connect(ac.destination);
      o.start(ac.currentTime + d); o.stop(ac.currentTime + d + 0.4);
    });
  } catch (e) { /* 音が出せない環境でも, 画面の知らせはある */ }
}
async function answerStreet(choice) {
  if (S.busy) return;
  S.busy = true;
  try { const r = await api('/api/street', { choice }); if (r) toast(r.text.replace(/\n/, ' '), 'ok'); } catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await refresh(); }
}

/* ---- あなたの在席 (心拍で伝える) */
S.lastInput = Date.now();
const idleSec = () => Math.round((Date.now() - S.lastInput) / 1000);
const fmtDur = (sec) => { const m = Math.floor(sec / 60); return m >= 60 ? `${Math.floor(m / 60)}時間${m % 60}分` : `${m}分`; };
const AWAY = { out: ['🚪', '外出中', 'ただいま'], work: ['💼', '仕事中', '仕事から帰る'], sleep: ['🌙', '就寝中', 'おはよう'],
  left: ['👋', 'そばを離れています', '戻る'] };

function renderAway() {
  const box = $('#away-overlay');
  const p = S.view.presence || {};
  const a = AWAY[p.mode];
  if (!a) { box.hidden = true; return; }
  const name = S.view.name;
  const since = p.since ? Math.max(0, Date.now() / 1000 - p.since) : 0;
  box.hidden = false;
  box.replaceChildren(h('div', { class: 'away-card' },
    h('div', { class: 'away-ic' }, a[0]),
    h('div', { class: 'away-title' }, p.solo ? `${p.solo.icon} ${p.solo.label}` : a[1]),
    (() => { const c = (S.view.outdoor || {}).current; const wx = (S.view.outdoor || {}).weather || {};
      return c ? h('div', { class: 'muted' }, `${c.icon} ${c.label}・${wx.icon || ''}${wx.label || ''}`) : ''; })(),
    streetCard() || '',
    phonePanel(),
    (() => { const c = (S.view.outdoor || {}).current; return c && c.log && c.log.length ? h('div', { class: 'street-log' },
      c.log.map((x) => h('div', { class: 'small' }, `${fmtTime(x.t)} ${x.text}`))) : ''; })(),
    h('div', { class: 'muted' }, `${fmtDur(since)}経過`),
    p.work ? h('div', { class: 'away-pay' }, p.work.raw < 0.25 ? 'まだ働き始めたばかり（15分未満は稼ぎなし）'
      : `ここで帰ると ${yen(p.work.pay)}（給料の出る ${p.work.hours.toFixed(1)}時間分）`) : '',
    p.work ? h('div', { class: 'muted small' }, '給料が出るのは 6〜23時、1日合計9時間まで。働いた時間ぶん体力が減ります') : '',
    // 外出・仕事は画面を開いているあいだだけ (閉じたら家に帰る). 就寝・またね は閉じてかまわない
    ['out', 'work'].includes(p.mode) ? h('p', { class: 'muted small' },
      p.mode === 'work' ? '働いているあいだに、同僚と顔を合わせることがあります。' : '出かけているあいだに、偶然だれかに会うことがあります（会わないことも）。',
      h('br'), `画面を閉じると、そこで${p.mode === 'work' ? '仕事' : '外出'}を切り上げて家に帰ります。誰かに会えるのは、画面を開いて出かけているあいだだけです${p.mode === 'work' ? '（給料も閉じた時点まで）' : ''}。`,
      (S.boot.settings.offline || {}).enabled !== false ? h('span', {}, h('br'), '閉じたあとは「オフライン時の過ごし方」どおりに過ごします（勤務時間なら仕事、それ以外は家で静かに）。') : '',
      h('br'), p.mode === 'work' ? '戻ったときに、働いた時間ぶんのお給料が入ります（上限あり）。' : '「' + a[2] + '」で戻ります。')
      : h('p', { class: 'muted small' }, S.view.bond && S.view.bond.mode ? `${name}のそばを離れています。このまま画面を閉じてもかまいません。`
        : '一人で過ごしています。このまま画面を閉じてもかまいません。', h('br'), '「' + a[2] + '」で戻ります。'),
    h('button', { class: 'btn primary', disabled: S.busy, onclick: comeBack }, a[2])));
}

async function comeBack() {
  if (S.busy) return;
  S.busy = true;
  try { handleActResult(await api('/api/presence/back', {})); } catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await refresh(); }
}

/* ---- キャラからの働きかけ */
function renderApproach() {
  const box = $('#approach-box');
  const ap = S.view.approach;
  if (!ap) { box.hidden = true; return; }
  const rest = Math.max(0, Math.round(ap.until - Date.now() / 1000));
  box.hidden = false;
  box.replaceChildren(
    h('div', { class: 'req-text' }, h('b', {}, `${ap.icon} ${S.view.name}${ap.apart ? 'から' : 'が'}${ap.label}`),
      h('span', { class: 'muted small', id: 'ap-rest' }, `（あと${Math.ceil(rest / 60)}分）`)),
    h('div', { class: 'row' },
      h('button', { class: 'btn primary', disabled: S.busy, onclick: () => answerApproach('accept') }, ap.accept),
      h('button', { class: 'btn', disabled: S.busy, onclick: () => answerApproach('later') }, ap.later)));
}

async function answerApproach(ans) {
  if (S.busy) return;
  S.busy = true;
  try {
    const r = await api('/api/approach', { answer: ans });
    if (r.entry) handleActResult(r);
  } catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await refresh(); }
}

// キャラのほうから起きた記録 (働きかけ・返事がなかった) を会話欄に出す
function showAutoEntry() {
  const au = S.view.auto;
  if (!au) return;
  if (S.autoSeen === undefined) { S.autoSeen = au.id; return; }   // 開いた直後は出し直さない
  if (au.id === S.autoSeen) return;
  S.autoSeen = au.id;
  const e = S.view.log.find((x) => x.id === au.id);
  if (!e) return;
  showEntry(e, true);
  if (e.job) trackJob(e.job);
  if (document.hidden) {
    S.titleBase = S.titleBase || document.title;
    document.title = '💬 ' + S.titleBase;
  }
}

/* ---- お金タブ: 財布・支払い・銘柄・ニュース・稼ぐ */
function renderMoney() {
  const v = S.view;
  const L = v.life || {};
  const M = L.market || { assets: [], news: [] };
  const inv = L.invest || {};
  const policy = (key, opts) => h('select', { value: L[key], onchange: async (ev) => {
    const c = clone(S.boot.character);
    c[key] = ev.target.value;
    try { await api('/api/character/save', { data: c }); await loadBoot(); await refresh(); } catch (e) { toast(e.message, 'err'); }
  } }, opts.map(([k, l]) => h('option', { value: k }, l)));
  const asset = (a) => {
    const qty = h('input', { type: 'number', min: 1, step: 1, value: S.tradeQty?.[a.id] || 1, class: 'qty',
      oninput: (ev) => { (S.tradeQty = S.tradeQty || {})[a.id] = ev.target.value; } });
    const pl = a.qty ? a.value - a.cost : 0;
    return h('div', { class: 'asset' },
      h('div', { class: 'asset-head', title: a.desc }, h('span', { class: 'ic' }, a.icon), h('b', {}, a.name),
        h('div', { class: 'spacer' }), h('b', {}, yen(a.price)),
        h('span', { class: 'chg ' + (a.day >= 0 ? 'up' : 'down') }, `${a.day >= 0 ? '+' : ''}${a.day}%`)),
      a.history.length > 1 ? sparkline(a.history, `${a.name}の値動き（直近72時間・1時間ごと）`) : '',
      a.qty ? h('div', { class: 'muted small' }, `保有 ${a.qty}株・評価 ${yen(a.value)}（`,
        h('span', { class: pl >= 0 ? 'up' : 'down' }, `${pl >= 0 ? '+' : ''}${yen(pl)}`), '）') : '',
      h('div', { class: 'row trade' }, qty, h('span', { class: 'muted small' }, '株'),
        h('button', { class: 'btn', disabled: S.busy, onclick: () => trade(a.id, +qty.value) }, '買う'),
        h('button', { class: 'btn', disabled: S.busy || !a.qty, onclick: () => trade(a.id, -qty.value) }, '売る'),
        a.qty ? h('button', { class: 'btn ghost small', disabled: S.busy, onclick: () => trade(a.id, -a.qty) }, '全部売る') : ''));
  };
  const av = v.available || {};
  $('#tab-money').replaceChildren(
    h('div', { class: 'pgroup money-box' }, h('h4', {}, '財布'),
      h('div', { class: 'money-row' }, h('span', {}, 'あなた'), h('b', {}, yen(L.my_money || 0))),
      h('div', { class: 'money-row' }, h('span', {}, v.name), h('b', {}, yen(L.her_money || 0))),
      inv.value ? h('div', { class: 'money-row' }, h('span', {}, '株（評価額）'),
        h('b', { class: inv.value >= inv.invested ? 'up' : 'down' }, `${yen(inv.value)}（${inv.value >= inv.invested ? '+' : ''}${yen(inv.value - inv.invested)}）`)) : '',
      h('div', { class: 'money-row' }, h('span', {}, 'お出かけ代'),
        policy('pay_policy', [['auto', 'おまかせ'], ['me', 'あなたが払う'], ['split', '割り勘'], ['her', 'おごってもらう']])),
      L.living ? h('div', { class: 'money-row', title: 'あなたの家の毎日の生活費と、月はじめの家賃・光熱費・通信費の分け方' }, h('span', {}, '生活費・家賃'),
        policy('living_policy', [['split', '折半'], ['me', 'あなたが払う'], ['her', `${v.name}が払う`]])) : '',
      L.debt ? h('div', { class: 'money-row', title: '払えなかった生活費・家賃。月はじめに少し利息がつきます' }, h('span', {}, '借金'), h('b', { class: 'down' }, yen(L.debt)),
        h('button', { class: 'btn small', disabled: S.busy || !(L.my_money > 0), onclick: () => repay('debt', L.debt, '借金') }, '返す')) : '',
      ...(L.loans || []).map((x) => h('div', { class: 'money-row' }, h('span', {}, `${x.name}に借りている`), h('b', { class: 'down' }, yen(x.amount)),
        h('button', { class: 'btn small', disabled: S.busy || !(L.my_money > 0), onclick: () => repay(x.id, x.amount, x.name) }, '返す'))),
      L.in_debt ? h('div', { class: 'muted small' }, '借金のあいだは、食材・洗剤などの必需品しか買えません。') : '',
      (L.money_notes || []).length ? h('div', { class: 'muted small' }, ...L.money_notes.slice(-3).map((x) => h('div', {}, `${fmtTime(x.t)} ${x.text}`))) : ''),
    h('div', { class: 'pgroup' }, h('h4', {}, '稼ぐ'),
      h('div', { class: 'earn' },
        h('button', { class: 'cmd', disabled: S.busy || !(av.go_work || {}).ok, onclick: () => doAct('go_work'),
          title: '「仕事に行ってくる」と告げて、実際にそばを離れます。戻ったときに働いた時間ぶん稼げます（画面を開いているあいだだけ。閉じたらそこまで）' },
          h('span', { class: 'ic' }, '💼'), h('span', {}, '仕事に行く'), h('small', { class: 'muted' }, '離れた時間ぶん')),
        h('button', { class: 'cmd', disabled: S.busy || !(av.side_job || {}).ok || (av.side_job || {}).cooldown > 0, onclick: openTask,
          title: '家で1分間の作業をします。こなした数とミスで稼ぎが決まります' },
          h('span', { class: 'ic' }, '🧵'), h('span', {}, '内職する'),
          h('small', { class: 'muted' }, (av.side_job || {}).cooldown > 0 ? `あと${Math.ceil(av.side_job.cooldown / 60)}分` : '1分の作業'))),
      h('div', { class: 'muted small' }, `体力 ${Math.floor(L.stamina ?? 100)}・今日の勤務 ${(L.work_today || 0).toFixed(1)} / 9時間・仕事スキル ${Math.round((L.skills || {}).work || 0)}`),
      h('div', { class: 'muted small' }, '仕事に出られるのは 6〜21時（体力20以上）。給料は 6〜23時の分だけ、1日9時間まで。内職は体力10を使います')),
    h('div', { class: 'pgroup' }, h('h4', {}, '株'),
      h('div', { class: 'muted small', style: 'margin-bottom:6px' }, 'ニュースは当たるとは限りません。値動きはリアル時間で進みます。'),
      ...M.assets.map(asset)),
    h('div', { class: 'pgroup' }, h('h4', {}, 'ニュース'),
      M.news.length ? M.news.map((n) => h('div', { class: 'news' },
        h('span', { class: n.dir > 0 ? 'up' : 'down' }, n.dir > 0 ? '▲' : '▼'), h('span', {}, n.text),
        h('span', { class: 'muted small' }, fmtTime(n.t)))) : h('div', { class: 'muted small' }, 'まだニュースはありません')));
}

async function repay(to, owed, name) {
  if (S.busy) return;
  const v = prompt(`${name}に返す額（円）`, String(Math.min(owed, (S.view.life || {}).my_money || 0)));
  if (v === null) return;
  const amount = Math.trunc(+v);
  if (!(amount > 0)) return toast('返す額を入れてください', 'err');
  S.busy = true;
  try { const r = await api('/api/money/repay', { to, amount }); toast(`${yen(r.amount)}返しました${r.left ? `（残り ${yen(r.left)}）` : '（完済）'}`); }
  catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await refresh(); }
}
async function trade(asset, qty) {
  qty = Math.trunc(qty);
  if (!qty) return toast('株数を入れてください', 'err');
  if (S.busy) return;
  S.busy = true;
  try { handleActResult(await api('/api/market/trade', { asset, qty })); } catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await refresh(); }
}

/* ---- 内職 (1分間の作業ミニゲーム) */
const TASKS = {
  sort: { name: '仕分け', desc: '流れてくる品物を、正しい箱に入れます（キー 1〜4 でも）',
    bins: [['🍎', '果物', ['🍎', '🍌', '🍇', '🍑', '🍊', '🍓']], ['🥕', '野菜', ['🥕', '🥦', '🍆', '🌽', '🥒', '🧅']],
      ['🐟', '魚介', ['🐟', '🐠', '🦐', '🦑', '🐙', '🦀']], ['🍞', 'パン', ['🍞', '🥐', '🥖', '🥯', '🥨', '🧇']]],
    next() { const b = Math.floor(Math.random() * 4); const it = this.bins[b][2]; return { show: it[Math.floor(Math.random() * it.length)], ans: b }; },
    buttons() { return this.bins.map((b, i) => `${i + 1} ${b[0]} ${b[1]}`); } },
  check: { name: '検算', desc: '計算が合っているか確かめます（キー ←/F = 合っている、→/J = 間違い）',
    next() {
      const a = 10 + Math.floor(Math.random() * 90), b = 10 + Math.floor(Math.random() * 90), plus = Math.random() < 0.6;
      let r = plus ? a + b : a - b;
      const ok = Math.random() < 0.5;
      if (!ok) r += [1, -1, 10, -10, 2][Math.floor(Math.random() * 5)];
      return { show: `${a} ${plus ? '+' : '−'} ${b} = ${r}`, ans: ok ? 0 : 1 };
    },
    buttons() { return ['← 合っている', '間違い →']; } },
};

function openTask() {
  const dlg = $('#task-dlg');
  $('#task-sub').textContent = '';
  $('#task-body').replaceChildren(
    h('p', { class: 'muted' }, '1分間の作業です。こなした数が多いほど、ミスが少ないほど稼げます。仕事スキルが上がると単価も上がります。'),
    h('div', { class: 'task-pick' }, Object.entries(TASKS).map(([k, t]) => h('button', { class: 'cmd', onclick: () => startTask(k) },
      h('b', {}, t.name), h('small', { class: 'muted' }, t.desc)))));
  dlg.showModal();
}

async function startTask(kind) {
  let tk;
  try { tk = await api('/api/task/start', { kind }); } catch (e) { toast(e.message, 'err'); return; }
  const T = TASKS[kind];
  const run = { ok: 0, ng: 0, cur: T.next(), end: Date.now() + tk.seconds * 1000, done: false };
  S.task = run;
  $('#task-sub').textContent = `${T.name}・1個 ${tk.unit}円`;
  const item = h('div', { class: 'task-item' }, run.cur.show);
  const score = h('div', { class: 'task-score' });
  const bar = h('i');
  const pick = (i) => {
    if (run.done) return;
    if (i === run.cur.ans) { run.ok++; item.classList.remove('ng'); item.classList.add('ok'); } else { run.ng++; item.classList.remove('ok'); item.classList.add('ng'); }
    run.cur = T.next();
    item.textContent = run.cur.show;
    setTimeout(() => item.classList.remove('ok', 'ng'), 150);
    score.textContent = `できた ${run.ok}　ミス ${run.ng}`;
  };
  run.key = (ev) => {
    const k = ev.key;
    const idx = kind === 'sort' ? ['1', '2', '3', '4'].indexOf(k)
      : (k === 'ArrowLeft' || k === 'f' || k === 'F') ? 0 : (k === 'ArrowRight' || k === 'j' || k === 'J') ? 1 : -1;
    if (idx >= 0) { ev.preventDefault(); pick(idx); }
  };
  document.addEventListener('keydown', run.key);
  score.textContent = 'できた 0　ミス 0';
  $('#task-body').replaceChildren(
    h('div', { class: 'task-timer' }, bar), score, item,
    h('div', { class: 'task-btns ' + kind }, T.buttons().map((label, i) => h('button', { class: 'btn', onclick: () => pick(i) }, label))));
  run.timer = setInterval(async () => {
    const rest = run.end - Date.now();
    bar.style.width = Math.max(0, rest / (tk.seconds * 10)) + '%';
    if (rest > 0 || run.done) return;
    run.done = true;
    clearInterval(run.timer);
    document.removeEventListener('keydown', run.key);
    try {
      const r = await api('/api/task/finish', { token: tk.token, ok: run.ok, ng: run.ng });
      $('#task-body').replaceChildren(h('div', { class: 'task-result' },
        h('div', { class: 'big' }, yen(r.task.pay)), h('div', {}, `できた ${r.task.ok}　ミス ${r.task.ng}`),
        r.entry.skill && r.entry.skill.work ? h('div', { class: 'muted' }, `仕事スキル +${r.entry.skill.work}`) : '',
        h('button', { class: 'btn primary', onclick: () => $('#task-dlg').close() }, '閉じる')));
      handleActResult(r);
    } catch (e) { toast(e.message, 'err'); $('#task-dlg').close(); }
    S.task = null;
    await refresh();
  }, 100);
}

function closeTask() {
  const run = S.task;
  if (run && !run.done) {
    if (!confirm('作業を途中でやめますか？（稼ぎはありません）')) return;
    run.done = true;
    clearInterval(run.timer);
    document.removeEventListener('keydown', run.key);
    S.task = null;
  }
  $('#task-dlg').close();
}

const SKILL_HINT = {
  talk: '会話のコマンドの効き目。上がると話が弾みやすく、低いと沈黙することも',
  touch: 'ふれあいのコマンドの効き目。低いうちは、急にするとびっくりされることも',
  cook: '料理・おやつ・お茶の効き目。低いと失敗することも、高いと絶品に',
  work: '仕事のお給料と、内職の単価',
};
/* ---- 見た目でわかること: 数値は出さず, 様子から受ける印象だけ (少しずれることもある) */
const LOOK = {
  satiety: ['ぺこぺこそう', 'お腹すいてそう', 'ふつう', '満たされてそう', 'お腹いっぱいそう'],
  hydration: ['からからそう', '喉が渇いてそう', 'ふつう', '潤ってそう', '十分そう'],
  energy: ['ぐったりしている', '疲れてそう', 'ふつう', '元気そう', 'とても元気そう'],
  sleepiness: ['ぱっちり', '目は冴えてそう', 'ふつう', '眠そう', 'とても眠そう'],
  hygiene: ['くたびれてる', 'ちょっと気になる', 'ふつう', 'さっぱりしてる', 'すっきり清潔'],
  health: ['具合が悪そう', '顔色がいまいち', 'ふつう', '調子よさそう', 'はつらつ'],
  mood: ['沈んでいる', '浮かない顔', 'ふつう', '機嫌よさそう', 'ご機嫌'],
  stress: ['のびのびしてる', '落ち着いてる', 'ふつう', 'ぴりぴりしてそう', '張りつめてる'],
  boredom: ['夢中そう', '楽しそう', 'ふつう', '退屈そう', 'とても退屈そう'],
  loneliness: ['満たされてそう', '落ち着いてる', 'ふつう', '寂しそう', 'とても寂しそう'],
  shyness: ['平然としてる', 'いつもどおり', 'ほんのり赤い', '照れてる', '真っ赤'],
};
const LOOK_FUZZ = { stress: 18, loneliness: 18 };       // 外からは読みにくいものは, ずれが大きい
function lookWord(p, val) {
  const words = LOOK[p.id];
  if (!words) return null;                                // 好感度・信頼など, 見ただけではわからない
  // 同じ時間帯のうちは同じ印象になるよう, ずれは param と時刻 (1時間単位) で決める
  const seed = [...(p.id + Math.floor(Date.now() / 3600000))].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
  const fuzz = ((seed % 1000) / 1000 - 0.5) * 2 * (LOOK_FUZZ[p.id] || 10);
  const n = Math.max(0, Math.min(99.9, ((val + fuzz) - (p.min ?? 0)) / ((p.max ?? 100) - (p.min ?? 0)) * 100));
  return words[Math.floor(n / 20)];
}
function statMode() { return S.peek ? 'exact' : (S.ui.stats || 'exact'); }

function renderStatus() {
  const v = S.view;
  const groups = [['physical', 'からだ'], ['mental', 'こころ']];
  const others = S.boot.params.filter((p) => !['physical', 'mental'].includes(p.group));
  const mode = statMode();
  const rows = (list) => list.map((p) => {
    const val = v.params[p.id] ?? 0;
    if (mode === 'look') {
      const w = lookWord(p, val);
      return h('div', { class: 'prow look' }, h('span', {}, p.name), h('span', { class: w ? '' : 'muted' }, w || '？（見ただけではわからない）'));
    }
    const pct = ((val - (p.min ?? 0)) / ((p.max ?? 100) - (p.min ?? 0))) * 100;
    const d = S.lastDeltas[p.id];
    return h('div', { class: 'prow' + (d ? ' flash' : ''), title: p.id },
      h('span', {}, p.name),
      h('div', { class: 'bar' }, h('i', { style: `width:${pct}%;background:${level(p, val)}` })),
      h('span', { class: 'pval' }, d ? `${d > 0 ? '+' : ''}${d}` : Math.round(val)));
  });
  const sc = v.scene;
  const hide = veiled();
  const flags = [sc.asleep && '睡眠中', sc.away && '外出中', sc.busy && '手が離せない'].filter(Boolean).join('・');
  const L = v.life || {};
  // 離れている相手の機嫌の理由は, 本人から聞いたもの (told) だけ
  const reasons = (L.reasons || []).filter((r) => !hide || r.told).map((r) => h('div', { class: 'reason ' + r.mood },
    h('span', {}, r.mood === 'good' ? '😊' : '😣'),
    h('span', {}, r.tell || '？（まだ聞いていない）'),
    h('span', { class: 'muted small' }, fmtTime(r.t))));
  $('#tab-status').replaceChildren(
    h('div', { class: 'scene-box' },
      h('div', {}, h('b', {}, '時間帯 '), v.phase.label),
      h('div', {}, h('b', {}, 'いま '), hide ? '離れていて、様子はわからない' : `${sc.label}（${sc.location || '—'}）`, !hide && flags ? `　${flags}` : ''),
      h('div', {}, h('b', {}, '最後のふれあい '), v.absent < 1 ? `${Math.round(v.absent * 60)}分前` : `${v.absent.toFixed(1)}時間前`),
      h('div', {}, h('b', {}, 'あなた '), (v.presence || {}).label || '—')),
    h('div', { class: 'pgroup' }, h('h4', {}, 'いまの気分の理由'),
      reasons.length ? reasons : h('div', { class: 'muted small' }, '特になし')),
    h('div', { class: 'pgroup' }, h('h4', {}, 'あなた'),
      h('div', { class: 'prow', title: '仕事・内職で減り、時間で戻ります（寝ると早い）。減っていると、構っても効きが悪くなります' },
        h('span', {}, '体力'),
        h('div', { class: 'bar' }, h('i', { style: `width:${L.stamina ?? 100}%;background:${(L.stamina ?? 100) >= 50 ? 'var(--good)' : (L.stamina ?? 100) >= 20 ? 'var(--mid)' : 'var(--bad)'}` })),
        h('span', { class: 'pval' }, Math.floor(L.stamina ?? 100)))),
    h('div', { class: 'pgroup' }, h('h4', {}, 'あなたのスキル'),
      Object.entries(L.skills || {}).map(([k, val]) => h('div', { class: 'prow', title: SKILL_HINT[k] || '' },
        h('span', {}, SKILL_NAME[k] || k),
        h('div', { class: 'bar' }, h('i', { style: `width:${val}%;background:var(--sky)` })),
        h('span', { class: 'pval' }, Math.floor(val))))),
    (S.ui.stats || 'exact') !== 'exact' ? h('div', { class: 'peek row' },
      h('span', { class: 'muted small' }, S.peek ? '一時的に正確な数値を表示中' : mode === 'look' ? `${v.name}の様子（見た感じ。正確とは限りません）` : `${v.name}のステータスは隠しています`),
      h('div', { class: 'spacer' }),
      h('button', { class: 'btn ghost small', onclick: () => {
        S.peek = !S.peek;
        clearTimeout(S.peekTimer);
        if (S.peek) S.peekTimer = setTimeout(() => { S.peek = false; renderStatus(); }, 60000);
        renderStatus();
      } }, S.peek ? '戻す' : '数値を見る（1分）')) : '',
    hide ? h('p', { class: 'muted small' }, `${v.name}とは離れているので、からだやこころの様子はわかりません（会うか、本人から聞けば分かることも）。設定 → 表示 で「離れている相手の様子も見る」にすると見えます。`) : '',
    ...(mode === 'hidden' || hide ? [] : [
      ...groups.map(([g, label]) => h('div', { class: 'pgroup' }, h('h4', {}, `${v.name}の${label}`), rows(S.boot.params.filter((p) => p.group === g)))),
      others.length ? h('div', { class: 'pgroup' }, h('h4', {}, `${v.name}のその他`), rows(others)) : '']),
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
/* ---- ギャラリー: 時系列 / シチュエーション (= プロンプト) 別 */
async function openGallery() {
  S.galMode = S.galMode || 'time';
  $$('#gal-mode button').forEach((x) => { x.onclick = () => { S.galMode = x.dataset.mode; S.galKey = null; drawGallery(); }; });
  $('#gallery-dlg').showModal();
  await drawGallery();
}

function galItem(e, im) {
  return h('div', { class: 'gal-item', style: `background-image:url("${imgUrl(im.path)}")`, 'data-path': im.path,
    onclick: () => openLightbox(e, im) }, h('span', {}, `${fmtTime(im.t || e.t)} ${e.icon || ''}${e.action_name || ''}`));
}

async function drawGallery() {
  const box = $('#gallery');
  box.replaceChildren();
  $$('#gal-mode button').forEach((x) => x.classList.toggle('on', x.dataset.mode === S.galMode));
  $('#gal-more').hidden = true;
  if (S.galMode === 'prompt' && S.galKey) {
    const g = await api('/api/album?key=' + S.galKey);
    $('#gal-count').textContent = `${g.items.length} 枚`;
    box.append(h('div', { class: 'gal-back' }, h('button', { class: 'btn ghost', onclick: () => { S.galKey = null; drawGallery(); } }, '← シチュエーション一覧'),
      g.items[0] ? h('code', { class: 'muted small' }, g.items[0].pos) : ''));
    for (const it of g.items) box.append(galItem(it.entry, it));
    return;
  }
  if (S.galMode === 'prompt') {
    const r = await api('/api/album');
    $('#gal-count').textContent = `${r.groups.length} シチュエーション`;
    for (const g of r.groups) {
      box.append(h('div', { class: 'gal-item group', style: `background-image:url("${imgUrl(g.cover)}")`, title: g.pos,
        onclick: () => { S.galKey = g.key; drawGallery(); } },
      h('b', { class: 'gal-n' }, `${g.count}枚`), h('span', {}, g.label)));
    }
    if (!r.groups.length) box.append(h('p', { class: 'muted' }, 'まだ画像がありません'));
    return;
  }
  let offset = 0;
  const load = async () => {
    const r = await api(`/api/log?images=1&offset=${offset}&limit=40`);
    offset += r.items.length;
    $('#gal-count').textContent = `${r.total} 件の記録`;
    for (const e of r.items) for (const im of [...(e.images || [])].reverse()) box.append(galItem(e, im));
    $('#gal-more').hidden = offset >= r.total;
  };
  $('#gal-more').onclick = load;
  await load();
}

function openLightbox(e, im) {
  $('#lb-img').src = imgUrl(im.path);
  $('#lb-open').href = imgUrl(im.path);
  $('#lb-text').textContent = e.text || e.action_name;
  $('#lb-meta').textContent = `${fmtTime(im.t || e.t)}・${e.action_name}・${e.scene || ''}・seed ${im.seed}`;
  $('#lb-prompt').textContent = `${im.pos}

Negative: ${im.neg}`;
  $('#lb-stage').onclick = () => {
    showEntry(Object.assign({}, e, { image: im.path }), false);
    setImage(im.path);
    $('#lightbox').close(); $('#gallery-dlg').close();
  };
  $('#lb-delete').onclick = async () => {
    if (!confirm('この画像を消しますか？（ファイルも削除され、元に戻せません）')) return;
    try {
      await api('/api/image/delete', { path: im.path });
      $$(`.gal-item[data-path="${CSS.escape(im.path)}"]`).forEach((x) => x.remove());
      if ($('#stage-img').dataset.rel === im.path) { $('#stage-img').classList.remove('show'); delete $('#stage-img').dataset.rel; }
      $('#lightbox').close();
      toast('消しました', 'ok');
      await refresh();
    } catch (err) { toast(err.message, 'err'); }
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
  hideTip();
  $$('#snav button').forEach((b) => b.classList.toggle('on', b.dataset.sec === sec));
  const body = $('#sbody');
  body.replaceChildren(...[SEC[sec]()].flat().filter((x) => x != null && x !== false));
  const head = $('.sbar h3', body);
  if (head) head.after(h('button', { class: 'btn ghost', title: 'この画面の説明（説明書）', onclick: () => openManual('sec-' + sec) }, '📖'));
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
// 項目名の横の ⓘ に出す説明. 画面にヒントが出ている項目と, 名前で分かる項目には付けない
const TIPS = {
  'あなたの名前': 'セリフの {player} に入ります。呼び方を固定していなければ、性格プリセットの呼び方（「{player}さん」など）の中で使われます',
  'Positive（外見・固有の特徴）': '髪・目・体型など、服以外のいつも変わらない特徴を書きます。服は「普段の服装」や着せ替えに書きます',
  '普段の服装（スケジュールで未指定のとき）': '生活スケジュールの予定で服装が空欄のときに着る服です',
  'プリセット': 'セリフの口調が変わります。条件・効果・画像は変わりません',
  '一人称': 'セリフの {fp} に入ります',
  '一人称（言いよどみ）': 'セリフの {fp_st} に入ります。照れたときなど',
  '終了': '開始より前の時刻にすると、日をまたぐ予定になります（22:00〜02:00 など）',
  '表示名': '画面の「いまの場面」と、セリフの {activity_label} に出ます',
  'activity id': '条件 activity=… で使う英数字の id です。反応やコマンドの条件で場面を見分けるのに使います',
  '場所': '画面の場面表示と、セリフの {location} に出ます',
  '服装（空欄=継続）': '空欄なら、そのときの服のまま。一時シーンでは @outing と書くとお出かけ着になります',
  '毎時の効果': 'この場面にいる1時間あたりのパラメータ変化です（例: energy:+8, sleepiness:-10）',
  'Positive（場面）': '背景・ポーズ・小物など、この場面の画像に足すタグです',
  '継続（分）': '一時シーンが続く時間です。過ぎると予定どおりの場面に戻ります',
  '着られる条件': '満たさないと、着せ替えタブで選べません。空欄ならいつでも',
  'Positive（服装）': '服のタグです。外見とは別の層に入り、着替えるとここが差し替わります',
  '実行できる条件': '満たさないとボタンが押せません。例: free=true（手が空いている）',
  '連続時の効果倍率': 'クールダウン中にくり返したときに効果へ掛ける倍率です（0.5 = くり返すたびに半分）',
  '効果': '1回あたりのパラメータ変化です（例: mood:+5, loneliness:-10）',
  'Positive（行動）': 'この行動の画像に足すタグです（ポーズ・構図など）',
  '条件': '空欄ならいつでも。例: mood>=50, affection<30',
  '追加の効果': '行動の効果に足されます。「置き換える」がオンなら、これだけになります',
  'Positive（反応）': 'この反応のときの表情・しぐさなどです',
  '分類': 'ステータスタブでの並び（からだ／こころ）です',
  '基本変化（/時）': '何もしなくても1時間に変わる量です（満腹度なら負）',
  '目標値': '自然回帰で戻っていく先の値です',
  'ホスト / アドレス': '同じ PC なら 127.0.0.1。別の PC なら、その PC の IP アドレス（ComfyUI は --listen 付きで起動）',
  'ポート': 'ComfyUI の既定は 8188 です',
  '同じプロンプトの画像があるとき': 'すぐ表示: 既存の画像を即座に出し、上限枚数までは裏で追加生成します\n毎回生成: 必ず ComfyUI で描きます',
  '幅': '8 の倍数。モデルに合わせます（SD1.5 なら 512 前後、SDXL なら 1024 前後）',
  '高さ': '8 の倍数。モデルに合わせます（SD1.5 なら 768 前後、SDXL なら 1216 前後）',
  'Steps': 'サンプリングの回数です。多いほど丁寧で遅くなります（20〜30 が目安）',
  'CFG': 'プロンプトへの忠実さです（5〜8 が目安）',
  '共通 Positive（先頭）': 'すべての画像の先頭に付く品質タグです（masterpiece など）',
  '共通 Negative': 'すべての画像に付くネガティブです',
  '「おかえり」を出す不在時間（時間）': 'これより長く空けてから開くと、「おかえり」（コマンド _return）の反応が出ます',
  '種類': 'Ollama か、LM Studio・llama.cpp などの OpenAI 互換 API',
  'モデル名': 'Ollama なら ollama list で出る名前です',
  'temperature': '高いほど自由な言い回しになります（0.7〜1.0 が目安）',
  'あなたのスキル': 'このコマンドの効き目が、あなたのスキルで 0.6〜1.4 倍になり、使うたびにスキルが伸びます。反応の条件では sk_talk などで参照できます',
  // チェックボックス
  '行動の効果・シーン切替を置き換える': '断る反応などに使います。オンだと、行動の効果・一時シーン・お金のやりとりを行わず、この反応の効果だけになります',
  '場面プロンプトを使わない（服装は残す）': '行動のプロンプトだけで場面を描くときに使います（出かけた先など）',
  'あなたも写る': '画像に、設定「あなた」の外見（Positive）を加えます',
  '家でだけできる': 'お出かけ中（一緒に出かけている場面）は出しません',
  'LLM を使わない': 'セリフ生成 (LLM) が有効でも、定型のセリフのままにします',
  '外出': '家にいない状態です。条件では away=true になります',
  '睡眠': '寝ている状態です。条件では asleep=true になります',
  '手が離せない': '用事の最中です。条件では busy=true になり、free=true ではなくなります',
  '外に着ていける': 'オフの服（部屋着・パジャマなど）は、お出かけのときにお出かけ着へ替わります',
  '寝たらスケジュール通りの服に戻す': '着せ替えた服は、寝るときに解除されます',
  '高いほど悪い': 'ステータスのバーの色が逆になります（ストレス・眠気など）',
  '中立': '良し悪しの色を付けません',
  'HTTPS': 'リバースプロキシなどで https で公開しているとき',
  'システムのプロキシを使う': '社内ネットワークなど、プロキシを通さないと届かないとき。既定では直接つなぎます',
};
const tipMark = (label) => TIPS[label] ? h('i', { class: 'tip', tabindex: 0, 'data-tip': TIPS[label] }, 'i') : null;
const fld = (label, el, hint, cls) => h('label', { class: 'fld ' + (cls || '') }, h('span', { class: 'fl' }, label, hint ? null : tipMark(label)), el, hint ? h('small', { class: 'hint' }, hint) : null);
const chk = (obj, key, label, onchange) => h('label', { class: 'check' }, inp(obj, key, { type: 'checkbox', onchange }), label, tipMark(label));

// ⓘ の説明: ダイアログの中でも切れないよう, 画面に固定した吹き出しで出す
function showTip(el) {
  hideTip();
  const box = h('div', { class: 'tipbox' }, el.dataset.tip);
  (el.closest('dialog') || document.body).append(box);
  const r = el.getBoundingClientRect(), b = box.getBoundingClientRect();
  box.style.left = Math.max(8, Math.min(r.left - 8, innerWidth - b.width - 8)) + 'px';
  box.style.top = (r.bottom + 7 + b.height > innerHeight ? r.top - b.height - 7 : r.bottom + 7) + 'px';
  S.tipBox = box;
}
function hideTip() { if (S.tipBox) { S.tipBox.remove(); S.tipBox = null; } }

function openManual(anchor) {
  const url = '/static/manual.html' + (anchor ? '#' + anchor : '');
  $('#manual-frame').src = url;
  $('#manual-tab').href = url;
  if (!$('#manual-dlg').open) $('#manual-dlg').showModal();
}

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
    h('div', {}, '条件キー: ', ['activity', 'location', 'phase', 'free', 'away', 'asleep', 'busy', 'hour', 'time', 'weekday', 'day', 'weekend', 'absent', 'repeat', 'outfit', 'outing', 'overriding', 'month', 'season', 'stage', 'apart', 'met_14d', 'gap_d', 'ready', 'gift_feel', 'money_feel']
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

/* ---- あなた (プレイヤー) */
// 行動パターン: 曜日を選んで, その日の流れ (時刻・行動・行き先・研鑽の分野) を編集. ほかの曜日へコピーもできる
function routineEditor(days) {
  const L = (S.boot.routine || {}).labels || {};
  const ch = ((S.view || {}).outdoor || {}).choices || {};
  const pl = ((S.view || {}).outdoor || {}).places || {};
  const skills = ((S.view || {}).solo || {}).skills || {};
  const cur = S.routineDay || 'mon';
  const list = days[cur] = days[cur] || [];
  const redraw = () => showSection('player');
  const sel = (b, key, opts, after) => h('select', { onchange: (ev) => { b[key] = ev.target.value; if (after) after(); redraw(); } },
    opts.map(([v, l]) => h('option', { value: v, selected: b[key] === v }, l)));
  const copyTo = (keys) => { keys.forEach((k) => { if (k !== cur) days[k] = clone(list); }); toast('コピーしました（保存で確定）', 'ok'); };
  return h('div', { class: 'routine' },
    h('div', { class: 'row', style: 'gap:4px;flex-wrap:wrap' }, DAYS.map(([d, label]) => h('button', { class: 'btn small' + (d === cur ? ' primary' : ''),
      onclick: () => { S.routineDay = d; redraw(); } }, label))),
    list.sort((a, b) => a.at.localeCompare(b.at)).map((b, i) => h('div', { class: 'row routine-row' },
      inp(b, 'at', { type: 'time' }),
      sel(b, 'do', Object.entries(L), () => {
        if (ch[b.do]) b.place = b.place && ch[b.do].includes(b.place) ? b.place : ch[b.do][0]; else delete b.place;
        if (b.do === 'practice') b.skill = b.skill || 'talk'; else delete b.skill;
      }),
      ch[b.do] ? sel(b, 'place', ch[b.do].map((x) => [x, `${(pl[x] || {}).icon || ''}${(pl[x] || {}).label || x}`])) : '',
      b.do === 'practice' ? sel(b, 'skill', Object.entries(skills)) : '',
      h('button', { class: 'btn small danger', onclick: () => { list.splice(i, 1); redraw(); } }, '×'))),
    h('div', { class: 'row', style: 'gap:6px;flex-wrap:wrap;margin-top:6px' },
      h('button', { class: 'btn small', onclick: () => { list.push({ at: '12:00', do: 'rest' }); redraw(); } }, '＋行動を足す'),
      h('button', { class: 'btn small', onclick: () => copyTo(['mon', 'tue', 'wed', 'thu', 'fri']) }, '平日（月〜金）にコピー'),
      h('button', { class: 'btn small', onclick: () => copyTo(['sat', 'sun']) }, '休日（土日）にコピー'),
      h('button', { class: 'btn small', onclick: () => copyTo(DAYS.map(([d]) => d)) }, '全曜日にコピー')));
}

const DAYS = [['mon', '月'], ['tue', '火'], ['wed', '水'], ['thu', '木'], ['fri', '金'], ['sat', '土'], ['sun', '日']];
SEC.player = () => {
  const p = SE.settings.player = SE.settings.player || {};
  // オフライン時の過ごし方 (画面を閉じている間): 曜日ごとの勤務時間. それ以外は家で静かに過ごす
  const off = SE.settings.offline = SE.settings.offline || {};
  if (off.enabled === undefined) off.enabled = true;
  if (!off.days) off.days = clone((S.boot.routine || {}).days || {});   // 以前の勤務時間の設定は, 読み替えた流れから始める
  if (!p.name) p.name = SE.settings.player_name || '';
  return [
    saveBar('あなた', async () => { await api('/api/settings', { settings: { player: p, offline: { enabled: off.enabled, days: off.days } } }); await reloadAll('player'); }),
    h('p', { class: 'lead' }, 'あなた自身の情報です（全ワールド共通）。キャラクターはこれを踏まえて反応します：セリフの {player} {player_job} {player_like} などに入り、反応の条件（player_gender・player_age・player_has_job・player_likes）で使え、LLM でセリフを作るときにも伝わります。呼ばれ方はキャラクターごと（性格プリセット）です。'),
    h('div', { class: 'grid4' },
      fld('名前', inp(p, 'name', { ph: 'ユウ' })),
      fld('性別', inp(p, 'gender', { type: 'select', options: [['', '設定しない'], ['male', '男性'], ['female', '女性'], ['other', 'その他']] })),
      fld('年齢', inp(p, 'age', { type: 'number' })),
      fld('職業', inp(p, 'job', { ph: '会社員' })),
      fld('人柄', inp(p, 'personality', { ph: '穏やかで少し不器用' }), null, 'span2'),
      fld('好きなもの', inp(p, 'likes', { ph: 'コーヒー, 映画, 猫' }), 'カンマ区切り', 'span2'),
      fld('苦手なもの', inp(p, 'dislikes', { ph: 'ピーマン, 早起き' }), 'カンマ区切り', 'span2'),
      fld('その他（キャラクターに伝わること）', inp(p, 'note', { type: 'textarea', rows: 2 }), null, 'span2')),
    h('div', { class: 'sect' }, '画像'),
    fld('あなたの外見（Positive）', inp(p, 'looks', { type: 'textarea', rows: 2, ph: '1boy, short black hair, hoodie' }),
      '「あなたも写る」コマンド（抱きしめる・手をつなぐ・お出かけ など）の画像に加えます。空欄なら加えません'),
    h('div', { class: 'sect' }, 'あなたの行動パターン（画面を閉じているあいだ）'),
    h('label', { class: 'check' }, inp(off, 'enabled', { type: 'checkbox' }), ' 画面を閉じているあいだも、下の流れのとおりに過ごす（オフラインモード）'),
    h('p', { class: 'hint' }, '曜日ごとの1日の流れです。各行動はその時刻から次の行動の時刻まで続きます。仕事（給料・体力・仕事スキル。うまくいかない・早退・残業も）、買い物（買うものリストの品を買う）、散歩・カフェ（出先での出会いは、気づけないので無難な対応）、家事・研鑽（洗剤・本があるとはかどる）、休む・家で静かに・寝る（体力が戻る）。雨で散歩をやめる、疲れて家事を飛ばす、など予定どおりにいかないこともあります。離れているキャラからメッセージが届くことも。30分未満の離席は対象外。結果は次に開いたとき、時系列でまとめて見られます。'),
    routineEditor(off.days),
  ];
};

/* ---- キャラクター */
SEC.char = () => {
  const c = SE.char, st = SE.settings;
  // 同じワールドのほかのキャラとの関係 (c から見た向き). 再描画しても編集中の値を保つ
  const hereNow = S.boot.characters.some((x) => x.id === c.id);     // 定義だけ (このワールドにいない人) を編集中なら, 関係は扱わない
  const others = hereNow ? S.boot.characters.filter((x) => x.id !== c.id) : [];
  if (!SE.rels || SE.rels.cid !== c.id || SE.rels.boot !== S.boot) {
    const mine = (S.boot.relations || {})[c.id] || {};
    SE.rels = { cid: c.id, boot: S.boot, map: Object.fromEntries(others.map((o) => [o.id, {
      knows: !!(mine[o.id] || {}).knows, kind: (mine[o.id] || {}).kind || '', affinity: (mine[o.id] || {}).affinity ?? 50 }])) };
  }
  const rels = SE.rels.map;
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
    saveBar('キャラクター', async () => {
      await api('/api/character/save', { data: c });
      if (others.length && S.boot.characters.some((x) => x.id === c.id)) await api('/api/relations', { id: c.id, relations: rels });
      await reloadAll('char');
    }, h('div', { class: 'row' },
      h('select', { onchange: (ev) => editDefinition(ev.target.value) },
        [['このワールドにいる', true], ['このワールドにはいない（定義だけ）', false]].map(([label, here]) => {
          const xs = allDefs().filter((x) => x.here === here);
          return xs.length ? h('optgroup', { label }, xs.map((x) => h('option', { value: x.id, selected: x.id === c.id }, x.name))) : '';
        })),
      h('button', { class: 'btn', onclick: newCharacterDialog }, '＋新規'))),
    h('p', { class: 'lead' }, 'キャラクターの定義（名前・外見・性格・服・スケジュールなど）は全ワールド共通で、ここでの変更は全ワールドに反映されます。状態・ログ・あなたとの間柄・キャラ同士の関係はワールドごとです。どこかのワールドに現れている（知り合っている）キャラは削除できません。外見の SD プロンプトは保存のたびに履歴へ残り、いつでも復元できます。あなた自身の情報は「あなた」で設定します。'),
    h('div', { class: 'grid4' },
      fld('名前', inp(c, 'name')),
      fld('一人称（固定）', inp(c, 'first_person', { ph: `空欄＝プリセット（${(curPersona(c) || {}).first_person || '私'}）` }),
        '空欄なら性格プリセットに従う'),
      fld('あなたの呼び方（固定）', inp(c, 'player_call', { ph: `空欄＝プリセット（${(curPersona(c) || {}).player_call || '{player}'}）` }),
        '{player} = あなたの名前。空欄なら性格プリセットに従う')),
    likesEditor(c),
    h('div', { class: 'sect' }, '外見プロンプト'),
    fld('Positive（外見・固有の特徴）', posEl),
    fld('Negative', negEl),
    fld('普段の服装（スケジュールで未指定のとき）', inp(c, 'outfit_default')),
    fld('お出かけ着（散歩などで外に出るとき）', inp(c, 'outfit_outing'), '部屋着やパジャマのまま出かけないよう、外出時はこの服になります（着せ替えで「外に着ていける」服を選んでいればそちら）'),
    h('div', { class: 'sect' }, '性格プリセット（セリフの口調）'),
    personaPicker(c),
    h('div', { class: 'sect' }, '性格・口調の説明（LLM 使用時に参照）'),
    inp(c, 'persona', { type: 'textarea', rows: 3 }),
    h('div', { class: 'sect' }, `${c.name}から見たほかのキャラ（同じワールド内）`),
    others.length ? h('div', {},
      h('p', { class: 'hint' }, '知っている人だけ、関係と好感度（0〜100）が LLM のセリフ作りに渡ります。向きごとに別なので、相手から見た関係は相手を選んで設定します。'),
      others.map((o) => {
        const r = rels[o.id];
        return h('div', { class: 'grid4 rel-row' },
          h('label', { class: 'fld' }, h('span', { class: 'fl' }, o.name),
            h('span', {}, h('input', { type: 'checkbox', checked: r.knows, onchange: (ev) => { r.knows = ev.target.checked; } }), ' 知っている')),
          fld('関係', inp(r, 'kind', { ph: '友人・姉妹・同僚など' })),
          fld('好感度', inp(r, 'affinity', { type: 'number' })));
      })) : h('p', { class: 'hint' }, hereNow ? 'このワールドにはほかのキャラがいません（＋新規で増やせます）。' : 'このキャラはこのワールドにはいないので、関係はこのワールドに出てから設定できます。'),
    othersSection(),
    h('div', { class: 'sect' }, `プロンプト履歴（${(c.prompt_history || []).length}）`),
    hist,
  ];
};

// キャラの追加: このワールドに現れるか・あなたとの間柄を確かめる (同居はいきなりは選べない)
function newCharacterDialog() {
  const v = { name: '', pos: '1girl, solo', persona_id: '', stage: 'contact' };
  const dlg = h('dialog', { class: 'modal', style: 'width:min(600px,94vw);height:auto;overflow:auto' });
  const close = () => { dlg.close(); dlg.remove(); };
  dlg.append(h('div', { class: 'modal-body', style: 'padding:16px;max-width:560px' },
    h('h3', {}, 'キャラクターを追加'),
    fld('名前', inp(v, 'name', { ph: '例: みお' })),
    fld('性格プリセット', inp(v, 'persona_id', { type: 'select', options: [['', 'なし（共通のセリフ）'], ...(S.boot.personas || []).map((p) => [p.id, p.name])] })),
    fld('外見プロンプト', inp(v, 'pos', { type: 'textarea', rows: 3 }), '「現れない」を選ぶと、出会うまでこのワールドでは編集できないので、ここで決めておきます'),
    fld('このワールドでの、あなたとの間柄', inp(v, 'stage', { type: 'select', options: [
      ['contact', '📱 連絡先を知っている'], ['known', '👤 知り合い（顔は知っているが、連絡先は知らない）'],
      ['absent', '— このワールドには現れない（偶然の出会いを待つ）'], ['random', '🎲 くじで決める']] }),
      'どれを選んでも登録キャラになり、ほかのワールドでは出会いや新しいワールドの顔ぶれの候補になります。同居はいきなりは選べません（仲を深めて「一緒に住まない？」を）。スケジュールは今のキャラから複製します'),
    h('div', { class: 'row', style: 'justify-content:flex-end;margin-top:12px' },
      h('button', { class: 'btn', onclick: close }, 'やめる'),
      h('button', { class: 'btn primary', onclick: async () => {
        if (!v.name.trim()) { toast('名前を入れてください', 'err'); return; }
        try {
          const r = await api('/api/character/new', v);
          const st = r.character._stage;
          const label = { absent: 'このワールドには現れない（偶然の出会いを待つ）', known: '👤 知り合い', contact: '📱 連絡先を知っている' }[st];
          S.current = null; await reloadAll('char');
          dlg.replaceChildren(h('div', { class: 'modal-body', style: 'padding:16px;max-width:560px' },
            h('h3', {}, `${r.character.name}を${st === 'absent' ? '登録しました' : '追加しました'}`),
            h('p', {}, `${v.stage === 'random' ? '🎲 くじの結果: ' : '間柄: '}${label}`),
            st === 'absent' ? h('p', { class: 'hint' }, 'このワールドのキャラ一覧には出ません。出先で偶然会えば、段階的に知り合えます（会えないことも）。この画面の下の「キャラクターの定義（全ワールド共通）」で、確認・編集・このワールドに出すことができます。') : '',
            h('div', { class: 'row', style: 'justify-content:flex-end;margin-top:12px' }, h('button', { class: 'btn primary', onclick: close }, '閉じる'))));
        } catch (e) { toast(e.message, 'err'); }
      } }, '追加'))));
  document.body.append(dlg);
  dlg.showModal();
}

// まだこのワールドに現れていない登録キャラ: 確認・編集・このワールドに出す・削除
// このワールドにはまだ現れていないキャラの定義: 確認・編集・このワールドに出す・削除 (どこにも現れていない定義だけ)
// 全員の定義. サーバーが古く defs が無いときは, このワールドの人とそれ以外から組み立てる
function allDefs() {
  if (S.boot.defs) return S.boot.defs;
  return [...(S.boot.characters || []).map((x) => ({ ...x, here: true, worlds: [], origin: '' })),
    ...(S.boot.others || []).map((x) => ({ ...x, here: false, worlds: x._worlds || [], origin: '' }))];
}
// キャラクターの定義 (全ワールド共通. どのワールドから見ても同じ一覧): このワールドにいるか・どこに現れているか・どこから来たか
const STAGE_JA = { known: '知り合い', contact: '連絡先', visit: '家に行ける仲', live: '同居' };
function othersSection() {
  const list = allDefs();
  const pname2 = (id) => ((S.boot.personas || []).find((p) => p.id === id) || {}).name || '性格なし';
  return h('div', {},
    h('div', { class: 'sect' }, `キャラクターの定義（全ワールド共通・${list.length}人）`),
    h('p', { class: 'hint' }, 'どのワールドから見ても同じ一覧です。「どこから来たか」で、いつ・どこで作った（出会って登録した）人かが分かります。このワールドにいない人は、出先で偶然会えば段階的に知り合えるほか、ここから知り合い・連絡先として出すこともできます。削除は、どのワールドにも現れていない定義だけです。'),
    list.map((c) => h('div', { class: 'row reg-row' + (c.id === (SE.char || {}).id ? ' on' : '') },
      h('div', { style: 'flex:1;min-width:12em' },
        h('b', {}, c.name), h('span', { class: 'muted small' }, `　${pname2(c.persona_id)}`),
        h('div', { class: 'small' }, c.here ? `このワールド: ${STAGE_JA[c.stage] || ''}` : 'このワールドにはいない',
          h('span', { class: 'muted' }, c.worlds.length ? `　（現れているワールド: ${c.worlds.join('、')}）` : '　（どのワールドにもまだ現れていない）')),
        h('div', { class: 'muted small' }, `どこから来たか: ${c.origin}`)),
      h('button', { class: 'btn small', onclick: () => editDefinition(c.id) }, '編集'),
      c.here ? '' : h('button', { class: 'btn small', title: 'このワールドに知り合い（連絡先は知らない）として出す', onclick: () => placeOther(c, 'known') }, '👤 知り合いとして出す'),
      c.here ? '' : h('button', { class: 'btn small', title: 'このワールドに連絡先を知っている人として出す', onclick: () => placeOther(c, 'contact') }, '📱 連絡先として出す'),
      h('button', { class: 'btn small danger', disabled: c.worlds.length > 0,
        title: c.worlds.length ? 'どこかのワールドに現れている（知り合っている）ので削除できません。編集はできます' : '定義を消す（全ワールドに波及）',
        onclick: async () => {
          if (!confirm(`「${c.name}」の定義を消しますか？（どのワールドの出会いの候補からも外れます）`)) return;
          try { await api('/api/character/delete', { id: c.id }); await reloadAll('char'); } catch (e) { toast(e.message, 'err'); }
        } }, '削除'))));
}
// 定義を編集する (このワールドにいない人も). いる人ならそのキャラを選ぶ
async function editDefinition(id) {
  if (S.boot.characters.some((x) => x.id === id)) {
    await api('/api/character/select', { id }); S.current = null; await reloadAll('char'); return;
  }
  try { SE.char = clone((await api('/api/character?id=' + encodeURIComponent(id))).character); showSection('char'); }
  catch (e) { toast(e.message, 'err'); }
}
async function placeOther(c, stage) {
  try { await api('/api/character/place', { id: c.id, stage }); toast(`${c.name}をこのワールドに出しました`, 'ok'); await reloadAll('char'); }
  catch (e) { toast(e.message, 'err'); }
}
function editRegistryDialog(c0) {
  const v = { id: c0.id, name: c0.name || '', pos: c0.pos || '', persona_id: c0.persona_id || '' };
  const dlg = h('dialog', { class: 'modal', style: 'width:min(600px,94vw);height:auto;overflow:auto' });
  const close = () => { dlg.close(); dlg.remove(); };
  dlg.append(h('div', { class: 'modal-body', style: 'padding:16px;max-width:560px' },
    h('h3', {}, `${c0.name}を編集`),
    fld('名前', inp(v, 'name')),
    fld('性格プリセット', inp(v, 'persona_id', { type: 'select', options: [['', 'なし（共通のセリフ）'], ...(S.boot.personas || []).map((p) => [p.id, p.name])] })),
    fld('外見プロンプト', inp(v, 'pos', { type: 'textarea', rows: 3 })),
    h('div', { class: 'row', style: 'justify-content:flex-end;margin-top:12px' },
      h('button', { class: 'btn', onclick: close }, 'やめる'),
      h('button', { class: 'btn primary', onclick: async () => {
        try { await api('/api/character/define', { data: Object.assign({}, v, { persona: '' }) }); close(); await reloadAll('char'); toast('保存しました（全ワールドに反映）', 'ok'); }
        catch (e) { toast(e.message, 'err'); }
      } }, '保存'))));
  document.body.append(dlg);
  dlg.showModal();
}

// 好き・苦手 (プレゼントの反応に効く). 触らなければ性格プリセットの既定に従う
function likesEditor(c) {
  const tags = (S.boot.catalog || {}).tags || {};
  const def = (S.boot.persona_likes || {})[c.persona_id] || [[], []];
  const cur = (k, i) => (c[k] !== undefined && c[k] !== null ? c[k] : def[i]);
  const row = (k, i, label) => h('div', { class: 'fld' }, h('span', { class: 'fl' }, label),
    h('div', { class: 'row', style: 'flex-wrap:wrap;gap:4px 10px' }, Object.entries(tags).map(([t, l]) => h('label', { class: 'check' },
      h('input', { type: 'checkbox', checked: cur(k, i).includes(t), onchange: (ev) => {
        const v = new Set(cur(k, i)); if (ev.target.checked) v.add(t); else v.delete(t); c[k] = [...v];
      } }), l))));
  return h('div', {},
    h('div', { class: 'sect' }, '好き・苦手（プレゼントの反応）'),
    row('likes', 0, '好きなもの'), row('dislikes', 1, '苦手なもの'),
    h('div', { class: 'row' }, h('span', { class: 'hint' }, c.likes == null && c.dislikes == null ? '性格プリセットの既定に従っています' : '自分で決めた好み'),
      h('button', { class: 'btn small', onclick: () => { c.likes = null; c.dislikes = null; showSection('char'); } }, '性格プリセットの既定に戻す')));
}

const curPersona = (c) => (S.boot.personas || []).find((p) => p.id === c.persona_id);

function personaPicker(c) {
  const ps = S.boot.personas || [];
  const cur = ps.find((p) => p.id === c.persona_id);
  return h('div', { class: 'grid2' },
    fld('プリセット', h('select', {
      value: c.persona_id || '',
      onchange: (ev) => {
        const p = ps.find((x) => x.id === ev.target.value);
        c.persona_id = ev.target.value || '';
        // 一人称・呼び方は固定していなければ自動でプリセットに従うので, ここでは性格の説明だけ合わせる
        if (p && (!c.persona || confirm(`「${p.name}」の性格の説明（LLM 用）もプリセットに合わせますか？`))) {
          c.persona = p.persona;
        }
        showSection('char');
      },
    }, h('option', { value: '' }, 'なし（共通のセリフ）'), ps.map((p) => h('option', { value: p.id }, p.name)))),
    h('div', { class: 'fld' }, h('span', { class: 'fl' }, '説明'),
      h('div', { class: 'hint', style: 'font-size:12.5px' }, cur ? cur.desc : 'コマンドやミニゲームに書かれた共通のセリフをそのまま使います'),
      cur && cur.traits && cur.traits.desc ? h('div', { class: 'hint', style: 'font-size:12.5px' }, '傾向: ' + cur.traits.desc) : '',
      cur ? h('button', { class: 'btn ghost', style: 'align-self:flex-start', onclick: () => { SE.personaSel = cur.id; showSection('personas'); } }, 'セリフ集を見る・編集') : ''));
}

/* ---- 性格プリセット (セリフ集) */
SEC.personas = () => {
  const ps = S.boot.personas || [];
  const box = h('div');
  const pick = h('select', { value: SE.personaSel || S.boot.character.persona_id || (ps[0] || {}).id, onchange: (ev) => { SE.personaSel = ev.target.value; SE.personaData = null; showSection('personas'); } },
    ps.map((p) => h('option', { value: p.id }, p.name + (p._custom ? '（編集済み）' : ''))));
  const load = async () => {
    const id = pick.value;
    if (!id) { box.replaceChildren(h('p', { class: 'muted' }, '性格プリセットがありません')); return; }
    if (!SE.personaData || SE.personaData.persona.id !== id) SE.personaData = await api('/api/persona?id=' + encodeURIComponent(id));
    const { persona: p, keys } = SE.personaData;
    p.lines = p.lines || {};
    const list = h('div');
    const search = h('input', { placeholder: 'キー・場面・セリフで絞り込み（例: hug, 野球拳, 断る）' });
    const draw = () => {
      const q = search.value.trim().toLowerCase();
      const rows = Object.entries(keys).filter(([k, v]) => !q || (k + v.scene + v.text + (p.lines[k] || []).join('')).toLowerCase().includes(q));
      list.replaceChildren(h('div', { class: 'muted small', style: 'margin:6px 0' }, `${rows.length} / ${Object.keys(keys).length} 場面（未記入 ${Object.keys(keys).filter((k) => !(p.lines[k] || []).length).length}）`),
        ...rows.slice(0, 150).map(([k, v]) => h('div', { class: 'card pl-row' },
          h('div', { class: 'card-head' }, h('b', {}, v.scene), h('code', { class: 'muted small' }, k), v.when ? h('span', { class: 'muted small' }, '条件: ' + v.when) : ''),
          h('div', { class: 'hint' }, '共通: ' + v.text),
          h('textarea', { rows: Math.max(1, (p.lines[k] || []).length), placeholder: '（空欄なら共通のセリフ）1行に1通り',
            value: (p.lines[k] || []).join('\n'),
            oninput: (ev) => { p.lines[k] = ev.target.value.split('\n').map((s) => s.trim()).filter(Boolean); } }))),
        rows.length > 150 ? h('p', { class: 'muted small' }, '多いので先頭150件だけ表示しています。絞り込んでください。') : '');
    };
    search.addEventListener('input', draw);
    draw();
    box.replaceChildren(
      h('div', { class: 'grid2' },
        fld('名前', inp(p, 'name')), fld('あなたの呼び方', inp(p, 'player_call'), '{player} = あなたの名前'),
        fld('一人称', inp(p, 'first_person')), fld('一人称（言いよどみ）', inp(p, 'first_person_stutter', { ph: '例: わ、私（無ければ空欄）' })),
        fld('説明（一覧に出る一行）', inp(p, 'desc'), null, 'spanall'),
        fld('性格・口調の説明（LLM 用）', inp(p, 'persona', { type: 'textarea', rows: 3 }), null, 'spanall'),
        fld('傾向（パラメータの動き方）', inp(p, 'traits', { type: 'textarea', rows: 4, fmt: (v) => JSON.stringify(v || {}, null, 0),
          parse: (x) => (x.trim() ? JSON.parse(x) : {}) }),
          'rate 基本変化の倍率 / drift 自然回帰の目標の加算 / drift_speed 戻る速さの倍率 / gain うれしい方向・hurt つらい方向の変化の倍率（パラメータ id ごと）/ approach 話しかけてくる多さ / absence 黙って離れられたときの堪え方 / jealousy ほかの人との仲に気づいたときの嫉妬の強さ / caution 段階の提案への慎重さ（ready に加算）/ gift 贈り物の効き目の倍率 / money お金・高価な物の受け止め方（money_feel に加算）/ neat きれい好き（-10〜10。家の散らかりを気にする・片付いていると好印象を持ちやすい）/ carer 世話焼き（0〜1。散らかっていると片付けを手伝い出す）',
          'spanall')),
      h('div', { class: 'sect' }, 'セリフ'),
      h('p', { class: 'hint' }, '各場面のセリフを1行に1通り書くと、その中からランダムに選ばれます。空欄の場面は共通のセリフになります。一人称は {fp}（言いよどみは {fp_st}）、あなたを呼ぶところは {call} と書くと、キャラクターの設定で固定した一人称・呼び方にも対応します。その他の置換文字は共通のセリフと同じものが使えます。'),
      search, list);
  };
  load().catch((e) => box.replaceChildren(h('p', { class: 'result err' }, e.message)));
  const cur = ps.find((p) => p.id === pick.value) || {};
  return [
    saveBar('性格・セリフ集', async () => {
      if (!SE.personaData) return;
      const r = await api('/api/persona/save', { persona: SE.personaData.persona });
      SE.personaData.persona = r.persona;
      await reloadAll('personas');
    }, h('div', { class: 'row' }, pick,
      h('button', { class: 'btn', onclick: async () => {
        if (!SE.personaData) return;
        const id = prompt('新しい性格の id（英数字）', SE.personaData.persona.id + '_custom');
        if (!id) return;
        const np = clone(SE.personaData.persona);
        np.id = id; np.name = np.name + '（コピー）';
        try { await api('/api/persona/save', { persona: np }); SE.personaSel = id; SE.personaData = null; await reloadAll('personas'); } catch (e) { toast(e.message, 'err'); }
      } }, '複製'),
      cur._custom ? h('button', { class: 'btn danger', onclick: async () => {
        if (!confirm('編集内容を捨てて、既定の内容に戻しますか？（既定の無い自作の性格は削除されます）')) return;
        await api('/api/persona/reset', { id: cur.id }); SE.personaData = null; await reloadAll('personas');
      } }, '既定に戻す') : '')),
    h('p', { class: 'lead' }, '性格ごとのセリフ集です。キャラクターの設定で選んだ性格のセリフが、コマンドの反応やミニゲームで使われます。条件・効果・画像プロンプトはコマンドやミニゲームの設定のままなので、口調だけが変わります。'),
    box,
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
        h('label', { class: 'check', title: 'あなたと一緒のお出かけ。お出かけ着になり、「家に帰る」が出る' },
          h('input', { type: 'checkbox', checked: !!e.outing, onchange: (ev) => { e.outing = ev.target.checked; } }), '一緒にお出かけ'),
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
        h('div', { class: 'fld' }, h('span', { class: 'fl' }, '外出'), chk(o, 'outing_ok', '外に着ていける')),
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
    h('p', { class: 'lead' }, '遊べるミニゲームの定義です（JSON で直接編集）。kind は yakyuken（野球拳）/ acchimuite（あっち向いてホイ）/ mahjong（脱衣麻雀）/ connect4 / hex / reversi / yacht / koikoi / poker / blackjack / concentration / oldmaid で、同じ kind で中身の違うゲームをいくつでも作れます。'),
    h('div', { class: 'keys' },
      h('div', {}, h('code', {}, 'require'), ' 遊べる条件（満たさないとボタンが押せない） / ', h('code', {}, 'when'), ' 誘いに乗る条件（満たさないと lines.refuse で断られる）'),
      h('div', {}, h('code', {}, 'stages'), ' 野球拳の段階。mode: add = 今の服に追記 / replace = 置き換え、remove = 外見プロンプトから外すタグ。', h('code', {}, 'giveup'), ' は降参時の服装'),
      h('div', {}, h('code', {}, 'lines'), ' 場面ごとのセリフ（反応と同じ書式: text / when / priority / pos / neg）。',
        '野球拳: refuse start hint draw round_win round_lose win lose quit interrupted、あっち向いてホイ: start hint draw rps_me rps_her point_me dodge_me point_her dodge_her win lose quit interrupted'),
      h('div', {}, h('code', {}, 'effects'), ' 場面ごとのパラメータ変化。セリフの置換: ', ['{her_hand}', '{my_hand}', '{hint_hand}', '{stage}', '{dir}', '{her_dir}'].map((k) => [h('code', {}, k), ' '])),
      h('div', {}, '条件で使える追加キー: ', ['game_stage', 'game_round', 'lives', 'my_point', 'her_point'].map((k) => [h('code', {}, k), ' '])),
      h('div', {}, '脱衣麻雀: ', h('code', {}, 'live_wall'), ' ツモ山の枚数 / ', h('code', {}, 'han_steps'), ' [最低翻, 脱ぐ段階数] の表 / ',
        h('code', {}, 'riichi_rate'), '、セリフ: refuse start hint(tenpai) her_riichi my_riichi hand_win hand_lose(tsumo) ryuukyoku win lose quit interrupted、置換 ',
        h('code', {}, '{yaku}'), ' ', h('code', {}, '{han}')),
      h('div', {}, '盤面ゲーム: ', h('code', {}, 'first'), ' me / her / random、', h('code', {}, 'size'), ' ヘックスの盤の大きさ、',
        h('code', {}, 'comment_every'), ' 途中のひとことの間隔、セリフ: start mid(advantage: 正 = あなた有利) pass win lose draw quit interrupted'),
      h('div', {}, 'ヨット: ', h('code', {}, 'first'), '、', h('code', {}, 'comment_every'), ' ラウンド間隔、セリフ: start mid my_yacht her_yacht win lose draw quit interrupted、置換 ',
        h('code', {}, '{me}'), ' ', h('code', {}, '{her}'), ' 合計点'),
      h('div', {}, '勝負の形（こいこい・ポーカー・ブラックジャック）: ', h('code', {}, 'stages'), ' を書くと脱衣（', h('code', {}, 'lives'),
        '）、無ければ ', h('code', {}, 'match'), ': wins（', h('code', {}, 'target'), ' 勝先取）/ points（', h('code', {}, 'rounds'),
        ' 局の合計点）。セリフ: round_win round_lose round_draw win lose draw、こいこい: her_koi my_koi、ポーカー: her_strong her_weak her_fold、',
        '神経衰弱: my_pair her_combo、ババ抜き: peek_joker peek_safe my_joker her_joker'),
      h('div', {}, '強さ（麻雀・盤面）: ', h('code', {}, 'skill'), ' 0〜1 / ', h('code', {}, 'err'), ' 凡ミス率（眠気・不機嫌で上がる）')),
    h('div', { style: 'margin-top:10px' }, ta),
    res,
  ];
};

/* ---- 表示 (このブラウザだけの設定) */
SEC.display = () => {
  const u = S.ui;
  const set = (k, v) => { u[k] = v; saveUi(); };
  const radio = (k, v, label) => h('label', { class: 'check' },
    h('input', { type: 'radio', name: 'ui-' + k, checked: u[k] === v, onchange: () => set(k, v) }), label);
  const range = (k, min, max, step, fmt) => {
    const out = h('span', { class: 'pval' }, fmt(u[k]));
    return h('div', { class: 'slider-row', style: 'grid-template-columns: 1fr 50px' }, h('input', { type: 'range', min, max, step, value: u[k],
      oninput: (ev) => { out.textContent = fmt(+ev.target.value); set(k, +ev.target.value); } }), out);
  };
  return [
    h('div', { class: 'sbar' }, h('h3', {}, '表示'), h('div', { class: 'spacer' }),
      h('button', { class: 'btn', onclick: () => { S.ui = Object.assign({}, UI_DEFAULT); saveUi(); showSection('display'); } }, '元に戻す')),
    h('p', { class: 'lead' }, '会話欄（セリフの窓）の見せ方です。このブラウザにだけ保存され、変更はすぐ反映されます。会話欄は 💬 ボタン・H キー・画像のクリックでいつでも隠せます。'),
    h('div', { class: 'sect' }, '会話欄の位置'),
    h('div', { class: 'row' }, radio('pos', 'bottom', '画像に重ねる（下）'), radio('pos', 'top', '画像に重ねる（上）'),
      radio('pos', 'below', '画像の下に分ける（重ならない）')),
    h('div', { class: 'sect' }, 'キャラクターのステータス'),
    h('div', { class: 'row' }, radio('stats', 'exact', '正確な数値'), radio('stats', 'look', '見た目でわかることだけ'), radio('stats', 'hidden', '隠す')),
    h('p', { class: 'hint' }, '「見た目でわかることだけ」は、眠そう・お腹すいてそう のような様子だけを出します（数値は出さず、少しずれることもあります。好感度や信頼など見えないものは「？」）。どちらの場合も、ステータスタブの「数値を見る」で1分だけ正確な数値を見られます。'),
    h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: u.deltas !== false, onchange: (ev) => set('deltas', ev.target.checked) }),
      'パラメータの変化（機嫌 +3 など）を会話欄とコマンドの説明に出す'),
    h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: !!u.showApart, onchange: (ev) => set('showApart', ev.target.checked) }),
      '離れている相手の様子も見る（いまの場面・ステータス・表情・機嫌の理由）'),
    h('p', { class: 'hint' }, '既定では、一緒に暮らしていない・会っていない相手の様子は見えません（本人から聞いた機嫌の理由だけ）。'),
    h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: u.callSound !== false, onchange: (ev) => set('callSound', ev.target.checked) }),
      '出先で声をかけられたときに、控えめな音でも知らせる'),
    h('div', { class: 'sect' }, '見た目'),
    h('div', { class: 'grid2' },
      h('div', { class: 'fld' }, h('span', { class: 'fl' }, '背景の濃さ'), range('alpha', 0.2, 0.95, 0.05, (v) => Math.round(v * 100) + '%')),
      h('div', { class: 'fld' }, h('span', { class: 'fl' }, '文字の大きさ'), range('font', 13, 24, 1, (v) => v + 'px')),
      h('div', { class: 'fld' }, h('span', { class: 'fl' }, '大きさ'),
        h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: !!u.compact, onchange: (ev) => set('compact', ev.target.checked) }),
          'コンパクト（高さを抑え、時刻と変化の表示を省く）')),
      h('div', { class: 'fld' }, h('span', { class: 'fl' }, '自動で隠す'),
        h('select', { value: String(u.autoHide), onchange: (ev) => set('autoHide', +ev.target.value) },
          [[0, '隠さない'], [3, '読み終えて3秒後'], [5, '読み終えて5秒後'], [10, '読み終えて10秒後']].map(([v, l]) => h('option', { value: String(v) }, l))),
        h('small', { class: 'hint' }, '新しいセリフが来たら、また表示されます'))),
  ];
};

/* ---- キャラの出来事 */
SEC.events = () => {
  const ta = h('textarea', { rows: 30, style: 'min-height:55vh', value: JSON.stringify(S.boot.events || [], null, 1) });
  const res = h('div', { class: 'result', hidden: true });
  ta.addEventListener('input', () => {
    try { JSON.parse(ta.value); ta.classList.remove('bad'); res.hidden = true; }
    catch (e) { ta.classList.add('bad'); res.hidden = false; res.className = 'result err'; res.textContent = 'JSON の書式エラー: ' + e.message; }
  });
  return [
    saveBar('キャラの出来事', async () => { await api('/api/events', { events: JSON.parse(ta.value) }); await reloadAll(); }),
    h('p', { class: 'lead' }, '時間の経過でキャラ側に起きる出来事です。機嫌などが動き、「機嫌の理由」として記録されます。「何かあった？」で聞くと、tell の内容を話します（「〜んです」とつながる常体で書く）。'),
    h('div', { class: 'keys' },
      h('div', {}, h('code', {}, 'mood'), ' good / bad / neutral（理由として記録されるのは good と bad）　', h('code', {}, 'when'), ' 起きる条件（her_money・my_money・absent なども使える）'),
      h('div', {}, h('code', {}, 'weight'), ' 起きやすさ　', h('code', {}, 'cooldown_h'), ' 同じ出来事が再び起きるまでの時間　', h('code', {}, 'effects'), ' パラメータ変化'),
      h('div', {}, h('code', {}, 'money'), ' {"a": 金額 or [最小, 最大]}（キャラのお金。負なら支出）　',
        h('code', {}, 'request'), ' {"kind": money | gift | treat | present, "amount": [最小, 最大]}（画面に「お願い」が出る）')),
    h('div', { style: 'margin-top:10px' }, ta), res,
  ];
};

/* ---- キャラからの働きかけ */
SEC.approaches = () => {
  const ta = h('textarea', { rows: 30, style: 'min-height:55vh', value: JSON.stringify(S.boot.approaches || [], null, 1) });
  const res = h('div', { class: 'result', hidden: true });
  ta.addEventListener('input', () => {
    try { JSON.parse(ta.value); ta.classList.remove('bad'); res.hidden = true; }
    catch (e) { ta.classList.add('bad'); res.hidden = false; res.className = 'result err'; res.textContent = 'JSON の書式エラー: ' + e.message; }
  });
  return [
    saveBar('キャラからの働きかけ', async () => { await api('/api/approaches', { approaches: JSON.parse(ta.value) }); await reloadAll(); }),
    h('p', { class: 'lead' }, 'あなたが画面を開いてそばにいるとき（構っている・放置している・作業中）に、キャラのほうから話しかけてくる内容です。寂しさ・退屈・好感度が高いほど来やすく、「作業するね」と告げていれば遠慮します（とても寂しければ来ます）。答えずに放っておくと、待ち時間のあとで「返事がなかった」になり、寂しいときほど機嫌が下がります。'),
    h('div', { class: 'keys' },
      h('div', {}, h('code', {}, 'when'), ' 来る条件（presence=busy なら作業中だけ）　', h('code', {}, 'weight'), ' 来やすさ　', h('code', {}, 'cooldown_h'), ' 同じ働きかけの間隔　', h('code', {}, 'text'), ' 話しかけるセリフ'),
      h('div', {}, h('code', {}, 'accept'), ' / ', h('code', {}, 'later'), ' 答えたとき（label ボタン名・text・effects・skill・reason_good）。accept に ', h('code', {}, 'action'), ' を書くと、そのコマンドを実行（例: walk, game）'),
      h('div', {}, h('code', {}, 'ignore'), ' 放っておいたとき（text・busy_text 作業中だったとき・effects）。効き目は寂しさで増え、作業中・不在なら減る')),
    h('div', { style: 'margin-top:10px' }, ta), res,
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
        fld('あなたのスキル', inp(a, 'skill', { type: 'select', options: [['', 'なし'], ['talk', '会話'], ['touch', 'スキンシップ'], ['cook', '料理'], ['work', '仕事']] })),
        fld('効果', inp(a, 'effects', { fmt: fmtEff, parse: parseEff, ph: 'mood:+5, loneliness:-10' }), null, 'spanall'),
        fld('Positive（行動）', inp(a, 'pos', { type: 'textarea', rows: 2 }), null, 'span2'),
        fld('Negative（行動）', inp(a, 'neg', { type: 'textarea', rows: 2 }), null, 'span2'),
        h('div', { class: 'row spanall' },
          chk(a, 'replace_scene', '場面プロンプトを使わない（服装は残す）'),
          chk(a, 'no_llm', 'LLM を使わない'),
          chk(a, 'home_only', '家でだけできる'),
          chk(a, 'with_player', 'あなたも写る'),
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
    h('p', { class: 'lead' }, 'キャラへの行動と、その反応を編集します。行動・反応のどちらにも Positive / Negative プロンプトを指定でき、画像生成時に共通 → キャラクター →（あなた）→ 服装 → 場面 → 時間帯 → 状態 → 行動 → 反応 の順で合成されます。'),
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
      h('div', { class: 'fld' }, h('span', { class: 'fl' }, '通信'), chk(c, 'use_proxy', 'システムのプロキシを使う')),
      h('div', { class: 'fld span2' }, h('span', { class: 'fl' }, 'ComfyUI 側の保存'),
        chk(c, 'keep_on_server', 'ComfyUI の output フォルダにも保存する'),
        h('small', { class: 'hint' }, 'オフ（既定）: ComfyUI の一時フォルダ（再起動で消える）経由で受け取り、このアプリの data/images にだけ保存します。カスタムワークフローの SaveImage も自動で一時保存に置き換えます。')),
      fld('保存先（オンのとき）', inp(c, 'output_prefix', { ph: 'kurashi/kurashi' }), 'output からの相対パス + ファイル名の頭。「kurashi/kurashi」なら output/kurashi/ に入る（内蔵ワークフローのみ）', 'span2')),
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
    h('div', { class: 'sect' }, 'お金・出来事'),
    (() => {
      const e = w.economy = w.economy || {};
      const n = (k, label, hint, step) => fld(label, inp(e, k, { type: 'number', step: step || '100' }), hint);
      return h('div', { class: 'grid3' },
        n('player_daily_income', 'あなたの日給（放置でたまる）', '日付が変わるたびに入る'),
        n('her_daily_income', 'キャラの日給', 'バイト代・仕送りなど'),
        n('living_cost_per_day', 'あなたの家の生活費（1日・二人暮らしの額）', '一人なら半分。同居相手との分け方は「お金」タブで選ぶ'),
        n('home_cost_per_month', 'あなたの家の家賃・光熱費・通信費（1か月）', '月はじめに引かれる。足りなければ知り合いに借りるか借金', '1000'),
        n('her_living_cost_per_day', 'キャラが自分で払う生活費（1日）', '一緒に暮らしていないキャラの分'),
        n('work_wage_per_hour', '仕事の時給', '仕事スキルで 0.6〜1.4 倍', '10'),
        n('work_max_hours', '仕事の上限（時間）', '1回の仕事で稼げる時間の上限', '1'),
        n('side_job_unit', '内職の単価（1個）', '仕事スキルで 0.6〜1.4 倍', '1'),
        n('news_rate_per_hour', '株のニュースの出やすさ（1時間あたり）', '0.12 ≒ 1日に3回ほど', '0.01'),
        n('news_accuracy', 'ニュースの当たりやすさ', '0.7 = 7割はニュースどおりに動く', '0.05'),
        n('event_rate_per_hour', '出来事の起きやすさ（1時間あたり）', '0.08 ≒ 起きている間に1日1〜2回', '0.01'));
    })(),
    h('div', { class: 'sect' }, '在席・働きかけ'),
    (() => {
      const e = w.presence = w.presence || {};
      const n = (k, label, hint, step) => fld(label, inp(e, k, { type: 'number', step: step || '1' }), hint);
      return h('div', { class: 'grid3' },
        n('idle_minutes', '「のんびり」になるまで（分）', 'この間なにも操作しないと、そばで放置している扱い'),
        n('gone_minutes', '「いない」になるまで（分）', '画面を閉じてから、この時間で不在とみなす'),
        n('approach_rate_per_hour', '働きかけの来やすさ（1時間あたり）', 'キャラの寂しさ・退屈・好感度でさらに増減', '0.1'),
        n('approach_apart_rate_per_hour', '離れている相手からのメッセージの来やすさ（1時間あたり）', '寂しさ・好感度・機嫌でさらに増減', '0.05'),
        n('approach_wait_minutes', '返事を待ってくれる時間（分）'),
        n('approach_quiet_minutes', '次の働きかけまでの間隔（分）'));
    })(),
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
    h('p', { class: 'lead' }, 'デバッグや調整用です。データは kurashi/data/ に JSON と画像で保存されています（ワールドごとの分は data/worlds/ の下）。'),
    h('div', { class: 'sect' }, 'ワールド'),
    worldManager(),
    h('div', { class: 'sect' }, `${v.name}の現在値を直接変更`),
    ...sliders,
    h('div', { class: 'row', style: 'margin-top:10px' },
      h('button', { class: 'btn primary', onclick: async () => { await api('/api/state/set', { values: vals }); toast('反映しました', 'ok'); await refresh(); } }, '反映'),
      h('button', { class: 'btn', onclick: async () => { await api('/api/state/clear_override', {}); toast('一時シーンを解除しました', 'ok'); await refresh(); } }, '一時シーンを解除（予定に戻す）'),
      h('button', { class: 'btn danger', onclick: async () => {
        if (!confirm('パラメータを初期値に戻しますか？（ログと画像は残ります）')) return;
        await api('/api/state/reset', {}); toast('初期化しました', 'ok'); await refresh(); showSection('data');
      } }, 'パラメータ初期化')),
    h('div', { class: 'sect' }, '出来事を起こす（テスト用）'),
    (() => {
      const sel = h('select', {}, (S.boot.events || []).map((e) => h('option', { value: e.id }, `${e.label}（${e.mood}）`)));
      return h('div', { class: 'row' }, sel, h('button', { class: 'btn', onclick: async () => {
        try { const r = await api('/api/events/force', { id: sel.value }); toast(`起こしました: ${r.event.label}`, 'ok'); await refresh(); } catch (e) { toast(e.message, 'err'); }
      } }, '起こす'));
    })(),
    h('div', { class: 'sect' }, '働きかけを起こす（テスト用）'),
    (() => {
      const sel = h('select', {}, (S.boot.approaches || []).map((e) => h('option', { value: e.id }, `${e.icon || ''} ${e.label || e.id}`)));
      return h('div', { class: 'row' }, sel, h('button', { class: 'btn', onclick: async () => {
        try { const r = await api('/api/approach/force', { id: sel.value }); $('#settings-dlg').close(); handleActResult(r); await refresh(); } catch (e) { toast(e.message, 'err'); }
      } }, '起こす'));
    })(),
    h('div', { class: 'sect' }, '偶然の出会いを起こす（テスト用）'),
    h('div', { class: 'row' },
      [['知らない人と知り合う', true], ['登録済みの人に偶然会う', false]].map(([label, stranger]) => h('button', { class: 'btn', onclick: async () => {
        const r = await api('/api/encounter/force', { stranger });
        toast(r.encounter ? r.encounter.text : '起きませんでした（返事待ちの人がいる・会える人がいない など）', r.encounter ? 'ok' : 'err');
        await refresh();
      } }, label))),
    h('div', { class: 'sect' }, 'エクスポート / インポート'),
    h('div', { class: 'row' },
      h('button', { class: 'btn', onclick: () => downloadJson('actions.json', S.boot.actions) }, 'コマンドを保存'),
      h('button', { class: 'btn', onclick: () => downloadJson('params.json', S.boot.params) }, 'パラメータを保存'),
      h('button', { class: 'btn', onclick: () => downloadJson(`character_${S.boot.character.id}.json`, S.boot.character) }, 'キャラクターを保存')),
    h('div', { class: 'row', style: 'margin-top:8px' },
      h('button', { class: 'btn', onclick: async () => { try { const j = await pickJson(); if (!Array.isArray(j)) throw new Error('配列ではありません'); await api('/api/actions', { actions: j }); await reloadAll(); toast('コマンドを読み込みました', 'ok'); } catch (e) { toast(e.message, 'err'); } } }, 'コマンドを読込'),
      h('button', { class: 'btn', onclick: async () => { try { const j = await pickJson(); if (!Array.isArray(j)) throw new Error('配列ではありません'); await api('/api/params', { params: j }); await reloadAll(); toast('パラメータを読み込みました', 'ok'); } catch (e) { toast(e.message, 'err'); } } }, 'パラメータを読込'),
      h('button', { class: 'btn', onclick: async () => { try { const j = await pickJson(); if (!j.id) throw new Error('id がありません'); await api('/api/character/save', { data: j }); if (!S.boot.characters.some((x) => x.id === j.id)) await api('/api/character/place', { id: j.id, stage: 'contact' }); await api('/api/character/select', { id: j.id }); S.current = null; await reloadAll(); toast('キャラクターを読み込みました', 'ok'); } catch (e) { toast(e.message, 'err'); } } }, 'キャラクターを読込')),
  ];
};

function worldManager() {
  const W = S.boot.worlds;
  const nameEl = h('input', { placeholder: '新しいワールドの名前' });
  const fromEl = h('select', {}, h('option', { value: '' }, '登録済みのキャラから始める（間柄はくじ）'),
    W.worlds.map((w) => h('option', { value: w.id }, `「${w.name}」のキャラ・コマンドなどを複製`)));
  return h('div', {},
    h('p', { class: 'hint' }, 'ワールドごとにキャラ・状態・ログ・お金・スキル・在席・コマンドなどの定義が別になります（同じキャラでもワールドが違えば無関係）。'
      + 'ComfyUI・LLM・表示の設定、性格プリセット、画像ファイルは全ワールド共通です（同じプロンプトの画像はワールドをまたいで使い回します）。'),
    W.worlds.map((w) => h('div', { class: 'row world-row' },
      h('span', { style: 'min-width:10em' }, (w.id === W.current ? '▶ ' : '') + w.name),
      w.id === W.current ? h('span', { class: 'muted' }, '開いています')
        : h('button', { class: 'btn', onclick: () => switchWorld(w.id) }, '開く'),
      h('button', { class: 'btn', onclick: async () => {
        const name = prompt('ワールドの名前', w.name);
        if (!name) return;
        await api('/api/world/rename', { id: w.id, name }); await reloadAll('data');
      } }, '名前変更'),
      h('button', { class: 'btn danger', onclick: async () => {
        if (!confirm(`ワールド「${w.name}」を削除しますか？（キャラ・状態・ログ・お金が消えます。画像ファイルは残ります）`)) return;
        try {
          const r = await api('/api/world/delete', { id: w.id });
          if (w.id === W.current || r.current !== W.current) location.reload(); else await reloadAll('data');
        } catch (e) { toast(e.message, 'err'); }
      } }, '削除'))),
    h('div', { class: 'row', style: 'margin-top:8px' }, nameEl, fromEl,
      h('button', { class: 'btn primary', onclick: async () => {
        const r = await api('/api/world/create', { name: nameEl.value, copy_from: fromEl.value });
        toast('ワールドを作りました', 'ok');
        location.reload();
        return r;
      } }, '＋作成して開く')));
}

/* ================================================================= events */
function bind() {
  $$('#tabs button').forEach((b) => b.addEventListener('click', () => {
    $$('#tabs button').forEach((x) => x.classList.toggle('on', x === b));
    for (const t of ['commands', 'dress', 'games', 'money', 'items', 'status', 'log']) $('#tab-' + t).hidden = t !== b.dataset.tab;
  }));
  $('#dialogue').addEventListener('click', () => {
    if (S.typing) { clearInterval(S.typing); S.typing = null; $('#dtext').textContent = S.typingText; }
  });
  $('#world-select').addEventListener('change', (ev) => switchWorld(ev.target.value));
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
  $('#btn-chat').addEventListener('click', () => openChat());
  $('#home-chip').addEventListener('click', () => openHome());
  $('#btn-manual').addEventListener('click', () => openManual());
  const seen = () => { S.lastInput = Date.now(); };
  for (const t of ['keydown', 'pointerdown', 'wheel', 'touchstart']) document.addEventListener(t, seen, { passive: true, capture: true });
  document.addEventListener('pointermove', () => { if (Date.now() - S.lastInput > 5000) seen(); }, { passive: true });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && S.titleBase) { document.title = S.titleBase; S.titleBase = null; }
    if (!document.hidden) refresh();
  });
  $('#task-close').addEventListener('click', closeTask);
  $('#task-dlg').addEventListener('cancel', (ev) => { ev.preventDefault(); closeTask(); });
  for (const t of ['mouseover', 'focusin']) document.addEventListener(t, (ev) => { const el = ev.target.closest?.('.tip'); if (el) showTip(el); });
  for (const t of ['mouseout', 'focusout']) document.addEventListener(t, (ev) => { if (ev.target.closest?.('.tip')) hideTip(); });
  // ⓘ は label の中にあるので, 押してもチェックや入力欄が反応しないようにする
  document.addEventListener('click', (ev) => { if (ev.target.closest?.('.tip')) ev.preventDefault(); }, true);
  $$('#snav button').forEach((b) => b.addEventListener('click', () => showSection(b.dataset.sec)));
  $$('[data-close]').forEach((b) => b.addEventListener('click', () => b.closest('dialog').close()));
  $('#settings-dlg').addEventListener('close', () => refresh());
  $('#btn-dlg').addEventListener('click', () => setDlgHidden(!S.dlgHidden));
  // 画像そのもの (会話欄・ボタン以外) のクリックでも出し入れ
  $('#stage').addEventListener('click', (ev) => {
    if (ev.target.closest('.dialogue, .stage-tools, .stage-top, button')) return;
    setDlgHidden(!S.dlgHidden);
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'h' && ev.key !== 'H') return;
    if (ev.ctrlKey || ev.metaKey || ev.altKey || ev.target.closest?.('input, textarea, select, dialog[open]')) return;
    setDlgHidden(!S.dlgHidden);
  });
  if (window.ResizeObserver) new ResizeObserver(fitDialogueSpace).observe($('#dialogue'));
  applyUi();
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
