"""Interactive login flows for supported Copilot providers."""

from pathlib import Path

from copilot_tools_gateway.providers.consumer.assisted_auth import (
    CONSUMER_REFRESH_STEPS,
    format_browser_steps,
)
from copilot_tools_gateway.providers.consumer.assisted_auth import (
    login_consumer as _login_consumer,
)
from copilot_tools_gateway.providers.consumer.assisted_auth import (
    refresh_consumer as _refresh_consumer,
)
from copilot_tools_gateway.providers.m365.assisted_auth import login_m365 as _login_m365
from copilot_tools_gateway.providers.m365.assisted_auth import refresh_m365 as _refresh_m365
from copilot_tools_gateway.settings import GatewayPaths

__all__ = [
    "CONSUMER_REFRESH_STEPS",
    "login_consumer",
    "login_m365",
    "refresh_consumer",
    "refresh_m365",
]


def login_consumer(paths: GatewayPaths) -> Path:
    return _login_consumer(paths)


def refresh_consumer(paths: GatewayPaths) -> Path:
    return _refresh_consumer(paths)


def login_m365(paths: GatewayPaths) -> Path:
    return _login_m365(paths)


def refresh_m365(paths: GatewayPaths) -> Path:
    return _refresh_m365(paths)


def _format_browser_steps(title: str, steps: tuple[str, ...], prompt: str) -> str:
    return format_browser_steps(title, steps, prompt)
