'use strict';
/* Comfy LIFE — フロントエンド (依存なし) */

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
  view: null,       // /api/state (あなた中心: company = いまそばにいる人, target = 「誰かと」の相手, with = その人の様子)
  current: null,    // 表示中のログエントリ
  jobs: new Map(),  // jid -> job view
  busy: false,
  typing: null,
  lastDeltas: {},
  showHidden: false,
  tab: 'solo', sub: 'commands', logWho: '',
};
const pname = (id) => (S.boot.params.find((p) => p.id === id) || {}).name || id;
const T = () => (S.view && S.view.with) || null;          // 「誰かと」の相手の様子 (誰もそばにいなければ null)
const tid = () => (S.view && S.view.target) || null;
const cname = (id) => (S.boot.characters.find((x) => x.id === id) || {}).name || '';
// 「誰かと」の操作には相手を添える
const withT = (body) => Object.assign({}, body || {}, tid() ? { character: tid() } : {});

/* ---------------------------------------------------------------- boot */
async function loadBoot() {
  S.boot = await api('/api/boot');
  const ws = $('#world-select');
  ws.replaceChildren(...S.boot.worlds.worlds.map((w) => h('option', { value: w.id }, '🌐 ' + w.name)));
  ws.value = S.boot.worlds.current;
  ws.hidden = S.boot.worlds.worlds.length < 2;
}

// ワールドを切り替えたら, キャラ・ログ・お金・在席がすべて別になるので画面ごと読み直す
async function switchWorld(id) {
  await api('/api/world/switch', { id });
  location.reload();
}

async function refresh() {
  if (!S.boot) return;               // 起動の読み込みより先に呼ばれた (画面の表示切り替えなど)
  try {
    const q = S.view && S.view.target ? '&character=' + encodeURIComponent(S.view.target) : '';
    S.view = await api('/api/state?beat=1&idle=' + idleSec() + q);
  } catch (e) {
    toast('状態の取得に失敗: ' + e.message, 'err');
    return;
  }
  const v = S.view;
  // ミニゲームの画面 (minigames.js) は S.view.games / S.view.name を見る: 「誰かと」の相手のもの
  v.games = (T() || {}).games || { list: [], current: null };
  v.name = (T() || {}).name || '';
  for (const j of v.jobs) if (!S.jobs.has(j.id)) trackJob(j.id);
  if (v.gap) toast(v.gap.text, 'ok');
  if (v.street_auto) toast(v.street_auto.text.split('\n')[0], 'ok');
  for (const m of v.appoint_events || []) toast(`📅 ${m}`, 'ok');
  if (v.closed) toast(v.closed.text, 'ok');
  for (const w of v.workplace || []) toast(`🏪 ${w}`, 'ok');
  if (v.shop_done) { toast(v.shop_done.nothing ? `🛍 ${v.shop_done.label}で買うものはなかった` : `🛍 ${v.shop_done.label}で買い物を終えた（${yen(v.shop_done.total)}）`, 'ok'); if (S.ui.callSound !== false) chime(); }
  for (const m of v.replies || []) toast(`📱 ${m.name}から返信: ${m.text.replace(/\n.*/s, '').slice(0, 60)}`, 'ok');
  // そばにいる顔ぶれが変わったら, ステージは描き直す (一人なら何も出さない)
  const who = (v.company || []).map((c) => c.id).join(',');
  if (S.lastCompany !== undefined && S.lastCompany !== who) { S.current = null; clearStage(); }
  if (S.lastCompany !== who && S.tab !== 'with' && v.target && S.lastCompany !== undefined) showTab('with');
  S.lastCompany = who;
  renderTop();
  renderStageMode();
  renderAway();
  renderApproach();
  renderRequest();
  renderEncounter();
  renderStreet();
  renderOffline();
  const cb = $('#chat-badge');
  cb.hidden = !v.chat_unread;
  cb.textContent = v.chat_unread > 99 ? '99+' : String(v.chat_unread || '');
  const tb = $('#task-chat-badge');      // 内職の画面の 📱 (内職中も届いたメッセージが分かるように)
  tb.hidden = cb.hidden;
  tb.textContent = cb.textContent;
  if (S.chatDlg && S.chatDlg.open) drawChat();
  renderTabs();
  renderSoloTab();
  renderWith();
  renderMoney();
  renderItems();
  renderPeople();
  renderLog();
  if (T()) {
    const last = v.log.find((e) => e.who === tid() && !e.mine);
    if (!S.current && last) showEntry(last, false);
    if (!S.current && !last) showGreeting();
    showAutoEntry();
  }
}

function showGreeting() {
  const t = T();
  if (!t) return;
  setDialogue(t.bond && t.bond.mode === 'home' ? `（${t.name}がいる。右の「誰かと」から話しかけてみよう）` : `（${t.name}と一緒にいる）`, false);
}

/* ---------------------------------------------------------------- clock */
function tickClock() {
  const d = new Date();
  $('#clock-hm').textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  $('#clock-s').textContent = ':' + pad(d.getSeconds());
  $('#clock-date').textContent = `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} (${DOW[d.getDay()]})`;
  const t = T();
  if (t && t.override_until) {
    const rest = Math.max(0, Math.round(t.override_until - Date.now() / 1000));
    const el = $('#ov-rest');
    if (el) el.textContent = rest > 0 ? `あと${Math.ceil(rest / 60)}分` : '';
    if (rest === 0 && !S.ovRefresh) { S.ovRefresh = true; refresh().finally(() => { S.ovRefresh = false; }); }
  }
  updateGenBadge();
  const aps = (S.view && S.view.approaches) || [];
  if (aps.length) {
    for (const ap of aps) {
      const rest = Math.max(0, Math.round(ap.until - Date.now() / 1000));
      const el = document.getElementById('ap-rest-' + ap.cid);
      if (el) el.textContent = `（あと${Math.ceil(rest / 60)}分）`;
      if (rest === 0 && !S.apRefresh) { S.apRefresh = true; refresh().finally(() => { S.apRefresh = false; }); }
    }
  }
}

/* ---------------------------------------------------------------- top bar / stage */
function moodFace(p, sc) {
  if (sc && sc.asleep) return '😴';
  if (sc && sc.away) return '🚶';
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
function renderTop() {
  const v = S.view;
  $('#phase-chip').textContent = v.phase.label || '—';
  const wx = (v.outdoor || {}).weather;
  $('#weather-chip').textContent = wx ? `${wx.icon} ${wx.label}` : '';
  // 誰と暮らしているか・家の様子
  const live = (v.people || []).find((p) => p.stage === 'live');
  const hm = v.home || {};
  const hc = $('#home-chip');
  hc.textContent = `🏠 ${live ? live.name + 'と同居' : '一人暮らし'}${hm.label ? '・' + hm.label : ''}`;
  hc.title = `${live ? live.name + 'と暮らしている' : '誰とも暮らしていない（一人暮らし）'}。家は「${hm.label || '—'}」（クリックで家の様子）`;
  hc.dataset.level = String(hm.level ?? '');
  if (S.homeDlg && S.homeDlg.open) drawHome();
  // いまそばにいる人 (いなければ, そうはっきり書く)
  const comp = v.company || [];
  const nc = $('#near-chip');
  nc.textContent = comp.length ? `👥 ${comp.map((c) => c.name).join('・')}` : '🧍 いまは一人';
  nc.title = comp.length ? 'いまそばにいる: ' + comp.map((c) => `${c.name}（${c.label}）`).join('、') : 'いまそばには誰もいない';
  nc.classList.toggle('alone', !comp.length);
}

// 一人のとき (誰もそばにいないとき), ステージ (画像と会話欄) には何も出さない. 画像は常にキャラクターのものだけ
function renderStageMode() {
  const alone = !T();
  $('#stage').classList.toggle('alone', alone);
  const t = T();
  const sc = t && t.scene;
  $('#scene-chip').textContent = t ? `${sc.location ? '📍' + sc.location + '　' : ''}${t.name}: ${sc.label || ''}` : '';
}
function clearStage() {
  if (S.typing) { clearInterval(S.typing); S.typing = null; }
  const img = $('#stage-img'); img.removeAttribute('src'); delete img.dataset.rel; img.classList.remove('show');
  $('#stage-bg').style.backgroundImage = '';
  $('#dtext').textContent = ''; $('#nameplate').textContent = ''; $('#dtime').textContent = ''; $('#deltas').replaceChildren();
}

/* ---------------------------------------------------------------- tabs */
function showTab(tab) {
  if (tab === 'with' && !T()) tab = 'solo';
  S.tab = tab;
  $$('#tabs button').forEach((x) => x.classList.toggle('on', x.dataset.tab === tab));
  for (const t of ['solo', 'with', 'money', 'items', 'people', 'log']) $('#tab-' + t).hidden = t !== tab;
}
function showSub(sub) {
  S.sub = sub;
  $$('#subtabs button').forEach((x) => x.classList.toggle('on', x.dataset.sub === sub));
  for (const t of ['commands', 'dress', 'games', 'status', 'wmoney']) $('#tab-' + t).hidden = t !== sub;
}
function renderTabs() {
  const wb = $('#tabs button[data-tab="with"]');
  const comp = S.view.company || [];
  wb.hidden = !comp.length;           // そばに誰もいなければ「誰かと」は出さない
  wb.textContent = comp.length === 1 ? `${comp[0].name}と` : '誰かと';
  if (S.tab === 'with' && !comp.length) showTab('solo');
  else showTab(S.tab);
  const aps = S.view.approaches || [];
  $('#tabs button[data-tab="people"]').classList.toggle('dot', aps.some((a) => a.apart));
}

/* ---------------------------------------------------------------- commands */
// 「何を、誰と（あるいは一人で）するか」: 「一人で」タブと「誰かと」タブ（相手はそばにいる人から選ぶ）
const isSoloAction = (a) => a.category === 'あなたの予定' || a.id === 'side_job';
const isMoneyAction = (a) => a.category === 'お金' && a.id !== 'side_job';     // 相手とのお金のやりとり (「誰かと」の「お金のこと」)
function cmdButton(a) {
  const st = T().available[a.id];
  const tip = [a.when ? '条件: ' + a.when : '', S.ui.deltas !== false && a.effects && Object.keys(a.effects).length ?
    '効果: ' + Object.entries(a.effects).map(([k, v]) => `${pname(k)}${v > 0 ? '+' : ''}${v}`).join(' ') : '',
    st.cooldown ? `連続実行で効果減 (あと${Math.ceil(st.cooldown / 60)}分)` : ''].filter(Boolean).join('\n');
  const od = (S.view.outdoor || {}).places || {};
  const pl = a.override && a.override.outing && a.override.place ? od[a.override.place] : null;    // お出かけの行き先 (表から)
  const why = (S.view.blocked || {})[isMoneyAction(a) || a.category !== 'system' ? 'social' : ''];
  return h('button', { class: 'cmd', disabled: !st.ok || S.busy || !!why, title: [why, tip, pl ? `行き先: ${(a.places || []).length > 1 ? '選べます' : pl.label}` : ''].filter(Boolean).join('\n'),
    onclick: () => (['gift', 'expensive_gift'].includes(a.id) ? giftPicker(a.id)
      : (a.places || []).length > 1 ? pickPlace(a) : (!a.confirm || confirm(a.confirm)) && doAct(a.id)) },
    h('span', { class: 'ic' }, a.icon || '•'), h('span', {}, a.name),
    pl && !((a.places || []).length > 1) ? h('small', { class: 'muted' }, pl.open === false ? `${pl.label}・${pl.note}` : pl.label) : null,
    st.cooldown ? h('span', { class: 'cd' }, '♻') : null);
}

// 「一人で」: 一人の行動 (休む・家事・研鑽・日記・外出・仕事・内職・寝る など) と スマホ. 下に, あなたの体力とスキル
function renderSoloTab() {
  const v = S.view, so = v.solo || {}, Y = v.you || {};
  const free = (v.presence || {}).mode === 'none';
  const btn = (icon, label, onclick, tip, dis) => h('button', { class: 'cmd', disabled: !free || S.busy || dis || !!(v.blocked || {}).solo,
    title: (v.blocked || {}).solo || tip || '', onclick },
    h('span', { class: 'ic' }, icon), h('span', {}, label));
  const kinds = (so.kinds || []).map((k) => k.id === 'chores'
    ? btn(k.icon, k.label, () => { S.choresOpen = !S.choresOpen; renderSoloTab(); }, '片付け（戻るまで）か、家計簿をつける（15分ほど）を選ぶ')
    : k.id === 'practice'
    ? btn(k.icon, k.label, () => { S.practiceOpen = !S.practiceOpen; renderSoloTab(); }, '会話・スキンシップ・料理・仕事のどれかを練習する（戻るまで）')
    : OD_CHOICES()[k.id] ? btn(k.icon, k.label, () => { S.placeFor = S.placeFor === k.id ? null : k.id; renderSoloTab(); },
      '行き先を選んで出かける。画面を開いているあいだだけ（閉じたら家に帰る）。偶然の出会いはその間に')
      : btn(k.icon, k.label, () => soloStart(k.id), '家で、戻るまで'));
  const pres = v.presence || {};
  const busyNow = pres.mode === 'busy' ? h('div', { class: 'solo-now' },
    h('span', {}, pres.solo ? `${pres.solo.icon} ${pres.solo.label}…` : '🖥 作業中…'),
    h('span', { class: 'muted small' }, '終えると、過ごした時間で結果が出ます'),
    h('button', { class: 'btn primary small', disabled: S.busy, onclick: comeBack }, pres.solo ? `${pres.solo.label.replace(/中$/, '')}を終える` : '作業を終える')) : null;
  const near = so.near;
  const sj = v.side_job;
  const bl = (v.blocked || {}).solo;
  $('#tab-solo').replaceChildren(...[
    busyNow,
    bl && !busyNow ? h('div', { class: 'blocked-note' }, `⏸ ${bl}`) : null,
    h('div', { class: 'cat solo' },
      h('div', { class: 'cat-title' }, near ? `一人で（${near.name}には告げてから）` : '一人で'),
      h('div', { class: 'cmds' }, ...kinds,
        h('button', { class: 'cmd', disabled: S.busy, title: '自炊・外食・買って食べる・買ってきたものを食べる', onclick: openMeal },
          h('span', { class: 'ic' }, '🍚'), h('span', {}, '食べる'), (v.meal || {}).satiety_low ? h('small', { class: 'muted' }, (v.meal || {}).hunger) : null),
        h('button', { class: 'cmd', disabled: S.busy, title: '今日の出来事から日記をつける（読み返しもここから）', onclick: openDiary },
          h('span', { class: 'ic' }, '📓'), h('span', {}, so.diary_today ? '日記（今日の分あり）' : '日記をつける')),
        // 作業する・仕事に行く・寝る・席を外す: そばに誰かいれば「〜してくるね」と告げる形、いなければ一人で
        ...(so.plain || []).map((p) => btn(p.icon, p.label, () => soloStart(p.id), near ? `${near.name}に告げてから` : '告げる相手はいない（一人で）', !p.ok)),
        h('button', { class: 'cmd', disabled: S.busy || !!sj, onclick: openTask,
          title: '家でパズル（マインスイーパ・数独・ピクロス・スリザーリンク・15パズル）を解いて稼ぎます' },
          h('span', { class: 'ic' }, '🧵'), h('span', {}, '内職する'), sj ? h('small', { class: 'muted' }, sj.reason.replace(/^.*（(.*)）$/, '$1')) : null))),
    S.placeFor && free ? h('div', { class: 'cmds', style: 'margin-bottom:10px' },
      h('div', { class: 'muted small', style: 'grid-column:1/-1' }, '行き先（行き先しだいで、することが決まります。人の多さは時間帯と天気しだい）'),
      ...placeGroups(OD_CHOICES()[S.placeFor], (pl) => { const P = (S.view.outdoor.places || {})[pl] || {};
        if (P.open === false) return h('button', { class: 'cmd', disabled: true, title: `${P.label}は閉まっています（${P.hours}）` },
          h('span', { class: 'ic' }, P.icon || '📍'), h('span', {}, P.label || pl), h('small', { class: 'muted' }, P.note));
        return btn(P.icon || '📍', P.label || pl, () => { const k = S.placeFor; S.placeFor = null; soloStart(k, null, pl); }, placeTip(pl)); })) : null,
    S.choresOpen && free ? h('div', { class: 'cmds', style: 'margin-bottom:10px' },
      btn('🧹', '片付け', () => { S.choresOpen = false; soloStart('chores'); }, '散らかり・洗い物・洗濯物・ゴミを片付ける（戻るまで。洗剤があるとはかどる）'),
      btn('📒', '家計簿をつける', () => { S.choresOpen = false; soloStart('kakeibo'); }, '前につけたときから今までのお金の出入りを書き込む（15分ほど）。日を空けるほど、うろ覚えになる')) : null,
    S.practiceOpen && free ? h('div', { class: 'cmds', style: 'margin-bottom:10px' },
      Object.entries(so.skills || {}).map(([id, label]) => btn('📚', `${label}の練習`, () => { S.practiceOpen = false; soloStart('practice', id); }))) : null,
    (v.appoints || []).some((x) => x.status === 'set' || x.status === 'waiting') ? h('div', { class: 'cat' },
      h('div', { class: 'cat-title' }, '約束（自分でその場所へ出向く）'),
      (v.appoints || []).filter((x) => x.status === 'set' || x.status === 'waiting').map((x) => appointLine(x, true))) : null,
    planSection(v),
    h('div', { class: 'cat' }, h('div', { class: 'cat-title' }, 'スマホ'),
      h('div', { class: 'cmds' }, h('button', { class: 'cmd', disabled: S.busy, onclick: () => openChat(), title: '連絡先の人を選んで、メッセージの種類か電話を選ぶ（誰かといるときも使えます）' },
        h('span', { class: 'ic' }, '📱'), h('span', {}, 'スマホを見る'), v.chat_unread ? h('small', { class: 'muted' }, `未読 ${v.chat_unread}`) : null))),
    h('div', { class: 'pgroup' }, h('h4', {}, 'あなた'),
      h('div', { class: 'muted small', style: 'margin-bottom:4px' }, `いま: ${(v.presence || {}).label || '—'}${near ? `（そばに${(v.company || []).map((c) => c.name).join('・')}）` : '（一人）'}`),
      v.meal && v.meal.health && v.meal.health.level ? h('div', { class: 'health-now lv' + v.meal.health.level },
        h('span', {}, `🤒 ${v.meal.health.word}`), v.meal.health.med ? h('span', { class: 'muted small' }, '（薬を飲んだ）') : '',
        h('div', { class: 'row', style: 'gap:6px;margin-top:4px' },
          h('button', { class: 'btn small', disabled: S.busy || !v.meal.health.medicine, title: v.meal.health.medicine ? `風邪薬 ×${v.meal.health.medicine}` : '風邪薬を持っていない（ドラッグストア・コンビニで買える）',
            onclick: takeMedicine }, `💊 薬を飲む${v.meal.health.medicine ? '' : '（なし）'}`),
          h('span', { class: 'muted small' }, v.meal.health.level >= 3 ? '病院は「外出」の行き先から（営業時間あり・お金がかかる）' : '休めば治ることも。こじらせることも'))) : '',
      v.meal && v.meal.health && v.meal.health.exercise ? h('div', { class: 'small', style: 'margin-bottom:4px' }, `🏃 ${v.meal.health.exercise}`,
        v.meal.health.cap < 100 ? h('span', { class: 'muted' }, `（体力の上限 ${v.meal.health.cap}）`) : '') : '',
      v.meal ? h('div', { class: 'small', style: 'margin-bottom:4px' }, `🍚 ${v.meal.hunger}`, ...(v.meal.nutri || []).map((x) => h('span', { class: 'muted' }, `・${x}`)),
        v.meal.last ? h('span', { class: 'muted' }, `（最後に食べたのは ${fmtTime(v.meal.last.t)} の${v.meal.last.label}）`) : '') : '',
      h('div', { class: 'prow', title: '仕事・内職・外出・家事で減り、時間で戻ります（寝ると早い）。減っていると、構っても効きが悪くなります' },
        h('span', {}, '体力'),
        h('div', { class: 'bar' }, h('i', { style: `width:${Y.stamina ?? 100}%;background:${(Y.stamina ?? 100) >= 50 ? 'var(--good)' : (Y.stamina ?? 100) >= 20 ? 'var(--mid)' : 'var(--bad)'}` })),
        h('span', { class: 'pval' }, Math.floor(Y.stamina ?? 100))),
      Object.entries(Y.skills || {}).map(([k, val]) => h('div', { class: 'prow', title: SKILL_HINT[k] || '' },
        h('span', { title: (Y.rusty || []).includes(k) ? 'しばらく使っていないので、鈍ってきた（使えば元の高さまでは戻りやすい）' : '' }, `${SKILL_NAME[k] || k}${(Y.rusty || []).includes(k) ? '（鈍り）' : ''}`),
        h('div', { class: 'bar' }, h('i', { style: `width:${val}%;background:var(--sky)` })),
        h('span', { class: 'pval' }, Math.floor(val)))))].filter(Boolean));
}

const OD_CHOICES = () => (S.view && S.view.outdoor && S.view.outdoor.choices) || {};
// 行き先を分類 (近所・お店・遊びに・家) ごとに並べる
function placeGroups(ids, mk) {
  const od = (S.view || {}).outdoor || {};
  const P = od.places || {}, G = od.groups || {};
  const by = {};
  for (const id of ids) (by[(P[id] || {}).group || 'near'] = by[(P[id] || {}).group || 'near'] || []).push(id);
  return Object.keys(G).filter((g) => by[g]).flatMap((g) => [h('div', { class: 'muted small', style: 'grid-column:1/-1;margin-top:2px' }, G[g]), ...by[g].map(mk)]);
}
function placeTip(id) {
  const od = (S.view || {}).outdoor || {};
  const p = (od.places || {})[id] || {};
  return [(p.does || []).map((d) => (od.does || {})[d] || d).join('・'), p.hours && p.hours !== '24時間' ? `営業 ${p.hours}` : ''].filter(Boolean).join('\n');
}
// 行き先を選べるお出かけ (散歩・買い物・デートなど): 表の行き先から選んで誘う
function pickPlace(a) {
  const od = (S.view || {}).outdoor || {};
  const dlg = h('dialog', { class: 'modal', style: 'width:min(480px,94vw);height:auto' });
  const close = () => { dlg.close(); dlg.remove(); };
  dlg.append(h('div', { style: 'padding:14px' },
    h('div', { class: 'row' }, h('b', {}, `${a.icon || ''} ${a.name}: 行き先`), h('div', { class: 'spacer' }), h('button', { class: 'btn ghost small', onclick: close }, '✕')),
    h('div', { class: 'cmds', style: 'margin-top:8px' }, ...placeGroups(a.places, (id) => {
      const p = (od.places || {})[id] || {};
      return h('button', { class: 'cmd', disabled: p.open === false, title: placeTip(id), onclick: () => { close(); doAct(a.id, undefined, id); } },
        h('span', { class: 'ic' }, p.icon || '📍'), h('span', {}, p.label || id), p.open === false ? h('small', { class: 'muted' }, p.note) : null);
    }))));
  document.body.append(dlg);
  dlg.showModal();
}
async function soloStart(kind, skill, place) {
  if (S.busy) return;
  S.busy = true;
  try {
    const r = await api('/api/solo/start', withT({ kind, skill, place }));
    if (r.act) handleActResult(r.act); else toast(r.done || `${r.label}…`, 'ok');
  } catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await refresh(); }
}

async function takeMedicine() {
  if (S.busy) return;
  S.busy = true;
  try { toast((await api('/api/medicine', {})).text, 'ok'); } catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await refresh(); }
}

// 食べる: 自炊 (持ち物の食材・料理スキルで作れる献立) / 買ってきたもの / いる行き先で外食・買って食べる
function openMeal() {
  const dlg = h('dialog', { class: 'modal', style: 'width:min(560px,94vw);height:auto;max-height:88vh;overflow:auto' });
  const close = () => { dlg.close(); dlg.remove(); };
  const eat = async (how, id) => {
    if (S.busy) return;
    S.busy = true;
    try { const r = await api('/api/meal', { how, id }); toast(r.meal.text, 'ok'); close(); } catch (e) { toast(e.message, 'err'); }
    finally { S.busy = false; await refresh(); }
  };
  const M = S.view.meal || {};
  const NU = { staple: '主食', protein: 'たんぱく質', veg: '野菜' };
  const row = (label, sub, btn) => h('div', { class: 'row item-row' }, h('div', { style: 'flex:1' }, label, sub ? h('div', { class: 'muted small' }, sub) : ''), btn);
  dlg.append(h('div', { style: 'padding:16px' },
    h('div', { class: 'row' }, h('h3', { style: 'margin:0' }, '🍚 食べる'), h('div', { class: 'spacer' }), h('button', { class: 'btn ghost small', onclick: close }, '✕')),
    h('p', { class: 'muted small' }, `${M.hunger || ''}${(M.nutri || []).length ? '。' + M.nutri.join('。') : ''}`),
    M.place ? h('div', { class: 'pgroup' }, h('h4', {}, `${M.place_label}で`),
      (M.menu || []).length ? M.menu.map((m) => row(`${m.name}　${yen(m.price)}前後`, Object.entries(m.nutri).filter(([, v]) => v >= 6).map(([k]) => NU[k]).join('・') || '軽め',
        h('button', { class: 'btn small primary', disabled: S.busy, onclick: () => eat('out', m.id) }, '食べる')))
        : h('p', { class: 'muted small' }, 'ここでは食べられません（閉まっているか、食べるところがない）')) : '',
    M.home ? h('div', { class: 'pgroup' }, h('h4', {}, '自炊（持ち物の食材を使う）'),
      (S.view.blocked || {}).cook ? h('div', { class: 'blocked-note' }, `⏸ ${S.view.blocked.cook}`) : '',
      (M.dishes || []).map((d) => row(d.name, `${d.need.join('・')}${d.ok ? '' : '　— ' + d.why}`,
        h('button', { class: 'btn small', disabled: S.busy || !d.ok || !!(S.view.blocked || {}).cook, onclick: () => eat('cook', d.id) }, '作って食べる'))),
      h('p', { class: 'hint' }, '料理スキルが上がると作れる献立が増え、主食・たんぱく質・野菜がそろいやすくなります。食材は買い物（買うものリスト）で。')) : '',
    M.home && (M.items || []).length ? h('div', { class: 'pgroup' }, h('h4', {}, '買ってきたもの'),
      M.items.map((x) => row(`${x.name} ×${x.count}`, '', h('button', { class: 'btn small', disabled: S.busy, onclick: () => eat('item', x.id) }, '食べる')))) : '',
    !M.home && !M.place ? h('p', { class: 'muted' }, 'いまは食べられるところにいません。') : ''));
  document.body.append(dlg);
  dlg.showModal();
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

/* ---------------------------------------------------------------- 誰かと */
// そばにいる人とすること. 複数人いれば, 相手をプルダウンで選ぶ (いまは一人に向けた行動だけ)
async function setTarget(id) {
  if (S.busy || id === tid()) return;
  try { await api('/api/target', { id }); } catch (e) { toast(e.message, 'err'); }
  S.view.target = id;
  S.current = null; clearStage();
  await refresh();
}
function renderWith() {
  const t = T();
  if (!t) {           // 誰もそばにいない: 中身も空に
    $('#with-card').replaceChildren();
    for (const id of ['commands', 'dress', 'games', 'status', 'wmoney']) $('#tab-' + id).replaceChildren();
    return;
  }
  const comp = S.view.company || [];
  const sc = t.scene;
  const face = h('div', { class: 'who-face' });
  if (t.face) { face.style.backgroundImage = `url("${imgUrl(t.face)}")`; face.title = moodFace(t.params, sc); } else face.textContent = moodFace(t.params, sc);
  const pick = comp.length > 1
    ? h('select', { class: 'char-select', title: '誰に向けてするか（そばにいる人から）', onchange: (ev) => setTarget(ev.target.value) },
      comp.map((c) => h('option', { value: c.id, selected: c.id === t.character }, `${BOND_IC[c.stage] || ''} ${c.name}`)))
    : h('b', { class: 'who-name' }, t.name);
  $('#with-card').replaceChildren(h('div', { class: 'who' }, face,
    h('div', { class: 'who-body' },
      h('div', { class: 'row', style: 'gap:6px' }, pick, comp.length > 1 ? h('span', { class: 'muted small' }, `と（ほかに ${comp.filter((c) => c.id !== t.character).map((c) => c.name).join('・')}）`) : h('span', { class: 'muted small' }, 'と')),
      h('div', { class: 'who-scene' }, `${sc.label}${sc.location ? '（' + sc.location + '）' : ''}`,
        sc.source === 'override' ? h('span', { class: 'muted', id: 'ov-rest', style: 'margin-left:6px' }) : null),
      h('div', { class: 'tags' },
        h('span', { class: 'tag', style: 'background:#2b2540;color:#d9d0ff' }, moodFace(t.params, sc)),
        t.bond ? h('span', { class: 'tag bond', title: 'あなたとの間柄・いまどこで会っているか' }, `${BOND_IC[t.bond.stage] || ''}${t.bond.stage_label}・${t.bond.label}`) : '',
        t.dress && t.dress.wearing ? h('span', { class: 'tag dress' }, '👗' + t.dress.wearing) : '',
        t.life && t.life.hint ? h('span', { class: 'tag hint', title: '「何かあった？」で聞いてみよう' },
          t.life.hint_mood === 'good' ? '✨うれしそう' : '💭何かあったみたい') : '',
        ...t.tags.map((x) => h('span', { class: 'tag' }, x.label))))));
  showSub(S.sub);
  renderCommands();
  renderDress();
  renderGames();
  const gw = (S.view.blocked || {}).game;
  if (gw && !(t.games || {}).current) {
    $('#tab-games').prepend(h('div', { class: 'blocked-note' }, `⏸ ${gw}`));
    $$('#tab-games button').forEach((b) => { b.disabled = true; b.title = gw; });
  }
  renderStatus();
  renderWMoney();
}

function renderCommands() {
  const t = T();
  const box = $('#tab-commands');
  if (!t) { box.replaceChildren(); return; }
  const av = t.available;
  const cats = new Map();
  let hidden = 0;
  for (const a of S.boot.actions) {
    if (a.category === 'system' || !av[a.id] || isSoloAction(a) || isMoneyAction(a) || a.category === '連絡') continue;
    if (!av[a.id].ok && !S.showHidden) { hidden++; continue; }
    if (!cats.has(a.category)) cats.set(a.category, []);
    cats.get(a.category).push(a);
  }
  const out = [];
  const why = (S.view.blocked || {}).social;
  if (why) out.push(h('div', { class: 'blocked-note' }, `⏸ ${why}`));
  for (const [cat, list] of cats) {
    out.push(h('div', { class: 'cat' },
      h('div', { class: 'cat-title' }, cat || 'その他'),
      h('div', { class: 'cmds' }, list.map(cmdButton))));
  }
  if (!cats.size) out.push(h('p', { class: 'muted' }, '今できることはなさそうだ…'));
  out.push(h('button', { class: 'cmds-hidden-toggle', onclick: () => { S.showHidden = !S.showHidden; renderCommands(); } },
    S.showHidden ? '▲ 今できないコマンドを隠す' : `▼ 今できないコマンドも表示 (${hidden})`));
  box.replaceChildren(...out);
}

// 相手とのお金のやりとり: お小遣い・お金を借りる・高価なプレゼント, お出かけ代と生活費の取り決め, 借りているお金を返す
function renderWMoney() {
  const t = T();
  const box = $('#tab-wmoney');
  if (!t) { box.replaceChildren(); return; }
  const L = t.life || {};
  const Y = S.view.you || {};
  const policy = (key, opts) => h('select', { onchange: async (ev) => {
    try {
      const c = clone((await api('/api/character?id=' + encodeURIComponent(t.character))).character);
      c[key] = ev.target.value;
      await api('/api/character/save', { data: c }); await loadBoot(); await refresh();
    } catch (e) { toast(e.message, 'err'); }
  } }, opts.map(([k, l]) => h('option', { value: k, selected: L[key] === k }, l)));
  const acts = S.boot.actions.filter((a) => isMoneyAction(a) && t.available[a.id]);
  box.replaceChildren(
    h('div', { class: 'pgroup money-box' }, h('h4', {}, `${t.name}とのお金`),
      h('div', { class: 'money-row' }, h('span', {}, 'あなたの手元'), h('b', {}, yen(Y.my_money || 0))),
      h('div', { class: 'money-row' }, h('span', {}, 'お出かけ代'),
        policy('pay_policy', [['auto', 'おまかせ'], ['me', 'あなたが払う'], ['split', '割り勘'], ['her', 'おごってもらう']])),
      L.living ? h('div', { class: 'money-row', title: 'あなたの家の毎日の生活費と、月はじめの家賃・光熱費・通信費の分け方' }, h('span', {}, '生活費・家賃'),
        policy('living_policy', [['split', '折半'], ['me', 'あなたが払う'], ['her', `${t.name}が払う`]])) : '',
      L.owed ? h('div', { class: 'money-row' }, h('span', {}, `${t.name}に借りている`), h('b', { class: 'down' }, yen(L.owed)),
        h('button', { class: 'btn small', disabled: S.busy || !(Y.my_money > 0), onclick: () => repay(t.character, L.owed, t.name) }, '返す')) : '',
      h('p', { class: 'hint' }, `${t.name}の所持金は分かりません。困っているかどうかは、おねだりや会話からにじみます。`)),
    acts.length ? h('div', { class: 'cat' }, h('div', { class: 'cat-title' }, 'やりとり'),
      h('div', { class: 'cmds' }, acts.filter((a) => t.available[a.id].ok || S.showHidden).map(cmdButton))) : '');
}

/* ---------------------------------------------------------------- dress tab */
function renderDress() {
  const t = T();
  if (!t) { $('#tab-dress').replaceChildren(); return; }
  const d = t.dress;
  const items = t.wardrobe || [];
  const card = (id, icon, name, ok, tip) => h('button', {
    class: 'outfit' + (d.current === id ? ' on' : ''), disabled: !d.can || !ok || S.busy,
    title: tip || '', onclick: () => doAct('_dress', id),
  }, h('span', { class: 'ic' }, icon), h('span', {}, name));
  $('#tab-dress').replaceChildren(
    h('div', { class: 'dress-now' },
      h('div', {}, h('b', {}, 'いまの服 '), d.wearing || 'おまかせ（スケジュール通り）', d.self ? h('span', { class: 'muted small' }, '（本人が選んだ服）') : ''),
      h('div', {}, h('code', {}, d.outfit || '—')),
      d.fixed ? h('div', { class: 'muted small' }, '※ 今の場面は服装固定（就寝中など）なので、着せ替えは場面が変わってから反映されます') : '',
      !d.can ? h('div', { class: 'muted small' }, `今は着替えられません（${d.why}）`) : ''),
    h('div', { class: 'outfits' },
      card('', '🔄', 'おまかせ', true, 'スケジュール通りの服に戻す'),
      items.map((o) => card(o.id, o.icon || '👕', (o.name || o.id) + boldMark(o.bold), d.items[o.id],
        (o.when ? '条件: ' + o.when + ' / ' : '') + (o.bold ? `大胆さ ${o.bold}（着てくれるかは仲・気分・性格しだい）` : o.pos)))),
    items.length ? '' : h('p', { class: 'muted small' }, '持っている服がありません。店で服を買って贈るか、設定 → キャラクター → 着せ替え で持たせられます。'),
    h('p', { class: 'hint', style: 'margin-top:12px' }, t.dress_reset_on_sleep !== false
      ? '着せ替えた服は、寝るとスケジュール通りの服に戻ります。' : '着せ替えた服は「おまかせ」を選ぶまで続きます。'),
    ...poseSections(t),
  );
}

// ポーズを取って / 見せて (大人のキャラだけ. 断られることもある. 頼んだものは相手が好みとして覚える)
function poseSections(t) {
  const ps = t.posing;
  if (!ps) return [];
  if (!ps.can) return [h('div', { class: 'sect' }, '📸 ポーズ・見せて'), h('p', { class: 'muted small' }, ps.why)];
  return [['pose', '_pose', '📸 ポーズを取って'], ['show', '_show', '👀 見せて']].map(([typ, aid, title]) => h('div', {},
    h('div', { class: 'sect' }, title),
    h('div', { class: 'outfits' }, ps.items.filter((o) => o.type === typ).map((o) => h('button', {
      class: 'outfit', disabled: S.busy || !o.here, title: o.here ? (o.bold ? `大胆さ ${o.bold}（受けてくれるかは仲・気分・性格・場所しだい）` : o.pos) : '外では頼めません',
      onclick: () => doPose(aid, o.id) }, h('span', { class: 'ic' }, o.icon || '📸'), h('span', {}, o.name + boldMark(o.bold)))))));
}
async function doPose(aid, pid) {
  if (S.busy) return;
  S.busy = true;
  try { handleActResult(await api('/api/act', withT({ action: aid, pose: pid }))); }
  catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await refresh(); }
}

/* ---------------------------------------------------------------- games tab */
// ミニゲームの画面 (renderGames など) は static/minigames.js (単独版 minigame_lab と同じもの)

async function gameAct(path, body) {
  if (S.busy) return;
  S.busy = true;
  renderGames();
  try {
    const r = await api(path, withT(body));
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

async function doAct(aid, outfit, place) {
  if (S.busy) return;
  S.busy = true;
  renderCommands();
  try {
    const r = outfit === undefined ? await api('/api/act', withT(place ? { action: aid, place } : { action: aid })) : await api('/api/dress', withT({ outfit }));
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
  if (!r.entry) return;
  S.lastDeltas = r.entry.deltas || {};
  if (r.job) trackJob(r.job);
  // 一人のとき (誰もそばにいない) はステージに何も出さない: 結果は知らせとログで
  if (r.entry.mine || !r.entry.who && !tid() || r.entry.who && r.entry.who !== tid() && !(S.view.company || []).some((c) => c.id === r.entry.who)) {
    if (r.entry.text && !r.solo) toast(r.entry.text.replace(/\n.*/s, ''), r.missed ? 'err' : 'ok');
    return;
  }
  showEntry(r.entry, true);
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
const UI_DEFAULT = { pos: 'bottom', alpha: 0.82, font: 17, compact: false, autoHide: 0, deltas: true, stats: 'exact', showApart: false, callSound: true,
  callRemind: true, vibrate: true, browserNotify: false };
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
  $('#nameplate').textContent = narr ? 'ナレーション' : (name || (T() || {}).name || '');
  const el = $('#dtext');
  if (S.typing) { clearInterval(S.typing); S.typing = null; }
  if (!animate) { el.textContent = text; return; }
  let i = 0;
  const chars = [...text];
  el.replaceChildren('', h('span', { class: 'caret' }));
  S.typing = setInterval(() => {
    i++;
    if (!el.firstChild) { clearInterval(S.typing); S.typing = null; return; }     // 途中でステージを片付けた
    el.firstChild.textContent = chars.slice(0, i).join('');
    if (i >= chars.length) { clearInterval(S.typing); S.typing = null; el.textContent = text; }
  }, 28);
  S.typingText = text;
}

function showEntry(e, animate) {
  if (!T()) { if (e.image) openLightbox(e, { path: e.image, seed: e.seed, pos: e.pos, neg: e.neg, t: e.t }); return; }   // 一人のときはステージを使わない
  S.current = e;
  setDialogue(e.text || `（${e.action_name}）`, animate, e.who_name || cname(e.who));
  $('#dtime').textContent = `${fmtTime(e.t)}・${e.icon || ''}${e.action_name}${e.text_src === 'llm' ? '・LLM' : ''}`
    + (e.reused ? `・既存${e.same_prompt || ''}枚から表示${e.job ? '（新規生成中）' : e.busy_skip ? '（生成中のため新規生成なし）' : ''}` : '');
  $('#deltas').replaceChildren(...Object.entries(S.ui.deltas === false ? {} : (e.deltas || {})).map(([k, v]) => {
    const p = S.boot.params.find((x) => x.id === k) || {};
    const cls = p.neutral ? '' : ((v > 0) !== !!p.invert ? 'up' : 'down');
    return h('span', { class: 'delta ' + cls }, `${pname(k)} ${v > 0 ? '+' : ''}${v}`);
  }), ...Object.entries(e.money || {}).map(([k, v]) => h('span', { class: 'delta money ' + (v > 0 ? 'up' : 'down') },
    `${k === 'p' ? 'あなた' : e.who_name || cname(e.who)} ${v > 0 ? '+' : ''}${yen(v)}`)),
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
      if (j.kind === 'icon') { /* 顔のアイコン: ステージの画像は変えない */ }
      else if (S.current && S.current.id === j.entry) { S.current.image = j.image; setImage(j.image); }
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

const SKILL_NAME = { talk: '会話', touch: 'スキンシップ', cook: '料理', work: '仕事', house: '家事', care: '気配り', groom: '身だしなみ', budget: 'やりくり', write: '文章' };
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
  const req = T() && T().life && T().life.request;      // おねがいは, そばにいるときに言われる
  if (!req) { box.hidden = true; return; }
  const name = T().name;
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
      if (r.registered) { toast(`${r.registered.name}を登録しました（スマホから連絡できます）`, 'ok'); await loadBoot(); }
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

/* ---- スマホ: 外出中・仕事中・一人の時間・誰かといるときでも, そばにいない相手にメッセージ・電話できる (トーク一覧から).
   メッセージの返信は相手の状況しだいで遅れる/来ない. 電話は出ないことも (あとで折り返しが来ることも) */
function phonePanel() {
  if (!(S.view.contacts || []).length) return '';
  return h('div', { class: 'phone-panel' }, h('button', { class: 'btn small', onclick: () => openChat() },
    `📱 スマホを見る${S.view.chat_unread ? `（未読 ${S.view.chat_unread}）` : ''}`));
}

/* ---- 持ち物: 持っている品物・買うものリスト・品物の一覧 (どの店で売っているか) */
const PLACE_LABEL = (id) => ((S.view.outdoor || {}).places || {})[id] ? `${S.view.outdoor.places[id].icon}${S.view.outdoor.places[id].label}` : id;
function renderItems() {
  const box = $('#tab-items');
  const iv = S.view.items || { items: [], shop_list: [] };
  const cat = (S.boot.catalog || {}).items || [];
  const want = Object.fromEntries(iv.shop_list.map((x) => [x.id, x.want]));
  const setWant = async (id, qty) => { try { await api('/api/items/list', { id, qty }); await refresh(); } catch (e) { toast(e.message, 'err'); } };
  const t = T();
  const canGive = !!(t && (t.available.gift || {}).ok);   // いま目の前にいて, 受け取れる状態か
  box.replaceChildren(
    h('div', { class: 'pgroup' }, h('h4', {}, '🎒 持ち物'),
      iv.items.length ? iv.items.map((it) => h('div', { class: 'row item-row' },
        h('span', { style: 'flex:1' }, `${it.icon} ${it.name} ×${it.count}${it.nut ? '回分' : ''}`),
        it.giftable && canGive ? h('button', { class: 'btn small', disabled: S.busy, title: `${t.name}に渡す`,
          onclick: () => giveItem(it.id, t.character) }, `🎁 ${t.name}に渡す`) : ''))
        : h('p', { class: 'muted small' }, 'なにも持っていない。買うものリストに入れておくと、買い物のときに買ってくる。'),
      h('p', { class: 'hint' }, '料理は食材、お茶はお茶っ葉・コーヒー豆、おやつはお菓子を使います（無ければありあわせで効き目が落ちる）。家事は洗剤があるとはかどり、研鑽はその分野の本があると伸びやすくなります（本は減りません）。')),
    h('div', { class: 'pgroup' }, h('h4', {}, '📝 買うものリスト'),
      h('p', { class: 'hint' }, '買い物（とカフェ）に出たとき、その店で売っていれば買ってきます。品切れや値段の上下があり、お金が足りなければ買えません。リストにない物をつい買うこともあります。'),
      cat.map((it) => h('div', { class: 'row item-row' },
        h('span', { style: 'flex:1;min-width:10em' }, `${it.icon} ${it.name}`, h('span', { class: 'muted small' }, ` ${yen(it.price)}前後${it.servings > 1 ? `（${it.servings}回分）` : ''}・${it.places.map(PLACE_LABEL).join(' ')}`),
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
  dlg.append(h('div', { style: 'padding:16px' }, h('h3', {}, `${T().name}に渡すもの`),
    gifts.map((it) => h('div', { class: 'row item-row' }, h('span', { style: 'flex:1' }, `${it.icon} ${it.name} ×${it.count}`),
      h('button', { class: 'btn small primary', onclick: () => { close(); giveItem(it.id, tid()); } }, '渡す'))),
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
  S.chatSeen = {};                    // 開いたときは一番下から
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
  const listTop = (dlg.querySelector('.chat-list') || {}).scrollTop || 0;
  const prevTop = keepScroll ? keepScroll.scrollTop : 0;      // 描き直す前に (外した要素の位置は 0 になる)
  const atBottom = !keepScroll || keepScroll.scrollTop + keepScroll.clientHeight >= keepScroll.scrollHeight - 30;
  const listEl = h('div', { class: 'chat-list' },
    h('div', { class: 'chat-head' }, h('b', { title: '相手を選んで、メッセージか電話' }, '📱 スマホ'), h('div', { class: 'spacer' }),
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
    for (const x of th.appoints || []) {
      body.push(h('div', { class: 'chat-sys' }, `📅 ${x.when}に${x.place_label}「${x.do_label}」（${x.status_label}）`,
        x.status === 'offered' ? h('span', {}, '　',
          h('button', { class: 'btn small', disabled: S.busy, onclick: () => answerAppoint(x.id, true) }, '行く'), ' ',
          h('button', { class: 'btn small ghost', disabled: S.busy, onclick: () => answerAppoint(x.id, false) }, '断る'), ' ',
          h('button', { class: 'btn small ghost', disabled: S.busy, title: '別の日時（・行き先）を返す。相手の予定や気分しだいで、受けてくれる・断られる・また別の案が返ってくる',
            onclick: () => { S.apForm = { counter: x.id, place: x.place, do: x.do }; drawChat(); } }, '別の日時なら'))
          : (x.status === 'set' || x.status === 'waiting') && !x.here && !x.home_me
            ? h('span', {}, '　', h('button', { class: 'btn small', disabled: S.busy, onclick: () => goAppoint(x.id) }, `🚶 ${x.place_label}へ出かける`)) : ''));
    }
    const can = !th.together;
    threadEl = h('div', { class: 'chat-thread' },
      h('div', { class: 'chat-head' },
        h('button', { class: 'btn ghost small chat-back', onclick: () => { S.chatCid = null; drawChat(); } }, '‹'),
        avatar(th.face, th.name, 'small'), h('b', {}, th.name),
        h('span', { class: 'muted small', style: 'margin-left:8px' }, th.together ? 'そばにいる' : th.promise ? `📅 会う約束（${hhmm(th.promise)}まで）` : ''),
        h('div', { class: 'spacer' }), h('button', { class: 'btn ghost small chat-close', onclick: () => dlg.close() }, '✕')),
      h('div', { class: 'chat-body' }, body.length ? body : h('p', { class: 'muted small', style: 'text-align:center' }, 'まだやりとりはありません')),
      (() => {          // 返事を待たれているメッセージ: ここでも返事を選べる
        const ap = can && (S.view.approaches || []).find((x) => x.cid === th.id && x.choices);
        if (!ap) return '';
        return h('div', { class: 'chat-reply' }, h('div', { class: 'muted small' }, `${ap.icon} 返事を選ぶ（あと${Math.max(1, Math.ceil((ap.until - Date.now() / 1000) / 60))}分）`),
          h('div', { class: 'row', style: 'flex-wrap:wrap;gap:6px' },
            ...ap.choices.map((c) => h('button', { class: 'chat-kind', disabled: S.busy, onclick: async () => { await answerApproach(th.id, 'reply', c.id); S.chatJump = true; drawChat(); } }, c.label)),
            h('button', { class: 'chat-kind ghost', disabled: S.busy, onclick: async () => { await answerApproach(th.id, 'later'); drawChat(); } }, ap.later)));
      })(),
      h('div', { class: 'chat-send' },
        can ? [...th.kinds.map((k) => h('button', { class: 'chat-kind', disabled: S.busy, onclick: () => sendChat(th.id, k.id) }, `${k.icon} ${k.label}`)),
          (th.appoint_choices || []).length ? h('button', { class: 'chat-kind', disabled: S.busy, onclick: () => { S.apForm = S.apForm ? null : {}; drawChat(); } }, '📅 約束する') : '',
          ...(th.actions || []).map((a) => h('button', { class: 'chat-kind', disabled: S.busy || !a.ok, onclick: () => phoneAct(th.id, a.id) }, `${a.icon} ${a.name}`)),
          S.apForm ? appointForm(th) : '']
          : h('p', { class: 'muted small' }, 'いまはそばにいるので、直接話しましょう。')));
    void lastMine;
  }
  dlg.classList.toggle('thread-open', !!th);
  dlg.replaceChildren(h('div', { class: 'chat-wrap' }, listEl, threadEl));
  // 開いたとき・新しく届いた/送ったときは一番下へ (読み返している途中で何も増えていなければ, その位置のまま)
  const lastT = th && th.items.length ? th.items[th.items.length - 1].t : 0;
  const fresh = th && (S.chatSeen || {})[th.id] !== lastT;
  if (th) (S.chatSeen = S.chatSeen || {})[th.id] = lastT;
  const nl = dlg.querySelector('.chat-list');
  if (nl) nl.scrollTop = listTop;                 // トーク一覧の位置も保つ
  const nb = dlg.querySelector('.chat-body');
  if (nb && (atBottom || S.chatJump || fresh)) nb.scrollTop = nb.scrollHeight;
  else if (nb && keepScroll && S.chatDrawn === (th && th.id)) nb.scrollTop = prevTop;    // 描き直しても, 読んでいた位置のまま
  S.chatDrawn = th ? th.id : null;
  S.chatJump = false;
  clearTimeout(S.chatPoll);       // 返信待ちの間は, 相手がまだスマホを見ていればすぐ返ってくるので, こまめに見る
  if (th && th.waiting) S.chatPoll = setTimeout(() => { if (dlg.open && S.chatCid === th.id) drawChat(); }, 8000);
}
// 約束の誘い: 日時・行き先・何をするか
function appointForm(th) {
  const f = S.apForm;
  const ch = th.appoint_choices || [];
  f.place = ch.some((c) => c.place === f.place) ? f.place : (ch[0] || {}).place;
  const cur = ch.find((c) => c.place === f.place) || { dos: [] };
  f.do = cur.dos.some((d) => d.id === f.do) ? f.do : (cur.dos[0] || {}).id;
  f.day = f.day ?? 1;
  f.time = f.time || '13:00';
  const days = Array.from({ length: 14 }, (_, i) => { const d = new Date(Date.now() + i * 86400000); return [i, i === 0 ? '今日' : i === 1 ? '明日' : `${d.getMonth() + 1}/${d.getDate()}（${'日月火水木金土'[d.getDay()]}）`]; });
  const times = []; for (let m = 7 * 60; m <= 22 * 60; m += 30) times.push(`${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`);
  const sel = (key, opts) => h('select', { onchange: (ev) => { f[key] = key === 'day' ? +ev.target.value : ev.target.value; drawChat(); } },
    opts.map(([v, l]) => h('option', { value: v, selected: String(f[key]) === String(v) }, l)));
  const G = ((S.view || {}).outdoor || {}).groups || {};
  return h('div', { class: 'appoint-form', style: 'flex-basis:100%;display:flex;flex-wrap:wrap;gap:6px;align-items:center' },
    sel('day', days), sel('time', times.map((t) => [t, t])),
    sel('place', ch.map((c) => [c.place, `${c.icon}${c.label}（${G[c.group] || ''}${c.hours && c.hours !== '24時間' ? '・' + c.hours : ''}）`])),
    sel('do', cur.dos.map((d) => [d.id, `${d.icon} ${d.name}`])),
    h('button', { class: 'btn small primary', disabled: S.busy, onclick: () => proposeAppoint(th.id) }, f.counter ? 'この日時なら、と返す' : '誘う'),
    f.counter ? h('button', { class: 'btn small ghost', onclick: () => { S.apForm = null; drawChat(); } }, 'やめる') : '',
    h('span', { class: 'muted small' }, '返事は時間差で届きます。その時間に予定があれば断られます'));
}
async function proposeAppoint(cid) {
  const f = S.apForm;
  const d = new Date(Date.now() + f.day * 86400000);
  const [hh, mm] = f.time.split(':').map(Number);
  d.setHours(hh, mm, 0, 0);
  if (S.busy) return;
  S.busy = true;
  try {
    if (f.counter) await api('/api/appoint/answer', { id: f.counter, counter: { t: d.getTime() / 1000, place: f.place, do: f.do } });
    else await api('/api/appoint', { id: cid, t: d.getTime() / 1000, place: f.place, do: f.do });
    S.apForm = null; S.chatJump = true;
  } catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await drawChat(); refresh(); }
}
async function answerAppoint(id, yes) {
  if (S.busy) return;
  S.busy = true;
  try { await api('/api/appoint/answer', { id, yes }); } catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await drawChat(); refresh(); }
}
// スマホから: 電話・「家に行ってもいい？」など (結果はトークと知らせに)
async function phoneAct(cid, action) {
  if (S.busy) return;
  S.busy = true;
  try {
    const r = await api('/api/act', { action, character: cid });
    toast(r.entry.text.replace(/\n.*/s, ''), r.missed ? 'err' : 'ok');
    S.chatJump = true;
  } catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await drawChat(); refresh(); }
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
        `${t(x.t)}〜${hm(x.end)}　${x.label}：${x.text}`, planNote(x), (x.meets || []).length ? h('div', { class: 'muted' }, '　' + x.meets.join(' / ')) : ''))
        : h('div', { class: 'muted small' }, '家で静かに過ごした')),
    h('div', { class: 'small' }, `お金 ${rep.pay >= 0 ? '+' : ''}${yen(rep.pay)}・体力 ${Math.round(rep.stamina[0])} → ${Math.round(rep.stamina[1])}`),
    rep.meets.length ? h('div', { class: 'pgroup' }, h('h4', {}, '出会い'), rep.meets.map((m) => h('div', { class: 'small' }, m))) : '',
    h('div', { class: 'pgroup' }, h('h4', {}, '届いたメッセージ'),
      rep.messages.length ? rep.messages.map((m) => h('div', { class: 'row', style: 'align-items:flex-start' },
        h('div', { style: 'flex:1' }, h('b', {}, m.name), h('span', { class: 'muted small' }, ` ${t(m.t)}`), h('div', {}, m.text),
          m.auto_reply ? h('div', { class: 'muted small' }, `↳ 自動で返事（${(REPLY_POLICY.find((p) => p[0] === m.auto_reply.choice) || [])[1] || m.auto_reply.choice}）: ${m.auto_reply.text}`) : '',
          m.mood < 0 ? h('div', { class: 'muted small' }, '（返事がなくて、少し気にしているかも）') : ''),
        (() => {             // まだ返事を待っているメッセージなら, 返事を選ぶ (待ちが終わっていれば出さない)
          const ap = (S.view.approaches || []).find((x) => x.cid === m.cid && x.choices);
          if (!ap) return '';
          return h('div', { class: 'row', style: 'flex-wrap:wrap;gap:4px;max-width:60%' }, ap.choices.map((c) => h('button', { class: 'btn small', onclick: async (ev) => {
            ev.target.parentNode.querySelectorAll('button').forEach((b) => { b.disabled = true; });
            try { const r = await api('/api/approach', { answer: 'reply', choice: c.id, character: m.cid }); toast(`${m.name}に返事をした`, 'ok'); if (r && r.entry) S.lastDeltas = r.entry.deltas || {}; }
            catch (e) { toast(e.message, 'err'); }
          } }, c.label)));
        })())) : h('div', { class: 'muted small' }, 'なし')),
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
    h('div', { class: 'row', style: 'align-items:center;gap:8px;flex-wrap:nowrap' }, avatar(sp.face, sp.name, 'small'),
      h('div', {}, sp.type === 'call' ? `💬 ${sp.where}で、${sp.name}に声をかけられた` : `👀 ${sp.where}で、${sp.name}を見かけた`)),
    sp.text ? h('div', { class: 'muted' }, `「${sp.text}」`) : '',
    h('div', { class: 'row' }, sp.options.map((o) => h('button', { class: 'btn small', disabled: S.busy, onclick: () => answerStreet(o.id) }, o.label))));
}
function renderStreet() {
  const box = $('#street-box');
  const away = !$('#away-overlay').hidden;
  const card = away ? null : (streetCard() || appointCard());
  box.hidden = !card;
  if (card) box.replaceChildren(card);
  const sp = S.view.street_pending;
  if (sp && sp.type === 'call') {
    // 声をかけられた: 名前を呼ばれれば気づくのと同じく, はっきり知らせる (見かけただけのときは控えめのまま)
    notifyCall(`st:${sp.t}`, `💬 ${sp.where}で、${sp.name}に声をかけられた`, sp.text ? `「${sp.text}」` : '', true);
  } else if (sp && document.hidden && !NOTIFY.blink) {
    document.title = '・Comfy LIFE';
  }
}
/* ---- 知らせ: 話しかけられた・メッセージが来て返事を待たれている・出先で声をかけられた. 見落とさないように,
   画面の知らせ・音・タブの題名の点滅・画面を見ていないときはブラウザの通知 (許可したときだけ)・スマホは振動で知らせる.
   返事をするまで, 2 分ごとに一度だけ音で知らせ直す (設定で切れる) */
const NOTIFY = { seen: new Set(), blink: null, lastRemind: 0 };
function notifyCall(key, title, body, strong) {
  if (NOTIFY.seen.has(key)) return;
  NOTIFY.seen.add(key);
  NOTIFY.lastRemind = Date.now();
  toast(title, 'ok');
  if (S.ui.callSound !== false) chime(strong);
  if (S.ui.vibrate !== false && navigator.vibrate) { try { navigator.vibrate(strong ? [120, 80, 120] : 90); } catch (e) { /* 振動できない端末 */ } }
  if (document.hidden || !document.hasFocus()) {
    blinkTitle(title);
    if (S.ui.browserNotify && 'Notification' in window && Notification.permission === 'granted') {
      try {
        const n = new Notification('Comfy LIFE', { body: title + (body ? '\n' + body : ''), tag: 'comfy-life-call', renotify: true });
        n.onclick = () => { window.focus(); n.close(); };
      } catch (e) { /* 通知が出せない環境でも, 題名の点滅と音はある */ }
    }
  }
}
function blinkTitle(text) {
  clearInterval(NOTIFY.blink);
  let on = false;
  NOTIFY.blink = setInterval(() => { on = !on; document.title = on ? text : 'Comfy LIFE'; }, 1000);
}
function stopBlink() {
  if (NOTIFY.blink) { clearInterval(NOTIFY.blink); NOTIFY.blink = null; }
  document.title = 'Comfy LIFE';
}
function callPending() {
  const v = S.view || {};
  return (v.approaches || []).length > 0 || (v.street_pending && v.street_pending.type === 'call');
}
// 返事をするまで, 2 分ごとに一度だけ音 (と振動) で知らせ直す
setInterval(() => {
  if (!S.view || S.ui.callRemind === false || !callPending()) return;
  if (Date.now() - NOTIFY.lastRemind < 120000) return;
  NOTIFY.lastRemind = Date.now();
  if (S.ui.callSound !== false) chime(false);
  if (S.ui.vibrate !== false && navigator.vibrate) { try { navigator.vibrate(60); } catch (e) { /* 振動できない端末 */ } }
}, 15000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) stopBlink(); });
window.addEventListener('focus', () => stopBlink());
// 知らせの音: 話しかけられた・声をかけられた (strong) は 3 音, 知らせ直し・ほかは控えめな 2 音
function chime(strong) {
  try {
    const ac = S.audio || (S.audio = new (window.AudioContext || window.webkitAudioContext)());
    if (ac.state === 'suspended') ac.resume();
    const vol = strong ? 0.2 : 0.12;
    (strong ? [[660, 0], [880, 0.16], [1046, 0.32]] : [[660, 0], [880, 0.16]]).forEach(([f, d]) => {
      const o = ac.createOscillator(), g = ac.createGain();
      o.type = 'sine'; o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, ac.currentTime + d);
      g.gain.exponentialRampToValueAtTime(vol, ac.currentTime + d + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + d + 0.35);
      o.connect(g).connect(ac.destination);
      o.start(ac.currentTime + d); o.stop(ac.currentTime + d + 0.4);
    });
  } catch (e) { /* 音が出せない環境でも, 画面の知らせはある */ }
}
// 約束: 自分でその場所へ出向く (行き先を約束の場所にした外出). 約束の場所にいる状態で時刻を迎えると会える
const remainText = (sec) => (sec > 0 ? `あと${fmtDur(sec)}` : `${fmtDur(-sec)}過ぎ`);
function appointLine(x, withBtn) {
  const set = x.status === 'set' || x.status === 'waiting';
  return h('div', { class: 'appoint-line' },
    h('div', {}, x.status === 'waiting' ? `📍 ${x.place_label}で待っている（${x.name}はまだ来ていない）`
      : `📅 ${x.when}に${x.place_label}で${x.name}と「${x.do_label}」`, set ? h('span', { class: 'muted small' }, `（${remainText(x.remain)}）`) : ''),
    withBtn && set ? h('div', { class: 'row' },
      x.here ? h('span', { class: 'muted small' }, x.home_me ? '家にいれば、時間に来てくれます' : 'もう着いている。時間まで、ここで待つ')
        : x.home_me ? h('span', { class: 'muted small' }, 'あなたの家に来てもらう約束（その時間に家にいる）')
          : h('button', { class: 'btn small', disabled: S.busy || ((S.view.presence || {}).mode !== 'none' && (S.view.presence || {}).mode !== 'out'),
            title: '行き先を約束の場所にして出かけます（すぐ着きます）。画面を閉じると家に帰るので、約束の場所にいないことになります',
            onclick: () => goAppoint(x.id) }, `🚶 ${x.place_label}へ出かける`)) : '');
}
// 約束の時刻が近い: 出かける (着いていれば, 時間まで待つ)
function appointCard() {
  const due = (S.view.appoints || []).filter((x) => x.due || x.status === 'waiting');
  if (!due.length) return null;
  return h('div', { class: 'street-card calling' }, due.map((x) => appointLine(x, true)));
}
async function goAppoint(id) {
  if (S.busy) return;
  S.busy = true;
  try { const r = await api('/api/appoint/go', { id }); if (r.text) toast(r.text, 'ok'); else handleActResult(r); } catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await refresh(); }
}
// 立ち話のあと: そのまま一緒に過ごすか (相手から誘われた / こちらから誘える)
function joinCard() {
  const j = S.view.street_join;
  if (!j) return null;
  const go = async (yes) => {
    if (S.busy) return;
    S.busy = true;
    try { const r = await api('/api/street/join', { yes }); toast(r.text.replace(/\n/, ' '), 'ok'); } catch (e) { toast(e.message, 'err'); }
    finally { S.busy = false; await refresh(); }
  };
  return h('div', { class: 'street-card' + (j.offer ? ' calling' : '') },
    h('div', { class: 'row', style: 'align-items:center;gap:8px;flex-wrap:nowrap' }, avatar(j.face, j.name, 'small'),
      h('div', {}, j.offer ? `🚶 ${j.name}に、このまま一緒にいないかと誘われた` : `🚶 ${j.name}と、${j.where}で立ち話をした`)),
    j.line ? h('div', { class: 'muted' }, `「${j.line}」`) : '',
    h('div', { class: 'row' },
      h('button', { class: 'btn small', disabled: S.busy, onclick: () => go(true) }, j.offer ? '一緒に過ごす' : '一緒に過ごさない？と誘う'),
      h('button', { class: 'btn small', disabled: S.busy, onclick: () => go(false) }, j.offer ? '今日はやめておく' : 'ここで別れる')));
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
  const comp = (S.view.company || []).map((c) => c.name).join('・');
  const since = p.since ? Math.max(0, Date.now() / 1000 - p.since) : 0;
  box.hidden = false;
  box.replaceChildren(h('div', { class: 'away-card' },
    h('div', { class: 'away-ic' }, a[0]),
    h('div', { class: 'away-title' }, p.solo ? `${p.solo.icon} ${p.solo.label}` : a[1]),
    (() => { const c = (S.view.outdoor || {}).current; const wx = (S.view.outdoor || {}).weather || {};
      return c ? h('div', { class: 'muted' }, `${c.icon} ${c.label}・${wx.icon || ''}${wx.label || ''}`) : ''; })(),
    shopCard(p),
    streetCard() || '',
    joinCard() || '',
    ...(S.view.appoints || []).filter((x) => (x.status === 'set' || x.status === 'waiting') && x.remain < 6 * 3600 && x.remain > -2700)
      .map((x) => h('div', { class: 'away-appoint' + (x.here ? ' here' : '') },
        `📅 約束: ${hhmm(x.t)} ${x.name}（${x.place_label}・${remainText(x.remain)}）${x.here ? '　📍ここ' : ''}`,
        x.here || x.home_me ? '' : h('button', { class: 'btn small', disabled: S.busy, style: 'margin-left:6px', onclick: () => goAppoint(x.id) }, `${x.place_label}へ向かう`))),
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
      : h('p', { class: 'muted small' }, comp ? `${comp}のそばを離れています。このまま画面を閉じてもかまいません。`
        : '一人で過ごしています。このまま画面を閉じてもかまいません。', h('br'), '「' + a[2] + '」で戻ります。'),
    h('button', { class: 'btn primary', disabled: S.busy, onclick: comeBack }, a[2])));
}

// 店での買い物: 品を選んでいる間は「買い物中」, 済んだら目立つ知らせ (読んだら閉じる. 帰る・ほかの店へ)
function shopCard(p) {
  if (p.mode !== 'out') return '';
  const sh = p.shop;
  if (!sh) {
    return p.shop_wait != null ? h('div', { class: 'shop-card wait' }, `🛒 買い物中…（品を選んでいる。${p.shop_wait > 60 ? `あと${Math.ceil(p.shop_wait / 60)}分くらい` : 'もうすぐ'}）`) : '';
  }
  if (sh.seen) return h('div', { class: 'shop-card done small' }, `🛍 ${sh.label}での買い物は済んだ（${yen(sh.total)}）`);
  const bought = sh.bought || [];
  return h('div', { class: 'shop-card done' },
    h('div', { class: 'shop-head' }, h('b', {}, sh.nothing ? `🛍 ${sh.label}で買うものはなかった` : `🛍 ${sh.label}で買い物を終えた`),
      h('span', { class: 'shop-total' }, `合計 ${yen(sh.total)}`)),
    sh.nothing ? h('div', { class: 'small' }, sh.nothing) : '',
    bought.filter((b) => !b.impulse).length ? h('div', { class: 'small' }, '買えた: ' + bought.filter((b) => !b.impulse).map((b) => `${b.icon || ''}${b.name}（${yen(b.price)}）`).join('、')) : '',
    bought.filter((b) => b.impulse).length ? h('div', { class: 'small' }, 'ついでに買った: ' + bought.filter((b) => b.impulse).map((b) => `${b.icon || ''}${b.name}（${yen(b.price)}）`).join('、')) : '',
    (sh.missed || []).length ? h('div', { class: 'small down' }, '買えなかった: ' + sh.missed.join('。')) : '',
    (sh.elsewhere || []).length ? h('div', { class: 'small muted' }, `この店には売っていない: ${sh.elsewhere.join('、')}（ほかの店で）`) : '',
    h('div', { class: 'row', style: 'gap:6px;justify-content:center;margin-top:6px' },
      h('button', { class: 'btn small primary', disabled: S.busy, onclick: comeBack }, '帰る'),
      h('button', { class: 'btn small', disabled: S.busy, onclick: pickNextShop }, 'ほかの店へ'),
      h('button', { class: 'btn small ghost', disabled: S.busy, onclick: async () => { await api('/api/shop/ack', {}); await refresh(); } }, '閉じる（ここにいる）')));
}
// 出かけている先から, ほかの行き先へ (いまの外出の結果を出して, そのまま向かう)
function pickNextShop() {
  const od = (S.view || {}).outdoor || {};
  const ids = (OD_CHOICES().out || []).filter((id) => id !== ((S.view.presence || {}).solo ? (od.current || {}).place : null));
  const dlg = h('dialog', { class: 'modal', style: 'width:min(480px,94vw);height:auto;max-height:86vh;overflow:auto' });
  const close = () => { dlg.close(); dlg.remove(); };
  dlg.append(h('div', { style: 'padding:14px' },
    h('div', { class: 'row' }, h('b', {}, 'ほかの行き先へ'), h('div', { class: 'spacer' }), h('button', { class: 'btn ghost small', onclick: close }, '✕')),
    h('div', { class: 'cmds', style: 'margin-top:8px' }, ...placeGroups(ids, (id) => {
      const P = (od.places || {})[id] || {};
      return h('button', { class: 'cmd', disabled: P.open === false || S.busy, title: placeTip(id), onclick: async () => {
        close();
        if (S.busy) return;
        S.busy = true;
        try { const r = await api('/api/solo/move', { place: id }); if (r.solo) toast(r.solo.text, 'ok'); toast(`${P.label}へ向かった`, 'ok'); }
        catch (e) { toast(e.message, 'err'); } finally { S.busy = false; await refresh(); }
      } }, h('span', { class: 'ic' }, P.icon || '📍'), h('span', {}, P.label || id), P.open === false ? h('small', { class: 'muted' }, P.note) : null);
    }))));
  document.body.append(dlg);
  dlg.showModal();
}

async function comeBack() {
  const p = (S.view || {}).presence || {};
  if (p.mode === 'out' && p.shop_wait != null && !p.shop && !confirm('まだ買い物の途中です（品を選んでいる）。何も買わずに帰りますか？')) return;
  if (S.busy) return;
  S.busy = true;
  try { handleActResult(await api('/api/presence/back', withT({}))); } catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await refresh(); }
}

/* ---- キャラからの働きかけ: そばにいる人が話しかけてくる / 離れている人からメッセージが来て返事を待たれている */
function renderApproach() {
  const box = $('#approach-box');
  const aps = S.view.approaches || [];
  if (!aps.length) { box.hidden = true; return; }
  box.hidden = false;
  box.classList.toggle('calling', true);
  for (const ap of aps) {          // 新しく話しかけられた・メッセージが来た: 知らせる (同じ働きかけは一度だけ)
    notifyCall(`ap:${ap.cid}:${ap.id}:${Math.round(ap.until)}`, `${ap.icon} ${ap.name}${ap.apart ? 'から' : 'が'}${ap.label}`,
      ap.apart ? '' : 'そばで話しかけられています', !ap.apart);
  }
  box.replaceChildren(...aps.map((ap) => {
    const rest = Math.max(0, Math.round(ap.until - Date.now() / 1000));
    return h('div', { class: 'ap-item' },
      h('div', { class: 'req-text' }, h('b', {}, `${ap.icon} ${ap.name}${ap.apart ? 'から' : 'が'}${ap.label}`),
        h('span', { class: 'muted small', id: 'ap-rest-' + ap.cid }, `（あと${Math.ceil(rest / 60)}分）`)),
      ap.choices        // メッセージ: 返事を選ぶ (どれが良く効くかは相手しだい)
        ? h('div', { class: 'row', style: 'flex-wrap:wrap;gap:6px' },
          ...ap.choices.map((c) => h('button', { class: 'btn small', disabled: S.busy, onclick: () => answerApproach(ap.cid, 'reply', c.id) }, c.label)),
          h('button', { class: 'btn small ghost', disabled: S.busy, onclick: () => answerApproach(ap.cid, 'later') }, ap.later))
        : h('div', { class: 'row' },
          h('button', { class: 'btn primary', disabled: S.busy, onclick: () => answerApproach(ap.cid, 'accept') }, ap.accept),
          h('button', { class: 'btn', disabled: S.busy, onclick: () => answerApproach(ap.cid, 'later') }, ap.later)));
  }));
}

async function answerApproach(cid, ans, choice) {
  if (S.busy) return;
  S.busy = true;
  try {
    const r = await api('/api/approach', { answer: ans, character: cid, choice });
    if (r.entry) handleActResult(Object.assign(r, { entry: Object.assign({ who: cid }, r.entry) }));
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
}

/* ---- お金タブ: 財布・支払い・銘柄・ニュース・稼ぐ */
// お金タブ: あなたのお金 (財布・借金と借りているお金・仕事・内職・株). 相手とのお金のやりとりは「誰かと」の「お金のこと」
function renderMoney() {
  const v = S.view;
  const L = v.you || {};
  const M = L.market || { assets: [], news: [] };
  const inv = L.invest || {};
  const asset = (a) => {
    const qty = h('input', { type: 'number', min: 1, step: 1, value: S.tradeQty?.[a.id] || 1, class: 'qty',
      oninput: (ev) => { (S.tradeQty = S.tradeQty || {})[a.id] = ev.target.value; } });
    const pl = a.qty ? a.value - a.cost : 0;
    const open = (S.assetOpen || {})[a.id];
    const lim = h('input', { type: 'number', min: 1, step: 1, value: Math.round(a.price), class: 'qty', title: '指値（円）' });
    const days = h('input', { type: 'number', min: 1, max: 30, step: 1, value: 5, class: 'qty', title: '期限（日）' });
    const plan = (M.plans || []).find((p) => p.asset === a.id);
    const amt = h('input', { type: 'number', min: 1000, step: 1000, value: plan ? plan.amount : 10000, class: 'qty', title: '毎月の積立額（円）' });
    const pday = h('input', { type: 'number', min: 1, max: 28, step: 1, value: plan ? plan.day : 10, class: 'qty', title: '毎月の積立日' });
    const pre = M.open ? '' : '予約で';
    return h('div', { class: 'asset' },
      h('div', { class: 'asset-head', title: a.desc, style: 'cursor:pointer', onclick: () => { S.assetOpen = Object.assign({}, S.assetOpen, { [a.id]: !open }); renderMoney(); } },
        h('span', { class: 'ic' }, a.icon), h('b', {}, a.name), a.sector_label ? h('span', { class: 'tag', style: 'margin-left:4px;white-space:nowrap;font-size:11px' }, a.sector_label) : '',
        plan ? h('span', { class: 'tag', style: 'margin-left:4px', title: `毎月${plan.day}日に${yen(plan.amount)}分` }, '積立') : '',
        h('div', { class: 'spacer' }), h('b', { style: 'white-space:nowrap' }, yen(a.price)),
        h('span', { class: 'chg ' + (a.day >= 0 ? 'up' : 'down'), title: '前の取引日の終わりから' }, `${a.day >= 0 ? '+' : ''}${a.day}%`)),
      a.qty ? h('div', { class: 'muted small' }, `保有 ${a.qty}株・評価 ${yen(a.value)}（`,
        h('span', { class: pl >= 0 ? 'up' : 'down' }, `${pl >= 0 ? '+' : ''}${yen(pl)}`), '）') : '',
      open ? [
        h('div', { class: 'muted small' }, a.desc),
        a.history.length > 1 ? sparkline(a.history, `${a.name}の値動き（取引時間の 1 時間ごと）`) : '',
        h('div', { class: 'row trade' }, qty, h('span', { class: 'muted small' }, '株'),
          h('button', { class: 'btn', disabled: S.busy, title: M.open ? 'いまの値段で買う' : '次の取引開始に、そのときの値段で買う', onclick: () => trade(a.id, +qty.value) }, pre + '買う'),
          h('button', { class: 'btn', disabled: S.busy || !a.qty, onclick: () => trade(a.id, -qty.value) }, pre + '売る'),
          a.qty ? h('button', { class: 'btn ghost small', disabled: S.busy, onclick: () => trade(a.id, -a.qty) }, '全部' + (pre || '') + '売る') : ''),
        h('div', { class: 'row trade' }, h('span', { class: 'muted small' }, '指値'), lim, h('span', { class: 'muted small' }, '円・'), days, h('span', { class: 'muted small' }, '日'),
          h('button', { class: 'btn small', disabled: S.busy, title: 'この値段以下になったら買う', onclick: () => marketOrder(a.id, 'buy', +qty.value, +lim.value, +days.value) }, '以下で買う'),
          h('button', { class: 'btn small', disabled: S.busy || !a.qty, title: 'この値段以上になったら売る', onclick: () => marketOrder(a.id, 'sell', +qty.value, +lim.value, +days.value) }, '以上で売る')),
        h('div', { class: 'row trade' }, h('span', { class: 'muted small' }, '積立 毎月'), pday, h('span', { class: 'muted small' }, '日に'), amt, h('span', { class: 'muted small' }, '円'),
          h('button', { class: 'btn small', disabled: S.busy, onclick: () => marketApi('/api/market/plan', { asset: a.id, amount: +amt.value, day: +pday.value }, '積立を設定しました') }, plan ? '変える' : '始める'),
          plan ? h('button', { class: 'btn ghost small', disabled: S.busy, onclick: () => marketApi('/api/market/plan', { drop: plan.id }, '積立をやめました') }, 'やめる') : '')] : '');
  };
  const ok = (k) => ((v.solo || {}).plain || []).some((p) => p.id === k && p.ok) && (v.presence || {}).mode === 'none';
  const EA = v.earn || {};
  $('#tab-money').replaceChildren(
    h('div', { class: 'pgroup money-box' }, h('h4', {}, 'あなたの財布'),
      h('div', { class: 'money-row' }, h('span', {}, '手元'), h('b', {}, yen(L.my_money || 0))),
      inv.value ? h('div', { class: 'money-row' }, h('span', {}, '株（評価額）'),
        h('b', { class: inv.value >= inv.invested ? 'up' : 'down' }, `${yen(inv.value)}（${inv.value >= inv.invested ? '+' : ''}${yen(inv.value - inv.invested)}）`)) : '',
      L.debt ? h('div', { class: 'money-row', title: '払えなかった生活費・家賃。月はじめに少し利息がつきます' }, h('span', {}, '借金'), h('b', { class: 'down' }, yen(L.debt)),
        h('button', { class: 'btn small', disabled: S.busy || !(L.my_money > 0), onclick: () => repay('debt', L.debt, '借金') }, '返す')) : '',
      ...(L.loans || []).map((x) => h('div', { class: 'money-row' }, h('span', {}, `${x.name}に借りている`), h('b', { class: 'down' }, yen(x.amount)),
        h('button', { class: 'btn small', disabled: S.busy || !(L.my_money > 0), title: 'そばにいなければ振り込み（返事はメッセージで）', onclick: () => repay(x.id, x.amount, x.name) }, '返す'))),
      L.in_debt ? h('div', { class: 'muted small' }, '借金のあいだは、食材・洗剤などの必需品しか買えません。') : '',
      (L.money_notes || []).length ? h('div', { class: 'muted small' }, ...L.money_notes.slice(-3).map((x) => h('div', {}, `${fmtTime(x.t)} ${x.text}`))) : ''),
    kakeiboPanel(),
    h('div', { class: 'pgroup' }, h('h4', {}, '稼ぐ'),
      h('div', { class: 'earn' },
        h('button', { class: 'cmd', disabled: S.busy || !ok('work'), onclick: () => soloStart('work'),
          title: '仕事に行きます（そばに誰かいれば告げてから）。戻ったときに働いた時間ぶん稼げます（画面を開いているあいだだけ。閉じたらそこまで）' },
          h('span', { class: 'ic' }, '💼'), h('span', {}, '仕事に行く'), h('small', { class: 'muted' }, '離れた時間ぶん')),
        h('button', { class: 'cmd', disabled: S.busy || !!v.side_job, onclick: openTask,
          title: '家でパズルを解いて稼ぎます。難しさ・速さ・ミスで稼ぎが決まります' },
          h('span', { class: 'ic' }, '🧵'), h('span', {}, '内職する'),
          h('small', { class: 'muted' }, v.side_job ? v.side_job.reason.replace(/^.*（(.*)）$/, '$1') : 'パズルを解く'))),
      h('div', { class: 'muted small' }, `体力 ${Math.floor(L.stamina ?? 100)}・今日の勤務 ${(L.work_today || 0).toFixed(1)} / 9時間・仕事スキル ${Math.round((L.skills || {}).work || 0)}`),
      h('div', { class: 'muted small' }, `本業の時給 ${yen(EA.wage || 0)}${EA.wage !== EA.base_wage ? `（始め ${yen(EA.base_wage || 0)}）` : ''}・今月の本業 ${EA.month_h || 0}時間。月ごとの勤務で時給が見直され、6月・12月の10日に賞与が出ます（休みが多いと下がる・出ない）`),
      h('div', { class: 'muted small' }, '仕事に出られるのは 6〜21時（体力20以上）。給料は 6〜23時の分だけ、1日9時間まで。内職は体力10を使います'),
      partTimePanel(EA, v), sideWorkPanel(EA, v), fleaPanel(EA), lottoPanel(EA)),
    h('div', { class: 'pgroup' }, h('h4', {}, '株'),
      h('div', { class: 'row', style: 'margin-bottom:4px' }, h('span', { class: 'tag' + (M.open ? ' bond' : '') }, M.open ? `📈 取引中（${M.until}まで）` : `🌙 取引時間外（次は ${M.next}）`),
        h('span', { class: 'muted small' }, `買付余力 ${yen(M.buy_power ?? L.my_money ?? 0)}`)),
      h('div', { class: 'muted small', style: 'margin-bottom:6px' }, '取引時間は平日の 9:00〜11:30 と 12:30〜15:00（土日・祝日・年末年始は休み）。値段はそのあいだだけ動き、時間外のニュースは次の取引開始の値段に効きます。時間外の売買は予約になります。ニュースは当たるとは限りません。銘柄を押すと、売買・指値・積立。'),
      ...M.assets.map(asset),
      (M.orders || []).length ? h('div', { class: 'kb-cats' }, h('div', { class: 'muted small' }, '注文中'),
        M.orders.map((o) => h('div', { class: 'money-row small' },
          h('span', {}, `${o.name} ${o.qty}株 ${o.limit ? `${yen(o.limit)}${o.side === 'buy' ? '以下で買う' : '以上で売る'}（${fmtTime(o.until)}まで）` : (o.side === 'buy' ? '予約で買う' : '予約で売る')}`),
          h('button', { class: 'btn ghost small', disabled: S.busy, onclick: () => marketApi('/api/market/cancel', { id: o.id }, '注文を取り消しました') }, '取消')))) : '',
      (M.fills || []).length ? h('div', { class: 'kb-cats' }, h('div', { class: 'muted small' }, '注文・積立の結果'),
        M.fills.map((x) => h('div', { class: 'muted small' }, `${fmtTime(x.t)} ${x.text}`))) : ''),
    (M.rumors || []).length ? h('div', { class: 'pgroup' }, h('h4', {}, '聞いた噂'),
      h('div', { class: 'muted small' }, '知り合いから聞いた話です。当たるとは限りません（会話と気配りのスキルが高いほど、よく聞けて、確かな話が多くなります）。'),
      M.rumors.map((r) => h('div', { class: 'news' },
        h('span', { class: r.dir > 0 ? 'up' : 'down' }, r.dir > 0 ? '△' : '▽'), h('span', {}, `${r.text}`),
        h('span', { class: 'muted small' }, `${fmtTime(r.t)}・${r.via === 'secondhand' ? `${r.src_name}のことを人づてに` : `${r.src_name}から`}`)))) : '',
    h('div', { class: 'pgroup' }, h('h4', {}, 'ニュース'),
      M.news.length ? M.news.map((n) => h('div', { class: 'news' },
        h('span', { class: n.dir > 0 ? 'up' : 'down' }, n.dir > 0 ? '▲' : '▼'), h('span', {}, n.text),
        h('span', { class: 'muted small' }, fmtTime(n.t) + (n.after ? '（時間外）' : '')))) : h('div', { class: 'muted small' }, 'まだニュースはありません')));
}

// アルバイト: いまのバイト (シフト・バイトに行く・辞める) と求人 (応募: 曜日と時間を決める)
function partTimePanel(EA, v) {
  const P = EA.parttime;
  const hm = (t) => new Date(t * 1000).toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit' });
  if (P) {
    const free = (v.presence || {}).mode === 'none';
    return h('div', { class: 'kb-cats' },
      h('div', { class: 'money-row' }, h('span', {}, `🧑‍💼 ${P.label}（${P.place_label}・時給 ${yen(P.wage)}）`),
        h('button', { class: 'btn small ghost', disabled: S.busy, onclick: () => confirm(`${P.label}を辞めますか？`) && earnApi('/api/earn/parttime/quit', {}) }, '辞める')),
      h('div', { class: 'muted small' }, `シフト: ${P.shift_text}${P.absent ? `・この30日で${P.absent}回休んだ（3回で辞めさせられる）` : ''}`),
      h('div', { class: 'row' },
        h('button', { class: 'cmd', disabled: S.busy || !P.now || !free, title: 'シフトの時間（前後30分から）に行けます。戻ったとき、シフトと重なった時間ぶんのバイト代が出ます',
          onclick: () => earnApi('/api/earn/parttime/go', withT({}), 'バイトに出かけた') },
          h('span', { class: 'ic' }, '🧑‍💼'), h('span', {}, 'バイトに行く'), h('small', { class: 'muted' }, P.now ? 'いまシフトの時間' : P.next ? `次は ${hm(P.next)}` : ''))));
  }
  const open = S.jobsOpen;
  return h('div', { class: 'kb-cats' },
    h('button', { class: 'btn small', onclick: () => { S.jobsOpen = !open; renderMoney(); } }, open ? '▾ 求人を閉じる' : '▸ アルバイトの求人を見る'),
    open ? (EA.jobs || []).map((j) => {
      const f = (S.jobForm = S.jobForm || {})[j.id] = (S.jobForm || {})[j.id] || { days: [], from: `${String(Math.max(j.hours[0], 17)).padStart(2, '0')}:00`, to: `${String(Math.min(j.hours[1], 21)).padStart(2, '0')}:00` };
      const ng = (EA.rejected || {})[j.id];
      return h('div', { class: 'asset' },
        h('div', { class: 'asset-head' }, h('b', {}, j.label), h('span', { class: 'tag', style: 'margin-left:4px' }, j.place_label), h('div', { class: 'spacer' }), h('b', {}, `時給 ${yen(j.wage)}`)),
        h('div', { class: 'muted small' }, `${j.hours[0]}:00〜${j.hours[1]}:00 のあいだで 1 回 2〜8 時間。${SKILL_NAME[j.skill] || ''}のスキルで少し上下`),
        h('div', { class: 'row trade' }, ...'mon,tue,wed,thu,fri,sat,sun'.split(',').map((d, i) => h('label', { class: 'check' },
          h('input', { type: 'checkbox', checked: f.days.includes(d), onchange: (ev) => { f.days = ev.target.checked ? [...f.days, d] : f.days.filter((x) => x !== d); } }), '月火水木金土日'[i]))),
        h('div', { class: 'row trade' },
          h('input', { type: 'time', value: f.from, step: 1800, style: 'width:7.5em;flex:none', onchange: (ev) => { f.from = ev.target.value; } }), h('span', { class: 'muted small' }, '〜'),
          h('input', { type: 'time', value: f.to, step: 1800, style: 'width:7.5em;flex:none', onchange: (ev) => { f.to = ev.target.value; } }),
          h('button', { class: 'btn small', disabled: S.busy || !!ng, title: '面接があります（身だしなみ・会話で受かりやすく）',
            onclick: () => earnApi('/api/earn/parttime/apply', { job: j.id, shifts: [{ days: f.days.join(','), from: f.from, to: f.to }] }) }, ng ? '少し待つ' : '応募する')));
    }) : '');
}
// 副業 (スキルを生かす依頼) と, 知り合いからの頼まれごと
function sideWorkPanel(EA, v) {
  const G = EA.gigs || { offers: [], kinds: [], rep: {} };
  const free = (v.presence || {}).mode === 'none';
  const until = (t) => `${fmtTime(t)}まで`;
  return h('div', { class: 'kb-cats' },
    h('div', { class: 'muted small' }, '💡 副業の依頼（スキルと評判しだいで、ときどき来ます）: ' + G.kinds.map((k) => `${k.label}${k.open ? `（評判 ${G.rep[k.id] ?? 30}）` : `（${SKILL_NAME[k.skill]} ${k.min} から）`}`).join('・')),
    ...G.offers.map((o) => h('div', { class: 'money-row small' },
      h('span', {}, `${o.icon} ${o.label}・${o.client}（${o.h}時間ほど・${yen(o.pay)}くらい・${until(o.until)}）`),
      h('button', { class: 'btn small', disabled: S.busy || !free, title: '取りかかります（終わったら戻る）。時間と出来ばえで報酬と評判が決まります',
        onclick: () => earnApi('/api/earn/gig', withT({ id: o.id }), '取りかかった') }, '取りかかる'))),
    (EA.favors || []).length ? h('div', { class: 'muted small', style: 'margin-top:4px' }, '🤝 頼まれごと（お礼をもらえるかは仲しだい）') : '',
    ...(EA.favors || []).map((f) => h('div', { class: 'money-row small' },
      h('span', {}, `${f.name}から: ${f.label}（${f.h}時間ほど・${until(f.until)}）`),
      h('div', { class: 'row' },
        h('button', { class: 'btn small', disabled: S.busy || !free, onclick: () => earnApi('/api/earn/favor', withT({ id: f.id, yes: true }), '手伝いに行った') }, '引き受ける'),
        h('button', { class: 'btn small ghost', disabled: S.busy, onclick: () => earnApi('/api/earn/favor', { id: f.id, yes: false }) }, '断る')))));
}
// フリマ: 使わない持ち物を出品 (売れるかと値段は, 品物と時期しだい)
function fleaPanel(EA) {
  const fl = EA.flea || [], its = EA.flea_items || [];
  const open = S.fleaOpen;
  return h('div', { class: 'kb-cats' },
    h('button', { class: 'btn small', onclick: () => { S.fleaOpen = !open; renderMoney(); } }, `${open ? '▾' : '▸'} 📦 フリマ${fl.length ? `（出品中 ${fl.length}）` : ''}`),
    open ? [
      h('div', { class: 'muted small' }, '使わない持ち物を出品します（食べ物・消耗品は出せません）。相場（定価の半分くらい）より安いほど早く売れ、季節でも売れ行きが変わります（服は衣替えの時期、マフラーは秋冬）。売れると手数料 10% と送料が引かれます。30日で売れなければ手元に戻ります。'),
      ...fl.map((x) => h('div', { class: 'money-row small' }, h('span', {}, `${x.icon} ${x.name} ${yen(x.price)}（手取り ${yen(x.net)}・相場 ${yen(x.fair)}・${fmtTime(x.until)}まで）`),
        h('button', { class: 'btn ghost small', disabled: S.busy, onclick: () => earnApi('/api/earn/flea_cancel', { id: x.id }) }, '取り下げる'))),
      its.length ? its.map((it) => {
        const pr = h('input', { type: 'number', min: 100, step: 100, value: it.fair, class: 'qty', title: '値段（円）' });
        return h('div', { class: 'money-row small' }, h('span', {}, `${it.icon} ${it.name}（${it.n}個・定価 ${yen(it.price)}・送料 ${yen(it.ship)}）`),
          h('div', { class: 'row' }, pr, h('span', { class: 'muted small' }, '円'),
            h('button', { class: 'btn small', disabled: S.busy, onclick: () => earnApi('/api/earn/flea', { item: it.id, price: +pr.value }) }, '出品')));
      }) : h('div', { class: 'muted small' }, '出品できる持ち物がありません')] : '');
}
// 宝くじ: 売り場のある行き先で買い, 金曜の 18 時に抽せん (ほぼ当たらない)
function lottoPanel(EA) {
  const L = EA.lotto || { tickets: [], results: [] };
  const n = h('input', { type: 'number', min: 1, max: 100, step: 1, value: 10, class: 'qty' });
  return h('div', { class: 'kb-cats' },
    h('div', { class: 'row' }, h('span', { class: 'small' }, `🎫 宝くじ（1枚${yen(L.price || 300)}・金曜18時に抽せん）`),
      L.can ? [n, h('span', { class: 'muted small' }, '枚'), h('button', { class: 'btn small', disabled: S.busy, onclick: () => earnApi('/api/earn/lotto', { n: +n.value }) }, '買う')]
        : h('span', { class: 'muted small' }, '駅前・商店街・モールの売り場で買えます')),
    L.tickets.length ? h('div', { class: 'muted small' }, '抽せん待ち: ' + L.tickets.map((t) => `${t.n}枚（${fmtTime(t.draw)}）`).join('・')) : '',
    L.results.length ? h('div', { class: 'muted small' }, '結果: ' + L.results.map((r) => `${fmtTime(r.t)} ${r.n}枚 ${r.won ? yen(r.won) : 'はずれ'}`).join('・')) : '');
}
async function earnApi(path, body, okMsg) {
  if (S.busy) return;
  S.busy = true;
  try {
    const r = await api(path, body);
    if (r.entry || r.act) handleActResult(r.act || r); else if (r.text) toast(r.text, r.ok === false ? 'err' : 'ok'); else if (okMsg) toast(okMsg, 'ok');
  } catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await refresh(); }
}

// 家計簿: 見えるのは, つけた分だけ (記録した日ごとの出入り・分類ごとの合計) と, 1日にどれくらい稼げばいいかの見積もり
function kakeiboPanel() {
  const K = S.view.kakeibo;
  if (!K) return '';
  const E = K.estimate || {};
  const F = E.fixed || {};
  const sign = (n) => `${n > 0 ? '+' : ''}${yen(n)}`;
  const open = S.kbOpen || {};
  return h('div', { class: 'pgroup kakeibo' }, h('h4', {}, '📒 家計簿'),
    h('div', { class: 'muted small' }, K.last_written ? `最後につけたのは ${K.since_days === 0 ? '今日' : K.since_days + '日前'}（${fmtTime(K.last_written)}）`
      : 'まだつけていません（家事 → 家計簿をつける）'),
    h('div', { class: 'kb-est' },
      h('div', {}, h('b', {}, '1日あたり稼げばいい額: '), E.need ? `${yen(E.need[0])}〜${yen(E.need[1])}くらい` : `固定費だけで ${yen(Math.max(0, (F.total || 0) - (E.passive || 0)))} ほど`,
        h('span', { class: 'muted small' }, `（${E.note || ''}）`)),
      h('div', { class: 'muted small' }, `決まっている出費（1日あたり）: 家賃・光熱費・通信費 ${yen(F.rent || 0)}・生活費 ${yen(F.living || 0)}${F.interest ? `・借金の利息 ${yen(F.interest)}` : ''}`
        + (E.variable ? `／記録からの食費・買い物など ${yen(E.variable[0])}〜${yen(E.variable[1])}` : '') + `／毎日のわずかな収入 ${yen(E.passive || 0)}`)),
    (K.cats || []).length ? h('div', { class: 'kb-cats' }, h('div', { class: 'muted small' }, 'この30日の記録（分類ごと）'),
      K.cats.map((c) => h('div', { class: 'money-row small' }, h('span', {}, c.label), h('b', { class: c.total >= 0 ? 'up' : 'down' }, sign(c.total))))) : '',
    (K.days || []).map((d) => h('div', { class: 'kb-day' },
      h('div', { class: 'row', style: 'cursor:pointer', onclick: () => { S.kbOpen = Object.assign({}, open, { [d.day]: !open[d.day] }); renderMoney(); } },
        h('span', {}, `${open[d.day] ? '▾' : '▸'} ${d.day.slice(5).replace('-', '/')}`), d.fuzzy ? h('span', { class: 'muted small' }, 'うろ覚え') : '',
        h('div', { class: 'spacer' }), d.in ? h('span', { class: 'up small' }, sign(d.in)) : '', h('span', { class: 'down small' }, sign(d.out))),
      open[d.day] ? d.items.map((x) => h('div', { class: 'money-row small muted' }, h('span', {}, `${x.label}${x.n ? '・' + x.n : ''}${x.approx ? '（約）' : ''}`), h('span', {}, sign(x.a)))) : '')));
}

async function repay(to, owed, name) {
  if (S.busy) return;
  const v = prompt(`${name}に返す額（円）`, String(Math.min(owed, (S.view.you || {}).my_money || 0)));
  if (v === null) return;
  const amount = Math.trunc(+v);
  if (!(amount > 0)) return toast('返す額を入れてください', 'err');
  S.busy = true;
  try { const r = await api('/api/money/repay', { to, amount }); toast(`${yen(r.amount)}返しました${r.left ? `（残り ${yen(r.left)}）` : '（完済）'}`); }
  catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await refresh(); }
}
async function marketApi(path, body, ok) {
  if (S.busy) return;
  S.busy = true;
  try { await api(path, body); if (ok) toast(ok, 'ok'); } catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await refresh(); }
}
function marketOrder(asset, side, qty, limit, days) {
  qty = Math.trunc(qty);
  if (!(qty > 0)) return toast('株数を入れてください', 'err');
  if (!(limit > 0)) return toast('値段を入れてください', 'err');
  return marketApi('/api/market/order', { asset, side, qty, limit, days }, `指値の注文を出しました（${yen(limit)}${side === 'buy' ? '以下で買う' : '以上で売る'}）`);
}
async function trade(asset, qty) {
  qty = Math.trunc(qty);
  if (!qty) return toast('株数を入れてください', 'err');
  if (S.busy) return;
  S.busy = true;
  try { handleActResult(await api('/api/market/trade', withT({ asset, qty }))); } catch (e) { toast(e.message, 'err'); }
  finally { S.busy = false; await refresh(); }
}

/* ---- 内職 (パズル: マインスイーパ・数独・ピクロス・15パズル). 盤面と答え合わせはサーバ */
function openTask() {
  const dlg = $('#task-dlg');
  if (S.view && S.view.task_active && !S.task) {        // やりかけの内職: 続きから (再起動のあとも)
    $('#task-body').replaceChildren(h('p', { class: 'muted' }, 'やりかけの内職を読み込んでいます…'));
    if (!dlg.open) dlg.showModal();                     // 先に開く (盤の大きさは作業画面の幅で決める)
    resumeTask();
    return;
  }
  const why = S.view && S.view.side_job;          // 休憩中・体力不足などで始められない: 先に理由を出す
  if (why) {
    $('#task-sub').textContent = '';
    $('#task-body').replaceChildren(h('p', {}, `🧵 ${why.reason}`),
      h('p', { class: 'muted small' }, '内職は1回ごとに体力を10使い、終わると30分休憩です。'),
      h('button', { class: 'btn', onclick: () => dlg.close() }, '閉じる'));
    if (!dlg.open) dlg.showModal();
    return;
  }
  const cat = (S.boot && S.boot.puzzles) || { kinds: [], levels: [] };
  S.taskLevel = S.taskLevel || 'easy';
  const draw = () => {
    $('#task-sub').textContent = '';
    $('#task-body').replaceChildren(
      h('p', { class: 'muted' }, '知られたパズルを解いて稼ぎます。解けたら難しさに応じた額（仕事スキルで上がる）、速いほど・ミスが少ないほど多め。途中でやめると少しだけ。終わると30分休憩です。'),
      h('div', { class: 'row pz-levels' }, h('span', { class: 'muted small' }, '難しさ'),
        cat.levels.map((l) => h('button', { class: 'btn small' + (S.taskLevel === l.id ? ' primary' : ''), onclick: () => { S.taskLevel = l.id; draw(); } }, l.name))),
      h('div', { class: 'task-pick' }, cat.kinds.map((k) => h('button', { class: 'cmd', onclick: () => startTask(k.id, S.taskLevel) },
        h('b', {}, k.name), h('small', { class: 'muted' }, k.desc)))));
  };
  draw();
  dlg.showModal();
}

async function resumeTask() {
  let tk;
  try { tk = await api('/api/task/resume', {}); } catch (e) { toast(e.message, 'err'); await refresh(); return; }
  beginTask(tk);
  toast('やりかけの内職の続きから', 'ok');
}
async function startTask(kind, level) {
  let tk;
  $('#task-body').replaceChildren(h('p', { class: 'muted' }, '盤面を作っています…'));      // スリザーリンクの難などは数秒かかる
  try { tk = await api('/api/task/start', { kind, level }); } catch (e) { toast(e.message, 'err'); await refresh(); return; }
  beginTask(tk);
}
// 盤の描画と操作 (beginTask / renderTask など) は static/puzzles.js (単独版 puzzle_lab と同じもの)

async function finishTask(gaveUp) {
  const T = S.task;
  if (!T || T.done) return;
  T.done = true;
  clearInterval(T.timer);
  document.removeEventListener('keydown', T.key);
  try {
    const r = await api('/api/task/finish', withT({ token: T.tk.token }));
    const k = r.task;
    T.view = k.view;
    renderTask(h('div', { class: 'task-result' },
      h('div', {}, k.solved ? `✨ できあがり（${fmtSec(k.sec)}${k.fast ? '・速い！' : ''}・ミス ${k.miss}）` : `${k.view && k.view.stuck ? '動かせなくなった' : '途中でやめた'}（${fmtSec(k.sec)}・ミス ${k.miss}）`),
      h('div', { class: 'big' }, yen(k.pay)),
      r.entry && r.entry.skill && r.entry.skill.work ? h('div', { class: 'muted' }, `仕事スキル +${r.entry.skill.work}`) : '',
      r.entry && r.entry.skill && r.entry.skill.write ? h('div', { class: 'muted' }, `文章スキル +${r.entry.skill.write}`) : '',
      h('button', { class: 'btn primary', onclick: () => $('#task-dlg').close() }, '閉じる')));
    handleActResult(r);
  } catch (e) { toast(e.message, 'err'); $('#task-dlg').close(); }
  S.task = null;
  await refresh();
  void gaveUp;
}

function closeTask() {
  const T = S.task;
  if (T && !T.done) {
    if (!confirm('途中でやめますか？（進んだぶんの少しだけ稼げます）')) return;
    finishTask(true);
    return;
  }
  $('#task-dlg').close();
}

const SKILL_HINT = {
  talk: '会話のコマンドの効き目。上がると話が弾みやすく、低いと沈黙することも',
  touch: 'ふれあいのコマンドの効き目。低いうちは、急にするとびっくりされることも',
  cook: '料理・おやつ・お茶の効き目。低いと失敗することも、高いと絶品に',
  work: '仕事のお給料と、内職の単価',
  house: '片付けのはかどり。家事・一緒に掃除・研鑽で伸びる',
  care: '相手の様子の見え方（見た目の印象のずれが小さい・何かあったことに気づきやすい）。様子を見る・何かあった？・相談にのる・研鑽で伸びる',
  groom: '出先で会った人との知り合いやすさ（少しだけ）。出かける・服を買う・研鑽で伸びる',
  budget: '家計簿の覚えのよさ（丸め・書き漏らしが減り、見積もりの幅が狭い）、買い物で少し安く買え衝動買いが減り、品切れのとき代わりの品を選べる。家計簿・買い物・研鑽で伸びる',
  write: '文章の仕事（副業）の依頼の来やすさと出来ばえ。研鑽（文章の書き方の本があると伸びやすい）と文章の仕事で伸びる',
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
  const care = ((S.view || {}).you || {}).care || 0;      // 気配りがあるほど, 印象のずれが小さい
  const fuzz = ((seed % 1000) / 1000 - 0.5) * 2 * (LOOK_FUZZ[p.id] || 10) * (1 - 0.5 * care);
  const n = Math.max(0, Math.min(99.9, ((val + fuzz) - (p.min ?? 0)) / ((p.max ?? 100) - (p.min ?? 0)) * 100));
  return words[Math.floor(n / 20)];
}
function statMode() { return S.peek ? 'exact' : (S.ui.stats || 'exact'); }

// 「誰かと」の「ようす」: 相手のからだ・こころ (表示設定に従う: 数値 / 見た感じ / 隠す) と, いまの気分の理由
function paramRows(params, mode, flash) {
  return (list) => list.map((p) => {
    const val = params[p.id] ?? 0;
    if (mode === 'look') {
      const w = lookWord(p, val);
      return h('div', { class: 'prow look' }, h('span', {}, p.name), h('span', { class: w ? '' : 'muted' }, w || '？（見ただけではわからない）'));
    }
    const pct = ((val - (p.min ?? 0)) / ((p.max ?? 100) - (p.min ?? 0))) * 100;
    const d = flash ? S.lastDeltas[p.id] : null;
    return h('div', { class: 'prow' + (d ? ' flash' : ''), title: p.id },
      h('span', {}, p.name),
      h('div', { class: 'bar' }, h('i', { style: `width:${pct}%;background:${level(p, val)}` })),
      h('span', { class: 'pval' }, d ? `${d > 0 ? '+' : ''}${d}` : Math.round(val)));
  });
}
function renderStatus() {
  const t = T();
  const box = $('#tab-status');
  if (!t) { box.replaceChildren(); return; }
  const groups = [['physical', 'からだ'], ['mental', 'こころ']];
  const others = S.boot.params.filter((p) => !['physical', 'mental'].includes(p.group));
  const mode = statMode();
  const rows = paramRows(t.params, mode, true);
  const sc = t.scene;
  const flags = [sc.asleep && '睡眠中', sc.busy && '手が離せない'].filter(Boolean).join('・');
  const L = t.life || {};
  const reasons = (L.reasons || []).map((r) => h('div', { class: 'reason ' + r.mood },
    h('span', {}, r.mood === 'good' ? '😊' : '😣'),
    h('span', {}, r.tell || '？（まだ聞いていない）'),
    h('span', { class: 'muted small' }, fmtTime(r.t))));
  box.replaceChildren(
    h('div', { class: 'scene-box' },
      h('div', {}, h('b', {}, '時間帯 '), S.view.phase.label),
      h('div', {}, h('b', {}, 'いま '), `${sc.label}（${sc.location || '—'}）`, flags ? `　${flags}` : ''),
      h('div', {}, h('b', {}, '最後のふれあい '), t.absent < 1 ? `${Math.round(t.absent * 60)}分前` : `${t.absent.toFixed(1)}時間前`)),
    h('div', { class: 'pgroup' }, h('h4', {}, 'いまの気分の理由'),
      reasons.length ? reasons : h('div', { class: 'muted small' }, '特になし')),
    (S.ui.stats || 'exact') !== 'exact' ? h('div', { class: 'peek row' },
      h('span', { class: 'muted small' }, S.peek ? '一時的に正確な数値を表示中' : mode === 'look' ? `${t.name}の様子（見た感じ。正確とは限りません）` : `${t.name}のステータスは隠しています`),
      h('div', { class: 'spacer' }),
      h('button', { class: 'btn ghost small', onclick: () => {
        S.peek = !S.peek;
        clearTimeout(S.peekTimer);
        if (S.peek) S.peekTimer = setTimeout(() => { S.peek = false; renderStatus(); }, 60000);
        renderStatus();
      } }, S.peek ? '戻す' : '数値を見る（1分）')) : '',
    ...(mode === 'hidden' ? [] : [
      ...groups.map(([g, label]) => h('div', { class: 'pgroup' }, h('h4', {}, `${t.name}の${label}`), rows(S.boot.params.filter((p) => p.group === g)))),
      others.length ? h('div', { class: 'pgroup' }, h('h4', {}, `${t.name}のその他`), rows(others)) : '']),
  );
  setTimeout(() => { S.lastDeltas = {}; }, 4000);
}

/* ---------------------------------------------------------------- 関係性 tab */
// 知っている人全員: 間柄の段階・最後に会った/連絡した日・あなたが知っていること (好きなもの・聞いた話)・貸し借り・見た目の印象
const KNOWN_LABEL = { like: '好き', dislike: '苦手', heard: '聞いた話' };
function ago(t) {
  if (!t) return '—';
  const d = Math.floor((Date.now() / 1000 - t) / 86400);
  const dt = new Date(t * 1000);
  return d <= 0 ? `今日 ${hhmm(t)}` : d === 1 ? '昨日' : `${d}日前（${dt.getMonth() + 1}/${dt.getDate()}）`;
}
const SCHED_VIA = { talk: '本人から', secondhand: '人づてに', workplace: '職場で見かけた', message: 'メッセージで' };
function renderPeople() {
  const ps = S.view.people || [];
  const box = $('#tab-people');
  const mode = statMode();
  box.replaceChildren(
    h('p', { class: 'hint' }, '知っている人との関係です。見た目の印象は、そばにいる人だけ分かります（離れている人は「？」）。好きなもの・聞いた話・予定は、渡してみた・部屋で見た・本人や人づてに聞いた・見かけたものだけです（予定は変わることもあります）。'),
    ...ps.map((p) => {
      const near = !!p.mode;
      const see = near || S.ui.showApart;
      const face = h('div', { class: 'who-face small' });
      if (p.face) face.style.backgroundImage = `url("${imgUrl(p.face)}")`; else face.textContent = p.name.slice(0, 1);
      const look = see && mode !== 'hidden'
        ? ['mood', 'energy', 'health', 'loneliness'].map((id) => S.boot.params.find((x) => x.id === id)).filter(Boolean)
          .map((x) => (mode === 'look' || !near ? `${x.name}: ${lookWord(x, p.params[x.id] ?? 0) || '？'}` : `${x.name} ${Math.round(p.params[x.id] ?? 0)}`)).join('・')
        : '？（いまは見えない）';
      const likes = p.known.filter((k) => k.kind === 'like' || k.kind === 'dislike');
      const heard = p.known.filter((k) => k.kind === 'heard');
      const stock = p.known.filter((k) => k.kind === 'stock');
      const row = (label, val) => [h('span', { class: 'muted' }, label), h('span', {}, val)];
      return h('div', { class: 'person' + (near ? ' near' : '') },
        h('div', { class: 'person-head' }, face,
          h('div', { style: 'flex:1;min-width:0' },
            h('div', {}, h('b', {}, p.name), h('span', { class: 'tag bond' + (near ? '' : ' apart'), style: 'margin-left:6px' }, `${BOND_IC[p.stage] || ''}${p.stage_label}`),
              near ? h('span', { class: 'tag', style: 'margin-left:4px' }, '👥 そばにいる') : '',
              p.pending_msg ? h('span', { class: 'tag', style: 'margin-left:4px' }, '📱 返信待ち') : ''),
            h('div', { class: 'muted small' }, p.label)),
          p.stage !== 'known' && !near ? h('button', { class: 'btn small', title: 'スマホで連絡する', onclick: () => openChat(p.id) }, '📱') : '',
          h('button', { class: 'btn small ghost', title: 'この人との記録をログで見る', onclick: () => { S.logWho = p.id; showTab('log'); renderLog(); } }, '📜')),
        h('div', { class: 'person-grid small' },
          row('最後に会った', near ? 'いま一緒' : ago(p.last_met)),
          row('最後に連絡した', ago(p.last_contact)),
          row('見た目の印象', look),
          row('好きなもの', likes.length ? likes.map((k) => `${KNOWN_LABEL[k.kind]}: ${k.text}`).join('・') : '？（まだ知らない）'),
          heard.length ? row('聞いた話', heard.slice(0, 4).map((k) => h('div', {}, `${ago(k.t)}　${k.text}`))) : '',
          stock.length ? row('株の噂', stock.slice(0, 3).map((k) => h('div', {}, `${ago(k.t)}　${k.text}（${k.about ? `${k.about}のことを人づてに` : k.via === 'message' ? 'メッセージで' : '本人から'}）`))) : '',
          (p.sched || []).length ? row('予定について', p.sched.slice(0, 6).map((k) => h('div', { class: k.stale || k.old ? 'muted' : '' },
            `${k.text}（${SCHED_VIA[k.via] || '聞いた'}・${ago(k.t)}）`, k.stale ? h('span', { class: 'tag', style: 'margin-left:4px' }, 'もう違うかも') : k.old ? h('span', { class: 'tag', style: 'margin-left:4px' }, '前に聞いた話') : ''))) : '',
          p.owed ? row('貸し借り', h('span', { class: 'down' }, `あなたが ${yen(p.owed)} 借りている`)) : '',
          p.living_policy ? row('生活費', { split: '折半', me: 'あなたが払う', her: `${p.name}が払う` }[p.living_policy] || '') : ''));
    }),
    ps.length ? '' : h('p', { class: 'muted' }, 'まだ知っている人がいません。出かけると、偶然だれかに会うことがあります。'));
}

/* ---------------------------------------------------------------- log tab */
// あなたの 1 本の時系列 (一人の時間・外出・連絡も同じ流れで). 人で絞り込める
function logItem(e) {
  const th = h('div', { class: 'log-thumb' });
  if (e.image) th.style.backgroundImage = `url("${imgUrl(e.image)}")`;
  else th.textContent = e.job ? '⏳' : e.error ? '⚠' : (e.icon || '•');
  return h('div', { class: 'log-item' + (S.current && S.current.id === e.id ? ' cur' : '') + (e.mine ? ' mine' : ''), 'data-id': e.id,
    onclick: () => (e.who && (S.view.company || []).some((c) => c.id === e.who) ? showEntry(e, false)
      : e.image ? openLightbox(e, { path: e.image, seed: e.seed, pos: e.pos, neg: e.neg, t: e.t }) : null) },
    th,
    h('div', { class: 'log-main' },
      h('div', { class: 'log-head' }, h('span', {}, fmtTime(e.t)), h('span', { class: 'log-who' }, e.mine ? 'あなた' : e.who_name || ''),
        h('span', {}, `${e.icon || ''}${e.action_name}`), h('span', {}, e.apart && e.action !== 'call' && !S.ui.showApart ? '' : e.scene || '')),
      h('div', { class: 'log-text' }, e.text || '—')));
}

async function renderLog() {
  const v = S.view;
  const box = $('#tab-log');
  const who = S.logWho || '';
  const sel = h('select', { class: 'char-select', onchange: (ev) => { S.logWho = ev.target.value; renderLog(); } },
    h('option', { value: '' }, 'みんな（あなたの記録すべて）'), h('option', { value: 'me', selected: who === 'me' }, '🧍 一人の時間だけ'),
    (v.people || []).map((p) => h('option', { value: p.id, selected: who === p.id }, `${BOND_IC[p.stage] || ''} ${p.name}`)));
  let items = v.log, total = v.log_total;
  if (who) {
    try { const r = await api(`/api/log?who=${encodeURIComponent(who)}&offset=0&limit=60`); items = r.items; total = r.total; } catch (e) { toast(e.message, 'err'); }
  }
  box.replaceChildren(h('div', { class: 'row log-filter' }, h('span', { class: 'muted small' }, '絞り込み'), sel), ...items.map(logItem));
  if (total > items.length) {
    let offset = items.length;
    const more = h('div', { class: 'center' }, h('button', { class: 'btn ghost', onclick: async () => {
      const r = await api(`/api/log?offset=${offset}&limit=60${who ? '&who=' + encodeURIComponent(who) : ''}`);
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
  $('#lb-stage').hidden = $('#lb-delete').hidden = false;
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

// 服の一覧のサンプル画像を大きく見る (ギャラリーと同じ拡大表示)
function openSampleLightbox(o) {
  $('#lb-img').src = imgUrl(o.sample);
  $('#lb-open').href = imgUrl(o.sample);
  $('#lb-text').textContent = `${o.icon || '👕'} ${o.name}（サンプル）`;
  $('#lb-meta').textContent = `${((S.boot.outfits || {}).kinds || {})[o.kind] || ''}・大胆さ ${o.bold || 0}`;
  $('#lb-prompt').textContent = `服装: ${o.pos}${o.neg ? '\n\nNegative: ' + o.neg : ''}`;
  $('#lb-stage').hidden = $('#lb-delete').hidden = true;
  $('#lightbox').showModal();
}

/* ================================================================= settings */
const SEC = {};
let SE = {}; // 編集中のワーキングコピー

// 設定で編集するキャラ: 前に選んだ人 → 「誰かと」の相手 → 最後に選んだ相手
async function editChar() {
  const id = S.editCid || tid() || S.boot.character.id;
  if (id === S.boot.character.id) return clone(S.boot.character);
  try { return clone((await api('/api/character?id=' + encodeURIComponent(id))).character); } catch (e) { return clone(S.boot.character); }
}
async function openSettings(sec) {
  SE = {
    settings: clone(S.boot.settings), char: await editChar(), actions: clone(S.boot.actions),
    params: clone(S.boot.params), world: clone(S.boot.world), selAction: SE.selAction || 0,
  };
  $('#settings-dlg').showModal();
  showSection(sec || SE.sec || 'char');
}
// キャラごとの設定: 「キャラクター」の中のタブ (上に編集するキャラの選択). ほかは全体の設定
const CHAR_SECS = [['char', '基本・外見'], ['schedule', '生活スケジュール'], ['wardrobe', '着せ替え']];
function charHead(cur) {
  const c = SE.char;
  return h('div', { class: 'char-head' },
    h('div', { class: 'row' }, h('span', { class: 'muted small' }, '編集するキャラ'),
      h('select', { onchange: (ev) => editDefinition(ev.target.value) },
        [['このワールドにいる', true], ['このワールドにはいない（定義だけ）', false]].map(([label, here]) => {
          const xs = allDefs().filter((x) => x.here === here);
          return xs.length ? h('optgroup', { label }, xs.map((x) => h('option', { value: x.id, selected: x.id === c.id }, x.name))) : '';
        }))),
    h('div', { class: 'seg char-tabs' }, CHAR_SECS.map(([id, label]) => h('button', { class: id === cur ? 'on' : '', onclick: () => showSection(id) }, label))));
}
function showSection(sec) {
  SE.sec = sec;
  hideTip();
  const navSec = CHAR_SECS.some(([id]) => id === sec) ? 'char' : sec;
  $$('#snav button').forEach((b) => b.classList.toggle('on', b.dataset.sec === navSec));
  const body = $('#sbody');
  body.replaceChildren(...[SEC[sec]()].flat().filter((x) => x != null && x !== false));
  const head = $('.sbar h3', body);
  if (head) head.after(h('button', { class: 'btn ghost', title: 'この画面の説明（説明書）', onclick: () => openManual('sec-' + sec) }, '📖'));
  body.scrollTop = 0;
}
async function reloadAll(sec) {
  await loadBoot();
  SE.settings = clone(S.boot.settings); SE.char = await editChar();
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
// 閉じていた間のまとめ: 予定ごとに, 予定どおり / 代わりに何をしたか (理由つき) / 何もしなかった, 切り上げた
function planNote(x) {
  const p = x.plan;
  if (!p) return '';
  const at = p.at ? `${p.at}の予定「${p.orig}」` : '予定なし';
  const s = p.src === 'plan' ? `📌 予定どおり${p.cut ? '（次の予定の時刻で切り上げた）' : ''}`
    : p.src === 'appoint' ? '📅 約束（約束が先）'
    : p.src === 'fallback' ? `↪ ${p.at ? `${at}は${p.why}ので、` : '空き時間なので、'}未指定時コマンドの「${p.label}」に`
    : p.src === 'routine' ? `↪ ${at}は${p.why}ので、設定の行動パターンに`
    : `✕ ${at}は${p.why}ので、何もしなかった`;
  return h('div', { class: 'muted' }, '　' + s);
}
// 予定 (画面を閉じている間の過ごし方を日ごとに. core/planner.py): 予定 → 未指定時コマンド (優先度順) → 設定の行動パターン → 何もしない
function commandPicker(b, redraw) {
  const L = (S.boot.routine || {}).labels || {};
  const od0 = (S.view || {}).outdoor || {};
  const ch = Object.assign({}, od0.choices || {}, { out: od0.routine_choices || (od0.choices || {}).out || [] });
  const pl = od0.places || {};
  const skills = ((S.view || {}).solo || {}).skills || {};
  const MH = (S.boot.routine || {}).meal_how || {}, MP = (S.boot.routine || {}).meal_places || {};
  const sel = (key, opts, after) => h('select', { onchange: (ev) => { b[key] = ev.target.value; if (after) after(); redraw(); } },
    opts.map(([v, l]) => h('option', { value: v, selected: b[key] === v }, l)));
  const placeOpt = (x) => [x, `${(pl[x] || {}).icon || ''}${(pl[x] || {}).label || x}${(pl[x] || {}).hours && pl[x].hours !== '24時間' ? '（' + pl[x].hours + '）' : ''}`];
  return [
    sel('do', Object.entries(L), () => {
      if (ch[b.do]) b.place = b.place && ch[b.do].includes(b.place) ? b.place : ch[b.do][0]; else delete b.place;
      if (b.do === 'practice') b.skill = b.skill || 'talk'; else delete b.skill;
      if (b.do === 'meal') { b.how = b.how || 'cook'; } else delete b.how;
    }),
    b.do === 'meal' ? sel('how', Object.entries(MH), () => { const ps = MP[b.how]; if (ps) b.place = ps.includes(b.place) ? b.place : ps[0]; else delete b.place; }) : '',
    b.do === 'meal' && MP[b.how] ? sel('place', MP[b.how].map(placeOpt)) : '',
    ch[b.do] ? sel('place', ch[b.do].map(placeOpt)) : '',
    b.do === 'practice' ? sel('skill', Object.entries(skills)) : ''];
}
const STREET_POLICY = [['', '無難に（会釈・通り過ぎる）'], ['chat', '応じて立ち話する'], ['nod', '軽く会釈する'], ['decline', '急いでいると断る']];
const REPLY_POLICY = [['', '返さない（あとで手で返す）'], ['cheerful', '明るく乗る'], ['expand', '話を広げる'], ['worry', '心配する'], ['tease', 'からかう'], ['curt', '素っ気なく']];
function planSection(v) {
  const P = v.plan;
  if (!P) return null;
  const redraw = () => renderSoloTab();
  const f = S.planForm = S.planForm || { date: P.dates[1] || P.dates[0], at: '09:00', do: 'out', place: 'supermarket' };
  if (S.planEdit && !P.items.some((y) => y.id === S.planEdit)) S.planEdit = null;      // 書き換え中の予定が消えた (過ぎた・消した)
  const editing = !!S.planEdit;
  if (!P.dates.includes(f.date)) f.date = P.dates[0];
  const fb = S.fbForm = S.fbForm || { do: 'rest' };
  const md = (d) => { const [, m, dd] = d.split('-'); return `${+m}/${+dd}`; };
  const call = async (path, body) => { if (S.busy) return false; S.busy = true; let ok = false; try { await api(path, body); ok = true; } catch (e) { toast(e.message, 'err'); } finally { S.busy = false; await refresh(); } return ok; };
  const clash = P.appoints.find((a) => a.date === f.date && Math.abs((+a.at.slice(0, 2) * 60 + +a.at.slice(3)) - (+f.at.slice(0, 2) * 60 + +f.at.slice(3))) < 150);
  const byDate = P.dates.map((d) => [d, P.items.filter((x) => x.date === d), P.appoints.filter((a) => a.date === d)]);
  const order = (i, dir) => { const xs = P.fallback.map((x) => ({ do: x.do, place: x.place, how: x.how, skill: x.skill })); const j = i + dir; if (j < 0 || j >= xs.length) return; [xs[i], xs[j]] = [xs[j], xs[i]]; call('/api/plan/fallback', { items: xs }); };
  return h('details', { class: 'cat plan', open: !!S.planOpen, ontoggle: (ev) => { S.planOpen = ev.target.open; } },
    h('summary', { class: 'cat-title' }, `🗓 予定（画面を閉じている間）${P.items.length ? `　${P.items.length}件` : ''}`),
    h('p', { class: 'hint' }, `${P.horizon}日先まで組めます（段取りのスキル ${P.skill}。上がると先まで）。予定のコマンドができなければ、未指定時コマンドを上から順に、それもできなければ設定の行動パターン。約束の時刻は約束が先です。画面を開いているときは、時刻になっても知らせるだけです。`),
    ...byDate.map(([d, xs, as]) => (xs.length || as.length) ? h('div', { class: 'plan-day' }, h('b', {}, md(d)),
      ...as.map((a) => h('div', { class: 'plan-row muted' }, `📅 ${a.at} ${a.name}との約束（${a.place}）`)),
      ...xs.map((x) => h('div', { class: 'plan-row' + (S.planEdit === x.id ? ' editing' : '') }, h('span', {}, `${x.at} ${x.label}`),
        h('span', {}, h('button', { class: 'btn small ghost', disabled: S.busy, title: '下の欄に読み込んで書き換える',
          onclick: () => { S.planEdit = x.id; S.planForm = { date: x.date, at: x.at, do: x.do, place: x.place, how: x.how, skill: x.skill }; redraw(); } }, '✎'),
        h('button', { class: 'btn small ghost danger', disabled: S.busy, onclick: () => { if (S.planEdit === x.id) S.planEdit = null; call('/api/plan/remove', { id: x.id }); } }, '×'))))) : ''),
    h('div', { class: 'row plan-form', style: 'flex-wrap:wrap;gap:6px' },
      h('select', { onchange: (ev) => { f.date = ev.target.value; redraw(); } }, P.dates.map((d, i) => h('option', { value: d, selected: d === f.date }, `${md(d)}${i === 0 ? '（今日）' : i === 1 ? '（明日）' : ''}`))),
      h('input', { type: 'time', value: f.at, onchange: (ev) => { f.at = ev.target.value; redraw(); } }), ...commandPicker(f, redraw),
      h('button', { class: 'btn small primary', disabled: S.busy || !!clash, title: clash ? `${clash.at}に${clash.name}との約束があります` : '',
        onclick: async () => { const rep = editing ? S.planEdit : undefined;
          if (await call('/api/plan/add', { date: f.date, at: f.at, replace: rep, item: { do: f.do, place: f.place, how: f.how, skill: f.skill } }) && rep) { S.planEdit = null; redraw(); } } }, editing ? '✔ 書き換える' : '＋予定に足す'),
      editing ? h('button', { class: 'btn small ghost', onclick: () => { S.planEdit = null; redraw(); } }, 'やめる') : ''),
    clash ? h('div', { class: 'muted small' }, `⚠ ${clash.at}に${clash.name}との約束（${clash.place}）があります。約束が先です`) : '',
    h('div', { class: 'sect' }, '未指定時コマンド（上から順に）'),
    ...P.fallback.map((x, i) => h('div', { class: 'plan-row' }, h('span', {}, `${i + 1}. ${x.label}`),
      h('span', {}, h('button', { class: 'btn small ghost', onclick: () => order(i, -1) }, '↑'), h('button', { class: 'btn small ghost', onclick: () => order(i, 1) }, '↓'),
        h('button', { class: 'btn small ghost danger', onclick: () => call('/api/plan/fallback', { items: P.fallback.filter((_, j) => j !== i).map((y) => ({ do: y.do, place: y.place, how: y.how, skill: y.skill })) }) }, '×')))),
    h('div', { class: 'row', style: 'flex-wrap:wrap;gap:6px' }, ...commandPicker(fb, redraw),
      h('button', { class: 'btn small', disabled: S.busy, onclick: () => call('/api/plan/fallback', { items: P.fallback.map((y) => ({ do: y.do, place: y.place, how: y.how, skill: y.skill })).concat([{ do: fb.do, place: fb.place, how: fb.how, skill: fb.skill }]) }) }, '＋足す')),
    h('div', { class: 'sect' }, '自動の応答（閉じている間）'),
    h('p', { class: 'hint' }, 'その場にいないので、手で選ぶより効き目は弱く、相手の様子を読み違えることもあります。'),
    h('div', { class: 'row', style: 'flex-wrap:wrap;gap:6px' },
      h('label', { class: 'small' }, '出先でばったり ', h('select', { onchange: (ev) => call('/api/plan/auto', { street: ev.target.value, reply: P.auto.reply || '' }) },
        STREET_POLICY.map(([k, l]) => h('option', { value: k, selected: (P.auto.street || '') === k }, l)))),
      h('label', { class: 'small' }, '届いたメッセージ ', h('select', { onchange: (ev) => call('/api/plan/auto', { street: P.auto.street || '', reply: ev.target.value }) },
        REPLY_POLICY.map(([k, l]) => h('option', { value: k, selected: (P.auto.reply || '') === k }, l))))));
}

function routineEditor(days) {
  const L = (S.boot.routine || {}).labels || {};
  const od0 = (S.view || {}).outdoor || {};
  const ch = Object.assign({}, od0.choices || {}, { out: od0.routine_choices || (od0.choices || {}).out || [] });   // 人の家は行動パターンには入れない
  const pl = od0.places || {};
  const skills = ((S.view || {}).solo || {}).skills || {};
  const MH = (S.boot.routine || {}).meal_how || {}, MP = (S.boot.routine || {}).meal_places || {};
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
        if (b.do === 'meal') b.how = b.how || 'cook'; else delete b.how;
      }),
      // 食事: 自炊 (食材があれば) / 外食 (行き先. 営業時間に従う) / 買って食べる
      b.do === 'meal' ? sel(b, 'how', Object.entries(MH), () => { const ps = MP[b.how]; if (ps) b.place = ps.includes(b.place) ? b.place : ps[0]; else delete b.place; }) : '',
      b.do === 'meal' && MP[b.how] ? sel(b, 'place', MP[b.how].map((x) => [x, `${(pl[x] || {}).icon || ''}${(pl[x] || {}).label || x}${(pl[x] || {}).hours && pl[x].hours !== '24時間' ? '（' + pl[x].hours + '）' : ''}`])) : '',
      ch[b.do] ? sel(b, 'place', ch[b.do].map((x) => [x, `${(pl[x] || {}).icon || ''}${(pl[x] || {}).label || x}${(pl[x] || {}).hours && pl[x].hours !== '24時間' ? '（' + pl[x].hours + '）' : ''}`])) : '',
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
      h('button', { class: 'btn ghost', title: 'このキャラの定義を JSON で保存（データ → キャラクターを読込 で戻せる）', onclick: () => downloadJson(`character_${c.id}.json`, c) }, '書き出す'),
      h('button', { class: 'btn', onclick: newCharacterDialog }, '＋新規'))),
    charHead('char'),
    h('p', { class: 'lead' }, 'キャラクターの定義（名前・外見・性格・服・スケジュールなど）は全ワールド共通で、ここでの変更は全ワールドに反映されます。状態・ログ・あなたとの間柄・キャラ同士の関係はワールドごとです。どこかのワールドに現れている（知り合っている）キャラは削除できません。外見の SD プロンプトは保存のたびに履歴へ残り、いつでも復元できます。あなた自身の情報は「あなた」で設定します。'),
    h('div', { class: 'grid4' },
      fld('名前', inp(c, 'name')),
      fld('年齢（任意）', inp(c, 'age', { type: 'number' }), '18 歳未満を入れると「ポーズを取って」「見せて」と相手からの持ちかけは出ません（空欄は大人として扱う）'),
      fld('一人称（固定）', inp(c, 'first_person', { ph: `空欄＝プリセット（${(curPersona(c) || {}).first_person || '私'}）` }),
        '空欄なら性格プリセットに従う'),
      fld('あなたの呼び方（固定）', inp(c, 'player_call', { ph: `空欄＝プリセット（${(curPersona(c) || {}).player_call || '{player}'}）` }),
        '{player} = あなたの名前。空欄なら性格プリセットに従う')),
    likesEditor(c),
    h('div', { class: 'sect' }, '外見プロンプト'),
    iconRow(c),
    fld('Positive（外見・固有の特徴）', posEl),
    fld('Negative', negEl),
    fld('普段の服装（スケジュールで未指定のとき）', outfitInput(c, 'outfit_default')),
    fld('お出かけ着（散歩などで外に出るとき）', outfitInput(c, 'outfit_outing'), '部屋着やパジャマのまま出かけないよう、外出時はこの服になります（着せ替えで「外に着ていける」服を選んでいればそちら）'),
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

// 顔だけのアイコン (トーク・関係性の顔). 一度だけ作って定義に固定. 作り直しは外見を変えたあとなどに
function iconRow(c) {
  const face = h('div', { class: 'who-face' });
  const hint = h('span', { class: 'hint' });
  const btn = h('button', { class: 'btn' });
  const show = () => {
    if (c.icon) { face.style.backgroundImage = `url("${imgUrl(c.icon)}")`; face.textContent = ''; } else face.textContent = (c.name || '?').slice(0, 1);
    hint.textContent = c.icon ? '顔のアイコン（トーク・関係性に出ます）' : 'まだ顔のアイコンがありません（それまではいちばん新しい画像を使います）';
    btn.textContent = c.icon ? '作り直す' : '作る';
  };
  // できたらこの欄の顔を入れ替え, 画面の顔 (トーク・関係性) も読み直す
  const watch = (jid) => {
    const tick = async () => {
      const j = await api('/api/job?id=' + jid).catch(() => null);
      if (j && j.status === 'done') { c.icon = j.image; show(); toast(`${c.name || ''}の顔のアイコンができました`, 'ok'); refresh(); return; }
      if (j && ['error', 'cancelled', 'unknown'].includes(j.status)) { if (j.error) toast('顔のアイコン: ' + j.error, 'err'); return; }
      setTimeout(tick, 1500);
    };
    setTimeout(tick, 1500);
  };
  btn.onclick = async () => {
    try {
      const r = await api('/api/character/icon', { id: c.id });
      toast('顔のアイコンを作っています（保存済みの外見で。できたら入れ替わります）', 'ok');
      if (r && r.job) watch(r.job);
    } catch (e) { toast(e.message, 'err'); }
  };
  show();
  return h('div', { class: 'row', style: 'align-items:center;gap:10px;margin:6px 0' }, face, hint, btn);
}

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
  S.editCid = id;
  try {
    SE.char = clone((await api('/api/character?id=' + encodeURIComponent(id))).character); SE.rels = null;
    showSection(CHAR_SECS.some(([x]) => x === SE.sec) ? SE.sec : 'char');
  }
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
  if (!ps.some((p) => p.id === SE.personaSel)) SE.personaSel = (ps[0] || {}).id;      // キャラの選択とは別. 前に開いた性格のまま
  const pick = h('select', { onchange: (ev) => { SE.personaSel = ev.target.value; SE.personaData = null; showSection('personas'); } },
    ps.map((p) => h('option', { value: p.id }, p.name + (p._custom ? '（編集済み）' : ''))));
  pick.value = SE.personaSel || '';
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
          'rate 基本変化の倍率 / drift 自然回帰の目標の加算 / drift_speed 戻る速さの倍率 / gain うれしい方向・hurt つらい方向の変化の倍率（パラメータ id ごと）/ approach 話しかけてくる多さ / absence 黙って離れられたときの堪え方 / jealousy ほかの人との仲に気づいたときの嫉妬の強さ / caution 段階の提案への慎重さ（ready に加算）/ gift 贈り物の効き目の倍率 / money お金・高価な物の受け止め方（money_feel に加算）/ neat きれい好き（-10〜10。家の散らかりを気にする・片付いていると好印象を持ちやすい）/ carer 世話焼き（0〜1。散らかっていると片付けを手伝い出す） / punctual 時間を守る（0〜1。低いほど約束に遅れたり来なかったりする）',
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
    opts.days ? fld('勤め先（行き先）', inp(e, 'workplace', { type: 'select', options: [['', 'なし'],
      ...Object.entries((S.view && S.view.outdoor && S.view.outdoor.places) || {}).map(([id, p]) => [id, p.label || id])] }),
      'この時間にあなたがこの行き先へ行くと、店員として働いているのに出会います（予定を知るきっかけになります）') : null,
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
  if (!SE.schedOk) {      // 遊んでいる画面では相手の予定は分からないもの. 作る人の画面なので, 開く前に一言
    return [h('div', { class: 'sbar' }, h('h3', {}, `${c.name}の生活スケジュール`)), charHead('schedule'), h('div', { class: 'card' },
      h('p', {}, '⚠ ここは作る人のための画面です。遊ぶときに見ると、相手の予定が分かってしまいます。'),
      h('p', { class: 'muted small' }, '遊んでいるあいだの相手の予定は、話のついで・人づて・職場で見かける・メッセージなどで、少しずつ「関係性」に分かっていきます。'),
      h('button', { class: 'btn', onclick: () => { SE.schedOk = true; showSection('schedule'); } }, '分かったうえで開く'))];
  }
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
    charHead('schedule'),
    c.schedule.some((e) => e.asleep) ? '' : h('p', { class: 'hint' }, '⚠ 睡眠（状態の「睡眠」）の予定がありません。このままだと 1:00〜7:00 は寝ていることにします（予定が一致しない時間だけ）。'),
    h('p', { class: 'lead' }, '実際の時刻に合わせて、上から順に最初に一致した予定が「いまの場面」になります。どれにも一致しなければ「普段」が使われます。日をまたぐ予定（22:00〜02:00 など）も書けます。毎時の効果は滞在 1 時間あたりのパラメータ変化です。'),
    paramKeysHint(),
    h('div', { class: 'sect' }, '普段（予定のない時間）'),
    h('div', { class: 'card' }, sceneFields(c.default_activity)),
    h('div', { class: 'sect' }, '予定'),
    list,
    h('button', { class: 'btn', onclick: () => { c.schedule.push({ days: 'all', from: '10:00', to: '11:00', activity: 'new', label: '新しい予定', location: '', pos: '', neg: '', effects: {} }); draw(); } }, '＋予定を追加'),
  ];
};

/* ---- 着せ替え (その人の持っている服) */
const boldMark = (b) => (b ? ' ' + '🔥'.repeat(b) : '');
const OWNED_FROM = { default: '最初から', player: 'あなたが贈った', self: '自分で買った' };
SEC.wardrobe = () => {
  const c = SE.char;
  const all = ((S.boot.outfits || {}).items) || [];
  c.clothes = c.clothes || [];
  c.dress_reset_on_sleep = c.dress_reset_on_sleep !== false;
  const list = h('div');
  const draw = () => {
    list.replaceChildren(...all.map((o) => {
      const own = c.clothes.find((x) => x.id === o.id);
      return h('div', { class: 'card' + (own ? '' : ' off') },
        h('div', { class: 'card-head', style: 'flex-wrap:wrap' },
          h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: !!own, onchange: (ev) => {
            if (ev.target.checked) c.clothes.push({ id: o.id, from: 'default', t: Date.now() / 1000 });
            else c.clothes = c.clothes.filter((x) => x.id !== o.id);
            draw();
          } }), ` ${o.icon || '👕'} ${o.name}${boldMark(o.bold)}`),
          h('span', { class: 'muted small' }, (S.boot.outfits.kinds || {})[o.kind] || ''),
          own ? h('span', { class: 'muted small' }, OWNED_FROM[own.from] || '') : ''),
        own ? h('details', {}, h('summary', { class: 'muted small' }, `${c.name}用にプロンプトを上書き（体型などで見え方を変えたいときだけ）`),
          h('div', { class: 'grid4' },
            fld('Positive（空欄なら一覧のまま）', inp(own, 'pos', { type: 'textarea', rows: 2, ph: o.pos }), null, 'span2'),
            fld('Negative', inp(own, 'neg', { type: 'textarea', rows: 2, ph: o.neg }), null, 'span2'))) : '');
    }));
  };
  draw();
  return [
    saveBar(`${c.name}の着せ替え`, async () => { await api('/api/character/save', { data: c }); await reloadAll('wardrobe'); }),
    charHead('wardrobe'),
    h('p', { class: 'lead' }, `${c.name}が持っている服です。着せ替えタブには、持っている服だけが並びます。服そのもの（名前・プロンプト・大胆さ・季節など）は「服の一覧」で全員共通に編集します。持っている服は、あなたが店で買って贈る（受け取るかは大胆さ・仲・好みしだい）か、本人が自分で買うことでも増えます。頼まれていないときは、本人が気分・季節・天気で普段着や外出の服を選ぶこともあります。`),
    h('div', { class: 'row', style: 'margin-bottom:10px' }, chk(c, 'dress_reset_on_sleep', '寝たらスケジュール通りの服に戻す')),
    list,
  ];
};

/* ---- 服の一覧 (全体で 1 つ) */
SEC.outfits = () => {
  const O = S.boot.outfits || { items: [], kinds: {}, seasons: {}, bold: [] };
  const items = SE.outfits = SE.outfits || clone(O.items);
  const st = SE.settings;
  st.images = st.images || {};
  const list = h('div');
  const sampleBox = (o) => {
    const im = h('div', { class: 'who-face', style: 'width:96px;height:128px;border-radius:8px' + (o.sample ? ';cursor:zoom-in' : ''),
      title: o.sample ? '押すと大きく表示' : '', onclick: () => { if (o.sample) openSampleLightbox(o); } });
    if (o.sample) im.style.backgroundImage = `url("${imgUrl(o.sample)}")`; else im.textContent = o.icon || '👕';
    return h('div', { class: 'row', style: 'align-items:center;gap:10px;flex-wrap:wrap' }, im,
      h('button', { class: 'btn', onclick: async () => {
        try {
          const r = await api('/api/outfit/sample', { id: o.id });
          toast('サンプル画像を作っています（保存済みの服装で）', 'ok');
          watchSample(r.job, o);
        } catch (e) { toast(e.message, 'err'); }
      } }, o.sample ? 'サンプル画像を作り直す' : 'サンプル画像を作る'));
  };
  const watchSample = (jid, o) => {
    const tick = async () => {
      const j = await api('/api/job?id=' + jid).catch(() => null);
      if (j && j.status === 'done') { o.sample = j.image; toast(`「${o.name}」のサンプル画像ができました`, 'ok'); draw(); return; }
      if (j && ['error', 'cancelled', 'unknown'].includes(j.status)) { if (j.error) toast('サンプル画像: ' + j.error, 'err'); return; }
      setTimeout(tick, 1500);
    };
    setTimeout(tick, 1500);
  };
  const seasons = (o) => h('div', { class: 'row' }, Object.entries(O.seasons).map(([k, label]) => h('label', { class: 'check' },
    h('input', { type: 'checkbox', checked: (o.seasons || []).includes(k), onchange: (ev) => {
      o.seasons = (o.seasons || []).filter((x) => x !== k).concat(ev.target.checked ? [k] : []);
    } }), label)), h('span', { class: 'muted small' }, '（どれも付けなければ通年）'));
  const draw = () => {
    list.replaceChildren(...items.map((o, i) => h('div', { class: 'card' },
      h('div', { class: 'card-head', style: 'flex-wrap:wrap' }, h('b', { style: 'white-space:nowrap' }, `${o.icon || '👕'} ${o.name || o.id}${boldMark(o.bold)}`), h('code', { class: 'muted small' }, o.id),
        h('div', { class: 'spacer' }),
        h('button', { class: 'btn ghost', onclick: () => { moveIn(items, i, -1); draw(); } }, '↑'),
        h('button', { class: 'btn ghost', onclick: () => { moveIn(items, i, 1); draw(); } }, '↓'),
        h('button', { class: 'btn ghost', onclick: () => { const n = clone(o); n.id += '_copy'; n.name += '（複製）'; delete n.sample; items.splice(i + 1, 0, n); draw(); } }, '複製'),
        h('button', { class: 'btn ghost danger', onclick: () => { if (confirm(`「${o.name}」を一覧から消しますか？（持っている人の着せ替えからも外れます）`)) { items.splice(i, 1); draw(); } } }, '削除')),
      sampleBox(o),
      h('div', { class: 'grid4' },
        fld('id', inp(o, 'id'), '反応の条件 outfit=… で使う'), fld('名前', inp(o, 'name')), fld('アイコン', inp(o, 'icon')),
        fld('種類', inp(o, 'kind', { type: 'select', options: Object.entries(O.kinds) })),
        fld('大胆さ', inp(o, 'bold', { type: 'select', options: O.bold.map((l, b) => [String(b), `${b} ${l}`]), parse: Number })),
        h('div', { class: 'fld' }, h('span', { class: 'fl' }, '外出'), chk(o, 'outing_ok', '外に着ていける')),
        fld('値段（0 で店に並べない）', inp(o, 'price', { type: 'number' })),
        fld('売っている店', inp(o, 'places', { fmt: (v) => (v || []).join(', '), parse: (v) => v.split(/[,、\s]+/).filter(Boolean) }), 'mall, shopping_street など'),
        h('div', { class: 'fld spanall' }, h('span', { class: 'fl' }, '季節'), seasons(o)),
        fld('着られる条件', inp(o, 'when', { ph: 'affection>=40' })),
        fld('Positive（服装）', inp(o, 'pos', { type: 'textarea', rows: 2 }), null, 'span2'),
        fld('Negative', inp(o, 'neg', { type: 'textarea', rows: 2 }), null, 'span2')))));
  };
  draw();
  return [
    saveBar('服の一覧', async () => {
      await api('/api/outfits', { items });
      await api('/api/settings', { settings: { images: st.images } });
      SE.outfits = null; await reloadAll('outfits');
    }),
    h('p', { class: 'lead' }, '服の一覧は全員共通です（コマンドや性格プリセットと同じ考え方）。キャラクターは、この中から「持っている服」を持ちます（設定 → キャラクター → 着せ替え）。大胆さは 0 ふつう〜3 かなり大胆で、大胆な服を着てくれるかは、好感度・信頼・間柄・性格の恥じらい・その日の機嫌・場所しだいです（仲が深くても断られることはあり、しつこく頼むと怒ります）。値段を付けた服は店（売っている店）で買え、持ち物からプレゼントにできます。'),
    fld('サンプル画像のプロンプト', inp(st.images, 'sample_prompt', { type: 'textarea', rows: 3, ph: O.sample_prompt }),
      '{outfit} がその服の服装（Positive）に置き換わります。空欄なら既定。共通プロンプトの前置きも付きます'),
    list,
    h('button', { class: 'btn', onclick: () => { items.push({ id: 'outfit' + Date.now().toString(36), name: '新しい服', icon: '👕', kind: 'casual', bold: 0, outing_ok: false, seasons: [], price: 0, places: ['mall'], when: '', pos: '', neg: '' }); draw(); } }, '＋服を追加'),
  ];
};

/* ---- ポーズ・見せての一覧 (全体で 1 つ) */
SEC.poses = () => {
  const P = S.boot.poses || { items: [], types: {} };
  const items = SE.poses = SE.poses || clone(P.items);
  const list = h('div');
  const draw = () => {
    list.replaceChildren(...items.map((o, i) => h('div', { class: 'card' },
      h('div', { class: 'card-head', style: 'flex-wrap:wrap' }, h('b', { style: 'white-space:nowrap' }, `${o.icon || '📸'} ${o.name || o.id}${boldMark(o.bold)}`),
        h('span', { class: 'muted small' }, P.types[o.type] || ''), h('code', { class: 'muted small' }, o.id), h('div', { class: 'spacer' }),
        h('button', { class: 'btn ghost', onclick: () => { moveIn(items, i, -1); draw(); } }, '↑'),
        h('button', { class: 'btn ghost', onclick: () => { moveIn(items, i, 1); draw(); } }, '↓'),
        h('button', { class: 'btn ghost danger', onclick: () => { items.splice(i, 1); draw(); } }, '削除')),
      h('div', { class: 'grid4' },
        fld('id', inp(o, 'id')), fld('名前', inp(o, 'name')), fld('アイコン', inp(o, 'icon')),
        fld('種類', inp(o, 'type', { type: 'select', options: Object.entries(P.types) })),
        fld('大胆さ', inp(o, 'bold', { type: 'select', options: ((S.boot.outfits || {}).bold || []).map((l, b) => [String(b), `${b} ${l}`]), parse: Number })),
        h('div', { class: 'fld' }, h('span', { class: 'fl' }, '場所'), chk(o, 'outside_ok', '外でも頼める')),
        fld('Positive（ポーズ・「〜 focus」）', inp(o, 'pos', { type: 'textarea', rows: 2 }), null, 'span2'),
        fld('Negative', inp(o, 'neg', { type: 'textarea', rows: 2 }), null, 'span2')))));
  };
  draw();
  return [
    saveBar('ポーズ・見せて', async () => { await api('/api/poses', { items }); SE.poses = null; await reloadAll('poses'); }),
    h('p', { class: 'lead' }, '「ポーズを取って」「見せて」で頼めるものの一覧です（全員共通）。18 歳未満と設定したキャラは対象外です（判定は年齢の欄だけ。空欄なら大人として扱います）。受けてくれるかは、着せ替えの大胆さと同じく、好感度・信頼・間柄・恥じらい・機嫌・場所しだいで、しつこく頼むと怒らせます。見せては「eye focus」のように「〜 focus」の形で書きます。キャラは頼まれたもの・感想の選び方から、あなたの好みを覚えます。'),
    list,
    h('button', { class: 'btn', onclick: () => { items.push({ id: 'pose' + Date.now().toString(36), type: 'pose', name: '新しいポーズ', icon: '📸', bold: 0, outside_ok: false, pos: '', neg: '' }); draw(); } }, '＋追加'),
  ];
};

// 服装の入力欄: 自由入力と, 服の一覧から選ぶプルダウン (選ぶとその服の服装が入る)
function outfitInput(obj, key) {
  const el = inp(obj, key);
  const items = ((S.boot.outfits || {}).items) || [];
  const sel = h('select', { style: 'max-width:12em', onchange: (ev) => {
    const o = items.find((x) => x.id === ev.target.value);
    if (o) { obj[key] = o.pos; el.value = o.pos; }
    ev.target.value = '';
  } }, h('option', { value: '' }, '服の一覧から…'), items.map((o) => h('option', { value: o.id }, `${o.icon || ''} ${o.name}`)));
  return h('div', { class: 'row', style: 'gap:6px;flex-wrap:nowrap' }, el, sel);
}

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
    h('div', { class: 'sect' }, '知らせ（話しかけられた・メッセージが来た・出先で声をかけられた）'),
    h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: u.callSound !== false, onchange: (ev) => set('callSound', ev.target.checked) }),
      '音でも知らせる'),
    h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: u.callRemind !== false, onchange: (ev) => set('callRemind', ev.target.checked) }),
      '返事をするまで、2 分ごとに一度知らせ直す'),
    h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: u.vibrate !== false, onchange: (ev) => set('vibrate', ev.target.checked) }),
      'スマホでは振動でも知らせる（対応している端末だけ）'),
    h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: !!u.browserNotify, onchange: async (ev) => {
      const on = ev.target.checked;
      if (on && 'Notification' in window && Notification.permission !== 'granted') {
        let p = 'denied';
        try { p = await Notification.requestPermission(); } catch (e) { /* 許可を聞けない環境 */ }
        if (p !== 'granted') { ev.target.checked = false; toast('ブラウザの通知が許可されませんでした（ブラウザのサイトの設定で許可できます）', 'err'); return; }
      }
      if (on && !('Notification' in window)) { ev.target.checked = false; toast('このブラウザは通知に対応していません', 'err'); return; }
      set('browserNotify', on);
    } }), '画面を見ていないときは、ブラウザの通知でも知らせる（初めてオンにすると、ブラウザが許可を聞きます）'),
    h('p', { class: 'hint' }, '画面を見ていないときは、タブの題名も点滅します。ブラウザの通知は、この画面を開いたまま別のタブやアプリを見ているときに出ます（画面を閉じているあいだは出ません）。'),
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
        fld('あなたのスキル', inp(a, 'skill', { type: 'select', options: [['', 'なし'], ['talk', '会話'], ['touch', 'スキンシップ'], ['cook', '料理'], ['work', '仕事'], ['house', '家事'], ['care', '気配り'], ['groom', '身だしなみ'], ['budget', 'やりくり'], ['write', '文章']] })),
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
      fld('顔アイコンに足すタグ（Positive）', inp(st.images, 'icon_pos', { ph: 'portrait,looking at viewer,simple background,1girl,solo,masterpiece,best quality,amazing quality' }), '空欄なら既定。キャラの外見のプロンプトのあとに足して、顔だけの画像を一度だけ作ります（共通プロンプトは入れないので、画質のタグもここに）', 'span2'),
      fld('顔アイコンの Negative', inp(st.images, 'icon_neg', { ph: 'full body,wide shot,multiple views,worst quality,bad quality,(monochrome),3d,(shiny skin:1.2),worst detail,text,logo,cropped,deformed,blurry,sketch,censor' })),
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

/* ---- 共通プロンプト (全ワールド共通) */
SEC.prompt = () => {
  const pr = SE.settings.prompt;
  return [
    saveBar('共通プロンプト', async () => {
      await api('/api/settings', { settings: { prompt: pr } });
      await reloadAll();
    }),
    h('p', { class: 'lead' }, 'すべての画像に付く品質タグです（全ワールド共通）。時刻による光の演出は「時間帯・数値」（このワールドの決まり）にあります。'),
    fld('共通 Positive（先頭）', inp(pr, 'prefix_pos', { type: 'textarea', rows: 2 })),
    fld('共通 Negative', inp(pr, 'prefix_neg', { type: 'textarea', rows: 3 })),
  ];
};

/* ---- 時間帯・数値 (このワールドの決まり) */
SEC.worldnums = () => {
  const w = SE.world;
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
    saveBar('時間帯・数値', async () => {
      await api('/api/world', { world: w });
      await reloadAll();
    }),
    h('p', { class: 'lead' }, 'このワールドの時間帯（時刻による光の演出）と、お金・出来事・在席・働きかけの数値です（ワールドごと）。'),
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
        n('side_job_rate_per_min', '内職の額（目安の時間1分あたり）', '解けたとき。目安の時間 × この額（難しいほど少し上乗せ）。仕事スキルで 0.6〜1.4 倍、速さとミスで上下', '5'),
        n('news_rate_per_hour', '株のニュースの出やすさ（1時間あたり）', '0.25 ≒ 1日に6回ほど（全銘柄で）', '0.01'),
        n('news_accuracy', 'ニュースの当たりやすさ', '0.7 = 7割はニュースどおりに動く', '0.05'),
        n('event_rate_per_hour', '出来事の起きやすさ（1時間あたり）', '0.08 ≒ 起きている間に1日1〜2回', '0.01'));
    })(),
    h('div', { class: 'sect' }, '内職のタイピング（データ入力）に足す語・文'),
    (() => {
      const t = w.typing_extra = w.typing_extra || {};
      const hint = '1 行に「表記|よみ」。よみはひらがな（カタカナ・数字・記号もそのまま打てます）。打てない字のある行は使いません';
      return h('div', { class: 'grid3' },
        fld('単語（易）', inp(t, 'words', { type: 'textarea', rows: 4, ph: '買い物袋|かいものぶくろ' }), hint),
        fld('短い文（中）', inp(t, 'short', { type: 'textarea', rows: 4, ph: '洗濯物を取り込む。|せんたくものをとりこむ。' })),
        fld('長めの文（難）', inp(t, 'long', { type: 'textarea', rows: 4, ph: '伝票番号 1234-5678、3個口。|でんぴょうばんごう1234-5678、3こぐち。' })));
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
  const people = S.view.people || [];
  SE.dbg = people.some((p) => p.id === SE.dbg) ? SE.dbg : (tid() || (people[0] || {}).id);
  const dbgP = people.find((p) => p.id === SE.dbg) || { params: {}, name: '' };
  const v = { params: dbgP.params, name: dbgP.name };
  const C = { character: SE.dbg };
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
    h('div', { class: 'sect' }, '現在値を直接変更・出来事や働きかけを起こす（テスト用）'),
    h('div', { class: 'row' }, h('span', {}, '対象'), h('select', { onchange: (ev) => { SE.dbg = ev.target.value; showSection('data'); } },
      people.map((p) => h('option', { value: p.id, selected: p.id === SE.dbg }, p.name)))),
    ...sliders,
    h('div', { class: 'row', style: 'margin-top:10px' },
      h('button', { class: 'btn primary', onclick: async () => { await api('/api/state/set', Object.assign({ values: vals }, C)); toast('反映しました', 'ok'); await refresh(); } }, '反映'),
      h('button', { class: 'btn', onclick: async () => { await api('/api/state/clear_override', C); toast('一時シーンを解除しました', 'ok'); await refresh(); } }, '一時シーンを解除（予定に戻す）'),
      h('button', { class: 'btn danger', onclick: async () => {
        if (!confirm('パラメータを初期値に戻しますか？（ログと画像は残ります）')) return;
        await api('/api/state/reset', C); toast('初期化しました', 'ok'); await refresh(); showSection('data');
      } }, 'パラメータ初期化')),
    h('div', { class: 'sect' }, '出来事を起こす（テスト用）'),
    (() => {
      const sel = h('select', {}, (S.boot.events || []).map((e) => h('option', { value: e.id }, `${e.label}（${e.mood}）`)));
      return h('div', { class: 'row' }, sel, h('button', { class: 'btn', onclick: async () => {
        try { const r = await api('/api/events/force', Object.assign({ id: sel.value }, C)); toast(`起こしました: ${r.event.label}`, 'ok'); await refresh(); } catch (e) { toast(e.message, 'err'); }
      } }, '起こす'));
    })(),
    h('div', { class: 'sect' }, '働きかけを起こす（テスト用）'),
    (() => {
      const sel = h('select', {}, (S.boot.approaches || []).map((e) => h('option', { value: e.id }, `${e.icon || ''} ${e.label || e.id}`)));
      return h('div', { class: 'row' }, sel, h('button', { class: 'btn', onclick: async () => {
        try { const r = await api('/api/approach/force', Object.assign({ id: sel.value }, C)); $('#settings-dlg').close(); handleActResult(r); await refresh(); } catch (e) { toast(e.message, 'err'); }
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
      h('button', { class: 'btn', onclick: () => downloadJson('params.json', S.boot.params) }, 'パラメータを保存')),
    h('p', { class: 'hint' }, 'キャラクターの書き出しは キャラクター → 基本・外見 の「書き出す」から（編集しているキャラ）。'),
    h('div', { class: 'row', style: 'margin-top:8px' },
      h('button', { class: 'btn', onclick: async () => { try { const j = await pickJson(); if (!Array.isArray(j)) throw new Error('配列ではありません'); await api('/api/actions', { actions: j }); await reloadAll(); toast('コマンドを読み込みました', 'ok'); } catch (e) { toast(e.message, 'err'); } } }, 'コマンドを読込'),
      h('button', { class: 'btn', onclick: async () => { try { const j = await pickJson(); if (!Array.isArray(j)) throw new Error('配列ではありません'); await api('/api/params', { params: j }); await reloadAll(); toast('パラメータを読み込みました', 'ok'); } catch (e) { toast(e.message, 'err'); } } }, 'パラメータを読込'),
      h('button', { class: 'btn', onclick: async () => { try { const j = await pickJson(); if (!j.id) throw new Error('id がありません'); await api('/api/character/save', { data: j }); if (!S.boot.characters.some((x) => x.id === j.id)) await api('/api/character/place', { id: j.id, stage: 'contact' }); S.editCid = j.id; await reloadAll(); toast('キャラクターを読み込みました', 'ok'); } catch (e) { toast(e.message, 'err'); } } }, 'キャラクターを読込')),
  ];
};

// セーブの読み込み: zip を新しいワールドとして足す (いまのワールド・定義・画像は上書きしない)
function importWorld() {
  const f = h('input', { type: 'file', accept: '.zip,application/zip' });
  f.onchange = () => {
    const file = f.files[0];
    if (!file) return;
    const rd = new FileReader();
    rd.onload = async () => {
      toast('読み込んでいます…');
      try {
        const r = await api('/api/world/import', { data: rd.result });
        const bits = [`キャラ ${r.characters} 人`];
        if (Object.keys(r.renamed || {}).length) bits.push(`うち ${Object.keys(r.renamed).length} 人はこちらの定義と中身が違うので別の人として足した`);
        bits.push(r.with_images ? `画像 ${r.images} 枚を足した` : '画像なし（記録の画像は表示されません）');
        toast(`ワールド「${r.name}」を足しました（${bits.join('・')}）。開くと続きから遊べます`, 'ok');
        await reloadAll('data');
      } catch (e) { toast(e.message, 'err'); }
    };
    rd.readAsDataURL(file);
  };
  f.click();
}

function worldManager() {
  const W = S.boot.worlds;
  const ex = SE.exportOpt = SE.exportOpt || { images: false };
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
      h('a', { class: 'btn', href: `/api/world/export?id=${encodeURIComponent(w.id)}`, title: 'このワールドと、そこにいるキャラの定義を 1 つのファイル（zip）に',
        onclick: (ev) => { ev.currentTarget.href = `/api/world/export?id=${encodeURIComponent(w.id)}${ex.images ? '&images=1' : ''}`; } }, '書き出す'),
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
      } }, '＋作成して開く')),
    h('div', { class: 'sect' }, 'セーブの書き出し・読み込み'),
    h('p', { class: 'hint' }, '「書き出す」で、そのワールド（状態・ログ・あなた・トーク・コマンドなどの定義）と、そこにいるキャラの定義（自作・編集した性格プリセットも）を 1 つの zip にします。'
      + '読み込みは、いつも新しいワールドとして足します（いまのワールド・キャラの定義・画像は上書きしません。同じキャラで中身の違う定義は、別の人として足します）。'),
    h('div', { class: 'row' },
      chk(ex, 'images', '書き出しに画像も含める（記録・顔のアイコンの画像。ファイルが大きくなります）'),
      h('button', { class: 'btn', onclick: importWorld }, 'セーブを読み込む')));
}

/* ================================================================= events */
function bind() {
  $$('#tabs button').forEach((b) => b.addEventListener('click', () => showTab(b.dataset.tab)));
  $$('#subtabs button').forEach((b) => b.addEventListener('click', () => showSub(b.dataset.sub)));
  $('#near-chip').addEventListener('click', () => showTab(T() ? 'with' : 'solo'));
  $('#dialogue').addEventListener('click', () => {
    if (S.typing) { clearInterval(S.typing); S.typing = null; $('#dtext').textContent = S.typingText; }
  });
  $('#world-select').addEventListener('change', (ev) => switchWorld(ev.target.value));
  $('#btn-settings').addEventListener('click', () => openSettings());
  $('#btn-gallery').addEventListener('click', openGallery);
  $('#btn-chat').addEventListener('click', () => openChat());
  $('#home-chip').addEventListener('click', () => openHome());
  $('#btn-manual').addEventListener('click', () => openManual());
  const seen = () => { S.lastInput = Date.now(); };
  for (const t of ['keydown', 'pointerdown', 'wheel', 'touchstart']) document.addEventListener(t, seen, { passive: true, capture: true });
  document.addEventListener('pointermove', () => { if (Date.now() - S.lastInput > 5000) seen(); }, { passive: true });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refresh();
  });
  $('#task-close').addEventListener('click', closeTask);
  $('#task-dlg').addEventListener('cancel', (ev) => { ev.preventDefault(); closeTask(); });
  $('#task-chat').addEventListener('click', () => openChat());     // 内職の画面の上にスマホを開く (閉じれば内職に戻る)
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
    const r = await api('/api/prompt' + (tid() ? '?character=' + encodeURIComponent(tid()) : ''));
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
    try { const r = await api('/api/generate', withT({})); showEntry(r.entry, false); trackJob(r.job); await refresh(); } catch (e) { toast(e.message, 'err'); }
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
}

async function init() {
  bind();
  try { await loadBoot(); } catch (e) { toast('サーバに接続できません: ' + e.message, 'err'); return; }
  await refresh();
  if (T()) showTab('with');
  try { const r = await api('/api/visit', {}); if (r.result) handleActResult(r.result); } catch (e) { toast(e.message, 'err'); }
  tickClock();
  setInterval(tickClock, 1000);
  setInterval(refresh, 30000);
}
init();
