"""MCP tools for agentic coding clients."""

from pathlib import Path

from copilot_tools_gateway.app_factory import build_registry
from copilot_tools_gateway.domain.errors import GatewayError
from copilot_tools_gateway.domain.models import FileChatInput, ProviderId, VisionInput
from copilot_tools_gateway.mcp_guidance import AgentGuidance
from copilot_tools_gateway.mcp_responses import (
    chat_success_result,
    file_chat_success_result,
    mcp_error,
    mcp_status_response,
    mcp_success,
)


def run_mcp_server() -> None:
    from mcp.server.fastmcp import FastMCP

    registry = build_registry()
    server = FastMCP("copilot-tools-gateway")

    @server.tool()
    def copilot_status() -> dict[str, object]:
        """Return MCP response v2 provider status and safe next-step guidance."""
        return mcp_status_response(registry.list_statuses())

    @server.tool()
    def copilot_chat(
        prompt: str,
        model: str = ProviderId.AUTO.value,
        conversation_id: str | None = None,
    ) -> dict[str, object]:
        """Ask Copilot for text using copilot-auto, m365-copilot, or copilot.

        Pass conversation_id to continue a provider conversation when the
        selected provider reports conversation_resume support in the response.
        Returns an MCP response v2 envelope with agent-facing retry guidance.
        """
        try:
            provider = registry.resolve(model)
            result = provider.chat(prompt, conversation_id=conversation_id)
        except GatewayError as exc:
            return mcp_error(
                tool="copilot_chat",
                model_requested=model,
                exc=exc,
                statuses=registry.list_statuses(),
            )
        return mcp_success(
            tool="copilot_chat",
            model_requested=model,
            provider=result.provider_id,
            result=chat_success_result(
                text=result.text,
                conversation_id=result.conversation_id,
                capabilities=provider.capabilities,
            ),
            agent=_success_agent("Copilot chat completed.", "Copilot returned a response."),
            diagnostics=_chat_diagnostics(result.text, result.conversation_id),
        )

    @server.tool()
    def copilot_generate_image(
        prompt: str,
        model: str = ProviderId.AUTO.value,
        count: int = 1,
    ) -> dict[str, object]:
        """Generate images when the selected Copilot provider supports images.

        Accepted models are copilot-auto, m365-copilot, and copilot. Returns an
        MCP response v2 envelope with image URLs in result.images.
        """
        try:
            provider = registry.resolve(model)
            images = provider.generate_image(prompt, count=count)
        except GatewayError as exc:
            return mcp_error(
                tool="copilot_generate_image",
                model_requested=model,
                exc=exc,
                statuses=registry.list_statuses(),
            )
        image_result = {
            "images": [{"url": image.url, "preview_url": image.preview_url} for image in images],
            "count": len(images),
        }
        return mcp_success(
            tool="copilot_generate_image",
            model_requested=model,
            provider=provider.provider_id,
            result=image_result,
            agent=_success_agent("Image generation completed.", "Copilot generated images."),
            diagnostics={"image_count": len(images), "requested_count": count},
        )

    @server.tool()
    def copilot_vision(
        image_path: str,
        prompt: str,
        model: str = ProviderId.AUTO.value,
    ) -> dict[str, object]:
        """Ask Copilot to interpret a PNG or JPEG image.

        Accepted models are copilot-auto, m365-copilot, and copilot. The
        consumer provider supports PNG and JPEG image attachments. Returns an
        MCP response v2 envelope with result.text.
        """
        try:
            provider = registry.resolve(model)
            result = provider.describe_image(VisionInput(prompt=prompt, image_path=image_path))
        except GatewayError as exc:
            return mcp_error(
                tool="copilot_vision",
                model_requested=model,
                exc=exc,
                statuses=registry.list_statuses(),
            )
        vision_result: dict[str, object] = {
            "text": result.text,
            "conversation_id": result.conversation_id,
            "input_image_supported": True,
        }
        return mcp_success(
            tool="copilot_vision",
            model_requested=model,
            provider=result.provider_id,
            result=vision_result,
            agent=_success_agent("Image analysis completed.", "Copilot analyzed the image."),
            diagnostics=_chat_diagnostics(result.text, result.conversation_id),
        )

    @server.tool()
    def copilot_chat_with_files(
        file_paths: list[str],
        prompt: str,
        model: str = ProviderId.AUTO.value,
    ) -> dict[str, object]:
        """Ask Copilot to answer using local file attachments.

        M365 supports document and image attachments when document access is
        refreshed. Consumer Copilot supports PNG and JPEG image attachments, but
        not document attachments. Returns an MCP response v2 envelope.
        """
        try:
            provider = registry.resolve(model)
            result = provider.chat_with_files(FileChatInput(prompt=prompt, file_paths=file_paths))
        except GatewayError as exc:
            return mcp_error(
                tool="copilot_chat_with_files",
                model_requested=model,
                exc=exc,
                statuses=registry.list_statuses(),
            )
        return mcp_success(
            tool="copilot_chat_with_files",
            model_requested=model,
            provider=result.provider_id,
            result=file_chat_success_result(
                text=result.text,
                conversation_id=result.conversation_id,
                file_paths=file_paths,
                attachment_mode=_attachment_mode(file_paths),
            ),
            agent=_success_agent(
                "File chat completed.",
                "Copilot answered using the provided attachments.",
            ),
            diagnostics={
                "file_count": len(file_paths),
                "attachment_mode": _attachment_mode(file_paths),
            },
        )

    server.run()


def _success_agent(summary: str, user_message: str) -> AgentGuidance:
    return AgentGuidance(
        summary=summary,
        user_message=user_message,
        recommended_action="none",
        recommended_command=None,
        retryable=False,
        retry_after_action=False,
        next_steps=[],
    )


def _chat_diagnostics(text: str, conversation_id: str | None) -> dict[str, object]:
    return {
        "text_length": len(text),
        "conversation_id_present": conversation_id is not None,
    }


def _attachment_mode(file_paths: list[str]) -> str:
    image_extensions = {".jpg", ".jpeg", ".png"}
    extensions = {Path(file_path).suffix.lower() for file_path in file_paths}
    if extensions and extensions <= image_extensions:
        return "image"
    if extensions and extensions.isdisjoint(image_extensions):
        return "document"
    return "mixed"
