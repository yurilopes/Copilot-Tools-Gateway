"""Microsoft 365 Copilot session parsing."""

import base64
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from copilot_tools_gateway.domain.errors import SessionExpiredError
from copilot_tools_gateway.domain.json_types import (
    JsonObject,
    int_value,
    object_value,
    optional_string_value,
    string_value,
)


def jwt_payload(token: str) -> JsonObject:
    parts = token.split(".")
    if len(parts) < 2:
        raise ValueError("Access token is not a JWT")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    decoded = base64.urlsafe_b64decode(payload)
    value = json.loads(decoded)
    return object_value(value, "jwt payload")


@dataclass(frozen=True)
class M365Session:
    access_token: str
    oid: str
    tid: str
    expires_at: int
    client_id: str | None = None

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at - 60

    @classmethod
    def from_access_token(cls, token: str) -> "M365Session":
        claims = jwt_payload(token)
        audience = str(claims.get("aud", ""))
        scopes = str(claims.get("scp", ""))
        if "substrate.office.com/sydney" not in audience and "sydney.readwrite" not in scopes:
            raise ValueError("Token is not valid for the M365 Copilot chat service")
        return cls(
            access_token=token,
            oid=string_value(claims.get("oid"), "oid"),
            tid=string_value(claims.get("tid"), "tid"),
            expires_at=int_value(claims.get("exp"), "exp"),
            client_id=optional_string_value(claims.get("appid")),
        )

    @classmethod
    def from_token_response(cls, payload: JsonObject) -> "M365Session":
        return cls.from_access_token(string_value(payload.get("access_token"), "access_token"))

    @classmethod
    def load(cls, path: Path) -> "M365Session":
        value = json.loads(path.read_text(encoding="utf-8"))
        data = object_value(value, "M365 session")
        session = cls(
            access_token=string_value(data.get("access_token"), "access_token"),
            oid=string_value(data.get("oid"), "oid"),
            tid=string_value(data.get("tid"), "tid"),
            expires_at=int_value(data.get("expires_at"), "expires_at"),
            client_id=optional_string_value(data.get("client_id")),
        )
        if session.expired:
            raise SessionExpiredError("M365 session is expired")
        return session

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
