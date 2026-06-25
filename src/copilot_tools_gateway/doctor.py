"""Safe local health checks for Copilot Tools Gateway."""

import importlib.util
import json
import time
from pathlib import Path

from copilot_tools_gateway.app_factory import build_registry
from copilot_tools_gateway.mcp_responses import mcp_status_response
from copilot_tools_gateway.settings import GatewayPaths


def doctor_report(paths: GatewayPaths) -> dict[str, object]:
    statuses = build_registry(paths).list_statuses()
    return {
        "ok": any(status.available for status in statuses),
        "checked_at": time.time(),
        "dependencies": _dependency_report(),
        "session_files": _session_file_report(paths),
        "provider_status": mcp_status_response(statuses)["result"],
        "notes": [
            "This report never includes session file contents.",
            "Run the recommended command for any provider or capability that needs action.",
        ],
    }


def print_doctor_report(paths: GatewayPaths) -> None:
    print(json.dumps(doctor_report(paths), indent=2, sort_keys=True))


def _dependency_report() -> list[dict[str, object]]:
    return [
        {"name": name, "importable": importlib.util.find_spec(module) is not None}
        for name, module in (
            ("curl-cffi", "curl_cffi"),
            ("fastapi", "fastapi"),
            ("mcp", "mcp"),
            ("playwright", "playwright"),
            ("pydoll", "pydoll"),
            ("uvicorn", "uvicorn"),
            ("websockets", "websockets"),
        )
    ]


def _session_file_report(paths: GatewayPaths) -> list[dict[str, object]]:
    return [
        _file_state("consumer_auth", paths.consumer_auth_file),
        _file_state("m365_chat_session", paths.m365_token_file),
        _file_state("m365_graph_session", paths.m365_graph_token_file),
        _file_state("m365_search_session", paths.m365_search_token_file),
        _file_state("m365_web_auth", paths.m365_web_auth_file),
    ]


def _file_state(name: str, path: Path) -> dict[str, object]:
    if not path.exists():
        return {"name": name, "present": False, "age_seconds": None}
    return {
        "name": name,
        "present": True,
        "age_seconds": max(0, int(time.time() - path.stat().st_mtime)),
    }
