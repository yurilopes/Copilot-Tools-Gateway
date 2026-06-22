"""Consumer Copilot session storage."""

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from copilot_tools_gateway.domain.errors import ProviderUnavailableError
from copilot_tools_gateway.domain.json_types import object_value, optional_string_value

AUTH_MAX_AGE_SECONDS = 50 * 60


@dataclass(frozen=True)
class ConsumerAuth:
    cookies: dict[str, str]
    access_token: str | None
    saved_at: float

    @property
    def expired(self) -> bool:
        return time.time() - self.saved_at >= AUTH_MAX_AGE_SECONDS

    @classmethod
    def load(cls, path: Path) -> "ConsumerAuth":
        if not path.exists():
            raise ProviderUnavailableError("Consumer session file was not found")
        value = json.loads(path.read_text(encoding="utf-8"))
        data = object_value(value, "consumer session")
        cookies_value = object_value(data.get("cookies"), "cookies")
        cookies: dict[str, str] = {}
        for key, cookie_value in cookies_value.items():
            if isinstance(key, str) and isinstance(cookie_value, str):
                cookies[key] = cookie_value
        saved_at_value = data.get("saved_at")
        saved_at = float(saved_at_value) if isinstance(saved_at_value, int | float) else 0.0
        auth = cls(
            cookies=cookies,
            access_token=optional_string_value(data.get("access_token")),
            saved_at=saved_at,
        )
        if not auth.cookies and auth.access_token is None:
            raise ProviderUnavailableError("Consumer session contains no cookies or access token")
        return auth

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
