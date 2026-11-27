---
name: kurashi-versioning
description: "kurashi の版管理と進め方 (2026-11-06): VERSION/CHANGES/REMAINING, 機能=minor・修正=patch, 全テストは頼まれた時だけ, beta 表記"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 5dfd1f36-22d2-4433-a74f-3650140124f7
  modified: 2026-11-06T15:25:51.013Z
---

kurashi ([[kurashi-comfy-life]]) の進め方 (2026-11-06 ユーザー指示). クレジット節約が第一 ([[kurashi-cost-over-speed]]).

- 版は `kurashi/VERSION`. 1.0.0 = c987217 時点. 履歴と次の版の中身は `docs/CHANGES.md`, 残件は `docs/REMAINING.md` (機能追加 / 修正 を分ける).
- 機能追加コミット → 次の版で minor を上げる (1.0.0→1.1.0). 修正コミット → patch (1.0.0→1.0.1).
- 1 つの版に機能追加だけ/修正だけを複数載せてよい. 混在させないのは**努力義務** (2026-11-07 緩和: 緊急修正パッチの意味合いもあるため. 混ぜたら区分に「機能追加・修正」と書く).
- **全テストはユーザーが要求するまで流さない.** 部分テスト = 実装の差分と関連モジュールのテストだけ.
- **版を上げる (VERSION を書き換える) のは全テスト完了時だけ.** それまでは CHANGES の「次の版」に「x.y.zbeta」として載せる. 実装直後で部分テスト前は alpha (ふだんは実装のすぐあと部分テストまでやるので beta から).
- 残件 (docs/REMAINING.md) は**版の候補ごとのまとまり**で並べる (修正 F1.. / 機能追加 A1..、一緒に直すとよいものを自動でまとめる。混ぜない). 各行に状態・追加日・重さ (軽/中/重) を書く (2026-11-06 指示).
- 残件は精密に: 片付いたら REMAINING から消して CHANGES の次の版へ. 新しく見つけた・提案して保留したものは区分を付けて足す ([[kurashi-remaining-list]]: 確認待ちは入れない).

**Why:** 変更が増えて、何がどの版に入ったか・何が残っているかを追えるようにしたい. 全テストは重いので節約のため.
**How to apply:** コミットのたびに CHANGES の次の版 (区分・beta) と REMAINING を更新して同じコミットに入れる. 全テストを頼まれて通ったら VERSION を上げ, 次の版を確定の見出しにする. 旧 [[kurashi-test-cadence]] の「全テストは最後に一度」はこれで置き換え (頼まれたときだけ).
