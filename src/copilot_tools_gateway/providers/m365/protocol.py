"""SignalR protocol helpers for Microsoft 365 Copilot."""

import json
import locale
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime

from copilot_tools_gateway.domain.json_types import JsonValue
from copilot_tools_gateway.domain.models import GeneratedImage, ProviderId
from copilot_tools_gateway.providers.m365.uploads import M365DocumentAnnotation, M365ImageAnnotation

RECORD_SEPARATOR = "\x1e"
M365_SOCKET_VARIANTS = ",".join(
    [
        "EnableMcpServerWidgets",
        "feature.EnableMcpServerWidgets",
        "feature.EnableImageGenInsufficientTokensThrottled",
        "feature.EnableImageGenSystemCapacityThrottled",
        "feature.EnableLuForChatCIQ",
        "feature.enableChatCIQPlugin",
        "EnableRequestPlugins",
        "feature.EnableSensitivityLabels",
        "EnableUnsupportedUrlDetector",
        "feature.IsCustomEngineCopilotEnabled",
        "feature.bizchatfluxv3",
        "feature.enablechatpages",
        "feature.enableCodeCanvas",
        "feature.turnOnWorkTabRecommendation",
        "feature.turnOnDARecommendation",
        "feature.IsStreamingModeInChatRequestEnabled",
        "IncludeSourceAttributionsConcise",
        "SkipPublishEmptyMessage",
        "feature.EnableDeduplicatingSourceAttributions",
        "feature.IsCitationsReferencesOutputEnabled",
        "feature.enableDeltaStreamingForReferences",
        "feature.enableIncludeReferencesInDeltaResponse",
        "feature.enablereferencesforagents",
        "Enable3PActionProgressMessages",
        "feature.enableClientWebRtc",
        "feature.EnableMeetingRecapOfSeriesMeetingWithCiq",
        "feature.EnableReferencesListCompleteSignal",
        "feature.StorageMessageSplitDisabled",
        "feature.EnableCuaTakeControlApi",
        "SingletonEnvOn",
        "cdxenablefccinmainline",
        "EnableComposeWidget",
        "feature.cwcallowedos",
        "feature.EnableMergingPureDeltas",
        "feature.disabledisallowedmsgs",
        "feature.enableCitationsForSynthesisData",
        "feature.EnableConversationShareApis",
        "feature.enableGenerateGraphicArtOptionsSet",
        "cdximagen",
        "feature.EnableUpdatedUXForConfirmationDialog",
        "feature.EnableContentApiandDocTypeHtmlInRichAnswers",
        "cdxgrounding_api_v2_rich_web_answers_reference_bottom_force",
        "cdxenablerenderforisocomp",
        "feature.EnableClientFileURLSupportForOfficeWebPaidCopilot",
        "feature.EnableDesignEditorImageGrounding",
        "feature.EnableDesignerEditor",
        "feature.EnableSkipRehydrationForSpeCIdImages",
        "feature.EnablePersonalization",
        "agt_bizchat_enableRichResponses",
        "feature.EnableBase64DataInMessageAnnotations",
        "feature.EnableSkipEmittingMessageOnFlush",
        "feature.EnableRemoveEmptySourceAttributions",
        "feature.EnableRemoveStreamingMode",
        "feature.OfficeWebToHelix",
        "feature.OfficeDesktopToHelix",
        "feature.M365TeamsHubToHelix",
        "feature.OwaHubToHelix",
        "feature.MonarchHubToHelix",
        "feature.Win32OutlookHubToHelix",
        "feature.MacOutlookHubToHelix",
        "Agt_bizchat_enableGpt5ForHelix",
    ]
)


def location_info() -> dict[str, JsonValue]:
    current = datetime.now().astimezone()
    offset = current.utcoffset()
    offset_hours = int(offset.total_seconds() // 3600) if offset is not None else 0
    timezone_name = current.tzname() or "UTC"
    if timezone_name == "Hora oficial do Brasil":
        timezone_name = "America/Sao_Paulo"
    return {
        "timeZoneOffset": offset_hours,
        "timeZone": timezone_name,
    }


def client_locale() -> str:
    language, _encoding = locale.getlocale()
    if not language:
        return "en-us"
    return language.replace("_", "-").lower()

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
    "Chat",
    "Suggestion",
    "InternalSearchQuery",
    "Disengaged",
    "InternalLoaderMessage",
    "Progress",
    "GeneratedCode",
    "RenderCardRequest",
    "AdsQuery",
    "SemanticSerp",
    "GenerateContentQuery",
    "GenerateGraphicArt",
    "SearchQuery",
    "ConfirmationCard",
    "AuthError",
    "DeveloperLogs",
    "TriggerPlugin",
    "HintInvocation",
    "MemoryUpdate",
    "EndOfRequest",
    "TriggerConfirmation",
    "ResumeInvokeAction",
    "ResumeUserInputRequest",
    "TriggerUserInputRequest",
    "EscapeHatch",
    "TriggerPluginAuth",
    "ResumePluginAuth",
    "SideBySide",
    "ReferencesListComplete",
    "SwitchRespondingEndpoint",
]

IMAGE_OPTION_SETS = [
    "search_result_progress_messages_with_search_queries",
    "update_textdoc_response_after_streaming",
    "deepleo_networking_timeout_10minutes_canmore",
    "cwc_flux_image",
    "cwc_code_interpreter",
    "cwc_code_interpreter_amsfix",
    "cwcfluxgptv",
    "flux_v3_gptv_enable_upload_multi_image_in_turn_wo_ch",
    "gptvnorm2048",
    "cwc_code_interpreter_citation_fix",
    "code_interpreter_interactive_charts",
    "cwc_code_interpreter_interactive_charts_inline_image",
    "code_interpreter_matplotlib_patching",
    "cwc_fileupload_odb",
    "update_memory_plugin",
    "add_custom_instructions",
    "cwc_flux_v3",
    "flux_v3_progress_messages",
    "enable_batch_token_processing",
    "enable_gg_gpt",
    "flux_v3_references",
    "flux_v3_references_entities",
    "flux_v3_image_gen_enable_dimensions",
    "flux_v3_image_gen_enable_non_watermarked_storage",
    "flux_v3_image_gen_enable_icon_dimensions",
    "flux_v3_image_gen_enable_system_text_with_params",
    "flux_v3_image_gen_enable_designer_dimensions_meta_prompting_in_system_prompts",
    "flux_v3_image_gen_enable_story",
    "rich_responses",
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


def image_file_annotation(annotation: M365ImageAnnotation) -> dict[str, JsonValue]:
    return {
        "id": annotation.doc_id,
        "messageAnnotationType": "ImageFile",
        "messageAnnotationMetadata": {
            "@type": "File",
            "annotationType": "File",
            "fileName": annotation.file_name,
            "fileType": annotation.file_type,
        },
    }


def local_file_annotation(annotation: M365DocumentAnnotation) -> dict[str, JsonValue]:
    return {
        "id": annotation.doc_id,
        "messageAnnotationType": "LocalFile",
        "text": annotation.file_name,
        "url": annotation.url,
    }


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
