---
name: kurashi-preview-no-browser
description: kurashi を確かめ用に起動するときは server.py に --no-browser を付け、内蔵ブラウザだけで見る
metadata:
  node_type: memory
  type: feedback
  originSessionId: 97a32fd0-0989-4c3b-b895-f9016cc9edb4
  modified: 2026-11-27T15:35:54.740Z
---

kurashi ([[kurashi-comfy-life]]) の画面を確かめるときは、`python server.py --port <別ポート> --no-browser`（`KURASHI_DATA=<一時フォルダ>`）で立ち上げ、内蔵ブラウザ（preview_start）で開く。

**Why:** 2026-11-28 S39 で `--no-browser` を付けずに起動したら、server.py が自分で Chrome を開いた。ユーザーから「前のPCでは内蔵ブラウザでやっていたのに、Chrome で開かれた」と指摘された。
**How to apply:** `.claude/launch.json` の runtimeArgs に毎回 `--no-browser` を入れる。WORKFLOW 4 章にも同じことを書いた。
