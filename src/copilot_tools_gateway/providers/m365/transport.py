"""M365 Copilot transport frame builders."""

import json
from collections.abc import AsyncIterator
from typing import Protocol
from urllib.parse import quote, urlencode

from copilot_tools_gateway.domain.errors import UpstreamProtocolError
from copilot_tools_gateway.domain.json_types import JsonValue
from copilot_tools_gateway.providers.m365.auth import M365Session
from copilot_tools_gateway.providers.m365.protocol import (
    M365_SOCKET_VARIANTS,
    RECORD_SEPARATOR,
    client_locale,
    decode_signalr,
    is_final_update,
    location_info,
    text_delta,
    update_text,
)

BASE_URL = "wss://substrate.office.com/m365Copilot/Chathub"


class SignalRTextSocket(Protocol):
    def __aiter__(self) -> AsyncIterator[str | bytes]:
        ...


def socket_url(session: M365Session, session_id: str, conversation_id: str) -> str:
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


def chat_frame(
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


async def stream_text_response(socket: SignalRTextSocket) -> AsyncIterator[str]:
    previous_text = ""
    async for payload in socket:
        if not isinstance(payload, str):
            continue
        for message in decode_signalr(payload):
            current_text = update_text(message)
            if current_text is not None:
                delta = text_delta(current_text, previous_text)
                previous_text = current_text
                if delta:
                    yield delta
                if is_final_update(message):
                    return
            if message.get("type") == 7:
                raise UpstreamProtocolError("M365 Copilot closed the connection")
