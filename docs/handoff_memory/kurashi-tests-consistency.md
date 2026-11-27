---
name: kurashi-tests-consistency
description: kurashi の全テストはクレジットに響かないので、整合性を確かめるテストはいくらでも増やしてよい
metadata:
  node_type: memory
  type: feedback
  originSessionId: 81ac0c06-9095-4f5b-8434-0f3a9f37b689
  modified: 2026-11-07T05:20:08.379Z
---

kurashi の全テストはクレジットにほぼ響かない（ローカルで流すだけ）ので、テストはいくらでも増やしてよい。整合性を重視する。

**Why:** デート中に家事やジョギングができてしまった（2026-11-07）。どのテストも「この状態で、本来できないものが押せる」組み合わせを見ていなかった。ユーザーは「これくらいテストで解消できていると思っていた」と言っている。

**How to apply:** 状態を変える変更をしたら、状態 × 行動の総当たりや「画面で押せる＝本当にできる」の突き合わせを、テストに足す（例: `test_out_with_solo`、`test_state_matrix`）。長くなっても気にしない。毎回流すのは関連テストだけで、全テストは頼まれたときだけ（[[kurashi-test-cadence]]）。
