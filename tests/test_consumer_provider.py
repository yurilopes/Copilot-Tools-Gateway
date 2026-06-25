import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from copilot_tools_gateway.domain.errors import UnsupportedCapabilityError
from copilot_tools_gateway.domain.models import FileChatInput, GeneratedImage, VisionInput
from copilot_tools_gateway.providers.consumer.auth import ConsumerAuth
from copilot_tools_gateway.providers.consumer.driver import ConsumerConversation
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


def test_consumer_file_chat_reuses_conversation_id(tmp_path) -> None:
    auth_file = tmp_path / "token.json"
    ConsumerAuth(
        cookies={"_U": "cookie"},
        access_token=None,
        saved_at=time.time(),
    ).save(auth_file)
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"image")
    driver = RecordingConsumerDriver()
    provider = ConsumerProvider(auth_file=auth_file)
    provider._driver = driver

    result = provider.chat_with_files(
        FileChatInput(
            prompt="describe it",
            file_paths=[str(image_path)],
            conversation_id="conversation-1",
        )
    )

    assert driver.conversation_id == "conversation-1"
    assert result.conversation_id == "conversation-1"
    assert result.text == "done"


def test_consumer_vision_reuses_conversation_id(tmp_path) -> None:
    auth_file = tmp_path / "token.json"
    ConsumerAuth(
        cookies={"_U": "cookie"},
        access_token=None,
        saved_at=time.time(),
    ).save(auth_file)
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"image")
    driver = RecordingConsumerDriver()
    provider = ConsumerProvider(auth_file=auth_file)
    provider._driver = driver

    result = provider.describe_image(
        VisionInput(
            prompt="describe it",
            image_path=str(image_path),
            conversation_id="conversation-2",
        )
    )

    assert driver.conversation_id == "conversation-2"
    assert result.conversation_id == "conversation-2"
    assert result.text == "done"


def test_consumer_chat_adds_context_for_reused_conversation_id(tmp_path) -> None:
    auth_file = tmp_path / "token.json"
    ConsumerAuth(
        cookies={"_U": "cookie"},
        access_token=None,
        saved_at=time.time(),
    ).save(auth_file)
    driver = RecordingConsumerDriver()
    provider = ConsumerProvider(auth_file=auth_file)
    provider._driver = driver

    provider.chat("remember CTG-MARKER", conversation_id="conversation-3")
    provider.chat("what did I ask you to remember?", conversation_id="conversation-3")

    assert driver.prompts[-1].startswith("Previous messages in this gateway conversation")
    assert "remember CTG-MARKER" in driver.prompts[-1]
    assert "what did I ask you to remember?" in driver.prompts[-1]


class RecordingConsumerDriver:
    def __init__(self) -> None:
        self.conversation_id: str | None = None
        self.prompts: list[str] = []

    def create_completion(
        self,
        prompt: str,
        cookies: dict[str, str],
        access_token: str | None,
        conversation_id: str | None,
        timeout_seconds: int,
        image_paths: list[Path] | None = None,
    ) -> Iterator[str | GeneratedImage | ConsumerConversation]:
        self.conversation_id = conversation_id
        self.prompts.append(prompt)
        yield "done"
