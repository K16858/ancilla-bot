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
| `GET /api/v1/events?subject=&since=&limit=` | `since` は `24h` / `30m` / `7d` または ISO 時刻 |

エラーは `{"error": "..."}`（400 / 404 / 503=Inventory 不正）。

## 操作（role: operate）

`POST /api/v1/chat` — `{"message": "...", "images": [...]}` → `{"response": "..."}`（409: 会話中）。`/chat` と同じ処理。

## SSE: `GET /api/v1/stream`（role: read）

`fetch` のストリーミングで読む（`EventSource` は Authorization ヘッダーを付けられない）。

- `event: homelab_event` / `id: <events.id>` / `data: <Event JSON>`：新しい Event ごと。
- `event: incidents_changed` / `data: {}`（id なし）：Incident 表が変わった（作成・確認・解決・診断。CLI からの操作も検出）。受け取ったら `/incidents` を取り直す。
- `: heartbeat` コメントを約 15 秒ごと。
- 追い付き：`Last-Event-ID` ヘッダー（または `?after=<id>`）を付けて再接続すると、その id より後の Event を送る。無指定なら接続後の新規のみ。
- DB を約 2 秒ごとにポーリングする。接続ごとにスレッドを使うため他のリクエストは塞がれない。

`/ui` は WebUI（静的配信）用に予約。
