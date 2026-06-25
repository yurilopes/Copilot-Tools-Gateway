"""Consumer Copilot attachment uploads."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from copilot_tools_gateway.domain.errors import ProviderUnavailableError, UpstreamProtocolError
from copilot_tools_gateway.providers.consumer.message_frames import ConsumerContentPart

COPILOT_URL = "https://copilot.microsoft.com"
ATTACHMENT_URL = f"{COPILOT_URL}/c/api/attachments"


@dataclass(frozen=True)
class ConsumerImageAttachment:
    url: str
    file_name: str

    def to_content_part(self) -> ConsumerContentPart:
        return {"type": "image", "url": self.url, "fileName": self.file_name}


def upload_consumer_images(
    session: object,
    image_paths: list[Path],
    timeout_seconds: int,
    access_token: str | None = None,
) -> list[ConsumerImageAttachment]:
    attachments: list[ConsumerImageAttachment] = []
    for image_path in image_paths:
        attachments.append(
            upload_consumer_image(
                session,
                image_path,
                timeout_seconds,
                access_token=access_token,
            )
        )
    return attachments


def upload_consumer_image(
    session: object,
    image_path: Path,
    timeout_seconds: int,
    access_token: str | None = None,
) -> ConsumerImageAttachment:
    if not image_path.exists():
        raise ProviderUnavailableError(f"Image file was not found: {image_path}")
    raw_bytes = image_path.read_bytes()
    if not raw_bytes:
        raise ProviderUnavailableError(f"Image file is empty: {image_path}")
    mime_type = consumer_image_mime_type(raw_bytes, image_path)
    post_method = getattr(session, "post", None)
    if not callable(post_method):
        raise UpstreamProtocolError("Consumer HTTP session cannot upload attachments")
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": mime_type,
        "origin": COPILOT_URL,
        "referer": f"{COPILOT_URL}/",
    }
    if access_token:
        headers["authorization"] = f"Bearer {access_token}"
    response = post_method(
        ATTACHMENT_URL,
        headers=headers,
        data=raw_bytes,
        timeout=timeout_seconds,
    )
    status_code = getattr(response, "status_code", 0)
    if not isinstance(status_code, int):
        raise UpstreamProtocolError("Consumer attachment status was not an integer")
    if status_code >= 400:
        raise UpstreamProtocolError(f"Consumer image upload failed: {status_code}")
    value = _response_json(response)
    if not isinstance(value, Mapping):
        raise UpstreamProtocolError("Consumer image upload response was not an object")
    url = value.get("url")
    if not isinstance(url, str) or not url:
        raise UpstreamProtocolError("Consumer image upload response did not include a URL")
    validate_attachment_url(url)
    return ConsumerImageAttachment(url=url, file_name=image_path.name)


def validate_attachment_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme and parts.scheme not in {"http", "https"}:
        raise UpstreamProtocolError("Consumer image upload response URL was invalid")
    if parts.scheme and not parts.netloc:
        raise UpstreamProtocolError("Consumer image upload response URL was invalid")
    if not parts.path:
        raise UpstreamProtocolError("Consumer image upload response URL was invalid")


def consumer_image_mime_type(raw_bytes: bytes, image_path: Path) -> str:
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw_bytes.startswith(b"\xff\xd8"):
        return "image/jpeg"
    suffix = image_path.suffix or str(image_path)
    raise ProviderUnavailableError(f"Unsupported consumer image file type: {suffix}")


def _response_json(response: object) -> object:
    json_method = getattr(response, "json", None)
    if not callable(json_method):
        raise UpstreamProtocolError("Consumer response did not expose JSON")
    return json_method()
