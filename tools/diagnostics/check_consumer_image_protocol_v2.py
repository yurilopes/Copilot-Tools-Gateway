"""Run sanitized consumer Copilot image protocol discovery."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections.abc import Iterator, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = ROOT / "src"
DEFAULT_IMAGE_PATH = ROOT / "captures" / "ctg-attach-image.png"
DEFAULT_OUTPUT_PATH = ROOT / "captures" / "consumer-image-protocol-v2.jsonl"
DEFAULT_PROMPT = "Read the exact text in this image. Return only the text."
EXPECTED_MARKER = "CTG_ATTACH_IMAGE_1"


def main() -> None:
    args = parse_args()
    add_import_path(ROOT)
    add_import_path(PROJECT_SRC)
    result = asyncio.run(run_protocol_discovery(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl(args.output, result)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run sanitized consumer image protocol discovery."
    )
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE_PATH)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--skip-ui", action="store_true")
    return parser.parse_args()


def add_import_path(path: Path) -> None:
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


async def run_protocol_discovery(args: argparse.Namespace) -> dict[str, object]:
    if not args.image.exists():
        return {"ok": False, "error": "image file was not found", "image": str(args.image)}
    ui_result: dict[str, object] | None = None
    if not args.skip_ui:
        ui_result = await capture_ui_image_shape(args.image, args.prompt)
    direct_results = list(run_direct_candidate_matrix(args.image, args.prompt))
    return {
        "ok": any(result.get("passed") is True for result in direct_results),
        "timestamp": time.time(),
        "image_name": args.image.name,
        "ui_capture": ui_result,
        "direct_candidates": direct_results,
    }


async def capture_ui_image_shape(image_path: Path, prompt: str) -> dict[str, object]:
    from copilot_tools_gateway.providers.consumer.assisted_auth import (
        CONSUMER_URL,
        create_browser,
        load_pydoll_modules,
    )
    from copilot_tools_gateway.providers.consumer.browser_image_chat import (
        BrowserImageChatCapture,
        click_send_button,
        record_received_frame,
        verify_prompt_inserted,
        wait_for_image_response,
    )
    from copilot_tools_gateway.settings import GatewayPaths
    from tools.diagnostics.capture_consumer_websocket_shape import (
        record_websocket_created,
        record_websocket_frame,
    )

    records: list[dict[str, object]] = []
    tracked_request_ids: set[str] = set()
    capture = BrowserImageChatCapture()
    paths = GatewayPaths.from_cwd(ROOT)
    paths.consumer_profile_dir.mkdir(parents=True, exist_ok=True)
    modules = load_pydoll_modules(paths.root)
    from pydoll.protocol.network.events import NetworkEvent

    browser = create_browser(modules, paths.consumer_profile_dir)
    async with browser:
        tab = await browser.start()
        await tab.enable_network_events()
        await tab.on(
            NetworkEvent.WEBSOCKET_CREATED,
            lambda event: record_websocket_created(records, tracked_request_ids, event),
        )
        await tab.on(
            NetworkEvent.WEBSOCKET_FRAME_SENT,
            lambda event: record_websocket_frame(
                records, tracked_request_ids, "sent", event
            ),
        )
        await tab.on(
            NetworkEvent.WEBSOCKET_FRAME_RECEIVED,
            lambda event: (
                record_websocket_frame(records, tracked_request_ids, "received", event),
                record_received_frame(capture, event),
            ),
        )
        await tab.go_to(CONSUMER_URL, timeout=45)
        await asyncio.sleep(5)
        file_input = await tab.find(tag_name="input", timeout=10, type="file")
        await file_input.set_input_files(str(image_path))
        await asyncio.sleep(8)
        textbox = await tab.find(tag_name="textarea", timeout=20)
        await textbox.insert_text(prompt)
        await verify_prompt_inserted(tab, len(prompt))
        if not await click_send_button(tab):
            load_pydoll_modules(paths.root)
            from pydoll.constants import Key

            await tab.keyboard.press(Key.ENTER)
        await wait_for_image_response(capture)
    return {
        "ok": bool(capture.text.strip()),
        "text_length": len(capture.text),
        "text_hash": short_hash(capture.text),
        "marker_found": EXPECTED_MARKER in capture.text,
        "unreadable": response_looks_unreadable(capture.text),
        "websocket_shapes": websocket_shapes(records),
        "sent_frames": sent_frame_summaries(records),
        "sent_send_frames": sent_send_frame_summaries(records),
        "record_count": len(records),
    }


def run_direct_candidate_matrix(image_path: Path, prompt: str) -> Iterator[dict[str, object]]:
    from copilot_tools_gateway.providers.consumer.auth import ConsumerAuth
    from copilot_tools_gateway.providers.consumer.driver import ConsumerDriver
    from copilot_tools_gateway.providers.consumer.message_frames import ConsumerImageSendCandidate
    from copilot_tools_gateway.providers.consumer.vision_failures import (
        consumer_image_response_is_unreadable,
    )
    from copilot_tools_gateway.settings import GatewayPaths

    paths = GatewayPaths.from_cwd(ROOT)
    auth = ConsumerAuth.load(paths.consumer_auth_file)
    driver = ConsumerDriver()
    for candidate in ConsumerImageSendCandidate:
        started = time.time()
        try:
            text_parts: list[str] = []
            conversation_id_present = False
            for item in driver.create_completion(
                prompt=prompt,
                cookies=auth.cookies,
                access_token=auth.access_token,
                conversation_id=None,
                timeout_seconds=120,
                image_paths=[image_path],
                image_send_candidate=candidate,
            ):
                if isinstance(item, str):
                    text_parts.append(item)
                else:
                    conversation_id_present = True
            text = "".join(text_parts)
            unreadable = consumer_image_response_is_unreadable(text)
            marker_found = EXPECTED_MARKER in text
            yield {
                "candidate": candidate.value,
                "ok": True,
                "passed": marker_found and not unreadable,
                "marker_found": marker_found,
                "unreadable": unreadable,
                "text_length": len(text),
                "text_hash": short_hash(text),
                "conversation_id_present": conversation_id_present,
                "duration_seconds": round(time.time() - started, 3),
            }
        except Exception as exc:
            yield {
                "candidate": candidate.value,
                "ok": False,
                "passed": False,
                "safe_error": safe_error(exc),
                "duration_seconds": round(time.time() - started, 3),
            }


def sent_send_frame_summaries(records: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for record in records:
        if record.get("kind") != "sent":
            continue
        summary = record.get("summary")
        if isinstance(summary, Mapping) and summary.get("event") == "send":
            summaries.append({str(key): value for key, value in summary.items()})
    return summaries


def sent_frame_summaries(records: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for record in records:
        if record.get("kind") != "sent":
            continue
        summary = record.get("summary")
        if isinstance(summary, Mapping):
            summaries.append({str(key): value for key, value in summary.items()})
    return summaries


def websocket_shapes(records: list[dict[str, object]]) -> list[dict[str, object]]:
    shapes: list[dict[str, object]] = []
    for record in records:
        if record.get("kind") != "websocket":
            continue
        shape = record.get("url_shape")
        if isinstance(shape, Mapping):
            shapes.append({str(key): value for key, value in shape.items()})
    return shapes


def response_looks_unreadable(text: str) -> bool:
    from copilot_tools_gateway.providers.consumer.vision_failures import (
        consumer_image_response_is_unreadable,
    )

    return consumer_image_response_is_unreadable(text)


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def safe_error(exc: Exception) -> dict[str, object]:
    message = str(exc)
    return {
        "type": type(exc).__name__,
        "code": safe_error_code(message),
        "message_length": len(message),
        "message_hash": short_hash(message),
    }


def safe_error_code(message: str) -> str:
    normalized = message.lower()
    if "browser challenge" in normalized or "refresh consumer" in normalized:
        return "browser_challenge"
    if "timed out" in normalized or "timeout" in normalized:
        return "timeout"
    return "upstream_error"


def append_jsonl(path: Path, value: object) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
