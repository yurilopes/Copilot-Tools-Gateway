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
            run = _recommended_command_text(status.recommended_command)
            raise ProviderUnavailableError(
                f"Provider {provider_id.value} is unavailable{detail}{run}"
            )
        return provider

    def _resolve_auto(self) -> CopilotProvider:
        first_unavailable: ProviderStatus | None = None
        for provider_id in (ProviderId.M365, ProviderId.CONSUMER):
            provider = self._providers.get(provider_id)
            if provider is None:
                continue
            status = provider.status()
            if status.available:
                return provider
            if first_unavailable is None:
                first_unavailable = status
        run = _recommended_command_text(
            first_unavailable.recommended_command if first_unavailable is not None else None
        )
        raise ProviderUnavailableError(f"No configured Copilot provider is available{run}")

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


def _recommended_command_text(command: list[str] | None) -> str:
    if command is None:
        return ""
    return f". Run: {' '.join(command)}"
