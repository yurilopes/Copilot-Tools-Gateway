from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from copilot_tools_gateway.domain.errors import ProviderUnavailableError, UnsupportedCapabilityError
from copilot_tools_gateway.domain.models import (
    ChatResult,
    FileChatInput,
    GeneratedImage,
    ProviderCapabilities,
    ProviderId,
    ProviderStatus,
    VisionInput,
)
from copilot_tools_gateway.providers.registry import ProviderRegistry


@dataclass
class FakeProvider:
    provider_id: ProviderId
    available: bool

    label = "Fake"
    capabilities = ProviderCapabilities(
        chat=True,
        streaming=True,
        image_generation=False,
        vision=False,
        file_chat=False,
        conversation_resume=False,
    )

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider_id=self.provider_id,
            configured=self.available,
            available=self.available,
            label=self.label,
            capabilities=self.capabilities,
        )

    def chat(self, prompt: str, conversation_id: str | None = None) -> ChatResult:
        return ChatResult(
            text=prompt,
            provider_id=self.provider_id,
            conversation_id=conversation_id,
        )

    def stream(self, prompt: str, conversation_id: str | None = None) -> Iterator[str]:
        yield prompt

    def generate_image(self, prompt: str, count: int = 1) -> list[GeneratedImage]:
        raise UnsupportedCapabilityError("not supported")

    def describe_image(self, request: VisionInput) -> ChatResult:
        raise UnsupportedCapabilityError("not supported")

    def chat_with_files(self, request: FileChatInput) -> ChatResult:
        raise UnsupportedCapabilityError("not supported")


def test_auto_prefers_m365_when_available() -> None:
    registry = ProviderRegistry(
        [
            FakeProvider(ProviderId.M365, available=True),
            FakeProvider(ProviderId.CONSUMER, available=True),
        ]
    )

    provider = registry.resolve(ProviderId.AUTO)

    assert provider.provider_id == ProviderId.M365


def test_auto_uses_consumer_when_m365_unavailable() -> None:
    registry = ProviderRegistry(
        [
            FakeProvider(ProviderId.M365, available=False),
            FakeProvider(ProviderId.CONSUMER, available=True),
        ]
    )

    provider = registry.resolve("copilot-auto")

    assert provider.provider_id == ProviderId.CONSUMER


def test_explicit_unavailable_provider_fails() -> None:
    registry = ProviderRegistry([FakeProvider(ProviderId.M365, available=False)])

    with pytest.raises(ProviderUnavailableError):
        registry.resolve("m365-copilot")
