"""Slack Bot integration for Ancilla-Bot.

必要な環境変数:
  SLACK_BOT_TOKEN  ... xoxb-... (Bot User OAuth Token)
  SLACK_APP_TOKEN  ... xapp-... (App-Level Token, connections:write スコープ, Socket Mode 用)

任意:
  SLACK_NOTIFY_CHANNEL_ID ... 通知送信先チャンネル ID
"""

from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from slack_bolt import App

from ancilla_bot.notifications.pending_take import take_pending_jsonl_lines
from slack_bolt.adapter.socket_mode import SocketModeHandler

MAX_RESPONSE_CHARS = 3000
NOTIFY_POLL_INTERVAL = 30
NOTIFY_MAX_MESSAGE_CHARS = 3000
API_HOST = os.getenv("ANCILLA_API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("ANCILLA_API_PORT", "8765"))
NOTIFICATIONS_DIR = Path(os.getenv("ANCILLA_NOTIFICATIONS_DIR", "data/notifications"))
PENDING_FILE = "pending.jsonl"


def _get_api_url() -> str:
    return f"http://{API_HOST}:{API_PORT}/chat"


def _call_daemon(message: str, images: list[str] | None = None) -> str:
    url = _get_api_url()
    payload: dict[str, Any] = {"message": message or "(画像のみ)"}
    if images:
        payload["images"] = images[:4]
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return (data.get("response") or "")[:MAX_RESPONSE_CHARS]
    except httpx.ConnectError:
        return "デーモンに接続できません。ancilla run が起動しているか確認してください。"
    except httpx.TimeoutException:
        return "エラー: 応答がタイムアウトしました。処理に時間がかかっている可能性があります。"
    except Exception as e:
        err_msg = str(e).strip() if e else ""
        return f"エラー: {err_msg}" if err_msg else "エラー: 応答の取得に失敗しました。"


def _download_images(files: list[dict[str, Any]], bot_token: str) -> list[str]:
    """Slack のファイルオブジェクトから画像を base64 でダウンロードする。"""
    out: list[str] = []
    headers = {"Authorization": f"Bearer {bot_token}"}
    with httpx.Client(timeout=30.0) as client:
        for f in files:
            mimetype = f.get("mimetype", "")
            if not mimetype.startswith("image/"):
                continue
            url = f.get("url_private_download") or f.get("url_private", "")
            if not url:
                continue
            try:
                r = client.get(url, headers=headers)
                r.raise_for_status()
                out.append(base64.b64encode(r.content).decode("ascii"))
            except Exception:
                continue
            if len(out) >= 4:
                break
    return out


def _pending_path() -> Path:
    return NOTIFICATIONS_DIR / PENDING_FILE


def _notify_loop(app: App, channel_id: str) -> None:
    """pending.jsonl をポーリングして Slack チャンネルに通知を送る。"""
    path = _pending_path()
    while True:
        time.sleep(NOTIFY_POLL_INTERVAL)
        lines = take_pending_jsonl_lines(path)
        if not lines:
            continue
        for line in lines:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = (rec.get("message") or "").strip()
            if not msg:
                continue
            title = (rec.get("title") or "").strip()
            source = (rec.get("source") or "").strip()
            prefix = ""
            if source == "system":
                prefix = "[システム] "
            elif source == "report":
                prefix = "[報告] "
            elif source == "email":
                prefix = "[メール] "
            # Slack は *bold*（Discord は **bold**）
            if title:
                msg = f"{prefix}*[{title}]*\n{msg}"
            elif prefix:
                msg = prefix + msg
            if len(msg) > NOTIFY_MAX_MESSAGE_CHARS:
                msg = msg[:NOTIFY_MAX_MESSAGE_CHARS] + "..."
            try:
                app.client.chat_postMessage(channel=channel_id, text=msg)
            except Exception:
                break


def run_bot() -> None:
    bot_token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    app_token = os.getenv("SLACK_APP_TOKEN", "").strip()
    if not bot_token:
        raise SystemExit("SLACK_BOT_TOKEN を設定してください。")
    if not app_token:
        raise SystemExit(
            "SLACK_APP_TOKEN を設定してください（xapp-... ）。"
            " Slack アプリの Settings → Socket Mode → Enable Socket Mode を ON にして"
            " App-Level Token (connections:write) を発行してください。"
        )

    app = App(token=bot_token)

    def _handle_event(body: dict[str, Any], say: Any, is_mention: bool) -> None:
        event = body.get("event", {})
        if event.get("bot_id"):
            return  # 自分自身のメッセージは無視
        text = (event.get("text") or "").strip()
        if is_mention:
            text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
        files = event.get("files", [])
        images = _download_images(files, bot_token) if files else []
        if not text and not images:
            return
        response = _call_daemon(text, images if images else None)
        if len(response) > MAX_RESPONSE_CHARS:
            response = response[:MAX_RESPONSE_CHARS] + "..."
        thread_ts = event.get("thread_ts") or event.get("ts")
        say(text=response, thread_ts=thread_ts)

    @app.event("app_mention")
    def handle_mention(body: dict[str, Any], say: Any) -> None:
        _handle_event(body, say, is_mention=True)

    @app.event("message")
    def handle_dm(body: dict[str, Any], say: Any) -> None:
        event = body.get("event", {})
        # DM チャンネル（channel_type == "im"）のみ処理。チャンネル投稿は app_mention で拾う
        if event.get("channel_type") != "im":
            return
        _handle_event(body, say, is_mention=False)

    notify_channel = os.getenv("SLACK_NOTIFY_CHANNEL_ID", "").strip()
    if notify_channel:
        t = threading.Thread(
            target=_notify_loop,
            args=(app, notify_channel),
            daemon=True,
            name="slack_notify",
        )
        t.start()

    handler = SocketModeHandler(app, app_token)
    print("Slack Socket Mode で起動しています...")
    handler.start()


def main() -> None:
    run_bot()
