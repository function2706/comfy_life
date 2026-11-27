---
name: resume-on-error-immediately
description: 別セッションがAPIエラーで止まった通知が来たら、ユーザーに聞かれる前にその場で再開させる
metadata:
  node_type: memory
  type: feedback
  originSessionId: 1b8797c1-a8d8-4eac-8c1d-73695d5df51d
  modified: 2026-10-26T10:45:31.148Z
---

別セッションが API エラー（TLS・InvalidHTTPResponse・利用上限など）で止まったという通知が届いたら、そのターンのうちに確認なしで SendMessage して再開させる。ユーザーに言われるのを待たない。再開させたことは一行で伝える。

**Why:** 2026-10-26、エラー通知を受けたまま再開させず、ユーザーに「監視してる？あなたがエラー時に復帰させるんよ？」と二度言われた。
**How to apply:** 通知の中に "ended its turn with an error" があれば、git の状態を確かめたうえで、すぐに続きの指示を送る。利用上限ならリセット時刻を確かめて、その後に再開させる。[[kurashi-comfy-life]]
