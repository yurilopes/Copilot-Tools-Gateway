"""Microsoft 365 Copilot provider."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Protocol

from websockets.asyncio.client import connect
from websockets.typing import Origin

from copilot_tools_gateway.async_runtime import run_async, run_async_iter
from copilot_tools_gateway.domain.errors import (
    ProviderUnavailableError,
    SessionExpiredError,
    UpstreamProtocolError,
)
from copilot_tools_gateway.domain.models import (
    ChatResult,
    ConversationListResult,
    FileChatInput,
    GeneratedImage,
    ProviderCapabilities,
    ProviderId,
    ProviderStatus,
    VisionInput,
)
from copilot_tools_gateway.providers.m365 import transport as m365_transport
from copilot_tools_gateway.providers.m365.auth import M365Session
from copilot_tools_gateway.providers.m365.capability_status import m365_capability_status
from copilot_tools_gateway.providers.m365.conversations import M365Conversations
from copilot_tools_gateway.providers.m365.file_chat import chat_with_files
from copilot_tools_gateway.providers.m365.history import list_m365_conversations
from copilot_tools_gateway.providers.m365.protocol import (
    CHAT_ALLOWED_MESSAGE_TYPES,
    CHAT_OPTION_SETS,
    IMAGE_ALLOWED_MESSAGE_TYPES,
    IMAGE_OPTION_SETS,
    decode_signalr,
    final_text,
    image_artifacts,
    image_file_annotation,
    signalr_handshake,
)
from copilot_tools_gateway.providers.m365.tokens import graph_token_is_valid, search_token_is_valid
from copilot_tools_gateway.providers.m365.uploads import (
    upload_image,
)
from copilot_tools_gateway.providers.m365.web_auth import M365WebAuth

M365_ORIGIN = Origin("https://m365.cloud.microsoft")


class SignalRSocket(Protocol):
    def __aiter__(self) -> AsyncIterator[str | bytes]:
        ...

    async def send(self, message: str) -> None:
        ...

    async def recv(self) -> str | bytes:
        ...


class M365Provider:
    provider_id = ProviderId.M365
    label = "Microsoft 365 Copilot"
    capabilities = ProviderCapabilities(
        chat=True,
        streaming=True,
        image_generation=True,
        vision=True,
        file_chat=True,
        conversation_resume=True,
        conversation_listing=True,
    )

    def __init__(
        self,
        token_file: Path,
        graph_token_file: Path | None = None,
        search_token_file: Path | None = None,
        web_auth_file: Path | None = None,
        timeout_seconds: float = 120,
    ) -> None:
        self._token_file = token_file
        self._graph_token_file = graph_token_file
        self._search_token_file = search_token_file
        self._web_auth_file = web_auth_file
        self._timeout_seconds = timeout_seconds
        self._conversations = M365Conversations()

    def status(self) -> ProviderStatus:
        if not self._token_file.exists():
            return ProviderStatus(
                provider_id=self.provider_id,
                configured=False,
                available=False,
                label=self.label,
                capabilities=self.capabilities,
                detail="M365 session file was not found",
                recommended_action="login_session",
                recommended_command=["python", "-m", "copilot_tools_gateway", "login", "m365"],
                capability_status=m365_capability_status("login_required", False, False),
            )
        try:
            M365Session.load(self._token_file)
        except SessionExpiredError as exc:
            return ProviderStatus(
                provider_id=self.provider_id,
                configured=True,
                available=False,
                label=self.label,
                capabilities=self.capabilities,
                detail=str(exc),
                recommended_action="refresh_session",
                recommended_command=["python", "-m", "copilot_tools_gateway", "refresh", "m365"],
                capability_status=m365_capability_status("needs_refresh", False, False),
            )
        except Exception as exc:
            return ProviderStatus(
                provider_id=self.provider_id,
                configured=True,
                available=False,
                label=self.label,
                capabilities=self.capabilities,
                detail=str(exc),
                recommended_action="login_session",
                recommended_command=["python", "-m", "copilot_tools_gateway", "login", "m365"],
                capability_status=m365_capability_status("login_required", False, False),
            )
        documents_ready = self._document_access_ready()
        history_ready = self._conversation_listing_ready()
        return ProviderStatus(
            provider_id=self.provider_id,
            configured=True,
            available=True,
            label=self.label,
            capabilities=self.capabilities,
            capability_status=m365_capability_status("ready", documents_ready, history_ready),
        )

    def chat(self, prompt: str, conversation_id: str | None = None) -> ChatResult:
        return run_async(self._chat(prompt, conversation_id))

    def stream(self, prompt: str, conversation_id: str | None = None) -> Iterator[str]:
        yield from run_async_iter(lambda: self._stream_chat(prompt, conversation_id))

    def generate_image(self, prompt: str, count: int = 1) -> list[GeneratedImage]:
        images = run_async(self._generate_image(prompt))
        return images[:count]

    def describe_image(self, request: VisionInput) -> ChatResult:
        return run_async(self._describe_image(request))

    def chat_with_files(self, request: FileChatInput) -> ChatResult:
        return run_async(
            chat_with_files(
                request=request,
                session=self._load_session(),
                graph_token=self._load_graph_token(),
                search_token=self._load_search_token(),
                conversations=self._conversations,
                timeout_seconds=self._timeout_seconds,
            )
        )

    def list_conversations(
        self,
        limit: int = 20,
        cursor: str | None = None,
    ) -> ConversationListResult:
        return list_m365_conversations(
            session=self._load_session(),
            web_auth=self._load_web_auth(),
            limit=limit,
            cursor=cursor,
            timeout_seconds=self._timeout_seconds,
        )

    def _load_session(self) -> M365Session:
        if not self._token_file.exists():
            raise ProviderUnavailableError("M365 session is not configured")
        return M365Session.load(self._token_file)

    def _load_graph_token(self) -> str:
        if self._graph_token_file is None or not self._graph_token_file.exists():
            raise ProviderUnavailableError(
                "M365 Graph token is not configured. Run: python -m copilot_tools_gateway "
                "refresh m365"
            )
        token = self._graph_token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise ProviderUnavailableError(
                "M365 Graph token is empty. Run: python -m copilot_tools_gateway refresh m365"
            )
        if not graph_token_is_valid(token):
            raise ProviderUnavailableError(
                "M365 Graph token is invalid or expired. Run: python -m "
                "copilot_tools_gateway refresh m365"
            )
        return token

    def _load_search_token(self) -> str:
        if self._search_token_file is None or not self._search_token_file.exists():
            raise ProviderUnavailableError(
                "M365 search token is not configured. Run: python -m copilot_tools_gateway "
                "refresh m365"
            )
        token = self._search_token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise ProviderUnavailableError(
                "M365 search token is empty. Run: python -m copilot_tools_gateway refresh m365"
            )
        if not search_token_is_valid(token):
            raise ProviderUnavailableError(
                "M365 search token is invalid or expired. Run: python -m "
                "copilot_tools_gateway refresh m365"
            )
        return token

    def _load_web_auth(self) -> M365WebAuth:
        if self._web_auth_file is None:
            raise ProviderUnavailableError("M365 web session is missing or expired")
        return M365WebAuth.load(self._web_auth_file)

    def _document_access_ready(self) -> bool:
        try:
            self._load_graph_token()
            self._load_search_token()
        except ProviderUnavailableError:
            return False
        return True

    def _conversation_listing_ready(self) -> bool:
        try:
            self._load_web_auth()
        except ProviderUnavailableError:
            return False
        return True

    async def _chat(self, prompt: str, conversation_id: str | None) -> ChatResult:
        session = self._load_session()
        conversation = self._conversations.prepare_prompt(conversation_id, prompt)
        session_id = str(uuid.uuid4())
        url = m365_transport.socket_url(session, session_id, conversation.conversation_id)
        chunks: list[str] = []
        async with asyncio.timeout(self._timeout_seconds):
            async with connect(url, origin=M365_ORIGIN) as socket:
                await self._handshake(socket)
                await socket.send(
                    m365_transport.chat_frame(
                        prompt=conversation.prompt,
                        session_id=session_id,
                        option_sets=CHAT_OPTION_SETS,
                        allowed_message_types=CHAT_ALLOWED_MESSAGE_TYPES,
                    )
                )
                async for chunk in m365_transport.stream_text_response(socket):
                    chunks.append(chunk)
                text = "".join(chunks)
                self._conversations.record_turn(
                    conversation.conversation_id,
                    prompt,
                    text,
                )
                return ChatResult(
                    text=text,
                    provider_id=self.provider_id,
                    conversation_id=conversation.conversation_id,
                )
        raise TimeoutError("M365 Copilot did not return a final update in time")

    async def _stream_chat(
        self,
        prompt: str,
        conversation_id: str | None,
    ) -> AsyncIterator[str]:
        session = self._load_session()
        conversation = self._conversations.prepare_prompt(conversation_id, prompt)
        session_id = str(uuid.uuid4())
        url = m365_transport.socket_url(session, session_id, conversation.conversation_id)
        chunks: list[str] = []
        async with asyncio.timeout(self._timeout_seconds):
            async with connect(url, origin=M365_ORIGIN) as socket:
                await self._handshake(socket)
                await socket.send(
                    m365_transport.chat_frame(
                        prompt=conversation.prompt,
                        session_id=session_id,
                        option_sets=CHAT_OPTION_SETS,
                        allowed_message_types=CHAT_ALLOWED_MESSAGE_TYPES,
                    )
                )
                async for chunk in m365_transport.stream_text_response(socket):
                    chunks.append(chunk)
                    yield chunk
                self._conversations.record_turn(
                    conversation.conversation_id,
                    prompt,
                    "".join(chunks),
                )
                return
        raise TimeoutError("M365 Copilot did not return a final update in time")

    async def _generate_image(self, prompt: str) -> list[GeneratedImage]:
        session = self._load_session()
        session_id = str(uuid.uuid4())
        url = m365_transport.socket_url(session, session_id, str(uuid.uuid4()))
        request_prompt = f"{prompt}\n\nDo not describe the image. Generate the image."
        latest_images: list[GeneratedImage] = []
        async with asyncio.timeout(self._timeout_seconds):
            async with connect(url, origin=M365_ORIGIN) as socket:
                await self._handshake(socket)
                await socket.send(
                    m365_transport.chat_frame(
                        prompt=request_prompt,
                        session_id=session_id,
                        option_sets=IMAGE_OPTION_SETS,
                        allowed_message_types=IMAGE_ALLOWED_MESSAGE_TYPES,
                    )
                )
                async for payload in socket:
                    if not isinstance(payload, str):
                        continue
                    for message in decode_signalr(payload):
                        latest_images = image_artifacts(message) or latest_images
                        if latest_images and any(image.status == 2 for image in latest_images):
                            return latest_images
                        if message.get("type") == 7:
                            raise UpstreamProtocolError("M365 Copilot closed the connection")
        if latest_images:
            return latest_images
        raise TimeoutError("M365 Copilot did not return a generated image in time")

    async def _describe_image(self, request: VisionInput) -> ChatResult:
        session = self._load_session()
        conversation = self._conversations.prepare_prompt(
            request.conversation_id,
            request.prompt,
        )
        session_id = str(uuid.uuid4())
        annotation = await asyncio.to_thread(
            upload_image,
            session,
            Path(request.image_path),
            self._timeout_seconds,
        )
        url = m365_transport.socket_url(session, session_id, conversation.conversation_id)
        async with asyncio.timeout(self._timeout_seconds):
            async with connect(url, origin=M365_ORIGIN) as socket:
                await self._handshake(socket)
                await socket.send(
                    m365_transport.chat_frame(
                        prompt=conversation.prompt,
                        session_id=session_id,
                        option_sets=CHAT_OPTION_SETS,
                        allowed_message_types=CHAT_ALLOWED_MESSAGE_TYPES,
                        message_annotations=[image_file_annotation(annotation)],
                    )
                )
                async for payload in socket:
                    if not isinstance(payload, str):
                        continue
                    for message in decode_signalr(payload):
                        text = final_text(message)
                        if text is not None:
                            self._conversations.record_turn(
                                conversation.conversation_id,
                                request.prompt,
                                text,
                            )
                            return ChatResult(
                                text=text,
                                provider_id=self.provider_id,
                                conversation_id=conversation.conversation_id,
                            )
                        if message.get("type") == 7:
                            raise UpstreamProtocolError("M365 Copilot closed the connection")
        raise TimeoutError("M365 Copilot did not return a vision response in time")

    async def _handshake(self, socket: SignalRSocket) -> None:
        await socket.send(signalr_handshake())
        handshake = await socket.recv()
        if not isinstance(handshake, str):
            raise UpstreamProtocolError("M365 SignalR handshake returned a non-text frame")
        if not any(message == {} for message in decode_signalr(handshake)):
            raise UpstreamProtocolError("M365 SignalR handshake failed")
