"""知らせの音 (A33. static/app.js の SOUND_KINDS / playSound / soundTable) を, ヘッドレスのブラウザで確かめる.

- 種類ごとの既定の音 (A33 より前の音に近いもの) と, 選んだ音・音量・「鳴らさない」がその種類にだけ効く
- 「音でも知らせる」(callSound) を切ると全部鳴らない. 旧設定 (callSound: false だけ) も全部鳴らない (遡及の読み替え)
- 知らせの入り口 (notifyCall の話しかけ・メッセージ・声をかけられた / 知らせ直し / 取り直しの返信・約束・終わった) が, それぞれの種類で鳴る
- 試し聞き (▶・全部を順に) は callSound を切っていても鳴る. 音そのもの (playTone) が本当に WebAudio で鳴らせる
- 設定の画面に全種類の行があり, 欄を変えるとその種類だけ保存される. 描き直しで欄のフォーカスが外れない
- 着信のくり返し (startRing / stopRing) が止まる

    python tools/test_sounds.py
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
from test_focus_keep import free_port  # noqa: E402

PAGE = r"""<!doctype html><meta charset="utf-8"><body>
<iframe id="f" src="/" style="width:1280px;height:900px"></iframe><pre id="out">NOT RUN</pre>
<script>
const f = document.getElementById('f');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
f.onload = () => setTimeout(async () => {
  const w = f.contentWindow, d = f.contentDocument, out = [], S = w.eval('S');
  if (S.inactive) { document.getElementById('out').textContent = 'LOST (another copy of this page is the active screen)'; return; }
  const ok = (name, c) => out.push(name + (c ? ':OK' : ':NG'));
  try {
    await w.refresh(); d.querySelectorAll('dialog[open]').forEach((x) => x.close());
    const KINDS = w.eval('SOUND_KINDS').map((k) => k[0]), TONES = Object.keys(w.eval('SOUND_TONES'));
    ok('kinds', ['talk', 'message', 'street', 'ring', 'voice', 'appoint', 'done', 'remind'].every((k) => KINDS.includes(k)));
    // 本物の音: 鳴らせる (AudioContext) . 以降は鳴った音を記録するだけにする
    ok('real-tone', TONES.every((t) => w.eval('playTone')(t, 10) === true));
    ok('real-unknown', w.eval('playTone')('nope', 50) === false);
    const real = w.eval('playTone');
    let rec = [];
    w.eval('playTone = (t, v) => { window.__rec.push([t, v]); return true; }');
    w.__rec = rec;
    const fresh = () => { rec.length = 0; };
    const ui0 = JSON.parse(JSON.stringify(S.ui));
    // 1. 既定: 前の音に近い (話しかけ・声をかけられた = 3 音で強め, メッセージ・知らせ直し = 2 音で控えめ). 聞き分けられるよう, 種類ごとに音か音量が違う
    S.ui.sounds = {}; S.ui.callSound = true;
    const pick = (k) => w.eval('soundPick')(k);
    ok('def-talk', pick('talk').tone === 'chime3' && pick('talk').vol === 67);
    ok('def-message', pick('message').tone === 'chime2' && pick('message').vol === 40);
    ok('def-street', pick('street').tone.startsWith('chime3') && pick('street').tone !== 'chime3');
    const sig = KINDS.filter((k) => k !== 'remind').map((k) => pick(k).tone + '/' + pick(k).vol);
    ok('def-distinct', new Set(sig).size === sig.length);
    // 2. 種類ごと: 鳴る音はその種類の設定
    for (const k of KINDS) { fresh(); w.playSound(k); ok('play-' + k, rec.length === 1 && rec[0][0] === pick(k).tone && rec[0][1] === pick(k).vol); }
    // 3. 1 つの種類だけ変える / 鳴らさない: ほかは変わらない
    S.ui.sounds = { message: { tone: 'bell', vol: 80 }, done: { tone: 'off', vol: 50 }, talk: { tone: 'pop', vol: 0 } };
    fresh(); w.playSound('message'); ok('set-message', rec.length === 1 && rec[0][0] === 'bell' && rec[0][1] === 80);
    fresh(); ok('off-done', w.playSound('done') === false && rec.length === 0);
    fresh(); ok('vol0-talk', w.playSound('talk') === false && rec.length === 0);
    fresh(); w.playSound('street'); ok('other-unchanged', rec.length === 1 && rec[0][0] === 'chime3d');
    // 壊れた値 (知らない音・範囲外の音量) は既定に戻して読む
    S.ui.sounds = { appoint: { tone: 'zzz', vol: 999 } };
    ok('bad-value', pick('appoint').tone === 'bell' && pick('appoint').vol === 100);
    // 4. 「音でも知らせる」を切る: 全部鳴らない. 旧設定 (sounds が無く callSound: false) も同じ
    S.ui.sounds = {}; S.ui.callSound = false;
    fresh(); ok('master-off', KINDS.every((k) => w.playSound(k) === false) && rec.length === 0);
    w.localStorage.setItem('kurashi.ui', JSON.stringify({ callSound: false, font: 18 }));
    const old = Object.assign({}, w.eval('UI_DEFAULT'), JSON.parse(w.localStorage.getItem('kurashi.ui')));
    const keepUi = S.ui; S.ui = old;
    fresh(); ok('legacy-off', KINDS.every((k) => w.playSound(k) === false) && rec.length === 0);
    S.ui = keepUi;
    // 5. 知らせの入り口: それぞれの種類で鳴る
    S.ui.callSound = true; S.ui.sounds = { talk: { tone: 'ding', vol: 50 }, message: { tone: 'knock', vol: 50 }, street: { tone: 'pop', vol: 50 },
      appoint: { tone: 'bell', vol: 50 }, done: { tone: 'low2', vol: 50 }, remind: { tone: 'chime2', vol: 20 } };
    fresh(); w.notifyCall('t1', 'x', '', true, 'talk'); ok('nc-talk', rec.length === 1 && rec[0][0] === 'ding');
    fresh(); w.notifyCall('t2', 'x', '', false, 'message'); ok('nc-message', rec.length === 1 && rec[0][0] === 'knock');
    fresh(); w.notifyCall('t3', 'x', '', true, 'street'); ok('nc-street', rec.length === 1 && rec[0][0] === 'pop');
    fresh(); w.notifyCall('t3', 'x', '', true, 'street'); ok('nc-once', rec.length === 0);
    fresh(); w.notifyCall('t4', 'x', '', true); ok('nc-strong-default', rec.length === 1 && rec[0][0] === 'ding');
    // 話しかけ (そば / 離れて) は renderApproach から: 種類が分かれている
    fresh(); S.view.approaches = [{ cid: 'a', id: 1, until: 9e9, icon: '💬', name: 'A', label: 'x', apart: false },
      { cid: 'b', id: 2, until: 9e9, icon: '📱', name: 'B', label: 'y', apart: true }];
    try { w.renderApproach(); } catch (e) { /* 描くのに要る値が足りなくても, 知らせは先に出る */ }
    ok('ap-kinds', rec.map((x) => x[0]).join() === 'ding,knock');
    S.view.approaches = [];
    // 取り直し: 返信 → 約束 → 終わった の順に 1 つだけ
    const api0 = w.eval('api');
    const fake = async (extra) => {
      const v = JSON.parse(JSON.stringify(S.view));
      Object.assign(v, { replies: [], appoint_events: [], shop_done: null, arrival: null, approaches: [], street_pending: null }, extra);
      w.eval('api = async () => window.__v');
      w.__v = v;
      fresh(); await w.refresh();
      w.eval('api = window.__api0');
      return rec.map((x) => x[0]).join();
    };
    w.__api0 = api0;
    ok('rf-reply', await fake({ replies: [{ name: 'A', text: 'hi' }], appoint_events: ['x'], shop_done: { label: 'L', total: 1 } }) === 'knock');
    ok('rf-appoint', await fake({ appoint_events: ['x'], shop_done: { label: 'L', total: 1 } }) === 'bell');
    ok('rf-done', await fake({ shop_done: { label: 'L', total: 1 } }) === 'low2');
    ok('rf-arrival', await fake({ arrival: { text: '着いた' } }) === 'low2');
    ok('rf-none', await fake({}) === '');
    await w.refresh();
    // 6. 着信のくり返し: 止まる
    fresh(); w.startRing(); await sleep(3300); w.stopRing(); const n = rec.length; await sleep(3300);
    ok('ring-repeat', n >= 2 && rec.every((x) => x[0] === pick('ring').tone) && rec.length === n);
    // 7. 設定の画面: 全種類の行・試し聞きは callSound を切っていても鳴る・変えるとその種類だけ保存
    S.ui.sounds = {}; S.ui.callSound = false;
    await w.openSettings('display');
    const sels = [...d.querySelectorAll('#sbody select[data-sound]')];
    ok('rows', sels.length === KINDS.length);
    fresh(); d.querySelector('#sbody .sound-row button').click(); ok('preview-master-off', rec.length === 1 && rec[0][0] === pick('talk').tone);
    const s2 = d.querySelector('#sbody select[data-sound=done]');
    s2.value = 'ding'; fresh(); s2.dispatchEvent(new w.Event('change'));
    const saved = JSON.parse(w.localStorage.getItem('kurashi.ui') || '{}').sounds || {};
    ok('save-one', saved.done && saved.done.tone === 'ding' && Object.keys(saved).length === 1 && rec.length === 1 && rec[0][0] === 'ding');
    s2.value = 'off'; fresh(); s2.dispatchEvent(new w.Event('change'));
    ok('save-off', (JSON.parse(w.localStorage.getItem('kurashi.ui')).sounds.done || {}).tone === 'off' && rec.length === 0);
    // 全部を順に: 鳴らさないもの以外を順に
    fresh(); d.querySelector('#sbody .sound-demo').click(); await sleep(2200 * 8 + 500);
    ok('demo-all', rec.length === KINDS.length - 1);
    // 描き直しでフォーカスが外れない (設定の画面は周期の描き直しの外だが, 念のため)
    const el = d.querySelector('#sbody select[data-sound=talk]'); el.focus();
    await w.refresh(); await w.refresh();
    ok('focus', d.activeElement === el && d.contains(el));
    d.getElementById('settings-dlg').close();
    S.ui = Object.assign(S.ui, ui0); w.eval('saveUi')();
    w.eval('playTone = window.__real'); w.__real = real;
  } catch (e) { out.push('ERR:' + e.message); }
  document.getElementById('out').textContent = 'RESULT:' + out.join(' ');
}, 5000);
</script>"""


def main():
    brs = find_browsers()
    if not brs:
        print("sounds: SKIP (Edge / Chrome が見つからない)")
        return
    tmp = tempfile.mkdtemp(prefix="kurashi_sounds_")
    page = os.path.join(ROOT, "static", "_sounds_test.html")
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
        url = "http://127.0.0.1:%d/static/_sounds_test.html" % port
        out = ""
        for k, br in enumerate(brs):
            for again in range(5):
                try:
                    out = run_browser([br, "--headless", "--disable-gpu", "--no-first-run", "--autoplay-policy=no-user-gesture-required",
                                          "--user-data-dir=" + os.path.join(tmp, "prof%d_%d" % (k, again)),
                                          "--virtual-time-budget=90000", "--dump-dom", url], timeout=120)
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
    print("sounds:", res)
    items = res.split()
    bad = [x for x in items if not x.endswith(":OK")]
    assert len(items) >= 30 and not bad, bad or res
    print("ALL OK")


if __name__ == "__main__":
    main()
