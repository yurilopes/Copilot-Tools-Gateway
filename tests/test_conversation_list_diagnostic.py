import json

from tools.diagnostics.conversation_list_protocol_safety import (
    conversation_id_from_url,
    ignored_sidebar_text,
    m365_ui_recommended_action,
    normalize_sidebar_candidates,
    safe_failure,
    safe_link_values,
    safe_metric_urls,
    safe_page_state,
    safe_request_json_shape,
    safe_shape,
    safe_string_attr,
    safe_url_path,
    unique_records,
    url_is_relevant,
)


def test_conversation_list_safe_failure_omits_sensitive_message() -> None:
    result = safe_failure(
        "copilot",
        "direct-api",
        RuntimeError("token cookie authorization browser storage raw requests private text"),
    )

    serialized = json.dumps(result).lower()

    assert "token" not in serialized
    assert "cookie" not in serialized
    assert "authorization" not in serialized
    assert "browser storage" not in serialized
    assert "raw requests" not in serialized
    assert "private text" not in serialized


def test_conversation_list_safe_shape_omits_item_values() -> None:
    result = safe_shape(
        {
            "results": [
                {
                    "id": "secret-id",
                    "title": "private title",
                    "messages": [{"text": "private message"}],
                }
            ]
        }
    )

    serialized = json.dumps(result).lower()

    assert "secret-id" not in serialized
    assert "private title" not in serialized
    assert "private message" not in serialized
    assert result["results_count"] == 1
    assert result["results_item_keys"] == ["id", "messages", "title"]


def test_conversation_list_page_state_is_sanitized() -> None:
    result = safe_page_state(
        url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize?secret=value",
        title="Private title",
        body_text="Private Copilot conversation text",
    )

    serialized = json.dumps(result).lower()

    assert result["host"] == "login.microsoftonline.com"
    assert result["path"] == "/common/oauth2/v2.0/authorize"
    assert result["has_sign_in_redirect"] is True
    assert "secret=value" not in serialized
    assert "private title" not in serialized
    assert "private copilot conversation text" not in serialized


def test_m365_ui_recommended_action_guides_login() -> None:
    page_state = {
        "has_sign_in_redirect": True,
    }

    action = m365_ui_recommended_action(page_state, [])

    assert action == "login_m365_in_open_browser_then_rerun"


def test_m365_ui_recommended_action_guides_sidebar_open() -> None:
    page_state = {
        "has_sign_in_redirect": False,
    }

    action = m365_ui_recommended_action(page_state, [])

    assert action == "open_m365_sidebar_history_then_rerun"


def test_safe_string_attr_returns_only_strings() -> None:
    class Request:
        method = "GET"
        resource_type = 123

    assert safe_string_attr(Request(), "method") == "GET"
    assert safe_string_attr(Request(), "resource_type") == ""
    assert safe_string_attr(Request(), "missing") == ""


def test_unique_records_keeps_distinct_event_types() -> None:
    records = [
        {"event": "request", "host": "example.test", "path": "/history"},
        {"event": "request", "host": "example.test", "path": "/history"},
        {"event": "response", "host": "example.test", "path": "/history", "status": 200},
    ]

    unique = unique_records(records)

    assert unique == [
        {"event": "request", "host": "example.test", "path": "/history"},
        {"event": "response", "host": "example.test", "path": "/history", "status": 200},
    ]


def test_url_is_relevant_keeps_m365_chat_loader() -> None:
    assert url_is_relevant("https://m365.cloud.microsoft/chat/") is True
    assert url_is_relevant("https://m365.cloud.microsoft/chat/conversation/abc") is True
    assert url_is_relevant("https://m365.cloud.microsoft/library") is False


def test_safe_url_path_redacts_conversation_id() -> None:
    path = "/chat/conversation/fb3ec36a-e0b0-48b4-ba23-da634a582ae7"

    assert safe_url_path(path) == "/chat/conversation/:conversation_id"


def test_safe_link_values_hashes_conversation_id() -> None:
    values = [
        {
            "path": "/chat/conversation/fb3ec36a-e0b0-48b4-ba23-da634a582ae7",
            "conversationIdHashInput": "fb3ec36a-e0b0-48b4-ba23-da634a582ae7",
            "textLength": 14,
        }
    ]

    result = safe_link_values(values)
    serialized = json.dumps(result)

    assert result == [
        {
            "path": "/chat/conversation/:conversation_id",
            "conversation_id_length": 36,
            "conversation_id_hash": "3bacabb9014e",
            "text_length": 14,
        }
    ]
    assert "fb3ec36a" not in serialized


def test_safe_metric_urls_redacts_url_values() -> None:
    result = safe_metric_urls(
        {
            "httpRequestMetrics": [
                {
                    "url": (
                        "https://m365.cloud.microsoft/chat/conversation/"
                        "fb3ec36a-e0b0-48b4-ba23-da634a582ae7?secret=value"
                    ),
                    "method": "GET",
                    "statusCode": 200,
                }
            ]
        }
    )
    serialized = json.dumps(result)

    assert result == [
        {
            "host": "m365.cloud.microsoft",
            "path": "/chat/conversation/:conversation_id",
            "query_keys": ["secret"],
            "method": "GET",
            "status": 200,
        }
    ]
    assert "fb3ec36a" not in serialized
    assert "value" not in serialized


def test_safe_request_json_shape_keeps_action_and_omits_values() -> None:
    result = safe_request_json_shape(
        {
            "action": "GetConversationPageHistoryList",
            "syncState": "private-sync",
            "state": {"conversationPageHistoryList": {"chats": [{"title": "private"}]}},
        }
    )
    serialized = json.dumps(result)

    assert result["action"] == "GetConversationPageHistoryList"
    assert result["keys"] == ["action", "state", "syncState"]
    assert "private-sync" not in serialized
    assert "private" not in serialized


def test_conversation_id_from_url_reads_m365_path() -> None:
    conversation_id = conversation_id_from_url(
        "https://m365.cloud.microsoft/chat/conversation/"
        "fb3ec36a-e0b0-48b4-ba23-da634a582ae7"
    )

    assert conversation_id == "fb3ec36a-e0b0-48b4-ba23-da634a582ae7"


def test_normalize_sidebar_candidates_filters_navigation() -> None:
    candidates = normalize_sidebar_candidates(
        [
            {"text": "Novo chat", "x": 50, "y": 80},
            {"text": "Read the attached Word document", "x": 120, "y": 220},
            {"text": "Atualizar", "x": 120, "y": 720},
        ]
    )

    assert len(candidates) == 1
    assert candidates[0].text == "Read the attached Word document"
    assert ignored_sidebar_text("Pesquisar") is True
