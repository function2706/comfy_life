---
name: kurashi-test-cadence
description: kurashi のテストは変更ごとに関連するものだけ、全テスト (10 分超) は一通り実装し終えた最後に一度
metadata:
  node_type: memory
  type: feedback
  originSessionId: 5dfd1f36-22d2-4433-a74f-3650140124f7
  modified: 2026-10-30T08:57:43.528Z
---

kurashi では、変更のたびに全テスト (tools/test_*.py 約 80 本, 10 分以上) を流して待たない。
一通り実装する間は、足したテストと触ったところに関係するテストだけを流してコミットし、全テストは最後に一度だけ流す。
落ちたものはそこで直してから報告する。
2026-10-31 追認: 大きな改修中に全テストを流して待つのも不要。「実装→部分テスト→実装→部分テスト→…→全テスト」の順。
マップのように進め方を任されたものは、段階ごとに確認を取らず最後まで進める（[[autonomy-preference]]）。

**Why:** 2026-10-30 ユーザー「これ毎回全テストやるの？」「一通り実装して、その度に関連するところだけテストして、最後に全テストでよくない？」。
全テスト待ちで毎回報告が遅れていた。
**How to apply:** 関連テストの目安: 触ったモジュール名の test_*、engine/chat/presence を触ったら test_chat・test_msgreply・test_presence・test_manners、
性格別セリフを足したら check_persona・check_tone・test_personas。最後の全テストは前景か、裏で流して結果を待ってから報告。関連: [[kurashi-comfy-life]]
