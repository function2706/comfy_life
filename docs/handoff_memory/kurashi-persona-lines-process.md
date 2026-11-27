---
name: kurashi-persona-lines-process
description: kurashi の性格別セリフは聞かずに・残件にせず、実装と同じ作業の中で全性格ぶん書き上げる（別コミット）
metadata:
  node_type: memory
  type: feedback
  originSessionId: a31c2e58-c13c-4b7d-b0fa-12c8e99c4a02
  modified: 2026-11-15T11:01:36.196Z
---

kurashi ([[kurashi-comfy-life]]) で新しい場面 (セリフのキー) が増えたときの手順 (2026-11-15 ユーザー指示で改定):
1. 実装変更をコミット (共通セリフだけ入れる).
2. **聞かずに、同じセッションで続けて**性格別セリフを全性格ぶん書き、別コミットにする. 行数は報告に書くだけ.
3. 「セリフ待ち」を REMAINING に足さない. 性格別セリフまで書いて、はじめて完成.

**Why:** 2026-11-15、着せ替え → お願いタブの作業で「セリフ待ち 135 行」を残件 A27 に足して報告したら、
ユーザー: 「セリフも勝手に足されるべきではない残件」「何も言わずに残件とせず、最初からそこまで追加で完成とすべき」.
残件は減らすのが正義で、勝手に増やさない ([[kurashi-remaining-list]]) の延長.
旧手順 (2026-10-21: 書く前に追加予定数を報告して了承を待つ / 別セッションで書く) はこれで置き換え.

**How to apply:** 書き方の決まりは変わらない ([[kurashi-persona-tone-samples]]・[[kurashi-show-line-samples]]: 口癖で性格を出さない・報告に代表例を引用).
docs/WORKFLOW.md の 1 章・5 章にも同じ決まりを書いてある.
