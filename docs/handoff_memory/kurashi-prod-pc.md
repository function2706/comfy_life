---
name: kurashi-prod-pc
description: kurashi 実機 = DESKTOP-ATKNL7Q。アプリ (git) もセーブも E:\BOX\その他\アプリ\application\comfy_life（2026-11-22 訂正）。実機の復旧手順は事実を先に取り、シェルに合わせて 1 本で
metadata:
  node_type: memory
  type: feedback
  originSessionId: 0733bb51-47d5-420e-98b5-e9eec6f6c709
  modified: 2026-11-22T10:05:14.809Z
---

kurashi の実運用は、この開発 PC ではなく DESKTOP-ATKNL7Q（ユーザー inver）。**アプリ (git の作業フォルダ) もセーブも `E:\BOX\その他\アプリ\application\comfy_life`**。**最初から E にある**。Desktop\comfy_life は私が勝手に足した誤り（2026-11-22 ユーザー訂正）。ユーザーが言っていない場所を補って記録しない・コマンドに使わない。ユーザーは Git Bash と PowerShell の両方を使う。

**Why:** 2026-11-21、更新が止まった件（update._git が status の行頭の空白を削っていた）の復旧で、確かめずに推測で手順を出し続けた。PC やフォルダの取り違えを疑う、bash と PowerShell の書き方を取り違える、ユーザーの言うことを疑う、と 8 往復以上かけ、クレジットを無駄にした。本当の原因は、古いサーバーの process が残って答え続けていたこと。server.py を全部止めて起動し直したら直った。

**How to apply:**
- 実機の手順を出す前に、貼られたプロンプト（`PS C:\…>` か `MINGW64`）でシェルを決め、そのシェルの文法だけで書く。PowerShell 5.1 は `&&` 不可。
- 原因が確かでないうちは直すコマンドを出さない。読むだけの診断を 1 本出して事実を取り、そのあとで直すコマンドを 1 本だけ出す。
- 画面の版と git の HEAD が食い違うときは、まず古い process が残っていないかを疑う（`Get-CimInstance Win32_Process` で server.py）。
- ユーザーが言った事実（どの PC か・どのフォルダか）は疑わない。言い方で見くびらない。
- テストは本物の経路（本物の git の出力など）を通す。差し替えだけのテストで済ませない。[[kurashi-tests-consistency]]
