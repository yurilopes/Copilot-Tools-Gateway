"""Pydoll-assisted consumer Copilot session capture."""

from __future__ import annotations

import asyncio
import importlib
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Protocol, Self, TypeGuard, runtime_checkable

from copilot_tools_gateway.domain.errors import LoginFailedError
from copilot_tools_gateway.providers.consumer.auth import ConsumerAuth
from copilot_tools_gateway.settings import GatewayPaths

CONSUMER_URL = "https://copilot.microsoft.com/"
CONSUMER_CAPTURE_WAIT_SECONDS = 5
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
(() => {
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
})()
"""


@dataclass(frozen=True)
class PydollModules:
    chrome_factory: BrowserFactory
    options_factory: OptionsFactory


@runtime_checkable
class BrowserFactory(Protocol):
    def __call__(self, *, options: object) -> object:
        ...


@runtime_checkable
class OptionsFactory(Protocol):
    def __call__(self) -> object:
        ...


class PydollOptions(Protocol):
    start_timeout: int

    def add_argument(self, argument: str) -> object:
        ...


class PydollTab(Protocol):
    async def go_to(self, url: str, timeout: int) -> object:
        ...

    async def execute_script(self, script: str, *, return_by_value: bool) -> object:
        ...

    async def get_cookies(self) -> object:
        ...


class PydollBrowser(Protocol):
    async def __aenter__(self) -> Self:
        ...

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> object:
        ...

    async def start(self) -> PydollTab:
        ...


def login_consumer(paths: GatewayPaths) -> Path:
    return capture_consumer_session(
        paths,
        title="Consumer Copilot login",
        steps=CONSUMER_LOGIN_STEPS,
        prompt="Press Enter after the Copilot chat page is visible: ",
    )


def refresh_consumer(paths: GatewayPaths) -> Path:
    return capture_consumer_session(
        paths,
        title="Consumer Copilot refresh warm-up",
        steps=CONSUMER_REFRESH_STEPS,
        prompt=(
            "Press Enter after Copilot answers the browser message. "
            "The gateway will then save the refreshed local session: "
        ),
    )


def capture_consumer_session(
    paths: GatewayPaths,
    title: str,
    steps: tuple[str, ...],
    prompt: str,
) -> Path:
    return asyncio.run(_capture_consumer_session(paths, title, steps, prompt))


async def _capture_consumer_session(
    paths: GatewayPaths,
    title: str,
    steps: tuple[str, ...],
    prompt: str,
) -> Path:
    modules = load_pydoll_modules(paths.root)
    paths.consumer_profile_dir.mkdir(parents=True, exist_ok=True)
    browser = create_browser(modules, paths.consumer_profile_dir)
    async with browser:
        tab = await browser.start()
        await tab.go_to(CONSUMER_URL, timeout=45)
        await asyncio.sleep(CONSUMER_CAPTURE_WAIT_SECONDS)
        input(format_browser_steps(title, steps, prompt))
        await asyncio.sleep(CONSUMER_CAPTURE_WAIT_SECONDS)
        auth = await capture_consumer_auth(tab)
        if auth is None:
            raise LoginFailedError("Consumer login did not capture cookies or a Copilot token")
        auth.save(paths.consumer_auth_file)
        return paths.consumer_auth_file


def load_pydoll_modules(root: Path) -> PydollModules:
    try:
        chrome_module = importlib.import_module("pydoll.browser.chromium")
        options_module = importlib.import_module("pydoll.browser.options")
    except ModuleNotFoundError as exc:
        local_pydoll = root.parent / "pydoll"
        if not local_pydoll.exists():
            raise LoginFailedError(
                "Pydoll is required for consumer login. Install project dependencies first."
            ) from exc
        sys.path.insert(0, str(local_pydoll))
        chrome_module = importlib.import_module("pydoll.browser.chromium")
        options_module = importlib.import_module("pydoll.browser.options")
    return PydollModules(
        chrome_factory=browser_factory(chrome_module, "Chrome"),
        options_factory=options_factory(options_module, "ChromiumOptions"),
    )


def browser_factory(module: ModuleType, name: str) -> BrowserFactory:
    value = getattr(module, name, None)
    if not isinstance(value, BrowserFactory):
        raise LoginFailedError(f"Pydoll did not expose {name}")
    return value


def options_factory(module: ModuleType, name: str) -> OptionsFactory:
    value = getattr(module, name, None)
    if not isinstance(value, OptionsFactory):
        raise LoginFailedError(f"Pydoll did not expose {name}")
    return value


def create_browser(modules: PydollModules, profile_dir: Path) -> PydollBrowser:
    options = create_options(modules.options_factory, profile_dir)
    browser = modules.chrome_factory(options=options)
    if not is_pydoll_browser(browser):
        raise LoginFailedError("Pydoll Chrome entry point returned an invalid browser")
    return browser


def create_options(options_factory: OptionsFactory, profile_dir: Path) -> PydollOptions:
    options = options_factory()
    if not is_pydoll_options(options):
        raise LoginFailedError("Pydoll ChromiumOptions cannot add browser arguments")
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    set_start_timeout(options, 30)
    return options


def set_start_timeout(options: PydollOptions, seconds: int) -> None:
    try:
        options.start_timeout = seconds
    except AttributeError as exc:
        raise LoginFailedError("Pydoll ChromiumOptions cannot set start timeout") from exc


def is_pydoll_options(value: object) -> TypeGuard[PydollOptions]:
    return callable(getattr(value, "add_argument", None))


def is_pydoll_browser(value: object) -> TypeGuard[PydollBrowser]:
    return all(
        callable(getattr(value, method_name, None))
        for method_name in ("__aenter__", "__aexit__", "start")
    )


async def capture_consumer_auth(tab: PydollTab) -> ConsumerAuth | None:
    token_value = await evaluate_consumer_token(tab)
    cookies = await consumer_cookies(tab)
    token = token_value if isinstance(token_value, str) else None
    if not cookies and token is None:
        return None
    return ConsumerAuth(cookies=cookies, access_token=token, saved_at=time.time())


async def evaluate_consumer_token(tab: PydollTab) -> object:
    execute_script = getattr(tab, "execute_script", None)
    if not callable(execute_script):
        raise LoginFailedError("Pydoll tab cannot evaluate consumer token")
    response = await execute_script(CONSUMER_TOKEN_SCRIPT, return_by_value=True)
    return runtime_value(response)


async def consumer_cookies(tab: PydollTab) -> dict[str, str]:
    get_cookies = getattr(tab, "get_cookies", None)
    if not callable(get_cookies):
        raise LoginFailedError("Pydoll tab cannot read cookies")
    raw_cookies = await get_cookies()
    if not isinstance(raw_cookies, list):
        raise LoginFailedError("Pydoll returned invalid cookie data")
    cookies: dict[str, str] = {}
    for cookie in raw_cookies:
        if not cookie_is_microsoft(cookie):
            continue
        name = cookie.get("name")
        value = cookie.get("value")
        if isinstance(name, str) and isinstance(value, str):
            cookies[name] = value
    return cookies


def runtime_value(response: object) -> object:
    if not isinstance(response, Mapping):
        return None
    outer = response.get("result")
    if not isinstance(outer, Mapping):
        return None
    inner = outer.get("result")
    if not isinstance(inner, Mapping):
        return None
    return inner.get("value")


def cookie_is_microsoft(cookie: object) -> bool:
    if not isinstance(cookie, Mapping):
        return False
    domain = cookie.get("domain")
    return isinstance(domain, str) and "microsoft.com" in domain


def format_browser_steps(title: str, steps: tuple[str, ...], prompt: str) -> str:
    lines = [title, "", "Use the opened Pydoll browser window:", ""]
    lines.extend(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    lines.extend(["", prompt])
    return "\n".join(lines)
