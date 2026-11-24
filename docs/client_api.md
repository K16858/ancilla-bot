# Ancilla クライアント API（/api/v1）

WebUI / Companion 向け。Core の HTTP API（既定 `http://127.0.0.1:8765`）に同居する。

## 認証

```
ancilla api token create webui --role read      # 1 回だけ表示。同名で再実行するとローテーション
ancilla api token revoke webui
ancilla api token list
```

- `/api/v1/...` は常に `Authorization: Bearer <token>` が必要（ループバックでも）。
- 401: 無し・不明・失効 / 403: role 不足。`operate` は `read` を含む。
- DB には SHA-256 hash のみ保存。
- 従来のエンドポイント（`/chat` `/cancel` `/health`）はループバックからは認証なし。
  ループバック外からは `operate` トークンが必要（無ければ 403）。
  そのため API を `ANCILLA_API_BIND_HOST=0.0.0.0` 等で公開しても `ANCILLA_INSECURE_BIND` は不要（MCP HTTP / WS / Node の平文 ws は従来どおり必要）。

## 参照（role: read、JSON）

| Endpoint | 内容 |
| --- | --- |
| `GET /api/v1/summary` | `hosts` / `services` の状態別件数、`open_incidents` の深刻度別件数、`evaluated_at` |
| `GET /api/v1/hosts`, `/hosts/{id}` | 宣言 + `status`（state / flags / evidence[].observed_at）+ `evaluated_at`。詳細は `services` |
| `GET /api/v1/services`, `/services/{id}` | 同上。詳細は `impact: {dependencies, dependents}` |
| `GET /api/v1/nodes` | `host_id` `connected` `last_seen` `os` `version` `hostname`（トークン hash は返さない） |
| `GET /api/v1/incidents?all=1` | 既定は未解決のみ |
| `GET /api/v1/incidents/{INC-000001}` | 詳細（Event・影響・診断） |
| `GET /api/v1/me` | トークン名と role（`{name, role}`）。UI が操作ボタンの出し分けに使う |
| `GET /api/v1/approvals` | 承認待ち。`run_id` `tool` `args` `description`（操作・対象・引数・期限）`created_at` `expires_at`（TTL=`ANCILLA_APPROVAL_TTL_HOURS`）`source`（依頼元） |
| `GET /api/v1/events?subject=&since=&limit=` | `since` は `24h` / `30m` / `7d` または ISO 時刻 |
| `GET /api/v1/timers`, `/timers/{id}` | 秒精度タイマー一覧（`?all=1` で終了済み含む）と `server_now` |
| `GET /api/v1/notifications?since_id=&limit=` | 通知イベント履歴（`since_id` 指定でそれ以降を昇順取得） |

エラーは `{"error": "..."}`（400 / 404 / 503=Inventory 不正）。

## 操作（role: operate）

`POST /api/v1/chat` — `{"message": "...", "images": [...]}` → `{"response": "..."}`（409: 会話中）。`/chat` と同じ処理。

`POST /api/v1/chat/cancel` — `{"ok": true}`。実行中の会話・思考を中断する。

`POST /api/v1/companion/chat` — `{"message": "...", "session_id": "default", "reset_pending": false}` → `{"reply": "...", "emotion": ..., "end_conversation": false, "session_id": "..."}`（409: 会話中）。CLI / Discord の通常履歴と分離した短期履歴（直近 6 往復・30 分 TTL）を使い、長期記憶とツールは共有する。音声経由の `approve` 承認コマンドは無効。

`POST /api/v1/companion/session/end` — `{"session_id": "default"}` → `{"ok": true, "ended": ..., "session_id": "..."}`。待機復帰や約 10 秒無言タイムアウト時に未完了の聞き返し状態を打ち切る（完了済みの直近文脈は保持）。

`POST /api/v1/timers` — `{"duration_sec": 180, "label": ""}` → `201` 作成したタイマー JSON。

`PATCH /api/v1/timers/{id}` — `{"action": "stop"}`（鳴動停止）または `{"duration_sec": ..., "add_sec": ..., "label": ...}`。

`DELETE /api/v1/timers/{id}` — タイマー取消。

`POST /api/v1/voice/stt?prompt=...` — 音声バイナリ（`Content-Type: audio/webm` / `audio/mp4` / `audio/wav` 等）→ `{"text": "..."}`（`STT_BASE_URL` 未設定時は 503）。

`POST /api/v1/voice/tts` — `{"text": "..."}` → `audio/wav` バイナリ（`TTS_BASE_URL` 未設定時は 503、上流エラー時 502）。

`POST /api/v1/approvals/{run_id}/approve` / `/reject` — `{"message": "..."}`。CLI（`ancilla approve`）・Discord・Slack と同じ `approve_run` / `reject_run` を呼ぶので、期限（TTL）と Policy の再検査も同一。承認は同期実行で、homelab の再起動は Node の応答待ち（最大 約 60 秒）でブロックする（接続ごとのスレッドなので他は塞がれない）。拒否・期限切れ・Policy DENY も 200 でメッセージに入る。承認待ちの確保は DB の `UPDATE ... WHERE status='pending'` で原子的に行うため、同時に承認しても実行は 1 回。承認者は `pending_approvals.resolved_by` と `action_log.approved_by` に `webui:<token名>` / `cli` / `discord` / `slack` で残る。

## SSE: `GET /api/v1/stream`（role: read）

`fetch` のストリーミングで読む（`EventSource` は Authorization ヘッダーを付けられない）。

- `event: homelab_event` / `id: <events.id>` / `data: <Event JSON>`：新しい Event ごと。
- `event: incidents_changed` / `data: {}`（id なし）：Incident 表が変わった（作成・確認・解決・診断。CLI からの操作も検出）。受け取ったら `/incidents` を取り直す。
- `event: approvals_changed` / `data: {}`（id なし）：承認待ちの増減・状態変化。`/approvals` を取り直す。
- `event: timers_changed` / `data: <TimersPayload>`：タイマーの作成・更新・満了・停止・取消。
- `event: timer_fired` / `data: <TimerItem>`：タイマーが満了して `firing` になった瞬間。
- `event: notification` / `id: <notification_events.id>` / `data: <Notification JSON>`：`append_notification` で記録された通知（Discord / Slack の配送キューには干渉しない）。
- `: heartbeat` コメントを約 15 秒ごと。
- 追い付き：`Last-Event-ID` ヘッダー（または `?after=<id>`）で `homelab_event`、`?after_notification=<id>` で `notification` の再接続後追い付きができる。無指定なら接続後の新規のみ。
- タイマー・通知変更時は `threading.Condition` で即時 wakeup しつつ、DB の変更は約 2 秒ごとにポーリングする。接続ごとにスレッドを使うため他のリクエストは塞がれない。

## WebUI（`/ui`）

WebUI（React + Vite、`webui/`）を Core が `/ui/` で静的配信する（`/` は `/ui/` へ 302）。静的ファイルはトークン不要で、データは `/api/v1` がトークンで守る。

```
cd webui && npm ci && npm run build        # webui/dist に出力
ancilla api token create webui --role read # ブラウザのログイン画面に貼る
```

- 配信元は `ANCILLA_WEBUI_DIR`（既定 `<ANCILLA_ROOT>/webui/dist`）。未ビルドなら `/ui/` は 404 でビルド手順を返す。
- トークンは localStorage に保存。「ログアウト」で消える。401 でもログイン画面に戻る。
- 開発: `cd webui && npm run dev`（Vite、`/api` は `http://127.0.0.1:8765` へプロキシ）。
- 画面: 概要 / Host / Service / Incident / Node / 承認。

## Companion（`/companion`）

Companion（React + Vite + PWA、`companion/`）を Core が `/companion/` で静的配信する（`/companion` は `/companion/` へ 302）。静的ファイルはトークン不要で、API 通信は Bearer トークンで保護される。

```
cd companion && npm ci && npm run build          # companion/dist に出力
ancilla api token create companion --role operate # 音声会話・タイマー停止用に operate を発行
```

- 配信元は `ANCILLA_COMPANION_DIR`（既定 `<ANCILLA_ROOT>/companion/dist`）。未ビルドなら `/companion/` は 404 でビルド手順を返す。
- 開発: `cd companion && npm run dev`（Vite、`/api` は `http://127.0.0.1:8765` へプロキシ）。
- 主な画面・機能: 起動時ワンタップ音声アンロック、待機時計画面、タップ起動の連続音声対話（両字幕・無言約 10 秒自動復帰・無音時はテキスト入力フォールバック）、秒精度タイマー（クライアント時刻ズレ補正・満了アラーム・停止同期）、おやすみモード／夜間スケジュール抑制（タイマー以外はサイレント蓄積）。
- タブレット実機（iPad / Android）でマイク入力（`getUserMedia`）を使うには `https://`（リバースプロキシや Tailscale Serve 等での HTTPS 終端）または `localhost` 接続が必要。PWA（ホーム画面へ追加）での全画面表示に対応している。
