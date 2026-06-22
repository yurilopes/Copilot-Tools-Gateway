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
from copilot_tools_gateway.domain.models import (
    ChatResult,
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
    RECORD_SEPARATOR,
    decode_signalr,
    final_text,
    image_artifacts,
    signalr_handshake,
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
        vision=False,
        conversation_resume=False,
    )

    def __init__(self, token_file: Path, timeout_seconds: float = 120) -> None:
        self._token_file = token_file
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
        text = asyncio.run(self._chat(prompt))
        return ChatResult(text=text, provider_id=self.provider_id)

    def stream(self, prompt: str, conversation_id: str | None = None) -> Iterator[str]:
        yield self.chat(prompt, conversation_id=conversation_id).text

    def generate_image(self, prompt: str, count: int = 1) -> list[GeneratedImage]:
        images = asyncio.run(self._generate_image(prompt))
        return images[:count]

    def describe_image(self, request: VisionInput) -> ChatResult:
        raise UnsupportedCapabilityError("M365 provider vision is not implemented yet")

    def _load_session(self) -> M365Session:
        if not self._token_file.exists():
            raise ProviderUnavailableError("M365 session is not configured")
        return M365Session.load(self._token_file)

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
                "variants": "Agt_bizchat_enableGpt5ForHelix",
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
    ) -> str:
        compact = session_id.replace("-", "")
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
            "message": {
                "author": "user",
                "inputMethod": "Keyboard",
                "text": prompt,
                "entityAnnotationTypes": ["People", "File", "Event", "Email", "TeamsMessage"],
                "requestId": compact,
                "locale": "en-us",
                "messageType": "Chat",
                "experienceType": "Default",
                "adaptiveCards": [],
                "clientPreferences": {},
                "connectedFederatedConnections": ["dummyid"],
            },
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
