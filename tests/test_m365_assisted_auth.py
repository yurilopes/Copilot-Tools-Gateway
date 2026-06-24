import base64
import json

from copilot_tools_gateway.providers.m365.assisted_auth import (
    M365TokenCapture,
    _format_browser_steps,
)


def test_m365_token_capture_deduplicates_and_tracks_safe_state() -> None:
    capture = M365TokenCapture()
    chat_token = _jwt(
        {
            "aud": "https://substrate.office.com/sydney",
            "oid": "user-id",
            "tid": "tenant-id",
            "exp": 2_000_000_000,
        }
    )
    graph_token = _jwt({"aud": "https://graph.microsoft.com", "exp": 2_000_000_000})
    search_token = _jwt(
        {
            "aud": "https://substrate.office.com/search",
            "scp": "SubstrateSearch-Internal.ReadWrite",
            "exp": 2_000_000_000,
        }
    )

    capture.append_token(chat_token)
    capture.append_token(chat_token)
    capture.append_token(graph_token)
    capture.append_token(graph_token)
    capture.append_token(search_token)
    capture.append_token(search_token)

    assert len(capture.sessions) == 1
    assert len(capture.graph_tokens) == 1
    assert len(capture.search_tokens) == 1
    assert capture.has_chat_token is True
    assert capture.has_document_tokens is True


def test_m365_browser_steps_report_safe_capture_state_without_tokens() -> None:
    capture = M365TokenCapture()
    message = _format_browser_steps(
        "Microsoft 365 Copilot refresh",
        ("Attach a small document if Graph or search tokens are still missing.",),
        "Press Enter after browser action: ",
        capture,
    )

    assert "Microsoft 365 Copilot refresh" in message
    assert "Copilot chat token captured: no" in message
    assert "Graph token captured: no" in message
    assert "Search token captured: no" in message
    assert "cookies" not in message.lower()
    assert "browser storage" not in message.lower()


def _jwt(payload: dict[str, object]) -> str:
    header = {"alg": "none", "typ": "JWT"}
    return ".".join(
        [
            _base64url_json(header),
            _base64url_json(payload),
            "signature",
        ]
    )


def _base64url_json(value: dict[str, object]) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
