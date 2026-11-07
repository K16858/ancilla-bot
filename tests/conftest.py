import shutil
from pathlib import Path

import pytest

from ancilla_bot.memory import core as memory_core

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def character_prompts(tmp_path: Path, monkeypatch) -> Path:
    """CHARACTER.md はローカル上書き（gitignore）なので、テストでは追跡済みの example を使う。"""
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    shutil.copy(ROOT / "data" / "prompts" / "CHARACTER.md.example", prompts / "CHARACTER.md")
    monkeypatch.setattr(memory_core, "DEFAULT_PROMPTS_DIR", prompts)
    return prompts
