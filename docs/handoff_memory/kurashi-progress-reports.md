---
name: kurashi-progress-reports
description: kurashi の長い作業 (全テストなど) は途中の進捗を区切りごとに伝える
metadata:
  node_type: memory
  type: feedback
  originSessionId: 5dfd1f36-22d2-4433-a74f-3650140124f7
  modified: 2026-11-06T07:15:39.857Z
---

kurashi ([[kurashi-comfy-life]]) で時間のかかる作業は, 途中で進捗を伝える (2026-11-06「長いので途中の進捗報告は欲しい（今後も）」).

**Why:** 全テストなど数分〜かかる作業の間, 何が起きているか分からない.
**How to apply:** 全テストは 1 本の背景実行にせず, いくつか (分野ごと・3〜4 回) に分けて流し, 区切りごとに「◯/115 本、落ちたもの」を一行で伝える. 長い実装も手順の区切りで一言. 報告は短く (クレジット節約 [[kurashi-cost-over-speed]]).
