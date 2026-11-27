---
name: kurashi-session-workflow
description: kurashi は作業 1 つごとに新セッション。作業前に kurashi/docs/WORKFLOW.md を読む（決まりはそこに集約）
metadata:
  node_type: memory
  type: feedback
  originSessionId: 953dd1c1-bfe8-4788-90a8-e61822215941
  modified: 2026-11-14T03:39:31.108Z
---

kurashi ([[kurashi-comfy-life]]) の作業は、まず `kurashi/docs/WORKFLOW.md` を読み、そこに書いた範囲だけ docs を読む（全部は読まない）。
ユーザーの最初のひとことは「残件 S3」「設計 A15」「残件追加: …」「不具合: …」「セリフ …」「全テスト」の形で来る（WORKFLOW 1 章）。

- セッションは作業 1 つ（REMAINING.md の「まとまりの表」の 1 行）ごとにユーザーが新しく立てる。長く使い回さない。
- 残件を足すたびに、まとまりの吟味（同じ所を触るものを 1 セッションに）をして表を直す。
- 性格別セリフは実装とは別のセッション。全テストはユーザーが実行セッションを指示する。
- Fable は基本設計のみを担当し、キャンペーン終了後の実装は Sonnet / Opus に任せる想定（2026-11-14 ユーザー）。だから残件と設計は、会話なしで読んで着手できる書き方にする。
- kurashi の決まりを新しく言われたら、memory だけでなく WORKFLOW.md にも書く（別モデル・別PCのセッションが読めるように）。

**Why:** 2026-11-14 ユーザー。長いセッションはクレジット消費が増えるため（[[kurashi-cost-over-speed]]）。
**How to apply:** kurashi の話が出たら WORKFLOW.md から。版の決まりは [[kurashi-versioning]]。
