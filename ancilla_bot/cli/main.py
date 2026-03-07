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
from typing import Any

import httpx
from dotenv import load_dotenv
from loguru import logger

from ancilla_bot.core.agent_loop import is_exit_command, run_agent_loop_with_tools
from ancilla_bot.llm.ollama_client import VISION_ENABLED
from ancilla_bot.heartbeat.db import (
    get_due_reminders,
    get_due_tasks,
    has_due_work,
    mark_reminders_completed,
    mark_tasks_completed,
)
from ancilla_bot.api.server import run_server
from ancilla_bot.memory.compress import compress_once, should_compress
from ancilla_bot.memory.conversation_store import append_overflow, load_active_history, save_active_history
from ancilla_bot.memory.short_term import append_and_trim
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
                if lock.acquire(blocking=False):
                    try:
                        from ancilla_bot.batch.summarize import run_summarize
                        run_summarize()
                        last_run_path.write_text(today, encoding="utf-8")
                        logger.info("slow heartbeat: run_summarize done for {}", today)
                    except Exception as e:
                        logger.warning("slow heartbeat run_summarize failed: {}", e)
                    finally:
                        lock.release()
        except Exception as e:
            logger.warning("slow heartbeat loop error: {}", e)
        stop.wait(HEARTBEAT_INTERVAL_SEC)


def _build_fast_heartbeat_message(tasks: list, reminders: list) -> str:
    """取得したタスク・リマインダーから擬似メッセージを組み立てる。"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [f"[SYSTEM_EVENT: HEARTBEAT] 現在時刻は{now_str}です。"]
    for t in tasks:
        parts.append(f"タスクID #{t['id']}: {t['content']}（予定: {t['scheduled_at']}）")
    for r in reminders:
        parts.append(f"リマインダーID #{r['id']}: {r['content']}（予定: {r['scheduled_at']}）")
    parts.append("ユーザーに適切な通知を行い、タスクを完了状態にしてください。")
    return "\n".join(parts)


def _fast_heartbeat_loop(lock: threading.Lock, stop: threading.Event) -> None:
    """該当タスク・リマインダーがあれば擬似メッセージを ReAct に投入。"""
    while not stop.is_set():
        try:
            if not has_due_work():
                stop.wait(HEARTBEAT_INTERVAL_SEC)
                continue
            if not lock.acquire(blocking=False):
                stop.wait(HEARTBEAT_INTERVAL_SEC)
                continue
            try:
                now = datetime.now()
                tasks = get_due_tasks(at=now)
                reminders = get_due_reminders(at=now)
                if not tasks and not reminders:
                    continue
                pseudo = _build_fast_heartbeat_message(tasks, reminders)
                history = load_active_history()
                run_agent_loop_with_tools(pseudo, history, on_turn=None)
                mark_tasks_completed([t["id"] for t in tasks])
                mark_reminders_completed([r["id"] for r in reminders])
                logger.info("fast heartbeat: processed {} tasks, {} reminders", len(tasks), len(reminders))
            except Exception as e:
                logger.warning("fast heartbeat run failed: {}", e)
            finally:
                lock.release()
        except Exception as e:
            logger.warning("fast heartbeat loop error: {}", e)
        stop.wait(HEARTBEAT_INTERVAL_SEC)


def _handle_message(
    user_input: str,
    conversation_history: list[dict[str, str]],
    agent_lock: threading.Lock | None,
    max_chars: int,
    on_turn: Any,
    images: list[str] | None = None,
) -> str:
    if agent_lock is not None and not agent_lock.acquire(blocking=False):
        return "バックグラウンド処理中です。しばらくお待ちください。"
    if images and not VISION_ENABLED:
        return "画像処理は無効です。.env で OLLAMA_VISION_ENABLED=true にしてください（メインモデルが視覚対応の場合）。"
    try:
        response = run_agent_loop_with_tools(
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
        while should_compress(conversation_history, max_chars):
            compress_once(conversation_history, max_chars)
        return response
    finally:
        if agent_lock is not None:
            agent_lock.release()


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
            try:
                user_input = input("Ancilla CLI > ")
            except (EOFError, KeyboardInterrupt):
                print("\n終了します。")
                break

            if is_exit_command(user_input):
                print("終了コマンドが入力されたため、REPL を終了します。")
                break

            response = _handle_message(user_input, history, agent_lock, MAX_HISTORY_CHARS, on_turn)
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
    agent_lock = threading.Lock()
    stop = threading.Event()
    conversation_history = load_active_history()
    api_port = int(os.getenv("ANCILLA_API_PORT", "8765"))

    def chat_handler(msg: str, imgs: list[str] | None = None) -> str:
        return _handle_message(
            msg, conversation_history, agent_lock, MAX_HISTORY_CHARS, None, images=imgs
        )

    api_thread = threading.Thread(
        target=lambda: run_server("127.0.0.1", api_port, chat_handler),
        daemon=True,
        name="api",
    )
    api_thread.start()
    logger.info("API http://127.0.0.1:{}/chat", api_port)

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
    slow_thread.start()
    fast_thread.start()
    try:
        _run_repl(args, agent_lock=agent_lock, conversation_history=conversation_history)
    finally:
        save_active_history(conversation_history)
        stop.set()
        slow_thread.join(timeout=HEARTBEAT_INTERVAL_SEC + 5)
        fast_thread.join(timeout=HEARTBEAT_INTERVAL_SEC + 5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ancilla-Bot CLI")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG レベルでログを出力")
    parser.add_argument("--log-file", metavar="PATH", help="ログをファイルにも出力（例: data/logs/ancilla.log）")
    parser.add_argument("-r", "--show-reasoning", action="store_true", help="thought とツール呼び出しを薄く表示")
    subparsers = parser.add_subparsers(dest="command", help="サブコマンド")

    subparsers.add_parser("run", help="常駐モード（REPL + API + Heartbeat）。終了は exit 等。")
    subparsers.add_parser("client", help="API に接続する REPL クライアント。先に ancilla run を起動すること。")
    subparsers.add_parser("discord", help="Discord Bot。先に ancilla run を起動し、DISCORD_BOT_TOKEN を設定すること。")

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
    if args.command == "batch":
        if args.batch_command == "summarize":
            _run_batch_summarize()
        return

    _run_repl(args, agent_lock=None)


if __name__ == "__main__":
    main()

