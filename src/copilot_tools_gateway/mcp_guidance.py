"""Agent guidance for MCP response envelopes."""

from dataclasses import dataclass

from copilot_tools_gateway.domain.errors import (
    GatewayError,
    ProviderUnavailableError,
    SessionExpiredError,
    UnsupportedCapabilityError,
    UpstreamProtocolError,
)
from copilot_tools_gateway.domain.models import ProviderId, ProviderStatus, provider_model_ids

ACTION_NONE = "none"
ACTION_LOGIN_SESSION = "login_session"
ACTION_REFRESH_SESSION = "refresh_session"
ACTION_BROWSER_WARMUP = "browser_warmup"
ACTION_RETRY = "retry"
ACTION_USE_DIFFERENT_PROVIDER = "use_different_provider"
ACTION_UNSUPPORTED_CAPABILITY = "unsupported_capability"

ERROR_PROVIDER_UNAVAILABLE = "provider_unavailable"
ERROR_SESSION_EXPIRED = "session_expired"
ERROR_UNSUPPORTED_CAPABILITY = "unsupported_capability"
ERROR_UPSTREAM_PROTOCOL = "upstream_protocol_error"
ERROR_LOGIN_REQUIRED = "login_required"
ERROR_REFRESH_REQUIRED = "refresh_required"
ERROR_UNKNOWN_MODEL = "unknown_model"

SENSITIVE_TERMS = (
    "authorization",
    "browser storage",
    "cookie",
    "cookies",
    "raw request",
    "raw requests",
    "token",
    "tokens",
)


@dataclass(frozen=True)
class AgentGuidance:
    summary: str
    user_message: str
    recommended_action: str
    recommended_command: list[str] | None
    retryable: bool
    retry_after_action: bool
    next_steps: list[str]


def error_code(exc: GatewayError) -> str:
    detail = str(exc).lower()
    if isinstance(exc, SessionExpiredError):
        return ERROR_SESSION_EXPIRED
    if isinstance(exc, UnsupportedCapabilityError):
        return ERROR_UNSUPPORTED_CAPABILITY
    if isinstance(exc, UpstreamProtocolError):
        return ERROR_UPSTREAM_PROTOCOL
    if isinstance(exc, ProviderUnavailableError):
        if "unknown model" in detail or "unknown provider model" in detail:
            return ERROR_UNKNOWN_MODEL
        if "not configured" in detail or "not found" in detail:
            return ERROR_LOGIN_REQUIRED
        if "expired" in detail or "invalid" in detail or "empty" in detail:
            return ERROR_REFRESH_REQUIRED
        return ERROR_PROVIDER_UNAVAILABLE
    return ERROR_UPSTREAM_PROTOCOL


def error_message(code: str) -> str:
    messages = {
        ERROR_PROVIDER_UNAVAILABLE: "Provider is unavailable.",
        ERROR_SESSION_EXPIRED: "Provider session expired.",
        ERROR_UNSUPPORTED_CAPABILITY: "Provider does not support this capability.",
        ERROR_UPSTREAM_PROTOCOL: "Provider returned an unexpected upstream response.",
        ERROR_LOGIN_REQUIRED: "Provider login is required.",
        ERROR_REFRESH_REQUIRED: "Provider refresh is required.",
        ERROR_UNKNOWN_MODEL: "Unknown model was requested.",
    }
    return messages.get(code, "Gateway request failed.")


def safe_detail(
    code: str,
    exc: GatewayError,
    status: ProviderStatus | None,
) -> str:
    if code == ERROR_UNKNOWN_MODEL:
        return f"Valid models are: {', '.join(provider_model_ids())}."
    if code == ERROR_REFRESH_REQUIRED and mentions_m365_document_auth(str(exc)):
        return "M365 document access needs refresh."
    if status is not None and status.detail:
        return sanitize_text(status.detail) or error_message(code)
    return sanitize_text(str(exc)) or error_message(code)


def error_agent(
    code: str,
    model_requested: str | None,
    exc: GatewayError,
    status: ProviderStatus | None,
) -> AgentGuidance:
    if code == ERROR_UNKNOWN_MODEL:
        return AgentGuidance(
            summary="The requested Copilot model is not supported.",
            user_message=f"Choose one of these models: {', '.join(provider_model_ids())}.",
            recommended_action=ACTION_UNSUPPORTED_CAPABILITY,
            recommended_command=None,
            retryable=False,
            retry_after_action=False,
            next_steps=["Retry with copilot-auto, m365-copilot, or copilot."],
        )
    if code == ERROR_UNSUPPORTED_CAPABILITY:
        return _unsupported_capability_agent(model_requested, exc)
    if code == ERROR_UPSTREAM_PROTOCOL and mentions_consumer_challenge(str(exc)):
        return consumer_warmup_agent()
    if code in {ERROR_LOGIN_REQUIRED, ERROR_PROVIDER_UNAVAILABLE}:
        return _provider_action_agent(status, ACTION_LOGIN_SESSION)
    if code in {ERROR_SESSION_EXPIRED, ERROR_REFRESH_REQUIRED}:
        if status is not None and status.provider_id == ProviderId.CONSUMER:
            return consumer_warmup_agent()
        return _provider_action_agent(status, ACTION_REFRESH_SESSION)
    return AgentGuidance(
        summary="The provider request failed.",
        user_message="Copilot Tools Gateway could not complete the request.",
        recommended_action=ACTION_RETRY,
        recommended_command=None,
        retryable=True,
        retry_after_action=False,
        next_steps=["Call copilot_status if the failure repeats."],
    )


def top_status_recommendation(statuses: list[ProviderStatus]) -> dict[str, object]:
    available = [status for status in statuses if status.available]
    if available:
        preferred = preferred_status(available)
        if preferred is None:
            return _default_login_recommendation()
        return {
            "summary": f"{preferred.label} is available.",
            "recommended_provider": preferred.provider_id.value,
            "recommended_action": ACTION_NONE,
            "recommended_command": None,
        }
    actionable = preferred_status([status for status in statuses if status.recommended_action])
    if actionable is not None:
        return {
            "summary": f"{actionable.label} needs {actionable.recommended_action}.",
            "recommended_provider": actionable.provider_id.value,
            "recommended_action": actionable.recommended_action,
            "recommended_command": actionable.recommended_command,
        }
    return _default_login_recommendation()


def _default_login_recommendation() -> dict[str, object]:
    return {
        "summary": "No provider is currently available.",
        "recommended_provider": None,
        "recommended_action": ACTION_LOGIN_SESSION,
        "recommended_command": ["python", "-m", "copilot_tools_gateway", "login", "m365"],
    }


def preferred_status(statuses: list[ProviderStatus]) -> ProviderStatus | None:
    by_id = {status.provider_id: status for status in statuses}
    return by_id.get(ProviderId.M365) or by_id.get(ProviderId.CONSUMER)


def status_next_steps(recommendation: dict[str, object]) -> list[str]:
    action = recommendation["recommended_action"]
    command = command_or_none(recommendation["recommended_command"])
    if action == ACTION_NONE:
        return ["Use copilot-auto, or choose a specific provider model when needed."]
    if command is not None:
        return [
            "Run the recommended local command.",
            "Complete any browser sign-in or challenge steps if a browser opens.",
            "Call copilot_status again before retrying the original tool.",
        ]
    return ["Configure at least one Copilot provider and call copilot_status again."]


def select_status(
    model_requested: str | None,
    statuses: list[ProviderStatus],
    provider: ProviderId | None,
) -> ProviderStatus | None:
    if provider is not None:
        return find_status(statuses, provider)
    if model_requested == ProviderId.M365.value:
        return find_status(statuses, ProviderId.M365)
    if model_requested == ProviderId.CONSUMER.value:
        return find_status(statuses, ProviderId.CONSUMER)
    return preferred_status([status for status in statuses if not status.available])


def find_status(statuses: list[ProviderStatus], provider_id: ProviderId) -> ProviderStatus | None:
    return next((status for status in statuses if status.provider_id == provider_id), None)


def error_provider(provider: ProviderId | None, status: ProviderStatus | None) -> str | None:
    if provider is not None:
        return provider.value
    if status is not None:
        return status.provider_id.value
    return None


def command_or_none(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    if all(isinstance(item, str) for item in value):
        return value.copy()
    return None


def mentions_consumer_challenge(detail: str) -> bool:
    lowered = detail.lower()
    markers = ("challenge", "chat-service-unavailable", "cloudflare")
    return any(marker in lowered for marker in markers)


def mentions_m365_document_auth(detail: str) -> bool:
    lowered = detail.lower()
    return "graph token" in lowered or "search token" in lowered


def sanitize_text(value: str | None) -> str | None:
    if value is None:
        return None
    sanitized = value
    for term in SENSITIVE_TERMS:
        sanitized = sanitized.replace(term, "credential")
        sanitized = sanitized.replace(term.title(), "Credential")
        sanitized = sanitized.replace(term.upper(), "CREDENTIAL")
    return sanitized


def consumer_warmup_agent() -> AgentGuidance:
    return AgentGuidance(
        summary="Consumer Copilot needs browser warm-up before retrying.",
        user_message=(
            "Consumer Copilot needs a browser warm-up. Run refresh consumer, complete any "
            "browser challenge, send one normal browser message, wait for the answer, then retry."
        ),
        recommended_action=ACTION_BROWSER_WARMUP,
        recommended_command=["python", "-m", "copilot_tools_gateway", "refresh", "consumer"],
        retryable=True,
        retry_after_action=True,
        next_steps=[
            "Run the recommended refresh command.",
            "Complete any browser challenge.",
            "Send one normal message in the browser and wait for Copilot to answer.",
            "Retry the original MCP tool call.",
        ],
    )


def _unsupported_capability_agent(
    model_requested: str | None,
    exc: GatewayError,
) -> AgentGuidance:
    detail = str(exc).lower()
    if model_requested == ProviderId.CONSUMER.value and "image attachments only" in detail:
        return AgentGuidance(
            summary="Consumer Copilot does not support document attachments here.",
            user_message=(
                "The consumer Copilot provider supports PNG and JPEG attachments only. "
                "Use m365-copilot for document attachments."
            ),
            recommended_action=ACTION_USE_DIFFERENT_PROVIDER,
            recommended_command=None,
            retryable=False,
            retry_after_action=False,
            next_steps=["Retry the file request with model m365-copilot."],
        )
    return AgentGuidance(
        summary="The selected provider does not support this tool request.",
        user_message="This Copilot provider does not support the requested capability.",
        recommended_action=ACTION_UNSUPPORTED_CAPABILITY,
        recommended_command=None,
        retryable=False,
        retry_after_action=False,
        next_steps=["Call copilot_status and choose a provider with the needed capability."],
    )


def _provider_action_agent(
    status: ProviderStatus | None,
    fallback_action: str,
) -> AgentGuidance:
    provider_name = status.label if status is not None else "Copilot"
    action = status.recommended_action if status is not None else fallback_action
    command = status.recommended_command if status is not None else None
    return AgentGuidance(
        summary=f"{provider_name} is not ready.",
        user_message=f"{provider_name} needs {action} before this request can run.",
        recommended_action=action or fallback_action,
        recommended_command=command,
        retryable=True,
        retry_after_action=True,
        next_steps=_action_next_steps(command),
    )


def _action_next_steps(command: list[str] | None) -> list[str]:
    if command is None:
        return ["Call copilot_status for provider setup guidance before retrying."]
    return [
        "Run the recommended local command.",
        "Complete any browser sign-in or challenge steps if requested.",
        "Retry the original MCP tool call after the command succeeds.",
    ]
