"""Provider contract for Copilot account families."""

from collections.abc import Iterator
from typing import Protocol

from copilot_tools_gateway.domain.models import (
    ChatResult,
    FileChatInput,
    GeneratedImage,
    ProviderCapabilities,
    ProviderId,
    ProviderStatus,
    VisionInput,
)


class CopilotProvider(Protocol):
    provider_id: ProviderId
    label: str
    capabilities: ProviderCapabilities

    def status(self) -> ProviderStatus:
        """Return a safe, normalized provider status."""

    def chat(self, prompt: str, conversation_id: str | None = None) -> ChatResult:
        """Return a complete chat response."""

    def stream(self, prompt: str, conversation_id: str | None = None) -> Iterator[str]:
        """Yield chat response chunks."""

    def generate_image(self, prompt: str, count: int = 1) -> list[GeneratedImage]:
        """Generate images and return safe URLs."""

    def describe_image(self, request: VisionInput) -> ChatResult:
        """Ask the provider to interpret an image."""

    def chat_with_files(self, request: FileChatInput) -> ChatResult:
        """Ask the provider to answer using local files as attachments."""
