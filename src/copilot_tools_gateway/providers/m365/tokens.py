"""Token classification for Microsoft 365 Copilot browser capture."""

import time
from dataclasses import dataclass
from enum import StrEnum

from copilot_tools_gateway.providers.m365.auth import M365Session, jwt_payload

GRAPH_AUDIENCES = {
    "https://graph.microsoft.com",
    "00000003-0000-0000-c000-000000000000",
}
SEARCH_AUDIENCES = {"https://substrate.office.com/search"}
SEARCH_SCOPES = {"SubstrateSearch-Internal.ReadWrite"}


class M365CapturedTokenKind(StrEnum):
    CHATHUB = "chathub"
    GRAPH = "graph"
    SEARCH = "search"


@dataclass(frozen=True)
class M365CapturedToken:
    kind: M365CapturedTokenKind
    token: str
    session: M365Session | None = None


def classify_m365_access_token(token: str, now: int | None = None) -> M365CapturedToken | None:
    session = _session_from_chathub_token(token)
    if session is not None:
        return M365CapturedToken(
            kind=M365CapturedTokenKind.CHATHUB,
            token=token,
            session=session,
        )
    if graph_token_is_valid(token, now=now):
        return M365CapturedToken(kind=M365CapturedTokenKind.GRAPH, token=token)
    if search_token_is_valid(token, now=now):
        return M365CapturedToken(kind=M365CapturedTokenKind.SEARCH, token=token)
    return None


def graph_token_is_valid(token: str, now: int | None = None) -> bool:
    return _token_audience_is_valid(token, GRAPH_AUDIENCES, now=now)


def search_token_is_valid(token: str, now: int | None = None) -> bool:
    if not _token_audience_is_valid(token, SEARCH_AUDIENCES, now=now):
        return False
    try:
        claims = jwt_payload(token)
    except (ValueError, TypeError):
        return False
    scopes = claims.get("scp")
    if not isinstance(scopes, str):
        return False
    return bool(SEARCH_SCOPES.intersection(scopes.split()))


def _token_audience_is_valid(token: str, audiences: set[str], now: int | None = None) -> bool:
    try:
        claims = jwt_payload(token)
    except (ValueError, TypeError):
        return False
    audience = claims.get("aud")
    expires_at = claims.get("exp")
    if not isinstance(audience, str) or audience not in audiences:
        return False
    if not isinstance(expires_at, int) or isinstance(expires_at, bool):
        return False
    active_now = int(time.time()) if now is None else now
    return expires_at > active_now + 60


def _session_from_chathub_token(token: str) -> M365Session | None:
    try:
        return M365Session.from_access_token(token)
    except ValueError:
        return None
