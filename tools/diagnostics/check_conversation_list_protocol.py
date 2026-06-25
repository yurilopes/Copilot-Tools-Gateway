"""Run sanitized conversation list protocol checks."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = ROOT / "src"
DEFAULT_JSONL_PATH = ROOT / "captures" / "conversation-list-protocol.jsonl"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.diagnostics.conversation_list_protocol_safety import (  # noqa: E402
    m365_ui_recommended_action,
    query_keys,
    safe_failure,
    safe_items,
    safe_page_state,
    safe_request_json_shape,
    safe_shape,
    safe_sidebar_clicks,
    safe_sidebar_links,
    safe_string_attr,
    safe_url_path,
    scroll_sidebar_history,
    unique_records,
    url_is_relevant,
)


def main() -> None:
    args = parse_args()
    add_import_path(PROJECT_SRC)
    result = run_checks(
        include_m365_ui=args.m365_ui,
        m365_ui_wait_seconds=args.m365_ui_wait_seconds,
    )
    args.jsonl.parent.mkdir(parents=True, exist_ok=True)
    with args.jsonl.open("a", encoding="utf-8") as file:
        file.write(json.dumps(result, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate conversation listing protocols with sanitized output."
    )
    parser.add_argument("--jsonl", type=Path, default=DEFAULT_JSONL_PATH)
    parser.add_argument("--m365-ui", action="store_true")
    parser.add_argument("--m365-ui-wait-seconds", type=int, default=15)
    return parser.parse_args()


def add_import_path(path: Path) -> None:
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


def run_checks(
    *,
    include_m365_ui: bool,
    m365_ui_wait_seconds: int,
) -> dict[str, object]:
    checks: list[dict[str, object]] = [check_consumer_direct(), check_m365_direct()]
    if include_m365_ui:
        checks.append(check_m365_ui_shapes(wait_seconds=m365_ui_wait_seconds))
    return {
        "ok": any(check.get("ok") is True for check in checks),
        "checked_at": time.time(),
        "checks": checks,
    }


def check_consumer_direct() -> dict[str, object]:
    from copilot_tools_gateway.providers.consumer.auth import ConsumerAuth
    from copilot_tools_gateway.providers.consumer.history import list_consumer_conversations
    from copilot_tools_gateway.settings import GatewayPaths

    try:
        paths = GatewayPaths.from_cwd(ROOT)
        auth = ConsumerAuth.load(paths.consumer_auth_file)
        result = list_consumer_conversations(
            cookies=auth.cookies,
            access_token=auth.access_token,
            limit=20,
            cursor=None,
            timeout_seconds=30,
        )
        return {
            "provider": "copilot",
            "backend": "direct-api",
            "ok": True,
            "count": result.count,
            "has_more": result.has_more,
            "next_cursor_present": result.next_cursor is not None,
            "items": safe_items(result.conversations),
        }
    except Exception as exc:
        return safe_failure("copilot", "direct-api", exc)


def check_m365_direct() -> dict[str, object]:
    from copilot_tools_gateway.providers.m365.auth import M365Session
    from copilot_tools_gateway.providers.m365.history import list_m365_conversations
    from copilot_tools_gateway.providers.m365.web_auth import M365WebAuth
    from copilot_tools_gateway.settings import GatewayPaths

    try:
        paths = GatewayPaths.from_cwd(ROOT)
        session = M365Session.load(paths.m365_token_file)
        web_auth = M365WebAuth.load(paths.m365_web_auth_file)
        result = list_m365_conversations(
            session=session,
            web_auth=web_auth,
            limit=20,
            cursor=None,
            timeout_seconds=30,
        )
        return {
            "provider": "m365-copilot",
            "backend": "direct-api",
            "ok": True,
            "count": result.count,
            "has_more": result.has_more,
            "next_cursor_present": result.next_cursor is not None,
            "items": safe_items(result.conversations),
        }
    except Exception as exc:
        return safe_failure("m365-copilot", "direct-api", exc)


def check_m365_ui_shapes(*, wait_seconds: int) -> dict[str, object]:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    from copilot_tools_gateway.providers.m365.assisted_auth import M365_URL
    from copilot_tools_gateway.settings import GatewayPaths

    records: list[dict[str, object]] = []
    page_state: dict[str, object] | None = None
    sidebar_links: list[dict[str, object]] = []
    sidebar_clicks: list[dict[str, object]] = []
    paths = GatewayPaths.from_cwd(ROOT)

    def record_request(request: object) -> None:
        url = getattr(request, "url", "")
        if not isinstance(url, str) or not url_is_relevant(url):
            return
        parsed = urlsplit(url)
        records.append(
            request_record := {
                "event": "request",
                "host": parsed.netloc,
                "path": safe_url_path(parsed.path),
                "query_keys": query_keys(parsed.query),
                "method": safe_string_attr(request, "method"),
                "resource_type": safe_string_attr(request, "resource_type"),
            }
        )
        post_data_json = getattr(request, "post_data_json", None)
        if callable(post_data_json):
            with suppress(ValueError, json.JSONDecodeError):
                request_record["json_shape"] = safe_request_json_shape(post_data_json())

    def record_response(response: object) -> None:
        url = getattr(response, "url", "")
        if not isinstance(url, str) or not url_is_relevant(url):
            return
        parsed = urlsplit(url)
        item: dict[str, object] = {
            "event": "response",
            "host": parsed.netloc,
            "path": safe_url_path(parsed.path),
            "query_keys": query_keys(parsed.query),
            "status": getattr(response, "status", None),
            "content_type": "",
        }
        try:
            headers = getattr(response, "headers", {})
            if isinstance(headers, Mapping):
                content_type = headers.get("content-type")
                item["content_type"] = content_type if isinstance(content_type, str) else ""
            if "json" in str(item["content_type"]).lower():
                item["shape"] = safe_shape(response.json())
        except (PlaywrightError, ValueError, json.JSONDecodeError):
            pass
        records.append(item)

    def record_websocket(websocket: object) -> None:
        url = getattr(websocket, "url", "")
        if not isinstance(url, str) or not url_is_relevant(url):
            return
        parsed = urlsplit(url)
        records.append(
            {
                "event": "websocket",
                "host": parsed.netloc,
                "path": safe_url_path(parsed.path),
                "query_keys": query_keys(parsed.query),
            }
        )

    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(paths.m365_profile_dir),
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
                timeout=60_000,
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.on("request", record_request)
                page.on("response", record_response)
                page.on("websocket", record_websocket)
                page.goto(M365_URL, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(max(wait_seconds, 1) * 1_000)
                scroll_sidebar_history(page)
                page.wait_for_timeout(5_000)
                page_state = safe_page_state(
                    url=page.url,
                    title=page.title(),
                    body_text=page.locator("body").inner_text(timeout=10_000),
                )
                sidebar_links = safe_sidebar_links(page)
                sidebar_clicks = safe_sidebar_clicks(page)
            finally:
                context.close()
        return {
            "provider": "m365-copilot",
            "backend": "ui-shape-capture",
            "ok": bool(records),
            "page_state": page_state,
            "recommended_action": m365_ui_recommended_action(page_state, records),
            "record_count": len(records),
            "records": unique_records(records),
            "sidebar_link_count": len(sidebar_links),
            "sidebar_links": sidebar_links,
            "sidebar_click_count": len(sidebar_clicks),
            "sidebar_clicks": sidebar_clicks,
        }
    except Exception as exc:
        return safe_failure("m365-copilot", "ui-shape-capture", exc)


if __name__ == "__main__":
    main()
