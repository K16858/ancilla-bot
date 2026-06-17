from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
from pathlib import Path

import discord
import httpx

from ancilla_bot.notifications.pending_take import requeue_pending_jsonl_lines, take_pending_jsonl_lines

MAX_RESPONSE_CHARS = 1900
NOTIFY_POLL_INTERVAL = 30
NOTIFY_MAX_MESSAGE_CHARS = 1900
API_HOST = os.getenv("ANCILLA_API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("ANCILLA_API_PORT", "8765"))
NOTIFICATIONS_DIR = Path(
    os.getenv("ANCILLA_NOTIFICATIONS_DIR", "data/notifications")
)
PENDING_FILE = "pending.jsonl"


def _get_api_url() -> str:
    return f"http://{API_HOST}:{API_PORT}/chat"


def _get_cancel_url() -> str:
    return f"http://{API_HOST}:{API_PORT}/cancel"


async def _request_cancel() -> bool:
    url = _get_cancel_url()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={})
            resp.raise_for_status()
            return True
    except Exception:
        return False


async def _call_daemon(message: str, images: list[str] | None = None) -> str:
    url = _get_api_url()
    payload: dict = {"message": message or "(画像のみ)"}
    if images:
        payload["images"] = images[:4]
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
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


async def _download_images(attachments: list[discord.Attachment]) -> list[str]:
    out: list[str] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for att in attachments:
            if not att.content_type or not att.content_type.startswith("image/"):
                continue
            try:
                r = await client.get(att.url)
                r.raise_for_status()
                out.append(base64.b64encode(r.content).decode("ascii"))
            except Exception:
                continue
    return out[:4]


async def _call_daemon_with_typing(
    channel: discord.abc.Messageable,
    message: str,
    images: list[str] | None = None,
) -> str:
    """HTTP 待機中も typing インジケーターを維持する。"""
    stop = asyncio.Event()

    async def _typing_loop() -> None:
        while not stop.is_set():
            async with channel.typing():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=8.0)
                except asyncio.TimeoutError:
                    continue

    typing_task = asyncio.create_task(_typing_loop())
    try:
        return await _call_daemon(message, images)
    finally:
        stop.set()
        typing_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await typing_task


def _pending_path() -> Path:
    return NOTIFICATIONS_DIR / PENDING_FILE


async def _notify_loop(client: discord.Client) -> None:
    """
    pending.jsonl をポーリングし、通知を送信してからファイルを空にする。
    届け先は DISCORD_NOTIFY_CHANNEL_ID または DISCORD_NOTIFY_USER_ID のどちらか。
    """
    channel_id = os.getenv("DISCORD_NOTIFY_CHANNEL_ID", "").strip()
    user_id = os.getenv("DISCORD_NOTIFY_USER_ID", "").strip()
    if not channel_id and not user_id:
        return
    destination = None
    if channel_id:
        try:
            ch = await client.fetch_channel(int(channel_id))
            destination = ("channel", ch)
        except (ValueError, discord.NotFound, discord.Forbidden):
            pass
    if destination is None and user_id:
        try:
            user = await client.fetch_user(int(user_id))
            destination = ("user", user)
        except (ValueError, discord.NotFound):
            pass
    if destination is None:
        return

    path = _pending_path()
    while True:
        await asyncio.sleep(NOTIFY_POLL_INTERVAL)
        lines = take_pending_jsonl_lines(path)
        if not lines:
            continue
        for i, line in enumerate(lines):
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
            if title:
                msg = f"{prefix}**[{title}]**\n{msg}"
            elif prefix:
                msg = prefix + msg
            if len(msg) > NOTIFY_MAX_MESSAGE_CHARS:
                msg = msg[:NOTIFY_MAX_MESSAGE_CHARS] + "..."
            try:
                if destination[0] == "channel" and destination[1]:
                    await destination[1].send(msg)
                elif destination[0] == "user" and destination[1]:
                    await destination[1].send(msg)
            except (discord.Forbidden, discord.HTTPException):
                requeue_pending_jsonl_lines(lines[i:], path)
                break


def run_bot() -> None:
    intents = discord.Intents.default()
    intents.message_content = True

    client = discord.Client(intents=intents)
    tree = discord.app_commands.CommandTree(client)

    @tree.command(name="stop", description="進行中のエージェント処理をキャンセルする")
    async def stop_command(interaction: discord.Interaction) -> None:
        ok = await _request_cancel()
        if ok:
            await interaction.response.send_message(
                "キャンセルを要求しました。",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "キャンセルに失敗しました。デーモンが起動しているか確認してください。",
                ephemeral=True,
            )

    @client.event
    async def on_ready():
        print(f"Discord にログイン: {client.user}")
        await tree.sync()
        if os.getenv("DISCORD_NOTIFY_CHANNEL_ID") or os.getenv("DISCORD_NOTIFY_USER_ID"):
            if getattr(client, "_ancilla_notify_loop_started", False):
                return
            setattr(client, "_ancilla_notify_loop_started", True)
            asyncio.create_task(_notify_loop(client))

    @client.event
    async def on_message(message: discord.Message):
        if message.author == client.user:
            return
        text = message.content.strip() if message.content else ""
        is_dm = message.guild is None
        is_mention = client.user and client.user.mentioned_in(message)
        if not (is_dm or is_mention):
            return
        if is_mention and client.user:
            for m in (f"<@{client.user.id}>", f"<@!{client.user.id}>"):
                text = text.replace(m, "")
            text = text.strip()
        images = await _download_images(message.attachments)
        if not text and not images:
            return
        response = await _call_daemon_with_typing(
            message.channel, text, images if images else None
        )
        if len(response) > MAX_RESPONSE_CHARS:
            response = response[:MAX_RESPONSE_CHARS] + "..."
        await message.reply(response, mention_author=False)

    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN を設定してください。.env に Bot トークンを書いてください。")
    try:
        client.run(token)
    except discord.LoginFailure:
        raise SystemExit(
            "Discord ログインに失敗しました（401）。DISCORD_BOT_TOKEN が正しいか確認してください。"
            " Discord 開発者ポータル → アプリ → Bot → Reset Token で再発行できます。"
        )


def main() -> None:
    run_bot()
