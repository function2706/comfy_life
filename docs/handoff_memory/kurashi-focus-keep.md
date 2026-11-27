---
name: kurashi-focus-keep
description: kurashi の画面は 30 秒ごとに描き直す. 入力中の欄のフォーカスが外れる不具合はテスト項目 (test_focus_keep) で見張る
metadata:
  node_type: memory
  type: feedback
  originSessionId: 81ac0c06-9095-4f5b-8434-0f3a9f37b689
  modified: 2026-11-06T17:29:41.464Z
---

kurashi ([[kurashi-comfy-life]]) の static/app.js は refresh (30 秒ごと) で画面を描き直す. 欄が作り直されると, 開いたプルダウンが閉じてフォーカスが外れる. 2 回起きた (地図の経路検索のプルダウンほか). 2026-11-07 に「テスト項目化しておいて」と言われ, `editingForm()` で入力中は描き直しを待つ形にし, ブラウザのテスト `tools/test_focus_keep.py` を足した.

**Why:** 同じ種類の不具合が別の画面で繰り返し出ていた.
**How to apply:** プルダウン・時刻・文字の欄を新しく足したら, 描き直しのたびに作り直される場所かを考える. `test_focus_keep` に、その欄を確かめる項目を足す（部分テストにも入れる）. 描き直しを `renderState` 以外の周期処理で足すときは, `editingForm()` で待つ.
