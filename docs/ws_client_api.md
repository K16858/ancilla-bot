# Ancilla WebSocket クライアント API リファレンス

接続先: `ws://<host>:<port>`（既定: `ws://127.0.0.1:8766`）

メッセージはすべて **JSON テキスト** フレームで送受信します。  
最大メッセージサイズは **16 MB**（base64 エンコード後）。

---

## 概要：セッションモード

サーバーは内部的に 2 つのモードを持ちます。

| モード | 説明 |
|--------|------|
| `main` | 通常待受状態。エージェントは主に heartbeat で動作。 |
| `edge` | エッジデバイス接続中。`audio_input` で ReAct が動く。 |

`status_update` や `audio_input` を受信すると `edge` モードに自動遷移します。  
`session_end` または `status_update(state=disconnected)` で `main` に戻ります。

---

## アップリンク（クライアント → サーバー）

### `status_update`

接続・切断の状態を通知します。接続時に最初に送ります。

```json
{ "event": "status_update", "state": "active" }
```

| フィールド | 型 | 説明 |
|---|---|---|
| `state` | `"active"` \| `"disconnected"` | `"active"` で `edge` モードに遷移。`"disconnected"` でセッション終了。 |

**サーバーの動作:**
- `"active"` → `ui_control(show_avatar)` をダウンリンク送信
- `"disconnected"` → エッジセッション終了、`ui_control(hide_avatar)` 送信

---

### `audio_input`

音声データ（WAV / base64）を送信します。2 つの用途があります。

#### ① 自発入力（VAD トリガー）

```json
{
  "event": "audio_input",
  "data": "<base64 エンコードされた WAV>"
}
```

**サーバーの動作:**
1. `edge` モードに遷移（まだなら）
2. STT で文字起こし
3. 最新の `vision_input` 画像があれば LLM コンテキストに自動添付
4. ReAct エージェント実行
5. TTS 合成 → `agent_response` をダウンリンク送信

#### ② `media_request` への応答

エージェントが `get_audio` ツールを呼んだ場合の応答です。

```json
{
  "event": "audio_input",
  "data": "<base64 エンコードされた WAV>",
  "request_id": "<サーバーから届いた request_id>"
}
```

**サーバーの動作:** STT → 認識テキストをエージェントの待機キューに渡す（ReAct は回さない）

**音声フォーマット:** WAV（`float32` または `PCM_16`）、推奨サンプルレート 16000 Hz

---

### `vision_input`

画像データ（JPEG / PNG の base64）を送信します。2 つの用途があります。

#### ① 自発入力（カメラストリーム）

```json
{
  "event": "vision_input",
  "data": "<base64 エンコードされた画像>"
}
```

**サーバーの動作:** 最新画像バッファ（`_latest_vision_image`）を更新するのみ。  
次の `audio_input` 処理時に自動添付されます。ReAct は即座には起動しません。

#### ② `media_request` への応答

エージェントが `get_image` ツールを呼んだ場合の応答です。

```json
{
  "event": "vision_input",
  "data": "<base64 エンコードされた画像>",
  "request_id": "<サーバーから届いた request_id>"
}
```

**サーバーの動作:** 画像をエージェントの待機キューに渡す（LLM への添付はエージェントが制御）

---

### `session_end`

接続を終了することをサーバーに通知します。

```json
{ "event": "session_end" }
```

**サーバーの動作:** エッジセッション終了、対話履歴を要約して記憶に保存、`hide_avatar` 送信

---

## ダウンリンク（サーバー → クライアント）

### `agent_response`

エージェントの応答です。`audio_input` 処理後に送信されます。

```json
{
  "event": "agent_response",
  "text": "はい、聞こえています！",
  "emotion": "Neutral",
  "audio_format": "wav",
  "audio_data": "<base64 エンコードされた WAV>"
}
```

| フィールド | 型 | 説明 |
|---|---|---|
| `text` | `string` | 応答テキスト |
| `emotion` | `string` \| `null` | 感情ラベル（`"Neutral"`, `"Happy"` 等）|
| `audio_format` | `"wav"` \| なし | TTS 音声がある場合のフォーマット |
| `audio_data` | `string` \| なし | TTS 音声（base64 WAV）。TTS 無効時は省略。 |

---

### `ui_control`

UI 状態を制御するコマンドです。

```json
{ "event": "ui_control", "command": "show_avatar" }
```

| `command` | タイミング |
|---|---|
| `"show_avatar"` | `edge` セッション開始時（接続確認・`audio_input` 受信時） |
| `"hide_avatar"` | `edge` セッション終了時 |

---

### `media_request`

エージェントがデバイスにカメラ撮影またはマイク録音を要求します。  
受信したら対応するアップリンク（`vision_input` / `audio_input`）を `request_id` 付きで返してください。

```json
{
  "event": "media_request",
  "kind": "camera",
  "request_id": "abc123",
  "reason": "現在の状況を確認したい"
}
```

| フィールド | 型 | 説明 |
|---|---|---|
| `kind` | `"camera"` \| `"microphone"` | 要求するメディアの種類 |
| `request_id` | `string` | 応答時に必ず同じ値を返す |
| `reason` | `string` | エージェントが要求した理由（表示用） |

**応答例（カメラ）:**
```json
{
  "event": "vision_input",
  "data": "<base64>",
  "request_id": "abc123"
}
```

**応答例（マイク）:**
```json
{
  "event": "audio_input",
  "data": "<base64 WAV>",
  "request_id": "abc123"
}
```

> **注意:** `request_id` がないと通常の自発入力として処理されます。

---

## 典型的なメッセージフロー

### 通常の音声会話

```
クライアント                        サーバー
    |                                  |
    |-- status_update(active) -------->|
    |<- ui_control(show_avatar) -------|
    |                                  |
    |-- vision_input(画像) ----------->|  ※ バッファ更新のみ
    |                                  |
    |-- audio_input(音声) ------------>|
    |                                  |  STT → 画像自動添付 → ReAct → TTS
    |<- ui_control(show_avatar) -------|
    |<- agent_response(text+audio) ----|
    |                                  |
    |-- session_end ------------------>|
    |<- ui_control(hide_avatar) -------|
```

### エージェント主導のカメラ取得

```
クライアント                        サーバー
    |                                  |
    |<- media_request(camera, id=X) ---|  エージェントが get_image を呼んだ
    |                                  |
    |  （撮影）                         |
    |-- vision_input(画像, id=X) ------>|  エージェントの待機キューに渡る
    |                                  |  エージェント処理続行 → agent_response
    |<- agent_response(text+audio) ----|
```

---

## エラー・制約

| 状況 | 挙動 |
|---|---|
| STT で空の認識結果 | `"音声を認識できませんでした。"` を返答 |
| 同時接続は 1 クライアントのみ | 新規接続時に旧接続を強制切断 |
| JSON 以外のメッセージ | サーバーログに記録、無視 |
| `request_id` 付き応答でウェイター不在 | 自発入力として扱う（`request_id` なし扱い） |
| `audio_input` で `_run_react_cb` 未登録 | STT テキストをそのまま `text` として `agent_response` 送信 |
