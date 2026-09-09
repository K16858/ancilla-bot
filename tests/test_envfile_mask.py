from ancilla_bot.cli.envfile import is_secret_key, mask_secret


def test_mask_secret_edges():
    assert mask_secret("") == "(empty)"
    assert mask_secret("abcd") == "****"
    assert mask_secret("abcdefghij") == "ab****ghij"


def test_is_secret_key():
    assert is_secret_key("OPENAI_API_KEY")
    assert is_secret_key("CUSTOM_TOKEN")
    assert not is_secret_key("LLM_PROVIDER")
