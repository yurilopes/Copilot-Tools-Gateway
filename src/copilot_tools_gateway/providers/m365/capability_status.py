"""Microsoft 365 provider capability readiness helpers."""


def m365_capability_status(
    core_readiness: str,
    documents_ready: bool,
    history_ready: bool,
) -> dict[str, str]:
    document_readiness = "ready" if documents_ready else "needs_refresh"
    history_readiness = "ready" if history_ready else "needs_refresh"
    if core_readiness != "ready":
        document_readiness = core_readiness
        history_readiness = core_readiness
    return {
        "chat": core_readiness,
        "streaming": core_readiness,
        "image_generation": core_readiness,
        "vision": core_readiness,
        "file_chat": document_readiness,
        "documents": document_readiness,
        "conversation_resume": core_readiness,
        "conversation_listing": history_readiness,
    }
