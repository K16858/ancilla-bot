import json

import pytest

from ancilla_bot.llm.tool_adapter import (
    _coerce_user_answer,
    _native_message_to_result,
    _parse_gbnf_response,
)


def test_parse_gbnf_valid_final_answer():
    raw = json.dumps(
        {"thought": "t", "final_answer": "hello", "action": None, "action_input": None}
    )
    result = _parse_gbnf_response(raw)
    assert result.thought == "t"
    assert result.final_answer == "hello"
    assert result.action is None


def test_parse_gbnf_with_surrounding_noise():
    inner = json.dumps({"thought": "t", "action": "get_time", "action_input": {}})
    result = _parse_gbnf_response(f"prefix {inner} suffix")
    assert result.action == "get_time"
    assert result.action_input == {}


def test_parse_gbnf_empty_raises():
    with pytest.raises(ValueError, match="empty LLM response"):
        _parse_gbnf_response("  ")


def test_coerce_user_answer_unwraps_json():
    wrapped = json.dumps({"thought": "t", "final_answer": "plain text"})
    assert _coerce_user_answer(wrapped) == "plain text"
    assert _coerce_user_answer("already plain") == "already plain"


def test_native_message_bad_arguments_becomes_empty_dict():
    result = _native_message_to_result(
        {
            "content": "x",
            "tool_calls": [{"function": {"name": "get_time", "arguments": "not-json"}}],
        }
    )
    assert result.action == "get_time"
    assert result.action_input == {}
