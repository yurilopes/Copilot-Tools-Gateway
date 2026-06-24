import time

import pytest

from copilot_tools_gateway.domain.errors import UnsupportedCapabilityError
from copilot_tools_gateway.domain.models import FileChatInput
from copilot_tools_gateway.providers.consumer.auth import ConsumerAuth
from copilot_tools_gateway.providers.consumer.provider import (
    CONSUMER_REFRESH_COMMAND,
    CONSUMER_STALE_SESSION_MESSAGE,
    ConsumerProvider,
)


def test_consumer_status_recommends_login_when_session_is_missing(tmp_path) -> None:
    provider = ConsumerProvider(auth_file=tmp_path / "token.json")

    status = provider.status()

    assert status.available is False
    assert status.configured is False
    assert status.recommended_action == "login_session"
    assert status.recommended_command == [
        "python",
        "-m",
        "copilot_tools_gateway",
        "login",
        "consumer",
    ]


def test_consumer_status_recommends_refresh_when_session_is_stale(tmp_path) -> None:
    auth_file = tmp_path / "token.json"
    ConsumerAuth(
        cookies={"_U": "cookie"},
        access_token=None,
        saved_at=0.0,
    ).save(auth_file)
    provider = ConsumerProvider(auth_file=auth_file)

    status = provider.status()

    assert status.available is False
    assert status.configured is True
    assert status.detail == "Consumer session is stale"
    assert status.recommended_action == "refresh_session"
    assert status.recommended_command == CONSUMER_REFRESH_COMMAND


def test_consumer_chat_recommends_guided_refresh_when_session_is_stale(tmp_path) -> None:
    auth_file = tmp_path / "token.json"
    ConsumerAuth(
        cookies={"_U": "cookie"},
        access_token=None,
        saved_at=0.0,
    ).save(auth_file)
    provider = ConsumerProvider(auth_file=auth_file)

    with pytest.raises(UnsupportedCapabilityError) as exc_info:
        provider.chat("hello")

    assert str(exc_info.value) == CONSUMER_STALE_SESSION_MESSAGE
    assert "refresh consumer" in str(exc_info.value)
    assert "send a normal browser message" in str(exc_info.value)
    assert "cookies" not in str(exc_info.value).lower()
    assert "tokens" not in str(exc_info.value).lower()


def test_consumer_status_available_for_fresh_session(tmp_path) -> None:
    auth_file = tmp_path / "token.json"
    ConsumerAuth(
        cookies={"_U": "cookie"},
        access_token=None,
        saved_at=time.time(),
    ).save(auth_file)
    provider = ConsumerProvider(auth_file=auth_file)

    status = provider.status()

    assert status.available is True
    assert status.recommended_action is None
    assert status.recommended_command is None


def test_consumer_status_reports_image_file_chat_capability(tmp_path) -> None:
    auth_file = tmp_path / "token.json"
    ConsumerAuth(
        cookies={"_U": "cookie"},
        access_token=None,
        saved_at=time.time(),
    ).save(auth_file)
    provider = ConsumerProvider(auth_file=auth_file)

    status = provider.status()

    assert status.capabilities.vision is True
    assert status.capabilities.file_chat is True


def test_consumer_file_chat_rejects_non_image_attachments(tmp_path) -> None:
    auth_file = tmp_path / "token.json"
    ConsumerAuth(
        cookies={"_U": "cookie"},
        access_token=None,
        saved_at=time.time(),
    ).save(auth_file)
    docx_path = tmp_path / "document.docx"
    docx_path.write_bytes(b"docx")
    provider = ConsumerProvider(auth_file=auth_file)

    with pytest.raises(UnsupportedCapabilityError) as exc_info:
        provider.chat_with_files(FileChatInput(prompt="read it", file_paths=[str(docx_path)]))

    assert "image attachments only" in str(exc_info.value)
    assert "document.docx" in str(exc_info.value)
