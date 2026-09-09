from ancilla_bot.core.cancel import is_cancelled, request_cancel, reset_cancel
from ancilla_bot.llm import http as llm_http


def test_request_cancel_closes_shared_client() -> None:
    client = llm_http.get_client()
    assert client.is_closed is False
    try:
        request_cancel()
        assert client.is_closed is True
        assert is_cancelled() is True
    finally:
        reset_cancel()
        llm_http.close_client()
