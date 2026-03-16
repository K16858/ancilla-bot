"""
WebSocket サーバー
"""

from __future__ import annotations

import asyncio
import base64
import json
import queue
from collections.abc import Callable
from typing import Literal

from loguru import logger

from ancilla_bot.api import stt_client, tts_client
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

UPLINK_EVENTS = ("audio_input", "vision_input", "status_update", "session_end")

_current_connection: ServerConnection | None = None
_downlink_queue: queue.Queue[tuple[str, dict]] = queue.Queue()
_run_react_cb: Callable[[str, list[dict[str, str]]], str] | None = None
_session_mode: Literal["main", "dedicated"] = "main"
_dedicated_history: list[dict[str, str]] = []


def send_downlink(event: str, payload: dict) -> None:
    """Downlink をキューに載せる"""
    _downlink_queue.put((event, payload))


def _get_downlink(timeout: float = 0.2) -> tuple[str, dict] | None:
    try:
        return _downlink_queue.get(timeout=timeout)
    except queue.Empty:
        return None


def _reset_session_state() -> None:
    """セッション状態を main に戻し、専用履歴をクリアする"""
    global _session_mode, _dedicated_history
    _session_mode = "main"
    _dedicated_history = []


def _end_dedicated_session(send_hide: bool = True) -> None:
    """専用セッションを終了し、main に戻す。send_hide が True なら hide_avatar を送る。"""
    global _session_mode, _dedicated_history
    if _session_mode == "dedicated":
        _session_mode = "main"
        _dedicated_history = []
        if send_hide:
            send_downlink("ui_control", {"command": "hide_avatar"})


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
                                state = data.get("state") if isinstance(data, dict) else None
                                if state == "disconnected":
                                    _end_dedicated_session()
                                else:
                                    send_downlink("ui_control", {"command": "show_avatar"})
                            elif event == "session_end":
                                _end_dedicated_session()
                            elif event == "audio_input":
                                global _session_mode, _dedicated_history
                                if _session_mode == "main":
                                    _session_mode = "dedicated"
                                    _dedicated_history = []
                                    send_downlink("ui_control", {"command": "show_avatar"})
                                b64 = data.get("data") if isinstance(data.get("data"), str) else None
                                response_text = ""
                                if b64:
                                    try:
                                        audio_bytes = base64.b64decode(b64)
                                    except Exception:
                                        audio_bytes = b""
                                    if audio_bytes:
                                        text = await loop.run_in_executor(
                                            None,
                                            lambda: stt_client.transcribe(audio_bytes, "audio/wav"),
                                        )
                                        logger.info("ws audio_input STT: {}", text or "(empty)")
                                        if not (text or "").strip():
                                            response_text = "音声を認識できませんでした。"
                                        elif _run_react_cb:
                                            try:
                                                response_text = await loop.run_in_executor(
                                                    None,
                                                    lambda t=text: _run_react_cb(t, _dedicated_history),
                                                )
                                            except Exception as e:
                                                logger.warning("ws audio_input ReAct failed: {}", e)
                                                response_text = "処理中にエラーが発生しました。"
                                        else:
                                            response_text = text.strip()
                                    else:
                                        response_text = "音声データのデコードに失敗しました。"
                                else:
                                    response_text = "音声データがありません。"
                                if response_text:
                                    payload = {"emotion_tag": "Neutral", "text": response_text}
                                    wav_bytes = await loop.run_in_executor(
                                        None,
                                        lambda: tts_client.synthesize(response_text),
                                    )
                                    if wav_bytes:
                                        payload["audio_format"] = "wav"
                                        payload["audio_data"] = base64.b64encode(wav_bytes).decode("ascii")
                                    send_downlink("agent_response", payload)
                                else:
                                    logger.debug("ws audio_input: no data")
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
            _reset_session_state()
        logger.info("ws client disconnected")


def run_ws_server(
    host: str,
    port: int,
    run_react: Callable[[str, list[dict[str, str]]], str] | None = None,
) -> None:
    """WebSocket サーバーを起動する。run_react(text, history) が渡されていれば audio_input で ReAct を実行する。"""
    global _run_react_cb
    _run_react_cb = run_react

    async def _serve() -> None:
        async with serve(_handle_connection, host, port) as ws_server:
            logger.info("WebSocket server listening on ws://{}:{}", host, port)
            await asyncio.Future()

    asyncio.run(_serve())
