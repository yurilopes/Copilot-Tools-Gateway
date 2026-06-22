"""MCP tools for agentic coding clients."""

from copilot_tools_gateway.app_factory import build_registry
from copilot_tools_gateway.domain.errors import GatewayError
from copilot_tools_gateway.domain.models import ProviderId, VisionInput


def run_mcp_server() -> None:
    from mcp.server.fastmcp import FastMCP

    registry = build_registry()
    server = FastMCP("copilot-tools-gateway")

    @server.tool()
    def copilot_status() -> dict[str, object]:
        """Return configured providers and their capabilities."""
        statuses: list[dict[str, object]] = []
        for status in registry.list_statuses():
            statuses.append(
                {
                    "provider": status.provider_id.value,
                    "configured": status.configured,
                    "available": status.available,
                    "label": status.label,
                    "detail": status.detail,
                    "capabilities": status.capabilities.__dict__,
                }
            )
        return {"providers": statuses}

    @server.tool()
    def copilot_chat(prompt: str, model: str = ProviderId.AUTO.value) -> dict[str, object]:
        """Ask Copilot for a text response."""
        try:
            provider = registry.resolve(model)
            result = provider.chat(prompt)
        except GatewayError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "provider": result.provider_id.value,
            "conversation_id": result.conversation_id,
            "text": result.text,
        }

    @server.tool()
    def copilot_generate_image(
        prompt: str,
        model: str = ProviderId.AUTO.value,
        count: int = 1,
    ) -> dict[str, object]:
        """Generate images with Copilot when the provider supports it."""
        try:
            provider = registry.resolve(model)
            images = provider.generate_image(prompt, count=count)
        except GatewayError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "provider": provider.provider_id.value,
            "images": [{"url": image.url, "preview_url": image.preview_url} for image in images],
        }

    @server.tool()
    def copilot_vision(
        image_path: str,
        prompt: str,
        model: str = ProviderId.AUTO.value,
    ) -> dict[str, object]:
        """Ask Copilot to interpret an image when the provider supports it."""
        try:
            provider = registry.resolve(model)
            result = provider.describe_image(VisionInput(prompt=prompt, image_path=image_path))
        except GatewayError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "provider": result.provider_id.value,
            "conversation_id": result.conversation_id,
            "text": result.text,
        }

    server.run()
