# Ancilla-Bot

クラウドに依存しない、自律した常駐型 LLM アシスタントエージェント

## 要件

- Python 3.11+
- [Ollama](https://ollama.com/)（ローカルで稼働していること）
- （任意）SearXNG（Web 検索ツール用）
- （任意）Discord  Bot トークン（Discord 連携時）

## インストール

```bash
git clone <repo>
cd ancilla-bot
pip install -e .
```

## 設定

プロジェクトルートに `.env` を置く。`.env.example` をコピーして編集する。

```bash
cp .env.example .env
```

主な項目:

| 変数 | 説明 | 既定 |
|------|------|------|
| `OLLAMA_BASE_URL` | Ollama の URL | `http://localhost:11434` |
| `OLLAMA_MODEL` | メインモデル名 | `qwen3:4b` |
| `OLLAMA_VISION_ENABLED` | メインモデルが視覚対応なら true | `true` |
| `ANCILLA_MAX_HISTORY_CHARS` | 会話履歴の最大文字数 | `4000` |
| `ANCILLA_API_PORT` | 常駐時の API ポート | `8765` |
| `DISCORD_BOT_TOKEN` | Discord Bot トークン（`ancilla discord` 用） | - |

エージェントの人格・ルールは `workspace/AGENT.md`、ユーザー情報は `workspace/USER.md`。作業範囲は `workspace/` 以下。

## 使い方

### REPL のみ（単発）

```bash
ancilla
```

対話して終了するまで。終了は `exit` / `quit` / `:q`。

### 常駐モード（推奨）

```bash
ancilla run
```

- 同一プロセスで REPL + HTTP API + Heartbeat（Fast / Slow）が動く
- 会話履歴は共有され、コンテキストが逼迫すると要約して圧縮しつつ長期記憶に送る
- リマインダー・タスクは SQLite で管理され、Fast Heartbeat で発火するとエージェントに渡される

終了は REPL で `exit` 等。

### クライアント（API に接続）

先に `ancilla run` を起動したうえで、別ターミナルで:

```bash
ancilla client
```

同じデーモンに接続する REPL。`ANCILLA_API_HOST` / `ANCILLA_API_PORT` で接続先を変更可能。

### Discord Bot

先に `ancilla run` を起動し、`.env` に `DISCORD_BOT_TOKEN` を設定して:

```bash
ancilla discord
```

DM または Bot メンションでメッセージを送ると、デーモン経由で応答する。画像添付にも対応（`OLLAMA_VISION_ENABLED=true` かつ視覚対応モデル時）。

### バッチ要約

```bash
ancilla batch summarize
```

会話ログ（overflow + active）をブロック単位で要約し、JSONL と ChromaDB に保存。長期記憶の検索（`search_memory`）で参照される。常駐時の Slow Heartbeat でも同処理が深夜に実行される。

## サブコマンド一覧

| コマンド | 説明 |
|----------|------|
| （なし） | REPL のみ（単発） |
| `run` | 常駐（REPL + API + Heartbeat） |
| `client` | API に接続する REPL クライアント |
| `discord` | Discord Bot |
| `batch summarize` | 会話の要約バッチ |

オプション: `-v` / `--verbose`（DEBUG ログ）、`-r` / `--show-reasoning`（思考・ツール表示）、`--log-file PATH`。

## ツール

- `get_time` … 現在日時
- `web_search` … Web 検索（SearXNG）
- `read_file` / `write_file` … workspace 内ファイル
- `update_memory` … USER.md / AGENT.md 更新
- `search_memory` … 長期記憶（要約）のベクトル検索
- `manage_state` … SQLite（tasks, reminders, finances, audit_log）の CRUD

## ライセンス

未定
