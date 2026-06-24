"""Microsoft 365 Copilot provider."""

import asyncio
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, urlencode

from websockets.asyncio.client import connect
from websockets.typing import Origin

from copilot_tools_gateway.domain.errors import (
    ProviderUnavailableError,
    UnsupportedCapabilityError,
    UpstreamProtocolError,
)
from copilot_tools_gateway.domain.json_types import JsonValue
from copilot_tools_gateway.domain.models import (
    ChatResult,
    FileChatInput,
    GeneratedImage,
    ProviderCapabilities,
    ProviderId,
    ProviderStatus,
    VisionInput,
)
from copilot_tools_gateway.providers.m365.auth import M365Session
from copilot_tools_gateway.providers.m365.protocol import (
    CHAT_ALLOWED_MESSAGE_TYPES,
    CHAT_OPTION_SETS,
    IMAGE_ALLOWED_MESSAGE_TYPES,
    IMAGE_OPTION_SETS,
    M365_SOCKET_VARIANTS,
    RECORD_SEPARATOR,
    client_locale,
    decode_signalr,
    final_text,
    image_artifacts,
    image_file_annotation,
    local_file_annotation,
    location_info,
    signalr_handshake,
)
from copilot_tools_gateway.providers.m365.runtime import run_async
from copilot_tools_gateway.providers.m365.tokens import graph_token_is_valid, search_token_is_valid
from copilot_tools_gateway.providers.m365.uploads import (
    M365DocumentAnnotation,
    unfurl_document,
    upload_document,
    upload_image,
)

BASE_URL = "wss://substrate.office.com/m365Copilot/Chathub"
M365_ORIGIN = Origin("https://m365.cloud.microsoft")


class SignalRSocket(Protocol):
    async def send(self, message: str) -> None:
        ...

    async def recv(self) -> str | bytes:
        ...


class M365Provider:
    provider_id = ProviderId.M365
    label = "Microsoft 365 Copilot"
    capabilities = ProviderCapabilities(
        chat=True,
        streaming=False,
        image_generation=True,
        vision=True,
        file_chat=True,
        conversation_resume=False,
    )

    def __init__(
        self,
        token_file: Path,
        graph_token_file: Path | None = None,
        search_token_file: Path | None = None,
        timeout_seconds: float = 120,
    ) -> None:
        self._token_file = token_file
        self._graph_token_file = graph_token_file
        self._search_token_file = search_token_file
        self._timeout_seconds = timeout_seconds

    def status(self) -> ProviderStatus:
        if not self._token_file.exists():
            return ProviderStatus(
                provider_id=self.provider_id,
                configured=False,
                available=False,
                label=self.label,
                capabilities=self.capabilities,
                detail="M365 session file was not found",
            )
        try:
            M365Session.load(self._token_file)
        except Exception as exc:
            return ProviderStatus(
                provider_id=self.provider_id,
                configured=True,
                available=False,
                label=self.label,
                capabilities=self.capabilities,
                detail=str(exc),
            )
        return ProviderStatus(
            provider_id=self.provider_id,
            configured=True,
            available=True,
            label=self.label,
            capabilities=self.capabilities,
        )

    def chat(self, prompt: str, conversation_id: str | None = None) -> ChatResult:
        if conversation_id is not None:
            raise UnsupportedCapabilityError(
                "M365 provider does not support conversation resume yet"
            )
        text = run_async(self._chat(prompt))
        return ChatResult(text=text, provider_id=self.provider_id)

    def stream(self, prompt: str, conversation_id: str | None = None) -> Iterator[str]:
        yield self.chat(prompt, conversation_id=conversation_id).text

    def generate_image(self, prompt: str, count: int = 1) -> list[GeneratedImage]:
        images = run_async(self._generate_image(prompt))
        return images[:count]

    def describe_image(self, request: VisionInput) -> ChatResult:
        text = run_async(self._describe_image(request))
        return ChatResult(text=text, provider_id=self.provider_id)

    def chat_with_files(self, request: FileChatInput) -> ChatResult:
        text = run_async(self._chat_with_files(request))
        return ChatResult(text=text, provider_id=self.provider_id)

    def _load_session(self) -> M365Session:
        if not self._token_file.exists():
            raise ProviderUnavailableError("M365 session is not configured")
        return M365Session.load(self._token_file)

    def _load_graph_token(self) -> str:
        if self._graph_token_file is None or not self._graph_token_file.exists():
            raise ProviderUnavailableError(
                "M365 Graph token is not configured. Run refresh m365."
            )
        token = self._graph_token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise ProviderUnavailableError("M365 Graph token is empty. Run refresh m365.")
        if not graph_token_is_valid(token):
            raise ProviderUnavailableError(
                "M365 Graph token is invalid or expired. Run refresh m365."
            )
        return token

    def _load_search_token(self) -> str:
        if self._search_token_file is None or not self._search_token_file.exists():
            raise ProviderUnavailableError(
                "M365 search token is not configured. Run refresh m365."
            )
        token = self._search_token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise ProviderUnavailableError("M365 search token is empty. Run refresh m365.")
        if not search_token_is_valid(token):
            raise ProviderUnavailableError(
                "M365 search token is invalid or expired. Run refresh m365."
            )
        return token

    async def _chat(self, prompt: str) -> str:
        session = self._load_session()
        session_id = str(uuid.uuid4())
        url = self._socket_url(session, session_id, str(uuid.uuid4()))
        async with asyncio.timeout(self._timeout_seconds):
            async with connect(url, origin=M365_ORIGIN) as socket:
                await self._handshake(socket)
                await socket.send(
                    self._chat_frame(
                        prompt=prompt,
                        session_id=session_id,
                        option_sets=CHAT_OPTION_SETS,
                        allowed_message_types=CHAT_ALLOWED_MESSAGE_TYPES,
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
        raise TimeoutError("M365 Copilot did not return a final update in time")

    async def _generate_image(self, prompt: str) -> list[GeneratedImage]:
        session = self._load_session()
        session_id = str(uuid.uuid4())
        url = self._socket_url(session, session_id, str(uuid.uuid4()))
        request_prompt = f"{prompt}\n\nDo not describe the image. Generate the image."
        latest_images: list[GeneratedImage] = []
        async with asyncio.timeout(self._timeout_seconds):
            async with connect(url, origin=M365_ORIGIN) as socket:
                await self._handshake(socket)
                await socket.send(
                    self._chat_frame(
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

    async def _describe_image(self, request: VisionInput) -> str:
        session = self._load_session()
        session_id = str(uuid.uuid4())
        annotation = await asyncio.to_thread(
            upload_image,
            session,
            Path(request.image_path),
            self._timeout_seconds,
        )
        url = self._socket_url(session, session_id, str(uuid.uuid4()))
        async with asyncio.timeout(self._timeout_seconds):
            async with connect(url, origin=M365_ORIGIN) as socket:
                await self._handshake(socket)
                await socket.send(
                    self._chat_frame(
                        prompt=request.prompt,
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
                            return text
                        if message.get("type") == 7:
                            raise UpstreamProtocolError("M365 Copilot closed the connection")
        raise TimeoutError("M365 Copilot did not return a vision response in time")

    async def _chat_with_files(self, request: FileChatInput) -> str:
        if not request.file_paths:
            raise ProviderUnavailableError("At least one file path is required")
        session = self._load_session()
        graph_token = self._load_graph_token()
        search_token = self._load_search_token()
        session_id = str(uuid.uuid4())
        annotations = []
        for file_path in request.file_paths:
            path = Path(file_path)
            if _is_image_path(path):
                image = await asyncio.to_thread(
                    upload_image,
                    session,
                    path,
                    self._timeout_seconds,
                )
                annotations.append(image_file_annotation(image))
            else:
                document = await asyncio.to_thread(
                    upload_document,
                    graph_token,
                    path,
                    self._timeout_seconds,
                )
                await asyncio.to_thread(
                    _try_unfurl_document,
                    session,
                    search_token,
                    document,
                    self._timeout_seconds,
                )
                annotations.append(local_file_annotation(document))
        return await self._chat_with_annotations(
            session=session,
            prompt=request.prompt,
            session_id=session_id,
            annotations=annotations,
        )

    async def _chat_with_annotations(
        self,
        session: M365Session,
        prompt: str,
        session_id: str,
        annotations: list[dict[str, JsonValue]],
    ) -> str:
        url = self._socket_url(session, session_id, str(uuid.uuid4()))
        async with asyncio.timeout(self._timeout_seconds):
            async with connect(url, origin=M365_ORIGIN) as socket:
                await self._handshake(socket)
                await socket.send(
                    self._chat_frame(
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

    async def _handshake(self, socket: SignalRSocket) -> None:
        await socket.send(signalr_handshake())
        handshake = await socket.recv()
        if not isinstance(handshake, str):
            raise UpstreamProtocolError("M365 SignalR handshake returned a non-text frame")
        if not any(message == {} for message in decode_signalr(handshake)):
            raise UpstreamProtocolError("M365 SignalR handshake failed")

    @staticmethod
    def _socket_url(session: M365Session, session_id: str, conversation_id: str) -> str:
        compact = session_id.replace("-", "")
        query = urlencode(
            {
                "chatsessionid": compact,
                "XRoutingParameterSessionKey": compact,
                "clientrequestid": compact,
                "X-SessionId": session_id,
                "ConversationId": conversation_id,
                "access_token": session.access_token,
                "variants": M365_SOCKET_VARIANTS,
                "source": '"officeweb"',
                "product": "Office",
                "agentHost": "Bizchat.FullScreen",
                "licenseType": "Starter",
                "isEdu": "false",
                "agent": "web",
                "scenario": "OfficeWebIncludedCopilot",
            },
            quote_via=quote,
        )
        return f"{BASE_URL}/{session.oid}@{session.tid}?{query}"

    @staticmethod
    def _chat_frame(
        prompt: str,
        session_id: str,
        option_sets: list[str],
        allowed_message_types: list[str],
        message_annotations: list[dict[str, JsonValue]] | None = None,
    ) -> str:
        compact = session_id.replace("-", "")
        message: dict[str, JsonValue] = {
            "author": "user",
            "inputMethod": "Keyboard",
            "text": prompt,
            "entityAnnotationTypes": ["People", "File", "Event", "Email", "TeamsMessage"],
            "requestId": compact,
            "locationInfo": location_info(),
            "locale": client_locale(),
            "messageType": "Chat",
            "experienceType": "Default",
            "adaptiveCards": [],
            "clientPreferences": {},
            "connectedFederatedConnections": ["dummyid"],
        }
        if message_annotations:
            message["messageAnnotations"] = message_annotations
        argument = {
            "source": "officeweb",
            "clientCorrelationId": compact,
            "sessionId": session_id,
            "optionsSets": option_sets,
            "streamingMode": "ConciseWithPadding",
            "spokenTextMode": "None",
            "options": {},
            "extraExtensionParameters": {},
            "allowedMessageTypes": allowed_message_types,
            "sliceIds": [],
            "threadLevelGptId": {},
            "traceId": compact,
            "isStartOfSession": False,
            "clientInfo": {
                "clientPlatform": "mcmcopilot-web",
                "clientAppName": "Office",
                "clientEntrypoint": "mcmcopilot-officeweb",
                "clientSessionId": session_id,
                "ProductCategory": "Chat",
                "clientAppType": "Web",
                "productEntryPoint": "ChatPanel",
                "deviceOS": "Windows",
                "deviceType": "Desktop",
                "clientPlatformVersion": "10",
            },
            "message": message,
            "plugins": [{"Id": "BingWebSearch", "Source": "BuiltIn"}],
            "isSbsSupported": True,
            "tone": "Magic",
            "renderReferencesBehindEOS": True,
            "disconnectBehavior": "continue",
        }
        return (
            json.dumps(
                {"arguments": [argument], "invocationId": "0", "target": "chat", "type": 4},
                separators=(",", ":"),
            )
            + RECORD_SEPARATOR
        )


def _is_image_path(path: Path) -> bool:
    return path.suffix.lower() in {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


def _try_unfurl_document(
    session: M365Session,
    search_token: str,
    document: M365DocumentAnnotation,
    timeout_seconds: float,
) -> bool:
    try:
        unfurl_document(session, search_token, document, timeout_seconds)
    except UpstreamProtocolError:
        return False
    return True
