"""
WebSocket サーバー
"""

from __future__ import annotations

import asyncio
import json

from loguru import logger
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

UPLINK_EVENTS = ("audio_input", "vision_input", "status_update")

_current_connection: ServerConnection | None = None


async def _handle_connection(websocket: ServerConnection) -> None:
    global _current_connection
    if _current_connection is not None and _current_connection.open:
        _current_connection.close()
        await _current_connection.wait_closed()
    _current_connection = websocket
    logger.info("ws client connected")
    try:
        while True:
            raw = await websocket.recv()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
                event = data.get("event") if isinstance(data, dict) else None
                if event in UPLINK_EVENTS:
                    logger.info("ws event: {}", event)
                elif event is not None:
                    logger.debug("ws event (unhandled): {}", event)
            except json.JSONDecodeError:
                logger.debug("ws invalid JSON: {}", raw[:200] if len(raw) > 200 else raw)
    except ConnectionClosed:
        pass
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
