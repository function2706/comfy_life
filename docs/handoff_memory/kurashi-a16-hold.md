---
name: kurashi-a16-hold
description: kurashi A16（外出先から操作）は main に取り込み済み（1.7.0beta）。残りは実機確認と制限 2 つ
metadata:
  node_type: memory
  type: project
  originSessionId: a958be65-2390-4883-bdb9-19c2e6811604
  modified: 2026-11-13T05:54:02.340Z
---

kurashi の残件 A16（スマホ用の入り口 `/phone`・閉じている間の進行 `core/remote.py`・Web Push `core/push.py`）は、2026-11-13 に main へ取り込んだ（早送り。11a81e8 まで。VERSION 1.7.0beta）。保留ブランチ `hold/a16-phone` は消した。同日 origin/main にプッシュ済み。

- 未確認: 実機（Tailscale・iPhone と Android での通知の許可と受信）。ユーザー側の作業。全テストは未実施。
- 残り（REMAINING の A16）: 同居相手へ閉じている間に送れない・`appoint.live` を閉じている間は進めていない。
- 決定済み: スマホは両方、待ち時間は届いた時から、署名は自前・本文なし、画面は既存の 📱 だけ。
- `test_focus_keep` は、画面なしの Edge がページを 2 つ読む競争をやり直しで避ける形に直した（1 回 100 秒ほど）。
- 確認用サーバは親フォルダの `.claude/launch.json` の `kurashi-a16`（一時データ。起動スクリプトはその時のスクラッチパッドにあるので、無ければ作り直す）。

**Why:** 2026-11-10 にクレジットの都合で保留 → 11-13 に再開して仕上げ、ユーザーの「取り込む」で main へ。
**How to apply:** 実機で通知が来ないと言われたら、説明書 `#remote` の手順と `data/push.json` の端末の `err` を見る。このシェルの heredoc は `\\n` や `\\/` のバックスラッシュを壊すことがあるので、バックスラッシュを含むパッチは Write で作ったスクリプトか Edit で当てる。関連: [[kurashi-versioning]] [[kurashi-cost-over-speed]]

**2026-11-15 追記**: 残りの制限 2 つ（同居相手にスマホから送れない・閉じている間は約束の連絡が届かない）は 49ff173 で解消。REMAINING から A16 は消えた。残りは実機確認だけ。
