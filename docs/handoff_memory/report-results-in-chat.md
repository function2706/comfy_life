---
name: report-results-in-chat
description: 別セッションの作業結果は、確認の箱だけで済ませず必ずこの会話の本文に中身を書く
metadata:
  node_type: memory
  type: feedback
  originSessionId: 1b8797c1-a8d8-4eac-8c1d-73695d5df51d
  modified: 2026-10-26T04:53:59.297Z
---

別セッション（kurashi-3 など）が作業を終えたら, 結果の中身（何を実装したか・数値・決め手・残り）を必ずこの会話の本文に書いて報告する.
wrap_up の箱（recap と質問）だけで終わらせない. 了承待ちの質問も, 結果を書いた後に出す.

**Why:** 2026-10-26, 反応系メッセージの改修完了時に箱だけで了承を求めたら「その前に結果を書いて、必ずこのチャンネルに今後も表示すること」と指示された.
**How to apply:** 完了通知を受けたら list_events で報告全文を読み, 要点を本文に書いてから wrap_up する. [[kurashi-comfy-life]]
