from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from copilot_tools_gateway.domain.errors import ProviderUnavailableError, UnsupportedCapabilityError
from copilot_tools_gateway.domain.models import (
    ChatResult,
    ConversationListResult,
    FileChatInput,
    GeneratedImage,
    ProviderCapabilities,
    ProviderId,
    ProviderStatus,
    VisionInput,
)
from copilot_tools_gateway.mcp_server import _resolve_conversation_listing_provider
from copilot_tools_gateway.providers.registry import ProviderRegistry


@dataclass
class FakeProvider:
    provider_id: ProviderId
    available: bool
    recommended_command: list[str] | None = None

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
            detail="fake unavailable" if not self.available else None,
            recommended_action="login_session" if self.recommended_command else None,
            recommended_command=self.recommended_command,
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

    def list_conversations(
        self,
        limit: int = 20,
        cursor: str | None = None,
    ) -> ConversationListResult:
        return ConversationListResult(conversations=[], count=0, has_more=False)


@dataclass
class ListingFakeProvider(FakeProvider):
    conversation_listing: bool = False

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            chat=True,
            streaming=True,
            image_generation=False,
            vision=False,
            file_chat=False,
            conversation_resume=False,
            conversation_listing=self.conversation_listing,
        )


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


def test_explicit_unavailable_provider_includes_recommended_command() -> None:
    registry = ProviderRegistry(
        [
            FakeProvider(
                ProviderId.M365,
                available=False,
                recommended_command=["python", "-m", "copilot_tools_gateway", "login", "m365"],
            )
        ]
    )

    with pytest.raises(ProviderUnavailableError) as exc_info:
        registry.resolve("m365-copilot")

    assert "Run: python -m copilot_tools_gateway login m365" in str(exc_info.value)


def test_auto_unavailable_provider_includes_first_recommended_command() -> None:
    registry = ProviderRegistry(
        [
            FakeProvider(
                ProviderId.M365,
                available=False,
                recommended_command=["python", "-m", "copilot_tools_gateway", "refresh", "m365"],
            ),
            FakeProvider(
                ProviderId.CONSUMER,
                available=False,
                recommended_command=["python", "-m", "copilot_tools_gateway", "login", "consumer"],
            ),
        ]
    )

    with pytest.raises(ProviderUnavailableError) as exc_info:
        registry.resolve("copilot-auto")

    assert "Run: python -m copilot_tools_gateway refresh m365" in str(exc_info.value)


def test_conversation_listing_auto_uses_available_provider_with_capability() -> None:
    registry = ProviderRegistry(
        [
            ListingFakeProvider(ProviderId.M365, available=True, conversation_listing=False),
            ListingFakeProvider(ProviderId.CONSUMER, available=True, conversation_listing=True),
        ]
    )

    provider = _resolve_conversation_listing_provider(registry, ProviderId.AUTO.value)

    assert provider.provider_id == ProviderId.CONSUMER
