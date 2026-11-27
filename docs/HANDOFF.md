# 別PCでの開発の引き継ぎ（2026-11-28）

開発用PCを一時的に替えるための手順。これだけ読めば続きができる。
（実運用の PC = DESKTOP-ATKNL7Q `E:\BOX\その他\アプリ\application\comfy_life` は変わらない。）

## 1. 引き継ぎ時点の状態

- `main` = `f638b92`（2026-11-27 23:52）。作業ツリーはきれい・push 済み。
- 版: `VERSION` は 1.7.0、CHANGES の「次の版」= 1.8.0beta を積み上げ中（全テスト前）。
- ほかのブランチ: `hold/sincerity`（保留の「誠実さ」。触らない）。
- 次にやることは [REMAINING.md](REMAINING.md) の「まとまりの表」。進め方は [WORKFLOW.md](WORKFLOW.md)（セッションは最初にこれを読む）。

## 2. 新しいPCの準備

要るもの: Git（GitHub に push できる認証）、Python 3.8 以上（追加パッケージ不要）、Claude デスクトップアプリ。

フォルダの形はこのPCと同じにする（親フォルダで Claude を開き、その中に `kurashi`）:

```powershell
mkdir C:\work\claude; cd C:\work\claude
git clone https://github.com/function2706/comfy_life.git kurashi
```

（`C:\work\claude` は例。好きな場所でよい。以下 `<作業フォルダ>` と書く。）

## 3. Claude の記憶（メモリー）を移す

このPCで溜めた kurashi の決まり・ユーザーの好み（日本語で返す・ToDo を使わない・サブエージェント禁止・必ず push など）は `docs/handoff_memory/` に写してある。
新しいPCで、**Claude で `<作業フォルダ>` を一度開いてから**、PowerShell で次を打つ（記憶の置き場は作業フォルダのパスから決まる）:

```powershell
cd <作業フォルダ>; $d="$HOME\.claude\projects\" + ((Get-Location).Path -replace '[^A-Za-z0-9]','-') + "\memory"; New-Item -ItemType Directory -Force $d | Out-Null; Copy-Item kurashi\docs\handoff_memory\*.md $d -Force; Get-ChildItem $d | Measure-Object | Select-Object Count
```

33 個（`MEMORY.md` を含む）と出れば済み。新しいセッションで「kurashi の記憶を確認して」と聞けば読めているか分かる。

## 4. 「仕様」グループと、右に REMAINING.md が出る状態

このPCでは、サイドバーの手動グループ「仕様」から新しいセッションを始めると、右のファイル枠に `kurashi/docs/REMAINING.md` が開いた状態になる。
設定ファイル（`.claude/`・`launch.json`・アプリの設定）にはそれを指定する項目が無く、アプリが**最後に開いていたファイル枠を覚えている**ものと見られる（確証なし）。再現の手順:

1. Code タブのサイドバーで新しいグループを作り、名前を「仕様」にする。
2. `<作業フォルダ>` を作業フォルダにしてセッションを始め、そのセッションを「仕様」に入れる。
3. 右のファイル枠を開き、`kurashi/docs/REMAINING.md` を開いておく。
4. 次の新しいセッションでも開いたままになっていれば完了。ならなければ、セッションの最初に「REMAINING.md を右に出して」と言えば開ける。

## 5. このPCと違う所の注意

- WORKFLOW 4 章の「8765 番は別のアプリが使っている」はこのPCの話。新しいPCでも、確かめるときは `KURASHI_DATA=<一時フォルダ>` と別のポートで動かす（実データを汚さないため）。画像生成は `tools/mock_comfy.py`。
- `<作業フォルダ>\.claude\launch.json`（確かめ用のサーバー定義）は持っていかなくてよい。セッションが必要なときに作る。
- 記憶の中の「このPC」「開発PC」は、新しいPCのことと読み替える。
- コードを書くセッションは同時に 1 つだけ（WORKFLOW 10 章）。**元のPCと新しいPCで同時に書かない**。戻すときは、新しいPCで push → 元のPCで `git pull`。

## 6. 元のPCに戻るとき

1. 新しいPCで全部 commit・push 済みか `git status -sb` で確かめる。
2. 元のPCの `kurashi` で `git pull`。
3. 新しいPCで増えた記憶があれば、`docs/handoff_memory/` に写して push し、元のPCの記憶の置き場へ同じように写す（3 章のコマンドを元のPCで）。
