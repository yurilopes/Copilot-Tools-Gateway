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
    def __init__(
        self,
        payload: object,
        status_code: int = 200,
        status_codes: list[int] | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.status_codes = status_codes or []
        self.url: str | None = None
        self.urls: list[str] = []

    def get(self, url: str) -> FakeResponse:
        self.url = url
        self.urls.append(url)
        if self.status_codes:
            return FakeResponse(self.payload, self.status_codes.pop(0))
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


def test_consumer_history_retries_recoverable_failure() -> None:
    session = FakeSession(
        {
            "results": [{"id": "conversation-1", "title": "One"}],
            "next": None,
        },
        status_codes=[503, 200],
    )

    result = fetch_consumer_conversations(
        session,
        limit=20,
        cursor=None,
        retry_delay_seconds=0.0,
    )

    assert result.count == 1
    assert len(session.urls) == 2


def test_consumer_history_rejects_external_cursor() -> None:
    with pytest.raises(UpstreamProtocolError):
        fetch_consumer_conversations(
            FakeSession({"results": []}),
            limit=20,
            cursor="https://example.invalid/c/api/conversations",
        )
