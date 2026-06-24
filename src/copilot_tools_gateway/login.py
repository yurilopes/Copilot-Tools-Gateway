"""Interactive login flows for supported Copilot providers."""

import time
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from copilot_tools_gateway.domain.errors import LoginFailedError
from copilot_tools_gateway.providers.consumer.auth import ConsumerAuth
from copilot_tools_gateway.providers.m365.assisted_auth import login_m365 as _login_m365
from copilot_tools_gateway.providers.m365.assisted_auth import refresh_m365 as _refresh_m365
from copilot_tools_gateway.settings import GatewayPaths

CONSUMER_URL = "https://copilot.microsoft.com/"
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
    return _login_m365(paths)


def refresh_m365(paths: GatewayPaths) -> Path:
    return _refresh_m365(paths)


def _cookie_is_microsoft(cookie: object) -> bool:
    if not isinstance(cookie, Mapping):
        return False
    domain = cookie.get("domain")
    return isinstance(domain, str) and "microsoft.com" in domain
