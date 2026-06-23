"""Consumer Copilot WebSocket driver."""

import json
import time
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from select import select
from typing import Protocol
from urllib.parse import quote

from curl_cffi.const import CurlECode, CurlInfo
from curl_cffi.curl import CurlError
from curl_cffi.requests import CurlWsFlag, Session

from copilot_tools_gateway.domain.errors import UpstreamProtocolError
from copilot_tools_gateway.domain.json_types import JsonValue
from copilot_tools_gateway.domain.models import GeneratedImage, ProviderId
from copilot_tools_gateway.providers.consumer.challenges import (
    solve_copilot_challenge,
    solve_hashcash,
)

COPILOT_URL = "https://copilot.microsoft.com"
CHAT_WEBSOCKET_URL = "wss://copilot.microsoft.com/c/api/chat?api-version=2"
START_CONVERSATION_URL = f"{COPILOT_URL}/c/api/start"
SOCKET_BAD = -1


class CurlLike(Protocol):
    def getinfo(self, option: object) -> int:
        ...


class CurlFrame(Protocol):
    bytesleft: int
    flags: int


class ConsumerWebSocket(Protocol):
    curl: CurlLike

    def send(self, payload: bytes, flags: object) -> object:
        ...

    def recv_fragment(self) -> tuple[bytes | bytearray, CurlFrame]:
        ...


class ConsumerHttpSession(Protocol):
    def post(self, url: str, json: Mapping[str, object]) -> object:
        ...


@dataclass(frozen=True)
class ConsumerConversation:
    conversation_id: str


class ConsumerDriver:
    def create_completion(
        self,
        prompt: str,
        cookies: dict[str, str],
        access_token: str | None,
        conversation_id: str | None,
        timeout_seconds: int,
    ) -> Iterator[str | GeneratedImage | ConsumerConversation]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "CopilotNative/30.0.440505001-prod (Android 14; Google; Pixel 8 Pro)",
            "X-Search-UILang": "en-US",
        }

        with Session(
            timeout=timeout_seconds,
            impersonate="chrome",
            cookies=cookies,
            headers=headers,
        ) as session:
            active_conversation_id = conversation_id or self._start_conversation(session)
            if conversation_id is None:
                yield ConsumerConversation(active_conversation_id)

            send_frame = json.dumps(
                {
                    "event": "send",
                    "conversationId": active_conversation_id,
                    "content": [{"type": "text", "text": prompt}],
                    "mode": "chat",
                }
            ).encode("utf-8")
            try:
                websocket = session.ws_connect(
                    _websocket_url(access_token),
                    headers={"Origin": COPILOT_URL},
                )
            except CurlError:
                if access_token is None:
                    raise
                websocket = session.ws_connect(
                    _websocket_url(None),
                    headers={"Origin": COPILOT_URL},
                )
            websocket.send(send_frame, CurlWsFlag.TEXT)
            yield from self._read_stream(websocket, send_frame, timeout_seconds)

    def _start_conversation(self, session: ConsumerHttpSession) -> str:
        response = session.post(
            START_CONVERSATION_URL,
            json={
                "timeZone": "UTC",
                "startNewConversation": True,
                "teenSupportEnabled": True,
                "correctPersonalizationSetting": True,
                "deferredDataUseCapable": True,
            },
        )
        status_code = getattr(response, "status_code", 0)
        if not isinstance(status_code, int):
            raise UpstreamProtocolError("Consumer conversation status was not an integer")
        if status_code >= 400:
            raise UpstreamProtocolError(
                f"Consumer conversation start failed: {status_code}"
            )
        value = _response_json(response)
        if not isinstance(value, Mapping):
            raise UpstreamProtocolError("Consumer conversation response was not an object")
        conversation_id = (
            value.get("currentConversationId") or value.get("id") or value.get("conversationId")
        )
        if not isinstance(conversation_id, str) or not conversation_id:
            raise UpstreamProtocolError("Consumer conversation response did not include an id")
        return conversation_id

    def _read_stream(
        self,
        websocket: ConsumerWebSocket,
        send_frame: bytes,
        timeout_seconds: int,
        idle_timeout_seconds: int = 60,
    ) -> Iterator[str | GeneratedImage]:
        buffer = b""
        started = False
        answered_challenge = False
        image_prompt: str | None = None
        last_event = "none"
        overall_deadline = time.time() + timeout_seconds
        while True:
            deadline = min(overall_deadline, time.time() + idle_timeout_seconds)
            chunk = self._recv_frame(websocket, deadline)
            if chunk is None:
                if time.time() >= overall_deadline:
                    raise TimeoutError("Consumer Copilot stream exceeded the configured timeout")
                raise TimeoutError(f"Consumer Copilot socket went idle after event: {last_event}")
            buffer += chunk
            messages, buffer = self._drain_json(buffer)
            for message in messages:
                event = message.get("event")
                last_event = event if isinstance(event, str) else "unknown"
                if event == "challenge" and not answered_challenge:
                    token = self._solve_challenge(message)
                    websocket.send(
                        json.dumps(
                            {
                                "event": "challengeResponse",
                                "token": token,
                                "method": message.get("method"),
                            }
                        ).encode("utf-8"),
                        CurlWsFlag.TEXT,
                    )
                    answered_challenge = True
                    websocket.send(send_frame, CurlWsFlag.TEXT)
                elif event == "appendText":
                    started = True
                    text = message.get("text")
                    if isinstance(text, str):
                        yield text
                elif event == "generatingImage":
                    prompt = message.get("prompt")
                    image_prompt = prompt if isinstance(prompt, str) else None
                elif event == "imageGenerated":
                    url = message.get("url")
                    preview = message.get("thumbnailUrl")
                    if isinstance(url, str):
                        yield GeneratedImage(
                            url=url,
                            provider_id=ProviderId.CONSUMER,
                            prompt=image_prompt,
                            preview_url=preview if isinstance(preview, str) else None,
                        )
                elif event == "done":
                    return
                elif event == "error":
                    error_code = message.get("errorCode")
                    if isinstance(error_code, str) and error_code:
                        raise UpstreamProtocolError(
                            f"Consumer Copilot returned an error event: {error_code}"
                        )
                    raise UpstreamProtocolError("Consumer Copilot returned an error event")
        if not started:
            raise UpstreamProtocolError("Consumer Copilot did not start streaming")

    @staticmethod
    def _recv_frame(websocket: ConsumerWebSocket, deadline: float) -> bytes | None:
        curl = websocket.curl
        socket_fd = curl.getinfo(CurlInfo.ACTIVESOCKET)
        if socket_fd == SOCKET_BAD:
            raise ConnectionError("Consumer WebSocket has no active socket")
        chunks: list[bytes] = []
        while True:
            try:
                chunk, frame = websocket.recv_fragment()
                chunks.append(chunk if isinstance(chunk, bytes) else bytes(chunk))
                if frame.bytesleft == 0 and frame.flags & CurlWsFlag.CONT == 0:
                    return b"".join(chunks)
            except CurlError as exc:
                if exc.code != CurlECode.AGAIN:
                    raise
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                select([socket_fd], [], [], min(0.5, remaining))

    @staticmethod
    def _solve_challenge(message: Mapping[str, JsonValue]) -> str:
        method = message.get("method")
        parameter = message.get("parameter")
        if not method and not parameter:
            return ""
        if method == "hashcash" and isinstance(parameter, str):
            return solve_hashcash(parameter)
        if method == "copilot" and isinstance(parameter, str):
            return solve_copilot_challenge(parameter)
        raise UpstreamProtocolError("Consumer Copilot returned an unsupported challenge")

    @staticmethod
    def _drain_json(buffer: bytes) -> tuple[list[Mapping[str, JsonValue]], bytes]:
        decoder = json.JSONDecoder()
        text = buffer.decode("utf-8", errors="ignore")
        messages: list[Mapping[str, JsonValue]] = []
        index = 0
        while index < len(text):
            while index < len(text) and text[index].isspace():
                index += 1
            if index >= len(text):
                break
            try:
                value, next_index = decoder.raw_decode(text, index)
            except json.JSONDecodeError:
                break
            if isinstance(value, Mapping):
                messages.append(value)
            index = next_index
        return messages, text[index:].encode("utf-8")


def _response_json(response: object) -> object:
    json_method = getattr(response, "json", None)
    if not callable(json_method):
        raise UpstreamProtocolError("Consumer response did not expose JSON")
    return json_method()


def _websocket_url(access_token: str | None) -> str:
    websocket_url = f"{CHAT_WEBSOCKET_URL}&clientSessionId={uuid.uuid4()}"
    if access_token:
        return f"{websocket_url}&accessToken={quote(access_token, safe='')}"
    return websocket_url
