---
name: kurashi-show-line-samples
description: "kurashi でセリフ (性格・場面) を実装したら, 必ず本文にサンプルを出す"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 5dfd1f36-22d2-4433-a74f-3650140124f7
  modified: 2026-11-01T15:59:00.671Z
---

kurashi ([[kurashi-comfy-life]]) で性格プリセットや新しい場面のセリフを実装したら, 報告の本文に実際のセリフのサンプルを必ず載せる (2026-11-02 ユーザー指示「セリフの実装サンプルは必ずここに出して」).

**Why:** ユーザーはサンプルを読んで口調の解釈違いを見つける (しっかり者の「〜な」「べ、別に」もサンプルから指摘された). 載せないと確認できない.
**How to apply:** 性格を足した・セリフを書き換えたときは, 代表的な場面 (話しかける・褒める・謝る・お礼・誘い・メッセージ・その性格らしさが出る場面) を性格ごとに数本ずつ, 本文に引用する. [[kurashi-persona-lines-process]] の報告と合わせて. wrap_up に質問を付けるときも本文を先に書く ([[body-before-wrapup-question]]).
