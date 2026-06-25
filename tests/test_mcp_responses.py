import json

from copilot_tools_gateway.domain.errors import (
    ProviderUnavailableError,
    UnsupportedCapabilityError,
)
from copilot_tools_gateway.domain.models import ProviderCapabilities, ProviderId, ProviderStatus
from copilot_tools_gateway.mcp_responses import (
    AgentGuidance,
    chat_success_result,
    mcp_error,
    mcp_status_response,
    mcp_success,
)

CAPABILITIES = ProviderCapabilities(
    chat=True,
    streaming=True,
    image_generation=True,
    vision=True,
    file_chat=True,
    conversation_resume=True,
)


def test_chat_success_uses_mcp_response_v2_envelope() -> None:
    response = mcp_success(
        tool="copilot_chat",
        model_requested=ProviderId.AUTO.value,
        provider=ProviderId.M365,
        result=chat_success_result(
            text="Hello",
            conversation_id="conversation-1",
            capabilities=CAPABILITIES,
        ),
        agent=AgentGuidance(
            summary="Copilot chat completed.",
            user_message="Copilot returned a response.",
            recommended_action="none",
            recommended_command=None,
            retryable=False,
            retry_after_action=False,
            next_steps=[],
        ),
        diagnostics={"text_length": 5},
    )

    assert response["schema_version"] == "mcp-response/v2"
    assert response["ok"] is True
    assert response["provider"] == "m365-copilot"
    assert response["result"] == {
        "text": "Hello",
        "conversation_id": "conversation-1",
        "conversation_resume_supported": True,
        "streaming_supported": True,
    }
    assert response["agent"] == {
        "summary": "Copilot chat completed.",
        "user_message": "Copilot returned a response.",
        "recommended_action": "none",
        "recommended_command": None,
        "retryable": False,
        "retry_after_action": False,
        "next_steps": [],
    }


def test_provider_unavailable_includes_recommended_command() -> None:
    status = _status(
        provider_id=ProviderId.M365,
        available=False,
        detail="M365 session file was not found",
        recommended_action="login_session",
        recommended_command=["python", "-m", "copilot_tools_gateway", "login", "m365"],
    )

    response = mcp_error(
        tool="copilot_chat",
        model_requested=ProviderId.M365.value,
        exc=ProviderUnavailableError("Provider m365-copilot is unavailable"),
        statuses=[status],
    )

    assert response["ok"] is False
    assert response["error"] == {
        "code": "provider_unavailable",
        "message": "Provider is unavailable.",
        "safe_detail": "M365 session file was not found",
        "provider": "m365-copilot",
    }
    assert response["agent"]["recommended_command"] == [
        "python",
        "-m",
        "copilot_tools_gateway",
        "login",
        "m365",
    ]
    assert response["agent"]["retry_after_action"] is True


def test_unknown_model_lists_valid_models_and_is_not_retryable() -> None:
    response = mcp_error(
        tool="copilot_chat",
        model_requested="bad-model",
        exc=ProviderUnavailableError("Unknown model: bad-model"),
        statuses=[],
    )

    assert response["error"]["code"] == "unknown_model"
    assert response["agent"]["retryable"] is False
    assert response["agent"]["retry_after_action"] is False
    assert response["error"]["safe_detail"] == (
        "Valid models are: copilot-auto, m365-copilot, copilot."
    )


def test_consumer_document_unsupported_recommends_m365() -> None:
    response = mcp_error(
        tool="copilot_chat_with_files",
        model_requested=ProviderId.CONSUMER.value,
        exc=UnsupportedCapabilityError(
            "Consumer provider currently supports image attachments only. "
            "Unsupported file attachments: report.docx"
        ),
        statuses=[_status(ProviderId.CONSUMER, available=True)],
    )

    assert response["error"]["code"] == "unsupported_capability"
    assert response["agent"]["recommended_action"] == "use_different_provider"
    assert response["agent"]["retryable"] is False
    assert response["agent"]["next_steps"] == [
        "Retry the file request with model m365-copilot."
    ]


def test_status_response_returns_top_level_recommendation() -> None:
    response = mcp_status_response(
        [
            _status(
                provider_id=ProviderId.M365,
                available=False,
                recommended_action="refresh_session",
                recommended_command=["python", "-m", "copilot_tools_gateway", "refresh", "m365"],
            ),
            _status(
                provider_id=ProviderId.CONSUMER,
                available=False,
                recommended_action="login_session",
                recommended_command=[
                    "python",
                    "-m",
                    "copilot_tools_gateway",
                    "login",
                    "consumer",
                ],
            ),
        ]
    )

    result = response["result"]

    assert response["ok"] is True
    assert result["recommendation"] == {
        "summary": "Microsoft 365 Copilot needs refresh_session.",
        "recommended_provider": "m365-copilot",
        "recommended_action": "refresh_session",
        "recommended_command": [
            "python",
            "-m",
            "copilot_tools_gateway",
            "refresh",
            "m365",
        ],
    }
    assert response["agent"]["recommended_action"] == "refresh_session"


def test_error_response_sanitizes_sensitive_terms() -> None:
    response = mcp_error(
        tool="copilot_chat",
        model_requested=ProviderId.M365.value,
        exc=ProviderUnavailableError(
            "Graph token expired and cookie authorization data is unavailable"
        ),
        statuses=[
            _status(
                provider_id=ProviderId.M365,
                available=False,
                detail="Graph token expired",
                recommended_action="refresh_session",
                recommended_command=["python", "-m", "copilot_tools_gateway", "refresh", "m365"],
            )
        ],
    )

    serialized = json.dumps(response).lower()

    assert "token" not in serialized
    assert "cookie" not in serialized
    assert "authorization" not in serialized
    assert "browser storage" not in serialized


def _status(
    provider_id: ProviderId,
    available: bool,
    detail: str | None = None,
    recommended_action: str | None = None,
    recommended_command: list[str] | None = None,
) -> ProviderStatus:
    return ProviderStatus(
        provider_id=provider_id,
        configured=available,
        available=available,
        label="Microsoft 365 Copilot" if provider_id == ProviderId.M365 else "Microsoft Copilot",
        capabilities=CAPABILITIES,
        detail=detail,
        recommended_action=recommended_action,
        recommended_command=recommended_command,
    )
