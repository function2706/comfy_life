"""Tailscale で外から開けるようにする (設定 → 表示 →「スマホから（外出先で）」のスイッチ).

Tailscale (自分の端末どうしだけがつながる VPN) の serve で, このサーバ (127.0.0.1:ポート) を https://<PC の名前>.<tailnet>.ts.net に出す.
ここでするのは, もう入っている tailscale のコマンドを呼ぶことだけ:
- 状態を見る: tailscale status --json (動いているか・サインインしているか・この PC の名前・HTTPS の証明書が使えるか)
- 出す: tailscale serve --bg <ポート> / 止める: tailscale serve --https=443 off
- 出ているか: tailscale serve status --json (このサーバのポートへ渡す設定があるか)
できないこと (手で一度だけ): Tailscale のインストール・サインイン・管理画面での HTTPS の有効化・スマホ側の設定.
funnel (インターネット全体への公開) は使わない. 呼ぶコマンドの引数は決め打ちで, 画面から受け取るのはオン / オフだけ.
設定 settings.remote.tailscale がオンなら, 起動のたびに出し直す (server.py).
"""
import json
import os
import shutil
import subprocess

TIMEOUT = 20
WIN_PATHS = (r"C:\Program Files\Tailscale\tailscale.exe", r"C:\Program Files (x86)\Tailscale\tailscale.exe")


def find_exe():
    exe = shutil.which("tailscale")
    if exe:
        return exe
    for p in WIN_PATHS:
        if os.path.isfile(p):
            return p
    return None


def run(args, timeout=TIMEOUT):
    """tailscale を呼ぶ. (終了コード, 出力) を返す. 入っていなければ (None, ""). 返ってこなければ (-1, 出力)."""
    exe = find_exe()
    if not exe:
        return None, ""
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000          # CREATE_NO_WINDOW: 黒い窓を出さない
    try:
        r = subprocess.run([exe] + list(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                           timeout=timeout, **kw)
        return r.returncode, r.stdout.decode("utf-8", "replace").strip()
    except subprocess.TimeoutExpired as e:
        return -1, (e.stdout or b"").decode("utf-8", "replace").strip()
    except OSError as e:
        return -1, str(e)


def _json(text):
    try:
        i = text.index("{")
        return json.loads(text[i:])
    except (ValueError, TypeError):
        return None


def _proxies(obj):
    """serve の設定の中の, 渡し先 (Proxy) をすべて."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "Proxy" and isinstance(v, str):
                out.append(v)
            else:
                out += _proxies(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _proxies(v)
    return out


def _to_port(proxy, port):
    """渡し先が, このサーバのポートか (http://127.0.0.1:8765・localhost:8765・8765 など)."""
    tail = proxy.rstrip("/").rsplit(":", 1)[-1]
    return tail == str(port)


class Tailnet:
    def __init__(self, app):
        self.app = app
        self.port = 8765             # server.py が起動のときに入れる
        self.run = run               # テストで差し替える

    def wanted(self):
        return bool((self.app.settings.get("remote") or {}).get("tailscale"))

    def view(self):
        """画面に出す状態: installed・running・https・serving・url と, できない理由 why."""
        v = {"installed": False, "running": False, "https": False, "serving": False, "url": None, "why": None,
             "wanted": self.wanted(), "port": self.port}
        code, out = self.run(["status", "--json"])
        if code is None:
            v["why"] = "この PC に Tailscale が入っていません（https://tailscale.com/download から入れて、サインインしてください）。"
            return v
        v["installed"] = True
        st = _json(out)
        if not st:
            v["why"] = "Tailscale の状態を読めませんでした（Tailscale が起動しているか確かめてください）: %s" % out[:160]
            return v
        state = st.get("BackendState")
        v["running"] = state == "Running"
        if not v["running"]:
            v["why"] = ("Tailscale にサインインしていません（Tailscale を開いてサインインしてください）。" if state in ("NeedsLogin", "NoState")
                        else "Tailscale が接続されていません（状態: %s。Tailscale を開いて接続してください）。" % state)
            return v
        name = ((st.get("Self") or {}).get("DNSName") or "").rstrip(".")
        certs = st.get("CertDomains") or []
        v["https"] = bool(certs)
        host = certs[0] if certs else name
        if host:
            v["url"] = "https://%s/phone" % host
        if not certs:
            v["why"] = ("HTTPS が有効になっていません。Tailscale の管理画面（https://login.tailscale.com/admin/dns）で、"
                        "MagicDNS と HTTPS Certificates を有効にしてください（一度だけ）。")
        code, out = self.run(["serve", "status", "--json"])
        cfg = _json(out) if code == 0 else None
        v["serving"] = bool(cfg) and any(_to_port(p, self.port) for p in _proxies(cfg))
        return v

    def set(self, on):
        """出す / 止める. 設定にも覚える (オンなら, 起動のたびに出し直す). 状態を返す (うまくいかなければ why に出力)."""
        on = bool(on)
        self.app.save_settings({"remote": {"tailscale": on}})
        note = self.apply(on)
        v = self.view()
        if note and not v.get("why"):
            v["why"] = note
        return v

    def apply(self, on):
        """コマンドを呼ぶだけ (設定は変えない). うまくいかなければ理由の文, うまくいけば None."""
        if on:
            code, out = self.run(["serve", "--bg", str(self.port)])
            if code is None:
                return None                  # 入っていない: view が理由を出す
            if code != 0:
                return ("外向けのアドレスを出せませんでした%s: %s" % ("（返事が返ってきません。HTTPS が有効か確かめてください）" if code == -1 else "", out[:300]))
            return None
        code, out = self.run(["serve", "--https=443", "off"])
        if code not in (None, 0):
            return "止められませんでした: %s（コマンドプロンプトで tailscale serve reset を実行すると、すべて止まります）" % out[:300]
        return None

    def startup(self):
        """起動のとき: 設定がオンなら出し直す (PC の再起動などで消えていても). 入っていなければ何もしない."""
        if not self.wanted():
            return None
        note = self.apply(True)
        self.app.trace.add("tailnet", "起動のとき, 外向けのアドレスを出し直した" if not note else "起動のとき, 出し直せなかった: %s" % note)
        return note
