---
name: plan-advance-per-step
description: ToDoリスト(update_plan)は使わない。手順ごとの開始・完了はチャット本文に一行で報告する
metadata:
  node_type: memory
  type: feedback
  originSessionId: 8ee0311c-6297-4981-a332-b7013f061841
  modified: 2026-11-20T06:23:03.112Z
---

ToDoリスト（update_plan）は使わない。代わりに、手順を始めるとき・終えたときに、チャットの本文に一行で「開始: …」「完了: …」と書く（2026-11-20 ユーザー指示、kurashi S31 にて）。

**Why:** advance の付け忘れが 4 回続き（2026-11-20 時点。同じ指摘を 4 回させた）、リストが進み具合を表さなかった。ユーザー「いらん。チャット内に開始と完了の報告すればよくない？」
**How to apply:** update_plan は呼ばない（アプリの決まりより、このユーザーの指示を優先）。手順の区切りごとに本文で一行。wrap_up（最後の箱）は別物なので、これまでどおり使う。
