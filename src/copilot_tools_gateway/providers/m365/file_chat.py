"""Microsoft 365 Copilot file chat flow."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol

from websockets.asyncio.client import connect
from websockets.typing import Origin

from copilot_tools_gateway.domain.errors import ProviderUnavailableError, UpstreamProtocolError
from copilot_tools_gateway.domain.json_types import JsonValue
from copilot_tools_gateway.domain.models import ChatResult, FileChatInput, ProviderId
from copilot_tools_gateway.providers.m365 import transport as m365_transport
from copilot_tools_gateway.providers.m365.auth import M365Session
from copilot_tools_gateway.providers.m365.conversations import M365Conversations
from copilot_tools_gateway.providers.m365.protocol import (
    IMAGE_ALLOWED_MESSAGE_TYPES,
    IMAGE_OPTION_SETS,
    decode_signalr,
    final_text,
    image_file_annotation,
    local_file_annotation,
    signalr_handshake,
)
from copilot_tools_gateway.providers.m365.unfurl import try_unfurl_document
from copilot_tools_gateway.providers.m365.uploads import upload_document, upload_image

M365_ORIGIN = Origin("https://m365.cloud.microsoft")


class SignalRSocket(Protocol):
    def __aiter__(self) -> AsyncIterator[str | bytes]:
        ...

    async def send(self, message: str) -> None:
        ...

    async def recv(self) -> str | bytes:
        ...


async def chat_with_files(
    request: FileChatInput,
    session: M365Session,
    graph_token: str,
    search_token: str,
    conversations: M365Conversations,
    timeout_seconds: float,
) -> ChatResult:
    if not request.file_paths:
        raise ProviderUnavailableError("At least one file path is required")
    conversation = conversations.prepare_prompt(
        request.conversation_id,
        request.prompt,
    )
    session_id = str(uuid.uuid4())
    annotations = await _file_annotations(
        request.file_paths,
        session,
        graph_token,
        search_token,
        timeout_seconds,
    )
    text = await _send_file_chat(
        session=session,
        prompt=conversation.prompt,
        session_id=session_id,
        conversation_id=conversation.conversation_id,
        annotations=annotations,
        timeout_seconds=timeout_seconds,
    )
    conversations.record_turn(
        conversation.conversation_id,
        request.prompt,
        text,
    )
    return ChatResult(
        text=text,
        provider_id=ProviderId.M365,
        conversation_id=conversation.conversation_id,
    )


async def _file_annotations(
    file_paths: list[str],
    session: M365Session,
    graph_token: str,
    search_token: str,
    timeout_seconds: float,
) -> list[dict[str, JsonValue]]:
    annotations: list[dict[str, JsonValue]] = []
    for file_path in file_paths:
        path = Path(file_path)
        if _is_image_path(path):
            image = await asyncio.to_thread(
                upload_image,
                session,
                path,
                timeout_seconds,
            )
            annotations.append(image_file_annotation(image))
            continue
        document = await asyncio.to_thread(
            upload_document,
            graph_token,
            path,
            timeout_seconds,
        )
        await asyncio.to_thread(
            try_unfurl_document,
            session,
            search_token,
            document,
            timeout_seconds,
        )
        annotations.append(local_file_annotation(document))
    return annotations


async def _send_file_chat(
    session: M365Session,
    prompt: str,
    session_id: str,
    conversation_id: str,
    annotations: list[dict[str, JsonValue]],
    timeout_seconds: float,
) -> str:
    url = m365_transport.socket_url(session, session_id, conversation_id)
    async with asyncio.timeout(timeout_seconds):
        async with connect(url, origin=M365_ORIGIN) as socket:
            await _handshake(socket)
            await socket.send(
                m365_transport.chat_frame(
                    prompt=prompt,
                    session_id=session_id,
                    option_sets=IMAGE_OPTION_SETS,
                    allowed_message_types=IMAGE_ALLOWED_MESSAGE_TYPES,
                    message_annotations=annotations,
                )
            )
            async for payload in socket:
                if not isinstance(payload, str):
                    continue
                for message in decode_signalr(payload):
                    text = final_text(message)
                    if text is not None:
                        return text
                    if message.get("type") == 7:
                        raise UpstreamProtocolError("M365 Copilot closed the connection")
    raise TimeoutError("M365 Copilot did not return a file chat response in time")


async def _handshake(socket: SignalRSocket) -> None:
    await socket.send(signalr_handshake())
    handshake = await socket.recv()
    if not isinstance(handshake, str):
        raise UpstreamProtocolError("M365 SignalR handshake returned a non-text frame")
    if not any(message == {} for message in decode_signalr(handshake)):
        raise UpstreamProtocolError("M365 SignalR handshake failed")


def _is_image_path(path: Path) -> bool:
    return path.suffix.lower() in {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
