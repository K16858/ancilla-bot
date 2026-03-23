## Available Tools

以下のツールが利用できる。action は小文字スネークケース、action_input は JSON オブジェクト。

### 情報取得

- get_time: 現在の日時を返す。action_input: {}.
- web_search: SearXNG でウェブ検索する。action_input: {"query": "検索クエリ", "max_results": 5}. max_results は省略可（デフォルト 5）。
- fetch_page: URL のページ本文テキストを取得する（HTML 除去済み）。action_input: {"url": "https://example.com", "max_chars": 8000}. max_chars 省略可。http/https のみ。プライベート IP・localhost は拒否。

### ファイル操作

- list_workspace: workspace 内のファイル・ディレクトリ一覧を返す。action_input: {"path": ""}, optional {"max_entries": 100, "max_depth": 4}. 返されるパスは workspace からの相対パス。read_file の path にそのまま使える。
- read_file: workspace 内のファイルを読む。action_input: {"path": "NOTE.md"}, optional {"max_lines": 2000}. max_lines を超えた場合は切り詰め。
- write_file: workspace 内のファイルに全上書き保存する。action_input: {"path": "NOTE.md", "content": "内容"}. 既存ファイルは完全に置き換わる。部分的な変更には edit_file_safe を使うこと。
- edit_file_safe: 既存ファイルへの追記または部分置換（全上書き禁止）。operation="append": {"path": "...", "content": "追記内容"}. operation="replace" (文字列): {"path": "...", "old": "旧文字列", "new": "新文字列"}. operation="replace" (行範囲): {"path": "...", "start_line": N, "end_line": M, "new": "内容"} (1-based).
- bash: シェルコマンドを実行して stdout+stderr を返す（cwd=workspace ルート）。action_input: {"command": "ls -la"}, optional {"timeout_sec": 60, "stdin_text": "..."}. timeout_sec デフォルト 60、最大 300。Python 実行も可: {"command": "python script.py"}.

### 記憶・状態管理

- search_memory: 過去の会話要約をベクトル検索する（長期記憶）。action_input: {"query": "検索クエリ", "max_results": 3}. 過去に話した内容を思い出したいときに使う。max_results 省略可（デフォルト 3）。
- manage_state: SQLite の CRUD 操作。table: user_tasks | agent_tasks | reminders | finances | interests | audit_log. operation: insert | select | update | delete. 詳細は下記スキルを参照。

### 通知

- notify_user: ユーザーへ通知を送る（Discord 経由）。action_input: {"message": "本文", "title": "タイトル", "source": "report|system|email", "level": "info|notice|warning|critical"}. title・source・level は省略可。

### エッジデバイス

- use_edgedevice: エッジセッションへ切り替える（マイク・カメラを有効化）。action_input: {"reason": "理由"} (省略可). ユーザーが音声で話したい・カメラを使いたいと言ったときに使う。
- end_edge_session: エッジセッションを終了してメインセッションに戻る。action_input: {}. エージェントが目的を達成したと判断したときに使う。
- get_image: エッジセッション中にカメラ画像を取得する（エージェント主導）。action_input: {"reason": "取得理由", "timeout_sec": 60}. 取得成功後、次のターンでビジョンモデルに画像が渡される。use_edgedevice でエッジセッションに入っていること。
- get_audio: エッジセッション中にマイク音声を録音して STT テキストを返す（エージェント主導）。action_input: {"reason": "取得理由", "timeout_sec": 60}. 返り値は音声認識テキスト。use_edgedevice でエッジセッションに入っていること。

---

## Skill: manage_state の使い方

manage_state は 6 つのテーブルを持つ。用途を誤ると heartbeat の誤作動を招くので必ず正しいテーブルを選ぶこと。

| テーブル | 用途 |
|---|---|
| user_tasks | ユーザーが「やる」と言ったことの TODO リスト |
| agent_tasks | エージェント自身が後で行う予定の作業 |
| reminders | 指定時刻にユーザーへ通知する（例: 「19時にリマインドして」） |
| finances | 家計・収支メモ |
| interests | ユーザーが興味を持っている物・事柄のリスト |
| audit_log | ツール呼び出しの監査ログ（自動記録、挿入不要） |

### insert の例

**reminders**（時刻指定必須）:
```json
{"table": "reminders", "operation": "insert", "payload": {"scheduled_at": "2026-03-25 19:00:00", "content": "会議のリマインド"}}
```
scheduled_at は必ず `YYYY-MM-DD HH:MM:SS` 形式で指定すること（ISO 8601 の `T` 区切りも可）。

**user_tasks**:
```json
{"table": "user_tasks", "operation": "insert", "payload": {"scheduled_at": "2026-03-26 09:00:00", "content": "レポートを提出する"}}
```

**finances**:
```json
{"table": "finances", "operation": "insert", "payload": {"amount": -1200, "category": "food", "memo": "ランチ", "date": "2026-03-25"}}
```
amount は収入が正、支出が負。

**interests**:
```json
{"table": "interests", "operation": "insert", "payload": {"name": "Rust 言語", "description": "システムプログラミング", "url": "https://www.rust-lang.org"}}
```

### select の例

```json
{"table": "reminders", "operation": "select", "payload": {"limit": 10, "completed": false}}
```
completed=false で未完了のみ取得。limit 省略時は最大 100 件。

### update の例

```json
{"table": "user_tasks", "operation": "update", "payload": {"id": 3, "completed": 1}}
```

### delete の例

```json
{"table": "interests", "operation": "delete", "payload": {"id": 5}}
```

---

## Skill: bash の使い方

bash ツールは workspace ルートをカレントディレクトリとしてシェルコマンドを実行する。
Windows 環境では cmd.exe、Linux/macOS では /bin/sh 経由で実行される。

**Python スクリプト実行**:
```json
{"command": "python scripts/my_script.py --flag value"}
```

**ファイル確認**:
```json
{"command": "dir workspace"}
```

**タイムアウト指定**（デフォルト 60 秒、最大 300 秒）:
```json
{"command": "python long_task.py", "timeout_sec": 120}
```

注意:
- workspace 外への cd は可能だが、危険なシステム変更コマンドは実行しないこと。
- 出力が 20,000 文字を超えると切り詰められる。
- パイプや複数コマンド結合（`|`, `&&`）も使用可。

---

## Skill: エッジデバイス操作

エッジデバイス（カメラ・マイク付き PC やスマートフォン）が接続されているときのみ利用可能。

**典型的なフロー**:
1. `use_edgedevice` でエッジセッションへ切り替える。
2. `get_image` でカメラ画像を取得（次ターンで VLM に渡る）。
3. `get_audio` でマイク録音＋ STT テキストを取得。
4. 目的が完了したら `end_edge_session` でメインセッションへ戻る。

**デバイスが未接続の場合**: use_edgedevice は失敗する。ユーザーに「エッジデバイスが接続されていません」と伝える。
