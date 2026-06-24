"""Domain models shared across providers and transports."""

from dataclasses import dataclass
from enum import StrEnum


class ProviderId(StrEnum):
    AUTO = "copilot-auto"
    M365 = "m365-copilot"
    CONSUMER = "copilot"


@dataclass(frozen=True)
class ProviderCapabilities:
    chat: bool
    streaming: bool
    image_generation: bool
    vision: bool
    file_chat: bool
    conversation_resume: bool


@dataclass(frozen=True)
class ProviderStatus:
    provider_id: ProviderId
    configured: bool
    available: bool
    label: str
    capabilities: ProviderCapabilities
    detail: str | None = None
    recommended_action: str | None = None
    recommended_command: list[str] | None = None


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ChatResult:
    text: str
    provider_id: ProviderId
    conversation_id: str | None = None


@dataclass(frozen=True)
class GeneratedImage:
    url: str
    provider_id: ProviderId
    prompt: str | None = None
    preview_url: str | None = None
    status: int | None = None


@dataclass(frozen=True)
class VisionInput:
    prompt: str
    image_path: str


@dataclass(frozen=True)
class FileChatInput:
    prompt: str
    file_paths: list[str]


def provider_model_ids() -> list[str]:
    return [ProviderId.AUTO.value, ProviderId.M365.value, ProviderId.CONSUMER.value]
