"""Interactive login flows for supported Copilot providers."""

import json
import time
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from copilot_tools_gateway.domain.errors import LoginFailedError
from copilot_tools_gateway.domain.json_types import object_value
from copilot_tools_gateway.providers.consumer.auth import ConsumerAuth
from copilot_tools_gateway.providers.m365.auth import M365Session
from copilot_tools_gateway.settings import GatewayPaths

CONSUMER_URL = "https://copilot.microsoft.com/"
M365_URL = "https://m365.cloud.microsoft/chat/"
CONSUMER_TOKEN_ATTEMPTS = 5
CONSUMER_ORIGIN_ATTEMPTS = 6
CONSUMER_TOKEN_RETRY_DELAY_MS = 1_000

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
    from playwright.sync_api import sync_playwright

    paths.consumer_profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(paths.consumer_profile_dir),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(CONSUMER_URL, wait_until="domcontentloaded")
            input("Sign in to consumer Copilot if needed, then press Enter here: ")
            _open_consumer_origin(page)
            token_value = _evaluate_consumer_token(page)
            cookies: dict[str, str] = {}
            for cookie in context.cookies():
                if _cookie_is_microsoft(cookie):
                    name = cookie.get("name")
                    value = cookie.get("value")
                    if isinstance(name, str) and isinstance(value, str):
                        cookies[name] = value
            token = token_value if isinstance(token_value, str) else None
            if not cookies and token is None:
                raise LoginFailedError("Consumer login did not capture cookies or a Copilot token")
            auth = ConsumerAuth(cookies=cookies, access_token=token, saved_at=time.time())
            auth.save(paths.consumer_auth_file)
            return paths.consumer_auth_file
        finally:
            context.close()


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
    from playwright.sync_api import sync_playwright

    candidates: list[M365Session] = []
    token_request_urls: set[str] = set()
    profile_dir = paths.session_dir / "m365" / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    def inspect_response(response: object) -> None:
        url = getattr(response, "url", "")
        if not isinstance(url, str):
            return
        if "/oauth2/v2.0/token" in url:
            token_request_urls.add(url)
            _append_session_from_response(response, candidates)
        if "/m365Copilot/Chathub/" in url:
            _append_session_from_websocket_url(url, candidates)

    def inspect_websocket(websocket: object) -> None:
        url = getattr(websocket, "url", "")
        if isinstance(url, str) and "/m365Copilot/Chathub/" in url:
            _append_session_from_websocket_url(url, candidates)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.on("response", inspect_response)
            page.on("websocket", inspect_websocket)
            page.goto(M365_URL, wait_until="domcontentloaded")
            input("Sign in to Microsoft 365 Copilot, open chat, then press Enter here: ")
            if not candidates:
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(5_000)
            if not candidates:
                raise LoginFailedError("M365 login did not capture a valid Copilot chat token")
            session = max(candidates, key=lambda item: item.expires_at)
            session.save(paths.m365_token_file)
            return paths.m365_token_file
        finally:
            context.close()


def _cookie_is_microsoft(cookie: object) -> bool:
    if not isinstance(cookie, Mapping):
        return False
    domain = cookie.get("domain")
    return isinstance(domain, str) and "microsoft.com" in domain


def _append_session_from_response(response: object, candidates: list[M365Session]) -> None:
    try:
        text_method = getattr(response, "text", None)
        if not callable(text_method):
            return
        body_text = text_method()
        if not isinstance(body_text, str):
            return
        payload = object_value(json.loads(body_text), "token response")
        candidates.append(M365Session.from_token_response(payload))
    except Exception:
        return


def _append_session_from_websocket_url(url: str, candidates: list[M365Session]) -> None:
    values = parse_qs(urlsplit(url).query)
    tokens = values.get("access_token")
    if not tokens:
        return
    token = tokens[0]
    try:
        candidates.append(M365Session.from_access_token(token))
    except ValueError:
        return
