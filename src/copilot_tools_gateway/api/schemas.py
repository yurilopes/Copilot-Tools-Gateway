"""Pydantic request schemas for the local HTTP API."""

from pydantic import BaseModel, Field

from copilot_tools_gateway.domain.json_types import JsonValue
from copilot_tools_gateway.domain.models import ChatMessage, ProviderId


class OpenAIMessage(BaseModel):
    role: str
    content: str | list[JsonValue] | None = None

    def to_domain(self) -> ChatMessage:
        return ChatMessage(role=self.role, content=self._content_to_text())

    def _content_to_text(self) -> str:
        if self.content is None:
            return ""
        if isinstance(self.content, str):
            return self.content
        parts: list[str] = []
        for item in self.content:
            if isinstance(item, dict):
                item_type = item.get("type")
                text = item.get("text")
                if item_type == "text" and isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)


class ChatCompletionRequest(BaseModel):
    messages: list[OpenAIMessage] = Field(min_length=1)
    model: str = ProviderId.AUTO.value
    stream: bool = False
    conversation_id: str | None = None


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(min_length=1)
    model: str = ProviderId.AUTO.value
    n: int = Field(default=1, ge=1, le=4)
    response_format: str = "url"
