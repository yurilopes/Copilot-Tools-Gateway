"""Application factory for providers and transports."""

from copilot_tools_gateway.providers.consumer.provider import ConsumerProvider
from copilot_tools_gateway.providers.m365.provider import M365Provider
from copilot_tools_gateway.providers.registry import ProviderRegistry
from copilot_tools_gateway.settings import GatewayPaths


def build_registry(paths: GatewayPaths | None = None) -> ProviderRegistry:
    active_paths = paths or GatewayPaths.from_cwd()
    return ProviderRegistry(
        providers=[
            M365Provider(token_file=active_paths.m365_token_file),
            ConsumerProvider(auth_file=active_paths.consumer_auth_file),
        ]
    )
