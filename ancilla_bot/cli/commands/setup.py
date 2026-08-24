"""ancilla setup — 対話的な .env 編集。"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import shlex
import shutil
import subprocess
import sys
from typing import Callable

from ancilla_bot.cli import envfile, health, process, ux
from ancilla_bot.cli.paths import get_root

_ALIASES = {
    "web-search": "search",
    "websearch": "search",
    "web": "search",
    "notifications": "notify",
    "adapters": "notify",
}

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

TOPIC_HELP = [
    "ancilla setup provider",
    "ancilla setup embeddings",
    "ancilla setup search",
    "ancilla setup keys",
    "ancilla setup notify",
    "ancilla setup api",
    "ancilla setup show [--all]",
    "ancilla setup set KEY=VALUE",
    "ancilla setup edit",
]


def cmd_setup(args: argparse.Namespace) -> int:
    envfile.ensure_env_file()
    topic = (getattr(args, "topic", None) or "").strip().lower()
    topic = _ALIASES.get(topic, topic)
    rest = list(getattr(args, "args", None) or [])

    if topic in ("", "menu"):
        if not sys.stdin.isatty():
            return ux.fail("Non-interactive setup requires a topic.", next_cmds=TOPIC_HELP)
        return _run_interactive(_menu)
    if topic == "set":
        return _setup_set(rest)
    if topic == "edit":
        return _setup_edit()
    if topic == "show":
        return _setup_show(show_all=bool(getattr(args, "all", False)))

    interactive = {
        "provider": _setup_provider,
        "embeddings": _setup_embeddings,
        "search": _setup_web_search,
        "keys": _setup_keys,
        "notify": _setup_notify,
        "api": _setup_api,
    }
    handler = interactive.get(topic)
    if handler is None:
        return ux.fail(f"Unknown setup topic: {topic}", next_cmds=TOPIC_HELP)
    if not sys.stdin.isatty():
        return ux.fail(
            f"setup {topic} is interactive.",
            cause="Use setup set for non-interactive changes.",
            next_cmds=["ancilla setup set KEY=VALUE", "ancilla setup show --all"],
        )
    return _run_interactive(handler)


def _run_interactive(fn: Callable[[], int]) -> int:
    """入力が尽きた/中断された場合にトレースバックを出さない。"""
    try:
        return fn()
    except (EOFError, KeyboardInterrupt):
        print()
        return ux.fail("Aborted.", next_cmds=["ancilla setup set KEY=VALUE"])


def _menu() -> int:
    while True:
        print()
        print("Ancilla Setup")
        print()
        print("[1] LLM Provider")
        print("[2] Embeddings")
        print("[3] Web Search")
        print("[4] API Keys / Tokens")
        print("[5] Notification Targets")
        print("[6] Core Connection")
        print("[7] Show Configuration")
        print("[8] Edit .env in $EDITOR")
        print("[0] Exit")
        choice = input("> ").strip()
        if choice == "0":
            return 0
        if choice == "1":
            _setup_provider()
        elif choice == "2":
            _setup_embeddings()
        elif choice == "3":
            _setup_web_search()
        elif choice == "4":
            _setup_keys()
        elif choice == "5":
            _setup_notify()
        elif choice == "6":
            _setup_api()
        elif choice == "7":
            _setup_show()
            input("\nPress Enter to continue...")
        elif choice == "8":
            _setup_edit()
        else:
            print("Invalid choice.")


def _prompt(
    label: str,
    current: str | None,
    *,
    secret: bool = False,
    fallback: str | None = None,
) -> str | None:
    """Enter で現状維持。戻り値 None=変更なし。

    未設定のキーには fallback（コード側の既定値）を参考として示すだけで、
    Enter しても .env には書かない。
    """
    if current:
        shown = envfile.mask_secret(current) if secret else current
    elif fallback:
        shown = f"unset -> {fallback}"
    else:
        shown = "empty"
    prompt = f"{label} [{shown}]: "
    if secret:
        # Windows でも動くよう getpass、失敗時は通常 input
        try:
            raw = getpass.getpass(prompt)
        except Exception:
            raw = input(prompt)
    else:
        raw = input(prompt)
    if raw == "":
        return None
    return raw


def _apply(updates: dict[str, str | None], *, before: dict[str, str]) -> int:
    cleaned = {k: v for k, v in updates.items() if v is not None}
    # None markers for clear are kept if explicitly in updates with None - we only pass non-None from prompts
    if not cleaned:
        print("No changes.")
        return 0
    changed = envfile.set_values(cleaned)
    if not changed:
        print("No changes.")
        return 0
    print()
    print("Configuration updated.")
    print()
    print("Changed:")
    for key in changed:
        old = before.get(key, "")
        new = cleaned.get(key, "")
        if envfile.is_secret_key(key):
            old_s = envfile.mask_secret(old) if old else "(empty)"
            new_s = envfile.mask_secret(new) if new else "(empty)"
        else:
            old_s = old or "(empty)"
            new_s = new or "(empty)"
        print(f"  {key}: {old_s} -> {new_s}")
    if process.is_running("core"):
        print()
        print("Core is currently running.")
        print()
        print("Restart to apply:")
        print("  ancilla restart core")
    return 0


def _setup_provider() -> int:
    before = envfile.read_env_map()
    provider = before.get("LLM_PROVIDER") or "ollama"
    print(f"Current LLM_PROVIDER: {provider}")
    print("Choose: [1] ollama  [2] openai  [Enter] keep")
    choice = input("> ").strip()
    updates: dict[str, str | None] = {}
    if choice == "1":
        updates["LLM_PROVIDER"] = "ollama"
        provider = "ollama"
    elif choice == "2":
        updates["LLM_PROVIDER"] = "openai"
        provider = "openai"

    if provider == "ollama":
        base = before.get("OLLAMA_BASE_URL") or "http://localhost:11434"
        v = _prompt("OLLAMA_BASE_URL", before.get("OLLAMA_BASE_URL"), fallback=base)
        if v is not None:
            updates["OLLAMA_BASE_URL"] = v
            base = v
        models = health.ollama_models(base)
        if models is None:
            print(f"  ! Cannot reach Ollama at {base}")
        elif not models:
            print("  ! Ollama has no models pulled (ollama pull <model>)")
        else:
            print("  Available models (enter a number or a name):")
            for i, name in enumerate(models, 1):
                print(f"    [{i}] {name}")
        v = _prompt("OLLAMA_MODEL", before.get("OLLAMA_MODEL"))
        if v is not None:
            if models and v.isdigit() and 1 <= int(v) <= len(models):
                v = models[int(v) - 1]
            updates["OLLAMA_MODEL"] = v
        model = updates.get("OLLAMA_MODEL") or before.get("OLLAMA_MODEL") or ""
        if not model:
            print("  ! OLLAMA_MODEL is required for LLM_PROVIDER=ollama")
        elif models and not health.ollama_has_model(models, model):
            print(f"  ! {model} is not pulled on {base}")
    else:
        v = _prompt("LLM_BASE_URL", before.get("LLM_BASE_URL"))
        if v is not None:
            updates["LLM_BASE_URL"] = v
        v = _prompt("LLM_MODEL", before.get("LLM_MODEL"))
        if v is not None:
            updates["LLM_MODEL"] = v
        if not (updates.get("OPENAI_API_KEY") or before.get("OPENAI_API_KEY")):
            print("  ! OPENAI_API_KEY is not set (ancilla setup keys)")
    return _apply(updates, before=before)


def _setup_embeddings() -> int:
    before = envfile.read_env_map()
    updates: dict[str, str | None] = {}
    v = _prompt("LLM_EMBED_PROVIDER", before.get("LLM_EMBED_PROVIDER"), fallback="same as LLM_PROVIDER")
    if v is not None:
        updates["LLM_EMBED_PROVIDER"] = v
    v = _prompt("OLLAMA_EMBED_MODEL", before.get("OLLAMA_EMBED_MODEL"), fallback="nomic-embed-text")
    if v is not None:
        updates["OLLAMA_EMBED_MODEL"] = v
    v = _prompt("LLM_EMBED_MODEL", before.get("LLM_EMBED_MODEL"))
    if v is not None:
        updates["LLM_EMBED_MODEL"] = v
    return _apply(updates, before=before)


def _setup_web_search() -> int:
    before = envfile.read_env_map()
    updates: dict[str, str | None] = {}
    v = _prompt("WEB_SEARCH_PROVIDER", before.get("WEB_SEARCH_PROVIDER"), fallback="searxng")
    if v is not None:
        updates["WEB_SEARCH_PROVIDER"] = v
    v = _prompt("SEARXNG_URL", before.get("SEARXNG_URL"), fallback="http://localhost:8080")
    if v is not None:
        updates["SEARXNG_URL"] = v
    v = _prompt("SEARXNG_USER", before.get("SEARXNG_USER"))
    if v is not None:
        updates["SEARXNG_USER"] = v
    v = _prompt("SEARXNG_PASSWORD", before.get("SEARXNG_PASSWORD"), secret=True)
    if v is not None:
        updates["SEARXNG_PASSWORD"] = v
    v = _prompt("BRAVE_API_KEY", before.get("BRAVE_API_KEY"), secret=True)
    if v is not None:
        updates["BRAVE_API_KEY"] = v
    v = _prompt("TAVILY_API_KEY", before.get("TAVILY_API_KEY"), secret=True)
    if v is not None:
        updates["TAVILY_API_KEY"] = v
    return _apply(updates, before=before)


def _setup_keys() -> int:
    before = envfile.read_env_map()
    updates: dict[str, str | None] = {}
    keys = [
        "OPENAI_API_KEY",
        "BRAVE_API_KEY",
        "TAVILY_API_KEY",
        "SEARXNG_TOKEN",
        "DISCORD_BOT_TOKEN",
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
    ]
    print("Secrets: Enter=keep, or type new value.")
    for key in keys:
        cur = before.get(key)
        print()
        print(f"{key}: {envfile.mask_secret(cur) if cur else '(empty)'}")
        print("[K] Keep  [R] Replace  [C] Clear  [Q] Done")
        action = input("> ").strip().upper() or "K"
        if action == "Q":
            break
        if action == "K":
            continue
        if action == "C":
            updates[key] = ""
            continue
        if action == "R":
            v = _prompt(key, cur, secret=True)
            if v is not None:
                updates[key] = v
    return _apply(updates, before=before)


def _setup_notify() -> int:
    """通知の届け先。トークンだけ設定しても届かないので分けてある。"""
    before = envfile.read_env_map()
    updates: dict[str, str | None] = {}
    if not before.get("DISCORD_BOT_TOKEN"):
        print("! DISCORD_BOT_TOKEN is not set (ancilla setup keys)")
    v = _prompt("DISCORD_NOTIFY_CHANNEL_ID", before.get("DISCORD_NOTIFY_CHANNEL_ID"))
    if v is not None:
        updates["DISCORD_NOTIFY_CHANNEL_ID"] = v
    v = _prompt("DISCORD_NOTIFY_USER_ID", before.get("DISCORD_NOTIFY_USER_ID"))
    if v is not None:
        updates["DISCORD_NOTIFY_USER_ID"] = v
    if not (before.get("SLACK_BOT_TOKEN") and before.get("SLACK_APP_TOKEN")):
        print("! SLACK_BOT_TOKEN / SLACK_APP_TOKEN are not set (ancilla setup keys)")
    v = _prompt("SLACK_NOTIFY_CHANNEL_ID", before.get("SLACK_NOTIFY_CHANNEL_ID"))
    if v is not None:
        updates["SLACK_NOTIFY_CHANNEL_ID"] = v
    return _apply(updates, before=before)


def _setup_api() -> int:
    before = envfile.read_env_map()
    updates: dict[str, str | None] = {}
    v = _prompt("ANCILLA_CORE_URL", before.get("ANCILLA_CORE_URL"), fallback="http://127.0.0.1:8765")
    if v is not None:
        updates["ANCILLA_CORE_URL"] = v
    v = _prompt("ANCILLA_API_BIND_HOST", before.get("ANCILLA_API_BIND_HOST"), fallback="127.0.0.1")
    if v is not None:
        updates["ANCILLA_API_BIND_HOST"] = v
    v = _prompt("ANCILLA_API_PORT", before.get("ANCILLA_API_PORT"), fallback="8765")
    if v is not None:
        updates["ANCILLA_API_PORT"] = v
    v = _prompt("ANCILLA_WS_PORT", before.get("ANCILLA_WS_PORT"), fallback="8766")
    if v is not None:
        updates["ANCILLA_WS_PORT"] = v
    v = _prompt("ANCILLA_INSTANCE_NAME", before.get("ANCILLA_INSTANCE_NAME"))
    if v is not None:
        updates["ANCILLA_INSTANCE_NAME"] = v
    return _apply(updates, before=before)


def _setup_set(pairs: list[str]) -> int:
    """非対話向け。ウィザードに無いキーもここから触れる。"""
    if not pairs:
        return ux.fail(
            "Usage: ancilla setup set KEY=VALUE [KEY=VALUE ...]",
            cause="KEY= (empty value) clears the key.",
            next_cmds=["ancilla setup show --all"],
        )
    before = envfile.read_env_map()
    updates: dict[str, str | None] = {}
    for item in pairs:
        key, sep, value = item.partition("=")
        key = key.strip()
        if not sep or not _KEY_RE.match(key):
            return ux.fail(
                f"Invalid assignment: {item}",
                next_cmds=["ancilla setup set KEY=VALUE"],
            )
        updates[key] = value
    return _apply(updates, before=before)


def _editor_command() -> list[str] | None:
    raw = (os.getenv("VISUAL") or os.getenv("EDITOR") or "").strip()
    if raw:
        return shlex.split(raw, posix=os.name != "nt")
    for candidate in ("nano", "vim", "vi", "notepad"):
        if shutil.which(candidate):
            return [candidate]
    return None


def _setup_edit() -> int:
    path = envfile.ensure_env_file()
    cmd = _editor_command()
    if not cmd:
        return ux.fail(
            "No editor found.",
            cause="Set $EDITOR or $VISUAL.",
            next_cmds=["ancilla setup show --all", "ancilla setup set KEY=VALUE"],
        )
    try:
        subprocess.call([*cmd, str(path)])
    except OSError as exc:
        return ux.fail(f"Failed to launch editor: {' '.join(cmd)}", cause=str(exc))
    print(f"Edited {path}")
    if process.is_running("core"):
        print()
        print("Restart to apply:")
        print("  ancilla restart core")
    return 0


_SHOW_KEYS = [
    "LLM_PROVIDER",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_EMBED_PROVIDER",
    "OLLAMA_EMBED_MODEL",
    "WEB_SEARCH_PROVIDER",
    "SEARXNG_URL",
    "SEARXNG_USER",
    "ANCILLA_API_BIND_HOST",
    "ANCILLA_API_PORT",
    "ANCILLA_WS_PORT",
    "ANCILLA_CORE_URL",
    "ANCILLA_INSTANCE_NAME",
    "ANCILLA_SANDBOX",
    "ANCILLA_BASH_ALLOWLIST",
    "OPENAI_API_KEY",
    "BRAVE_API_KEY",
    "TAVILY_API_KEY",
    "SEARXNG_PASSWORD",
    "DISCORD_BOT_TOKEN",
    "DISCORD_NOTIFY_CHANNEL_ID",
    "DISCORD_NOTIFY_USER_ID",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "SLACK_NOTIFY_CHANNEL_ID",
]


def _setup_show(*, show_all: bool = False) -> int:
    data = envfile.read_env_map()
    keys = list(_SHOW_KEYS)
    if show_all:
        keys += [k for k in _example_keys() if k not in keys]
        keys += [k for k in data if k not in keys]
    print(f"Root: {get_root()}")
    print()
    for key in keys:
        src = envfile.value_source(key)
        val = envfile.get_value(key) or data.get(key) or ""
        if envfile.is_secret_key(key):
            shown = envfile.mask_secret(val) if val else "(empty)"
        else:
            shown = val or "(empty)"
        print(f"{key:<30} {shown:<40} {src}")
    if not show_all:
        print()
        print("ancilla setup show --all  for every key in .env.example")
    return 0


def _example_keys() -> list[str]:
    """.env.example の登場順キー（コメントアウトされた雛形を含む）。"""
    path = envfile.example_path()
    if not path.is_file():
        return []
    keys: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*#?\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m and m.group(1) not in keys:
            keys.append(m.group(1))
    return keys
