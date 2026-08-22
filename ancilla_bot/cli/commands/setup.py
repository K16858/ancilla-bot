"""ancilla setup — 対話的な .env 編集。"""

from __future__ import annotations

import argparse
import getpass
import sys

from ancilla_bot.cli import envfile, process, ux
from ancilla_bot.cli.paths import get_root


def cmd_setup(args: argparse.Namespace) -> int:
    envfile.ensure_env_file()
    topic = (getattr(args, "topic", None) or "").strip().lower()
    if topic in ("", "menu"):
        if not sys.stdin.isatty():
            return ux.fail(
                "Non-interactive setup requires a topic.",
                next_cmds=[
                    "ancilla setup provider",
                    "ancilla setup keys",
                    "ancilla setup api",
                    "ancilla setup show",
                ],
            )
        return _menu()
    if topic == "provider":
        return _setup_provider()
    if topic == "keys":
        return _setup_keys()
    if topic == "api":
        return _setup_api()
    if topic == "show":
        return _setup_show()
    return ux.fail(
        f"Unknown setup topic: {topic}",
        next_cmds=["ancilla setup", "ancilla setup show"],
    )


def _menu() -> int:
    while True:
        print()
        print("Ancilla Setup")
        print()
        print("[1] LLM Provider")
        print("[2] Embeddings")
        print("[3] Web Search")
        print("[4] API Keys / Tokens")
        print("[5] Core Connection")
        print("[6] Show Configuration")
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
            _setup_api()
        elif choice == "6":
            _setup_show()
            input("\nPress Enter to continue...")
        else:
            print("Invalid choice.")


def _prompt(label: str, current: str | None, *, secret: bool = False) -> str | None:
    """Enter で維持、入力で更新。空文字を明示したい場合はユーザーが入力。戻り値 None=変更なし。"""
    shown = envfile.mask_secret(current) if secret and current else (current or "(empty)")
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

    if provider == "ollama" or (updates.get("LLM_PROVIDER") or provider) == "ollama":
        v = _prompt("OLLAMA_BASE_URL", before.get("OLLAMA_BASE_URL") or "http://localhost:11434")
        if v is not None:
            updates["OLLAMA_BASE_URL"] = v
        v = _prompt("OLLAMA_MODEL", before.get("OLLAMA_MODEL") or "qwen3:4b")
        if v is not None:
            updates["OLLAMA_MODEL"] = v
    else:
        v = _prompt("LLM_BASE_URL", before.get("LLM_BASE_URL"))
        if v is not None:
            updates["LLM_BASE_URL"] = v
        v = _prompt("LLM_MODEL", before.get("LLM_MODEL"))
        if v is not None:
            updates["LLM_MODEL"] = v
    return _apply(updates, before=before)


def _setup_embeddings() -> int:
    before = envfile.read_env_map()
    updates: dict[str, str | None] = {}
    v = _prompt("LLM_EMBED_PROVIDER", before.get("LLM_EMBED_PROVIDER") or "(same as LLM_PROVIDER)")
    if v is not None:
        updates["LLM_EMBED_PROVIDER"] = v
    v = _prompt("OLLAMA_EMBED_MODEL", before.get("OLLAMA_EMBED_MODEL") or "nomic-embed-text")
    if v is not None:
        updates["OLLAMA_EMBED_MODEL"] = v
    v = _prompt("LLM_EMBED_MODEL", before.get("LLM_EMBED_MODEL"))
    if v is not None:
        updates["LLM_EMBED_MODEL"] = v
    return _apply(updates, before=before)


def _setup_web_search() -> int:
    before = envfile.read_env_map()
    updates: dict[str, str | None] = {}
    v = _prompt("WEB_SEARCH_PROVIDER", before.get("WEB_SEARCH_PROVIDER") or "searxng")
    if v is not None:
        updates["WEB_SEARCH_PROVIDER"] = v
    v = _prompt("SEARXNG_URL", before.get("SEARXNG_URL") or "http://localhost:8080")
    if v is not None:
        updates["SEARXNG_URL"] = v
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
        print("[K] Keep  [R] Replace  [C] Clear")
        action = input("> ").strip().upper() or "K"
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


def _setup_api() -> int:
    before = envfile.read_env_map()
    updates: dict[str, str | None] = {}
    v = _prompt("ANCILLA_CORE_URL", before.get("ANCILLA_CORE_URL") or "http://127.0.0.1:8765")
    if v is not None:
        updates["ANCILLA_CORE_URL"] = v
    v = _prompt("ANCILLA_API_BIND_HOST", before.get("ANCILLA_API_BIND_HOST") or "127.0.0.1")
    if v is not None:
        updates["ANCILLA_API_BIND_HOST"] = v
    v = _prompt("ANCILLA_API_PORT", before.get("ANCILLA_API_PORT") or "8765")
    if v is not None:
        updates["ANCILLA_API_PORT"] = v
    v = _prompt("ANCILLA_INSTANCE_NAME", before.get("ANCILLA_INSTANCE_NAME") or "")
    if v is not None:
        updates["ANCILLA_INSTANCE_NAME"] = v
    return _apply(updates, before=before)


def _setup_show() -> int:
    data = envfile.read_env_map()
    keys = [
        "LLM_PROVIDER",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_EMBED_PROVIDER",
        "OLLAMA_EMBED_MODEL",
        "WEB_SEARCH_PROVIDER",
        "ANCILLA_API_BIND_HOST",
        "ANCILLA_API_PORT",
        "ANCILLA_CORE_URL",
        "ANCILLA_INSTANCE_NAME",
        "OPENAI_API_KEY",
        "BRAVE_API_KEY",
        "TAVILY_API_KEY",
        "DISCORD_BOT_TOKEN",
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
    ]
    print(f"Root: {get_root()}")
    print()
    for key in keys:
        src = envfile.value_source(key)
        val = envfile.get_value(key) or data.get(key) or ""
        if envfile.is_secret_key(key):
            shown = envfile.mask_secret(val) if val else "(empty)"
        else:
            shown = val or "(empty)"
        print(f"{key:<28} {shown:<40} {src}")
    return 0
