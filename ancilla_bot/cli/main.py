"""
Ancilla-Bot CLIエントリーポイント
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import httpx
from dotenv import load_dotenv
from loguru import logger

from ancilla_bot.core.agent_loop import is_exit_command, run_agent_loop_with_tools
from ancilla_bot.core.cancel import reset_cancel, request_cancel
from ancilla_bot.llm import send_chat
from ancilla_bot.llm.ollama_client import VISION_ENABLED
from ancilla_bot.memory.core import build_character_prompt, build_core_memory
from ancilla_bot.heartbeat.db import (
    get_due_reminders,
    get_due_tasks,
    has_due_work,
    manage_state as db_manage_state,
    mark_reminders_completed,
    mark_agent_tasks_completed,
    mark_user_tasks_completed,
)
from ancilla_bot.ambient.aggregator import collect_context_snapshot
from ancilla_bot.api.server import run_server
from ancilla_bot.api.ws_server import (
    ObservationConfig,
    is_device_connected,
    is_edge_session,
    run_ws_server,
)
from ancilla_bot.memory.compress import compress_once, should_compress
from ancilla_bot.memory.conversation_store import append_overflow, load_active_history, load_overflow, save_active_history
from ancilla_bot.memory.short_term import append_and_trim
from ancilla_bot.notifications import append_notification
from ancilla_bot.utils.logging_config import init_logging

load_dotenv()

REASONING_THOUGHT_MAX = 200
REASONING_OBSERVATION_MAX = 100
DIM = "\033[2m"
RESET = "\033[0m"

# 履歴最大文字数
MAX_HISTORY_CHARS = int(os.getenv("ANCILLA_MAX_HISTORY_CHARS", "4000"))

HEARTBEAT_TIME_STR = os.getenv("ANCILLA_HEARTBEAT_TIME", "03:00")
HEARTBEAT_INTERVAL_SEC = 60
DEFAULT_CONVERSATION_DIR = Path(os.getenv("ANCILLA_CONVERSATION_DIR", "data/conversation"))

# メッセージ待ち行列
PENDING_MESSAGES: list[dict[str, Any]] = []

# Fast Heartbeat 用の直近日付（YYYY-MM-DD）。プロセス内でのみ保持する。
_LAST_HEARTBEAT_DATE: str | None = None

# エージェント応答がエラーとみなされるプレフィックス（ハートビート完了判定用）
_AGENT_ERROR_PREFIXES: Final[tuple[str, ...]] = (
    "内部エラー",
    "処理を完了できませんでした",
    "バックグラウンド処理中",
    "応答の解析に失敗",
)


def _is_agent_success(response: str) -> bool:
    """エージェント応答が有効（エラーでない）かどうか判定する。"""
    if not response or len(response) < 5:
        return False
    for prefix in _AGENT_ERROR_PREFIXES:
        if response.startswith(prefix):
            return False
    # 生 JSON がそのまま返ってきた場合も失敗扱い
    stripped = response.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return False
    return True

# Idle Reflection: 最終ユーザー入力時刻・最終 reflection 実行時刻（epoch 秒）。
_last_user_input_time: float = time.time()
_last_proactive_dt: datetime | None = None
_last_idle_reflection_time: float = 0.0

# 常駐モードで管理するインメモリ会話履歴。WS/API/REPL 全経路で共有。
# None のうちは未初期化（常駐モード未起動）。
_shared_history: list[dict[str, Any]] | None = None

# Idle Reflection 設定（環境変数で上書き可）
IDLE_THRESHOLD_SEC: Final[int] = int(os.getenv("ANCILLA_IDLE_THRESHOLD_MIN", "30")) * 60
IDLE_COOLDOWN_SEC: Final[int] = int(os.getenv("ANCILLA_IDLE_COOLDOWN_MIN", "60")) * 60
IDLE_POLL_SEC: Final[int] = 60  # アイドル監視のポーリング間隔（秒）
IDLE_MAX_TOOL_TURNS: Final[int] = int(os.getenv("ANCILLA_IDLE_MAX_TOOL_TURNS", "8"))


def _reasoning_line(text: str, dim: bool) -> str:
    if dim and sys.stderr.isatty():
        return f"{DIM}{text}{RESET}"
    return text


def _print_reasoning(
    thought: str,
    action: str | None,
    action_input: dict[str, Any] | None,
    observation: str | None,
) -> None:
    dim = True
    t = (thought or "")[:REASONING_THOUGHT_MAX]
    if len(thought or "") > REASONING_THOUGHT_MAX:
        t += "..."
    if t:
        print(_reasoning_line(f"  thought: {t}", dim))
    if action is not None:
        args_str = str(action_input or {})[:80]
        if len(str(action_input or {})) > 80:
            args_str += "..."
        line = f"  action: {action} ({args_str})"
        if observation:
            obs = observation.replace("Observation: ", "", 1)[:REASONING_OBSERVATION_MAX]
            if len(observation) > REASONING_OBSERVATION_MAX + 12:
                obs += "..."
            line += f" → Observation: {obs}"
        print(_reasoning_line(line, dim))


def _parse_heartbeat_time(s: str) -> tuple[int, int]:
    """ANCILLA_HEARTBEAT_TIME を (hour, minute) にパース。デフォルト (3, 0)。"""
    s = (s or "03:00").strip()
    try:
        parts = s.split(":")
        hour = int(parts[0]) % 24
        minute = int(parts[1]) if len(parts) > 1 else 0
        return (hour, minute)
    except (ValueError, IndexError):
        return (3, 0)


def _slow_heartbeat_loop(lock: threading.Lock, stop: threading.Event) -> None:
    """1分ごとに時刻を確認し、設定時刻かつ未実行なら run_summarize を実行。"""
    hour_target, minute_target = _parse_heartbeat_time(HEARTBEAT_TIME_STR)
    last_run_path = Path(os.getenv("ANCILLA_CONVERSATION_DIR", str(DEFAULT_CONVERSATION_DIR))) / "heartbeat_last_run.txt"
    last_run_path.parent.mkdir(parents=True, exist_ok=True)

    while not stop.is_set():
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            if last_run_path.exists():
                try:
                    last = last_run_path.read_text(encoding="utf-8").strip()
                    if last == today:
                        stop.wait(HEARTBEAT_INTERVAL_SEC)
                        continue
                except OSError:
                    pass
            if now.hour == hour_target and now.minute == minute_target:
                if is_edge_session():
                    stop.wait(HEARTBEAT_INTERVAL_SEC)
                    continue
                if lock.acquire(blocking=False):
                    try:
                        from ancilla_bot.batch.summarize import run_summarize

                        # その日の要約・ベクトル化
                        run_summarize()
                        last_run_path.write_text(today, encoding="utf-8")
                        logger.info("run_summarize done for {}", today)
                    except Exception as e:
                        logger.warning("run_summarize failed: {}", e)
                    finally:
                        lock.release()
        except Exception as e:
            logger.warning("loop error: {}", e)
        stop.wait(HEARTBEAT_INTERVAL_SEC)


def _build_fast_heartbeat_message(
    tasks: list,
    reminders: list,
    *,
    date_changed: bool,
    today: str,
) -> str:
    """取得したタスク・リマインダーと日付変更イベントから擬似メッセージを組み立てる。"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    if date_changed:
        parts = [
            f"[SYSTEM_EVENT] 日付が {today} に変更されました。現在時刻は{now_str}です。"
        ]
    else:
        parts = [f"[SYSTEM_EVENT] 現在時刻は{now_str}です。"]
    if is_device_connected():
        parts.append(
            "[エッジデバイス接続中] カメラ・マイク付きのデバイスが現在接続されています。"
            "必要と判断した場合は use_edgedevice ツールでデバイスとやりとりできます。"
        )
    for t in tasks:
        parts.append(f"タスクID #{t['id']}: {t['content']}（予定: {t['scheduled_at']}）")
    for r in reminders:
        parts.append(f"リマインダーID #{r['id']}: {r['content']}（予定: {r['scheduled_at']}）")
    parts.append("ユーザーに適切な通知を行い、タスクを完了状態にしてください。")
    return "\n".join(parts)


def _load_proactive_rules() -> list[dict[str, Any]]:
    import yaml

    path = Path(os.getenv("ANCILLA_PROACTIVE_RULES_PATH", "data/proactive_rules.yaml"))
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = data.get("rules") or []
    return [r for r in rules if isinstance(r, dict)]


def _maybe_run_proactive(snapshot: dict[str, Any], lock: threading.Lock) -> None:
    global _last_proactive_dt
    from ancilla_bot.personal_model import load as load_personal_model
    from ancilla_bot.proactive import can_interrupt, evaluate

    rules = _load_proactive_rules()
    if not rules:
        return
    last_interaction = (
        datetime.fromtimestamp(_last_user_input_time)
        if _last_user_input_time > 0
        else datetime.now()
    )
    action = evaluate(snapshot, load_personal_model(), rules, last_interaction)
    if action is None or not can_interrupt(action, _last_proactive_dt):
        return
    if not lock.acquire(blocking=False):
        return
    try:
        pseudo = f"[SYSTEM_EVENT:PROACTIVE:{action.trigger}] {action.content}"
        history = _shared_history if _shared_history is not None else load_active_history()
        response, _emotion = run_agent_loop_with_tools(pseudo, history, on_turn=None)
        if response.strip():
            append_notification(
                response.strip(),
                source="system",
                level="info",
                detail=f"proactive={action.trigger}",
            )
        if _shared_history is not None and response:
            dropped = append_and_trim(
                _shared_history,
                [
                    {"role": "user", "content": pseudo},
                    {"role": "assistant", "content": response},
                ],
                max_chars=MAX_HISTORY_CHARS,
            )
            if dropped:
                append_overflow(dropped)
            save_active_history(_shared_history)
        _last_proactive_dt = datetime.now()
        logger.info("proactive action triggered: {}", action.trigger)
    except Exception as e:
        logger.warning("proactive run failed: {}", e)
    finally:
        lock.release()


def _fast_heartbeat_loop(lock: threading.Lock, stop: threading.Event) -> None:
    """該当タスク・リマインダーがあれば擬似メッセージを ReAct に投入"""
    while not stop.is_set():
        try:
            if is_edge_session():
                stop.wait(HEARTBEAT_INTERVAL_SEC)
                continue
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            global _LAST_HEARTBEAT_DATE
            date_changed = _LAST_HEARTBEAT_DATE is not None and today != _LAST_HEARTBEAT_DATE
            _LAST_HEARTBEAT_DATE = today

            if not date_changed and not has_due_work(at=now):
                snapshot = collect_context_snapshot(_last_user_input_time)
                if snapshot:
                    logger.debug("ambient snapshot keys={}", list(snapshot.keys()))
                    _maybe_run_proactive(snapshot, lock)
                stop.wait(HEARTBEAT_INTERVAL_SEC)
                continue
            if not lock.acquire(blocking=False):
                stop.wait(HEARTBEAT_INTERVAL_SEC)
                continue
            try:
                tasks = get_due_tasks(at=now)
                reminders = get_due_reminders(at=now)
                if not date_changed and not tasks and not reminders:
                    continue
                pseudo = _build_fast_heartbeat_message(
                    tasks,
                    reminders,
                    date_changed=date_changed,
                    today=today,
                )
                history = _shared_history if _shared_history is not None else load_active_history()
                response, _emotion = run_agent_loop_with_tools(pseudo, history, on_turn=None)
                if _is_agent_success(response):
                    user_ids = [t["id"] for t in tasks if t.get("_table") == "user_tasks"]
                    agent_ids = [t["id"] for t in tasks if t.get("_table") == "agent_tasks"]
                    mark_user_tasks_completed(user_ids)
                    mark_agent_tasks_completed(agent_ids)
                    mark_reminders_completed([r["id"] for r in reminders])
                    if response.strip():
                        append_notification(
                            response.strip(),
                            source="system",
                            level="info",
                            detail=f"tasks={len(tasks)}, reminders={len(reminders)}",
                        )
                    # heartbeat の会話を共有履歴に保存してコンテキストを継続
                    if _shared_history is not None and response:
                        dropped = append_and_trim(
                            _shared_history,
                            [
                                {"role": "user", "content": pseudo},
                                {"role": "assistant", "content": response},
                            ],
                            max_chars=MAX_HISTORY_CHARS,
                        )
                        if dropped:
                            append_overflow(dropped)
                        save_active_history(_shared_history)
                    logger.info("fast heartbeat: processed {} tasks, {} reminders", len(tasks), len(reminders))
                else:
                    logger.warning(
                        "fast heartbeat: agent response looks like an error, NOT marking completed. response={!r}",
                        response[:120],
                    )
            except Exception as e:
                logger.warning("fast heartbeat run failed: {}", e)
            finally:
                lock.release()
        except Exception as e:
            logger.warning("fast heartbeat loop error: {}", e)
        stop.wait(HEARTBEAT_INTERVAL_SEC)


def _load_pending_self_tasks() -> str:
    """source='self' かつ completed=0 の agent_tasks を取得してプロンプト用文字列に変換する。"""
    try:
        import json
        raw = db_manage_state(
            table="agent_tasks",
            operation="select",
            payload={"source": "self", "completed": False, "limit": 20},
        )
        tasks = json.loads(raw) if raw and raw.startswith("[") else []
        if not tasks:
            return ""
        lines = [f"  [{t['id']}] {t['content']}" for t in tasks]
        return "\n".join(lines)
    except Exception:
        return ""


def _build_idle_reflection_message(idle_min: int = 0) -> str:
    """
    Idle Reflection メッセージを組み立てる。
    idle_min: ユーザーからの最終入力からの経過分数。
    """
    device_note = (
        "\nNote: An edge device (camera/mic) is currently connected."
        " If useful, you may call use_edgedevice to interact with it."
        if is_device_connected()
        else ""
    )
    idle_str = f"{idle_min} minutes" if idle_min > 0 else "a while"

    pending_tasks_str = _load_pending_self_tasks()
    if pending_tasks_str:
        pending_block = (
            "\n\n[Your pending self-tasks (source=self, completed=0) — loaded automatically]:\n"
            + pending_tasks_str
            + "\nResume or complete these before starting new work."
        )
    else:
        pending_block = ""

    return (
        f"[SYSTEM_EVENT: IDLE_REFLECTION] No user input for {idle_str}.\n\n"
        "Use this idle time proactively and freely.\n\n"
        "Style:\n"
        "  - You may act autonomously and creatively.\n"
        "  - Casual chat, small updates, and mood-based check-ins are welcome.\n"
        "  - You do not need to be overly formal or task-only.\n\n"
        "Guidance:\n"
        "1) Avoid repetitive behavior.\n"
        "  - Do not keep repeating the same topic in consecutive idle cycles.\n"
        "  - If your current idea is too similar to what you recently did, switch topics or angle.\n\n"
        "2) Preserve freedom.\n"
        "  - You can choose any useful action: research, note updates, cleanup, reminders, brainstorming, or light conversation.\n"
        "  - If there are pending tasks, you may handle them first, but side exploration is allowed.\n\n"
        "3) Keep notifications pleasant.\n"
        "  - You may notify the user casually.\n"
        "  - Avoid notifications with essentially the same content as recent ones.\n\n"
        "4) Prefer novelty when possible.\n"
        "  - If new information is weak, pivot to another interest, unfinished item, or a small improvement.\n\n"
        "Operational hints:\n"
        "  - Check your pending self-tasks and relevant state as needed.\n"
        "  - Update your task status when you make progress.\n"
        "  - If nothing meaningful is found, finish with a brief final answer."
        f"{pending_block}"
        f"{device_note}"
    )


def _idle_reflection_loop(lock: threading.Lock, stop: threading.Event) -> None:
    """
    アイドル時間を監視し、閾値を超えたら Idle Reflection を実行する。
    ANCILLA_IDLE_THRESHOLD_MIN（デフォルト30分）以上入力がなく、
    かつ ANCILLA_IDLE_COOLDOWN_MIN（デフォルト60分）以上前に最後の reflection が実行されていれば発動。
    """
    global _last_idle_reflection_time
    while not stop.is_set():
        stop.wait(IDLE_POLL_SEC)
        if stop.is_set():
            break
        try:
            if is_edge_session():
                continue
            now = time.time()
            idle_sec = now - _last_user_input_time
            since_last = now - _last_idle_reflection_time
            if idle_sec < IDLE_THRESHOLD_SEC:
                continue
            if since_last < IDLE_COOLDOWN_SEC:
                continue
            if not lock.acquire(blocking=False):
                continue
            try:
                idle_min = int(idle_sec / 60)
                msg = _build_idle_reflection_message(idle_min)
                history = _shared_history if _shared_history is not None else load_active_history()
                response, _emotion = run_agent_loop_with_tools(
                    msg,
                    history,
                    on_turn=None,
                    max_turns=IDLE_MAX_TOOL_TURNS,
                    nag_interval=3,
                    nag_message="Check and update your agent_tasks (source=self) to track progress.",
                )
                # idle reflection の会話を共有履歴に保存してコンテキストを継続
                if _shared_history is not None and response:
                    dropped = append_and_trim(
                        _shared_history,
                        [
                            {"role": "user", "content": msg},
                            {"role": "assistant", "content": response},
                        ],
                        max_chars=MAX_HISTORY_CHARS,
                    )
                    if dropped:
                        append_overflow(dropped)
                    save_active_history(_shared_history)
                _last_idle_reflection_time = time.time()
                logger.info("idle reflection triggered after {} min idle", idle_min)
            except Exception as e:
                logger.warning("idle reflection failed: {}", e)
            finally:
                lock.release()
        except Exception as e:
            logger.warning("idle reflection loop error: {}", e)


def _handle_message(
    user_input: str,
    conversation_history: list[dict[str, str]],
    agent_lock: threading.Lock | None,
    max_chars: int,
    on_turn: Any,
    images: list[str] | None = None,
    *,
    source: str | None = None,
) -> str:
    global _last_user_input_time
    _last_user_input_time = time.time()
    reset_cancel()

    if agent_lock is not None and not agent_lock.acquire(blocking=False):
        PENDING_MESSAGES.append(
            {"input": user_input, "images": images, "source": source or "unknown"}
        )
        return "バックグラウンド処理中です。しばらくお待ちください。"
    try:
        result = _process_message_core(
            user_input,
            conversation_history,
            max_chars=max_chars,
            on_turn=on_turn,
            images=images,
        )
        if agent_lock is not None:
            threading.Thread(
                target=_run_compress_with_lock,
                args=(conversation_history, max_chars, agent_lock),
                daemon=True,
                name="compress",
            ).start()
            threading.Thread(
                target=_run_summarize_with_lock,
                args=(agent_lock,),
                daemon=True,
                name="summarize",
            ).start()
        else:
            _run_compress_loop(conversation_history, max_chars)
        return result
    finally:
        if agent_lock is not None:
            agent_lock.release()


def _process_message_core(
    user_input: str,
    conversation_history: list[dict[str, str]],
    *,
    max_chars: int,
    on_turn: Any,
    images: list[str] | None = None,
) -> str:
    """
    Lock を取得済みであることを前提に、1 メッセージ分の処理を行う。
    """
    if images and not VISION_ENABLED:
        return "画像処理は無効です。.env で OLLAMA_VISION_ENABLED=true にしてください（メインモデルが視覚対応の場合）。"
    response, _emotion = run_agent_loop_with_tools(
        user_input, conversation_history, on_turn=on_turn, images=images
    )
    user_msg = {"role": "user", "content": user_input}
    assistant_msg = {"role": "assistant", "content": response}
    dropped = append_and_trim(
        conversation_history,
        [user_msg, assistant_msg],
        max_chars=max_chars,
    )
    if dropped:
        append_overflow(dropped)
    save_active_history(conversation_history)
    return response


def _run_compress_loop(history: list[dict[str, str]], max_chars: int) -> None:
    """会話履歴が閾値を超えていれば要約・長期記憶書き込みを繰り返す。"""
    while should_compress(history, max_chars):
        compress_once(history, max_chars)


def _run_compress_with_lock(
    history: list[dict[str, str]], max_chars: int, lock: threading.Lock
) -> None:
    """agent_lock を取得してから _run_compress_loop を実行する（バックグラウンド用）。"""
    lock.acquire()
    try:
        _run_compress_loop(history, max_chars)
    finally:
        lock.release()


def _run_summarize_with_lock(lock: threading.Lock) -> None:
    """overflow が十分たまったらバッチ要約を実行する（バックグラウンド用）。"""
    from ancilla_bot.batch.summarize import TURNS_PER_BLOCK, run_summarize

    if len(load_overflow()) < 2 * TURNS_PER_BLOCK:
        return
    lock.acquire()
    try:
        run_summarize()
        from ancilla_bot.personal_model import extract_and_update

        extract_and_update(load_overflow() + load_active_history())
    except Exception as e:
        logger.warning("batch summarize failed: {}", e)
    finally:
        lock.release()


def _run_repl(
    args: argparse.Namespace,
    *,
    agent_lock: threading.Lock | None = None,
    conversation_history: list[dict[str, str]] | None = None,
) -> None:
    level = "DEBUG" if args.verbose else os.getenv("ANCILLA_LOG_LEVEL", "INFO")
    log_file = args.log_file or os.getenv("ANCILLA_LOG_FILE") or None
    init_logging(level=level, log_file=log_file)

    print("Ancilla CLI を起動しました。終了するには 'exit', 'quit', ':q' のいずれかを入力してください。")
    history = conversation_history if conversation_history is not None else load_active_history()
    on_turn = _print_reasoning if args.show_reasoning else None

    try:
        while True:
            # まずキューに溜まったメッセージを処理する（REPL 起動中のみ）
            while PENDING_MESSAGES:
                pending = PENDING_MESSAGES.pop(0)
                # Lock があれば取得してから処理する
                if agent_lock is not None and not agent_lock.acquire(blocking=False):
                    # まだ処理できないので先頭に戻して後回し
                    PENDING_MESSAGES.insert(0, pending)
                    break
                try:
                    response = _process_message_core(
                        pending.get("input", ""),
                        history,
                        max_chars=MAX_HISTORY_CHARS,
                        on_turn=on_turn,
                        images=pending.get("images"),
                    )
                    if agent_lock is not None:
                        threading.Thread(
                            target=_run_compress_with_lock,
                            args=(history, MAX_HISTORY_CHARS, agent_lock),
                            daemon=True,
                            name="compress",
                        ).start()
                    else:
                        _run_compress_loop(history, MAX_HISTORY_CHARS)
                    print(f"Ancilla (queued): {response}")
                finally:
                    if agent_lock is not None and agent_lock.locked():
                        agent_lock.release()

            try:
                user_input = input("Ancilla CLI > ")
            except (EOFError, KeyboardInterrupt):
                print("\n終了します。")
                break

            if is_exit_command(user_input):
                print("終了コマンドが入力されたため、REPL を終了します。")
                break

            response = _handle_message(
                user_input,
                history,
                agent_lock,
                MAX_HISTORY_CHARS,
                on_turn,
                source="repl",
            )
            print(f"Ancilla: {response}")
    finally:
        if conversation_history is None:
            save_active_history(history)


def _run_client(args: argparse.Namespace) -> None:
    host = os.getenv("ANCILLA_API_HOST", "127.0.0.1")
    port = int(os.getenv("ANCILLA_API_PORT", "8765"))
    url = f"http://{host}:{port}/chat"
    print(f"Ancilla クライアント (接続先 {url})。終了: exit / quit / :q")
    while True:
        try:
            user_input = input("Ancilla CLI > ")
        except (EOFError, KeyboardInterrupt):
            print("\n終了します。")
            break
        if is_exit_command(user_input):
            print("終了コマンドが入力されたため、終了します。")
            break
        try:
            resp = httpx.post(url, json={"message": user_input}, timeout=60.0)
            resp.raise_for_status()
            data = resp.json()
            print(f"Ancilla: {data.get('response', '')}")
        except httpx.ConnectError:
            print("Ancilla: 接続できません。ancilla run が起動しているか確認してください。")
        except Exception as e:
            print(f"Ancilla: エラー {e}")


def _run_batch_summarize() -> None:
    from ancilla_bot.batch.summarize import run_summarize

    run_summarize()


def _run_resident(args: argparse.Namespace) -> None:
    global _shared_history
    agent_lock = threading.Lock()
    stop = threading.Event()
    conversation_history = load_active_history()
    _shared_history = conversation_history  # 全スレッドで共有
    api_port = int(os.getenv("ANCILLA_API_PORT", "8765"))

    def chat_handler(msg: str, imgs: list[str] | None = None) -> str:
        return _handle_message(
            msg,
            conversation_history,
            agent_lock,
            MAX_HISTORY_CHARS,
            None,
            images=imgs,
            source="api",
        )

    api_thread = threading.Thread(
        target=lambda: run_server(
            "127.0.0.1", api_port, chat_handler, cancel_handler=request_cancel
        ),
        daemon=True,
        name="api",
    )
    api_thread.start()
    logger.info("API http://127.0.0.1:{}/chat", api_port)

    ws_port = int(os.getenv("ANCILLA_WS_PORT", "8766"))

    def run_react_ws(text: str, history: list | None = None) -> tuple[str, str | None]:
        """
        WS 用: (answer, emotion) を返す
        """
        global _last_user_input_time
        _last_user_input_time = time.time()

        conv_history: list[dict[str, str]] = history if history is not None else []
        if agent_lock is not None and not agent_lock.acquire(blocking=False):
            return "バックグラウンド処理中です。しばらくお待ちください。", None
        try:
            answer, emotion = run_agent_loop_with_tools(
                text,
                conv_history,
                on_turn=None,
                images=None,
            )
            user_msg: dict[str, str] = {"role": "user", "content": text}
            assistant_msg: dict[str, str] = {"role": "assistant", "content": answer}
            if history is not None:
                history.append(user_msg)
                history.append(assistant_msg)
            # WS 会話を main 履歴にも追記してディスクに保存（idle/heartbeat 参照用）
            dropped = append_and_trim(
                conversation_history, [user_msg, assistant_msg], max_chars=MAX_HISTORY_CHARS
            )
            if dropped:
                append_overflow(dropped)
            save_active_history(conversation_history)
            # compress は別スレッドで（ロックは既に保持中なので直接実行）
            _run_compress_loop(conversation_history, MAX_HISTORY_CHARS)
            return answer, emotion
        finally:
            if agent_lock is not None:
                agent_lock.release()

    def _run_observe_ws(image_b64: str, history: list[dict[str, str]] | None = None) -> str | None:
        """エージェント自律観察: 画像を見て短いコメントを生成する（ReAct なし）。"""
        if agent_lock is not None and not agent_lock.acquire(blocking=False):
            return None
        try:
            system_prompt = build_character_prompt()
            recent = (history or [])[-6:]  # 直近6件までをコンテキストとして挿入
            msgs: list[dict] = [{"role": "system", "content": system_prompt}]
            msgs.extend(recent)
            msgs.append({"role": "user", "content": "今の状況を見て、自然に一言どうぞ。"})
            result = send_chat(msgs, images=[image_b64])
            return (result or "").strip() or None
        except Exception as exc:
            logger.warning("observe ws error: {}", exc)
            return None
        finally:
            if agent_lock is not None:
                agent_lock.release()

    obs_cfg = ObservationConfig(
        enabled=os.getenv("ANCILLA_OBS_ENABLED", "true").strip().lower() in ("1", "true", "yes"),
        poll_interval_sec=float(os.getenv("ANCILLA_OBS_POLL_SEC", "10")),
        min_comment_interval_sec=float(os.getenv("ANCILLA_OBS_MIN_INTERVAL_SEC", "45")),
        max_comment_interval_sec=float(os.getenv("ANCILLA_OBS_MAX_INTERVAL_SEC", "180")),
    )

    ws_thread = threading.Thread(
        target=run_ws_server,
        args=("127.0.0.1", ws_port),
        kwargs={
            "run_react": run_react_ws,
            "run_observe": _run_observe_ws if VISION_ENABLED else None,
            "observe_cfg": obs_cfg,
        },
        daemon=True,
        name="ws",
    )
    ws_thread.start()
    logger.info("WebSocket ws://127.0.0.1:{}", ws_port)

    slow_thread = threading.Thread(
        target=_slow_heartbeat_loop,
        args=(agent_lock, stop),
        daemon=True,
        name="slow_heartbeat",
    )
    fast_thread = threading.Thread(
        target=_fast_heartbeat_loop,
        args=(agent_lock, stop),
        daemon=True,
        name="fast_heartbeat",
    )
    idle_thread = threading.Thread(
        target=_idle_reflection_loop,
        args=(agent_lock, stop),
        daemon=True,
        name="idle_reflection",
    )
    slow_thread.start()
    fast_thread.start()
    idle_thread.start()
    logger.info(
        "idle reflection: threshold={}min cooldown={}min",
        IDLE_THRESHOLD_SEC // 60,
        IDLE_COOLDOWN_SEC // 60,
    )
    try:
        _run_repl(args, agent_lock=agent_lock, conversation_history=conversation_history)
    finally:
        save_active_history(conversation_history)
        stop.set()
        slow_thread.join(timeout=HEARTBEAT_INTERVAL_SEC + 5)
        fast_thread.join(timeout=HEARTBEAT_INTERVAL_SEC + 5)
        idle_thread.join(timeout=IDLE_POLL_SEC + 5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ancilla-Bot CLI")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG レベルでログを出力")
    parser.add_argument("--log-file", metavar="PATH", help="ログをファイルにも出力（例: data/logs/ancilla.log）")
    parser.add_argument("-r", "--show-reasoning", action="store_true", help="thought とツール呼び出しを薄く表示")
    subparsers = parser.add_subparsers(dest="command", help="サブコマンド")

    subparsers.add_parser("run", help="常駐モード（REPL + API + Heartbeat）。終了は exit 等。")
    subparsers.add_parser("client", help="API に接続する REPL クライアント。先に ancilla run を起動すること。")
    subparsers.add_parser("discord", help="Discord Bot。先に ancilla run を起動し、DISCORD_BOT_TOKEN を設定すること。")
    subparsers.add_parser("slack", help="Slack Bot（Socket Mode）。先に ancilla run を起動し、SLACK_BOT_TOKEN と SLACK_APP_TOKEN を設定すること。")

    batch_parser = subparsers.add_parser("batch", help="バッチ処理")
    batch_sub = batch_parser.add_subparsers(dest="batch_command", required=True)
    batch_sub.add_parser("summarize", help="会話を結合し summaries に出力")

    args = parser.parse_args()

    if args.command == "run":
        _run_resident(args)
        return
    if args.command == "client":
        _run_client(args)
        return
    if args.command == "discord":
        from ancilla_bot.discord_bot import main as discord_main
        discord_main()
        return
    if args.command == "slack":
        from ancilla_bot.slack_bot import main as slack_main
        slack_main()
        return
    if args.command == "batch":
        if args.batch_command == "summarize":
            _run_batch_summarize()
        return

    _run_repl(args, agent_lock=None)


if __name__ == "__main__":
    main()

