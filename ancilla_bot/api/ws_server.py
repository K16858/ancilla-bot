"""
WebSocket サーバー

メディア取得:
- エージェントが get_image / get_audio で media_request（request_id 付き）を送り、
  デバイスが同じ request_id で vision_input / audio_input を返すまで待つ（エージェント主導）。
- 自発の vision_input: 最新画像バッファのみ更新（通常のメッセージ化はしない）。
- 自発の audio_input（request_id なし）: STT → 最新画像があれば自動添付 → ReAct → TTS。
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from loguru import logger

from ancilla_bot.api import stt_client, tts_client
from ancilla_bot.batch.vector_store import add_summaries_to_store
from ancilla_bot.llm import send_chat
from ancilla_bot.llm.ollama_client import VISION_ENABLED
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

UPLINK_EVENTS = ("audio_input", "vision_input", "status_update", "session_end")


@dataclass
class ObservationConfig:
    """自律観察ループの設定。すべて環境変数でオーバーライド可能。"""

    enabled: bool = True
    poll_interval_sec: float = 10.0
    min_comment_interval_sec: float = 45.0
    max_comment_interval_sec: float = 180.0


_current_connection: ServerConnection | None = None
_downlink_queue: queue.Queue[tuple[str, dict]] = queue.Queue()
_run_react_cb: Callable[[str, list[dict[str, str]]], tuple[str, str | None]] | None = None
_run_observe_cb: Callable[[str], str | None] | None = None
_observe_cfg: ObservationConfig = ObservationConfig()
_session_mode: Literal["main", "edge"] = "main"
_edge_history: list[dict[str, str]] = []
# デバイス自発の vision_input の最新（エージェント取得とは別）
_latest_vision_image: str | None = None

_media_lock = threading.Lock()
# media_request に対する応答待ち（request_id -> 1 件だけ受け取るキュー）
_camera_waiters: dict[str, queue.Queue[str]] = {}
_mic_waiters: dict[str, queue.Queue[str]] = {}

_vlm_stage_lock = threading.Lock()
_staged_vlm_images: list[str] | None = None

# 観察ループ状態
_is_react_running: bool = False
_last_observe_time: float = 0.0
_prev_vision_hash: str = ""


def send_downlink(event: str, payload: dict) -> None:
    """Downlink をキューに載せる"""
    _downlink_queue.put((event, payload))


def is_edge_session() -> bool:
    """現在がエッジセッションかどうか"""
    return _session_mode == "edge"


def is_device_connected() -> bool:
    """エッジデバイスが WebSocket で接続中かどうか"""
    return _current_connection is not None and _current_connection.open


def get_latest_vision_image() -> str | None:
    """自発 vision_input の最新画像（base64）。エージェント pull とは別。"""
    return _latest_vision_image


def register_camera_waiter(request_id: str) -> queue.Queue[str]:
    q: queue.Queue[str] = queue.Queue(maxsize=1)
    with _media_lock:
        _camera_waiters[request_id] = q
    return q


def unregister_camera_waiter(request_id: str) -> None:
    with _media_lock:
        _camera_waiters.pop(request_id, None)


def register_mic_waiter(request_id: str) -> queue.Queue[str]:
    q: queue.Queue[str] = queue.Queue(maxsize=1)
    with _media_lock:
        _mic_waiters[request_id] = q
    return q


def unregister_mic_waiter(request_id: str) -> None:
    with _media_lock:
        _mic_waiters.pop(request_id, None)


def stage_vlm_images(b64_list: list[str]) -> None:
    """次の LLM 呼び出しで渡す画像（get_image 成功時）。"""
    global _staged_vlm_images
    with _vlm_stage_lock:
        _staged_vlm_images = list(b64_list)


def take_staged_vlm_images() -> list[str] | None:
    """ステージ済み画像を取り出してクリア。なければ None。"""
    global _staged_vlm_images
    with _vlm_stage_lock:
        x = _staged_vlm_images
        _staged_vlm_images = None
    return x


def _clear_media_waiters() -> None:
    with _media_lock:
        _camera_waiters.clear()
        _mic_waiters.clear()


async def _run_with_downlink_pump(
    loop: asyncio.AbstractEventLoop,
    websocket: ServerConnection,
    func: Callable,
) -> any:
    """func を executor で実行しながら downlink キューを並行してクライアントに転送する。

    ReAct 内の get_image / get_audio ツールが send_downlink() で media_request を積んでも
    _handle_connection が await run_in_executor 中で詰まるため届かない問題を解消する。
    """

    async def _pump() -> None:
        while True:
            item = await loop.run_in_executor(None, lambda: _get_downlink(0.1))
            if item is not None:
                event, payload = item
                msg = json.dumps({"event": event, **payload}, ensure_ascii=False)
                try:
                    await websocket.send(msg)
                    logger.debug("downlink pump sent: {}", event)
                except Exception as exc:
                    logger.warning("downlink pump send failed: {}", exc)
                    break

    pump_task = asyncio.create_task(_pump())
    try:
        return await loop.run_in_executor(None, func)
    finally:
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump_task


def _get_downlink(timeout: float = 0.2) -> tuple[str, dict] | None:
    try:
        return _downlink_queue.get(timeout=timeout)
    except queue.Empty:
        return None


def _image_hash(b64: str) -> str:
    """画像の変化検出用ハッシュ。PIL が使える場合は縮小グレースケール比較、なければ先頭バイト MD5。"""
    try:
        import io

        from PIL import Image

        raw = base64.b64decode(b64)
        img = Image.open(io.BytesIO(raw)).convert("L").resize((32, 32), Image.BILINEAR)
        return hashlib.md5(img.tobytes()).hexdigest()
    except Exception:
        raw_bytes = b64.encode("ascii")
        return hashlib.md5(raw_bytes[:4096]).hexdigest()


async def _observation_loop(
    loop: asyncio.AbstractEventLoop,
    websocket: ServerConnection,
    cfg: ObservationConfig,
) -> None:
    """エッジセッション中、定期的に画面を観察してコメントを生成する自律ループ。"""
    global _is_react_running, _last_observe_time, _prev_vision_hash

    logger.debug("observation loop started (poll={}s)", cfg.poll_interval_sec)
    try:
        while True:
            await asyncio.sleep(cfg.poll_interval_sec)

            if _is_react_running:
                continue
            if _run_observe_cb is None:
                continue
            image = _latest_vision_image
            if image is None:
                continue

            now = time.monotonic()
            elapsed = now - _last_observe_time
            new_hash = _image_hash(image)
            changed = new_hash != _prev_vision_hash

            should_comment = (changed and elapsed >= cfg.min_comment_interval_sec) or (
                elapsed >= cfg.max_comment_interval_sec
            )

            if not should_comment:
                if changed:
                    _prev_vision_hash = new_hash
                continue

            _prev_vision_hash = new_hash
            _last_observe_time = now
            _is_react_running = True
            logger.info("observation: generating comment (elapsed={:.0f}s, changed={})", elapsed, changed)
            try:
                response_text = await loop.run_in_executor(
                    None, lambda img=image: _run_observe_cb(img)
                )
            except Exception as exc:
                logger.warning("observation cb error: {}", exc)
                response_text = None
            finally:
                _is_react_running = False

            if response_text:
                payload: dict = {"emotion": "Neutral", "text": response_text}
                try:
                    wav_bytes = await loop.run_in_executor(
                        None, lambda: tts_client.synthesize(response_text)
                    )
                    if wav_bytes:
                        payload["audio_format"] = "wav"
                        payload["audio_data"] = base64.b64encode(wav_bytes).decode("ascii")
                except Exception as exc:
                    logger.warning("observation TTS error: {}", exc)
                _edge_history.append({"role": "assistant", "content": response_text})
                send_downlink("agent_response", payload)
                logger.info("observation: sent comment: {}", response_text[:80])
    except asyncio.CancelledError:
        logger.debug("observation loop cancelled")
        raise


def _reset_session_state() -> None:
    """セッション状態を main に戻し、エッジ履歴をクリアする"""
    global _session_mode, _edge_history
    _session_mode = "main"
    _edge_history = []
    _clear_media_waiters()
    with _vlm_stage_lock:
        global _staged_vlm_images
        _staged_vlm_images = None


def _summarize_edge_history_and_store() -> None:
    """エッジセッションの履歴を要約"""
    global _edge_history
    history = list(_edge_history)
    if not history:
        return
    parts: list[str] = []
    for m in history:
        role = m.get("role", "")
        content = (m.get("content", "") or "").strip()
        if content:
            parts.append(f"{role}: {content}")
    text = "\n".join(parts)
    if not text.strip():
        return
    prompt = "次の対話内容を1-3文で日本語要約してください。出力は要約本文のみとし、前後に説明を付けないでください。\n\n" + text
    try:
        raw = send_chat([{"role": "user", "content": prompt}], format=None)
        summary = (raw or "").strip()
        if not summary:
            return
        record = {
            "date": "",
            "start_index": 0,
            "end_index": len(history) - 1,
            "summary": summary,
            "message_count": len(history),
            "tool_used": True,
        }
        add_summaries_to_store([record])
    except Exception:
        return


def _end_edge_session(send_hide: bool = True) -> None:
    """エッジセッションを終了し、main に戻す。send_hide が True なら hide_avatar を送る。"""
    global _session_mode, _edge_history
    if _session_mode == "edge":
        _summarize_edge_history_and_store()
        _session_mode = "main"
        _edge_history = []
        _clear_media_waiters()
        with _vlm_stage_lock:
            global _staged_vlm_images
            _staged_vlm_images = None
        if send_hide:
            send_downlink("ui_control", {"command": "hide_avatar"})


def switch_to_edge_session_if_needed() -> bool:
    """現在 main ならエッジセッションに切り替え、show_avatar を送る。切り替えた場合 True。"""
    global _session_mode, _edge_history
    if _session_mode == "main":
        _session_mode = "edge"
        _edge_history = []
        _clear_media_waiters()
        send_downlink("ui_control", {"command": "show_avatar"})
        return True
    return False


async def _handle_connection(websocket: ServerConnection) -> None:
    global _current_connection, _latest_vision_image, _is_react_running
    global _last_observe_time, _prev_vision_hash
    if _current_connection is not None and _current_connection.open:
        _current_connection.close()
        await _current_connection.wait_closed()
    _current_connection = websocket
    _is_react_running = False
    _last_observe_time = 0.0
    _prev_vision_hash = ""
    logger.info("ws client connected")
    loop = asyncio.get_running_loop()

    observation_task: asyncio.Task | None = None
    if _run_observe_cb is not None and VISION_ENABLED and _observe_cfg.enabled:
        observation_task = asyncio.create_task(
            _observation_loop(loop, websocket, _observe_cfg),
            name="observation",
        )

    try:
        recv_task: asyncio.Task | None = asyncio.create_task(websocket.recv())
        queue_task = loop.run_in_executor(None, lambda: _get_downlink(0.2))
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
                                    _end_edge_session()
                                else:
                                    send_downlink("ui_control", {"command": "show_avatar"})
                            elif event == "session_end":
                                _end_edge_session()
                            elif event == "vision_input":
                                data_field = data.get("data") if isinstance(data.get("data"), str) else None
                                rid = data.get("request_id") if isinstance(data.get("request_id"), str) else None
                                if data_field and rid:
                                    with _media_lock:
                                        cq = _camera_waiters.get(rid)
                                    if cq is not None:
                                        try:
                                            cq.put_nowait(data_field)
                                        except queue.Full:
                                            pass
                                    else:
                                        _latest_vision_image = data_field
                                elif data_field:
                                    _latest_vision_image = data_field
                            elif event == "audio_input":
                                rid = data.get("request_id") if isinstance(data.get("request_id"), str) else None
                                b64 = data.get("data") if isinstance(data.get("data"), str) else None
                                # エージェント主導 get_audio への応答（ReAct は回さない）
                                if rid and b64:
                                    with _media_lock:
                                        mq = _mic_waiters.get(rid)
                                    if mq is not None:
                                        try:
                                            audio_bytes = base64.b64decode(b64)
                                        except Exception:
                                            audio_bytes = b""
                                        if audio_bytes:
                                            text = await loop.run_in_executor(
                                                None,
                                                lambda: stt_client.transcribe(audio_bytes, "audio/wav"),
                                            )
                                            st = (text or "").strip()
                                            try:
                                                mq.put_nowait(st or "(空の認識結果)")
                                            except queue.Full:
                                                pass
                                        else:
                                            try:
                                                mq.put_nowait("(デコード失敗)")
                                            except queue.Full:
                                                pass
                                        recv_task = asyncio.create_task(websocket.recv())
                                        continue
                                # --- 自発のマイク入力: STT → ReAct → TTS ---
                                switch_to_edge_session_if_needed()
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
                                            if VISION_ENABLED and _latest_vision_image:
                                                stage_vlm_images([_latest_vision_image])
                                                logger.debug("ws audio_input: staged latest vision image")
                                            _is_react_running = True
                                            try:
                                                response_text, emotion = await _run_with_downlink_pump(
                                                    loop,
                                                    websocket,
                                                    lambda t=text: _run_react_cb(t, _edge_history),
                                                )
                                            except Exception as e:
                                                logger.warning("ws audio_input ReAct failed: {}", e)
                                                response_text = "処理中にエラーが発生しました。"
                                                emotion = None
                                            finally:
                                                _is_react_running = False
                                        else:
                                            response_text = text.strip()
                                            emotion = None
                                    else:
                                        response_text = "音声データのデコードに失敗しました。"
                                else:
                                    response_text = "音声データがありません。"
                                if response_text:
                                    payload = {"emotion": (locals().get("emotion") or "Neutral"), "text": response_text}
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
                    queue_task = loop.run_in_executor(None, lambda: _get_downlink(0.2))
            if connection_closed:
                break
        for t in (recv_task, queue_task):
            if t is not None and not t.done():
                t.cancel()
    finally:
        if observation_task is not None and not observation_task.done():
            observation_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await observation_task
        if _current_connection is websocket:
            _current_connection = None
            _reset_session_state()
        logger.info("ws client disconnected")


def run_ws_server(
    host: str,
    port: int,
    run_react: Callable[[str, list[dict[str, str]]], tuple[str, str | None]] | None = None,
    run_observe: Callable[[str], str | None] | None = None,
    observe_cfg: ObservationConfig | None = None,
) -> None:
    """WebSocket サーバーを起動する。

    Args:
        run_react: audio_input 受信時に呼ぶ ReAct コールバック (text, history) -> (answer, emotion)
        run_observe: 自律観察ループが画像変化を検知したとき呼ぶコールバック (image_b64) -> comment | None
        observe_cfg: 観察ループの設定。None の場合はデフォルト値を使用。
    """
    global _run_react_cb, _run_observe_cb, _observe_cfg
    _run_react_cb = run_react
    _run_observe_cb = run_observe
    if observe_cfg is not None:
        _observe_cfg = observe_cfg

    async def _serve() -> None:
        async with serve(
            _handle_connection, host, port, max_size=16 * 1024 * 1024
        ) as ws_server:
            logger.info("WebSocket server listening on ws://{}:{}", host, port)
            await asyncio.Future()

    asyncio.run(_serve())
