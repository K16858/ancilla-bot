from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path

import discord
import httpx

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


async def _call_daemon(message: str, images: list[str] | None = None) -> str:
    url = _get_api_url()
    payload: dict = {"message": message or "(画像のみ)"}
    if images:
        payload["images"] = images[:4]
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return (data.get("response") or "")[:MAX_RESPONSE_CHARS]
    except httpx.ConnectError:
        return "デーモンに接続できません。ancilla run が起動しているか確認してください。"
    except Exception as e:
        return f"エラー: {e}"


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
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if not lines:
            continue
        sent = 0
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
                sent += 1
            except (discord.Forbidden, discord.HTTPException):
                break
        if sent > 0:
            try:
                path.write_text("", encoding="utf-8")
            except OSError:
                pass


def run_bot() -> None:
    intents = discord.Intents.default()
    intents.message_content = True

    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"Discord にログイン: {client.user}")
        if os.getenv("DISCORD_NOTIFY_CHANNEL_ID") or os.getenv("DISCORD_NOTIFY_USER_ID"):
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
        async with message.channel.typing():
            response = await _call_daemon(text, images if images else None)
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
