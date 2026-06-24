"""Safe diagnostics for Microsoft 365 document attachment metadata."""

import hashlib
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

from copilot_tools_gateway.domain.json_types import object_value, optional_string_value

DOC_ASPX_PATH = "/_layouts/15/Doc.aspx"
DOCUMENT_LIBRARY_MARKERS = ("/Documents/", "/Shared%20Documents/", "/Shared Documents/")


@dataclass(frozen=True)
class SafeStringSummary:
    present: bool
    length: int
    digest: str | None

    @classmethod
    def from_value(cls, value: object) -> "SafeStringSummary":
        if not isinstance(value, str) or not value:
            return cls(present=False, length=0, digest=None)
        return cls(
            present=True,
            length=len(value),
            digest=hashlib.sha256(value.encode("utf-8")).hexdigest()[:12],
        )


@dataclass(frozen=True)
class SafeDocumentMetadataSummary:
    top_level_keys: list[str]
    parent_reference_keys: list[str]
    sharepoint_ids_keys: list[str]
    has_web_url: bool
    web_url_length: int
    web_url_looks_like_doc_aspx: bool
    has_sharepoint_ids: bool
    has_parent_reference: bool
    site_id: SafeStringSummary
    drive_id: SafeStringSummary
    item_id: SafeStringSummary
    list_item_unique_id: SafeStringSummary


def safe_document_metadata_summary(item: dict[str, object]) -> SafeDocumentMetadataSummary:
    parent = _optional_object(item.get("parentReference"))
    sharepoint_ids = _optional_object(item.get("sharepointIds"))
    web_url = optional_string_value(item.get("webUrl"))
    return SafeDocumentMetadataSummary(
        top_level_keys=sorted(item),
        parent_reference_keys=sorted(parent),
        sharepoint_ids_keys=sorted(sharepoint_ids),
        has_web_url=web_url is not None,
        web_url_length=len(web_url) if web_url is not None else 0,
        web_url_looks_like_doc_aspx=_is_doc_aspx_url(web_url),
        has_sharepoint_ids=bool(sharepoint_ids),
        has_parent_reference=bool(parent),
        site_id=SafeStringSummary.from_value(parent.get("siteId")),
        drive_id=SafeStringSummary.from_value(parent.get("driveId")),
        item_id=SafeStringSummary.from_value(item.get("id")),
        list_item_unique_id=SafeStringSummary.from_value(sharepoint_ids.get("listItemUniqueId")),
    )


def document_annotation_url(item: dict[str, object]) -> str:
    web_url = optional_string_value(item.get("webUrl"))
    if web_url is None:
        raise ValueError("webUrl must be a string")
    if _is_doc_aspx_url(web_url):
        return web_url
    doc_aspx_url = _doc_aspx_url_from_item(item, web_url)
    return doc_aspx_url or web_url


def _doc_aspx_url_from_item(item: dict[str, object], web_url: str) -> str | None:
    sharepoint_ids = _optional_object(item.get("sharepointIds"))
    list_item_unique_id = optional_string_value(sharepoint_ids.get("listItemUniqueId"))
    file_name = optional_string_value(item.get("name"))
    if list_item_unique_id is None or file_name is None:
        return None
    parts = urlsplit(web_url)
    site_path = _site_path_from_web_path(parts.path)
    if site_path is None:
        return None
    query = urlencode(
        {
            "sourcedoc": f"{{{list_item_unique_id}}}",
            "file": file_name,
            "action": "default",
            "mobileredirect": "true",
        },
        quote_via=quote,
    )
    return urlunsplit((parts.scheme, parts.netloc, f"{site_path}{DOC_ASPX_PATH}", query, ""))


def _site_path_from_web_path(path: str) -> str | None:
    for marker in DOCUMENT_LIBRARY_MARKERS:
        index = path.find(marker)
        if index > 0:
            return path[:index]
    return None


def _is_doc_aspx_url(url: str | None) -> bool:
    if url is None:
        return False
    parts = urlsplit(url)
    if not parts.path.endswith(DOC_ASPX_PATH):
        return False
    keys = parse_qs(parts.query)
    return {"sourcedoc", "file", "action", "mobileredirect"}.issubset(keys)


def _optional_object(value: object) -> dict[str, object]:
    try:
        return dict(object_value(value, "metadata object"))
    except ValueError:
        return {}
