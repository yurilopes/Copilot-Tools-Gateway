"""OpenAI-compatible response builders."""

import json
import time
import uuid

from copilot_tools_gateway.domain.models import ChatResult


def new_completion_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex}"


def completion_response(result: ChatResult, model: str) -> dict[str, object]:
    return {
        "id": new_completion_id(),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "provider": result.provider_id.value,
        "conversation_id": result.conversation_id,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def stream_chunk(
    completion_id: str,
    created: int,
    model: str,
    delta: dict[str, str],
    finish_reason: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, object]:
    chunk: dict[str, object] = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    if conversation_id is not None:
        chunk["conversation_id"] = conversation_id
    return chunk


def sse_event(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
