---
name: kurashi-always-push
description: kurashi はコミットしたら必ず push する（聞かずに、docs だけのコミットも）
metadata:
  node_type: memory
  type: feedback
  originSessionId: 7e116952-f778-437e-8f1c-ca68bddaf68b
  modified: 2026-11-14T19:12:24.844Z
---

kurashi（comfy_life）では、コミットしたら毎回そのまま `git push` する。確認は取らない。docs だけのコミットも同じ。

**Why:** 2026-11-15 にユーザーが「pushは必ずして、これからも」と指示した（それまでの WORKFLOW では「push は言われたら」だった）。
**How to apply:** コミットの直後に push し、報告で push 済みと書く。kurashi/docs/WORKFLOW.md 4 章にも反映済み。関連: [[kurashi-session-workflow]] [[kurashi-versioning]]
