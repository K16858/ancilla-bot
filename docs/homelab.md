# HomeLab 運用ガイド

Ancilla で自宅サーバー群（HomeLab）の状態を把握し、障害を検知・通知・診断し、許可したサービスだけを再起動する機能の運用手順。
Client API の仕様は [`client_api.md`](client_api.md)。

## 概要とアーキテクチャ

```
 各ホスト                              Core（常駐）
┌──────────────┐  wss/ws (8768)   ┌──────────────────────────────────┐
│ ancilla node │ ───────────────► │ Node 用 WS ─► 観測 (DB)          │
│ (telemetry,  │ ◄─── 命令 ────── │ ヘルスチェック(health_url)       │
│  Node-A 実行)│                  │   └► 状態判定 ─► Event ─► Incident │
└──────────────┘                  │        ├► 通知 (Discord / Slack)   │
                                  │        ├► 診断 (LLM、別 Task)      │
                                  │        └► 自動再起動 (任意)        │
 ブラウザ(WebUI) / Companion ───► │ /api/v1 (HTTP + SSE), /ui         │
                                  └──────────────────────────────────┘
```

- 宣言（`homelab.yaml`）: Host / Service / 依存関係 / 許可する操作。
- 観測: Node が報告間隔ごとに CPU・メモリ・ディスク・サービス状態を送り、Core が `health_url` を直接叩く。
- 判定: 観測から `healthy / degraded / unhealthy / unknown` を決め、2 回続いた変化だけを Event にする（一瞬の揺らぎは無視）。
- Incident: Event を集約する。Host 停止時はサービスごとの Incident を作らず Host の 1 件にまとめ、依存先の障害は依存先の Incident に寄せる。作成・深刻度上昇・診断・解決のときだけ通知する。
- 診断: Incident 作成時に LLM が読み取り専用で調べ、結果を Incident に残す。LLM が使えなくても Incident と通知は出る（診断は「未実施」）。
- 操作: `logs` と `restart` だけ。`homelab.yaml` に書いた操作を、承認（または Self-Healing の `auto`）のうえ Node が実行する。

## セットアップ

### 1. Core

```bash
ancilla install core && ancilla setup && ancilla start
cp homelab.yaml.example data/homelab.yaml   # 自分の環境に書き換える
ancilla homelab check                       # 検証のみ。壊れていても Core は起動する
```

`ancilla homelab hosts / services / inspect <id>` で宣言内容と影響範囲を確認できる。`data/homelab.yaml` は更新すると自動で読み直される。パスは `ANCILLA_HOMELAB_PATH` で変更できる。

### 2. homelab.yaml

見本は [`homelab.yaml.example`](../homelab.yaml.example)。要点:

- ID は小文字 slug（`a-z 0-9 - _`）。YAML 1.1 の都合で `on / off / yes / no` は真偽値になるため、そうした ID は引用符で囲む（`id: "off"`）。
- Host: `node: true` の Host だけ Node を入れられる。HAOS など専用 OS は `node: false`。
- Service: `kind` は `systemd / docker / windows_service / http / other`。`unit` は systemd unit 名・コンテナ名・Windows サービス名。`health_url` があれば Core が直接ヘルスチェックする。`depends_on` で依存を宣言する。
- 操作の許可（`actions`）。書いていない操作は拒否される。

```yaml
services:
  - id: prometheus
    name: Prometheus
    host: core
    kind: docker
    unit: prometheus
    health_url: http://core.home.arpa:9090/-/healthy
    actions:
      logs: auto            # 承認なしで読み取り（approval | auto）
      restart: approval     # approval | auto | auto_dry_run
```

| 値 | 意味 |
| --- | --- |
| `restart: approval` | 承認後に再起動する |
| `restart: auto_dry_run` | 自動再起動の条件を満たしたとき「再起動するはずだった」と通知するだけ（実行しない） |
| `restart: auto` | 条件を満たせば承認なしで再起動する（下記 Self-Healing） |
| `logs: auto` / `approval` | 直近 N 行（既定 100、最大 500）の取得。`auto` は承認なし |

`restart` / `logs` の対象になるのは `kind` が `systemd` か `docker` のサービスで、Host が `node: true` のものだけ。

### 3. Node のインストール

Core 側で Host ごとにトークンを発行する（1 回だけ表示。再発行すると古いものは失効）。

```bash
ancilla homelab node-token node-1
```

**Linux（systemd 常駐）**: Node を入れるホストで実行する。

```bash
ancilla install node --core wss://core.home.arpa:8768 --host-id node-1 --token <token> \
  --allow-restart wazuh-manager,prometheus --allow-logs wazuh-manager,prometheus
```

- `.env` に `ANCILLA_NODE_*` を書き、`ancilla-node.service`（非 root、`NoNewPrivileges`、`ProtectSystem=strict`）を登録して起動する。要 sudo。
- `--allow-restart` / `--allow-logs` は Node のローカル許可リスト。ここに無い unit は、Core が乗っ取られても実行しない（実行のたびに上書きされる。空にして再実行すると全拒否に戻る）。
- `--allow-restart` の systemd unit には polkit ルール（`/etc/polkit-1/rules.d/50-ancilla-node.rules`）が作られ、Node ユーザーはその unit の `restart` だけを非 root で実行できる。docker コンテナの再起動は Node ユーザーが `docker` グループに入っている必要がある。
- `--allow-logs` で systemd unit のログを読むには、Node ユーザーが `systemd-journal` グループに必要。自動では変更されないので表示されるコマンドを実行する（`sudo usermod -aG systemd-journal <user>`、反映にはサービス再起動）。

**Windows**: タスクスケジューラのタスク `AncillaNode`（ログオン時に起動、管理者権限なし）を登録する。

```powershell
ancilla install node --core wss://core.home.arpa:8768 --host-id workstation --token <token>
```

- 状態の観測（CPU・メモリ・ディスク・`windows_service` の running/stopped）はできる。`restart` / `logs` は未対応（systemd / docker のみ）。
- ログオンしないと Node は起動しない（サービスではない）。

**手動実行**: 上記 `ANCILLA_NODE_CORE_URL / ANCILLA_NODE_HOST_ID / ANCILLA_NODE_TOKEN` を環境変数または `.env` に置いて `ancilla node`。

確認: `ancilla homelab nodes`（`connected` になる）。切れても Node は指数バックオフ（最大 60 秒）で自動再接続する。

### 4. Node 通信路の保護

Node の WS は既定で `127.0.0.1:8768`。別ホストから接続させるには次のどちらかが必要:

- **TLS**（推奨）: Core に `ANCILLA_NODE_HOST=0.0.0.0`、`ANCILLA_NODE_TLS_CERT` / `ANCILLA_NODE_TLS_KEY` を設定すると `wss://` になる。自己署名なら Node 側に `ANCILLA_NODE_CA_FILE` を置く。
- **経路が暗号化済み（Tailscale / WireGuard など）**: 平文 `ws://` のまま `ANCILLA_NODE_HOST` を 0.0.0.0 や VPN の IP にし、`ANCILLA_INSECURE_BIND=1` を設定する（起動時に警告ログが出る）。

トークンは Node 接続の唯一の認証。漏れたら `ancilla homelab node-revoke <host>`（接続中の Node は 10 秒以内に切断される）。

## 日常運用

### CLI

| コマンド | 内容 |
| --- | --- |
| `ancilla homelab status [id]` | Host / Service の状態。観測時刻と鮮度つき |
| `ancilla homelab events [--subject id]` | 確定した状態変化 |
| `ancilla homelab incidents [--all]` | Incident 一覧（既定は未解決） |
| `ancilla homelab incident INC-000001` | 詳細（Event・影響・診断・操作履歴） |
| `ancilla homelab ack INC-000001` | 確認済みにする |
| `ancilla homelab resolve INC-000001` | 手動で解決する（回復すれば自動で解決する） |
| `ancilla homelab diagnose INC-000001` | 再診断（同期実行） |
| `ancilla homelab nodes` | Node の接続状態 |

状態の見方: Node だけが落ちた Host は `unhealthy` ではなく `degraded` + `node_lost`（そのホストのサービスに `health_url` が生きていれば）か `unknown` になる。観測が古い（報告間隔の 3 倍超）値は `stale` として扱われる。

### WebUI

```bash
cd webui && npm ci && npm run build        # webui/dist に出力
ancilla api token create webui --role read # 1 回だけ表示
```

ブラウザで `http://<core>:8765/ui/` を開き、トークンを貼る。概要・Host・Service・Incident・Node が見られ、Incident の作成・解決は再読み込みなしで反映される。`operate` トークン（`ancilla api token create <name> --role operate`）なら承認待ちの承認・却下もできる。トークンは `ancilla api token list / revoke <name>` で管理する。トークンが無い、失効している、`read` で操作系を呼ぶ、はそれぞれ 401 / 401 / 403。

ループバック外へ API を公開する場合は `ANCILLA_API_BIND_HOST=0.0.0.0`（トークンがあるので `ANCILLA_INSECURE_BIND` は不要）。ただし平文 HTTP なので、通信路は Tailscale 等で守る。

### 承認

`restart: approval` のサービスを、会話で「Prometheus を再起動して」と頼むと承認待ちになる（操作・対象・引数・期限が表示される。期限は `ANCILLA_APPROVAL_TTL_HOURS`、既定 24）。承認は次のどれからでも同じ検査（Policy の再判定、期限、Node の許可リスト）を通る。

- WebUI: `operate` トークンで承認・却下ボタン
- CLI: `ancilla approve <run_id>` / `ancilla reject <run_id>`
- Discord / Slack: オーナーが `approve <run_id>` / `reject <run_id>` と送る（オーナー以外は不可）

承認後、Node が再起動し、数回の報告間隔のあいだ `healthy` に戻るか確かめる。戻らなければ失敗として Incident に記録し通知する。

## Self-Healing の導入手順

人が事前に許可したサービスだけ、承認なしで再起動する。判断は通常のコードで、LLM は可否を決めない。

1. まず `actions: {restart: auto_dry_run}` にする。条件を満たす障害が起きたとき「再起動するはずだった」通知だけが出る。
2. 数日〜数週間見て、通知の内容が妥当なら `auto` に変える。
3. いつでも `ancilla homelab autoheal off` で、`auto` / `auto_dry_run` を含むすべての自動再起動を止められる（`on` で戻す、`status` で確認。再起動不要で即時）。

自動で再起動する条件（すべて満たすとき）:

- Incident が `service_down` で、対象がそのサービス自身
- Host が生きていて、Node が接続中かつ報告が新しい
- 依存先（推移的）とその Host に未解決 Incident がない（下流の症状ではない）
- 回数制限内: Incident ごとに 1 回、サービスごとに 24 時間で 3 回

満たさなければ自動再起動せず、理由つきで人に通知する（Incident ごとに 1 回）。再起動後に回復しなければ自動処理を止めて通知し、承認待ちに戻す。

## 環境変数

`.env.example` にも載っている。Core / Node のどちらで効くかを併記する。

| 変数 | 既定 | 内容 |
| --- | --- | --- |
| `ANCILLA_HOMELAB_PATH` | `<ANCILLA_ROOT>/data/homelab.yaml` | Inventory のパス（Core） |
| `ANCILLA_HOMELAB_INTERVAL` | `30` | 報告・ヘルスチェック・判定・鮮度・再起動後検証の間隔（秒）。Core に設定すれば Node へ配られる。起動直後の猶予は `max(90 秒, 3 間隔)`。動作確認以外は変えない |
| `ANCILLA_NODE_HOST` / `ANCILLA_NODE_PORT` | `127.0.0.1` / `8768` | Node 用 WS の待ち受け（Core） |
| `ANCILLA_NODE_TLS_CERT` / `ANCILLA_NODE_TLS_KEY` | 空 | 両方設定すると `wss://`（Core）。片方だけは起動エラー |
| `ANCILLA_INSECURE_BIND` | 空 | `1` で平文 ws / MCP HTTP / WS を非ループバックに出すことを許す（Core） |
| `ANCILLA_API_BIND_HOST` / `ANCILLA_API_PORT` | `127.0.0.1` / `8765` | API・WebUI の待ち受け（Core） |
| `ANCILLA_WEBUI_DIR` | `<ANCILLA_ROOT>/webui/dist` | WebUI のビルド成果物（Core） |
| `ANCILLA_APPROVAL_TTL_HOURS` | `24` | 承認待ちの有効期限（Core） |
| `ANCILLA_NODE_CORE_URL` | 空 | Core の Node 用 URL（例 `wss://core.home.arpa:8768`）（Node） |
| `ANCILLA_NODE_HOST_ID` | 空 | この Node の Host ID（Node） |
| `ANCILLA_NODE_TOKEN` | 空 | `node-token` で発行したトークン。秘密（Node） |
| `ANCILLA_NODE_CA_FILE` | 空 | 自己署名 Core の CA 証明書（Node） |
| `ANCILLA_NODE_ALLOW_RESTART` / `ANCILLA_NODE_ALLOW_LOGS` | 空 | Node のローカル許可リスト（カンマ区切り unit）。空は全拒否。通常は `install node` が書く（Node） |

## トラブルシューティング

| 症状 | 確認 |
| --- | --- |
| `homelab nodes` が `disconnected` / `revoked` | Node のログ（`journalctl -u ancilla-node` / `schtasks /Query /TN AncillaNode`）。`HTTP 401` はトークン不一致か失効 → `node-token` で再発行して `.env` を更新。`ConnectionRefused` は Core の `ANCILLA_NODE_HOST/PORT`・FW・TLS 設定 |
| `wss://` で接続できない | 自己署名なら `ANCILLA_NODE_CA_FILE`。証明書の SAN と接続先ホスト名を合わせる |
| Core が起動時に bind で止まる | 平文のまま非ループバックに出している。TLS にするか `ANCILLA_INSECURE_BIND=1` |
| 状態が `unknown` のまま | Node が未接続か、`health_url` の無いサービス。`homelab status <id>` の evidence で観測時刻を見る |
| `homelab check` がエラー | メッセージの行を直す。`on/off/yes/no` の ID は引用符、未知の参照・重複 ID・範囲外の値が主な原因 |
| 再起動が拒否される | (1) `actions` に宣言があるか (2) Host が `node: true` か (3) Node の許可リストに unit があるか（`.env` の `ANCILLA_NODE_ALLOW_RESTART`）(4) polkit ルールがあるか (5) 命令の期限（120 秒）切れ＝Core と Node の時計ずれ |
| 診断が「未実施」 | LLM に接続できない。`ancilla doctor` で確認し、復旧後に `homelab diagnose <id>` |
| 通知が来ない | Discord / Slack Bot が起動しているか、通知先の設定（`.env.example` の `DISCORD_*` / `SLACK_*`）。通知は `data/notifications/` に必ず追記される |
| WebUI が 404 | `webui/dist` が無い。`npm run build` |

## 既知の制限

- 診断の待ち行列はメモリのみ。Core を再起動すると未処理の診断は消える（`homelab diagnose` で再実行）。
- Node は処理済みの命令 ID をメモリにしか持たない。Node 再起動後の再送は重複排除されないが、命令の期限（120 秒）が二重実行の窓を縛る。
- 命令の期限は Core の時刻で付けて Node の時計で判定する。時計が 120 秒以上ずれると全命令が「期限切れ」になる。NTP を合わせること。
- Windows の Node はログオン時に起動する（サービスではない）。ログオフ中は `node_lost`。
- Windows サービス（`windows_service`）は観測のみで、`restart` / `logs` は未対応。
- `restart` / `logs` は systemd と docker のみ。設定変更・マシン再起動・ネットワーク隔離は無い。
- ヘルスチェックは逐次実行。サービスが数十を超えて 1 周が報告間隔を超えるなら、並列化が必要。
- Node の認証はトークンのみ（mTLS ではない）。通信路は TLS か VPN で守ること。
- 診断が失敗（スキップ）したときの追加通知は無い。Incident の `diagnosis_status` で確認する。
