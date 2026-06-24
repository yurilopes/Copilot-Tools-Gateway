"""Interactive login flows for supported Copilot providers."""

import json
import time
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import BrowserContext, Page, Playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from copilot_tools_gateway.domain.errors import LoginFailedError
from copilot_tools_gateway.domain.json_types import object_value, string_value
from copilot_tools_gateway.providers.consumer.auth import ConsumerAuth
from copilot_tools_gateway.providers.m365.auth import M365Session
from copilot_tools_gateway.providers.m365.tokens import (
    M365CapturedTokenKind,
    classify_m365_access_token,
)
from copilot_tools_gateway.settings import GatewayPaths

CONSUMER_URL = "https://copilot.microsoft.com/"
M365_URL = "https://m365.cloud.microsoft/chat/"
CONSUMER_TOKEN_ATTEMPTS = 5
CONSUMER_ORIGIN_ATTEMPTS = 6
CONSUMER_TOKEN_RETRY_DELAY_MS = 1_000
BROWSER_LAUNCH_TIMEOUT_MS = 60_000
CONSUMER_LOGIN_STEPS = (
    "Sign in to consumer Copilot if needed.",
    "If Copilot asks you to choose an account, choose the personal account.",
    "Wait until the Copilot chat page is visible.",
)
CONSUMER_REFRESH_STEPS = (
    "Complete any browser challenge if it appears.",
    "Send one normal message to Copilot in the opened browser.",
    "Wait until Copilot answers that browser message.",
    "Return to this terminal and press Enter.",
)

CONSUMER_TOKEN_SCRIPT = """
() => {
  try {
    let fallback = null;
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      const value = localStorage.getItem(key);
      if (value && value.indexOf('"credentialType":"AccessToken"') !== -1) {
        try {
          const parsed = JSON.parse(value);
          if (parsed && parsed.secret) {
            if (parsed.target && parsed.target.indexOf('ChatAI') !== -1) return parsed.secret;
            if (!fallback) fallback = parsed.secret;
          }
        } catch (error) {}
      }
    }
    return fallback;
  } catch (error) {}
  return null;
}
"""


def login_consumer(paths: GatewayPaths) -> Path:
    return _capture_consumer_session(
        paths,
        title="Consumer Copilot login",
        steps=CONSUMER_LOGIN_STEPS,
        prompt="Press Enter after the Copilot chat page is visible: ",
        require_prompt=True,
    )


def refresh_consumer(paths: GatewayPaths) -> Path:
    return _capture_consumer_session(
        paths,
        title="Consumer Copilot refresh warm-up",
        steps=CONSUMER_REFRESH_STEPS,
        prompt=(
            "Press Enter after Copilot answers the browser message. "
            "The gateway will then save the refreshed local session: "
        ),
        require_prompt=True,
    )


def _capture_consumer_session(
    paths: GatewayPaths,
    title: str,
    steps: tuple[str, ...],
    prompt: str,
    require_prompt: bool,
) -> Path:
    from playwright.sync_api import sync_playwright

    paths.consumer_profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = _launch_consumer_context(playwright, paths.consumer_profile_dir)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(CONSUMER_URL, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(3_000)
            if require_prompt:
                input(_format_browser_steps(title, steps, prompt))
            auth = _capture_consumer_auth(context, page)
            if auth is None and not require_prompt:
                input(prompt)
                auth = _capture_consumer_auth(context, page)
            if auth is None:
                raise LoginFailedError("Consumer login did not capture cookies or a Copilot token")
            auth.save(paths.consumer_auth_file)
            return paths.consumer_auth_file
        finally:
            context.close()


def _format_browser_steps(title: str, steps: tuple[str, ...], prompt: str) -> str:
    lines = [title, "", "Use the opened browser window:", ""]
    lines.extend(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    lines.extend(["", prompt])
    return "\n".join(lines)


def _launch_consumer_context(playwright: Playwright, profile_dir: Path) -> BrowserContext:
    launch_args = ["--disable-blink-features=AutomationControlled"]
    try:
        return playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            channel="chrome",
            args=launch_args,
            timeout=BROWSER_LAUNCH_TIMEOUT_MS,
        )
    except PlaywrightError:
        return playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            args=launch_args,
            timeout=BROWSER_LAUNCH_TIMEOUT_MS,
        )


def _capture_consumer_auth(context: object, page: Page) -> ConsumerAuth | None:
    _open_consumer_origin(page)
    token_value = _evaluate_consumer_token(page)
    cookies: dict[str, str] = {}
    cookies_method = getattr(context, "cookies", None)
    if not callable(cookies_method):
        raise LoginFailedError("Consumer browser context cannot read cookies")
    for cookie in cookies_method():
        if _cookie_is_microsoft(cookie):
            name = cookie.get("name")
            value = cookie.get("value")
            if isinstance(name, str) and isinstance(value, str):
                cookies[name] = value
    token = token_value if isinstance(token_value, str) else None
    if not cookies and token is None:
        return None
    return ConsumerAuth(cookies=cookies, access_token=token, saved_at=time.time())


def _open_consumer_origin(page: Page) -> None:
    last_error: PlaywrightError | None = None
    for _ in range(CONSUMER_ORIGIN_ATTEMPTS):
        with suppress(PlaywrightTimeoutError):
            page.wait_for_load_state("domcontentloaded", timeout=5_000)
        if _is_consumer_origin(page.url):
            return
        try:
            page.goto(CONSUMER_URL, wait_until="domcontentloaded", timeout=15_000)
            if _is_consumer_origin(page.url):
                return
        except PlaywrightError as exc:
            last_error = exc
            page.wait_for_timeout(CONSUMER_TOKEN_RETRY_DELAY_MS)
    message = (
        "Consumer login did not land on copilot.microsoft.com. "
        "If this account redirects to Microsoft 365 Copilot, run login m365."
    )
    if last_error is not None:
        raise LoginFailedError(message) from last_error
    raise LoginFailedError(message)


def _is_consumer_origin(url: str) -> bool:
    return url.startswith(CONSUMER_URL)


def _evaluate_consumer_token(page: Page) -> object:
    last_error: PlaywrightError | None = None
    for _ in range(CONSUMER_TOKEN_ATTEMPTS):
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5_000)
            return page.evaluate(CONSUMER_TOKEN_SCRIPT)
        except PlaywrightTimeoutError:
            return page.evaluate(CONSUMER_TOKEN_SCRIPT)
        except PlaywrightError as exc:
            last_error = exc
            page.wait_for_timeout(CONSUMER_TOKEN_RETRY_DELAY_MS)
    if last_error is not None:
        raise LoginFailedError(
            "Consumer login page did not stabilize after sign-in"
        ) from last_error
    raise LoginFailedError("Consumer login could not evaluate the signed-in page")


def login_m365(paths: GatewayPaths) -> Path:
    return _capture_m365_session(
        paths,
        prompt=(
            "Sign in to Microsoft 365 Copilot, open chat, send a message "
            "or attach a file if Graph tools are needed, then press Enter here: "
        ),
    )


def refresh_m365(paths: GatewayPaths) -> Path:
    return _capture_m365_session(
        paths,
        prompt=(
            "Use the opened Microsoft 365 Copilot page if action is needed. "
            "Send a message or attach a file if Graph tools are needed, then press Enter here: "
        ),
    )


def _capture_m365_session(paths: GatewayPaths, prompt: str) -> Path:
    from playwright.sync_api import sync_playwright

    candidates: list[M365Session] = []
    graph_tokens: list[str] = []
    search_tokens: list[str] = []
    paths.m365_profile_dir.mkdir(parents=True, exist_ok=True)

    def inspect_response(response: object) -> None:
        url = getattr(response, "url", "")
        if not isinstance(url, str):
            return
        if "/oauth2/v2.0/token" in url:
            _append_tokens_from_oauth_response(response, candidates, graph_tokens, search_tokens)
        if "/m365Copilot/Chathub/" in url:
            _append_chathub_session_from_websocket_url(url, candidates)

    def inspect_websocket(websocket: object) -> None:
        url = getattr(websocket, "url", "")
        if isinstance(url, str) and "/m365Copilot/Chathub/" in url:
            _append_chathub_session_from_websocket_url(url, candidates)

    def inspect_request(request: object) -> None:
        url = getattr(request, "url", "")
        if not isinstance(url, str):
            return
        if "graph.microsoft.com" in url:
            _append_bearer_token_from_request(request, graph_tokens, M365CapturedTokenKind.GRAPH)
        if "substrate.office.com/searchservice" in url:
            _append_bearer_token_from_request(request, search_tokens, M365CapturedTokenKind.SEARCH)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(paths.m365_profile_dir),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.on("response", inspect_response)
            page.on("request", inspect_request)
            page.on("websocket", inspect_websocket)
            page.goto(M365_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(5_000)
            if not candidates or not graph_tokens or not search_tokens:
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(5_000)
            if not candidates or not graph_tokens or not search_tokens:
                input(prompt)
            if not candidates or not graph_tokens or not search_tokens:
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(5_000)
            if not candidates:
                raise LoginFailedError("M365 login did not capture a valid Copilot chat token")
            session = max(candidates, key=lambda item: item.expires_at)
            session.save(paths.m365_token_file)
            if graph_tokens:
                paths.m365_graph_token_file.write_text(graph_tokens[-1], encoding="utf-8")
            if search_tokens:
                paths.m365_search_token_file.write_text(search_tokens[-1], encoding="utf-8")
            return paths.m365_token_file
        finally:
            context.close()


def _cookie_is_microsoft(cookie: object) -> bool:
    if not isinstance(cookie, Mapping):
        return False
    domain = cookie.get("domain")
    return isinstance(domain, str) and "microsoft.com" in domain


def _append_tokens_from_oauth_response(
    response: object,
    candidates: list[M365Session],
    graph_tokens: list[str],
    search_tokens: list[str],
) -> None:
    try:
        text_method = getattr(response, "text", None)
        if not callable(text_method):
            return
        body_text = text_method()
        if not isinstance(body_text, str):
            return
        payload = object_value(json.loads(body_text), "token response")
        _append_classified_token(
            string_value(payload.get("access_token"), "access_token"),
            candidates,
            graph_tokens,
            search_tokens,
        )
    except Exception:
        return


def _append_chathub_session_from_websocket_url(url: str, candidates: list[M365Session]) -> None:
    values = parse_qs(urlsplit(url).query)
    tokens = values.get("access_token")
    if not tokens:
        return
    captured = classify_m365_access_token(tokens[0])
    if captured is None or captured.session is None:
        return
    candidates.append(captured.session)


def _append_bearer_token_from_request(
    request: object,
    tokens: list[str],
    expected_kind: M365CapturedTokenKind,
) -> None:
    header_method = getattr(request, "header_value", None)
    if not callable(header_method):
        return
    header_value = header_method("authorization")
    if not isinstance(header_value, str):
        return
    prefix = "Bearer "
    if not header_value.startswith(prefix):
        return
    token = header_value.removeprefix(prefix)
    captured = classify_m365_access_token(token)
    if captured is not None and captured.kind == expected_kind:
        tokens.append(token)


def _append_classified_token(
    token: str,
    candidates: list[M365Session],
    graph_tokens: list[str],
    search_tokens: list[str],
) -> None:
    captured = classify_m365_access_token(token)
    if captured is None:
        return
    if captured.kind == M365CapturedTokenKind.CHATHUB and captured.session is not None:
        candidates.append(captured.session)
        return
    if captured.kind == M365CapturedTokenKind.GRAPH:
        graph_tokens.append(captured.token)
        return
    if captured.kind == M365CapturedTokenKind.SEARCH:
        search_tokens.append(captured.token)
