from __future__ import annotations

import os

import discord
import httpx

MAX_RESPONSE_CHARS = 1900
API_HOST = os.getenv("ANCILLA_API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("ANCILLA_API_PORT", "8765"))


def _get_api_url() -> str:
    return f"http://{API_HOST}:{API_PORT}/chat"


async def _call_daemon(message: str) -> str:
    url = _get_api_url()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json={"message": message})
            resp.raise_for_status()
            data = resp.json()
            return (data.get("response") or "")[:MAX_RESPONSE_CHARS]
    except httpx.ConnectError:
        return "デーモンに接続できません。ancilla run が起動しているか確認してください。"
    except Exception as e:
        return f"エラー: {e}"


def run_bot() -> None:
    intents = discord.Intents.default()
    intents.message_content = True

    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"Discord にログイン: {client.user}")

    @client.event
    async def on_message(message: discord.Message):
        if message.author == client.user:
            return
        text = message.content.strip()
        if not text:
            return
        is_dm = message.guild is None
        is_mention = client.user and client.user.mentioned_in(message)
        if not (is_dm or is_mention):
            return
        if is_mention and client.user:
            for m in (f"<@{client.user.id}>", f"<@!{client.user.id}>"):
                text = text.replace(m, "")
            text = text.strip()
            if not text:
                return
        async with message.channel.typing():
            response = await _call_daemon(text)
        if len(response) > MAX_RESPONSE_CHARS:
            response = response[:MAX_RESPONSE_CHARS] + "..."
        await message.reply(response, mention_author=False)

    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN を設定してください。")
    client.run(token)


def main() -> None:
    run_bot()
