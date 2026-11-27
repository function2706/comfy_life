---
name: kurashi-commit-subject
description: kurashi のコミットは 1 行目（英語の短い件名）と本文の間に必ず空行。件名に本文が連なると更新チェック欄が見づらい
metadata:
  node_type: memory
  type: feedback
  originSessionId: 0c6e4210-6ba0-49e6-90d2-f7d983a612f1
  modified: 2026-11-21T14:16:21.477Z
---

kurashi のコミットメッセージは、1 行目を短い英語の件名だけにし、本文（日本語の箇条）との間に必ず空行を入れる。`git commit -m "件名" -m "本文"` の形で書く（-m 1 つに改行で続けると空行が無く、件名に本文が全部連なる）。

**Why:** 2026-11-21、ea1239d などで件名と本文の間に空行が無く、アプリの更新チェック欄（git log の件名を出す）に本文まで一行で出て見づらいと言われた。

**How to apply:** コミットのたびに -m を件名用と本文用に分ける。push 済みのものは書き換えない。[[kurashi-always-push]]
