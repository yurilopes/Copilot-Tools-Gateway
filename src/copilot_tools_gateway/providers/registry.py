"""Provider resolution for model names and automatic routing."""

from collections.abc import Iterable

from copilot_tools_gateway.domain.errors import ProviderUnavailableError
from copilot_tools_gateway.domain.models import ProviderId, ProviderStatus
from copilot_tools_gateway.providers.base import CopilotProvider


class ProviderRegistry:
    def __init__(self, providers: Iterable[CopilotProvider]) -> None:
        self._providers = {provider.provider_id: provider for provider in providers}

    def list_statuses(self) -> list[ProviderStatus]:
        return [provider.status() for provider in self._providers.values()]

    def resolve(self, model: str | ProviderId | None) -> CopilotProvider:
        provider_id = self._normalize_model(model)
        if provider_id == ProviderId.AUTO:
            return self._resolve_auto()
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ProviderUnavailableError(f"Unknown provider model: {provider_id.value}")
        status = provider.status()
        if not status.available:
            detail = f": {status.detail}" if status.detail else ""
            raise ProviderUnavailableError(f"Provider {provider_id.value} is unavailable{detail}")
        return provider

    def _resolve_auto(self) -> CopilotProvider:
        for provider_id in (ProviderId.M365, ProviderId.CONSUMER):
            provider = self._providers.get(provider_id)
            if provider is not None and provider.status().available:
                return provider
        raise ProviderUnavailableError("No configured Copilot provider is available")

    @staticmethod
    def _normalize_model(model: str | ProviderId | None) -> ProviderId:
        if model is None:
            return ProviderId.AUTO
        if isinstance(model, ProviderId):
            return model
        try:
            return ProviderId(model)
        except ValueError as exc:
            raise ProviderUnavailableError(f"Unknown model: {model}") from exc
