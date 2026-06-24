"""Upload helpers for Microsoft 365 Copilot attachments."""

import base64
import binascii
import json
import mimetypes
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from copilot_tools_gateway.domain.errors import ProviderUnavailableError, UpstreamProtocolError
from copilot_tools_gateway.domain.json_types import object_value, string_value
from copilot_tools_gateway.providers.m365.auth import M365Session
from copilot_tools_gateway.providers.m365.document_diagnostics import document_annotation_url

UPLOAD_URL = "https://substrate.office.com/m365Copilot/UploadFile"
UNFURL_URL = "https://substrate.office.com/searchservice/api/v1/unfurl?domain=prod"
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
UPLOAD_OPTIONS = [
    "cwcgptvsan",
    "flux_v3_gptv_enable_upload_multi_image_in_turn_wo_ch",
    "gptvnorm2048",
]


@dataclass(frozen=True)
class M365ImageAnnotation:
    doc_id: str
    file_name: str
    file_type: str

    def to_message_annotation(self) -> dict[str, object]:
        return {
            "id": self.doc_id,
            "messageAnnotationType": "ImageFile",
            "messageAnnotationMetadata": {
                "@type": "File",
                "annotationType": "File",
                "fileName": self.file_name,
                "fileType": self.file_type,
            },
        }


@dataclass(frozen=True)
class M365DocumentAnnotation:
    doc_id: str
    url: str
    file_name: str

    def to_message_annotation(self) -> dict[str, object]:
        return {
            "id": self.doc_id,
            "messageAnnotationType": "LocalFile",
            "text": self.file_name,
            "url": self.url,
        }


def upload_image(
    session: M365Session,
    image_path: Path,
    timeout_seconds: float,
) -> M365ImageAnnotation:
    if not image_path.exists():
        raise ProviderUnavailableError(f"Image file was not found: {image_path}")
    raw_bytes = image_path.read_bytes()
    if not raw_bytes:
        raise ProviderUnavailableError(f"Image file is empty: {image_path}")

    file_name = image_path.name
    file_type = _image_file_type(image_path)
    encoded_file = base64.b64encode(raw_bytes).decode("ascii")
    conversation_id = str(uuid.uuid4())
    boundary = f"----CopilotToolsGateway{uuid.uuid4().hex}"
    body = _multipart_body(
        boundary=boundary,
        conversation_id=conversation_id,
        encoded_file=f"data:image/{file_type};base64,{encoded_file}",
    )
    headers = {
        "Authorization": f"Bearer {session.access_token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Origin": "https://m365.cloud.microsoft",
        "x-anchormailbox": f"{session.oid}@{session.tid}",
        "x-scenario": "OfficeWebIncludedCopilot",
        "x-variants": "feature.EnableImageSupportInUploadFile",
    }
    request = Request(
        UPLOAD_URL,
        data=body,
        headers=headers,
        method="POST",
    )
    payload = _json_request(request, timeout_seconds, "M365 image upload")
    data = object_value(payload, "M365 upload response")
    doc_id = string_value(data.get("docId"), "docId")
    return M365ImageAnnotation(doc_id=doc_id, file_name=file_name, file_type=file_type)


def upload_document(
    graph_token: str,
    document_path: Path,
    timeout_seconds: float,
) -> M365DocumentAnnotation:
    if not document_path.exists():
        raise ProviderUnavailableError(f"Document file was not found: {document_path}")
    raw_bytes = document_path.read_bytes()
    if not raw_bytes:
        raise ProviderUnavailableError(f"Document file is empty: {document_path}")

    _prepare_document_upload(graph_token, timeout_seconds)
    upload_url = _create_graph_upload_session(graph_token, document_path.name, timeout_seconds)
    item = _upload_graph_file(upload_url, raw_bytes, timeout_seconds)
    _read_sensitivity_label(graph_token, item, timeout_seconds)
    enriched_item = _read_document_metadata(graph_token, item, timeout_seconds)
    _read_root_site_url(graph_token, timeout_seconds)
    file_name = string_value(item.get("name"), "name")
    return M365DocumentAnnotation(
        doc_id=_sharepoint_document_id(enriched_item),
        url=document_annotation_url(item),
        file_name=file_name,
    )


def unfurl_document(
    session: M365Session,
    search_token: str,
    annotation: M365DocumentAnnotation,
    timeout_seconds: float,
) -> None:
    body = json.dumps(
        _unfurl_document_body(annotation),
        separators=(",", ":"),
    ).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {search_token}",
        "Content-Type": "application/json",
        "Origin": "https://m365.cloud.microsoft",
        "Referer": "https://m365.cloud.microsoft/chat/",
        "x-anchormailbox": f"OID:{session.oid}@{session.tid}",
        "x-routingparameter-sessionkey": f"OID:{session.oid}@{session.tid}",
        "client-request-id": str(uuid.uuid4()),
        "client-session-id": str(uuid.uuid4()),
        "x-client-language": "pt-br",
        "x-client-localtime": datetime.now().astimezone().isoformat(timespec="milliseconds"),
    }
    request = Request(
        UNFURL_URL,
        data=body,
        headers=headers,
        method="POST",
    )
    _json_request(request, timeout_seconds, "M365 document unfurl")


def _unfurl_document_body(annotation: M365DocumentAnnotation) -> dict[str, object]:
    return {
        "EntityRequests": [
            {
                "QueryAnnotations": [
                    {
                        "Id": annotation.doc_id,
                        "Type": "LocalFile",
                        "Text": annotation.file_name,
                    }
                ],
                "PreferredResultSourceFormat": "EntityData",
                "SupportedResultSourceFormats": ["EntityData"],
            }
        ],
        "LogicalId": str(uuid.uuid4()),
        "Cvid": str(uuid.uuid4()),
        "Scenario": {
            "Name": "Harmony.Web.Copilot_Drawer",
            "Dimensions": [
                {
                    "DimensionName": "ScenarioDescription",
                    "DimensionValue": (
                        "OfficeWebIncludedCopilot.prefetch.getdocumentsummary.fileupload"
                    ),
                },
                {
                    "DimensionName": "ScenarioType",
                    "DimensionValue": "PO",
                },
            ],
        },
        "CacheMode": "FireForget",
    }


def _prepare_document_upload(graph_token: str, timeout_seconds: float) -> None:
    # The M365 web client warms these endpoints before upload. Some delegated
    # Graph tokens cannot read the tenant label catalog, so this is best-effort.
    for path, operation in (
        ("/me/informationProtection/sensitivityLabels", "Graph sensitivity label catalog"),
        ("/me/drive/special/copilotuploads", "Graph Copilot uploads folder"),
    ):
        try:
            _graph_get(graph_token, path, timeout_seconds, operation)
        except UpstreamProtocolError:
            continue


def _create_graph_upload_session(
    graph_token: str,
    file_name: str,
    timeout_seconds: float,
) -> str:
    encoded_name = quote(file_name)
    body = json.dumps(
        {"item": {"@microsoft.graph.conflictBehavior": "replace", "name": file_name}},
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        f"{GRAPH_BASE_URL}/me/drive/special/copilotuploads:/{encoded_name}:/createUploadSession",
        data=body,
        headers={
            "Accept": "*/*",
            "Authorization": f"Bearer {graph_token}",
            "Content-Type": "application/json",
            "Origin": "https://m365.cloud.microsoft",
        },
        method="POST",
    )
    payload = _json_request(request, timeout_seconds, "Graph upload session")
    data = object_value(payload, "Graph upload session")
    return string_value(data.get("uploadUrl"), "uploadUrl")


def _upload_graph_file(
    upload_url: str,
    raw_bytes: bytes,
    timeout_seconds: float,
) -> dict[str, object]:
    request = Request(
        upload_url,
        data=raw_bytes,
        headers=_sharepoint_upload_headers(len(raw_bytes)),
        method="PUT",
    )
    payload = _json_request(request, timeout_seconds, "Graph file upload")
    return dict(object_value(payload, "Graph drive item"))


def _sharepoint_upload_headers(byte_count: int) -> dict[str, str]:
    return {
        "Content-Range": f"bytes 0-{byte_count - 1}/{byte_count}",
        "Content-Type": "application/octet-stream",
        "Prefer": "ExtractTextOnCommit, pacToken=N",
    }


def _read_sensitivity_label(
    graph_token: str,
    item: dict[str, object],
    timeout_seconds: float,
) -> None:
    parent = object_value(item.get("parentReference"), "parentReference")
    drive_id = string_value(parent.get("driveId"), "driveId")
    item_id = string_value(item.get("id"), "id")
    request = Request(
        f"{GRAPH_BASE_URL}/drives/{drive_id}/items/{item_id}?$select=sensitivityLabel",
        headers=_graph_headers(graph_token),
        method="GET",
    )
    _json_request(request, timeout_seconds, "Graph sensitivity label")


def _read_document_metadata(
    graph_token: str,
    item: dict[str, object],
    timeout_seconds: float,
) -> dict[str, object]:
    parent = object_value(item.get("parentReference"), "parentReference")
    drive_id = string_value(parent.get("driveId"), "driveId")
    item_id = string_value(item.get("id"), "id")
    request = Request(
        (
            f"{GRAPH_BASE_URL}/drives/{drive_id}/items/{item_id}"
            "?$select=id,name,webUrl,parentReference,sharepointIds,file,size"
        ),
        headers=_graph_headers(graph_token),
        method="GET",
    )
    payload = _json_request(request, timeout_seconds, "Graph document metadata")
    return dict(object_value(payload, "Graph document metadata"))


def _read_root_site_url(graph_token: str, timeout_seconds: float) -> None:
    try:
        _graph_get(
            graph_token,
            "/sites/root/sharepointIds/siteUrl",
            timeout_seconds,
            "Graph SharePoint root site URL",
        )
    except UpstreamProtocolError:
        return


def _graph_get(
    graph_token: str,
    path: str,
    timeout_seconds: float,
    operation: str,
) -> object:
    request = Request(
        f"{GRAPH_BASE_URL}{path}",
        headers=_graph_headers(graph_token),
        method="GET",
    )
    return _json_request(request, timeout_seconds, operation)


def _graph_headers(graph_token: str) -> dict[str, str]:
    return {
        "Accept": "*/*",
        "Authorization": f"Bearer {graph_token}",
        "Origin": "https://m365.cloud.microsoft",
    }


def _multipart_body(boundary: str, conversation_id: str, encoded_file: str) -> bytes:
    lines: list[str] = []
    _append_form_field(lines, boundary, "scenario", "UploadImage")
    _append_form_field(lines, boundary, "conversationId", conversation_id)
    _append_form_field(lines, boundary, "FileBase64", encoded_file)
    for option_set in UPLOAD_OPTIONS:
        _append_form_field(lines, boundary, "optionsSets", option_set)
    lines.append(f"--{boundary}--")
    lines.append("")
    return "\r\n".join(lines).encode("utf-8")


def _append_form_field(lines: list[str], boundary: str, name: str, value: str) -> None:
    lines.append(f"--{boundary}")
    lines.append(f'Content-Disposition: form-data; name="{name}"')
    lines.append("")
    lines.append(value)


def _image_file_type(image_path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(str(image_path))
    if mime_type is None or not mime_type.startswith("image/"):
        unsupported_type = image_path.suffix or str(image_path)
        raise ProviderUnavailableError(f"Unsupported image file type: {unsupported_type}")
    file_type = mime_type.split("/", maxsplit=1)[1].lower()
    if not file_type:
        raise UpstreamProtocolError("Could not determine image file type for M365 upload")
    return file_type


def _sharepoint_document_id(item: dict[str, object]) -> str:
    sharepoint_ids = object_value(item.get("sharepointIds"), "sharepointIds")
    raw_prefix = (
        string_value(sharepoint_ids.get("siteId"), "siteId")
        + ","
        + string_value(sharepoint_ids.get("webId"), "webId")
        + ","
        + string_value(sharepoint_ids.get("listId"), "listId")
        + "?"
    ).encode("utf-8")
    item_id = string_value(item.get("id"), "id")
    _base64url_decode(item_id)
    encoded_prefix = base64.urlsafe_b64encode(raw_prefix).decode("ascii").rstrip("=")
    encoded = f"{encoded_prefix}{item_id}"
    return f"SPO_{encoded}"


def _base64url_decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as exc:
        raise UpstreamProtocolError("Graph item id was not valid base64url") from exc


def _json_request(request: Request, timeout_seconds: float, operation: str) -> object:
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise UpstreamProtocolError(f"{operation} failed with HTTP {exc.code}") from exc
    except URLError as exc:
        raise UpstreamProtocolError(f"{operation} failed") from exc
    except json.JSONDecodeError as exc:
        raise UpstreamProtocolError(f"{operation} returned invalid JSON") from exc
