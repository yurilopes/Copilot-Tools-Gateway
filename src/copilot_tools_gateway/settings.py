"""Project paths and runtime settings."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GatewayPaths:
    root: Path
    session_dir: Path
    m365_token_file: Path
    consumer_auth_file: Path
    consumer_profile_dir: Path

    @classmethod
    def from_cwd(cls, cwd: Path | None = None) -> "GatewayPaths":
        root = (cwd or Path.cwd()).resolve()
        session_dir = root / "session"
        return cls(
            root=root,
            session_dir=session_dir,
            m365_token_file=session_dir / "m365" / "token.json",
            consumer_auth_file=session_dir / "consumer" / "token.json",
            consumer_profile_dir=session_dir / "consumer" / "profile",
        )
