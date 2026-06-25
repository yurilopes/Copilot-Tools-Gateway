"""Consumer Copilot conversation history."""

from collections.abc import Mapping
from typing import Protocol
from urllib.parse import urljoin, urlsplit

from curl_cffi.requests import Session

from copilot_tools_gateway.domain.errors import UpstreamProtocolError
from copilot_tools_gateway.domain.models import ConversationListResult, ConversationSummary

COPILOT_URL = "https://copilot.microsoft.com"
CONVERSATIONS_URL = f"{COPILOT_URL}/c/api/conversations"


class ConsumerHistorySession(Protocol):
    def get(self, url: str) -> object:
        ...


def list_consumer_conversations(
    *,
    cookies: dict[str, str],
    access_token: str | None,
    limit: int,
    cursor: str | None,
    timeout_seconds: int,
) -> ConversationListResult:
    headers = {
        "accept": "application/json, text/plain, */*",
        "origin": COPILOT_URL,
        "referer": f"{COPILOT_URL}/",
    }
    if access_token:
        headers["authorization"] = f"Bearer {access_token}"
    with Session(
        timeout=timeout_seconds,
        impersonate="chrome",
        cookies=cookies,
        headers=headers,
    ) as session:
        return fetch_consumer_conversations(session, limit=limit, cursor=cursor)


def fetch_consumer_conversations(
    session: ConsumerHistorySession,
    *,
    limit: int,
    cursor: str | None,
) -> ConversationListResult:
    response = session.get(_history_url(cursor))
    status_code = getattr(response, "status_code", 0)
    if not isinstance(status_code, int):
        raise UpstreamProtocolError("Consumer conversation history status was not an integer")
    if status_code >= 400:
        raise UpstreamProtocolError(f"Consumer conversation history failed: {status_code}")
    payload = _response_json(response)
    if not isinstance(payload, Mapping):
        raise UpstreamProtocolError("Consumer conversation history response was not an object")
    results = payload.get("results")
    if not isinstance(results, list):
        raise UpstreamProtocolError("Consumer conversation history did not include results")
    conversations = _conversation_summaries(results, limit)
    next_cursor = _optional_string(payload.get("next"))
    return ConversationListResult(
        conversations=conversations,
        count=len(conversations),
        has_more=next_cursor is not None,
        next_cursor=next_cursor,
    )


def _history_url(cursor: str | None) -> str:
    if cursor is None or not cursor.strip():
        return CONVERSATIONS_URL
    value = cursor.strip()
    url = urljoin(COPILOT_URL, value)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "copilot.microsoft.com":
        raise UpstreamProtocolError("Consumer conversation cursor is outside Copilot")
    if not parsed.path.startswith("/c/api/conversations"):
        raise UpstreamProtocolError("Consumer conversation cursor is not a history cursor")
    return url


def _conversation_summaries(items: list[object], limit: int) -> list[ConversationSummary]:
    conversations: list[ConversationSummary] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        conversation_id = _optional_string(
            item.get("id") or item.get("conversationId") or item.get("currentConversationId")
        )
        title = _optional_string(item.get("title"))
        if conversation_id is None:
            continue
        conversations.append(
            ConversationSummary(
                conversation_id=conversation_id,
                title=title or "Untitled conversation",
            )
        )
        if len(conversations) >= limit:
            break
    return conversations


def _response_json(response: object) -> object:
    json_method = getattr(response, "json", None)
    if not callable(json_method):
        raise UpstreamProtocolError("Consumer conversation history did not expose JSON")
    try:
        return json_method()
    except ValueError as exc:
        raise UpstreamProtocolError("Consumer conversation history response was not JSON") from exc


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
