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


def _redirect(mp: pytest.MonkeyPatch, base: Path) -> None:
    """データの置き場をすべて base 配下へ向ける。実行時に環境変数を読むパスは env で、
    import 時に確定する定数は（読み込み済みなら）属性を差し替える。"""
    import sys

    for k, v in {
        "ANCILLA_ROOT": base,
        "ANCILLA_CONVERSATION_DIR": base / "conversation",
        "ANCILLA_NOTIFICATIONS_DIR": base / "notifications",
        "ANCILLA_VECTOR_STORE_DIR": base / "vector_store",
        "ANCILLA_PERSONAL_MODEL_PATH": base / "personal_model.yaml",
    }.items():
        mp.setenv(k, str(v))
    import ancilla_bot.tracing.store  # noqa: F401  (TRACE_DIR は固定値)

    for mod, attr, val in [
        ("ancilla_bot.heartbeat.db", "DEFAULT_CONVERSATION_DIR", base / "conversation"),
        ("ancilla_bot.memory.conversation_store", "DEFAULT_CONVERSATION_DIR", base / "conversation"),
        ("ancilla_bot.batch.summary_search", "DEFAULT_CONVERSATION_DIR", base / "conversation"),
        ("ancilla_bot.cli.main", "DEFAULT_CONVERSATION_DIR", base / "conversation"),
        ("ancilla_bot.batch.vector_store", "DEFAULT_VECTOR_STORE_DIR", base / "vector_store"),
        ("ancilla_bot.notifications.store", "DEFAULT_NOTIFICATIONS_DIR", base / "notifications"),
        ("ancilla_bot.discord_bot", "NOTIFICATIONS_DIR", base / "notifications"),
        ("ancilla_bot.slack_bot", "NOTIFICATIONS_DIR", base / "notifications"),
        ("ancilla_bot.personal_model", "DEFAULT_PATH", base / "personal_model.yaml"),
        ("ancilla_bot.tracing.store", "TRACE_DIR", base / "traces"),
    ]:
        if mod in sys.modules:
            mp.setattr(sys.modules[mod], attr, val)


@pytest.fixture(autouse=True, scope="session")
def _isolate_data_session(tmp_path_factory):
    """テストが実データ（DB・通知・trace など）に触れないようにする。
    テスト終了後も残るバックグラウンドスレッド（SSE など）が実データへ戻らないよう、セッション全体で一時ディレクトリを既定にする。"""
    mp = pytest.MonkeyPatch()
    _redirect(mp, tmp_path_factory.mktemp("data_session"))
    yield
    mp.undo()


@pytest.fixture(autouse=True)
def _isolate_data(tmp_path_factory, monkeypatch):
    """テストごとに空のデータ置き場へ向ける（個別テストの monkeypatch は後勝ち）。"""
    _redirect(monkeypatch, tmp_path_factory.mktemp("data"))
