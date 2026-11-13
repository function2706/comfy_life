"""画面の描き直しで, 入力の途中の欄 (プルダウン・時刻・文字) のフォーカスが外れないこと (static/app.js の refresh / editingForm).

30 秒ごとの状態の取り直し (refresh) は画面を描き直す. 描き直すと欄が作り直されて, 開いていたプルダウンが閉じ, フォーカスが外れていた
(地図の「時刻を決めて調べる」のプルダウン. 前にも別の欄で起きた). 入力の途中は描き直しを待ち, 欄を離れたら描き直す.
一時データでサーバを立て, ヘッドレスのブラウザ (Edge か Chrome) で画面を開いて確かめる.
- 地図の時刻を決めて調べる: プルダウン・時刻の欄にフォーカスを置いたまま描き直しても, フォーカスが残る
- 予定 (日付・時刻・コマンド・行き先・行き方・未指定時コマンド・自動の応答)・一人でタブのほかの欄・お金・ログ・関係性・
  持ち物のタブ・トークの約束の欄 (出ている欄はすべて)
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
from test_slither_history import find_browsers  # noqa: E402

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
    out.push(name + (d.activeElement === el && d.contains(el) ? ':OK' : ':NG'));
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
    // 2. 一人で: 予定 (日付・時刻・コマンド・行き先・行き方・未指定時コマンド・自動の応答)
    await keepAll(() => { closeModal(); w.showTab('solo'); S.planOpen = true; S.planForm = { date: (S.view.plan || {}).dates?.[1], at: '09:00', do: 'out', place: 'mall' }; w.renderSoloTab(); },
      '#tab-solo .plan', 'plan');
    // 3. 一人で: 本を読む・映画のジャンルなど, 一人でタブのほかの欄
    await keepAll(() => { closeModal(); w.showTab('solo'); S.readOpen = 'movie'; w.renderSoloTab(); }, '#tab-solo', 'solo');
    // 4. お金・ログ・関係性・持ち物のタブ
    for (const tb of ['money', 'log', 'people', 'items']) await keepAll(() => { closeModal(); w.showTab(tb); }, '#tab-' + tb, tb);
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
                    out = subprocess.run([br, "--headless", "--disable-gpu", "--no-first-run",
                                          "--user-data-dir=" + os.path.join(tmp, "prof%d_%d" % (k, again)),
                                          "--virtual-time-budget=60000", "--dump-dom", url],
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=90).stdout.decode("utf-8", "replace")
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
    assert items and not bad and {"map-select:OK", "map-time:OK", "resume:OK"} <= set(items) and any(x.startswith("plan") for x in items)         and any(x.startswith("chat") and x.endswith(":OK") for x in items), res
    print("ALL OK")


if __name__ == "__main__":
    main()
