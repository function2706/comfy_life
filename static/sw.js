/* Comfy LIFE: スマホの通知を受け取る service worker (core/push.py).
   通知の合図には本文が無い. 合図を受けたら, 家の PC から届いたものを取りに行って (GET /api/phone/news) 通知に出す.
   取りに行けなければ (圏外・Tailscale が切れている), 「新しいメッセージ」とだけ出す.
   ページの置き場 (キャッシュ) はしない: 画面はいつも家の PC から読む. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('push', (e) => {
  e.waitUntil((async () => {
    let title = 'Comfy LIFE';
    let body = '新しいメッセージが届いています';
    let tag = 'comfy-life';
    try {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 6000);
      const r = await fetch('/api/phone/news?since=0', { cache: 'no-store', signal: ctl.signal });
      clearTimeout(timer);
      const news = (await r.json()).news || [];
      const n = news[news.length - 1];
      if (n && Date.now() / 1000 - n.t < 900) {          // いま届いたもの (古い控えは出さない)
        title = n.name || title;
        body = n.text || body;
        tag = 'comfy-life-' + n.cid;                       // 同じ相手の通知は, 新しいものに置き換える
      }
    } catch (err) { /* 取りに行けない: 本文なしで知らせる */ }
    await self.registration.showNotification(title, {
      body, tag, renotify: true, icon: '/static/img/icon-192.png', badge: '/static/img/icon-badge.png', data: { url: '/phone' },
    });
  })());
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  e.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const open = all.find((c) => new URL(c.url).pathname.replace(/\/+$/, '') === '/phone');
    if (open) return open.focus();
    return self.clients.openWindow('/phone');
  })());
});
