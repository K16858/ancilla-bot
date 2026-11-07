import asyncio
from types import SimpleNamespace

import pytest

from ancilla_bot import discord_bot, slack_bot


class _FakeDiscordClient:
    handlers: dict = {}
    user = SimpleNamespace(id=1, mentioned_in=lambda m: False)

    def __init__(self, *a, **k):
        pass

    def event(self, fn):
        self.handlers[fn.__name__] = fn
        return fn

    def run(self, token):
        pass


def _start_discord(monkeypatch, owner):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "t")
    if owner is None:
        monkeypatch.delenv("DISCORD_OWNER_ID", raising=False)
    else:
        monkeypatch.setenv("DISCORD_OWNER_ID", owner)
    monkeypatch.setattr(discord_bot.discord, "Client", _FakeDiscordClient)
    monkeypatch.setattr(discord_bot.discord.app_commands, "CommandTree", lambda c: SimpleNamespace(command=lambda **k: lambda f: f))
    discord_bot.run_bot()
    return _FakeDiscordClient.handlers["on_message"]


def _dm(author_id, text="hi"):
    replies = []

    async def reply(r, **k):
        replies.append(r)

    msg = SimpleNamespace(
        author=SimpleNamespace(id=author_id), content=text, guild=None, attachments=[],
        channel=None, reply=reply,
    )
    return msg, replies


@pytest.mark.parametrize("author, expect_reply", [(42, True), (43, False)])
def test_discord_only_owner(monkeypatch, author, expect_reply):
    on_message = _start_discord(monkeypatch, "42")

    async def fake_call(*a, **k):
        return "ok"

    monkeypatch.setattr(discord_bot, "_call_daemon_with_typing", fake_call)
    msg, replies = _dm(author)
    asyncio.run(on_message(msg))
    assert bool(replies) is expect_reply


def test_discord_refuses_without_owner(monkeypatch):
    with pytest.raises(SystemExit):
        _start_discord(monkeypatch, None)


class _FakeSlackApp:
    handlers: dict = {}

    def __init__(self, *a, **k):
        pass

    def event(self, name):
        def deco(fn):
            self.handlers[name] = fn
            return fn

        return deco


def _start_slack(monkeypatch, owner):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "b")
    monkeypatch.setenv("SLACK_APP_TOKEN", "a")
    monkeypatch.delenv("SLACK_NOTIFY_CHANNEL_ID", raising=False)
    if owner is None:
        monkeypatch.delenv("SLACK_OWNER_ID", raising=False)
    else:
        monkeypatch.setenv("SLACK_OWNER_ID", owner)
    monkeypatch.setattr(slack_bot, "App", _FakeSlackApp)
    monkeypatch.setattr(slack_bot, "SocketModeHandler", lambda *a: SimpleNamespace(start=lambda: None))
    slack_bot.run_bot()
    return _FakeSlackApp.handlers["message"]


@pytest.mark.parametrize("user, expect_reply", [("U1", True), ("U2", False)])
def test_slack_only_owner(monkeypatch, user, expect_reply):
    handle_dm = _start_slack(monkeypatch, "U1")
    monkeypatch.setattr(slack_bot, "_call_daemon", lambda *a, **k: "ok")
    said = []
    body = {"event": {"user": user, "text": "hi", "channel_type": "im", "ts": "1"}}
    handle_dm(body, lambda **k: said.append(k))
    assert bool(said) is expect_reply


def test_slack_refuses_without_owner(monkeypatch):
    with pytest.raises(SystemExit):
        _start_slack(monkeypatch, None)
