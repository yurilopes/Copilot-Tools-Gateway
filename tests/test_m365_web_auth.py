import json
import time

import pytest

from copilot_tools_gateway.domain.errors import ProviderUnavailableError
from copilot_tools_gateway.providers.m365.web_auth import (
    M365_WEB_AUTH_MAX_AGE_SECONDS,
    M365WebAuth,
)


def test_m365_web_auth_filters_m365_cookies() -> None:
    auth = M365WebAuth.from_browser_cookies(
        [
            {
                "name": "m365-cookie",
                "value": "private-value",
                "domain": ".m365.cloud.microsoft",
            },
            {
                "name": "other-cookie",
                "value": "private-value",
                "domain": ".example.invalid",
            },
        ]
    )

    assert auth.cookies == {"m365-cookie": "private-value"}


def test_m365_web_auth_loads_saved_session(tmp_path) -> None:
    path = tmp_path / "web-auth.json"
    M365WebAuth(cookies={"m365-cookie": "private-value"}, saved_at=time.time()).save(path)

    auth = M365WebAuth.load(path)

    assert auth.cookies == {"m365-cookie": "private-value"}


def test_m365_web_auth_rejects_missing_empty_or_expired(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    empty = tmp_path / "empty.json"
    expired = tmp_path / "expired.json"
    empty.write_text(json.dumps({"cookies": {}, "saved_at": time.time()}), encoding="utf-8")
    expired.write_text(
        json.dumps(
            {
                "cookies": {"m365-cookie": "private-value"},
                "saved_at": time.time() - M365_WEB_AUTH_MAX_AGE_SECONDS - 1,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProviderUnavailableError):
        M365WebAuth.load(missing)
    with pytest.raises(ProviderUnavailableError):
        M365WebAuth.load(empty)
    with pytest.raises(ProviderUnavailableError):
        M365WebAuth.load(expired)
