"""Core 側の Node 用 WebSocket エンドポイント（認証・hello/config・telemetry 受信）。

メッセージ: hello (Node→Core), config (Core→Node), telemetry (Node→Core, ack なし)。
PR 08 は set_telemetry_handler() で telemetry の処理を差し込む。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import json
import os
import ssl
from collections.abc import Callable
from http import HTTPStatus

from loguru import logger
from websockets.asyncio.server import ServerConnection, serve

from ancilla_bot.homelab import inventory as inv
from ancilla_bot.homelab import store

REPORT_INTERVAL_SEC = 30
HELLO_TIMEOUT_SEC = 10.0
# 失効の検知方法: CLI は別プロセスなので接続を直接切れない。
# 接続ごとに RECHECK_SEC 間隔で nodes 表を見直し、失効・再発行されていたら切断する。
# あわせて last_seen も更新する（CLI の接続状態表示の根拠）。
RECHECK_SEC = 10.0

_connections: dict[str, ServerConnection] = {}
# host_id -> 最新の telemetry（メモリのみ。永続化は PR 08）
latest_telemetry: dict[str, dict] = {}
_loop: asyncio.AbstractEventLoop | None = None  # 接続を扱っているイベントループ（send_command が別スレッドから使う）
_pending: dict[str, tuple[str, concurrent.futures.Future]] = {}  # command id -> (host_id, 結果の Future)
_telemetry_handler: Callable[[str, dict], None] | None = None


def set_telemetry_handler(fn: Callable[[str, dict], None] | None) -> None:
    """telemetry 受信時に (host_id, message) で呼ばれる。"""
    global _telemetry_handler
    _telemetry_handler = fn


def is_connected(host_id: str) -> bool:
    return host_id in _connections


def send_command(host_id: str, cmd: dict, timeout: float = 60) -> dict:
    """別スレッドから呼ぶ。Node に命令を送り command_result を待つ。失敗は ok=False の結果で返す（例外にしない）。"""
    cid = str(cmd.get("id", ""))

    def fail(msg: str) -> dict:
        return {"type": "command_result", "id": cid, "ok": False, "output": "", "error": msg,
                "started_at": "", "finished_at": ""}

    ws, loop = _connections.get(host_id), _loop
    if ws is None or loop is None:
        return fail(f"node '{host_id}' は接続されていません")
    fut: concurrent.futures.Future = concurrent.futures.Future()
    _pending[cid] = (host_id, fut)
    try:
        asyncio.run_coroutine_threadsafe(ws.send(json.dumps(cmd)), loop).result(timeout=10)
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        return fail("node からの応答がタイムアウトしました")
    except Exception as e:
        return fail(f"送信に失敗しました: {type(e).__name__}: {e}")
    finally:
        _pending.pop(cid, None)


def _authenticate(connection: ServerConnection, request):
    auth = request.headers.get("Authorization", "")
    scheme, _, token = auth.partition(" ")
    host_id = store.verify_token(token.strip()) if scheme.lower() == "bearer" and token else None
    if host_id is None:
        logger.warning("node: 認証失敗 peer={}", connection.remote_address)
        return connection.respond(HTTPStatus.UNAUTHORIZED, "unauthorized\n")
    connection.node_host_id = host_id
    return None


def _config_message(host_id: str) -> dict:
    i = inv.load_inventory()
    host = i.host(host_id)
    if host is None or not host.node:
        raise inv.InventoryError(f"host '{host_id}' は homelab.yaml で node: true になっていません")
    services = [
        {"id": s.id, "kind": s.kind, "unit": s.unit} for s in i.services
        if s.host == host_id and s.kind in ("systemd", "docker", "windows_service")
    ]
    return {"type": "config", "interval": REPORT_INTERVAL_SEC, "services": services}


async def _watch(ws: ServerConnection, host_id: str) -> None:
    while True:
        await asyncio.sleep(RECHECK_SEC)
        if not store.is_active(host_id):
            logger.warning("node: トークン失効のため切断 host={}", host_id)
            await ws.close(1008, "token revoked")
            return
        store.touch(host_id)


async def _handle(ws: ServerConnection) -> None:
    global _loop
    _loop = asyncio.get_running_loop()
    host_id: str = ws.node_host_id
    try:
        hello = json.loads(await asyncio.wait_for(ws.recv(), HELLO_TIMEOUT_SEC))
        if hello.get("type") != "hello" or hello.get("host_id") != host_id:
            await ws.close(1008, "hello mismatch")
            return
        config = _config_message(host_id)
    except (asyncio.TimeoutError, ValueError, AttributeError, inv.InventoryError) as e:
        logger.warning("node: hello 失敗 host={}: {}", host_id, e)
        await ws.close(1008, "bad hello")
        return

    old = _connections.get(host_id)
    _connections[host_id] = ws
    if old is not None:
        logger.warning("node: 重複接続のため古い接続を切断 host={}", host_id)
        await old.close(1008, "replaced by new connection")

    store.touch(
        host_id,
        os=str(hello.get("os", "")),
        version=str(hello.get("version", "")),
        hostname=str(hello.get("hostname", "")),
    )
    logger.info("node: 接続 host={} version={}", host_id, hello.get("version", ""))
    watcher = asyncio.create_task(_watch(ws, host_id))
    try:
        await ws.send(json.dumps(config))
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            store.touch(host_id)
            if isinstance(msg, dict) and msg.get("type") == "telemetry":
                latest_telemetry[host_id] = msg
                if _telemetry_handler is not None:
                    _telemetry_handler(host_id, msg)
            elif isinstance(msg, dict) and msg.get("type") == "command_result":
                # 命令を送った host 本人の結果だけ受け取る（他 Node の接続からは解決できない）
                p = _pending.get(str(msg.get("id", "")))
                if p is not None and p[0] == host_id and not p[1].done():
                    p[1].set_result(msg)
    except Exception as e:  # ConnectionClosed を含む。切断は通常の終了として扱う
        logger.info("node: 切断 host={}: {}", host_id, type(e).__name__)
    finally:
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
        if _connections.get(host_id) is ws:
            del _connections[host_id]


def node_bind() -> tuple[str, int, ssl.SSLContext | None]:
    host = os.getenv("ANCILLA_NODE_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("ANCILLA_NODE_PORT", "8768"))
    cert = (os.getenv("ANCILLA_NODE_TLS_CERT") or "").strip()
    key = (os.getenv("ANCILLA_NODE_TLS_KEY") or "").strip()
    if bool(cert) != bool(key):
        raise SystemExit("ANCILLA_NODE_TLS_CERT と ANCILLA_NODE_TLS_KEY は両方設定してください")
    ctx = None
    if cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
    return host, port, ctx


def make_server(host: str, port: int, ssl_context: ssl.SSLContext | None = None):
    return serve(
        _handle, host, port, ssl=ssl_context, process_request=_authenticate, max_size=1024 * 1024
    )


def run_node_server(host: str, port: int, ssl_context: ssl.SSLContext | None = None) -> None:
    async def _serve() -> None:
        async with make_server(host, port, ssl_context):
            logger.info(
                "Node endpoint {}://{}:{}", "wss" if ssl_context else "ws", host, port
            )
            await asyncio.Future()

    asyncio.run(_serve())
