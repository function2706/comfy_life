"""画面の描き直しで, 入力の途中の欄 (プルダウン・時刻・文字) のフォーカスが外れないこと (static/app.js の refresh / editingForm).

30 秒ごとの状態の取り直し (refresh) は画面を描き直す. 描き直すと欄が作り直されて, 開いていたプルダウンが閉じ, フォーカスが外れていた
(地図の「時刻を決めて調べる」のプルダウン. 前にも別の欄で起きた). 入力の途中は描き直しを待ち, 欄を離れたら描き直す.
一時データでサーバを立て, ヘッドレスのブラウザ (Edge か Chrome) で画面を開いて確かめる.
- 地図の時刻を決めて調べる: プルダウン・時刻の欄にフォーカスを置いたまま描き直しても, フォーカスが残る
- 「本を読む」の欄など, ほかの画面のプルダウンでも (出ている欄はすべて)
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
  const keep = async (el, name) => {
    el.focus();
    if (d.activeElement !== el) return;              // 隠れている・押せない欄は数えない
    await w.refresh(); await w.refresh();
    out.push(name + (d.activeElement === el && d.contains(el) ? ':OK' : ':NG'));
  };
  try {
    d.querySelectorAll('dialog[open]').forEach((x) => x.close());
    w.openMap();
    S.mapSel = 'park'; S.routeQ = { to: 'park', by: 'depart', at: '', res: null }; w.renderMap();     // 時刻の欄も使える指定で
    await keep(d.querySelector('dialog[open] select'), 'map-select');
    await keep(d.querySelector('dialog[open] input[type=time]'), 'map-time');
    d.activeElement.blur(); await sleep(800);
    out.push(S.renderPending ? 'resume:NG' : 'resume:OK');
    S.mapDlg.close();
    w.showTab('solo'); S.readOpen = 'movie'; w.renderSoloTab();
    const sels = [...d.querySelectorAll('select')].filter((x) => x.offsetParent);
    let i = 0;
    for (const s of sels.slice(0, 5)) await keep(s, 'select' + (i++));
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
            try:                                  # Edge の版によっては画面なしの起動が返らない: 次のブラウザへ
                out = subprocess.run([br, "--headless", "--disable-gpu", "--no-first-run", "--user-data-dir=" + os.path.join(tmp, "prof%d" % k),
                                      "--virtual-time-budget=20000", "--dump-dom", url],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=90).stdout.decode("utf-8", "replace")
            except subprocess.TimeoutExpired:
                out = ""
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
    assert items and all(x.endswith(":OK") for x in items) and {"map-select:OK", "map-time:OK", "resume:OK"} <= set(items), res
    print("ALL OK")


if __name__ == "__main__":
    main()
