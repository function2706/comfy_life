"""外出先から (スマホ用の入り口 /phone・通知): 家の画面を閉じている間も, 相手の側だけを時間どおりに進める.

ふだんは, 時間を進めるのは家の画面の更新 (state_view) で, 閉じていた間は次に開いたときにまとめて計算する (outdoor.check_gap →
offline.simulate). それだと, 閉じている間に「メッセージが届いた」という出来事がその時刻には存在しないので, スマホで読むことも
通知することもできない. ここでは設定 (settings.remote.live) がオンのとき, サーバが 1 分おきに (server.py の ticker):

- 連絡先を知っていて離れている相手の時間を進める (App.tick)
- 離れている相手からのメッセージの抽せん (presence.live. 画面を開いているときと同じ多さ)
- 返事待ちの返信を届ける (App.deliver_due)

あなた自身の過ごし方 (仕事・買い物・食事・約束) は進めない: 今までどおり, 家の画面を開いたときにまとめて (行動パターン・予定).
そのまとめのメッセージ (offline._messages) は, ここで進めた時間 (spans) を除いて数える (二重に届かない).
返事の待ち時間は, 届いた時から数える (通知が来たのに返さなければ, ふつうに「返事がなかった」. 予定の「自動の応答」を
組んでいれば, 待ち時間が切れたときに弱い自動の返事). 設定がオフなら, 何もしない (今までどおり).
PC がスリープして間が空いた分は進めない (その分は, まとめの計算に任せる).
"""
import threading
import time

STEP_SEC = 60            # 進める間隔 (server.py の ticker)
BREAK_SEC = 300          # これより間が空いたら (PC のスリープなど), 続きにしない: その間はまとめの計算に任せる
NEWS_KEEP = 40           # 届いたものの控え (通知から開いたスマホが取りに来る)


class Remote:
    def __init__(self, app):
        self.app = app
        self.active = False          # いま step の中 (presence.live が, 閉じている間の抽せんを通す)
        self.news = []               # 届いたもの [{id, t, cid, name, text}] (新しい順ではなく, 届いた順)
        self._seq = 0
        self._nlock = threading.Lock()
        self.on_news = None          # 届いたときに呼ぶ (通知の送信. core/push.py)

    # ------------------------------------------------------------------ 設定・記録
    def live_on(self):
        return bool((self.app.settings.get("remote") or {}).get("live"))

    def spans(self):
        """ここで進めた時間 [[始まり, 終わり]] (あなたの状態に. 最後の心拍より前のものは捨てる)."""
        return self.app.presence.rec().setdefault("remote_spans", [])

    def covered(self, t):
        return any(a <= t <= b for a, b in self.app.presence.rec().get("remote_spans") or [])

    def uncovered(self, t0, t1):
        """t0〜t1 のうち, ここで進めていない秒数."""
        got = 0.0
        for a, b in self.app.presence.rec().get("remote_spans") or []:
            got += max(0.0, min(b, t1) - max(a, t0))
        return max(0.0, (t1 - t0) - got)

    def closed(self, now):
        """家の画面が閉じている (心拍が途絶えている) か."""
        p = self.app.presence.rec()
        return now - p.get("beat", 0) > self.app.presence._gone_sec()

    # ------------------------------------------------------------------ 進める
    def step(self, now=None):
        """1 分おきに. 家の画面が閉じていて, 設定がオンなら, 相手の側を進める. 届いたもの [{cid, name, text}] を返す."""
        app = self.app
        if not self.live_on():
            return []
        now = now or time.time()
        with app.lock:
            if not self.closed(now):
                return []                    # 家の画面が開いている: そちらが進める
            p = app.presence.rec()
            sp = self.spans()
            beat = p.get("beat", 0)
            sp[:] = [s for s in sp if s[1] > beat][-50:]
            if sp and now - sp[-1][1] <= BREAK_SEC:
                sp[-1][1] = now
            else:
                sp.append([now, now])        # 始まり・間が空いたあと: ここから (空いた間は, まとめの計算に)
            out = []
            self.active = True
            try:
                for cid in list(app.chars):
                    if app.bonds.stage(cid) == "known" or app.bonds.together(cid):
                        continue
                    app.tick(cid, now)
                    st = app.state(cid)
                    e = app.presence.live(app.chars[cid], st, now)
                    if e:
                        app.save_state(cid)
                out = app._deliver_due(now)
            finally:
                self.active = False
            app.presence.save()
            return out

    # ------------------------------------------------------------------ 届いたものの控え
    def note(self, cid, it):
        """相手の発言がトークに入った (chat.add). いま届いたものだけ控える (まとめの計算で時刻をさかのぼって入るものは除く)."""
        now = time.time()
        if abs(now - float(it.get("t") or now)) > 120:
            return
        char = self.app.chars.get(cid) or {}
        with self._nlock:
            self._seq += 1
            n = {"id": self._seq, "t": it["t"], "cid": cid, "name": char.get("name", ""),
                 "text": str(it.get("text") or "").replace("📱『", "").replace("』", "").split("\n")[0][:80]}
            self.news.append(n)
            del self.news[:-NEWS_KEEP]
        if self.on_news:
            try:
                self.on_news(n)
            except Exception as e:  # noqa: BLE001  (通知が送れなくても, 届いたこと自体は変わらない)
                self.app.trace.add("remote", "通知を送れなかった: %s" % e, cid, now)

    def add_news(self, cid, name, text):
        """控えに 1 件足す (通知のテスト)."""
        with self._nlock:
            self._seq += 1
            n = {"id": self._seq, "t": time.time(), "cid": cid, "name": name, "text": text}
            self.news.append(n)
            del self.news[:-NEWS_KEEP]
        return n

    def news_since(self, since=0):
        with self._nlock:
            return [n for n in self.news if n["id"] > int(since or 0)]
