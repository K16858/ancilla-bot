# Ancilla

常駐型 LLM アシスタント。

## 要件

- Python 3.11+
- git
- LLM（[Ollama](https://ollama.com/) または OpenAI 互換 API）

## インストール

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/K16858/ancilla-bot/main/scripts/install.sh | bash

# Windows (PowerShell)
irm https://raw.githubusercontent.com/K16858/ancilla-bot/main/scripts/install.ps1 | iex
```

```bash
ancilla install core
ancilla setup
ancilla start
ancilla
```

開発時はリポジトリで `pip install -e .` のあと、同じ手順でよい。

## 使い方

```bash
ancilla start                 # Core をバックグラウンド起動
ancilla                       # 会話（exit / quit / :q で終了）
ancilla start --cli           # Core 確保 + CLI（CLI 終了後も Core は残る）
ancilla start all             # Core + 設定済み Adapter
ancilla status
ancilla logs core --follow
ancilla stop
ancilla setup                 # 設定変更
ancilla doctor
ancilla update                # 更新前に stop が必要
```

設定の詳細は `.env.example`、WebSocket 仕様は `docs/ws_client_api.md` を参照。
