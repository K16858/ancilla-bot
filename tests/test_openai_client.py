import httpx
import pytest

from ancilla_bot.llm import http as llm_http
from ancilla_bot.llm import openai_client as oc

BASE = "http://llm.local"


@pytest.fixture
def sent(monkeypatch):
    """post_json を差し替え、送信内容を記録して reply を返す。"""
    calls = []
    reply = {"choices": [{"message": {"role": "assistant", "content": " ok "}}]}

    def fake_post(url, body, *, timeout, headers=None):
        calls.append({"url": url, "body": body, "headers": headers})
        return httpx.Response(200, json=reply, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm_http, "post_json", fake_post)
    return calls


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("LLM_API_KEY", "LLM_MAX_TOKENS", "OLLAMA_THINK"):
        monkeypatch.delenv(name, raising=False)


def _set_reply(monkeypatch, data, status=200):
    def fake_post(url, body, *, timeout, headers=None):
        return httpx.Response(status, json=data, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm_http, "post_json", fake_post)


def test_send_chat_builds_request_and_strips_content(sent):
    messages = [
        {"role": "system", "content": "A"},
        {"role": "user", "content": "hi"},
        {"role": "system", "content": "B"},
    ]
    assert oc.send_chat(messages, base_url=BASE + "/", model="qwen3") == "ok"
    call = sent[0]
    assert call["url"] == BASE + "/v1/chat/completions"
    assert call["headers"] is None
    body = call["body"]
    assert body["model"] == "qwen3"
    assert body["messages"] == [{"role": "system", "content": "A\n\nB"}, {"role": "user", "content": "hi"}]
    assert body["chat_template_kwargs"] == {"enable_thinking": True}
    assert "response_format" not in body and "max_tokens" not in body


def test_api_key_and_max_tokens_from_env(sent, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", " secret ")
    monkeypatch.setenv("LLM_MAX_TOKENS", "128")
    oc.send_chat([{"role": "user", "content": "x"}], base_url=BASE, model="m")
    assert sent[0]["headers"] == {"Authorization": "Bearer secret"}
    assert sent[0]["body"]["max_tokens"] == 128


@pytest.mark.parametrize(
    "model,env,fmt,expected",
    [
        ("sarashina3-mini", "", None, False),
        ("org/Llama-3:8b", "", None, False),
        ("qwen3", "", {"type": "object"}, False),
        ("sarashina3-mini", "true", None, True),
        ("qwen3", "0", None, False),
    ],
)
def test_thinking_switch(sent, monkeypatch, model, env, fmt, expected):
    monkeypatch.setenv("OLLAMA_THINK", env)
    oc.send_chat([{"role": "user", "content": "x"}], base_url=BASE, model=model, format=fmt)
    body = sent[0]["body"]
    assert body["chat_template_kwargs"]["enable_thinking"] is expected
    if fmt:
        assert body["response_format"]["json_schema"]["schema"] == fmt


def test_images_are_attached_to_last_user_message(sent, monkeypatch):
    monkeypatch.setattr(oc, "VISION_ENABLED", True)
    oc.send_chat([{"role": "user", "content": "what?"}], base_url=BASE, model="m", images=["QUJD"])
    content = sent[0]["body"]["messages"][-1]["content"]
    assert content == [
        {"type": "text", "text": "what?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
    ]
    with pytest.raises(ValueError):
        oc.send_chat([{"role": "assistant", "content": "x"}], base_url=BASE, model="m", images=["QUJD"])


def test_list_content_is_flattened(monkeypatch):
    _set_reply(monkeypatch, {"choices": [{"message": {"content": [{"type": "text", "text": "a"}, "b", {"type": "x"}]}}]})
    assert oc.send_chat([{"role": "user", "content": "x"}], base_url=BASE, model="m") == "ab"


def test_send_chat_message_passes_tools_and_returns_message(sent):
    tools = [{"type": "function", "function": {"name": "get_time", "parameters": {"type": "object"}}}]
    msg = oc.send_chat_message([{"role": "user", "content": "x"}], base_url=BASE, model="m", tools=tools)
    assert msg["content"] == " ok "
    assert sent[0]["body"]["tools"] == tools


@pytest.mark.parametrize(
    "data",
    [{"choices": []}, {"choices": [{"message": {"role": "assistant"}}]}],
)
def test_malformed_responses_raise(monkeypatch, data):
    _set_reply(monkeypatch, data)
    with pytest.raises(ValueError):
        oc.send_chat([{"role": "user", "content": "x"}], base_url=BASE, model="m")


def test_http_error_propagates(monkeypatch):
    _set_reply(monkeypatch, {"error": "bad"}, status=401)
    with pytest.raises(httpx.HTTPStatusError):
        oc.send_chat([{"role": "user", "content": "x"}], base_url=BASE, model="m")


def test_missing_config_raises():
    with pytest.raises(ValueError, match="LLM_BASE_URL"):
        oc.send_chat([], base_url="", model="m")
    with pytest.raises(ValueError, match="LLM_MODEL"):
        oc.send_chat([], base_url=BASE, model="")


def test_embed_text(monkeypatch):
    _set_reply(monkeypatch, {"data": [{"embedding": [1, 2.5]}]})
    assert oc.embed_text("x", base_url=BASE, model="e") == [1.0, 2.5]
    _set_reply(monkeypatch, {"data": []})
    with pytest.raises(ValueError):
        oc.embed_text("x", base_url=BASE, model="e")
    with pytest.raises(ValueError, match="LLM_EMBED_MODEL"):
        oc.embed_text("x", base_url=BASE, model=" ")
