"""
WebSocket サーバー
"""

from __future__ import annotations

import asyncio
import json
import queue

from loguru import logger
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

UPLINK_EVENTS = ("audio_input", "vision_input", "status_update")

_current_connection: ServerConnection | None = None
_downlink_queue: queue.Queue[tuple[str, dict]] = queue.Queue()


def send_downlink(event: str, payload: dict) -> None:
    """Downlink をキューに載せる"""
    _downlink_queue.put((event, payload))


def _get_downlink(timeout: float = 0.2) -> tuple[str, dict] | None:
    try:
        return _downlink_queue.get(timeout=timeout)
    except queue.Empty:
        return None


async def _handle_connection(websocket: ServerConnection) -> None:
    global _current_connection
    if _current_connection is not None and _current_connection.open:
        _current_connection.close()
        await _current_connection.wait_closed()
    _current_connection = websocket
    logger.info("ws client connected")
    loop = asyncio.get_running_loop()
    try:
        recv_task: asyncio.Task | None = asyncio.create_task(websocket.recv())
        queue_task: asyncio.Task | None = asyncio.create_task(
            loop.run_in_executor(None, lambda: _get_downlink(0.2))
        )
        connection_closed = False
        while True:
            done, pending = await asyncio.wait(
                [t for t in (recv_task, queue_task) if t is not None],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in done:
                if t is recv_task:
                    recv_task = None
                    try:
                        raw = t.result()
                    except ConnectionClosed:
                        for p in pending:
                            p.cancel()
                        connection_closed = True
                        break
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")
                    try:
                        data = json.loads(raw)
                        event = data.get("event") if isinstance(data, dict) else None
                        if event in UPLINK_EVENTS:
                            logger.info("ws event: {}", event)
                            if event == "status_update":
                                send_downlink("ui_control", {"command": "show_avatar"})
                        elif event is not None:
                            logger.debug("ws event (unhandled): {}", event)
                    except json.JSONDecodeError:
                        logger.debug(
                            "ws invalid JSON: {}", raw[:200] if len(raw) > 200 else raw
                        )
                    recv_task = asyncio.create_task(websocket.recv())
                elif t is queue_task:
                    queue_task = None
                    item = t.result()
                    if item is not None:
                        event, payload = item
                        msg = json.dumps({"event": event, **payload}, ensure_ascii=False)
                        await websocket.send(msg)
                    queue_task = asyncio.create_task(
                        loop.run_in_executor(None, lambda: _get_downlink(0.2))
                    )
            if connection_closed:
                break
        for t in (recv_task, queue_task):
            if t is not None and not t.done():
                t.cancel()
    finally:
        if _current_connection is websocket:
            _current_connection = None
        logger.info("ws client disconnected")


def run_ws_server(host: str, port: int) -> None:
    """WebSocket サーバーを起動する"""
    async def _serve() -> None:
        async with serve(_handle_connection, host, port) as ws_server:
            logger.info("WebSocket server listening on ws://{}:{}", host, port)
            await asyncio.Future()

    asyncio.run(_serve())
