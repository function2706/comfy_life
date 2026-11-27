---
name: kurashi-s17-no-more-stages
description: kurashi S17（A11 交通網と道）は段に分けない。残りを 1 つの作業として一度にやる
metadata:
  node_type: memory
  type: feedback
  originSessionId: 3a28d98d-a68e-46df-9a97-5c4eeff664a5
  modified: 2026-11-20T18:50:20.792Z
---

S17（残件 A11 交通網と道）は段に分けない。残り（道路網・路線・時間帯・混雑・快速）を 1 つの作業として一度にやる（2026-11-21 ユーザー指示）。

**Why:** 過去のセッションが勝手に A11 を段 1・段 2 に切っていた。「段 2 で打ち止め」と受け取ったら違うと言われた — 打ち止めではなく「分けるな」。

**How to apply:** S17 の設計・実装で段に切らない（設計に「段の切り方」を書く形でも、段を作らない）。残件にも「段 n」と書かない。分けないと無理だと思ったら、切る前にユーザーに聞く。REMAINING.md の S17 行・A11 にも書いてある。関連: [[kurashi-versioning]] [[kurashi-remaining-list]]
