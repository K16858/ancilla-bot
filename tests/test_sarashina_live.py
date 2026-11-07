"""Sarashina API（OpenAI 互換）への実通信テスト。SARASHINA_API_KEY が無ければ skip。

キーは .env（gitignore 済み）か環境変数に置く。リポジトリへは書かない。
"""

import os

import pytest
from dotenv import load_dotenv

from ancilla_bot.llm import openai_client as oc
from ancilla_bot.llm.schemas import AgentResponseWithTools
from ancilla_bot.llm.tool_adapter import _build_ollama_tools, _native_message_to_result, _parse_gbnf_response

load_dotenv()

BASE = os.getenv("SARASHINA_BASE_URL", "https://api.sarashina.ai")
MODEL = os.getenv("SARASHINA_MODEL", "sarashina3-mini")

pytestmark = pytest.mark.skipif(not os.getenv("SARASHINA_API_KEY"), reason="SARASHINA_API_KEY not set")


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", os.environ["SARASHINA_API_KEY"])
    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)


def test_plain_chat():
    out = oc.send_chat(
        [{"role": "system", "content": "数字だけで答える。"}, {"role": "user", "content": "1+1は？"}],
        base_url=BASE,
        model=MODEL,
        timeout=60,
    )
    assert "2" in out


def test_gbnf_mode_response_parses_to_agent_schema():
    raw = oc.send_chat(
        [
            {"role": "system", "content": "あなたはエージェント。使えるツール: get_time（現在時刻）。JSON で答える。"},
            {"role": "user", "content": "こんにちは、と挨拶だけ返して。"},
        ],
        base_url=BASE,
        model=MODEL,
        format=AgentResponseWithTools.model_json_schema(),
        timeout=60,
    )
    # action は schema 上 enum 制約が無く、モデルが架空のツール名を返すことがある（agent_loop が Unknown tool として処理）
    result = _parse_gbnf_response(raw)
    assert result.assistant_message is None and result.thought
    assert result.final_answer or result.action


def test_native_tool_call_with_real_registry():
    message = oc.send_chat_message(
        [{"role": "user", "content": "今の時刻を教えて。"}],
        base_url=BASE,
        model=MODEL,
        tools=_build_ollama_tools(),
        timeout=60,
    )
    result = _native_message_to_result(message)
    assert result.action == "get_time"
    assert isinstance(result.action_input, dict)
