import json

import pytest

from copilot_tools_gateway.domain.errors import UnsupportedCapabilityError, UpstreamProtocolError
from copilot_tools_gateway.providers.m365.history import (
    M365_CHAT_PAGE_URL,
    M365_CHAT_URL,
    M365_INITIAL_PAGE_CURSOR_PREFIX,
    fetch_m365_conversations,
)


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self._payload


class FakeSession:
    def __init__(
        self,
        payload: object,
        status_code: int = 200,
        page_status_code: int = 200,
        status_codes: list[int] | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.status_codes = status_codes or []
        self.page_status_code = page_status_code
        self.gets: list[str] = []
        self.posts: list[tuple[str, str, object | None]] = []

    def get(self, url: str, headers: object | None = None) -> FakeResponse:
        self.gets.append(url)
        assert headers == {"accept": "text/html"}
        return FakeResponse({}, self.page_status_code)

    def post(self, url: str, data: str, headers: object | None = None) -> FakeResponse:
        self.posts.append((url, data, headers))
        if self.status_codes:
            return FakeResponse(self.payload, self.status_codes.pop(0))
        return FakeResponse(self.payload, self.status_code)


def test_m365_history_normalizes_nav_pane_shape() -> None:
    session = FakeSession(
        {
            "store": {
                "conversationPageHistoryList": {
                    "chats": [
                        {
                            "conversationId": "conversation-1",
                            "chatName": "Quarterly Planning",
                            "messages": [{"text": "private"}],
                        }
                    ],
                    "syncState": "opaque-next-cursor",
                }
            }
        }
    )

    result = fetch_m365_conversations(session, limit=20, cursor=None)
    body = json.loads(session.posts[0][1])
    headers = session.posts[0][2]

    assert session.posts[0][0] == M365_CHAT_URL
    assert session.gets == [M365_CHAT_PAGE_URL]
    assert isinstance(headers, dict)
    assert headers["accept"] == "application/json"
    assert headers["x-route-id"] == "chat"
    assert body == {
        "action": "RefreshNavPane",
        "conversationHistoryFilter": None,
        "skipAgentListCache": True,
        "skipNotebooks": True,
    }
    assert result.count == 1
    assert result.has_more is False
    assert result.next_cursor is None
    assert result.conversations[0].conversation_id == "conversation-1"
    assert result.conversations[0].title == "Quarterly Planning"
    assert "private" not in str(result)


def test_m365_history_rejects_unvalidated_cursor() -> None:
    session = FakeSession({"store": {"conversationPageHistoryList": {"chats": []}}})

    with pytest.raises(UnsupportedCapabilityError):
        fetch_m365_conversations(session, limit=20, cursor="cursor-1")
    assert session.posts == []


def test_m365_history_uses_local_cursor_for_initial_page() -> None:
    session = FakeSession(
        {
            "store": {
                "conversationPageHistoryList": {
                    "chats": [
                        {"conversationId": "conversation-1", "chatName": "One"},
                        {"conversationId": "conversation-2", "chatName": "Two"},
                    ],
                }
            }
        }
    )

    first_page = fetch_m365_conversations(session, limit=1, cursor=None)
    second_page = fetch_m365_conversations(
        session,
        limit=1,
        cursor=first_page.next_cursor,
    )

    assert first_page.conversations[0].conversation_id == "conversation-1"
    assert first_page.has_more is True
    assert first_page.next_cursor == f"{M365_INITIAL_PAGE_CURSOR_PREFIX}1"
    assert second_page.conversations[0].conversation_id == "conversation-2"
    assert second_page.has_more is False
    assert second_page.next_cursor is None


def test_m365_history_rejects_missing_chats() -> None:
    with pytest.raises(UpstreamProtocolError):
        fetch_m365_conversations(
            FakeSession({"store": {"conversationPageHistoryList": {}}}),
            limit=20,
            cursor=None,
        )


def test_m365_history_retries_recoverable_post_failure() -> None:
    session = FakeSession(
        {
            "store": {
                "conversationPageHistoryList": {
                    "chats": [{"conversationId": "conversation-1", "chatName": "One"}],
                }
            }
        },
        status_codes=[403, 200],
    )

    result = fetch_m365_conversations(
        session,
        limit=20,
        cursor=None,
        retry_delay_seconds=0.0,
    )

    assert result.count == 1
    assert len(session.posts) == 2
    assert session.gets == [M365_CHAT_PAGE_URL, M365_CHAT_PAGE_URL]


def test_m365_history_rejects_chat_page_failure() -> None:
    with pytest.raises(UpstreamProtocolError):
        fetch_m365_conversations(
            FakeSession(
                {"store": {"conversationPageHistoryList": {"chats": []}}},
                page_status_code=403,
            ),
            limit=20,
            cursor=None,
        )
