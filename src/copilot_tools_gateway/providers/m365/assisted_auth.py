"""Browser-assisted Microsoft 365 Copilot session capture."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import BrowserContext, Page, Playwright
from playwright.sync_api import Error as PlaywrightError

from copilot_tools_gateway.domain.errors import LoginFailedError
from copilot_tools_gateway.domain.json_types import object_value, string_value
from copilot_tools_gateway.providers.m365.auth import M365Session
from copilot_tools_gateway.providers.m365.tokens import (
    M365CapturedTokenKind,
    classify_m365_access_token,
)
from copilot_tools_gateway.settings import GatewayPaths

M365_URL = "https://m365.cloud.microsoft/chat/"
M365_CAPTURE_WAIT_MS = 8_000
M365_RELOAD_WAIT_MS = 5_000
M365_BROWSER_TIMEOUT_MS = 60_000
M365_LOGIN_STEPS = (
    "Sign in to Microsoft 365 Copilot if needed.",
    "Wait until the Copilot chat page is visible.",
    "Send one normal message if the chat token has not appeared.",
    "Attach a small document if Graph or search tokens are needed.",
)
M365_REFRESH_STEPS = (
    "Wait for the page to finish loading.",
    "Send one normal message if the chat token has not appeared.",
    "Attach a small document if Graph or search tokens are still missing.",
    "Return to this terminal and press Enter.",
)


@dataclass
class M365TokenCapture:
    sessions: list[M365Session] = field(default_factory=list)
    graph_tokens: list[str] = field(default_factory=list)
    search_tokens: list[str] = field(default_factory=list)
    _session_keys: set[tuple[str, str, int]] = field(default_factory=set)
    _graph_seen: set[str] = field(default_factory=set)
    _search_seen: set[str] = field(default_factory=set)

    @property
    def has_chat_token(self) -> bool:
        return bool(self.sessions)

    @property
    def has_graph_token(self) -> bool:
        return bool(self.graph_tokens)

    @property
    def has_search_token(self) -> bool:
        return bool(self.search_tokens)

    @property
    def has_document_tokens(self) -> bool:
        return self.has_graph_token and self.has_search_token

    def append_token(self, token: str) -> None:
        captured = classify_m365_access_token(token)
        if captured is None:
            return
        if captured.kind == M365CapturedTokenKind.CHATHUB and captured.session is not None:
            key = (
                captured.session.oid,
                captured.session.tid,
                captured.session.expires_at,
            )
            if key not in self._session_keys:
                self._session_keys.add(key)
                self.sessions.append(captured.session)
            return
        if captured.kind == M365CapturedTokenKind.GRAPH and captured.token not in self._graph_seen:
            self._graph_seen.add(captured.token)
            self.graph_tokens.append(captured.token)
            return
        if (
            captured.kind == M365CapturedTokenKind.SEARCH
            and captured.token not in self._search_seen
        ):
            self._search_seen.add(captured.token)
            self.search_tokens.append(captured.token)

    def best_session(self) -> M365Session:
        if not self.sessions:
            raise LoginFailedError("M365 login did not capture a valid Copilot chat token")
        return max(self.sessions, key=lambda item: item.expires_at)


@dataclass(frozen=True)
class M365CaptureHandlers:
    inspect_response: Callable[[object], None]
    inspect_request: Callable[[object], None]
    inspect_websocket: Callable[[object], None]

    def detach_from(self, page: Page) -> None:
        for event_name, handler in (
            ("response", self.inspect_response),
            ("request", self.inspect_request),
            ("websocket", self.inspect_websocket),
        ):
            try:
                page.remove_listener(event_name, handler)
            except PlaywrightError:
                continue


def login_m365(paths: GatewayPaths) -> Path:
    return capture_m365_session(
        paths,
        title="Microsoft 365 Copilot login",
        steps=M365_LOGIN_STEPS,
        prompt=(
            "Press Enter after Microsoft 365 Copilot is signed in and any needed "
            "document action is complete: "
        ),
    )


def refresh_m365(paths: GatewayPaths) -> Path:
    return capture_m365_session(
        paths,
        title="Microsoft 365 Copilot refresh",
        steps=M365_REFRESH_STEPS,
        prompt=(
            "Press Enter after the page is loaded and any requested browser action "
            "is complete. The gateway will save refreshed tokens: "
        ),
    )


def capture_m365_session(
    paths: GatewayPaths,
    title: str,
    steps: tuple[str, ...],
    prompt: str,
) -> Path:
    from playwright.sync_api import sync_playwright

    capture = M365TokenCapture()
    paths.m365_profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = _launch_m365_context(playwright, paths.m365_profile_dir)
        page: Page | None = None
        handlers: M365CaptureHandlers | None = None
        try:
            page = context.pages[0] if context.pages else context.new_page()
            handlers = _attach_capture_handlers(page, capture)
            page.goto(M365_URL, wait_until="domcontentloaded", timeout=M365_BROWSER_TIMEOUT_MS)
            _wait_for_capture(page, capture, M365_CAPTURE_WAIT_MS)
            if not capture.has_chat_token or not capture.has_document_tokens:
                page.reload(wait_until="domcontentloaded", timeout=M365_BROWSER_TIMEOUT_MS)
                _wait_for_capture(page, capture, M365_RELOAD_WAIT_MS)
            if not capture.has_chat_token or not capture.has_document_tokens:
                input(_format_browser_steps(title, steps, prompt, capture))
                _wait_for_capture(page, capture, M365_CAPTURE_WAIT_MS)
            if not capture.has_chat_token or not capture.has_document_tokens:
                page.reload(wait_until="domcontentloaded", timeout=M365_BROWSER_TIMEOUT_MS)
                _wait_for_capture(page, capture, M365_RELOAD_WAIT_MS)

            session = capture.best_session()
            session.save(paths.m365_token_file)
            if capture.graph_tokens:
                paths.m365_graph_token_file.write_text(
                    capture.graph_tokens[-1],
                    encoding="utf-8",
                )
            if capture.search_tokens:
                paths.m365_search_token_file.write_text(
                    capture.search_tokens[-1],
                    encoding="utf-8",
                )
            return paths.m365_token_file
        finally:
            if page is not None and handlers is not None:
                handlers.detach_from(page)
            _safe_close_context(context)


def _launch_m365_context(playwright: Playwright, profile_dir: Path) -> BrowserContext:
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
        timeout=M365_BROWSER_TIMEOUT_MS,
    )


def _attach_capture_handlers(page: Page, capture: M365TokenCapture) -> M365CaptureHandlers:
    def inspect_response(response: object) -> None:
        url = getattr(response, "url", "")
        if not isinstance(url, str):
            return
        if "/oauth2/v2.0/token" in url:
            _append_tokens_from_oauth_response(response, capture)
        if "/m365Copilot/Chathub/" in url:
            _append_chathub_session_from_websocket_url(url, capture)

    def inspect_websocket(websocket: object) -> None:
        url = getattr(websocket, "url", "")
        if isinstance(url, str) and "/m365Copilot/Chathub/" in url:
            _append_chathub_session_from_websocket_url(url, capture)

    def inspect_request(request: object) -> None:
        url = getattr(request, "url", "")
        if not isinstance(url, str):
            return
        if "graph.microsoft.com" in url:
            _append_bearer_token_from_request(request, capture, M365CapturedTokenKind.GRAPH)
        if "substrate.office.com/searchservice" in url:
            _append_bearer_token_from_request(request, capture, M365CapturedTokenKind.SEARCH)

    page.on("response", inspect_response)
    page.on("request", inspect_request)
    page.on("websocket", inspect_websocket)
    return M365CaptureHandlers(
        inspect_response=inspect_response,
        inspect_request=inspect_request,
        inspect_websocket=inspect_websocket,
    )


def _wait_for_capture(page: Page, capture: M365TokenCapture, timeout_ms: int) -> None:
    deadline = time.monotonic() + timeout_ms / 1_000
    while time.monotonic() < deadline:
        if capture.has_chat_token and capture.has_document_tokens:
            return
        page.wait_for_timeout(500)


def _format_browser_steps(
    title: str,
    steps: tuple[str, ...],
    prompt: str,
    capture: M365TokenCapture,
) -> str:
    lines = [title, "", "Use the opened browser window:", ""]
    lines.extend(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    lines.extend(
        [
            "",
            "Current safe capture state:",
            f"- Copilot chat token captured: {_yes_no(capture.has_chat_token)}",
            f"- Graph token captured: {_yes_no(capture.has_graph_token)}",
            f"- Search token captured: {_yes_no(capture.has_search_token)}",
            "",
            prompt,
        ]
    )
    return "\n".join(lines)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _append_tokens_from_oauth_response(response: object, capture: M365TokenCapture) -> None:
    try:
        text_method = getattr(response, "text", None)
        if not callable(text_method):
            return
        body_text = text_method()
        if not isinstance(body_text, str):
            return
        payload = object_value(json.loads(body_text), "token response")
        capture.append_token(string_value(payload.get("access_token"), "access_token"))
    except (json.JSONDecodeError, PlaywrightError, ValueError):
        return


def _append_chathub_session_from_websocket_url(url: str, capture: M365TokenCapture) -> None:
    values = parse_qs(urlsplit(url).query)
    tokens = values.get("access_token")
    if tokens:
        capture.append_token(tokens[0])


def _append_bearer_token_from_request(
    request: object,
    capture: M365TokenCapture,
    expected_kind: M365CapturedTokenKind,
) -> None:
    header_method = getattr(request, "header_value", None)
    if not callable(header_method):
        return
    try:
        header_value = header_method("authorization")
    except PlaywrightError:
        return
    if not isinstance(header_value, str):
        return
    prefix = "Bearer "
    if not header_value.startswith(prefix):
        return
    token = header_value.removeprefix(prefix)
    captured = classify_m365_access_token(token)
    if captured is not None and captured.kind == expected_kind:
        capture.append_token(token)


def _safe_close_context(context: BrowserContext) -> None:
    try:
        context.close()
    except PlaywrightError:
        return
