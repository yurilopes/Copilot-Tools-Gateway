import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from urllib.parse import parse_qs, urlsplit

from copilot_tools_gateway.domain.errors import UpstreamProtocolError
from copilot_tools_gateway.providers.m365 import unfurl as m365_unfurl
from copilot_tools_gateway.providers.m365.auth import M365Session
from copilot_tools_gateway.providers.m365.document_diagnostics import (
    document_annotation_url,
    safe_document_metadata_summary,
)
from copilot_tools_gateway.providers.m365.protocol import (
    IMAGE_ALLOWED_MESSAGE_TYPES,
    IMAGE_OPTION_SETS,
    RECORD_SEPARATOR,
    decode_signalr,
    final_text,
    image_file_annotation,
    is_final_update,
    local_file_annotation,
    text_delta,
    update_text,
)
from copilot_tools_gateway.providers.m365.provider import M365Provider
from copilot_tools_gateway.providers.m365.transport import chat_frame, socket_url
from copilot_tools_gateway.providers.m365.unfurl import unfurl_document_body
from copilot_tools_gateway.providers.m365.uploads import (
    M365DocumentAnnotation,
    M365ImageAnnotation,
    _sharepoint_document_id,
    _sharepoint_upload_headers,
)


def test_m365_provider_reports_conversation_resume() -> None:
    assert M365Provider.capabilities.conversation_resume is True


def test_m365_provider_reports_conversation_listing() -> None:
    assert M365Provider.capabilities.conversation_listing is True


def test_m365_provider_reports_real_streaming() -> None:
    assert M365Provider.capabilities.streaming is True


def test_update_text_reads_partial_and_final_updates() -> None:
    partial = {
        "target": "update",
        "arguments": [
            {
                "isLastUpdate": False,
                "messages": [{"author": "bot", "text": "Hello"}],
            }
        ],
    }
    final = {
        "target": "update",
        "arguments": [
            {
                "isLastUpdate": True,
                "messages": [{"author": "bot", "text": "Hello world"}],
            }
        ],
    }

    assert update_text(partial) == "Hello"
    assert final_text(partial) is None
    assert is_final_update(partial) is False
    assert update_text(final) == "Hello world"
    assert final_text(final) == "Hello world"
    assert is_final_update(final) is True


def test_text_delta_uses_cumulative_update_suffix() -> None:
    assert text_delta("Hello", "") == "Hello"
    assert text_delta("Hello world", "Hello") == " world"
    assert text_delta("Rewritten", "Hello") == "Rewritten"


def test_image_file_annotation_shape() -> None:
    annotation = image_file_annotation(
        M365ImageAnnotation(doc_id="doc-123", file_name="sample.png", file_type="png")
    )

    assert annotation == {
        "id": "doc-123",
        "messageAnnotationType": "ImageFile",
        "messageAnnotationMetadata": {
            "@type": "File",
            "annotationType": "File",
            "fileName": "sample.png",
            "fileType": "png",
        },
    }


def test_local_file_annotation_shape() -> None:
    annotation = local_file_annotation(
        M365DocumentAnnotation(
            doc_id="SPO_doc",
            url="https://example.invalid/doc",
            file_name="sample.docx",
        )
    )

    assert annotation == {
        "id": "SPO_doc",
        "messageAnnotationType": "LocalFile",
        "text": "sample.docx",
        "url": "https://example.invalid/doc",
    }


def test_sharepoint_document_id_uses_sharepoint_ids_and_decoded_item_id() -> None:
    item_bytes = b"item-bytes"
    site_id = "1" * 36
    web_id = "2" * 36
    list_id = "3" * 36
    item = {
        "id": urlsafe_b64encode(item_bytes).decode("ascii").rstrip("="),
        "sharepointIds": {
            "siteId": site_id,
            "webId": web_id,
            "listId": list_id,
        },
    }

    doc_id = _sharepoint_document_id(item)
    encoded = doc_id.removeprefix("SPO_")
    raw_value = urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))

    assert doc_id.startswith("SPO_")
    assert raw_value == f"{site_id},{web_id},{list_id}?".encode() + item_bytes


def test_sharepoint_document_id_preserves_original_item_id_encoding() -> None:
    item = {
        "id": "aXRlbS1ieXRlc1",
        "sharepointIds": {
            "siteId": "1" * 36,
            "webId": "2" * 36,
            "listId": "3" * 36,
        },
    }

    doc_id = _sharepoint_document_id(item)

    assert doc_id.endswith("aXRlbS1ieXRlc1")


def test_document_annotation_url_keeps_doc_aspx_url() -> None:
    item = {
        "webUrl": (
            "https://example.sharepoint.com/personal/user/_layouts/15/Doc.aspx"
            "?sourcedoc=%7Babc%7D&file=sample.docx&action=default&mobileredirect=true"
        )
    }

    assert document_annotation_url(item) == item["webUrl"]


def test_document_annotation_url_builds_doc_aspx_when_sharepoint_ids_exist() -> None:
    item = {
        "name": "sample.docx",
        "webUrl": "https://example.sharepoint.com/personal/user/Documents/sample.docx",
        "sharepointIds": {"listItemUniqueId": "11111111-1111-1111-1111-111111111111"},
    }

    assert document_annotation_url(item) == (
        "https://example.sharepoint.com/personal/user/_layouts/15/Doc.aspx"
        "?sourcedoc=%7B11111111-1111-1111-1111-111111111111%7D"
        "&file=sample.docx&action=default&mobileredirect=true"
    )


def test_sharepoint_upload_headers_request_text_extraction() -> None:
    headers = _sharepoint_upload_headers(123)

    assert "Content-Length" not in headers
    assert headers["Content-Range"] == "bytes 0-122/123"
    assert headers["Content-Type"] == "application/octet-stream"
    assert headers["Prefer"] == "ExtractTextOnCommit, pacToken=N"


def test_unfurl_document_body_uses_local_file_annotation() -> None:
    body = unfurl_document_body(
        M365DocumentAnnotation(
            doc_id="SPO_doc",
            url="https://example.invalid/doc",
            file_name="sample.docx",
        )
    )

    entity_requests = body["EntityRequests"]
    assert isinstance(entity_requests, list)
    request = entity_requests[0]
    assert isinstance(request, dict)
    annotations = request["QueryAnnotations"]
    assert isinstance(annotations, list)
    assert annotations[0] == {
        "Id": "SPO_doc",
        "Type": "LocalFile",
        "Text": "sample.docx",
        "Url": "https://example.invalid/doc",
    }
    assert body["CacheMode"] == "FireForget"


def test_try_unfurl_document_returns_false_on_upstream_failure(monkeypatch) -> None:
    def fail_unfurl(*args: object, **kwargs: object) -> None:
        raise UpstreamProtocolError("M365 document unfurl failed with HTTP 400")

    monkeypatch.setattr(m365_unfurl, "unfurl_document", fail_unfurl)
    session = M365Session(
        access_token="token",
        oid="user",
        tid="tenant",
        expires_at=2_000_000_000,
    )
    annotation = M365DocumentAnnotation(
        doc_id="SPO_doc",
        url="https://example.invalid/doc",
        file_name="sample.docx",
    )

    ok = m365_unfurl.try_unfurl_document(session, "search-token", annotation, 10)

    assert ok is False


def test_file_chat_protocol_lists_follow_ui_order() -> None:
    assert IMAGE_ALLOWED_MESSAGE_TYPES[:6] == [
        "Chat",
        "Suggestion",
        "InternalSearchQuery",
        "Disengaged",
        "InternalLoaderMessage",
        "Progress",
    ]
    assert IMAGE_ALLOWED_MESSAGE_TYPES[-2:] == [
        "ReferencesListComplete",
        "SwitchRespondingEndpoint",
    ]
    assert IMAGE_OPTION_SETS[:2] == [
        "search_result_progress_messages_with_search_queries",
        "update_textdoc_response_after_streaming",
    ]
    assert IMAGE_OPTION_SETS[-1] == "rich_responses"


def test_safe_document_metadata_summary_does_not_expose_raw_ids() -> None:
    item = {
        "id": "secret-item-id",
        "name": "sample.docx",
        "webUrl": "https://example.sharepoint.com/personal/user/Documents/sample.docx",
        "parentReference": {
            "siteId": "secret-site-id",
            "driveId": "secret-drive-id",
        },
        "sharepointIds": {"listItemUniqueId": "secret-list-id"},
    }

    summary = safe_document_metadata_summary(item)

    assert summary.has_web_url is True
    assert summary.has_parent_reference is True
    assert summary.has_sharepoint_ids is True
    assert summary.site_id.present is True
    assert summary.site_id.length == len("secret-site-id")
    assert summary.site_id.digest != "secret-site-id"
    assert summary.drive_id.digest != "secret-drive-id"
    assert summary.item_id.digest != "secret-item-id"
    assert summary.list_item_unique_id.digest != "secret-list-id"


def test_chat_frame_includes_message_annotations() -> None:
    payload = chat_frame(
        prompt="Describe this image",
        session_id="11111111-1111-1111-1111-111111111111",
        option_sets=["chat-option"],
        allowed_message_types=["Chat"],
        message_annotations=[
            image_file_annotation(
                M365ImageAnnotation(doc_id="doc-123", file_name="sample.png", file_type="png")
            ),
            local_file_annotation(
                M365DocumentAnnotation(
                    doc_id="SPO_doc",
                    url="https://example.invalid/doc",
                    file_name="sample.docx",
                )
            ),
        ],
    )

    frames = list(decode_signalr(payload))

    assert payload.endswith(RECORD_SEPARATOR)
    assert len(frames) == 1
    frame = frames[0]
    assert frame["target"] == "chat"
    arguments = frame["arguments"]
    assert isinstance(arguments, list)
    message = arguments[0]["message"]
    assert isinstance(message, dict)
    assert message["text"] == "Describe this image"
    assert message["messageAnnotations"] == [
        {
            "id": "doc-123",
            "messageAnnotationType": "ImageFile",
            "messageAnnotationMetadata": {
                "@type": "File",
                "annotationType": "File",
                "fileName": "sample.png",
                "fileType": "png",
            },
        },
        {
            "id": "SPO_doc",
            "messageAnnotationType": "LocalFile",
            "text": "sample.docx",
            "url": "https://example.invalid/doc",
        },
    ]


def test_chat_frame_is_valid_json_record() -> None:
    payload = chat_frame(
        prompt="Hello",
        session_id="11111111-1111-1111-1111-111111111111",
        option_sets=["chat-option"],
        allowed_message_types=["Chat"],
    )

    value = json.loads(payload.removesuffix(RECORD_SEPARATOR))

    assert value["type"] == 4
    assert value["target"] == "chat"


def test_chat_frame_uses_compact_request_id() -> None:
    payload = chat_frame(
        prompt="Hello",
        session_id="11111111-1111-1111-1111-111111111111",
        option_sets=["chat-option"],
        allowed_message_types=["Chat"],
    )

    value = json.loads(payload.removesuffix(RECORD_SEPARATOR))
    message = value["arguments"][0]["message"]

    assert message["requestId"] == "11111111111111111111111111111111"


def test_socket_url_uses_compact_session_query_ids() -> None:
    session = M365Session(
        access_token="token",
        oid="user",
        tid="tenant",
        expires_at=2_000_000_000,
    )

    url = socket_url(
        session=session,
        session_id="11111111-2222-4333-8444-555555555555",
        conversation_id="66666666-7777-4888-9999-000000000000",
    )
    values = parse_qs(urlsplit(url).query)

    assert values["chatsessionid"] == ["11111111222243338444555555555555"]
    assert values["XRoutingParameterSessionKey"] == ["11111111222243338444555555555555"]
    assert values["clientrequestid"] == ["11111111222243338444555555555555"]
    assert values["X-SessionId"] == ["11111111-2222-4333-8444-555555555555"]
    assert values["ConversationId"] == ["66666666-7777-4888-9999-000000000000"]
    assert "feature.EnableClientFileURLSupportForOfficeWebPaidCopilot" in values["variants"][0]
