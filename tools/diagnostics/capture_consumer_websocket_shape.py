"""Capture sanitized consumer Copilot WebSocket shape with direct Pydoll.

This diagnostic tool records only derived metadata such as keys, lengths,
public event names, and short hashes. It does not write raw WebSocket payloads,
cookies, tokens, browser storage, or session files.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = ROOT / "src"
DEFAULT_PYDOLL_ROOT = ROOT.parent / "pydoll"
DEFAULT_OUTPUT_PATH = ROOT / "captures" / "consumer-websocket-shape.json"
DEFAULT_STATUS_PATH = ROOT / "captures" / "consumer-websocket-shape-status.json"
COPILOT_URL = "https://copilot.microsoft.com/"


def main() -> None:
    args = parse_args()
    add_import_path(PROJECT_SRC)
    add_import_path(args.pydoll_root)
    asyncio.run(capture(args))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture sanitized consumer Copilot WebSocket frame shapes."
    )
    parser.add_argument(
        "--seconds",
        type=int,
        default=900,
        help="Seconds to keep the browser open for manual interaction.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path for sanitized capture JSON.",
    )
    parser.add_argument(
        "--status",
        type=Path,
        default=DEFAULT_STATUS_PATH,
        help="Path for status JSON.",
    )
    parser.add_argument(
        "--pydoll-root",
        type=Path,
        default=DEFAULT_PYDOLL_ROOT,
        help="Local Pydoll checkout root. Pydoll is optional and not a project dependency.",
    )
    return parser.parse_args()


def add_import_path(path: Path) -> None:
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


async def capture(args: argparse.Namespace) -> None:
    from pydoll.browser.chromium import Chrome
    from pydoll.browser.options import ChromiumOptions
    from pydoll.protocol.network.events import NetworkEvent

    from copilot_tools_gateway.settings import GatewayPaths

    records: list[dict[str, object]] = []
    tracked_request_ids: set[str] = set()
    paths = GatewayPaths.from_cwd(ROOT)
    paths.consumer_profile_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.status.parent.mkdir(parents=True, exist_ok=True)

    options = ChromiumOptions()
    options.add_argument(f"--user-data-dir={paths.consumer_profile_dir}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    options.start_timeout = 30

    write_json(args.status, {"state": "starting", "output": str(args.output)})
    async with Chrome(options=options) as browser:
        tab = await browser.start()
        await tab.enable_network_events()
        await tab.on(
            NetworkEvent.WEBSOCKET_CREATED,
            lambda event: record_websocket_created(records, tracked_request_ids, event),
        )
        await tab.on(
            NetworkEvent.WEBSOCKET_FRAME_SENT,
            lambda event: record_websocket_frame(records, tracked_request_ids, "sent", event),
        )
        await tab.on(
            NetworkEvent.WEBSOCKET_FRAME_RECEIVED,
            lambda event: record_websocket_frame(records, tracked_request_ids, "received", event),
        )
        await tab.go_to(COPILOT_URL, timeout=45)
        write_json(
            args.status,
            {"state": "capturing", "seconds": args.seconds, "output": str(args.output)},
        )
        for _ in range(args.seconds):
            await asyncio.sleep(1)
            write_json(args.output, records)

    write_json(args.output, records)
    write_json(
        args.status,
        {
            "state": "done",
            "record_count": len(records),
            "append_count": count_events(records, "appendText"),
            "output": str(args.output),
        },
    )


def record_websocket_created(
    records: list[dict[str, object]],
    tracked_request_ids: set[str],
    event: Mapping[str, object],
) -> None:
    params = event.get("params")
    if not isinstance(params, Mapping):
        return
    url = params.get("url")
    request_id = params.get("requestId")
    if not isinstance(url, str) or not isinstance(request_id, str):
        return
    if "copilot.microsoft.com" not in url:
        return
    tracked_request_ids.add(request_id)
    records.append(
        {
            "kind": "websocket",
            "time": time.time(),
            "request_id_hash": short_hash(request_id),
            "url_shape": summarize_url(url),
        }
    )


def record_websocket_frame(
    records: list[dict[str, object]],
    tracked_request_ids: set[str],
    direction: str,
    event: Mapping[str, object],
) -> None:
    params = event.get("params")
    if not isinstance(params, Mapping):
        return
    request_id = params.get("requestId")
    if not isinstance(request_id, str) or request_id not in tracked_request_ids:
        return
    response = params.get("response")
    if not isinstance(response, Mapping):
        return
    payload = response.get("payloadData")
    if not isinstance(payload, str):
        return
    records.append(
        {
            "kind": direction,
            "time": time.time(),
            "request_id_hash": short_hash(request_id),
            "summary": summarize_payload(payload),
        }
    )


def summarize_url(url: str) -> dict[str, object]:
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    return {
        "scheme": parts.scheme,
        "host": parts.netloc,
        "path": parts.path,
        "query_keys": sorted(query),
        "has_access_token": "accessToken" in query,
        "access_token_length": first_query_value_length(query, "accessToken"),
        "client_session_id_length": first_query_value_length(query, "clientSessionId"),
    }


def first_query_value_length(query: dict[str, list[str]], key: str) -> int | None:
    values = query.get(key)
    if not values:
        return None
    return len(values[0])


def summarize_payload(payload: str) -> dict[str, object]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return {"format": "text", "length": len(payload), "hash": short_hash(payload)}
    return summarize_value(value, len(payload))


def summarize_value(value: object, payload_length: int) -> dict[str, object]:
    if isinstance(value, Mapping):
        return summarize_mapping(value, payload_length)
    if isinstance(value, Sequence) and not isinstance(value, str):
        return {"format": "array", "length": payload_length, "item_count": len(value)}
    return {"format": "json", "length": payload_length, "value_type": type(value).__name__}


def summarize_mapping(value: Mapping[object, object], payload_length: int) -> dict[str, object]:
    result: dict[str, object] = {
        "format": "object",
        "keys": sorted(str(key) for key in value),
        "length": payload_length,
    }
    copy_public_strings(value, result)
    copy_string_lengths(value, result)
    copy_collection_shapes(value, result)
    return result


def copy_public_strings(
    value: Mapping[object, object],
    result: dict[str, object],
) -> None:
    for key in ("event", "method", "mode", "errorCode", "source", "type"):
        item = value.get(key)
        if isinstance(item, str):
            result[str(key)] = item


def copy_string_lengths(
    value: Mapping[object, object],
    result: dict[str, object],
) -> None:
    for key in ("conversationId", "requestId", "id", "token", "parameter", "text"):
        item = value.get(key)
        if isinstance(item, str):
            result[f"{key}_length"] = len(item)
            result[f"{key}_hash"] = short_hash(item)


def copy_collection_shapes(
    value: Mapping[object, object],
    result: dict[str, object],
) -> None:
    for key in ("content", "messages", "supportedFeatures", "supportedActions", "supportedCards"):
        item = value.get(key)
        if isinstance(item, Sequence) and not isinstance(item, str):
            result[f"{key}_length"] = len(item)
            if item and isinstance(item[0], Mapping):
                result[f"first_{key}_keys"] = sorted(str(item_key) for item_key in item[0])
                first_type = item[0].get("type")
                if isinstance(first_type, str):
                    result[f"first_{key}_type"] = first_type
    for key in ("context", "options", "metadata"):
        item = value.get(key)
        if isinstance(item, Mapping):
            result[f"{key}_keys"] = sorted(str(item_key) for item_key in item)


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def count_events(records: list[dict[str, object]], event_name: str) -> int:
    count = 0
    for record in records:
        summary = record.get("summary")
        if isinstance(summary, Mapping) and summary.get("event") == event_name:
            count += 1
    return count


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
