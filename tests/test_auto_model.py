import pytest

from ancilla_bot.cli.commands.setup import model_choice
from ancilla_bot.llm.auto_model import is_auto, pick_auto
from ancilla_bot.llm.ollama_client import resolve_model as resolve_ollama
from ancilla_bot.llm.openai_client import resolve_model as resolve_openai


def test_is_auto_ignores_case():
    assert is_auto("Auto")
    assert is_auto(" auto ")
    assert not is_auto("auto:latest")


def test_pick_auto_requires_one():
    assert pick_auto(["qwen3:4b"], setting="OLLAMA_MODEL") == "qwen3:4b"
    with pytest.raises(ValueError, match="2 件"):
        pick_auto(["a", "b"], setting="OLLAMA_MODEL")
    with pytest.raises(ValueError, match="0 件"):
        pick_auto([], setting="LLM_MODEL")


def test_model_choice_defaults_to_auto():
    assert model_choice("", ["qwen3:4b"]) == "auto"
    assert model_choice("0", ["qwen3:4b"]) == "auto"
    assert model_choice("Auto", []) == "auto"
    assert model_choice("1", ["qwen3:4b", "llama3:8b"]) == "qwen3:4b"
    assert model_choice("custom:7b", ["qwen3:4b"]) == "custom:7b"
    with pytest.raises(ValueError, match="out of range"):
        model_choice("3", ["qwen3:4b"])


def test_resolve_ollama_auto(monkeypatch):
    monkeypatch.setattr("ancilla_bot.cli.health.ollama_models", lambda *args, **kwargs: ["only:latest"])
    assert resolve_ollama("auto", "http://localhost:11434") == "only:latest"


def test_resolve_ollama_keeps_explicit_name(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("listed")

    monkeypatch.setattr("ancilla_bot.cli.health.ollama_models", fail)
    assert resolve_ollama("qwen3:4b", "http://localhost:11434") == "qwen3:4b"


def test_resolve_openai_auto(monkeypatch):
    monkeypatch.setattr("ancilla_bot.cli.health.openai_models", lambda *args, **kwargs: ["foo.gguf"])
    assert resolve_openai("Auto", "http://llm:8080") == "foo.gguf"


def test_preflight_ollama_auto_one(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "auto")
    monkeypatch.setattr("ancilla_bot.cli.health.ollama_models", lambda *args, **kwargs: ["only:latest"])
    monkeypatch.setattr("ancilla_bot.llm.send_chat", lambda *args, **kwargs: "pong")
    from ancilla_bot.cli.preflight import run_preflight

    assert run_preflight() is None


def test_preflight_ollama_auto_many(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "auto")
    monkeypatch.setattr("ancilla_bot.cli.health.ollama_models", lambda *args, **kwargs: ["a:1", "b:1"])
    from ancilla_bot.cli.preflight import run_preflight

    err = run_preflight()
    assert err is not None
    assert "2 件" in err
