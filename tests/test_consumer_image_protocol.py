import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from copilot_tools_gateway.domain.errors import UpstreamProtocolError
from copilot_tools_gateway.domain.models import FileChatInput, GeneratedImage
from copilot_tools_gateway.providers.consumer.auth import ConsumerAuth
from copilot_tools_gateway.providers.consumer.driver import ConsumerConversation
from copilot_tools_gateway.providers.consumer.message_frames import (
    ConsumerImageSendCandidate,
    send_frames_for_candidate,
)
from copilot_tools_gateway.providers.consumer.provider import ConsumerProvider
from copilot_tools_gateway.providers.consumer.vision_failures import (
    consumer_image_response_is_unreadable,
)
from copilot_tools_gateway.settings import GatewayPaths
from tools.diagnostics.check_consumer_image_protocol_v2 import safe_error

IMAGE_PART = {"type": "image", "url": "/images/uploaded.png", "fileName": "image.png"}


def test_image_send_candidate_image_text_shape() -> None:
    frames = send_frames_for_candidate(
        conversation_id="conversation-1",
        prompt="Read it",
        image_parts=[IMAGE_PART],
        candidate=ConsumerImageSendCandidate.IMAGE_TEXT,
    )

    assert len(frames) == 1
    assert frames[0]["content"] == [
        IMAGE_PART,
        {"type": "text", "text": "Read it"},
    ]


def test_image_send_candidate_image_then_text_shape() -> None:
    frames = send_frames_for_candidate(
        conversation_id="conversation-1",
        prompt="Read it",
        image_parts=[IMAGE_PART],
        candidate=ConsumerImageSendCandidate.IMAGE_THEN_TEXT,
    )

    assert len(frames) == 2
    assert frames[0]["content"] == [IMAGE_PART]
    assert frames[1]["content"] == [{"type": "text", "text": "Read it"}]


def test_image_send_candidate_text_image_shape() -> None:
    frames = send_frames_for_candidate(
        conversation_id="conversation-1",
        prompt="Read it",
        image_parts=[IMAGE_PART],
        candidate=ConsumerImageSendCandidate.TEXT_IMAGE,
    )

    assert len(frames) == 1
    assert frames[0]["content"] == [
        {"type": "text", "text": "Read it"},
        IMAGE_PART,
    ]


def test_image_send_candidate_image_only_shape() -> None:
    frames = send_frames_for_candidate(
        conversation_id="conversation-1",
        prompt="Read it",
        image_parts=[IMAGE_PART],
        candidate=ConsumerImageSendCandidate.IMAGE_ONLY,
    )

    assert len(frames) == 1
    assert frames[0]["content"] == [IMAGE_PART]


def test_unreadable_image_classifier_does_not_reject_placeholder_description() -> None:
    text = "The image is a placeholder labeled CTG_ATTACH_IMAGE_1 on a white background."

    assert consumer_image_response_is_unreadable(text) is False


def test_unreadable_image_classifier_catches_vision_failure() -> None:
    text = "I can't directly read or extract text from an image right now."

    assert consumer_image_response_is_unreadable(text) is True


def test_provider_uses_browser_fallback_for_unreadable_direct_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_file = tmp_path / "token.json"
    ConsumerAuth(cookies={"_U": "cookie"}, access_token=None, saved_at=time.time()).save(auth_file)
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"image")
    provider = ConsumerProvider(
        auth_file=auth_file,
        paths=GatewayPaths.from_cwd(tmp_path),
    )
    provider._driver = StaticConsumerDriver(
        "I can't directly read or extract text from an image right now."
    )
    monkeypatch.setattr(
        "copilot_tools_gateway.providers.consumer.provider.run_browser_image_chat",
        lambda prompt, paths, gateway_paths: "The image says CTG_ATTACH_IMAGE_1.",
    )

    result = provider.chat_with_files(
        FileChatInput(prompt="read it", file_paths=[str(image_path)])
    )

    assert result.text == "The image says CTG_ATTACH_IMAGE_1."
    assert result.metadata == {
        "attachment_backend": "browser-assisted",
        "direct_attempted": True,
        "fallback_used": True,
    }


def test_provider_uses_browser_fallback_for_direct_protocol_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_file = tmp_path / "token.json"
    ConsumerAuth(cookies={"_U": "cookie"}, access_token=None, saved_at=time.time()).save(auth_file)
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"image")
    provider = ConsumerProvider(
        auth_file=auth_file,
        paths=GatewayPaths.from_cwd(tmp_path),
    )
    provider._driver = RaisingConsumerDriver()
    monkeypatch.setattr(
        "copilot_tools_gateway.providers.consumer.provider.run_browser_image_chat",
        lambda prompt, paths, gateway_paths: "The image says CTG_ATTACH_IMAGE_1.",
    )

    result = provider.chat_with_files(
        FileChatInput(prompt="read it", file_paths=[str(image_path)])
    )

    assert result.metadata == {
        "attachment_backend": "browser-assisted",
        "direct_attempted": True,
        "fallback_used": True,
    }


def test_provider_returns_direct_metadata_when_direct_image_is_readable(
    tmp_path: Path,
) -> None:
    auth_file = tmp_path / "token.json"
    ConsumerAuth(cookies={"_U": "cookie"}, access_token=None, saved_at=time.time()).save(auth_file)
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"image")
    provider = ConsumerProvider(
        auth_file=auth_file,
        paths=GatewayPaths.from_cwd(tmp_path),
    )
    provider._driver = StaticConsumerDriver("The image says CTG_ATTACH_IMAGE_1.")

    result = provider.chat_with_files(
        FileChatInput(prompt="read it", file_paths=[str(image_path)])
    )

    assert result.metadata == {
        "attachment_backend": "direct-websocket",
        "direct_attempted": True,
        "fallback_used": False,
    }


def test_diagnostic_safe_error_does_not_include_sensitive_values() -> None:
    summary = safe_error(RuntimeError("token cookie authorization raw request"))
    serialized = str(summary).lower()

    assert summary["code"] == "upstream_error"
    assert "token" not in serialized
    assert "cookie" not in serialized
    assert "authorization" not in serialized
    assert "raw request" not in serialized


def test_diagnostic_safe_error_classifies_browser_challenge() -> None:
    summary = safe_error(RuntimeError("Run refresh consumer after browser challenge"))

    assert summary["code"] == "browser_challenge"


class StaticConsumerDriver:
    def __init__(self, text: str) -> None:
        self._text = text

    def create_completion(
        self,
        prompt: str,
        cookies: dict[str, str],
        access_token: str | None,
        conversation_id: str | None,
        timeout_seconds: int,
        image_paths: list[Path] | None = None,
    ) -> Iterator[str | GeneratedImage | ConsumerConversation]:
        yield ConsumerConversation("conversation-1")
        yield self._text


class RaisingConsumerDriver:
    def create_completion(
        self,
        prompt: str,
        cookies: dict[str, str],
        access_token: str | None,
        conversation_id: str | None,
        timeout_seconds: int,
        image_paths: list[Path] | None = None,
    ) -> Iterator[str | GeneratedImage | ConsumerConversation]:
        raise UpstreamProtocolError("Consumer image upload failed")
        yield "unreachable"
