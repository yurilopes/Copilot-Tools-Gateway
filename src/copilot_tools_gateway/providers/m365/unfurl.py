"""M365 document unfurl helpers."""

import json
import uuid
from datetime import datetime
from urllib.request import Request

from copilot_tools_gateway.domain.errors import UpstreamProtocolError
from copilot_tools_gateway.providers.m365.auth import M365Session
from copilot_tools_gateway.providers.m365.uploads import M365DocumentAnnotation, json_request

UNFURL_URL = "https://substrate.office.com/searchservice/api/v1/unfurl?domain=prod"


def unfurl_document(
    session: M365Session,
    search_token: str,
    annotation: M365DocumentAnnotation,
    timeout_seconds: float,
) -> None:
    body = json.dumps(
        unfurl_document_body(annotation),
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        UNFURL_URL,
        data=body,
        headers=_unfurl_headers(session, search_token),
        method="POST",
    )
    json_request(request, timeout_seconds, "M365 document unfurl")


def try_unfurl_document(
    session: M365Session,
    search_token: str,
    annotation: M365DocumentAnnotation,
    timeout_seconds: float,
) -> bool:
    try:
        unfurl_document(session, search_token, annotation, timeout_seconds)
    except UpstreamProtocolError:
        return False
    return True


def unfurl_document_body(annotation: M365DocumentAnnotation) -> dict[str, object]:
    return {
        "EntityRequests": [
            {
                "QueryAnnotations": [
                    {
                        "Id": annotation.doc_id,
                        "Type": "LocalFile",
                        "Text": annotation.file_name,
                        "Url": annotation.url,
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


def _unfurl_headers(session: M365Session, search_token: str) -> dict[str, str]:
    mailbox = f"OID:{session.oid}@{session.tid}"
    request_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {search_token}",
        "Content-Type": "application/json",
        "Origin": "https://m365.cloud.microsoft",
        "Referer": "https://m365.cloud.microsoft/chat/",
        "x-anchormailbox": mailbox,
        "x-routingparameter-sessionkey": mailbox,
        "client-request-id": request_id,
        "client-session-id": session_id,
        "x-client-language": "pt-br",
        "x-client-localtime": datetime.now().astimezone().isoformat(timespec="milliseconds"),
    }
