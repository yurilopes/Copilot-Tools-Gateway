"""Prompt conversion for OpenAI-compatible chat messages."""

from copilot_tools_gateway.domain.models import ChatMessage


def messages_to_prompt(messages: list[ChatMessage]) -> str:
    if len(messages) == 1 and messages[0].role == "user":
        return messages[0].content
    labels = {"system": "System", "user": "User", "assistant": "Assistant", "tool": "Tool"}
    lines = [f"{labels.get(message.role, message.role)}: {message.content}" for message in messages]
    lines.append("Assistant:")
    return "\n".join(lines)
