"""Domain-specific gateway errors."""


class GatewayError(Exception):
    """Base class for internal gateway errors."""


class ProviderUnavailableError(GatewayError):
    """Raised when a requested provider is not configured or cannot be used."""


class UnsupportedCapabilityError(GatewayError):
    """Raised when a provider does not support a requested operation."""


class UpstreamProtocolError(GatewayError):
    """Raised when a provider returns an unexpected upstream protocol shape."""


class SessionExpiredError(ProviderUnavailableError):
    """Raised when a stored provider session is no longer usable."""


class LoginFailedError(GatewayError):
    """Raised when an interactive login cannot capture a usable session."""
