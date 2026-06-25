"""Structured MCP response envelopes for agent clients."""

from copilot_tools_gateway.domain.errors import GatewayError
from copilot_tools_gateway.domain.models import (
    ConversationListResult,
    ProviderCapabilities,
    ProviderId,
    ProviderStatus,
    provider_model_ids,
)
from copilot_tools_gateway.mcp_guidance import (
    AgentGuidance,
    command_or_none,
    error_agent,
    error_code,
    error_message,
    error_provider,
    safe_detail,
    sanitize_text,
    select_status,
    status_next_steps,
    top_status_recommendation,
)

MCP_RESPONSE_SCHEMA_VERSION = "mcp-response/v2"


def mcp_success(
    *,
    tool: str,
    model_requested: str | None,
    provider: ProviderId | None,
    result: dict[str, object],
    agent: AgentGuidance,
    diagnostics: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": MCP_RESPONSE_SCHEMA_VERSION,
        "ok": True,
        "tool": tool,
        "model_requested": model_requested,
        "provider": provider.value if provider is not None else None,
        "result": result,
        "error": None,
        "agent": _agent_dict(agent),
        "diagnostics": diagnostics or {},
    }


def mcp_error(
    *,
    tool: str,
    model_requested: str | None,
    exc: GatewayError,
    statuses: list[ProviderStatus],
    provider: ProviderId | None = None,
) -> dict[str, object]:
    code = error_code(exc)
    status = select_status(model_requested, statuses, provider)
    agent = error_agent(code, model_requested, exc, status)
    related_provider = error_provider(provider, status)
    return {
        "schema_version": MCP_RESPONSE_SCHEMA_VERSION,
        "ok": False,
        "tool": tool,
        "model_requested": model_requested,
        "provider": related_provider,
        "result": None,
        "error": {
            "code": code,
            "message": error_message(code),
            "safe_detail": safe_detail(code, exc, status),
            "provider": related_provider,
        },
        "agent": _agent_dict(agent),
        "diagnostics": {
            "valid_models": provider_model_ids(),
            "provider_statuses": [_status_dict(item) for item in statuses],
        },
    }


def mcp_status_response(statuses: list[ProviderStatus]) -> dict[str, object]:
    recommendation = top_status_recommendation(statuses)
    result: dict[str, object] = {
        "providers": [_status_dict(status) for status in statuses],
        "recommendation": recommendation,
    }
    agent = AgentGuidance(
        summary="Provider status was collected.",
        user_message="Copilot Tools Gateway provider status is available.",
        recommended_action=str(recommendation["recommended_action"]),
        recommended_command=command_or_none(recommendation["recommended_command"]),
        retryable=False,
        retry_after_action=False,
        next_steps=status_next_steps(recommendation),
    )
    return mcp_success(
        tool="copilot_status",
        model_requested=None,
        provider=None,
        result=result,
        agent=agent,
        diagnostics={"provider_count": len(statuses)},
    )


def chat_success_result(
    *,
    text: str,
    conversation_id: str | None,
    capabilities: ProviderCapabilities,
) -> dict[str, object]:
    return {
        "text": text,
        "conversation_id": conversation_id,
        "conversation_resume_supported": capabilities.conversation_resume,
        "streaming_supported": capabilities.streaming,
    }


def file_chat_success_result(
    *,
    text: str,
    conversation_id: str | None,
    file_paths: list[str],
    attachment_mode: str,
) -> dict[str, object]:
    return {
        "text": text,
        "conversation_id": conversation_id,
        "file_count": len(file_paths),
        "file_extensions": _file_extensions(file_paths),
        "attachment_mode": attachment_mode,
    }


def conversation_list_success_result(result: ConversationListResult) -> dict[str, object]:
    return {
        "conversations": [
            {
                "title": conversation.title,
                "conversation_id": conversation.conversation_id,
            }
            for conversation in result.conversations
        ],
        "count": result.count,
        "has_more": result.has_more,
        "next_cursor": result.next_cursor,
    }


def _agent_dict(agent: AgentGuidance) -> dict[str, object]:
    return {
        "summary": agent.summary,
        "user_message": agent.user_message,
        "recommended_action": agent.recommended_action,
        "recommended_command": agent.recommended_command,
        "retryable": agent.retryable,
        "retry_after_action": agent.retry_after_action,
        "next_steps": agent.next_steps,
    }


def _status_dict(status: ProviderStatus) -> dict[str, object]:
    return {
        "provider": status.provider_id.value,
        "configured": status.configured,
        "available": status.available,
        "label": status.label,
        "detail": sanitize_text(status.detail),
        "recommended_action": status.recommended_action,
        "recommended_command": status.recommended_command,
        "capability_status": status.capability_status or _default_capability_status(status),
        "capabilities": {
            "chat": status.capabilities.chat,
            "streaming": status.capabilities.streaming,
            "image_generation": status.capabilities.image_generation,
            "vision": status.capabilities.vision,
            "file_chat": status.capabilities.file_chat,
            "conversation_resume": status.capabilities.conversation_resume,
            "conversation_listing": status.capabilities.conversation_listing,
        },
    }


def _default_capability_status(status: ProviderStatus) -> dict[str, str]:
    readiness = "ready" if status.available else "unavailable"
    values: dict[str, str] = {}
    for name, supported in (
        ("chat", status.capabilities.chat),
        ("streaming", status.capabilities.streaming),
        ("image_generation", status.capabilities.image_generation),
        ("vision", status.capabilities.vision),
        ("file_chat", status.capabilities.file_chat),
        ("conversation_resume", status.capabilities.conversation_resume),
        ("conversation_listing", status.capabilities.conversation_listing),
    ):
        values[name] = readiness if supported else "unsupported"
    return values


def _file_extensions(file_paths: list[str]) -> list[str]:
    extensions = sorted(
        {path.rsplit(".", maxsplit=1)[-1].lower() for path in file_paths if "." in path}
    )
    return [f".{extension}" for extension in extensions]
