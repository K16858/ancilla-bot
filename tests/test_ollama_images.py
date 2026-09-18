import pytest

from ancilla_bot.llm import ollama_client


def test_attach_images_requires_trailing_user(monkeypatch):
    monkeypatch.setattr(ollama_client, "VISION_ENABLED", True)
    with pytest.raises(ValueError, match="末尾の user"):
        ollama_client._attach_images([{"role": "system", "content": "x"}], ["img"])


def test_attach_images_sets_last_user(monkeypatch):
    monkeypatch.setattr(ollama_client, "VISION_ENABLED", True)
    out = ollama_client._attach_images([{"role": "user", "content": "hi"}], ["img"])
    assert out[-1]["images"] == ["img"]
    assert out[-1]["role"] == "user"
