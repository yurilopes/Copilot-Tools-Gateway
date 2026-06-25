"""Check consumer Copilot conversation resume across MCP process restarts."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = ROOT / "src"
DEFAULT_JSONL_PATH = ROOT / "captures" / "consumer-conversation-resume.jsonl"
DEFAULT_MARKER = "CTG-CONSUMER-RESUME-20260625"
DEFAULT_TOPIC = "dark chocolate"


def main() -> None:
    args = parse_args()
    add_import_path(PROJECT_SRC)
    result = asyncio.run(run_check(args.marker, args.topic))
    if args.jsonl:
        args.jsonl.parent.mkdir(parents=True, exist_ok=True)
        with args.jsonl.open("a", encoding="utf-8") as file:
            file.write(json.dumps(result, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["ok"]:
        raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate consumer Copilot conversation resume through MCP."
    )
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=DEFAULT_JSONL_PATH,
        help="Append a sanitized resume result to this JSONL file.",
    )
    parser.add_argument(
        "--marker",
        default=DEFAULT_MARKER,
        help="Safe marker used to test resumed context.",
    )
    parser.add_argument(
        "--topic",
        default=DEFAULT_TOPIC,
        help="Safe topic used to test resumed context.",
    )
    return parser.parse_args()


def add_import_path(path: Path) -> None:
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


async def run_check(marker: str, topic: str) -> dict[str, object]:
    started_at = time.time()
    first_prompt = (
        f"Start a short test conversation about {topic}. Remember this exact marker: "
        f"{marker}. Keep the answer concise."
    )
    first_payload = await call_consumer_chat(first_prompt, None)
    if first_payload.get("ok") is not True:
        return failure_result(started_at, "first_call_failed", first_payload)

    first_result = payload_result(first_payload)
    conversation_id = first_result.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id:
        return failure_result(started_at, "missing_conversation_id", first_payload)

    resume_prompt = (
        "We are resuming a previous conversation. Without me repeating it, "
        "state the topic and the exact marker I asked you to remember."
    )
    resume_payload = await call_consumer_chat(resume_prompt, conversation_id)
    if resume_payload.get("ok") is not True:
        return failure_result(started_at, "resume_call_failed", resume_payload)

    first_text = payload_text(first_payload)
    resume_text = payload_text(resume_payload)
    marker_found = marker in resume_text
    topic_found = topic.lower() in resume_text.lower()
    return {
        "checked_at": started_at,
        "ok": marker_found and topic_found,
        "provider": "copilot",
        "conversation_id": conversation_id,
        "first_response_length": len(first_text),
        "resume_response_length": len(resume_text),
        "marker_found": marker_found,
        "topic_found": topic_found,
        "process_restart_tested": True,
    }


async def call_consumer_chat(prompt: str, conversation_id: str | None) -> dict[str, object]:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    arguments: dict[str, object] = {
        "model": "copilot",
        "prompt": prompt,
    }
    if conversation_id is not None:
        arguments["conversation_id"] = conversation_id
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "copilot_tools_gateway", "mcp"],
        cwd=str(ROOT),
    )
    async with stdio_client(parameters) as streams, ClientSession(
        streams[0],
        streams[1],
    ) as session:
        await session.initialize()
        result = await session.call_tool("copilot_chat", arguments)
        return first_json_object(result.content)


def failure_result(
    started_at: float,
    reason: str,
    payload: dict[str, object],
) -> dict[str, object]:
    error = payload.get("error")
    error_code: str | None = None
    if isinstance(error, Mapping):
        code = error.get("code")
        error_code = code if isinstance(code, str) else None
    return {
        "checked_at": started_at,
        "ok": False,
        "provider": "copilot",
        "reason": reason,
        "error_code": error_code,
    }


def payload_result(payload: dict[str, object]) -> dict[str, object]:
    result = payload.get("result")
    return result if isinstance(result, dict) else {}


def payload_text(payload: dict[str, object]) -> str:
    text = payload_result(payload).get("text")
    return text if isinstance(text, str) else ""


def first_json_object(content: object) -> dict[str, object]:
    if not isinstance(content, list):
        return {"ok": False, "error": {"code": "invalid_mcp_content"}}
    for item in content:
        text = getattr(item, "text", None)
        if not isinstance(text, str):
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {"ok": False, "error": {"code": "missing_mcp_json"}}


if __name__ == "__main__":
    main()
