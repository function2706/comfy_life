"""画面の描き直しで, 入力の途中の欄 (プルダウン・時刻・文字) のフォーカスが外れないこと (static/app.js の refresh / editingForm).

30 秒ごとの状態の取り直し (refresh) は画面を描き直す. 描き直すと欄が作り直されて, 開いていたプルダウンが閉じ, フォーカスが外れていた
(地図の「時刻を決めて調べる」のプルダウン. 前にも別の欄で起きた). 入力の途中は描き直しを待ち, 欄を離れたら描き直す.
一時データでサーバを立て, ヘッドレスのブラウザ (Edge か Chrome) で画面を開いて確かめる.
- 画面の上の「🗺 地図」で開いた地図が, 描き直しで閉じない (A40)
- 地図の時刻を決めて調べる: プルダウン・時刻の欄にフォーカスを置いたまま描き直しても, フォーカスが残る
- 予定 (日付・時刻・コマンド・行き先・行き方・未指定時コマンド・自動の応答)・一人でタブのほかの欄・お金・ログ・関係性・
  持ち物のタブ・トークの約束の欄 (出ている欄はすべて)
- 設定の「表示」の知らせの音の欄 (A33)
- 誰かと → ゲームの「罰ゲーム・勝負の形を選んで遊ぶ」の欄 (A12. 家に来てもらっている形にして)
- 誰かと → お願いの服の棚の名前で探す欄・系統のプルダウン (S37. 以前は「部品で合わせる」のプルダウン)
- 服の棚で選んだ服が描き直しで戻らない・コーデの下書きの色の見本 / 買うものリストの服の区分のタブと色の丸 / 服の一覧の売る色 (S35・S37)
- 設定のキャラクター → 服の好みのプルダウンと色の丸 (S36)
- 欄を離れたら, 待っていた描き直しをする

    python tools/test_focus_keep.py
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from test_slither_history import find_browsers, run_browser  # noqa: E402

PAGE = r"""<!doctype html><meta charset="utf-8"><body>
<iframe id="f" src="/" style="width:1280px;height:900px"></iframe><pre id="out">NOT RUN</pre>
<script>
const f = document.getElementById('f');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
f.onload = () => setTimeout(async () => {
  const w = f.contentWindow, d = f.contentDocument, out = [], S = w.eval('S');      // const の S は window に載らない
  const closeModal = (keep) => d.querySelectorAll('dialog[open]').forEach((x) => { if (x !== keep) x.close(); });
  // A headless browser sometimes loads this page twice at once (seen with Edge 157: two headless processes hit the server 0.1 s apart).
  // Only one screen can be active (server.py gate), so the copy that lost must not drive the app: it reports no RESULT,
  // and the runner below moves on to the next browser if the dumped copy was the one that lost.
  if (S.inactive) { document.getElementById('out').textContent = 'LOST (another copy of this page is the active screen)'; return; }
  // 欄にフォーカスを置いたまま, 周期の描き直し (refresh と, トークを開いていればトークの描き直し) を起こし, フォーカスが残るか
  const keep = async (el, name) => {
    el.focus();
    if (d.activeElement !== el) return;              // 隠れている・押せない欄は数えない
    await w.refresh(); await w.refresh();
    if (S.chatDlg && S.chatDlg.open) await w.drawChat(true);
    out.push(name + (d.activeElement === el && d.contains(el) ? ':OK'
      : ':NG(' + el.tagName + '.' + (el.className || el.type || '') + (el.title ? '/' + el.title : '') + (el.parentNode ? '<' + (el.parentNode.textContent || '').slice(0, 20) : '') + ')'));
  };
  // 場所 (root) にある欄をすべて (プルダウン・時刻・日付・数字・文字). 描き直しで作り直されるので, 毎回探し直す
  const FIELDS = 'select, input[type=time], input[type=date], input[type=number], input[type=text], input:not([type]), textarea';
  const keepAll = async (setup, rootSel, name) => {
    await setup();
    const n = d.querySelectorAll(rootSel + ' :is(' + FIELDS + ')').length;
    if (!n) out.push(name + ':NONE');
    for (let i = 0; i < n; i++) {
      await setup();
      const el = [...d.querySelectorAll(rootSel + ' :is(' + FIELDS + ')')][i];
      if (el && !el.disabled && el.offsetParent) await keep(el, name + i);
    }
  };
  try {
    await w.refresh(); closeModal();                 // 閉じていた間のまとめ (開いたときだけ) を先に閉じる
    // 1. 地図: 経路を調べる (時刻の欄も使える指定で)
    w.openMap();
    S.mapSel = 'park'; S.routeQ = { to: 'park', by: 'depart', at: '', res: null }; w.renderMap();
    await keep(d.querySelector('dialog[open] select'), 'map-select');
    await keep(d.querySelector('dialog[open] input[type=time]'), 'map-time');
    d.activeElement.blur(); await sleep(800);
    out.push(S.renderPending ? 'resume:NG' : 'resume:OK');
    S.mapDlg.close();
    // 1a. 画面の上の「🗺 地図」(A40): どの場面でも開け, 周期の描き直しで閉じない
    d.getElementById('btn-map').click(); await w.refresh(); await w.refresh();
    out.push('map-top' + (S.mapDlg.open && d.querySelector('dialog[open] svg') && d.querySelector('dialog[open]').textContent.includes('🗺 地図') ? ':OK' : ':NG'));
    S.mapDlg.close();
    // 1b. ギャラリーの「誰の画像か」のプルダウン (A19)
    await w.openGallery();
    await keep(d.querySelector('#gal-who'), 'gal-who');
    d.getElementById('gallery-dlg').close();
    // 2. 一人で: 予定 (日付・時刻・コマンド・行き先・行き方・未指定時コマンド・自動の応答)
    await keepAll(() => { closeModal(); w.showTab('solo'); S.planOpen = true; S.planForm = { date: (S.view.plan || {}).dates?.[1], at: '09:00', do: 'out', place: 'mall' }; w.renderSoloTab(); },
      '#tab-solo .plan', 'plan');
    // 3. 一人で: 本を読む・映画のジャンルなど, 一人でタブのほかの欄
    await keepAll(() => { closeModal(); w.showTab('solo'); S.readOpen = 'movie'; w.renderSoloTab(); }, '#tab-solo', 'solo');
    // 4. お金・ログ・関係性・持ち物のタブ
    for (const tb of ['money', 'log', 'people', 'items']) await keepAll(() => { closeModal(); w.showTab(tb); }, '#tab-' + tb, tb);
    // 4b. スクロール位置 (F9): 右の欄の各タブ・地図で, 欄の中をスクロールしたまま描き直しても, 先頭に戻らない (app.js の scrollMarks).
    //     欄を低くして必ずスクロールできるようにし, その中でスクロールできる入れ子の欄 (買うものリストなど) も, あれば全部確かめる
    const low = d.createElement('style');
    // (.plan は描き直しのたびに作り直される欄: 作り直される入れ子の欄でも位置が残ること. 外側の欄は作り直されないので元から残る)
    low.textContent = '.tab-body{max-height:140px!important;overflow:auto!important}.plan{max-height:60px!important;overflow:auto!important}';
    d.head.append(low);
    const scrollers = (root) => [root, ...root.querySelectorAll('*')].filter((el) => el.offsetParent && el.scrollHeight > el.clientHeight + 30
      && ['auto', 'scroll'].includes(w.getComputedStyle(el).overflowY));
    const keepScrollAll = async (setup, rootSel, name) => {
      await setup();
      const n = scrollers(d.querySelector(rootSel)).length;
      if (!n) out.push(name + ':NONE');
      for (let i = 0; i < n; i++) {
        await setup();
        const el = scrollers(d.querySelector(rootSel))[i];
        if (!el) continue;
        el.scrollTop = 24;
        const want = el.scrollTop;
        await w.refresh(); await w.refresh();
        const el2 = scrollers(d.querySelector(rootSel))[i];
        out.push(name + i + (el2 && want > 0 && Math.abs(el2.scrollTop - want) <= 1 ? ':OK' : ':NG(' + (el2 ? el2.scrollTop : 'gone') + '/' + want + ')'));
      }
    };
    for (const tb of ['solo', 'money', 'log', 'people', 'items']) await keepScrollAll(() => { closeModal(); w.showTab(tb); }, '#tab-' + tb, 'scroll-' + tb);
    await keepScrollAll(() => { closeModal(); w.showTab('solo'); S.planOpen = true; w.renderSoloTab(); }, '#tab-solo', 'scroll-plan');
    await keepScrollAll(() => { closeModal(); w.openMap(); S.mapSel = 'park'; w.renderMap(); }, 'dialog[open]', 'scroll-map');
    closeModal(); low.remove();
    // 4d. 誰かと → ゲーム: 罰ゲーム・勝負の形の欄 (A12. お金・行き先・呼び方・禁止のプルダウン, 形, n).
    // 時刻しだいで同居相手がそばにいないので, セーブエディタで家に来てもらっている形にする (あとで消す)
    const gcid = ((S.view.people || [])[0] || {}).id;
    const now0 = Date.now() / 1000;
    try { await w.api('/api/save/set', { path: ['player', 'presence', 'with'], value: { cid: gcid, mode: 'guest', t: now0, until: now0 + 36000 } }); }
    catch (e) { out.push('gsetup:' + e.message); }
    await w.refresh();
    await keepAll(() => {
      closeModal(); w.showTab('with'); w.showSub('games');
      S.ff = { connect4: { open: true, pens: ['money', 'date', 'callname', 'ban'], form: 'first', n: 3, opt: { money: '1000', date: '', call: '', ban: 'phone' } } };
      (S.view.games.list || []).forEach((g) => { g.base_ok = true; });      // 相手の手が空いていない時刻でも欄を出す (欄のフォーカスだけを見る)
      w.renderGames();
    }, '#tab-games .ff-pick', 'forfeit');
    // 4e. 誰かと → お願い: 服の棚 (S37) の名前で探す欄・系統のプルダウン
    await keepAll(() => { closeModal(); w.showTab('with'); w.showSub('dress'); w.renderDress(); }, '#tab-dress .closet', 'closet');
    // 4f. 服の棚 (S37): 選んだ服とタブは描き直しても残る (タイルに色の見本). 部品を「コーデに入れる」と下書きに色の見本つきで出る
    closeModal(); w.showTab('with'); w.showSub('dress'); S.cz = {}; S.coordDraft = {}; w.renderDress();
    {
      const tiles = () => [...d.querySelectorAll('#tab-dress .cz-tile')];
      const t1 = tiles()[1];
      if (!t1) out.push('owned:NONE');
      else {
        const nm = t1.querySelector('.cz-name').textContent; t1.click();
        await w.refresh(); await w.refresh();
        const on = d.querySelector('#tab-dress .cz-tile.on');
        out.push('owned' + (on && on.querySelector('.cz-name').textContent === nm && d.querySelector('#tab-dress .cz-tile .swatch') ? ':OK' : ':NG'));
      }
      const add = [...d.querySelectorAll('#tab-dress .cz-det button')].find((b) => b.textContent.includes('コーデに'));
      if (!add) out.push('coord-swatch:NONE');
      else { add.click(); out.push('coord-swatch' + (d.querySelector('#tab-dress .coord-bar .swatch') ? ':OK' : ':NG')); }
    }
    // スマホ幅 (375px) で, 着せ替えの部品の欄・色の見本・持っている服が, タブの欄から横にはみ出さない
    f.style.width = '375px'; await sleep(600); w.renderDress(); await sleep(100);
    const td = d.querySelector('#tab-dress'), tr = td.getBoundingClientRect().right;
    const over = [...td.querySelectorAll('*')].filter((e) => e.offsetParent && e.getBoundingClientRect().right > tr + 1)
      .map((e) => e.tagName + '.' + (e.className || '') + '<' + (e.textContent || '').slice(0, 12)).slice(0, 4).join('|');
    out.push('narrow-dress' + (tr > 200 && !over ? ':OK' : ':NG(' + Math.round(tr) + '/' + over + ')'));
    f.style.width = '1280px'; await sleep(400);
    S.coordDraft = {};
    try { await w.api('/api/save/del', { path: ['player', 'presence', 'with'] }); } catch (e) { out.push('gclean:' + e.message); }
    await w.refresh(); closeModal();
    // 4g. 買うものリスト (S35・S37): 種類ごとのサブタブ「服」は服の棚 (区分のタブ), 色は色の丸. 選んだ色とタブは描き直しても残る
    closeModal(); S.slKind = 'clothes'; w.openShopList('kind');
    const tabs = () => [...d.querySelectorAll('dialog[open] .slot-tabs button')];
    if (tabs().length < 3) out.push('shop-tabs:NG(' + tabs().length + ')');
    else {
      const t2 = tabs().find((b) => b.textContent.startsWith('ボトムス'));
      t2.click();
      const dots = () => [...d.querySelectorAll('dialog[open] .color-dots')][0];
      const pick = dots().querySelectorAll('button.swatch')[2];
      const name = pick.title; pick.click();
      await w.refresh(); await w.refresh(); w.drawShopList();
      const on = dots().querySelector('button.swatch.on');
      out.push('shop-tabs' + (tabs().find((b) => b.classList.contains('primary')).textContent.startsWith('ボトムス') && on && on.title === name
        && dots().querySelector('.color-name').textContent === name ? ':OK' : ':NG'));
    }
    // スマホ幅 (375px) で, 区分のタブ・色の丸が買うものリストの窓から横にはみ出さない
    f.style.width = '375px'; await sleep(600); w.drawShopList();
    const sd = d.querySelector('dialog[open]');
    out.push('narrow-shop' + (sd.scrollWidth - sd.clientWidth <= 1 ? ':OK' : ':NG(' + (sd.scrollWidth - sd.clientWidth) + ')'));
    f.style.width = '1280px'; await sleep(400);
    S.slDlg.close();
    // 4h. 設定の服の一覧 (S35): 売る色を色の丸で切り替える (全部付いている = 空, 1 つ外すと 13 色)
    closeModal(); S.cz = Object.assign(S.cz || {}, { olist: { tab: 'bottom', sel: 'p_miniskirt', q: '', style: '', season: false } });
    await w.openSettings('outfits');
    const sc = [...d.querySelectorAll('#sbody .color-dots')].find((x) => x.closest('.card').textContent.includes('ミニスカート'));
    if (!sc) out.push('sell-colors:NONE');
    else {
      sc.querySelector('button.swatch').click();
      const sc2 = [...d.querySelectorAll('#sbody .color-dots')].find((x) => x.closest('.card').textContent.includes('ミニスカート'));
      out.push('sell-colors' + (sc2.querySelectorAll('button.swatch.off').length === 1 && sc2.textContent.includes('13 色') ? ':OK' : ':NG'));
    }
    closeModal();
    // 4i. 設定のキャラクター → 服の好み (S36): 種類の好き嫌い・部位のこだわりのプルダウン. 色の丸と系統を押しても描き直しで戻らない
    await keepAll(async () => { closeModal(); await w.openSettings('char'); }, '#sbody .fashion-edit', 'fashion');
    {
      const fe = () => d.querySelector('#sbody .fashion-edit');
      const dot = fe() && [...fe().querySelectorAll('.color-dots')][0].querySelector('button.swatch.off');
      if (!dot) out.push('fashion-dot:NONE');
      else {
        const nm = dot.title; dot.click();
        await w.refresh(); await w.refresh();
        out.push('fashion-dot' + (fe() && fe().textContent.includes(nm) && [...fe().querySelectorAll('.color-dots')][0].querySelector('button.swatch.on[title="' + nm + '"]') ? ':OK' : ':NG'));
      }
    }
    closeModal();
    // 4c. 設定の「表示」: 知らせの音の欄 (A33. 種類ごとの音のプルダウン)
    await keepAll(async () => { closeModal(); await w.openSettings('display'); }, '#sbody .sound-table', 'sound');
    closeModal();
    // 5. トーク: 約束の欄 (日時・行き先)
    const cid = ((S.view.people || [])[0] || {}).id;
    if (cid) {
      // 約束の欄は, 離れている連絡先の相手だけ: 一時データの町では同居しているので, セーブエディタで連絡先の間柄にする
      try { await w.api('/api/save/set', { path: ['player', 'bonds', cid, 'stage'], value: 'contact' }); } catch (e) { out.push('setup:' + e.message); }
      try { await w.api('/api/save/del', { path: ['player', 'with'] }); } catch (e) { /* 一緒にいなければ無い */ }
      await w.refresh(); closeModal();
      w.openChat(cid); await sleep(1500);
      await keepAll(async () => { closeModal(S.chatDlg); S.apForm = S.apForm || {}; S.chatTab = 'invite'; await w.drawChat(); }, 'dialog[open]', 'chat');
      if (out[out.length - 1] === 'chat:NONE') out.push('chatdbg:' + (S.chatDlg.innerText || '').replace(/\s+/g, '_').slice(-120));
      // 6. トーク: スタンプなどの選択欄のスクロール位置 (F9. 描き直しで先頭に戻らない). 欄を低くして, 必ずスクロールできるようにする
      const st = d.createElement('style');
      st.textContent = '.chat-pick-list{max-height:26px!important;overflow:auto!important}';
      d.head.append(st);
      S.apForm = null; S.chatPick = 'stamp'; await w.drawChat();
      let pl = d.querySelector('dialog[open] .chat-pick-list');
      if (!pl || pl.scrollHeight <= pl.clientHeight + 4) out.push('pickscroll:NONE');
      else {
        pl.scrollTop = 20;
        const want = pl.scrollTop;
        await w.refresh(); await w.drawChat(true);
        pl = d.querySelector('dialog[open] .chat-pick-list');
        out.push('pickscroll' + (pl && want > 0 && Math.abs(pl.scrollTop - want) <= 1 ? ':OK' : ':NG(' + (pl ? pl.scrollTop : 'gone') + '/' + want + ')'));
      }
      st.remove();
      // 7. 謝る・お礼の理由を記憶で選ぶ窓 (A20): 描き直しで閉じない・選択肢 (並びも) が変わらない
      for (const kind of ['apology', 'thanks']) {
        await w.quizDialog(cid, kind, 'test', () => {});
        const qd = d.querySelector('dialog.quiz-dlg[open]');
        const before = qd ? qd.innerText : '';
        await w.refresh(); await w.refresh(); await w.drawChat(true);
        const qd2 = d.querySelector('dialog.quiz-dlg[open]');
        out.push('quiz-' + kind + (qd && qd2 === qd && qd.innerText === before && qd.querySelectorAll('.quiz-choice').length >= 2 ? ':OK' : ':NG'));
        if (qd) { qd.close(); qd.remove(); }
      }
    }
  } catch (e) { out.push('ERR:' + e.message); }
  document.getElementById('out').textContent = 'RESULT:' + out.join(' ');
}, 5000);
</script>"""


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    brs = find_browsers()
    if not brs:
        print("focus keep: SKIP (Edge / Chrome が見つからない)")
        return
    tmp = tempfile.mkdtemp(prefix="kurashi_focus_")
    page = os.path.join(ROOT, "static", "_focus_test.html")
    port = free_port()
    env = dict(os.environ, KURASHI_DATA=os.path.join(tmp, "data"), PYTHONIOENCODING="utf-8")
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py"), "--port", str(port), "--no-browser"], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with open(page, "w", encoding="utf-8") as f:
            f.write(PAGE)
        for _ in range(60):                       # 立ち上がるまで
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.5)
        url = "http://127.0.0.1:%d/static/_focus_test.html" % port
        out = ""
        for k, br in enumerate(brs):
            for again in range(5):                # LOST: the dumped copy of the page was not the active screen (see PAGE). Try again
                try:                              # Edge の版によっては画面なしの起動が返らない: 次のブラウザへ
                    out = run_browser([br, "--headless", "--disable-gpu", "--no-first-run",
                                          "--user-data-dir=" + os.path.join(tmp, "prof%d_%d" % (k, again)),
                                          "--virtual-time-budget=60000", "--dump-dom", url], timeout=90)
                except subprocess.TimeoutExpired:
                    out = ""
                if "LOST (" not in out:
                    break
            if "RESULT:" in out:
                break
    finally:
        srv.terminate()
        try:
            srv.wait(10)
        except subprocess.TimeoutExpired:
            srv.kill()
        if os.path.exists(page):
            os.remove(page)
        shutil.rmtree(tmp, ignore_errors=True)
    i = out.find("RESULT:")
    res = out[i + 7:out.find("</pre>", i)].strip() if i >= 0 else "(結果なし) " + out[:300]
    print("focus keep:", res)
    items = res.split()
    bad = [x for x in items if not (x.endswith(":OK") or x.endswith(":NONE"))]
    assert items and not bad and {"map-select:OK", "map-time:OK", "map-top:OK", "resume:OK", "gal-who:OK"} <= set(items) and any(x.startswith("plan") for x in items)         and any(x.startswith("chat") and x.endswith(":OK") for x in items)         and sum(1 for x in items if x.startswith("scroll-") and x.endswith(":OK")) >= 5 and "scroll-plan1:OK" in items         and {"quiz-apology:OK", "quiz-thanks:OK"} <= set(items) and "sound0:OK" in items         and {"owned:OK", "shop-tabs:OK", "sell-colors:OK", "narrow-shop:OK", "narrow-dress:OK"} <= set(items)         and sum(1 for x in items if x.startswith("forfeit") and x.endswith(":OK")) >= 5, res
    print("ALL OK")


if __name__ == "__main__":
    main()
