"""Pydoll-assisted consumer Copilot image chat."""

from __future__ import annotations

import asyncio
import importlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Protocol, Self, TypeGuard

from copilot_tools_gateway.async_runtime import run_async
from copilot_tools_gateway.domain.errors import LoginFailedError, UpstreamProtocolError
from copilot_tools_gateway.providers.consumer.assisted_auth import (
    CONSUMER_URL,
    capture_consumer_auth,
    create_browser,
    load_pydoll_modules,
    runtime_value,
)
from copilot_tools_gateway.settings import GatewayPaths

IMAGE_CHAT_IDLE_SECONDS = 5
IMAGE_CHAT_WAIT_SECONDS = 120
COMPOSER_STATE_SCRIPT = """
(() => {
  const textareas = Array.from(document.querySelectorAll('textarea'));
  const buttons = Array.from(document.querySelectorAll('button'));
  return {
    textareaCount: textareas.length,
    maxValueLength: Math.max(0, ...textareas.map((item) => item.value.length)),
    sendButtonCount: buttons.filter((button) => {
      const value = [
        button.getAttribute('aria-label') || '',
        button.getAttribute('title') || '',
        button.getAttribute('data-testid') || ''
      ].join(' ').toLowerCase();
      return !button.disabled && (
        value.includes('send') ||
        value.includes('enviar') ||
        value.includes('submit')
      );
    }).length
  };
})()
"""
CLICK_SEND_BUTTON_SCRIPT = """
(() => {
  const buttons = Array.from(document.querySelectorAll('button'));
  for (const button of buttons) {
    const value = [
      button.getAttribute('aria-label') || '',
      button.getAttribute('title') || '',
      button.getAttribute('data-testid') || ''
    ].join(' ').toLowerCase();
    if (!button.disabled && (
      value.includes('send') ||
      value.includes('enviar') ||
      value.includes('submit')
    )) {
      button.click();
      return true;
    }
  }
  return false;
})()
"""


class PydollElement(Protocol):
    async def set_input_files(self, files: str | Path | list[str | Path]) -> object:
        ...

    async def insert_text(self, text: str) -> object:
        ...


class PydollKeyboard(Protocol):
    async def press(self, key: object) -> object:
        ...


class PydollTab(Protocol):
    @property
    def keyboard(self) -> PydollKeyboard:
        ...

    async def go_to(self, url: str, timeout: int) -> object:
        ...

    async def enable_network_events(self) -> object:
        ...

    async def on(self, event: object, callback: object) -> object:
        ...

    async def execute_script(self, script: str, *, return_by_value: bool) -> object:
        ...

    async def get_cookies(self) -> object:
        ...

    async def find(
        self,
        *,
        tag_name: str | None = None,
        timeout: int = 0,
        **attributes: object,
    ) -> PydollElement:
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


@dataclass
class BrowserImageChatCapture:
    text_parts: list[str] = field(default_factory=list)
    done: bool = False
    error_code: str | None = None
    last_text_at: float | None = None

    @property
    def text(self) -> str:
        return "".join(self.text_parts)


@dataclass(frozen=True)
class PydollRuntime:
    browser: PydollBrowser
    websocket_created_event: object
    websocket_frame_received_event: object
    enter_key: object


def run_browser_image_chat(
    prompt: str,
    image_paths: list[Path],
    paths: GatewayPaths,
) -> str:
    return run_async(browser_image_chat(prompt, image_paths, paths))


async def browser_image_chat(
    prompt: str,
    image_paths: list[Path],
    paths: GatewayPaths,
) -> str:
    if not image_paths:
        raise UpstreamProtocolError("At least one image is required for browser image chat")
    runtime = load_pydoll_runtime(paths)
    capture = BrowserImageChatCapture()
    async with runtime.browser as browser:
        tab = await browser.start()
        if not is_pydoll_tab(tab):
            raise LoginFailedError("Pydoll returned an invalid tab")
        await tab.enable_network_events()
        await tab.on(runtime.websocket_created_event, lambda event: None)
        await tab.on(
            runtime.websocket_frame_received_event,
            lambda event: record_received_frame(capture, event),
        )
        await tab.go_to(CONSUMER_URL, timeout=45)
        await asyncio.sleep(5)
        file_input = await tab.find(tag_name="input", timeout=10, type="file")
        await file_input.set_input_files([str(path) for path in image_paths])
        await asyncio.sleep(8)
        textbox = await tab.find(tag_name="textarea", timeout=20)
        await textbox.insert_text(prompt)
        await verify_prompt_inserted(tab, len(prompt))
        if not await click_send_button(tab):
            await tab.keyboard.press(runtime.enter_key)
        await wait_for_image_response(capture)
        auth = await capture_consumer_auth(tab)
        if auth is not None:
            auth.save(paths.consumer_auth_file)
    if capture.error_code:
        raise UpstreamProtocolError(f"Consumer browser image chat failed: {capture.error_code}")
    if not capture.text.strip():
        raise UpstreamProtocolError("Consumer browser image chat returned no text")
    return capture.text


def load_pydoll_runtime(paths: GatewayPaths) -> PydollRuntime:
    modules = load_pydoll_modules(paths.root)
    browser = create_browser(modules, paths.consumer_profile_dir)
    if not is_pydoll_browser(browser):
        raise LoginFailedError("Pydoll returned an invalid browser")
    network_events = import_module("pydoll.protocol.network.events", paths.root)
    constants = import_module("pydoll.constants", paths.root)
    return PydollRuntime(
        browser=browser,
        websocket_created_event=module_nested_attr(
            network_events,
            "NetworkEvent",
            "WEBSOCKET_CREATED",
        ),
        websocket_frame_received_event=module_nested_attr(
            network_events,
            "NetworkEvent",
            "WEBSOCKET_FRAME_RECEIVED",
        ),
        enter_key=module_nested_attr(constants, "Key", "ENTER"),
    )


def import_module(name: str, root: Path) -> ModuleType:
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        load_pydoll_modules(root)
        return importlib.import_module(name)


def module_nested_attr(module: ModuleType, owner: str, name: str) -> object:
    parent = getattr(module, owner, None)
    if parent is None:
        raise LoginFailedError(f"Pydoll did not expose {owner}")
    value = getattr(parent, name, None)
    if value is None:
        raise LoginFailedError(f"Pydoll did not expose {owner}.{name}")
    return value


def record_received_frame(capture: BrowserImageChatCapture, event: object) -> None:
    params = mapping_value(event, "params")
    response = mapping_value(params, "response")
    payload = response.get("payloadData")
    if not isinstance(payload, str):
        return
    try:
        message = json.loads(payload)
    except json.JSONDecodeError:
        return
    if not isinstance(message, Mapping):
        return
    event_name = message.get("event")
    if event_name == "appendText":
        text = message.get("text")
        if isinstance(text, str):
            capture.text_parts.append(text)
            capture.last_text_at = time.monotonic()
    elif event_name == "done":
        capture.done = True
    elif event_name == "error":
        error_code = message.get("errorCode")
        capture.error_code = error_code if isinstance(error_code, str) else "unknown"


def mapping_value(source: object, key: str) -> Mapping[object, object]:
    if not isinstance(source, Mapping):
        return {}
    value = source.get(key)
    return value if isinstance(value, Mapping) else {}


async def verify_prompt_inserted(tab: PydollTab, prompt_length: int) -> None:
    value = runtime_value(await tab.execute_script(COMPOSER_STATE_SCRIPT, return_by_value=True))
    if not isinstance(value, Mapping):
        raise UpstreamProtocolError("Consumer browser image chat could not inspect composer state")
    max_value_length = value.get("maxValueLength")
    if not isinstance(max_value_length, int) or max_value_length < prompt_length:
        raise UpstreamProtocolError("Consumer browser image chat did not insert the prompt")


async def click_send_button(tab: PydollTab) -> bool:
    value = runtime_value(await tab.execute_script(CLICK_SEND_BUTTON_SCRIPT, return_by_value=True))
    return value is True


async def wait_for_image_response(capture: BrowserImageChatCapture) -> None:
    deadline = asyncio.get_running_loop().time() + IMAGE_CHAT_WAIT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        if capture.done or capture.error_code:
            return
        if (
            capture.text_parts
            and capture.last_text_at is not None
            and time.monotonic() - capture.last_text_at >= IMAGE_CHAT_IDLE_SECONDS
        ):
            return
        await asyncio.sleep(0.5)
    raise TimeoutError("Consumer browser image chat did not finish in time")


def is_pydoll_browser(value: object) -> TypeGuard[PydollBrowser]:
    return all(
        callable(getattr(value, method_name, None))
        for method_name in ("__aenter__", "__aexit__", "start")
    )


def is_pydoll_tab(value: object) -> TypeGuard[PydollTab]:
    return all(
        callable(getattr(value, method_name, None))
        for method_name in ("go_to", "enable_network_events", "on", "find")
    ) and isinstance(getattr(value, "keyboard", None), object)
