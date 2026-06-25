"""Microsoft 365 Copilot conversation history."""

import json
import time
import uuid
from collections.abc import Mapping
from typing import Protocol

from curl_cffi.requests import Session

from copilot_tools_gateway.domain.errors import UnsupportedCapabilityError, UpstreamProtocolError
from copilot_tools_gateway.domain.models import ConversationListResult, ConversationSummary
from copilot_tools_gateway.providers.m365.auth import M365Session
from copilot_tools_gateway.providers.m365.web_auth import M365WebAuth

M365_CLOUD_URL = "https://m365.cloud.microsoft"
M365_CHAT_URL = f"{M365_CLOUD_URL}/chat"
M365_CHAT_PAGE_URL = f"{M365_CLOUD_URL}/chat/"
M365_HISTORY_ATTEMPTS = 2
M365_HISTORY_RETRY_DELAY_SECONDS = 2.0
M365_HISTORY_RETRY_STATUS_CODES = {403}
M365_INITIAL_PAGE_CURSOR_PREFIX = "m365-initial-offset:"


class M365HistorySession(Protocol):
    def get(self, url: str, headers: Mapping[str, str] | None = None) -> object:
        ...

    def post(
        self,
        url: str,
        data: str,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        ...


def list_m365_conversations(
    *,
    session: M365Session,
    web_auth: M365WebAuth,
    limit: int,
    cursor: str | None,
    timeout_seconds: float,
) -> ConversationListResult:
    with Session(
        timeout=timeout_seconds,
        impersonate="chrome",
        cookies=web_auth.cookies,
    ) as client:
        return fetch_m365_conversations(
            client,
            limit=limit,
            cursor=cursor,
            retry_delay_seconds=M365_HISTORY_RETRY_DELAY_SECONDS,
        )


def fetch_m365_conversations(
    session: M365HistorySession,
    *,
    limit: int,
    cursor: str | None,
    retry_delay_seconds: float = 0.0,
) -> ConversationListResult:
    offset = _initial_page_offset(cursor)
    for attempt_index in range(M365_HISTORY_ATTEMPTS):
        result = _fetch_m365_conversations_once(session, limit, offset)
        if isinstance(result, ConversationListResult):
            return result
        if _should_retry_history_status(result, attempt_index):
            _sleep_before_retry(retry_delay_seconds)
            continue
        raise UpstreamProtocolError(f"M365 conversation history failed: {result}")
    raise UpstreamProtocolError("M365 conversation history retry was exhausted")


def _fetch_m365_conversations_once(
    session: M365HistorySession,
    limit: int,
    offset: int,
) -> ConversationListResult | int:
    _load_chat_page(session)
    response = session.post(
        M365_CHAT_URL,
        data=json.dumps(_history_body(), separators=(",", ":")),
        headers=_history_headers(),
    )
    status_code = getattr(response, "status_code", 0)
    if not isinstance(status_code, int):
        raise UpstreamProtocolError("M365 conversation history status was not an integer")
    if status_code >= 400:
        return status_code
    payload = _response_json(response)
    result = _conversation_list_result(payload, limit, offset)
    if result is None:
        raise UpstreamProtocolError("M365 conversation history did not include chats")
    return result


def _should_retry_history_status(status_code: int, attempt_index: int) -> bool:
    return (
        status_code in M365_HISTORY_RETRY_STATUS_CODES
        and attempt_index + 1 < M365_HISTORY_ATTEMPTS
    )


def _sleep_before_retry(delay_seconds: float) -> None:
    if delay_seconds > 0:
        time.sleep(delay_seconds)


def _load_chat_page(session: M365HistorySession) -> None:
    response = session.get(M365_CHAT_PAGE_URL, headers={"accept": "text/html"})
    status_code = getattr(response, "status_code", 0)
    if not isinstance(status_code, int):
        raise UpstreamProtocolError("M365 chat page status was not an integer")
    if status_code >= 400:
        raise UpstreamProtocolError(f"M365 chat page failed: {status_code}")


def _history_headers() -> dict[str, str]:
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "origin": M365_CLOUD_URL,
        "referer": M365_CHAT_PAGE_URL,
        "x-client-eligibility": "{}",
        "x-host-context": json.dumps(
            {"hostName": "m365.cloud.microsoft", "clientPlatform": "web"},
            separators=(",", ":"),
        ),
        "x-route-id": "chat",
        "x-session-id": str(uuid.uuid4()),
    }


def _initial_page_offset(cursor: str | None) -> int:
    if cursor is None or not cursor.strip():
        return 0
    value = cursor.strip()
    if not value.startswith(M365_INITIAL_PAGE_CURSOR_PREFIX):
        raise UnsupportedCapabilityError(
            "M365 conversation listing pagination is not validated yet"
        )
    offset_text = value.removeprefix(M365_INITIAL_PAGE_CURSOR_PREFIX)
    if not offset_text.isdecimal():
        raise UnsupportedCapabilityError("M365 conversation listing cursor is invalid")
    return int(offset_text)


def _history_body() -> dict[str, object]:
    return {
        "action": "RefreshNavPane",
        "conversationHistoryFilter": None,
        "skipAgentListCache": True,
        "skipNotebooks": True,
    }


def _conversation_list_result(
    payload: object,
    limit: int,
    offset: int,
) -> ConversationListResult | None:
    items = _items(payload)
    if items is None:
        return None
    all_conversations = _conversation_summaries(items)
    conversations = all_conversations[offset : offset + limit]
    next_cursor = _next_initial_page_cursor(
        next_offset=offset + len(conversations),
        total_count=len(all_conversations),
    )
    return ConversationListResult(
        conversations=conversations,
        count=len(conversations),
        has_more=next_cursor is not None,
        next_cursor=next_cursor,
    )


def _items(payload: object) -> list[object] | None:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, Mapping):
        return None
    history_list = _m365_history_list(payload)
    if history_list is not None:
        chats = history_list.get("chats")
        if isinstance(chats, list):
            return chats
    for key in ("conversations", "items", "value", "results", "data", "chats"):
        items = payload.get(key)
        if isinstance(items, list):
            return items
    return None


def _m365_history_list(payload: Mapping[object, object]) -> Mapping[object, object] | None:
    store = payload.get("store")
    if not isinstance(store, Mapping):
        return None
    history_list = store.get("conversationPageHistoryList")
    return history_list if isinstance(history_list, Mapping) else None


def _conversation_summaries(items: list[object]) -> list[ConversationSummary]:
    conversations: list[ConversationSummary] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        conversation_id = _optional_string(
            item.get("id")
            or item.get("conversationId")
            or item.get("threadId")
            or item.get("sessionId")
        )
        title = _optional_string(
            item.get("title") or item.get("chatName") or item.get("name") or item.get("topic")
        )
        if conversation_id is None:
            continue
        conversations.append(
            ConversationSummary(
                conversation_id=conversation_id,
                title=title or "Untitled conversation",
            )
        )
    return conversations


def _next_initial_page_cursor(next_offset: int, total_count: int) -> str | None:
    if next_offset >= total_count:
        return None
    return f"{M365_INITIAL_PAGE_CURSOR_PREFIX}{next_offset}"


def _response_json(response: object) -> object:
    json_method = getattr(response, "json", None)
    if not callable(json_method):
        raise UpstreamProtocolError("M365 conversation history did not expose JSON")
    try:
        return json_method()
    except ValueError as exc:
        raise UpstreamProtocolError("M365 conversation history response was not JSON") from exc


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
