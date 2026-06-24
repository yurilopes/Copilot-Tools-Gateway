"""Check consumer Copilot WebSocket health without exposing session data."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = ROOT / "src"
DEFAULT_JSONL_PATH = ROOT / "captures" / "consumer-websocket-health.jsonl"
EXPECTED_TEXT = "CTG consumer websocket health check"


def main() -> None:
    args = parse_args()
    add_import_path(PROJECT_SRC)
    result = run_check()
    if args.jsonl:
        args.jsonl.parent.mkdir(parents=True, exist_ok=True)
        with args.jsonl.open("a", encoding="utf-8") as file:
            file.write(json.dumps(result, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["ok"]:
        raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether consumer Copilot WebSocket chat is currently usable."
    )
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=DEFAULT_JSONL_PATH,
        help="Append a sanitized measurement result to this JSONL file.",
    )
    return parser.parse_args()


def add_import_path(path: Path) -> None:
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


def run_check() -> dict[str, object]:
    from copilot_tools_gateway.app_factory import build_registry
    from copilot_tools_gateway.domain.errors import GatewayError
    from copilot_tools_gateway.domain.models import ProviderId
    from copilot_tools_gateway.settings import GatewayPaths

    started_at = time.time()
    paths = GatewayPaths.from_cwd(ROOT)
    registry = build_registry(paths)
    try:
        provider = registry.resolve(ProviderId.CONSUMER)
        result = provider.chat(f"Reply with exactly: {EXPECTED_TEXT}")
    except GatewayError as exc:
        return {
            "checked_at": started_at,
            "ok": False,
            "session_file_age_seconds": session_file_age_seconds(paths.consumer_auth_file),
            "error": str(exc),
        }
    text = result.text.strip()
    return {
        "checked_at": started_at,
        "ok": text == EXPECTED_TEXT,
        "provider": result.provider_id.value,
        "conversation_id_present": result.conversation_id is not None,
        "response_length": len(result.text),
        "response_matches_expected": text == EXPECTED_TEXT,
        "session_file_age_seconds": session_file_age_seconds(paths.consumer_auth_file),
    }


def session_file_age_seconds(path: Path) -> float | None:
    if not path.exists():
        return None
    return max(0.0, time.time() - path.stat().st_mtime)


if __name__ == "__main__":
    main()
