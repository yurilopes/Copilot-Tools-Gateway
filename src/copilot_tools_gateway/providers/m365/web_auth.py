"""Microsoft 365 Copilot web session storage."""

import json
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from copilot_tools_gateway.domain.errors import ProviderUnavailableError
from copilot_tools_gateway.domain.json_types import object_value, sequence_value

M365_WEB_AUTH_MAX_AGE_SECONDS = 50 * 60
M365_WEB_COOKIE_DOMAIN = "m365.cloud.microsoft"


@dataclass(frozen=True)
class M365WebAuth:
    cookies: dict[str, str]
    saved_at: float

    @property
    def expired(self) -> bool:
        return time.time() - self.saved_at >= M365_WEB_AUTH_MAX_AGE_SECONDS

    @classmethod
    def load(cls, path: Path) -> "M365WebAuth":
        if not path.exists():
            raise ProviderUnavailableError("M365 web session is missing or expired")
        value = json.loads(path.read_text(encoding="utf-8"))
        data = object_value(value, "M365 web session")
        cookies_value = object_value(data.get("cookies"), "cookies")
        cookies: dict[str, str] = {}
        for key, cookie_value in cookies_value.items():
            if isinstance(key, str) and isinstance(cookie_value, str):
                cookies[key] = cookie_value
        saved_at_value = data.get("saved_at")
        saved_at = float(saved_at_value) if isinstance(saved_at_value, int | float) else 0.0
        auth = cls(cookies=cookies, saved_at=saved_at)
        if not auth.cookies or auth.expired:
            raise ProviderUnavailableError("M365 web session is missing or expired")
        return auth

    @classmethod
    def from_browser_cookies(cls, values: object) -> "M365WebAuth":
        cookies: dict[str, str] = {}
        for value in sequence_value(values):
            if not isinstance(value, Mapping):
                continue
            name = value.get("name")
            cookie_value = value.get("value")
            domain = value.get("domain")
            if not isinstance(name, str) or not isinstance(cookie_value, str):
                continue
            if isinstance(domain, str) and M365_WEB_COOKIE_DOMAIN not in domain:
                continue
            cookies[name] = cookie_value
        return cls(cookies=cookies, saved_at=time.time())

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
