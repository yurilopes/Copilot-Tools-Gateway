"""FastAPI transport for Copilot Tools Gateway."""

import threading
import time
from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse

from copilot_tools_gateway.api.openai_format import (
    new_completion_id,
    sse_event,
    stream_chunk,
)
from copilot_tools_gateway.api.prompt import messages_to_prompt
from copilot_tools_gateway.api.schemas import ChatCompletionRequest, ImageGenerationRequest
from copilot_tools_gateway.app_factory import build_registry
from copilot_tools_gateway.domain.errors import GatewayError
from copilot_tools_gateway.domain.models import provider_model_ids
from copilot_tools_gateway.providers.base import CopilotProvider

app = FastAPI(title="Copilot Tools Gateway", version="0.1.0")
registry = build_registry()

# One upstream account should process one operation at a time.
upstream_lock = threading.Lock()


@app.get("/v1/models")
def list_models() -> dict[str, object]:
    return {
        "object": "list",
        "data": [
            {"id": model_id, "object": "model", "created": 0, "owned_by": "microsoft"}
            for model_id in provider_model_ids()
        ],
    }


@app.post("/v1/chat/completions")
def chat_completions(
    request: ChatCompletionRequest,
) -> JSONResponse | StreamingResponse | dict[str, object]:
    messages = [message.to_domain() for message in request.messages]
    prompt = messages_to_prompt(messages)
    if not prompt.strip():
        return _error_response(400, "No text content in messages", "invalid_request_error")
    provider = registry.resolve(request.model)
    if request.stream:
        return StreamingResponse(
            _stream_chat(provider, prompt, request.model, request.conversation_id),
            media_type="text/event-stream",
        )
    try:
        with upstream_lock:
            result = provider.chat(prompt, conversation_id=request.conversation_id)
    except GatewayError as exc:
        return _error_response(502, str(exc), "upstream_error")
    return {
        "id": new_completion_id(),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model,
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


@app.post("/v1/images/generations")
def image_generations(request: ImageGenerationRequest) -> JSONResponse | dict[str, object]:
    if request.response_format != "url":
        return _error_response(
            400,
            "Only response_format=url is supported",
            "invalid_request_error",
        )
    try:
        provider = registry.resolve(request.model)
        with upstream_lock:
            images = provider.generate_image(request.prompt, count=request.n)
    except GatewayError as exc:
        return _error_response(502, str(exc), "upstream_error")
    return {
        "created": int(time.time()),
        "provider": provider.provider_id.value,
        "data": [{"url": image.url} for image in images],
    }


@app.get("/")
def root() -> dict[str, object]:
    return {
        "service": "Copilot Tools Gateway",
        "models": provider_model_ids(),
        "providers": [status.__dict__ for status in registry.list_statuses()],
    }


def _stream_chat(
    provider: CopilotProvider,
    prompt: str,
    model: str,
    conversation_id: str | None,
) -> Iterator[str]:
    completion_id = new_completion_id()
    created = int(time.time())
    try:
        with upstream_lock:
            yield sse_event(stream_chunk(completion_id, created, model, {"role": "assistant"}))
            for chunk in provider.stream(prompt, conversation_id=conversation_id):
                if chunk:
                    yield sse_event(stream_chunk(completion_id, created, model, {"content": chunk}))
            yield sse_event(stream_chunk(completion_id, created, model, {}, finish_reason="stop"))
    except Exception as exc:
        yield sse_event(
            stream_chunk(
                completion_id,
                created,
                model,
                {"content": f"\n[error: {exc}]"},
                finish_reason="error",
            )
        )
    yield "data: [DONE]\n\n"


def _error_response(status_code: int, message: str, error_type: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": error_type}},
    )
