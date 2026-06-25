import base64

import pytest

from copilot_tools_gateway.domain.errors import (
    ProviderUnavailableError,
    UpstreamProtocolError,
)
from copilot_tools_gateway.providers.consumer.challenges import solve_hashcash
from copilot_tools_gateway.providers.consumer.driver import (
    CONSUMER_BROWSER_CHALLENGE_MESSAGE,
    ConsumerDriver,
)
from copilot_tools_gateway.providers.consumer.uploads import (
    ATTACHMENT_URL,
    consumer_image_mime_type,
    upload_consumer_image,
    validate_attachment_url,
)


class FakeUploadResponse:
    status_code = 200

    def json(self) -> dict[str, str]:
        return {"url": "/images/uploaded.png"}


class FakeUploadSession:
    def __init__(self) -> None:
        self.url: str | None = None
        self.headers: dict[str, str] | None = None
        self.data_length: int | None = None
        self.timeout: int | None = None

    def post(
        self,
        url: str,
        headers: dict[str, str],
        data: bytes,
        timeout: int,
    ) -> FakeUploadResponse:
        self.url = url
        self.headers = headers
        self.data_length = len(data)
        self.timeout = timeout
        return FakeUploadResponse()


def test_hashcash_accepts_plain_parameter() -> None:
    token = solve_hashcash("seed:0")

    assert token == "0"


def test_hashcash_accepts_base64url_parameter() -> None:
    parameter = base64.urlsafe_b64encode(b"seed:0").decode("ascii").rstrip("=")

    token = solve_hashcash(parameter)

    assert token == "0"


def test_cloudflare_challenge_requires_browser_refresh() -> None:
    with pytest.raises(UpstreamProtocolError) as exc_info:
        ConsumerDriver._solve_challenge({"method": "cloudflare"})

    assert str(exc_info.value) == CONSUMER_BROWSER_CHALLENGE_MESSAGE


def test_chat_service_unavailable_requires_browser_refresh() -> None:
    with pytest.raises(UpstreamProtocolError) as exc_info:
        raise ConsumerDriver._error_event({"errorCode": "chat-service-unavailable"})

    assert str(exc_info.value) == CONSUMER_BROWSER_CHALLENGE_MESSAGE


def test_consumer_image_mime_type_accepts_png(tmp_path) -> None:
    path = tmp_path / "image.png"

    assert consumer_image_mime_type(b"\x89PNG\r\n\x1a\npayload", path) == "image/png"


def test_consumer_image_mime_type_accepts_jpeg(tmp_path) -> None:
    path = tmp_path / "image.jpg"

    assert consumer_image_mime_type(b"\xff\xd8payload", path) == "image/jpeg"


def test_consumer_image_mime_type_rejects_document(tmp_path) -> None:
    path = tmp_path / "document.docx"

    with pytest.raises(ProviderUnavailableError) as exc_info:
        consumer_image_mime_type(b"PK\x03\x04payload", path)

    assert "Unsupported consumer image file type" in str(exc_info.value)


def test_consumer_driver_uploads_image_attachment(tmp_path) -> None:
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"\xff\xd8payload")
    session = FakeUploadSession()

    attachment = upload_consumer_image(session, image_path, timeout_seconds=30)

    assert session.url == ATTACHMENT_URL
    assert session.headers == {
        "accept": "application/json, text/plain, */*",
        "content-type": "image/jpeg",
        "origin": "https://copilot.microsoft.com",
        "referer": "https://copilot.microsoft.com/",
    }
    assert session.data_length == len(b"\xff\xd8payload")
    assert session.timeout == 30
    assert attachment.to_content_part() == {
        "type": "image",
        "url": "/images/uploaded.png",
        "fileName": "image.jpg",
    }


def test_consumer_driver_uploads_image_attachment_with_access_token(tmp_path) -> None:
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"\xff\xd8payload")
    session = FakeUploadSession()

    upload_consumer_image(
        session,
        image_path,
        timeout_seconds=30,
        access_token="access-token",
    )

    assert session.headers == {
        "accept": "application/json, text/plain, */*",
        "authorization": "Bearer access-token",
        "content-type": "image/jpeg",
        "origin": "https://copilot.microsoft.com",
        "referer": "https://copilot.microsoft.com/",
    }


def test_consumer_attachment_url_accepts_absolute_url() -> None:
    validate_attachment_url("https://copilot.microsoft.com/images/uploaded.png")
