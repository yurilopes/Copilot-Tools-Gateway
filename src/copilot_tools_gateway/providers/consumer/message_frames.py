"""Consumer Copilot WebSocket message frame builders."""

import json
from collections.abc import Mapping
from enum import StrEnum
from typing import TypeAlias

from copilot_tools_gateway.domain.json_types import JsonValue
from copilot_tools_gateway.providers.consumer.protocol import set_options_frame

ConsumerContentPart: TypeAlias = dict[str, JsonValue]
ConsumerFrame: TypeAlias = dict[str, JsonValue]


class ConsumerImageSendCandidate(StrEnum):
    IMAGE_THEN_TEXT = "image-then-text"
    IMAGE_TEXT = "image-text"
    TEXT_IMAGE = "text-image"
    IMAGE_ONLY = "image-only"


DEFAULT_IMAGE_SEND_CANDIDATE = ConsumerImageSendCandidate.IMAGE_THEN_TEXT


def encoded_set_options_frame() -> bytes:
    return encode_frame(set_options_frame())


def encoded_consent_frame() -> bytes:
    return encode_frame(consent_frame())


def consent_frame() -> ConsumerFrame:
    return {
        "event": "reportLocalConsents",
        "grantedConsents": [],
    }


def send_frames_for_candidate(
    *,
    conversation_id: str,
    prompt: str,
    image_parts: list[ConsumerContentPart],
    candidate: ConsumerImageSendCandidate,
) -> list[ConsumerFrame]:
    text_part = text_content_part(prompt)
    if not image_parts:
        return [send_frame(conversation_id, [text_part])]
    if candidate == ConsumerImageSendCandidate.IMAGE_THEN_TEXT:
        return [
            send_frame(conversation_id, image_parts),
            send_frame(conversation_id, [text_part]),
        ]
    if candidate == ConsumerImageSendCandidate.IMAGE_TEXT:
        return [send_frame(conversation_id, [*image_parts, text_part])]
    if candidate == ConsumerImageSendCandidate.TEXT_IMAGE:
        return [send_frame(conversation_id, [text_part, *image_parts])]
    return [send_frame(conversation_id, image_parts)]


def send_frame(conversation_id: str, content: list[ConsumerContentPart]) -> ConsumerFrame:
    return {
        "event": "send",
        "conversationId": conversation_id,
        "content": content,
        "mode": "smart",
        "context": {},
    }


def text_content_part(prompt: str) -> ConsumerContentPart:
    return {"type": "text", "text": prompt}


def encode_frame(frame: Mapping[str, object]) -> bytes:
    return json.dumps(frame, separators=(",", ":")).encode("utf-8")
