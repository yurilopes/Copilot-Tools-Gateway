from copilot_tools_gateway.providers.consumer.assisted_auth import wait_for_user_ready
from tools.diagnostics.capture_consumer_websocket_shape import (
    summarize_payload,
    summarize_url,
)


def test_consumer_websocket_url_summary_does_not_include_raw_token() -> None:
    summary = summarize_url(
        "wss://copilot.microsoft.com/c/api/chat?"
        "api-version=2&clientSessionId=session-123&accessToken=secret-token"
    )

    assert summary["host"] == "copilot.microsoft.com"
    assert summary["query_keys"] == ["accessToken", "api-version", "clientSessionId"]
    assert summary["has_access_token"] is True
    assert summary["access_token_length"] == len("secret-token")
    assert "secret-token" not in str(summary)


def test_consumer_websocket_payload_summary_does_not_include_raw_text() -> None:
    summary = summarize_payload(
        '{"event":"appendText","text":"private response text","id":"message-id"}'
    )

    assert summary["event"] == "appendText"
    assert summary["text_length"] == len("private response text")
    assert "text_hash" in summary
    assert "private response text" not in str(summary)
    assert "message-id" not in str(summary)


def test_consumer_wait_for_user_ready_handles_noninteractive_input(
    monkeypatch,
    capsys,
) -> None:
    def raise_eof(prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)

    wait_for_user_ready("Consumer Copilot refresh warm-up", ("Send one message.",), "")

    output = capsys.readouterr().out
    assert "Consumer Copilot refresh warm-up" in output
    assert "No interactive terminal input is available" in output
