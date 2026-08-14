# Ancilla

クラウドに依存しない、自律した常駐型 LLM アシスタントエージェント。

## 要件

- Python 3.11+
- LLM サーバー（いずれか 1 つ）:
  - [Ollama](https://ollama.com/)（ローカルで稼働していること。既定プロバイダ）
  - OpenAI 互換 API（llama.cpp 等。`LLM_PROVIDER=openai`）
- （任意）SearXNG … `web_search` ツール用
- （任意）Discord Bot トークン … `ancilla discord` 用
- （任意）Slack App トークン … `ancilla slack` 用（Socket Mode）
- （任意）STT / TTS サーバー … WebSocket 経由の音声入出力用（faster-whisper-server / Coeiroink 等）

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

主な項目（全項目は `.env.example` 参照）:

| 変数                                    | 説明                                                                       | 既定                     |
| --------------------------------------- | -------------------------------------------------------------------------- | ------------------------ |
| `LLM_PROVIDER`                          | `ollama` または `openai`（llama.cpp 等の OpenAI 互換）                     | `ollama`                 |
| `LLM_BASE_URL` / `LLM_MODEL`            | OpenAI 互換プロバイダの URL / モデル（`LLM_PROVIDER=openai` 時に必須）    | -                        |
| `LLM_EMBED_PROVIDER`                    | 埋め込みだけ別プロバイダにする場合（例: チャット=openai, 埋め込み=ollama）| `LLM_PROVIDER` と同じ     |
| `OLLAMA_BASE_URL`                       | Ollama の URL                                                              | `http://localhost:11434` |
| `OLLAMA_MODEL`                          | メインモデル名                                                             | `qwen3:4b`               |
| `OLLAMA_EMBED_MODEL`                    | 埋め込み用モデル（RAG 有効時）                                             | `nomic-embed-text`       |
| `OLLAMA_VISION_ENABLED`                 | メインモデルが視覚対応なら true（画像付きメッセージ対応）                  | `true`                   |
| `ANCILLA_MAX_HISTORY_CHARS`             | 会話履歴の最大文字数。未設定なら LLM の n_ctx から自動算出                 | 自動（取得不可時 4000）  |
| `ANCILLA_TOOL_MODE`                     | ツール呼び出し方式: `gbnf`（JSON Schema 制約）\| `native`（Ollama tools=） | `gbnf`                   |
| `ANCILLA_HEARTBEAT_TIME`                | Slow Heartbeat（要約バッチ）の実行時刻                                     | `03:00`                  |
| `ANCILLA_VERIFY_ANSWER`                 | 回答の自己検証（Self-Reflection）の有効/無効                               | `true`                   |
| `ANCILLA_RAG_ENABLED`                   | 長期記憶のベクトル検索（ChromaDB）有効/無効                                | `true`                   |
| `ANCILLA_PLUGINS`                       | ドメインプラグイン（カンマ区切り: `research,learning,meeting`）            | -                        |
| `ANCILLA_API_HOST` / `ANCILLA_API_PORT` | 常駐時の HTTP API アドレス/ポート                                          | `127.0.0.1` / `8765`     |
| `ANCILLA_WS_PORT`                       | WebSocket サーバーのポート（フロントエンド/エッジデバイス接続用）          | `8766`                   |
| `DISCORD_BOT_TOKEN`                     | Discord Bot トークン（`ancilla discord` 用）                               | -                        |
| `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN`   | Slack Bot トークン（`ancilla slack` 用、Socket Mode）                      | -                        |

エージェントの人格・ルールは `workspace/AGENT.md`（native モード時は `workspace/AGENT.native.md`）、ユーザー情報は `workspace/USER.md`。システムプロンプトの Markdown は `data/prompts/`（`CHARACTER.md` / `TOOLS.md`）。作業範囲は `workspace/` 以下に制限されます。

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

同一プロセスで REPL + HTTP API + WebSocket + Heartbeat が動きます。

- **HTTP API**: `POST /chat`（`{"message": "..."}`、任意で `images`）、`POST /cancel`、`GET /health`
- **WebSocket**: 音声/画像入力・エッジセッション・自律観察ループ（プロトコルは `docs/ws_client_api.md`）
- **Fast Heartbeat**（60 秒周期）: 期限到来のタスク・リマインダーを発火してエージェントに渡す。仕事が無いときは ambient シグナルからプロアクティブ判定
- **Slow Heartbeat**（既定 03:00 に 1 日 1 回）: 会話のバッチ要約を JSONL + ChromaDB に保存
- **Idle Reflection**: 最終入力から 30 分以上（`ANCILLA_IDLE_THRESHOLD_MIN`）経過すると自律行動
- 会話履歴は全経路で共有され、コンテキストが逼迫すると要約で圧縮しつつ長期記憶に送る

REPL を不要にして API・Heartbeat だけを常駐させる場合は `ancilla run --no-repl`。終了は REPL で `exit` 等。

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

### Slack Bot

先に `ancilla run` を起動し、`.env` に `SLACK_BOT_TOKEN` と `SLACK_APP_TOKEN` を設定して:

```bash
ancilla slack
```

Socket Mode を使用するため公開 URL は不要。メンション/DM で応答する。

### agent run の記録・トレース・再開

各応答は SQLite の `agent_runs` / `agent_run_steps` に記録されます。

```bash
ancilla runs               # agent_runs の一覧（--limit N）
ancilla trace <run_id>     # 実行ステップの表示
ancilla resume <run_id>    # 記録から run を再開（続きを実行）
```

### バッチ要約

```bash
ancilla batch summarize
```

会話ログ（overflow + active）をブロック単位で要約し、JSONL と ChromaDB に保存。長期記憶の検索（`search_memory`）で参照されます。常駐時の Slow Heartbeat でも同処理が実行されます。

## サブコマンド一覧

| コマンド          | 説明                                                                      |
| ----------------- | ------------------------------------------------------------------------- |
| （なし）          | REPL のみ（単発）                                                         |
| `run`             | 常駐（REPL + HTTP API + WebSocket + Heartbeat）。`--no-repl` で REPL なし |
| `client`          | API に接続する REPL クライアント                                          |
| `discord`         | Discord Bot                                                               |
| `slack`           | Slack Bot（Socket Mode）                                                  |
| `runs`            | agent_runs の一覧表示                                                     |
| `trace`           | agent_run のステップ表示                                                  |
| `resume`          | agent_run の再開                                                          |
| `batch summarize` | 会話の要約バッチ                                                          |

共通オプション: `-v` / `--verbose`（DEBUG ログ）、`-r` / `--show-reasoning`（思考・ツール表示）、`--log-file PATH`。

### プラグイン（`ANCILLA_PLUGINS` で有効化）

- research: `search_arxiv` … arXiv 論文検索
- learning: `add_learning_item` / `review_due` / `record_review` … 学習項目の登録・復習
- meeting: `start_meeting` / `end_meeting` / `search_meetings` … ミーティング記録

## 永続化・データ

| 保存先                                         | 内容                                                                                            |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `data/conversation/ancilla.db`（SQLite）       | user_tasks, agent_tasks, reminders, finances, interests, audit_log, agent_runs, agent_run_steps |
| `data/conversation/active_history.jsonl`       | 現行の短期会話履歴                                                                              |
| `data/conversation/overflow.jsonl`             | 履歴から溢れた古いメッセージ                                                                    |
| `data/conversation/summaries/YYYY-MM-DD.jsonl` | 会話ブロックの要約（長期記憶）                                                                  |
| `data/vector_store/`（ChromaDB）               | 要約の埋め込みベクトル（RAG 有効時）                                                            |
| `data/personal_model.yaml`                     | 構造化ユーザーモデル（会話から自動更新）                                                        |
| `data/proactive_rules.yaml`                    | プロアクティブ介入ルール                                                                        |
| `data/notifications/pending.jsonl`             | 能動通知キュー（Discord / Slack がポーリング送信）                                              |
| `data/traces/events.jsonl`                     | agent run のイベントトレース                                                                    |
| `workspace/`                                   | AGENT.md / AGENT.native.md / USER.md / NOTE.md 等。エージェントの作業領域                       |

## コンテナ運用（任意）

```bash
docker compose up -d --build
```

`ancilla run --no-repl` で起動し、`data/` と `workspace/` を volume マウントします。既定の構成では Ollama を `host.docker.internal` 経由で参照します。

## ドキュメント

- `docs/ws_client_api.md` … WebSocket プロトコル仕様（Uplink/Downlink、エッジセッション、音声/画像フロー）
- `docs/notes/` … 設計メモ・ロードマップ・フロントエンド統合計画など
