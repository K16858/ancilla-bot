"""ancilla doctor — 診断のみ（自動修復なし）。"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

import httpx

from ancilla_bot.cli import envfile, health, process
from ancilla_bot.cli.paths import get_root


def cmd_doctor(_args: argparse.Namespace) -> int:
    root = get_root()
    failures = 0

    print("Ancilla Doctor")
    print()

    def check(label: str, ok: bool, detail: str = "", *, next_cmd: str | None = None) -> None:
        nonlocal failures
        mark = "[ok]" if ok else "[x]"
        line = f"{mark} {label}"
        if detail:
            line = f"{line}: {detail}"
        print(line)
        if not ok:
            failures += 1
            if next_cmd:
                print(f"    -> {next_cmd}")

    check("Installation root", root.is_dir(), str(root))
    check("Python", sys.version_info >= (3, 11), f"{sys.version.split()[0]}", next_cmd=None)
    check("Git", shutil.which("git") is not None, shutil.which("git") or "not found")

    env_p = envfile.env_path(root)
    check(".env", env_p.is_file(), str(env_p) if env_p.is_file() else "missing", next_cmd="ancilla install core")

    ws = root / "workspace"
    writable = False
    try:
        ws.mkdir(parents=True, exist_ok=True)
        probe = ws / ".ancilla_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        writable = True
    except OSError:
        writable = False
    check("Workspace writable", writable, str(ws), next_cmd="ancilla install core")

    core_pid = process.get_running_pid("core")
    check("Core process", core_pid is not None, f"pid={core_pid}" if core_pid else "not running", next_cmd="ancilla start")

    healthy = health.check_health()
    check("Core health", healthy, health.health_url(), next_cmd="ancilla logs core")

    provider = (envfile.get_value("LLM_PROVIDER") or "ollama").strip().lower()
    if provider == "openai":
        base = (envfile.get_value("LLM_BASE_URL") or "").strip()
        model = (envfile.get_value("LLM_MODEL") or "").strip()
        check("LLM provider", bool(base and model), f"openai base={base or '?'} model={model or '?'}", next_cmd="ancilla setup provider")
    else:
        ollama = (envfile.get_value("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
        reachable = False
        try:
            with httpx.Client(timeout=3.0) as client:
                r = client.get(f"{ollama}/api/tags")
                reachable = r.status_code == 200
        except Exception:
            reachable = False
        check("Ollama reachable", reachable, ollama, next_cmd="ancilla setup provider")
        model = (envfile.get_value("OLLAMA_MODEL") or "qwen3:4b").strip()
        model_ok = False
        if reachable:
            try:
                with httpx.Client(timeout=3.0) as client:
                    r = client.get(f"{ollama}/api/tags")
                    names = [m.get("name", "") for m in (r.json().get("models") or [])]
                    model_ok = any(model == n or n.startswith(model.split(":")[0]) for n in names)
            except Exception:
                model_ok = False
        check("Ollama model", model_ok if reachable else False, model, next_cmd="ancilla setup provider")

    embed = envfile.get_value("OLLAMA_EMBED_MODEL") or envfile.get_value("LLM_EMBED_MODEL") or "nomic-embed-text"
    check("Embedding model configured", bool(embed), str(embed))

    search = (envfile.get_value("WEB_SEARCH_PROVIDER") or "searxng").strip().lower()
    search_ok = True
    search_detail = search
    if search == "brave" and not envfile.get_value("BRAVE_API_KEY"):
        search_ok = False
        search_detail = "brave (missing BRAVE_API_KEY)"
    elif search == "tavily" and not envfile.get_value("TAVILY_API_KEY"):
        search_ok = False
        search_detail = "tavily (missing TAVILY_API_KEY)"
    check("Web Search provider", search_ok, search_detail, next_cmd="ancilla setup keys")

    discord_tok = bool(envfile.get_value("DISCORD_BOT_TOKEN"))
    slack_ok = bool(envfile.get_value("SLACK_BOT_TOKEN") and envfile.get_value("SLACK_APP_TOKEN"))
    check("Discord configured", discord_tok, "token set" if discord_tok else "not configured", next_cmd="ancilla setup keys")
    check("Slack configured", slack_ok, "tokens set" if slack_ok else "not configured", next_cmd="ancilla setup keys")

    print()
    if failures:
        print(f"{failures} check(s) failed.")
        return 1
    print("All checks passed.")
    return 0
