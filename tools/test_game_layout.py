"""ゲームの途中は, 盤を真ん中に・相手の絵と会話欄を右の欄に入れ替える (S27 / A32. static/app.js の renderGamingMode, style.css の .layout.gaming).

一時データでサーバを立て, ヘッドレスのブラウザ (Edge か Chrome) で画面を開いて確かめる.
- 遊ぶ前は今までの並び (左 = 絵, 右 = 横の欄)
- ゲームを始めると gaming: 盤が左の広い列に, 絵が右の 400px に. タブ・相手の札・小さいタブは隠れ, 会話欄は絵の下 (dlg-below)
- 30 秒ごとの描き直し (refresh) を何度しても並びが崩れない. 盤 (リバーシ) のマスが, 横の欄にあったときより大きい
- スピード: 描き直しても問い合わせのタイマーが替わらない (二重に動かない・止まらない)
- 狭い画面 (980px 未満): 上に絵 (低め), その下に盤
- 決着して閉じる / やめると元の並び (会話欄の位置も設定どおり)

    python tools/test_game_layout.py
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
<iframe id="f" src="/" style="width:1400px;height:900px"></iframe><pre id="out">NOT RUN</pre>
<script>
const f = document.getElementById('f');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
f.onload = () => setTimeout(async () => {
  const w = f.contentWindow, d = f.contentDocument, out = [], S = w.eval('S');
  if (S.inactive) { document.getElementById('out').textContent = 'LOST (another copy of this page is the active screen)'; return; }
  const closeModal = () => d.querySelectorAll('dialog[open]').forEach((x) => x.close());
  const ok = (name, c, info) => out.push(name + (c ? ':OK' : ':NG' + (info !== undefined ? '(' + info + ')' : '')));
  const R = (sel) => { const e = d.querySelector(sel); return e ? e.getBoundingClientRect() : { left: 0, top: 0, width: 0, height: 0 }; };
  const shown = (sel) => { const e = d.querySelector(sel); return !!e && w.getComputedStyle(e).display !== 'none' && !e.closest('[hidden]'); };
  const lay = d.querySelector('.layout'), stage = d.getElementById('stage');
  const start = async (ids) => {
    for (const id of ids) {
      const g = (S.view.games.list || []).find((x) => x.id === id && x.ok);
      if (!g) continue;
      await w.gameAct('/api/game/start', { game: id });
      if (S.view.games.current) return id;
    }
    return '';
  };
  try {
    await w.refresh(); closeModal();
    // 一時データの町では, いまの時刻に同居相手が出かけている・寝ていることがある: セーブエディタで「家に来ている」にする
    const cid = ((S.view.people || [])[0] || {}).id;
    if (cid) {          // 寝ている・仕事中だと遊べない (free): 相手の一時シーンも「遊びに来ている」に
      const now = Date.now() / 1000;
      try {
        await w.api('/api/save/set', { path: ['player', 'with'], value: { cid, mode: 'guest', t: now, until: now + 7200 } });
        await w.api('/api/save/set', { path: ['state', cid, 'override'], value: { activity: 'guest', label: 'あなたの家に遊びに来ている',
          location: 'あなたの家', until: now + 7200, pos: 'indoors, apartment, living room', neg: '' } });
      } catch (e) { out.push('setup:' + e.message); }
      await w.refresh(); closeModal();
    }
    ok('company', !!S.view.with, (S.view.company || []).length);
    ok('before', !lay.classList.contains('gaming') && R('#stage').left < R('.side').left);
    // 横の欄でのリバーシのマス (比べる元): 盤を横の欄に描いて測る
    w.showTab('with'); w.showSub('games');
    const g1 = await start(['reversi']);
    let cellNarrow = 0;
    if (g1) {
      // gaming を外した並びで一度測る (横の欄 400px の中の盤)
      lay.classList.remove('gaming'); await sleep(50);
      cellNarrow = R('.rv-cell').width;
      lay.classList.add('gaming'); await sleep(50);
    }
    const gid = g1 || await start(['connect4', 'hex', 'yacht', 'numeron', 'mahjong']);
    ok('started', !!gid, ((S.view.games.list || []).find((x) => x.id === 'reversi') || {}).why + '|' + JSON.stringify(S.view.blocked || {}));
    await w.refresh(); await sleep(100);
    ok('gaming', lay.classList.contains('gaming'));
    ok('board-left', R('#tab-games').left < R('#stage').left && R('#tab-games').width > 700, R('#tab-games').width);
    ok('stage-right', Math.abs(R('#stage').width - 400) <= 2 && R('#stage').height > 600, R('#stage').width + 'x' + R('#stage').height);
    ok('tabs-hidden', !shown('#tabs') && !shown('#subtabs') && !shown('#with-card'));
    ok('games-shown', shown('#tab-games') && !!d.querySelector('#tab-games .board'));
    ok('dlg-below', stage.classList.contains('dlg-below') && !stage.classList.contains('dlg-top'));
    ok('dialogue-in-stage', R('#dialogue').left >= R('#stage').left - 1 && R('#dialogue').top > R('#stage').top + 100);
    ok('img-in-stage', w.getComputedStyle(d.getElementById('stage-img')).display !== 'none' && R('#stage-img').left >= R('#stage').left - 1);
    ok('tools-in-stage', shown('.stage-tools') && R('.stage-tools').left > R('#stage').left);
    for (let i = 0; i < 3; i++) await w.refresh();
    ok('refresh-keep', lay.classList.contains('gaming') && shown('#tab-games') && !shown('#tabs'));
    if (gid === 'reversi') {
      const big = R('.rv-cell').width;
      ok('cell-bigger', big > cellNarrow * 1.3 && R('.rv').height <= 900 - 58, cellNarrow.toFixed(1) + '->' + big.toFixed(1));
    }
    // 狭い画面: 上に絵 (低め), その下に盤
    f.style.width = '900px'; await sleep(300);
    ok('narrow-order', R('#stage').top < R('#tab-games').top && R('#stage').width > 800, R('#stage').top + '/' + R('#tab-games').top);
    ok('narrow-low', R('#stage').height < 900 * 0.4 && R('#stage').height >= 200, R('#stage').height);
    f.style.width = '1400px'; await sleep(300);
    // やめる (決着していれば閉じる) → 元の並び
    await w.gameAct('/api/game/quit', {});
    await w.refresh();
    ok('back', !lay.classList.contains('gaming') && R('#stage').left < R('.side').left && shown('#tabs'));
    ok('back-dlg', stage.classList.contains('dlg-below') === (S.ui.pos === 'below'));
    // スピード: 描き直してもタイマーが替わらない
    w.showTab('with'); w.showSub('games');
    const sp = await start(['speed']);
    if (!sp) out.push('speed:NONE');
    else {
      await sleep(400);
      const t0 = S.spTimer;
      for (let i = 0; i < 3; i++) await w.refresh();
      await sleep(400);
      ok('speed-timer', !!t0 && S.spTimer === t0 && lay.classList.contains('gaming'), t0 + '/' + S.spTimer);
      // F10: 場札を押さえている間は描き直さない (以前は 0.3 秒ごとに盤を作り直して, 押してから離すまでの手が消えていた).
      // 返事待ちの間に出した手は捨てずに送る. 何も変わらない問い合わせでは描き直さない
      const cur = S.view.games.current;
      if (cur && cur.speed) cur.speed.start_in = 0;
      await sleep(2600);                                   // 「せーの」のあと
      const sent = [], api0 = w.api, rg0 = w.renderGames;
      let renders = 0;
      w.api = async (u, b) => { if (b && b.act === 'play') sent.push(b.i); return api0(u, b); };
      w.renderGames = (...a) => { renders++; return rg0(...a); };
      try {
        const card = d.querySelector('.sp-mine');
        if (!card) out.push('speed-hold:NONE');
        else {
          const rc = card.getBoundingClientRect(), opt = { bubbles: true, clientX: rc.x + 5, clientY: rc.y + 5, pointerId: 1 };
          card.dispatchEvent(new w.PointerEvent('pointerdown', opt));
          const r0 = renders;
          await sleep(1300);                              // 問い合わせが 4 回ほど入る
          ok('speed-hold', renders === r0 && d.contains(card), renders - r0);
          card.parentElement.dispatchEvent(new w.PointerEvent('pointerup', opt));
          await sleep(700);
          ok('speed-hold-sent', sent.length === 1, JSON.stringify(sent));
          S.spBusy = true; w.spSend({ act: 'play', i: 2 }); const q = !!S.spQueue; S.spBusy = false;
          ok('speed-queue', q, q);
          await w.spSend({ act: 'tick' });
          ok('speed-queue-sent', sent.includes(2) && !S.spQueue, JSON.stringify(sent));
        }
        const v = (S.view.games.current || {}).speed;
        if (v && !v.over) {
          const r1 = renders, k1 = w.spKey(v);
          await sleep(1000);
          const k2 = w.spKey((S.view.games.current || {}).speed);
          ok('speed-idle', k1 !== k2 || renders === r1, (renders - r1) + ' renders');
        }
      } finally { w.api = api0; w.renderGames = rg0; }
      await w.gameAct('/api/game/quit', {}); await w.refresh();
      await sleep(700);
      ok('speed-stop', !S.spTimer && !lay.classList.contains('gaming'), S.spTimer);
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
        print("game layout: SKIP (Edge / Chrome が見つからない)")
        return
    tmp = tempfile.mkdtemp(prefix="kurashi_gamelayout_")
    page = os.path.join(ROOT, "static", "_game_layout_test.html")
    port = free_port()
    env = dict(os.environ, KURASHI_DATA=os.path.join(tmp, "data"), PYTHONIOENCODING="utf-8")
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py"), "--port", str(port), "--no-browser"], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with open(page, "w", encoding="utf-8") as f:
            f.write(PAGE)
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.5)
        url = "http://127.0.0.1:%d/static/_game_layout_test.html" % port
        out = ""
        for k, br in enumerate(brs):
            for again in range(5):
                try:
                    out = subprocess.run([br, "--headless", "--disable-gpu", "--no-first-run", "--window-size=1500,1000",
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
    print("game layout:", res)
    items = res.split()
    bad = [x for x in items if not (x.endswith(":OK") or x.endswith(":NONE"))]
    need = {"company:OK", "before:OK", "started:OK", "gaming:OK", "board-left:OK", "stage-right:OK", "tabs-hidden:OK", "dlg-below:OK",
            "refresh-keep:OK", "narrow-order:OK", "narrow-low:OK", "back:OK", "back-dlg:OK"}
    assert items and not bad and need <= set(items), res
    print("ALL OK")


if __name__ == "__main__":
    main()
