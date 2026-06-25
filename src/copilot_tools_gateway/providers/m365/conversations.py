"""Transient M365 conversation context for one gateway process."""

import uuid
from dataclasses import dataclass

MAX_TURNS = 6
MAX_TEXT_LENGTH = 1_200


@dataclass(frozen=True)
class M365ConversationPrompt:
    conversation_id: str
    prompt: str


class M365Conversations:
    def __init__(self) -> None:
        self._turns_by_conversation: dict[str, list[str]] = {}

    def prepare_prompt(self, conversation_id: str | None, prompt: str) -> M365ConversationPrompt:
        active_conversation_id = conversation_id or str(uuid.uuid4())
        turns = self._turns_by_conversation.get(active_conversation_id, [])
        if not turns:
            return M365ConversationPrompt(active_conversation_id, prompt)
        context = "\n".join(turns[-MAX_TURNS:])
        return M365ConversationPrompt(
            conversation_id=active_conversation_id,
            prompt=(
                "Previous messages in this gateway conversation:\n"
                f"{context}\n\n"
                "Use this context as authoritative when the current request asks about "
                "earlier turns, remembered markers, previous images, or previous files.\n\n"
                "Current user request:\n"
                f"{prompt}"
            ),
        )

    def record_turn(self, conversation_id: str, user_prompt: str, assistant_text: str) -> None:
        turns = self._turns_by_conversation.setdefault(conversation_id, [])
        turns.append(f"User: {_clip(user_prompt)}")
        turns.append(f"Copilot: {_clip(assistant_text)}")
        del turns[:-MAX_TURNS]


def _clip(value: str) -> str:
    if len(value) <= MAX_TEXT_LENGTH:
        return value
    return f"{value[:MAX_TEXT_LENGTH]}..."
