import base64
import json

from copilot_tools_gateway.providers.m365.tokens import (
    M365CapturedTokenKind,
    classify_m365_access_token,
    graph_token_is_valid,
)


def test_classify_chathub_token() -> None:
    token = _jwt(
        {
            "aud": "https://substrate.office.com/sydney",
            "oid": "user-id",
            "tid": "tenant-id",
            "exp": 2_000,
        }
    )

    captured = classify_m365_access_token(token, now=1_000)

    assert captured is not None
    assert captured.kind == M365CapturedTokenKind.CHATHUB
    assert captured.session is not None
    assert captured.session.oid == "user-id"
    assert captured.session.tid == "tenant-id"


def test_classify_graph_token() -> None:
    token = _jwt(
        {
            "aud": "https://graph.microsoft.com",
            "exp": 2_000,
        }
    )

    captured = classify_m365_access_token(token, now=1_000)

    assert captured is not None
    assert captured.kind == M365CapturedTokenKind.GRAPH
    assert captured.session is None


def test_classify_search_token() -> None:
    token = _jwt(
        {
            "aud": "https://substrate.office.com/search",
            "scp": "SubstrateSearch-Internal.ReadWrite",
            "exp": 2_000,
        }
    )

    captured = classify_m365_access_token(token, now=1_000)

    assert captured is not None
    assert captured.kind == M365CapturedTokenKind.SEARCH
    assert captured.session is None


def test_reject_graph_token_without_expiry() -> None:
    token = _jwt({"aud": "https://graph.microsoft.com"})

    assert graph_token_is_valid(token, now=1_000) is False
    assert classify_m365_access_token(token, now=1_000) is None


def test_reject_expired_graph_token() -> None:
    token = _jwt(
        {
            "aud": "https://graph.microsoft.com",
            "exp": 1_030,
        }
    )

    assert graph_token_is_valid(token, now=1_000) is False
    assert classify_m365_access_token(token, now=1_000) is None


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
