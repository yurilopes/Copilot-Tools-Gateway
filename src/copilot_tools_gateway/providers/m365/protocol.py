"""SignalR protocol helpers for Microsoft 365 Copilot."""

import json
from collections.abc import Iterator, Mapping, Sequence

from copilot_tools_gateway.domain.json_types import JsonValue
from copilot_tools_gateway.domain.models import GeneratedImage, ProviderId

RECORD_SEPARATOR = "\x1e"

CHAT_ALLOWED_MESSAGE_TYPES = [
    "Chat",
    "Suggestion",
    "InternalSearchQuery",
    "Disengaged",
    "Progress",
    "GeneratedCode",
    "RenderCardRequest",
    "SearchQuery",
    "AuthError",
    "DeveloperLogs",
    "EndOfRequest",
    "ReferencesListComplete",
]

CHAT_OPTION_SETS = [
    "search_result_progress_messages_with_search_queries",
    "update_textdoc_response_after_streaming",
    "rich_responses",
]

IMAGE_ALLOWED_MESSAGE_TYPES = [
    *CHAT_ALLOWED_MESSAGE_TYPES,
    "InternalLoaderMessage",
    "AdsQuery",
    "SemanticSerp",
    "GenerateContentQuery",
    "GenerateGraphicArt",
    "ConfirmationCard",
    "TriggerPlugin",
    "HintInvocation",
    "MemoryUpdate",
    "TriggerConfirmation",
    "ResumeInvokeAction",
    "ResumeUserInputRequest",
    "TriggerUserInputRequest",
    "EscapeHatch",
    "TriggerPluginAuth",
    "ResumePluginAuth",
    "SideBySide",
    "SwitchRespondingEndpoint",
]

IMAGE_OPTION_SETS = [
    *CHAT_OPTION_SETS,
    "deepleo_networking_timeout_10minutes_canmore",
    "cwc_flux_image",
    "cwc_code_interpreter",
    "cwcfluxgptv",
    "flux_v3_gptv_enable_upload_multi_image_in_turn_wo_ch",
    "gptvnorm2048",
    "cwc_fileupload_odb",
    "cwc_flux_v3",
    "flux_v3_progress_messages",
    "enable_gg_gpt",
    "flux_v3_references",
    "flux_v3_image_gen_enable_dimensions",
]


def decode_signalr(payload: str) -> Iterator[Mapping[str, JsonValue]]:
    for part in payload.split(RECORD_SEPARATOR):
        if not part.strip():
            continue
        try:
            value = json.loads(part)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            yield value


def signalr_handshake() -> str:
    return json.dumps({"protocol": "json", "version": 1}) + RECORD_SEPARATOR


def final_text(message: Mapping[str, JsonValue]) -> str | None:
    if message.get("target") != "update":
        return None
    update = _first_object(message.get("arguments"))
    if update is None or update.get("isLastUpdate") is not True:
        return None
    bot_messages = [
        item for item in _objects(update.get("messages")) if item.get("author") == "bot"
    ]
    if not bot_messages:
        return None
    text = bot_messages[-1].get("text")
    return text if isinstance(text, str) else None


def image_artifacts(message: Mapping[str, JsonValue]) -> list[GeneratedImage]:
    if message.get("target") != "update" and message.get("type") != 2:
        return []
    containers = []
    first_argument = _first_object(message.get("arguments"))
    if first_argument is not None:
        containers.append(first_argument)
    item = message.get("item")
    if isinstance(item, Mapping):
        containers.append(item)

    images: list[GeneratedImage] = []
    seen: set[str] = set()
    for container in containers:
        for bot_message in _objects(container.get("messages")):
            for progress in _objects(bot_message.get("contentGenerationProgressList")):
                if progress.get("contentType") != "image":
                    continue
                status_value = progress.get("status")
                status = status_value if isinstance(status_value, int) else None
                for url in _strings(progress.get("ImageReferenceUrls")):
                    if url in seen:
                        continue
                    seen.add(url)
                    images.append(
                        GeneratedImage(url=url, provider_id=ProviderId.M365, status=status)
                    )
    return images


def _objects(value: JsonValue | object) -> list[Mapping[str, JsonValue]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _strings(value: JsonValue | object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return []
    return [item for item in value if isinstance(item, str)]


def _first_object(value: JsonValue | object) -> Mapping[str, JsonValue] | None:
    objects = _objects(value)
    return objects[0] if objects else None
