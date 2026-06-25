import pytest

from copilot_tools_gateway.domain.errors import UpstreamProtocolError
from copilot_tools_gateway.providers.consumer.history import fetch_consumer_conversations


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self._payload


class FakeSession:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.url: str | None = None

    def get(self, url: str) -> FakeResponse:
        self.url = url
        return FakeResponse(self.payload, self.status_code)


def test_consumer_history_normalizes_title_and_id_only() -> None:
    session = FakeSession(
        {
            "results": [
                {
                    "id": "conversation-1",
                    "title": "Validation Marker Inquiry",
                    "updatedAt": "private-date",
                    "messages": [{"text": "private"}],
                }
            ],
            "next": "/c/api/conversations?cursor=next",
        }
    )

    result = fetch_consumer_conversations(session, limit=20, cursor=None)

    assert result.count == 1
    assert result.has_more is True
    assert result.next_cursor == "/c/api/conversations?cursor=next"
    assert result.conversations[0].conversation_id == "conversation-1"
    assert result.conversations[0].title == "Validation Marker Inquiry"
    assert "private" not in str(result)


def test_consumer_history_bounds_returned_items() -> None:
    session = FakeSession(
        {
            "results": [
                {"id": "conversation-1", "title": "One"},
                {"id": "conversation-2", "title": "Two"},
            ],
            "next": None,
        }
    )

    result = fetch_consumer_conversations(session, limit=1, cursor=None)

    assert result.count == 1
    assert result.conversations[0].conversation_id == "conversation-1"


def test_consumer_history_rejects_external_cursor() -> None:
    with pytest.raises(UpstreamProtocolError):
        fetch_consumer_conversations(
            FakeSession({"results": []}),
            limit=20,
            cursor="https://example.invalid/c/api/conversations",
        )
