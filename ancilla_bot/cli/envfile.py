""".env の読み書き（コメント保持・atomic・秘密マスク）。"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from ancilla_bot.cli.paths import get_root

SECRET_KEYS = {
    "OPENAI_API_KEY",
    "BRAVE_API_KEY",
    "TAVILY_API_KEY",
    "SEARXNG_TOKEN",
    "SEARXNG_PASSWORD",
    "DISCORD_BOT_TOKEN",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
}

_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def env_path(root: Path | None = None) -> Path:
    return (root or get_root()) / ".env"


def example_path(root: Path | None = None) -> Path:
    return (root or get_root()) / ".env.example"


def ensure_env_file(root: Path | None = None) -> Path:
    path = env_path(root)
    if path.is_file():
        return path
    ex = example_path(root)
    if ex.is_file():
        path.write_text(ex.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        path.write_text("", encoding="utf-8")
    _chmod_private(path)
    return path


def read_env_map(path: Path | None = None) -> dict[str, str]:
    p = path or env_path()
    if not p.is_file():
        return {}
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = _LINE_RE.match(s)
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
            raw = raw[1:-1]
        out[key] = raw
    return out


def get_value(key: str, *, path: Path | None = None) -> str | None:
    env_val = os.getenv(key)
    if env_val is not None and env_val != "":
        return env_val
    return read_env_map(path).get(key)


def value_source(key: str, *, path: Path | None = None) -> str:
    file_map = read_env_map(path)
    env_val = os.environ.get(key)
    file_val = file_map.get(key)
    # load_dotenv 後は .env も environ に載るので、ファイルと不一致のときだけ environment
    if env_val is not None and env_val != "" and env_val != file_val:
        return "environment"
    if file_val is not None:
        return ".env"
    if env_val is not None and env_val != "":
        return "environment"
    return "default"


def mask_secret(value: str, *, keep: int = 4) -> str:
    if not value:
        return "(empty)"
    if len(value) <= keep:
        return "*" * len(value)
    return f"{value[:2]}{'*' * max(4, len(value) - keep - 2)}{value[-keep:]}"


def is_secret_key(key: str) -> bool:
    if key in SECRET_KEYS:
        return True
    upper = key.upper()
    return upper.endswith("_TOKEN") or upper.endswith("_KEY") or upper.endswith("_PASSWORD")


def set_values(updates: dict[str, str | None], *, path: Path | None = None) -> list[str]:
    """
    キーを更新/追記/削除する。
    値が None ならキー行を削除。
    戻り値は変更されたキー一覧。
    """
    p = path or ensure_env_file()
    original = p.read_text(encoding="utf-8") if p.is_file() else ""
    lines = original.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        # normalize for rewrite
        pass

    changed: list[str] = []
    seen: set[str] = set()
    new_lines: list[str] = []

    for line in lines:
        raw = line.rstrip("\r\n")
        m = _LINE_RE.match(raw.strip()) if raw.strip() and not raw.strip().startswith("#") else None
        if not m:
            new_lines.append(line if line.endswith("\n") else line + "\n")
            continue
        key = m.group(1)
        if key not in updates:
            new_lines.append(line if line.endswith("\n") else line + "\n")
            continue
        seen.add(key)
        new_val = updates[key]
        old_val = m.group(2).strip()
        if len(old_val) >= 2 and old_val[0] == old_val[-1] and old_val[0] in ("'", '"'):
            old_compare = old_val[1:-1]
        else:
            old_compare = old_val
        if new_val is None:
            if key not in changed:
                changed.append(key)
            continue
        if old_compare != new_val:
            changed.append(key)
        new_lines.append(f"{key}={new_val}\n")

    for key, new_val in updates.items():
        if key in seen:
            continue
        if new_val is None:
            continue
        changed.append(key)
        new_lines.append(f"{key}={new_val}\n")

    text = "".join(new_lines)
    _atomic_write(p, text)
    _chmod_private(p)
    return changed


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _chmod_private(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
