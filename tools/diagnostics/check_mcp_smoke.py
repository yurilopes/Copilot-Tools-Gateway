"""Run sanitized MCP smoke checks through stdio."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = ROOT / "src"

if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))


async def run_smoke(python_command: str) -> dict[str, object]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=python_command,
        args=["-m", "copilot_tools_gateway", "mcp"],
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        checks = [
            await _call_status(session),
            await _call_list_conversations(session, "m365-copilot"),
            await _call_list_conversations(session, "copilot"),
            await _call_list_conversations(session, "copilot-auto"),
        ]
    return {
        "ok": any(check.get("ok") is True for check in checks),
        "checked_at": time.time(),
        "checks": checks,
    }


async def _call_status(session: object) -> dict[str, object]:
    response = await session.call_tool("copilot_status", {})
    payload = _response_payload(response)
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    providers = result.get("providers") if isinstance(result.get("providers"), list) else []
    return {
        "tool": "copilot_status",
        "ok": payload.get("ok") is True,
        "providers": [_safe_provider_status(item) for item in providers if isinstance(item, dict)],
    }


async def _call_list_conversations(session: object, model: str) -> dict[str, object]:
    response = await session.call_tool(
        "copilot_list_conversations",
        {"model": model, "limit": 5},
    )
    payload = _response_payload(response)
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    agent = payload.get("agent") if isinstance(payload.get("agent"), dict) else {}
    conversations = result.get("conversations")
    items = conversations if isinstance(conversations, list) else []
    return {
        "tool": "copilot_list_conversations",
        "model": model,
        "ok": payload.get("ok") is True,
        "provider": payload.get("provider"),
        "count": result.get("count"),
        "returned_items": len(items),
        "has_more": result.get("has_more"),
        "next_cursor_present": result.get("next_cursor") is not None,
        "first_item_keys": sorted(items[0].keys()) if items and isinstance(items[0], dict) else [],
        "error_code": error.get("code"),
        "recommended_action": agent.get("recommended_action"),
        "retry_after_action": agent.get("retry_after_action"),
    }


def _response_payload(response: object) -> dict[str, object]:
    content = getattr(response, "content", None)
    if not isinstance(content, list) or not content:
        return {"ok": False, "error": {"code": "empty_mcp_response"}}
    text = getattr(content[0], "text", "")
    if not isinstance(text, str):
        return {"ok": False, "error": {"code": "non_text_mcp_response"}}
    value = json.loads(text)
    return value if isinstance(value, dict) else {"ok": False, "error": {"code": "invalid_json"}}


def _safe_provider_status(item: dict[object, object]) -> dict[str, object]:
    capabilities = item.get("capabilities")
    capability_status = item.get("capability_status")
    return {
        "provider": item.get("provider"),
        "available": item.get("available"),
        "recommended_action": item.get("recommended_action"),
        "conversation_listing": _mapping_value(capabilities, "conversation_listing"),
        "capability_status": capability_status if isinstance(capability_status, dict) else {},
    }


def _mapping_value(value: object, key: str) -> object:
    if not isinstance(value, dict):
        return None
    return value.get(key)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run sanitized MCP smoke checks.")
    parser.add_argument("--python", default=str(ROOT / ".venv" / "Scripts" / "python.exe"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = asyncio.run(run_smoke(args.python))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
